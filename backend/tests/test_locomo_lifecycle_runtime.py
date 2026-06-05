import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "Core-Memory"))

from app.benchmarks.contracts import BenchmarkConversation, BenchmarkQA, BenchmarkTurn  # noqa: E402
from app.benchmarks.lifecycle_runner import _evidence_turn_refs, _filter_conversation_qa  # noqa: E402
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
                "turns_replayed": 0,
                "seeded_turns": 2,
                "qa_only_seeded": True,
                "capture_hook_calls": 0,
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
            "warnings": ["after_suite:no_claims_produced"],
            "corpus_after_replay": {"beads": 2, "associations": 0, "semantic_associations": 0, "entities": 0, "claims": 0},
            "corpus_after_pre_qa_flush": {"beads": 2, "associations": 0, "semantic_associations": 0, "entities": 0, "claims": 0},
            "corpus_after_qa": {"beads": 3, "associations": 0, "semantic_associations": 0, "entities": 0, "claims": 0},
            "corpus_after_suite": {"beads": 3, "associations": 0, "semantic_associations": 0, "entities": 0, "claims": 0},
            "corpus_snapshots": {"per_conversation": [{"conversation_id": "locomo:conv-1"}]},
            "scores": {
                "overall": {"answer_f1_mean": 1.0, "evidence_recall@5": 1.0},
                "by_effort": {"low": {}, "medium": {}, "high": {}},
                "accuracy_by_effort": {"low": 0.0, "medium": 0.0, "high": 1.0},
                "evidence_recall_by_effort": {"low": 0.0, "medium": 0.0, "high": 1.0},
                "latency_by_effort_ms": {"low": {}, "medium": {}, "high": {}},
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
            patch.object(runtime_mod.settings, "core_memory_demo_benchmark_root", str(Path(td) / "bench")), \
            patch.object(runtime_mod.settings, "core_memory_root", str(Path(td) / "seeded-live-root")), \
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
                qa_session_mode="isolated",
                seed_record={"seed_record_id": "seed-1", "seeded_turns": 2, "final_flush_count": 1},
            )

        self.assertTrue(out["ok"])
        self.assertEqual("locomo_native_lifecycle", out["suite"])
        self.assertEqual("locomo_native_lifecycle", out["report"]["config"]["dataset_mode"])
        self.assertEqual("isolated", out["report"]["config"]["qa_session_mode"])
        self.assertEqual(["low", "medium", "high"], out["report"]["config"]["retrieval_efforts"])
        self.assertTrue(out["report"]["lifecycle"]["lifecycle_faithful"])
        self.assertEqual(0, out["report"]["lifecycle"]["turns_replayed"])
        self.assertEqual(2, out["report"]["lifecycle"]["seeded_turns"])
        self.assertTrue(out["report"]["lifecycle"]["qa_only_seeded"])
        self.assertEqual(0, out["report"]["lifecycle"]["capture_hook_calls"])
        self.assertEqual(1, out["report"]["lifecycle"]["qa_cases"])
        self.assertEqual(["low", "medium", "high"], out["report"]["lifecycle"]["retrieval_efforts_per_qa"])
        self.assertFalse(any(bool(v) for v in out["report"]["shortcut_guards"].values()))
        self.assertIn("by_effort", out["report"]["scores"])
        for effort in ["low", "medium", "high"]:
            self.assertIn(effort, out["report"]["scores"].get("by_effort", {}))
        self.assertIn("corpus_after_replay", out["report"])
        self.assertIn("corpus_after_pre_qa_flush", out["report"])
        self.assertIn("corpus_after_qa", out["report"])
        self.assertIn("corpus_snapshots", out["report"])
        self.assertEqual(1, len(out["report"]["benchmark_table"]))
        self.assertEqual(1.0, out["report"]["benchmark_table"][0]["answer_f1"])
        self.assertTrue(out["report"]["benchmark_table"][0]["hit_any"])
        self.assertIn("after_suite:no_claims_produced", out["summary"]["warnings"])
        self.assertIn("after_suite:no_claims_produced", out["report"]["warnings"])
        self.assertEqual(2, out["report"]["corpus_after_replay"]["beads"])
        self.assertEqual(3, out["report"]["corpus_after_qa"]["beads"])
        self.assertEqual("locomo:conv-1", out["report"]["corpus_snapshots"]["per_conversation"][0]["conversation_id"])
        lifecycle_mock.assert_called_once()
        kwargs = lifecycle_mock.call_args.kwargs
        self.assertEqual(selected_samples, kwargs["samples"])
        self.assertEqual(selected_cases, kwargs["qa_cases"])
        self.assertEqual("isolated", kwargs["qa_session_mode"])
        self.assertTrue(kwargs["qa_only_seeded"])
        self.assertEqual(str(Path(td) / "seeded-live-root"), str(kwargs["root"]))
        self.assertEqual("eligible_seed_record_qa_only", out["report"]["ingestion"]["ingest_path"])
        self.assertEqual("seed-1", out["report"]["config"]["seed_record_id"])

    def test_bounded_replay_parses_whitespace_delimited_evidence_refs(self):
        turns = [
            BenchmarkTurn(
                turn_id=f"locomo:conv-1:D1:{idx}:{idx}",
                speaker="A",
                role="other",
                content=f"turn {idx}",
                metadata={"locomo_dia_id": f"D1:{idx}"},
            )
            for idx in range(1, 7)
        ]
        conv = BenchmarkConversation(
            benchmark_name="locomo",
            conversation_id="locomo:conv-1",
            session_id="bench:locomo:conv-1:replay",
            turns=turns,
            qa_cases=[
                BenchmarkQA(
                    qa_id="locomo:conv-1:q0001",
                    question="q",
                    gold_evidence=["D1:2 D1:4 D1:6"],
                    metadata={"locomo_sample_id": "conv-1"},
                )
            ],
        )

        bounded = _filter_conversation_qa(conv, {"locomo:conv-1:q0001"})

        self.assertEqual(["D1:2", "D1:4", "D1:6"], _evidence_turn_refs("D1:2 D1:4; D1:6"))
        self.assertEqual(6, len(bounded.turns))
        self.assertEqual(6, bounded.metadata["replay_turns_required"])
        self.assertFalse(bounded.metadata["missing_evidence_refs"])


if __name__ == "__main__":
    unittest.main()
