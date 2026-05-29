import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.semantic_env import configure_shared_semantic_backend_env


class TestSemanticEnv(unittest.TestCase):
    def test_sets_qdrant_and_kuzu_defaults_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            out = configure_shared_semantic_backend_env()
            self.assertEqual("qdrant", os.environ.get("CORE_MEMORY_VECTOR_BACKEND"))
            self.assertEqual("kuzu", os.environ.get("CORE_MEMORY_GRAPH_BACKEND"))
            self.assertEqual("required", os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"))
            self.assertEqual("off", os.environ.get("CORE_MEMORY_SEMANTIC_AUTODRAIN"))
            self.assertEqual(
                {
                    "CORE_MEMORY_VECTOR_BACKEND": "qdrant",
                    "CORE_MEMORY_GRAPH_BACKEND": "kuzu",
                    "CORE_MEMORY_CANONICAL_SEMANTIC_MODE": "required",
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

    def test_benchmark_database_url_not_bridged_to_pg_dsn(self):
        with patch.dict(os.environ, {"BENCHMARK_DATABASE_URL": "postgresql://demo/db"}, clear=True):
            configure_shared_semantic_backend_env()
            self.assertIsNone(os.environ.get("CORE_MEMORY_PG_DSN"))
            self.assertEqual("qdrant", os.environ.get("CORE_MEMORY_VECTOR_BACKEND"))


if __name__ == "__main__":
    unittest.main()
