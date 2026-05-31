"""Faithful LoCoMo methodology: proves the evidence-recall accuracy fix.

The demo historically scored evidence recall against dia_ids scraped off the
retrieval payload. Replay beads do not expose a per-turn dia_id as a metadata
field (the raw dia_id lives inside ``source_turn_ids``), so recall was
systematically undercounted. These tests pin the fix: an authoritative
``bead_id -> dia_id`` map is built from the bead index and used to recover the
dia_ids of retrieved beads, so recall is measured correctly.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.contracts import (
    BenchmarkConversation,
    BenchmarkLifecycleError,
    BenchmarkQA,
    BenchmarkShortcutFlags,
    BenchmarkTurn,
    assert_faithful_shortcuts,
)
from app.benchmarks import locomo_faithful


def _conversation() -> BenchmarkConversation:
    turns = [
        BenchmarkTurn(
            turn_id=f"locomo:s1:{dia}:0",
            speaker="Alice",
            role="user",
            content=f"utterance {dia}",
            metadata={"locomo_dia_id": dia},
        )
        for dia in ("D1:1", "D1:2", "D1:3", "D1:4")
    ]
    qa = [BenchmarkQA(qa_id="q1", question="when?", expected_answer="7 May 2023", gold_evidence=["D1:3", "D1:4"], category="2")]
    return BenchmarkConversation(
        benchmark_name="locomo",
        conversation_id="s1",
        session_id="locomo:s1:replay",
        turns=turns,
        qa_cases=qa,
        metadata={},
    )


def _write_index(root: Path, beads: dict) -> None:
    (root / ".beads").mkdir(parents=True, exist_ok=True)
    (root / ".beads" / "index.json").write_text(json.dumps({"beads": beads}), encoding="utf-8")


class TestDiaBeadMap(unittest.TestCase):
    def test_build_maps_source_turn_ids_to_dia(self):
        import tempfile

        conv = _conversation()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_index(root, {
                # One bead per turn; demo stores source_turn_ids=[turn_id, dia_id].
                "bead-a": {"id": "bead-a", "session_id": "locomo:s1:replay", "source_turn_ids": ["locomo:s1:D1:3:0", "D1:3"]},
                "bead-b": {"id": "bead-b", "session_id": "locomo:s1:replay", "source_turn_ids": ["locomo:s1:D1:4:0", "D1:4"]},
                # Foreign-session bead must be ignored.
                "bead-x": {"id": "bead-x", "session_id": "other", "source_turn_ids": ["locomo:s1:D1:1:0"]},
            })
            mapping = locomo_faithful.build_bead_to_dias(root, conv)
        self.assertEqual(["D1:3"], mapping["bead-a"])
        self.assertEqual(["D1:4"], mapping["bead-b"])
        self.assertNotIn("bead-x", mapping)

    def test_compacted_bead_maps_to_all_absorbed_dias(self):
        import tempfile

        conv = _conversation()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_index(root, {
                "compacted": {
                    "id": "compacted",
                    "session_id": "locomo:s1:replay",
                    "source_turn_ids": ["locomo:s1:D1:3:0", "locomo:s1:D1:4:0"],
                },
            })
            mapping = locomo_faithful.build_bead_to_dias(root, conv)
        self.assertEqual(["D1:3", "D1:4"], mapping["compacted"])


class TestRecallRecovery(unittest.TestCase):
    def test_bead_only_rows_recover_recall(self):
        # Retrieval rows carry ONLY a bead_id (the failure mode). Without the map,
        # dia_ids are empty and recall is zero; with the map, recall is correct.
        rows = [
            {"rank": 1, "bead_id": "bead-foo", "dia_ids": []},
            {"rank": 2, "bead_id": "bead-a", "dia_ids": []},   # -> D1:3 (rank 2)
            {"rank": 3, "bead_id": "bead-b", "dia_ids": []},   # -> D1:4 (rank 3)
        ]
        bead_to_dias = {"bead-a": ["D1:3"], "bead-b": ["D1:4"]}

        # Old behaviour (no map): nothing recovered -> recall 0.
        empty = locomo_faithful.ranked_dia_ids_for_rows(rows, {})
        self.assertEqual([], empty)
        zero = locomo_faithful.compute_evidence_recall(gold_evidence=["D1:3", "D1:4"], retrieved=empty, ks=[1, 3, 5])
        self.assertEqual(0.0, zero["recall@5"])
        self.assertFalse(zero["hit_any"])

        # Fixed behaviour: rows backfill from the map -> recall recovered. The
        # unmapped foreign row (bead-foo) is dropped, so the flat dia list
        # compresses to the two gold hits (upstream-faithful semantics).
        ranked = locomo_faithful.ranked_dia_ids_for_rows(rows, bead_to_dias)
        self.assertEqual(["D1:3", "D1:4"], ranked)
        fixed = locomo_faithful.compute_evidence_recall(gold_evidence=["D1:3", "D1:4"], retrieved=ranked, ks=[1, 3, 5])
        self.assertEqual(1.0, fixed["recall@5"])
        self.assertEqual(0.5, fixed["recall@1"])  # one of two gold dia_ids at rank 1
        self.assertTrue(fixed["hit_any"])
        self.assertAlmostEqual(1.0, fixed["mrr"])

    def test_vacuous_recall_when_no_gold(self):
        out = locomo_faithful.compute_evidence_recall(gold_evidence=[], retrieved=[], ks=[1, 5])
        self.assertTrue(out["vacuous"])
        self.assertEqual(1.0, out["recall@5"])


class TestScoringConventions(unittest.TestCase):
    def test_multihop_uses_max_over_subanswers(self):
        # "Paris" matches the first sub-answer exactly -> max sub-answer F1 is high.
        score = locomo_faithful.score_answer(category=1, prediction="Paris", answer="Paris, Rome")
        self.assertEqual(1.0, score)

    def test_category_three_strips_at_semicolon(self):
        self.assertEqual(1.0, locomo_faithful.score_answer(category=3, prediction="7 May 2023", answer="7 May 2023; evening"))

    def test_category_five_is_excluded_neutral(self):
        # Upstream excludes cat 5; score_answer returns neutral 1.0 and callers mark excluded.
        self.assertEqual(1.0, locomo_faithful.score_answer(category=5, prediction="anything", answer="whatever"))
        self.assertFalse(locomo_faithful.is_official_category(5))
        self.assertTrue(locomo_faithful.is_official_category(2))


class TestFaithfulGate(unittest.TestCase):
    def test_faithful_flags_pass(self):
        assert_faithful_shortcuts(BenchmarkShortcutFlags())  # no raise
        self.assertTrue(BenchmarkShortcutFlags().is_faithful())

    def test_any_shortcut_raises(self):
        flags = BenchmarkShortcutFlags(oracle_gold_used=True)
        self.assertFalse(flags.is_faithful())
        with self.assertRaises(BenchmarkLifecycleError):
            assert_faithful_shortcuts(flags)

    def test_is_faithful_in_to_dict_does_not_count_as_shortcut(self):
        # is_faithful is reported in to_dict() but must not register as an enabled shortcut.
        self.assertFalse(BenchmarkShortcutFlags().any_enabled())
        self.assertIn("is_faithful", BenchmarkShortcutFlags().to_dict())


if __name__ == "__main__":
    unittest.main()
