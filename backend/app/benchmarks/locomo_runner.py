from __future__ import annotations

import gc
import re
import threading
from pathlib import Path


class BenchmarkCancelledError(RuntimeError):
    pass
from typing import Any

from app.benchmarks.locomo_answer import generate_locomo_answer
from app.benchmarks.locomo_scoring import compute_evidence_recall, score_answer

try:
    from core_memory.integrations.api import hydrate_bead_sources, inspect_bead
except Exception:  # pragma: no cover
    hydrate_bead_sources = None  # type: ignore
    inspect_bead = None  # type: ignore
try:
    from core_memory.retrieval.normalize import classify_intent
except Exception:  # pragma: no cover
    classify_intent = None  # type: ignore
try:
    from core_memory.retrieval.tools import memory as memory_tools
except Exception:  # pragma: no cover
    memory_tools = None  # type: ignore
try:
    from core_memory.retrieval.contracts import recall_result_from_memory_execute
except Exception:  # pragma: no cover
    recall_result_from_memory_execute = None  # type: ignore

try:
    from core_memory.retrieval.trace import trace_request
except Exception:  # pragma: no cover
    try:
        from core_memory.retrieval.pipeline.canonical import trace_request
    except Exception:  # pragma: no cover
        try:
            from core_memory.retrieval.pipeline import memory_trace as trace_request
        except Exception:  # pragma: no cover
            trace_request = None  # type: ignore
try:
    from core_memory.runtime.turn_archive import find_turn_record
except Exception:  # pragma: no cover
    find_turn_record = None  # type: ignore
try:
    from core_memory.retrieval.agent import recall as core_recall
