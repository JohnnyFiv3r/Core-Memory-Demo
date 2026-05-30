from __future__ import annotations

import json
import string
from collections import Counter
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.benchmarks.contracts import BenchmarkConversation, BenchmarkQA

# Vendored measurement core from upstream Core-Memory benchmarks/locomo (PR #166).
# The benchmarks/ package is not part of the installed wheel (pyproject ships
# only core_memory*), so the methodology lives here and imports core_memory only
# indirectly. Used by the faithful lifecycle path; locomo_scoring.py stays the
# legacy runner's scorer.

OFFICIAL_CATEGORIES = frozenset({1, 2, 3, 4})
EXCLUDED_CATEGORIES = frozenset({5})

_ARTICLES = {"a", "an", "the"}
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def normalize_text(value: str) -> str:
    text = str(value or "").lower().translate(_PUNCT_TABLE)
    return " ".join(t for t in text.split() if t not in _ARTICLES)


def token_f1(prediction: str, answer: str) -> float:
    pred = normalize_text(prediction).split()
    gold = normalize_text(answer).split()
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    overlap = sum((Counter(pred) & Counter(gold)).values())
    if not overlap:
        return 0.0
    precision = overlap / len(pred)
    recall = overlap / len(gold)
    return (2 * precision * recall) / (precision + recall)


def multihop_f1(prediction: str, answer: str) -> float:
    # Category 1 gold answers are comma-separated; score the best-matching part.
    subs = [a.strip() for a in str(answer or "").split(",") if a.strip()]
    if not subs:
        return token_f1(prediction, answer)
    return max(token_f1(prediction, sub) for sub in subs)


def is_official_category(category: int | str | None) -> bool:
    cat = int(category) if str(category or "").isdigit() else 0
    return cat in OFFICIAL_CATEGORIES


def score_answer(*, category: int | str | None, prediction: str, answer: str) -> float:
    cat = int(category) if str(category or "").isdigit() else 0
    if cat == 1:
        return multihop_f1(prediction, answer)
    if cat == 3:
        # Canonical answer is the prefix before the first semicolon.
        return token_f1(prediction, str(answer or "").split(";", 1)[0].strip())
    if cat == 5:
        # Excluded from official scoring (broken keys); neutral, callers mark excluded.
        return 1.0
    return token_f1(prediction, answer)


def compute_evidence_recall(
    *,
    gold_evidence: list[str],
    retrieved: list[str],
    ks: list[int] | None = None,
) -> dict[str, Any]:
    """Recall over a rank-ordered list of dia_ids (position 0 == rank 1).

    No gold evidence -> vacuous 1.0, flagged so aggregation can drop the case
    from published-comparable numbers.
    """
    ks = ks or [1, 3, 5, 10]
    gold = {str(d).strip() for d in gold_evidence if str(d).strip()}
    if not gold:
        return {"vacuous": True, **{f"recall@{k}": 1.0 for k in ks}, "mrr": 1.0, "hit_any": True}

    hit_ranks = [rank for rank, dia in enumerate((str(d).strip() for d in retrieved), start=1) if dia in gold]
    out: dict[str, Any] = {"vacuous": False}
    for k in ks:
        out[f"recall@{k}"] = round(sum(1 for r in hit_ranks if r <= k) / len(gold), 4)
    out["mrr"] = round(1.0 / min(hit_ranks), 4) if hit_ranks else 0.0
    out["hit_any"] = bool(hit_ranks)
    return out


