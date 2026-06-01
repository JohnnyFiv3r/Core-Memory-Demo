import json
import tempfile
import unittest
from pathlib import Path

from app.core.semantic_upgrade import (
    _UNIFIED_BEAD_PROJECTION_UPGRADE,
    queue_semantic_projection_upgrade_once,
)


class TestSemanticProjectionUpgrade(unittest.TestCase):
    def test_requirements_pin_core_memory_reconcile_fix_and_explicit_qdrant(self):
        requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("fcf29b8a01957cff3604c44a2a7864d43b09164e", requirements)
        self.assertIn("core-memory[qdrant,kuzu,mcp]", requirements)
        self.assertIn("qdrant-client[fastembed]>=1.9", requirements)
        self.assertNotIn("48d21794424c3efd996ee3ed80839d33c4b4fee0", requirements)

    def test_queues_projection_rebuild_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "core-memory"

            first = queue_semantic_projection_upgrade_once(root)
            self.assertTrue(first.get("ok"))
            self.assertTrue(first.get("queued"))
            self.assertFalse(first.get("already_applied"))

            marker_path = root / ".beads" / "semantic" / "projection-upgrades.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertIn(_UNIFIED_BEAD_PROJECTION_UPGRADE, marker.get("applied") or [])

            manifest_path = root / ".beads" / "semantic" / "manifest.json"
            self.assertFalse(manifest_path.exists())

            queue_path = root / ".beads" / "semantic" / "rebuild-queue.json"
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertTrue(queue.get("queued"))
            self.assertEqual("reconcile", queue.get("mode"))
            self.assertEqual(1, int(queue.get("epoch") or 0))

            second = queue_semantic_projection_upgrade_once(root)
            self.assertTrue(second.get("ok"))
            self.assertFalse(second.get("queued"))
            self.assertTrue(second.get("already_applied"))

            queue_after = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(1, int(queue_after.get("epoch") or 0))

    def test_new_core_memory_projection_includes_association_anchors(self):
        from core_memory.schema.bead_projection import build_retrieval_text

        text = build_retrieval_text(
            {
                "title": "Budget review",
                "type": "decision",
                "summary": ["Approved Q3 infrastructure spend"],
                "entities": ["Acme Finance"],
                "topics": ["budgeting"],
                "goal_keys": ["reduce_cost"],
                "decision_keys": ["approve_budget"],
                "cause_candidates": ["qdrant_latency_drop"],
                "effect_candidates": ["faster_recall"],
            }
        )

        self.assertIn("Acme Finance", text)
        self.assertIn("budgeting", text)
        self.assertIn("reduce_cost", text)
        self.assertIn("reduce cost", text)
        self.assertIn("approve_budget", text)
        self.assertIn("approve budget", text)
        self.assertIn("qdrant_latency_drop", text)
        self.assertIn("faster_recall", text)


if __name__ == "__main__":
    unittest.main()
