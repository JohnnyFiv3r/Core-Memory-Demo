from __future__ import annotations

import json
import os
import re
import shutil
import time
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
from core_memory.runtime.jobs import async_jobs_status, run_async_jobs
from core_memory.write_pipeline.continuity_injection import load_continuity_injection

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

DEFAULT_SEED_USER_MESSAGES: list[str] = [
    "Should we use MySQL or PostgreSQL for JSON-heavy service?",
    "What lesson did we learn?",
    "What evidence supports the DB decision?",
    "What project goal is pending?",
    "Why FastAPI?",
]

STORY_PACK_DIR = Path(__file__).resolve().parents[3] / "demo" / "story-pack"
TURN_HEADER_RE = re.compile(r"^##\s*Turn\s+(\d{3})\s*:\s*(.+?)\s*$", re.MULTILINE)
SEND_PROMPT_RE = re.compile(r"^\*\*Send:\*\*\s*`([^`]+)`\s*$", re.MULTILINE)


def _load_story_pack_bundle(*, pack_dir: Path | None = None) -> dict[str, Any]:
    base = Path(pack_dir or STORY_PACK_DIR)
    manifest_path = base / "replay-order.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"story_pack_manifest_not_found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    acts_cfg = list(manifest.get("acts") or [])
    all_turns: list[dict[str, Any]] = []
    checkpoints: dict[int, list[dict[str, Any]]] = {}

    for act in acts_cfg:
        rel = str(act.get("file") or "").strip()
        if not rel:
            continue
        act_path = base / rel
        if not act_path.exists():
            raise FileNotFoundError(f"story_pack_act_not_found: {act_path}")

        text = act_path.read_text(encoding="utf-8")
        headers = list(TURN_HEADER_RE.finditer(text))
        turns: list[dict[str, Any]] = []
        for i, header in enumerate(headers):
            turn_no = int(header.group(1))
            title = str(header.group(2) or "").strip()
            start = header.end()
            end = headers[i + 1].start() if (i + 1) < len(headers) else len(text)
            block = text[start:end]
            send_match = SEND_PROMPT_RE.search(block)
            if not send_match:
                raise ValueError(f"story_pack_missing_send_prompt: {act_path.name} turn {turn_no:03d}")
            turns.append(
                {
                    "turn": turn_no,
                    "title": title,
                    "prompt": str(send_match.group(1) or "").strip(),
                    "act": str(act.get("act") or ""),
                    "act_title": str(act.get("title") or ""),
                    "session_hint": str(act.get("default_session") or ""),
                    "file": rel,
                }
            )

        if turns:
            expected_start = int(act.get("turn_start") or turns[0]["turn"])
            expected_end = int(act.get("turn_end") or turns[-1]["turn"])
            if turns[0]["turn"] != expected_start or turns[-1]["turn"] != expected_end:
                raise ValueError(
                    f"story_pack_turn_range_mismatch: {act_path.name}"
                    f" expected={expected_start:03d}-{expected_end:03d}"
                    f" parsed={turns[0]['turn']:03d}-{turns[-1]['turn']:03d}"
                )
            all_turns.extend(turns)

        for cp in list(act.get("checkpoints") or []):
            after_turn = int(cp.get("after_turn") or 0)
            if after_turn <= 0:
                continue
            row = dict(cp or {})
            row["act"] = str(act.get("act") or "")
            row["act_title"] = str(act.get("title") or "")
            checkpoints.setdefault(after_turn, []).append(row)

    all_turns = sorted(all_turns, key=lambda x: int(x.get("turn") or 0))
    turn_numbers = [int(x.get("turn") or 0) for x in all_turns]
    if turn_numbers:
        expected = list(range(turn_numbers[0], turn_numbers[-1] + 1))
        if turn_numbers != expected:
            raise ValueError("story_pack_turns_not_contiguous")

    return {
        "manifest": manifest,
        "pack_dir": str(base),
        "turns": all_turns,
        "checkpoints": checkpoints,
    }


