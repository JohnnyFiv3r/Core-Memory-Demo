import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestTranscriptIngestNormalizer(unittest.TestCase):
    def test_pairs_user_assistant_and_preserves_metadata(self):
        from app.ingest.transcript import normalize_transcript_payload

        out = normalize_transcript_payload(
            {
                "transcript_id": "smoke/source 1",
                "session_id": "session A",
                "metadata": {"source": "unit"},
                "turns": [
                    {"role": "human", "content": "Use PostgreSQL", "timestamp": "2026-05-12T19:30:00Z", "speaker": "Johnny"},
                    {"role": "ai", "content": "Recorded.", "timestamp": "2026-05-12T19:30:01Z"},
                ],
            }
        )
        self.assertTrue(out["ok"])
        self.assertEqual("smoke-source-1", out["transcript_id"])
        self.assertEqual("session-A", out["session_id"])
        self.assertEqual(2, out["turns_received"])
        self.assertEqual(1, out["turns_paired"])
        env = out["envelopes"][0]
        self.assertEqual("Use PostgreSQL", env["turns"][0]["content"])
        self.assertEqual("Recorded.", env["turns"][1]["content"])
        self.assertEqual("transcript_ingest", env["metadata"]["source"])
        self.assertEqual("Johnny", env["metadata"]["user_speaker"])

    def test_trailing_user_becomes_user_only_turn(self):
        from app.ingest.transcript import normalize_transcript_payload

        out = normalize_transcript_payload({"turns": [{"role": "user", "content": "Remember this"}]})
        self.assertEqual(1, out["turns_paired"])
        self.assertEqual("Remember this", out["envelopes"][0]["turns"][0]["content"])
        self.assertEqual(1, len(out["envelopes"][0]["turns"]))

    def test_rejects_bad_payloads(self):
        from app.ingest.transcript import normalize_transcript_payload

        with self.assertRaisesRegex(ValueError, "turns_required"):
            normalize_transcript_payload({"turns": []})
        with self.assertRaisesRegex(ValueError, "unsupported_role"):
            normalize_transcript_payload({"turns": [{"role": "system", "content": "x"}]})
        with self.assertRaisesRegex(ValueError, "content_required"):
            normalize_transcript_payload({"turns": [{"role": "user", "content": "  "}]})


class TestTranscriptIngestRuntime(unittest.TestCase):
    def test_ingest_turn_envelopes_uses_runtime_path(self):
        from app.ingest.transcript import ingest_turn_envelopes, normalize_transcript_payload

        with tempfile.TemporaryDirectory() as td:
            normalized = normalize_transcript_payload(
                {
                    "transcript_id": "unit-runtime",
                    "session_id": "unit-runtime-session",
                    "flush_policy": "none",
                    "turns": [
                        {"role": "user", "content": "Project Heron uses PostgreSQL for tenant config."},
                        {"role": "assistant", "content": "Recorded."},
                    ],
                }
            )
            out = ingest_turn_envelopes(root=td, envelopes=normalized["envelopes"], flush_policy="none")
            self.assertTrue(out["ok"])
            self.assertEqual(1, out["turns_ingested"])
            index_path = Path(td) / ".beads" / "index.json"
            self.assertTrue(index_path.exists())
            self.assertIn("unit-runtime-session", index_path.read_text(encoding="utf-8"))


class TestTranscriptIngestRoute(unittest.TestCase):
    def test_post_ingest_transcript_returns_job_and_status(self):
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"fastapi unavailable: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["CORE_MEMORY_ROOT"] = str(root / "core-memory")
            os.environ["CORE_MEMORY_DEMO_BENCHMARK_ROOT"] = str(root / "core-memory-bench")
            os.environ["CORE_MEMORY_DEMO_ARTIFACTS_ROOT"] = str(root / "core-memory-artifacts")
            os.environ["CORE_MEMORY_DEMO_BENCHMARK_RUN_MODE"] = "inline"
            os.environ["ALLOWED_ORIGIN"] = "http://localhost:5173"

            from app.main import app

            c = TestClient(app)
            res = c.post(
                "/api/ingest/transcript",
                json={
                    "transcript_id": "route-smoke",
                    "session_id": "route-smoke-session",
                    "flush_policy": "none",
                    "turns": [
                        {"role": "user", "content": "Project Heron uses PostgreSQL for tenant config."},
                        {"role": "assistant", "content": "Recorded."},
                    ],
                },
            )
            self.assertEqual(202, res.status_code)
            data = res.json()
            self.assertTrue(data.get("ok"))
            job_id = data.get("job_id")
            self.assertTrue(str(job_id).startswith("ingest-"))

            last = None
            for _ in range(20):
                status = c.get(f"/api/ingest/jobs/{job_id}")
                self.assertEqual(200, status.status_code)
                last = status.json()
                if last.get("done"):
                    break
                time.sleep(0.1)
            self.assertIsNotNone(last)
            self.assertTrue(last.get("done"), last)
            self.assertEqual("completed", last.get("status"), last)
            self.assertEqual("transcript_ingest", (last.get("result") or {}).get("kind"))

    def test_bad_payload_returns_422(self):
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"fastapi unavailable: {exc}")
        from app.main import app

        c = TestClient(app)
        res = c.post("/api/ingest/transcript", json={"turns": []})
        self.assertEqual(422, res.status_code)
        self.assertIn("turns_required", str(res.json()))


if __name__ == "__main__":
    unittest.main()