except Exception:  # pragma: no cover
    core_recall = None  # type: ignore


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
    """Build metadata-aware retrieval hints for LoCoMo QA.

    Keep sample/session anchoring in metadata filters instead of hard lexical
    terms.  The question text itself already drives semantic search; making every
    entity/token a required term can filter out the relevant turn before reranking.
    """
    q = str(question or "")
    sample = str(sample_id or "").strip()
    metadata: dict[str, Any] = {}
    if sample:
        metadata["sample_id"] = sample
        metadata["session_id"] = f"locomo:{sample}"

    must_terms: list[str] = []
    # Session references are metadata on LoCoMo turns, so they remain safe as
    # key=value terms once the engine includes metadata in typed filtering.
    for match in re.finditer(r"\bsession\s+(\d+)\b", q, flags=re.IGNORECASE):
        value = str(match.group(1))
        metadata["session_index"] = value
        must_terms.append(f"session_index={value}")
    # Exact dates are unusually high-signal and can appear in either turn text or
    # session metadata.
    for match in re.finditer(r"\b\d{1,2}\s+[A-Z][a-z]+\s+\d{4}\b", q):
        must_terms.append(match.group(0))

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
        "metadata": metadata,
        "must_terms": deduped[:8],
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
        dia_key = ",".join(str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip())
        key = str(row.get("bead_id") or dia_key or row.get("title") or row.get("snippet") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _turn_text_from_record(rec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    md = dict((rec or {}).get("metadata") or {})
    text = str(md.get("locomo_display_text") or rec.get("assistant_final") or "").strip()
    speaker = str(md.get("locomo_speaker") or "").strip()
    if text and speaker and not text.lower().startswith(f"{speaker.lower()}:"):
        text = f"{speaker}: {text}"
    if str(md.get("locomo_session_date_time") or "").strip():
        text = f"Session date: {str(md.get('locomo_session_date_time') or '').strip()}\n\n{text}".strip()
    if str(md.get("blip_caption") or "").strip():
        text = f"{text}\n\nImage caption: {str(md.get('blip_caption') or '').strip()}".strip()
    return text, md


def _hydrate_locomo_rows(*, root: str, rows: list[dict[str, Any]], sample_id: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Force transcript hydration for retrieved LoCoMo rows.

    Search/trace rows can be compressed bead summaries.  This pass uses bead
    provenance and LoCoMo dia ids to fetch authoritative archived turn records
    when available, then replaces row text/snippet with full transcript text.
    """
    if not rows:
        return rows, {"used": False, "reason": "no_rows", "hydrated_rows": 0, "requested_turn_ids": []}
    sample = str(sample_id or "").strip()
    bead_ids: list[str] = []
    turn_ids: list[str] = []
    for row in rows[: max(1, int(limit or len(rows)))]:
        bid = str(row.get("bead_id") or "").strip()
        if bid and not bid.startswith("turn:"):
            bead_ids.append(bid)
        for tid in ((row.get("projection") or {}).get("source_turn_ids") or []):
            tid_s = str(tid or "").strip()
            if tid_s:
                turn_ids.append(tid_s)
        for dia in (row.get("dia_ids") or []):
            dia_s = str(dia or "").strip()
            if not dia_s:
                continue
            turn_ids.append(dia_s)
            if sample:
                turn_ids.append(f"locomo:{sample}:{dia_s}")
    # Preserve order while deduping.
    bead_ids = list(dict.fromkeys(bead_ids))
    turn_ids = list(dict.fromkeys(turn_ids))
    hydration: dict[str, Any] = {"used": False, "reason": "hydration_unavailable", "hydrated_rows": 0, "requested_turn_ids": turn_ids[:50]}
    hydrated_by_dia: dict[str, tuple[str, dict[str, Any]]] = {}

    def _capture_turn(rec: dict[str, Any] | None) -> bool:
        if not rec:
            return False
        text, md = _turn_text_from_record(dict(rec or {}))
        dia = str(md.get("locomo_dia_id") or "").strip()
        dias = [str(x).strip() for x in (md.get("locomo_dia_ids") or []) if str(x).strip()]
        if dia and dia not in dias:
            dias.append(dia)
        captured = False
        for did in dias:
            if text:
                hydrated_by_dia[did] = (text, md)
                captured = True
        return captured

    direct_records = 0
    if find_turn_record is not None and turn_ids:
        session_id = f"locomo:{sample}" if sample else None
        for tid in turn_ids[: max(1, int(limit or 10)) * 3]:
            rec = None
            try:
                rec = find_turn_record(root=Path(root), turn_id=tid, session_id=session_id)
                if rec is None:
                    rec = find_turn_record(root=Path(root), turn_id=tid, session_id=None)
            except Exception:
                rec = None
            if _capture_turn(rec):
                direct_records += 1

    if hydrate_bead_sources is not None and (bead_ids or turn_ids):
        try:
            h = hydrate_bead_sources(root=root, bead_ids=bead_ids[: max(1, int(limit or 10))], turn_ids=turn_ids[: max(1, int(limit or 10)) * 3], include_tools=False, before=0, after=0)
            for entry in list((h or {}).get("hydrated") or []):
                _capture_turn(dict((entry or {}).get("turn") or {}))
            hydration = {
                "used": True,
                "reason": "ok" if hydrated_by_dia else str((h or {}).get("reason") or "no_matching_turn_records"),
                "direct_turn_records": direct_records,
                "hydrated_turns": len(list((h or {}).get("hydrated") or [])) + direct_records,
                "hydrated_rows": 0,
                "requested_bead_ids": bead_ids[:50],
                "requested_turn_ids": turn_ids[:50],
            }
        except Exception as exc:
            hydration = {"used": bool(direct_records), "reason": "ok" if hydrated_by_dia else f"hydrate_failed:{exc}", "direct_turn_records": direct_records, "hydrated_rows": 0, "requested_turn_ids": turn_ids[:50]}
    elif direct_records:
        hydration = {"used": True, "reason": "ok", "direct_turn_records": direct_records, "hydrated_turns": direct_records, "hydrated_rows": 0, "requested_turn_ids": turn_ids[:50]}

    out: list[dict[str, Any]] = []
    hydrated_rows = 0
    for row in rows:
        item = dict(row or {})
        matched: tuple[str, dict[str, Any]] | None = None
        for dia in [str(x).strip() for x in (item.get("dia_ids") or []) if str(x).strip()]:
            if dia in hydrated_by_dia:
                matched = hydrated_by_dia[dia]
                break
        if matched:
            text, md = matched
            item["text"] = text
            item["snippet"] = text
            item["speaker"] = str(md.get("locomo_speaker") or item.get("speaker") or "").strip()
            item["session_date_time"] = str(md.get("locomo_session_date_time") or item.get("session_date_time") or "").strip()
            item["hydrated"] = True
            item["hydration_source"] = "turn_archive"
            hydrated_rows += 1
        else:
            item["hydrated"] = False
            item["hydration_source"] = "bead_or_row_text"
        out.append(item)
    hydration["hydrated_rows"] = hydrated_rows
    return out, hydration


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
    source_turn_ids = [str(x).strip() for x in (bead.get("source_turn_ids") or []) if str(x).strip()]
    if not raw_dia_ids:
        for source_turn_id in source_turn_ids:
            if source_turn_id.startswith("locomo:"):
                parts = source_turn_id.split(":", 2)
                if len(parts) == 3 and parts[2]:
                    raw_dia_ids.append(parts[2])
            elif source_turn_id.startswith("D"):
                raw_dia_ids.append(source_turn_id)
        if raw_dia_ids:
            dia_id_source = "bead.source_turn_ids"
    dia_ids = sorted(set(x for x in raw_dia_ids if x))
    sample_from_source_turn = ""
    for source_turn_id in source_turn_ids:
        if source_turn_id.startswith("locomo:"):
            parts = source_turn_id.split(":", 2)
            if len(parts) == 3 and parts[1]:
                sample_from_source_turn = parts[1]
                break
    return {
        "rank": rank,
        "bead_id": bead_id,
        "title": str(row.get("title") or bead.get("title") or "").strip(),
        "snippet": str(row.get("snippet") or "").strip(),
        "score": float(row.get("score") or 0.0),
        "source_surface": str(row.get("source_surface") or "").strip(),
        "anchor_reason": str(row.get("anchor_reason") or "").strip(),
        "claim_id": str(row.get("claim_id") or "").strip(),
        "claim_slot_key": str(row.get("claim_slot_key") or "").strip(),
        "claim_status": str(row.get("claim_status") or "").strip(),
        "claim_value": row.get("claim_value"),
        "dia_ids": dia_ids,
        "sample_id": str(metadata.get("sample_id") or metadata.get("locomo_sample_id") or sample_from_source_turn or "").strip(),
        "session_index": int(metadata.get("session_index") or metadata.get("locomo_session_index") or 0),
        "speaker": str(metadata.get("speaker") or metadata.get("locomo_speaker") or "").strip(),
        "session_date_time": str(metadata.get("session_date_time") or metadata.get("locomo_session_date_time") or "").strip(),
        "text": str(bead.get("detail") or "").strip(),
        "projection": {
            "bead_id_source": bead_id_source or "missing",
            "metadata_source": metadata_source,
            "dia_id_source": dia_id_source or "missing",
            "inspect_bead_found": bool(bead),
            "row_keys": sorted(str(k) for k in row.keys()),
            "metadata_keys": sorted(str(k) for k in metadata.keys()),
            "source_turn_ids": source_turn_ids,
        },
    }


def run_locomo_retrieval_case(*, root: str, sample_id: str, qa: dict[str, Any], retrieval_k: int = 8, evidence_recall_k: list[int] | None = None, answer_mode: str = "none", generator_model: str | None = None, retrieval_pipeline: str = "execute_trace") -> dict[str, Any]:
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
        },
    }
    try:
        result = memory_tools.execute(req, root=root, explain=False)
        recall_payload: dict[str, Any] = {}
        if recall_result_from_memory_execute is not None:
            recall_payload = recall_result_from_memory_execute(result, query=req["query"], effort="high", include_raw=False).to_dict()
        raw_results = list(result.get("results") or [])
        retrieved = [_extract_result_row(root=root, rank=idx, row=dict(row or {})) for idx, row in enumerate(raw_results, start=1)]
        pipeline_name = str(retrieval_pipeline or "execute_trace").strip().lower() or "execute_trace"
        # Phase 2: causal traversal anchored to semantic bead candidates.
        # Always runs as part of the single retrieval pass — results are merged
        # with the semantic set before hydration.
        trace_meta = {"used": False, "reason": "trace_unavailable", "anchor_ids": [], "chains": [], "grounding": {}}
        hydrate_meta: dict[str, Any] = {}
        trace_warning = None
        try:
            anchor_ids = [str((row or {}).get("bead_id") or "").strip() for row in raw_results if str((row or {}).get("bead_id") or "").strip()]
            if trace_request is not None:
                trace = trace_request(
                    root=root,
                    query=str(qa.get("question") or "").strip(),
                    k=max(int(retrieval_k or 8), 8),
                    anchor_ids=anchor_ids[: max(3, int(retrieval_k or 8))] if anchor_ids else None,
                    hydration={"max_beads": max(int(retrieval_k or 8), 8), "adjacent_before": 0, "adjacent_after": 0},
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
                    "result_count": len(list((trace or {}).get("results") or [])),
                    "result_ids": [str((r or {}).get("bead_id") or "").strip() for r in list((trace or {}).get("results") or [])[:20] if str((r or {}).get("bead_id") or "").strip()],
                    "chains": list((trace or {}).get("chains") or []),
                    "grounding": dict((trace or {}).get("grounding") or {}),
                    "diagnostics": dict((trace or {}).get("trace_diagnostics") or {}),
                }
            else:
                trace_meta = {"used": False, "reason": "trace_unavailable", "anchor_ids": [], "chains": [], "grounding": {}}
        except TypeError as exc:
            trace_warning = f"trace_request_type_error:{exc}"
            trace_meta = {"used": False, "reason": "trace_type_error", "anchor_ids": [], "chains": [], "grounding": {}}
        except Exception as exc:
            trace_warning = f"trace_request_failed:{exc}"
            trace_meta = {"used": False, "reason": "trace_failed", "anchor_ids": [], "chains": [], "grounding": {}}
        # Phase 3: source transcript lookup — hydrate bead candidates to full
        # archived turn text using turn refs identified in phases 1 and 2.
        retrieved, hydrate_meta = _hydrate_locomo_rows(root=root, rows=retrieved, sample_id=sample_id, limit=max(int(retrieval_k or 8), 8))
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
        answer = generate_locomo_answer(
            mode=answer_mode,
            root=root,
            sample_id=sample_id,
            qa=qa,
            retrieved_context=retrieved,
            generator_model=generator_model,
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
            "hydration": hydrate_meta,
            "retrieval_pipeline": pipeline_name,
            "recall_result": recall_payload,
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
                "hydration": hydrate_meta,
                "recall_tier_path": list(recall_payload.get("tier_path") or []),
                "recall_status": str(recall_payload.get("status") or ""),
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
            "used_dia_ids": [],
            "answer_f1": 0.0,
            "status": "error",
            "error": str(exc),
            "retrieved": [],
            "evidence_recall": compute_evidence_recall(gold_evidence=list(qa.get("evidence") or []), retrieved=[], ks=evidence_recall_k or [1, 3, 5, 8, 10]),
        }


def _slim_locomo_row(row: dict[str, Any], *, max_text_chars: int = 600) -> dict[str, Any]:
    text = str(row.get("text") or row.get("snippet") or "")
    projection = dict(row.get("projection") or {})
    return {
        "rank": int(row.get("rank") or 0),
        "bead_id": str(row.get("bead_id") or ""),
        "dia_ids": list(row.get("dia_ids") or []),
        "score": float(row.get("score") or 0.0),
        "locomo_score": float(row.get("locomo_score") or 0.0),
        "source_surface": str(row.get("source_surface") or ""),
        "text": text[:max_text_chars],
        "projection": {
            key: projection.get(key)
            for key in (
                "bead_id_source",
                "inspect_bead_found",
                "metadata_source",
                "dia_id_source",
            )
            if key in projection
        },
    }


def _slim_locomo_case_result(result: dict[str, Any], *, retrieved_limit: int = 10) -> dict[str, Any]:
    """Keep suite results bounded so 50-case benchmarks do not retain huge payloads."""
    row = dict(result or {})
    retrieved = list(row.get("retrieved") or [])
    row["retrieved"] = [_slim_locomo_row(dict(r or {})) for r in retrieved[: max(0, int(retrieved_limit))]]
    row["retrieved_omitted"] = max(0, len(retrieved) - len(row["retrieved"]))

    trace = dict(row.get("trace") or {})
    if trace:
        row["trace"] = {
            "used": bool(trace.get("used")),
            "reason": str(trace.get("reason") or ""),
            "anchor_ids": list(trace.get("anchor_ids") or [])[:10],
            "result_count": int(trace.get("result_count") or 0),
            "result_ids": list(trace.get("result_ids") or [])[:20],
        }
    return row


def run_locomo_retrieval_suite(*, root: str, qa_cases: list[dict[str, Any]], retrieval_k: int = 8, evidence_recall_k: list[int] | None = None, answer_mode: str = "none", generator_model: str | None = None, progress: Any | None = None, retrieval_pipeline: str = "execute_trace", cancel_event: threading.Event | None = None) -> dict[str, Any]:
    cases = []
    qa_rows = qa_cases or []
    total = len(qa_rows)
    for idx, case in enumerate(qa_rows, start=1):
        if cancel_event is not None and cancel_event.is_set():
            raise BenchmarkCancelledError("benchmark_cancelled_during_qa")
        result = run_locomo_retrieval_case(
            root=root,
            sample_id=str(case.get("sample_id") or ""),
            qa=dict(case or {}),
            retrieval_k=retrieval_k,
            evidence_recall_k=evidence_recall_k,
            answer_mode=answer_mode,
            generator_model=generator_model,
            retrieval_pipeline=retrieval_pipeline,
        )
        slim_result = _slim_locomo_case_result(result, retrieved_limit=max(int(retrieval_k or 8), 10))
        cases.append(slim_result)
        if callable(progress):
            try:
                progress(idx, total, dict(case or {}), dict(slim_result or {}))
            except Exception:
                pass
        if idx % 10 == 0:
            gc.collect()
    return {
        "cases": cases,
        "completed": sum(1 for c in cases if c.get("status") == "ok"),
        "failed": sum(1 for c in cases if c.get("status") == "error"),
        "total": total,
        "retrieval_pipeline": str(retrieval_pipeline or "execute_trace"),
    }
