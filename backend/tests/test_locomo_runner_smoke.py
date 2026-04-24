import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Core-Memory"))

if importlib.util.find_spec("pydantic_settings") is not None:
    from app.benchmarks.locomo_suite import ingest_locomo_samples
else:
    ingest_locomo_samples = None


class TestLocomoRunnerSmoke(unittest.TestCase):
    def test_ingest_locomo_samples_returns_traceable_rows(self):
        if ingest_locomo_samples is None:
            self.skipTest("pydantic_settings unavailable")
        samples = [
            {
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
                            },
                            {
                                "sample_id": "conv-1",
                                "session_index": 1,
                                "turn_index": 2,
                                "dia_id": "D1:2",
                                "speaker": "Bob",
                                "text": "Hi back",
                                "session_date_time": "1 Jan 2024",
                            },
                        ],
                    }
                ],
                "qa": [],
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            out = ingest_locomo_samples(base_root=td, samples=samples, ingestion_mode="turns")
            self.assertEqual(1, out["samples"])
            self.assertEqual(2, out["turns_total"])
            self.assertEqual(2, out["ingested_turns"])
            row = out["rows"][0]["ingested"][0]
            self.assertEqual("D1:1", row["dia_id"])
            self.assertEqual("locomo:conv-1", row["session_id"])
            self.assertEqual("conv-1", row["trace"]["sample_id"])


if __name__ == "__main__":
    unittest.main()
