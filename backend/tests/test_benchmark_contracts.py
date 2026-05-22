import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.contracts import (  # noqa: E402
    BenchmarkLifecycleError,
    BenchmarkShortcutFlags,
    assert_lifecycle_faithful_mode,
)
from app.benchmarks.locomo_loader import LocomoLoaderError, locomo_samples_to_benchmark_conversations  # noqa: E402


class TestBenchmarkContracts(unittest.TestCase):
    def test_faithful_mode_rejects_shortcut_flags(self):
        with self.assertRaisesRegex(BenchmarkLifecycleError, "synthetic_crawler_updates"):
            assert_lifecycle_faithful_mode(
                dataset_mode="locomo_native_lifecycle",
                shortcut_flags=BenchmarkShortcutFlags(synthetic_crawler_updates=True),
            )

    def test_non_faithful_mode_allows_fixture_shortcuts(self):
        assert_lifecycle_faithful_mode(
            dataset_mode="fixture_smoke",
            shortcut_flags=BenchmarkShortcutFlags(synthetic_crawler_updates=True, bead_direct_ingest=True),
        )

    def test_locomo_adapter_outputs_sample_scoped_contract(self):
        samples = [
            {
                "sample_id": "conv-1",
                "speaker_a": "A",
                "speaker_b": "B",
                "sessions": [
                    {
                        "session_index": 1,
                        "date_time": "1 Jan 2024",
                        "turns": [
                            {
                                "dia_id": "D1:1",
                                "speaker": "A",
                                "text": "hi",
                                "turn_index": 1,
                                "session_index": 1,
                            }
                        ],
                    }
                ],
                "qa": [
                    {
                        "qa_id": "conv-1:q0001",
                        "question": "Who said hi?",
                        "answer": "A",
                        "category": 2,
                        "evidence": ["D1:1"],
                    }
                ],
            }
        ]

        conversations = locomo_samples_to_benchmark_conversations(samples)

        self.assertEqual(1, len(conversations))
        conv = conversations[0]
        self.assertEqual("locomo", conv.benchmark_name)
        self.assertEqual("locomo:conv-1", conv.conversation_id)
        self.assertEqual("bench:locomo:conv-1:replay", conv.session_id)
        self.assertEqual("locomo:conv-1:D1:1:1", conv.turns[0].turn_id)
        self.assertEqual("other", conv.turns[0].role)
        self.assertEqual("locomo:conv-1:q0001", conv.qa_cases[0].qa_id)
        self.assertEqual(["D1:1"], conv.qa_cases[0].gold_evidence)
        self.assertEqual(("locomo_category_2",), conv.qa_cases[0].bucket_labels)

    def test_locomo_adapter_detects_duplicate_sample_scoped_turn_ids(self):
        samples = [
            {
                "sample_id": "conv-1",
                "sessions": [
                    {
                        "session_index": 1,
                        "turns": [
                            {"dia_id": "D1:1", "speaker": "A", "text": "first", "turn_index": 1},
                            {"dia_id": "D1:1", "speaker": "B", "text": "duplicate", "turn_index": 1},
                        ],
                    }
                ],
                "qa": [],
            }
        ]
        with self.assertRaisesRegex(LocomoLoaderError, "locomo_duplicate_turn_id"):
            locomo_samples_to_benchmark_conversations(samples)


if __name__ == "__main__":
    unittest.main()
