from __future__ import annotations

import asyncio
import json
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from pathlib import Path
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.benchmarks import benchmark_store
from app.benchmarks.locomo_loader import LocomoLoaderError
from app.benchmarks.locomo_suite import build_locomo_suite_metadata
from app.core.abuse import heavy_operation_slot, rate_limit_chat, rate_limit_general, rate_limit_heavy
from app.core.auth import auth_meta_payload, require_admin
from app.core.config import settings
from app.core.state_fallback import safe_state_fallback
from app.core.runtime import (
    compare_benchmark_runs,
    decide_entity_merge,
    detect_model,
    get_locomo_meta,
    get_story_pack_meta,
    get_last_benchmark_snapshot,
    inspect_bead_hydration_payload,
    inspect_bead_payload,
    inspect_claim_slot_payload,
    inspect_state_payload,
    inspect_turns_payload,
    list_demo_model_options,
    read_benchmark_history,
    replay_locomo_corpus,
    replay_story_pack,
    run_benchmark,
    run_chat,
    run_flush,
    run_recall,
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
BENCHMARK_JOB_TTL_SECONDS = 30 * 60
BENCHMARK_JOB_POLL_MS = 1200
BENCHMARK_JOB_MAX_EVENTS = 128
BENCHMARK_JOBS: dict[str, dict[str, Any]] = {}
ACTIVE_BENCHMARK_JOB_ID: str | None = None
SEED_STATUS: dict[str, Any] = {
    'active': False,
    'kind': '',
    'status': 'idle',
    'updated_ms': 0,
    'message': '',
}


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



def _prune_benchmark_jobs() -> None:
    global ACTIVE_BENCHMARK_JOB_ID

    now = _now_ms()
    ttl_ms = int(BENCHMARK_JOB_TTL_SECONDS * 1000)
    stale: list[str] = []
    for job_id, row in list(BENCHMARK_JOBS.items()):
        updated = int((row or {}).get('updated_ms') or 0)
        done = bool((row or {}).get('done'))
        age_ms = now - updated
        if done and age_ms > ttl_ms:
            stale.append(job_id)
        elif not done and age_ms > max(ttl_ms * 2, 10 * 60_000):
            stale.append(job_id)
    for job_id in stale:
        BENCHMARK_JOBS.pop(job_id, None)
        if ACTIVE_BENCHMARK_JOB_ID == job_id:
            ACTIVE_BENCHMARK_JOB_ID = None


def _strip_benchmark_case_payloads(value: Any) -> Any:
    """Return a copy of benchmark history data without heavyweight case arrays."""

    if isinstance(value, list):
        return [_strip_benchmark_case_payloads(item) for item in value]
    if not isinstance(value, dict):
        return value

    out: dict[str, Any] = {}
    heavy_lists = {'cases', 'rows', 'benchmark_table'}
    for key, item in value.items():
        if key in heavy_lists and isinstance(item, list):
            out[key] = []
            out[f'{key}_omitted'] = len(item)
            continue
        out[key] = _strip_benchmark_case_payloads(item)
    return out


def _slim_benchmark_history(history: list[Any]) -> list[Any]:
    return [
        {
            'run_id': str(((row.get('summary') or {}).get('run_id') or row.get('run_id') or '')),
            'created_at': str(row.get('created_at') or ''),
            'summary': dict(row.get('summary') or {}),
        } if isinstance(row, dict) else row
        for row in list(history or [])
    ]


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


def _set_seed_status(*, active: bool, kind: str, status: str, message: str) -> None:
    SEED_STATUS.update({
        'active': bool(active),
        'kind': str(kind or ''),
        'status': str(status or ''),
        'updated_ms': _now_ms(),
        'message': str(message or ''),
    })


def _benchmark_job_payload(row: dict[str, Any], *, cursor: int = 0) -> dict[str, Any]:
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
        'poll_after_ms': BENCHMARK_JOB_POLL_MS,
        'events': events,
        'cursor_next': next_cursor,
        'started_ms': int(row.get('started_ms') or 0),
        'updated_ms': int(row.get('updated_ms') or 0),
        'elapsed_ms': max(0, _now_ms() - int(row.get('started_ms') or _now_ms())),
        'abandoned': bool(row.get('abandoned')),
    }
    if row.get('error'):
        out['error'] = str(row.get('error') or '')
    if bool(row.get('done')) and isinstance(row.get('result'), dict):
        out['result'] = dict(row.get('result') or {})
    return out


def _stored_benchmark_job_payload(stored: dict[str, Any], *, cursor: int = 0) -> dict[str, Any]:
    status = str((stored or {}).get('status') or '')
    done = status in {'completed', 'failed'}
    result = stored.get('result') if isinstance(stored.get('result'), dict) else None
    out: dict[str, Any] = {
        'ok': True,
        'job_id': str((stored or {}).get('job_id') or ''),
        'status': status,
        'stage': status,
        'done': done,
        'error': (stored or {}).get('error'),
        'result': result,
        'events': [],
        'cursor': int(cursor),
        'cursor_next': int(cursor),
    }
    for key in ('created_at', 'updated_at', 'started_at', 'finished_at'):
        value = (stored or {}).get(key)
        if value:
            out[key] = value
    return out