def get_story_pack_meta() -> dict[str, Any]:
    bundle = _load_story_pack_bundle()
    manifest = dict(bundle.get("manifest") or {})
    turns = list(bundle.get("turns") or [])
    checkpoints = dict(bundle.get("checkpoints") or {})

    first_turn = int(turns[0].get("turn") or 0) if turns else 0
    last_turn = int(turns[-1].get("turn") or 0) if turns else 0
    checkpoint_count = sum(len(list(v or [])) for v in checkpoints.values())

    return {
        "ok": True,
        "pack_name": str(manifest.get("pack_name") or "story-pack"),
        "format_version": int(manifest.get("format_version") or 1),
        "total_turns": int(manifest.get("total_turns") or len(turns)),
        "loaded_turns": int(len(turns)),
        "turn_range": {"first": first_turn, "last": last_turn},
        "checkpoints": int(checkpoint_count),
        "sessions": dict(manifest.get("sessions") or {}),
        "acts": [
            {
                "act": str(a.get("act") or ""),
                "title": str(a.get("title") or ""),
                "turn_start": int(a.get("turn_start") or 0),
                "turn_end": int(a.get("turn_end") or 0),
                "file": str(a.get("file") or ""),
            }
            for a in list(manifest.get("acts") or [])
        ],
    }


def _provider_from_model_id(model_id: str) -> str:
    mid = str(model_id or "").strip().lower()
    if not mid:
        return ""
    if ":" in mid:
        return mid.split(":", 1)[0].strip()
    if "/" in mid:
        return mid.split("/", 1)[0].strip()
    return mid


def _required_api_key_env_for_model(model_id: str) -> str | None:
    provider = _provider_from_model_id(model_id)
    if provider in {"openai"}:
        return "OPENAI_API_KEY"
    if provider in {"anthropic"}:
        return "ANTHROPIC_API_KEY"
    if provider in {"google", "gemini", "google-gla"}:
        # Google adapters commonly use one of these.
        return "GEMINI_API_KEY|GOOGLE_API_KEY"
    return None


def _model_has_required_credentials(model_id: str) -> bool:
    req = _required_api_key_env_for_model(model_id)
    if not req:
        return True
    if "|" in req:
        keys = [x.strip() for x in req.split("|") if x.strip()]
        return any(bool(os.getenv(k)) for k in keys)
    return bool(os.getenv(req))


def detect_model() -> str:
    configured = settings.demo_model_id.strip()
    if configured and _model_has_required_credentials(configured):
        return configured

    # If configured model is missing credentials, fall through to supported fallbacks.
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic:claude-sonnet-4-20250514"
    if os.getenv("OPENAI_API_KEY"):
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
        configured = settings.demo_model_id.strip()
        if configured:
            req = _required_api_key_env_for_model(configured)
            if req:
                raise RuntimeError(f"missing_model_credentials: configured model '{configured}' requires {req}")
        raise RuntimeError("no_model_configured: set DEMO_MODEL_ID with matching provider credentials, or set ANTHROPIC_API_KEY / OPENAI_API_KEY")
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

    rolling_token_estimate = 0
    rolling_token_budget = 0
    rolling_record_count = 0
    try:
        continuity = load_continuity_injection(settings.core_memory_root)
        continuity_meta = dict((continuity or {}).get("meta") or {})
        continuity_records = list((continuity or {}).get("records") or [])
        rolling_token_estimate = int(continuity_meta.get("token_estimate") or 0)
        rolling_token_budget = int(continuity_meta.get("token_budget") or 0)
        rolling_record_count = int(continuity_meta.get("record_count") or len(continuity_records))
    except Exception:
        rolling_token_estimate = 0
        rolling_token_budget = 0
        rolling_record_count = 0

    out["session"].update(
        {
            "rolling_window_token_estimate": rolling_token_estimate,
            "rolling_window_token_budget": rolling_token_budget,
            "rolling_window_record_count": rolling_record_count,
        }
    )
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
        "rolling_window_token_estimate": rolling_token_estimate,
        "rolling_window_token_budget": rolling_token_budget,
        "rolling_window_record_count": rolling_record_count,
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


def run_flush(*, new_session_id: str | None = None) -> dict[str, Any]:
    out = process_flush(
        root=settings.core_memory_root,
        session_id=SESSION.session_id,
        promote=True,
        token_budget=max(500, int(SESSION.context_budget)),
        max_beads=80,
        source="core_memory_demo_backend",
    )
    old = SESSION.session_id
    forced_session = str(new_session_id or "").strip()
    SESSION.session_id = forced_session or _new_session_id()
    SESSION.token_usage = 0
    return {
        "flushed_session": old,
        "new_session": SESSION.session_id,
        "flush_ok": bool(out.get("ok")),
        "rolling_window_beads": int(len(((out.get("rolling_window") or {}).get("records") or []))),
    }


