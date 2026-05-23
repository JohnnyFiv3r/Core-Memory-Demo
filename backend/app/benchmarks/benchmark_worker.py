from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from app.core.semantic_env import configure_shared_semantic_backend_env

configure_shared_semantic_backend_env()

from app.benchmarks import benchmark_store
from app.core.config import settings
from app.core.runtime import run_benchmark
from app.ingest.transcript import run_transcript_ingest_job


def run_once() -> int:
    job = benchmark_store.claim_next_job()
    if not job:
        print('benchmark_worker: no queued job')
        return 0
    job_id = str(job.get('job_id') or '')
    request = dict(job.get('request') or {})
    kwargs = dict(job.get('kwargs') or {})
    kind = str(request.get('kind') or 'benchmark').strip() or 'benchmark'
    print(f'benchmark_worker: running {job_id} kind={kind}')
    try:
        if kind == 'transcript_ingest':
            out = run_transcript_ingest_job(**kwargs)
        else:
            last_heartbeat_write = 0.0
            last_ingest_write = 0.0
            last_replay_write = 0.0

            def heartbeat(stage: str, message: str) -> None:
                nonlocal last_heartbeat_write
                now = time.monotonic()
                stage_s = str(stage or '')
                message_s = str(message or '')
                if now - last_heartbeat_write < 1.5:
                    return
                last_heartbeat_write = now
                benchmark_store.update_job_progress(
                    job_id,
                    status='running',
                    stage=stage_s,
                    message=message_s,
                    event={'stage': stage_s, 'message': message_s},
                )

            def ingest_progress(n: int, total: int) -> None:
                nonlocal last_ingest_write
                now = time.monotonic()
                if now - last_ingest_write < 1.5 and int(n) < int(total):
                    return
                last_ingest_write = now
                benchmark_store.update_job_progress(
                    job_id,
                    status='running',
                    stage='ingesting',
                    message=f'Ingested {int(n)}/{int(total)} turns',
                    ingest_n=int(n),
                    ingest_total=int(total),
                )

            def progress(completed: int, total: int, case: dict[str, Any], result: dict[str, Any]) -> None:
                nonlocal last_replay_write
                phase = str((result or {}).get('phase') or '').strip().lower()
                stage = phase or 'retrieving'
                # Replay-turn callbacks fire once per turn (potentially 100+ times).
                # Rate-limit those writes; QA-phase events always go through.
                is_replay = stage == 'locomo_lifecycle'
                now = time.monotonic()
                if is_replay and now - last_replay_write < 2.0:
                    return
                if is_replay:
                    last_replay_write = now
                replay_done = int((result or {}).get('replay_turn_completed') or 0)
                replay_total = int((result or {}).get('replay_turn_total') or 0)
                if is_replay and replay_total > 0:
                    message = f'Replaying turns {replay_done}/{replay_total} · QA {int(completed)}/{int(total)}'
                else:
                    message = f'QA {int(completed)}/{int(total)}'
                benchmark_store.update_job_progress(
                    job_id,
                    status='running',
                    stage=stage,
                    message=message,
                    event={
                        'stage': stage,
                        'message': message,
                        'qa_completed': int(completed),
                        'qa_total': int(total),
                        'sample_id': str((case or {}).get('sample_id') or ''),
                        'qa_id': str((case or {}).get('qa_id') or ''),
                        'case_status': str((result or {}).get('status') or ''),
                        'conversation_id': str((result or {}).get('conversation_id') or ''),
                        'conversation_index': int((result or {}).get('conversation_index') or 0),
                        'conversations': int((result or {}).get('conversations') or 0),
                        'replay_turn_completed': replay_done,
                        'replay_turn_total': replay_total,
                        'turn_id': str((result or {}).get('turn_id') or ''),
                    },
                )

            benchmark_store.update_job_progress(job_id, status='running', stage='starting', message='Benchmark started')
            out = run_benchmark(**kwargs, progress=progress, ingest_progress=ingest_progress, heartbeat=heartbeat)
    except Exception as exc:
        benchmark_store.finish_job(job_id, error=str(exc))
        print(f'benchmark_worker: failed {job_id}: {exc}', file=sys.stderr)
        return 1
    benchmark_store.finish_job(job_id, result=dict(out or {}))
    status = 'ok' if bool((out or {}).get('ok')) else 'failed'
    print(f'benchmark_worker: completed {job_id} status={status}')
    return 0 if bool((out or {}).get('ok')) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run queued Core Memory demo benchmark jobs.')
    parser.add_argument('--once', action='store_true', help='Claim and run at most one queued benchmark job.')
    args = parser.parse_args(argv)
    return run_once()


if __name__ == '__main__':
    raise SystemExit(main())
