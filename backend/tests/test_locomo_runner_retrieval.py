import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_runner import run_locomo_retrieval_case


class TestLocomoRunnerRetrieval(unittest.TestCase):
    def test_retrieval_case_computes_evidence_metrics(self):
        qa = {
            "qa_id": "conv-1:q0001",
            "question": "When did Caroline go to the support group?",
            "answer": "7 May 2023",
            "category": 2,
            "evidence": ["D1:3"],
        }

        fake_execute = {
            "results": [
                {
                    "bead_id": "bead-1",
                    "title": "Alice at session 1, turn 3",
                    "snippet": "Caroline went to the support group on 7 May 2023",
                    "score": 0.91,
                    "source_surface": "session_bead",
                }
            ],
            "warnings": [],
            "backend": "lexical",
        }

        fake_bead = {
            "id": "bead-1",
            "detail": "Alice: Caroline went to the support group on 7 May 2023",
            "source_turn_ids": ["D1:3"],
            "metadata": {
                "sample_id": "conv-1",
                "session_index": 1,
                "speaker": "Alice",
                "session_date_time": "7 May 2023",
            },
        }

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib:
            mt.execute.return_value = fake_execute
            ib.return_value = fake_bead
            out = run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=8)

        self.assertEqual("ok", out["status"])
        self.assertEqual(1.0, out["evidence_recall"]["recall@1"])
        self.assertEqual(1.0, out["evidence_recall"]["mrr"])
        self.assertEqual(["D1:3"], out["retrieved"][0]["dia_ids"])


if __name__ == "__main__":
    unittest.main()
