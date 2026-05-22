import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestBenchmarkRoutesLocomo(unittest.TestCase):
    def test_active_benchmark_state_uses_active_job_not_stale_finished_snapshot(self):
        from app.routes import demo as demo_routes

        active_job = {
            "job_id": "job-live",
            "status": "running",
            "stage": "lifecycle_qa",
            "started_ms": 1000,
            "updated_ms": 2000,
            "kwargs": {
                "suite": "locomo_native_lifecycle",
                "root_mode": "snapshot",
                "semantic_mode_name": "required",
                "retrieval_k": 8,
                "qa_session_mode": "isolated",
            },
            "events": [
                {
                    "seq": 1,
                    "stage": "lifecycle_qa",
                    "qa_completed": 3,
                    "qa_total": 10,
                    "sample_id": "conv-1",
                    "qa_id": "locomo:conv-1:q0003",
                    "case_status": "retrieving",
                }
            ],
        }
        stale_snapshot = {
            "summary": {"run_id": "old-run", "status": "completed", "finished_at": "2026-01-01T00:00:00Z"},
            "report": {"config": {"suite": "locomo_qa"}},
        }

        summary, report = demo_routes._active_benchmark_state(active_job, stale_snapshot)

        self.assertEqual("", summary.get("run_id"))
        self.assertNotIn("finished_at", summary)
        self.assertEqual("running", summary.get("status"))
        self.assertEqual(3, summary.get("qa_completed"))
        self.assertEqual("locomo:conv-1:q0003", summary.get("qa_id"))
        self.assertEqual("job-live", report.get("active_job_id"))
        self.assertEqual("isolated", (report.get("config") or {}).get("qa_session_mode"))

    def test_locomo_suite_missing_dataset_fails_clearly(self):
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"fastapi unavailable: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["CORE_MEMORY_ROOT"] = str(root / "core-memory")
            os.environ["CORE_MEMORY_DEMO_BENCHMARK_ROOT"] = str(root / "core-memory-bench")
            os.environ["CORE_MEMORY_DEMO_ARTIFACTS_ROOT"] = str(root / "core-memory-artifacts")
            os.environ["CORE_MEMORY_LOCOMO_DATA_FILE"] = str(root / "missing-locomo.json")
            os.environ["ALLOWED_ORIGIN"] = "http://localhost:5173"

            from app.main import app

            c = TestClient(app)
            res = c.post("/api/benchmark-run", json={"suite": "locomo_qa", "root_mode": "clean"})
            self.assertEqual(200 if res.status_code == 200 else 400, res.status_code)
            data = res.json()
            self.assertFalse(bool(data.get("ok")))
            self.assertEqual("locomo_qa", data.get("suite"))
            self.assertIn("locomo_dataset_missing", list((data.get("summary") or {}).get("warnings") or []))

    def test_legacy_local_request_maps_to_fixture_smoke(self):
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"fastapi unavailable: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["CORE_MEMORY_ROOT"] = str(root / "core-memory")
            os.environ["CORE_MEMORY_DEMO_BENCHMARK_ROOT"] = str(root / "core-memory-bench")
            os.environ["CORE_MEMORY_DEMO_ARTIFACTS_ROOT"] = str(root / "core-memory-artifacts")
            os.environ["ALLOWED_ORIGIN"] = "http://localhost:5173"

            from app.main import app

            c = TestClient(app)
            res = c.post("/api/benchmark-run", json={"subset": "local", "limit": 1, "root_mode": "clean"})
            self.assertEqual(200, res.status_code)
            data = res.json()
            self.assertTrue(bool(data.get("ok")))
            self.assertEqual("fixture_smoke", data.get("suite"))
            self.assertEqual("fixture_smoke", (data.get("summary") or {}).get("suite"))
            self.assertIn("legacy_locomo_like_fixture", list((data.get("summary") or {}).get("warnings") or []))


if __name__ == "__main__":
    unittest.main()
