from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.abuse import heavy_operation_slot, rate_limit_chat, rate_limit_general, rate_limit_heavy
from app.core.auth import auth_meta_payload, require_admin
from app.core.config import settings
from app.core.state_fallback import safe_state_fallback
from app.core.runtime import (
    compare_benchmark_runs,
    decide_entity_merge,
    get_story_pack_meta,
    inspect_bead_hydration_payload,
    inspect_bead_payload,
    inspect_claim_slot_payload,
    inspect_state_payload,
    inspect_turns_payload,
    read_benchmark_history,
    replay_story_pack,
    run_benchmark,
    run_chat,
    run_flush,
    reset_test_session,
    seed_demo_history,
    suggest_entity_merges,
    LAST_BENCHMARK_REPORT,
    LAST_BENCHMARK_SUMMARY,
)

public_router = APIRouter(prefix='/api', tags=['demo-public'])
router = APIRouter(prefix='/api', tags=['demo'], dependencies=[Depends(require_admin), Depends(rate_limit_general)])


@public_router.get('/meta')
def meta():
    return {
        'ok': True,
        'message': 'Core Memory Demo backend active',
        'contract_status': 't2_in_progress',
        'auth': auth_meta_payload(),
    }


@router.get('/demo/state')
def demo_state(as_of: str | None = None):
    try:
        return inspect_state_payload(as_of=as_of)
    except Exception as exc:
        return JSONResponse(safe_state_fallback(str(exc)), status_code=200)


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


