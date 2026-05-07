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
        with patch.object(demo_routes, '_prune_benchmark_jobs'), \
             patch.object(demo_routes.asyncio, 'create_task', side_effect=_capture_task), \
             patch.object(demo_routes, '_benchmark_event'):
            out = await demo_routes.benchmark_run(req)
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
