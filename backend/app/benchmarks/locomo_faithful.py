"""Canonical (source-faithful) LoCoMo measurement layer.

This module ports the measurement core of the upstream Core Memory benchmark
harness (``benchmarks/locomo/`` in JohnnyFiv3r/Core-Memory, PR #166) into the
demo. That package is **not** shipped in the installed ``core-memory`` wheel
(``pyproject`` only includes ``core_memory*``), so the methodology is vendored
here rather than imported.

Why this exists — the demo's lifecycle runner historically scored evidence
recall against ``dia_ids`` scraped off the retrieval payload's metadata. Those
keys are not reliably present on an ``EvidenceItem`` (the replay bead stores the
raw dia_id inside ``source_turn_ids``, not as a metadata field), so recall was
systematically undercounted. The upstream harness instead builds an
authoritative ``bead_id -> dia_id`` map from the bead index's ``source_turn_ids``
and maps any retrieved ``bead_id`` back to dia space. That technique is the fix,
and it is what :func:`build_bead_to_dias` implements here.

The scoring functions mirror the upstream conventions exactly:
  * ``multihop_f1`` takes the **max** over comma-separated sub-answers (cat 1),
  * category 5 (adversarial/unanswerable) is **excluded** from official scoring
    because 444/446 questions have broken answer keys in the public corpus,
  * answer F1 is category-aware (cat 3 strips at the first semicolon).
"""
from __future__ import annotations

import json
import re
import string
from collections import Counter
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.benchmarks.contracts import BenchmarkConversation, BenchmarkQA

# Categories that count toward official, published-comparable LoCoMo evaluation.
OFFICIAL_CATEGORIES = frozenset({1, 2, 3, 4})
EXCLUDED_CATEGORIES = frozenset({5})

_ARTICLES = {"a", "an", "the"}
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


# ---------------------------------------------------------------------------
# Answer scoring (category-aware token / multi-hop F1) — upstream conventions
# ---------------------------------------------------------------------------
def normalize_text(value: str) -> str:
    text = str(value or "").lower()
    text = text.translate(_PUNCT_TABLE)
    tokens = [t for t in text.split() if t not in _ARTICLES]
    return " ".join(tokens)


def token_f1(prediction: str, answer: str) -> float:
    pred_tokens = normalize_text(prediction).split()
    gold_tokens = normalize_text(answer).split()
    if not pred_tokens and not gold_tokens:
        return 1.0
    if not pred_tokens or not gold_tokens:
        return 0.0
    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    return (2 * precision * recall) / (precision + recall)


def multihop_f1(prediction: str, answer: str) -> float:
    """Category 1: gold answer may be comma-separated; score max F1 per sub-answer."""
    sub_answers = [a.strip() for a in str(answer or "").split(",") if a.strip()]
    if not sub_answers:
        return token_f1(prediction, answer)
    return max(token_f1(prediction, sub) for sub in sub_answers)


def is_official_category(category: int | str | None) -> bool:
    cat = int(category) if str(category or "").isdigit() else 0
    return cat in OFFICIAL_CATEGORIES


def score_answer(*, category: int | str | None, prediction: str, answer: str) -> float:
    """Category-aware answer scoring in [0.0, 1.0] (upstream semantics)."""
    cat = int(category) if str(category or "").isdigit() else 0
    if cat == 1:
        return multihop_f1(prediction, answer)
    if cat == 3:
        # The canonical answer is the prefix before the first semicolon.
        gold = str(answer or "").split(";", 1)[0].strip()
        return token_f1(prediction, gold)
    if cat in {2, 4}:
        return token_f1(prediction, answer)
    if cat == 5:
        # Excluded from official evaluation; return neutral 1.0 so it never drags
        # an aggregate that mistakenly includes it. Callers should mark excluded.
        return 1.0
    return token_f1(prediction, answer)