@router.post('/chat', dependencies=[Depends(rate_limit_chat)])
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
        with heavy_operation_slot():
            return run_flush()
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/session/reset', dependencies=[Depends(rate_limit_heavy)])
async def session_reset(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    wipe_memory = bool((body or {}).get('wipe_memory', False))
    try:
        with heavy_operation_slot():
            return reset_test_session(wipe_memory=wipe_memory)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/seed', dependencies=[Depends(rate_limit_heavy)])
async def seed(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    messages = (body or {}).get('messages')
    max_turns_raw = (body or {}).get('max_turns')
    max_turns = None
    if isinstance(max_turns_raw, int) and max_turns_raw > 0:
        max_turns = int(max_turns_raw)
    if isinstance(max_turns, int) and max_turns > 0:
        max_turns = min(max_turns, max(1, int(settings.seed_max_turns)))

    wait_for_idle = bool((body or {}).get('wait_for_idle', False))
    idle_timeout_ms_raw = (body or {}).get('idle_timeout_ms')
    idle_timeout_ms = int(idle_timeout_ms_raw) if isinstance(idle_timeout_ms_raw, int) and idle_timeout_ms_raw > 0 else 120000

    idle_poll_ms_raw = (body or {}).get('idle_poll_ms')
    idle_poll_ms = int(idle_poll_ms_raw) if isinstance(idle_poll_ms_raw, int) and idle_poll_ms_raw > 0 else 250

    auto_flush = bool((body or {}).get('auto_flush', True))
    flush_threshold_ratio_raw = (body or {}).get('flush_threshold_ratio')
    flush_threshold_ratio = float(flush_threshold_ratio_raw) if isinstance(flush_threshold_ratio_raw, (int, float)) else 0.80

    flush_every_turns_raw = (body or {}).get('flush_every_turns')
    flush_every_turns = int(flush_every_turns_raw) if isinstance(flush_every_turns_raw, int) and flush_every_turns_raw > 0 else 0

    max_compaction_per_pass_raw = (body or {}).get('max_compaction_per_pass')
    max_compaction_per_pass = int(max_compaction_per_pass_raw) if isinstance(max_compaction_per_pass_raw, int) and max_compaction_per_pass_raw > 0 else 2

    max_side_effects_per_pass_raw = (body or {}).get('max_side_effects_per_pass')
    max_side_effects_per_pass = int(max_side_effects_per_pass_raw) if isinstance(max_side_effects_per_pass_raw, int) and max_side_effects_per_pass_raw > 0 else 8
    try:
        with heavy_operation_slot():
            out = await seed_demo_history(
                messages=messages if isinstance(messages, list) else None,
                max_turns=max_turns,
                wait_for_idle=wait_for_idle,
                idle_timeout_ms=idle_timeout_ms,
                idle_poll_ms=idle_poll_ms,
                auto_flush=auto_flush,
                flush_threshold_ratio=flush_threshold_ratio,
                flush_every_turns=flush_every_turns,
                max_compaction_per_pass=max_compaction_per_pass,
                max_side_effects_per_pass=max_side_effects_per_pass,
            )
        state = inspect_state_payload()
        out['stats'] = state.get('stats') or {}
        code = 200 if bool(out.get('ok')) else 400
        return JSONResponse(out, status_code=code)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.get('/story-pack/meta')
def story_pack_meta():
    try:
        return get_story_pack_meta()
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/story-pack/replay', dependencies=[Depends(rate_limit_heavy)])
async def story_pack_replay(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}

    max_turns_raw = (body or {}).get('max_turns')
    max_turns = int(max_turns_raw) if isinstance(max_turns_raw, int) and max_turns_raw > 0 else None

    start_turn_raw = (body or {}).get('start_turn')
    start_turn = int(start_turn_raw) if isinstance(start_turn_raw, int) and start_turn_raw > 0 else None

    end_turn_raw = (body or {}).get('end_turn')
    end_turn = int(end_turn_raw) if isinstance(end_turn_raw, int) and end_turn_raw > 0 else None

    max_allowed_replay = max(1, int(settings.replay_max_turns))
    if isinstance(max_turns, int) and max_turns > 0:
        max_turns = min(max_turns, max_allowed_replay)

    wait_for_idle = bool((body or {}).get('wait_for_idle', False))

    idle_timeout_ms_raw = (body or {}).get('idle_timeout_ms')
    idle_timeout_ms = int(idle_timeout_ms_raw) if isinstance(idle_timeout_ms_raw, int) and idle_timeout_ms_raw > 0 else 120000

    idle_poll_ms_raw = (body or {}).get('idle_poll_ms')
    idle_poll_ms = int(idle_poll_ms_raw) if isinstance(idle_poll_ms_raw, int) and idle_poll_ms_raw > 0 else 250

    max_compaction_per_pass_raw = (body or {}).get('max_compaction_per_pass')
    max_compaction_per_pass = int(max_compaction_per_pass_raw) if isinstance(max_compaction_per_pass_raw, int) and max_compaction_per_pass_raw > 0 else 2

    max_side_effects_per_pass_raw = (body or {}).get('max_side_effects_per_pass')
    max_side_effects_per_pass = int(max_side_effects_per_pass_raw) if isinstance(max_side_effects_per_pass_raw, int) and max_side_effects_per_pass_raw > 0 else 8

    run_checkpoints = bool((body or {}).get('run_checkpoints', True))
    reset_session = bool((body or {}).get('reset_session', True))
    use_manifest_sessions = bool((body or {}).get('use_manifest_sessions', True))
    auto_flush = bool((body or {}).get('auto_flush', True))
    flush_threshold_ratio_raw = (body or {}).get('flush_threshold_ratio')
    flush_threshold_ratio = float(flush_threshold_ratio_raw) if isinstance(flush_threshold_ratio_raw, (int, float)) else 0.80
    flush_every_turns_raw = (body or {}).get('flush_every_turns')
    flush_every_turns = int(flush_every_turns_raw) if isinstance(flush_every_turns_raw, int) and flush_every_turns_raw > 0 else 0
    benchmark_semantic_mode = str((body or {}).get('benchmark_semantic_mode') or 'required').strip() or 'required'

    benchmark_limit_raw = (body or {}).get('benchmark_limit')
    benchmark_limit = int(benchmark_limit_raw) if isinstance(benchmark_limit_raw, int) and benchmark_limit_raw > 0 else None
    if isinstance(benchmark_limit, int) and benchmark_limit > 0:
        benchmark_limit = min(benchmark_limit, max(1, int(settings.benchmark_limit_max_cases)))

    try:
        with heavy_operation_slot():
            out = await replay_story_pack(
                max_turns=max_turns,
                start_turn=start_turn,
                end_turn=end_turn,
                wait_for_idle=wait_for_idle,
                idle_timeout_ms=idle_timeout_ms,
                idle_poll_ms=idle_poll_ms,
                max_compaction_per_pass=max_compaction_per_pass,
                max_side_effects_per_pass=max_side_effects_per_pass,
                run_checkpoints=run_checkpoints,
                reset_session=reset_session,
                use_manifest_sessions=use_manifest_sessions,
                auto_flush=auto_flush,
                flush_threshold_ratio=flush_threshold_ratio,
                flush_every_turns=flush_every_turns,
                benchmark_semantic_mode=benchmark_semantic_mode,
                benchmark_limit=benchmark_limit,
            )
        code = 200 if bool(out.get('ok')) else 400
        return JSONResponse(out, status_code=code)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/benchmark-run', dependencies=[Depends(rate_limit_heavy)])
async def benchmark_run(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    subset = str((body or {}).get('subset') or 'local').strip().lower() or 'local'
    if subset not in {'local', 'full'}:
        subset = 'local'
    semantic_mode = str((body or {}).get('semantic_mode') or 'degraded_allowed').strip() or 'degraded_allowed'
    root_mode = str((body or {}).get('root_mode') or 'snapshot').strip().lower() or 'snapshot'
    if root_mode not in {'snapshot', 'clean'}:
        root_mode = 'snapshot'
    preload_from_demo = bool((body or {}).get('preload_from_demo', False))
    preload_turns_max = int((body or {}).get('preload_turns_max') or 200)
    preload_turns_max = min(max(1, preload_turns_max), max(1, int(settings.benchmark_preload_turns_max)))
    limit_raw = (body or {}).get('limit')
    limit = int(limit_raw) if isinstance(limit_raw, int) and limit_raw > 0 else None
    if isinstance(limit, int) and limit > 0:
        limit = min(limit, max(1, int(settings.benchmark_limit_max_cases)))

    try:
        with heavy_operation_slot():
            out = run_benchmark(
                subset=subset,
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


@router.post('/demo/entities/merge/suggest', dependencies=[Depends(rate_limit_heavy)])
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


@router.post('/demo/entities/merge/decide', dependencies=[Depends(rate_limit_heavy)])
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
