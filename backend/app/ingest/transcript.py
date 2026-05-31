from __future__ import annotations

from typing import Any

from core_memory import ingest_transcript as core_ingest_transcript

_ALLOWED_FLUSH_POLICIES = {"end_only", "per_session", "none"}
_ALLOWED_MODES = {"dyadic", "group"}
_ALLOWED_KWARGS = {"root", "transcript_id", "turns", "session_id", "flush_policy", "metadata", "mode", "window_size"}


def validate_transcript_request(payload: dict[str, Any], *, max_turns: int = 500) -> dict[str, Any]:
    """Validate the demo HTTP boundary without normalizing transcript semantics.

    Role aliases, message-field aliases, user/assistant pairing, session-window
    continuity, and association summaries are engine responsibilities owned by
    ``core_memory.ingest_transcript``. This function only builds a safe job
    kwargs payload and intentionally passes the original turn rows through.

    ``mode="group"`` selects Core Memory's N-speaker ingest gateway (multi-party
    transcripts), bypassing the dyadic user/assistant pairing requirement; an
    optional ``source_system`` (e.g. ``slack``/``discord``/``zoom:{id}``) is
    threaded through metadata so speaker-identity resolution can scope labels.
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
    mode = str(payload.get("mode") or "dyadic").strip().lower() or "dyadic"
    if mode not in _ALLOWED_MODES:
        raise ValueError(f"unsupported_mode:{mode}")
    metadata = dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}
    source_system = str(payload.get("source_system") or "").strip()
    if source_system:
        metadata.setdefault("source_system", source_system)

    built: dict[str, Any] = {
        "transcript_id": transcript_id,
        "session_id": session_id,
        "turns": list(raw_turns),
        "flush_policy": flush_policy,
        "metadata": metadata,
        "mode": mode,
    }
    window_size_raw = payload.get("window_size")
    if window_size_raw not in (None, ""):
        try:
            built["window_size"] = max(1, int(window_size_raw))
        except (TypeError, ValueError):
            raise ValueError("invalid_window_size")
    return built


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
    mode: str = "dyadic",
    window_size: int | None = None,
) -> dict[str, Any]:
    """Run transcript ingest through the Core-Memory engine API.

    ``mode``/``window_size`` are forwarded to Core Memory's N-speaker group
    ingest gateway when present; the dyadic default preserves prior behaviour.
    """

    kwargs: dict[str, Any] = {
        "root": root,
        "transcript_id": transcript_id,
        "turns": turns,
        "session_id": session_id,
        "flush_policy": flush_policy,
        "metadata": dict(metadata or {}),
    }
    if str(mode or "dyadic").strip().lower() == "group":
        kwargs["mode"] = "group"
        if window_size is not None:
            kwargs["window_size"] = int(window_size)
    out = core_ingest_transcript(**kwargs)
    return _with_boundary_warnings(dict(out or {}))


def transcript_job_kwargs(payload: dict[str, Any], *, root: str, max_turns: int = 500) -> dict[str, Any]:
    kwargs = {"root": root, **validate_transcript_request(payload, max_turns=max_turns)}
    # Keep the (dataset-agnostic) job payload minimal: only carry the N-speaker
    # group knobs when group mode is actually requested. The dyadic default
    # produces exactly the generic transcript kwargs.
    if str(kwargs.get("mode") or "dyadic") == "dyadic":
        kwargs.pop("mode", None)
        kwargs.pop("window_size", None)
    return {key: kwargs[key] for key in _ALLOWED_KWARGS if key in kwargs}
