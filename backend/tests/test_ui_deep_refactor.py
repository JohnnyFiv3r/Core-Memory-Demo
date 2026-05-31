"""Static assertions for the deep UI refactors (isolated, rollback-friendly).

These guard the three behaviour-preserving refactors that were split out of the
PR #141 UI sweep so each can be reverted independently:
  - debounced graph filter re-renders,
  - exponential backoff on benchmark poll network errors,
  - removal of the redundant /api/demo/runtime fetch on the standard refresh.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_JS = (Path(__file__).resolve().parents[2] / "frontend" / "public" / "chat-app.js").read_text()


class TestGraphDebounce(unittest.TestCase):
    def test_debounce_helper_and_debounced_graph_render_present(self):
        self.assertIn("function debounce(", _JS)
        self.assertIn("function debouncedRenderGraph(", _JS)
        # Filter callbacks use the debounced path, not eager renderGraph.
        self.assertIn("debouncedRenderGraph(beads, assocs)", _JS)


class TestBenchmarkPollBackoff(unittest.TestCase):
    def test_poll_uses_exponential_backoff_not_flat_retry(self):
        self.assertIn("POLL_BACKOFF_MAX_MS", _JS)
        self.assertIn("pollBackoffMs * 2", _JS)
        # The old flat 2s retry literal must be gone from the benchmark poll loop.
        self.assertNotIn("setTimeout(r, 2000)", _JS)


class TestSingleStateFetch(unittest.TestCase):
    def test_standard_refresh_reads_runtime_from_state_payload(self):
        # Runtime/last_turn/session come from the inspect/state payload; the second
        # /api/demo/runtime round-trip on the standard refresh path is removed.
        self.assertIn("const runtimeLocal = data.runtime || {};", _JS)
        self.assertIn("const lastTurnLocal = data.last_turn || {};", _JS)


if __name__ == "__main__":
    unittest.main()
