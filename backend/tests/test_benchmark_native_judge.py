import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.runtime import benchmark_enrich_mode  # noqa: E402
from app.benchmarks.contracts import BenchmarkConversation, BenchmarkTurn  # noqa: E402
from app.benchmarks.lifecycle_runner import (  # noqa: E402
    _benchmark_judge_mode_active,
    _locomo_replay_metadata,
)

_JUDGE_KEYS = (
    "CORE_MEMORY_DEMO_BENCHMARK_ENRICH_MODE",
    "CORE_MEMORY_BEAD_JUDGE_FALLBACK",
    "CORE_MEMORY_BEAD_FIELD_JUDGE_MODE",
)


def _clear():
    for k in _JUDGE_KEYS:
        os.environ.pop(k, None)


def _conv():
    turn = BenchmarkTurn(
        turn_id="locomo:conv-1:D1:1",
        speaker="Caroline",
        role="other",
        content="I went to a LGBTQ support group yesterday and it was powerful.",
        metadata={"locomo_dia_id": "D1:1", "locomo_speaker": "Caroline"},
    )
    return BenchmarkConversation(
        benchmark_name="locomo",
        conversation_id="conv-1",
        session_id="bench:locomo:conv-1:replay",
        turns=[turn],
        qa_cases=[],
    ), turn


class TestBenchmarkEnrichMode(unittest.TestCase):
    def setUp(self):
        _clear()
        self.addCleanup(_clear)

    def test_judge_mode_sets_and_restores_env(self):
        self.assertFalse(_benchmark_judge_mode_active())
        with benchmark_enrich_mode("judge"):
            self.assertTrue(_benchmark_judge_mode_active())
            self.assertEqual("judge", os.environ["CORE_MEMORY_DEMO_BENCHMARK_ENRICH_MODE"])
            self.assertEqual("1", os.environ["CORE_MEMORY_BEAD_JUDGE_FALLBACK"])
            self.assertEqual("llm", os.environ["CORE_MEMORY_BEAD_FIELD_JUDGE_MODE"])
        for k in _JUDGE_KEYS:
            self.assertIsNone(os.environ.get(k))

    def test_deterministic_mode_is_noop(self):
        with benchmark_enrich_mode("deterministic"):
            self.assertFalse(_benchmark_judge_mode_active())
            for k in _JUDGE_KEYS:
                self.assertIsNone(os.environ.get(k))

    def test_judge_mode_omits_crawler_updates(self):
        conv, turn = _conv()
        with benchmark_enrich_mode("judge"):
            md = _locomo_replay_metadata(root="/tmp/does-not-matter", conversation=conv, turn=turn)
        # No agent crawler_updates → engine runs the native judge.
        self.assertNotIn("crawler_updates", md)
        self.assertEqual("native_judge", md.get("_crawler_updates_source"))
        self.assertEqual("locomo", md.get("replay_source"))


if __name__ == "__main__":
    unittest.main()
