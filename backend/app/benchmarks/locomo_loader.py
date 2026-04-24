from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_WORKSPACE_LOCOMO = Path(__file__).resolve().parents[4] / "tmp" / "locomo_src" / "locomo"
DEFAULT_DATA_FILE = DEFAULT_WORKSPACE_LOCOMO / "data" / "locomo10.json"


class LocomoLoaderError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocomoDatasetMeta:
    dataset_path: str
    repo_root: str
    repo_commit: str | None
    sample_count: int
    qa_count: int
    turns_count: int
    qa_with_evidence_count: int
    session_count_min: int
    session_count_max: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_path": self.dataset_path,
            "repo_root": self.repo_root,
            "repo_commit": self.repo_commit,
            "samples": self.sample_count,
            "qa_total": self.qa_count,
            "turns_total": self.turns_count,
            "qa_with_evidence": self.qa_with_evidence_count,
            "session_count_min": self.session_count_min,
            "session_count_max": self.session_count_max,
        }


def _resolve_repo_root() -> Path:
    raw = str(os.getenv("CORE_MEMORY_LOCOMO_REPO_ROOT") or "").strip()
    if raw:
        return Path(raw)
    return DEFAULT_WORKSPACE_LOCOMO


def resolve_locomo_data_file() -> Path:
    raw = str(os.getenv("CORE_MEMORY_LOCOMO_DATA_FILE") or "").strip()
    if raw:
        return Path(raw)
    repo_root = _resolve_repo_root()
    candidate = repo_root / "data" / "locomo10.json"
    if candidate.exists():
        return candidate
    return DEFAULT_DATA_FILE


def _git_commit(repo_root: Path) -> str | None:
    head = repo_root / ".git" / "HEAD"
    if not head.exists():
        return None
    try:
        raw = head.read_text(encoding="utf-8").strip()
        if raw.startswith("ref:"):
            ref = raw.split(" ", 1)[1].strip()
            ref_path = repo_root / ".git" / ref
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()[:7]
        return raw[:7] or None
    except Exception:
        return None


def _session_numbers(conversation: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for key in conversation.keys():
        if not key.startswith("session_"):
            continue
        tail = key[len("session_") :]
        if not tail.isdigit():
            continue
        out.append(int(tail))
    return sorted(set(out))


def _normalize_turn(sample_id: str, session_index: int, session_date_time: str, turn_index: int, row: dict[str, Any]) -> dict[str, Any]:
    dia_id = str(row.get("dia_id") or f"S{session_index}:{turn_index}").strip() or f"S{session_index}:{turn_index}"
    return {
        "dia_id": dia_id,
        "speaker": str(row.get("speaker") or "").strip(),
        "text": str(row.get("text") or "").strip(),
        "blip_caption": str(row.get("blip_caption") or "").strip(),
        "img_url": str(row.get("img_url") or "").strip(),
        "img_search_query": str(row.get("img_search_query") or "").strip(),
        "sample_id": sample_id,
        "session_index": session_index,
        "session_date_time": session_date_time,
        "turn_index": turn_index,
    }


def _normalize_sample(row: dict[str, Any]) -> dict[str, Any]:
    sample_id = str(row.get("sample_id") or row.get("id") or "").strip()
    if not sample_id:
        raise LocomoLoaderError("sample_missing_sample_id")

    conversation = dict(row.get("conversation") or {})
    session_numbers = _session_numbers(conversation)
    sessions: list[dict[str, Any]] = []
    turns_total = 0
    for session_index in session_numbers:
        session_key = f"session_{session_index}"
        date_key = f"session_{session_index}_date_time"
        raw_turns = list(conversation.get(session_key) or [])
        session_date_time = str(conversation.get(date_key) or "").strip()
        norm_turns = [
            _normalize_turn(sample_id, session_index, session_date_time, turn_index, dict(turn or {}))
            for turn_index, turn in enumerate(raw_turns, start=1)
            if isinstance(turn, dict)
        ]
        turns_total += len(norm_turns)
        sessions.append(
            {
                "session_index": session_index,
                "date_time": session_date_time,
                "turns": norm_turns,
            }
        )

    qa_rows: list[dict[str, Any]] = []
    for idx, qa in enumerate(list(row.get("qa") or []), start=1):
        if not isinstance(qa, dict):
            continue
        qa_rows.append(
            {
                "qa_id": f"{sample_id}:q{idx:04d}",
                "question": str(qa.get("question") or "").strip(),
                "answer": str(qa.get("answer") or "").strip(),
                "category": int(qa.get("category") or 0),
                "evidence": [str(x).strip() for x in (qa.get("evidence") or []) if str(x).strip()],
            }
        )

    return {
        "sample_id": sample_id,
        "speaker_a": str(conversation.get("speaker_a") or "").strip(),
        "speaker_b": str(conversation.get("speaker_b") or "").strip(),
        "sessions": sessions,
        "qa": qa_rows,
        "observation": dict(row.get("observation") or {}),
        "session_summary": dict(row.get("session_summary") or {}),
        "event_summary": dict(row.get("event_summary") or {}),
        "turns_total": turns_total,
    }


def load_locomo_dataset(*, data_file: str | Path | None = None, require_exists: bool = True) -> tuple[list[dict[str, Any]], LocomoDatasetMeta]:
    path = Path(data_file) if data_file else resolve_locomo_data_file()
    if require_exists and not path.exists():
        raise LocomoLoaderError(f"locomo_dataset_missing:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise LocomoLoaderError("locomo_dataset_invalid_root")

    samples = [_normalize_sample(dict(row or {})) for row in payload if isinstance(row, dict)]
    sample_count = len(samples)
    qa_count = sum(len(s.get("qa") or []) for s in samples)
    turns_count = sum(int(s.get("turns_total") or 0) for s in samples)
    qa_with_evidence_count = sum(sum(1 for qa in (s.get("qa") or []) if qa.get("evidence")) for s in samples)
    session_counts = [len(s.get("sessions") or []) for s in samples] or [0]

    meta = LocomoDatasetMeta(
        dataset_path=str(path),
        repo_root=str(path.parents[1]),
        repo_commit=_git_commit(path.parents[1]),
        sample_count=sample_count,
        qa_count=qa_count,
        turns_count=turns_count,
        qa_with_evidence_count=qa_with_evidence_count,
        session_count_min=min(session_counts),
        session_count_max=max(session_counts),
    )

    if sample_count != 10:
        raise LocomoLoaderError(f"locomo_unexpected_sample_count:{sample_count}")
    if qa_count != 1986:
        raise LocomoLoaderError(f"locomo_unexpected_qa_count:{qa_count}")
    if turns_count != 5882:
        raise LocomoLoaderError(f"locomo_unexpected_turn_count:{turns_count}")

    return samples, meta
