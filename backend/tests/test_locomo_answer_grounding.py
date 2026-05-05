import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_answer import generate_locomo_answer


class TestLocomoAnswerGrounding(unittest.TestCase):
    def test_extractive_abstains_when_retrieval_is_weak(self):
        out = generate_locomo_answer(
            mode="extractive",
            qa={"question": "What happened?"},
            retrieved_context=[
                {
                    "score": 0.0,
                    "locomo_score": 0.0,
                    "dia_ids": [],
                    "text": "",
                }
            ],
        )
        self.assertEqual("No information available", out["answer"])
        self.assertTrue(out["unsupported"])
        self.assertEqual([], out["used_dia_ids"])

    def test_llm_abstains_before_agent_call_when_support_is_weak(self):
        with patch("app.benchmarks.locomo_answer.run_agent_for_root") as runner:
            out = generate_locomo_answer(
                mode="llm",
                root="/tmp/fake",
                sample_id="conv-1",
                qa={"question": "What happened?"},
                generator_model="fake-model",
                retrieved_context=[
                    {
                        "score": 0.0,
                        "locomo_score": 0.0,
                        "dia_ids": [],
                        "text": "",
                    }
                ],
            )
        runner.assert_not_called()
        self.assertEqual("No information available", out["answer"])
        self.assertTrue(out["unsupported"])

    def test_llm_uses_bounded_retrieved_context_prompt(self):
        async def _fake_runner(**kwargs):
            return {
                "assistant": '{"answer":"7 May 2023","used_dia_ids":["D1:3"],"confidence":"high","unsupported":false}'
            }

        with patch("app.benchmarks.locomo_answer.run_agent_for_root", side_effect=_fake_runner) as runner:
            out = generate_locomo_answer(
                mode="llm",
                root="/tmp/fake",
                sample_id="conv-1",
                qa={"question": "When did Caroline go to the support group?"},
                generator_model="fake-model",
                retrieved_context=[
                    {
                        "score": 1.0,
                        "locomo_score": 2.0,
                        "dia_ids": ["D1:3"],
                        "speaker": "Alice",
                        "session_date_time": "7 May 2023",
                        "text": "Caroline went to the support group on 7 May 2023",
                    }
                ],
            )
        self.assertEqual("7 May 2023", out["answer"])
        self.assertEqual(["D1:3"], out["used_dia_ids"])
        called = runner.call_args.kwargs
        self.assertIn("Retrieved evidence:", str(called.get("message") or ""))
        self.assertIn("Only answer from the supplied retrieved evidence block", str(called.get("instruction_prefix") or ""))


if __name__ == "__main__":
    unittest.main()
