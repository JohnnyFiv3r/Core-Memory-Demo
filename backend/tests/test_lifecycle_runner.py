import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.contracts import (  # noqa: E402
    BenchmarkConversation,
    BenchmarkLifecycleError,
    BenchmarkQA,
    BenchmarkShortcutFlags,
    BenchmarkTurn,
)
from app.benchmarks.lifecycle_runner import (  # noqa: E402
    RETRIEVAL_EFFORT_ORDER,
    replay_conversation_turns,
    run_lifecycle_conversation,
    run_pre_qa_flush,
    run_qa_efforts,
)


def _conversation() -> BenchmarkConversation:
    return BenchmarkConversation(
        benchmark_name="locomo",
        conversation_id="locomo:conv-1",
        session_id="bench:locomo:conv-1:replay",
        turns=[
            BenchmarkTurn(
                turn_id="locomo:conv-1:D1:1:1",
                speaker="A",
                role="other",
                content="hi",
                metadata={"locomo_sample_id": "conv-1", "locomo_dia_id": "D1:1"},
            ),
            BenchmarkTurn(
                turn_id="locomo:conv-1:D1:2:2",
                speaker="B",
                role="other",
                content="hello",
                metadata={"locomo_sample_id": "conv-1", "locomo_dia_id": "D1:2"},
            ),
        ],
        qa_cases=[
            BenchmarkQA(
                qa_id="locomo:conv-1:q0001",
                question="Who said hi?",
                expected_answer="A",
                gold_evidence=["D1:1"],
                bucket_labels=("locomo_category_2",),
            )
        ],
    )


class TestLifecycleRunner(unittest.TestCase):
    def test_replay_calls_capture_once_per_turn(self):
        calls = []

        def fake_process_turn_finalized(**kwargs):
            calls.append(kwargs)
            return {"ok": True, "turn_id": kwargs["turn_id"]}

        with tempfile.TemporaryDirectory() as td:
            out = replay_conversation_turns(
                root=td,
                conversation=_conversation(),
                process_turn_finalized_fn=fake_process_turn_finalized,
            )

        self.assertTrue(out["ok"])
        self.assertEqual(2, out["turns_replayed"])
        self.assertEqual(2, out["capture_hook_calls"])
        self.assertEqual("BENCHMARK_REPLAY", calls[0]["origin"])
        self.assertEqual("conversation_replay", calls[0]["metadata"]["benchmark_phase"])
        self.assertEqual("locomo:conv-1:D1:1:1", calls[0]["metadata"]["source_turn_id"])

    def test_pre_qa_flush_runs_after_replay_boundary_shape(self):
        flush_calls = []
        async_calls = []

        def fake_flush(**kwargs):
            flush_calls.append(kwargs)
            return {"ok": True, "flush_tx_id": kwargs["flush_tx_id"]}

        def fake_async(**kwargs):
            async_calls.append(kwargs)
            return {"ok": True}

        with tempfile.TemporaryDirectory() as td:
            out = run_pre_qa_flush(
                root=td,
                conversation=_conversation(),
                process_flush_fn=fake_flush,
                run_async_jobs_fn=fake_async,
            )

        self.assertTrue(out["ran"])
        self.assertEqual("benchmark_pre_qa", flush_calls[0]["source"])
        self.assertEqual("bench-preqa:locomo:conv-1", flush_calls[0]["flush_tx_id"])
        self.assertTrue(async_calls)
        self.assertTrue(async_calls[0]["run_semantic"])

    def test_qa_efforts_run_low_medium_high_in_order(self):
        order = []

        def fake_recall(request, *, effort, root, explain, include_raw):
            order.append(effort)
            return {"planning": {"selected_effort": effort}, "request": request, "root": root}

        with tempfile.TemporaryDirectory() as td:
            out = run_qa_efforts(
                root=td,
                conversation=_conversation(),
                qa=_conversation().qa_cases[0],
                recall_fn=fake_recall,
            )

        self.assertEqual(list(RETRIEVAL_EFFORT_ORDER), order)
        self.assertEqual(list(RETRIEVAL_EFFORT_ORDER), out["retrieval_order"])
        self.assertEqual(set(RETRIEVAL_EFFORT_ORDER), set(out["efforts"].keys()))
        self.assertEqual("full_bead_corpus", out["efforts"]["low"]["request"]["constraints"]["recall_scope"])

    def test_qa_efforts_reject_wrong_order(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(BenchmarkLifecycleError, "retrieval effort order"):
                run_qa_efforts(
                    root=td,
                    conversation=_conversation(),
                    qa=_conversation().qa_cases[0],
                    recall_fn=lambda *args, **kwargs: {},
                    retrieval_efforts=("high",),
                )

    def test_lifecycle_conversation_orchestrates_replay_flush_qa_and_qa_bead(self):
        events = []

        def fake_process_turn_finalized(**kwargs):
            events.append((kwargs["origin"], kwargs["turn_id"]))
            return {"ok": True}

        def fake_flush(**kwargs):
            events.append(("flush", kwargs["flush_tx_id"]))
            return {"ok": True}

        def fake_async(**kwargs):
            events.append(("async", "drain"))
            return {"ok": True}

        def fake_recall(request, *, effort, root, explain, include_raw):
            events.append(("recall", effort))
            return {"answer": f"answer-{effort}", "warnings": []}

        with tempfile.TemporaryDirectory() as td:
            out = run_lifecycle_conversation(
                root=td,
                conversation=_conversation(),
                process_turn_finalized_fn=fake_process_turn_finalized,
                process_flush_fn=fake_flush,
                run_async_jobs_fn=fake_async,
                recall_fn=fake_recall,
            )

        self.assertTrue(out["ok"])
        self.assertEqual("locomo_native_lifecycle", out["dataset_mode"])
        self.assertTrue(out["lifecycle"]["lifecycle_faithful"])
        self.assertEqual(2, out["lifecycle"]["capture_hook_calls"])
        self.assertEqual(["low", "medium", "high"], out["cases"][0]["retrieval_order"])
        self.assertTrue(out["cases"][0]["qa_bead_written"])
        self.assertEqual("bench:locomo:conv-1:qa", out["qa_session_id"])
        self.assertEqual(
            [
                ("BENCHMARK_REPLAY", "locomo:conv-1:D1:1:1"),
                ("BENCHMARK_REPLAY", "locomo:conv-1:D1:2:2"),
                ("flush", "bench-preqa:locomo:conv-1"),
                ("async", "drain"),
                ("recall", "low"),
                ("recall", "medium"),
                ("recall", "high"),
                ("BENCHMARK_QA", "qa:locomo:conv-1:q0001"),
            ],
            events,
        )

    def test_lifecycle_conversation_rejects_shortcuts_in_faithful_mode(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(BenchmarkLifecycleError, "bead_direct_ingest"):
                run_lifecycle_conversation(
                    root=td,
                    conversation=_conversation(),
                    shortcut_flags=BenchmarkShortcutFlags(bead_direct_ingest=True),
                    process_turn_finalized_fn=lambda **kwargs: {"ok": True},
                    process_flush_fn=lambda **kwargs: {"ok": True},
                    run_async_jobs_fn=lambda **kwargs: {"ok": True},
                    recall_fn=lambda *args, **kwargs: {},
                    write_qa_beads=False,
                )


if __name__ == "__main__":
    unittest.main()
