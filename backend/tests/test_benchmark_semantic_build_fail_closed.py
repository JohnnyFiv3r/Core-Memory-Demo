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


class TestExternalEmbeddingsActuallyUsed(unittest.TestCase):
    """Build can report ok=True while silently using FastEmbed instead of the
    requested external provider (no provider API call). Catch that."""

    def _required_openai(self):
        return patch.dict(
            "os.environ",
            {
                "CORE_MEMORY_CANONICAL_SEMANTIC_MODE": "required",
                "CORE_MEMORY_EMBEDDINGS_PROVIDER": "openai",
            },
            clear=False,
        )

    def test_raises_when_openai_requested_but_built_with_fastembed(self):
        build = {"ok": True, "backend": "qdrant", "manifest": "/tmp/ignored"}
        manifest = {"provider": "fastembed", "backend": "qdrant", "semantic_ready": True}
        with self._required_openai():
            with self.assertRaises(BenchmarkLifecycleError) as ctx:
                _assert_semantic_build_ok(build, manifest=manifest)
        msg = str(ctx.exception)
        self.assertIn("benchmark_semantic_external_not_used", msg)
        self.assertIn("openai", msg)
        self.assertIn("fastembed", msg)

    def test_raises_when_semantic_not_ready(self):
        build = {"ok": True, "manifest": "/tmp/ignored"}
        manifest = {"provider": "openai", "backend": "lexical", "semantic_ready": False}
        with self._required_openai():
            with self.assertRaises(BenchmarkLifecycleError):
                _assert_semantic_build_ok(build, manifest=manifest)

    def test_passes_when_openai_actually_used(self):
        build = {"ok": True, "manifest": "/tmp/ignored"}
        manifest = {"provider": "openai", "backend": "qdrant", "semantic_ready": True, "dimension": 3072}
        with self._required_openai():
            # Should not raise.
            _assert_semantic_build_ok(build, manifest=manifest)

    def test_passes_when_openai_qdrant_manifest_has_stale_ready_false(self):
        build = {"ok": True, "backend": "qdrant", "entries": 432, "manifest": "/tmp/ignored"}
        manifest = {
            "provider": "openai",
            "model": "text-embedding-3-large",
            "backend": "qdrant",
            "vector_backend": "qdrant",
            "semantic_ready": False,
            "dimension": 3072,
            "row_count": 432,
        }
        with self._required_openai():
            # An ok external-Qdrant/OpenAI build should not fail solely because a
            # deployed manifest carried a stale semantic_ready flag.
            _assert_semantic_build_ok(build, manifest=manifest)

    def test_raises_when_openai_qdrant_manifest_has_no_vector_dimension(self):
        build = {"ok": True, "backend": "qdrant", "entries": 432, "manifest": "/tmp/ignored"}
        manifest = {"provider": "openai", "backend": "qdrant", "vector_backend": "qdrant", "semantic_ready": False, "dimension": 0}
        with self._required_openai():
            with self.assertRaises(BenchmarkLifecycleError):
                _assert_semantic_build_ok(build, manifest=manifest)

    def test_no_provider_check_for_local_hash_provider(self):
        build = {"ok": True, "manifest": "/tmp/ignored"}
        manifest = {"provider": "fastembed", "backend": "qdrant", "semantic_ready": True}
        with patch.dict(
            "os.environ",
            {"CORE_MEMORY_CANONICAL_SEMANTIC_MODE": "required", "CORE_MEMORY_EMBEDDINGS_PROVIDER": "hash"},
            clear=False,
        ):
            # hash provider does not demand the external path.
            _assert_semantic_build_ok(build, manifest=manifest)

    def test_unreadable_manifest_does_not_false_fail(self):
        # ok build, external requested, but manifest path missing/unreadable and no
        # inline manifest -> must not raise (ok-check already passed).
        build = {"ok": True, "manifest": "/nonexistent/path/manifest.json"}
        with self._required_openai():
            _assert_semantic_build_ok(build)


if __name__ == "__main__":
    unittest.main()
