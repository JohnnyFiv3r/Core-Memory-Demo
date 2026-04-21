from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None

from core_memory.entity.merge_flow import (
    decide_entity_merge_proposal,
    suggest_entity_merge_proposals,
)
from core_memory.integrations.api import (
    get_turn,
    inspect_bead,
    inspect_bead_hydration,
    inspect_claim_slot,
    inspect_state,
    list_turn_summaries,
)
from core_memory.integrations.pydanticai.memory_tools import (
    continuity_prompt,
    memory_execute_tool,
    memory_search_tool,
    memory_trace_tool,
)
from core_memory.integrations.pydanticai.run import run_with_memory
from core_memory.retrieval.tools import memory as memory_tools
from core_memory.retrieval.normalize import classify_intent
from core_memory.persistence.store import MemoryStore
from core_memory.persistence.store_claim_ops import write_claim_updates_to_bead, write_claims_to_bead
from core_memory.runtime.engine import process_flush, process_turn_finalized
from core_memory.runtime.jobs import async_jobs_status, run_async_jobs
from core_memory.runtime.association_pass import run_association_pass
from core_memory.association.crawler_contract import merge_crawler_updates
from core_memory.write_pipeline.continuity_injection import load_continuity_injection

from app.core.config import settings


@dataclass
class SessionState:
    session_id: str
    context_budget: int
    token_usage: int = 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_as_of(value: str | None) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    if s.lower() in {"none", "null"}:
        return None
    return s


def _new_session_id() -> str:
    return f"demo-{uuid.uuid4().hex[:8]}"


SESSION = SessionState(session_id=_new_session_id(), context_budget=settings.demo_context_budget)
LAST_TURN_DIAGNOSTICS: dict[str, Any] = {}
LAST_BENCHMARK_REPORT: dict[str, Any] = {}
LAST_BENCHMARK_SUMMARY: dict[str, Any] = {}
LAST_BENCHMARK_HISTORY: list[dict[str, Any]] = []

DEFAULT_SEED_USER_MESSAGES: list[str] = [
    "Should we use MySQL or PostgreSQL for JSON-heavy service?",
    "What lesson did we learn?",
    "What evidence supports the DB decision?",
    "What project goal is pending?",
    "Why FastAPI?",
]

# Demo defaults to keep claim/association surfaces active unless explicitly overridden.
# Claim layer defaults are disabled here because heuristic claim extraction can pollute
# claim_state with assistant/meta chatter and degrade grounded retrieval quality.
# Keep this agent-driven by grounding on bead/association evidence.
os.environ.setdefault("CORE_MEMORY_CLAIM_LAYER", "0")
os.environ.setdefault("CORE_MEMORY_CLAIM_EXTRACTION_MODE", "off")
os.environ.setdefault("CORE_MEMORY_CLAIM_RESOLUTION", "0")
os.environ.setdefault("CORE_MEMORY_PREVIEW_ASSOC_PROMOTION", "1")
os.environ.setdefault("CORE_MEMORY_PREVIEW_ASSOC_ALLOW_SHARED_TAG", "1")
os.environ.setdefault("CORE_MEMORY_SEMANTIC_BUILD_ON_READ", "0")
os.environ.setdefault("CORE_MEMORY_DEMO_CHAT_SEMANTIC_MODE", "degraded_allowed")

STORY_PACK_DIR = Path(__file__).resolve().parents[3] / "demo" / "story-pack"
TURN_HEADER_RE = re.compile(r"^##\s*Turn\s+(\d{3})\s*:\s*(.+?)\s*$", re.MULTILINE)
SEND_PROMPT_RE = re.compile(r"^\*\*Send:\*\*\s*`([^`]+)`\s*$", re.MULTILINE)
ENTITY_CANDIDATE_RE = re.compile(r"\b([A-Z][A-Za-z0-9._-]{2,}|[A-Z]{2,}[A-Za-z0-9._-]*)\b")
TOKEN_ESTIMATE_SEGMENT_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_TIKTOKEN_ENCODER_CACHE: dict[str, Any] = {}

DEMO_MODEL_PRESETS: tuple[tuple[str, str], ...] = (
    ("anthropic:claude-opus-4-20250514", "Claude Opus 4"),
    ("anthropic:claude-sonnet-4-20250514", "Claude Sonnet 4"),
    ("anthropic:claude-3-5-haiku-latest", "Claude Haiku"),
    ("openai:gpt-4.1", "GPT-4.1"),
    ("openai:gpt-4o", "GPT-4o"),
    ("google-gla:gemini-2.5-pro", "Gemini 2.5 Pro"),
    ("google-gla:gemini-2.5-flash", "Gemini 2.5 Flash"),
)


def _load_story_pack_bundle(*, pack_dir: Path | None = None) -> dict[str, Any]:
    base = Path(pack_dir or STORY_PACK_DIR)
    manifest_path = base / "replay-order.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"story_pack_manifest_not_found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    acts_cfg = list(manifest.get("acts") or [])
    all_turns: list[dict[str, Any]] = []
    checkpoints: dict[int, list[dict[str, Any]]] = {}

    for act in acts_cfg:
        rel = str(act.get("file") or "").strip()
        if not rel:
            continue
        act_path = base / rel
        if not act_path.exists():
            raise FileNotFoundError(f"story_pack_act_not_found: {act_path}")

        text = act_path.read_text(encoding="utf-8")
        headers = list(TURN_HEADER_RE.finditer(text))
        turns: list[dict[str, Any]] = []
        for i, header in enumerate(headers):
            turn_no = int(header.group(1))
            title = str(header.group(2) or "").strip()
            start = header.end()
            end = headers[i + 1].start() if (i + 1) < len(headers) else len(text)
            block = text[start:end]
            send_match = SEND_PROMPT_RE.search(block)
            if not send_match:
                raise ValueError(f"story_pack_missing_send_prompt: {act_path.name} turn {turn_no:03d}")
            turns.append(
                {
                    "turn": turn_no,
                    "title": title,
                    "prompt": str(send_match.group(1) or "").strip(),
                    "act": str(act.get("act") or ""),
                    "act_title": str(act.get("title") or ""),
                    "session_hint": str(act.get("default_session") or ""),
                    "file": rel,
                }
            )

        if turns:
            expected_start = int(act.get("turn_start") or turns[0]["turn"])
            expected_end = int(act.get("turn_end") or turns[-1]["turn"])
            if turns[0]["turn"] != expected_start or turns[-1]["turn"] != expected_end:
                raise ValueError(
                    f"story_pack_turn_range_mismatch: {act_path.name}"
                    f" expected={expected_start:03d}-{expected_end:03d}"
                    f" parsed={turns[0]['turn']:03d}-{turns[-1]['turn']:03d}"
                )
            all_turns.extend(turns)

        for cp in list(act.get("checkpoints") or []):
            after_turn = int(cp.get("after_turn") or 0)
            if after_turn <= 0:
                continue
            row = dict(cp or {})
            row["act"] = str(act.get("act") or "")
            row["act_title"] = str(act.get("title") or "")
            checkpoints.setdefault(after_turn, []).append(row)

    all_turns = sorted(all_turns, key=lambda x: int(x.get("turn") or 0))
    turn_numbers = [int(x.get("turn") or 0) for x in all_turns]
    if turn_numbers:
        expected = list(range(turn_numbers[0], turn_numbers[-1] + 1))
        if turn_numbers != expected:
            raise ValueError("story_pack_turns_not_contiguous")

    return {
        "manifest": manifest,
        "pack_dir": str(base),
        "turns": all_turns,
        "checkpoints": checkpoints,
    }


def get_story_pack_meta() -> dict[str, Any]:
    bundle = _load_story_pack_bundle()
    manifest = dict(bundle.get("manifest") or {})
    turns = list(bundle.get("turns") or [])
    checkpoints = dict(bundle.get("checkpoints") or {})

    first_turn = int(turns[0].get("turn") or 0) if turns else 0
    last_turn = int(turns[-1].get("turn") or 0) if turns else 0
    checkpoint_count = sum(len(list(v or [])) for v in checkpoints.values())

    return {
        "ok": True,
        "pack_name": str(manifest.get("pack_name") or "story-pack"),
        "format_version": int(manifest.get("format_version") or 1),
        "total_turns": int(manifest.get("total_turns") or len(turns)),
        "loaded_turns": int(len(turns)),
        "turn_range": {"first": first_turn, "last": last_turn},
        "checkpoints": int(checkpoint_count),
        "sessions": dict(manifest.get("sessions") or {}),
        "acts": [
            {
                "act": str(a.get("act") or ""),
                "title": str(a.get("title") or ""),
                "turn_start": int(a.get("turn_start") or 0),
                "turn_end": int(a.get("turn_end") or 0),
                "file": str(a.get("file") or ""),
            }
            for a in list(manifest.get("acts") or [])
        ],
    }


def _provider_from_model_id(model_id: str) -> str:
    mid = str(model_id or "").strip().lower()
    if not mid:
        return ""
    if ":" in mid:
        return mid.split(":", 1)[0].strip()
    if "/" in mid:
        return mid.split("/", 1)[0].strip()
    return mid


def _required_api_key_env_for_model(model_id: str) -> str | None:
    provider = _provider_from_model_id(model_id)
    if provider in {"openai"}:
        return "OPENAI_API_KEY"
    if provider in {"anthropic"}:
        return "ANTHROPIC_API_KEY"
    if provider in {"google", "gemini", "google-gla"}:
        # Google adapters commonly use one of these.
        return "GEMINI_API_KEY|GOOGLE_API_KEY"
    return None


def _model_has_required_credentials(model_id: str) -> bool:
    req = _required_api_key_env_for_model(model_id)
    if not req:
        return True
    if "|" in req:
        keys = [x.strip() for x in req.split("|") if x.strip()]
        return any(bool(os.getenv(k)) for k in keys)
    return bool(os.getenv(req))


_MODEL_OVERRIDE: str = ""


def detect_model() -> str:
    override = str(_MODEL_OVERRIDE or "").strip()
    if override and _model_has_required_credentials(override):
        return override

    configured = settings.demo_model_id.strip()
    if configured and _model_has_required_credentials(configured):
        return configured

    # If configured model is missing credentials, fall through to supported fallbacks.
    if os.getenv("OPENAI_API_KEY"):
        return "openai:gpt-4o"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic:claude-sonnet-4-20250514"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "google-gla:gemini-2.5-flash"
    return ""


