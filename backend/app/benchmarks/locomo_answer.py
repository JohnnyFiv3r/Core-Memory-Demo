from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.core.agent_runtime import run_agent_for_root


def _extractive_answer(retrieved_context: list[dict[str, Any]]) -> dict[str, Any]:
    if not retrieved_context:
        return {
            "answer": "No information available",
            "used_dia_ids": [],
            "confidence": "low",
            "unsupported": True,
        }
    top = dict(retrieved_context[0] or {})
    text = str(top.get("text") or top.get("snippet") or "").strip()
    return {
        "answer": text or "No information available",
        "used_dia_ids": list(top.get("dia_ids") or []),
        "confidence": "medium" if text else "low",
        "unsupported": not bool(text),
    }


def _oracle_answer(*, qa: dict[str, Any], gold_context: list[dict[str, Any]]) -> dict[str, Any]:
    used = []
    parts = []
    for row in gold_context:
        used.extend([str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip()])
        text = str(row.get("text") or "").strip()
        if text:
            parts.append(text)
    answer = " ".join(parts).strip() or "No information available"
    return {
        "answer": answer,
        "used_dia_ids": sorted(set(used)),
        "confidence": "high" if parts else "low",
        "unsupported": not bool(parts),
    }


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _normalize_answer_payload(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    stripped = _JSON_FENCE_RE.sub("", text).strip() if text else ""
    parsed: dict[str, Any] | None = None
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            loaded = json.loads(stripped)
            if isinstance(loaded, dict):
                parsed = dict(loaded)
        except Exception:
            parsed = None
    if parsed is None:
        parsed = {"answer": text or "No information available"}

    answer = str(parsed.get("answer") or "No information available").strip() or "No information available"
    raw_used = parsed.get("used_dia_ids") or []
    used = [str(x).strip() for x in raw_used if str(x).strip()] if isinstance(raw_used, list) else []
    confidence = str(parsed.get("confidence") or "low").strip().lower() or "low"
    unsupported_raw = parsed.get("unsupported")
    if isinstance(unsupported_raw, bool):
        unsupported = unsupported_raw
    elif isinstance(unsupported_raw, str):
        unsupported = unsupported_raw.strip().lower() in {"true", "1", "yes", "unsupported"}
    else:
        unsupported = answer == "No information available"
    return {
        "answer": answer,
        "used_dia_ids": used,
        "confidence": confidence if confidence in {"low", "medium", "high"} else "low",
        "unsupported": unsupported,
    }


def _reconcile_used_dia_ids(*, used_dia_ids: list[str], retrieved_context: list[dict[str, Any]], gold_context: list[dict[str, Any]] | None = None) -> list[str]:
    allowed = set()
    for row in list(retrieved_context or []) + list(gold_context or []):
        allowed.update(str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip())
    used = [str(x).strip() for x in (used_dia_ids or []) if str(x).strip()]
    normalized = [x for x in used if x in allowed]
    if normalized:
        return sorted(set(normalized))
    fallback = []
    for row in retrieved_context or []:
        fallback.extend(str(x).strip() for x in (row.get("dia_ids") or []) if str(x).strip())
    if fallback:
        return sorted(set(fallback[:3]))
    return []


async def _llm_answer_async(*, root: str, sample_id: str, question: str, model_id: str) -> dict[str, Any]:
    out = await run_agent_for_root(
        root=root,
        session_id=f"locomo:{sample_id}",
        message=question,
        model_id=model_id,
        instruction_prefix=(
            "You are answering a benchmark evaluation question through the normal demo agent path. "
            "Use memory tools normally, stay grounded in stored memory, and answer concisely. "
            "When possible, return strict JSON with keys: answer, used_dia_ids, confidence, unsupported. "
            "If you cannot support an answer from memory, answer exactly 'No information available'."
        ),
        metadata={"benchmark_answering": True, "sample_id": sample_id},
    )
    raw = str(out.get("assistant") or "").strip()
    return _normalize_answer_payload(raw)


def generate_locomo_answer(*, mode: str, root: str | None = None, sample_id: str | None = None, qa: dict[str, Any], retrieved_context: list[dict[str, Any]], generator_model: str | None = None, gold_context: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    mode_name = str(mode or "none").strip().lower() or "none"
    if mode_name == "none":
        return {
            "answer": "",
            "used_dia_ids": [],
            "confidence": "low",
            "unsupported": True,
        }
    if mode_name == "extractive":
        return _extractive_answer(retrieved_context)
    if mode_name == "oracle_context":
        return _oracle_answer(qa=qa, gold_context=list(gold_context or []))
    if mode_name == "llm":
        model_id = str(generator_model or "").strip()
        if not model_id:
            raise RuntimeError("missing_generator_model")
        root_path = str(root or "").strip()
        if not root_path:
            raise RuntimeError("missing_root")
        sample_id_value = str(sample_id or qa.get("sample_id") or "").strip()
        if not sample_id_value:
            raise RuntimeError("missing_sample_id")
        out = asyncio.run(_llm_answer_async(root=root_path, sample_id=sample_id_value, question=str(qa.get("question") or ""), model_id=model_id))
        out["used_dia_ids"] = _reconcile_used_dia_ids(
            used_dia_ids=list(out.get("used_dia_ids") or []),
            retrieved_context=retrieved_context,
            gold_context=gold_context,
        )
        return out
    raise ValueError(f"unsupported_locomo_answer_mode:{mode_name}")
