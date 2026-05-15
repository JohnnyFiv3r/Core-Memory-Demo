import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestTranscriptIngestThinAdapter(unittest.TestCase):
    def test_demo_adapter_passes_turns_as_is_to_engine(self):
        from app.ingest import transcript as adapter

        turns = [
            {"role": "human", "text": "Use PostgreSQL", "extra": {"keep": True}},
            {"role": "ai", "message": "Recorded."},
        ]
        captured = {}

        def fake_ingest_transcript(**kwargs):
            captured.update(kwargs)
            return {
                "ok": True,
                "kind": "transcript_ingest",
                "turns_received": 2,
                "turns_paired": 1,
                "turns_ingested": 1,
                "warnings": [],
                "associations_created": {"count": 0, "by_type": {}, "items": []},
            }

        with patch.object(adapter, "core_ingest_transcript", side_effect=fake_ingest_transcript):
            out = adapter.run_transcript_ingest_job(
                root="/tmp/cm",
                transcript_id="raw",
                session_id="s1",
                turns=turns,
                flush_policy="none",
                metadata={"source": "unit"},
            )

        self.assertTrue(out["ok"])
        self.assertIs(captured["turns"], turns)
        self.assertEqual("/tmp/cm", captured["root"])
        self.assertEqual("raw", captured["transcript_id"])
        self.assertEqual("s1", captured["session_id"])
        self.assertEqual("none", captured["flush_policy"])
        self.assertEqual({"source": "unit"}, captured["metadata"])

    def test_demo_adapter_does_not_import_engine_normalizer(self):
        from app.ingest import transcript as adapter

        self.assertFalse(hasattr(adapter, "normalize_transcript_payload"))

    def test_boundary_validation_accepts_messages_without_preprocessing(self):
        from app.ingest.transcript import transcript_job_kwargs

        messages = [{"role": "human", "text": "Q"}, {"role": "agent", "body": "A"}]
        out = transcript_job_kwargs(
            {"transcript_id": "m1", "messages": messages, "metadata": {"x": 1}},
            root="/tmp/cm",
            max_turns=10,
        )
        self.assertEqual("/tmp/cm", out["root"])
        self.assertEqual("m1", out["transcript_id"])
        self.assertEqual(messages, out["turns"])
        self.assertEqual({"x": 1}, out["metadata"])

    def test_boundary_validation_rejects_bad_payloads(self):
        from app.ingest.transcript import transcript_job_kwargs

        with self.assertRaisesRegex(ValueError, "turns_required"):
            transcript_job_kwargs({"turns": []}, root="/tmp/cm")
        with self.assertRaisesRegex(ValueError, "turn_must_be_object"):
            transcript_job_kwargs({"turns": ["bad"]}, root="/tmp/cm")
        with self.assertRaisesRegex(ValueError, "unsupported_flush_policy"):
            transcript_job_kwargs({"turns": [{"role": "user", "content": "x"}], "flush_policy": "always"}, root="/tmp/cm")

    def test_unpaired_warning_is_preserved_or_derived_from_engine_result(self):
        from app.ingest import transcript as adapter

        def fake_ingest_transcript(**kwargs):
            return {
                "ok": True,
                "kind": "transcript_ingest",
                "turns_received": 3,
                "turns_paired": 1,
                "turns_ingested": 1,
                "warnings": [],
                "associations_created": {"count": 0, "by_type": {}, "items": []},
            }

        with patch.object(adapter, "core_ingest_transcript", side_effect=fake_ingest_transcript):
            out = adapter.run_transcript_ingest_job(
                root="/tmp/cm",
                transcript_id="trail",
                turns=[{"role": "user", "content": "Q"}],
            )
        self.assertIn("unpaired_final_user_turn", [w.get("code") for w in out["warnings"] if isinstance(w, dict)])

    def test_engine_result_passes_through_associations_created(self):
        from app.ingest import transcript as adapter

        expected = {"count": 1, "by_type": {"supports": 1}, "items": [{"relationship": "supports"}]}

        def fake_ingest_transcript(**kwargs):
            return {
                "ok": True,
                "kind": "transcript_ingest",
                "turns_received": 2,
                "turns_paired": 1,
                "turns_ingested": 1,
                "warnings": [],
                "associations_created": expected,
            }

        with patch.object(adapter, "core_ingest_transcript", side_effect=fake_ingest_transcript):
            out = adapter.run_transcript_ingest_job(root="/tmp/cm", transcript_id="assoc", turns=[{"role": "user", "content": "Q"}])
        self.assertEqual(expected, out["associations_created"])


class TestTranscriptIngestRoute(unittest.TestCase):
    def test_post_ingest_transcript_returns_accepted_and_status(self):
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
            self.assertEqual("accepted", data.get("status"))
            job_id = data.get("job_id")
            self.assertTrue(str(job_id).startswith("ingest-"))

            last = None
            for _ in range(20):
                status = c.get(f"/api/ingest/job/{job_id}")
                self.assertEqual(200, status.status_code)
                last = status.json()
                if last.get("done"):
                    break
                time.sleep(0.1)
            self.assertIsNotNone(last)
            self.assertTrue(last.get("done"), last)
            self.assertEqual("done", last.get("status"), last)
            self.assertEqual("transcript_ingest", (last.get("result") or {}).get("kind"))
            self.assertIn("associations_created", last)
            self.assertIn("warnings", last)

    def test_queue_mode_writes_generic_kwargs_only(self):
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"fastapi unavailable: {exc}")
        from app.main import app
        from app.routes import ingest as ingest_routes

        captured = {}

        def fake_enqueue(*, job_id, request, kwargs):
            captured["job_id"] = job_id
            captured["request"] = dict(request)
            captured["kwargs"] = dict(kwargs)
            return True

        c = TestClient(app)
        with patch.object(ingest_routes.settings, "transcript_ingest_run_mode", "queue"), \
             patch.object(ingest_routes.benchmark_store, "enqueue_job", side_effect=fake_enqueue):
            res = c.post(
                "/api/ingest/transcript",
                json={
                    "transcript_id": "queue-shape",
                    "session_id": "queue-session",
                    "sample_id": "locomo-only",
                    "sessions": [{"dia_id": "locomo"}],
                    "turns": [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}],
                    "flush_policy": "none",
                    "metadata": {"source": "unit"},
                },
            )
        self.assertEqual(202, res.status_code)
        self.assertEqual("accepted", res.json().get("status"))
        self.assertEqual("transcript_ingest", captured["request"].get("kind"))
        self.assertEqual({"root", "transcript_id", "session_id", "turns", "flush_policy", "metadata"}, set(captured["kwargs"].keys()))
        self.assertNotIn("sample_id", captured["kwargs"])
        self.assertNotIn("sessions", captured["kwargs"])

    def test_completed_stored_job_status_maps_done_and_passes_warnings(self):
        from app.routes import ingest as ingest_routes

        stored = {
            "job_id": "ingest-stored",
            "status": "completed",
            "request": {"kind": "transcript_ingest"},
            "result": {
                "ok": True,
                "turns_ingested": 1,
                "warnings": [{"code": "unpaired_final_user_turn"}],
                "associations_created": {"count": 0, "by_type": {}, "items": []},
            },
        }
        with patch.object(ingest_routes.benchmark_store, "read_job", return_value=stored):
            out = ingest_routes.ingest_job_status("ingest-stored")
        self.assertEqual("done", out["status"])
        self.assertEqual([{"code": "unpaired_final_user_turn"}], out["warnings"])

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
