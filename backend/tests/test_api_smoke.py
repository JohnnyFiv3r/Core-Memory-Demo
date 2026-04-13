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

            self.assertEqual(200, c.post("/api/seed").status_code)
            self.assertEqual(200, c.post("/api/flush").status_code)
            self.assertEqual(200, c.post("/api/benchmark-run", json={"limit": 2, "root_mode": "clean"}).status_code)


if __name__ == "__main__":
    unittest.main()
