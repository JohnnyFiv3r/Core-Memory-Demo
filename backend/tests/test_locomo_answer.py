import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_answer import generate_locomo_answer


class TestLocomoAnswer(unittest.TestCase):
    def test_normalize_answer_payload_handles_fenced_json(self):
        from app.benchmarks.locomo_answer import _normalize_answer_payload

        out = _normalize_answer_payload(
            '```json\n{"answer":"7 May 2023","used_dia_ids":["D1:3"],"confidence":"high","unsupported":false}\n```'
        )
        self.assertEqual("7 May 2023", out["answer"])
        self.assertEqual(["D1:3"], out["used_dia_ids"])
        self.assertEqual("high", out["confidence"])
        self.assertFalse(out["unsupported"])

    def test_none_mode(self):
        out = generate_locomo_answer(mode="none", qa={}, retrieved_context=[])
        self.assertEqual("", out["answer"])
        self.assertTrue(out["unsupported"])

    def test_extractive_mode(self):
        out = generate_locomo_answer(
            mode="extractive",
            qa={},
            retrieved_context=[{"text": "Caroline went on 7 May 2023", "dia_ids": ["D1:3"]}],
        )
        self.assertIn("7 May 2023", out["answer"])
        self.assertEqual(["D1:3"], out["used_dia_ids"])

    def test_oracle_context_mode(self):
        out = generate_locomo_answer(
            mode="oracle_context",
            qa={"gold_answer": "7 May 2023"},
            retrieved_context=[],
            gold_context=[{"dia_ids": ["D1:3"], "text": "Caroline went to the support group on 7 May 2023"}],
        )
        self.assertIn("7 May 2023", out["answer"])
        self.assertEqual(["D1:3"], out["used_dia_ids"])

    def test_llm_mode_uses_shared_demo_agent_path(self):
        with patch("app.benchmarks.locomo_answer.run_agent_for_root") as run_agent:
            run_agent.return_value = {
                "ok": True,
                "assistant": '```json\n{"answer":"7 May 2023","used_dia_ids":["D1:3"],"confidence":"high","unsupported":false}\n```',
                "model_id": "openai:gpt-4o-mini",
            }
            out = generate_locomo_answer(
                mode="llm",
                root="/tmp/fake",
                sample_id="conv-1",
                qa={"question": "When?"},
                retrieved_context=[{"text": "Caroline went on 7 May 2023", "dia_ids": ["D1:3"]}],
                generator_model="openai:gpt-4o-mini",
            )
        self.assertEqual("7 May 2023", out["answer"])
        self.assertEqual(["D1:3"], out["used_dia_ids"])
        self.assertEqual("high", out["confidence"])
        self.assertFalse(out["unsupported"])

    def test_llm_mode_reconciles_non_dataset_used_ids_back_to_retrieved_dia_ids(self):
        with patch("app.benchmarks.locomo_answer.run_agent_for_root") as run_agent:
            run_agent.return_value = {
                "ok": True,
                "assistant": '```json\n{"answer":"7 May 2023","used_dia_ids":["turn-abc123"],"confidence":"high","unsupported":false}\n```',
                "model_id": "openai:gpt-4o-mini",
            }
            out = generate_locomo_answer(
                mode="llm",
                root="/tmp/fake",
                sample_id="conv-1",
                qa={"question": "When?"},
                retrieved_context=[{"text": "Caroline went on 7 May 2023", "dia_ids": ["D1:3", "D1:4"]}],
                generator_model="openai:gpt-4o-mini",
            )
        self.assertEqual(["D1:3", "D1:4"], out["used_dia_ids"])


if __name__ == "__main__":
    unittest.main()
