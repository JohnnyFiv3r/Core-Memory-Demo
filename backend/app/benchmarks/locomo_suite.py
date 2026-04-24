from __future__ import annotations

import json
import platform
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.benchmarks.locomo_ingest import ingest_locomo_turns
from app.benchmarks.locomo_loader import LocomoLoaderError, load_locomo_dataset
from app.core.config import settings


def build_locomo_suite_metadata(*, suite: str, sample_limit: int | None = None, qa_limit: int | None = None, sample_ids: list[str] | None = None, category_filter: list[int] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    samples, meta = load_locomo_dataset()
    selected = list(samples)

    wanted_ids = [str(x).strip() for x in (sample_ids or []) if str(x).strip()]
    if wanted_ids:
        wanted = set(wanted_ids)
        selected = [row for row in selected if str(row.get("sample_id") or "") in wanted]

    if isinstance(sample_limit, int) and sample_limit > 0:
        selected = selected[: sample_limit]

    category_set = {int(x) for x in (category_filter or [])}
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

    if isinstance(qa_limit, int) and qa_limit > 0:
        selected_cases = selected_cases[: qa_limit]

    dataset_meta = meta.to_dict()
    dataset_meta.update(
        {
            "selected_samples": len(selected),
            "selected_qa_cases": len(selected_cases),
            "selected_sample_ids": [str(s.get("sample_id") or "") for s in selected],
            "category_filter": sorted(category_set),
            "python_version": platform.python_version(),
        }
    )

    return {
        "suite": suite,
        "source": "locomo_dataset",
        "dataset": dataset_meta,
    }, selected_cases, selected


def ingest_locomo_samples(*, base_root: str, samples: list[dict[str, Any]], ingestion_mode: str = "turns") -> dict[str, Any]:
    rows = []
    total_turns = 0
    ingested_turns = 0
    skipped_existing = 0
    for sample in samples:
        out = ingest_locomo_turns(root=base_root, sample=sample, mode=ingestion_mode)
        rows.append(out)
        total_turns += int(out.get("turns_total") or 0)
        ingested_turns += int(out.get("ingested_count") or 0)
        skipped_existing += int(out.get("skipped_existing_count") or 0)
    return {
        "mode": ingestion_mode,
        "samples": len(samples),
        "turns_total": total_turns,
        "ingested_turns": ingested_turns,
        "skipped_existing_count": skipped_existing,
        "rows": rows,
    }


def write_locomo_run_artifacts(*, run_id: str, summary: dict[str, Any], report: dict[str, Any], config: dict[str, Any], dataset_meta: dict[str, Any], ingestion_meta: dict[str, Any] | None = None) -> dict[str, str]:
    root = Path(settings.core_memory_demo_artifacts_root) / "locomo-runs" / run_id
    root.mkdir(parents=True, exist_ok=True)

    summary_path = root / "summary.json"
    report_path = root / "report.json"
    config_path = root / "config.json"
    dataset_meta_path = root / "dataset_meta.json"
    ingestion_meta_path = root / "ingestion_meta.json"
    cases_path = root / "cases.jsonl"
    failures_path = root / "failures.jsonl"

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    dataset_meta_path.write_text(json.dumps(dataset_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    ingestion_meta_path.write_text(json.dumps(dict(ingestion_meta or {}), ensure_ascii=False, indent=2), encoding="utf-8")

    cases = list(report.get("cases") or [])
    with cases_path.open("w", encoding="utf-8") as fh:
        for row in cases:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with failures_path.open("w", encoding="utf-8") as fh:
        for row in cases:
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
