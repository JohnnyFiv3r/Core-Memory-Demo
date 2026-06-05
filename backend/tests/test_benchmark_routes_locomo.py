import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestBenchmarkRoutesLocomo(unittest.TestCase):
    def tearDown(self):
        try:
            from app.routes import demo as demo_routes
            demo_routes.SEED_JOBS.clear()
            demo_routes.SEED_STATUS.clear()
            demo_routes.SEED_STATUS.update({'active': False, 'kind': '', 'status': 'idle', 'updated_ms': 0, 'message': ''})
        except Exception:
            pass

    def test_locomo_seed_turn_bound_uses_selected_qa_evidence_prefix(self):
        from app.routes import demo as demo_routes

        samples = [
            {
                "sample_id": "conv-26",
                "sessions": [
                    {
                        "session_index": 1,
                        "turns": [
                            {"dia_id": f"D1:{idx}", "turn_index": idx, "text": f"turn {idx}"}
                            for idx in range(1, 421)
                        ],
                    }
                ],
            }
        ]
        selected_cases = [
            {"sample_id": "conv-26", "qa_id": "q1", "evidence": ["D1:3"]},
            {"sample_id": "conv-26", "qa_id": "q20", "evidence": ["D1:175"]},
        ]

        required, meta = demo_routes._locomo_seed_turn_bound_from_selection(samples, selected_cases)

        self.assertEqual(175, required)
        self.assertTrue(meta["bounded_by_selected_qa"])
        self.assertEqual(2, meta["selected_qa_cases"])
        self.assertEqual(420, meta["sample_bounds"][0]["turns_available"])
        self.assertEqual(175, meta["sample_bounds"][0]["turns_required"])

    def test_locomo_seed_route_derives_max_turns_from_qa_limit(self):
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"fastapi unavailable: {exc}")
        from app.main import app
        from app.routes import demo as demo_routes

        samples = [
            {
                "sample_id": "conv-26",
                "sessions": [
                    {
                        "session_index": 1,
                        "turns": [
                            {"dia_id": f"D1:{idx}", "turn_index": idx, "text": f"turn {idx}"}
                            for idx in range(1, 421)
                        ],
                    }
                ],
            }
        ]
        selected_cases = [{"sample_id": "conv-26", "qa_id": "q20", "evidence": ["D1:175"]}]
        captured: dict[str, object] = {}

        async def fake_run_seed_job(job_id, kwargs):
            captured["job_id"] = job_id
            captured["kwargs"] = dict(kwargs)

        def fake_create_task(coro):
            try:
                coro.close()
            except Exception:
                pass
            return object()

        with patch.object(demo_routes, "build_locomo_suite_metadata", return_value=({"dataset": {"selected_sample_ids": ["conv-26"]}}, selected_cases, samples, {})), \
             patch.object(demo_routes, "_run_seed_job", side_effect=fake_run_seed_job), \
             patch.object(demo_routes.asyncio, "create_task", side_effect=fake_create_task):
            res = TestClient(app).post("/api/locomo/replay", json={"sample_mode": "single", "sample_id": "conv-26", "qa_limit": 20})

        self.assertEqual(200, res.status_code)
        self.assertTrue(res.json().get("ok"))
        job_id = str(res.json().get("job_id") or "")
        self.assertTrue(job_id)
        row = demo_routes.SEED_JOBS[job_id]
        self.assertEqual(175, (row.get("seed_selection") or {}).get("effective_max_turns"))
        self.assertEqual(20, (row.get("seed_selection") or {}).get("qa_limit"))

    def test_locomo_seed_eligibility_requires_completed_flushed_seed(self):
        from app.routes import demo as demo_routes

        demo_routes.SEED_JOBS.clear()
        self.assertEqual("benchmark_requires_seeded_corpus", demo_routes._locomo_seed_eligibility(sample_ids=["conv-1"])["error"])

        demo_routes.SEED_JOBS["seed-1"] = {
            "job_id": "seed-1",
            "status": "completed",
            "done": True,
            "updated_ms": 100,
            "result": {"ok": True, "sample_ids": ["conv-1"], "seeded": 2, "seeded_turns": 2, "requested_turns": 2, "queue_idle": True},
        }
        self.assertEqual("benchmark_requires_flushed_corpus", demo_routes._locomo_seed_eligibility(sample_ids=["conv-1"])["error"])

        demo_routes.SEED_JOBS["seed-1"]["result"].update({"final_flush_count": 1, "final_flush_failed": 0})
        eligibility = demo_routes._locomo_seed_eligibility(sample_ids=["conv-1"])
        self.assertTrue(eligibility["eligible"])
        self.assertEqual("seed-1", eligibility["seed_record_id"])

    def test_locomo_benchmark_route_fails_without_seed_record(self):
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

            from app.routes import demo as demo_routes
            demo_routes.SEED_JOBS.clear()
            old_mode = demo_routes.settings.benchmark_run_mode
            demo_routes.settings.benchmark_run_mode = "queue"
            from app.main import app

            try:
                res = TestClient(app).post("/api/benchmark-run", json={"suite": "locomo_native_lifecycle", "sample_ids": ["conv-1"]})
            finally:
                demo_routes.settings.benchmark_run_mode = old_mode
            self.assertEqual(409, res.status_code)
            data = res.json()
            self.assertFalse(bool(data.get("ok")))
            self.assertEqual("benchmark_requires_seeded_corpus", data.get("error"))

    def test_locomo_benchmark_route_rejects_active_seed_job(self):
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

            from app.routes import demo as demo_routes
            demo_routes.SEED_JOBS.clear()
            now = demo_routes._now_ms()
            demo_routes.SEED_JOBS["seed-live"] = {
                "job_id": "seed-live",
                "status": "running",
                "done": False,
                "started_ms": now,
                "updated_ms": now,
            }
            demo_routes.SEED_STATUS.update({'active': True, 'kind': 'locomo', 'status': 'running', 'updated_ms': now, 'message': 'Seeding LoCoMo'})
            old_mode = demo_routes.settings.benchmark_run_mode
            demo_routes.settings.benchmark_run_mode = "queue"
            from app.main import app

            try:
                res = TestClient(app).post("/api/benchmark-run", json={"suite": "locomo_native_lifecycle", "sample_ids": ["conv-1"]})
            finally:
                demo_routes.settings.benchmark_run_mode = old_mode
            self.assertEqual(409, res.status_code)
            data = res.json()
            self.assertFalse(bool(data.get("ok")))
            self.assertEqual("seed_in_progress", data.get("error"))
            self.assertEqual("seed-live", data.get("active_seed_job_id"))

    def test_prune_seed_jobs_reconciles_stale_unfinished_seed_status(self):
        from app.routes import demo as demo_routes

        demo_routes.SEED_JOBS.clear()
        old = demo_routes._now_ms() - int((demo_routes.SEED_JOB_TTL_SECONDS * 2 + 601) * 1000)
        demo_routes.SEED_JOBS["seed-stale"] = {
            "job_id": "seed-stale",
            "status": "running",
            "done": False,
            "started_ms": old,
            "updated_ms": old,
        }
        demo_routes.SEED_STATUS.update({'active': True, 'kind': 'locomo', 'status': 'running', 'updated_ms': old, 'message': 'old'})

        demo_routes._prune_seed_jobs()

        self.assertNotIn("seed-stale", demo_routes.SEED_JOBS)
        self.assertFalse(bool(demo_routes.SEED_STATUS.get("active")))
        self.assertEqual("failed", demo_routes.SEED_STATUS.get("status"))
        self.assertIn("Stale seed job pruned", str(demo_routes.SEED_STATUS.get("message") or ""))

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
                    "conversation_id": "locomo:conv-1",
                    "conversation_index": 1,
                    "conversations": 2,
                    "replay_turn_completed": 4,
                    "replay_turn_total": 9,
                    "turn_id": "locomo:conv-1:D1:4",
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
        self.assertEqual(4, summary.get("replay_turn_completed"))
        self.assertEqual(9, summary.get("replay_turn_total"))
        self.assertEqual("locomo:conv-1:D1:4", report.get("turn_id"))
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
