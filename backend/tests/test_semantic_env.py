import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.semantic_env import configure_shared_semantic_backend_env


class TestSemanticEnv(unittest.TestCase):
    def test_bridges_benchmark_database_to_core_memory_pgvector(self):
        with patch.dict(os.environ, {
            'BENCHMARK_DATABASE_URL': 'postgresql://demo/db',
            'OPENAI_API_KEY': 'sk-test',
        }, clear=True):
            out = configure_shared_semantic_backend_env()
            self.assertEqual('postgresql://demo/db', os.environ.get('CORE_MEMORY_PG_DSN'))
            self.assertEqual('pgvector', os.environ.get('CORE_MEMORY_VECTOR_BACKEND'))
            self.assertEqual('required', os.environ.get('CORE_MEMORY_CANONICAL_SEMANTIC_MODE'))
            self.assertEqual('openai', os.environ.get('CORE_MEMORY_EMBEDDINGS_PROVIDER'))
            self.assertEqual('shared_postgres_dsn', (out.get('changed') or {}).get('CORE_MEMORY_PG_DSN'))

    def test_explicit_semantic_dsn_and_backend_are_preserved(self):
        with patch.dict(os.environ, {
            'BENCHMARK_DATABASE_URL': 'postgresql://benchmark/db',
            'CORE_MEMORY_PG_DSN': 'postgresql://semantic/db',
            'CORE_MEMORY_VECTOR_BACKEND': 'qdrant',
            'CORE_MEMORY_CANONICAL_SEMANTIC_MODE': 'degraded_allowed',
            'CORE_MEMORY_EMBEDDINGS_PROVIDER': 'gemini',
        }, clear=True):
            out = configure_shared_semantic_backend_env()
            self.assertEqual('postgresql://semantic/db', os.environ.get('CORE_MEMORY_PG_DSN'))
            self.assertEqual('qdrant', os.environ.get('CORE_MEMORY_VECTOR_BACKEND'))
            self.assertEqual('degraded_allowed', os.environ.get('CORE_MEMORY_CANONICAL_SEMANTIC_MODE'))
            self.assertEqual('gemini', os.environ.get('CORE_MEMORY_EMBEDDINGS_PROVIDER'))
            self.assertEqual({}, out.get('changed'))

    def test_no_database_url_leaves_backend_unset(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}, clear=True):
            configure_shared_semantic_backend_env()
            self.assertIsNone(os.environ.get('CORE_MEMORY_PG_DSN'))
            self.assertIsNone(os.environ.get('CORE_MEMORY_VECTOR_BACKEND'))


if __name__ == '__main__':
    unittest.main()
