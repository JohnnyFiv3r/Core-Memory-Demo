import os
import tempfile
import unittest
from pathlib import Path


class TestApiSmoke(unittest.TestCase):
    def test_routes_smoke(self):
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
            self.assertEqual(200, c.get("/").status_code)
            self.assertEqual(200, c.get("/healthz").status_code)
            self.assertEqual(200, c.get("/api/meta").status_code)
            self.assertEqual(200, c.get("/api/demo/state").status_code)
            self.assertEqual(200, c.get("/v1/memory/inspect/state").status_code)
            self.assertEqual(200, c.get("/api/story-pack/meta").status_code)

            recall = c.post("/api/recall", json={"query": "test", "effort": "medium", "explain": False})
            self.assertEqual(200, recall.status_code)
            recall_payload = recall.json()
            for key in ("status", "evidence", "resolved_goals", "claim_slots"):
                self.assertIn(key, recall_payload)

            ingest = c.post(
                "/api/ingest/transcript",
                json={
                    "transcript_id": "smoke-transcript",
                    "session_id": "smoke-session",
                    "turns": [
                        {"role": "user", "content": "I prefer tea"},
                        {"role": "assistant", "content": "Noted."},
                    ],
                },
            )
            self.assertEqual(202, ingest.status_code)
            ingest_payload = ingest.json()
            result = ingest_payload.get("result") or {}
            if result:
                self.assertIn("associations_created", result)
                self.assertIn("semantic_status", result)

            self.assertEqual(200, c.post("/api/seed").status_code)
            self.assertEqual(200, c.post("/api/flush").status_code)
            self.assertEqual(
                200,
                c.post(
                    "/api/story-pack/replay",
                    json={
                        "max_turns": 1,
                        "run_checkpoints": False,
                        "wait_for_idle": False,
                    },
                ).status_code,
            )
            self.assertEqual(200, c.post("/api/benchmark-run", json={"limit": 2, "root_mode": "clean"}).status_code)


if __name__ == "__main__":
    unittest.main()
