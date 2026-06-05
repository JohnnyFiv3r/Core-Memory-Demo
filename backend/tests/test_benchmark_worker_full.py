import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks import benchmark_worker as bw


class TestLocomoFullWorkerJob(unittest.TestCase):
    """Option A: one worker invocation seeds then runs QA, streaming both phases."""

    def _run(self, *, seed_out, bench_out, kwargs):
        events = []
        order = []
        store = MagicMock()
        store.claim_next_job.return_value = {
            'job_id': 'job-1', 'request': {'kind': 'locomo_full'}, 'kwargs': kwargs,
        }
        store.update_job_progress.side_effect = lambda job_id, **kw: events.append(kw.get('stage'))

        def fake_seed(**kw):
            order.append('seed')
            if callable(kw.get('progress')):
                kw['progress'](1, 2)
                kw['progress'](2, 2)
            return seed_out

        def fake_bench(**kw):
            order.append('bench')
            if callable(kw.get('progress')):
                kw['progress'](1, 1, {'qa_id': 'q1'}, {'phase': 'qa', 'status': 'ok', 'answer': 'A', 'answer_f1': 1.0})
            return bench_out

        with patch.object(bw, 'benchmark_store', store), \
             patch.object(bw, 'replay_locomo_corpus', fake_seed), \
             patch.object(bw, 'run_benchmark', fake_bench):
            rc = bw.run_once()
        return rc, order, events, store

    def test_seed_then_qa_then_report_with_streaming(self):
        rc, order, events, store = self._run(
            seed_out={'ok': True, 'seeded': 2},
            bench_out={'ok': True, 'scores': {'overall': {}}},
            kwargs={'seed': {'sample_mode': 'single', 'sample_id': 'conv-26'},
                    'benchmark': {'suite': 'locomo_native_lifecycle'}},
        )
        self.assertEqual(0, rc)
        self.assertEqual(['seed', 'bench'], order)            # seed BEFORE qa
        self.assertIn('seeding', events)                      # seed phase streamed
        self.assertIn('seeded', events)                       # boundary streamed
        self.assertIn('qa', events)                           # qa phase streamed
        args, kw = store.finish_job.call_args
        self.assertEqual('job-1', args[0])
        self.assertTrue(kw['result']['ok'])
        self.assertEqual(2, kw['result']['seed']['seeded'])   # report carries seed summary

    def test_seed_failure_skips_qa_and_finishes_error(self):
        rc, order, events, store = self._run(
            seed_out={'ok': False, 'error': 'boom'},
            bench_out={'ok': True},
            kwargs={'seed': {}, 'benchmark': {}},
        )
        self.assertEqual(1, rc)
        self.assertEqual(['seed'], order)                     # QA never ran
        _, kw = store.finish_job.call_args
        self.assertIn('locomo_seed_failed', kw.get('error', ''))


if __name__ == '__main__':
    unittest.main()