def list_demo_model_options() -> dict[str, Any]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()

    for model_id, label in DEMO_MODEL_PRESETS:
        mid = str(model_id or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        options.append(
            {
                "model_id": mid,
                "label": str(label or mid),
                "available": bool(_model_has_required_credentials(mid)),
                "required_env": _required_api_key_env_for_model(mid),
            }
        )

    configured = str(settings.demo_model_id or "").strip()
    if configured and configured not in seen:
        options.append(
            {
                "model_id": configured,
                "label": configured,
                "available": bool(_model_has_required_credentials(configured)),
                "required_env": _required_api_key_env_for_model(configured),
            }
        )

    return {
        "ok": True,
        "selected_model": str(_MODEL_OVERRIDE or "").strip() or detect_model(),
        "auto_model": detect_model(),
        "override_model": str(_MODEL_OVERRIDE or "").strip(),
        "configured_model": configured,
        "options": options,
    }


def _model_context_window_tokens(model_id: str) -> int | None:
    configured_override_keys = [
        "CORE_MEMORY_DEMO_MODEL_CONTEXT_WINDOW",
        "DEMO_MODEL_CONTEXT_WINDOW",
        "CORE_MEMORY_SOURCE_MODEL_CONTEXT_WINDOW",
    ]
    for key in configured_override_keys:
        raw = str(os.getenv(key) or "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except Exception:
            continue
        if value > 0:
            return value

    mid = str(model_id or "").strip().lower()
    if not mid:
        return None

    # Provider/model-family conservative defaults.
    if "gpt-4o" in mid:
        return 128_000
    if "gpt-4.1" in mid:
        return 1_000_000
    if "gpt-5" in mid:
        return 400_000
    if "claude-sonnet-4" in mid or "claude-3.7" in mid or "claude-3-7" in mid:
        return 200_000
    if "claude-3.5" in mid or "claude-3-5" in mid:
        return 200_000
    if "gemini-2.5" in mid:
        return 1_048_576
    if "gemini-1.5" in mid:
        return 1_000_000

    provider = _provider_from_model_id(mid)
    if provider == "openai":
        return 128_000
    if provider in {"anthropic"}:
        return 200_000
    if provider in {"google", "gemini", "google-gla"}:
        return 1_000_000
    return None


def _resolved_context_budget_tokens() -> int:
    model_id = detect_model()
    inferred = _model_context_window_tokens(model_id)
    if inferred and int(inferred) > 0:
        return int(inferred)

    configured = int(getattr(settings, "demo_context_budget", 0) or 0)
    if configured > 0:
        return configured
    return 10_000


def _sync_session_context_budget() -> int:
    budget = max(1_000, int(_resolved_context_budget_tokens()))
    SESSION.context_budget = budget
    return budget


_sync_session_context_budget()


def create_agent(model_id: str):
    from pydantic_ai import Agent

    agent = Agent(
        model_id,
        system_prompt=(
            "You are a helpful project assistant. You have access to the team's "
            "persistent memory — decisions, lessons, goals, and context from prior "
            "conversations. Use your memory tools proactively to ground your answers "
            "in what the team has recorded. Be specific and cite what you find. "
            "Tool policy: call execute_memory_request first for recall questions; "
            "use search_memory as a secondary check; use trace_memory for "
            "explicit causal trace questions. Do not claim memory is missing unless "
            "both execute and search return no anchors/results."
        ),
        tools=[
            memory_execute_tool(root=settings.core_memory_root),
            memory_search_tool(root=settings.core_memory_root),
            memory_trace_tool(root=settings.core_memory_root),
        ],
    )

    @agent.system_prompt
    def inject_memory():
        return continuity_prompt(root=settings.core_memory_root, session_id=SESSION.session_id)

    return agent


_AGENT: Any | None = None
_AGENT_MODEL: str = ""
_ASSOC_JUDGE_AGENT: Any | None = None
_ASSOC_JUDGE_MODEL: str = ""

ALLOWED_ASSOC_RELATIONS: tuple[str, ...] = (
    "caused_by",
    "led_to",
    "blocked_by",
    "unblocks",
    "enables",
    "supports",
    "reinforces",
    "contradicts",
    "invalidates",
    "supersedes",
    "superseded_by",
    "resolves",
    "diagnoses",
    "derived_from",
    "follows",
    "precedes",
    "similar_pattern",
    "mirrors",
    "structural_symmetry",
    "applies_pattern_of",
    "violates_pattern_of",
    "generalizes",
    "specializes",
    "refines",
    "transferable_lesson",
    "reveals_bias",
    "constraint_transformed_into",
    "solves_same_mechanism",
    "associated_with",
)

_ASSOC_SPECIFIC_RELATIONS: set[str] = {
    "caused_by",
    "led_to",
    "blocked_by",
    "unblocks",
    "enables",
    "supports",
    "reinforces",
    "invalidates",
    "superseded_by",
    "resolves",
    "diagnoses",
    "precedes",
    "similar_pattern",
    "mirrors",
    "structural_symmetry",
    "applies_pattern_of",
    "violates_pattern_of",
    "generalizes",
    "specializes",
    "refines",
    "transferable_lesson",
    "reveals_bias",
    "constraint_transformed_into",
    "solves_same_mechanism",
    "supersedes",
    "contradicts",
}

ASSOC_JUDGE_INSTRUCTION_BLOCK = """
Use the strongest honest fit for every label.
Prefer specific, grounded meaning over vague defaults.

Read every edge as: source RELATION target.
Use follows only for meaningful sequence adjacency.
Use derived_from only when no stronger semantic relation is justified.

Allowed relationships and intent:
- caused_by: source happened because target directly created the condition/mechanism
- led_to: source contributed forward into target as downstream consequence
- blocked_by: source could not proceed because target obstructed it
- unblocks: source removes the blocker on target
- enables: source makes target possible or practical
- supports: source gives meaningful support to target
- reinforces: source strengthens confidence in target through repeated/independent agreement
- contradicts: source and target cannot both stand as written
- invalidates: source makes target no longer valid
- supersedes: source replaces target as newer/current version
- superseded_by: source has been replaced by target
- resolves: source settles or fixes the issue/open state in target
- diagnoses: source identifies the underlying mechanism behind target
- derived_from: source was built or inferred from target
- follows: source comes after target in a meaningful sequence
- precedes: source comes before target in a meaningful sequence
- similar_pattern: shared reusable pattern, but no stronger transfer/structure claim
- mirrors: notably parallel dynamics
- structural_symmetry: matching internal role structure
- applies_pattern_of: source deliberately reuses target's pattern
- violates_pattern_of: source breaks the pattern target suggests
- generalizes: source is a broader abstraction of target
- specializes: source is a narrower instance of target
- refines: source sharpens target without replacing it
- transferable_lesson: lesson from source should be reused in target context
- reveals_bias: source exposes a blind spot or recurrent reasoning error in target
- constraint_transformed_into: former limit became a reusable rule/pattern elsewhere
- solves_same_mechanism: source and target address the same underlying mechanism
- associated_with: meaningful relation exists, but no stronger relation is justified

Never invent facts or ids.
Do not use weak fallback labels as convenience defaults.
If unsure, omit the edge.
""".strip()


def set_demo_model_override(model_id: str | None) -> dict[str, Any]:
    global _MODEL_OVERRIDE, _AGENT, _AGENT_MODEL, _ASSOC_JUDGE_AGENT, _ASSOC_JUDGE_MODEL
    req_model = str(model_id or "").strip()

    if not req_model:
        _MODEL_OVERRIDE = ""
    else:
        if not _model_has_required_credentials(req_model):
            req = _required_api_key_env_for_model(req_model) or "provider credentials"
            raise RuntimeError(f"missing_model_credentials: '{req_model}' requires {req}")
        _MODEL_OVERRIDE = req_model

    _AGENT = None
    _AGENT_MODEL = ""
    _ASSOC_JUDGE_AGENT = None
    _ASSOC_JUDGE_MODEL = ""
    _sync_session_context_budget()
    return list_demo_model_options()


def get_agent() -> Any:
    global _AGENT, _AGENT_MODEL
    _sync_session_context_budget()
    model = detect_model()
    if not model:
        configured = settings.demo_model_id.strip()
        if configured:
            req = _required_api_key_env_for_model(configured)
            if req:
                raise RuntimeError(f"missing_model_credentials: configured model '{configured}' requires {req}")
        raise RuntimeError("no_model_configured: set DEMO_MODEL_ID with matching provider credentials, or set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY")

    if _AGENT is not None and _AGENT_MODEL == model:
        return _AGENT

    _AGENT = create_agent(model)
    _AGENT_MODEL = model
    return _AGENT


def _get_assoc_judge_agent() -> Any | None:
    global _ASSOC_JUDGE_AGENT, _ASSOC_JUDGE_MODEL
    model = detect_model().strip()
    if not model:
        return None
    if _ASSOC_JUDGE_AGENT is not None and _ASSOC_JUDGE_MODEL == model:
        return _ASSOC_JUDGE_AGENT
    try:
        from pydantic_ai import Agent

        _ASSOC_JUDGE_AGENT = Agent(
            model,
            system_prompt=(
                "You are a strict memory graph association judge. "
                "Only emit relationships that are directly supported by provided evidence. "
                "Use strongest honest-fit labeling and avoid weak defaults when stronger semantics are justified. "
                "Interpret all links as source RELATION target. "
                "Output JSON only."
            ),
        )
        _ASSOC_JUDGE_MODEL = model
        return _ASSOC_JUDGE_AGENT
    except Exception:
        return None


def inspect_state_payload(*, as_of: str | None = None) -> dict[str, Any]:
    as_of_n = _normalize_as_of(as_of)
    base = inspect_state(
        root=settings.core_memory_root,
        session_id=SESSION.session_id,
        as_of=as_of_n,
        limit_beads=300,
        limit_associations=300,
        limit_flushes=20,
        limit_merge_proposals=40,
    )
    out = dict(base or {})
    out["session"] = {
        "session_id": SESSION.session_id,
        "token_usage": SESSION.token_usage,
        "context_budget": SESSION.context_budget,
    }

    rolling_token_estimate = 0
    rolling_token_budget = 0
    rolling_record_count = 0
    try:
        continuity = load_continuity_injection(settings.core_memory_root)
        continuity_meta = dict((continuity or {}).get("meta") or {})
        continuity_records = list((continuity or {}).get("records") or [])
        rolling_token_estimate = int(continuity_meta.get("token_estimate") or 0)
        rolling_token_budget = int(continuity_meta.get("token_budget") or 0)
        rolling_record_count = int(continuity_meta.get("record_count") or len(continuity_records))
    except Exception:
        rolling_token_estimate = 0
        rolling_token_budget = 0
        rolling_record_count = 0

    out["session"].update(
        {
            "rolling_window_token_estimate": rolling_token_estimate,
            "rolling_window_token_budget": rolling_token_budget,
            "rolling_window_record_count": rolling_record_count,
            "selected_model": detect_model(),
            "model_override": str(_MODEL_OVERRIDE or "").strip(),
            "configured_model": str(settings.demo_model_id or "").strip(),
        }
    )
    out["last_turn"] = dict(LAST_TURN_DIAGNOSTICS or {})
    benchmark_snapshot = get_last_benchmark_snapshot(history_limit=20)
    out["benchmark"] = {
        "last_summary": dict(benchmark_snapshot.get("summary") or {}),
        "has_last_report": bool(benchmark_snapshot.get("report") or {}),
        "history": list(benchmark_snapshot.get("history") or [])[:20],
    }

    # Backward-compat projection fields used by current UI
    mem = dict(out.get("memory") or {})
    claims = dict(out.get("claims") or {})
    stats = dict(out.get("stats") or {})
    entities = dict(out.get("entities") or {})
    out["beads"] = list(mem.get("beads") or [])
    out["associations"] = list(mem.get("associations") or [])
    out["rolling_window"] = list(mem.get("rolling_window") or [])
    out["claim_state"] = list(claims.get("slots") or [])
    out["stats"] = {
        "total_beads": int(stats.get("total_beads") or len(out["beads"])),
        "total_associations": int(stats.get("total_associations") or len(out["associations"])),
        "rolling_window_size": int(stats.get("rolling_window_size") or len(out["rolling_window"])),
        "rolling_window_token_estimate": rolling_token_estimate,
        "rolling_window_token_budget": rolling_token_budget,
        "rolling_window_record_count": rolling_record_count,
        "claim_slot_count": int(stats.get("claim_slot_count") or len(out["claim_state"])),
        "entity_count": int(stats.get("entity_count") or len(list(entities.get("rows") or []))),
        "session_id": SESSION.session_id,
        "token_usage": SESSION.token_usage,
        "context_budget": SESSION.context_budget,
    }
    return out


def _token_estimator_model_name(model_id: str | None) -> str:
    mid = str(model_id or "").strip()
    if ":" in mid:
        mid = mid.split(":", 1)[1].strip()
    if "/" in mid:
        mid = mid.split("/", 1)[1].strip()
    return mid


def _tiktoken_encoder(model_id: str | None) -> Any | None:
    if tiktoken is None:
        return None

    model_name = _token_estimator_model_name(model_id)
    cache_key = model_name or "cl100k_base"
    cached = _TIKTOKEN_ENCODER_CACHE.get(cache_key)
    if cached is not None:
        return cached

    enc = None
    if model_name:
        try:
            enc = tiktoken.encoding_for_model(model_name)
        except Exception:
            enc = None

    if enc is None:
        try:
            enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            enc = None

    if enc is not None:
        _TIKTOKEN_ENCODER_CACHE[cache_key] = enc
    return enc


def _is_cjk_char(ch: str) -> bool:
    return (
        ("\u4e00" <= ch <= "\u9fff")
        or ("\u3400" <= ch <= "\u4dbf")
        or ("\u3040" <= ch <= "\u30ff")
        or ("\uac00" <= ch <= "\ud7af")
    )


def _estimate_text_tokens(text: str, *, model_id: str | None = None) -> int:
    s = str(text or "")
    if not s:
        return 0

    enc = _tiktoken_encoder(model_id)
    if enc is not None:
        try:
            return max(1, int(len(enc.encode(s, disallowed_special=()))))
        except Exception:
            pass

    utf8_bytes = len(s.encode("utf-8", errors="ignore"))
    by_bytes = (utf8_bytes + 3) // 4

    segments = len(TOKEN_ESTIMATE_SEGMENT_RE.findall(s))
    by_segments = (segments * 3 + 1) // 2

    cjk_chars = sum(1 for ch in s if _is_cjk_char(ch))
    by_cjk = cjk_chars + max(0, (utf8_bytes - cjk_chars) // 5)

    newlines = s.count("\n")
    newline_overhead = max(0, newlines // 4)

    return max(1, int(max(by_bytes, by_segments, by_cjk) + newline_overhead))


def record_turn_tokens(user_query: str, assistant_response: str, *, model_id: str | None = None) -> None:
    user_tokens = _estimate_text_tokens(user_query, model_id=model_id)
    assistant_tokens = _estimate_text_tokens(assistant_response, model_id=model_id)
    framing_overhead = 24
    SESSION.token_usage += max(1, int(user_tokens + assistant_tokens + framing_overhead))


def _heuristic_entities(*texts: str, limit: int = 16) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    stop = {
        "Before", "Show", "Open", "Record", "Add", "Explain", "What", "When", "Where", "Which", "Why", "How",
        "Turn", "Act", "Graph", "Claims", "Entities", "Runtime", "Benchmark", "Send", "Point", "Say",
    }
    for raw in texts:
        text = str(raw or "")
        if not text:
            continue
        for m in ENTITY_CANDIDATE_RE.finditer(text):
            token = str(m.group(1) or "").strip().strip(".,:;!?()[]{}\"'")
            if len(token) < 3:
                continue
            if token in stop:
                continue
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(token)
            if len(out) >= max(1, int(limit)):
                return out
    return out


def _seed_crawler_updates(*, user_query: str, turn_id: str) -> dict[str, Any]:
    uq = str(user_query or "").strip()
    entities = _heuristic_entities(uq)
    title = (uq or "Turn memory").splitlines()[0][:160]
    bead_type = _infer_seed_bead_type(uq)
    return {
        "beads_create": [
            {
                "type": bead_type,
                "title": title or "Turn memory",
                "summary": [uq[:240]] if uq else ["turn memory"],
                "because": [uq[:240]] if uq else [],
                "source_turn_ids": [str(turn_id or "")],
                "entities": entities,
                "tags": ["demo_seed", "crawler_reviewed", "turn_finalized"],
            }
        ]
    }


def _infer_seed_bead_type(user_query: str) -> str:
    text = str(user_query or "").strip().lower()
    if not text:
        return "context"
    if any(x in text for x in ["decide", "decision", "chose", "choose", "selected", "approved", "policy"]):
        return "decision"
    if any(x in text for x in ["goal", "objective", "target", "milestone", "pending", "plan"]):
        return "goal"
    if any(x in text for x in ["evidence", "because", "proof", "supports", "why"]):
        return "evidence"
    if any(x in text for x in ["outcome", "result", "completed", "shipped", "done"]):
        return "outcome"
    if any(x in text for x in ["lesson", "learned", "learning"]):
        return "lesson"
    if any(x in text for x in ["checkpoint", "flush", "session"]):
        return "checkpoint"
    return "context"


def _bead_entities(bead: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for x in list((bead or {}).get("entities") or []):
        token = str(x or "").strip()
        if token:
            out.add(token.lower())
    return out


def _bead_text(bead: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "detail"):
        val = str((bead or {}).get(key) or "").strip()
        if val:
            parts.append(val)
    for key in ("summary", "because", "retrieval_facts"):
        vals = list((bead or {}).get(key) or [])
        for v in vals:
            s = str(v or "").strip()
            if s:
                parts.append(s)
    return "\n".join(parts)


_ASSOC_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "our", "their",
    "were", "was", "have", "has", "had", "will", "would", "should", "could", "can", "cant",
    "about", "after", "before", "then", "than", "because", "there", "here", "when", "where",
    "what", "which", "who", "whom", "whose", "why", "how", "turn", "main", "session",
}


def _bead_tokens(bead: dict[str, Any], limit: int = 128) -> set[str]:
    text = _bead_text(bead).lower()
    out: set[str] = set()
    for tok in re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", text):
        if tok in _ASSOC_STOPWORDS:
            continue
        out.add(tok)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _session_turn_bead_ids(beads: dict[str, Any], *, session_id: str) -> list[str]:
    rows: list[dict[str, Any]] = []
    for b in beads.values():
        if not isinstance(b, dict):
            continue
        if str(b.get("session_id") or "") != str(session_id):
            continue
        if not list(b.get("source_turn_ids") or []):
            continue
        rows.append(b)
    rows.sort(key=lambda x: str((x or {}).get("created_at") or ""))
    return [str((r or {}).get("id") or "") for r in rows if str((r or {}).get("id") or "")]


def _cue_flags(text: str) -> dict[str, bool]:
    t = str(text or "").lower()
    return {
        "support": bool(any(x in t for x in ["because", "evidence", "supports", "proof", "confirmed", "validated"])),
        "supersede": bool(any(x in t for x in ["supersede", "superseded", "replaced", "instead of", "no longer use"])),
        "contradict": bool(any(x in t for x in ["contradict", "conflict", "wrong", "not true", "incorrect", "no longer"])),
        "caused_by": bool(any(x in t for x in ["because of", "due to", "caused by"])),
        "enables": bool(any(x in t for x in ["enables", "allows", "lets us", "made possible"])),
        "unblocks": bool(any(x in t for x in ["unblock", "unblocked", "resolved blocker", "not blocked"])),
        "blocked_by": bool(any(x in t for x in ["blocked by", "blocking", "cannot proceed", "stuck on"])),
    }


def _extract_json_object_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, flags=re.IGNORECASE)
    if m:
        return str(m.group(1) or "").strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return ""


async def _agent_judged_links_for_turn(*, current_id: str, ordered_ids: list[str], beads: dict[str, Any], max_links: int = 20) -> tuple[list[dict[str, Any]], list[str], bool, str]:
    current = dict(beads.get(str(current_id)) or {})
    if not current:
        return [], [], False, "current_bead_missing"
    if str(current_id) not in ordered_ids:
        return [], [], False, "current_bead_not_in_session_order"

    judge = _get_assoc_judge_agent()
    if judge is None:
        return [], [], False, "judge_unavailable"

    pos = ordered_ids.index(str(current_id))
    prior_ids = list(reversed(ordered_ids[:pos]))
    if not prior_ids:
        return [], [str(current_id)], True, ""

    current_entities = _bead_entities(current)
    current_tokens = _bead_tokens(current)

    candidates: list[dict[str, Any]] = []
    for target_id in prior_ids[:60]:
        target = dict(beads.get(str(target_id)) or {})
        if not target:
            continue
        shared_entities = sorted(current_entities.intersection(_bead_entities(target)))
        shared_terms = sorted(current_tokens.intersection(_bead_tokens(target)))
        score = (5 * len(shared_entities)) + min(6, len(shared_terms))
        if score <= 0:
            continue
        candidates.append(
            {
                "target_bead_id": str(target_id),
                "target_title": str(target.get("title") or "")[:140],
                "target_type": str(target.get("type") or ""),
                "target_summary": " ".join(str(x or "") for x in list(target.get("summary") or [])[:2])[:220],
                "target_excerpt": _bead_text(target)[:360],
                "shared_entities": shared_entities[:5],
                "shared_terms": shared_terms[:8],
                "evidence_score": int(score),
            }
        )

    if prior_ids and not any(str(c.get("target_bead_id") or "") == str(prior_ids[0]) for c in candidates):
        prev = dict(beads.get(str(prior_ids[0])) or {})
        candidates.append(
            {
                "target_bead_id": str(prior_ids[0]),
                "target_title": str(prev.get("title") or "")[:140],
                "target_type": str(prev.get("type") or ""),
                "target_summary": " ".join(str(x or "") for x in list(prev.get("summary") or [])[:2])[:220],
                "target_excerpt": _bead_text(prev)[:360],
                "shared_entities": [],
                "shared_terms": [],
                "evidence_score": 1,
            }
        )

    candidates.sort(key=lambda x: int(x.get("evidence_score") or 0), reverse=True)
    candidates = candidates[:18]
    candidate_ids = {str(c.get("target_bead_id") or "") for c in candidates}

    prompt = {
        "task": "Judge memory associations for the current bead. Add any allowed relations that apply and are directly supported.",
        "instruction_block": ASSOC_JUDGE_INSTRUCTION_BLOCK,
        "orientation": "source=current bead, target=prior bead, relation means source RELATION target",
        "rules": [
            "Only output links you can support from provided evidence.",
            "Do not invent bead ids or facts.",
            "Use only allowed relationship values.",
            "If unsure, omit the link.",
            "Prefer specific semantic relations over generic derived_from when evidence supports them.",
            "Use follows mainly for temporal adjacency.",
            "Do not emit follows for non-adjacent targets unless sequence evidence is explicit.",
        ],
        "allowed_relationships": list(ALLOWED_ASSOC_RELATIONS),
        "relation_guidance": {
            "caused_by": "source happened because target directly created the condition/mechanism",
            "led_to": "source contributed forward into target as downstream consequence",
            "blocked_by": "source could not proceed because target obstructed it",
            "unblocks": "source removes the blocker on target",
            "enables": "source makes target possible or practical",
            "supports": "source gives meaningful support to target",
            "reinforces": "source strengthens confidence in target through repeated or independent agreement",
            "contradicts": "source and target cannot both stand as written",
            "invalidates": "source makes target no longer valid",
            "supersedes": "source replaces target as newer/current version",
            "superseded_by": "source has been replaced by target",
            "resolves": "source settles or fixes the issue/open state in target",
            "diagnoses": "source identifies the underlying mechanism behind target",
            "derived_from": "source was built or inferred from target",
            "follows": "source comes after target in a meaningful sequence",
            "precedes": "source comes before target in a meaningful sequence",
            "similar_pattern": "shared reusable pattern, but no stronger transfer/structure claim",
            "mirrors": "notably parallel dynamics",
            "structural_symmetry": "matching internal role structure",
            "applies_pattern_of": "source deliberately reuses target's pattern",
            "violates_pattern_of": "source breaks the pattern target suggests",
            "generalizes": "source is a broader abstraction of target",
            "specializes": "source is a narrower instance of target",
            "refines": "source sharpens target without replacing it",
            "transferable_lesson": "lesson from source should be reused in target context",
            "reveals_bias": "source exposes a blind spot or recurrent reasoning error in target",
            "constraint_transformed_into": "former limit became a reusable rule/pattern elsewhere",
            "solves_same_mechanism": "source and target address the same underlying mechanism",
            "associated_with": "meaningful relation exists, but no stronger relation is justified",
        },
        "current": {
            "bead_id": str(current_id),
            "title": str(current.get("title") or "")[:180],
            "type": str(current.get("type") or ""),
            "summary": [str(x or "")[:220] for x in list(current.get("summary") or [])[:3]],
            "excerpt": _bead_text(current)[:500],
            "entities": sorted(list(current_entities))[:10],
            "cue_flags": _cue_flags(_bead_text(current)),
        },
        "candidate_targets": candidates,
        "output_schema": {
            "associations": [
                {
                    "target_bead_id": "string",
                    "relationship": "one_of_allowed_relationships",
                    "confidence": "0..1",
                    "reason_text": "short evidence-grounded reason",
                }
            ]
        },
    }

    try:
        resp = await judge.run(json.dumps(prompt, ensure_ascii=False))
        text = str(getattr(resp, "output", None) or getattr(resp, "data", None) or resp)
        payload_text = _extract_json_object_text(text)
        parsed = json.loads(payload_text) if payload_text else {}
    except Exception:
        return [], [], False, "judge_invoke_or_parse_failed"

    links: list[dict[str, Any]] = []
    referenced_ids: set[str] = {str(current_id)}
    seen: set[tuple[str, str, str]] = set()
    adjacency_target = str(prior_ids[0]) if prior_ids else ""

    valid_rows: list[tuple[str, str, float, str]] = []
    for row in list((parsed or {}).get("associations") or []):
        if not isinstance(row, dict):
            continue
        target_id = str(row.get("target_bead_id") or "").strip()
        rel = str(row.get("relationship") or "").strip().lower()
        if not target_id or target_id not in candidate_ids:
            continue
        if rel not in ALLOWED_ASSOC_RELATIONS:
            continue
        try:
            conf = float(row.get("confidence"))
        except Exception:
            conf = 0.6
        conf = max(0.0, min(1.0, conf))
        reason = str(row.get("reason_text") or "").strip()[:300]
        if not reason:
            reason = "agent-judged from provided candidate evidence"
        valid_rows.append((target_id, rel, conf, reason))

    specific_by_target: dict[str, bool] = {}
    for target_id, rel, _conf, _reason in valid_rows:
        if rel in _ASSOC_SPECIFIC_RELATIONS:
            specific_by_target[target_id] = True

    non_weak_by_target: dict[str, bool] = {}
    for target_id, rel, _conf, _reason in valid_rows:
        if rel not in {"associated_with"}:
            non_weak_by_target[target_id] = True

    follows_emitted = False
    for target_id, rel, conf, reason in valid_rows:
        if len(links) >= max(1, int(max_links)):
            break

        if rel == "follows":
            if follows_emitted:
                continue
            if adjacency_target and target_id != adjacency_target:
                continue
            follows_emitted = True

        if rel == "derived_from" and bool(specific_by_target.get(target_id)):
            continue

        if rel == "associated_with" and bool(non_weak_by_target.get(target_id)):
            continue

        key = (str(current_id), target_id, rel)
        if key in seen:
            continue
        seen.add(key)

        links.append(
            {
                "source_bead_id": str(current_id),
                "target_bead_id": str(target_id),
                "relationship": rel,
                "confidence": round(conf, 3),
                "reason_text": reason,
                "provenance": "demo_seed_agent_judged",
            }
        )
        referenced_ids.add(str(target_id))

    return links, sorted(referenced_ids), True, ""


def _proof_links_for_turn(*, current_id: str, ordered_ids: list[str], beads: dict[str, Any], max_links: int = 14) -> tuple[list[dict[str, Any]], list[str]]:
    current = dict(beads.get(str(current_id)) or {})
    if not current:
        return [], []

    if str(current_id) not in ordered_ids:
        return [], []
    pos = ordered_ids.index(str(current_id))
    prior_ids = list(reversed(ordered_ids[:pos]))

    current_entities = _bead_entities(current)
    current_tokens = _bead_tokens(current)
    current_text = _bead_text(current)
    flags = _cue_flags(current_text)

    dedupe: set[tuple[str, str, str]] = set()
    links: list[dict[str, Any]] = []
    referenced_ids: set[str] = {str(current_id)}

    if prior_ids:
        prev = prior_ids[0]
        key = (str(current_id), str(prev), "follows")
        dedupe.add(key)
        links.append(
            {
                "source_bead_id": str(current_id),
                "target_bead_id": str(prev),
                "relationship": "follows",
                "confidence": 0.62,
                "reason_text": "demo turn temporal adjacency",
                "provenance": "demo_seed",
            }
        )
        referenced_ids.add(str(prev))

    for target_id in prior_ids[:40]:
        if len(links) >= max(1, int(max_links)):
            break
        target = dict(beads.get(str(target_id)) or {})
        if not target:
            continue

        shared_entities = sorted(current_entities.intersection(_bead_entities(target)))
        shared_terms = sorted(current_tokens.intersection(_bead_tokens(target)))
        if not shared_entities and len(shared_terms) < 3:
            continue

        evidence_parts: list[str] = []
        if shared_entities:
            evidence_parts.append("shared entities: " + ", ".join(shared_entities[:3]))
        if len(shared_terms) >= 3:
            evidence_parts.append("shared terms: " + ", ".join(shared_terms[:4]))
        reason = "; ".join(evidence_parts)[:300]
        if not reason:
            continue

        relation_order: list[str] = []
        if shared_entities:
            relation_order.append("derived_from")
        if flags.get("support") and (shared_entities or len(shared_terms) >= 3):
            relation_order.append("supports")
        if flags.get("supersede") and (shared_entities or len(shared_terms) >= 3):
            relation_order.append("supersedes")
        if flags.get("contradict") and (shared_entities or len(shared_terms) >= 3):
            relation_order.append("contradicts")
        if flags.get("caused_by") and (shared_entities or len(shared_terms) >= 3):
            relation_order.append("caused_by")
        if flags.get("enables") and (shared_entities or len(shared_terms) >= 3):
            relation_order.append("enables")
        if flags.get("unblocks") and (shared_entities or len(shared_terms) >= 3):
            relation_order.append("unblocks")
        if flags.get("blocked_by") and (shared_entities or len(shared_terms) >= 3):
            relation_order.append("blocked_by")

        if not relation_order:
            continue

        for rel in relation_order:
            if len(links) >= max(1, int(max_links)):
                break
            key = (str(current_id), str(target_id), str(rel))
            if key in dedupe:
                continue
            dedupe.add(key)

            conf = 0.54
            conf += min(0.18, 0.06 * float(len(shared_entities)))
            conf += min(0.12, 0.03 * float(max(0, len(shared_terms) - 2)))
            if rel != "derived_from":
                conf += 0.06
            conf = max(0.3, min(0.95, conf))

            links.append(
                {
                    "source_bead_id": str(current_id),
                    "target_bead_id": str(target_id),
                    "relationship": rel,
                    "confidence": round(conf, 3),
                    "reason_text": reason,
                    "provenance": "demo_seed",
                }
            )
            referenced_ids.add(str(target_id))

    return links, sorted(referenced_ids)


def _latest_turn_bead_id_for_turn(*, root: str, session_id: str, turn_id: str) -> str:
    idx_path = Path(root) / ".beads" / "index.json"
    if not idx_path.exists():
        return ""
    try:
        payload = json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    beads = dict((payload.get("beads") or {})) if isinstance(payload, dict) else {}
    candidates: list[dict[str, Any]] = []
    for bead in beads.values():
        if not isinstance(bead, dict):
            continue
        if str(bead.get("session_id") or "") != str(session_id):
            continue
        source_turn_ids = [str(x) for x in (bead.get("source_turn_ids") or []) if str(x)]
        if str(turn_id) not in source_turn_ids:
            continue
        candidates.append(bead)

    if not candidates:
        return ""

    candidates.sort(key=lambda b: str((b or {}).get("created_at") or ""), reverse=True)
    return str((candidates[0] or {}).get("id") or "")


def _previous_session_turn_bead_id(*, root: str, session_id: str, current_bead_id: str) -> str:
    idx_path = Path(root) / ".beads" / "index.json"
    if not idx_path.exists():
        return ""
    try:
        payload = json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    beads = dict((payload.get("beads") or {})) if isinstance(payload, dict) else {}
    rows: list[dict[str, Any]] = []
    for bead in beads.values():
        if not isinstance(bead, dict):
            continue
        if str(bead.get("session_id") or "") != str(session_id):
            continue
        if not list(bead.get("source_turn_ids") or []):
            continue
        rows.append(bead)

    if not rows:
        return ""

    rows.sort(key=lambda b: str((b or {}).get("created_at") or ""))
    ids = [str((b or {}).get("id") or "") for b in rows if str((b or {}).get("id") or "")]
    if not ids:
        return ""

    current = str(current_bead_id or "").strip()
    if current and current in ids:
        pos = ids.index(current)
        if pos > 0:
            return ids[pos - 1]
    if len(ids) >= 2:
        return ids[-2]
    return ""


async def _link_turn_temporal_association(*, turn_id: str) -> dict[str, Any]:
    current_bead_id = _latest_turn_bead_id_for_turn(
        root=settings.core_memory_root,
        session_id=SESSION.session_id,
        turn_id=turn_id,
    )
    if not current_bead_id:
        return {"ok": False, "reason": "current_turn_bead_not_found"}

    idx_path = Path(settings.core_memory_root) / ".beads" / "index.json"
    beads = {}
    if idx_path.exists():
        try:
            payload = json.loads(idx_path.read_text(encoding="utf-8"))
            beads = dict((payload.get("beads") or {})) if isinstance(payload, dict) else {}
        except Exception:
            beads = {}

    ordered_ids = _session_turn_bead_ids(beads, session_id=SESSION.session_id)
    associations, referenced_ids, judge_used, judge_error = await _agent_judged_links_for_turn(
        current_id=current_bead_id,
        ordered_ids=ordered_ids,
        beads=beads,
        max_links=24,
    )
    if not associations:
        associations, referenced_ids = _proof_links_for_turn(
            current_id=current_bead_id,
            ordered_ids=ordered_ids,
            beads=beads,
            max_links=14,
        )
    if not associations:
        return {"ok": True, "linked": False, "reason": "no_proven_links"}

    out = run_association_pass(
        root=settings.core_memory_root,
        session_id=SESSION.session_id,
        updates={
            "association_scope": "historical_session",
            "associations": associations,
        },
        visible_bead_ids=list(referenced_ids),
    )
    merged = merge_crawler_updates(root=settings.core_memory_root, session_id=SESSION.session_id)

    relationship_counts: dict[str, int] = {}
    for row in associations:
        rel = str((row or {}).get("relationship") or "")
        if not rel:
            continue
        relationship_counts[rel] = int(relationship_counts.get(rel) or 0) + 1

    previous_bead_id = _previous_session_turn_bead_id(
        root=settings.core_memory_root,
        session_id=SESSION.session_id,
        current_bead_id=current_bead_id,
    )

    return {
        "ok": bool(out.get("ok", True)),
        "linked": int(out.get("associations_appended") or 0) > 0,
        "judge_used": bool(judge_used),
        "judge_error": str(judge_error or ""),
        "current_bead_id": str(current_bead_id),
        "previous_bead_id": str(previous_bead_id),
        "proven_link_candidates": int(len(associations)),
        "relationship_counts": relationship_counts,
        "associations_appended": int(out.get("associations_appended") or 0),
        "merge_associations_appended": int(merged.get("associations_appended") or 0),
    }


def _build_fallback_answer(message: str, retrieval: dict[str, Any] | None = None) -> str:
    out = dict(retrieval or {})
    results = list(out.get("results") or [])
    facts: list[str] = []
    for r in results[:3]:
        row = dict(r or {})
        title = str(row.get("title") or "").strip()
        summary = str(row.get("summary") or "").strip()
        text = title or summary or str(row.get("bead_id") or "").strip()
        if text:
            facts.append(text[:160])

    msg = str(message or "").strip()
    base = "Fallback response (no model configured). "
    if msg:
        base += "Recorded memory statement: " + msg
    else:
        base += "Recorded memory turn."
    if facts:
        base += " Related memory facts: " + "; ".join(facts)
    return base


def _chat_semantic_mode_name() -> str:
    demo_mode = str(os.getenv("CORE_MEMORY_DEMO_CHAT_SEMANTIC_MODE") or "").strip().lower()
    mode = demo_mode or "degraded_allowed"
    return mode if mode in {"required", "degraded_allowed"} else "degraded_allowed"


def _emit_chat_progress(progress: Callable[..., Any] | None, stage: str, message: str, **extra: Any) -> None:
    if not callable(progress):
        return
    try:
        progress(stage, message, **extra)
    except Exception:
        return


async def run_chat(message: str, *, progress: Callable[..., Any] | None = None) -> dict[str, Any]:
    global LAST_TURN_DIAGNOSTICS
    _sync_session_context_budget()
    turn_id = uuid.uuid4().hex[:12]
    fallback_error = ""
    model_id = detect_model()
    seed_updates = _seed_crawler_updates(user_query=message, turn_id=turn_id)
    turn_metadata = {
        "source": "core_memory_demo_backend",
        "crawler_updates": seed_updates,
    }
    chat_semantic_mode = _chat_semantic_mode_name()
    _emit_chat_progress(progress, "prepare", "Preparing memory turn", turn_id=turn_id, model_id=model_id, semantic_mode=chat_semantic_mode)

    try:
        _emit_chat_progress(progress, "retrieve", "Retrieving and grounding memory context")
        agent = get_agent()
        _emit_chat_progress(progress, "generate", "Generating assistant answer")
        with semantic_mode(chat_semantic_mode):
            result = await run_with_memory(
                agent,
                message,
                root=settings.core_memory_root,
                session_id=SESSION.session_id,
                turn_id=turn_id,
                metadata=turn_metadata,
            )
        answer = str(getattr(result, "output", None) or getattr(result, "data", None) or result)
        _emit_chat_progress(progress, "generated", "Assistant answer generated")
    except Exception as exc:
        err = str(exc or "").strip()
        fallback_error = err or "model_unavailable"
        _emit_chat_progress(progress, "fallback", "Primary model unavailable, using retrieval fallback", error=fallback_error)
        with semantic_mode(chat_semantic_mode):
            retrieval_preview = memory_tools.execute({"query": message, "intent": "remember", "k": 8}, root=settings.core_memory_root, explain=False)
        answer = _build_fallback_answer(message, retrieval_preview)
        process_turn_finalized(
            root=settings.core_memory_root,
            session_id=SESSION.session_id,
            turn_id=turn_id,
            transaction_id=f"demo-fallback-{uuid.uuid4().hex[:8]}",
            trace_id=f"demo-fallback-{uuid.uuid4().hex[:8]}",
            user_query=str(message or ""),
            assistant_final=str(answer or ""),
            origin="DEMO_CHAT_FALLBACK",
            metadata={
                "fallback": True,
                "fallback_error": fallback_error,
                "source": "core_memory_demo_backend",
                "crawler_updates": seed_updates,
            },
        )

    association_linking: dict[str, Any] = {}
    _emit_chat_progress(progress, "associations", "Linking temporal associations")
    try:
        association_linking = await _link_turn_temporal_association(turn_id=turn_id)
    except Exception as exc:
        association_linking = {"ok": False, "error": str(exc or "association_link_failed")}

    intent_probe = classify_intent(str(message or "")) or {}
    intent_class = str(intent_probe.get("intent_class") or "").strip().lower()

    req: dict[str, Any] = {"query": message, "k": 8}
    if intent_class in {"causal", "why", "what_changed"}:
        req["intent"] = "causal"

    _emit_chat_progress(progress, "diagnostics", "Collecting retrieval diagnostics")
    with semantic_mode(chat_semantic_mode):
        retrieval = memory_tools.execute(req, root=settings.core_memory_root, explain=False)

    top_result = (retrieval.get("results") or [{}])[0] if (retrieval.get("results") or []) else {}
    retrieval_mode = str(
        retrieval.get("retrieval_mode")
        or ((retrieval.get("request") or {}).get("grounding_mode") if isinstance(retrieval.get("request"), dict) else "")
        or "unknown"
    )

    grounding = dict(retrieval.get("grounding") or {})
    answer_rescued = False
    rescue_facts: list[str] = []

    _emit_chat_progress(progress, "tokenize", "Updating token usage")
    record_turn_tokens(message, answer, model_id=model_id)

    LAST_TURN_DIAGNOSTICS = {
        "ok": True,
        "turn_id": turn_id,
        "diagnostics": {
            "ok": bool(retrieval.get("ok")),
            "answer_outcome": str(retrieval.get("next_action") or "answered"),
            "retrieval_mode": retrieval_mode,
            "source_surface": "memory_execute",
            "anchor_reason": str((top_result or {}).get("anchor_reason") or "retrieved"),
            "result_count": int(len(list(retrieval.get("results") or []))),
            "top_bead_ids": [str(r.get("bead_id") or "") for r in list(retrieval.get("results") or [])[:5]],
            "chain_count": int(len(list(retrieval.get("chains") or []))),
            "grounding_level": str(grounding.get("level") or "none"),
            "grounding_required": bool(grounding.get("required")),
            "grounding_achieved": bool(grounding.get("achieved")),
            "grounding_reason": str(grounding.get("reason") or ""),
            "semantic_mode": chat_semantic_mode,
            "intent_class": intent_class or "remember",
            "warnings": list(retrieval.get("warnings") or []),
            "fallback_mode": bool(fallback_error),
            "fallback_error": fallback_error,
            "answer_rescued": bool(answer_rescued),
            "rescue_fact_count": int(len(rescue_facts)),
            "association_linking": association_linking,
        },
    }
    _emit_chat_progress(
        progress,
        "completed",
        "Chat turn completed",
        turn_id=turn_id,
        retrieval_mode=retrieval_mode,
        grounding_level=str(grounding.get("level") or "none"),
        fallback_mode=bool(fallback_error),
    )

    return {
        "ok": True,
        "session_id": SESSION.session_id,
        "turn_id": turn_id,
        "model_id": model_id,
        "assistant": answer,
        "last_answer": dict(LAST_TURN_DIAGNOSTICS),
    }


def run_flush(*, new_session_id: str | None = None) -> dict[str, Any]:
    _sync_session_context_budget()
    out = process_flush(
        root=settings.core_memory_root,
        session_id=SESSION.session_id,
        promote=True,
        token_budget=max(500, int(SESSION.context_budget)),
        max_beads=80,
        source="core_memory_demo_backend",
    )
    old = SESSION.session_id
    forced_session = str(new_session_id or "").strip()
    SESSION.session_id = forced_session or _new_session_id()
    SESSION.token_usage = 0
    _sync_session_context_budget()
    return {
        "flushed_session": old,
        "new_session": SESSION.session_id,
        "flush_ok": bool(out.get("ok")),
        "rolling_window_beads": int(len(((out.get("rolling_window") or {}).get("records") or []))),
    }


def reset_test_session(*, wipe_memory: bool = False) -> dict[str, Any]:
    global LAST_TURN_DIAGNOSTICS

    old_session = str(SESSION.session_id or "")
    wiped = False

    if bool(wipe_memory):
        root = Path(settings.core_memory_root)
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        wiped = True

    for root in settings.roots:
        Path(root).mkdir(parents=True, exist_ok=True)

    SESSION.session_id = _new_session_id()
    SESSION.token_usage = 0
    _sync_session_context_budget()
    LAST_TURN_DIAGNOSTICS = {}

    return {
        "ok": True,
        "wiped_memory": bool(wiped),
        "old_session": old_session,
        "new_session": SESSION.session_id,
        "context_budget": int(SESSION.context_budget),
    }


def _normalize_seed_messages(messages: list[Any] | None) -> list[str]:
    rows = list(messages or [])
    out: list[str] = []
    for x in rows:
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _queue_idle(status: dict[str, Any] | None) -> bool:
    s = dict(status or {})
    if int(s.get("pending_total") or 0) > 0:
        return False
    if int(s.get("processable_now") or 0) > 0:
        return False
    queues = dict(s.get("queues") or {})
    for _name, q in queues.items():
        row = dict(q or {})
        if int(row.get("pending") or row.get("queue_depth") or 0) > 0:
            return False
        if int(row.get("processable_now") or 0) > 0:
            return False
        if int(row.get("retry_ready") or 0) > 0:
            return False
    return True


def _drain_async_until_idle(
    *,
    timeout_ms: int,
    poll_ms: int,
    max_compaction: int,
    max_side_effects: int,
) -> dict[str, Any]:
    started = time.monotonic()
    timeout_s = max(1.0, float(timeout_ms) / 1000.0)
    poll_s = max(0.05, float(poll_ms) / 1000.0)

    passes = 0
    last_status: dict[str, Any] = {}
    while (time.monotonic() - started) <= timeout_s:
        last_status = async_jobs_status(root=settings.core_memory_root)
        if _queue_idle(last_status):
            return {
                "ok": True,
                "idle": True,
                "passes": passes,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "status": last_status,
            }

        out = run_async_jobs(
            root=settings.core_memory_root,
            run_semantic=True,
            max_compaction=max(1, int(max_compaction)),
            max_side_effects=max(1, int(max_side_effects)),
        )
        passes += 1
        comp_processed = int(((out.get("compaction_run") or {}).get("processed") or 0))
        se_processed = int(((out.get("side_effect_run") or {}).get("processed") or 0))
        sem_ran = bool(((out.get("semantic_run") or {}).get("ran") or False))

        if (comp_processed + se_processed) <= 0 and not sem_ran:
            time.sleep(poll_s)

    return {
        "ok": False,
        "idle": False,
        "passes": passes,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "status": last_status,
        "error": "idle_timeout",
    }


async def seed_demo_history(
    *,
    messages: list[Any] | None = None,
    max_turns: int | None = None,
    wait_for_idle: bool = False,
    idle_timeout_ms: int = 20000,
    idle_poll_ms: int = 250,
    auto_flush: bool = True,
    flush_threshold_ratio: float = 0.80,
    flush_every_turns: int = 0,
    max_compaction_per_pass: int = 2,
    max_side_effects_per_pass: int = 8,
) -> dict[str, Any]:
    prompts = _normalize_seed_messages(messages)
    if not prompts:
        prompts = list(DEFAULT_SEED_USER_MESSAGES)

    target = len(prompts)
    if isinstance(max_turns, int) and max_turns > 0:
        target = min(target, max_turns)

    seeded = 0
    seeded_since_flush = 0
    fallback_turns = 0
    fallback_error_counts: dict[str, int] = {}
    errors: list[dict[str, Any]] = []
    flush_events: list[dict[str, Any]] = []
    queue_waits: list[dict[str, Any]] = []

    def _should_flush() -> bool:
        if not auto_flush:
            return False
        if int(flush_every_turns) > 0 and seeded_since_flush >= int(flush_every_turns):
            return True
        budget = max(1, int(SESSION.context_budget))
        usage_ratio = float(SESSION.token_usage) / float(budget)
        return usage_ratio >= max(0.1, float(flush_threshold_ratio))

    for idx, user_query in enumerate(prompts[:target], start=1):
        try:
            turn_out = await run_chat(user_query)
            diag = dict(((turn_out.get("last_answer") or {}).get("diagnostics") or {}))
            if bool(diag.get("fallback_mode")):
                fallback_turns += 1
                ferr = str(diag.get("fallback_error") or "fallback").strip() or "fallback"
                fallback_error_counts[ferr] = int(fallback_error_counts.get(ferr) or 0) + 1
            seeded += 1
            seeded_since_flush += 1

            if wait_for_idle:
                wait_result = _drain_async_until_idle(
                    timeout_ms=idle_timeout_ms,
                    poll_ms=idle_poll_ms,
                    max_compaction=max_compaction_per_pass,
                    max_side_effects=max_side_effects_per_pass,
                )
                queue_waits.append({"turn": idx, **wait_result})
                if not bool(wait_result.get("idle")):
                    errors.append({
                        "index": idx,
                        "user_query": user_query[:160],
                        "error": "queue_not_idle_timeout",
                        "details": {
                            "elapsed_ms": wait_result.get("elapsed_ms"),
                            "passes": wait_result.get("passes"),
                            "pending_total": ((wait_result.get("status") or {}).get("pending_total")),
                        },
                    })
                    break

            if _should_flush():
                f = run_flush()
                flush_events.append(dict(f or {}))
                seeded_since_flush = 0
                if wait_for_idle:
                    post_wait = _drain_async_until_idle(
                        timeout_ms=idle_timeout_ms,
                        poll_ms=idle_poll_ms,
                        max_compaction=max_compaction_per_pass,
                        max_side_effects=max_side_effects_per_pass,
                    )
                    queue_waits.append({"turn": idx, "after_flush": True, **post_wait})
                    if not bool(post_wait.get("idle")):
                        errors.append({
                            "index": idx,
                            "user_query": user_query[:160],
                            "error": "queue_not_idle_timeout_after_flush",
                            "details": {
                                "elapsed_ms": post_wait.get("elapsed_ms"),
                                "passes": post_wait.get("passes"),
                                "pending_total": ((post_wait.get("status") or {}).get("pending_total")),
                            },
                        })
                        break
        except Exception as exc:
            errors.append({"index": idx, "user_query": user_query[:160], "error": str(exc)})

    final_queue = async_jobs_status(root=settings.core_memory_root)

    return {
        "ok": seeded > 0 and not errors,
        "seeded": seeded,
        "seeded_turns": seeded,
        "requested_turns": target,
        "failed_turns": len(errors),
        "errors": errors[:20],
        "mode": "chat_replay",
        "wait_for_idle": bool(wait_for_idle),
        "queue_idle": bool(_queue_idle(final_queue)),
        "queue": final_queue,
        "queue_wait_checks": queue_waits[-20:],
        "auto_flush": bool(auto_flush),
        "flush_count": len(flush_events),
        "flushes": flush_events[-20:],
        "fallback_turns": int(fallback_turns),
        "fallback_error_counts": dict(fallback_error_counts),
        "session": {
            "session_id": SESSION.session_id,
            "token_usage": SESSION.token_usage,
            "context_budget": SESSION.context_budget,
        },
    }


async def replay_story_pack(
    *,
    max_turns: int | None = None,
    start_turn: int | None = None,
    end_turn: int | None = None,
    wait_for_idle: bool = False,
    idle_timeout_ms: int = 20000,
    idle_poll_ms: int = 250,
    max_compaction_per_pass: int = 2,
    max_side_effects_per_pass: int = 8,
    run_checkpoints: bool = True,
    reset_session: bool = True,
    use_manifest_sessions: bool = True,
    benchmark_semantic_mode: str = "required",
    benchmark_limit: int | None = None,
    auto_flush: bool = True,
    flush_threshold_ratio: float = 0.80,
    flush_every_turns: int = 0,
) -> dict[str, Any]:
    bundle = _load_story_pack_bundle()
    manifest = dict(bundle.get("manifest") or {})
    turns = list(bundle.get("turns") or [])
    checkpoints_by_turn = dict(bundle.get("checkpoints") or {})

    start_at = int(start_turn or 0)
    end_at = int(end_turn or 0)
    if start_at > 0:
        turns = [t for t in turns if int(t.get("turn") or 0) >= start_at]
    if end_at > 0:
        turns = [t for t in turns if int(t.get("turn") or 0) <= end_at]
    if isinstance(max_turns, int) and max_turns > 0:
        turns = turns[: max_turns]

    if not turns:
        return {
            "ok": False,
            "error": "story_pack_no_turns_selected",
            "pack_name": str(manifest.get("pack_name") or "story-pack"),
        }

    sessions_cfg = dict(manifest.get("sessions") or {})
    if reset_session:
        initial_sid = str(sessions_cfg.get("initial") or "").strip() if use_manifest_sessions else ""
        SESSION.session_id = initial_sid or _new_session_id()
        SESSION.token_usage = 0

    selected_turns = {int(t.get("turn") or 0) for t in turns}
    executed_checkpoints: list[dict[str, Any]] = []
    queue_waits: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seeded = 0
    seeded_since_flush = 0
    flush_events: list[dict[str, Any]] = []
    fallback_turns = 0
    fallback_error_counts: dict[str, int] = {}

    def _should_flush() -> bool:
        if not auto_flush:
            return False
        if int(flush_every_turns) > 0 and seeded_since_flush >= int(flush_every_turns):
            return True
        budget = max(1, int(SESSION.context_budget))
        usage_ratio = float(SESSION.token_usage) / float(budget)
        return usage_ratio >= max(0.1, float(flush_threshold_ratio))

    for row in turns:
        turn_no = int(row.get("turn") or 0)
        prompt = str(row.get("prompt") or "").strip()
        if not prompt:
            continue

        try:
            turn_out = await run_chat(prompt)
            diag = dict(((turn_out.get("last_answer") or {}).get("diagnostics") or {}))
            if bool(diag.get("fallback_mode")):
                fallback_turns += 1
                ferr = str(diag.get("fallback_error") or "fallback").strip() or "fallback"
                fallback_error_counts[ferr] = int(fallback_error_counts.get(ferr) or 0) + 1
            seeded += 1
            seeded_since_flush += 1

            if wait_for_idle:
                wait_result = _drain_async_until_idle(
                    timeout_ms=idle_timeout_ms,
                    poll_ms=idle_poll_ms,
                    max_compaction=max_compaction_per_pass,
                    max_side_effects=max_side_effects_per_pass,
                )
                queue_waits.append({"turn": turn_no, **wait_result})
                if not bool(wait_result.get("idle")):
                    errors.append(
                        {
                            "turn": turn_no,
                            "error": "queue_not_idle_timeout",
                            "details": {
                                "elapsed_ms": wait_result.get("elapsed_ms"),
                                "passes": wait_result.get("passes"),
                                "pending_total": ((wait_result.get("status") or {}).get("pending_total")),
                            },
                        }
                    )
                    break

            if _should_flush():
                f = run_flush()
                flush_events.append(
                    {
                        "after_turn": turn_no,
                        "type": "auto_flush",
                        "ok": bool((f or {}).get("flush_ok")),
                        "new_session": str((f or {}).get("new_session") or ""),
                        "flushed_session": str((f or {}).get("flushed_session") or ""),
                    }
                )
                seeded_since_flush = 0
                if wait_for_idle:
                    post_wait = _drain_async_until_idle(
                        timeout_ms=idle_timeout_ms,
                        poll_ms=idle_poll_ms,
                        max_compaction=max_compaction_per_pass,
                        max_side_effects=max_side_effects_per_pass,
                    )
                    queue_waits.append({"turn": turn_no, "after_flush": True, **post_wait})
                    if not bool(post_wait.get("idle")):
                        errors.append(
                            {
                                "turn": turn_no,
                                "error": "queue_not_idle_timeout_after_flush",
                                "details": {
                                    "elapsed_ms": post_wait.get("elapsed_ms"),
                                    "passes": post_wait.get("passes"),
                                    "pending_total": ((post_wait.get("status") or {}).get("pending_total")),
                                },
                            }
                        )
                        break

            if errors:
                break

            if not run_checkpoints:
                continue

            for cp in list(checkpoints_by_turn.get(turn_no) or []):
                cp_type = str(cp.get("type") or "").strip().lower()
                if cp_type == "session_flush":
                    forced_next = str(cp.get("next_session") or "").strip() if use_manifest_sessions else ""
                    flush_out = run_flush(new_session_id=(forced_next or None))
                    event = {
                        "after_turn": turn_no,
                        "type": "session_flush",
                        "mode": str(cp.get("mode") or ""),
                        "ok": bool(flush_out.get("flush_ok")),
                        "new_session": str(flush_out.get("new_session") or ""),
                        "flushed_session": str(flush_out.get("flushed_session") or ""),
                    }
                    executed_checkpoints.append(event)

                    if wait_for_idle:
                        post_wait = _drain_async_until_idle(
                            timeout_ms=idle_timeout_ms,
                            poll_ms=idle_poll_ms,
                            max_compaction=max_compaction_per_pass,
                            max_side_effects=max_side_effects_per_pass,
                        )
                        queue_waits.append({"turn": turn_no, "after_flush": True, **post_wait})
                        if not bool(post_wait.get("idle")):
                            errors.append(
                                {
                                    "turn": turn_no,
                                    "error": "queue_not_idle_timeout_after_flush",
                                    "details": {
                                        "elapsed_ms": post_wait.get("elapsed_ms"),
                                        "passes": post_wait.get("passes"),
                                        "pending_total": ((post_wait.get("status") or {}).get("pending_total")),
                                    },
                                }
                            )
                            break
                elif cp_type == "benchmark":
                    mode_raw = str(cp.get("mode") or "snapshot").strip().lower()
                    root_mode = "clean" if mode_raw == "clean" else "snapshot"
                    bench = run_benchmark(
                        semantic_mode_name=str(benchmark_semantic_mode or "required"),
                        root_mode=root_mode,
                        preload_from_demo=False,
                        preload_turns_max=0,
                        limit=benchmark_limit,
                    )
                    summary = dict(bench.get("summary") or {})
                    executed_checkpoints.append(
                        {
                            "after_turn": turn_no,
                            "type": "benchmark",
                            "mode": root_mode,
                            "ok": bool(bench.get("ok")),
                            "run_id": str(summary.get("run_id") or ""),
                            "accuracy": summary.get("accuracy"),
                            "cases": int(summary.get("cases") or 0),
                            "pass": int(summary.get("pass") or 0),
                            "fail": int(summary.get("fail") or 0),
                        }
                    )
                else:
                    executed_checkpoints.append(
                        {
                            "after_turn": turn_no,
                            "type": cp_type or "unknown",
                            "ok": False,
                            "error": "unsupported_checkpoint_type",
                        }
                    )

            if errors:
                break
        except Exception as exc:
            errors.append(
                {
                    "turn": turn_no,
                    "error": str(exc),
                    "prompt": prompt[:200],
                }
            )
            break

    final_queue = async_jobs_status(root=settings.core_memory_root)
    first_turn = int(turns[0].get("turn") or 0)
    last_turn = int(turns[-1].get("turn") or 0)

    return {
        "ok": seeded > 0 and not errors,
        "pack_name": str(manifest.get("pack_name") or "story-pack"),
        "seeded": seeded,
        "requested_turns": int(len(turns)),
        "turn_range": {"first": first_turn, "last": last_turn},
        "selected_turns": sorted(selected_turns),
        "run_checkpoints": bool(run_checkpoints),
        "auto_flush": bool(auto_flush),
        "flush_count": int(len(flush_events)),
        "flushes": list(flush_events[-20:]),
        "checkpoint_count": int(len(executed_checkpoints)),
        "checkpoints": executed_checkpoints,
        "fallback_turns": int(fallback_turns),
        "fallback_error_counts": dict(fallback_error_counts),
        "errors": errors[:20],
        "wait_for_idle": bool(wait_for_idle),
        "queue_idle": bool(_queue_idle(final_queue)),
        "queue": final_queue,
        "queue_wait_checks": queue_waits[-40:],
        "session": {
            "session_id": SESSION.session_id,
            "token_usage": SESSION.token_usage,
            "context_budget": SESSION.context_budget,
        },
    }


@contextmanager
def semantic_mode(mode: str):
    key = "CORE_MEMORY_CANONICAL_SEMANTIC_MODE"
    old = os.environ.get(key)
    try:
        os.environ[key] = str(mode or "degraded_allowed")
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def _benchmark_history_file() -> Path:
    p = Path(settings.core_memory_demo_artifacts_root)
    p.mkdir(parents=True, exist_ok=True)
    return p / "benchmark-history.jsonl"


def _append_history(row: dict[str, Any]) -> None:
    f = _benchmark_history_file()
    with f.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")

    max_rows = max(10, int(settings.benchmark_history_max_rows))
    try:
        lines = [ln for ln in f.read_text(encoding="utf-8").splitlines() if str(ln or "").strip()]
        if len(lines) > max_rows:
            f.write_text("\n".join(lines[-max_rows:]) + "\n", encoding="utf-8")
    except Exception:
        # best effort only
        pass


def _prune_benchmark_run_dirs() -> None:
    root = Path(settings.core_memory_demo_benchmark_root)
    if not root.exists():
        return
    max_keep = max(10, int(settings.benchmark_runs_max_keep))
    try:
        dirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("bench-")]
        dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for old in dirs[max_keep:]:
            shutil.rmtree(old, ignore_errors=True)
    except Exception:
        # best effort only
        pass


def read_benchmark_history(limit: int = 20) -> list[dict[str, Any]]:
    file_rows: list[dict[str, Any]] = []
    f = _benchmark_history_file()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            raw = str(line or "").strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            if isinstance(rec, dict):
                file_rows.append(rec)

    file_rows = list(reversed(file_rows))
    in_memory_rows = [dict(x or {}) for x in list(LAST_BENCHMARK_HISTORY or [])]
    combined = in_memory_rows + file_rows

    seen: set[str] = set()
    dedup: list[dict[str, Any]] = []
    for r in combined:
        rid = str((r.get("summary") or {}).get("run_id") or r.get("run_id") or "")
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        dedup.append(r)
    return dedup[: max(1, int(limit))]


def _set_last_benchmark_cache(*, summary: dict[str, Any], report: dict[str, Any], history_row: dict[str, Any]) -> None:
    LAST_BENCHMARK_SUMMARY.clear()
    LAST_BENCHMARK_SUMMARY.update(dict(summary or {}))

    LAST_BENCHMARK_REPORT.clear()
    LAST_BENCHMARK_REPORT.update(dict(report or {}))

    run_id = str((summary or {}).get("run_id") or (history_row or {}).get("run_id") or "").strip()
    existing = [dict(x or {}) for x in list(LAST_BENCHMARK_HISTORY or [])]
    if run_id:
        existing = [
            x
            for x in existing
            if str((x.get("summary") or {}).get("run_id") or x.get("run_id") or "").strip() != run_id
        ]
    LAST_BENCHMARK_HISTORY[:] = ([dict(history_row or {})] + existing)[:100]


def get_last_benchmark_snapshot(*, history_limit: int = 20) -> dict[str, Any]:
    rows = read_benchmark_history(limit=max(1, int(history_limit)))
    latest = dict(rows[0] or {}) if rows else {}

    summary = dict(LAST_BENCHMARK_SUMMARY or {})
    report = dict(LAST_BENCHMARK_REPORT or {})

    if not summary:
        summary = dict(latest.get("summary") or {})
    if not report:
        report = dict(latest.get("report") or {})

    return {
        "ok": bool(report),
        "summary": summary,
        "report": report,
        "history": rows,
    }


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)


def _load_preload_turns_from_live(*, max_turns: int = 200) -> list[dict[str, str]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    target = max(1, int(max_turns))
    while len(rows) < target:
        page = list_turn_summaries(root=settings.core_memory_root, limit=min(200, target * 2), cursor=cursor)
        items = list(page.get("items") or [])
        if not items:
            break
        for rec in items:
            tid = str(rec.get("turn_id") or "").strip()
            sid = str(rec.get("session_id") or "").strip() or None
            if not tid:
                continue
            full = get_turn(turn_id=tid, root=settings.core_memory_root, session_id=sid) if tid else {}
            uq = str((full or rec).get("user_query") or "").strip()
            af = str((full or rec).get("assistant_final") or "").strip()
            if not uq or not af:
                continue
            rows.append(
                {
                    "session_id": str((full or rec).get("session_id") or sid or "demo"),
                    "turn_id": str((full or rec).get("turn_id") or tid),
                    "user_query": uq[:500],
                    "assistant_final": af[:900],
                    "origin": "DEMO_PRELOAD",
                }
            )
            if len(rows) >= target:
                break
        cursor = str(page.get("next_cursor") or "").strip() or None
        if not cursor:
            break

    return [dict(x or {}) for x in rows[:target]]


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

    workspace_core_memory = Path(__file__).resolve().parents[5] / "Core-Memory" / "benchmarks" / "locomo_like"
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


def _legacy_smoke_cases() -> list[dict[str, Any]]:
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


def _load_locomo_cases(*, subset: str = "local") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fixtures_dir, gold_dir = _locomo_benchmark_dirs()
    if not fixtures_dir.exists() or not gold_dir.exists():
        rows = _legacy_smoke_cases()
        return rows, {
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
        rows = _legacy_smoke_cases()
        return rows, {
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
        "source": "fixture_pack",
        "fixtures_dir": str(fixtures_dir),
        "gold_dir": str(gold_dir),
        "fixture_files": [p.name for p in all_fixture_paths],
        "available_cases": int(available_cases),
        "selected_cases": int(len(out)),
        "local_subset_cases": int(local_count),
        "full_subset_available": bool(full_subset_available),
    }


def _materialize_locomo_setup(*, root: str, setup: dict[str, Any], case_id: str) -> None:
    s = MemoryStore(root)
    bead_keys: dict[str, str] = {}

    for i, t in enumerate(list(setup.get("turns") or []), start=1):
        if not isinstance(t, dict):
            continue
        tid = str(t.get("turn_id") or f"{case_id}-turn-{i}").strip() or f"{case_id}-turn-{i}"
        sid = str(t.get("session_id") or "main").strip() or "main"
        uq = str(t.get("user_query") or "").strip()
        af = str(t.get("assistant_final") or "").strip()
        if not uq or not af:
            continue
        process_turn_finalized(
            root=root,
            session_id=sid,
            turn_id=tid,
            transaction_id=f"tx-{case_id}-{i}",
            trace_id=f"tr-{case_id}-{i}",
            user_query=uq,
            assistant_final=af,
            origin="BENCH_FIXTURE_TURN",
            metadata=dict(t.get("metadata") or {}),
        )

    for row in list(setup.get("beads") or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        bead_id = s.add_bead(
            type=str(row.get("type") or "context"),
            title=str(row.get("title") or "fixture bead"),
            summary=list(row.get("summary") or ["fixture"]),
            detail=str(row.get("detail") or ""),
            session_id=str(row.get("session_id") or "main"),
            source_turn_ids=list(row.get("source_turn_ids") or [f"{case_id}-setup"]),
            tags=list(row.get("tags") or ["benchmark_fixture"]),
            status=str(row.get("status") or "open"),
        )
        if key:
            bead_keys[key] = bead_id

    for row in list(setup.get("claims") or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("bead_key") or "").strip()
        bead_id = bead_keys.get(key)
        if not bead_id:
            continue
        write_claims_to_bead(root, bead_id, list(row.get("rows") or []))

    for row in list(setup.get("claim_updates") or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("bead_key") or "").strip()
        bead_id = bead_keys.get(key)
        if not bead_id:
            continue
        write_claim_updates_to_bead(root, bead_id, list(row.get("rows") or []))


def run_benchmark(*, semantic_mode_name: str, root_mode: str, preload_from_demo: bool, preload_turns_max: int, limit: int | None = None, subset: str = "local") -> dict[str, Any]:
    run_id = f"bench-{uuid.uuid4().hex[:10]}"
    started = _utc_now_iso()
    run_root = Path(settings.core_memory_demo_benchmark_root) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    base_root = run_root / "base"
    base_root.mkdir(parents=True, exist_ok=True)

    if str(root_mode or "snapshot") == "snapshot":
        _copy_tree(Path(settings.core_memory_root), base_root)

    preloaded_rows: list[dict[str, Any]] = []
    if preload_from_demo:
        preloaded_rows = _load_preload_turns_from_live(max_turns=preload_turns_max)
        for rec in preloaded_rows:
            process_turn_finalized(
                root=str(base_root),
                session_id=str(rec.get("session_id") or "bench"),
                turn_id=str(rec.get("turn_id") or uuid.uuid4().hex[:10]),
                transaction_id=f"bench-preload-{uuid.uuid4().hex[:8]}",
                trace_id=f"bench-preload-{uuid.uuid4().hex[:8]}",
                user_query=str(rec.get("user_query") or ""),
                assistant_final=str(rec.get("assistant_final") or ""),
                origin="BENCH_PRELOAD",
                metadata={"source": "demo_preload"},
            )

    rows, fixture_meta = _load_locomo_cases(subset=str(subset or "local"))
    if isinstance(limit, int) and limit > 0:
        rows = rows[: limit]

    per_case: list[dict[str, Any]] = []
    passes = 0
    with semantic_mode(semantic_mode_name):
        for c in rows:
            case_id = str(c.get("case_id") or f"case-{len(per_case)+1}")
            case_root = run_root / f"case-{case_id}"
            case_root.mkdir(parents=True, exist_ok=True)
            _copy_tree(base_root, case_root)
            _materialize_locomo_setup(root=str(case_root), setup=dict(c.get("setup") or {}), case_id=case_id)

            req = {
                "query": str(c.get("query") or ""),
                "intent": str(c.get("intent") or "remember"),
                "k": max(1, int(c.get("k") or 5)),
            }
            result = memory_tools.execute(req, root=str(case_root), explain=False)
            results = list(result.get("results") or [])
            expected_class = str(c.get("expected_answer_class") or "answer_partial")
            actual_class = str(result.get("answer_outcome") or "")
            class_ok = actual_class == expected_class

            expected_source_surface = str(c.get("expected_source_surface") or "")
            top_source_surface = str(((results[0] if results else {}) or {}).get("source_surface") or "")
            source_ok = (not expected_source_surface) or (top_source_surface == expected_source_surface)

            checks = {
                "answer_class": {
                    "expected": expected_class,
                    "actual": actual_class,
                    "pass": bool(class_ok),
                },
                "source_surface": {
                    "expected": expected_source_surface,
                    "actual": top_source_surface,
                    "pass": bool(source_ok),
                },
            }

            ok = bool(class_ok and source_ok)
            if ok:
                passes += 1
            per_case.append(
                {
                    "case_id": case_id,
                    "query": str(c.get("query") or ""),
                    "expected_answer_class": expected_class,
                    "actual_answer_class": actual_class,
                    "pass": bool(ok),
                    "checks": checks,
                    "bucket_labels": list(c.get("bucket_labels") or []),
                    "result_count": len(results),
                    "warnings": list(result.get("warnings") or []),
                    "backend": str(result.get("backend") or "unknown"),
                    "root": str(case_root),
                }
            )

    total = len(per_case)
    fail = max(0, total - passes)
    warnings: list[str] = []
    if str(subset or "local").strip().lower() == "full" and not bool(fixture_meta.get("full_subset_available")):
        warnings.append("full_subset_not_available_running_best_available_pack")
    warn_field = (fixture_meta or {}).get("warning")
    if isinstance(warn_field, list):
        for w in warn_field:
            if str(w).strip():
                warnings.append(str(w).strip())
    elif isinstance(warn_field, str) and warn_field.strip():
        warnings.append(warn_field.strip())

    summary = {
        "run_id": run_id,
        "started_at": started,
        "finished_at": _utc_now_iso(),
        "cases": total,
        "pass": passes,
        "fail": fail,
        "accuracy": (passes / total) if total else 0.0,
        "semantic_mode": semantic_mode_name,
        "subset": str(subset or "local"),
        "root_mode": root_mode,
        "isolated_root": str(run_root),
        "isolated_run": True,
        "preload_turn_count": int(len(preloaded_rows)),
        "backend_modes": sorted(set(str(x.get("backend") or "unknown") for x in per_case)),
        "warnings": sorted(set([str(x) for x in warnings if str(x).strip()])),
        "fixture_pack": dict(fixture_meta or {}),
    }
    report = {
        "totals": {"cases": total, "pass": passes, "fail": fail, "accuracy": summary["accuracy"]},
        "metadata": {
            "run_id": run_id,
            "semantic_mode": semantic_mode_name,
            "benchmark_backend_modes": summary["backend_modes"],
            "preload_turn_count": summary["preload_turn_count"],
            "root_mode": root_mode,
        },
        "cases": per_case,
        "per_bucket": {
            "overall": {
                "cases": total,
                "pass": passes,
                "fail": fail,
                "accuracy": summary["accuracy"],
            }
        },
    }

    history_row = {
        "run_id": run_id,
        "created_at": summary["finished_at"],
        "summary": dict(summary),
        "report": dict(report),
    }
    _set_last_benchmark_cache(summary=summary, report=report, history_row=history_row)
    _append_history(history_row)
    _prune_benchmark_run_dirs()

    return {"ok": True, "summary": summary, "report": report}


def compare_benchmark_runs(left_run_id: str, right_run_id: str) -> dict[str, Any]:
    rows = read_benchmark_history(limit=400)
    by_id = {str((r.get("summary") or {}).get("run_id") or r.get("run_id") or ""): r for r in rows}
    left = dict(by_id.get(str(left_run_id)) or {})
    right = dict(by_id.get(str(right_run_id)) or {})
    if not left or not right:
        return {"ok": False, "error": "run_id_not_found"}
    ls = dict(left.get("summary") or {})
    rs = dict(right.get("summary") or {})

    def _f(x: Any) -> float:
        try:
            return float(x or 0.0)
        except Exception:
            return 0.0

    return {
        "ok": True,
        "compare": {
            "left": ls,
            "right": rs,
            "delta": {
                "accuracy": round(_f(rs.get("accuracy")) - _f(ls.get("accuracy")), 4),
                "pass": int(rs.get("pass") or 0) - int(ls.get("pass") or 0),
                "fail": int(rs.get("fail") or 0) - int(ls.get("fail") or 0),
            },
        },
    }


def suggest_entity_merges(*, min_score: float = 0.86, max_pairs: int = 40, source: str = "demo") -> dict[str, Any]:
    return suggest_entity_merge_proposals(settings.core_memory_root, min_score=min_score, max_pairs=max_pairs, source=source)


def decide_entity_merge(*, proposal_id: str, decision: str, keep_entity_id: str | None = None, reviewer: str = "demo", notes: str = "", apply: bool = True) -> dict[str, Any]:
    return decide_entity_merge_proposal(
        settings.core_memory_root,
        proposal_id=proposal_id,
        decision=decision,
        reviewer=reviewer,
        notes=notes,
        apply=apply,
        keep_entity_id=keep_entity_id,
    )


def inspect_bead_payload(bead_id: str) -> dict[str, Any]:
    bead = inspect_bead(root=settings.core_memory_root, bead_id=bead_id)
    if bead is None:
        return {"ok": False, "error": "bead_not_found", "bead_id": bead_id}
    return {"ok": True, "bead": bead}


def inspect_bead_hydration_payload(bead_id: str) -> dict[str, Any]:
    return inspect_bead_hydration(root=settings.core_memory_root, bead_id=bead_id, include_tools=False, before=0, after=0)


def inspect_claim_slot_payload(subject: str, slot: str, as_of: str | None) -> dict[str, Any]:
    return inspect_claim_slot(
        root=settings.core_memory_root,
        subject=subject,
        slot=slot,
        as_of=_normalize_as_of(as_of),
    )


def inspect_turns_payload(session_id: str | None, limit: int, cursor: str | None) -> dict[str, Any]:
    return list_turn_summaries(root=settings.core_memory_root, session_id=session_id, limit=limit, cursor=cursor)
