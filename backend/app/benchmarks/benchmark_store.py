from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


_ALLOWED_ARTIFACTS = {
    'report.json': 'application/json',
    'summary.json': 'application/json',
    'config.json': 'application/json',
    'dataset_meta.json': 'application/json',
    'ingestion_meta.json': 'application/json',
    'comparison.json': 'application/json',
    'comparison_error.json': 'application/json',
    'cases.jsonl': 'application/x-ndjson',
    'failures.jsonl': 'application/x-ndjson',
}


def _database_url() -> str:
    return str(os.getenv('BENCHMARK_DATABASE_URL') or os.getenv('DATABASE_URL') or '').strip()


def enabled() -> bool:
    return bool(_database_url())


def _migration_path() -> Path:
    return Path(__file__).resolve().parents[2] / 'migrations' / '0001_benchmarks_schema.sql'


@lru_cache(maxsize=1)
def ensure_schema() -> bool:
    url = _database_url()
    if not url:
        return False
    sql = _migration_path().read_text(encoding='utf-8')
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)
    return True


def _json_or_none(raw: bytes | str) -> Any | None:
    try:
        return json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
    except Exception:
        return None


def _artifact_payload(path: Path, content_type: str) -> tuple[Any | None, bytes | None, int]:
    data = path.read_bytes()
    if content_type == 'application/json':
        parsed = _json_or_none(data)
        return parsed, None, len(data)
    return None, data, len(data)


