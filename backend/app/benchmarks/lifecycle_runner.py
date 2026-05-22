from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from app.benchmarks.contracts import (
    BenchmarkConversation,
    BenchmarkLifecycleError,
    BenchmarkQA,
    BenchmarkShortcutFlags,
    BenchmarkTurn,
    assert_lifecycle_faithful_mode,
)

RETRIEVAL_EFFORT_ORDER = ("low", "medium", "high")

ProcessTurnFinalized = Callable[..., dict[str, Any]]
ProcessFlush = Callable[..., dict[str, Any]]
RunAsyncJobs = Callable[..., dict[str, Any]]
RecallFunc = Callable[..., Any]


def _default_process_turn_finalized() -> ProcessTurnFinalized:
    from core_memory.runtime.engine import process_turn_finalized

    return process_turn_finalized


def _default_process_flush() -> ProcessFlush:
    from core_memory.runtime.engine import process_flush

    return process_flush


def _default_run_async_jobs() -> RunAsyncJobs:
    from core_memory.runtime.jobs import run_async_jobs

    return run_async_jobs


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


def replay_conversation_turns(
    *,
    root: str | Path,
    conversation: BenchmarkConversation,
    process_turn_finalized_fn: ProcessTurnFinalized | None = None,
) -> dict[str, Any]:
    """Replay normalized source turns through the capture/finalized-turn hook."""

    process_turn_finalized_fn = process_turn_finalized_fn or _default_process_turn_finalized()
    calls: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for turn in conversation.turns:
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
                metadata={
                    "benchmark_name": conversation.benchmark_name,
                    "benchmark_phase": "conversation_replay",
                    "conversation_id": conversation.conversation_id,
                    "source_turn_id": turn.turn_id,
                    **dict(turn.metadata or {}),
                },
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

    return {
        "ok": not errors,
        "conversation_id": conversation.conversation_id,
        "session_id": conversation.session_id,
        "turns_replayed": len(conversation.turns),
        "capture_hook_calls": len(calls),
        "calls": calls,
        "errors": errors,
        "corpus_after_replay": corpus_snapshot(root),
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
        "corpus_after_pre_qa_flush": corpus_snapshot(root),
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
        results[effort] = {
            "effort": effort,
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "request": req,
            "result": payload,
            "warnings": list(payload.get("warnings") or []),
        }
        order.append(effort)

    return {
        "qa_id": qa.qa_id,
        "conversation_id": conversation.conversation_id,
        "question": qa.question,
        "expected_answer": qa.expected_answer,
        "gold_evidence": list(qa.gold_evidence or []),
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
) -> dict[str, Any]:
    """Run the faithful benchmark lifecycle for one normalized conversation."""

    flags = shortcut_flags or BenchmarkShortcutFlags()
    assert_lifecycle_faithful_mode(dataset_mode=dataset_mode, shortcut_flags=flags)
    if str(qa_session_mode or "shared") != "shared":
        raise BenchmarkLifecycleError("only shared QA session mode is implemented in this phase")

    replay = replay_conversation_turns(root=root, conversation=conversation, process_turn_finalized_fn=process_turn_finalized_fn)
    pre_qa_flush = run_pre_qa_flush(
        root=root,
        conversation=conversation,
        process_flush_fn=process_flush_fn,
        run_async_jobs_fn=run_async_jobs_fn,
    )

    qa_session_id = conversation.session_id.replace(":replay", ":qa") if conversation.session_id.endswith(":replay") else f"{conversation.session_id}:qa"
    qa_results: list[dict[str, Any]] = []
    for qa in conversation.qa_cases:
        qa_result = run_qa_efforts(root=root, conversation=conversation, qa=qa, recall_fn=recall_fn, k=retrieval_k)
        if write_qa_beads:
            qa_result.update(write_qa_turn(root=root, conversation=conversation, qa=qa, qa_result=qa_result, qa_session_id=qa_session_id, process_turn_finalized_fn=process_turn_finalized_fn))
        else:
            qa_result["qa_bead_written"] = False
        qa_result["qa_session_id"] = qa_session_id
        qa_results.append(qa_result)

    return {
        "ok": bool(replay.get("ok")) and bool(pre_qa_flush.get("ok", True)),
        "dataset_mode": dataset_mode,
        "lifecycle": {
            "dataset_mode": dataset_mode,
            "lifecycle_faithful": dataset_mode == "locomo_native_lifecycle" and not flags.any_enabled(),
            "conversations": 1,
            "turns_replayed": int(replay.get("turns_replayed") or 0),
            "capture_hook_calls": int(replay.get("capture_hook_calls") or 0),
            "pre_qa_flush_ran": bool(pre_qa_flush.get("ran")),
            "qa_session_mode": qa_session_mode,
            "qa_cases": len(conversation.qa_cases),
            "retrieval_efforts_per_qa": list(RETRIEVAL_EFFORT_ORDER),
        },
        "shortcut_guards": flags.to_dict(),
        "conversation_id": conversation.conversation_id,
        "session_id": conversation.session_id,
        "qa_session_id": qa_session_id,
        "replay": replay,
        "pre_qa_flush": pre_qa_flush,
        "cases": qa_results,
        "corpus_after_qa": corpus_snapshot(root),
    }
