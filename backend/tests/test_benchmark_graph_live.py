"""Live benchmark graph streaming + answerer fixes.

Covers:
  - graph_snapshot_payload shape (beads + associations from the bead index),
  - the lifecycle runner emitting a graph_snapshot progress event after replay,
  - the worker mirroring graph_beads/graph_associations onto its event,
  - the answerer no longer failing closed when the top row lacks dia_ids,
  - the frontend wiring (snapshot accumulation + clear-on-new-run).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_JS = (Path(__file__).resolve().parents[2] / "frontend" / "public" / "chat-app.js").read_text()


class TestGraphSnapshotPayload(unittest.TestCase):
    def test_payload_shapes_beads_and_associations(self):
        from app.benchmarks.lifecycle_runner import graph_snapshot_payload

        with tempfile.TemporaryDirectory() as td:
            bd = Path(td) / ".beads"
            bd.mkdir(parents=True)
            (bd / "index.json").write_text(json.dumps({
                "beads": {"b1": {"id": "b1", "title": "T", "type": "context", "source_turn_ids": ["t1"]}},
                "associations": [
                    {"source_bead": "b1", "target_bead": "b2", "relationship": "entity_overlap", "confidence": 0.8, "reason_text": "why"},
                    {"source_bead": "", "target_bead": "b3"},  # dropped (no source)
                ],
            }))
            out = graph_snapshot_payload(td)
        self.assertEqual("b1", out["beads"][0]["id"])
        self.assertEqual(1, len(out["associations"]))
        a = out["associations"][0]
        self.assertEqual(("b1", "b2", "entity_overlap"), (a["source_bead"], a["target_bead"], a["relationship"]))
        self.assertEqual("why", a["explanation"])
        # stats reflects the raw index count (2), while the renderable list drops
        # the malformed (no-source) row.
        self.assertEqual(2, out["stats"]["total_associations"])
        self.assertEqual(1, out["stats"]["total_beads"])


class TestWorkerMirrorsGraphSnapshot(unittest.TestCase):
    def test_worker_event_carries_graph_beads_and_associations(self):
        import app.benchmarks.benchmark_worker as worker

        captured = {}

        def fake_update(job_id, **kwargs):
            if kwargs.get("event", {}).get("stage") == "graph_snapshot":
                captured.update(kwargs["event"])
            return True

        def fake_claim():
            return {"job_id": "j1", "request": {"kind": "benchmark"}, "kwargs": {}}

        def fake_run_benchmark(**kw):
            kw["progress"](0, 5, {}, {
                "phase": "graph_snapshot", "status": "graph_ready",
                "graph_beads": [{"id": "b1", "title": "T", "type": "context"}],
                "graph_associations": [{"source_bead": "b1", "target_bead": "b2", "relationship": "entity_overlap"}],
                "graph_stats": {"total_beads": 1, "total_associations": 1},
            })
            return {"ok": True}

        with patch.object(worker.benchmark_store, "claim_next_job", side_effect=fake_claim), \
             patch.object(worker.benchmark_store, "update_job_progress", side_effect=fake_update), \
             patch.object(worker.benchmark_store, "finish_job", return_value=True), \
             patch.object(worker, "run_benchmark", side_effect=fake_run_benchmark):
            worker.run_once()

        self.assertEqual("b1", captured["graph_beads"][0]["id"])
        self.assertEqual("b2", captured["graph_associations"][0]["target_bead"])
        self.assertEqual(1, captured["graph_stats"]["total_associations"])


class TestAnswererDoesNotFailClosed(unittest.TestCase):
    def test_support_strength_true_when_any_row_has_text_without_dia_ids(self):
        from app.benchmarks.locomo_answer import _support_strength

        # Top row has text but no dia_ids (e.g. a foreign/QA bead). Previously this
        # forced "No information available"; now we still attempt an answer.
        ctx = [{"text": "Caroline is a transgender woman.", "dia_ids": []}]
        self.assertTrue(_support_strength(ctx)["supported"])

    def test_support_strength_false_only_when_no_text(self):
        from app.benchmarks.locomo_answer import _support_strength

        self.assertFalse(_support_strength([])["supported"])
        self.assertFalse(_support_strength([{"text": "", "dia_ids": []}])["supported"])

    def test_prompt_requests_shortest_span(self):
        # The shortest-span instruction lives in the shared style rules used by
        # both LLM answer modes (recall_llm and the agentic llm mode).
        from app.benchmarks import locomo_answer

        self.assertIn("SHORTEST", locomo_answer._ANSWER_STYLE_RULES)
        self.assertIn("never ISO", locomo_answer._ANSWER_STYLE_RULES)


class TestFrontendBenchmarkGraphWiring(unittest.TestCase):
    def test_graph_snapshot_accumulated_and_rendered(self):
        self.assertIn("function accumulateBenchmarkGraph", _JS)
        self.assertIn("function renderBenchmarkRunGraph", _JS)
        self.assertIn("graph_snapshot", _JS)
        self.assertIn("benchmarkRunGraphAssociations", _JS)
        # graph snapshot drives the actual graph render
        self.assertIn("renderGraph(beads, assocs)", _JS)

    def test_new_run_clears_chat_and_graph(self):
        self.assertIn("function clearLiveBenchmarkView", _JS)
        self.assertIn("clearLiveBenchmarkView()", _JS)
        # the destructive clear wipes chat, panes, and every per-run accumulator
        for token in ("benchmarkRunGraphBeads.clear()", "messagesEl.textContent = ''", "renderGraph([], [])"):
            self.assertIn(token, _JS)

    def test_chat_clear_gated_behind_successful_locomo_start(self):
        # The destructive chat/pane wipe must only run for the streamed LoCoMo
        # suite AFTER the job start succeeds, so a rejected start or a non-LoCoMo
        # suite never erases the user's conversation. Up front we only do the
        # non-destructive accumulator reset.
        self.assertIn("function resetBenchmarkAccumulators", _JS)
        self.assertIn("resetBenchmarkAccumulators()", _JS)
        self.assertIn("isStreamedLocomo", _JS)
        # clearLiveBenchmarkView is invoked inside the isStreamedLocomo success
        # branch, which sits after activeBenchmarkPollJobId = jobId.
        post_success = _JS.split("activeBenchmarkPollJobId = jobId;", 1)[1]
        self.assertIn("if (isStreamedLocomo) {", post_success)
        self.assertIn("clearLiveBenchmarkView();", post_success)


class TestGpt55Default(unittest.TestCase):
    def test_openai_fallback_is_current_gpt5_alias(self):
        import inspect
        from app.core import runtime

        # gpt-5.5 is not a real OpenAI model; gpt-5.2 is the current latest alias.
        src = inspect.getsource(runtime.detect_model)
        self.assertIn("openai:gpt-5.2", src)
        self.assertNotIn("openai:gpt-5.5", src)
        self.assertNotIn("openai:gpt-4o\"", src)

    def test_gpt5_alias_in_presets(self):
        from app.core.runtime import DEMO_MODEL_PRESETS

        ids = [m for m, _ in DEMO_MODEL_PRESETS]
        self.assertIn("openai:gpt-5.2", ids)
        self.assertNotIn("openai:gpt-5.5", ids)


if __name__ == "__main__":
    unittest.main()
