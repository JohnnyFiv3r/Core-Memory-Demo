import json
import os
import tempfile
import unittest
from pathlib import Path


class _FakeCursor:
    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self):
        self.last_sql = ""
        self.last_params = []

    def execute(self, sql, params):
        self.last_sql = str(sql)
        self.last_params = list(params or [])
        return _FakeCursor()


def _set_retrieval_eligible(root: Path, bead_id: str) -> None:
    idx_path = root / ".beads" / "index.json"
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    row = dict((data.get("beads") or {}).get(bead_id) or {})
    row["retrieval_eligible"] = True
    row["status"] = "open"
    data.setdefault("beads", {})[bead_id] = row
    idx_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class TestRetrievalRegressions(unittest.TestCase):
    def test_pgvector_search_parameter_order(self):
        try:
            from core_memory.retrieval.vector_backend import PgvectorBackend
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"core_memory unavailable: {exc}")

        conn = _FakeConn()
        backend = PgvectorBackend.__new__(PgvectorBackend)
        backend._conn = conn
        backend._table = "core_memory_beads"

        query_vec = [0.1, 0.2, 0.3]
        backend.search(
            query_vec,
            k=7,
            filters={
                "type": "decision",
                "status": "open",
                "session_id": "demo-1",
                "created_after": "2026-01-01T00:00:00Z",
            },
        )

        q = str(query_vec)
        self.assertIn("ORDER BY embedding <=> %s::vector", conn.last_sql)
        self.assertEqual(
            [q, "decision", "open", "demo-1", "2026-01-01T00:00:00Z", q, 7],
            conn.last_params,
        )

    def test_memory_execute_smoke_no_programmingerror_warning(self):
        try:
            from core_memory.persistence.store import MemoryStore
            from core_memory.retrieval.tools import memory as memory_tools
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"core_memory unavailable: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "core-memory"
            os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "hash"

            store = MemoryStore(root=str(root))
            bead_id = store.add_bead(
                type="decision",
                title="We chose PostgreSQL for JSON-heavy workload",
                summary=["JSONB performance and single operational stack"],
                session_id="demo-regression",
                source_turn_ids=["turn-1"],
            )
            _set_retrieval_eligible(root, bead_id)

            out = memory_tools.execute(
                {"query": "Why did we choose PostgreSQL?", "intent": "remember", "k": 8},
                root=str(root),
                explain=False,
            )
            warnings = [str(w or "").strip().lower() for w in list(out.get("warnings") or [])]
            self.assertTrue(bool(out.get("ok")))
            self.assertFalse(any("semantic_backend_query_error:programmingerror" in w for w in warnings))

    def test_retrieval_alert_spike_tracking(self):
        try:
            from app.core import runtime
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"runtime unavailable: {exc}")

        prev_window = int(runtime.settings.retrieval_alert_window_seconds)
        prev_threshold = int(runtime.settings.retrieval_alert_spike_threshold)
        try:
            runtime.settings.retrieval_alert_window_seconds = 60
            runtime.settings.retrieval_alert_spike_threshold = 2
            runtime._RETRIEVAL_ALERT_TIMESTAMPS.clear()

            s1 = runtime._record_retrieval_alert(["semantic_backend_programmingerror"], now_epoch=1000.0)
            s2 = runtime._record_retrieval_alert(["semantic_backend_programmingerror"], now_epoch=1001.0)
            s3 = runtime._record_retrieval_alert([], now_epoch=1065.0)

            self.assertEqual(1, int(s1.get("recent_count") or 0))
            self.assertFalse(bool(s1.get("spike")))

            self.assertEqual(2, int(s2.get("recent_count") or 0))
            self.assertTrue(bool(s2.get("spike")))

            self.assertEqual(0, int(s3.get("recent_count") or 0))
            self.assertFalse(bool(s3.get("spike")))
        finally:
            runtime.settings.retrieval_alert_window_seconds = prev_window
            runtime.settings.retrieval_alert_spike_threshold = prev_threshold
            runtime._RETRIEVAL_ALERT_TIMESTAMPS.clear()


if __name__ == "__main__":
    unittest.main()
