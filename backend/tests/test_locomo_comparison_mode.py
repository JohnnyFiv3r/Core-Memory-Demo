import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'Core-Memory'))

if importlib.util.find_spec('pydantic_settings') is not None:
    from app.core import runtime as runtime_mod
else:
    runtime_mod = None


class TestLocomoComparisonMode(unittest.TestCase):
    def test_snapshot_sanitize_removes_inherited_claims_and_prior_locomo_beads(self):
        if runtime_mod is None:
            self.skipTest('pydantic_settings unavailable')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            idx_path = root / '.beads' / 'index.json'
            idx_path.parent.mkdir(parents=True, exist_ok=True)
            idx_path.write_text(
                json.dumps(
                    {
                        'beads': {
                            'live-1': {
                                'id': 'live-1',
                                'session_id': 'demo',
                                'claims': [{'id': 'c1', 'subject': 'user', 'slot': 'identity', 'value': 'Sam: Hey Evan'}],
                                'claim_updates': [{'id': 'u1'}],
                            },
                            'locomo-old': {
                                'id': 'locomo-old',
                                'session_id': 'locomo:conv-49',
                                'source_turn_ids': ['locomo:conv-49:D1:1'],
                                'tags': ['locomo'],
                                'claims': [{'id': 'bad', 'subject': 'user', 'slot': 'identity', 'value': 'Sam: Hey Evan'}],
                            },
                            'live-2': {'id': 'live-2', 'session_id': 'demo', 'summary': ['ordinary noise']},
                        },
                        'associations': [{'source': 'locomo-old', 'target': 'live-2'}, {'source': 'live-1', 'target': 'live-2'}],
                    }
                ),
                encoding='utf-8',
            )
            (root / 'live-1').mkdir()
            (root / 'live-1' / 'claims.json').write_text('[]', encoding='utf-8')

            stats = runtime_mod._sanitize_locomo_benchmark_snapshot(root)
            idx = json.loads(idx_path.read_text(encoding='utf-8'))

        self.assertEqual(1, stats['claim_payloads_stripped'])
        self.assertEqual(1, stats['claim_update_payloads_stripped'])
        self.assertEqual(1, stats['locomo_beads_removed'])
        self.assertEqual(1, stats['associations_removed'])
        self.assertIn('live-1', idx['beads'])
        self.assertIn('live-2', idx['beads'])
        self.assertNotIn('locomo-old', idx['beads'])
        self.assertEqual([], idx['beads']['live-1'].get('claims'))
        self.assertEqual([], idx['beads']['live-1'].get('claim_updates'))
        self.assertEqual([{'source': 'live-1', 'target': 'live-2'}], idx['associations'])

    def test_compare_paths_writes_comparison(self):
        if runtime_mod is None:
            self.skipTest('pydantic_settings unavailable')
        fake_dataset_meta = {'dataset': {'selected_samples': 1, 'selected_qa_cases': 1, 'dataset_path': 'locomo.json'}}
        fake_cases = [{'qa_id': 'q1', 'sample_id': 'conv-1', 'category': 2, 'question': 'Q?', 'answer': 'A', 'evidence': ['D1:1']}]
        fake_samples = [{'sample_id': 'conv-1', 'sessions': []}]
        fake_gold = {'D1:1': {'dia_ids': ['D1:1']}}
        main_report = {'cases': [{'qa_id': 'q1', 'sample_id': 'conv-1', 'category': 2, 'answer_f1': 0.0, 'evidence_recall': {'recall@5': 0.0, 'hit_any': False, 'mrr': 0.0}, 'status': 'ok'}], 'completed': 1, 'failed': 0}
        compare_report = {'cases': [{'qa_id': 'q1', 'sample_id': 'conv-1', 'category': 2, 'answer_f1': 1.0, 'evidence_recall': {'recall@5': 1.0, 'hit_any': True, 'mrr': 1.0}, 'status': 'ok'}], 'completed': 1, 'failed': 0}

        with tempfile.TemporaryDirectory() as td:
            old_bench_root = runtime_mod.settings.core_memory_demo_benchmark_root
            old_art_root = runtime_mod.settings.core_memory_demo_artifacts_root
            old_ingest_path = runtime_mod.settings.locomo_ingest_path
            old_compare = runtime_mod.settings.locomo_compare_paths_enabled
            runtime_mod.settings.core_memory_demo_benchmark_root = td
            runtime_mod.settings.core_memory_demo_artifacts_root = td
            runtime_mod.settings.locomo_ingest_path = 'bead_direct'
            runtime_mod.settings.locomo_compare_paths_enabled = True
            try:
                with patch.object(runtime_mod, 'build_locomo_suite_metadata', return_value=(fake_dataset_meta, fake_cases, fake_samples, fake_gold)), \
                     patch.object(runtime_mod, 'ingest_locomo_samples', side_effect=[{'ingested_turns': 1, 'rows': [], 'turns_total': 1, 'ingested_count': 1, 'skipped_existing_count': 0}, {'ingested_turns': 1, 'rows': [], 'turns_total': 1, 'ingested_count': 1, 'skipped_existing_count': 0}]), \
                     patch.object(runtime_mod, 'run_locomo_retrieval_suite', side_effect=[main_report, compare_report]), \
                     patch.object(runtime_mod, 'build_semantic_index', side_effect=[{'ok': True, 'backend': 'hash', 'entries': 1}, {'ok': True, 'backend': 'hash', 'entries': 1}]):
                    out = runtime_mod.run_benchmark(
                        semantic_mode_name='required',
                        root_mode='snapshot',
                        preload_from_demo=False,
                        preload_turns_max=5,
                        suite='locomo_mini',
                        sample_limit=1,
                        qa_limit=1,
                        sample_ids=['conv-1'],
                        category_filter=[],
                        retrieval_k=5,
                        ingestion_mode='turns',
                        answer_mode='llm',
                        generator_model=None,
                        evidence_recall_k=[1, 5],
                        persist_case_artifacts=True,
                        embeddings_provider='hash',
                    )
            finally:
                runtime_mod.settings.core_memory_demo_benchmark_root = old_bench_root
                runtime_mod.settings.core_memory_demo_artifacts_root = old_art_root
                runtime_mod.settings.locomo_ingest_path = old_ingest_path
                runtime_mod.settings.locomo_compare_paths_enabled = old_compare

        self.assertTrue(out['ok'])
        self.assertTrue(out['report']['config']['compare_paths_requested'])
        self.assertTrue(out['report']['config']['compare_paths_executed'])
        self.assertEqual('bead_direct', out['report']['config']['ingest_path_active'])
        self.assertEqual('canonical_replay', out['report']['config']['compare_target'])
        self.assertIn('comparison', out['report'])
        self.assertEqual('bead_direct', out['report']['comparison']['left'])
        self.assertEqual('canonical_replay', out['report']['comparison']['right'])
        self.assertGreater(out['report']['comparison']['overall']['delta']['evidence_recall@5'], 0.0)

    def test_compare_retrieval_modes_writes_comparison(self):
        if runtime_mod is None:
            self.skipTest('pydantic_settings unavailable')
        fake_dataset_meta = {'dataset': {'selected_samples': 1, 'selected_qa_cases': 1, 'dataset_path': 'locomo.json'}}
        fake_cases = [{'qa_id': 'q1', 'sample_id': 'conv-1', 'category': 2, 'question': 'Q?', 'answer': 'A', 'evidence': ['D1:1']}]
        fake_samples = [{'sample_id': 'conv-1', 'sessions': []}]
        fake_gold = {'D1:1': {'dia_ids': ['D1:1']}}
        main_report = {'cases': [{'qa_id': 'q1', 'sample_id': 'conv-1', 'category': 2, 'answer_f1': 0.0, 'evidence_recall': {'recall@5': 0.0, 'hit_any': False, 'mrr': 0.0}, 'status': 'ok'}], 'completed': 1, 'failed': 0}
        hydrated_report = {'cases': [{'qa_id': 'q1', 'sample_id': 'conv-1', 'category': 2, 'answer_f1': 1.0, 'evidence_recall': {'recall@5': 1.0, 'hit_any': True, 'mrr': 1.0}, 'status': 'ok', 'hydration': {'used': True, 'hydrated_rows': 1}}], 'completed': 1, 'failed': 0}

        with tempfile.TemporaryDirectory() as td:
            old_bench_root = runtime_mod.settings.core_memory_demo_benchmark_root
            old_art_root = runtime_mod.settings.core_memory_demo_artifacts_root
            old_ingest_path = runtime_mod.settings.locomo_ingest_path
            old_compare = runtime_mod.settings.locomo_compare_paths_enabled
            runtime_mod.settings.core_memory_demo_benchmark_root = td
            runtime_mod.settings.core_memory_demo_artifacts_root = td
            runtime_mod.settings.locomo_ingest_path = 'bead_direct'
            runtime_mod.settings.locomo_compare_paths_enabled = False
            try:
                with patch.object(runtime_mod, 'build_locomo_suite_metadata', return_value=(fake_dataset_meta, fake_cases, fake_samples, fake_gold)), \
                     patch.object(runtime_mod, 'ingest_locomo_samples', return_value={'ingested_turns': 1, 'rows': [], 'turns_total': 1, 'ingested_count': 1, 'skipped_existing_count': 0}), \
                     patch.object(runtime_mod, 'run_locomo_retrieval_suite', side_effect=[main_report, hydrated_report]), \
                     patch.object(runtime_mod, 'build_semantic_index', return_value={'ok': True, 'backend': 'hash', 'entries': 1}):
                    out = runtime_mod.run_benchmark(
                        semantic_mode_name='required',
                        root_mode='clean',
                        preload_from_demo=False,
                        preload_turns_max=5,
                        suite='locomo_mini',
                        sample_limit=1,
                        qa_limit=1,
                        sample_ids=['conv-1'],
                        category_filter=[],
                        retrieval_k=5,
                        ingestion_mode='turns',
                        answer_mode='extractive',
                        generator_model=None,
                        evidence_recall_k=[1, 5],
                        persist_case_artifacts=True,
                        embeddings_provider='hash',
                        compare_retrieval_modes=True,
                    )
            finally:
                runtime_mod.settings.core_memory_demo_benchmark_root = old_bench_root
                runtime_mod.settings.core_memory_demo_artifacts_root = old_art_root
                runtime_mod.settings.locomo_ingest_path = old_ingest_path
                runtime_mod.settings.locomo_compare_paths_enabled = old_compare

        self.assertTrue(out['ok'])
        self.assertTrue(out['report']['config']['compare_retrieval_modes_requested'])
        self.assertTrue(out['report']['config']['compare_retrieval_modes_executed'])
        self.assertEqual('execute_trace_hydrate', out['report']['config']['retrieval_compare_target'])
        self.assertIn('retrieval_mode_comparison', out['report'])
        self.assertGreater(out['report']['retrieval_mode_comparison']['overall']['delta']['evidence_recall@5'], 0.0)

    def test_compare_paths_surfaces_ingest_failure_step(self):
        if runtime_mod is None:
            self.skipTest('pydantic_settings unavailable')
        fake_dataset_meta = {'dataset': {'selected_samples': 1, 'selected_qa_cases': 1, 'dataset_path': 'locomo.json'}}
        fake_cases = [{'qa_id': 'q1', 'sample_id': 'conv-1', 'category': 2, 'question': 'Q?', 'answer': 'A', 'evidence': ['D1:1']}]
        fake_samples = [{'sample_id': 'conv-1', 'sessions': []}]
        fake_gold = {'D1:1': {'dia_ids': ['D1:1']}}
        main_report = {'cases': [{'qa_id': 'q1', 'sample_id': 'conv-1', 'category': 2, 'answer_f1': 0.0, 'evidence_recall': {'recall@5': 0.0, 'hit_any': False, 'mrr': 0.0}, 'status': 'ok'}], 'completed': 1, 'failed': 0}

        with tempfile.TemporaryDirectory() as td:
            old_bench_root = runtime_mod.settings.core_memory_demo_benchmark_root
            old_art_root = runtime_mod.settings.core_memory_demo_artifacts_root
            old_ingest_path = runtime_mod.settings.locomo_ingest_path
            old_compare = runtime_mod.settings.locomo_compare_paths_enabled
            runtime_mod.settings.core_memory_demo_benchmark_root = td
            runtime_mod.settings.core_memory_demo_artifacts_root = td
            runtime_mod.settings.locomo_ingest_path = 'bead_direct'
            runtime_mod.settings.locomo_compare_paths_enabled = True
            try:
                with patch.object(runtime_mod, 'build_locomo_suite_metadata', return_value=(fake_dataset_meta, fake_cases, fake_samples, fake_gold)), \
                     patch.object(runtime_mod, 'ingest_locomo_samples', side_effect=[{'ingested_turns': 1, 'rows': [], 'turns_total': 1, 'ingested_count': 1, 'skipped_existing_count': 0}, RuntimeError('flush failed')]), \
                     patch.object(runtime_mod, 'run_locomo_retrieval_suite', side_effect=[main_report]), \
                     patch.object(runtime_mod, 'build_semantic_index', side_effect=[{'ok': True, 'backend': 'hash', 'entries': 1}]):
                    out = runtime_mod.run_benchmark(
                        semantic_mode_name='required',
                        root_mode='snapshot',
                        preload_from_demo=False,
                        preload_turns_max=5,
                        suite='locomo_mini',
                        sample_limit=1,
                        qa_limit=1,
                        sample_ids=['conv-1'],
                        category_filter=[],
                        retrieval_k=5,
                        ingestion_mode='turns',
                        answer_mode='llm',
                        generator_model=None,
                        evidence_recall_k=[1, 5],
                        persist_case_artifacts=True,
                        embeddings_provider='hash',
                    )
            finally:
                runtime_mod.settings.core_memory_demo_benchmark_root = old_bench_root
                runtime_mod.settings.core_memory_demo_artifacts_root = old_art_root
                runtime_mod.settings.locomo_ingest_path = old_ingest_path
                runtime_mod.settings.locomo_compare_paths_enabled = old_compare

        self.assertTrue(out['ok'])
        self.assertTrue(out['report']['config']['compare_paths_requested'])
        self.assertTrue(out['report']['config']['compare_paths_executed'])
        self.assertNotIn('comparison', out['report'])
        self.assertEqual('ingest_locomo_samples', out['report']['comparison_error']['step'])
        self.assertIn('flush failed', out['report']['comparison_error']['error'])

    def test_compare_paths_skips_large_runs_to_avoid_memory_spike(self):
        if runtime_mod is None:
            self.skipTest('pydantic_settings unavailable')
        fake_dataset_meta = {'dataset': {'selected_samples': 1, 'selected_qa_cases': 50, 'dataset_path': 'locomo.json'}}
        fake_cases = [
            {'qa_id': f'q{i}', 'sample_id': 'conv-1', 'category': 2, 'question': 'Q?', 'answer': 'A', 'evidence': ['D1:1']}
            for i in range(50)
        ]
        fake_samples = [{'sample_id': 'conv-1', 'sessions': []}]
        fake_gold = {'D1:1': {'dia_ids': ['D1:1']}}
        main_report = {
            'cases': [
                {'qa_id': f'q{i}', 'sample_id': 'conv-1', 'category': 2, 'answer_f1': 1.0, 'evidence_recall': {'recall@5': 1.0, 'hit_any': True, 'mrr': 1.0}, 'status': 'ok'}
                for i in range(50)
            ],
            'completed': 50,
            'failed': 0,
        }

        with tempfile.TemporaryDirectory() as td:
            old_bench_root = runtime_mod.settings.core_memory_demo_benchmark_root
            old_art_root = runtime_mod.settings.core_memory_demo_artifacts_root
            old_compare_limit = runtime_mod.settings.locomo_compare_paths_max_qa_cases
            runtime_mod.settings.core_memory_demo_benchmark_root = td
            runtime_mod.settings.core_memory_demo_artifacts_root = td
            runtime_mod.settings.locomo_compare_paths_max_qa_cases = 12
            try:
                with patch.object(runtime_mod, 'build_locomo_suite_metadata', return_value=(fake_dataset_meta, fake_cases, fake_samples, fake_gold)), \
                     patch.object(runtime_mod, 'ingest_locomo_samples', return_value={'ingested_turns': 1, 'rows': [], 'turns_total': 1, 'ingested_count': 1, 'skipped_existing_count': 0}) as ingest_mock, \
                     patch.object(runtime_mod, 'run_locomo_retrieval_suite', return_value=main_report), \
                     patch.object(runtime_mod, 'build_semantic_index', return_value={'ok': True, 'backend': 'hash', 'entries': 1}):
                    out = runtime_mod.run_benchmark(
                        semantic_mode_name='required',
                        root_mode='clean',
                        preload_from_demo=False,
                        preload_turns_max=5,
                        suite='locomo_retrieval',
                        qa_per_category={'1': 10, '2': 10, '3': 10, '4': 10, '5': 10},
                        retrieval_k=8,
                        ingestion_mode='turns',
                        answer_mode='none',
                        evidence_recall_k=[1, 5],
                        persist_case_artifacts=True,
                        embeddings_provider='hash',
                        compare_paths=True,
                    )
            finally:
                runtime_mod.settings.core_memory_demo_benchmark_root = old_bench_root
                runtime_mod.settings.core_memory_demo_artifacts_root = old_art_root
                runtime_mod.settings.locomo_compare_paths_max_qa_cases = old_compare_limit

        self.assertTrue(out['ok'])
        self.assertTrue(out['report']['config']['compare_paths_requested'])
        self.assertFalse(out['report']['config']['compare_paths_executed'])
        self.assertIn('qa_cases_exceeds_compare_limit:50>12', out['report']['config']['compare_paths_skipped_reason'])
        self.assertEqual(1, ingest_mock.call_count)


if __name__ == '__main__':
    unittest.main()
