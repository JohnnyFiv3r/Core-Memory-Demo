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

        # PR #184 pin (master tip): engine recall quality (#183: drop causal
        # context->reflection over-typing + effort-tier association-hop expansion)
        # and demo ingest polling timeout (#184); on top of the #182 per-request
        # bead-judge directive and #181 Qdrant dim sentinel.
        self.assertIn("4f8929bf217ed067a8481bec28c1aa0fa813cf0e", requirements)
        self.assertIn("core-memory[qdrant,kuzu,mcp]", requirements)
        self.assertIn("qdrant-client[fastembed]>=1.9", requirements)
        self.assertIn("psycopg[binary]==3.3.2", requirements)
        # Superseded pins must not linger.
        self.assertNotIn("0639420119d55063d27c9251f96166961ea61f16", requirements)
        self.assertNotIn("97df33274c20a0ba7aa32d090efdce5076114f37", requirements)
        self.assertNotIn("c8ec297342bf16bdd89b2406ad3e667f67cf3bdb", requirements)
        self.assertNotIn("df897776fe4cc4bfead9417aa0ba07c7f3aa853f", requirements)
        self.assertNotIn("1640be3a199f260e7b185090e3f2c829e2da2503", requirements)
        self.assertNotIn("ca5038bf05a35f35e774bd4dc13df440daf712a0", requirements)
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
