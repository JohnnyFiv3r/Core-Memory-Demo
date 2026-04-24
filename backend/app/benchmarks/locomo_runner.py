from __future__ import annotations

from typing import Any

from app.benchmarks.locomo_scoring import compute_evidence_recall

try:
    from core_memory.integrations.api import inspect_bead
    from core_memory.retrieval.normalize import classify_intent
    from core_memory.retrieval.tools import memory as memory_tools
except Exception:  # pragma: no cover
    inspect_bead = None  # type: ignore
    classify_intent = None  # type: ignore
    memory_tools = None  # type: ignore


def _intent_for_question(question: str) -> str:
    if classify_intent is None:
        return "remember"
    try:
        out = classify_intent(str(question or "")) or {}
        return str(out.get("intent") or out.get("intent_class") or "remember").strip() or "remember"
    except Exception:
        return "remember"


def _extract_result_row(*, root: str, rank: int, row: dict[str, Any]) -> dict[str, Any]:
    bead_id = str(row.get("bead_id") or "").strip()
    bead = inspect_bead(root=root, bead_id=bead_id) if bead_id and inspect_bead is not None else None
    bead = dict(bead or {})
    metadata = dict(bead.get("metadata") or {})
    dia_ids = [str(x).strip() for x in (bead.get("source_turn_ids") or []) if str(x).strip()]
    return {
        "rank": rank,
        "bead_id": bead_id,
        "title": str(row.get("title") or bead.get("title") or "").strip(),
        "snippet": str(row.get("snippet") or "").strip(),
        "score": float(row.get("score") or 0.0),
        "source_surface": str(row.get("source_surface") or "").strip(),
        "dia_ids": dia_ids,
        "sample_id": str(metadata.get("sample_id") or "").strip(),
        "session_index": int(metadata.get("session_index") or 0),
        "speaker": str(metadata.get("speaker") or "").strip(),
        "session_date_time": str(metadata.get("session_date_time") or "").strip(),
        "text": str(bead.get("detail") or "").strip(),
    }


def run_locomo_retrieval_case(*, root: str, sample_id: str, qa: dict[str, Any], retrieval_k: int = 8, evidence_recall_k: list[int] | None = None) -> dict[str, Any]:
    if memory_tools is None:
        return {
            "qa_id": str(qa.get("qa_id") or ""),
            "sample_id": sample_id,
            "category": int(qa.get("category") or 0),
            "question": str(qa.get("question") or ""),
            "gold_answer": str(qa.get("answer") or ""),
            "prediction": "",
            "status": "error",
            "error": "core_memory_unavailable",
            "retrieved": [],
            "evidence_recall": compute_evidence_recall(gold_evidence=list(qa.get("evidence") or []), retrieved=[], ks=evidence_recall_k or [1, 3, 5, 8, 10]),
        }

    req = {
        "query": str(qa.get("question") or "").strip(),
        "intent": _intent_for_question(str(qa.get("question") or "")),
        "k": max(1, int(retrieval_k or 8)),
        "constraints": {
            "sample_id": sample_id,
            "session_id": f"locomo:{sample_id}",
        },
    }
    try:
        result = memory_tools.execute(req, root=root, explain=False)
        raw_results = list(result.get("results") or [])
        retrieved = [_extract_result_row(root=root, rank=idx, row=dict(row or {})) for idx, row in enumerate(raw_results, start=1)]
        evidence = compute_evidence_recall(
            gold_evidence=list(qa.get("evidence") or []),
            retrieved=retrieved,
            ks=evidence_recall_k or [1, 3, 5, 8, 10],
        )
        return {
            "qa_id": str(qa.get("qa_id") or ""),
            "sample_id": sample_id,
            "category": int(qa.get("category") or 0),
            "question": str(qa.get("question") or ""),
            "gold_answer": str(qa.get("answer") or ""),
            "prediction": "",
            "status": "ok",
            "retrieved": retrieved,
            "evidence_recall": evidence,
            "warnings": list(result.get("warnings") or []),
            "backend": str(result.get("backend") or "unknown"),
            "raw_result_count": len(raw_results),
        }
    except Exception as exc:
        return {
            "qa_id": str(qa.get("qa_id") or ""),
            "sample_id": sample_id,
            "category": int(qa.get("category") or 0),
            "question": str(qa.get("question") or ""),
            "gold_answer": str(qa.get("answer") or ""),
            "prediction": "",
            "status": "error",
            "error": str(exc),
            "retrieved": [],
            "evidence_recall": compute_evidence_recall(gold_evidence=list(qa.get("evidence") or []), retrieved=[], ks=evidence_recall_k or [1, 3, 5, 8, 10]),
        }


def run_locomo_retrieval_suite(*, root: str, qa_cases: list[dict[str, Any]], retrieval_k: int = 8, evidence_recall_k: list[int] | None = None) -> dict[str, Any]:
    cases = [
        run_locomo_retrieval_case(
            root=root,
            sample_id=str(case.get("sample_id") or ""),
            qa=dict(case or {}),
            retrieval_k=retrieval_k,
            evidence_recall_k=evidence_recall_k,
        )
        for case in qa_cases
    ]
    return {
        "cases": cases,
        "completed": sum(1 for c in cases if c.get("status") == "ok"),
        "failed": sum(1 for c in cases if c.get("status") == "error"),
    }
