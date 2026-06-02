from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from core_memory.persistence.store import MemoryStore
except Exception:  # pragma: no cover
    MemoryStore = None  # type: ignore
try:
    from core_memory.persistence.store_claim_ops import write_claims_to_bead
except Exception:  # pragma: no cover
    write_claims_to_bead = None  # type: ignore
try:
    from core_memory.runtime.turn.turn_archive import append_turn_record
except Exception:  # pragma: no cover
    append_turn_record = None  # type: ignore


def _turn_tags(*, sample_id: str, session_index: int, speaker: str) -> list[str]:
    tags = [
        "locomo",
        "locomo_dialog",
        f"sample:{sample_id}",
        f"session:{session_index}",
    ]
    if speaker:
        tags.append(f"speaker:{speaker}")
    return tags


def _compact_text(value: str, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _turn_scope_key(*, sample_id: str, dia_id: str) -> str:
    return f"{str(sample_id or '').strip()}::{str(dia_id or '').strip()}"


def _extract_locomo_claims(turn: dict[str, Any]) -> list[dict[str, Any]]:
    """Return no benchmark-injected claims for LoCoMo turns.

    The benchmark must not create dataset-specific subject/slot/value claims
    from LoCoMo transcript literals. Doing so turns the benchmark ingestion path
    into a hand-written answer-key adapter instead of an evaluation of the
    production memory/retrieval system.

    Keep this compatibility shim so older call sites remain harmless while the
    benchmark relies on raw ingested turns, generic production extraction, or
    explicitly separate non-scoring diagnostics.
    """
    _ = turn
    return []


def _build_supporting_facts(*, sample_id: str, session_index: int, turn_index: int, dia_id: str, speaker: str, text: str, session_date_time: str, blip_caption: str, img_url: str) -> list[str]:
    facts: list[str] = [
        f"sample_id={sample_id}",
        f"session_index={session_index}",
        f"turn_index={turn_index}",
        f"dia_id={dia_id}",
    ]
    if speaker:
        facts.append(f"speaker={speaker}")
    if session_date_time:
        facts.append(f"session_date_time={session_date_time}")
    if text:
        facts.append(_compact_text(f"{speaker}: {text}" if speaker else text, limit=280))
    if blip_caption:
        facts.append(_compact_text(f"image_caption={blip_caption}", limit=220))
    if img_url:
        facts.append(f"has_image=true")
    deduped: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        key = str(fact or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _archive_locomo_turn(*, root: str, turn: dict[str, Any]) -> None:
    if append_turn_record is None:
        return
    sample_id = str(turn.get("sample_id") or "").strip()
    dia_id = str(turn.get("dia_id") or "").strip()
    if not sample_id or not dia_id:
        return
    speaker = str(turn.get("speaker") or "").strip()
    text = str(turn.get("text") or "").strip()
    session_index = int(turn.get("session_index") or 0)
    turn_index = int(turn.get("turn_index") or 0)
    session_date_time = str(turn.get("session_date_time") or turn.get("date_time") or "").strip()
    img_url = str(turn.get("img_url") or "").strip()
    blip_caption = str(turn.get("blip_caption") or "").strip()
    assistant_final = f"{speaker}: {text}".strip(": ")
    try:
        append_turn_record(
            root=Path(root),
            session_id=f"locomo:{sample_id}",
            turn_id=f"locomo:{sample_id}:{dia_id}",
            transaction_id=f"tx-locomo:{sample_id}:{dia_id}",
            trace_id=f"tr-locomo:{sample_id}:{dia_id}",
            origin="LOCOMO_BENCHMARK_INGEST",
            ts=datetime.now(timezone.utc).isoformat(),
            user_query=f"[LoCoMo transcript] session={session_index} dia_id={dia_id} speaker={speaker}",
            assistant_final=assistant_final,
            assistant_final_ref=None,
            assistant_final_hash=hashlib.sha256(assistant_final.encode("utf-8")).hexdigest(),
            tools_trace=[],
            mesh_trace=[],
            metadata={
                "benchmark_name": "locomo",
                "locomo_sample_id": sample_id,
                "locomo_session_index": session_index,
                "locomo_session_date_time": session_date_time,
                "locomo_dia_id": dia_id,
                "locomo_dia_ids": [dia_id],
                "locomo_speaker": speaker,
                "locomo_turn_index": turn_index,
                "locomo_has_image": bool(img_url or blip_caption),
                "locomo_display_text": assistant_final,
                "img_url": img_url,
                "blip_caption": blip_caption,
                "replay_source": "locomo",
                "replay_policy": "bead_direct_turn_archive",
            },
        )
    except Exception:
        return


def build_turn_bead(turn: dict[str, Any]) -> dict[str, Any]:
    sample_id = str(turn.get("sample_id") or "").strip()
    session_index = int(turn.get("session_index") or 0)
    turn_index = int(turn.get("turn_index") or 0)
    speaker = str(turn.get("speaker") or "").strip()
    text = str(turn.get("text") or "").strip()
    blip_caption = str(turn.get("blip_caption") or "").strip()
    img_url = str(turn.get("img_url") or "").strip()
    dia_id = str(turn.get("dia_id") or f"S{session_index}:{turn_index}").strip()
    session_date_time = str(turn.get("session_date_time") or "").strip()
    detail = text
    if session_date_time:
        detail = f"Session date: {session_date_time}\n\n{detail}".strip()
    if blip_caption:
        detail = detail + f"\n\nImage caption: {blip_caption}"
    if img_url:
        detail = detail + f"\nImage URL: {img_url}"

    supporting_facts = _build_supporting_facts(
        sample_id=sample_id,
        session_index=session_index,
        turn_index=turn_index,
        dia_id=dia_id,
        speaker=speaker,
        text=text,
        session_date_time=session_date_time,
        blip_caption=blip_caption,
        img_url=img_url,
    )

    # CM #174: retrieval_eligible/retrieval_title/retrieval_facts removed — every
    # bead is indexed, and build_retrieval_text() embeds `title` directly. Carry
    # the utterance in the title (was in retrieval_title) so recall text is rich.
    return {
        "type": "context",
        "title": _compact_text(f"{speaker}: {text}".strip(), limit=160)
        or f"{speaker} at session {session_index}, turn {turn_index}".strip(),
        "summary": [f"{speaker}: {text}".strip()],
        "detail": detail,
        "session_id": f"locomo:{sample_id}",
        "source_turn_ids": [dia_id],
        "tags": _turn_tags(sample_id=sample_id, session_index=session_index, speaker=speaker),
        "entities": [x for x in [speaker, f"locomo:{sample_id}" if sample_id else ""] if x],
        "supporting_facts": supporting_facts,
        "metadata": {
            "source": "locomo",
            "sample_id": sample_id,
            "session_index": session_index,
            "dia_id": dia_id,
            "speaker": speaker,
            "session_date_time": session_date_time,
            "turn_index": turn_index,
            "has_image": bool(img_url or blip_caption),
            "img_url": img_url,
            "blip_caption": blip_caption,
        },
    }


def ingest_locomo_turns(*, root: str, sample: dict[str, Any], mode: str = "turns") -> dict[str, Any]:
    if str(mode or "turns") != "turns":
        raise ValueError(f"unsupported_locomo_ingestion_mode:{mode}")

    if MemoryStore is None:
        raise RuntimeError("core_memory_unavailable")
    store = MemoryStore(root=root)
    sample_id = str(sample.get("sample_id") or "").strip()
    sessions = list(sample.get("sessions") or [])
    ingested: list[dict[str, Any]] = []
    existing_ids: set[str] = set()
    idx_path = Path(root) / ".beads" / "index.json"
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            for row in (idx.get("beads") or {}).values():
                meta = dict(dict(row or {}).get("metadata") or {})
                row_sample_id = str(meta.get("sample_id") or "").strip()
                row_session_id = str(dict(row or {}).get("session_id") or "").strip()
                if not row_sample_id and row_session_id.startswith("locomo:"):
                    row_sample_id = row_session_id.split(":", 1)[1]
                for tid in (dict(row or {}).get("source_turn_ids") or []):
                    tid_s = str(tid).strip()
                    if tid_s and row_sample_id:
                        existing_ids.add(_turn_scope_key(sample_id=row_sample_id, dia_id=tid_s))
        except Exception:
            existing_ids = set()

    for session in sessions:
        for turn in list((session or {}).get("turns") or []):
            bead = build_turn_bead(dict(turn or {}))
            dia_id = str((bead.get("source_turn_ids") or [""])[0] or "").strip()
            turn_key = _turn_scope_key(sample_id=sample_id, dia_id=dia_id)
            if dia_id and turn_key in existing_ids:
                ingested.append(
                    {
                        "dia_id": dia_id,
                        "sample_id": sample_id,
                        "session_index": int(turn.get("session_index") or 0),
                        "turn_index": int(turn.get("turn_index") or 0),
                        "session_id": str(bead.get("session_id") or ""),
                        "bead_id": None,
                        "status": "skipped_existing",
                        "trace": dict(bead.get("metadata") or {}),
                    }
                )
                continue
            bead_id = store.add_bead(**bead)
            _archive_locomo_turn(root=root, turn=dict(turn or {}))
            claims = _extract_locomo_claims(dict(turn or {}))
            if claims and write_claims_to_bead is not None:
                write_claims_to_bead(root, bead_id, claims)
            existing_ids.add(turn_key)
            ingested.append(
                {
                    "dia_id": dia_id,
                    "sample_id": sample_id,
                    "session_index": int(turn.get("session_index") or 0),
                    "turn_index": int(turn.get("turn_index") or 0),
                    "session_id": str(bead.get("session_id") or ""),
                    "bead_id": bead_id,
                    "status": "ingested",
                    "claims_written": len(claims),
                    "trace": dict(bead.get("metadata") or {}),
                }
            )

    return {
        "ok": True,
        "sample_id": sample_id,
        "mode": "turns",
        "turns_total": sum(len((s or {}).get("turns") or []) for s in sessions),
        "ingested": ingested,
        "ingested_count": sum(1 for row in ingested if row.get("status") == "ingested"),
        "skipped_existing_count": sum(1 for row in ingested if row.get("status") == "skipped_existing"),
        "claims_written": sum(int(row.get("claims_written") or 0) for row in ingested),
    }


def attach_locomo_claims(*, root: str, sample: dict[str, Any], create_missing: bool = False) -> dict[str, Any]:
    """Compatibility no-op: LoCoMo benchmarks must not inject claims."""
    _ = (root, create_missing)
    return {
        "ok": True,
        "sample_id": str((sample or {}).get("sample_id") or ""),
        "claims_written": 0,
        "created_beads": 0,
        "rows": [],
    }
