import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestQaLiveSummary(unittest.TestCase):
    def test_extracts_question_answer_and_evidence(self):
        from app.benchmarks.contracts import BenchmarkQA
        from app.benchmarks.lifecycle_runner import _qa_live_summary

        qa = BenchmarkQA(qa_id="q1", question="what db?", expected_answer="postgres", category="2")
        qa_result = {
            "efforts": {
                "high": {
                    "result": {"answer": "PostgreSQL"},
                    "answer_f1": 0.83,
                    "retrieved": [
                        {"bead_id": "bead-1", "dia_ids": ["D1:3"], "snippet": "we chose postgres"},
                        {"bead_id": "", "dia_ids": []},
                    ],
                    "retrieved_dia_ids": ["D1:3"],
                }
            }
        }
        out = _qa_live_summary(qa, qa_result)
        self.assertEqual("what db?", out["question"])
        self.assertEqual("PostgreSQL", out["answer"])
        self.assertAlmostEqual(0.83, out["answer_f1"])
        self.assertEqual(["bead-1"], out["evidence_bead_ids"])
        self.assertEqual(1, len(out["evidence"]))
        self.assertEqual("D1:3", out["evidence"][0]["dia_ids"][0])


class TestBenchmarkRunState(unittest.TestCase):
    def test_no_runs_returns_inactive(self):
        from app.core import runtime as runtime_mod

        with tempfile.TemporaryDirectory() as td:
            with patch.object(runtime_mod.settings, "core_memory_demo_benchmark_root", str(Path(td) / "empty")):
                out = runtime_mod.inspect_benchmark_run_state_payload()
        self.assertTrue(out["ok"])
        self.assertFalse(out["active_run"])
        self.assertEqual([], out["beads"])

    def test_reads_newest_run_base(self):
        from app.core import runtime as runtime_mod

        with tempfile.TemporaryDirectory() as td:
            bench_root = Path(td) / "bench"
            base = bench_root / "run-123" / "base"
            (base / ".beads").mkdir(parents=True, exist_ok=True)
            (base / ".beads" / "index.json").write_text(json.dumps({"beads": {}}), encoding="utf-8")

            fake_state = {"memory": {"beads": [{"id": "b1", "title": "replayed turn"}], "associations": []}}
            with patch.object(runtime_mod.settings, "core_memory_demo_benchmark_root", str(bench_root)), \
                 patch.object(runtime_mod, "inspect_state", return_value=fake_state) as inspect_mock:
                out = runtime_mod.inspect_benchmark_run_state_payload()

        self.assertTrue(out["active_run"])
        self.assertEqual("run-123", out["run_id"])
        self.assertEqual("b1", out["beads"][0]["id"])
        # inspect_state must be pointed at the run's base root, not the demo root.
        _, kwargs = inspect_mock.call_args
        self.assertTrue(str(kwargs["root"]).endswith("run-123/base"))


class TestBenchmarkRunStateRoute(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        os.environ["CORE_MEMORY_ROOT"] = str(root / "core-memory")
        os.environ["CORE_MEMORY_DEMO_BENCHMARK_ROOT"] = str(root / "bench")
        os.environ["CORE_MEMORY_DEMO_ARTIFACTS_ROOT"] = str(root / "artifacts")
        os.environ["ALLOWED_ORIGIN"] = "http://localhost:5173"

    def tearDown(self):
        self._td.cleanup()

    def test_route_returns_inactive_when_no_runs(self):
        from fastapi.testclient import TestClient
        from app.main import app

        res = TestClient(app).get("/api/demo/benchmark/run-state")
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["active_run"])


if __name__ == "__main__":
    unittest.main()
