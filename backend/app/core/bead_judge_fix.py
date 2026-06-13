from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Workaround for a brace-escaping bug in Core Memory's bead-field judge prompt.
#
# core_memory.policy.bead_judge builds the LLM prompt with
#   _prompt_template().format(user_query=..., assistant_final=...)
# but the default template embeds a literal JSON schema example with UNESCAPED
# single braces (`{ "type": ... }`). str.format() reads those as replacement
# fields and raises KeyError on every call, in all three provider paths. Each
# path swallows it in a try/except, so judge_bead_fields() returns
# "llm_failed_fallback" and authors deterministic beads with NO claims — which
# trips the benchmark's `_assert_judge_engaged` fail-closed gate (0 claims) and,
# more importantly, silently degrades every demo memory the LLM judge should
# have authored.
#
# The bug is present in the pinned commit AND the latest upstream commit, so
# bumping the pin does not fix it; the real fix is to escape the template's
# braces (or switch to str.replace) in Core Memory itself. Until then we install
# a format-safe copy of the template through Core Memory's own
# CORE_MEMORY_BEAD_FIELD_PROMPT override. This is gated on the installed
# template actually being broken, so it becomes a no-op automatically once the
# upstream prompt is fixed.

_PLACEHOLDERS = ("user_query", "assistant_final")


def make_format_safe(template: str) -> str:
    """Double every brace, then restore the real ``{user_query}``/``{assistant_final}``.

    After str.format() the doubled braces collapse back to single literal braces
    (so the JSON schema example survives intact) while the two placeholders are
    substituted as intended.
    """
    safe = str(template or "").replace("{", "{{").replace("}", "}}")
    for name in _PLACEHOLDERS:
        safe = safe.replace("{{" + name + "}}", "{" + name + "}")
    return safe


def template_is_format_broken(template: str) -> bool:
    """True if ``template.format(...)`` raises on the judge's substitution call."""
    try:
        str(template or "").format(user_query="", assistant_final="")
        return False
    except (KeyError, IndexError, ValueError):
        return True


def install_bead_judge_prompt_format_fix() -> dict[str, Any]:
    """Install a format-safe bead-judge prompt iff the installed default is broken.

    Idempotent and side-effect-light: respects an existing operator override,
    no-ops when Core Memory is absent or its template already formats cleanly.
    """
    if str(os.environ.get("CORE_MEMORY_BEAD_FIELD_PROMPT") or "").strip() or str(
        os.environ.get("CORE_MEMORY_BEAD_FIELD_PROMPT_FILE") or ""
    ).strip():
        return {"applied": False, "reason": "operator_prompt_override_present"}
    try:
        from core_memory.policy import bead_judge as _bj
    except Exception as exc:  # pragma: no cover - core_memory always present in deploy
        return {"applied": False, "reason": f"core_memory_unavailable:{type(exc).__name__}"}
    template = getattr(_bj, "_PROMPT", None)
    if not isinstance(template, str) or not template.strip():
        return {"applied": False, "reason": "no_default_prompt"}
    if not template_is_format_broken(template):
        return {"applied": False, "reason": "prompt_already_format_safe"}
    safe = make_format_safe(template)
    if template_is_format_broken(safe):  # defensive: never install a still-broken prompt
        return {"applied": False, "reason": "format_safe_transform_failed"}
    os.environ["CORE_MEMORY_BEAD_FIELD_PROMPT"] = safe
    logger.warning(
        "Installed format-safe CORE_MEMORY_BEAD_FIELD_PROMPT: the pinned Core Memory "
        "bead-field judge template breaks str.format() on its literal JSON braces, which "
        "silently disables the LLM judge (0 claims). Fix upstream by escaping the prompt "
        "braces to remove this workaround."
    )
    return {"applied": True, "reason": "format_safe_prompt_installed"}
