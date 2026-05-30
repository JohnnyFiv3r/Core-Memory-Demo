import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestGroupTranscriptValidation(unittest.TestCase):
    def test_group_mode_and_window_and_source_system(self):
        from app.ingest.transcript import validate_transcript_request

        built = validate_transcript_request(
            {
                "turns": [
                    {"speaker": "U12345", "content": "kicking off the sync"},
                    {"speaker": "U67890", "content": "agenda is the migration"},
                    {"speaker": "U24680", "content": "I'll own the rollback plan"},
                ],
                "mode": "group",
                "window_size": 2,
                "source_system": "slack",
            },
            max_turns=100,
        )
        self.assertEqual("group", built["mode"])
        self.assertEqual(2, built["window_size"])
        self.assertEqual("slack", built["metadata"]["source_system"])

    def test_default_mode_is_dyadic_without_window(self):
        from app.ingest.transcript import validate_transcript_request

        built = validate_transcript_request({"turns": [{"role": "user", "content": "hi"}]})
        self.assertEqual("dyadic", built["mode"])
        self.assertNotIn("window_size", built)

    def test_rejects_unknown_mode_and_bad_window(self):
        from app.ingest.transcript import validate_transcript_request

        with self.assertRaises(ValueError):
            validate_transcript_request({"turns": [{"role": "user", "content": "hi"}], "mode": "solo"})
        with self.assertRaises(ValueError):
            validate_transcript_request({"turns": [{"role": "user", "content": "hi"}], "window_size": "lots"})

    def test_run_job_forwards_group_mode_to_engine(self):
        from app.ingest import transcript as adapter

        captured = {}

        def fake_ingest_transcript(**kwargs):
            captured.update(kwargs)
            return {"ok": True, "turns_received": 3, "turns_paired": 0, "turns_ingested": 3, "warnings": []}

        with patch.object(adapter, "core_ingest_transcript", side_effect=fake_ingest_transcript):
            adapter.run_transcript_ingest_job(
                root="/tmp/cm",
                transcript_id="grp",
                session_id="s1",
                turns=[{"speaker": "a", "content": "x"}],
                flush_policy="none",
                metadata={"source_system": "discord"},
                mode="group",
                window_size=5,
            )
        self.assertEqual("group", captured["mode"])
        self.assertEqual(5, captured["window_size"])

    def test_run_job_dyadic_does_not_forward_mode(self):
        from app.ingest import transcript as adapter

        captured = {}
        with patch.object(adapter, "core_ingest_transcript", side_effect=lambda **k: captured.update(k) or {"ok": True}):
            adapter.run_transcript_ingest_job(
                root="/tmp/cm", transcript_id="t", session_id="s", turns=[{"role": "user", "content": "x"}], flush_policy="none",
            )
        self.assertNotIn("mode", captured)
        self.assertNotIn("window_size", captured)


class _RouteTestBase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        os.environ["CORE_MEMORY_ROOT"] = str(root / "core-memory")
        os.environ["CORE_MEMORY_DEMO_BENCHMARK_ROOT"] = str(root / "core-memory-bench")
        os.environ["CORE_MEMORY_DEMO_ARTIFACTS_ROOT"] = str(root / "core-memory-artifacts")
        os.environ["ALLOWED_ORIGIN"] = "http://localhost:5173"

    def tearDown(self):
        self._td.cleanup()

    def _client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        return TestClient(app)


class TestDataInsightRoute(_RouteTestBase):
    def test_missing_required_fields_returns_400(self):
        res = self._client().post("/api/ingest/data-insight", json={"row": {"id": "rec-1"}})
        self.assertEqual(400, res.status_code)
        self.assertIn("required fields", res.json().get("error", ""))

    def test_valid_row_returns_bead_id(self):
        captured = {}

        def fake_ingest(root, session_id, row):
            captured["root"] = root
            captured["session_id"] = session_id
            captured["row"] = row
            return {"ok": True, "bead_id": "bead-xyz", "turn_id": "data-insight-rec-1"}

        with patch("core_memory.runtime.ingest.data_insight.ingest_data_insight_row", side_effect=fake_ingest):
            res = self._client().post(
                "/api/ingest/data-insight",
                json={
                    "session_id": "pipehouse-test",
                    "row": {
                        "id": "rec-1",
                        "source_table": "insights",
                        "as_of_timestamp": "2026-01-01T00:00:00Z",
                        "entity_refs": ["acct-1"],
                        "attribute_tags": ["churn_risk"],
                        "title": "Account at risk",
                        "content": "Usage dropped 40% month over month.",
                    },
                },
            )
        self.assertEqual(200, res.status_code, res.text)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual("bead-xyz", body["bead_id"])
        self.assertEqual("data-insight-rec-1", body["turn_id"])
        self.assertEqual("pipehouse-test", captured["session_id"])


class TestSessionCaptureRoute(_RouteTestBase):
    def test_missing_turns_returns_400(self):
        res = self._client().post("/api/session/capture", json={})
        self.assertEqual(400, res.status_code)
        self.assertEqual("turns_or_messages_required", res.json().get("error"))

    def test_valid_transcript_invokes_capture_session(self):
        captured = {}

        def fake_capture(payload):
            captured.update(payload or {})
            return {"ok": True, "session_id": "session_sync:inline", "bead_ids": ["b1", "b2"]}

        with patch("core_memory.integrations.mcp.tools.capture_session.capture_session_handler", side_effect=fake_capture):
            res = self._client().post(
                "/api/session/capture",
                json={
                    "turns": [
                        {"role": "user", "content": "remember the deploy used flag X"},
                        {"role": "assistant", "content": "noted"},
                    ],
                    "source_system": "demo",
                },
            )
        self.assertEqual(200, res.status_code, res.text)
        self.assertTrue(res.json()["ok"])
        # The demo binds its own memory root and forwards source_system.
        self.assertIn("root", captured)
        self.assertEqual("demo", captured["source_system"])
        self.assertEqual(2, len(captured["turns"]))


if __name__ == "__main__":
    unittest.main()
