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
        self.assertTrue(_benchmark_judge_mode_active())
        with benchmark_enrich_mode("judge"):
            self.assertTrue(_benchmark_judge_mode_active())
            # The directive is request-scoped (metadata), never process env.
            for k in _JUDGE_ENV:
                self.assertIsNone(os.environ.get(k))
        self.assertTrue(_benchmark_judge_mode_active())
        for k in _JUDGE_ENV:
            self.assertIsNone(os.environ.get(k))

    def test_deterministic_mode_request_is_ignored_for_official_locomo(self):
        with benchmark_enrich_mode("deterministic"):
            self.assertTrue(_benchmark_judge_mode_active())
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

    def test_no_mode_state_can_leak_because_official_locomo_is_always_judge(self):
        self.assertIsNone(set_benchmark_enrich_mode("deterministic"))
        self.assertTrue(_benchmark_judge_mode_active())


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

    def test_deterministic_label_no_longer_bypasses_zero_claims_guard(self):
        from app.benchmarks.lifecycle_runner import _assert_judge_engaged

        with self.assertRaises(Exception):
            _assert_judge_engaged(enrich_mode="deterministic", corpus={"claims": 0}, turns_replayed=175)

    def test_empty_replay_does_not_false_alarm(self):
        from app.benchmarks.lifecycle_runner import _assert_judge_engaged

        _assert_judge_engaged(enrich_mode="judge", corpus={"claims": 0}, turns_replayed=0)


class TestMultiHopRetrievalK(unittest.TestCase):
    """Multi-hop (LoCoMo cat 1) questions get a wider retrieval window than the
    configured single-hop default, so co-required evidence isn't stranded past k."""

    def _req(self, category):
        from app.benchmarks.contracts import BenchmarkConversation, BenchmarkQA
        from app.benchmarks.lifecycle_runner import _qa_recall_request, MULTI_HOP_RETRIEVAL_K
        conv = BenchmarkConversation(
            benchmark_name="locomo", conversation_id="conv-26",
            session_id="bench:locomo:conv-26:replay", turns=[], qa_cases=[],
        )
        qa = BenchmarkQA(qa_id="locomo:conv-26:q1", question="q?", category=category)
        return _qa_recall_request(conversation=conv, qa=qa, k=8), MULTI_HOP_RETRIEVAL_K

    def test_multihop_category_widens_k(self):
        req, mh_k = self._req(1)
        self.assertEqual(mh_k, req["k"])  # bumped from 8 to the multi-hop floor

    def test_single_hop_category_keeps_configured_k(self):
        req, _ = self._req(2)
        self.assertEqual(8, req["k"])  # single-fact keeps the configured k

    def test_configured_k_above_floor_is_respected(self):
        from app.benchmarks.contracts import BenchmarkConversation, BenchmarkQA
        from app.benchmarks.lifecycle_runner import _qa_recall_request
        conv = BenchmarkConversation(
            benchmark_name="locomo", conversation_id="c", session_id="s", turns=[], qa_cases=[],
        )
        qa = BenchmarkQA(qa_id="q", question="q?", category=1)
        # A caller asking for k=20 on multi-hop must not be lowered to the floor.
        self.assertEqual(20, _qa_recall_request(conversation=conv, qa=qa, k=20)["k"])


if __name__ == "__main__":
    unittest.main()
