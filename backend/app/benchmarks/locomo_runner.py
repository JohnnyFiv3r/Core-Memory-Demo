from __future__ import annotations

import re
from typing import Any

from app.benchmarks.locomo_answer import generate_locomo_answer
from app.benchmarks.locomo_scoring import compute_evidence_recall, score_answer

try:
    from core_memory.integrations.api import inspect_bead
    from core_memory.retrieval.normalize import classify_intent
    from core_memory.retrieval.pipeline.canonical import trace_request
    from core_memory.retrieval.tools import memory as memory_tools
except Exception:  # pragma: no cover
    inspect_bead = None  # type: ignore
    classify_intent = None  # type: ignore
    trace_request = None  # type: ignore
    memory_tools = None  # type: ignore


def _intent_for_question(question: str) -> str:
    if classify_intent is None:
        return "remember"
    try:
        out = classify_intent(str(question or "")) or {}
        return str(out.get("intent") or out.get("intent_class") or "remember").strip() or "remember"
    except Exception:
        return "remember"


_MONTH_RE = r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)"


def _question_terms(question: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9']+", str(question or "").lower()) if len(tok) >= 3}


def _question_speaker_hints(question: str) -> set[str]:
    return {m.group(1).strip().lower() for m in re.finditer(r"\b(?:did|does|was|is|when|where|why|what|who|how)\s+([A-Z][a-z]+)\b", str(question or ""))}


def _question_date_hints(question: str) -> set[str]:
    hints: set[str] = set()
    text = str(question or "")
    for m in re.finditer(rf"\b\d{{1,2}}\s+{_MONTH_RE}(?:\s+\d{{4}})?\b", text, flags=re.IGNORECASE):
        hints.add(m.group(0).strip().lower())
    for m in re.finditer(rf"\b{_MONTH_RE}\s+\d{{1,2}}(?:\s+\d{{4}})?\b", text, flags=re.IGNORECASE):
        hints.add(m.group(0).strip().lower())
    return hints


def _question_session_hints(question: str) -> set[int]:
    hints: set[int] = set()
    text = str(question or "")
    for m in re.finditer(r"\bsession\s+(\d{1,2})\b", text, flags=re.IGNORECASE):
        try:
            hints.add(int(m.group(1)))
        except Exception:
            continue
    return hints


def _question_sequence_hints(question: str) -> set[str]:
    text = str(question or "").lower()
    hints: set[str] = set()
    for marker in ["first", "last", "earlier", "later", "before", "after", "recent", "latest"]:
        if marker in text:
            hints.add(marker)
    return hints


def _build_locomo_facets(*, question: str, sample_id: str) -> dict[str, Any]:
    must_terms: list[str] = []
    seen: set[str] = set()
    session_hints = _question_session_hints(question)
    sequence_hints = _question_sequence_hints(question)
    values = [
        str(sample_id or "").strip(),
        *sorted(_question_speaker_hints(question)),
        *sorted(_question_date_hints(question)),
        *[f"session_index={idx}" for idx in sorted(session_hints)],
        *sorted(sequence_hints),
    ]
    for value in values:
        term = str(value or "").strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        must_terms.append(term)
    return {
        "scope": "project",
        "must_terms": must_terms[:8],
    }


def _score_locomo_row(*, question: str, sample_id: str, row: dict[str, Any]) -> float:
    score = float(row.get("score") or 0.0)
    question_terms = _question_terms(question)
    speaker_hints = _question_speaker_hints(question)
    date_hints = _question_date_hints(question)
    session_hints = _question_session_hints(question)
    sequence_hints = _question_sequence_hints(question)
    text = " ".join(
        [
            str(row.get("title") or ""),
            str(row.get("snippet") or ""),
            str(row.get("text") or ""),
            str(row.get("speaker") or ""),
            str(row.get("session_date_time") or ""),
        ]
    ).lower()
    metadata_sample = str(row.get("sample_id") or "").strip().lower()
    if metadata_sample and metadata_sample == str(sample_id or "").strip().lower():
        score += 3.0
    for speaker in speaker_hints:
        if speaker and speaker in str(row.get("speaker") or "").strip().lower():
            score += 2.0
    for hint in date_hints:
        if hint and hint in text:
            score += 1.5
    if session_hints and int(row.get("session_index") or 0) in session_hints:
        score += 1.5
    if sequence_hints:
        sidx = int(row.get("session_index") or 0)
        if "first" in sequence_hints and sidx == 1:
            score += 1.0
        if any(x in sequence_hints for x in {"recent", "latest", "last", "later", "after"}) and sidx > 0:
            score += min(1.0, sidx * 0.1)
        if any(x in sequence_hints for x in {"earlier", "before"}) and sidx > 0:
            score += max(0.0, 1.0 - min(1.0, sidx * 0.1))
    overlap = sum(1 for tok in question_terms if tok in text)
    score += min(2.0, overlap * 0.2)
    if str(row.get("source_surface") or "").strip().lower() in {"session_bead", "bead"}:
        score += 0.25
    return score


def _rerank_locomo_results(*, question: str, sample_id: str, retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for idx, row in enumerate(retrieved, start=1):
        item = dict(row or {})
        item["base_rank"] = idx
        item["locomo_score"] = _score_locomo_row(question=question, sample_id=sample_id, row=item)
        scored.append(item)
    scored.sort(key=lambda row: (-float(row.get("locomo_score") or 0.0), int(row.get("base_rank") or 0)))
    for idx, row in enumerate(scored, start=1):
        row["rank"] = idx
    return scored


def _extract_result_row(*, root: str, rank: int, row: dict[str, Any]) -> dict[str, Any]:
    bead_id = str(row.get("bead_id") or "").strip()
    bead = inspect_bead(root=root, bead_id=bead_id) if bead_id and inspect_bead is not None else None
    bead = dict(bead or {})
    metadata = dict(bead.get("metadata") or {})
    raw_dia_ids = []
    for key in ("dia_ids", "dia_id", "locomo_dia_ids", "locomo_dia_id"):
        value = metadata.get(key)
        if isinstance(value, list):
            raw_dia_ids.extend([str(x).strip() for x in value if str(x).strip()])
        elif str(value or "").strip():
            raw_dia_ids.append(str(value).strip())
    if not raw_dia_ids:
        raw_dia_ids.extend([str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip()])
    if not raw_dia_ids:
        raw_dia_ids.extend([str(x).strip() for x in (bead.get("source_turn_ids") or []) if str(x).strip().startswith("D")])
    dia_ids = sorted(set(x for x in raw_dia_ids if x))
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


def _expand_via_causal_trace(*, root: str, question: str, sample_id: str, anchors: list[dict[str, Any]], retrieval_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if trace_request is None:
        return list(anchors or []), {"used": False, "reason": "trace_unavailable", "chains": [], "grounding": {}}
    anchor_ids = [str((row or {}).get("bead_id") or "").strip() for row in list(anchors or []) if str((row or {}).get("bead_id") or "").strip()]
    if not anchor_ids:
        return list(anchors or []), {"used": False, "reason": "no_anchor_ids", "chains": [], "grounding": {}}
    trace = trace_request(
        root=root,
        query=question,
        k=max(3, min(int(retrieval_k or 8), len(anchor_ids))),
        constraints={"session_id": f"locomo:{sample_id}", "require_structural": False},
        anchor_ids=anchor_ids[: max(3, int(retrieval_k or 8))],
    )
    merged: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(list(anchors or []), start=1):
        item = dict(row or {})
        bead_id = str(item.get("bead_id") or "").strip() or f"anchor:{idx}"
        item.setdefault("anchor_source", "search")
        merged[bead_id] = item
    trace_results = list(trace.get("results") or [])
    for row in trace_results:
        item = _extract_result_row(root=root, rank=0, row=dict(row or {}))
        bead_id = str(item.get("bead_id") or "").strip()
        if not bead_id:
            continue
        existing = dict(merged.get(bead_id) or {})
        if existing:
            item["locomo_score"] = max(float(existing.get("locomo_score") or 0.0), float(item.get("locomo_score") or item.get("score") or 0.0))
            item["anchor_source"] = "search+trace"
            if not item.get("dia_ids"):
                item["dia_ids"] = list(existing.get("dia_ids") or [])
            if not item.get("text"):
                item["text"] = str(existing.get("text") or "")
        else:
            item["anchor_source"] = "trace"
        merged[bead_id] = item
    expanded = list(merged.values())
    expanded = _rerank_locomo_results(question=question, sample_id=sample_id, retrieved=expanded)
    return expanded, {
        "used": True,
        "anchor_ids": anchor_ids,
        "chains": list(trace.get("chains") or []),
        "grounding": dict(trace.get("grounding") or {}),
        "warnings": list(trace.get("warnings") or []),
    }


def run_locomo_retrieval_case(*, root: str, sample_id: str, qa: dict[str, Any], retrieval_k: int = 8, evidence_recall_k: list[int] | None = None, answer_mode: str = "none", generator_model: str | None = None, gold_context_map: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if memory_tools is None:
        return {
            "qa_id": str(qa.get("qa_id") or ""),
            "sample_id": sample_id,
            "category": int(qa.get("category") or 0),
            "question": str(qa.get("question") or ""),
            "gold_answer": str(qa.get("answer") or ""),
            "prediction": "",
            "answer_f1": 0.0,
            "status": "error",
            "error": "core_memory_unavailable",
            "retrieved": [],
            "evidence_recall": compute_evidence_recall(gold_evidence=list(qa.get("evidence") or []), retrieved=[], ks=evidence_recall_k or [1, 3, 5, 8, 10]),
        }

    question = str(qa.get("question") or "").strip()
    req = {
        "query": question,
        "intent": _intent_for_question(question),
        "k": max(1, int(retrieval_k or 8)),
        "constraints": {
            "session_id": f"locomo:{sample_id}",
        },
        "facets": _build_locomo_facets(question=question, sample_id=sample_id),
    }
    try:
        result = memory_tools.execute(req, root=root, explain=False)
        raw_results = list(result.get("results") or [])
        retrieved = [_extract_result_row(root=root, rank=idx, row=dict(row or {})) for idx, row in enumerate(raw_results, start=1)]
        retrieved = _rerank_locomo_results(
            question=question,
            sample_id=sample_id,
            retrieved=retrieved,
        )
        retrieved, trace_meta = _expand_via_causal_trace(
            root=root,
            question=question,
            sample_id=sample_id,
            anchors=retrieved[: max(3, int(retrieval_k or 8))],
            retrieval_k=retrieval_k,
        )
        evidence = compute_evidence_recall(
            gold_evidence=list(qa.get("evidence") or []),
            retrieved=retrieved,
            ks=evidence_recall_k or [1, 3, 5, 8, 10],
        )
        gold_context = []
        if str(answer_mode or "").strip().lower() == "oracle_context":
            lookup = dict(gold_context_map or {})
            gold_context = [dict(lookup.get(did) or {}) for did in list(qa.get("evidence") or []) if dict(lookup.get(did) or {})]
        answer = generate_locomo_answer(
            mode=answer_mode,
            root=root,
            sample_id=sample_id,
            qa=qa,
            retrieved_context=retrieved,
            generator_model=generator_model,
            gold_context=gold_context,
        )
        prediction = str(answer.get("answer") or "")
        answer_f1 = float(score_answer(category=int(qa.get("category") or 0), prediction=prediction, answer=str(qa.get("answer") or "")))
        return {
            "qa_id": str(qa.get("qa_id") or ""),
            "sample_id": sample_id,
            "category": int(qa.get("category") or 0),
            "question": str(qa.get("question") or ""),
            "gold_answer": str(qa.get("answer") or ""),
            "prediction": prediction,
            "used_dia_ids": list(answer.get("used_dia_ids") or []),
            "confidence": str(answer.get("confidence") or "low"),
            "unsupported": bool(answer.get("unsupported")),
            "answer_f1": answer_f1,
            "status": "ok",
            "retrieved": retrieved,
            "evidence_recall": evidence,
            "warnings": list(result.get("warnings") or []),
            "backend": str(result.get("backend") or "unknown"),
            "raw_result_count": len(raw_results),
            "trace": trace_meta,
        }
    except Exception as exc:
        return {
            "qa_id": str(qa.get("qa_id") or ""),
            "sample_id": sample_id,
            "category": int(qa.get("category") or 0),
            "question": str(qa.get("question") or ""),
            "gold_answer": str(qa.get("answer") or ""),
            "prediction": "",
            "answer_f1": 0.0,
            "status": "error",
            "error": str(exc),
            "retrieved": [],
            "evidence_recall": compute_evidence_recall(gold_evidence=list(qa.get("evidence") or []), retrieved=[], ks=evidence_recall_k or [1, 3, 5, 8, 10]),
        }


def run_locomo_retrieval_suite(*, root: str, qa_cases: list[dict[str, Any]], retrieval_k: int = 8, evidence_recall_k: list[int] | None = None, answer_mode: str = "none", generator_model: str | None = None, gold_context_map: dict[str, dict[str, Any]] | None = None, progress: Any | None = None) -> dict[str, Any]:
    cases = []
    total = len(list(qa_cases or []))
    for idx, case in enumerate(list(qa_cases or []), start=1):
        result = run_locomo_retrieval_case(
            root=root,
            sample_id=str(case.get("sample_id") or ""),
            qa=dict(case or {}),
            retrieval_k=retrieval_k,
            evidence_recall_k=evidence_recall_k,
            answer_mode=answer_mode,
            generator_model=generator_model,
            gold_context_map=gold_context_map,
        )
        cases.append(result)
        if callable(progress):
            try:
                progress(idx, total, dict(case or {}), dict(result or {}))
            except Exception:
                pass
    return {
        "cases": cases,
        "completed": sum(1 for c in cases if c.get("status") == "ok"),
        "failed": sum(1 for c in cases if c.get("status") == "error"),
        "total": total,
    }
