from __future__ import annotations

import asyncio
import json
import re
from typing import Any

try:
    from pydantic_ai import Agent
except Exception:  # pragma: no cover
    Agent = None  # type: ignore

try:
    from core_memory.integrations.pydanticai.memory_tools import (
        hydrate_bead_sources_tool,
        memory_execute_tool,
        memory_search_tool,
        memory_trace_tool,
    )
except Exception:  # pragma: no cover
    hydrate_bead_sources_tool = None  # type: ignore
    memory_execute_tool = None  # type: ignore
    memory_search_tool = None  # type: ignore
    memory_trace_tool = None  # type: ignore


class RequiredToolPhaseError(RuntimeError):
    """Raised when official LoCoMo QA does not execute required memory tools.

    The lifecycle runner treats this as fatal, not as an answer-generation
    warning, because official production-fidelity benchmarks must fail closed
    if the PydanticAI agent skips search → trace → hydrate.
    """

    def __init__(self, validation: dict[str, Any]):
        self.validation = dict(validation or {})
        super().__init__(str(self.validation.get("error") or "required_tool_phase_missing"))


def _support_strength(retrieved_context: list[dict[str, Any]]) -> dict[str, Any]:
    # Decide only whether there is *anything* worth asking the LLM about. The
    # gate is intentionally permissive: any retrieved row carrying text is enough
    # to attempt an answer, and the LLM still abstains on its own when the
    # evidence is genuinely insufficient. The previous gate required the single
    # top row to carry dia_ids, so a top hit that did not map to a conversation
    # dia_id (e.g. a foreign/QA bead) forced "No information available" even when
    # the rows below it clearly answered the question — a fail-closed bug that
    # tanked answer F1 on cases where gold evidence was actually retrieved.
    if not retrieved_context:
        return {"supported": False, "reason": "no_retrieval"}
    has_text = any(
        str((row or {}).get("text") or (row or {}).get("snippet") or "").strip()
        for row in retrieved_context
    )
    if not has_text:
        return {"supported": False, "reason": "empty_context"}
    return {"supported": True, "reason": "context_has_text"}


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


def _format_retrieved_context(retrieved_context: list[dict[str, Any]], *, limit: int | None = None) -> str:
    lines: list[str] = []
    rows = list(retrieved_context or [])
    if limit is not None:
        rows = rows[: max(1, int(limit))]
    for idx, row in enumerate(rows, start=1):
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


