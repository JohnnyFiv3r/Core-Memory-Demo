import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Core-Memory"))

from unittest.mock import patch

from app.benchmarks.locomo_ingest import _extract_locomo_claims, build_turn_bead, ingest_locomo_turns
from core_memory.runtime.turn.turn_archive import find_turn_record


class TestLocomoIngest(unittest.TestCase):
    def test_build_turn_bead_preserves_dia_id(self):
        bead = build_turn_bead(
            {
                "sample_id": "conv-1",
                "session_index": 1,
                "turn_index": 3,
                "dia_id": "D1:3",
                "speaker": "Alice",
                "text": "Hello there",
                "session_date_time": "1 Jan 2024",
            }
        )
        self.assertEqual(["D1:3"], bead["source_turn_ids"])
        self.assertEqual("locomo:conv-1", bead["session_id"])
        self.assertEqual("D1:3", bead["metadata"]["dia_id"])
        self.assertIn("sample_id=conv-1", bead["supporting_facts"])
        self.assertIn("session_index=1", bead["supporting_facts"])
        self.assertIn("turn_index=3", bead["supporting_facts"])
        self.assertIn("speaker=Alice", bead["supporting_facts"])
        self.assertIn("session_date_time=1 Jan 2024", bead["supporting_facts"])
        self.assertTrue(any("Alice: Hello there" in fact for fact in bead["supporting_facts"]))
        self.assertTrue(str(bead["detail"]).startswith("Session date: 1 Jan 2024"))

    def test_extract_locomo_claims_does_not_inject_dataset_specific_answers(self):
        claims = _extract_locomo_claims(
            {
                "sample_id": "conv-49",
                "session_index": 1,
                "turn_index": 2,
                "dia_id": "D1:2",
                "speaker": "Evan",
                "text": "I just got back from a trip with my family in my blue bicycle.",
                "session_date_time": "6:11 pm on 12 May, 2023",
            }
        )
        self.assertEqual([], claims)

    def test_ingest_is_idempotent_within_root(self):
        sample = {
            "sample_id": "conv-1",
            "sessions": [
                {
                    "session_index": 1,
                    "date_time": "1 Jan 2024",
                    "turns": [
                        {
                            "sample_id": "conv-1",
                            "session_index": 1,
                            "turn_index": 1,
                            "dia_id": "D1:1",
                            "speaker": "Alice",
                            "text": "Hello there",
                            "session_date_time": "1 Jan 2024",
                        }
                    ],
                }
            ],
        }
        class _FakeStore:
            def __init__(self, root):
                self.root = root
                self.calls = []

            def add_bead(self, **kwargs):
                idx_path = Path(self.root) / ".beads" / "index.json"
                idx_path.parent.mkdir(parents=True, exist_ok=True)
                data = {"beads": {"bead-1": dict(kwargs, id="bead-1")}}
                idx_path.write_text(json.dumps(data), encoding="utf-8")
                self.calls.append(kwargs)
                return "bead-1"

        with tempfile.TemporaryDirectory() as td:
            with patch("app.benchmarks.locomo_ingest.MemoryStore", _FakeStore):
                out1 = ingest_locomo_turns(root=td, sample=sample, mode="turns")
                out2 = ingest_locomo_turns(root=td, sample=sample, mode="turns")
            self.assertEqual(1, out1["ingested_count"])
            self.assertEqual(0, out1["skipped_existing_count"])
            self.assertEqual(0, out2["ingested_count"])
            self.assertEqual(1, out2["skipped_existing_count"])
            idx = json.loads((Path(td) / ".beads" / "index.json").read_text(encoding="utf-8"))
            beads = list((idx.get("beads") or {}).values())
            self.assertEqual(1, len(beads))
            self.assertEqual(["D1:1"], beads[0].get("source_turn_ids") or [])
            self.assertIn("sample_id=conv-1", beads[0].get("supporting_facts") or [])
            self.assertTrue(any("Alice: Hello there" in fact for fact in (beads[0].get("supporting_facts") or [])))
            turn = find_turn_record(root=Path(td), session_id="locomo:conv-1", turn_id="locomo:conv-1:D1:1")
            self.assertIsNotNone(turn)
            self.assertEqual("Alice: Hello there", turn.get("assistant_final"))
            self.assertEqual("D1:1", (turn.get("metadata") or {}).get("locomo_dia_id"))


if __name__ == "__main__":
    unittest.main()
