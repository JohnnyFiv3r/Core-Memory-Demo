import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestRecallApiContract(unittest.TestCase):
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

    def test_recall_endpoint_returns_public_contract(self):
        payload = {
            "ok": True,
            "status": "answered",
            "answer": "Deployment failed because the database URL was missing.",
            "evidence": [
                {
                    "bead_id": "bead-1",
                    "title": "Deploy failure",
                    "content_excerpt": "DATABASE_URL was missing during deploy.",
                    "score": 0.91,
                }
            ],
            "sources": [{"turn_id": "turn-1", "content_excerpt": "Deploy failed."}],
            "tier_path": ["claim_state", "semantic"],
            "resolved_goals": [],
            "claim_slots": {},
            "metadata": {"source_surface": "recall_orchestrator"},
            "contract": "recall_result",
            "schema_version": "recall_result.v1",
        }
        with patch("app.routes.demo.run_recall", return_value=payload) as recall:
            res = self._client().post("/api/recall", json={"query": "why did deployment fail", "effort": "high", "k": 5})
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertEqual("recall_result", body["contract"])
        self.assertEqual("recall_result.v1", body["schema_version"])
        self.assertEqual("recall_orchestrator", body["metadata"]["source_surface"])
        self.assertEqual(["claim_state", "semantic"], body["tier_path"])
        self.assertEqual("DATABASE_URL was missing during deploy.", body["evidence"][0]["content_excerpt"])
        recall.assert_called_once()
        _, kwargs = recall.call_args
        self.assertEqual("high", kwargs["effort"])
        self.assertEqual(5, kwargs["k"])
        self.assertFalse(kwargs["include_raw"])

    def test_recall_endpoint_rejects_missing_query_and_invalid_k(self):
        c = self._client()
        self.assertEqual(400, c.post("/api/recall", json={}).status_code)
        res = c.post("/api/recall", json={"query": "hello", "k": "nope"})
        self.assertEqual(400, res.status_code)
        self.assertEqual("invalid_k", res.json().get("error"))

    def test_recall_endpoint_rejects_invalid_effort(self):
        with patch("app.routes.demo.run_recall", side_effect=ValueError("recall effort must be one of: high, low, medium")):
            res = self._client().post("/api/recall", json={"query": "hello", "effort": "extreme"})
        self.assertEqual(400, res.status_code)
        self.assertIn("recall effort", res.json().get("error", ""))

    def test_recall_endpoint_forwards_as_of(self):
        with patch("app.routes.demo.run_recall", return_value={"ok": True, "status": "answered"}) as recall:
            res = self._client().post(
                "/api/recall",
                json={"query": "what did I say", "as_of": "2026-01-01T00:00:00Z"},
            )
        self.assertEqual(200, res.status_code)
        _, kwargs = recall.call_args
        self.assertEqual("2026-01-01T00:00:00Z", kwargs["as_of"])

    def test_recall_endpoint_maps_invalid_as_of_to_400(self):
        with patch(
            "app.routes.demo.run_recall",
            side_effect=ValueError("as_of must be a valid ISO 8601 timestamp, got 'nope'"),
        ):
            res = self._client().post("/api/recall", json={"query": "hello", "as_of": "nope"})
        self.assertEqual(400, res.status_code)
        self.assertIn("as_of", res.json().get("error", ""))


class TestRecallRuntimeContract(unittest.TestCase):
    def test_recall_payload_defaults_and_raw_gating(self):
        from app.core.runtime import _recall_result_to_payload
        from core_memory.retrieval.contracts import EvidenceItem, RecallResult

        result = RecallResult(
            status="answered",
            evidence=[EvidenceItem(bead_id="bead-1", content_excerpt="Grounded fact")],
            metadata={},
            raw={"results": [{"bead_id": "bead-1"}]},
        )

        public_payload = _recall_result_to_payload(result, include_raw=False)
        self.assertEqual("recall_result", public_payload["contract"])
        self.assertEqual("recall_result.v1", public_payload["schema_version"])
        self.assertEqual("recall_orchestrator", public_payload["metadata"]["source_surface"])
        self.assertNotIn("raw", public_payload)
        for key in ("evidence", "resolved_goals", "sources", "tier_path", "steps", "warnings"):
            self.assertIsInstance(public_payload[key], list)
        self.assertIsInstance(public_payload["claim_slots"], dict)

        raw_payload = _recall_result_to_payload(result, include_raw=True)
        self.assertIn("raw", raw_payload)
        self.assertEqual("bead-1", raw_payload["raw"]["results"][0]["bead_id"])

    def test_recall_payload_surfaces_conflicts_and_as_of(self):
        from app.core.runtime import _recall_result_to_payload
        from core_memory.retrieval.contracts import ConflictItem, RecallResult

        conflict = ConflictItem(
            subject="db",
            slot="host",
            claim_a_id="claim-a",
            claim_b_id="claim-b",
            epistemic_conflict_score=0.8,
        )
        result = RecallResult(
            status="answered",
            conflicts=[conflict],
            as_of="2026-01-01T00:00:00Z",
            metadata={},
        )
        payload = _recall_result_to_payload(result, include_raw=False)
        # conflicts is always a list in the public contract; as_of is carried through.
        self.assertIsInstance(payload["conflicts"], list)
        self.assertEqual("2026-01-01T00:00:00Z", payload["as_of"])

    def test_recall_payload_defaults_as_of_and_conflicts_when_absent(self):
        from app.core.runtime import _recall_result_to_payload
        from core_memory.retrieval.contracts import RecallResult

        payload = _recall_result_to_payload(RecallResult(status="empty"), include_raw=False)
        self.assertIsInstance(payload["conflicts"], list)
        self.assertIn("as_of", payload)

    def test_frontend_renders_recall_result_content_excerpt(self):
        root = Path(__file__).resolve().parents[2]
        js = (root / "frontend" / "public" / "chat-app.js").read_text()
        self.assertIn("function recallContractFromChatPayload", js)
        self.assertIn("function renderRecallEvidence", js)
        self.assertIn("item.content_excerpt", js)
        self.assertIn("recall-evidence-panel", js)


if __name__ == "__main__":
    unittest.main()
