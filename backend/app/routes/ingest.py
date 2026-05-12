from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.benchmarks import benchmark_store
from app.core.abuse import rate_limit_general
from app.core.auth import require_admin
from app.core.config import settings
from app.ingest.transcript import normalize_transcript_payload, run_transcript_ingest_job

router = APIRouter(prefix='/api', tags=['ingest'], dependencies=[Depends(require_admin), Depends(rate_limit_general)])

INGEST_JOB_TTL_SECONDS = 30 * 60
INGEST_JOBS: dict[str, dict[str, Any]] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _prune_ingest_jobs() -> None:
    now = _now_ms()
    ttl_ms = int(INGEST_JOB_TTL_SECONDS * 1000)
    for job_id, row in list(INGEST_JOBS.items()):
        updated = int((row or {}).get('updated_ms') or 0)
        if now - updated > ttl_ms:
            INGEST_JOBS.pop(job_id, None)


def _safe_job_payload(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        'ok': True,
        'job_id': str(row.get('job_id') or ''),
        'kind': 'transcript_ingest',
        'status': str(row.get('status') or 'queued'),
        'done': bool(row.get('done')),
        'created_ms': int(row.get('created_ms') or 0),
        'updated_ms': int(row.get('updated_ms') or 0),
    }
    if row.get('error'):
        out['error'] = str(row.get('error') or '')
    if isinstance(row.get('result'), dict):
        out['result'] = dict(row.get('result') or {})
    return out


def _stored_job_payload(stored: dict[str, Any]) -> dict[str, Any]:
    status = str((stored or {}).get('status') or '')
    result = stored.get('result') if isinstance(stored.get('result'), dict) else None
    out: dict[str, Any] = {
        'ok': True,
        'job_id': str((stored or {}).get('job_id') or ''),
        'kind': 'transcript_ingest',
        'status': status,
        'done': status in {'completed', 'failed'},
        'error': (stored or {}).get('error'),
        'result': result,
    }
    for key in ('created_at', 'updated_at', 'started_at', 'finished_at'):
        value = (stored or {}).get(key)
        if value:
            out[key] = value
    return out


def _run_ingest_job(job_id: str, kwargs: dict[str, Any]) -> None:
    row = INGEST_JOBS.get(job_id)
    if not isinstance(row, dict):
        return
    row['status'] = 'running'
    row['updated_ms'] = _now_ms()
    try:
        out = run_transcript_ingest_job(
            root=settings.core_memory_root,
            max_turns=int(settings.replay_max_turns),
            **kwargs,
        )
        row['status'] = 'completed' if bool((out or {}).get('ok')) else 'failed'
        row['done'] = True
        row['result'] = dict(out or {})
        if not bool((out or {}).get('ok')):
            row['error'] = 'transcript_ingest_failed'
    except Exception as exc:
        row['status'] = 'failed'
        row['done'] = True
        row['error'] = str(exc or 'transcript_ingest_failed')
    finally:
        row['updated_ms'] = _now_ms()


@router.post('/ingest/transcript', status_code=202)
async def ingest_transcript(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='invalid_json')
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail='payload_must_be_object')

    try:
        normalized = normalize_transcript_payload(body, max_turns=int(settings.replay_max_turns))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    job_id = f"ingest-{uuid.uuid4().hex[:12]}"
    kwargs = {
        'transcript_id': str(normalized.get('transcript_id') or ''),
        'session_id': str(normalized.get('session_id') or ''),
        'turns': list(body.get('turns') or []),
        'flush_policy': str(normalized.get('flush_policy') or 'end_only'),
        'metadata': dict(body.get('metadata') or {}) if isinstance(body.get('metadata'), dict) else {},
    }
    request_payload = {
        'kind': 'transcript_ingest',
        'transcript_id': kwargs['transcript_id'],
        'session_id': kwargs['session_id'],
        'turns_received': int(normalized.get('turns_received') or 0),
        'turns_paired': int(normalized.get('turns_paired') or 0),
    }

    _prune_ingest_jobs()
    run_mode = str(settings.transcript_ingest_run_mode or 'inline').strip().lower() or 'inline'
    if run_mode in {'queue', 'queued', 'cron'}:
        try:
            queued = benchmark_store.enqueue_job(job_id=job_id, request=request_payload, kwargs=kwargs)
        except Exception as exc:
            queued = False
            queue_error = str(exc)
        else:
            queue_error = ''
        if not queued:
            return JSONResponse({'ok': False, 'job_id': job_id, 'status': 'failed', 'error': 'ingest_queue_unavailable', 'detail': queue_error}, status_code=503)
        return {
            'ok': True,
            'job_id': job_id,
            'kind': 'transcript_ingest',
            'status': 'queued_external',
            'turns_received': int(normalized.get('turns_received') or 0),
            'turns_paired': int(normalized.get('turns_paired') or 0),
        }
    if run_mode in {'disabled', 'off'}:
        return JSONResponse({'ok': False, 'job_id': job_id, 'status': 'failed', 'error': 'ingest_run_disabled'}, status_code=503)

    row = {
        'job_id': job_id,
        'status': 'queued',
        'done': False,
        'error': None,
        'result': None,
        'created_ms': _now_ms(),
        'updated_ms': _now_ms(),
    }
    INGEST_JOBS[job_id] = row
    t = threading.Thread(target=_run_ingest_job, args=(job_id, kwargs), name=f'transcript-ingest-{job_id}', daemon=True)
    row['task'] = t
    t.start()
    return {
        'ok': True,
        'job_id': job_id,
        'kind': 'transcript_ingest',
        'status': 'queued',
        'turns_received': int(normalized.get('turns_received') or 0),
        'turns_paired': int(normalized.get('turns_paired') or 0),
    }


@router.get('/ingest/jobs/{job_id}')
def ingest_job_status(job_id: str):
    _prune_ingest_jobs()
    job_id_s = str(job_id or '').strip()
    stored = benchmark_store.read_job(job_id_s)
    if isinstance(stored, dict):
        request = dict(stored.get('request') or {})
        if str(request.get('kind') or '') == 'transcript_ingest':
            return _stored_job_payload(stored)
    row = INGEST_JOBS.get(job_id_s)
    if not isinstance(row, dict):
        return JSONResponse({'ok': False, 'error': 'ingest_job_not_found'}, status_code=404)
    return _safe_job_payload(row)
