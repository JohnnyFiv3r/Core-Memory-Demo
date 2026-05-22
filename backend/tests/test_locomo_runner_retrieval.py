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

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib, patch("app.benchmarks.locomo_runner.trace_request") as tr:
            mt.execute.return_value = fake_execute
            ib.return_value = fake_bead
            tr.return_value = {"results": [], "chains": [], "grounding": {}, "warnings": []}
            out = run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=8)

        self.assertEqual("ok", out["status"])
        self.assertEqual(1.0, out["evidence_recall"]["recall@1"])
        self.assertEqual(1.0, out["evidence_recall"]["mrr"])
        self.assertEqual(["D1:3"], out["retrieved"][0]["dia_ids"])

    def test_retrieval_projects_locomo_source_turn_ids(self):
        qa = {
            "qa_id": "conv-1:q0001",
            "question": "When did Caroline go to the support group?",
            "answer": "7 May 2023",
            "category": 2,
            "evidence": ["D1:3"],
        }

        fake_execute = {
            "results": [
                {"bead_id": "bead-1", "title": "turn", "snippet": "support group", "score": 0.91, "source_surface": "archive"}
            ],
            "warnings": [],
            "backend": "semantic",
        }
        fake_bead = {
            "id": "bead-1",
            "detail": "Caroline went to the support group on 7 May 2023",
            "source_turn_ids": ["locomo:conv-1:D1:3"],
            "metadata": {},
        }

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib, patch("app.benchmarks.locomo_runner.trace_request") as tr:
            mt.execute.return_value = fake_execute
            ib.return_value = fake_bead
            tr.return_value = {"results": [], "chains": [], "grounding": {}, "warnings": []}
            out = run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=8)

        self.assertEqual("ok", out["status"])
        self.assertEqual(["D1:3"], out["retrieved"][0]["dia_ids"])
        self.assertEqual("conv-1", out["retrieved"][0]["sample_id"])
        self.assertEqual(1.0, out["evidence_recall"]["recall@1"])

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

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib, patch("app.benchmarks.locomo_runner.trace_request") as tr:
            mt.execute.return_value = fake_execute
            ib.return_value = {}
            tr.return_value = {"results": [], "chains": [], "grounding": {}, "warnings": []}
            run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=8)

        req = mt.execute.call_args.args[0]
        facets = req.get("facets") or {}
        self.assertEqual("project", (facets.get("scope") or ""))
        self.assertEqual("conv-1", ((facets.get("metadata") or {}).get("sample_id") or ""))
        self.assertNotIn("session_id", facets.get("metadata") or {})
        must_terms = list(facets.get("must_terms") or [])
        self.assertNotIn("conv-1", must_terms)
        self.assertNotIn("caroline", [str(x).lower() for x in must_terms])
        self.assertTrue(any("7 may 2023" == str(x).lower() for x in must_terms))

    def test_retrieval_request_includes_session_hints(self):
        qa = {
            "qa_id": "conv-1:q0003",
            "question": "What happened in session 3 after Caroline moved?",
            "answer": "",
            "category": 2,
            "evidence": [],
        }

        fake_execute = {
            "results": [],
            "warnings": [],
            "backend": "lexical",
        }

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib, patch("app.benchmarks.locomo_runner.trace_request") as tr:
            mt.execute.return_value = fake_execute
            ib.return_value = {}
            tr.return_value = {"results": [], "chains": [], "grounding": {}, "warnings": []}
            run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=8)

        req = mt.execute.call_args.args[0]
        facets = req.get("facets") or {}
        must_terms = list(facets.get("must_terms") or [])
        self.assertEqual("3", str(((facets.get("metadata") or {}).get("session_index") or "")))
        self.assertIn("session_index=3", must_terms)
        self.assertNotIn("after", [str(x).lower() for x in must_terms])

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

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib, patch("app.benchmarks.locomo_runner.trace_request") as tr:
            mt.execute.return_value = fake_execute
            ib.side_effect = fake_inspect_bead
            tr.return_value = {"results": [], "chains": [], "grounding": {}, "warnings": []}
            out = run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=8)

        self.assertEqual("ok", out["status"])
        self.assertEqual("bead-right", out["retrieved"][0]["bead_id"])
        self.assertEqual(["D1:3"], out["retrieved"][0]["dia_ids"])
        self.assertNotIn("bead-wrong", [str(r.get("bead_id") or "") for r in out["retrieved"]])
        self.assertGreaterEqual(float(out["retrieved"][0].get("score") or 0.0), 0.0)

    def test_retrieval_filters_claim_state_answer_artifacts(self):
        qa = {
            "qa_id": "conv-1:q0005",
            "question": "What kind of interests do Caroline and Melanie share?",
            "answer": "painting",
            "category": 1,
            "evidence": ["D1:3"],
        }
        fake_execute = {
            "results": [
                {
                    "bead_id": "bead-answer-json",
                    "title": "prior answer",
                    "snippet": '{"answer":"prior benchmark answer","used_dia_ids":["D9:9"]}',
                    "score": 0.99,
                    "source_surface": "claim_state",
                    "dia_ids": ["abc123"],
                },
                {
                    "bead_id": "bead-turn",
                    "title": "real turn",
                    "snippet": "Caroline and Melanie both painted sunsets",
                    "score": 0.5,
                    "source_surface": "session",
                },
            ],
            "warnings": ["semantic_index_stale"],
            "backend": "semantic",
        }

        def fake_inspect_bead(*, root, bead_id):
            if bead_id == "bead-turn":
                return {
                    "id": "bead-turn",
                    "detail": "Caroline and Melanie both painted sunsets",
                    "source_turn_ids": ["locomo:conv-1:D1:3", "D1:3"],
                    "metadata": {"sample_id": "conv-1", "dia_ids": ["D1:3"]},
                }
            return {"id": "bead-answer-json", "detail": "prior benchmark answer", "metadata": {}}

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib, patch("app.benchmarks.locomo_runner.trace_request") as tr:
            mt.execute.return_value = fake_execute
            ib.side_effect = fake_inspect_bead
            tr.return_value = {"results": [], "chains": [], "grounding": {}, "warnings": []}
            out = run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=8)

        self.assertEqual(["bead-turn"], [str(r.get("bead_id") or "") for r in out["retrieved"]])
        self.assertEqual(1.0, out["evidence_recall"]["recall@1"])

    def test_retrieval_case_expands_with_causal_trace(self):
        qa = {
            "qa_id": "conv-1:q0004",
            "question": "Why did Caroline leave the support group?",
            "answer": "",
            "category": 2,
            "evidence": ["D1:3", "D1:4"],
        }

        fake_execute = {
            "results": [
                {
                    "bead_id": "bead-anchor",
                    "title": "Anchor",
                    "snippet": "Caroline mentioned the support group",
                    "score": 0.9,
                    "source_surface": "session_bead",
                }
            ],
            "warnings": [],
            "backend": "lexical",
        }

        def fake_inspect_bead(*, root, bead_id):
            if bead_id == "bead-trace":
                return {
                    "id": "bead-trace",
                    "detail": "Caroline left because the group reminded her of a painful event",
                    "source_turn_ids": ["D1:4"],
                    "metadata": {
                        "sample_id": "conv-1",
                        "session_index": 1,
                        "speaker": "Caroline",
                        "session_date_time": "7 May 2023",
                        "dia_id": "D1:4",
                    },
                }
            return {
                "id": "bead-anchor",
                "detail": "Caroline mentioned the support group",
                "source_turn_ids": ["D1:3"],
                "metadata": {
                    "sample_id": "conv-1",
                    "session_index": 1,
                    "speaker": "Caroline",
                    "session_date_time": "7 May 2023",
                    "dia_id": "D1:3",
                },
            }

        fake_trace = {
            "results": [
                {
                    "bead_id": "bead-trace",
                    "title": "Cause bead",
                    "snippet": "The group reminded her of a painful event",
                    "score": 0.85,
                    "source_surface": "session_bead",
                }
            ],
            "chains": [{"path": [{"bead_id": "bead-anchor"}, {"bead_id": "bead-trace"}], "score": 0.8}],
            "grounding": {"achieved": True, "level": "partial"},
            "warnings": [],
        }

        with patch("app.benchmarks.locomo_runner.memory_tools") as mt, patch("app.benchmarks.locomo_runner.inspect_bead") as ib, patch("app.benchmarks.locomo_runner.trace_request") as tr:
            mt.execute.return_value = fake_execute
            ib.side_effect = fake_inspect_bead
            tr.return_value = fake_trace
            out = run_locomo_retrieval_case(root="/tmp/fake", sample_id="conv-1", qa=qa, retrieval_k=5)

        self.assertEqual("ok", out["status"])
        self.assertTrue(out["trace"]["used"])
        self.assertEqual(["bead-anchor"], out["trace"]["anchor_ids"])
        bead_ids = [str(r.get("bead_id") or "") for r in out["retrieved"]]
        self.assertIn("bead-anchor", bead_ids)
        self.assertIn("bead-trace", bead_ids)
        self.assertTrue(out["trace"]["chains"])


if __name__ == "__main__":
    unittest.main()
