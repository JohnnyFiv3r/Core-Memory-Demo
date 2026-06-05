import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'Core-Memory'))

if importlib.util.find_spec('pydantic_settings') is not None:
    from app.routes import demo as demo_routes
else:
    demo_routes = None


class _Req:
    def __init__(self, body):
        self._body = body
        self.headers = {'content-type': 'application/json'}

    async def json(self):
        return dict(self._body)


class TestBenchmarkCompareToggle(unittest.IsolatedAsyncioTestCase):
    async def test_benchmark_run_forwards_compare_paths(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        req = _Req({
            'suite': 'locomo_mini',
            'compare_paths': True,
            'sample_limit': 1,
            'qa_limit': 1,
            'sample_ids': ['conv-1'],
            'qa_per_category': {'1': 3, '2': 2},
        })
        fake_task = object()
        seen = {}
        def _capture_task(coro):
            frame = getattr(coro, 'cr_frame', None)
            if frame is not None:
                seen['kwargs'] = dict(frame.f_locals.get('kwargs') or {})
            coro.close()
            return fake_task
        old_mode = demo_routes.settings.benchmark_run_mode
        demo_routes.settings.benchmark_run_mode = 'background'
        try:
            with patch.object(demo_routes, '_prune_benchmark_jobs'), \
                 patch.object(demo_routes.asyncio, 'create_task', side_effect=_capture_task), \
                 patch.object(demo_routes, '_benchmark_event'):
                out = await demo_routes.benchmark_run(req)
        finally:
            demo_routes.settings.benchmark_run_mode = old_mode
        self.assertTrue(out['ok'])
        self.assertTrue(seen['kwargs']['compare_paths'])
        self.assertEqual({'1': 3, '2': 2}, seen['kwargs']['qa_per_category'])
        demo_routes.BENCHMARK_JOBS.pop(out['job_id'], None)

    async def test_external_benchmark_mode_dispatches_without_create_task(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        req = _Req({'suite': 'locomo_mini', 'sample_limit': 1, 'qa_limit': 1})
        old_mode = demo_routes.settings.benchmark_run_mode
        old_url = demo_routes.settings.benchmark_dispatch_url
        demo_routes.settings.benchmark_run_mode = 'external'
        demo_routes.settings.benchmark_dispatch_url = 'https://runner.example.invalid/benchmark'
        try:
            with patch.object(demo_routes, '_prune_benchmark_jobs'), \
                 patch.object(demo_routes, '_dispatch_benchmark_job', return_value={'ok': True, 'job_id': 'render-job-1'}) as dispatch, \
                 patch.object(demo_routes.asyncio, 'create_task') as create_task:
                out = await demo_routes.benchmark_run(req)
        finally:
            demo_routes.settings.benchmark_run_mode = old_mode
            demo_routes.settings.benchmark_dispatch_url = old_url
        self.assertTrue(out['ok'])
        self.assertEqual('external_dispatched', out['status'])
        self.assertEqual('render-job-1', out['external_job_id'])
        self.assertEqual(1, dispatch.call_count)
        self.assertFalse(create_task.called)
        demo_routes.BENCHMARK_JOBS.pop(out['job_id'], None)

    async def test_queue_mode_reuses_active_stored_job(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        req = _Req({'suite': 'locomo_mini', 'sample_limit': 1, 'qa_limit': 1})
        old_mode = demo_routes.settings.benchmark_run_mode
        demo_routes.settings.benchmark_run_mode = 'queue'
        try:
            with patch.object(demo_routes, '_prune_benchmark_jobs'), \
                 patch.object(demo_routes.benchmark_store, 'read_active_job', return_value={'job_id': 'stored-active', 'status': 'running'}), \
                 patch.object(demo_routes.benchmark_store, 'enqueue_job') as enqueue:
                out = await demo_routes.benchmark_run(req)
        finally:
            demo_routes.settings.benchmark_run_mode = old_mode
        self.assertTrue(out['ok'])
        self.assertTrue(out['already_running'])
        self.assertEqual('stored-active', out['job_id'])
        self.assertFalse(enqueue.called)

    def test_benchmark_runtime_default_is_120_minutes(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        self.assertEqual(120 * 60, demo_routes.settings.benchmark_max_runtime_seconds)
        self.assertEqual(120 * 60, demo_routes.BENCHMARK_MAX_RUNTIME_SECONDS)

    async def test_locomo_lifecycle_queue_enqueues_combined_locomo_full_worker_job(self):
        # Option A: a queued LoCoMo run is a single worker job (seed + QA + report),
        # not a web-background QA-only task. It enqueues kind=locomo_full and does
        # not spawn an in-process create_task.
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        req = _Req({'suite': 'locomo_native_lifecycle', 'root_mode': 'snapshot', 'sample_ids': ['conv-1'], 'qa_limit': 5})
        old_mode = demo_routes.settings.benchmark_run_mode
        demo_routes.settings.benchmark_run_mode = 'queue'

        def fake_create_task(coro):
            try:
                coro.close()
            except Exception:
                pass
            return object()

        captured: dict = {}

        def fake_enqueue(*, job_id, request, kwargs):
            captured['request'] = dict(request)
            captured['kwargs'] = dict(kwargs)
            return True

        try:
            demo_routes.SEED_JOBS.clear()
            demo_routes.SEED_STATUS.update({'active': False})
            with patch.object(demo_routes, '_prune_benchmark_jobs'), \
                 patch.object(demo_routes.benchmark_store, 'read_active_job', return_value=None), \
                 patch.object(demo_routes.benchmark_store, 'diagnostics', return_value={}), \
                 patch.object(demo_routes.benchmark_store, 'enqueue_job', side_effect=fake_enqueue), \
                 patch.object(demo_routes.asyncio, 'create_task', side_effect=fake_create_task) as create_task:
                out = await demo_routes.benchmark_run(req)
        finally:
            demo_routes.settings.benchmark_run_mode = old_mode
            demo_routes.SEED_JOBS.clear()
        self.assertTrue(out['ok'])
        self.assertEqual('locomo_full', captured['request']['kind'])
        self.assertIn('seed', captured['kwargs'])
        self.assertIn('benchmark', captured['kwargs'])
        self.assertEqual(['conv-1'], captured['kwargs']['seed']['sample_ids'])
        self.assertEqual('single', captured['kwargs']['seed']['sample_mode'])
        self.assertEqual('isolated', captured['kwargs']['benchmark']['qa_session_mode'])
        self.assertFalse(captured['kwargs']['benchmark']['qa_only_seeded'])
        self.assertFalse(create_task.called)  # durable worker job, not web background

    async def test_locomo_lifecycle_queue_seeds_all_requested_samples(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        req = _Req({'suite': 'locomo_native_lifecycle', 'root_mode': 'snapshot', 'sample_ids': ['conv-1', 'conv-2'], 'qa_limit': 5})
        old_mode = demo_routes.settings.benchmark_run_mode
        demo_routes.settings.benchmark_run_mode = 'queue'

        captured: dict = {}

        def fake_enqueue(*, job_id, request, kwargs):
            captured['request'] = dict(request)
            captured['kwargs'] = dict(kwargs)
            return True

        try:
            demo_routes.SEED_JOBS.clear()
            demo_routes.SEED_STATUS.update({'active': False})
            with patch.object(demo_routes, '_prune_benchmark_jobs'), \
                 patch.object(demo_routes.benchmark_store, 'read_active_job', return_value=None), \
                 patch.object(demo_routes.benchmark_store, 'diagnostics', return_value={}), \
                 patch.object(demo_routes.benchmark_store, 'enqueue_job', side_effect=fake_enqueue):
                out = await demo_routes.benchmark_run(req)
        finally:
            demo_routes.settings.benchmark_run_mode = old_mode
            demo_routes.SEED_JOBS.clear()

        self.assertTrue(out['ok'])
        self.assertEqual('locomo_full', captured['request']['kind'])
        self.assertEqual(['conv-1', 'conv-2'], captured['kwargs']['seed']['sample_ids'])
        self.assertEqual('all', captured['kwargs']['seed']['sample_mode'])
        self.assertIsNone(captured['kwargs']['seed']['sample_id'])
        self.assertIsNone(captured['kwargs']['seed']['max_turns'])
        self.assertEqual(['conv-1', 'conv-2'], captured['kwargs']['benchmark']['sample_ids'])
        self.assertFalse(captured['kwargs']['benchmark']['qa_only_seeded'])

    async def test_locomo_lifecycle_queue_durably_enqueues_locomo_full_with_clean_shared_llm(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        req = _Req({'suite': 'locomo_native_lifecycle', 'root_mode': 'snapshot', 'qa_session_mode': 'shared', 'answer_mode': 'none', 'sample_ids': ['conv-1']})
        old_mode = demo_routes.settings.benchmark_run_mode
        demo_routes.settings.benchmark_run_mode = 'queue'

        def fake_create_task(coro):
            try:
                coro.close()
            except Exception:
                pass
            return object()

        captured: dict = {}

        def fake_enqueue(*, job_id, request, kwargs):
            captured['request'] = dict(request)
            captured['kwargs'] = dict(kwargs)
            return True

        try:
            demo_routes.SEED_JOBS.clear()
            demo_routes.SEED_STATUS.update({'active': False})
            with patch.dict(demo_routes.os.environ, {'CORE_MEMORY_VECTOR_BACKEND': 'qdrant', 'CORE_MEMORY_GRAPH_BACKEND': 'kuzu'}), \
                 patch.object(demo_routes, '_prune_benchmark_jobs'), \
                 patch.object(demo_routes.benchmark_store, 'read_active_job', return_value=None), \
                 patch.object(demo_routes.benchmark_store, 'diagnostics', return_value={}), \
                 patch.object(demo_routes.benchmark_store, 'enqueue_job', side_effect=fake_enqueue), \
                 patch.object(demo_routes.asyncio, 'create_task', side_effect=fake_create_task):
                out = await demo_routes.benchmark_run(req)
        finally:
            demo_routes.settings.benchmark_run_mode = old_mode
            demo_routes.SEED_JOBS.clear()
        self.assertTrue(out['ok'])
        self.assertEqual('locomo_full', captured['request']['kind'])
        bench = captured['kwargs']['benchmark']
        self.assertEqual('clean', bench['root_mode'])
        self.assertEqual('shared', bench['qa_session_mode'])
        self.assertFalse(bench['qa_only_seeded'])
        self.assertEqual('llm', bench['answer_mode'])

    def test_benchmark_request_for_store_uses_runtime_backends(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        with patch.dict(demo_routes.os.environ, {'CORE_MEMORY_VECTOR_BACKEND': 'qdrant', 'CORE_MEMORY_GRAPH_BACKEND': 'kuzu'}):
            out = demo_routes._benchmark_request_for_store({'suite': 'locomo_native_lifecycle', 'vector_backend': 'local-faiss'})
        self.assertEqual('qdrant', out['vector_backend'])
        self.assertEqual('kuzu', out['graph_backend'])

    def test_benchmark_last_returns_stored_active_without_snapshot(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        stored = {
            'job_id': 'active-db-job',
            'status': 'running',
            'request': {'suite': 'locomo_native_lifecycle', 'vector_backend': 'qdrant', 'graph_backend': 'kuzu'},
            'kwargs': {'suite': 'locomo_native_lifecycle', 'semantic_mode_name': 'required', 'root_mode': 'clean'},
            'progress': {'stage': 'locomo_lifecycle', 'stage_message': 'Replayed 111/175 turns'},
            'events': [],
            'started_at': '2026-06-01T22:41:46+00:00',
            'updated_at': '2026-06-01T22:44:34+00:00',
        }
        with patch.object(demo_routes, '_prune_benchmark_jobs'), \
             patch.object(demo_routes.benchmark_store, 'read_active_job', return_value=stored), \
             patch.object(demo_routes, 'get_last_benchmark_snapshot', side_effect=AssertionError('snapshot should not be read while active')):
            out = demo_routes.benchmark_last()
        self.assertTrue(out['ok'])
        self.assertEqual('running', out['summary']['status'])
        self.assertEqual('qdrant', out['report']['config']['vector_backend'])


    def test_benchmark_last_prefers_newer_failed_durable_job_over_stale_success(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        stale_snapshot = {
            'ok': True,
            'summary': {
                'run_id': 'bench-old-success',
                'status': 'completed',
                'finished_at': '2026-06-04T17:05:31+00:00',
            },
            'report': {'run_id': 'bench-old-success', 'status': 'completed'},
            'history': [{'run_id': 'bench-old-success', 'summary': {'run_id': 'bench-old-success'}}],
        }
        failed_job = {
            'job_id': 'job-new-failed',
            'status': 'failed',
            'request': {'kind': 'locomo_full', 'suite': 'locomo_native_lifecycle'},
            'kwargs': {'suite': 'locomo_native_lifecycle', 'semantic_mode_name': 'required', 'root_mode': 'clean'},
            'progress': {'stage': 'failed', 'stage_message': 'semantic build failed'},
            'events': [{'seq': 1, 'stage': 'failed', 'message': 'semantic build failed'}],
            'error': 'benchmark_semantic_build_failed_required: runtimeerror',
            'created_at': '2026-06-05T15:33:18+00:00',
            'updated_at': '2026-06-05T16:10:55+00:00',
            'finished_at': '2026-06-05T16:10:55+00:00',
        }
        with patch.object(demo_routes, '_prune_benchmark_jobs'), \
             patch.object(demo_routes.benchmark_store, 'read_active_job', return_value=None), \
             patch.object(demo_routes, 'get_last_benchmark_snapshot', return_value=stale_snapshot), \
             patch.object(demo_routes.benchmark_store, 'read_latest_job_by_kind', return_value=failed_job):
            out = demo_routes.benchmark_last()
        self.assertTrue(out['ok'])
        self.assertEqual('failed', out['summary']['status'])
        self.assertEqual('job-new-failed', out['summary']['job_id'])
        self.assertFalse(out['summary']['active'])
        self.assertIn('benchmark_semantic_build_failed_required', out['summary']['error'])
        self.assertEqual('', out['summary']['run_id'])
        self.assertNotEqual('bench-old-success', out['report'].get('run_id'))
        self.assertFalse(out['report']['active'])

    def test_benchmark_last_ignores_older_failed_durable_job_than_success(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        fresh_snapshot = {
            'ok': True,
            'summary': {
                'run_id': 'bench-new-success',
                'status': 'completed',
                'finished_at': '2026-06-05T17:05:31+00:00',
            },
            'report': {'run_id': 'bench-new-success', 'status': 'completed'},
            'history': [],
        }
        older_failed_job = {
            'job_id': 'job-old-failed',
            'status': 'failed',
            'request': {'kind': 'locomo_full'},
            'kwargs': {},
            'progress': {'stage': 'failed'},
            'events': [],
            'error': 'old failure',
            'created_at': '2026-06-05T15:33:18+00:00',
            'updated_at': '2026-06-05T16:10:55+00:00',
            'finished_at': '2026-06-05T16:10:55+00:00',
        }
        with patch.object(demo_routes, '_prune_benchmark_jobs'), \
             patch.object(demo_routes.benchmark_store, 'read_active_job', return_value=None), \
             patch.object(demo_routes, 'get_last_benchmark_snapshot', return_value=fresh_snapshot), \
             patch.object(demo_routes.benchmark_store, 'read_latest_job_by_kind', return_value=older_failed_job):
            out = demo_routes.benchmark_last()
        self.assertTrue(out['ok'])
        self.assertEqual('completed', out['summary']['status'])
        self.assertEqual('bench-new-success', out['summary']['run_id'])

    def test_benchmark_run_state_skips_filesystem_when_queue_active(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        stored = {'job_id': 'active-db-job', 'status': 'running'}
        with patch.object(demo_routes.benchmark_store, 'read_active_job', return_value=stored), \
             patch.object(demo_routes, 'inspect_benchmark_run_state_payload', side_effect=AssertionError('run-state should not inspect filesystem while queue active')):
            out = demo_routes.demo_benchmark_run_state()
        self.assertTrue(out['ok'])
        self.assertFalse(out['active_run'])
        self.assertEqual('durable_queue_active', out['source'])
        self.assertEqual('active-db-job', out['active_job_id'])

    def test_job_status_prefers_stored_completion_over_web_placeholder(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        job_id = 'stored-done'
        demo_routes.BENCHMARK_JOBS[job_id] = {
            'job_id': job_id,
            'status': 'queued_external',
            'stage': 'queued_external',
            'done': True,
            'result': {'queued': True},
            'events': [],
            'seq': 0,
            'started_ms': 1,
            'updated_ms': 1,
        }
        try:
            with patch.object(demo_routes, '_prune_benchmark_jobs'), \
                 patch.object(demo_routes.benchmark_store, 'read_job', return_value={
                     'job_id': job_id,
                     'status': 'completed',
                     'result': {'ok': True, 'run_id': 'bench-1'},
                     'error': None,
                     'finished_at': '2026-05-07T16:00:00+00:00',
                 }):
                out = demo_routes.benchmark_job_status(job_id)
        finally:
            demo_routes.BENCHMARK_JOBS.pop(job_id, None)
        self.assertEqual('completed', out['status'])
        self.assertTrue(out['done'])
        self.assertEqual('bench-1', out['result']['run_id'])


if __name__ == '__main__':
    unittest.main()
