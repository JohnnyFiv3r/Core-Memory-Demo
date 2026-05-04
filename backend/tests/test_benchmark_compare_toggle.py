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
        demo_routes.BENCHMARK_JOBS.pop(out['job_id'], None)


if __name__ == '__main__':
    unittest.main()
