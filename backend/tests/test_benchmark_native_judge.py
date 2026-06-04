import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.runtime import benchmark_enrich_mode  # noqa: E402
from app.benchmarks.contracts import BenchmarkConversation, BenchmarkTurn  # noqa: E402
from app.benchmarks.lifecycle_runner import (  # noqa: E402
    _benchmark_judge_mode_active,
    _locomo_replay_metadata,
    set_benchmark_enrich_mode,
)

# The demo must NOT toggle these process-wide; the judge is enabled per-request
# via metadata["bead_judge"] (Core Memory #182). These names are asserted-absent.
_JUDGE_ENV = ("CORE_MEMORY_BEAD_JUDGE_FALLBACK", "CORE_MEMORY_BEAD_FIELD_JUDGE_MODE")


def _clear():
    for k in _JUDGE_ENV:
        os.environ.pop(k, None)
    set_benchmark_enrich_mode(None)


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

    def test_judge_mode_sets_threadlocal_and_never_touches_env(self):
        self.assertFalse(_benchmark_judge_mode_active())
        with benchmark_enrich_mode("judge"):
            self.assertTrue(_benchmark_judge_mode_active())
            # The directive is request-scoped (metadata), never process env.
            for k in _JUDGE_ENV:
                self.assertIsNone(os.environ.get(k))
        self.assertFalse(_benchmark_judge_mode_active())
        for k in _JUDGE_ENV:
            self.assertIsNone(os.environ.get(k))

    def test_deterministic_mode_is_noop(self):
        with benchmark_enrich_mode("deterministic"):
            self.assertFalse(_benchmark_judge_mode_active())
            for k in _JUDGE_ENV:
                self.assertIsNone(os.environ.get(k))

    def test_judge_mode_omits_crawler_updates_and_sets_directive(self):
        conv, turn = _conv()
        with benchmark_enrich_mode("judge"):
            md = _locomo_replay_metadata(root="/tmp/does-not-matter", conversation=conv, turn=turn)
        self.assertNotIn("crawler_updates", md)
        self.assertEqual("native_judge", md.get("_crawler_updates_source"))
        # Per-request directive (#182) enables the judge for this turn only.
        self.assertEqual("llm", md.get("bead_judge"))

    def test_mode_is_thread_scoped_not_global(self):
        # Codex regression: an in-flight judge run must NOT leak its mode into a
        # concurrent deterministic run on another thread (which would skip
        # crawler_updates and corrupt its replay).
        seen: dict[str, bool] = {}
        in_judge = threading.Event()
        release = threading.Event()

        def judge_thread():
            with benchmark_enrich_mode("judge"):
                in_judge.set()
                release.wait(timeout=5)
                seen["judge_thread_active"] = _benchmark_judge_mode_active()

        t = threading.Thread(target=judge_thread)
        t.start()
        self.assertTrue(in_judge.wait(timeout=5))
        # While the judge run is mid-flight on its thread, this (deterministic)
        # thread must still see judge mode as inactive.
        seen["other_thread_active"] = _benchmark_judge_mode_active()
        release.set()
        t.join(timeout=5)

        self.assertTrue(seen["judge_thread_active"])      # judge thread: active
        self.assertFalse(seen["other_thread_active"])     # other thread: NOT active


class TestJudgeEngagementGuard(unittest.TestCase):
    """Fail closed when enrich_mode='judge' but the judge authored no claims —
    the demo-side defense against a silent deterministic masquerade."""

    def test_judge_with_zero_claims_raises(self):
        from app.benchmarks.contracts import BenchmarkLifecycleError
        from app.benchmarks.lifecycle_runner import _assert_judge_engaged

        with self.assertRaises(BenchmarkLifecycleError) as ctx:
            _assert_judge_engaged(
                enrich_mode="judge",
                corpus={"beads": 175, "claims": 0},
                turns_replayed=175,
            )
        self.assertIn("judge_requested_but_not_engaged", str(ctx.exception))

    def test_judge_with_claims_passes(self):
        from app.benchmarks.lifecycle_runner import _assert_judge_engaged

        # Should not raise.
        _assert_judge_engaged(enrich_mode="judge", corpus={"claims": 42}, turns_replayed=175)

    def test_deterministic_with_zero_claims_is_fine(self):
        from app.benchmarks.lifecycle_runner import _assert_judge_engaged

        # Deterministic crawler legitimately produces 0 claims — must not raise.
        _assert_judge_engaged(enrich_mode="deterministic", corpus={"claims": 0}, turns_replayed=175)

    def test_empty_replay_does_not_false_alarm(self):
        from app.benchmarks.lifecycle_runner import _assert_judge_engaged

        _assert_judge_engaged(enrich_mode="judge", corpus={"claims": 0}, turns_replayed=0)


if __name__ == "__main__":
    unittest.main()
