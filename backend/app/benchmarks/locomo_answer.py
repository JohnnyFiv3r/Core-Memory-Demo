from __future__ import annotations

import asyncio
import json
import re
from typing import Any

try:
    from pydantic_ai import Agent
except Exception:  # pragma: no cover
    Agent = None  # type: ignore


def _support_strength(retrieved_context: list[dict[str, Any]]) -> dict[str, Any]:
    if not retrieved_context:
        return {"supported": False, "reason": "no_retrieval"}
    top = retrieved_context[0] or {}
    top_text = str(top.get("text") or top.get("snippet") or "").strip()
    raw_score = top.get("locomo_score", top.get("score"))
    top_score = float(raw_score) if raw_score is not None else None
    used_dia_ids = [str(x).strip() for x in (top.get("dia_ids") or []) if str(x).strip()]
    if not top_text:
        return {"supported": False, "reason": "empty_top_text"}
    if not used_dia_ids:
        return {"supported": False, "reason": "missing_dia_ids"}
    return {"supported": True, "reason": "top_hit_grounded"}


def _extractive_answer(retrieved_context: list[dict[str, Any]], *, question: str = "") -> dict[str, Any]:
    support = _support_strength(retrieved_context)
    if not bool(support.get("supported")):
        return {
            "answer": "No information available",
            "used_dia_ids": [],
            "confidence": "low",
            "unsupported": True,
        }
    top = dict(retrieved_context[0] or {})
    claim_value = top.get("claim_value")
    if str(top.get("source_surface") or "") == "claim_state" and claim_value not in (None, ""):
        q = str(question or "").strip().lower()
        values: list[str] = []
        used: list[str] = []
        top_slot = str(top.get("claim_slot_key") or "")
        for row in retrieved_context or []:
            item = dict(row or {})
            if str(item.get("source_surface") or "") != "claim_state":
                continue
            if top_slot and str(item.get("claim_slot_key") or "") != top_slot:
                continue
            value = str(item.get("claim_value") or "").strip()
            if value and value not in values:
                values.append(value)
            used.extend(str(x).strip() for x in (item.get("dia_ids") or []) if str(x).strip())
        if q.startswith("how many") and values:
            words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
            answer = words.get(len(values), str(len(values)))
        else:
            answer = str(claim_value).strip()
        return {
            "answer": answer or "No information available",
            "used_dia_ids": sorted(set(used))[:5],
            "confidence": "high" if answer else "low",
            "unsupported": not bool(answer),
        }
    text = str(top.get("text") or top.get("snippet") or "").strip()
    return {
        "answer": text or "No information available",
        "used_dia_ids": list(top.get("dia_ids") or []),
        "confidence": "medium" if text else "low",
        "unsupported": not bool(text),
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


def _reconcile_used_dia_ids(*, used_dia_ids: list[str], retrieved_context: list[dict[str, Any]]) -> list[str]:
    allowed = set()
    for row in retrieved_context or []:
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


def _format_retrieved_context(retrieved_context: list[dict[str, Any]], *, limit: int = 5) -> str:
    lines: list[str] = []
    for idx, row in enumerate((retrieved_context or [])[: max(1, int(limit))], start=1):
        item = dict(row or {})
        dia_ids = ", ".join(str(x).strip() for x in (item.get("dia_ids") or []) if str(x).strip()) or "unknown"
        speaker = str(item.get("speaker") or "").strip()
        session_date_time = str(item.get("session_date_time") or "").strip()
        text = str(item.get("text") or item.get("snippet") or "").strip()
        bead_text = str(item.get("bead_text") or "").strip()
        turn_transcript = str(item.get("turn_transcript") or "").strip()
        score = float(item.get("locomo_score") or item.get("score") or 0.0)
        body_parts: list[str] = []
        if bead_text:
            body_parts.append(f"Bead: {bead_text}")
        if turn_transcript and turn_transcript != bead_text:
            body_parts.append(f"Turn transcript: {turn_transcript}")
        if text and text not in {bead_text, turn_transcript}:
            body_parts.append(f"Snippet: {text}")
        body = "\n".join(body_parts) or text
        lines.append(
            f"[{idx}] dia_ids={dia_ids} speaker={speaker} session_date_time={session_date_time} score={score:.3f}\n{body}"
        )
    return "\n\n".join(lines).strip()


async def _llm_answer_async(*, root: str, sample_id: str, question: str, model_id: str, retrieved_context: list[dict[str, Any]]) -> dict[str, Any]:
    support = _support_strength(retrieved_context)
    if not bool(support.get("supported")):
        return {
            "answer": "No information available",
            "used_dia_ids": [],
            "confidence": "low",
            "unsupported": True,
        }
    context_block = _format_retrieved_context(retrieved_context)
    context_prompt = (
        "Answer the question based on the retrieved conversation context below. "
        "Use each evidence row's session_date_time to resolve relative dates like yesterday, last week, today, or next month into the absolute date/month/year when possible. "
        "If the retrieved context does not contain enough information to answer, "
        "respond exactly with 'No information available'.\n\n"
        f"Question: {question}\n\n"
        f"Retrieved evidence:\n{context_block}\n\n"
        "Return strict JSON with keys: answer, used_dia_ids, confidence, unsupported. "
        "Only cite dia_ids that appear in the retrieved context."
    )
    if Agent is None:
        raise RuntimeError("pydantic_ai_unavailable")
    # Important benchmark isolation: answer generation must not run through
    # run_with_memory()/run_agent_for_root on the benchmark root.  That path
    # writes the generated answer back into Core Memory, marks the semantic
    # index dirty between QA cases, and can cause later retrieval to return a
    # previous answer JSON as evidence.  This answerer is deliberately a plain
    # no-tools LLM call over the already-retrieved evidence block.
    agent = Agent(
        model_id,
        system_prompt=(
            "You are a conversational memory benchmark answerer. "
            "Only answer from the supplied retrieved evidence block. "
            "Do not use tools, memory, prior answers, or unstated knowledge. "
            "If the evidence is insufficient, abstain with 'No information available'."
        ),
    )
    result = await agent.run(context_prompt)
    raw = str(getattr(result, "output", None) or getattr(result, "data", None) or result).strip()
    return _normalize_answer_payload(raw)


def generate_locomo_answer(*, mode: str, root: str | None = None, sample_id: str | None = None, qa: dict[str, Any], retrieved_context: list[dict[str, Any]], generator_model: str | None = None) -> dict[str, Any]:
    mode_name = str(mode or "none").strip().lower() or "none"
    if mode_name == "none":
        return {
            "answer": "",
            "used_dia_ids": [],
            "confidence": "low",
            "unsupported": True,
        }
    if mode_name == "extractive":
        return _extractive_answer(retrieved_context, question=str(qa.get("question") or ""))
    if mode_name == "oracle_context":
        raise ValueError("oracle_context_answer_mode_disabled_for_scored_benchmarks")
    if mode_name == "llm":
        if Agent is None:
            raise RuntimeError("pydantic_ai_unavailable")
        model_id = str(generator_model or "").strip()
        if not model_id:
            raise RuntimeError("missing_generator_model")
        root_path = str(root or "").strip()
        if not root_path:
            raise RuntimeError("missing_root")
        sample_id_value = str(sample_id or qa.get("sample_id") or "").strip()
        if not sample_id_value:
            raise RuntimeError("missing_sample_id")
        out = asyncio.run(
            _llm_answer_async(
                root=root_path,
                sample_id=sample_id_value,
                question=str(qa.get("question") or ""),
                model_id=model_id,
                retrieved_context=retrieved_context,
            )
        )
        out["used_dia_ids"] = _reconcile_used_dia_ids(
            used_dia_ids=list(out.get("used_dia_ids") or []),
            retrieved_context=retrieved_context,
        )
        return out
    raise ValueError(f"unsupported_locomo_answer_mode:{mode_name}")
