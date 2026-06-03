from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.benchmarks.locomo_turn_crawler import locomo_crawler_callable

try:
    from pydantic_ai import Agent
except Exception:  # pragma: no cover
    Agent = None  # type: ignore

try:
    from core_memory.schema.models import CANONICAL_BEAD_TYPES as _CANONICAL_TYPES
except Exception:  # pragma: no cover
    _CANONICAL_TYPES = {
        "context", "decision", "goal", "outcome", "lesson", "reflection",
        "incident", "hypothesis", "evidence", "data_insight", "precedent",
        "design_principle", "blocked", "checkpoint", "session_start",
        "session_end", "tool_call",
    }

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

# Types worth distinguishing for LoCoMo personal-conversation replay. The full
# canonical set is allowed, but the prompt steers toward the ones that actually
# occur in these dialogues; anything else coerces to "context" (matching the
# library's unknown-type policy).
_SYSTEM_PROMPT = (
    "You classify and enrich a single turn from a personal conversation into one "
    "memory bead using the Core Memory schema. Choose the single best type:\n"
    "- context: a stated fact, event, or piece of personal information (the default).\n"
    "- decision: the speaker chose or committed to something.\n"
    "- goal: a stated intention or plan for the future.\n"
    "- outcome: the result of an action or event.\n"
    "- lesson: a learning, realization, or takeaway.\n"
    "- reflection: a feeling, opinion, or self-assessment.\n"
    "- incident: a problem, setback, or something that went wrong.\n"
    "Extract structured fields. Resolve relative dates (yesterday, last week) "
    "against the session date when present. Return STRICT JSON only, no prose."
)


def _coerce_type(value: Any) -> str:
    t = str(value or "").strip().lower()
    return t if t in _CANONICAL_TYPES else "context"


def _as_list(value: Any, *, limit: int = 12) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = []
    out: list[str] = []
    for x in items:
        s = str(x or "").strip()
        if s and s not in out:
            out.append(s)
    return out[:limit]


def _build_prompt(*, turn_text: str, speaker: str, session_date_time: str, prior: list[dict[str, Any]]) -> str:
    prior_lines = []
    for row in (prior or [])[-6:]:
        t = str(row.get("title") or "").strip()
        if t:
            prior_lines.append(f"- {t}")
    prior_block = "\n".join(prior_lines) or "(none)"
    return (
        f"Speaker: {speaker or 'unknown'}\n"
        f"Session date: {session_date_time or 'unknown'}\n"
        f"Recent prior beads (for context only):\n{prior_block}\n\n"
        f"Turn text:\n{turn_text}\n\n"
        "Return STRICT JSON with keys:\n"
        "  type: one of context|decision|goal|outcome|lesson|reflection|incident\n"
        "  title: the single key fact in <=160 chars, no speaker prefix\n"
        "  summary: [one short sentence]\n"
        "  entities: [proper nouns / concrete topics mentioned]\n"
        "  because: [causal antecedent(s), only if explicitly stated, else []]\n"
        "  state_change: short phrase if this turn changes a fact/status, else \"\"\n"
        "  effective_from: ISO date or month/year the fact takes effect, else \"\"\n"
        "  observed_at: the session date if known, else \"\"\n"
    )


def _parse(raw: str) -> dict[str, Any] | None:
    text = _JSON_FENCE_RE.sub("", str(raw or "").strip()).strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        loaded = json.loads(text)
    except Exception:
        return None
    return dict(loaded) if isinstance(loaded, dict) else None


async def _enrich_async(*, model_id: str, turn_text: str, speaker: str, session_date_time: str, prior: list[dict[str, Any]]) -> dict[str, Any] | None:
    if Agent is None:
        raise RuntimeError("pydantic_ai_unavailable")
    agent = Agent(model_id, system_prompt=_SYSTEM_PROMPT)
    result = await agent.run(_build_prompt(turn_text=turn_text, speaker=speaker, session_date_time=session_date_time, prior=prior))
    raw = str(getattr(result, "output", None) or getattr(result, "data", None) or result).strip()
    return _parse(raw)


def locomo_llm_crawler_callable(payload: dict[str, Any], *, model_id: str) -> dict[str, Any]:
    """LLM-backed LoCoMo crawler: classify + enrich each replay turn into a typed,
    schema-rich bead, exercising the Core Memory bead schema (types + because /
    entities / state_change / effective_from) that the deterministic crawler
    leaves as a flat ``context`` bead.

    Association/graph linking is delegated to the deterministic crawler so graph
    connectivity stays reliable; only the single created bead is LLM-enriched.
    On any LLM failure the deterministic bead is returned unchanged, so the
    corpus is always complete (a per-turn LLM hiccup never drops a turn).
    """
    base = locomo_crawler_callable(payload) or {}
    base_beads = list(base.get("beads_create") or [])
    if not base_beads or not str(model_id or "").strip():
        return base
    if str((dict((payload or {}).get("request") or {}).get("metadata") or {}).get("replay_source") or "") != "locomo":
        return base

    req = dict((payload or {}).get("request") or {})
    md = dict(req.get("metadata") or {})
    ctx = dict((payload or {}).get("crawler_context") or {})
    turn_text = str(req.get("turn_text") or req.get("assistant_final") or req.get("user_query") or "").strip()
    if not turn_text:
        return base
    speaker = str(md.get("locomo_speaker") or "").strip()
    session_date_time = str(md.get("locomo_session_date_time") or md.get("session_date_time") or "").strip()
    prior = [dict(r or {}) for r in list(ctx.get("beads") or []) if isinstance(r, dict)]

    try:
        enriched = asyncio.run(_enrich_async(model_id=str(model_id), turn_text=turn_text, speaker=speaker, session_date_time=session_date_time, prior=prior))
    except Exception:
        enriched = None
    if not enriched:
        return base

    bead = dict(base_beads[0])
    bead["type"] = _coerce_type(enriched.get("type"))
    title = str(enriched.get("title") or "").strip()
    if title:
        bead["title"] = title[:160]
    summary = _as_list(enriched.get("summary"), limit=3)
    if summary:
        bead["summary"] = summary
    # Merge LLM entities with the deterministic entity set (keep both signals).
    merged_entities = _as_list(list(bead.get("entities") or []) + _as_list(enriched.get("entities")), limit=16)
    if merged_entities:
        bead["entities"] = merged_entities
    because = _as_list(enriched.get("because"), limit=4)
    if because:
        bead["because"] = because
    state_change = str(enriched.get("state_change") or "").strip()
    if state_change:
        bead["state_change"] = state_change
    effective_from = str(enriched.get("effective_from") or "").strip()
    if effective_from:
        bead["effective_from"] = effective_from
    observed_at = str(enriched.get("observed_at") or "").strip() or session_date_time
    if observed_at:
        bead["observed_at"] = observed_at
    tags = list(bead.get("tags") or [])
    if "llm_enriched" not in tags:
        tags.append("llm_enriched")
    bead["tags"] = tags

    return {"beads_create": [bead], "associations": list(base.get("associations") or [])}
