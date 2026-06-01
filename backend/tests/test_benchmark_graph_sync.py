"""Benchmark replay must sync associations into the graph backend.

Replay writes associations to .beads/index.json, but causal traversal at recall
time queries the configured graph backend (Kuzu/Neo4j). On the hosted config
(GRAPH_BACKEND=kuzu) that DB is never populated by turn processing, so
trace_request walks an empty graph and returns zero chains despite hundreds of
edges in the index. run_pre_qa_flush now syncs them; these tests pin that.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _write_index(root: Path, associations):
    bd = root / ".beads"
    bd.mkdir(parents=True, exist_ok=True)
    (bd / "index.json").write_text(
        json.dumps({"beads": {"b1": {"id": "b1"}, "b2": {"id": "b2"}}, "associations": associations}),
        encoding="utf-8",
    )


class TestSyncGraphBackend(unittest.TestCase):
    def test_null_backend_is_noop(self):
        os.environ["CORE_MEMORY_GRAPH_BACKEND"] = "none"
        from app.benchmarks.lifecycle_runner import sync_graph_backend

        with tempfile.TemporaryDirectory() as td:
            _write_index(Path(td), [{"source_bead": "b1", "target_bead": "b2", "relationship": "supports"}])
            out = sync_graph_backend(td)
        self.assertTrue(out["ok"])
        self.assertFalse(out["synced"])
        self.assertEqual("null_backend_reads_index_directly", out["reason"])

    def test_real_backend_receives_index_associations(self):
        from app.benchmarks import lifecycle_runner as lr

        captured = {}

        class FakeGraph:
            name = "kuzu"

            def sync_from_storage(self, beads, associations):
                captured["beads"] = beads
                captured["associations"] = associations
                return {"ok": True, "synced_associations": len(associations)}

        with tempfile.TemporaryDirectory() as td:
            assocs = [
                {"source_bead": "b1", "target_bead": "b2", "relationship": "supports"},
                {"source_bead": "b2", "target_bead": "b1", "relationship": "supports"},
            ]
            _write_index(Path(td), assocs)
            with patch("core_memory.persistence.graph.factory.create_graph_backend", return_value=FakeGraph()), \
                 patch("core_memory.persistence.graph.protocol.NullGraphBackend", new=type("X", (), {})):
                out = lr.sync_graph_backend(td)

        self.assertTrue(out["ok"])
        self.assertTrue(out["synced"])
        self.assertEqual("kuzu", out["backend"])
        # The index's associations were handed to the backend sync.
        self.assertEqual(2, len(captured["associations"]))

    def test_sync_failure_is_best_effort(self):
        from app.benchmarks import lifecycle_runner as lr

        def boom(_root):
            raise RuntimeError("kuzu exploded")

        with tempfile.TemporaryDirectory() as td:
            _write_index(Path(td), [])
            with patch("core_memory.persistence.graph.factory.create_graph_backend", side_effect=boom):
                out = lr.sync_graph_backend(td)
        self.assertFalse(out["ok"])
        self.assertFalse(out["synced"])
        self.assertIn("kuzu exploded", out["error"])

    def test_pre_qa_flush_calls_graph_sync(self):
        from app.benchmarks import lifecycle_runner as lr
        from app.benchmarks.contracts import BenchmarkConversation

        conv = BenchmarkConversation(
            benchmark_name="locomo",
            conversation_id="c1",
            session_id="s1:replay",
            turns=[],
            qa_cases=[],
            metadata={},
        )
        with tempfile.TemporaryDirectory() as td:
            _write_index(Path(td), [])
            with patch.object(lr, "sync_graph_backend", return_value={"ok": True, "synced": True, "backend": "kuzu"}) as sync_spy, \
                 patch.object(lr, "_default_run_async_jobs", return_value=lambda **kw: {"ok": True}):
                out = lr.run_pre_qa_flush(
                    root=td,
                    conversation=conv,
                    process_flush_fn=lambda **kw: {"ok": True},
                    run_async_jobs_fn=lambda **kw: {"ok": True},
                )
        sync_spy.assert_called_once()
        self.assertEqual({"ok": True, "synced": True, "backend": "kuzu"}, out["graph_sync"])


if __name__ == "__main__":
    unittest.main()
