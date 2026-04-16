from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.abuse import rate_limit_general
from app.core.auth import require_admin
from app.core.config import settings
from app.core.runtime import (
    inspect_bead_hydration_payload,
    inspect_bead_payload,
    inspect_claim_slot_payload,
    inspect_state_payload,
    inspect_turns_payload,
)

router = APIRouter(prefix='/v1/memory/inspect', tags=['inspect'], dependencies=[Depends(require_admin), Depends(rate_limit_general)])


@router.get('/state')
def inspect_state(as_of: str | None = None):
    try:
        return inspect_state_payload(as_of=as_of)
    except Exception as exc:
        fallback = {
            'ok': True,
            'warning': 'state_unavailable',
            'error': str(exc),
            'memory': {
                'beads': [],
                'associations': [],
                'rolling_window': [],
            },
            'claims': {'slots': []},
            'entities': {'rows': []},
            'beads': [],
            'associations': [],
            'rolling_window': [],
            'claim_state': [],
            'session': {
                'session_id': 'unavailable',
                'token_usage': 0,
                'context_budget': int(settings.demo_context_budget or 128000),
                'rolling_window_token_estimate': 0,
                'rolling_window_token_budget': 0,
                'rolling_window_record_count': 0,
            },
            'stats': {
                'total_beads': 0,
                'total_associations': 0,
                'rolling_window_size': 0,
                'rolling_window_token_estimate': 0,
                'rolling_window_token_budget': 0,
                'rolling_window_record_count': 0,
                'claim_slot_count': 0,
                'entity_count': 0,
                'session_id': 'unavailable',
                'token_usage': 0,
                'context_budget': int(settings.demo_context_budget or 128000),
            },
            'last_turn': {},
            'benchmark': {
                'last_summary': {},
                'has_last_report': False,
                'history': [],
            },
        }
        return JSONResponse(fallback, status_code=200)


@router.get('/beads/{bead_id}')
def inspect_bead(bead_id: str):
    out = inspect_bead_payload(bead_id)
    status = 200 if out.get('ok') else 404
    return JSONResponse(out, status_code=status)


@router.get('/beads/{bead_id}/hydrate')
def inspect_bead_hydrate(bead_id: str):
    return inspect_bead_hydration_payload(bead_id)


@router.get('/claim-slots/{subject}/{slot}')
def inspect_claim_slot(subject: str, slot: str, as_of: str | None = None):
    return inspect_claim_slot_payload(subject, slot, as_of)


@router.get('/turns')
def inspect_turns(session_id: str | None = None, limit: int = 200, cursor: str | None = None):
    return inspect_turns_payload(session_id, max(1, int(limit)), cursor)
