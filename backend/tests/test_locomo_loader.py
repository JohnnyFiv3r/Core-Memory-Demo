import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_loader import LocomoLoaderError, load_locomo_dataset


class TestLocomoLoader(unittest.TestCase):
    def test_loader_rejects_missing_dataset(self):
        with self.assertRaises(LocomoLoaderError):
            load_locomo_dataset(data_file="/tmp/definitely-missing-locomo.json")

    def test_loader_validates_tiny_fixture_shape(self):
        payload = [
            {
                "sample_id": "conv-1",
                "conversation": {
                    "speaker_a": "A",
                    "speaker_b": "B",
                    "session_1": [{"speaker": "A", "dia_id": "D1:1", "text": "hi"}],
                    "session_1_date_time": "1 Jan 2024",
                },
                "qa": [{"question": "q", "answer": "a", "category": 2, "evidence": ["D1:1"]}],
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tiny.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(LocomoLoaderError):
                load_locomo_dataset(data_file=path)


if __name__ == "__main__":
    unittest.main()
