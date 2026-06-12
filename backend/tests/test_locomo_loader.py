import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_loader import (
    LocomoLoaderError,
    compose_locomo_turn_content,
    load_locomo_dataset,
)


class TestComposeLocomoTurnContent(unittest.TestCase):
    def test_folds_session_date_and_caption_into_content(self):
        # The bead judge and the embedding index only see turn content, never
        # metadata. Without this, the session date (most cat-2 temporal golds)
        # and the image caption (gold evidence for 45% of scored QA) are
        # unretrievable.
        content = compose_locomo_turn_content(
            text="Check out this little guy!",
            session_date_time="1:56 pm on 8 May, 2023",
            blip_caption="a samoyed puppy on a beach",
        )
        self.assertEqual(
            "Session date: 1:56 pm on 8 May, 2023\n\n"
            "Check out this little guy!\n\n"
            "Image caption: a samoyed puppy on a beach",
            content,
        )

    def test_text_only_turn_is_unchanged(self):
        self.assertEqual("hello", compose_locomo_turn_content(text="hello"))


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
