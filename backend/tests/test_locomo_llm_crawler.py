import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks import locomo_llm_crawler as llm  # noqa: E402


def _payload():
    return {
        "root": "/tmp/x",
        "request": {
            "session_id": "bench:locomo:conv-1",
            "turn_id": "locomo:conv-1:D1:1",
            "turn_text": "Caroline decided to pursue counseling after the support group.",
            "user_query": "",
            "assistant_final": "",
            "metadata": {
                "replay_source": "locomo",
                "locomo_dia_id": "D1:1",
                "locomo_speaker": "Caroline",
                "locomo_session_date_time": "7 May 2023",
            },
        },
        "crawler_context": {"beads": []},
    }


class TestLocomoLLMCrawler(unittest.TestCase):
    def test_enriches_bead_with_llm_type_and_fields(self):
        async def fake_enrich(**kwargs):
            return {
                "type": "decision",
                "title": "Caroline decided to pursue counseling",
                "summary": ["Caroline chose a counseling career path."],
                "entities": ["Caroline", "counseling"],
                "because": ["the support group was powerful"],
                "state_change": "career path set to counseling",
                "effective_from": "2023-05-07",
                "observed_at": "7 May 2023",
            }

        with patch.object(llm, "_enrich_async", fake_enrich):
            out = llm.locomo_llm_crawler_callable(_payload(), model_id="openai:gpt-4o-mini")
        bead = out["beads_create"][0]
        self.assertEqual("decision", bead["type"])
        self.assertEqual("Caroline decided to pursue counseling", bead["title"])
        self.assertIn("the support group was powerful", bead["because"])
        self.assertEqual("career path set to counseling", bead["state_change"])
        self.assertEqual("2023-05-07", bead["effective_from"])
        self.assertIn("counseling", bead["entities"])
        self.assertIn("llm_enriched", bead["tags"])

    def test_invalid_type_coerces_to_context(self):
        async def fake_enrich(**kwargs):
            return {"type": "banana", "title": "x"}

        with patch.object(llm, "_enrich_async", fake_enrich):
            out = llm.locomo_llm_crawler_callable(_payload(), model_id="openai:gpt-4o-mini")
        self.assertEqual("context", out["beads_create"][0]["type"])

    def test_llm_failure_falls_back_to_deterministic_bead(self):
        async def boom(**kwargs):
            raise RuntimeError("llm down")

        with patch.object(llm, "_enrich_async", boom):
            out = llm.locomo_llm_crawler_callable(_payload(), model_id="openai:gpt-4o-mini")
        # Deterministic base bead is type 'context' and the turn is never dropped.
        self.assertEqual("context", out["beads_create"][0]["type"])

    def test_no_model_returns_deterministic_base(self):
        out = llm.locomo_llm_crawler_callable(_payload(), model_id="")
        self.assertEqual("context", out["beads_create"][0]["type"])

    def test_non_locomo_payload_passes_through(self):
        p = _payload()
        p["request"]["metadata"]["replay_source"] = "other"
        out = llm.locomo_llm_crawler_callable(p, model_id="openai:gpt-4o-mini")
        # Deterministic crawler returns {} for non-locomo; nothing to enrich.
        self.assertEqual({}, out)


if __name__ == "__main__":
    unittest.main()
