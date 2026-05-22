import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "Core-Memory"))

from app.core import runtime as runtime_mod  # noqa: E402


class TestLocomoLifecycleRuntime(unittest.TestCase):
    def test_run_benchmark_routes_native_lifecycle_suite(self):
        dataset_meta = {
            "suite": "locomo_native_lifecycle",
            "source": "locomo_dataset",
            "dataset": {
                "selected_samples": 1,
                "selected_qa_cases": 1,
                "dataset_path": "fake-locomo.json",
                "repo_commit": "abc1234",
            },
        }
        selected_cases = [{"qa_id": "conv-1:q0001", "sample_id": "conv-1", "question": "q"}]
        selected_samples = [{"sample_id": "conv-1", "sessions": [], "qa": []}]
        lifecycle_report = {
            "ok": True,
            "completed": 1,
            "lifecycle": {
                "dataset_mode": "locomo_native_lifecycle",
                "lifecycle_faithful": True,
                "turns_replayed": 2,
                "capture_hook_calls": 2,
                "qa_cases": 1,
                "retrieval_efforts_per_qa": ["low", "medium", "high"],
            },
            "shortcut_guards": {
                "synthetic_crawler_updates": False,
                "synthetic_temporal_edges": False,
                "bead_direct_ingest": False,
                "oracle_gold_used": False,
                "benchmark_aware_answer_prompt": False,
            },
            "cases": [
                {
                    "qa_id": "locomo:conv-1:q0001",
                    "conversation_id": "locomo:conv-1",
                    "question": "q",
                    "expected_answer": "gold",
                    "category": "2",
                    "gold_evidence": ["D1:1"],
                    "retrieval_order": ["low", "medium", "high"],
                    "efforts": {
                        "high": {
                            "prediction": "gold",
                            "answer_f1": 1.0,
                            "retrieved": [{"bead_id": "b1", "dia_ids": ["D1:1"], "score": 0.9}],
                            "retrieved_count": 1,
                            "evidence_recall": {"hit_any": True, "mrr": 1.0, "recall@1": 1.0, "recall@3": 1.0, "recall@5": 1.0},
                        }
                    },
                }
            ],
        }

        with tempfile.TemporaryDirectory() as td, \
            patch.object(runtime_mod.settings, "core_memory_demo_benchmark_root", td), \
            patch.object(runtime_mod.settings, "core_memory_root", td), \
            patch.object(runtime_mod.settings, "core_memory_demo_artifacts_root", str(Path(td) / "artifacts")), \
            patch.object(runtime_mod, "build_locomo_suite_metadata", return_value=(dataset_meta, selected_cases, selected_samples)), \
            patch.object(runtime_mod, "run_locomo_lifecycle_suite", return_value=lifecycle_report) as lifecycle_mock, \
            patch.object(runtime_mod, "benchmark_store") as store_mock:
            store_mock.save_run.return_value = None
            out = runtime_mod.run_benchmark(
                semantic_mode_name="degraded_allowed",
                root_mode="clean",
                preload_from_demo=False,
                preload_turns_max=1,
                suite="locomo_native_lifecycle",
                qa_limit=1,
            )

        self.assertTrue(out["ok"])
        self.assertEqual("locomo_native_lifecycle", out["suite"])
        self.assertEqual("locomo_native_lifecycle", out["report"]["config"]["dataset_mode"])
        self.assertEqual(["low", "medium", "high"], out["report"]["config"]["retrieval_efforts"])
        self.assertTrue(out["report"]["lifecycle"]["lifecycle_faithful"])
        self.assertEqual(1, len(out["report"]["benchmark_table"]))
        self.assertEqual(1.0, out["report"]["benchmark_table"][0]["answer_f1"])
        self.assertTrue(out["report"]["benchmark_table"][0]["hit_any"])
        lifecycle_mock.assert_called_once()
        kwargs = lifecycle_mock.call_args.kwargs
        self.assertEqual(selected_samples, kwargs["samples"])
        self.assertEqual(selected_cases, kwargs["qa_cases"])


if __name__ == "__main__":
    unittest.main()
