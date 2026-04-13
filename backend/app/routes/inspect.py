from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.runtime import (
    inspect_bead_hydration_payload,
    inspect_bead_payload,
    inspect_claim_slot_payload,
    inspect_state_payload,
    inspect_turns_payload,
)

router = APIRouter(prefix='/v1/memory/inspect', tags=['inspect'])


@router.get('/state')
def inspect_state(as_of: str | None = None):
    return inspect_state_payload(as_of=as_of)


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
