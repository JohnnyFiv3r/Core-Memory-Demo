import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Core-Memory"))

from unittest.mock import patch

from app.benchmarks.locomo_ingest import build_turn_bead, ingest_locomo_turns


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


if __name__ == "__main__":
    unittest.main()