def _benchmark_event(row: dict[str, Any], stage: str, message: str, **extra: Any) -> None:
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
    if len(events) > BENCHMARK_JOB_MAX_EVENTS:
        events = events[-BENCHMARK_JOB_MAX_EVENTS:]
    row['events'] = events
    row['seq'] = seq
    row['stage'] = str(stage or '')
    row['updated_ms'] = _now_ms()


def _dispatch_benchmark_job(job_id: str, body: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    url = str(settings.benchmark_dispatch_url or '').strip()
    if not url:
        return {'ok': False, 'error': 'benchmark_dispatch_not_configured'}

    payload = {
        'job_id': str(job_id or ''),
        'request': dict(body or {}),
        'kwargs': dict(kwargs or {}),
    }
    headers = {'Content-Type': 'application/json'}
    token = str(settings.benchmark_dispatch_token or '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    timeout = max(1, int(settings.benchmark_dispatch_timeout_seconds))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', 'replace')
            try:
                data = json.loads(raw) if raw.strip() else {}
            except Exception:
                data = {'raw': raw[:1000]}
            return {'ok': 200 <= int(resp.status) < 300, 'status_code': int(resp.status), **dict(data or {})}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:1000]
        return {'ok': False, 'status_code': int(exc.code), 'error': f'benchmark_dispatch_http_{exc.code}', 'detail': detail}
    except Exception as exc:
        return {'ok': False, 'error': f'benchmark_dispatch_failed:{exc}'}


def _active_benchmark_summary(row: dict[str, Any]) -> dict[str, Any]:
    events = list(row.get('events') or [])
    latest = dict(events[-1] or {}) if events else {}
    kwargs = dict(row.get('kwargs') or {})
    return {
        'run_id': '',
        'job_id': str(row.get('job_id') or ''),
        'status': str(row.get('status') or 'running'),
        'phase': str(row.get('stage') or latest.get('stage') or 'working'),
        'started_at': datetime.fromtimestamp(int(row.get('started_ms') or _now_ms()) / 1000, timezone.utc).isoformat(),
        'updated_at': datetime.fromtimestamp(int(row.get('updated_ms') or _now_ms()) / 1000, timezone.utc).isoformat(),
        'suite': str(kwargs.get('suite') or ''),
        'root_mode': str(kwargs.get('root_mode') or ''),
        'semantic_mode': str(kwargs.get('semantic_mode_name') or ''),
        'answer_mode': str(kwargs.get('answer_mode') or ''),
        'retrieval_k': int(kwargs.get('retrieval_k') or 0),
        'qa_completed': int(latest.get('qa_completed') or 0),
        'qa_cases': int(latest.get('qa_total') or 0),
        'sample_id': str(latest.get('sample_id') or ''),
        'qa_id': str(latest.get('qa_id') or ''),
        'case_status': str(latest.get('case_status') or ''),
        'warnings': [],
        'active': True,
    }


