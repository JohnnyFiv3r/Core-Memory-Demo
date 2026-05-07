CREATE SCHEMA IF NOT EXISTS benchmarks;

CREATE TABLE IF NOT EXISTS benchmarks.runs (
    run_id TEXT PRIMARY KEY,
    job_id TEXT,
    suite TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    report JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS benchmarks_runs_started_at_idx ON benchmarks.runs (started_at DESC);
CREATE INDEX IF NOT EXISTS benchmarks_runs_status_idx ON benchmarks.runs (status) WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS benchmarks.jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',
    request JSONB NOT NULL DEFAULT '{}'::jsonb,
    kwargs JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    claimed_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS benchmarks_jobs_status_created_idx ON benchmarks.jobs (status, created_at);

CREATE TABLE IF NOT EXISTS benchmarks.artifacts (
    run_id TEXT NOT NULL REFERENCES benchmarks.runs(run_id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content JSONB,
    content_bytes BYTEA,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, filename)
);

CREATE TABLE IF NOT EXISTS benchmarks.cases (
    run_id TEXT NOT NULL REFERENCES benchmarks.runs(run_id) ON DELETE CASCADE,
    qa_id TEXT NOT NULL,
    sample_id TEXT NOT NULL DEFAULT '',
    category INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT '',
    answer_f1 DOUBLE PRECISION,
    evidence_recall JSONB NOT NULL DEFAULT '{}'::jsonb,
    retrieved JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, qa_id)
);
CREATE INDEX IF NOT EXISTS benchmarks_cases_category_idx ON benchmarks.cases (run_id, category);
CREATE INDEX IF NOT EXISTS benchmarks_cases_status_idx ON benchmarks.cases (run_id, status) WHERE status = 'error';
