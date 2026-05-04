import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_suite import build_locomo_comparison, write_locomo_run_artifacts


class TestLocomoSuiteArtifacts(unittest.TestCase):
    def test_write_locomo_run_artifacts_writes_expected_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            from app.benchmarks import locomo_suite as suite_mod
            old_root = suite_mod.settings.core_memory_demo_artifacts_root
            suite_mod.settings.core_memory_demo_artifacts_root = str(root)
            try:
                comparison = build_locomo_comparison(
                    left_label='bead_direct',
                    left_report={'cases': [{'qa_id': 'q1', 'category': 2, 'sample_id': 'conv-1', 'answer_f1': 0.0, 'evidence_recall': {'recall@5': 0.0, 'hit_any': False, 'mrr': 0.0}}]},
                    right_label='canonical_replay',
                    right_report={'cases': [{'qa_id': 'q1', 'category': 2, 'sample_id': 'conv-1', 'answer_f1': 1.0, 'evidence_recall': {'recall@5': 1.0, 'hit_any': True, 'mrr': 1.0}}]},
                )
                out = write_locomo_run_artifacts(
                    run_id="bench-test123",
                    summary={"suite": "locomo_mini", "answer_f1_mean": 0.5},
                    report={"cases": [{"qa_id": "q1", "status": "ok"}, {"qa_id": "q2", "status": "error"}]},
                    config={"suite": "locomo_mini"},
                    dataset_meta={"repo_commit": "abc1234"},
                    ingestion_meta={"ingested_turns": 12},
                    comparison=comparison,
                )
            finally:
                suite_mod.settings.core_memory_demo_artifacts_root = old_root

            self.assertTrue(Path(out["summary"]).exists())
            self.assertTrue(Path(out["report"]).exists())
            self.assertTrue(Path(out["config"]).exists())
            self.assertTrue(Path(out["dataset_meta"]).exists())
            self.assertTrue(Path(out["ingestion_meta"]).exists())
            self.assertTrue(Path(out["cases"]).exists())
            self.assertTrue(Path(out["failures"]).exists())
            self.assertTrue(Path(out["comparison"]).exists())

            summary = json.loads(Path(out["summary"]).read_text(encoding="utf-8"))
            self.assertEqual("locomo_mini", summary["suite"])

            failures = Path(out["failures"]).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(1, len(failures))
            self.assertIn('"qa_id": "q2"', failures[0])

            comparison = json.loads(Path(out['comparison']).read_text(encoding='utf-8'))
            self.assertEqual('bead_direct', comparison['left'])
            self.assertEqual('canonical_replay', comparison['right'])
            self.assertGreater(comparison['overall']['delta']['evidence_recall@5'], 0.0)


if __name__ == "__main__":
    unittest.main()
