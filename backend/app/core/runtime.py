from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core_memory.entity.merge_flow import (
    decide_entity_merge_proposal,
    suggest_entity_merge_proposals,
)
from core_memory.integrations.api import (
    get_turn,
    inspect_bead,
    inspect_bead_hydration,
    inspect_claim_slot,
    inspect_state,
    list_turn_summaries,
)
from core_memory.integrations.pydanticai.memory_tools import (
    continuity_prompt,
    memory_execute_tool,
    memory_search_tool,
    memory_trace_tool,
)
from core_memory.integrations.pydanticai.run import run_with_memory
from core_memory.retrieval.tools import memory as memory_tools
from core_memory.runtime.engine import process_flush, process_turn_finalized

from app.core.config import settings


@dataclass
class SessionState:
    session_id: str
    context_budget: int
    token_usage: int = 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_session_id() -> str:
    return f"demo-{uuid.uuid4().hex[:8]}"


SESSION = SessionState(session_id=_new_session_id(), context_budget=settings.demo_context_budget)
LAST_TURN_DIAGNOSTICS: dict[str, Any] = {}
LAST_BENCHMARK_REPORT: dict[str, Any] = {}
LAST_BENCHMARK_SUMMARY: dict[str, Any] = {}
LAST_BENCHMARK_HISTORY: list[dict[str, Any]] = []


def detect_model() -> str:
    if settings.demo_model_id.strip():
        return settings.demo_model_id.strip()
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic:claude-sonnet-4-20250514"
    if os.getenv("OPENAI_API_KEY"):
        return "openai:gpt-4o"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        # pydantic-ai provider id for Gemini can vary; keep OpenAI/Anthropic as primary in MVP.
        return "openai:gpt-4o"
    return ""


def create_agent(model_id: str):
    from pydantic_ai import Agent

    agent = Agent(
        model_id,
        system_prompt=(
            "You are a helpful project assistant. Use memory tools to ground answers. "
            "Tool policy: execute first, search second, trace for causal requests."
        ),
        tools=[
            memory_execute_tool(root=settings.core_memory_root),
            memory_search_tool(root=settings.core_memory_root),
            memory_trace_tool(root=settings.core_memory_root),
        ],
    )

    @agent.system_prompt
    def inject_memory():
        return continuity_prompt(root=settings.core_memory_root, session_id=SESSION.session_id)

    return agent


_AGENT: Any | None = None


def get_agent() -> Any:
    global _AGENT
    if _AGENT is not None:
        return _AGENT
    model = detect_model()
    if not model:
        raise RuntimeError("no_model_configured")
    _AGENT = create_agent(model)
    return _AGENT


def inspect_state_payload(*, as_of: str | None = None) -> dict[str, Any]:
    base = inspect_state(
        root=settings.core_memory_root,
        session_id=SESSION.session_id,
        as_of=as_of,
        limit_beads=300,
        limit_associations=300,
        limit_flushes=20,
        limit_merge_proposals=40,
    )
    out = dict(base or {})
    out["session"] = {
        "session_id": SESSION.session_id,
        "token_usage": SESSION.token_usage,
        "context_budget": SESSION.context_budget,
    }
    out["last_turn"] = dict(LAST_TURN_DIAGNOSTICS or {})
    out["benchmark"] = {
        "last_summary": dict(LAST_BENCHMARK_SUMMARY or {}),
        "has_last_report": bool(LAST_BENCHMARK_REPORT),
        "history": list(LAST_BENCHMARK_HISTORY or [])[:20],
    }

    # Backward-compat projection fields used by current UI
    mem = dict(out.get("memory") or {})
    claims = dict(out.get("claims") or {})
    stats = dict(out.get("stats") or {})
    entities = dict(out.get("entities") or {})
    out["beads"] = list(mem.get("beads") or [])
    out["associations"] = list(mem.get("associations") or [])
    out["rolling_window"] = list(mem.get("rolling_window") or [])
    out["claim_state"] = list(claims.get("slots") or [])
    out["stats"] = {
        "total_beads": int(stats.get("total_beads") or len(out["beads"])),
        "total_associations": int(stats.get("total_associations") or len(out["associations"])),
        "rolling_window_size": int(stats.get("rolling_window_size") or len(out["rolling_window"])),
        "claim_slot_count": int(stats.get("claim_slot_count") or len(out["claim_state"])),
        "entity_count": int(stats.get("entity_count") or len(list(entities.get("rows") or []))),
        "session_id": SESSION.session_id,
        "token_usage": SESSION.token_usage,
        "context_budget": SESSION.context_budget,
    }
    return out


