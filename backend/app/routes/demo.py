from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.runtime import (
    compare_benchmark_runs,
    decide_entity_merge,
    inspect_bead_hydration_payload,
    inspect_bead_payload,
    inspect_claim_slot_payload,
    inspect_state_payload,
    inspect_turns_payload,
    read_benchmark_history,
    run_benchmark,
    run_chat,
    run_flush,
    seed_demo_history,
    suggest_entity_merges,
    LAST_BENCHMARK_REPORT,
    LAST_BENCHMARK_SUMMARY,
)

router = APIRouter(prefix='/api', tags=['demo'])


@router.get('/meta')
def meta():
    return {
        'ok': True,
        'message': 'Core Memory Demo backend active',
        'contract_status': 't2_in_progress',
    }


@router.get('/demo/state')
def demo_state(as_of: str | None = None):
    return inspect_state_payload(as_of=as_of)


@router.get('/demo/claims')
def demo_claims(as_of: str | None = None):
    state = inspect_state_payload(as_of=as_of)
    return {
        'ok': True,
        'claims': state.get('claims') or {},
        'session': state.get('session') or {},
    }


@router.get('/demo/entities')
def demo_entities():
    state = inspect_state_payload()
    return {
        'ok': True,
        'entities': state.get('entities') or {},
        'session': state.get('session') or {},
    }


@router.get('/demo/runtime')
def demo_runtime():
    state = inspect_state_payload()
    return {
        'ok': True,
        'runtime': state.get('runtime') or {},
        'last_turn': state.get('last_turn') or {},
        'session': state.get('session') or {},
    }


@router.get('/demo/bead/{bead_id}')
def demo_bead(bead_id: str):
    out = inspect_bead_payload(bead_id)
    status = 200 if out.get('ok') else 404
    return JSONResponse(out, status_code=status)


@router.get('/demo/bead/{bead_id}/hydrate')
def demo_bead_hydrate(bead_id: str):
    return inspect_bead_hydration_payload(bead_id)


@router.get('/demo/claim-slot/{subject}/{slot}')
def demo_claim_slot(subject: str, slot: str, as_of: str | None = None):
    return inspect_claim_slot_payload(subject, slot, as_of)


@router.get('/demo/turns')
def demo_turns(session_id: str | None = None, limit: int = 200, cursor: str | None = None):
    return inspect_turns_payload(session_id, max(1, int(limit)), cursor)


@router.post('/chat')
async def chat(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    message = str((body or {}).get('message') or (body or {}).get('query') or '').strip()
    if not message:
        return JSONResponse({'ok': False, 'error': 'missing_message'}, status_code=400)
    try:
        out = await run_chat(message)
        return out
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/flush')
def flush():
    try:
        return run_flush()
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/seed')
async def seed(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    messages = (body or {}).get('messages')
    max_turns_raw = (body or {}).get('max_turns')
    max_turns = None
    if isinstance(max_turns_raw, int) and max_turns_raw > 0:
        max_turns = int(max_turns_raw)
    try:
        out = await seed_demo_history(messages=messages if isinstance(messages, list) else None, max_turns=max_turns)
        state = inspect_state_payload()
        out['stats'] = state.get('stats') or {}
        return out
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/benchmark-run')
async def benchmark_run(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    semantic_mode = str((body or {}).get('semantic_mode') or 'degraded_allowed').strip() or 'degraded_allowed'
    root_mode = str((body or {}).get('root_mode') or 'snapshot').strip().lower() or 'snapshot'
    if root_mode not in {'snapshot', 'clean'}:
        root_mode = 'snapshot'
    preload_from_demo = bool((body or {}).get('preload_from_demo', False))
    preload_turns_max = int((body or {}).get('preload_turns_max') or 200)
    limit_raw = (body or {}).get('limit')
    limit = int(limit_raw) if isinstance(limit_raw, int) and limit_raw > 0 else None

    try:
        out = run_benchmark(
            semantic_mode_name=semantic_mode,
            root_mode=root_mode,
            preload_from_demo=preload_from_demo,
            preload_turns_max=preload_turns_max,
            limit=limit,
        )
        return out
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.get('/demo/benchmark/last')
def benchmark_last():
    history = read_benchmark_history(limit=20)
    latest_compare = None
    if len(history) >= 2:
        left = str((history[1].get('summary') or {}).get('run_id') or history[1].get('run_id') or '')
        right = str((history[0].get('summary') or {}).get('run_id') or history[0].get('run_id') or '')
        if left and right:
            cmp = compare_benchmark_runs(left, right)
            latest_compare = cmp.get('compare') if cmp.get('ok') else None
    return {
        'ok': bool(LAST_BENCHMARK_REPORT),
        'summary': dict(LAST_BENCHMARK_SUMMARY or {}),
        'report': dict(LAST_BENCHMARK_REPORT or {}),
        'history': history,
        'latest_compare': latest_compare,
    }


@router.get('/demo/benchmark/history')
def benchmark_history(limit: int = 20):
    return {'ok': True, 'history': read_benchmark_history(limit=max(1, min(200, int(limit))))}


@router.get('/demo/benchmark/compare/{left_run_id}/{right_run_id}')
def benchmark_compare(left_run_id: str, right_run_id: str):
    out = compare_benchmark_runs(left_run_id, right_run_id)
    status = 200 if out.get('ok') else 404
    return JSONResponse(out, status_code=status)


@router.post('/demo/entities/merge/suggest')
async def merge_suggest(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    min_score = float((body or {}).get('min_score') or 0.86)
    max_pairs = int((body or {}).get('max_pairs') or 40)
    source = str((body or {}).get('source') or 'demo').strip() or 'demo'
    try:
        out = suggest_entity_merges(min_score=min_score, max_pairs=max_pairs, source=source)
        return {'ok': bool(out.get('ok', True)), **dict(out or {})}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


@router.post('/demo/entities/merge/decide')
async def merge_decide(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    proposal_id = str((body or {}).get('proposal_id') or '').strip()
    decision = str((body or {}).get('decision') or '').strip().lower()
    keep_entity_id = str((body or {}).get('keep_entity_id') or '').strip() or None
    reviewer = str((body or {}).get('reviewer') or 'demo').strip() or 'demo'
    notes = str((body or {}).get('notes') or '').strip()
    apply = bool((body or {}).get('apply', True))

    if not proposal_id:
        return JSONResponse({'ok': False, 'error': 'missing_proposal_id'}, status_code=400)
    if decision not in {'accept', 'reject'}:
        return JSONResponse({'ok': False, 'error': 'invalid_decision'}, status_code=400)

    try:
        out = decide_entity_merge(
            proposal_id=proposal_id,
            decision=decision,
            keep_entity_id=keep_entity_id,
            reviewer=reviewer,
            notes=notes,
            apply=apply,
        )
        status = 200 if out.get('ok') else 400
        return JSONResponse({'ok': bool(out.get('ok')), **dict(out or {})}, status_code=status)
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}
