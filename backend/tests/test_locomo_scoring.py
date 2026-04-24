import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_scoring import compute_evidence_recall, score_answer


class TestLocomoScoring(unittest.TestCase):
    def test_token_f1_exact(self):
        self.assertEqual(1.0, score_answer(category=2, prediction="7 May 2023", answer="7 May 2023"))

    def test_token_f1_partial(self):
        self.assertGreater(score_answer(category=2, prediction="May 2023", answer="7 May 2023"), 0.0)

    def test_multihop_category(self):
        self.assertGreater(score_answer(category=1, prediction="Paris, Berlin", answer="Paris, Rome"), 0.4)

    def test_temporal_semicolon_behavior(self):
        self.assertEqual(1.0, score_answer(category=3, prediction="7 May 2023", answer="7 May 2023; in the evening"))

    def test_adversarial_no_info_behavior(self):
        self.assertEqual(1.0, score_answer(category=5, prediction="No information available", answer="irrelevant"))

    def test_evidence_recall(self):
        out = compute_evidence_recall(
            gold_evidence=["D1:3", "D1:4"],
            retrieved=[
                {"dia_ids": ["D9:1"]},
                {"dia_ids": ["D1:4"]},
                {"dia_ids": ["D1:3"]},
            ],
            ks=[1, 3, 5],
        )
        self.assertFalse(out["hit_any"] is False)
        self.assertEqual(0.0, out["recall@1"])
        self.assertEqual(1.0, out["recall@3"])
        self.assertEqual(0.5, out["mrr"])


if __name__ == "__main__":
    unittest.main()