def save_run(*, history_row: dict[str, Any], artifacts: dict[str, str] | None = None) -> bool:
    """Persist a completed benchmark run and artifacts into benchmarks.* tables.

    This is best-effort: callers should keep the existing filesystem history path
    as a fallback if Postgres is unavailable.
    """

    if not enabled():
        return False
    ensure_schema()

    summary = dict((history_row or {}).get('summary') or {})
    report = dict((history_row or {}).get('report') or {})
    run_id = str(summary.get('run_id') or (history_row or {}).get('run_id') or '').strip()
    if not run_id:
        return False
    config = dict(report.get('config') or {})
    scores = dict(report.get('scores') or {})
    suite = str(summary.get('suite') or config.get('suite') or 'unknown')
    status = str(summary.get('status') or 'completed')
    started_at = str(summary.get('started_at') or '').strip() or None
    finished_at = str(summary.get('finished_at') or (history_row or {}).get('created_at') or '').strip() or None
    error = str(summary.get('error') or report.get('error') or '').strip() or None

    with psycopg.connect(_database_url(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO benchmarks.runs
                (run_id, suite, status, started_at, finished_at, config, summary, scores, report, error, updated_at)
            VALUES
                (%s, %s, %s, COALESCE(%s::timestamptz, now()), %s::timestamptz, %s, %s, %s, %s, %s, now())
            ON CONFLICT (run_id) DO UPDATE SET
                suite = EXCLUDED.suite,
                status = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                finished_at = EXCLUDED.finished_at,
                config = EXCLUDED.config,
                summary = EXCLUDED.summary,
                scores = EXCLUDED.scores,
                report = EXCLUDED.report,
                error = EXCLUDED.error,
                updated_at = now()
            """,
            (run_id, suite, status, started_at, finished_at, Jsonb(config), Jsonb(summary), Jsonb(scores), Jsonb(report), error),
        )

        for filename, content_type in _ALLOWED_ARTIFACTS.items():
            raw_path = str((artifacts or {}).get(filename.split('.', 1)[0]) or '')
            if not raw_path:
                # write_locomo_run_artifacts uses keys like dataset_meta and comparison_error.
                key = filename.rsplit('.', 1)[0]
                raw_path = str((artifacts or {}).get(key) or '')
            if not raw_path:
                continue
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                continue
            content, content_bytes, size = _artifact_payload(path, content_type)
            conn.execute(
                """
                INSERT INTO benchmarks.artifacts
                    (run_id, filename, content_type, content, content_bytes, size_bytes, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (run_id, filename) DO UPDATE SET
                    content_type = EXCLUDED.content_type,
                    content = EXCLUDED.content,
                    content_bytes = EXCLUDED.content_bytes,
                    size_bytes = EXCLUDED.size_bytes,
                    updated_at = now()
                """,
                (run_id, filename, content_type, Jsonb(content) if content is not None else None, content_bytes, int(size)),
            )

        cases = list((history_row or {}).get('cases') or report.get('cases') or [])
        for case in cases:
            if not isinstance(case, dict):
                continue
            qa_id = str(case.get('qa_id') or '').strip()
            if not qa_id:
                continue
            evidence = dict(case.get('evidence_recall') or {})
            retrieved = list(case.get('retrieved') or [])
            conn.execute(
                """
                INSERT INTO benchmarks.cases
                    (run_id, qa_id, sample_id, category, status, answer_f1, evidence_recall, retrieved, error, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, qa_id) DO UPDATE SET
                    sample_id = EXCLUDED.sample_id,
                    category = EXCLUDED.category,
                    status = EXCLUDED.status,
                    answer_f1 = EXCLUDED.answer_f1,
                    evidence_recall = EXCLUDED.evidence_recall,
                    retrieved = EXCLUDED.retrieved,
                    error = EXCLUDED.error,
                    payload = EXCLUDED.payload
                """,
                (
                    run_id,
                    qa_id,
                    str(case.get('sample_id') or ''),
                    int(case.get('category') or 0),
                    str(case.get('status') or ''),
                    float(case.get('answer_f1')) if case.get('answer_f1') is not None else None,
                    Jsonb(evidence),
                    Jsonb(retrieved),
                    str(case.get('error') or '').strip() or None,
                    Jsonb(case),
                ),
            )
    return True


def read_history(limit: int = 20, *, include_report: bool = True) -> list[dict[str, Any]]:
    if not enabled():
        return []
    ensure_schema()
    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
        if include_report:
            rows = conn.execute(
                """
                SELECT run_id, finished_at, created_at, summary, report
                FROM benchmarks.runs
                ORDER BY COALESCE(finished_at, created_at) DESC
                LIMIT %s
                """,
                (max(1, int(limit)),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT run_id, finished_at, created_at, summary
                FROM benchmarks.runs
                ORDER BY COALESCE(finished_at, created_at) DESC
                LIMIT %s
                """,
                (max(1, int(limit)),),
            ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({
            'run_id': row.get('run_id'),
            'created_at': (row.get('finished_at') or row.get('created_at')).isoformat() if row.get('finished_at') or row.get('created_at') else '',
            'summary': dict(row.get('summary') or {}),
            'report': dict(row.get('report') or {}) if include_report else {},
        })
    return out


def enqueue_job(*, job_id: str, request: dict[str, Any], kwargs: dict[str, Any]) -> bool:
    if not enabled():
        return False
    ensure_schema()
    with psycopg.connect(_database_url(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO benchmarks.jobs (job_id, status, request, kwargs, updated_at)
            VALUES (%s, 'queued', %s, %s, now())
            ON CONFLICT (job_id) DO UPDATE SET
                request = EXCLUDED.request,
                kwargs = EXCLUDED.kwargs,
                status = 'queued',
                error = NULL,
                result = NULL,
                updated_at = now()
            """,
            (str(job_id), Jsonb(dict(request or {})), Jsonb(dict(kwargs or {}))),
        )
    return True


def read_job(job_id: str) -> dict[str, Any] | None:
    if not enabled():
        return None
    ensure_schema()
    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT job_id, status, request, kwargs, result, error, attempts, created_at, updated_at, started_at, finished_at
            FROM benchmarks.jobs
            WHERE job_id = %s
            """,
            (str(job_id),),
        ).fetchone()
    if not row:
        return None
    out = dict(row)
    for key in ('created_at', 'updated_at', 'started_at', 'finished_at'):
        if out.get(key) is not None:
            out[key] = out[key].isoformat()
    return out


def claim_next_job() -> dict[str, Any] | None:
    if not enabled():
        return None
    ensure_schema()
    with psycopg.connect(_database_url(), autocommit=True, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            WITH picked AS (
                SELECT job_id
                FROM benchmarks.jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE benchmarks.jobs j
            SET status = 'running', attempts = attempts + 1, claimed_at = now(), started_at = COALESCE(started_at, now()), updated_at = now()
            FROM picked
            WHERE j.job_id = picked.job_id
            RETURNING j.job_id, j.request, j.kwargs, j.attempts
            """
        ).fetchone()
    return dict(row) if row else None


def finish_job(job_id: str, *, result: dict[str, Any] | None = None, error: str | None = None) -> bool:
    if not enabled():
        return False
    ensure_schema()
    status = 'failed' if error else 'completed'
    with psycopg.connect(_database_url(), autocommit=True) as conn:
        conn.execute(
            """
            UPDATE benchmarks.jobs
            SET status = %s, result = %s, error = %s, finished_at = now(), updated_at = now()
            WHERE job_id = %s
            """,
            (status, Jsonb(dict(result or {})) if result is not None else None, error, str(job_id)),
        )
    return True


def read_artifact(run_id: str, filename: str) -> dict[str, Any] | None:
    if not enabled():
        return None
    if filename not in _ALLOWED_ARTIFACTS:
        return None
    safe_run_id = ''.join(ch for ch in str(run_id or '') if ch.isalnum() or ch in {'-', '_'})
    if not safe_run_id:
        return None
    ensure_schema()
    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT content_type, content, content_bytes, size_bytes
            FROM benchmarks.artifacts
            WHERE run_id = %s AND filename = %s
            """,
            (safe_run_id, filename),
        ).fetchone()
    if not row:
        return None
    content_type = str(row.get('content_type') or _ALLOWED_ARTIFACTS[filename])
    if row.get('content') is not None:
        body = json.dumps(row.get('content'), ensure_ascii=False, indent=2).encode('utf-8')
    else:
        body = bytes(row.get('content_bytes') or b'')
    return {
        'content_type': content_type,
        'body': body,
        'size_bytes': int(row.get('size_bytes') or len(body)),
    }
