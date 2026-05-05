from __future__ import annotations

import re
from typing import Any

from app.benchmarks.locomo_answer import generate_locomo_answer
from app.benchmarks.locomo_scoring import compute_evidence_recall, score_answer

try:
    from core_memory.integrations.api import inspect_bead
    from core_memory.retrieval.normalize import classify_intent
    from core_memory.retrieval.tools import memory as memory_tools
except Exception:  # pragma: no cover
    inspect_bead = None  # type: ignore
    classify_intent = None  # type: ignore
    memory_tools = None  # type: ignore

try:
    from core_memory.retrieval.trace import trace_request
except Exception:  # pragma: no cover
    try:
        from core_memory.retrieval.pipeline import memory_trace as trace_request
    except Exception:  # pragma: no cover
        trace_request = None  # type: ignore


_STOP_TERMS = {
    "a", "an", "and", "are", "did", "does", "for", "from", "has", "have", "how",
    "in", "is", "it", "of", "on", "or", "the", "to", "was", "what", "when", "where",
    "which", "who", "why", "with",
}


def _intent_for_question(question: str) -> str:
    if classify_intent is None:
        return "remember"
    try:
        out = classify_intent(str(question or "")) or {}
        return str(out.get("intent") or out.get("intent_class") or "remember").strip() or "remember"
    except Exception:
        return "remember"


def _locomo_facets(*, sample_id: str, question: str) -> dict[str, Any]:
    """Build retrieval hints that keep LoCoMo QA anchored to its sample/session.

    The Core Memory execute API currently treats arbitrary constraints as advisory
    metadata, while typed search honors facets.  Add both topic filters and
    lexical terms so snapshot-mode benchmark runs don't drift into unrelated demo
    memory before post-projection diagnostics can catch it.
    """
    q = str(question or "")
    sample = str(sample_id or "").strip()
    must_terms: list[str] = []
    if sample:
        must_terms.extend([sample, f"sample_id={sample}", f"sample:{sample}", f"locomo:{sample}"])

    # Date phrases and named entities are often decisive in LoCoMo questions.
    for match in re.finditer(r"\b\d{1,2}\s+[A-Z][a-z]+\s+\d{4}\b", q):
        must_terms.append(match.group(0))
    for match in re.finditer(r"\bsession\s+(\d+)\b", q, flags=re.IGNORECASE):
        must_terms.append(f"session_index={match.group(1)}")
    for token in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", q):
        must_terms.append(token)
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", q.lower()):
        if token not in _STOP_TERMS:
            must_terms.append(token)

    deduped: list[str] = []
    seen: set[str] = set()
    for term in must_terms:
        t = str(term or "").strip()
        key = t.lower()
        if not t or key in seen:
            continue
        seen.add(key)
        deduped.append(t)

    return {
        "scope": "project",
        "topic_keys": [f"sample:{sample}"] if sample else [],
        "must_terms": deduped[:24],
    }


