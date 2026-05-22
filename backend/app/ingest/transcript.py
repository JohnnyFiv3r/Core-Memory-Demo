from __future__ import annotations

from typing import Any

from core_memory import ingest_transcript as core_ingest_transcript

_ALLOWED_FLUSH_POLICIES = {"end_only", "per_session", "none"}
_ALLOWED_KWARGS = {"root", "transcript_id", "turns", "session_id", "flush_policy", "metadata"}


def validate_transcript_request(payload: dict[str, Any], *, max_turns: int = 500) -> dict[str, Any]:
    """Validate the demo HTTP boundary without normalizing transcript semantics.

    Role aliases, message-field aliases, user/assistant pairing, session-window
    continuity, and association summaries are engine responsibilities owned by
    ``core_memory.ingest_transcript``. This function only builds a safe job
    kwargs payload and intentionally passes the original turn rows through.
    """

    if not isinstance(payload, dict):
        raise ValueError("payload_must_be_object")

    raw_turns = payload.get("turns")
    if raw_turns is None:
        raw_turns = payload.get("messages")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ValueError("turns_required")
    if len(raw_turns) > max(1, int(max_turns)):
        raise ValueError(f"turns_limit_exceeded:{max_turns}")
    for idx, row in enumerate(raw_turns):
        if not isinstance(row, dict):
            raise ValueError(f"turn_must_be_object:{idx}")

    transcript_id = str(payload.get("transcript_id") or "transcript").strip() or "transcript"
    session_id_raw = payload.get("session_id")
    session_id = str(session_id_raw).strip() if session_id_raw is not None else None
    flush_policy = str(payload.get("flush_policy") or "end_only").strip().lower() or "end_only"
    if flush_policy not in _ALLOWED_FLUSH_POLICIES:
        raise ValueError(f"unsupported_flush_policy:{flush_policy}")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    return {
        "transcript_id": transcript_id,
        "session_id": session_id,
        "turns": list(raw_turns),
        "flush_policy": flush_policy,
        "metadata": dict(metadata or {}),
    }


def _warning_codes(warnings: list[Any]) -> set[str]:
    codes: set[str] = set()
    for warning in warnings:
        if isinstance(warning, dict):
            code = str(warning.get("code") or "").strip()
        else:
            code = str(warning or "").strip()
        if code:
            codes.add(code)
    return codes


def _with_boundary_warnings(out: dict[str, Any]) -> dict[str, Any]:
    result = dict(out or {})
    warnings = list(result.get("warnings") or [])
    codes = _warning_codes(warnings)
    turns_received = int(result.get("turns_received") or 0)
    turns_paired = int(result.get("turns_paired") or 0)
    if turns_received > turns_paired * 2 and "unpaired_final_user_turn" not in codes:
        warnings.append(
            {
                "code": "unpaired_final_user_turn",
                "message": "Final user turn has no assistant response; ingested by the engine as a user-only turn.",
            }
        )
    result["warnings"] = warnings
    result["ingested_count"] = int(result.get("turns_ingested") or result.get("ingested_count") or 0)
    result.setdefault("associations_created", {"count": 0, "by_type": {}, "items": []})
    return result


def run_transcript_ingest_job(
    *,
    root: str,
    transcript_id: str,
    turns: list[dict[str, Any]],
    session_id: str | None = None,
    flush_policy: str = "end_only",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run transcript ingest through the Core-Memory engine API."""

    out = core_ingest_transcript(
        root=root,
        transcript_id=transcript_id,
        turns=turns,
        session_id=session_id,
        flush_policy=flush_policy,
        metadata=dict(metadata or {}),
    )
    return _with_boundary_warnings(dict(out or {}))


def transcript_job_kwargs(payload: dict[str, Any], *, root: str, max_turns: int = 500) -> dict[str, Any]:
    kwargs = {"root": root, **validate_transcript_request(payload, max_turns=max_turns)}
    return {key: kwargs[key] for key in _ALLOWED_KWARGS if key in kwargs}
