import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.locomo_answer import generate_locomo_answer, validate_required_tool_phases


class _FakeAgentResult:
    output = '```json\n{"answer":"7 May 2023","used_dia_ids":["D1:3"],"confidence":"high","unsupported":false}\n```'

    def all_messages(self):
        return [
            {"parts": [{"tool_name": "search_memory", "args": {"query": "When?"}}]},
            {"parts": [{"tool_name": "trace_memory", "args": {"query": "When?", "max_depth": 6}}]},
            {"parts": [{"tool_name": "hydrate_sources", "args": {"bead_ids_json": "[]"}}]},
        ]


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

    def test_extractive_mode_answers_from_claim_value(self):
        out = generate_locomo_answer(
            mode="extractive",
            qa={"question": "What kind of car does Evan drive?"},
            retrieved_context=[
                {
                    "source_surface": "claim_state",
                    "claim_value": "blue bicycle",
                    "claim_slot_key": "Evan:vehicle",
                    "snippet": "Evan rides a blue bicycle",
                    "dia_ids": ["D1:2"],
                    "score": 0.9,
                }
            ],
        )
        self.assertEqual("blue bicycle", out["answer"])
        self.assertEqual(["D1:2"], out["used_dia_ids"])

    def test_oracle_context_mode_is_disabled_for_scored_benchmarks(self):
        with self.assertRaisesRegex(ValueError, "oracle_context_answer_mode_disabled"):
            generate_locomo_answer(
                mode="oracle_context",
                qa={"gold_answer": "7 May 2023"},
                retrieved_context=[],
            )

    def test_llm_mode_uses_memory_tools_and_requires_tool_phases(self):
        with patch("app.benchmarks.locomo_answer.Agent") as Agent, \
             patch("app.benchmarks.locomo_answer.memory_execute_tool", return_value=lambda: None), \
             patch("app.benchmarks.locomo_answer.memory_search_tool", return_value=lambda: None), \
             patch("app.benchmarks.locomo_answer.memory_trace_tool", return_value=lambda: None), \
             patch("app.benchmarks.locomo_answer.hydrate_bead_sources_tool", return_value=lambda: None):
            agent = Agent.return_value
            agent.run = AsyncMock(return_value=_FakeAgentResult())
            out = generate_locomo_answer(
                mode="llm",
                root="/tmp/fake",
                sample_id="conv-1",
                qa={"question": "When?"},
                retrieved_context=[{"text": "Caroline went on 7 May 2023", "dia_ids": ["D1:3"]}],
                generator_model="openai:gpt-4o-mini",
            )
        Agent.assert_called_once()
        self.assertEqual(4, len(Agent.call_args.kwargs.get("tools") or []))
        self.assertEqual("7 May 2023", out["answer"])
        self.assertEqual(["D1:3"], out["used_dia_ids"])
        self.assertEqual("high", out["confidence"])
        self.assertFalse(out["unsupported"])
        self.assertTrue(out["tool_phase_validation"]["ok"])
        self.assertEqual(["search_memory", "trace_memory", "hydrate_sources"], out["tool_phase_validation"]["tool_names"])

    def test_llm_mode_reconciles_non_dataset_used_ids_back_to_retrieved_dia_ids(self):
        class FakeBadIdResult(_FakeAgentResult):
            output = '```json\n{"answer":"7 May 2023","used_dia_ids":["turn-abc123"],"confidence":"high","unsupported":false}\n```'

        with patch("app.benchmarks.locomo_answer.Agent") as Agent, \
             patch("app.benchmarks.locomo_answer.memory_execute_tool", return_value=lambda: None), \
             patch("app.benchmarks.locomo_answer.memory_search_tool", return_value=lambda: None), \
             patch("app.benchmarks.locomo_answer.memory_trace_tool", return_value=lambda: None), \
             patch("app.benchmarks.locomo_answer.hydrate_bead_sources_tool", return_value=lambda: None):
            agent = Agent.return_value
            agent.run = AsyncMock(return_value=FakeBadIdResult())
            out = generate_locomo_answer(
                mode="llm",
                root="/tmp/fake",
                sample_id="conv-1",
                qa={"question": "When?"},
                retrieved_context=[{"text": "Caroline went on 7 May 2023", "dia_ids": ["D1:3", "D1:4"]}],
                generator_model="openai:gpt-4o-mini",
            )
        self.assertEqual(["D1:3", "D1:4"], out["used_dia_ids"])

    def test_required_tool_phase_validation_rejects_search_trace_only(self):
        out = validate_required_tool_phases([
            {"tool_name": "search_memory"},
            {"tool_name": "trace_memory"},
        ])
        self.assertFalse(out["ok"])
        self.assertEqual("required_tool_phase_missing", out["error"])
        self.assertEqual(["hydrate"], out["missing"])

    def test_required_tool_phase_validation_rejects_answer_before_hydration_order(self):
        out = validate_required_tool_phases([
            {"tool_name": "search_memory"},
            {"tool_name": "hydrate_sources"},
            {"tool_name": "trace_memory"},
        ])
        self.assertFalse(out["ok"])
        self.assertEqual("required_tool_phase_order_invalid", out["error"])


if __name__ == "__main__":
    unittest.main()

    def test_recall_llm_mode_answers_from_recall_evidence_without_tools(self):
        class FakeRecallResult(_FakeAgentResult):
            output = '{"answer":"7 May 2023","used_dia_ids":["D1:3"],"confidence":"high","unsupported":false}'

        with patch("app.benchmarks.locomo_answer.Agent") as Agent:
            agent = Agent.return_value
            agent.run = AsyncMock(return_value=FakeRecallResult())
            out = generate_locomo_answer(
                mode="recall_llm",
                qa={"question": "When did Caroline go?"},
                retrieved_context=[{"text": "Caroline went on 7 May 2023", "dia_ids": ["D1:3"], "score": 0.9}],
                generator_model="openai:gpt-4o-mini",
            )
        Agent.assert_called_once()
        # No second retrieval pass: the answerer gets no memory tools, only the
        # evidence the scored recall() already returned (inlined in the prompt).
        self.assertNotIn("tools", Agent.call_args.kwargs)
        prompt = agent.run.call_args.args[0]
        self.assertIn("Caroline went on 7 May 2023", prompt)
        self.assertEqual("7 May 2023", out["answer"])
        self.assertEqual(["D1:3"], out["used_dia_ids"])
        self.assertEqual("recall_evidence", out["answer_source"])
        self.assertNotIn("tool_phase_validation", out)

    def test_recall_llm_mode_abstains_on_empty_context_without_llm_call(self):
        with patch("app.benchmarks.locomo_answer.Agent") as Agent:
            out = generate_locomo_answer(
                mode="recall_llm",
                qa={"question": "When?"},
                retrieved_context=[],
                generator_model="openai:gpt-4o-mini",
            )
        Agent.assert_not_called()
        self.assertEqual("No information available", out["answer"])
        self.assertTrue(out["unsupported"])
