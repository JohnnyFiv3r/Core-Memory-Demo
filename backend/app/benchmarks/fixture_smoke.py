from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _locomo_benchmark_dirs() -> tuple[Path, Path]:
    env_fx = str(os.getenv("CORE_MEMORY_LOCOMO_FIXTURES_DIR") or "").strip()
    env_gold = str(os.getenv("CORE_MEMORY_LOCOMO_GOLD_DIR") or "").strip()
    if env_fx and env_gold:
        return Path(env_fx), Path(env_gold)

    demo_base = Path(__file__).resolve().parents[2] / "benchmarks" / "locomo_like"
    demo_fx = demo_base / "fixtures"
    demo_gold = demo_base / "gold"
    if demo_fx.exists() and demo_gold.exists():
        return demo_fx, demo_gold

    workspace_core_memory = Path(__file__).resolve().parents[4] / "Core-Memory" / "benchmarks" / "locomo_like"
    return workspace_core_memory / "fixtures", workspace_core_memory / "gold"


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def legacy_smoke_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "b1",
            "query": "What database did we choose?",
            "intent": "remember",
            "k": 8,
            "expected_answer_class": "answer_partial",
            "setup": {},
            "bucket_labels": ["smoke"],
        },
        {
            "case_id": "b2",
            "query": "What lesson did we learn about infra choices?",
            "intent": "remember",
            "k": 8,
            "expected_answer_class": "answer_partial",
            "setup": {},
            "bucket_labels": ["smoke"],
        },
        {
            "case_id": "b3",
            "query": "Why did we pick FastAPI?",
            "intent": "causal",
            "k": 8,
            "expected_answer_class": "answer_partial",
            "setup": {},
            "bucket_labels": ["smoke"],
        },
    ]


def load_fixture_smoke_cases(*, subset: str = "local") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fixtures_dir, gold_dir = _locomo_benchmark_dirs()
    if not fixtures_dir.exists() or not gold_dir.exists():
        rows = legacy_smoke_cases()
        return rows, {
            "suite": "fixture_smoke",
            "source": "legacy_smoke_fallback",
            "fixtures_dir": str(fixtures_dir),
            "gold_dir": str(gold_dir),
            "available_cases": int(len(rows)),
            "selected_cases": int(len(rows)),
            "full_subset_available": False,
            "warning": "fixture_dirs_missing",
        }

    all_fixture_paths = sorted(fixtures_dir.glob("*.jsonl"))
    fixture_paths = list(all_fixture_paths)
    if str(subset or "local").strip().lower() == "local":
        local_path = fixtures_dir / "local_subset.jsonl"
        if local_path.exists():
            fixture_paths = [local_path]

    gold_map: dict[str, dict[str, Any]] = {}
    for g in sorted(gold_dir.glob("*.json")):
        try:
            payload = json.loads(g.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = payload.get("cases") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            gid = str(row.get("id") or "").strip()
            if gid:
                gold_map[gid] = row

    out: list[dict[str, Any]] = []
    for fp in fixture_paths:
        for row in _read_jsonl_rows(fp):
            cid = str(row.get("id") or "").strip()
            if not cid:
                continue
            gold_id = str(row.get("gold_id") or cid).strip() or cid
            g = dict(gold_map.get(gold_id) or {})
            out.append(
                {
                    "case_id": cid,
                    "query": str(row.get("query") or "").strip(),
                    "intent": str(row.get("intent") or "remember").strip() or "remember",
                    "k": max(1, int(row.get("k") or 5)),
                    "setup": dict(row.get("setup") or {}),
                    "bucket_labels": [str(x) for x in (row.get("bucket_labels") or []) if str(x)],
                    "expected_answer_class": str(g.get("expected_answer_class") or "answer_partial").strip() or "answer_partial",
                    "expected_slot": str(g.get("expected_slot") or "").strip(),
                    "expected_source_surface": str(g.get("expected_source_surface") or "").strip(),
                }
            )

    if not out:
        rows = legacy_smoke_cases()
        return rows, {
            "suite": "fixture_smoke",
            "source": "legacy_smoke_fallback",
            "fixtures_dir": str(fixtures_dir),
            "gold_dir": str(gold_dir),
            "available_cases": int(len(rows)),
            "selected_cases": int(len(rows)),
            "full_subset_available": False,
            "warning": "fixture_rows_empty",
        }

    out.sort(key=lambda x: str(x.get("case_id") or ""))
    local_count = len(_read_jsonl_rows(fixtures_dir / "local_subset.jsonl")) if (fixtures_dir / "local_subset.jsonl").exists() else 0
    available_cases = sum(len(_read_jsonl_rows(p)) for p in all_fixture_paths)
    full_subset_available = bool(available_cases > max(local_count, 0))

    return out, {
        "suite": "fixture_smoke",
        "source": "fixture_pack",
        "fixtures_dir": str(fixtures_dir),
        "gold_dir": str(gold_dir),
        "fixture_files": [p.name for p in all_fixture_paths],
        "available_cases": int(available_cases),
        "selected_cases": int(len(out)),
        "local_subset_cases": int(local_count),
        "full_subset_available": bool(full_subset_available),
    }
