import os
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
    lifecycle_corpus_warnings,
    replay_conversation_turns,
    run_lifecycle_conversation,
    run_locomo_lifecycle_suite,
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
    def test_lifecycle_corpus_warnings_report_missing_runtime_products(self):
        warnings = lifecycle_corpus_warnings(
            {"beads": 2, "associations": 0, "semantic_associations": 0, "entities": 0, "claims": 0},
            phase="after_replay",
        )

        self.assertIn("after_replay:no_associations_produced", warnings)
        self.assertIn("after_replay:no_claims_produced", warnings)
        self.assertIn("after_replay:no_entities_produced", warnings)

    def test_replay_calls_capture_once_per_turn(self):
        calls = []
        progress_events = []
        before_env = {
            "CORE_MEMORY_AGENT_CRAWLER_INVOKE": os.environ.get("CORE_MEMORY_AGENT_CRAWLER_INVOKE"),
            "CORE_MEMORY_AGENT_CRAWLER_CALLABLE": os.environ.get("CORE_MEMORY_AGENT_CRAWLER_CALLABLE"),
            "CORE_MEMORY_ENRICHMENT_QUEUE": os.environ.get("CORE_MEMORY_ENRICHMENT_QUEUE"),
        }

        def fake_process_turn_finalized(**kwargs):
            calls.append(kwargs)
            return {"ok": True, "turn_id": kwargs["turn_id"]}

        with tempfile.TemporaryDirectory() as td:
            out = replay_conversation_turns(
                root=td,
                conversation=_conversation(),
                process_turn_finalized_fn=fake_process_turn_finalized,
                progress=lambda completed, total, case, result: progress_events.append((completed, total, case, result)),
                progress_completed=4,
                progress_total=9,
                conversation_index=2,
                conversation_total=3,
            )

        self.assertTrue(out["ok"])
        self.assertEqual(2, out["turns_replayed"])
        self.assertEqual(2, out["capture_hook_calls"])
        self.assertIn("after_replay:no_associations_produced", out["warnings"])
        self.assertEqual("BENCHMARK_REPLAY", calls[0]["origin"])
        self.assertEqual("conversation_replay", calls[0]["metadata"]["benchmark_phase"])
        self.assertEqual("locomo", calls[0]["metadata"]["replay_source"])
        self.assertEqual("locomo:conv-1:D1:1:1", calls[0]["metadata"]["source_turn_id"])
        self.assertIn("crawler_updates", calls[0]["metadata"])
        self.assertEqual("locomo_lifecycle", calls[0]["metadata"]["_crawler_updates_source"])
        self.assertEqual(before_env, {
            "CORE_MEMORY_AGENT_CRAWLER_INVOKE": os.environ.get("CORE_MEMORY_AGENT_CRAWLER_INVOKE"),
            "CORE_MEMORY_AGENT_CRAWLER_CALLABLE": os.environ.get("CORE_MEMORY_AGENT_CRAWLER_CALLABLE"),
            "CORE_MEMORY_ENRICHMENT_QUEUE": os.environ.get("CORE_MEMORY_ENRICHMENT_QUEUE"),
        })
        self.assertEqual(4, progress_events[0][0])
        self.assertEqual(9, progress_events[0][1])
        self.assertEqual("conv-1", progress_events[0][2]["sample_id"])
        self.assertEqual("locomo_lifecycle", progress_events[0][3]["phase"])
        self.assertEqual(2, progress_events[0][3]["conversation_index"])
        self.assertEqual(3, progress_events[0][3]["conversations"])
        self.assertEqual(0, progress_events[0][3]["replay_turn_completed"])
        self.assertEqual(2, progress_events[0][3]["replay_turn_total"])
        self.assertEqual("locomo:conv-1:D1:1:1", progress_events[0][3]["turn_id"])
        self.assertEqual(2, progress_events[-1][3]["replay_turn_completed"])

    def test_replay_fails_if_crawler_invocation_is_disabled(self):
        def fake_process_turn_finalized(**kwargs):
            return {
                "ok": True,
                "crawler_handoff": {
                    "agent_authored_gate": {
                        "error_code": "agent_updates_missing",
                        "agent_invocation": {"reason": "invocation_disabled"},
                    }
                },
            }

        with tempfile.TemporaryDirectory() as td:
            out = replay_conversation_turns(
                root=td,
                conversation=_conversation(),
                process_turn_finalized_fn=fake_process_turn_finalized,
            )

        self.assertFalse(out["ok"])
        self.assertEqual("locomo_crawler_not_invoked", out["errors"][0]["error"])

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

    def test_qa_efforts_score_each_effort(self):
        conv = _conversation()
        qa = BenchmarkQA(
            qa_id="qa-1",
            question="who likes pizza?",
            expected_answer="Alice likes pizza",
            gold_evidence=["D1:1"],
            category="2",
            bucket_labels=(),
            metadata={"category": 2},
        )

        def fake_recall(request, *, effort, root, explain, include_raw):
            return {
                "answer": "Alice likes pizza" if effort == "high" else "Alice",
                "results": [{"bead_id": "b1", "dia_ids": ["D1:1"], "score": 0.9}],
            }

        with tempfile.TemporaryDirectory() as td:
            out = run_qa_efforts(root=td, conversation=conv, qa=qa, recall_fn=fake_recall)

        self.assertEqual(1.0, out["efforts"]["high"]["answer_f1"])
        self.assertEqual(1.0, out["efforts"]["high"]["evidence_recall"]["recall@5"])
        self.assertEqual(["D1:1"], out["efforts"]["high"]["retrieved"][0]["dia_ids"])

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
        self.assertIn("after_qa:no_associations_produced", out["warnings"])
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

    def test_lifecycle_conversation_isolated_qa_clones_post_flush_root_per_case(self):
        events = []

        def fake_process_turn_finalized(**kwargs):
            events.append((kwargs["origin"], kwargs["turn_id"], Path(kwargs["root"]).name))
            marker = Path(kwargs["root"]) / ".beads"
            marker.mkdir(parents=True, exist_ok=True)
            (marker / "index.json").write_text('{"beads":{},"associations":[]}', encoding="utf-8")
            return {"ok": True}

        def fake_recall(request, *, effort, root, explain, include_raw):
            events.append(("recall", effort, Path(root).name))
            return {"answer": f"answer-{effort}", "warnings": []}

        with tempfile.TemporaryDirectory() as td:
            out = run_lifecycle_conversation(
                root=td,
                conversation=_conversation(),
                qa_session_mode="isolated",
                process_turn_finalized_fn=fake_process_turn_finalized,
                process_flush_fn=lambda **kwargs: {"ok": True},
                run_async_jobs_fn=lambda **kwargs: {"ok": True},
                recall_fn=fake_recall,
            )

        self.assertTrue(out["ok"])
        self.assertEqual("isolated", out["lifecycle"]["qa_session_mode"])
        self.assertTrue(out["cases"][0]["isolated_qa"]["enabled"])
        self.assertNotEqual(td, out["cases"][0]["isolated_qa"]["root"])
        self.assertIn(":qa:", out["cases"][0]["qa_session_id"])
        recall_roots = [name for kind, _effort, name in events if kind == "recall"]
        self.assertEqual(1, len(set(recall_roots)))
        self.assertNotEqual(Path(td).name, recall_roots[0])

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

    def test_locomo_lifecycle_suite_filters_selected_qa_cases(self):
        events = []
        progress_events = []
        sample = {
            "sample_id": "conv-1",
            "sessions": [
                {
                    "session_index": 1,
                    "date_time": "1 Jan 2024",
                    "turns": [
                        {"dia_id": "D1:1", "speaker": "A", "text": "hi", "turn_index": 1},
                    ],
                }
            ],
            "qa": [
                {"qa_id": "conv-1:q0001", "question": "selected?", "answer": "yes", "category": 1, "evidence": ["D1:1"]},
                {"qa_id": "conv-1:q0002", "question": "not selected?", "answer": "no", "category": 1, "evidence": ["D1:1"]},
            ],
        }

        def fake_recall(request, *, effort, root, explain, include_raw):
            events.append(("recall", effort, request["constraints"]["qa_id"]))
            return {"answer": f"answer-{effort}", "warnings": []}

        with tempfile.TemporaryDirectory() as td:
            out = run_locomo_lifecycle_suite(
                root=td,
                samples=[sample],
                qa_cases=[{"qa_id": "conv-1:q0001"}],
                process_turn_finalized_fn=lambda **kwargs: {"ok": True},
                process_flush_fn=lambda **kwargs: {"ok": True},
                run_async_jobs_fn=lambda **kwargs: {"ok": True},
                recall_fn=fake_recall,
                write_qa_beads=False,
                progress=lambda completed, total, case, result: progress_events.append((completed, total, case.get("qa_id"), result.get("status"), result)),
            )

        self.assertTrue(out["ok"])
        self.assertEqual(1, out["lifecycle"]["conversations"])
        self.assertEqual(1, out["lifecycle"]["qa_cases"])
        self.assertIn("after_suite:no_associations_produced", out["warnings"])
        self.assertIn("corpus_after_replay", out)
        self.assertIn("corpus_after_pre_qa_flush", out)
        self.assertIn("corpus_after_qa", out)
        self.assertIn("per_conversation", out["corpus_snapshots"])
        self.assertEqual("locomo:conv-1", out["corpus_snapshots"]["per_conversation"][0]["conversation_id"])
        self.assertEqual(1, len(out["cases"]))
        self.assertEqual("locomo:conv-1:q0001", out["cases"][0]["qa_id"])
        self.assertIn("by_effort", out["scores"])
        self.assertEqual(
            [("recall", "low", "locomo:conv-1:q0001"), ("recall", "medium", "locomo:conv-1:q0001"), ("recall", "high", "locomo:conv-1:q0001")],
            events,
        )
        self.assertIn((0, 1, "locomo:conv-1:q0001", "retrieving", {"status": "retrieving", "phase": "lifecycle_qa", "conversation_id": "locomo:conv-1"}), progress_events)
        self.assertIn((1, 1, "locomo:conv-1:q0001", "ok", {"status": "ok", "phase": "lifecycle_qa", "conversation_id": "locomo:conv-1"}), progress_events)
        replay_progress = [evt for evt in progress_events if (evt[4] or {}).get("phase") == "locomo_lifecycle"]
        self.assertTrue(replay_progress)
        self.assertEqual(1, replay_progress[-1][4].get("replay_turn_completed"))


if __name__ == "__main__":
    unittest.main()
