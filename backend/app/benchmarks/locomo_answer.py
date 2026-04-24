from __future__ import annotations

import asyncio
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


async def _llm_answer_async(*, root: str, sample_id: str, question: str, model_id: str) -> dict[str, Any]:
    out = await run_agent_for_root(
        root=root,
        session_id=f"locomo:{sample_id}",
        message=question,
        model_id=model_id,
    )
    raw = str(out.get("assistant") or "").strip()
    return {
        "answer": raw or "No information available",
        "used_dia_ids": [],
        "confidence": "low",
        "unsupported": not bool(raw) or raw == "No information available",
    }


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
        return asyncio.run(_llm_answer_async(root=root_path, sample_id=sample_id_value, question=str(qa.get("question") or ""), model_id=model_id))
    raise ValueError(f"unsupported_locomo_answer_mode:{mode_name}")
