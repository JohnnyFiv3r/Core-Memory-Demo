from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from app.core.semantic_env import configure_shared_semantic_backend_env

configure_shared_semantic_backend_env()

from app.benchmarks import benchmark_store
from app.core.config import settings
from app.core.embedding_preflight import (
    format_preflight_failure,
    format_preflight_report,
    preflight_embedding_backend,
)
from app.core.runtime import replay_locomo_corpus, run_benchmark
from app.ingest.transcript import run_transcript_ingest_job

# Job kinds that re-embed a corpus in-process and therefore need a working
# external embeddings backend before they spend ~90s seeding.
_SEMANTIC_BUILD_KINDS = {'locomo_seed', 'locomo_full', 'benchmark'}


def _make_progress_callbacks(job_id: str) -> dict[str, Any]:
    """Build the streaming callbacks that write live progress to benchmark_store.

    The app polls /demo/benchmark/run-state and renders from this persisted
    progress, so every phase (seed + QA) must keep calling these to stay visible
    in the UI. Defined once so the combined 'locomo_full' job streams both phases
    through the same channel the split jobs use.
    """
    throttle = {'seed': 0.0, 'heartbeat': 0.0, 'ingest': 0.0, 'replay': 0.0}

    def seed_progress(seeded: int, total: int) -> None:
        now = time.monotonic()
        if now - throttle['seed'] < 1.5 and int(seeded) < int(total):
            return
        throttle['seed'] = now
        benchmark_store.update_job_progress(
            job_id,
            status='running',
            stage='seeding',
            message=f'Seeded {int(seeded)}/{int(total)} turns',
            ingest_n=int(seeded),
            ingest_total=int(total),
            event={'stage': 'seeding', 'message': f'Seeded {int(seeded)}/{int(total)} turns', 'seeded': int(seeded), 'total': int(total)},
        )

    def seed_heartbeat(stage: str, message: str) -> None:
        benchmark_store.update_job_progress(
            job_id,
            status='running',
            stage=str(stage or 'seeding'),
            message=str(message or ''),
        )

    def heartbeat(stage: str, message: str) -> None:
        now = time.monotonic()
        stage_s = str(stage or '')
        message_s = str(message or '')
        if now - throttle['heartbeat'] < 1.5:
            return
        throttle['heartbeat'] = now
        benchmark_store.update_job_progress(
            job_id,
            status='running',
            stage=stage_s,
            message=message_s,
            event={'stage': stage_s, 'message': message_s},
        )

    def ingest_progress(n: int, total: int) -> None:
        now = time.monotonic()
        if now - throttle['ingest'] < 1.5 and int(n) < int(total):
            return
        throttle['ingest'] = now
        benchmark_store.update_job_progress(
            job_id,
            status='running',
            stage='ingesting',
            message=f'Ingested {int(n)}/{int(total)} turns',
            ingest_n=int(n),
            ingest_total=int(total),
        )

    def progress(completed: int, total: int, case: dict[str, Any], result: dict[str, Any]) -> None:
        result_d = dict(result or {})
        stage = str(result_d.get('phase') or 'retrieving').strip().lower() or 'retrieving'
        replay_done = int(result_d.get('replay_turn_completed') or 0)
        replay_total = int(result_d.get('replay_turn_total') or 0)
        if stage == 'locomo_lifecycle' and replay_total > 0:
            now = time.monotonic()
            if now - throttle['replay'] < 2.0 and replay_done < replay_total:
                return
            throttle['replay'] = now
            message = f'Replayed {replay_done}/{replay_total} turns'
        else:
            message = f'QA {int(completed)}/{int(total)}'
        event = {
            'stage': stage,
            'message': message,
            'qa_completed': int(completed),
            'qa_total': int(total),
            'sample_id': str((case or {}).get('sample_id') or ''),
            'qa_id': str((case or {}).get('qa_id') or ''),
            'case_status': str(result_d.get('status') or ''),
            'conversation_id': str(result_d.get('conversation_id') or ''),
            'conversation_index': int(result_d.get('conversation_index') or 0),
            'conversations': int(result_d.get('conversations') or 0),
            'replay_turn_completed': replay_done,
            'replay_turn_total': replay_total,
            'turn_id': str(result_d.get('turn_id') or ''),
        }
        # Mirror the per-QA live payload onto the persisted event so the
        # hosted (queued-worker) LoCoMo path streams the same question +
        # generated answer into the chat as the in-process path does.
        question = str((case or {}).get('question') or result_d.get('question') or '')
        answer = str(result_d.get('answer') or '')
        evidence_bead_ids = [str(b) for b in (result_d.get('evidence_bead_ids') or []) if str(b)]
        evidence = [r for r in (result_d.get('evidence') or []) if isinstance(r, dict)]
        if question:
            event['question'] = question
        if answer:
            event['answer'] = answer
        if str(result_d.get('status') or '') == 'ok':
            event['answer_f1'] = float(result_d.get('answer_f1') or 0.0)
        if evidence_bead_ids:
            event['evidence_bead_ids'] = evidence_bead_ids
        if evidence:
            event['evidence'] = evidence
        # Causal graph snapshot (beads + associations) for the live graph.
        graph_beads = [b for b in (result_d.get('graph_beads') or []) if isinstance(b, dict)]
        graph_associations = [a for a in (result_d.get('graph_associations') or []) if isinstance(a, dict)]
        if graph_beads:
            event['graph_beads'] = graph_beads
        if graph_associations:
            event['graph_associations'] = graph_associations
        if result_d.get('graph_stats'):
            event['graph_stats'] = dict(result_d.get('graph_stats') or {})
        benchmark_store.update_job_progress(
            job_id,
            status='running',
            stage=stage,
            message=message,
            event=event,
        )

    return {
        'seed_progress': seed_progress,
        'seed_heartbeat': seed_heartbeat,
        'heartbeat': heartbeat,
        'ingest_progress': ingest_progress,
        'progress': progress,
    }


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

    # Fail fast on a broken embeddings backend instead of seeding the whole
    # corpus first and dying at the required-semantic gate. Only deterministic
    # credential/endpoint failures (missing key, 401/403/404) abort here; a
    # transient probe failure is logged and the run proceeds.
    if kind in _SEMANTIC_BUILD_KINDS:
        preflight = preflight_embedding_backend()
        if not bool(preflight.get('ok')):
            detail = format_preflight_failure(preflight)
            # Full audit table (which key var actually wins) goes to the cron log
            # so a stale CORE_MEMORY_EMBEDDINGS_API_KEY shadowing a fresh
            # OPENAI_API_KEY is visible at a glance, not buried.
            print(format_preflight_report(preflight), file=sys.stderr)
            if bool(preflight.get('fatal')):
                benchmark_store.update_job_progress(job_id, status='running', stage='preflight', message=detail)
                benchmark_store.finish_job(job_id, error=detail)
                print(f'benchmark_worker: {detail}', file=sys.stderr)
                return 1
            print(f'benchmark_worker: embedding preflight warning (continuing): {detail}', file=sys.stderr)

    cb = _make_progress_callbacks(job_id)
    try:
        if kind == 'transcript_ingest':
            out = run_transcript_ingest_job(**kwargs)
        elif kind == 'locomo_seed':
            benchmark_store.update_job_progress(job_id, status='running', stage='starting', message='LoCoMo seed worker started')
            out = replay_locomo_corpus(progress=cb['seed_progress'], heartbeat=cb['seed_heartbeat'], **kwargs)
        elif kind == 'locomo_full':
            # Product LoCoMo benchmark: replay/seed + QA + report in one worker.
            # When benchmark kwargs request qa_only_seeded=False, run the official
            # lifecycle inside the benchmark-owned clean root instead of touching
            # the live app Qdrant path, which is not multi-worker safe on hosted.
            seed_kwargs = dict(kwargs.get('seed') or {})
            benchmark_kwargs = dict(kwargs.get('benchmark') or {})
            # Back-compat: pre-existing/external locomo_full rows may omit
            # qa_only_seeded. Only an explicit False selects the new product
            # clean-root lifecycle; missing/True preserves legacy seed-then-QA.
            if benchmark_kwargs.get('qa_only_seeded') is not False:
                benchmark_store.update_job_progress(job_id, status='running', stage='starting', message='LoCoMo full run: seeding corpus')
                seed_out = replay_locomo_corpus(progress=cb['seed_progress'], heartbeat=cb['seed_heartbeat'], **seed_kwargs)
                if not bool((seed_out or {}).get('ok', True)) or bool((seed_out or {}).get('cancelled')):
                    detail = str((seed_out or {}).get('error') or ('cancelled' if (seed_out or {}).get('cancelled') else 'unknown'))
                    benchmark_store.finish_job(job_id, error=f'locomo_seed_failed:{detail}')
                    print(f'benchmark_worker: seed phase failed {job_id}: {detail}', file=sys.stderr)
                    return 1
                benchmark_store.update_job_progress(
                    job_id,
                    status='running',
                    stage='seeded',
                    message=f"Seed complete ({int((seed_out or {}).get('seeded') or 0)} turns); starting QA",
                    event={'stage': 'seeded', 'message': 'Seed complete; starting QA', 'seeded': int((seed_out or {}).get('seeded') or 0)},
                )
                benchmark_kwargs.setdefault('seed_record', dict(seed_out or {}))
                out = run_benchmark(**benchmark_kwargs, progress=cb['progress'], ingest_progress=cb['ingest_progress'], heartbeat=cb['heartbeat'])
                out = {**dict(out or {}), 'seed': dict(seed_out or {})}
            else:
                benchmark_store.update_job_progress(job_id, status='running', stage='starting', message='LoCoMo full run: replaying corpus and building report')
                out = run_benchmark(**benchmark_kwargs, progress=cb['progress'], ingest_progress=cb['ingest_progress'], heartbeat=cb['heartbeat'])
        else:
            benchmark_store.update_job_progress(job_id, status='running', stage='starting', message='Benchmark started')
            out = run_benchmark(**kwargs, progress=cb['progress'], ingest_progress=cb['ingest_progress'], heartbeat=cb['heartbeat'])
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