def record_turn_tokens(user_query: str, assistant_response: str) -> None:
    turn_text = len(str(user_query or "")) + len(str(assistant_response or ""))
    SESSION.token_usage += (turn_text + 500) // 4


async def run_chat(message: str) -> dict[str, Any]:
    global LAST_TURN_DIAGNOSTICS
    agent = get_agent()
    turn_id = uuid.uuid4().hex[:12]
    result = await run_with_memory(
        agent,
        message,
        root=settings.core_memory_root,
        session_id=SESSION.session_id,
        turn_id=turn_id,
    )
    answer = str(getattr(result, "output", None) or getattr(result, "data", None) or result)
    record_turn_tokens(message, answer)

    req = {"query": message, "intent": "remember", "k": 8}
    retrieval = memory_tools.execute(req, root=settings.core_memory_root, explain=False)
    LAST_TURN_DIAGNOSTICS = {
        "ok": True,
        "turn_id": turn_id,
        "diagnostics": {
            "ok": bool(retrieval.get("ok")),
            "answer_outcome": str(retrieval.get("next_action") or "answered"),
            "retrieval_mode": str(retrieval.get("backend") or "unknown"),
            "source_surface": "memory_execute",
            "anchor_reason": "retrieved",
            "result_count": int(len(list(retrieval.get("results") or []))),
            "top_bead_ids": [str(r.get("bead_id") or "") for r in list(retrieval.get("results") or [])[:5]],
            "chain_count": int(len(list(retrieval.get("chains") or []))),
            "warnings": list(retrieval.get("warnings") or []),
        },
    }

    return {
        "ok": True,
        "session_id": SESSION.session_id,
        "turn_id": turn_id,
        "assistant": answer,
        "last_answer": dict(LAST_TURN_DIAGNOSTICS),
    }


def run_flush() -> dict[str, Any]:
    out = process_flush(
        root=settings.core_memory_root,
        session_id=SESSION.session_id,
        promote=True,
        token_budget=max(500, int(SESSION.context_budget)),
        max_beads=80,
        source="core_memory_demo_backend",
    )
    old = SESSION.session_id
    SESSION.session_id = _new_session_id()
    SESSION.token_usage = 0
    return {
        "flushed_session": old,
        "new_session": SESSION.session_id,
        "flush_ok": bool(out.get("ok")),
        "rolling_window_beads": int(len(((out.get("rolling_window") or {}).get("records") or []))),
    }


def seed_demo_history() -> dict[str, Any]:
    seed_turns = [
        ("seed-001", "Should we use MySQL or PostgreSQL for JSON-heavy service?", "Decision: choose PostgreSQL due to JSONB benchmark wins."),
        ("seed-002", "What lesson did we learn?", "Lesson: benchmark representative workload first."),
        ("seed-003", "What evidence supports the DB decision?", "Evidence: pgbench/sysbench showed PostgreSQL around 2x faster for JSON-heavy queries."),
        ("seed-004", "What project goal is pending?", "Goal: migrate auth to OAuth2 by end of Q2."),
        ("seed-005", "Why FastAPI?", "Decision: FastAPI for async-first I/O and native validation."),
    ]
    for i, (turn_id, user_q, assistant_f) in enumerate(seed_turns, start=1):
        process_turn_finalized(
            root=settings.core_memory_root,
            session_id="seed-history",
            turn_id=turn_id,
            transaction_id=f"seed-tx-{i:03d}",
            trace_id=f"seed-tr-{i:03d}",
            user_query=user_q,
            assistant_final=assistant_f,
            origin="DEMO_SEED",
            metadata={"source": "demo_seed", "seed": True},
        )
    return {"ok": True, "seeded": len(seed_turns)}


@contextmanager
def semantic_mode(mode: str):
    key = "CORE_MEMORY_CANONICAL_SEMANTIC_MODE"
    old = os.environ.get(key)
    try:
        os.environ[key] = str(mode or "degraded_allowed")
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def _benchmark_history_file() -> Path:
    p = Path(settings.core_memory_demo_artifacts_root)
    p.mkdir(parents=True, exist_ok=True)
    return p / "benchmark-history.jsonl"


def _append_history(row: dict[str, Any]) -> None:
    f = _benchmark_history_file()
    with f.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_benchmark_history(limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    f = _benchmark_history_file()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            raw = str(line or "").strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    out.extend([dict(x or {}) for x in LAST_BENCHMARK_HISTORY])
    out = list(reversed(out))
    seen: set[str] = set()
    dedup: list[dict[str, Any]] = []
    for r in out:
        rid = str((r.get("summary") or {}).get("run_id") or r.get("run_id") or "")
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        dedup.append(r)
    return dedup[: max(1, int(limit))]


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)


