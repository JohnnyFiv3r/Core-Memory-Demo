import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


def _http_error(code: int, body: dict) -> urllib.error.HTTPError:
    fp = io.BytesIO(json.dumps(body).encode("utf-8"))
    return urllib.error.HTTPError("https://api.openai.com/v1/embeddings", code, "err", {}, fp)

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

    def test_stale_explicit_key_shadowing_fresh_openai_key_is_flagged(self):
        # The "fresh key but still 401" case: a leftover CORE_MEMORY_EMBEDDINGS_API_KEY
        # outranks the freshly-rotated OPENAI_API_KEY and is what actually gets sent.
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-proj-FRESH-rotated-key-9999999999"
        os.environ["CORE_MEMORY_EMBEDDINGS_API_KEY"] = "sk-proj-STALE-old-key-0000000000"

        def _401(**_):
            raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

        out = ep.preflight_embedding_backend(probe=_401)
        self.assertFalse(out["ok"])
        self.assertTrue(out["fatal"])
        self.assertEqual("CORE_MEMORY_EMBEDDINGS_API_KEY", out["key_source"])
        self.assertIn("IGNORED", out["hint"])
        # Audit shows both vars present and which one wins.
        audit = {row["var"]: row for row in out["key_audit"]}
        self.assertTrue(audit["CORE_MEMORY_EMBEDDINGS_API_KEY"]["used"])
        self.assertFalse(audit["OPENAI_API_KEY"]["used"])
        self.assertTrue(audit["OPENAI_API_KEY"]["present"])

    def test_restricted_project_key_401_is_named_as_permissions_not_bad_key(self):
        # A fresh sk-proj-… key that authenticates but lacks model scope returns
        # HTTP 401 with code=insufficient_permissions. The preflight must call
        # this out as a permissions problem, not send the user chasing the key value.
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-proj-fresh-but-restricted-1234567890"

        def _scoped_401(**_):
            raise _http_error(401, {"error": {
                "message": "You have insufficient permissions for this operation. Missing scopes: model.request",
                "type": "invalid_request_error",
                "code": "insufficient_permissions",
            }})

        out = ep.preflight_embedding_backend(probe=_scoped_401)
        self.assertFalse(out["ok"])
        self.assertTrue(out["fatal"])
        self.assertEqual("http_401", out["error"])
        self.assertEqual("insufficient_permissions", out["api_error"]["code"])
        self.assertIn("permissions problem", out["hint"])
        self.assertIn("Model capabilities", out["hint"])
        self.assertIn("Missing scopes: model.request", out["hint"])

    def test_invalid_key_401_body_is_surfaced(self):
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-proj-typo-key-0000000000"

        def _bad_key(**_):
            raise _http_error(401, {"error": {
                "message": "Incorrect API key provided: sk-proj-***.",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }})

        out = ep.preflight_embedding_backend(probe=_bad_key)
        self.assertIn("invalid, revoked", out["hint"])
        self.assertIn("Incorrect API key provided", out["hint"])

    def test_custom_base_url_override_is_flagged(self):
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-proj-valid-looking-key-1234567890"
        os.environ["CORE_MEMORY_EMBEDDINGS_BASE_URL"] = "https://proxy.internal/v1"

        def _401(**_):
            raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

        out = ep.preflight_embedding_backend(probe=_401)
        self.assertIn("custom/override endpoint", out["hint"])

    def test_report_renders_audit_and_used_marker(self):
        import os
        os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-proj-valid-looking-key-1234567890"
        out = ep.preflight_embedding_backend(probe=lambda **_: {"ok": True, "dim": 1536})
        report = ep.format_preflight_report(out)
        self.assertIn("embedding preflight: OK", report)
        self.assertIn("OPENAI_API_KEY", report)
        self.assertIn("<-- USED", report)

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
