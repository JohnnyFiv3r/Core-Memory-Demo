from __future__ import annotations

import argparse
import sys
from typing import Any

from app.benchmarks import benchmark_store
from app.core.runtime import run_benchmark


def run_once() -> int:
    job = benchmark_store.claim_next_job()
    if not job:
        print('benchmark_worker: no queued job')
        return 0
    job_id = str(job.get('job_id') or '')
    kwargs = dict(job.get('kwargs') or {})
    print(f'benchmark_worker: running {job_id}')
    try:
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
