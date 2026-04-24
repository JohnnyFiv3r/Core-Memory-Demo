from __future__ import annotations

import re
import string
from statistics import mean
from typing import Any

_ARTICLES = {"a", "an", "the"}
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)
_NO_INFO_MARKERS = (
    "no information available",
    "not mentioned",
    "not provided",
    "unknown",
)


def normalize_text(value: str) -> str:
    text = str(value or "").lower().strip()
    text = text.translate(_PUNCT_TABLE)
    text = " ".join(tok for tok in text.split() if tok not in _ARTICLES)
    return text


def _tokens(value: str) -> list[str]:
    norm = normalize_text(value)
    return [tok for tok in norm.split() if tok]


def token_f1(prediction: str, answer: str) -> float:
    pred = _tokens(prediction)
    gold = _tokens(answer)
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    gold_counts: dict[str, int] = {}
    for token in gold:
        gold_counts[token] = gold_counts.get(token, 0) + 1
    overlap = 0
    for token in pred:
        count = gold_counts.get(token, 0)
        if count > 0:
            overlap += 1
            gold_counts[token] = count - 1
    if overlap <= 0:
        return 0.0
    precision = overlap / len(pred)
    recall = overlap / len(gold)
    return (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0


def _split_subanswers(value: str) -> list[str]:
    raw = [part.strip() for part in re.split(r"\s*,\s*", str(value or "")) if part.strip()]
    return raw or [str(value or "").strip()]


def multihop_f1(prediction: str, answer: str) -> float:
    pred_parts = _split_subanswers(prediction)
    answer_parts = _split_subanswers(answer)
    if not answer_parts:
        return 0.0
    scores = [max(token_f1(pred, gold) for pred in pred_parts) if pred_parts else 0.0 for gold in answer_parts]
    return mean(scores) if scores else 0.0


def score_answer(*, category: int, prediction: str, answer: str) -> float:
    pred = str(prediction or "").strip()
    gold = str(answer or "").strip()
    if int(category or 0) == 3:
        gold = gold.split(";")[0].strip()
    if int(category or 0) in {2, 3, 4}:
        return token_f1(pred, gold)
    if int(category or 0) == 1:
        return multihop_f1(pred, gold)
    if int(category or 0) == 5:
        norm = normalize_text(pred)
        return 1.0 if any(marker in norm for marker in _NO_INFO_MARKERS) else token_f1(pred, gold)
    return token_f1(pred, gold)


def compute_evidence_recall(*, gold_evidence: list[str], retrieved: list[dict[str, Any]], ks: list[int] | None = None) -> dict[str, Any]:
    target = [str(x).strip() for x in (gold_evidence or []) if str(x).strip()]
    cutoffs = list(ks or [1, 3, 5, 8, 10])
    if not target:
        out = {f"recall@{k}": 1.0 for k in cutoffs}
        out.update({"mrr": 1.0, "hit_any": True, "gold_evidence_count": 0, "retrieved_evidence_count": 0})
        return out

    ranked_hits: list[int] = []
    matched: set[str] = set()
    for idx, row in enumerate(retrieved, start=1):
        dia_ids = {str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip()}
        if dia_ids & set(target):
            ranked_hits.append(idx)
            matched |= (dia_ids & set(target))

    out: dict[str, Any] = {
        "hit_any": bool(ranked_hits),
        "gold_evidence_count": len(target),
        "retrieved_evidence_count": len(matched),
        "mrr": (1.0 / ranked_hits[0]) if ranked_hits else 0.0,
    }
    for k in cutoffs:
        top_matched: set[str] = set()
        for row in retrieved[: max(1, int(k))]:
            dia_ids = {str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip()}
            top_matched |= (dia_ids & set(target))
        out[f"recall@{k}"] = len(top_matched) / len(target) if target else 1.0
    return out


def aggregate_case_scores(cases: list[dict[str, Any]]) -> dict[str, Any]:
    def _avg(key: str, rows: list[dict[str, Any]]) -> float:
        vals = [float(r.get(key) or 0.0) for r in rows]
        return round(mean(vals), 4) if vals else 0.0

    def _avg_nested(rows: list[dict[str, Any]], nested_key: str) -> float:
        vals = [float((r.get("evidence_recall") or {}).get(nested_key) or 0.0) for r in rows]
        return round(mean(vals), 4) if vals else 0.0

    by_category: dict[str, list[dict[str, Any]]] = {}
    by_sample: dict[str, list[dict[str, Any]]] = {}
    for row in cases:
        by_category.setdefault(str(row.get("category") or "0"), []).append(row)
        by_sample.setdefault(str(row.get("sample_id") or "unknown"), []).append(row)

    overall = {
        "qa_count": len(cases),
        "answer_f1_mean": _avg("answer_f1", cases),
        "evidence_recall@5": _avg_nested(cases, "recall@5"),
        "hit_any": _avg_nested(cases, "hit_any"),
        "mrr": _avg_nested(cases, "mrr"),
    }

    return {
        "overall": overall,
        "by_category": {
            key: {
                "qa_count": len(rows),
                "answer_f1_mean": _avg("answer_f1", rows),
                "evidence_recall@5": _avg_nested(rows, "recall@5"),
                "hit_any": _avg_nested(rows, "hit_any"),
                "mrr": _avg_nested(rows, "mrr"),
            }
            for key, rows in sorted(by_category.items(), key=lambda item: int(item[0]))
        },
        "by_sample": {
            key: {
                "qa_count": len(rows),
                "answer_f1_mean": _avg("answer_f1", rows),
                "evidence_recall@5": _avg_nested(rows, "recall@5"),
                "hit_any": _avg_nested(rows, "hit_any"),
                "mrr": _avg_nested(rows, "mrr"),
            }
            for key, rows in sorted(by_sample.items())
        },
    }