def aggregate_case_scores(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Headline aggregate; recall metrics exclude vacuous (no-gold) cases."""
    with_evidence = [c for c in cases if not (c.get("evidence_recall") or {}).get("vacuous", True)]

    def _mean(nums: list[float]) -> float | None:
        return round(sum(nums) / len(nums), 4) if nums else None

    by_category: dict[str, dict[str, list[Any]]] = {}
    for case in cases:
        cat = str(case.get("category") or "unknown")
        row = by_category.setdefault(cat, {"cases": [], "answer_f1": [], "recall@1": [], "recall@5": [], "mrr": []})
        row["cases"].append(case.get("qa_id"))
        if not case.get("excluded"):
            row["answer_f1"].append(float(case.get("answer_f1", 0.0)))
        ev = case.get("evidence_recall") or {}
        if not ev.get("vacuous"):
            row["recall@1"].append(float(ev.get("recall@1", 0.0)))
            row["recall@5"].append(float(ev.get("recall@5", 0.0)))
            row["mrr"].append(float(ev.get("mrr", 0.0)))

    return {
        "total_cases": len(cases),
        "cases_with_evidence": len(with_evidence),
        "cases_without_evidence_annotation": len(cases) - len(with_evidence),
        "overall": {
            "answer_f1_mean": _mean([float(c.get("answer_f1", 0.0)) for c in cases if not c.get("excluded")]),
            "recall@1_mean": _mean([float((c.get("evidence_recall") or {}).get("recall@1", 0.0)) for c in with_evidence]),
            "recall@5_mean": _mean([float((c.get("evidence_recall") or {}).get("recall@5", 0.0)) for c in with_evidence]),
            "mrr_mean": _mean([float((c.get("evidence_recall") or {}).get("mrr", 0.0)) for c in with_evidence]),
            "hit_any_rate": _mean([1.0 if (c.get("evidence_recall") or {}).get("hit_any") else 0.0 for c in with_evidence]),
        },
        "by_category": {
            cat: {
                "case_count": len(v["cases"]),
                "answer_f1_mean": _mean(v["answer_f1"]),
                "recall@1_mean": _mean(v["recall@1"]),
                "recall@5_mean": _mean(v["recall@5"]),
                "mrr_mean": _mean(v["mrr"]),
            }
            for cat, v in sorted(by_category.items())
        },
        "methodology_note": "primary_recall_metrics_exclude_vacuous_evidence_cases",
    }


def _read_bead_index(root: str | Path) -> dict[str, Any]:
    idx = Path(root) / ".beads" / "index.json"
    if not idx.exists():
        return {}
    try:
        return json.loads(idx.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_bead_to_dias(root: str | Path, conversation: BenchmarkConversation) -> dict[str, list[str]]:
    """Map every replay bead to the dia_ids it covers, read from the index.

    Bead IDs are non-deterministic across runs, so recall is scored in dia_id
    space. Each bead's source_turn_ids are resolved back to dia_ids via the
    conversation's own turn metadata. Built after compaction, so a compacted
    bead that absorbs several turns maps to all their dia_ids.
    """
    turn_to_dia: dict[str, str] = {}
    for turn in conversation.turns:
        dia = str((turn.metadata or {}).get("locomo_dia_id") or (turn.metadata or {}).get("dia_id") or "").strip()
        if dia:
            turn_to_dia[str(turn.turn_id)] = dia
            turn_to_dia[dia] = dia

    session_id = str(conversation.session_id or "")
    beads = (_read_bead_index(root).get("beads") or {})
    bead_to_dias: dict[str, list[str]] = {}
    for bead in beads.values():
        if not isinstance(bead, dict):
            continue
        bead_session = str(bead.get("session_id") or "")
        if session_id and bead_session and bead_session != session_id:
            continue
        bead_id = str(bead.get("id") or "")
        if not bead_id:
            continue
        dias: list[str] = []
        for src in bead.get("source_turn_ids") or []:
            dia = turn_to_dia.get(str(src).strip())
            if dia and dia not in dias:
                dias.append(dia)
        if dias:
            bead_to_dias[bead_id] = sorted(dias)
    return bead_to_dias


def ranked_dia_ids_for_rows(rows: list[dict[str, Any]], bead_to_dias: dict[str, list[str]] | None) -> list[str]:
    """Flatten ranked rows to a de-duplicated dia_id list, preferring a row's own
    dia_ids and falling back to the bead_id -> dia_ids map."""
    bead_to_dias = bead_to_dias or {}
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        dias = [str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip()]
        if not dias:
            dias = list(bead_to_dias.get(str((row or {}).get("bead_id") or "").strip(), []))
        for dia in dias:
            if dia not in seen:
                seen.add(dia)
                out.append(dia)
    return out


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """Interface a dataset adapter implements to plug into the measurement core."""

    @property
    def name(self) -> str: ...

    def load_conversations(self, **kwargs: Any) -> list[BenchmarkConversation]: ...

    def score_answer(self, *, qa: BenchmarkQA, prediction: str) -> float: ...

    def score_evidence(self, *, qa: BenchmarkQA, retrieved_ids: list[str], k: int) -> dict[str, Any]: ...
