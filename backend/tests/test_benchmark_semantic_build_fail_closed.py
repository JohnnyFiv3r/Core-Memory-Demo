import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmarks.contracts import BenchmarkLifecycleError  # noqa: E402
from app.benchmarks.lifecycle_runner import _assert_semantic_build_ok  # noqa: E402


class TestSemanticBuildFailClosed(unittest.TestCase):
    def _required(self):
        return patch.dict("os.environ", {"CORE_MEMORY_CANONICAL_SEMANTIC_MODE": "required"}, clear=False)

    def test_required_raises_on_invalid_state_and_surfaces_root_cause(self):
        build = {
            "ok": False,
            "error": {
                "code": "semantic_build_invalid_state",
                "message": "Required semantic build did not produce a usable semantic backend",
                "detail": {"last_build_error": "openai: Connection error to api.openai.com"},
            },
        }
        with self._required():
            with self.assertRaises(BenchmarkLifecycleError) as ctx:
                _assert_semantic_build_ok(build)
        msg = str(ctx.exception)
        self.assertIn("benchmark_semantic_build_failed_required", msg)
        self.assertIn("semantic_build_invalid_state", msg)
        # The actual embedding error must be surfaced, not swallowed.
        self.assertIn("Connection error to api.openai.com", msg)

    def test_required_raises_on_plain_string_error(self):
        with self._required():
            with self.assertRaises(BenchmarkLifecycleError):
                _assert_semantic_build_ok({"ok": False, "error": "boom"})

    def test_required_passes_when_build_ok(self):
        with self._required():
            # Should not raise.
            _assert_semantic_build_ok({"ok": True, "backend": "qdrant", "semantic_ready": True})

    def test_degraded_allowed_tolerates_failed_build(self):
        with patch.dict("os.environ", {"CORE_MEMORY_CANONICAL_SEMANTIC_MODE": "degraded_allowed"}, clear=False):
            # Non-required mode must not raise even on a failed build.
            _assert_semantic_build_ok({"ok": False, "error": {"code": "x"}})


if __name__ == "__main__":
    unittest.main()
