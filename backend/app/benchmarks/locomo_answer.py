from __future__ import annotations

import asyncio
import json
from typing import Any

try:
    from pydantic_ai import Agent
except Exception:  # pragma: no cover
    Agent = None  # type: ignore


def _build_prompt(question: str, retrieved_context: list[dict[str, Any]]) -> str:
    ctx_lines = []
    for row in retrieved_context:
        ctx_lines.append(
            json.dumps(
                {
                    "rank": int(row.get("rank") or 0),
                    "dia_ids": list(row.get("dia_ids") or []),
                    "speaker": str(row.get("speaker") or ""),
                    "session_date_time": str(row.get("session_date_time") or ""),
                    "text": str(row.get("text") or row.get("snippet") or ""),
                },
                ensure_ascii=False,
            )
        )
    context_block = "\n".join(ctx_lines) if ctx_lines else "[]"
    return (
        "Answer the user question using only the provided context.\n"
        "Do not use outside knowledge.\n"
        "If the answer is not supported by the context, answer exactly 'No information available'.\n"
        "Return strict JSON with keys: answer, used_dia_ids, confidence, unsupported.\n"
        "confidence must be one of: low, medium, high.\n"
        f"Question: {question}\n"
        f"Retrieved context:\n{context_block}\n"
    )


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


async def _llm_answer_async(*, question: str, retrieved_context: list[dict[str, Any]], model_id: str) -> dict[str, Any]:
    if Agent is None:
        raise RuntimeError("pydantic_ai_unavailable")
    agent = Agent(model_id)
    prompt = _build_prompt(question, retrieved_context)
    result = await agent.run(prompt)
    raw = str(getattr(result, "output", None) or getattr(result, "data", None) or result).strip()
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {
            "answer": raw or "No information available",
            "used_dia_ids": [],
            "confidence": "low",
            "unsupported": not bool(raw),
        }
    parsed.setdefault("answer", "No information available")
    parsed.setdefault("used_dia_ids", [])
    parsed.setdefault("confidence", "low")
    parsed.setdefault("unsupported", False)
    return parsed


def generate_locomo_answer(*, mode: str, qa: dict[str, Any], retrieved_context: list[dict[str, Any]], generator_model: str | None = None, gold_context: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
        return asyncio.run(_llm_answer_async(question=str(qa.get("question") or ""), retrieved_context=retrieved_context, model_id=model_id))
    raise ValueError(f"unsupported_locomo_answer_mode:{mode_name}")
