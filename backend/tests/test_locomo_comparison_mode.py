import importlib.util
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


if __name__ == '__main__':
    unittest.main()