# ---------------------------------------------------------------------------
# Evidence recall in dia_id space (flat ranked list) — upstream semantics
# ---------------------------------------------------------------------------
def compute_evidence_recall(
    *,
    gold_evidence: list[str],
    retrieved: list[str],
    ks: list[int] | None = None,
) -> dict[str, Any]:
    """Score evidence recall against a flat, rank-ordered list of dia_ids.

    ``retrieved`` is one dia_id per rank (position 0 == rank 1). When
    ``gold_evidence`` is empty, recall is vacuously 1.0 and ``vacuous`` is set so
    aggregation can exclude the case from headline (published-comparable) numbers.
    """
    if ks is None:
        ks = [1, 3, 5, 10]
    gold_set = {str(d).strip() for d in gold_evidence if str(d).strip()}
    if not gold_set:
        return {"vacuous": True, **{f"recall@{k}": 1.0 for k in ks}, "mrr": 1.0, "hit_any": True}

    retrieved_norm = [str(d).strip() for d in retrieved]
    hit_ranks = [rank for rank, dia in enumerate(retrieved_norm, start=1) if dia in gold_set]

    out: dict[str, Any] = {"vacuous": False}
    for k in ks:
        hits_at_k = sum(1 for r in hit_ranks if r <= k)
        out[f"recall@{k}"] = round(hits_at_k / len(gold_set), 4)
    out["mrr"] = round(1.0 / min(hit_ranks), 4) if hit_ranks else 0.0
    out["hit_any"] = bool(hit_ranks)
    return out


