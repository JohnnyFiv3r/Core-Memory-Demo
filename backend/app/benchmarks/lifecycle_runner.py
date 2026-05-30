from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from app.benchmarks.contracts import (
    BenchmarkConversation,
    BenchmarkLifecycleError,
    BenchmarkQA,
    BenchmarkShortcutFlags,
    BenchmarkTurn,
    assert_faithful_shortcuts,
    assert_lifecycle_faithful_mode,
)
from app.benchmarks.locomo_answer import generate_locomo_answer
from app.benchmarks.locomo_loader import locomo_samples_to_benchmark_conversations
from app.benchmarks.locomo_scoring import compute_evidence_recall
from app.benchmarks import locomo_faithful
from core_memory.integrations.api import hydrate_bead_sources
from app.benchmarks.locomo_turn_crawler import locomo_crawler_callable

RETRIEVAL_EFFORT_ORDER = ("low", "medium", "high")

ProcessTurnFinalized = Callable[..., dict[str, Any]]
ProcessFlush = Callable[..., dict[str, Any]]
RunAsyncJobs = Callable[..., dict[str, Any]]
RecallFunc = Callable[..., Any]

def _turn_text(turn: BenchmarkTurn) -> str:
    return f"{turn.speaker} [{turn.role}]: {turn.content}"


def _locomo_replay_metadata(
    *,
    root: str | Path,
    conversation: BenchmarkConversation,
    turn: BenchmarkTurn,
) -> dict[str, Any]:
    """Build request-scoped LoCoMo crawler metadata for one replay turn.

    The benchmark must not toggle process-wide Core Memory env flags in a
    concurrent server. Instead, it computes the LoCoMo crawler updates for this
    turn and passes them through metadata.crawler_updates, which is already a
    request-scoped Core Memory contract.
    """

    metadata: dict[str, Any] = {
        "benchmark_name": conversation.benchmark_name,
        "benchmark_phase": "conversation_replay",
        "conversation_id": conversation.conversation_id,
        "source_turn_id": turn.turn_id,
        **dict(turn.metadata or {}),
    }
    if str(conversation.benchmark_name or "").strip().lower() != "locomo":
        return metadata

    metadata["replay_source"] = "locomo"
    try:
        from core_memory.association.crawler_contract import build_crawler_context

        crawler_context = build_crawler_context(root=str(root), session_id=conversation.session_id, limit=200)
        req = {
            "session_id": conversation.session_id,
            "turn_id": turn.turn_id,
            "turns": [{"speaker": turn.speaker, "role": turn.role, "content": turn.content}],
            "speakers": [turn.speaker],
            "user_query": turn.content if str(turn.role or "") == "user" else "",
            "assistant_final": turn.content if str(turn.role or "") == "assistant" else "",
            "turn_text": _turn_text(turn),
            "source_turn_ref": {"turn_id": turn.turn_id, "session_id": conversation.session_id, "speakers": [turn.speaker]},
            "metadata": metadata,
        }
        updates = locomo_crawler_callable({"root": str(root), "request": req, "crawler_context": crawler_context})
    except Exception as exc:  # noqa: BLE001 - replay result should surface exact failure
        raise BenchmarkLifecycleError(f"locomo_crawler_prepare_failed:{exc}") from exc

    if isinstance(updates, dict) and updates:
        metadata["crawler_updates"] = updates
        metadata["_crawler_updates_source"] = "locomo_lifecycle"
    return metadata


def _default_process_turn_finalized() -> ProcessTurnFinalized:
    from core_memory.runtime.engine import process_turn_finalized

    return process_turn_finalized


def _default_process_flush() -> ProcessFlush:
    from core_memory.runtime.engine import process_flush

    return process_flush


def _default_run_async_jobs() -> RunAsyncJobs:
    from core_memory.runtime.queue.jobs import run_async_jobs

    return run_async_jobs


def _build_semantic_index(root: str | Path) -> dict[str, Any]:
    from core_memory.retrieval.semantic_index import build_semantic_index

    return dict(build_semantic_index(Path(root)) or {})


def _default_recall() -> RecallFunc:
    try:
        from core_memory.retrieval.agent import recall
    except Exception as exc:  # pragma: no cover - depends on installed Core Memory version
        raise BenchmarkLifecycleError(f"core_memory_recall_unavailable:{exc}") from exc
    return recall


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        out = to_dict()
        return dict(out or {}) if isinstance(out, dict) else {"value": out}
    return {"value": value}


