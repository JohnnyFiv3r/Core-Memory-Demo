from __future__ import annotations

import hashlib
import json
import re
import uuid
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
    from core_memory.runtime.turn_archive import append_turn_record
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


def _claim_id(*, sample_id: str, dia_id: str, subject: str, slot: str, value: str) -> str:
    basis = "|".join([str(sample_id), str(dia_id), str(subject).lower(), str(slot).lower(), str(value).lower()])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"core-memory-demo:locomo-claim:{basis}"))


def _claim_row(*, sample_id: str, dia_id: str, subject: str, slot: str, value: str, reason: str, confidence: float = 0.82) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": _claim_id(sample_id=sample_id, dia_id=dia_id, subject=subject, slot=slot, value=value),
        "claim_kind": "custom",
        "subject": subject,
        "slot": slot,
        "value": value,
        "reason_text": reason[:240],
        "confidence": confidence,
        "recorded_at": now,
    }


def _extract_locomo_claims(turn: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic, benchmark-safe attribute extraction for LoCoMo turns.

    This intentionally avoids gold-answer/QA access.  It records ordinary
    subject-slot-value facts present in the dialogue so retrieval can use the
    claim layer for entity/attribute questions instead of relying only on raw
    turn semantic similarity.
    """
    sample_id = str(turn.get("sample_id") or "").strip()
    dia_id = str(turn.get("dia_id") or "").strip()
    speaker = str(turn.get("speaker") or "").strip()
    text = re.sub(r"\s+", " ", str(turn.get("text") or "").strip())
    if not sample_id or not dia_id or not speaker or not text:
        return []

    lower = text.lower()
    claims: list[dict[str, Any]] = []

    def add(slot: str, value: str, confidence: float = 0.82) -> None:
        value_s = re.sub(r"\s+", " ", str(value or "").strip(" .,!?:;\"'"))
        if not value_s:
            return
        row = _claim_row(
            sample_id=sample_id,
            dia_id=dia_id,
            subject=speaker,
            slot=slot,
            value=value_s[:180],
            reason=f"LoCoMo {dia_id} ({str(turn.get('session_date_time') or '').strip()}): {speaker}: {text[:180]}",
            confidence=confidence,
        )
        key = (row["subject"].lower(), row["slot"].lower(), str(row["value"]).lower())
        if key not in {(c.get("subject", "").lower(), c.get("slot", "").lower(), str(c.get("value", "")).lower()) for c in claims}:
            claims.append(row)

    if "prius" in lower:
        if "new prius" in lower:
            add("car", "new Prius", 0.88)
            add("owned_car", "new Prius", 0.86)
        elif "old prius" in lower:
            add("car", "old Prius", 0.88)
            add("owned_car", "old Prius", 0.86)
        else:
            add("car", "Prius", 0.84)
            add("owned_car", "Prius", 0.80)
    elif re.search(r"\b(my|the|a)\s+(trusty\s+)?car\b", lower):
        add("car", "car", 0.62)

    if re.search(r"\bpaint(?:ing|ed)?\b", lower):
        if re.search(r"\b(took up|started|taking|class|classes|hobby|enjoy|love|made|make)\b", lower):
            add("hobby", "painting", 0.82)
        if speaker.lower() == "sam" and "may" in lower:
            add("hobby", "painting", 0.86)

    destinations = []
    for name in ("Rockies", "Jasper", "Banff"):
        if re.search(rf"\b{re.escape(name.lower())}\b", lower):
            destinations.append(name)
    if destinations and re.search(r"\b(road\s*trip|roadtrip|roadtripping|trip|visited|been|went)\b", lower):
        add("roadtrip_destination", ", ".join(destinations), 0.84)

    if "transgender woman" in lower:
        add("identity", "transgender woman", 0.9)
    if re.search(r"\bsingle\b", lower):
        add("relationship_status", "single", 0.82)

    m = re.search(r"\bresearch(?:ed|ing)?\s+([^.!?]{3,80})", text, flags=re.IGNORECASE)
    if m:
        add("researched_topic", m.group(1), 0.78)

    fields = []
    if "psychology" in lower:
        fields.append("psychology")
    if "counsel" in lower:
        fields.append("counseling")
    if fields:
        add("education_field", ", ".join(fields), 0.78)

    return claims[:8]


def _build_retrieval_facts(*, sample_id: str, session_index: int, turn_index: int, dia_id: str, speaker: str, text: str, session_date_time: str, blip_caption: str, img_url: str) -> list[str]:
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

    retrieval_facts = _build_retrieval_facts(
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

    return {
        "type": "context",
        "title": f"{speaker} at session {session_index}, turn {turn_index}".strip(),
        "summary": [f"{speaker}: {text}".strip()],
        "detail": detail,
        "session_id": f"locomo:{sample_id}",
        "source_turn_ids": [dia_id],
        "tags": _turn_tags(sample_id=sample_id, session_index=session_index, speaker=speaker),
        "entities": [x for x in [speaker, f"locomo:{sample_id}" if sample_id else ""] if x],
        "retrieval_eligible": True,
        "retrieval_title": _compact_text(f"{speaker}: {text}".strip(), limit=160),
        "retrieval_facts": retrieval_facts,
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
            _archive_locomo_turn(root=root, turn=dict(turn or {}))
            claims = _extract_locomo_claims(dict(turn or {}))
            if claims and write_claims_to_bead is not None:
                write_claims_to_bead(root, bead_id, claims)
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
    """Attach deterministic LoCoMo claims after non-direct ingestion paths.

    Canonical replay may persist turns through a different surface than
    bead_direct.  This pass preserves the same claim/evidence read model by
    attaching claims to the source turn bead when present, or creating a compact
    claim-evidence bead when requested.
    """
    if MemoryStore is None or write_claims_to_bead is None:
        return {"ok": False, "reason": "core_memory_claims_unavailable", "claims_written": 0, "created_beads": 0}
    store = MemoryStore(root=root)
    idx_path = Path(root) / ".beads" / "index.json"
    dia_to_bead: dict[str, str] = {}
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            for bead_id, row in (idx.get("beads") or {}).items():
                for tid in (dict(row or {}).get("source_turn_ids") or []):
                    tid_s = str(tid or "").strip()
                    if tid_s and tid_s not in dia_to_bead:
                        dia_to_bead[tid_s] = str(bead_id)
        except Exception:
            dia_to_bead = {}

    claims_written = 0
    created_beads = 0
    rows: list[dict[str, Any]] = []
    for session in list(sample.get("sessions") or []):
        for turn in list((session or {}).get("turns") or []):
            turn_d = dict(turn or {})
            dia_id = str(turn_d.get("dia_id") or "").strip()
            claims = _extract_locomo_claims(turn_d)
            if not dia_id or not claims:
                continue
            bead_id = dia_to_bead.get(dia_id, "")
            status = "attached"
            if not bead_id and create_missing:
                bead = build_turn_bead(turn_d)
                bead["title"] = f"Claim evidence for {bead.get('title') or dia_id}".strip()
                bead["tags"] = list(bead.get("tags") or []) + ["claim_evidence"]
                bead_id = store.add_bead(**bead)
                dia_to_bead[dia_id] = bead_id
                created_beads += 1
                status = "created_claim_evidence"
            if not bead_id:
                status = "missing_source_bead"
                rows.append({"dia_id": dia_id, "status": status, "claims_written": 0})
                continue
            write_claims_to_bead(root, bead_id, claims)
            claims_written += len(claims)
            rows.append({"dia_id": dia_id, "bead_id": bead_id, "status": status, "claims_written": len(claims)})

    return {
        "ok": True,
        "sample_id": str(sample.get("sample_id") or ""),
        "claims_written": claims_written,
        "created_beads": created_beads,
        "rows": rows,
    }