def aggregate_case_scores(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case scores; primary recall metrics exclude vacuous cases.

    Mirrors the upstream ``aggregate_case_scores`` so faithful-suite headline
    numbers are comparable to published LoCoMo systems.
    """
    with_evidence = [c for c in cases if not bool((c.get("evidence_recall") or {}).get("vacuous", True))]

    def _agg(nums: list[float]) -> float | None:
        return round(sum(nums) / len(nums), 4) if nums else None

    answer_f1_all = [float(c.get("answer_f1", 0.0)) for c in cases if not c.get("excluded")]

    by_category: dict[str, dict[str, list[Any]]] = {}
    for case in cases:
        cat = str(case.get("category") or "unknown")
        row = by_category.setdefault(cat, {"cases": [], "answer_f1": [], "recall@1": [], "recall@5": [], "mrr": []})
        row["cases"].append(case.get("qa_id"))
        if not case.get("excluded"):
            row["answer_f1"].append(float(case.get("answer_f1", 0.0)))
        ev = dict(case.get("evidence_recall") or {})
        if not ev.get("vacuous"):
            row["recall@1"].append(float(ev.get("recall@1", 0.0)))
            row["recall@5"].append(float(ev.get("recall@5", 0.0)))
            row["mrr"].append(float(ev.get("mrr", 0.0)))

    by_category_agg = {
        cat: {
            "case_count": len(v["cases"]),
            "answer_f1_mean": _agg(v["answer_f1"]),
            "recall@1_mean": _agg(v["recall@1"]),
            "recall@5_mean": _agg(v["recall@5"]),
            "mrr_mean": _agg(v["mrr"]),
        }
        for cat, v in sorted(by_category.items())
    }

    return {
        "total_cases": len(cases),
        "cases_with_evidence": len(with_evidence),
        "cases_without_evidence_annotation": len(cases) - len(with_evidence),
        "overall": {
            "answer_f1_mean": _agg(answer_f1_all),
            "recall@1_mean": _agg([float((c.get("evidence_recall") or {}).get("recall@1", 0.0)) for c in with_evidence]),
            "recall@5_mean": _agg([float((c.get("evidence_recall") or {}).get("recall@5", 0.0)) for c in with_evidence]),
            "mrr_mean": _agg([float((c.get("evidence_recall") or {}).get("mrr", 0.0)) for c in with_evidence]),
            "hit_any_rate": _agg([1.0 if (c.get("evidence_recall") or {}).get("hit_any") else 0.0 for c in with_evidence]),
        },
        "by_category": by_category_agg,
        "methodology_note": "primary_recall_metrics_exclude_vacuous_evidence_cases",
    }


# ---------------------------------------------------------------------------
# Robust dia_id <-> bead_id mapping (the core accuracy fix)
# ---------------------------------------------------------------------------
def _read_bead_index(root: str | Path) -> dict[str, Any]:
    idx_path = Path(root) / ".beads" / "index.json"
    if not idx_path.exists():
        return {}
    try:
        return json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_bead_to_dias(
    root: str | Path,
    conversation: BenchmarkConversation,
) -> dict[str, list[str]]:
    """Build ``{bead_id: [dia_id, ...]}`` from the bead index after ingestion.

    Bead IDs are non-deterministic across ingestion runs, so evidence recall is
    scored in dia_id space. This reads ``source_turn_ids`` from every bead in the
    conversation's replay session and resolves each one to a dia_id using the
    conversation's own turn metadata — so the mapping survives compaction (a
    compacted bead that absorbs several turns maps to all their dia_ids).
    """
    # Resolve every replay turn to its dia_id, keyed by both the turn_id and the
    # raw dia_id (the demo stores source_turn_ids=[turn_id, dia_id]).
    turn_to_dia: dict[str, str] = {}
    known_dias: set[str] = set()
    for turn in conversation.turns:
        dia_id = str((turn.metadata or {}).get("locomo_dia_id") or (turn.metadata or {}).get("dia_id") or "").strip()
        if not dia_id:
            continue
        known_dias.add(dia_id)
        turn_to_dia[str(turn.turn_id)] = dia_id
        turn_to_dia[dia_id] = dia_id

    session_id = str(conversation.session_id or "")
    idx = _read_bead_index(root)
    beads = dict((idx.get("beads") or {})) if isinstance(idx, dict) else {}

    bead_to_dias: dict[str, list[str]] = {}
    for bead in beads.values():
        if not isinstance(bead, dict):
            continue
        # Replay beads carry the conversation's session_id; tolerate empty/legacy.
        bead_session = str(bead.get("session_id") or "")
        if session_id and bead_session and bead_session != session_id:
            continue
        bead_id = str(bead.get("id") or "")
        if not bead_id:
            continue
        dias: list[str] = []
        for src in bead.get("source_turn_ids") or []:
            src = str(src).strip()
            dia = turn_to_dia.get(src)
            if dia and dia not in dias:
                dias.append(dia)
        if dias:
            bead_to_dias[bead_id] = sorted(dias)
    return bead_to_dias


def ranked_dia_ids_for_rows(
    rows: list[dict[str, Any]],
    bead_to_dias: dict[str, list[str]] | None,
) -> list[str]:
    """Flatten ranked retrieval rows into a rank-ordered, de-duplicated dia list.

    Prefers dia_ids already present on a row (e.g. surfaced metadata), then falls
    back to the authoritative ``bead_to_dias`` map keyed on the row's bead_id.
    """
    out: list[str] = []
    seen: set[str] = set()
    bead_to_dias = bead_to_dias or {}
    for row in rows:
        dias = [str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip()]
        if not dias:
            bead_id = str((row or {}).get("bead_id") or "").strip()
            dias = list(bead_to_dias.get(bead_id) or [])
        for dia in dias:
            if dia not in seen:
                seen.add(dia)
                out.append(dia)
    return out


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """Generic adapter protocol every dataset adapter must satisfy.

    Ported from the upstream ``benchmarks/contracts.py`` so the demo can grow
    additional datasets behind one measurement interface.
    """

    @property
    def name(self) -> str: ...

    def load_conversations(self, **kwargs: Any) -> list[BenchmarkConversation]: ...

    def score_answer(self, *, qa: BenchmarkQA, prediction: str) -> float: ...

    def score_evidence(self, *, qa: BenchmarkQA, retrieved_ids: list[str], k: int) -> dict[str, Any]: ...
