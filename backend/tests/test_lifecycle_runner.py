import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


def _write_judged_bead(root: str | Path, *, bead_id: str = "bead-judge-1", session_id: str = "bench:locomo:conv-1:replay", turn_id: str = "locomo:conv-1:D1:1:1", dia_id: str = "D1:1") -> None:
    """Seed a minimal judge-authored bead in tests that mock Core Memory.

    Production code now fails closed when judge mode produces zero claims. Unit
    tests that replace process_turn_finalized with a no-op must still model the
    native judge's observable artifact instead of accidentally testing a silent
    fallback path.
    """
    beads_dir = Path(root) / ".beads"
    beads_dir.mkdir(parents=True, exist_ok=True)
    idx_path = beads_dir / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {"beads": {}, "associations": []}
    idx.setdefault("beads", {})[bead_id] = {
        "id": bead_id,
        "session_id": session_id,
        "source_turn_ids": [turn_id, dia_id],
        "claims": [{"text": "A said hi.", "confidence": 1.0}],
    }
    idx_path.write_text(json.dumps(idx), encoding="utf-8")


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
        self.assertNotIn("crawler_updates", calls[0]["metadata"])
        self.assertEqual("llm", calls[0]["metadata"]["bead_judge"])
        self.assertEqual("native_judge", calls[0]["metadata"]["_crawler_updates_source"])
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

    def test_replay_accepts_missing_agent_updates_because_native_judge_authors_beads(self):
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

        self.assertTrue(out["ok"])
        self.assertEqual([], out["errors"])

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
        self.assertEqual(2, len(async_calls))
        self.assertTrue(async_calls[0]["run_semantic"])
        self.assertTrue(async_calls[1]["run_semantic"])
        self.assertEqual({"ok": True}, out["pre_flush_drain"])
        self.assertEqual({"ok": True}, out["post_flush_drain"])

    def test_qa_efforts_default_to_single_high_effort_recall(self):
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

        self.assertEqual(["high"], order)
        self.assertEqual(["high"], out["retrieval_order"])
        self.assertEqual({"high"}, set(out["efforts"].keys()))
        self.assertEqual("full_bead_corpus", out["efforts"]["high"]["request"]["constraints"]["recall_scope"])

    def test_qa_efforts_run_explicit_low_medium_high_in_order(self):
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
                retrieval_efforts=RETRIEVAL_EFFORT_ORDER,
            )

        self.assertEqual(list(RETRIEVAL_EFFORT_ORDER), order)
        self.assertEqual(list(RETRIEVAL_EFFORT_ORDER), out["retrieval_order"])
        self.assertEqual(set(RETRIEVAL_EFFORT_ORDER), set(out["efforts"].keys()))
        self.assertEqual("full_bead_corpus", out["efforts"]["low"]["request"]["constraints"]["recall_scope"])

    def test_qa_efforts_reject_wrong_order_and_missing_high(self):
        with tempfile.TemporaryDirectory() as td:
            for bad in (("high", "low"), ("medium", "low", "high"), ("low",), ()):
                with self.assertRaisesRegex(BenchmarkLifecycleError, "retrieval efforts"):
                    run_qa_efforts(
                        root=td,
                        conversation=_conversation(),
                        qa=_conversation().qa_cases[0],
                        recall_fn=lambda *args, **kwargs: {},
                        retrieval_efforts=bad,
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

    def test_qa_efforts_generates_high_effort_answer_when_configured(self):
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
            return {"raw": {"results": [{"bead_id": "b1", "dia_ids": ["D1:1"], "snippet": "Alice likes pizza."}]}}

        with tempfile.TemporaryDirectory() as td, patch(
            "app.benchmarks.lifecycle_runner.generate_locomo_answer",
            return_value={"answer": "Alice likes pizza", "used_dia_ids": ["D1:1"], "confidence": "high", "unsupported": False},
        ) as answerer:
            out = run_qa_efforts(root=td, conversation=conv, qa=qa, recall_fn=fake_recall, retrieval_efforts=RETRIEVAL_EFFORT_ORDER, answer_mode="llm", generator_model="test:model")

        self.assertEqual(1, answerer.call_count)
        self.assertEqual(1.0, out["efforts"]["high"]["answer_f1"])
        self.assertEqual(0.0, out["efforts"]["low"]["answer_f1"])
        self.assertEqual("Alice likes pizza", out["efforts"]["high"]["prediction"])
        self.assertEqual("Alice likes pizza", out["efforts"]["high"]["result"]["answer"])

    def test_qa_efforts_score_raw_recall_rows(self):
        conv = _conversation()
        qa = BenchmarkQA(
            qa_id="qa-1",
            question="when did Caroline go?",
            expected_answer="7 May 2023",
            gold_evidence=["D1:3"],
            category="2",
            bucket_labels=(),
            metadata={"category": 2},
        )

        def fake_recall(request, *, effort, root, explain, include_raw):
            return {
                "status": "partial",
                "raw": {
                    "results": [
                        {
                            "bead_id": "bead-1",
                            "dia_ids": ["D1:3"],
                            "score": 0.9,
                            "snippet": "Caroline went to the LGBTQ support group.",
                        }
                    ]
                },
            }

        with tempfile.TemporaryDirectory() as td:
            out = run_qa_efforts(root=td, conversation=conv, qa=qa, recall_fn=fake_recall)

        self.assertEqual(1.0, out["efforts"]["high"]["evidence_recall"]["recall@5"])
        self.assertEqual(["D1:3"], out["efforts"]["high"]["retrieved"][0]["dia_ids"])

    def test_qa_efforts_hydrates_full_bead_and_turn_transcript_for_answer_generation(self):
        conv = _conversation()
        qa = BenchmarkQA(
            qa_id="qa-1",
            question="when did Caroline go?",
            expected_answer="7 May 2023",
            gold_evidence=["D1:3"],
            category="2",
            bucket_labels=(),
            metadata={"category": 2},
        )

        def fake_recall(request, *, effort, root, explain, include_raw):
            return {"raw": {"results": [{"bead_id": "bead-1", "score": 0.9, "metadata": {"dia_ids": ["D1:3"]}}]}}

        def fake_hydrate(**kwargs):
            return {
                "beads": [{"id": "bead-1", "source_turn_ids": ["turn-1"]}],
                "hydrated": [
                    {
                        "turn": {
                            "turn_id": "turn-1",
                            "metadata": {"locomo_session_date_time": "4:04 pm on 8 May, 2023"},
                            "turns": [{"speaker": "Caroline", "role": "other", "content": "I went to a LGBTQ support group yesterday."}],
                        }
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as td:
            index_dir = Path(td) / ".beads"
            index_dir.mkdir(parents=True)
            (index_dir / "index.json").write_text(
                '{"beads":{"bead-1":{"id":"bead-1","title":"Caroline went to support group","source_turn_ids":["turn-1"],"type":"context"}}}',
                encoding="utf-8",
            )
            with patch("app.benchmarks.lifecycle_runner.hydrate_bead_sources", side_effect=fake_hydrate), patch(
                "app.benchmarks.lifecycle_runner.generate_locomo_answer",
                return_value={"answer": "7 May 2023", "used_dia_ids": ["D1:3"], "confidence": "high", "unsupported": False},
            ) as answerer:
                out = run_qa_efforts(root=td, conversation=conv, qa=qa, recall_fn=fake_recall, answer_mode="llm", generator_model="test:model")

        retrieved_context = answerer.call_args.kwargs["retrieved_context"]
        self.assertEqual("Caroline went to support group", retrieved_context[0]["bead"]["title"])
        self.assertIn("Caroline: I went to a LGBTQ support group yesterday.", retrieved_context[0]["turn_transcript"])
        self.assertEqual("4:04 pm on 8 May, 2023", retrieved_context[0]["session_date_time"])
        self.assertEqual("Caroline: I went to a LGBTQ support group yesterday.", retrieved_context[0]["text"])
        self.assertEqual(1.0, out["efforts"]["high"]["answer_f1"])

    def test_qa_efforts_preserves_metadata_snippet_for_answer_generation(self):
        conv = _conversation()
        qa = BenchmarkQA(
            qa_id="qa-1",
            question="when did Caroline go?",
            expected_answer="7 May 2023",
            gold_evidence=["D1:3"],
            category="2",
            bucket_labels=(),
            metadata={"category": 2},
        )

        def fake_recall(request, *, effort, root, explain, include_raw):
            return {
                "raw": {
                    "results": [
                        {
                            "bead_id": "bead-1",
                            "score": 0.9,
                            "metadata": {
                                "dia_ids": ["D1:3"],
                                "snippet": "Caroline went to the LGBTQ support group yesterday.",
                            },
                        }
                    ]
                }
            }

        with tempfile.TemporaryDirectory() as td, patch(
            "app.benchmarks.lifecycle_runner.generate_locomo_answer",
            return_value={"answer": "7 May 2023", "used_dia_ids": ["D1:3"], "confidence": "high", "unsupported": False},
        ) as answerer:
            out = run_qa_efforts(root=td, conversation=conv, qa=qa, recall_fn=fake_recall, answer_mode="llm", generator_model="test:model")

        retrieved_context = answerer.call_args.kwargs["retrieved_context"]
        self.assertEqual("Caroline went to the LGBTQ support group yesterday.", retrieved_context[0]["snippet"])
        self.assertEqual(1.0, out["efforts"]["high"]["answer_f1"])

    def test_lifecycle_conversation_orchestrates_replay_flush_qa_and_qa_bead(self):
        events = []

        def fake_process_turn_finalized(**kwargs):
            events.append((kwargs["origin"], kwargs["turn_id"]))
            _write_judged_bead(kwargs["root"], session_id=kwargs["session_id"], turn_id=kwargs["turn_id"], dia_id=str((kwargs.get("metadata") or {}).get("locomo_dia_id") or "D1:1"))
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
        self.assertEqual(["high"], out["cases"][0]["retrieval_order"])
        self.assertTrue(out["cases"][0]["qa_bead_written"])
        self.assertIn("after_qa:no_associations_produced", out["warnings"])
        self.assertEqual("bench:locomo:conv-1:qa", out["qa_session_id"])
        self.assertEqual(
            [
                ("BENCHMARK_REPLAY", "locomo:conv-1:D1:1:1"),
                ("BENCHMARK_REPLAY", "locomo:conv-1:D1:2:2"),
                ("async", "drain"),
                ("flush", "bench-preqa:locomo:conv-1"),
                ("async", "drain"),
                ("recall", "high"),
                ("BENCHMARK_QA", "qa:locomo:conv-1:q0001"),
            ],
            events,
        )

    def test_qa_only_seeded_conversation_does_not_replay_or_flush_seeded_corpus(self):
        def fail_process_turn_finalized(**kwargs):
            raise AssertionError("QA-only seeded benchmark must not replay turns or write QA beads in this test")

        def fail_flush(**kwargs):
            raise AssertionError("QA-only seeded benchmark must not run pre-QA flush")

        def fake_recall(request, *, effort, root, explain, include_raw):
            return {"answer": "A", "warnings": [], "raw": {"results": []}}

        with tempfile.TemporaryDirectory() as td:
            _write_judged_bead(td)
            out = run_lifecycle_conversation(
                root=td,
                conversation=_conversation(),
                qa_only_seeded=True,
                process_turn_finalized_fn=fail_process_turn_finalized,
                process_flush_fn=fail_flush,
                recall_fn=fake_recall,
                write_qa_beads=False,
            )

        self.assertTrue(out["ok"])
        self.assertTrue(out["replay"]["skipped_replay"])
        self.assertEqual("eligible_seed_record", out["replay"]["replay_source"])
        self.assertFalse(out["pre_qa_flush"]["ran"])
        self.assertEqual("eligible_seed_record", out["pre_qa_flush"]["source"])
        self.assertTrue(out["lifecycle"]["qa_only_seeded"])
        self.assertEqual(0, out["lifecycle"]["turns_replayed"])
        self.assertEqual(2, out["lifecycle"]["seeded_turns"])

    def test_required_tool_phase_failure_is_per_qa_not_fatal(self):
        # A tool-phase violation fails closed for THAT question (recorded as an
        # unanswered tool-phase failure) but must not abort the run or discard the
        # report.
        from app.benchmarks.locomo_answer import RequiredToolPhaseError

        def fake_recall(request, *, effort, root, explain, include_raw):
            return {"answer": f"answer-{effort}", "warnings": [], "raw": {"results": []}}

        with tempfile.TemporaryDirectory() as td, \
             patch(
                 "app.benchmarks.lifecycle_runner.generate_locomo_answer",
                 side_effect=RequiredToolPhaseError({"ok": False, "error": "required_tool_phase_missing", "missing": ["hydrate"]}),
             ):
            out = run_qa_efforts(
                root=td,
                conversation=_conversation(),
                qa=_conversation().qa_cases[0],
                recall_fn=fake_recall,
                answer_mode="llm",
                generator_model="test:model",
            )
        high = out["efforts"]["high"]
        self.assertTrue(high.get("tool_phase_failed"))
        self.assertTrue(high.get("answer_scored"))
        self.assertEqual("", high.get("prediction"))
        self.assertEqual(["hydrate"], (high.get("tool_phase_validation") or {}).get("missing"))

    def test_lifecycle_conversation_recovers_recall_from_bead_dia_map(self):
        # Regression: retrieval rows that carry only a bead_id (no surfaced
        # dia_id) used to score evidence recall as zero. The bead_id -> dia_id
        # map built from the index after replay must recover recall.
        import json

        def fake_process_turn_finalized(**kwargs):
            root = Path(kwargs["root"])
            beads_dir = root / ".beads"
            beads_dir.mkdir(parents=True, exist_ok=True)
            idx_path = beads_dir / "index.json"
            idx = json.loads(idx_path.read_text()) if idx_path.exists() else {"beads": {}}
            turn_id = kwargs["turn_id"]
            dia = str((kwargs.get("metadata") or {}).get("locomo_dia_id") or "")
            bead_id = f"bead-{dia.replace(':', '-')}"
            idx["beads"][bead_id] = {
                "id": bead_id,
                "session_id": kwargs["session_id"],
                # Demo convention: source_turn_ids carries [turn_id, dia_id].
                "source_turn_ids": [turn_id, dia],
                "claims": [{"text": "A said hi.", "confidence": 1.0}],
            }
            idx_path.write_text(json.dumps(idx), encoding="utf-8")
            return {"ok": True}

        def fake_recall(request, *, effort, root, explain, include_raw):
            # Rows expose ONLY a bead_id — the historical failure mode.
            return {"answer": f"answer-{effort}", "warnings": [], "raw": {"results": [{"bead_id": "bead-D1-1"}]}}

        with tempfile.TemporaryDirectory() as td:
            out = run_lifecycle_conversation(
                root=td,
                conversation=_conversation(),  # gold_evidence=["D1:1"]
                process_turn_finalized_fn=fake_process_turn_finalized,
                process_flush_fn=lambda **kwargs: {"ok": True},
                run_async_jobs_fn=lambda **kwargs: {"ok": True},
                recall_fn=fake_recall,
            )

        self.assertGreaterEqual(out["lifecycle"]["dia_bead_map_size"], 1)
        high = out["cases"][0]["efforts"]["high"]
        self.assertEqual(["D1:1"], high["retrieved_dia_ids"])
        self.assertEqual(1.0, high["evidence_recall"]["recall@5"])
        self.assertTrue(high["evidence_recall"]["hit_any"])

    def test_lifecycle_conversation_isolated_qa_clones_post_flush_root_per_case(self):
        events = []

        def fake_process_turn_finalized(**kwargs):
            events.append((kwargs["origin"], kwargs["turn_id"], Path(kwargs["root"]).name))
            marker = Path(kwargs["root"]) / ".beads"
            marker.mkdir(parents=True, exist_ok=True)
            _write_judged_bead(kwargs["root"], session_id=kwargs["session_id"], turn_id=kwargs["turn_id"], dia_id=str((kwargs.get("metadata") or {}).get("locomo_dia_id") or "D1:1"))
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

        def fake_process_turn_finalized(**kwargs):
            _write_judged_bead(kwargs["root"], session_id=kwargs["session_id"], turn_id=kwargs["turn_id"], dia_id=str((kwargs.get("metadata") or {}).get("locomo_dia_id") or "D1:1"))
            return {"ok": True}

        with tempfile.TemporaryDirectory() as td:
            out = run_locomo_lifecycle_suite(
                root=td,
                samples=[sample],
                qa_cases=[{"qa_id": "conv-1:q0001"}],
                process_turn_finalized_fn=fake_process_turn_finalized,
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
            [("recall", "high", "locomo:conv-1:q0001")],
            events,
        )
        self.assertIn((0, 1, "locomo:conv-1:q0001", "retrieving", {"status": "retrieving", "phase": "lifecycle_qa", "conversation_id": "locomo:conv-1"}), progress_events)
        # The post-QA "ok" event carries the live summary (question + generated
        # answer) so the demo can echo each QA into the chat as it runs.
        ok_events = [e for e in progress_events if e[0] == 1 and e[3] == "ok"]
        self.assertTrue(ok_events)
        ok_payload = ok_events[-1][4]
        self.assertEqual("lifecycle_qa", ok_payload["phase"])
        self.assertEqual("selected?", ok_payload["question"])
        self.assertEqual("answer-high", ok_payload["answer"])
        self.assertIn("evidence_bead_ids", ok_payload)
        replay_progress = [evt for evt in progress_events if (evt[4] or {}).get("phase") == "locomo_lifecycle"]
        self.assertTrue(replay_progress)
        self.assertEqual(1, replay_progress[-1][4].get("replay_turn_completed"))



class TestLifecycleAggregateVacuousExclusion(unittest.TestCase):
    def test_vacuous_and_excluded_rows_do_not_inflate_aggregate(self):
        from app.benchmarks.lifecycle_runner import aggregate_lifecycle_effort_scores

        cases = [
            # Annotated case: real miss -> recall@5 0.0, not vacuous.
            {"efforts": {"high": {
                "answer_f1": 0.0, "latency_ms": 1.0, "excluded": False,
                "evidence_recall": {"recall@5": 0.0, "hit_any": False, "vacuous": False},
            }}},
            # Vacuous case (no gold evidence): recall@5 1.0 but must be excluded.
            {"efforts": {"high": {
                "answer_f1": 1.0, "latency_ms": 1.0, "excluded": False,
                "evidence_recall": {"recall@5": 1.0, "hit_any": True, "vacuous": True},
            }}},
        ]
        high = aggregate_lifecycle_effort_scores(cases)["by_effort"]["high"]
        # Only the annotated row counts toward recall -> 0.0 (not 0.5).
        self.assertEqual(0.0, high["evidence_recall@5"])
        self.assertEqual(0.0, high["hit_any"])
        self.assertEqual(2, high["qa_count"])
        self.assertEqual(1, high["scored_qa_count"])

    def test_excluded_category_dropped_from_answer_f1(self):
        from app.benchmarks.lifecycle_runner import aggregate_lifecycle_effort_scores

        # High effort always synthesizes a prediction (run_qa_efforts), so include
        # one — that is what marks the answer as generated (answer_generated=True).
        cases = [
            {"efforts": {"high": {
                "answer_f1": 0.0, "latency_ms": 1.0, "excluded": False, "prediction": "wrong",
                "evidence_recall": {"recall@5": 0.0, "hit_any": False, "vacuous": False},
            }}},
            # Excluded (e.g. cat 5) row scores a neutral 1.0 — must not be averaged in.
            {"efforts": {"high": {
                "answer_f1": 1.0, "latency_ms": 1.0, "excluded": True, "prediction": "n/a",
                "evidence_recall": {"recall@5": 1.0, "hit_any": True, "vacuous": False},
            }}},
        ]
        high = aggregate_lifecycle_effort_scores(cases)["by_effort"]["high"]
        self.assertEqual(0.0, high["answer_f1_mean"])  # excluded row dropped, not 0.5
        self.assertTrue(high["answer_generated"])

    def test_tool_phase_failure_counts_as_zero_answer_score(self):
        from app.benchmarks.lifecycle_runner import aggregate_lifecycle_effort_scores

        scores = aggregate_lifecycle_effort_scores([
            {"efforts": {"high": {
                "answer_f1": 1.0,
                "prediction": "A",
                "excluded": False,
                "evidence_recall": {"recall@5": 1.0, "hit_any": True, "vacuous": False},
            }}},
            {"efforts": {"high": {
                "answer_f1": 0.0,
                "prediction": "",
                "answer_scored": True,
                "tool_phase_failed": True,
                "excluded": False,
                "evidence_recall": {"recall@5": 0.0, "hit_any": False, "vacuous": False},
            }}},
        ])

        high = scores["by_effort"]["high"]
        self.assertTrue(high["answer_generated"])
        self.assertEqual(0.5, high["answer_f1_mean"])
        self.assertEqual(0.5, scores["accuracy_by_effort"]["high"])

    def test_retrieval_only_effort_answer_accuracy_is_not_reported_as_zero(self):
        from app.benchmarks.lifecycle_runner import aggregate_lifecycle_effort_scores

        scores = aggregate_lifecycle_effort_scores([
            {"efforts": {
                "low": {
                    "answer_f1": 0.0,
                    "prediction": "",
                    "evidence_recall": {"recall@5": 1.0, "hit_any": True, "vacuous": False},
                },
                "high": {
                    "answer_f1": 1.0,
                    "prediction": "7 May 2023",
                    "evidence_recall": {"recall@5": 1.0, "hit_any": True, "vacuous": False},
                },
            }}
        ])

        self.assertFalse(scores["by_effort"]["low"]["answer_generated"])
        self.assertIsNone(scores["by_effort"]["low"]["answer_f1_mean"])
        self.assertIsNone(scores["accuracy_by_effort"]["low"])
        self.assertEqual(1.0, scores["accuracy_by_effort"]["high"])


if __name__ == "__main__":
    unittest.main()

class TestLocomoAnswerContextFormatting(unittest.TestCase):
    def test_format_retrieved_context_includes_all_retrieved_rows_by_default(self):
        from app.benchmarks.locomo_answer import _format_retrieved_context

        rows = [
            {
                "dia_ids": [f"D1:{idx}"],
                "text": f"evidence row {idx}",
                "score": 1.0 / idx,
            }
            for idx in range(1, 9)
        ]

        out = _format_retrieved_context(rows)

        self.assertIn("dia_ids=D1:1", out)
        self.assertIn("dia_ids=D1:8", out)
        self.assertIn("evidence row 8", out)


class TestRequiredToolPhasePerQA(unittest.TestCase):
    """One agent that skips a required tool phase invalidates THAT question but
    must not abort the run or discard the report (regression for the no-report,
    last-questions-dropped failure)."""

    def test_required_tool_phase_failure_is_recorded_not_fatal(self):
        from app.benchmarks import lifecycle_runner as lr
        from app.benchmarks.locomo_answer import RequiredToolPhaseError

        conv = _conversation()
        qa = conv.qa_cases[0]

        def fake_recall(request, *, effort, root, explain, include_raw):
            return {"results": []}

        def boom(**kwargs):
            raise RequiredToolPhaseError({"error": "missing_trace_phase"})

        with tempfile.TemporaryDirectory() as td, patch.object(lr, "generate_locomo_answer", boom):
            out = run_qa_efforts(root=td, conversation=conv, qa=qa, recall_fn=fake_recall, k=8, answer_mode="llm")

        high = out["efforts"]["high"]
        self.assertEqual("", high.get("prediction"))
        self.assertEqual(0.0, high.get("answer_f1"))
        self.assertTrue(high.get("tool_phase_failed"))
        self.assertEqual("missing_trace_phase", (high.get("tool_phase_validation") or {}).get("error"))
        self.assertTrue(any("required_tool_phase_failed" in str(w) for w in high.get("warnings") or []))
