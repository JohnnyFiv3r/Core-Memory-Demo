from __future__ import annotations

import json
import platform
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.benchmarks.locomo_ingest import ingest_locomo_turns
from app.benchmarks.locomo_loader import LocomoLoaderError, load_locomo_dataset
from app.benchmarks.locomo_scoring import aggregate_case_scores
from app.core.config import settings


def _normalize_qa_per_category(raw: dict[int | str, int] | None) -> dict[int, int]:
    out: dict[int, int] = {}
    for key, value in dict(raw or {}).items():
        try:
            cat = int(key)
            limit = int(value)
        except Exception:
            continue
        if cat > 0 and limit > 0:
            out[cat] = limit
    return out


def build_locomo_suite_metadata(*, suite: str, sample_limit: int | None = None, qa_limit: int | None = None, sample_ids: list[str] | None = None, category_filter: list[int] | None = None, qa_per_category: dict[int | str, int] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    samples, meta = load_locomo_dataset()
    selected = list(samples)

    wanted_ids = [str(x).strip() for x in (sample_ids or []) if str(x).strip()]
    if wanted_ids:
        wanted = set(wanted_ids)
        selected = [row for row in selected if str(row.get("sample_id") or "") in wanted]

    if isinstance(sample_limit, int) and sample_limit > 0:
        selected = selected[: sample_limit]

    category_caps = _normalize_qa_per_category(qa_per_category)
    category_set = {int(x) for x in (category_filter or [])}
    if category_caps:
        category_set = set(category_set or category_caps.keys())
    selected_cases: list[dict[str, Any]] = []
    for sample in selected:
        sample_id = str(sample.get("sample_id") or "")
        for qa in list(sample.get("qa") or []):
            if category_set and int(qa.get("category") or 0) not in category_set:
                continue
            selected_cases.append(
                {
                    "qa_id": str(qa.get("qa_id") or ""),
                    "sample_id": sample_id,
                    "category": int(qa.get("category") or 0),
                    "question": str(qa.get("question") or "").strip(),
                    "answer": str(qa.get("answer") or "").strip(),
                    "evidence": list(qa.get("evidence") or []),
                }
            )

    available_by_category: dict[int, int] = {}
    for row in selected_cases:
        cat = int(row.get("category") or 0)
        available_by_category[cat] = available_by_category.get(cat, 0) + 1

    selected_by_category: dict[int, int] = {}
    if category_caps:
        selected_cases_stratified: list[dict[str, Any]] = []
        selected_sample_order = [str(sample.get("sample_id") or "") for sample in selected]
        by_category_sample: dict[int, dict[str, list[dict[str, Any]]]] = {}
        for row in selected_cases:
            cat = int(row.get("category") or 0)
            if cat not in category_caps:
                continue
            sid = str(row.get("sample_id") or "")
            by_category_sample.setdefault(cat, {}).setdefault(sid, []).append(row)

        used_by_category: dict[int, int] = {}
        capped_categories = sorted(set(category_caps) & set(category_set or category_caps.keys()))
        for cat in capped_categories:
            cap = int(category_caps.get(cat) or 0)
            if cap <= 0:
                continue
            per_sample = by_category_sample.get(cat) or {}
            used = 0
            # Round-robin across samples instead of taking the first N rows in
            # dataset order. The previous dataset-order cap could satisfy an
            # entire category from conv-26 alone, producing a nominal 50-QA run
            # that was really a single-conversation stress test.
            while used < cap:
                added = False
                offset = used // max(1, len(selected_sample_order))
                for sample_id in selected_sample_order:
                    rows = per_sample.get(sample_id) or []
                    if offset >= len(rows):
                        continue
                    selected_cases_stratified.append(rows[offset])
                    used += 1
                    added = True
                    if used >= cap:
                        break
                if not added:
                    break
            used_by_category[cat] = used
        selected_cases = selected_cases_stratified
        selected_by_category = dict(sorted(used_by_category.items()))
    elif isinstance(qa_limit, int) and qa_limit > 0:
        selected_cases = selected_cases[: qa_limit]

    if not selected_by_category:
        for row in selected_cases:
            cat = int(row.get("category") or 0)
            selected_by_category[cat] = selected_by_category.get(cat, 0) + 1
        selected_by_category = dict(sorted(selected_by_category.items()))

    dataset_meta = meta.to_dict()
    dataset_meta.update(
        {
            "selected_samples": len(selected),
            "selected_qa_cases": len(selected_cases),
            "selected_sample_ids": [str(s.get("sample_id") or "") for s in selected],
            "selected_qa_by_sample": {
                sample_id: sum(1 for row in selected_cases if str(row.get("sample_id") or "") == sample_id)
                for sample_id in [str(s.get("sample_id") or "") for s in selected]
            },
            "category_filter": sorted(category_set),
            "qa_limit": qa_limit,
            "qa_per_category": {str(k): int(v) for k, v in sorted(category_caps.items())},
            "available_qa_by_category": {str(k): int(v) for k, v in sorted(available_by_category.items())},
            "selected_qa_by_category": {str(k): int(v) for k, v in sorted(selected_by_category.items())},
            "selection_strategy": "stratified_by_category" if category_caps else "dataset_order",
            "python_version": platform.python_version(),
        }
    )

    return {
        "suite": suite,
        "source": "locomo_dataset",
        "dataset": dataset_meta,
    }, selected_cases, selected


def ingest_locomo_samples(*, base_root: str, samples: list[dict[str, Any]], ingestion_mode: str = "turns", ingest_path_override: str | None = None) -> dict[str, Any]:
    rows = []
    total_turns = 0
    ingested_turns = 0
    skipped_existing = 0
    claims_written = 0
    ingest_path = str(ingest_path_override or settings.locomo_ingest_path or 'bead_direct').strip().lower() or 'bead_direct'
    replay_mode = str(settings.locomo_replay_mode or 'transcript_only').strip().lower() or 'transcript_only'
    flush_policy = str(settings.locomo_replay_flush_policy or 'per_session').strip().lower() or 'per_session'
    for sample in samples:
        if ingest_path == 'canonical_replay':
            from app.benchmarks.locomo_replay import replay_locomo_sample
            out = replay_locomo_sample(root=base_root, sample=sample, mode=replay_mode, flush_policy=flush_policy)
            out["claims_written"] = 0
        else:
            out = ingest_locomo_turns(root=base_root, sample=sample, mode=ingestion_mode)
        rows.append(out)
        total_turns += int(out.get("turns_total") or 0)
        ingested_turns += int(out.get("ingested_count") or 0)
        skipped_existing += int(out.get("skipped_existing_count") or 0)
        claims_written += int(out.get("claims_written") or 0)
    return {
        "mode": ingestion_mode,
        "ingest_path": ingest_path,
        "replay_mode": replay_mode if ingest_path == 'canonical_replay' else '',
        "flush_policy": flush_policy if ingest_path == 'canonical_replay' else '',
        "samples": len(samples),
        "turns_total": total_turns,
        "ingested_turns": ingested_turns,
        "skipped_existing_count": skipped_existing,
        "claims_written": claims_written,
        "rows": rows,
    }


def build_locomo_comparison(*, left_label: str, left_report: dict[str, Any], right_label: str, right_report: dict[str, Any]) -> dict[str, Any]:
    left_cases = list((left_report or {}).get('cases') or [])
    right_cases = list((right_report or {}).get('cases') or [])
    left_scores = aggregate_case_scores(left_cases)
    right_scores = aggregate_case_scores(right_cases)

    def _metrics(scores: dict[str, Any]) -> dict[str, float]:
        overall = dict((scores or {}).get('overall') or {})
        return {
            'answer_f1_mean': float(overall.get('answer_f1_mean') or 0.0),
            'evidence_recall@5': float(overall.get('evidence_recall@5') or 0.0),
            'hit_any': float(overall.get('hit_any') or 0.0),
            'mrr': float(overall.get('mrr') or 0.0),
        }

    def _by_category(scores: dict[str, Any]) -> dict[str, dict[str, float]]:
        return {str(k): dict(v or {}) for k, v in dict((scores or {}).get('by_category') or {}).items()}

    left_metrics = _metrics(left_scores)
    right_metrics = _metrics(right_scores)
    categories = sorted(set(_by_category(left_scores).keys()) | set(_by_category(right_scores).keys()), key=lambda x: int(x))
    by_category = {}
    left_by_category = _by_category(left_scores)
    right_by_category = _by_category(right_scores)
    for cat in categories:
        l = left_by_category.get(cat) or {}
        r = right_by_category.get(cat) or {}
        by_category[cat] = {
            left_label: {
                'qa_count': int(l.get('qa_count') or 0),
                'answer_f1_mean': float(l.get('answer_f1_mean') or 0.0),
                'evidence_recall@5': float(l.get('evidence_recall@5') or 0.0),
                'hit_any': float(l.get('hit_any') or 0.0),
            },
            right_label: {
                'qa_count': int(r.get('qa_count') or 0),
                'answer_f1_mean': float(r.get('answer_f1_mean') or 0.0),
                'evidence_recall@5': float(r.get('evidence_recall@5') or 0.0),
                'hit_any': float(r.get('hit_any') or 0.0),
            },
            'delta': {
                'answer_f1_mean': float(r.get('answer_f1_mean') or 0.0) - float(l.get('answer_f1_mean') or 0.0),
                'evidence_recall@5': float(r.get('evidence_recall@5') or 0.0) - float(l.get('evidence_recall@5') or 0.0),
                'hit_any': float(r.get('hit_any') or 0.0) - float(l.get('hit_any') or 0.0),
            },
        }
    return {
        'ok': True,
        'left': left_label,
        'right': right_label,
        'overall': {
            left_label: left_metrics,
            right_label: right_metrics,
            'delta': {key: right_metrics[key] - left_metrics[key] for key in left_metrics.keys()},
        },
        'by_category': by_category,
    }


def write_locomo_run_artifacts(*, run_id: str, summary: dict[str, Any], report: dict[str, Any], config: dict[str, Any], dataset_meta: dict[str, Any], ingestion_meta: dict[str, Any] | None = None, comparison: dict[str, Any] | None = None, comparison_error: dict[str, Any] | None = None, cases: list[dict[str, Any]] | None = None) -> dict[str, str]:
    root = Path(settings.core_memory_demo_artifacts_root) / "locomo-runs" / run_id
    root.mkdir(parents=True, exist_ok=True)

    summary_path = root / "summary.json"
    report_path = root / "report.json"
    config_path = root / "config.json"
    dataset_meta_path = root / "dataset_meta.json"
    ingestion_meta_path = root / "ingestion_meta.json"
    cases_path = root / "cases.jsonl"
    failures_path = root / "failures.jsonl"
    comparison_path = root / "comparison.json"
    comparison_error_path = root / "comparison_error.json"

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    dataset_meta_path.write_text(json.dumps(dataset_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    ingestion_meta_path.write_text(json.dumps(dict(ingestion_meta or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    if comparison is not None:
        comparison_path.write_text(json.dumps(dict(comparison or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    if comparison_error is not None:
        comparison_error_path.write_text(json.dumps(dict(comparison_error or {}), ensure_ascii=False, indent=2), encoding="utf-8")

    cases_rows = list(cases if cases is not None else (report.get("cases") or []))
    with cases_path.open("w", encoding="utf-8") as fh:
        for row in cases_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with failures_path.open("w", encoding="utf-8") as fh:
        for row in cases_rows:
            if row.get("status") == "error":
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "root": str(root),
        "summary": str(summary_path),
        "report": str(report_path),
        "config": str(config_path),
        "dataset_meta": str(dataset_meta_path),
        "ingestion_meta": str(ingestion_meta_path),
        "cases": str(cases_path),
        "failures": str(failures_path),
        "comparison": str(comparison_path) if comparison is not None else "",
        "comparison_error": str(comparison_error_path) if comparison_error is not None else "",
    }


def make_locomo_missing_dataset_response(*, suite: str, root_mode: str, semantic_mode_name: str, error: Exception) -> dict[str, Any]:
    run_id = f"bench-{uuid.uuid4().hex[:10]}"
    msg = str(error)
    return {
        "ok": False,
        "suite": suite,
        "summary": {
            "run_id": run_id,
            "suite": suite,
            "root_mode": root_mode,
            "semantic_mode": semantic_mode_name,
            "warnings": ["locomo_dataset_missing"],
            "error": msg,
        },
        "report": {
            "config": {
                "suite": suite,
                "root_mode": root_mode,
                "semantic_mode": semantic_mode_name,
            },
            "dataset": {
                "status": "missing",
                "error": msg,
            },
            "cases": [],
        },
        "error": msg,
    }