def _tool_call_name(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("tool_name", "name", "function", "tool"):
            if str(value.get(key) or "").strip():
                return str(value.get(key) or "").strip()
    for key in ("tool_name", "name", "function_name"):
        if str(getattr(value, key, "") or "").strip():
            return str(getattr(value, key) or "").strip()
    return ""


def extract_tool_transcript(result: Any) -> list[dict[str, Any]]:
    """Best-effort PydanticAI tool-call transcript extraction.

    Kept permissive for tests and provider/version drift: callers may pass a
    result object, a dict payload, or a pre-shaped list of tool call rows.
    """
    if isinstance(result, list):
        return [dict(x) for x in result if isinstance(x, dict)]
    if isinstance(result, dict):
        rows = result.get("tool_calls") or result.get("tool_transcript") or result.get("tools") or []
        return [dict(x) for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []
    rows: list[dict[str, Any]] = []
    messages_obj = None
    all_messages = getattr(result, "all_messages", None)
    if callable(all_messages):
        try:
            messages_obj = all_messages()
        except Exception:
            messages_obj = None
    if messages_obj is None:
        messages_obj = getattr(result, "messages", None) or getattr(result, "_messages", None) or []
    for msg in list(messages_obj or []):
        parts = getattr(msg, "parts", None)
        if parts is None and isinstance(msg, dict):
            parts = msg.get("parts") or []
        for part in list(parts or []):
            name = _tool_call_name(part)
            if not name:
                continue
            args = getattr(part, "args", None)
            if args is None and isinstance(part, dict):
                args = part.get("args") or part.get("arguments")
            rows.append({"tool_name": name, "args": args})
    return rows


def validate_required_tool_phases(tool_transcript: list[dict[str, Any]]) -> dict[str, Any]:
    names = [str(_tool_call_name(row)).strip() for row in list(tool_transcript or [])]
    names_l = [n.lower() for n in names if n]
    phases = {
        "search": any("search" in n or "execute_memory_request" == n for n in names_l),
        "trace": any("trace" in n for n in names_l),
        "hydrate": any("hydrate" in n or "get_turn" in n or "source" in n for n in names_l),
    }
    missing = [phase for phase, ok in phases.items() if not ok]
    if missing:
        return {"ok": False, "error": "required_tool_phase_missing", "missing": missing, "tool_names": names}
    phase_positions = {
        "search": next(i for i, n in enumerate(names_l) if "search" in n or "execute_memory_request" == n),
        "trace": next(i for i, n in enumerate(names_l) if "trace" in n),
        "hydrate": next(i for i, n in enumerate(names_l) if "hydrate" in n or "get_turn" in n or "source" in n),
    }
    if not (phase_positions["search"] < phase_positions["trace"] < phase_positions["hydrate"]):
        return {"ok": False, "error": "required_tool_phase_order_invalid", "positions": phase_positions, "tool_names": names}
    return {"ok": True, "phases": phases, "positions": phase_positions, "tool_names": names}


async def _llm_answer_async(*, root: str, sample_id: str, question: str, model_id: str, retrieved_context: list[dict[str, Any]]) -> dict[str, Any]:
    context_prompt = (
        "Answer this LoCoMo benchmark question using Core Memory tools only. "
        "Before answering, you MUST perform these phases in order: "
        "(1) semantic memory search/execute, (2) causal trace with max_depth up to 6, "
        "and (3) hydrate/get source turns for candidate and traced beads. "
        "Use hydrated source-turn text and dates to resolve relative dates like yesterday, last week, today, or next month into absolute dates when possible. "
        "Answer with the SHORTEST possible span that directly answers the question "
        "— just the fact itself (a date, name, place, number, or short list), with no "
        "preamble, restatement of the question, or full sentence. For example answer "
        "'7 May 2023', not 'She went on 7 May 2023'. If the question asks for several "
        "items, give them as a comma-separated list. "
        "If hydrated memory context does not contain enough information to answer, "
        "respond exactly with 'No information available'.\n\n"
        f"Question: {question}\n\n"
        "Return strict JSON with keys: answer, used_dia_ids, confidence, unsupported. "
        "Only cite dia_ids that appear in hydrated source context."
    )
    if Agent is None:
        raise RuntimeError("pydantic_ai_unavailable")
    if not all(callable(tool) for tool in [memory_execute_tool, memory_search_tool, memory_trace_tool, hydrate_bead_sources_tool]):
        raise RuntimeError("core_memory_pydanticai_tools_unavailable")
    agent = Agent(
        model_id,
        system_prompt=(
            "You are a conversational memory benchmark answerer. Use Core Memory tools before answering. "
            "Do not use unstated knowledge, prior answers, or benchmark gold labels. "
            "Answer with the shortest exact span (a date, name, place, number, or "
            "comma-separated list) — never a full sentence or a restatement of the "
            "question. If the evidence is insufficient, abstain with 'No information available'."
        ),
        tools=[
            memory_execute_tool(root=root),
            memory_search_tool(root=root),
            memory_trace_tool(root=root),
            hydrate_bead_sources_tool(root=root),
        ],
    )
    result = await agent.run(context_prompt)
    raw = str(getattr(result, "output", None) or getattr(result, "data", None) or result).strip()
    tool_transcript = extract_tool_transcript(result)
    phase_validation = validate_required_tool_phases(tool_transcript)
    if not bool(phase_validation.get("ok")):
        raise RequiredToolPhaseError(phase_validation)
    out = _normalize_answer_payload(raw)
    out["tool_transcript"] = tool_transcript
    out["tool_phase_validation"] = phase_validation
    out["agent_model"] = model_id
    return out


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