def _active_benchmark_state(active_job: dict[str, Any], snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    active_summary = _active_benchmark_summary(active_job)
    report = dict(snapshot.get('report') or {})
    active_job_id = str(active_job.get('job_id') or '')
    if active_job_id:
        summary = active_summary
        summary['active'] = True
        compact_report: dict[str, Any] = {
            'live': True,
            'run_id': '',
            'status': str(summary.get('status') or active_job.get('status') or 'running'),
            'phase': str(summary.get('phase') or active_job.get('stage') or 'working'),
            'active_job_id': active_job_id,
            'active': True,
            'qa_completed': int(summary.get('qa_completed') or 0),
            'qa_cases': int(summary.get('qa_cases') or 0),
            'sample_id': str(summary.get('sample_id') or ''),
            'qa_id': str(summary.get('qa_id') or ''),
            'case_status': str(summary.get('case_status') or ''),
        }
        for key in (
            'started_at',
            'finished_at',
            'suite',
            'root_mode',
            'semantic_mode',
            'answer_mode',
            'retrieval_k',
            'artifact_path',
            'warnings',
            'samples',
            'qa_cases',
            'turns_ingested',
            'preload_turn_count',
            'backend_modes',
        ):
            if key in summary:
                compact_report[key] = summary.get(key)
        config = report.get('config')
        kwargs = dict(active_job.get('kwargs') or {})
        if isinstance(config, dict) and config:
            compact_report['config'] = {
                'suite': str(kwargs.get('suite') or config.get('suite') or summary.get('suite') or ''),
                'root_mode': str(kwargs.get('root_mode') or config.get('root_mode') or summary.get('root_mode') or ''),
                'semantic_mode': str(kwargs.get('semantic_mode_name') or config.get('semantic_mode') or summary.get('semantic_mode') or ''),
                'answer_mode': str(kwargs.get('answer_mode') or config.get('answer_mode') or summary.get('answer_mode') or ''),
                'retrieval_k': int(kwargs.get('retrieval_k') or config.get('retrieval_k') or summary.get('retrieval_k') or 0),
                'qa_session_mode': str(kwargs.get('qa_session_mode') or config.get('qa_session_mode') or ''),
            }
        elif summary:
            compact_report['config'] = {
                'suite': str(summary.get('suite') or ''),
                'root_mode': str(summary.get('root_mode') or ''),
                'semantic_mode': str(summary.get('semantic_mode') or ''),
                'answer_mode': str(summary.get('answer_mode') or ''),
                'retrieval_k': int(summary.get('retrieval_k') or 0),
                'qa_session_mode': str(kwargs.get('qa_session_mode') or ''),
            }
        dataset = report.get('dataset')
        if isinstance(dataset, dict) and dataset:
            compact_report['dataset'] = {
                'dataset_path': str(dataset.get('dataset_path') or summary.get('dataset_path') or ''),
                'samples': int(dataset.get('samples') or summary.get('samples') or 0),
                'qa_total': int(dataset.get('qa_total') or summary.get('qa_cases') or 0),
                'turns_total': int(dataset.get('turns_total') or summary.get('turns_ingested') or 0),
                'selected_samples': int(dataset.get('selected_samples') or summary.get('samples') or 0),
                'selected_qa_cases': int(dataset.get('selected_qa_cases') or summary.get('qa_cases') or 0),
                'python_version': str(dataset.get('python_version') or ''),
            }
            sample_ids = dataset.get('selected_sample_ids')
            if isinstance(sample_ids, list) and sample_ids:
                compact_report['dataset']['selected_sample_ids'] = [str(x) for x in sample_ids[:10] if str(x).strip()]
        environment = report.get('environment')
        if isinstance(environment, dict) and environment:
            compact_report['environment'] = {
                'embeddings_provider': str(environment.get('embeddings_provider') or ''),
                'embeddings_model': str(environment.get('embeddings_model') or ''),
            }
        semantic_build = report.get('semantic_build')
        if isinstance(semantic_build, dict) and semantic_build:
            compact_report['semantic_build'] = {
                'ok': bool(semantic_build.get('ok')),
                'backend': semantic_build.get('backend'),
                'entries': semantic_build.get('entries'),
                'error': semantic_build.get('error'),
            }
        return summary, compact_report
    summary = active_summary
    report = {
        'status': str(active_job.get('status') or 'running'),
        'phase': str(active_job.get('stage') or 'working'),
        'active_job_id': active_job_id,
        'active': True,
    }
    return summary, report


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


async def _run_benchmark_job(job_id: str, kwargs: dict[str, Any]) -> None:
    global ACTIVE_BENCHMARK_JOB_ID

    row = BENCHMARK_JOBS.get(job_id)
    if not isinstance(row, dict):
        return

    row['status'] = 'waiting_for_slot'
    _benchmark_event(row, 'queued', 'Benchmark request accepted')

    while ACTIVE_BENCHMARK_JOB_ID and ACTIVE_BENCHMARK_JOB_ID != job_id:
        current = BENCHMARK_JOBS.get(job_id)
        if not isinstance(current, dict):
            return
        if bool(current.get('abandoned')):
            current['status'] = 'abandoned'
            current['done'] = True
            current['updated_ms'] = _now_ms()
            _benchmark_event(current, 'abandoned', 'Benchmark abandoned before start')
            return
        await asyncio.sleep(0.25)

    ACTIVE_BENCHMARK_JOB_ID = job_id
    row['status'] = 'running'
    _benchmark_event(row, 'starting', 'Benchmark started')

    def progress(completed: int, total: int, case: dict[str, Any], result: dict[str, Any]) -> None:
        current = BENCHMARK_JOBS.get(job_id)
        if not isinstance(current, dict):
            return
        current['status'] = 'running'
        current['updated_ms'] = _now_ms()
        stage = str((result or {}).get('phase') or 'retrieving').strip().lower() or 'retrieving'
        status = str((result or {}).get('status') or '').strip()
        _benchmark_event(
            current,
            stage,
            f'QA {int(completed)}/{int(total)}',
            qa_completed=int(completed),
            qa_total=int(total),
            sample_id=str((case or {}).get('sample_id') or ''),
            qa_id=str((case or {}).get('qa_id') or ''),
            case_status=status,
        )

    try:
        out = await asyncio.to_thread(run_benchmark, progress=progress, **kwargs)
        current = BENCHMARK_JOBS.get(job_id)
        if not isinstance(current, dict):
            return
        current['status'] = 'completed' if bool((out or {}).get('ok')) else 'failed'
        current['done'] = True
        current['result'] = dict(out or {})
        current['updated_ms'] = _now_ms()
        if bool(current.get('abandoned')):
            _benchmark_event(current, 'abandoned', 'Benchmark finished after being superseded')
        elif bool((out or {}).get('ok')):
            _benchmark_event(current, 'done', 'Benchmark completed', run_id=str(((out or {}).get('summary') or {}).get('run_id') or ''))
        else:
            current['error'] = str((out or {}).get('error') or 'benchmark_failed')
            _benchmark_event(current, 'failed', 'Benchmark failed', error=current['error'])
    except Exception as exc:
        current = BENCHMARK_JOBS.get(job_id)
        if not isinstance(current, dict):
            return
        current['status'] = 'failed'
        current['done'] = True
        current['error'] = str(exc or 'benchmark_failed')
        current['updated_ms'] = _now_ms()
        _benchmark_event(current, 'failed', 'Benchmark failed', error=current['error'])
    finally:
        if ACTIVE_BENCHMARK_JOB_ID == job_id:
            ACTIVE_BENCHMARK_JOB_ID = None


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


@router.post('/recall', dependencies=[Depends(rate_limit_chat)])
async def recall_endpoint(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    query = str((body or {}).get('query') or (body or {}).get('message') or '').strip()
    if not query:
        return JSONResponse({'ok': False, 'error': 'missing_query'}, status_code=400)
    effort = str((body or {}).get('effort') or 'medium').strip().lower() or 'medium'
    speaker = str((body or {}).get('speaker') or '').strip() or None
    include_raw = bool((body or {}).get('include_raw', False))
    k_raw = (body or {}).get('k')
    k: int | None = None
    if k_raw not in (None, ''):
        try:
            k = max(1, int(k_raw))
        except Exception:
            return JSONResponse({'ok': False, 'error': 'invalid_k'}, status_code=400)
    try:
        out = run_recall(query, effort=effort, speaker=speaker, k=k, include_raw=include_raw)
        status = 200 if bool(out.get('ok', True)) else 400
        return JSONResponse(out, status_code=status)
    except ValueError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


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


@public_router.get('/locomo/ping')
def locomo_ping():
    return {'ok': True, 'route': 'locomo-public', 'meta_route': '/api/locomo/meta'}


@public_router.get('/locomo/meta')
def locomo_meta():
    try:
        return get_locomo_meta()
    except FileNotFoundError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.get('/demo/seed-status')
def demo_seed_status():
    return {'ok': True, **dict(SEED_STATUS)}


@router.get('/demo/control-state')
def demo_control_state():
    _prune_benchmark_jobs()
    active_job = BENCHMARK_JOBS.get(str(ACTIVE_BENCHMARK_JOB_ID or '').strip()) if ACTIVE_BENCHMARK_JOB_ID else None
    benchmark_job = _benchmark_job_payload(active_job, cursor=0) if isinstance(active_job, dict) else None
    snapshot = get_last_benchmark_snapshot(history_limit=3)
    benchmark_summary = dict(snapshot.get('summary') or {})
    benchmark_report = _strip_benchmark_case_payloads(dict(snapshot.get('report') or {}))
    benchmark_history = list(snapshot.get('history') or [])
    if isinstance(active_job, dict):
        benchmark_summary, benchmark_report = _active_benchmark_state(active_job, snapshot)
        benchmark_history = benchmark_history[:2]
    return {
        'ok': True,
        'seed': dict(SEED_STATUS),
        'benchmark': {
            'active_job_id': str(ACTIVE_BENCHMARK_JOB_ID or ''),
            'active': bool(isinstance(active_job, dict) and not bool(active_job.get('done'))),
            'job': benchmark_job,
            'summary': benchmark_summary,
            'report': benchmark_report,
            'history': _slim_benchmark_history(benchmark_history),
            'qa_completed': int(((benchmark_job or {}).get('events') or [{}])[-1].get('qa_completed') or 0) if benchmark_job else 0,
            'qa_total': int(((benchmark_job or {}).get('events') or [{}])[-1].get('qa_total') or 0) if benchmark_job else 0,
        },
    }


@router.post('/locomo/replay')
async def locomo_replay(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    sample_mode = str((body or {}).get('sample_mode') or 'single').strip() or 'single'
    sample_id = (body or {}).get('sample_id')
    replay_mode = str((body or {}).get('replay_mode') or 'transcript_only').strip() or 'transcript_only'
    max_turns_raw = (body or {}).get('max_turns')
    start_session_raw = (body or {}).get('start_session')
    max_sessions_raw = (body or {}).get('max_sessions')
    wait_for_idle = bool((body or {}).get('wait_for_idle', True))
    idle_timeout_ms = int((body or {}).get('idle_timeout_ms') or 120000)
    idle_poll_ms = int((body or {}).get('idle_poll_ms') or 250)
    auto_flush = bool((body or {}).get('auto_flush', True))
    flush_threshold_ratio = float((body or {}).get('flush_threshold_ratio') or 0.80)
    flush_every_turns = int((body or {}).get('flush_every_turns') or 0)
    max_compaction_per_pass = int((body or {}).get('max_compaction_per_pass') or 2)
    max_side_effects_per_pass = int((body or {}).get('max_side_effects_per_pass') or 8)
    reset_session = bool((body or {}).get('reset_session', False))

    max_turns = int(max_turns_raw) if isinstance(max_turns_raw, (int, float)) and int(max_turns_raw) > 0 else None
    start_session = int(start_session_raw) if isinstance(start_session_raw, (int, float)) and int(start_session_raw) > 0 else None
    max_sessions = int(max_sessions_raw) if isinstance(max_sessions_raw, (int, float)) and int(max_sessions_raw) > 0 else None
    try:
        _set_seed_status(active=True, kind='locomo', status='running', message='LoCoMo replay in progress')
        out = await replay_locomo_corpus(
            sample_mode=sample_mode,
            sample_id=str(sample_id).strip() if sample_id is not None else None,
            replay_mode=replay_mode,
            max_turns=max_turns,
            start_session=start_session,
            max_sessions=max_sessions,
            wait_for_idle=wait_for_idle,
            idle_timeout_ms=idle_timeout_ms,
            idle_poll_ms=idle_poll_ms,
            auto_flush=auto_flush,
            flush_threshold_ratio=flush_threshold_ratio,
            flush_every_turns=flush_every_turns,
            max_compaction_per_pass=max_compaction_per_pass,
            max_side_effects_per_pass=max_side_effects_per_pass,
            reset_session=reset_session,
        )
        _set_seed_status(active=False, kind='locomo', status='completed' if bool((out or {}).get('ok')) else 'failed', message=str((out or {}).get('error') or 'LoCoMo replay complete'))
        return out
    except FileNotFoundError as exc:
        _set_seed_status(active=False, kind='locomo', status='failed', message=str(exc))
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=404)
    except ValueError as exc:
        _set_seed_status(active=False, kind='locomo', status='failed', message=str(exc))
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    except Exception as exc:
        _set_seed_status(active=False, kind='locomo', status='failed', message=str(exc))
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
        _set_seed_status(active=True, kind='story_pack', status='running', message='Story-pack replay in progress')
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
        _set_seed_status(active=False, kind='story_pack', status='completed' if bool(out.get('ok')) else 'failed', message=str(out.get('error') or 'Story-pack replay complete'))
        code = 200 if bool(out.get('ok')) else 400
        return JSONResponse(out, status_code=code)
    except HTTPException as exc:
        _set_seed_status(active=False, kind='story_pack', status='failed', message=str(exc.detail))
        return _http_exc_response(exc)
    except Exception as exc:
        _set_seed_status(active=False, kind='story_pack', status='failed', message=str(exc))
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


@router.get('/demo/benchmark/preflight')
def benchmark_preflight(
    suite: str = 'locomo_mini',
    semantic_mode: str = 'required',
    answer_mode: str = 'none',
    generator_model: str = '',
):
    import importlib.util
    import os

    suite_name = str(suite or 'locomo_mini').strip().lower() or 'locomo_mini'
    semantic_mode_name = str(semantic_mode or 'required').strip().lower() or 'required'
    answer_mode_name = str(answer_mode or 'none').strip().lower() or 'none'
    generator_model_name = str(generator_model or '').strip()
    if answer_mode_name == 'llm' and not generator_model_name:
        generator_model_name = detect_model()
    embeddings_provider = str(os.environ.get('CORE_MEMORY_EMBEDDINGS_PROVIDER') or '').strip() or 'hash'
    embeddings_model = str(os.environ.get('CORE_MEMORY_EMBEDDINGS_MODEL') or '').strip()

    dataset_ok = True
    dataset_error: dict[str, Any] | None = None
    try:
        build_locomo_suite_metadata(suite=suite_name, sample_limit=1, qa_limit=1)
    except LocomoLoaderError as exc:
        dataset_ok = False
        dataset_error = {'type': exc.__class__.__name__, 'message': str(exc)}

    provider_dependencies: list[dict[str, Any]] = []
    if embeddings_provider == 'openai':
        provider_dependencies.append({'name': 'openai', 'installed': importlib.util.find_spec('openai') is not None, 'required_for': 'provider_embeddings'})
    if embeddings_provider not in {'hash', ''}:
        provider_dependencies.append({'name': 'numpy', 'installed': importlib.util.find_spec('numpy') is not None, 'required_for': 'semantic_vectors'})
        provider_dependencies.append({'name': 'faiss', 'installed': importlib.util.find_spec('faiss') is not None, 'required_for': 'semantic_index'})

    answer_dependencies: list[dict[str, Any]] = []
    llm_answer_ready = True
    llm_answer_error: str | None = None
    if answer_mode_name == 'llm':
        answer_dependencies.append({'name': 'pydantic_ai', 'installed': importlib.util.find_spec('pydantic_ai') is not None, 'required_for': 'llm_answering'})
        if not generator_model_name:
            llm_answer_ready = False
            llm_answer_error = 'missing_generator_model'
        elif generator_model_name.startswith('openai:') and importlib.util.find_spec('openai') is None:
            llm_answer_ready = False
            llm_answer_error = 'missing_openai_client'

    semantic_required_ready = all(bool(row.get('installed')) for row in provider_dependencies)
    overall_ok = bool(dataset_ok)
    if semantic_mode_name == 'required':
        overall_ok = overall_ok and semantic_required_ready
    if answer_mode_name == 'llm':
        overall_ok = overall_ok and llm_answer_ready and all(bool(row.get('installed')) for row in answer_dependencies)

    return {
        'ok': overall_ok,
        'suite': suite_name,
        'semantic_mode': semantic_mode_name,
        'answer_mode': answer_mode_name,
        'generator_model': generator_model_name,
        'dataset': {
            'ok': dataset_ok,
            'error': dataset_error,
        },
        'semantic': {
            'provider': embeddings_provider,
            'model': embeddings_model,
            'required_ready': semantic_required_ready,
            'dependencies': provider_dependencies,
        },
        'answering': {
            'ready': llm_answer_ready if answer_mode_name == 'llm' else True,
            'error': llm_answer_error,
            'dependencies': answer_dependencies,
        },
    }


@router.post('/benchmark-run')
async def benchmark_run(request: Request):
    body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    suite = str((body or {}).get('suite') or '').strip().lower()
    subset = str((body or {}).get('subset') or 'local').strip().lower() or 'local'
    if subset not in {'local', 'full'}:
        subset = 'local'
    if suite not in {'fixture_smoke', 'locomo_qa', 'locomo_retrieval', 'locomo_mini', 'locomo_native_lifecycle'}:
        suite = 'fixture_smoke'
    legacy_mode = not bool((body or {}).get('suite'))
    if legacy_mode and subset == 'full':
        suite = 'locomo_qa'
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
    sample_limit_raw = (body or {}).get('sample_limit')
    sample_limit = int(sample_limit_raw) if isinstance(sample_limit_raw, int) and sample_limit_raw > 0 else None
    if isinstance(sample_limit, int) and sample_limit > 0:
        sample_limit = min(sample_limit, max(1, int(settings.locomo_max_samples)))
    qa_limit_raw = (body or {}).get('qa_limit')
    qa_limit = int(qa_limit_raw) if isinstance(qa_limit_raw, int) and qa_limit_raw > 0 else None
    if isinstance(qa_limit, int) and qa_limit > 0:
        qa_limit = min(qa_limit, max(1, int(settings.locomo_max_qa_cases)))
    sample_ids = [str(x).strip() for x in ((body or {}).get('sample_ids') or []) if str(x).strip()]
    category_filter = [int(x) for x in ((body or {}).get('category_filter') or []) if str(x).strip()]
    qa_per_category_raw = (body or {}).get('qa_per_category') or {}
    qa_per_category: dict[str, int] = {}
    if isinstance(qa_per_category_raw, dict):
        for key, value in qa_per_category_raw.items():
            try:
                cat = int(key)
                cap = int(value)
            except Exception:
                continue
            if cat > 0 and cap > 0:
                qa_per_category[str(cat)] = min(cap, max(1, int(settings.locomo_max_qa_cases)))
    retrieval_k = int((body or {}).get('retrieval_k') or settings.locomo_default_retrieval_k)
    retrieval_k = max(1, retrieval_k)
    ingestion_mode = str((body or {}).get('ingestion_mode') or settings.locomo_ingest_mode_default).strip() or settings.locomo_ingest_mode_default
    answer_mode = str((body or {}).get('answer_mode') or '').strip() or None
    generator_model = str((body or {}).get('generator_model') or '').strip() or None
    embeddings_provider = str((body or {}).get('embeddings_provider') or '').strip() or None
    evidence_recall_k = [int(x) for x in ((body or {}).get('evidence_recall_k') or [1, 3, 5, 8, 10]) if str(x).strip()]
    persist_case_artifacts = bool((body or {}).get('persist_case_artifacts', True))
    compare_paths = bool((body or {}).get('compare_paths', False))
    compare_retrieval_modes = bool((body or {}).get('compare_retrieval_modes', False))
    retrieval_pipeline = str((body or {}).get('retrieval_pipeline') or 'execute_trace').strip().lower() or 'execute_trace'
    if retrieval_pipeline not in {'execute_trace', 'execute_trace_hydrate', 'forced_three_phase', 'three_phase'}:
        retrieval_pipeline = 'execute_trace'
    qa_session_mode = str((body or {}).get('qa_session_mode') or 'shared').strip().lower() or 'shared'
    if qa_session_mode not in {'shared', 'isolated'}:
        qa_session_mode = 'shared'

    kwargs = dict(
        suite=suite,
        subset=subset,
        semantic_mode_name=semantic_mode,
        root_mode=root_mode,
        preload_from_demo=preload_from_demo,
        preload_turns_max=preload_turns_max,
        limit=limit,
        sample_limit=sample_limit,
        qa_limit=qa_limit,
        sample_ids=sample_ids,
        category_filter=category_filter,
        qa_per_category=qa_per_category,
        retrieval_k=retrieval_k,
        ingestion_mode=ingestion_mode,
        answer_mode=answer_mode,
        generator_model=generator_model,
        evidence_recall_k=evidence_recall_k,
        persist_case_artifacts=persist_case_artifacts,
        legacy_mode=legacy_mode,
        embeddings_provider=embeddings_provider,
        compare_paths=compare_paths,
        compare_retrieval_modes=compare_retrieval_modes,
        retrieval_pipeline=retrieval_pipeline,
        qa_session_mode=qa_session_mode,
    )

    _prune_benchmark_jobs()
    prior_job_id = ACTIVE_BENCHMARK_JOB_ID
    prior_row = BENCHMARK_JOBS.get(prior_job_id or '') if prior_job_id else None
    if isinstance(prior_row, dict) and not bool(prior_row.get('done')):
        prior_row['updated_ms'] = _now_ms()
        _benchmark_event(prior_row, 'running', 'Benchmark request reused active job')
        return {
            'ok': True,
            'job_id': prior_job_id,
            'status': str(prior_row.get('status') or 'running'),
            'active_job_id': prior_job_id,
            'already_running': True,
            'superseded_job_id': None,
        }
    stored_active = benchmark_store.read_active_job()
    if isinstance(stored_active, dict):
        active_job_id = str(stored_active.get('job_id') or '').strip()
        if active_job_id:
            return {
                'ok': True,
                'job_id': active_job_id,
                'status': str(stored_active.get('status') or 'running'),
                'active_job_id': active_job_id,
                'already_running': True,
                'superseded_job_id': None,
            }

    job_id = uuid.uuid4().hex[:12]
    row = {
        'job_id': job_id,
        'kwargs': dict(kwargs),
        'status': 'queued',
        'stage': 'queued',
        'done': False,
        'error': None,
        'result': None,
        'events': [],
        'seq': 0,
        'started_ms': _now_ms(),
        'updated_ms': _now_ms(),
        'abandoned': False,
    }
    BENCHMARK_JOBS[job_id] = row
    if isinstance(prior_row, dict) and not bool(prior_row.get('done')):
        prior_row['superseded_by'] = job_id
    run_mode = str(settings.benchmark_run_mode or 'inline').strip().lower() or 'inline'
    if run_mode in {'queue', 'queued', 'cron'}:
        try:
            queued = benchmark_store.enqueue_job(job_id=job_id, request=dict(body or {}), kwargs=kwargs)
        except Exception as exc:
            queued = False
            row['queue_error_detail'] = str(exc)
        if not queued:
            row['status'] = 'failed'
            row['done'] = True
            row['error'] = 'benchmark_queue_unavailable'
            _benchmark_event(row, 'failed', 'Benchmark queue unavailable', detail=str(row.get('queue_error_detail') or ''))
            return JSONResponse({'ok': False, 'job_id': job_id, 'status': 'failed', 'error': row['error'], 'detail': str(row.get('queue_error_detail') or '')}, status_code=503)
        row['status'] = 'queued_external'
        row['done'] = True
        row['result'] = {'queued': True}
        _benchmark_event(row, 'queued_external', 'Benchmark queued for external worker', supersedes=prior_job_id or '')
        return {'ok': True, 'job_id': job_id, 'status': 'queued_external', 'superseded_job_id': prior_job_id}
    if run_mode in {'external', 'dispatch'}:
        _benchmark_event(row, 'queued', 'Benchmark dispatch queued', supersedes=prior_job_id or '')
        dispatched = _dispatch_benchmark_job(job_id, dict(body or {}), kwargs)
        if not bool(dispatched.get('ok')):
            row['status'] = 'failed'
            row['done'] = True
            row['error'] = str(dispatched.get('error') or 'benchmark_dispatch_failed')
            _benchmark_event(row, 'failed', 'Benchmark dispatch failed', error=row['error'])
            return JSONResponse({'ok': False, 'job_id': job_id, 'status': 'failed', 'error': row['error'], 'dispatch': dispatched}, status_code=503)
        row['status'] = 'external_dispatched'
        row['done'] = True
        row['external_job_id'] = str(dispatched.get('job_id') or dispatched.get('id') or '')
        row['result'] = {'external': True, 'dispatch': dispatched}
        _benchmark_event(row, 'external_dispatched', 'Benchmark dispatched to external runner', external_job_id=row['external_job_id'])
        return {
            'ok': True,
            'job_id': job_id,
            'status': 'external_dispatched',
            'external_job_id': row['external_job_id'],
            'superseded_job_id': prior_job_id,
        }
    if run_mode in {'disabled', 'off'}:
        row['status'] = 'failed'
        row['done'] = True
        row['error'] = 'benchmark_run_disabled'
        _benchmark_event(row, 'failed', 'Benchmark run disabled')
        return JSONResponse({'ok': False, 'job_id': job_id, 'status': 'failed', 'error': row['error']}, status_code=503)
    if run_mode in {'inline', 'sync', 'synchronous'}:
        _benchmark_event(row, 'queued', 'Benchmark queued', supersedes=prior_job_id or '')
        await _run_benchmark_job(job_id, kwargs)
        if isinstance(row.get('result'), dict):
            return dict(row.get('result') or {})
        return _benchmark_job_payload(row)
    task = asyncio.create_task(_run_benchmark_job(job_id, kwargs))
    row['task'] = task
    _benchmark_event(row, 'queued', 'Benchmark queued', supersedes=prior_job_id or '')
    return {'ok': True, 'job_id': job_id, 'status': 'queued', 'superseded_job_id': prior_job_id}


@router.get('/demo/benchmark/job/{job_id}')
def benchmark_job_status(job_id: str, cursor: int = 0):
    _prune_benchmark_jobs()
    job_id_s = str(job_id or '').strip()
    stored = benchmark_store.read_job(job_id_s)
    row = BENCHMARK_JOBS.get(job_id_s)
    if isinstance(stored, dict):
        stored_status = str(stored.get('status') or '')
        stored_done = stored_status in {'completed', 'failed'}
        # Queue/cron mode leaves a short-lived in-memory row in the web
        # process. The cron worker owns the durable job status in Postgres, so
        # prefer it whenever it has advanced beyond the initial web-only
        # placeholder. Otherwise /job/{id} can keep reporting queued_external
        # forever even after the worker completed.
        if stored_done or stored_status in {'queued', 'running'} or not isinstance(row, dict):
            if isinstance(row, dict) and stored_done:
                row['status'] = stored_status
                row['stage'] = stored_status
                row['done'] = True
                row['error'] = stored.get('error')
                if isinstance(stored.get('result'), dict):
                    row['result'] = dict(stored.get('result') or {})
                row['updated_ms'] = _now_ms()
            return _stored_benchmark_job_payload(stored, cursor=max(0, int(cursor)))
    if not isinstance(row, dict):
        return JSONResponse({'ok': False, 'error': 'benchmark_job_not_found'}, status_code=404)
    return _benchmark_job_payload(row, cursor=max(0, int(cursor)))


@router.get('/demo/benchmark/last')
def benchmark_last():
    _prune_benchmark_jobs()
    snapshot = get_last_benchmark_snapshot(history_limit=3)
    history = list(snapshot.get('history') or [])
    latest_compare = None
    active_job = next((row for row in BENCHMARK_JOBS.values() if isinstance(row, dict) and not bool(row.get('done'))), None)

    summary = dict(snapshot.get('summary') or {})
    report = dict(snapshot.get('report') or {})
    ok = bool(snapshot.get('ok'))

    if isinstance(active_job, dict):
        summary, report = _active_benchmark_state(active_job, snapshot)
        ok = True

    if len(history) >= 2:
        left = str((history[1].get('summary') or {}).get('run_id') or history[1].get('run_id') or '')
        right = str((history[0].get('summary') or {}).get('run_id') or history[0].get('run_id') or '')
        if left and right:
            try:
                cmp = compare_benchmark_runs(left, right)
                latest_compare = cmp.get('compare') if cmp.get('ok') else None
            except Exception:
                latest_compare = None
    if isinstance(active_job, dict):
        history = history[:2]
    history = _slim_benchmark_history(history)
    report = _strip_benchmark_case_payloads(report) if isinstance(report, dict) else report
    return {
        'ok': ok,
        'summary': summary,
        'report': report,
        'history': history,
        'latest_compare': latest_compare,
    }


@router.get('/demo/benchmark/artifact/{run_id}/{filename}')
def benchmark_artifact_download(run_id: str, filename: str):
    allowed = {'report.json', 'summary.json', 'config.json', 'dataset_meta.json', 'ingestion_meta.json', 'comparison.json', 'comparison_error.json', 'cases.jsonl', 'failures.jsonl'}
    name = str(filename or '').strip()
    if name not in allowed:
        raise HTTPException(status_code=404, detail='artifact_not_found')
    safe_run_id = ''.join(ch for ch in str(run_id or '') if ch.isalnum() or ch in {'-', '_'})
    if not safe_run_id:
        raise HTTPException(status_code=404, detail='artifact_not_found')
    root = Path(settings.core_memory_demo_artifacts_root) / 'locomo-runs' / safe_run_id
    path = root / name
    if not path.exists() or not path.is_file():
        try:
            db_artifact = benchmark_store.read_artifact(safe_run_id, name)
        except Exception:
            db_artifact = None
        if not db_artifact:
            raise HTTPException(status_code=404, detail='artifact_not_found')
        media_type = str(db_artifact.get('content_type') or ('application/json' if name.endswith('.json') else 'application/x-ndjson'))
        return StreamingResponse(
            BytesIO(bytes(db_artifact.get('body') or b'')),
            media_type=media_type,
            headers={'Content-Disposition': f'attachment; filename="{safe_run_id}-{name}"'},
        )
    media_type = 'application/json' if name.endswith('.json') else 'application/x-ndjson'
    return FileResponse(path=str(path), filename=f'{safe_run_id}-{name}', media_type=media_type)


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
