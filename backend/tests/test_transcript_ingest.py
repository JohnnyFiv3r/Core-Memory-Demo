import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual("unpaired_final_user_turn", out["warnings"][0]["code"])

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

    def test_ingest_preserves_session_window_between_chunks(self):
        from app.ingest.transcript import run_transcript_ingest_job

        with tempfile.TemporaryDirectory() as td:
            seen_windows: list[list[str]] = []
            bead_counter = {"n": 0}

            def fake_process_turn_finalized(root: str, **env):
                from core_memory.persistence.store import MemoryStore

                seen_windows.append(list(env.get("window_bead_ids") or []))
                bead_counter["n"] += 1
                bid = MemoryStore(root).add_bead(
                    type="context",
                    title=f"bead-{bead_counter['n']}",
                    summary=["chunk"],
                    session_id=env["session_id"],
                    source_turn_ids=[env["turn_id"]],
                )
                return {"ok": True, "bead_ids": [bid]}

            with patch("app.ingest.transcript.process_turn_finalized", side_effect=fake_process_turn_finalized):
                first = run_transcript_ingest_job(
                    root=td,
                    transcript_id="chunk-1",
                    session_id="same-session",
                    flush_policy="none",
                    turns=[{"role": "user", "content": "First"}, {"role": "assistant", "content": "One"}],
                )
                second = run_transcript_ingest_job(
                    root=td,
                    transcript_id="chunk-2",
                    session_id="same-session",
                    flush_policy="none",
                    turns=[{"role": "user", "content": "Second"}, {"role": "assistant", "content": "Two"}],
                )
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertTrue(set(first["ingested"][0]["bead_ids"]).issubset(set(seen_windows[1])))

    def test_associations_summary_matches_transcript_ingest_shape(self):
        from app.ingest.transcript import run_transcript_ingest_job

        with tempfile.TemporaryDirectory() as td:
            def fake_process_turn_finalized(root: str, **env):
                import json
                from core_memory.persistence.store import MemoryStore

                store = MemoryStore(root)
                b1 = store.add_bead(type="decision", title="A", summary=["A"], session_id=env["session_id"], source_turn_ids=[env["turn_id"]])
                b2 = store.add_bead(type="context", title="B", summary=["B"], session_id=env["session_id"], source_turn_ids=[env["turn_id"]])
                idx_path = Path(root) / ".beads" / "index.json"
                idx = json.loads(idx_path.read_text(encoding="utf-8"))
                idx.setdefault("associations", []).append({"source_bead": b1, "target_bead": b2, "relationship": "supports", "confidence": 0.9})
                idx_path.write_text(json.dumps(idx), encoding="utf-8")
                return {"ok": True, "bead_ids": [b1, b2]}

            with patch("app.ingest.transcript.process_turn_finalized", side_effect=fake_process_turn_finalized):
                out = run_transcript_ingest_job(
                    root=td,
                    transcript_id="assoc",
                    session_id="assoc-session",
                    flush_policy="none",
                    turns=[{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}],
                )
        self.assertEqual(1, out["associations_created"]["count"])
        self.assertEqual({"supports": 1}, out["associations_created"]["by_type"])
        self.assertEqual("supports", out["associations_created"]["items"][0]["relationship"])


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
            self.assertEqual("done", last.get("status"), last)
            self.assertEqual("transcript_ingest", (last.get("result") or {}).get("kind"))
            self.assertIn("associations_created", last)

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
                },
            )
        self.assertEqual(202, res.status_code)
        self.assertEqual({"transcript_id", "session_id", "turns", "flush_policy"}, set(captured["kwargs"].keys()))
        self.assertNotIn("sample_id", captured["kwargs"])
        self.assertNotIn("sessions", captured["kwargs"])

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
