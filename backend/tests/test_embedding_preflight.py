import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import embedding_preflight as ep


def _clear_env(monkeysetenv):
    for name in (
        "CORE_MEMORY_EMBEDDINGS_PROVIDER", "CORE_MEMORY_EMBEDDING_PROVIDER",
        "CORE_MEMORY_EMBEDDINGS_API_KEY", "CORE_MEMORY_EMBEDDING_API_KEY",
        "CORE_MEMORY_EMBEDDINGS_BASE_URL", "CORE_MEMORY_EMBEDDING_BASE_URL",
        "CORE_MEMORY_EMBEDDINGS_MODEL", "CORE_MEMORY_EMBEDDING_MODEL",
        "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
    ):
        monkeysetenv.pop(name, None)


class TestEmbeddingPreflight(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict("os.environ", {}, clear=False)
        self._env.start()
        _clear_env(__import__("os").environ)

    def tearDown(self):
        self._env.stop()

    def test_default_provider_is_skipped_as_non_external(self):
        # No provider configured -> FastEmbed/local default, no external key needed.
        out = ep.preflight_embedding_backend(probe=lambda **_: {"ok": True, "dim": 3})
        self.assertTrue(out["ok"])
        self.assertTrue(out["skipped"])

    def test_missing_key_is_fatal_with_per_service_hint(self):
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        out = ep.preflight_embedding_backend(probe=lambda **_: {"ok": True, "dim": 3})
        self.assertFalse(out["ok"])
        self.assertTrue(out["fatal"])
        self.assertEqual("missing_embedding_api_key", out["error"])
        self.assertIn("per-service", out["hint"])

    def test_openrouter_key_to_openai_is_flagged(self):
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-deadbeefdeadbeefdeadbeef"

        def _401(**_):
            raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

        out = ep.preflight_embedding_backend(probe=_401)
        self.assertFalse(out["ok"])
        self.assertTrue(out["fatal"])
        self.assertEqual("http_401", out["error"])
        self.assertEqual("OPENROUTER_API_KEY", out["key_source"])
        self.assertIn("OpenRouter", out["hint"])
        # Key is masked, never logged in full.
        self.assertNotIn("deadbeef", out["key"])

    def test_live_401_is_fatal(self):
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-proj-valid-looking-key-1234567890"

        def _401(**_):
            raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

        out = ep.preflight_embedding_backend(probe=_401)
        self.assertFalse(out["ok"])
        self.assertTrue(out["fatal"])
        self.assertEqual("OPENAI_API_KEY", out["key_source"])
        self.assertIn("401", out["hint"])

    def test_transient_probe_failure_is_non_fatal(self):
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-proj-valid-looking-key-1234567890"

        def _boom(**_):
            raise TimeoutError("connection timed out")

        out = ep.preflight_embedding_backend(probe=_boom)
        self.assertFalse(out["ok"])
        self.assertFalse(out["fatal"])  # network blip must not block a valid run
        self.assertIn("probe_failed", out["error"])

    def test_valid_key_passes(self):
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-proj-valid-looking-key-1234567890"
        out = ep.preflight_embedding_backend(probe=lambda **_: {"ok": True, "dim": 1536})
        self.assertTrue(out["ok"])
        self.assertFalse(out["fatal"])
        self.assertEqual(1536, out["dim"])

    def test_quoted_key_value_is_flagged(self):
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = '"sk-proj-quoted-key-1234567890"'

        def _401(**_):
            raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

        out = ep.preflight_embedding_backend(probe=_401)
        self.assertIn("quotes", out["hint"])

    def test_format_failure_is_single_line_with_hint(self):
        line = ep.format_preflight_failure({
            "error": "http_401", "key_source": "OPENAI_API_KEY", "key": "sk-proj…7890 (len=34)",
            "provider": "openai", "base_url": "https://api.openai.com/v1", "model": "text-embedding-3-large",
            "hint": "check the worker key",
        })
        self.assertIn("embedding_preflight_failed:http_401", line)
        self.assertIn("key_source=OPENAI_API_KEY", line)
        self.assertIn("check the worker key", line)
        self.assertEqual(1, len(line.splitlines()))


if __name__ == "__main__":
    unittest.main()
