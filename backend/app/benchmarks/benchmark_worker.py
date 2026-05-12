from __future__ import annotations

import argparse
import sys
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
    kind = str(request.get('kind') or kwargs.get('kind') or 'benchmark').strip() or 'benchmark'
    print(f'benchmark_worker: running {job_id} kind={kind}')
    try:
        if kind == 'transcript_ingest':
            out = run_transcript_ingest_job(root=settings.core_memory_root, max_turns=int(settings.replay_max_turns), **kwargs)
        else:
            out = run_benchmark(**kwargs)
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
