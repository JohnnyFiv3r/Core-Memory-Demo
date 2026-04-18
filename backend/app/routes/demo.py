from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.abuse import heavy_operation_slot, rate_limit_chat, rate_limit_general, rate_limit_heavy
from app.core.auth import auth_meta_payload, require_admin
from app.core.config import settings
from app.core.state_fallback import safe_state_fallback
from app.core.runtime import (
    compare_benchmark_runs,
    decide_entity_merge,
    get_story_pack_meta,
    get_last_benchmark_snapshot,
    inspect_bead_hydration_payload,
    inspect_bead_payload,
    inspect_claim_slot_payload,
    inspect_state_payload,
    inspect_turns_payload,
    list_demo_model_options,
    read_benchmark_history,
    replay_story_pack,
    run_benchmark,
    run_chat,
    run_flush,
    reset_test_session,
    seed_demo_history,
    set_demo_model_override,
    suggest_entity_merges,
)

public_router = APIRouter(prefix='/api', tags=['demo-public'])
router = APIRouter(prefix='/api', tags=['demo'], dependencies=[Depends(require_admin), Depends(rate_limit_general)])

CHAT_JOB_TTL_SECONDS = 15 * 60
CHAT_JOB_POLL_MS = 450
CHAT_JOB_MAX_EVENTS = 48
CHAT_JOBS: dict[str, dict[str, Any]] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _prune_chat_jobs() -> None:
    now = _now_ms()
    ttl_ms = int(CHAT_JOB_TTL_SECONDS * 1000)
    stale: list[str] = []
    for job_id, row in list(CHAT_JOBS.items()):
        updated = int((row or {}).get('updated_ms') or 0)
        done = bool((row or {}).get('done'))
        age_ms = now - updated
        if done and age_ms > ttl_ms:
            stale.append(job_id)
        elif not done and age_ms > max(ttl_ms * 2, 60_000):
            stale.append(job_id)
    for job_id in stale:
        CHAT_JOBS.pop(job_id, None)


def _chat_event(row: dict[str, Any], stage: str, message: str, **extra: Any) -> None:
    events = list(row.get('events') or [])
    seq = int(row.get('seq') or 0) + 1
    evt: dict[str, Any] = {
        'seq': seq,
        'ts_ms': _now_ms(),
        'stage': str(stage or ''),
        'message': str(message or ''),
    }
    for k, v in dict(extra or {}).items():
        if v is None:
            continue
        evt[str(k)] = v
    events.append(evt)
    if len(events) > CHAT_JOB_MAX_EVENTS:
        events = events[-CHAT_JOB_MAX_EVENTS:]
    row['events'] = events
    row['seq'] = seq
    row['stage'] = str(stage or '')
    row['updated_ms'] = _now_ms()


def _chat_job_payload(row: dict[str, Any], *, cursor: int = 0) -> dict[str, Any]:
    events = [e for e in list(row.get('events') or []) if int((e or {}).get('seq') or 0) > int(cursor)]
    next_cursor = int(cursor)
    if events:
        next_cursor = int((events[-1] or {}).get('seq') or cursor)

    out: dict[str, Any] = {
        'ok': True,
        'job_id': str(row.get('job_id') or ''),
        'status': str(row.get('status') or 'running'),
        'stage': str(row.get('stage') or ''),
        'done': bool(row.get('done')),
        'poll_after_ms': CHAT_JOB_POLL_MS,
        'events': events,
        'cursor_next': next_cursor,
        'started_ms': int(row.get('started_ms') or 0),
        'updated_ms': int(row.get('updated_ms') or 0),
        'elapsed_ms': max(0, _now_ms() - int(row.get('started_ms') or _now_ms())),
    }
    if row.get('error'):
        out['error'] = str(row.get('error') or '')
    if bool(row.get('done')) and isinstance(row.get('result'), dict):
        out['result'] = dict(row.get('result') or {})
    return out


async def _run_chat_job(job_id: str, message: str) -> None:
    row = CHAT_JOBS.get(job_id)
    if not isinstance(row, dict):
        return

    row['status'] = 'running'
    _chat_event(row, 'queued', 'Request accepted, starting chat pipeline')

    def progress(stage: str, text: str, **extra: Any) -> None:
        current = CHAT_JOBS.get(job_id)
        if not isinstance(current, dict):
            return
        _chat_event(current, stage, text, **extra)

    try:
        out = await run_chat(message, progress=progress)
        current = CHAT_JOBS.get(job_id)
        if not isinstance(current, dict):
            return
        current['status'] = 'completed'
        current['done'] = True
        current['result'] = dict(out or {})
        current['updated_ms'] = _now_ms()
        _chat_event(current, 'done', 'Assistant response ready', turn_id=str((out or {}).get('turn_id') or ''))
    except Exception as exc:
        current = CHAT_JOBS.get(job_id)
        if not isinstance(current, dict):
            return
        current['status'] = 'failed'
        current['done'] = True
        current['error'] = str(exc or 'chat_failed')
        current['updated_ms'] = _now_ms()
        _chat_event(current, 'failed', 'Chat failed', error=str(exc or 'chat_failed'))