def _build_preload_turns_file_from_live(*, max_turns: int = 200) -> str:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    target = max(1, int(max_turns))
    while len(rows) < target:
        page = list_turn_summaries(root=settings.core_memory_root, limit=min(200, target * 2), cursor=cursor)
        items = list(page.get("items") or [])
        if not items:
            break
        for rec in items:
            tid = str(rec.get("turn_id") or "").strip()
            sid = str(rec.get("session_id") or "").strip() or None
            if not tid:
                continue
            full = get_turn(turn_id=tid, root=settings.core_memory_root, session_id=sid) if tid else {}
            uq = str((full or rec).get("user_query") or "").strip()
            af = str((full or rec).get("assistant_final") or "").strip()
            if not uq or not af:
                continue
            rows.append(
                {
                    "session_id": str((full or rec).get("session_id") or sid or "demo"),
                    "turn_id": str((full or rec).get("turn_id") or tid),
                    "user_query": uq[:500],
                    "assistant_final": af[:900],
                    "origin": "DEMO_PRELOAD",
                }
            )
            if len(rows) >= target:
                break
        cursor = str(page.get("next_cursor") or "").strip() or None
        if not cursor:
            break

    if not rows:
        return ""
    fd, path = tempfile.mkstemp(prefix="demo-preload-", suffix=".jsonl")
    os.close(fd)
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[:target]), encoding="utf-8")
    return path


def _benchmark_cases() -> list[dict[str, Any]]:
    return [
        {"case_id": "b1", "query": "What database did we choose?", "expect": "postgres"},
        {"case_id": "b2", "query": "What lesson did we learn about infra choices?", "expect": "benchmark"},
        {"case_id": "b3", "query": "Why did we pick FastAPI?", "expect": "async"},
    ]


def run_benchmark(*, semantic_mode_name: str, root_mode: str, preload_from_demo: bool, preload_turns_max: int, limit: int | None = None) -> dict[str, Any]:
    global LAST_BENCHMARK_REPORT, LAST_BENCHMARK_SUMMARY, LAST_BENCHMARK_HISTORY

    run_id = f"bench-{uuid.uuid4().hex[:10]}"
    started = _utc_now_iso()
    run_root = Path(settings.core_memory_demo_benchmark_root) / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    if str(root_mode or "snapshot") == "snapshot":
        _copy_tree(Path(settings.core_memory_root), run_root)

    preload_file = ""
    try:
        if preload_from_demo:
            preload_file = _build_preload_turns_file_from_live(max_turns=preload_turns_max)
            if preload_file:
                for line in Path(preload_file).read_text(encoding="utf-8").splitlines():
                    rec = json.loads(line)
                    process_turn_finalized(
                        root=str(run_root),
                        session_id=str(rec.get("session_id") or "bench"),
                        turn_id=str(rec.get("turn_id") or uuid.uuid4().hex[:10]),
                        transaction_id=f"bench-preload-{uuid.uuid4().hex[:8]}",
                        trace_id=f"bench-preload-{uuid.uuid4().hex[:8]}",
                        user_query=str(rec.get("user_query") or ""),
                        assistant_final=str(rec.get("assistant_final") or ""),
                        origin="BENCH_PRELOAD",
                        metadata={"source": "demo_preload"},
                    )

        rows = _benchmark_cases()
        if isinstance(limit, int) and limit > 0:
            rows = rows[:limit]

        per_case: list[dict[str, Any]] = []
        passes = 0
        with semantic_mode(semantic_mode_name):
            for c in rows:
                result = memory_tools.execute({"query": c["query"], "intent": "remember", "k": 8}, root=str(run_root), explain=False)
                results = list(result.get("results") or [])
                text_blob = " ".join(
                    [
                        str((r.get("title") or "")).lower() + " " + str((r.get("summary") or "")).lower()
                        for r in results
                    ]
                )
                ok = str(c["expect"]).lower() in text_blob
                if ok:
                    passes += 1
                per_case.append(
                    {
                        "case_id": c["case_id"],
                        "query": c["query"],
                        "expected": c["expect"],
                        "pass": bool(ok),
                        "result_count": len(results),
                        "warnings": list(result.get("warnings") or []),
                        "backend": str(result.get("backend") or "unknown"),
                    }
                )

        total = len(per_case)
        fail = max(0, total - passes)
        summary = {
            "run_id": run_id,
            "started_at": started,
            "finished_at": _utc_now_iso(),
            "cases": total,
            "pass": passes,
            "fail": fail,
            "accuracy": (passes / total) if total else 0.0,
            "semantic_mode": semantic_mode_name,
            "root_mode": root_mode,
            "isolated_root": str(run_root),
            "isolated_run": True,
            "preload_turn_count": preload_turns_max if preload_from_demo else 0,
            "backend_modes": sorted(set(str(x.get("backend") or "unknown") for x in per_case)),
            "warnings": [],
        }
        report = {
            "totals": {"cases": total, "pass": passes, "fail": fail, "accuracy": summary["accuracy"]},
            "metadata": {
                "run_id": run_id,
                "semantic_mode": semantic_mode_name,
                "benchmark_backend_modes": summary["backend_modes"],
                "preload_turn_count": summary["preload_turn_count"],
                "root_mode": root_mode,
            },
            "cases": per_case,
            "per_bucket": {
                "overall": {
                    "cases": total,
                    "pass": passes,
                    "fail": fail,
                    "accuracy": summary["accuracy"],
                }
            },
        }

        LAST_BENCHMARK_SUMMARY = dict(summary)
        LAST_BENCHMARK_REPORT = dict(report)

        history_row = {
            "run_id": run_id,
            "created_at": summary["finished_at"],
            "summary": dict(summary),
            "report": dict(report),
        }
        LAST_BENCHMARK_HISTORY = ([history_row] + list(LAST_BENCHMARK_HISTORY or []))[:100]
        _append_history(history_row)

        return {"ok": True, "summary": summary, "report": report}
    finally:
        if preload_file:
            Path(preload_file).unlink(missing_ok=True)


