import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.semantic_env import configure_shared_semantic_backend_env, normalize_embedded_qdrant_summary


class TestSemanticEnv(unittest.TestCase):
    def test_sets_qdrant_and_kuzu_defaults_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            out = configure_shared_semantic_backend_env()
            self.assertEqual("qdrant", os.environ.get("CORE_MEMORY_VECTOR_BACKEND"))
            self.assertEqual("kuzu", os.environ.get("CORE_MEMORY_GRAPH_BACKEND"))
            self.assertEqual("var/core-memory/.beads/qdrant", os.environ.get("CORE_MEMORY_QDRANT_PATH"))
            self.assertEqual("var/core-memory/.beads/kuzu", os.environ.get("CORE_MEMORY_KUZU_PATH"))
            self.assertEqual("required", os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"))
            self.assertEqual("off", os.environ.get("CORE_MEMORY_SEMANTIC_AUTODRAIN"))
            self.assertEqual(
                {
                    "CORE_MEMORY_VECTOR_BACKEND": "qdrant",
                    "CORE_MEMORY_GRAPH_BACKEND": "kuzu",
                    "CORE_MEMORY_QDRANT_PATH": "var/core-memory/.beads/qdrant",
                    "CORE_MEMORY_CANONICAL_SEMANTIC_MODE": "required",
                    "CORE_MEMORY_KUZU_PATH": "var/core-memory/.beads/kuzu",
                    "CORE_MEMORY_SEMANTIC_AUTODRAIN": "off",
                },
                out.get("changed"),
            )

    def test_explicit_backend_is_preserved(self):
        with patch.dict(
            os.environ,
            {
                "CORE_MEMORY_VECTOR_BACKEND": "pgvector",
                "CORE_MEMORY_GRAPH_BACKEND": "neo4j",
                "CORE_MEMORY_CANONICAL_SEMANTIC_MODE": "degraded_allowed",
                "CORE_MEMORY_SEMANTIC_AUTODRAIN": "on",
            },
            clear=True,
        ):
            out = configure_shared_semantic_backend_env()
            self.assertEqual("pgvector", os.environ.get("CORE_MEMORY_VECTOR_BACKEND"))
            self.assertEqual("neo4j", os.environ.get("CORE_MEMORY_GRAPH_BACKEND"))
            self.assertEqual("degraded_allowed", os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"))
            self.assertEqual("on", os.environ.get("CORE_MEMORY_SEMANTIC_AUTODRAIN"))
            self.assertEqual({}, out.get("changed"))

    def test_partial_pgvector_legacy_backend_gets_required_mode_and_openai_provider(self):
        with patch.dict(
            os.environ,
            {
                "CORE_MEMORY_VECTOR_BACKEND": "pgvector",
                "CORE_MEMORY_PG_DSN": "postgresql://semantic/db",
                "OPENAI_API_KEY": "sk-test",
            },
            clear=True,
        ):
            out = configure_shared_semantic_backend_env()
            self.assertEqual("pgvector", os.environ.get("CORE_MEMORY_VECTOR_BACKEND"))
            self.assertEqual("required", os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"))
            self.assertEqual("openai", os.environ.get("CORE_MEMORY_EMBEDDINGS_PROVIDER"))
            self.assertEqual("off", os.environ.get("CORE_MEMORY_SEMANTIC_AUTODRAIN"))
            self.assertEqual("required", (out.get("changed") or {}).get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"))
            self.assertEqual("openai", (out.get("changed") or {}).get("CORE_MEMORY_EMBEDDINGS_PROVIDER"))

    def test_partial_postgres_alias_legacy_backend_gets_required_mode(self):
        with patch.dict(os.environ, {"CORE_MEMORY_VECTOR_BACKEND": "postgresql"}, clear=True):
            out = configure_shared_semantic_backend_env()
            self.assertEqual("postgresql", os.environ.get("CORE_MEMORY_VECTOR_BACKEND"))
            self.assertEqual("required", os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"))
            self.assertIsNone(os.environ.get("CORE_MEMORY_EMBEDDINGS_PROVIDER"))
            self.assertEqual("required", (out.get("changed") or {}).get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"))

    def test_benchmark_database_url_not_bridged_to_pg_dsn(self):
        with patch.dict(os.environ, {"BENCHMARK_DATABASE_URL": "postgresql://demo/db"}, clear=True):
            configure_shared_semantic_backend_env()
            self.assertIsNone(os.environ.get("CORE_MEMORY_PG_DSN"))
            self.assertEqual("qdrant", os.environ.get("CORE_MEMORY_VECTOR_BACKEND"))

    def test_embedded_qdrant_summary_uses_path_not_localhost_probe(self):
        with self.subTest("path mode"):
            with tempfile.TemporaryDirectory() as tmp:
                with patch.dict(os.environ, {"CORE_MEMORY_VECTOR_BACKEND": "qdrant"}, clear=True):
                    summary = normalize_embedded_qdrant_summary(
                        {
                            "backend": "qdrant",
                            "rows_count": 3,
                            "connectivity_checked": True,
                            "connectivity_ok": False,
                            "connectivity_error": "qdrant_unreachable:<urlopen error [Errno 111] Connection refused>",
                            "usable_backend": False,
                        },
                        root=Path(tmp) / "core-memory",
                    )
                self.assertTrue(summary["connectivity_ok"])
                self.assertEqual("", summary["connectivity_error"])
                self.assertTrue(summary["usable_backend"])
                self.assertEqual("embedded_qdrant_path", summary["deployment_profile"])


if __name__ == "__main__":
    unittest.main()
