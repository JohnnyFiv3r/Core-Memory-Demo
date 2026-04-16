from __future__ import annotations

from typing import Any

from app.core.config import settings


def safe_state_fallback(error: str = "state_unavailable") -> dict[str, Any]:
    budget = int(settings.demo_context_budget or 128000)
    return {
        "ok": True,
        "warning": "state_unavailable",
        "error": str(error or "state_unavailable"),
        "memory": {
            "beads": [],
            "associations": [],
            "rolling_window": [],
        },
        "claims": {"slots": []},
        "entities": {"rows": []},
        "beads": [],
        "associations": [],
        "rolling_window": [],
        "claim_state": [],
        "session": {
            "session_id": "unavailable",
            "token_usage": 0,
            "context_budget": budget,
            "rolling_window_token_estimate": 0,
            "rolling_window_token_budget": 0,
            "rolling_window_record_count": 0,
        },
        "stats": {
            "total_beads": 0,
            "total_associations": 0,
            "rolling_window_size": 0,
            "rolling_window_token_estimate": 0,
            "rolling_window_token_budget": 0,
            "rolling_window_record_count": 0,
            "claim_slot_count": 0,
            "entity_count": 0,
            "session_id": "unavailable",
            "token_usage": 0,
            "context_budget": budget,
        },
        "last_turn": {},
        "benchmark": {
            "last_summary": {},
            "has_last_report": False,
            "history": [],
        },
    }

