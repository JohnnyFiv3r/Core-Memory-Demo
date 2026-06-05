import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestBenchmarkStoreKindFilters(unittest.TestCase):
    def test_read_active_job_includes_locomo_full_by_default(self):
        from app.benchmarks import benchmark_store

        captured: dict[str, object] = {}

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                captured['sql'] = sql
                captured['params'] = params

                class Row:
                    def fetchone(self):
                        return None

                return Row()

        with patch.object(benchmark_store, 'enabled', return_value=True), \
             patch.object(benchmark_store, 'ensure_schema', return_value=None), \
             patch.object(benchmark_store, '_database_url', return_value='postgres://example'), \
             patch.object(benchmark_store, 'psycopg', SimpleNamespace(connect=lambda *a, **k: FakeConn())):
            benchmark_store.read_active_job(max_age_seconds=0)

        self.assertIn("COALESCE(request->>'kind', 'benchmark') = ANY(%s)", str(captured.get('sql') or ''))
        self.assertEqual(['benchmark', 'locomo_full'], captured.get('params')[0])

    def test_timeout_stale_jobs_filters_default_benchmark_kind(self):
        from app.benchmarks import benchmark_store

        captured: dict[str, object] = {}

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                captured['sql'] = sql
                captured['params'] = params

                class Rows:
                    def fetchall(self):
                        return []

                return Rows()

        with patch.object(benchmark_store, 'enabled', return_value=True), \
             patch.object(benchmark_store, 'ensure_schema', return_value=None), \
             patch.object(benchmark_store, '_database_url', return_value='postgres://example'), \
             patch.object(benchmark_store, 'psycopg', SimpleNamespace(connect=lambda *a, **k: FakeConn())):
            benchmark_store.timeout_stale_jobs(max_runtime_seconds=0)

        self.assertIn("COALESCE(request->>'kind', 'benchmark') = ANY(%s)", str(captured.get('sql') or ''))
        self.assertEqual(['benchmark', 'locomo_full'], captured.get('params')[1])

    def test_timeout_stale_queued_jobs_filters_default_benchmark_kind(self):
        from app.benchmarks import benchmark_store

        captured: dict[str, object] = {}

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                captured['sql'] = sql
                captured['params'] = params

                class Rows:
                    def fetchall(self):
                        return []

                return Rows()

        with patch.object(benchmark_store, 'enabled', return_value=True), \
             patch.object(benchmark_store, 'ensure_schema', return_value=None), \
             patch.object(benchmark_store, '_database_url', return_value='postgres://example'), \
             patch.object(benchmark_store, 'Jsonb', lambda value: value), \
             patch.object(benchmark_store, 'psycopg', SimpleNamespace(connect=lambda *a, **k: FakeConn())):
            benchmark_store.timeout_stale_queued_jobs(max_queue_seconds=0)

        self.assertIn("COALESCE(request->>'kind', 'benchmark') = ANY(%s)", str(captured.get('sql') or ''))
        self.assertEqual(['benchmark', 'locomo_full'], captured.get('params')[2])


if __name__ == '__main__':
    unittest.main()
