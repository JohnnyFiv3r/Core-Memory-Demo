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

    def test_benchmark_backend_paths_overrides_live_env_and_restores(self):
        from app.benchmarks import lifecycle_runner as lr

        # Simulate the hosted config: env points at the LIVE store.
        os.environ["CORE_MEMORY_KUZU_PATH"] = "/var/data/core-memory/.beads/kuzu"
        os.environ["CORE_MEMORY_QDRANT_PATH"] = "/var/data/core-memory/.beads/qdrant"
        with tempfile.TemporaryDirectory() as td:
            with lr.benchmark_backend_paths(td):
                # Inside the scope both vars point at the benchmark root, not live.
                self.assertEqual(str(Path(td) / ".beads" / "kuzu"), os.environ["CORE_MEMORY_KUZU_PATH"])
                self.assertEqual(str(Path(td) / ".beads" / "qdrant"), os.environ["CORE_MEMORY_QDRANT_PATH"])
            # Restored afterward.
            self.assertEqual("/var/data/core-memory/.beads/kuzu", os.environ["CORE_MEMORY_KUZU_PATH"])
            self.assertEqual("/var/data/core-memory/.beads/qdrant", os.environ["CORE_MEMORY_QDRANT_PATH"])
        os.environ.pop("CORE_MEMORY_KUZU_PATH", None)
        os.environ.pop("CORE_MEMORY_QDRANT_PATH", None)

    def test_backend_paths_restores_unset_vars(self):
        from app.benchmarks import lifecycle_runner as lr

        os.environ.pop("CORE_MEMORY_KUZU_PATH", None)
        with tempfile.TemporaryDirectory() as td:
            with lr.benchmark_backend_paths(td):
                self.assertIn("CORE_MEMORY_KUZU_PATH", os.environ)
            # Was unset before -> must be unset after, not left dangling.
            self.assertNotIn("CORE_MEMORY_KUZU_PATH", os.environ)

    def test_sync_clears_graph_dir_before_load(self):
        from app.benchmarks import lifecycle_runner as lr

        synced_calls = []

        class FakeGraph:
            name = "kuzu"

            def sync_from_storage(self, beads, associations):
                synced_calls.append(len(associations))
                return {"ok": True}

        with tempfile.TemporaryDirectory() as td:
            _write_index(Path(td), [{"source_bead": "b1", "target_bead": "b2", "relationship": "supports"}])
            # Pre-existing graph dir with content -> must be wiped before sync.
            graph_dir = Path(td) / ".beads" / "kuzu"
            graph_dir.mkdir(parents=True, exist_ok=True)
            (graph_dir / "stale.db").write_text("old", encoding="utf-8")
            with patch("core_memory.persistence.graph.factory.create_graph_backend", return_value=FakeGraph()), \
                 patch("core_memory.persistence.graph.protocol.NullGraphBackend", new=type("X", (), {})):
                out = lr.sync_graph_backend(td)
            self.assertTrue(out["synced"])
            # The stale graph dir contents were removed before the rebuild.
            self.assertFalse((graph_dir / "stale.db").exists())

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

    def test_isolated_qa_rescopes_backend_paths_to_qa_root(self):
        """In isolated mode, recall/write for each QA must see env paths pinned to
        the per-QA copy, not the shared base root (otherwise hosted qdrant/kuzu
        access defeats isolation)."""
        from app.benchmarks import lifecycle_runner as lr
        from app.benchmarks.contracts import BenchmarkConversation, BenchmarkQA, BenchmarkTurn

        os.environ["CORE_MEMORY_KUZU_PATH"] = "/var/data/core-memory/.beads/kuzu"
        seen_kuzu_paths = []

        def fake_recall(request, *, effort, root, explain, include_raw):
            # Capture the env path the recall would resolve for this QA case.
            seen_kuzu_paths.append(os.environ.get("CORE_MEMORY_KUZU_PATH"))
            return {"answer": "a", "warnings": [], "raw": {"results": []}}

        def fake_process_turn_finalized(**kw):
            beads_dir = Path(kw["root"]) / ".beads"
            beads_dir.mkdir(parents=True, exist_ok=True)
            (beads_dir / "index.json").write_text(
                json.dumps({
                    "beads": {
                        "bead-judge-1": {
                            "id": "bead-judge-1",
                            "session_id": kw["session_id"],
                            "source_turn_ids": [kw["turn_id"], "D1:1"],
                            "claims": [{"text": "A said hi.", "confidence": 1.0}],
                        }
                    },
                    "associations": [],
                }),
                encoding="utf-8",
            )
            return {"ok": True}

        conv = BenchmarkConversation(
            benchmark_name="locomo",
            conversation_id="conv-1",
            session_id="bench:locomo:conv-1:replay",
            turns=[BenchmarkTurn(turn_id="locomo:conv-1:D1:1:1", speaker="A", role="user", content="hi", metadata={"locomo_dia_id": "D1:1"})],
            qa_cases=[BenchmarkQA(qa_id="conv-1:q1", question="q?", expected_answer="a", category="2", gold_evidence=["D1:1"])],
            metadata={},
        )
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "base"
            (base / ".beads").mkdir(parents=True, exist_ok=True)
            (base / ".beads" / "index.json").write_text(json.dumps({"beads": {}, "associations": []}), encoding="utf-8")
            try:
                lr.run_lifecycle_conversation(
                    root=str(base),
                    conversation=conv,
                    qa_session_mode="isolated",
                    process_turn_finalized_fn=fake_process_turn_finalized,
                    process_flush_fn=lambda **kw: {"ok": True},
                    run_async_jobs_fn=lambda **kw: {"ok": True},
                    recall_fn=fake_recall,
                    write_qa_beads=False,
                )
            finally:
                os.environ.pop("CORE_MEMORY_KUZU_PATH", None)

        # recall ran with the env pinned to the isolated qa_root's kuzu dir,
        # NOT the base root and NOT the live /var/data path.
        self.assertTrue(seen_kuzu_paths)
        for p in seen_kuzu_paths:
            self.assertIn("-qa-isolated", str(p))
            self.assertTrue(str(p).endswith(".beads/kuzu"))
            self.assertNotEqual("/var/data/core-memory/.beads/kuzu", p)


if __name__ == "__main__":
    unittest.main()