def _locomo_score(row: dict[str, Any], *, sample_id: str, question: str) -> float:
    score = float(row.get("score") or 0.0)
    metadata = dict((row.get("projection") or {}))
    row_sample = str(row.get("sample_id") or "").strip()
    if row_sample and row_sample == str(sample_id or "").strip():
        score += 1.0
    elif row_sample:
        score -= 1.0
    q_terms = {t.lower() for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", str(question or "")) if t.lower() not in _STOP_TERMS}
    text = " ".join(str(row.get(k) or "") for k in ("title", "snippet", "text", "speaker", "session_date_time")).lower()
    if q_terms:
        score += min(0.75, 0.08 * len([t for t in q_terms if t in text]))
    # Prefer rows whose projection is traceable to LoCoMo dia ids.
    if row.get("dia_ids"):
        score += 0.2
    if str(metadata.get("inspect_bead_found") or "").lower() == "false":
        score -= 0.3
    return score


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("bead_id") or row.get("title") or row.get("snippet") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _extract_result_row(*, root: str, rank: int, row: dict[str, Any]) -> dict[str, Any]:
    bead_id_source = ""
    bead_id = ""
    for key in ("bead_id", "id", "result_id", "source_id"):
        value = str(row.get(key) or "").strip()
        if value:
            bead_id = value
            bead_id_source = key
            break
    bead_raw = inspect_bead(root=root, bead_id=bead_id) if bead_id and inspect_bead is not None else None
    bead = dict(bead_raw or {})
    metadata = dict(bead.get("metadata") or {})
    metadata_source = "bead.metadata" if metadata else "none"
    raw_dia_ids = []
    dia_id_source = ""
    for key in ("dia_ids", "dia_id", "locomo_dia_ids", "locomo_dia_id"):
        value = metadata.get(key)
        if isinstance(value, list):
            raw_dia_ids.extend([str(x).strip() for x in value if str(x).strip()])
            if raw_dia_ids and not dia_id_source:
                dia_id_source = f"metadata.{key}"
        elif str(value or "").strip():
            raw_dia_ids.append(str(value).strip())
            if raw_dia_ids and not dia_id_source:
                dia_id_source = f"metadata.{key}"
    if not raw_dia_ids:
        locomo_dia_id = str(metadata.get("locomo_dia_id") or "").strip()
        if locomo_dia_id:
            raw_dia_ids.append(locomo_dia_id)
            dia_id_source = dia_id_source or "metadata.locomo_dia_id"
    if not raw_dia_ids:
        raw_dia_ids.extend([str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip()])
        if raw_dia_ids:
            dia_id_source = "row.dia_ids"
    if not raw_dia_ids:
        raw_dia_ids.extend([str(x).strip() for x in (bead.get("source_turn_ids") or []) if str(x).strip().startswith("D")])
        if raw_dia_ids:
            dia_id_source = "bead.source_turn_ids"
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
        "projection": {
            "bead_id_source": bead_id_source or "missing",
            "metadata_source": metadata_source,
            "dia_id_source": dia_id_source or "missing",
            "inspect_bead_found": bool(bead),
            "row_keys": sorted(str(k) for k in row.keys()),
            "metadata_keys": sorted(str(k) for k in metadata.keys()),
            "source_turn_ids": [str(x).strip() for x in (bead.get("source_turn_ids") or []) if str(x).strip()],
        },
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

    req = {
        "query": str(qa.get("question") or "").strip(),
        "intent": _intent_for_question(str(qa.get("question") or "")),
        "k": max(1, int(retrieval_k or 8)),
        "facets": _locomo_facets(sample_id=sample_id, question=str(qa.get("question") or "")),
        "constraints": {
            "sample_id": sample_id,
            "session_id": f"locomo:{sample_id}",
        },
    }
    try:
        result = memory_tools.execute(req, root=root, explain=False)
        raw_results = list(result.get("results") or [])
        retrieved = [_extract_result_row(root=root, rank=idx, row=dict(row or {})) for idx, row in enumerate(raw_results, start=1)]
        trace_meta = {"used": False, "reason": "trace_disabled", "anchor_ids": [], "chains": [], "grounding": {}}
        trace_warning = None
        try:
            anchor_ids = [str((row or {}).get("bead_id") or "").strip() for row in raw_results if str((row or {}).get("bead_id") or "").strip()]
            if anchor_ids and trace_request is not None:
                trace = trace_request(
                    root=root,
                    query=str(qa.get("question") or "").strip(),
                    k=max(3, min(int(retrieval_k or 8), len(anchor_ids))),
                    anchor_ids=anchor_ids[: max(3, int(retrieval_k or 8))],
                )
                trace_rows = [
                    _extract_result_row(root=root, rank=len(retrieved) + idx, row=dict(row or {}))
                    for idx, row in enumerate(list((trace or {}).get("results") or []), start=1)
                ]
                if trace_rows:
                    retrieved = _dedupe_rows(retrieved + trace_rows)
                trace_meta = {
                    "used": True,
                    "reason": "trace_ok",
                    "anchor_ids": anchor_ids[: max(3, int(retrieval_k or 8))],
                    "chains": list((trace or {}).get("chains") or []),
                    "grounding": dict((trace or {}).get("grounding") or {}),
                }
            else:
                trace_meta = {"used": False, "reason": "no_anchor_ids", "anchor_ids": [], "chains": [], "grounding": {}}
        except TypeError as exc:
            trace_warning = f"trace_request_type_error:{exc}"
            trace_meta = {"used": False, "reason": "trace_type_error", "anchor_ids": [], "chains": [], "grounding": {}}
        except Exception as exc:
            trace_warning = f"trace_request_failed:{exc}"
            trace_meta = {"used": False, "reason": "trace_failed", "anchor_ids": [], "chains": [], "grounding": {}}
        for row in retrieved:
            row["locomo_score"] = _locomo_score(row, sample_id=sample_id, question=str(qa.get("question") or ""))
        retrieved.sort(key=lambda r: float(r.get("locomo_score") or 0.0), reverse=True)
        for idx, row in enumerate(retrieved, start=1):
            row["rank"] = idx
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
        gold_evidence = [str(x).strip() for x in (qa.get("evidence") or []) if str(x).strip()]
        gold_evidence_set = set(gold_evidence)
        matched_gold_dia_ids = sorted({str(x).strip() for r in retrieved for x in (r.get("dia_ids") or []) if str(x).strip() in gold_evidence_set})
        top_hits = {k: bool({str(x).strip() for row in retrieved[:k] for x in (row.get("dia_ids") or []) if str(x).strip()} & gold_evidence_set) for k in [1, 3, 5, 10]}
        projection_counts = {
            "no_bead_id": sum(1 for r in retrieved if str(((r.get("projection") or {}).get("bead_id_source") or "")) == "missing"),
            "bead_not_found": sum(1 for r in retrieved if not bool((r.get("projection") or {}).get("inspect_bead_found"))),
            "metadata_missing": sum(1 for r in retrieved if str(((r.get("projection") or {}).get("metadata_source") or "")) == "none"),
            "no_dia_ids_in_metadata": sum(1 for r in retrieved if str(((r.get("projection") or {}).get("dia_id_source") or "")) == "missing"),
        }
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
            "warnings": list(result.get("warnings") or []) + ([trace_warning] if trace_warning else []),
            "backend": str(result.get("backend") or "unknown"),
            "raw_result_count": len(raw_results),
            "trace": trace_meta,
            "diagnostics": {
                "raw_result_count": len(raw_results),
                "raw_result_keys": sorted({str(k) for row in raw_results[:1] for k in dict(row or {}).keys()}),
                "raw_top_ids": [str((row or {}).get("bead_id") or (row or {}).get("id") or (row or {}).get("result_id") or (row or {}).get("source_id") or "") for row in raw_results[:5]],
                "retrieved_count": len(retrieved),
                "projection_drops": projection_counts,
                "projected_dia_ids_top5": [list((row or {}).get("dia_ids") or []) for row in retrieved[:5]],
                "gold_evidence": gold_evidence,
                "gold_in_top_k": top_hits,
                "gold_in_any_retrieved": bool(matched_gold_dia_ids),
                "matched_gold_dia_ids": matched_gold_dia_ids,
                "answerer_used_dia_ids": list(answer.get("used_dia_ids") or []),
                "answerer_unsupported": bool(answer.get("unsupported")),
            },
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
    qa_rows = qa_cases or []
    total = len(qa_rows)
    for idx, case in enumerate(qa_rows, start=1):
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
