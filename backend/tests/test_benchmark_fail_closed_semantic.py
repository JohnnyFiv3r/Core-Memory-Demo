import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.runtime import (  # noqa: E402
    BenchmarkSemanticUnavailable,
    _assert_benchmark_semantic_ready,
    _assert_no_degraded_semantic,
)


class TestBenchmarkSemanticReadyPreflight(unittest.TestCase):
    def test_required_rejects_hash_provider(self):
        with self.assertRaises(BenchmarkSemanticUnavailable) as ctx:
            _assert_benchmark_semantic_ready("hash", "required")
        self.assertIn("provider_is_hash", str(ctx.exception))

    def test_required_rejects_unset_provider(self):
        with self.assertRaises(BenchmarkSemanticUnavailable):
            _assert_benchmark_semantic_ready("", "required")

    def test_required_rejects_openai_without_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            with self.assertRaises(BenchmarkSemanticUnavailable) as ctx:
                _assert_benchmark_semantic_ready("openai", "required")
        self.assertIn("missing_key", str(ctx.exception))

    def test_required_rejects_openai_not_installed(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False):
            with patch("importlib.util.find_spec", return_value=None):
                with self.assertRaises(BenchmarkSemanticUnavailable) as ctx:
                    _assert_benchmark_semantic_ready("openai", "required")
        self.assertIn("not_installed", str(ctx.exception))

    def test_required_passes_for_openai_with_key_and_package(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False):
            with patch("importlib.util.find_spec", return_value=object()):
                # Should not raise.
                _assert_benchmark_semantic_ready("openai", "required")

    def test_degraded_allowed_mode_never_enforces(self):
        # In a non-required mode the hash fallback is permitted, so no raise.
        _assert_benchmark_semantic_ready("hash", "degraded_allowed")
        _assert_benchmark_semantic_ready("", "degraded_allowed")


class TestNoDegradedSemanticGuard(unittest.TestCase):
    def test_required_rejects_report_with_degraded_marker(self):
        report = {"cases": [{"efforts": {"high": {"result": {"warnings": ["semantic_backend_unavailable_degraded"]}}}}]}
        with self.assertRaises(BenchmarkSemanticUnavailable) as ctx:
            _assert_no_degraded_semantic(report, "required")
        self.assertIn("degraded_midrun", str(ctx.exception))

    def test_required_passes_clean_report(self):
        report = {"cases": [{"efforts": {"high": {"result": {"warnings": []}}}}]}
        # Should not raise.
        _assert_no_degraded_semantic(report, "required")

    def test_degraded_allowed_mode_tolerates_degraded_marker(self):
        report = {"warnings": ["semantic_backend_unavailable_degraded"]}
        # Non-required mode does not reject degraded reports.
        _assert_no_degraded_semantic(report, "degraded_allowed")


class TestSemanticModeForcesExternalEmbeddings(unittest.TestCase):
    """An external provider must force CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS on
    in-process, so the corpus build cannot silently fall back to FastEmbed."""

    def setUp(self):
        from app.core.runtime import semantic_mode  # noqa: F401
        self.semantic_mode = semantic_mode

    def test_openai_provider_forces_external_flag(self):
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS", None)
            with self.semantic_mode("required", embeddings_provider="openai"):
                self.assertEqual("1", os.environ.get("CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS"))
            # Restored / removed after the context exits.
            self.assertIsNone(os.environ.get("CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS"))

    def test_hash_provider_does_not_force_external_flag(self):
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS", None)
            with self.semantic_mode("degraded_allowed", embeddings_provider="hash"):
                self.assertIsNone(os.environ.get("CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS"))

    def test_no_provider_leaves_flag_untouched(self):
        import os
        with patch.dict("os.environ", {"CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS": "preexisting"}, clear=False):
            with self.semantic_mode("required"):
                self.assertEqual("preexisting", os.environ.get("CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS"))


if __name__ == "__main__":
    unittest.main()