def _normalize_seed_messages(messages: list[Any] | None) -> list[str]:
    rows = list(messages or [])
    out: list[str] = []
    for x in rows:
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _queue_idle(status: dict[str, Any] | None) -> bool:
    s = dict(status or {})
    if int(s.get("pending_total") or 0) > 0:
        return False
    if int(s.get("processable_now") or 0) > 0:
        return False
    queues = dict(s.get("queues") or {})
    for _name, q in queues.items():
        row = dict(q or {})
        if int(row.get("pending") or row.get("queue_depth") or 0) > 0:
            return False
        if int(row.get("processable_now") or 0) > 0:
            return False
        if int(row.get("retry_ready") or 0) > 0:
            return False
    return True


def _drain_async_until_idle(
    *,
    timeout_ms: int,
    poll_ms: int,
    max_compaction: int,
    max_side_effects: int,
) -> dict[str, Any]:
    started = time.monotonic()
    timeout_s = max(1.0, float(timeout_ms) / 1000.0)
    poll_s = max(0.05, float(poll_ms) / 1000.0)

    passes = 0
    last_status: dict[str, Any] = {}
    while (time.monotonic() - started) <= timeout_s:
        last_status = async_jobs_status(root=settings.core_memory_root)
        if _queue_idle(last_status):
            return {
                "ok": True,
                "idle": True,
                "passes": passes,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "status": last_status,
            }

        out = run_async_jobs(
            root=settings.core_memory_root,
            run_semantic=True,
            max_compaction=max(1, int(max_compaction)),
            max_side_effects=max(1, int(max_side_effects)),
        )
        passes += 1
        comp_processed = int(((out.get("compaction_run") or {}).get("processed") or 0))
        se_processed = int(((out.get("side_effect_run") or {}).get("processed") or 0))
        sem_ran = bool(((out.get("semantic_run") or {}).get("ran") or False))

        if (comp_processed + se_processed) <= 0 and not sem_ran:
            time.sleep(poll_s)

    return {
        "ok": False,
        "idle": False,
        "passes": passes,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "status": last_status,
        "error": "idle_timeout",
    }


async def seed_demo_history(
    *,
    messages: list[Any] | None = None,
    max_turns: int | None = None,
    wait_for_idle: bool = True,
    idle_timeout_ms: int = 20000,
    idle_poll_ms: int = 250,
    auto_flush: bool = True,
    flush_threshold_ratio: float = 0.85,
    flush_every_turns: int = 0,
    max_compaction_per_pass: int = 2,
    max_side_effects_per_pass: int = 8,
) -> dict[str, Any]:
    prompts = _normalize_seed_messages(messages)
    if not prompts:
        prompts = list(DEFAULT_SEED_USER_MESSAGES)

    target = len(prompts)
    if isinstance(max_turns, int) and max_turns > 0:
        target = min(target, max_turns)

    seeded = 0
    seeded_since_flush = 0
    errors: list[dict[str, Any]] = []
    flush_events: list[dict[str, Any]] = []
    queue_waits: list[dict[str, Any]] = []

    def _should_flush() -> bool:
        if not auto_flush:
            return False
        if int(flush_every_turns) > 0 and seeded_since_flush >= int(flush_every_turns):
            return True
        budget = max(1, int(SESSION.context_budget))
        usage_ratio = float(SESSION.token_usage) / float(budget)
        return usage_ratio >= max(0.1, float(flush_threshold_ratio))

    for idx, user_query in enumerate(prompts[:target], start=1):
        try:
            await run_chat(user_query)
            seeded += 1
            seeded_since_flush += 1

            if wait_for_idle:
                wait_result = _drain_async_until_idle(
                    timeout_ms=idle_timeout_ms,
                    poll_ms=idle_poll_ms,
                    max_compaction=max_compaction_per_pass,
                    max_side_effects=max_side_effects_per_pass,
                )
                queue_waits.append({"turn": idx, **wait_result})
                if not bool(wait_result.get("idle")):
                    errors.append({
                        "index": idx,
                        "user_query": user_query[:160],
                        "error": "queue_not_idle_timeout",
                        "details": {
                            "elapsed_ms": wait_result.get("elapsed_ms"),
                            "passes": wait_result.get("passes"),
                            "pending_total": ((wait_result.get("status") or {}).get("pending_total")),
                        },
                    })
                    break

            if _should_flush():
                f = run_flush()
                flush_events.append(dict(f or {}))
                seeded_since_flush = 0
                if wait_for_idle:
                    post_wait = _drain_async_until_idle(
                        timeout_ms=idle_timeout_ms,
                        poll_ms=idle_poll_ms,
                        max_compaction=max_compaction_per_pass,
                        max_side_effects=max_side_effects_per_pass,
                    )
                    queue_waits.append({"turn": idx, "after_flush": True, **post_wait})
                    if not bool(post_wait.get("idle")):
                        errors.append({
                            "index": idx,
                            "user_query": user_query[:160],
                            "error": "queue_not_idle_timeout_after_flush",
                            "details": {
                                "elapsed_ms": post_wait.get("elapsed_ms"),
                                "passes": post_wait.get("passes"),
                                "pending_total": ((post_wait.get("status") or {}).get("pending_total")),
                            },
                        })
                        break
        except Exception as exc:
            errors.append({"index": idx, "user_query": user_query[:160], "error": str(exc)})

    final_queue = async_jobs_status(root=settings.core_memory_root)

    return {
        "ok": seeded > 0 and not errors,
        "seeded": seeded,
        "seeded_turns": seeded,
        "requested_turns": target,
        "failed_turns": len(errors),
        "errors": errors[:20],
        "mode": "chat_replay",
        "wait_for_idle": bool(wait_for_idle),
        "queue_idle": bool(_queue_idle(final_queue)),
        "queue": final_queue,
        "queue_wait_checks": queue_waits[-20:],
        "auto_flush": bool(auto_flush),
        "flush_count": len(flush_events),
        "flushes": flush_events[-20:],
        "session": {
            "session_id": SESSION.session_id,
            "token_usage": SESSION.token_usage,
            "context_budget": SESSION.context_budget,
        },
    }


