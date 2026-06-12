import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'Core-Memory'))

if importlib.util.find_spec('pydantic_settings') is not None and importlib.util.find_spec('core_memory') is not None:
    from app.core import runtime as runtime_mod
else:
    runtime_mod = None


class TestLocomoBenchmarkFidelity(unittest.TestCase):
    def _row(self, *, session_index=2, dia_id='D2:7'):
        return {
            'sample_id': 'conv-1',
            'session_index': session_index,
            'turn_index': 7,
            'dia_id': dia_id,
            'speaker': 'Caroline',
            'text': 'I went to the support group on 7 May 2023.',
            'session_date_time': '7 May 2023',
        }

    def test_replay_turn_uses_real_single_turn_and_session_scope(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        captured = {}

        def fake_finalize(**kwargs):
            captured.update(kwargs)
            return {'ok': True, 'processed': 1}

        with tempfile.TemporaryDirectory() as td, patch.object(runtime_mod, 'process_turn_finalized', side_effect=fake_finalize):
            out = runtime_mod._replay_locomo_row(self._row(), root=td)
            corpus = runtime_mod.build_visible_corpus(Path(td))

        self.assertTrue(out['ok'])
        self.assertNotIn('evidence_bead_id', out)
        self.assertEqual('locomo:conv-1:session:2', out['session_id'])
        self.assertEqual('locomo:conv-1:session:2', captured['session_id'])
        self.assertEqual('locomo:conv-1:D2:7', captured['turn_id'])
        self.assertEqual('BENCHMARK_REPLAY', captured['origin'])
        turns = captured['turns']
        self.assertEqual(1, len(turns))
        self.assertEqual('other', turns[0].role)
        self.assertEqual('Caroline', turns[0].speaker)
        # Session date is folded into the ingested content: the bead judge and
        # the embedding index only ever see turn content, not turn metadata.
        self.assertEqual(
            'Session date: 7 May 2023\n\nI went to the support group on 7 May 2023.',
            turns[0].content,
        )
        self.assertNotEqual('[LoCoMo transcript replay]', turns[0].content)
        self.assertNotIn('crawler_updates', captured['metadata'])
        self.assertEqual('llm', captured['metadata']['bead_judge'])
        self.assertEqual('native_judge', captured['metadata']['_crawler_updates_source'])
        evidence_rows = [r for r in corpus if 'locomo_turn_evidence' in list(((r.get('bead') or {}).get('tags') or []))]
        self.assertEqual([], evidence_rows)

    def test_replay_turn_reports_process_turn_failure(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        with patch.object(runtime_mod, 'process_turn_finalized', return_value={'ok': False, 'error': 'boom'}):
            out = runtime_mod._replay_locomo_row(self._row(), root='/tmp/fake')
        self.assertFalse(out['ok'])
        self.assertEqual('boom', out['result']['error'])

    def test_duplicate_dia_ids_keep_sample_scoped_turn_ids_without_direct_beads(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        row1 = self._row(dia_id='D1:1')
        row2 = dict(row1)
        row2['sample_id'] = 'conv-2'
        with tempfile.TemporaryDirectory() as td, \
             patch.object(runtime_mod, 'process_turn_finalized', return_value={'ok': True, 'processed': 1}):
            out1 = runtime_mod._replay_locomo_row(row1, root=td)
            out2 = runtime_mod._replay_locomo_row(row2, root=td)
            corpus = runtime_mod.build_visible_corpus(Path(td))

        self.assertTrue(out1['ok'])
        self.assertTrue(out2['ok'])
        self.assertEqual('locomo:conv-1:D1:1', out1.get('turn_id'))
        self.assertEqual('locomo:conv-2:D1:1', out2.get('turn_id'))
        evidence_rows = [r for r in corpus if 'locomo_turn_evidence' in list(((r.get('bead') or {}).get('tags') or []))]
        self.assertEqual([], evidence_rows)

    def test_replay_turn_requires_stable_dia_id_and_text(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        with self.assertRaisesRegex(ValueError, 'locomo_missing_dia_id'):
            runtime_mod._replay_locomo_row({**self._row(), 'dia_id': ''}, root='/tmp/fake')
        with self.assertRaisesRegex(ValueError, 'locomo_empty_turn_text'):
            runtime_mod._replay_locomo_row({**self._row(), 'text': ''}, root='/tmp/fake')

    def test_ingest_replay_fails_on_partial_turn_errors(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        sample = {
            'sample_id': 'conv-1',
            'sessions': [
                {'session_index': 1, 'date_time': '1 Jan 2024', 'turns': [self._row(session_index=1, dia_id='D1:1'), self._row(session_index=1, dia_id='D1:2')]},
            ],
        }

        with tempfile.TemporaryDirectory() as td, \
             patch.object(runtime_mod, '_replay_locomo_row', side_effect=[{'ok': True, 'session_id': 'locomo:conv-1:session:1'}, {'ok': False, 'result': {'error': 'boom'}}]), \
             patch.object(runtime_mod, 'process_flush', return_value={'ok': True, 'session_id': 'locomo:conv-1:session:1'}), \
             patch.object(runtime_mod, '_drain_async_until_idle', return_value={'ok': True, 'passes': 1}), \
             patch.object(runtime_mod, 'async_jobs_status', return_value={'queues': {}}):
            out = runtime_mod.ingest_locomo_samples_through_core_memory(samples=[sample], base_root=td)

        self.assertFalse(out['ok'])
        self.assertEqual(1, out['ingested_turns'])
        self.assertEqual(1, out['failed_turns'])
        self.assertEqual('boom', out['errors'][0]['error'])

    def test_seed_replay_fails_on_partial_turn_errors(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        rows = [self._row(dia_id='D1:1'), self._row(dia_id='D1:2')]
        meta = {'sample_mode': 'single', 'sample_ids': ['conv-1'], 'session_range': {}, 'sessions_replayed': 1, 'turns_available': 2}

        with patch.object(runtime_mod, '_iter_locomo_replay_rows', return_value=(rows, meta)), \
             patch.object(runtime_mod, '_replay_locomo_row', side_effect=[{'ok': True, 'session_id': 'locomo:conv-1:session:1'}, {'ok': False, 'result': {'error': 'boom'}}]), \
             patch.object(runtime_mod, 'record_turn_tokens'), \
             patch.object(runtime_mod, 'detect_model', return_value='test-model'), \
             patch.object(runtime_mod, '_drain_async_until_idle', return_value={'ok': True, 'passes': 1}), \
             patch.object(runtime_mod, 'async_jobs_status', return_value={'queues': {}}):
            out = runtime_mod.replay_locomo_corpus(sample_mode='single', sample_id='conv-1')

        self.assertFalse(out['ok'])
        self.assertEqual(1, out['seeded_turns'])
        self.assertEqual(1, out['failed_turns'])
        self.assertEqual('boom', out['errors'][0]['error'])

    def test_drain_async_fails_fast_on_semantic_failure(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        status_queued = {'ok': True, 'pending_total': 1, 'processable_now': 1, 'queues': {'semantic_rebuild': {'queued': True, 'pending': 1}}}
        status_after = {'ok': True, 'pending_total': 1, 'processable_now': 1, 'queues': {'semantic_rebuild': {'queued': True, 'pending': 1}}}
        run_out = {
            'ok': False,
            'semantic_run': {'ran': True, 'ok': False, 'result': {'error': {'code': 'qdrant_failed'}}},
            'compaction_run': {'processed': 0, 'ok': True},
            'side_effect_run': {'processed': 0, 'ok': True},
        }

        with patch.object(runtime_mod, 'async_jobs_status', side_effect=[status_queued, status_after]), \
             patch.object(runtime_mod, 'run_async_jobs', return_value=run_out) as run_mock:
            out = runtime_mod._drain_async_until_idle(
                timeout_ms=600_000,
                poll_ms=1000,
                max_compaction=4,
                max_side_effects=16,
            )

        self.assertFalse(out['ok'])
        self.assertEqual('semantic_drain_failed', out['error'])
        self.assertEqual(1, out['passes'])
        self.assertEqual(run_out, out['last_run'])
        self.assertEqual(1, run_mock.call_count)

    def test_seed_replay_treats_semantic_drain_failure_as_warning(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        rows = [self._row(dia_id='D1:1')]
        meta = {'sample_mode': 'single', 'sample_ids': ['conv-1'], 'session_range': {}, 'sessions_replayed': 1, 'turns_available': 1}

        with patch.object(runtime_mod, '_iter_locomo_replay_rows', return_value=(rows, meta)), \
             patch.object(runtime_mod, '_replay_locomo_row', return_value={'ok': True, 'session_id': 'locomo:conv-1:session:1'}), \
             patch.object(runtime_mod, 'record_turn_tokens'), \
             patch.object(runtime_mod, 'detect_model', return_value='test-model'), \
             patch.object(runtime_mod, '_drain_async_until_idle', return_value={'ok': False, 'error': 'semantic_drain_failed', 'passes': 1}), \
             patch.object(runtime_mod, 'async_jobs_status', return_value={'queues': {}}):
            out = runtime_mod.replay_locomo_corpus(sample_mode='single', sample_id='conv-1')

        self.assertTrue(out['ok'])
        self.assertFalse(out['drain_failed'])
        self.assertTrue(out['drain_warning'])
        self.assertEqual('semantic_drain_failed', out['post_drain']['error'])
        self.assertEqual(1, out['seeded_turns'])

    def test_seed_replay_preserves_cancellation_from_drain(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        rows = [self._row(dia_id='D1:1')]
        meta = {'sample_mode': 'single', 'sample_ids': ['conv-1'], 'session_range': {}, 'sessions_replayed': 1, 'turns_available': 1}

        with patch.object(runtime_mod, '_iter_locomo_replay_rows', return_value=(rows, meta)), \
             patch.object(runtime_mod, '_replay_locomo_row', return_value={'ok': True, 'session_id': 'locomo:conv-1:session:1'}), \
             patch.object(runtime_mod, 'record_turn_tokens'), \
             patch.object(runtime_mod, 'detect_model', return_value='test-model'), \
             patch.object(runtime_mod, '_drain_async_until_idle', return_value={'ok': False, 'cancelled': True, 'error': 'drain_cancelled', 'passes': 1}), \
             patch.object(runtime_mod, 'async_jobs_status', return_value={'queues': {}}):
            out = runtime_mod.replay_locomo_corpus(sample_mode='single', sample_id='conv-1')

        self.assertFalse(out['ok'])
        self.assertTrue(out['cancelled'])
        self.assertFalse(out['drain_failed'])
        self.assertEqual('drain_cancelled', out['post_drain']['error'])
        self.assertEqual(1, out['seeded_turns'])

    def test_ingest_replay_preserves_cancellation_from_drain(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        sample = {
            'sample_id': 'conv-1',
            'sessions': [
                {'session_index': 1, 'date_time': '1 Jan 2024', 'turns': [self._row(session_index=1, dia_id='D1:1')]},
            ],
        }

        with tempfile.TemporaryDirectory() as td, \
             patch.object(runtime_mod, '_replay_locomo_row', return_value={'ok': True, 'session_id': 'locomo:conv-1:session:1'}), \
             patch.object(runtime_mod, 'process_flush', return_value={'ok': True, 'session_id': 'locomo:conv-1:session:1'}), \
             patch.object(runtime_mod, '_drain_async_until_idle', return_value={'ok': False, 'cancelled': True, 'error': 'drain_cancelled', 'passes': 1}), \
             patch.object(runtime_mod, 'async_jobs_status', return_value={'queues': {}}):
            out = runtime_mod.ingest_locomo_samples_through_core_memory(samples=[sample], base_root=td)

        self.assertFalse(out['ok'])
        self.assertTrue(out['cancelled'])
        self.assertFalse(out['drain_failed'])
        self.assertEqual('drain_cancelled', out['post_drain']['error'])
        self.assertEqual(1, out['ingested_turns'])

    def test_ingest_replay_flushes_each_locomo_session_before_post_flush_drain(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        sample = {
            'sample_id': 'conv-1',
            'sessions': [
                {'session_index': 1, 'date_time': '1 Jan 2024', 'turns': [self._row(session_index=1, dia_id='D1:1')]},
                {'session_index': 2, 'date_time': '2 Jan 2024', 'turns': [self._row(session_index=2, dia_id='D2:1')]},
            ],
        }
        flush_order = []

        def fake_flush(**kwargs):
            flush_order.append(kwargs['session_id'])
            return {'ok': True, 'session_id': kwargs['session_id']}

        with tempfile.TemporaryDirectory() as td, \
             patch.object(runtime_mod, 'process_turn_finalized', return_value={'ok': True, 'processed': 1}), \
             patch.object(runtime_mod, 'process_flush', side_effect=fake_flush), \
             patch.object(runtime_mod, '_drain_async_until_idle', return_value={'ok': True, 'passes': 1}), \
             patch.object(runtime_mod, 'async_jobs_status', return_value={'queues': {}}):
            out = runtime_mod.ingest_locomo_samples_through_core_memory(samples=[sample], base_root=td)

        self.assertTrue(out['ok'])
        self.assertEqual(2, out['ingested_turns'])
        self.assertEqual(['locomo:conv-1:session:1', 'locomo:conv-1:session:2'], flush_order)
        self.assertEqual('per_locomo_session_before_qa', out['flush_policy'])
        self.assertEqual(2, out['flush_count'])
        self.assertEqual(0, out['flush_failed'])
        self.assertEqual(1, out['post_drain']['passes'])

    def test_corpus_validation_blocks_tiny_semantic_or_unprovenanced_corpus(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        with patch.object(runtime_mod, 'build_visible_corpus', return_value=[{'bead_id': 'b1', 'source_turn_ids': []}]):
            with self.assertRaisesRegex(RuntimeError, 'invalid_benchmark_corpus'):
                runtime_mod._validate_locomo_benchmark_corpus(root='/tmp/fake', turns_ingested=419, semantic_build={'entries': 1})

    def test_corpus_validation_accepts_native_source_turn_ids(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        rows = [
            {'bead_id': f'b{i}', 'source_turn_ids': [f'locomo:conv-1:D1:{i}']}
            for i in range(1, 86)
        ]
        with patch.object(runtime_mod, 'build_visible_corpus', return_value=rows):
            out = runtime_mod._validate_locomo_benchmark_corpus(root='/tmp/fake', turns_ingested=100, semantic_build={'entries': 85})
        self.assertTrue(out['ok'])
        self.assertEqual(85, out['sample_scoped_turn_ids_visible'])
        self.assertEqual(85, out['distinct_dia_ids_visible'])

    def test_corpus_validation_is_sample_scoped_not_bare_dia_scoped(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        rows = []
        for sample_i in range(1, 6):
            for dia_i in range(1, 21):
                rows.append({'bead_id': f'b{sample_i}-{dia_i}', 'source_turn_ids': [f'locomo:conv-{sample_i}:D1:{dia_i}', f'D1:{dia_i}']})
        with patch.object(runtime_mod, 'build_visible_corpus', return_value=rows):
            out = runtime_mod._validate_locomo_benchmark_corpus(root='/tmp/fake', turns_ingested=100, semantic_build={'entries': 100})
        self.assertTrue(out['ok'])
        self.assertEqual(100, out['sample_scoped_turn_ids_visible'])
        self.assertEqual(20, out['distinct_dia_ids_visible'])

    def test_corpus_validation_rejects_session_head_only_corpus(self):
        if runtime_mod is None:
            self.skipTest('runtime unavailable')
        rows = [
            {'bead_id': f'b{i}', 'source_turn_ids': [f'locomo:conv-41:D{i}:1']}
            for i in range(1, 33)
        ]
        with patch.object(runtime_mod, 'build_visible_corpus', return_value=rows):
            with self.assertRaisesRegex(RuntimeError, 'invalid_benchmark_corpus'):
                runtime_mod._validate_locomo_benchmark_corpus(root='/tmp/fake', turns_ingested=663, semantic_build={'entries': 32})


if __name__ == '__main__':
    unittest.main()
