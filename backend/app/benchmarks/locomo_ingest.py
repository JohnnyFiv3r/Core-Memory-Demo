from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from core_memory.persistence.store import MemoryStore
except Exception:  # pragma: no cover
    MemoryStore = None  # type: ignore


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


def build_turn_bead(turn: dict[str, Any]) -> dict[str, Any]:
    sample_id = str(turn.get("sample_id") or "").strip()
    session_index = int(turn.get("session_index") or 0)
    turn_index = int(turn.get("turn_index") or 0)
    speaker = str(turn.get("speaker") or "").strip()
    text = str(turn.get("text") or "").strip()
    blip_caption = str(turn.get("blip_caption") or "").strip()
    img_url = str(turn.get("img_url") or "").strip()
    dia_id = str(turn.get("dia_id") or f"S{session_index}:{turn_index}").strip()
    detail = text
    if blip_caption:
        detail = detail + f"\n\nImage caption: {blip_caption}"
    if img_url:
        detail = detail + f"\nImage URL: {img_url}"

    return {
        "type": "context",
        "title": f"{speaker} at session {session_index}, turn {turn_index}".strip(),
        "summary": [f"{speaker}: {text}".strip()],
        "detail": detail,
        "session_id": f"locomo:{sample_id}",
        "source_turn_ids": [dia_id],
        "tags": _turn_tags(sample_id=sample_id, session_index=session_index, speaker=speaker),
        "retrieval_eligible": True,
        "retrieval_title": f"{speaker}: {text[:160]}".strip(),
        "retrieval_facts": [
            f"sample_id={sample_id}",
            f"session_index={session_index}",
            f"dia_id={dia_id}",
            f"speaker={speaker}",
        ],
        "metadata": {
            "source": "locomo",
            "sample_id": sample_id,
            "session_index": session_index,
            "dia_id": dia_id,
            "speaker": speaker,
            "session_date_time": str(turn.get("session_date_time") or "").strip(),
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
                for tid in (dict(row or {}).get("source_turn_ids") or []):
                    if str(tid).strip():
                        existing_ids.add(str(tid).strip())
        except Exception:
            existing_ids = set()

    for session in sessions:
        for turn in list((session or {}).get("turns") or []):
            bead = build_turn_bead(dict(turn or {}))
            dia_id = str((bead.get("source_turn_ids") or [""])[0] or "").strip()
            if dia_id and dia_id in existing_ids:
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
            existing_ids.add(dia_id)
            ingested.append(
                {
                    "dia_id": dia_id,
                    "sample_id": sample_id,
                    "session_index": int(turn.get("session_index") or 0),
                    "turn_index": int(turn.get("turn_index") or 0),
                    "session_id": str(bead.get("session_id") or ""),
                    "bead_id": bead_id,
                    "status": "ingested",
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
    }