async def replay_story_pack(
    *,
    max_turns: int | None = None,
    start_turn: int | None = None,
    end_turn: int | None = None,
    wait_for_idle: bool = True,
    idle_timeout_ms: int = 20000,
    idle_poll_ms: int = 250,
    max_compaction_per_pass: int = 2,
    max_side_effects_per_pass: int = 8,
    run_checkpoints: bool = True,
    reset_session: bool = True,
    use_manifest_sessions: bool = True,
    benchmark_semantic_mode: str = "required",
    benchmark_limit: int | None = None,
) -> dict[str, Any]:
    bundle = _load_story_pack_bundle()
    manifest = dict(bundle.get("manifest") or {})
    turns = list(bundle.get("turns") or [])
    checkpoints_by_turn = dict(bundle.get("checkpoints") or {})

    start_at = int(start_turn or 0)
    end_at = int(end_turn or 0)
    if start_at > 0:
        turns = [t for t in turns if int(t.get("turn") or 0) >= start_at]
    if end_at > 0:
        turns = [t for t in turns if int(t.get("turn") or 0) <= end_at]
    if isinstance(max_turns, int) and max_turns > 0:
        turns = turns[: max_turns]

    if not turns:
        return {
            "ok": False,
            "error": "story_pack_no_turns_selected",
            "pack_name": str(manifest.get("pack_name") or "story-pack"),
        }

    sessions_cfg = dict(manifest.get("sessions") or {})
    if reset_session:
        initial_sid = str(sessions_cfg.get("initial") or "").strip() if use_manifest_sessions else ""
        SESSION.session_id = initial_sid or _new_session_id()
        SESSION.token_usage = 0

    selected_turns = {int(t.get("turn") or 0) for t in turns}
    executed_checkpoints: list[dict[str, Any]] = []
    queue_waits: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seeded = 0

    for row in turns:
        turn_no = int(row.get("turn") or 0)
        prompt = str(row.get("prompt") or "").strip()
        if not prompt:
            continue

        try:
            await run_chat(prompt)
            seeded += 1

            if wait_for_idle:
                wait_result = _drain_async_until_idle(
                    timeout_ms=idle_timeout_ms,
                    poll_ms=idle_poll_ms,
                    max_compaction=max_compaction_per_pass,
                    max_side_effects=max_side_effects_per_pass,
                )
                queue_waits.append({"turn": turn_no, **wait_result})
                if not bool(wait_result.get("idle")):
                    errors.append(
                        {
                            "turn": turn_no,
                            "error": "queue_not_idle_timeout",
                            "details": {
                                "elapsed_ms": wait_result.get("elapsed_ms"),
                                "passes": wait_result.get("passes"),
                                "pending_total": ((wait_result.get("status") or {}).get("pending_total")),
                            },
                        }
                    )
                    break

            if not run_checkpoints:
                continue

            for cp in list(checkpoints_by_turn.get(turn_no) or []):
                cp_type = str(cp.get("type") or "").strip().lower()
                if cp_type == "session_flush":
                    forced_next = str(cp.get("next_session") or "").strip() if use_manifest_sessions else ""
                    flush_out = run_flush(new_session_id=(forced_next or None))
                    event = {
                        "after_turn": turn_no,
                        "type": "session_flush",
                        "mode": str(cp.get("mode") or ""),
                        "ok": bool(flush_out.get("flush_ok")),
                        "new_session": str(flush_out.get("new_session") or ""),
                        "flushed_session": str(flush_out.get("flushed_session") or ""),
                    }
                    executed_checkpoints.append(event)

                    if wait_for_idle:
                        post_wait = _drain_async_until_idle(
                            timeout_ms=idle_timeout_ms,
                            poll_ms=idle_poll_ms,
                            max_compaction=max_compaction_per_pass,
                            max_side_effects=max_side_effects_per_pass,
                        )
                        queue_waits.append({"turn": turn_no, "after_flush": True, **post_wait})
                        if not bool(post_wait.get("idle")):
                            errors.append(
                                {
                                    "turn": turn_no,
                                    "error": "queue_not_idle_timeout_after_flush",
                                    "details": {
                                        "elapsed_ms": post_wait.get("elapsed_ms"),
                                        "passes": post_wait.get("passes"),
                                        "pending_total": ((post_wait.get("status") or {}).get("pending_total")),
                                    },
                                }
                            )
                            break
                elif cp_type == "benchmark":
                    mode_raw = str(cp.get("mode") or "snapshot").strip().lower()
                    root_mode = "clean" if mode_raw == "clean" else "snapshot"
                    bench = run_benchmark(
                        semantic_mode_name=str(benchmark_semantic_mode or "required"),
                        root_mode=root_mode,
                        preload_from_demo=False,
                        preload_turns_max=0,
                        limit=benchmark_limit,
                    )
                    summary = dict(bench.get("summary") or {})
                    executed_checkpoints.append(
                        {
                            "after_turn": turn_no,
                            "type": "benchmark",
                            "mode": root_mode,
                            "ok": bool(bench.get("ok")),
                            "run_id": str(summary.get("run_id") or ""),
                            "accuracy": summary.get("accuracy"),
                            "cases": int(summary.get("cases") or 0),
                            "pass": int(summary.get("pass") or 0),
                            "fail": int(summary.get("fail") or 0),
                        }
                    )
                else:
                    executed_checkpoints.append(
                        {
                            "after_turn": turn_no,
                            "type": cp_type or "unknown",
                            "ok": False,
                            "error": "unsupported_checkpoint_type",
                        }
                    )

            if errors:
                break
        except Exception as exc:
            errors.append(
                {
                    "turn": turn_no,
                    "error": str(exc),
                    "prompt": prompt[:200],
                }
            )
            break

    final_queue = async_jobs_status(root=settings.core_memory_root)
    first_turn = int(turns[0].get("turn") or 0)
    last_turn = int(turns[-1].get("turn") or 0)

    return {
        "ok": seeded > 0 and not errors,
        "pack_name": str(manifest.get("pack_name") or "story-pack"),
        "seeded": seeded,
        "requested_turns": int(len(turns)),
        "turn_range": {"first": first_turn, "last": last_turn},
        "selected_turns": sorted(selected_turns),
        "run_checkpoints": bool(run_checkpoints),
        "checkpoint_count": int(len(executed_checkpoints)),
        "checkpoints": executed_checkpoints,
        "errors": errors[:20],
        "wait_for_idle": bool(wait_for_idle),
        "queue_idle": bool(_queue_idle(final_queue)),
        "queue": final_queue,
        "queue_wait_checks": queue_waits[-40:],
        "session": {
            "session_id": SESSION.session_id,
            "token_usage": SESSION.token_usage,
            "context_budget": SESSION.context_budget,
        },
    }


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


def _load_preload_turns_from_live(*, max_turns: int = 200) -> list[dict[str, str]]:
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

    return [dict(x or {}) for x in rows[:target]]


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

    preloaded_rows: list[dict[str, Any]] = []
    if preload_from_demo:
        preloaded_rows = _load_preload_turns_from_live(max_turns=preload_turns_max)
        for rec in preloaded_rows:
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
        "preload_turn_count": int(len(preloaded_rows)),
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