def _result_prediction(payload: dict[str, Any]) -> str:
    for key in ("answer", "prediction", "text", "final", "output"):
        value = str((payload or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def _result_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    payload = dict(payload or {})
    for key in ("results", "retrieved", "rows", "beads", "evidence"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [dict(row or {}) for row in rows if isinstance(row, dict)]
    raw = payload.get("raw")
    if isinstance(raw, dict):
        for key in ("results", "anchors", "retrieved", "rows", "beads"):
            rows = raw.get(key)
            if isinstance(rows, list):
                return [dict(row or {}) for row in rows if isinstance(row, dict)]
    return []


def _normalize_retrieved_row(row: dict[str, Any], *, rank: int, bead_lookup: dict[str, Any] | None = None, turn_lookup: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict((row or {}).get("metadata") or {})
    dia_values: list[str] = []
    for source in (row, metadata):
        for key in ("dia_ids", "dia_id", "locomo_dia_ids", "locomo_dia_id"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, list):
                dia_values.extend(str(x).strip() for x in value if str(x).strip())
            elif str(value or "").strip():
                dia_values.append(str(value).strip())
    bead_id = ""
    for key in ("bead_id", "id", "result_id", "source_id"):
        value = str((row or {}).get(key) or "").strip()
        if value:
            bead_id = value
            break
    bead = dict((bead_lookup or {}).get(bead_id) or {}) if bead_id else {}
    source_turn_ids = []
    for value in (row.get("source_turn_ids"), metadata.get("source_turn_ids"), bead.get("source_turn_ids")):
        if isinstance(value, list):
            source_turn_ids.extend(str(x).strip() for x in value if str(x).strip())
        elif str(value or "").strip():
            source_turn_ids.append(str(value).strip())
    source_turn_ids = list(dict.fromkeys(source_turn_ids))
    transcript_parts: list[str] = []
    for tid in source_turn_ids:
        hydrated = dict((turn_lookup or {}).get(tid) or {})
        turn = dict(hydrated.get("turn") or hydrated)
        turns = turn.get("turns") if isinstance(turn.get("turns"), list) else []
        if turns:
            for t in turns:
                if not isinstance(t, dict):
                    continue
                speaker = str(t.get("speaker") or t.get("role") or "").strip()
                content = str(t.get("content") or "").strip()
                if content:
                    transcript_parts.append((f"{speaker}: " if speaker else "") + content)
        else:
            content = str(turn.get("content") or turn.get("assistant_final") or turn.get("user_query") or "").strip()
            if content:
                transcript_parts.append(content)
    turn_transcript = "\n".join(transcript_parts).strip()
    turn_dates = []
    for tid in source_turn_ids:
        hydrated = dict((turn_lookup or {}).get(tid) or {})
        turn = dict(hydrated.get("turn") or hydrated)
        metadata_turn = dict(turn.get("metadata") or {})
        date_value = str(
            metadata_turn.get("locomo_session_date_time")
            or metadata_turn.get("session_date_time")
            or turn.get("session_date_time")
            or turn.get("ts")
            or ""
        ).strip()
        if date_value:
            turn_dates.append(date_value)
    session_date_time = next((x for x in turn_dates if x), "")
    bead_text = str(
        bead.get("title")
        or "\n".join(str(x).strip() for x in (bead.get("summary") or []) if str(x).strip())
        or bead.get("detail")
        or ""
    ).strip()
    snippet = str(
        turn_transcript
        or bead_text
        or (row or {}).get("snippet")
        or (row or {}).get("text")
        or metadata.get("snippet")
        or metadata.get("text")
        or metadata.get("title")
        or (row or {}).get("title")
        or ""
    ).strip()
    return {
        "rank": int((row or {}).get("rank") or rank),
        "bead_id": bead_id,
        "dia_ids": sorted(set(dia_values)),
        "score": float((row or {}).get("score") or 0.0),
        "snippet": snippet,
        "text": snippet,
        "bead": bead,
        "bead_text": bead_text,
        "source_turn_ids": source_turn_ids,
        "turn_transcript": turn_transcript,
        "hydrated_turns": [dict((turn_lookup or {}).get(tid) or {}) for tid in source_turn_ids if (turn_lookup or {}).get(tid)],
        "speaker": str(metadata.get("speaker") or (row or {}).get("speaker") or "").strip(),
        "session_date_time": str(metadata.get("session_date_time") or (row or {}).get("session_date_time") or session_date_time or "").strip(),
        "source_surface": str((row or {}).get("source_surface") or metadata.get("source_surface") or bead.get("source_surface") or "").strip(),
    }


def _hydrate_retrieval_context(*, root: str | Path, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    bead_ids = []
    turn_ids = []
    for row in rows:
        metadata = dict((row or {}).get("metadata") or {})
        bid = str((row or {}).get("bead_id") or (row or {}).get("id") or "").strip()
        if bid:
            bead_ids.append(bid)
        for source in (row, metadata):
            vals = source.get("source_turn_ids") if isinstance(source, dict) else None
            if isinstance(vals, list):
                turn_ids.extend(str(x).strip() for x in vals if str(x).strip())
    try:
        hydrated = hydrate_bead_sources(root=str(root), bead_ids=list(dict.fromkeys(bead_ids)), turn_ids=list(dict.fromkeys(turn_ids)), include_tools=False, before=0, after=0)
    except Exception as exc:
        return {}, {}, {"ok": False, "error": str(exc), "bead_ids": list(dict.fromkeys(bead_ids)), "turn_ids": list(dict.fromkeys(turn_ids))}
    bead_lookup = {str(b.get("id") or ""): dict(b) for b in list((hydrated or {}).get("beads") or []) if isinstance(b, dict) and str(b.get("id") or "")}
    try:
        idx = json.loads((Path(root) / ".beads" / "index.json").read_text(encoding="utf-8"))
    except Exception:
        idx = {}
    for bid, bead in dict((idx or {}).get("beads") or {}).items():
        if str(bid) in set(bead_ids) and isinstance(bead, dict):
            merged = {**dict(bead_lookup.get(str(bid)) or {}), **dict(bead), "id": str(bead.get("id") or bid)}
            bead_lookup[str(bid)] = merged
    turn_lookup: dict[str, Any] = {}
    for h in list((hydrated or {}).get("hydrated") or []):
        if not isinstance(h, dict):
            continue
        turn = dict(h.get("turn") or {})
        tid = str(turn.get("turn_id") or turn.get("id") or "").strip()
        if tid:
            turn_lookup[tid] = h
    return bead_lookup, turn_lookup, dict(hydrated or {})


def _score_effort_payload(
    *,
    root: str | Path,
    qa: BenchmarkQA,
    payload: dict[str, Any],
    latency_ms: float,
    bead_to_dias: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    result_rows = _result_rows(payload)
    bead_lookup, turn_lookup, hydration = _hydrate_retrieval_context(root=root, rows=result_rows)
    retrieved = [_normalize_retrieved_row(row, rank=idx, bead_lookup=bead_lookup, turn_lookup=turn_lookup) for idx, row in enumerate(result_rows, start=1)]
    # ACCURACY FIX: the retrieval payload does not reliably surface a per-turn
    # dia_id, so a row's dia_ids can come back empty and silently zero out
    # evidence recall. Backfill each row's dia_ids from the authoritative
    # bead_id -> dia_id map built from the bead index after ingestion. The flat,
    # rank-ordered dia list is then scored with the upstream-faithful recall.
    bead_to_dias = bead_to_dias or {}
    for row in retrieved:
        if not row.get("dia_ids"):
            mapped = list(bead_to_dias.get(str(row.get("bead_id") or ""), []))
            if mapped:
                row["dia_ids"] = mapped
    prediction = _result_prediction(payload)
    category_raw = (qa.metadata or {}).get("category") or qa.category or 0
    try:
        category = int(category_raw or 0)
    except Exception:
        category = 0
    excluded = category not in locomo_faithful.OFFICIAL_CATEGORIES
    answer_f1 = (
        locomo_faithful.score_answer(category=category, prediction=prediction, answer=str(qa.expected_answer or ""))
        if qa.expected_answer is not None
        else 0.0
    )
    # Primary (published-comparable) recall: flat dia_id space, upstream semantics.
    ranked_dias = locomo_faithful.ranked_dia_ids_for_rows(retrieved, bead_to_dias)
    evidence = locomo_faithful.compute_evidence_recall(
        gold_evidence=list(qa.gold_evidence or []),
        retrieved=ranked_dias,
        ks=[1, 3, 5, 8, 10],
    )
    # Secondary (legacy) row-based recall, retained for auditing/UI continuity.
    evidence_rowwise = compute_evidence_recall(gold_evidence=list(qa.gold_evidence or []), retrieved=retrieved, ks=[1, 3, 5, 8, 10])
    return {
        "prediction": prediction,
        "answer_f1": float(answer_f1),
        "excluded": bool(excluded),
        "retrieved": retrieved,
        "retrieved_count": len(retrieved),
        "retrieved_dia_ids": ranked_dias,
        "evidence_recall": evidence,
        "evidence_recall_rowwise": evidence_rowwise,
        "retrieval_hydration": hydration,
        "latency_ms": float(latency_ms),
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * float(percentile)))))
    return round(ordered[idx], 3)


def aggregate_lifecycle_effort_scores(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_effort: dict[str, dict[str, Any]] = {}
    for effort in RETRIEVAL_EFFORT_ORDER:
        rows = [dict(((case.get("efforts") or {}).get(effort) or {})) for case in cases]
        rows = [row for row in rows if row]
        latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
        answer_scores = [float(row.get("answer_f1") or 0.0) for row in rows]
        recall5 = [float((row.get("evidence_recall") or {}).get("recall@5") or 0.0) for row in rows]
        hit_any = [1.0 if bool((row.get("evidence_recall") or {}).get("hit_any")) else 0.0 for row in rows]
        by_effort[effort] = {
            "qa_count": len(rows),
            "answer_f1_mean": round(sum(answer_scores) / len(answer_scores), 4) if answer_scores else 0.0,
            "evidence_recall@5": round(sum(recall5) / len(recall5), 4) if recall5 else 0.0,
            "hit_any": round(sum(hit_any) / len(hit_any), 4) if hit_any else 0.0,
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
            },
        }
    return {
        "overall": dict(by_effort.get("high") or {}),
        "by_effort": by_effort,
        "accuracy_by_effort": {effort: float((by_effort.get(effort) or {}).get("answer_f1_mean") or 0.0) for effort in RETRIEVAL_EFFORT_ORDER},
        "evidence_recall_by_effort": {effort: float((by_effort.get(effort) or {}).get("evidence_recall@5") or 0.0) for effort in RETRIEVAL_EFFORT_ORDER},
        "latency_by_effort_ms": {effort: dict((by_effort.get(effort) or {}).get("latency_ms") or {}) for effort in RETRIEVAL_EFFORT_ORDER},
    }


def corpus_snapshot(root: str | Path) -> dict[str, int]:
    """Read a lightweight corpus snapshot from the bead index."""

    path = Path(root) / ".beads" / "index.json"
    if not path.exists():
        return {"beads": 0, "associations": 0, "semantic_associations": 0, "entities": 0, "claims": 0}
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"beads": 0, "associations": 0, "semantic_associations": 0, "entities": 0, "claims": 0}
    if not isinstance(payload, dict):
        return {"beads": 0, "associations": 0, "semantic_associations": 0, "entities": 0, "claims": 0}

    beads = dict(payload.get("beads") or {})
    associations = list(payload.get("associations") or [])
    semantic_excluded = {"follows", "precedes", "shared_tag", "associated_with"}
    semantic_associations = 0
    for assoc in associations:
        if not isinstance(assoc, dict):
            continue
        rel = str(assoc.get("relationship") or assoc.get("type") or "").strip().lower()
        if rel and rel not in semantic_excluded:
            semantic_associations += 1
    claims = 0
    for bead in beads.values():
        if isinstance(bead, dict):
            claims += len(list(bead.get("claims") or []))
    return {
        "beads": len(beads),
        "associations": len(associations),
        "semantic_associations": semantic_associations,
        "entities": len(dict(payload.get("entities") or {})),
        "claims": claims,
    }


def lifecycle_corpus_warnings(snapshot: dict[str, Any], *, phase: str) -> list[str]:
    """Warn about missing runtime products without synthesizing them."""

    prefix = f"{str(phase or 'lifecycle')}:"
    warnings: list[str] = []
    if int((snapshot or {}).get("associations") or 0) <= 0:
        warnings.append(prefix + "no_associations_produced")
    if int((snapshot or {}).get("semantic_associations") or 0) <= 0:
        warnings.append(prefix + "no_semantic_associations_produced")
    if int((snapshot or {}).get("claims") or 0) <= 0:
        warnings.append(prefix + "no_claims_produced")
    if int((snapshot or {}).get("entities") or 0) <= 0:
        warnings.append(prefix + "no_entities_produced")
    return warnings


def _dedupe_warnings(rows: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        text = str(row or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def suite_corpus_snapshots(results: list[dict[str, Any]], corpus_after_suite: dict[str, int]) -> dict[str, Any]:
    """Expose PRD-visible corpus snapshots without hiding per-conversation detail."""

    per_conversation: list[dict[str, Any]] = []
    for result in results:
        replay = dict(result.get("replay") or {})
        pre_qa_flush = dict(result.get("pre_qa_flush") or {})
        row = {
            "conversation_id": str(result.get("conversation_id") or ""),
            "corpus_after_replay": dict(replay.get("corpus_after_replay") or {}),
            "corpus_after_pre_qa_flush": dict(pre_qa_flush.get("corpus_after_pre_qa_flush") or {}),
            "corpus_after_qa": dict(result.get("corpus_after_qa") or {}),
        }
        per_conversation.append(row)

    last = per_conversation[-1] if per_conversation else {}
    return {
        "corpus_after_replay": dict(last.get("corpus_after_replay") or {}),
        "corpus_after_pre_qa_flush": dict(last.get("corpus_after_pre_qa_flush") or {}),
        "corpus_after_qa": dict(last.get("corpus_after_qa") or corpus_after_suite or {}),
        "corpus_after_suite": dict(corpus_after_suite or {}),
        "per_conversation": per_conversation,
    }


def replay_conversation_turns(
    *,
    root: str | Path,
    conversation: BenchmarkConversation,
    process_turn_finalized_fn: ProcessTurnFinalized | None = None,
    progress: Any | None = None,
    progress_completed: int = 0,
    progress_total: int = 0,
    conversation_index: int = 1,
    conversation_total: int = 1,
) -> dict[str, Any]:
    """Replay normalized source turns through the capture/finalized-turn hook."""

    process_turn_finalized_fn = process_turn_finalized_fn or _default_process_turn_finalized()
    calls: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    total_turns = len(conversation.turns)
    for idx, turn in enumerate(conversation.turns, start=1):
        _emit_progress(
            progress,
            progress_completed,
            progress_total,
            None,
            {
                "status": "replaying",
                "phase": "locomo_lifecycle",
                "conversation_id": conversation.conversation_id,
                "conversation_index": conversation_index,
                "conversations": conversation_total,
                "replay_turn_completed": idx - 1,
                "replay_turn_total": total_turns,
                "turn_id": turn.turn_id,
            },
        )
        t0 = time.perf_counter()
        try:
            out = process_turn_finalized_fn(
                root=str(root),
                session_id=conversation.session_id,
                turn_id=turn.turn_id,
                transaction_id=f"tx:{turn.turn_id}",
                trace_id=f"trace:{turn.turn_id}",
                turns=[
                    {
                        "speaker": turn.speaker,
                        "role": turn.role,
                        "content": turn.content,
                    }
                ],
                metadata=_locomo_replay_metadata(root=root, conversation=conversation, turn=turn),
                origin="BENCHMARK_REPLAY",
            )
            ok = bool((out or {}).get("ok", True))
            calls.append(
                {
                    "turn_id": turn.turn_id,
                    "ok": ok,
                    "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                    "result": dict(out or {}),
                }
            )
            gate = (((out or {}).get("crawler_handoff") or {}).get("agent_authored_gate") or {})
            invocation = dict(gate.get("agent_invocation") or {}) if isinstance(gate, dict) else {}
            if str(gate.get("error_code") or "") == "agent_updates_missing" or str(invocation.get("reason") or "") == "invocation_disabled":
                errors.append({
                    "turn_id": turn.turn_id,
                    "error": "locomo_crawler_not_invoked",
                    "error_code": str(gate.get("error_code") or ""),
                    "invocation_reason": str(invocation.get("reason") or ""),
                })
            if not ok:
                errors.append({"turn_id": turn.turn_id, "error": str((out or {}).get("error") or "turn_replay_failed")})
        except Exception as exc:
            errors.append({"turn_id": turn.turn_id, "error": str(exc)})
            calls.append(
                {
                    "turn_id": turn.turn_id,
                    "ok": False,
                    "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                    "error": str(exc),
                }
            )

        _emit_progress(
            progress,
            progress_completed,
            progress_total,
            None,
            {
                "status": "replayed" if not errors or errors[-1].get("turn_id") != turn.turn_id else "failed",
                "phase": "locomo_lifecycle",
                "conversation_id": conversation.conversation_id,
                "conversation_index": conversation_index,
                "conversations": conversation_total,
                "replay_turn_completed": idx,
                "replay_turn_total": total_turns,
                "turn_id": turn.turn_id,
            },
        )

    snapshot = corpus_snapshot(root)
    warnings = lifecycle_corpus_warnings(snapshot, phase="after_replay")
    return {
        "ok": not errors,
        "conversation_id": conversation.conversation_id,
        "session_id": conversation.session_id,
        "turns_replayed": len(conversation.turns),
        "capture_hook_calls": len(calls),
        "calls": calls,
        "errors": errors,
        "warnings": warnings,
        "corpus_after_replay": snapshot,
    }


def run_pre_qa_flush(
    *,
    root: str | Path,
    conversation: BenchmarkConversation,
    token_budget: int = 1200,
    max_beads: int = 12,
    process_flush_fn: ProcessFlush | None = None,
    run_async_jobs_fn: RunAsyncJobs | None = None,
    drain_async: bool = True,
    max_compaction: int = 25,
    max_side_effects: int = 25,
) -> dict[str, Any]:
    """Fire the pre-QA session flush boundary and optionally drain queues."""

    process_flush_fn = process_flush_fn or _default_process_flush()
    flush_tx_id = f"bench-preqa:{conversation.conversation_id}"
    t0 = time.perf_counter()
    out = process_flush_fn(
        root=str(root),
        session_id=conversation.session_id,
        promote=True,
        token_budget=int(token_budget),
        max_beads=int(max_beads),
        source="benchmark_pre_qa",
        flush_tx_id=flush_tx_id,
    )
    flush_result = dict(out or {})
    async_result: dict[str, Any] | None = None
    if drain_async:
        run_async_jobs_fn = run_async_jobs_fn or _default_run_async_jobs()
        async_result = dict(
            run_async_jobs_fn(
                root=str(root),
                run_semantic=True,
                max_compaction=int(max_compaction),
                max_side_effects=int(max_side_effects),
            )
            or {}
        )
    snapshot = corpus_snapshot(root)
    warnings = lifecycle_corpus_warnings(snapshot, phase="after_pre_qa_flush")
    return {
        "ran": True,
        "ok": bool(flush_result.get("ok", True)),
        "flush_tx_id": flush_tx_id,
        "source": "benchmark_pre_qa",
        "token_budget": int(token_budget),
        "max_beads": int(max_beads),
        "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        "result": flush_result,
        "async_drain": async_result,
        "warnings": warnings,
        "corpus_after_pre_qa_flush": snapshot,
    }


def _qa_recall_request(*, conversation: BenchmarkConversation, qa: BenchmarkQA, k: int | None) -> dict[str, Any]:
    req: dict[str, Any] = {
        "raw_query": qa.question,
        "intent": str((qa.metadata or {}).get("intent") or "remember"),
        "constraints": {
            "benchmark_name": conversation.benchmark_name,
            "conversation_id": conversation.conversation_id,
            "qa_id": qa.qa_id,
            "recall_scope": "full_bead_corpus",
        },
    }
    if k is not None:
        req["k"] = max(1, int(k))
    return req


def run_qa_efforts(
    *,
    root: str | Path,
    conversation: BenchmarkConversation,
    qa: BenchmarkQA,
    recall_fn: RecallFunc | None = None,
    retrieval_efforts: tuple[str, ...] = RETRIEVAL_EFFORT_ORDER,
    k: int | None = None,
    answer_mode: str = "none",
    generator_model: str | None = None,
    bead_to_dias: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Run every configured retrieval effort for one QA case in order."""

    efforts = tuple(str(x).strip().lower() for x in retrieval_efforts if str(x).strip())
    if efforts != RETRIEVAL_EFFORT_ORDER:
        raise BenchmarkLifecycleError(f"retrieval effort order must be {RETRIEVAL_EFFORT_ORDER}, got {efforts}")
    recall_fn = recall_fn or _default_recall()
    req = _qa_recall_request(conversation=conversation, qa=qa, k=k)
    results: dict[str, Any] = {}
    order: list[str] = []

    for effort in efforts:
        t0 = time.perf_counter()
        raw = recall_fn(dict(req), effort=effort, root=str(root), explain=True, include_raw=True)
        payload = _as_dict(raw)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        score_meta = _score_effort_payload(root=root, qa=qa, payload=payload, latency_ms=latency_ms, bead_to_dias=bead_to_dias)
        warnings = list(payload.get("warnings") or [])
        answer_payload: dict[str, Any] = {}
        # Lifecycle recall returns evidence but does not synthesize an answer.
        # Generate exactly the high-effort benchmark answer here so answer_f1
        # measures the answerer over retrieved evidence instead of scoring blank
        # recall payloads as zero.
        if effort == "high" and str(answer_mode or "none").strip().lower() != "none":
            try:
                sample_id = str(conversation.conversation_id or "").replace("locomo:", "", 1)
                answer_payload = generate_locomo_answer(
                    mode=str(answer_mode or "none"),
                    root=str(root),
                    sample_id=sample_id,
                    qa={
                        "question": qa.question,
                        "answer": qa.expected_answer,
                        "category": qa.category,
                        "sample_id": sample_id,
                        "qa_id": qa.qa_id,
                    },
                    retrieved_context=list(score_meta.get("retrieved") or []),
                    generator_model=generator_model,
                )
                prediction = str(answer_payload.get("answer") or "").strip()
                category_raw = (qa.metadata or {}).get("category") or qa.category or 0
                try:
                    category = int(category_raw or 0)
                except Exception:
                    category = 0
                score_meta["prediction"] = prediction
                score_meta["answer_f1"] = float(locomo_faithful.score_answer(category=category, prediction=prediction, answer=str(qa.expected_answer or ""))) if qa.expected_answer is not None else 0.0
                payload = {**payload, "answer": prediction, "answer_payload": answer_payload}
            except Exception as exc:
                warnings.append(f"answer_generation_failed:{type(exc).__name__}:{exc}")
        results[effort] = {
            "effort": effort,
            "latency_ms": latency_ms,
            "request": req,
            "result": payload,
            "warnings": warnings,
            "answer_payload": answer_payload,
            **score_meta,
        }
        order.append(effort)

    return {
        "qa_id": qa.qa_id,
        "conversation_id": conversation.conversation_id,
        "question": qa.question,
        "expected_answer": qa.expected_answer,
        "gold_evidence": list(qa.gold_evidence or []),
        "category": qa.category,
        "bucket_labels": list(qa.bucket_labels or []),
        "retrieval_order": order,
        "efforts": results,
    }


def write_qa_turn(
    *,
    root: str | Path,
    conversation: BenchmarkConversation,
    qa: BenchmarkQA,
    qa_result: dict[str, Any],
    qa_session_id: str,
    process_turn_finalized_fn: ProcessTurnFinalized | None = None,
) -> dict[str, Any]:
    """Write one QA lifecycle bead after effort retrieval for shared QA mode."""

    process_turn_finalized_fn = process_turn_finalized_fn or _default_process_turn_finalized()
    high = dict((dict((qa_result or {}).get("efforts") or {}).get("high") or {}).get("result") or {})
    final_answer = str(high.get("answer") or high.get("text") or high.get("status") or "").strip()
    if not final_answer:
        final_answer = "High-effort retrieval completed; answer generation not configured in lifecycle runner."
    turn_id = f"qa:{qa.qa_id}"
    out = process_turn_finalized_fn(
        root=str(root),
        session_id=qa_session_id,
        turn_id=turn_id,
        transaction_id=f"tx:{turn_id}",
        trace_id=f"trace:{turn_id}",
        turns=[
            {"role": "user", "speaker": "benchmark_user", "content": qa.question},
            {"role": "assistant", "speaker": "benchmark_agent", "content": final_answer},
        ],
        metadata={
            "benchmark_name": conversation.benchmark_name,
            "benchmark_phase": "qa",
            "conversation_id": conversation.conversation_id,
            "qa_id": qa.qa_id,
            "retrieval_efforts": list(RETRIEVAL_EFFORT_ORDER),
            "selected_answer_effort": "high",
        },
        origin="BENCHMARK_QA",
    )
    return {"qa_bead_written": bool((out or {}).get("ok", True)), "turn_id": turn_id, "result": dict(out or {})}


def _safe_path_part(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(value or "").strip())
    return cleaned.strip(".-") or "qa"


def _isolated_qa_root(*, root: str | Path, conversation: BenchmarkConversation, qa: BenchmarkQA) -> Path:
    base = Path(root)
    parent = base.parent
    out = parent / f"{base.name}-qa-isolated" / _safe_path_part(conversation.conversation_id) / _safe_path_part(qa.qa_id)
    if out.exists():
        shutil.rmtree(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(base, out, ignore=shutil.ignore_patterns("*-qa-isolated"))
    return out


def _qa_live_summary(qa: BenchmarkQA, qa_result: dict[str, Any]) -> dict[str, Any]:
    """Compact per-QA payload for live UI: question, generated answer, evidence.

    Lets the demo echo each LoCoMo QA into the chat and surface the beads it
    retrieved without waiting for the final report.
    """
    high = dict((dict((qa_result or {}).get("efforts") or {}).get("high") or {}))
    high_result = dict(high.get("result") or {})
    answer = str(high_result.get("answer") or high.get("prediction") or "").strip()
    retrieved = list(high.get("retrieved") or [])
    evidence = [
        {
            "bead_id": str(r.get("bead_id") or ""),
            "dia_ids": list(r.get("dia_ids") or []),
            "snippet": str(r.get("snippet") or r.get("text") or "")[:180],
        }
        for r in retrieved[:5]
        if isinstance(r, dict) and str(r.get("bead_id") or "")
    ]
    return {
        "question": str(qa.question or ""),
        "answer": answer,
        "answer_f1": float(high.get("answer_f1") or 0.0),
        "category": str(qa.category or ""),
        "evidence": evidence,
        "evidence_bead_ids": [e["bead_id"] for e in evidence],
        "retrieved_dia_ids": list(high.get("retrieved_dia_ids") or []),
    }


def _emit_progress(progress: Any | None, completed: int, total: int, qa: BenchmarkQA | None, result: dict[str, Any]) -> None:
    if progress is None:
        return
    metadata = dict((qa.metadata if qa else {}) or {})
    case = {
        "qa_id": str((qa.qa_id if qa else "") or ""),
        "sample_id": str(metadata.get("sample_id") or metadata.get("locomo_sample_id") or ""),
        "question": str((qa.question if qa else "") or ""),
    }
    result_payload = dict(result or {})
    if not case["sample_id"]:
        conversation_id = str(result_payload.get("conversation_id") or "")
        if conversation_id.startswith("locomo:"):
            case["sample_id"] = conversation_id.split(":", 1)[1]
    try:
        progress(int(completed), int(total), case, result_payload)
    except TypeError:
        try:
            progress({"completed": int(completed), "total": int(total), "case": case, "result": result_payload})
        except Exception:
            pass
    except Exception:
        pass


def run_lifecycle_conversation(
    *,
    root: str | Path,
    conversation: BenchmarkConversation,
    dataset_mode: str = "locomo_native_lifecycle",
    shortcut_flags: BenchmarkShortcutFlags | None = None,
    qa_session_mode: str = "shared",
    process_turn_finalized_fn: ProcessTurnFinalized | None = None,
    process_flush_fn: ProcessFlush | None = None,
    run_async_jobs_fn: RunAsyncJobs | None = None,
    recall_fn: RecallFunc | None = None,
    write_qa_beads: bool = True,
    retrieval_k: int | None = None,
    answer_mode: str = "none",
    generator_model: str | None = None,
    progress: Any | None = None,
    progress_total: int | None = None,
    progress_completed_offset: int = 0,
) -> dict[str, Any]:
    """Run the faithful benchmark lifecycle for one normalized conversation."""

    flags = shortcut_flags or BenchmarkShortcutFlags()
    assert_lifecycle_faithful_mode(dataset_mode=dataset_mode, shortcut_flags=flags)
    qa_session_mode_name = str(qa_session_mode or "shared").strip().lower() or "shared"
    if qa_session_mode_name not in {"shared", "isolated"}:
        raise BenchmarkLifecycleError("qa_session_mode must be shared or isolated")

    replay = replay_conversation_turns(
        root=root,
        conversation=conversation,
        process_turn_finalized_fn=process_turn_finalized_fn,
        progress=progress,
        progress_completed=progress_completed_offset,
        progress_total=progress_total if progress_total is not None else len(conversation.qa_cases),
        conversation_index=int((conversation.metadata or {}).get("conversation_index") or 1),
        conversation_total=int((conversation.metadata or {}).get("conversation_total") or 1),
    )
    pre_qa_flush = run_pre_qa_flush(
        root=root,
        conversation=conversation,
        process_flush_fn=process_flush_fn,
        run_async_jobs_fn=run_async_jobs_fn,
    )
    semantic_build: dict[str, Any] = {}
    try:
        semantic_build = _build_semantic_index(root)
    except Exception as exc:
        semantic_build = {"ok": False, "error": str(exc)}

    # Build the authoritative bead_id -> dia_id map AFTER replay + pre-QA flush so
    # it reflects the post-compaction corpus that recall actually retrieves from.
    # This is what makes evidence recall trustworthy (see locomo_faithful). The
    # map is built once on the base root; isolated QA roots are copytree clones
    # that preserve bead IDs, so the same map applies to them.
    try:
        bead_to_dias = locomo_faithful.build_bead_to_dias(root, conversation)
    except Exception:
        bead_to_dias = {}

    qa_session_id = conversation.session_id.replace(":replay", ":qa") if conversation.session_id.endswith(":replay") else f"{conversation.session_id}:qa"
    qa_results: list[dict[str, Any]] = []
    total_for_progress = int(progress_total if progress_total is not None else len(conversation.qa_cases))
    offset_for_progress = int(progress_completed_offset or 0)
    for idx, qa in enumerate(conversation.qa_cases, start=1):
        _emit_progress(progress, offset_for_progress + idx - 1, total_for_progress, qa, {"status": "retrieving", "phase": "lifecycle_qa", "conversation_id": conversation.conversation_id})
        qa_root: str | Path = root
        qa_session_id_for_case = qa_session_id
        isolated_meta: dict[str, Any] = {"enabled": False}
        if qa_session_mode_name == "isolated":
            isolated_path = _isolated_qa_root(root=root, conversation=conversation, qa=qa)
            qa_root = isolated_path
            qa_session_id_for_case = f"{qa_session_id}:{_safe_path_part(qa.qa_id)}"
            isolated_meta = {
                "enabled": True,
                "root": str(isolated_path),
                "corpus_before_qa": corpus_snapshot(isolated_path),
            }

        qa_result = run_qa_efforts(root=qa_root, conversation=conversation, qa=qa, recall_fn=recall_fn, k=retrieval_k, answer_mode=answer_mode, generator_model=generator_model, bead_to_dias=bead_to_dias)
        if write_qa_beads:
            qa_result.update(write_qa_turn(root=qa_root, conversation=conversation, qa=qa, qa_result=qa_result, qa_session_id=qa_session_id_for_case, process_turn_finalized_fn=process_turn_finalized_fn))
        else:
            qa_result["qa_bead_written"] = False
        if isolated_meta.get("enabled"):
            isolated_meta["corpus_after_qa"] = corpus_snapshot(qa_root)
        qa_result["qa_session_id"] = qa_session_id_for_case
        qa_result["qa_session_mode"] = qa_session_mode_name
        qa_result["isolated_qa"] = isolated_meta
        qa_results.append(qa_result)
        _emit_progress(
            progress,
            offset_for_progress + idx,
            total_for_progress,
            qa,
            {"status": "ok", "phase": "lifecycle_qa", "conversation_id": conversation.conversation_id, **_qa_live_summary(qa, qa_result)},
        )

    scores = aggregate_lifecycle_effort_scores(qa_results)
    corpus_after_qa = corpus_snapshot(root)
    warnings = _dedupe_warnings(
        list(replay.get("warnings") or [])
        + list(pre_qa_flush.get("warnings") or [])
        + lifecycle_corpus_warnings(corpus_after_qa, phase="after_qa")
    )

    return {
        "ok": bool(replay.get("ok")) and bool(pre_qa_flush.get("ok", True)),
        "dataset_mode": dataset_mode,
        "lifecycle": {
            "dataset_mode": dataset_mode,
            "lifecycle_faithful": dataset_mode == "locomo_native_lifecycle" and not flags.any_enabled(),
            "conversations": 1,
            "turns_replayed": int(replay.get("turns_replayed") or 0),
            "replay_turns_original": int((conversation.metadata or {}).get("replay_turns_original") or len(conversation.turns)),
            "replay_turns_required": int((conversation.metadata or {}).get("replay_turns_required") or len(conversation.turns)),
            "bounded_replay": bool((conversation.metadata or {}).get("bounded_replay")),
            "bounded_replay_reason": str((conversation.metadata or {}).get("bounded_replay_reason") or ""),
            "capture_hook_calls": int(replay.get("capture_hook_calls") or 0),
            "pre_qa_flush_ran": bool(pre_qa_flush.get("ran")),
            "qa_session_mode": qa_session_mode_name,
            "qa_cases": len(conversation.qa_cases),
            "dia_bead_map_size": len(bead_to_dias),
            "retrieval_efforts_per_qa": list(RETRIEVAL_EFFORT_ORDER),
        },
        "shortcut_guards": flags.to_dict(),
        "warnings": warnings,
        "conversation_id": conversation.conversation_id,
        "session_id": conversation.session_id,
        "qa_session_id": qa_session_id,
        "replay": replay,
        "pre_qa_flush": pre_qa_flush,
        "semantic_build": semantic_build,
        "scores": scores,
        "cases": qa_results,
        "corpus_after_qa": corpus_after_qa,
    }


def _case_identity(row: dict[str, Any]) -> str:
    raw = str((row or {}).get("qa_id") or "").strip()
    if raw.startswith("locomo:"):
        return raw
    return f"locomo:{raw}" if raw else ""


def _evidence_turn_refs(raw: str) -> list[str]:
    refs: list[str] = []
    normalized = str(raw or "").replace(",", " ").replace(";", " ")
    for chunk in normalized.split():
        ref = chunk.strip()
        if ref:
            refs.append(ref)
    return refs


def _bounded_replay_turns_for_qa(conversation: BenchmarkConversation, qa_cases: list[BenchmarkQA]) -> tuple[list[BenchmarkTurn], dict[str, Any]]:
    """Trim replay to the latest source turn required by the selected QA evidence.

    LoCoMo QA limits select questions, not turns. Replaying the full conversation for
    a small QA subset makes the UI look frozen and turns a 50-QA smoke run into a
    full-conversation replay. For selected QA subsets, keep faithful chronology but
    stop after the latest gold evidence turn referenced by those selected cases.
    """

    turns = list(conversation.turns)
    if not turns or not qa_cases:
        return turns, {"bounded_replay": False}

    turn_index_by_ref: dict[str, int] = {}
    for idx, turn in enumerate(turns, start=1):
        metadata = dict(turn.metadata or {})
        refs = [
            str(turn.turn_id or "").strip(),
            str(metadata.get("locomo_dia_id") or "").strip(),
        ]
        for ref in refs:
            if ref:
                turn_index_by_ref[ref] = idx

    max_required = 0
    missing_refs: list[str] = []
    evidence_refs = 0
    for qa in qa_cases:
        for raw_ref in list(qa.gold_evidence or []):
            for ref in _evidence_turn_refs(str(raw_ref or "")):
                evidence_refs += 1
                idx = turn_index_by_ref.get(ref)
                if idx is None:
                    missing_refs.append(ref)
                    continue
                max_required = max(max_required, idx)

    if max_required <= 0:
        return turns, {
            "bounded_replay": False,
            "bounded_replay_reason": "no_selected_qa_evidence_refs_matched",
            "selected_qa_cases": len(qa_cases),
            "selected_evidence_refs": evidence_refs,
            "missing_evidence_refs": missing_refs[:20],
        }

    bounded = turns[:max_required]
    return bounded, {
        "bounded_replay": max_required < len(turns),
        "bounded_replay_reason": "selected_qa_latest_evidence_turn",
        "selected_qa_cases": len(qa_cases),
        "selected_evidence_refs": evidence_refs,
        "missing_evidence_refs": missing_refs[:20],
        "replay_turns_original": len(turns),
        "replay_turns_required": max_required,
    }


def _filter_conversation_qa(conversation: BenchmarkConversation, selected_case_ids: set[str]) -> BenchmarkConversation:
    if not selected_case_ids:
        return conversation
    qa_cases = [qa for qa in conversation.qa_cases if qa.qa_id in selected_case_ids]
    turns, replay_meta = _bounded_replay_turns_for_qa(conversation, qa_cases)
    metadata = dict(conversation.metadata or {})
    metadata.update(replay_meta)
    return BenchmarkConversation(
        benchmark_name=conversation.benchmark_name,
        conversation_id=conversation.conversation_id,
        session_id=conversation.session_id,
        turns=turns,
        qa_cases=qa_cases,
        metadata=metadata,
    )


def run_locomo_lifecycle_suite(
    *,
    root: str | Path,
    samples: list[dict[str, Any]],
    qa_cases: list[dict[str, Any]] | None = None,
    dataset_mode: str = "locomo_native_lifecycle",
    shortcut_flags: BenchmarkShortcutFlags | None = None,
    qa_session_mode: str = "shared",
    process_turn_finalized_fn: ProcessTurnFinalized | None = None,
    process_flush_fn: ProcessFlush | None = None,
    run_async_jobs_fn: RunAsyncJobs | None = None,
    recall_fn: RecallFunc | None = None,
    write_qa_beads: bool = True,
    retrieval_k: int | None = None,
    answer_mode: str = "none",
    generator_model: str | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Run faithful LoCoMo lifecycle benchmark over selected samples.

    This is the first suite-level bridge from existing LoCoMo selection to the
    new lifecycle runner. It keeps the adapter pure and preserves selected QA
    filtering from legacy suite controls.
    """

    flags = shortcut_flags or BenchmarkShortcutFlags()
    assert_lifecycle_faithful_mode(dataset_mode=dataset_mode, shortcut_flags=flags)
    # Hard, mode-independent contamination gate (upstream parity): an official
    # faithful run can never silently carry a shortcut flag.
    assert_faithful_shortcuts(flags)

    selected_case_ids = {_case_identity(row) for row in list(qa_cases or []) if _case_identity(row)}
    conversations = [
        _filter_conversation_qa(conv, selected_case_ids)
        for conv in locomo_samples_to_benchmark_conversations(list(samples or []))
    ]
    conversations = [conv for conv in conversations if conv.turns and conv.qa_cases]

    results: list[dict[str, Any]] = []
    completed_qa = 0
    failed = 0
    total_qa = sum(len(conv.qa_cases) for conv in conversations)
    for idx, conversation in enumerate(conversations, start=1):
        conversation.metadata["conversation_index"] = idx
        conversation.metadata["conversation_total"] = len(conversations)
        _emit_progress(progress, completed_qa, total_qa, None, {"status": "replaying", "phase": "locomo_lifecycle", "conversation_index": idx, "conversations": len(conversations), "conversation_id": conversation.conversation_id})
        out = run_lifecycle_conversation(
            root=root,
            conversation=conversation,
            dataset_mode=dataset_mode,
            shortcut_flags=flags,
            qa_session_mode=qa_session_mode,
            process_turn_finalized_fn=process_turn_finalized_fn,
            process_flush_fn=process_flush_fn,
            run_async_jobs_fn=run_async_jobs_fn,
            recall_fn=recall_fn,
            write_qa_beads=write_qa_beads,
            retrieval_k=retrieval_k,
            answer_mode=answer_mode,
            generator_model=generator_model,
            progress=progress,
            progress_total=total_qa,
            progress_completed_offset=completed_qa,
        )
        results.append(out)
        completed_qa += int(((out.get("lifecycle") or {}).get("qa_cases") or 0))
        if not bool(out.get("ok")):
            failed += 1

    cases: list[dict[str, Any]] = []
    for result in results:
        cases.extend(list(result.get("cases") or []))
    scores = aggregate_lifecycle_effort_scores(cases)
    corpus_after_suite = corpus_snapshot(root)
    snapshots = suite_corpus_snapshots(results, corpus_after_suite)
    semantic_builds = [dict(r.get("semantic_build") or {}) for r in results if isinstance(r.get("semantic_build"), dict)]
    semantic_build = dict(semantic_builds[-1] if semantic_builds else {})
    if semantic_builds:
        semantic_build["conversation_builds"] = semantic_builds
    warnings = _dedupe_warnings(
        [w for result in results for w in list(result.get("warnings") or [])]
        + lifecycle_corpus_warnings(corpus_after_suite, phase="after_suite")
    )

    return {
        "ok": failed == 0,
        "dataset_mode": dataset_mode,
        "lifecycle": {
            "dataset_mode": dataset_mode,
            "lifecycle_faithful": dataset_mode == "locomo_native_lifecycle" and not flags.any_enabled(),
            "conversations": len(conversations),
            "turns_replayed": sum(int(((r.get("lifecycle") or {}).get("turns_replayed") or 0)) for r in results),
            "replay_turns_original": sum(int(((r.get("lifecycle") or {}).get("replay_turns_original") or 0)) for r in results),
            "replay_turns_required": sum(int(((r.get("lifecycle") or {}).get("replay_turns_required") or 0)) for r in results),
            "bounded_replay": any(bool((r.get("lifecycle") or {}).get("bounded_replay")) for r in results),
            "capture_hook_calls": sum(int(((r.get("lifecycle") or {}).get("capture_hook_calls") or 0)) for r in results),
            "pre_qa_flush_ran": all(bool((r.get("lifecycle") or {}).get("pre_qa_flush_ran")) for r in results) if results else False,
            "qa_session_mode": qa_session_mode,
            "qa_cases": completed_qa,
            "retrieval_efforts_per_qa": list(RETRIEVAL_EFFORT_ORDER),
        },
        "shortcut_guards": flags.to_dict(),
        "warnings": warnings,
        "completed": completed_qa,
        "failed_conversations": failed,
        "scores": scores,
        "conversations": results,
        "cases": cases,
        "corpus_after_replay": dict(snapshots.get("corpus_after_replay") or {}),
        "corpus_after_pre_qa_flush": dict(snapshots.get("corpus_after_pre_qa_flush") or {}),
        "corpus_after_qa": dict(snapshots.get("corpus_after_qa") or {}),
        "corpus_after_suite": corpus_after_suite,
        "corpus_snapshots": snapshots,
        "semantic_build": semantic_build,
    }
