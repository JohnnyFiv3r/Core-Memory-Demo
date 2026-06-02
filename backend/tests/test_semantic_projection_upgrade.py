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

        # PR #175 schema pin (type-vocabulary revision + bead dataclass
        # completeness; supersedes the #174 retrieval-gate-removal pin).
        self.assertIn("ca5038bf05a35f35e774bd4dc13df440daf712a0", requirements)
        self.assertIn("core-memory[qdrant,kuzu,mcp]", requirements)
        self.assertIn("qdrant-client[fastembed]>=1.9", requirements)
        self.assertIn("psycopg[binary]==3.3.2", requirements)
        self.assertNotIn("c0c85606ddb3799b171f6fea9a67d35c2bfea66e", requirements)
        self.assertNotIn("7cb8f932d5f09cf3726ade95e549bac60988011b", requirements)

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

    def test_new_core_memory_projection_embeds_entities_and_facts(self):
        # CM #174 slimmed the projection: the legacy anchors (topics/*_keys/
        # cause_candidates/effect_candidates) were removed. build_retrieval_text
        # now composes title/summary/entities/supporting_facts/tags — the fields
        # that survive the schema migration carry the recall signal.
        from core_memory.schema.bead_projection import build_retrieval_text

        text = build_retrieval_text(
            {
                "title": "Budget review",
                "type": "decision",
                "summary": ["Approved Q3 infrastructure spend"],
                "entities": ["Acme Finance", "budgeting"],
                "supporting_facts": ["Q3 infrastructure budget approved"],
            }
        )

        self.assertIn("Budget review", text)
        self.assertIn("Acme Finance", text)
        self.assertIn("budgeting", text)
        self.assertIn("Q3 infrastructure budget approved", text)


if __name__ == "__main__":
    unittest.main()