def _http_exc_response(exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    payload: dict[str, object] = {'ok': False, 'error': detail}
    if detail == 'heavy_operation_in_progress':
        payload['hint'] = 'heavy endpoints are concurrency-scoped per caller; retry shortly or serialize parallel heavy requests per caller/session'
    return JSONResponse(payload, status_code=int(exc.status_code), headers=dict(exc.headers or {}))


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


@router.get('/demo/models')
def demo_models():
    try:
        return list_demo_model_options()
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/demo/model')
async def demo_model_set(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    model_id = str((body or {}).get('model_id') or '').strip()
    try:
        return set_demo_model_override(model_id or None)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)


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


@router.post('/chat/start', dependencies=[Depends(rate_limit_chat)])
async def chat_start(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    message = str((body or {}).get('message') or (body or {}).get('query') or '').strip()
    if not message:
        return JSONResponse({'ok': False, 'error': 'missing_message'}, status_code=400)

    _prune_chat_jobs()
    job_id = uuid.uuid4().hex[:12]
    started = _now_ms()
    CHAT_JOBS[job_id] = {
        'job_id': job_id,
        'status': 'queued',
        'stage': 'queued',
        'done': False,
        'error': '',
        'result': None,
        'seq': 0,
        'events': [],
        'started_ms': started,
        'updated_ms': started,
    }
    task = asyncio.create_task(_run_chat_job(job_id, message))
    CHAT_JOBS[job_id]['task'] = task
    _chat_event(CHAT_JOBS[job_id], 'queued', 'Chat request queued')
    return {
        'ok': True,
        'job_id': job_id,
        'status': 'queued',
        'poll_after_ms': CHAT_JOB_POLL_MS,
    }


@router.get('/chat/status/{job_id}')
def chat_status(job_id: str, cursor: int = 0):
    _prune_chat_jobs()
    row = CHAT_JOBS.get(str(job_id or '').strip())
    if not isinstance(row, dict):
        return JSONResponse({'ok': False, 'error': 'chat_job_not_found'}, status_code=404)
    return _chat_job_payload(row, cursor=max(0, int(cursor)))


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
async def flush(request: Request):
    try:
        with heavy_operation_slot(request):
            await rate_limit_heavy(request)
            return run_flush()
    except HTTPException as exc:
        return _http_exc_response(exc)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/session/reset')
async def session_reset(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    wipe_memory = bool((body or {}).get('wipe_memory', False))
    try:
        with heavy_operation_slot(request):
            await rate_limit_heavy(request)
            return reset_test_session(wipe_memory=wipe_memory)
    except HTTPException as exc:
        return _http_exc_response(exc)
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
        with heavy_operation_slot(request):
            await rate_limit_heavy(request)
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
    except HTTPException as exc:
        return _http_exc_response(exc)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.get('/story-pack/meta')
def story_pack_meta():
    try:
        return get_story_pack_meta()
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/story-pack/replay')
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
        with heavy_operation_slot(request):
            await rate_limit_heavy(request)
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
    except HTTPException as exc:
        return _http_exc_response(exc)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.post('/benchmark-run')
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
        with heavy_operation_slot(request):
            await rate_limit_heavy(request)
            out = run_benchmark(
                subset=subset,
                semantic_mode_name=semantic_mode,
                root_mode=root_mode,
                preload_from_demo=preload_from_demo,
                preload_turns_max=preload_turns_max,
                limit=limit,
            )
        return out
    except HTTPException as exc:
        return _http_exc_response(exc)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.get('/demo/benchmark/last')
def benchmark_last():
    snapshot = get_last_benchmark_snapshot(history_limit=20)
    history = list(snapshot.get('history') or [])
    latest_compare = None
    if len(history) >= 2:
        left = str((history[1].get('summary') or {}).get('run_id') or history[1].get('run_id') or '')
        right = str((history[0].get('summary') or {}).get('run_id') or history[0].get('run_id') or '')
        if left and right:
            cmp = compare_benchmark_runs(left, right)
            latest_compare = cmp.get('compare') if cmp.get('ok') else None
    return {
        'ok': bool(snapshot.get('ok')),
        'summary': dict(snapshot.get('summary') or {}),
        'report': dict(snapshot.get('report') or {}),
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