def compare_benchmark_runs(left_run_id: str, right_run_id: str) -> dict[str, Any]:
    rows = read_benchmark_history(limit=400)
    by_id = {str((r.get("summary") or {}).get("run_id") or r.get("run_id") or ""): r for r in rows}
    left = dict(by_id.get(str(left_run_id)) or {})
    right = dict(by_id.get(str(right_run_id)) or {})
    if not left or not right:
        return {"ok": False, "error": "run_id_not_found"}
    ls = dict(left.get("summary") or {})
    rs = dict(right.get("summary") or {})

    def _f(x: Any) -> float:
        try:
            return float(x or 0.0)
        except Exception:
            return 0.0

    return {
        "ok": True,
        "compare": {
            "left": ls,
            "right": rs,
            "delta": {
                "accuracy": round(_f(rs.get("accuracy")) - _f(ls.get("accuracy")), 4),
                "pass": int(rs.get("pass") or 0) - int(ls.get("pass") or 0),
                "fail": int(rs.get("fail") or 0) - int(ls.get("fail") or 0),
            },
        },
    }


def suggest_entity_merges(*, min_score: float = 0.86, max_pairs: int = 40, source: str = "demo") -> dict[str, Any]:
    return suggest_entity_merge_proposals(settings.core_memory_root, min_score=min_score, max_pairs=max_pairs, source=source)


def decide_entity_merge(*, proposal_id: str, decision: str, keep_entity_id: str | None = None, reviewer: str = "demo", notes: str = "", apply: bool = True) -> dict[str, Any]:
    return decide_entity_merge_proposal(
        settings.core_memory_root,
        proposal_id=proposal_id,
        decision=decision,
        reviewer=reviewer,
        notes=notes,
        apply=apply,
        keep_entity_id=keep_entity_id,
    )


def inspect_bead_payload(bead_id: str) -> dict[str, Any]:
    bead = inspect_bead(root=settings.core_memory_root, bead_id=bead_id)
    if bead is None:
        return {"ok": False, "error": "bead_not_found", "bead_id": bead_id}
    return {"ok": True, "bead": bead}


def inspect_bead_hydration_payload(bead_id: str) -> dict[str, Any]:
    return inspect_bead_hydration(root=settings.core_memory_root, bead_id=bead_id, include_tools=False, before=0, after=0)


def inspect_claim_slot_payload(subject: str, slot: str, as_of: str | None) -> dict[str, Any]:
    return inspect_claim_slot(root=settings.core_memory_root, subject=subject, slot=slot, as_of=as_of)


def inspect_turns_payload(session_id: str | None, limit: int, cursor: str | None) -> dict[str, Any]:
    return list_turn_summaries(root=settings.core_memory_root, session_id=session_id, limit=limit, cursor=cursor)
