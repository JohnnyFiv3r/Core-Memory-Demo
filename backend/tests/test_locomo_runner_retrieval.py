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

    def test_retrieval_request_includes_general_facets(self):
        qa = {
            "qa_id": "conv-1:q0000",
            "question": "When did Caroline go to the support group on 7 May 2023?",
            "answer": "7 May 2023",
            "category": 2,
            "evidence": ["D1:3"],
        }

        fake_execute = {
            "results": [],
            "warnings": [],
            "backend": "lexical",
        }

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib:
            mt.execute.return_value = fake_execute
            ib.return_value = {}
            run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=8)

        req = mt.execute.call_args.args[0]
        self.assertEqual("project", ((req.get("facets") or {}).get("scope") or ""))
        must_terms = list((req.get("facets") or {}).get("must_terms") or [])
        self.assertIn("conv-1", must_terms)
        self.assertIn("caroline", [str(x).lower() for x in must_terms])
        self.assertTrue(any("7 may 2023" == str(x).lower() for x in must_terms))

    def test_retrieval_case_reranks_same_sample_and_speaker_cues(self):
        qa = {
            "qa_id": "conv-1:q0002",
            "question": "When did Caroline go to the support group?",
            "answer": "7 May 2023",
            "category": 2,
            "evidence": ["D1:3"],
        }

        fake_execute = {
            "results": [
                {
                    "bead_id": "bead-wrong",
                    "title": "Bob at session 1, turn 1",
                    "snippet": "Bob mentioned a support group once",
                    "score": 0.95,
                    "source_surface": "session_bead",
                },
                {
                    "bead_id": "bead-right",
                    "title": "Caroline at session 1, turn 3",
                    "snippet": "Caroline went to the support group on 7 May 2023",
                    "score": 0.72,
                    "source_surface": "session_bead",
                },
            ],
            "warnings": [],
            "backend": "lexical",
        }

        def fake_inspect_bead(*, root, bead_id):
            if bead_id == "bead-right":
                return {
                    "id": "bead-right",
                    "detail": "Caroline went to the support group on 7 May 2023",
                    "source_turn_ids": ["D1:3"],
                    "metadata": {
                        "sample_id": "conv-1",
                        "session_index": 1,
                        "speaker": "Caroline",
                        "session_date_time": "7 May 2023",
                        "dia_id": "D1:3",
                    },
                }
            return {
                "id": "bead-wrong",
                "detail": "Bob mentioned a support group once",
                "source_turn_ids": ["D9:9"],
                "metadata": {
                    "sample_id": "conv-9",
                    "session_index": 1,
                    "speaker": "Bob",
                    "session_date_time": "1 Jan 2020",
                    "dia_id": "D9:9",
                },
            }

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib:
            mt.execute.return_value = fake_execute
            ib.side_effect = fake_inspect_bead
            out = run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=8)

        self.assertEqual("ok", out["status"])
        self.assertEqual("bead-right", out["retrieved"][0]["bead_id"])
        self.assertEqual(["D1:3"], out["retrieved"][0]["dia_ids"])
        self.assertGreater(float(out["retrieved"][0].get("locomo_score") or 0.0), float(out["retrieved"][1].get("locomo_score") or 0.0))
        self.assertGreaterEqual(float(out["retrieved"][0].get("score") or 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
