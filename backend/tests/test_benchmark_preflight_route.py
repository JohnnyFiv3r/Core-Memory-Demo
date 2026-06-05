import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestBenchmarkPreflightRoute(unittest.TestCase):
    def test_preflight_reports_openai_semantic_and_llm_answering_ready(self):
        from fastapi.testclient import TestClient
        from app.main import app

        env = patch.dict(os.environ, {
            'CORE_MEMORY_VECTOR_BACKEND': 'qdrant',
            'CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS': '1',
            'CORE_MEMORY_EMBEDDINGS_PROVIDER': 'openai',
            'CORE_MEMORY_EMBEDDINGS_MODEL': 'text-embedding-3-large',
            'OPENAI_API_KEY': 'test-key',
        }, clear=False)
        def fake_find_spec(name):
            if name in {'qdrant_client', 'openai', 'numpy', 'pydantic_ai'}:
                return object()
            return None

        with patch('app.routes.demo.build_locomo_suite_metadata') as build_meta, \
             patch('importlib.util.find_spec', side_effect=fake_find_spec), \
             env:
            build_meta.return_value = ({'dataset': {'selected_samples': 1, 'selected_qa_cases': 1}}, [], [], {})
            c = TestClient(app)
            res = c.get('/api/demo/benchmark/preflight?semantic_mode=required&answer_mode=llm&generator_model=openai:gpt-4o-mini')

        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertTrue(body['ok'], body)
        self.assertTrue(body['dataset']['ok'])
        self.assertEqual('qdrant', body['semantic']['vector_backend'])
        self.assertEqual('openai', body['semantic']['provider'])
        self.assertTrue(body['semantic']['required_ready'])
        self.assertEqual([], body['semantic']['config_errors'])
        self.assertTrue(any(row['name'] == 'qdrant_client' for row in body['semantic']['dependencies']))
        self.assertTrue(any(row['name'] == 'openai' for row in body['semantic']['dependencies']))
        self.assertFalse(any(row['name'] == 'faiss' for row in body['semantic']['dependencies']))
        self.assertTrue(any(row['name'] == 'pydantic_ai' for row in body['answering']['dependencies']))

    def test_required_preflight_rejects_non_qdrant_config(self):
        from fastapi.testclient import TestClient
        from app.main import app

        env = patch.dict(os.environ, {
            'CORE_MEMORY_VECTOR_BACKEND': 'local-faiss',
            'CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS': '0',
            'CORE_MEMORY_EMBEDDINGS_PROVIDER': 'openai',
            'CORE_MEMORY_EMBEDDINGS_MODEL': 'text-embedding-3-large',
            'OPENAI_API_KEY': 'test-key',
        }, clear=False)
        def fake_find_spec(name):
            if name in {'openai', 'numpy', 'pydantic_ai', 'faiss'}:
                return object()
            return None

        with patch('app.routes.demo.build_locomo_suite_metadata') as build_meta, \
             patch('importlib.util.find_spec', side_effect=fake_find_spec), \
             env:
            build_meta.return_value = ({'dataset': {'selected_samples': 1, 'selected_qa_cases': 1}}, [], [], {})
            c = TestClient(app)
            res = c.get('/api/demo/benchmark/preflight?semantic_mode=required&answer_mode=llm&generator_model=openai:gpt-4o-mini')

        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertFalse(body['ok'])
        self.assertFalse(body['semantic']['required_ready'])
        self.assertIn('CORE_MEMORY_VECTOR_BACKEND must be qdrant, got local-faiss', body['semantic']['config_errors'])

    def test_required_preflight_allows_legacy_suite_local_faiss(self):
        from fastapi.testclient import TestClient
        from app.main import app

        env = patch.dict(os.environ, {
            'CORE_MEMORY_VECTOR_BACKEND': 'local-faiss',
            'CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS': '0',
            'CORE_MEMORY_EMBEDDINGS_PROVIDER': 'openai',
            'CORE_MEMORY_EMBEDDINGS_MODEL': 'text-embedding-3-small',
            'OPENAI_API_KEY': 'test-key',
        }, clear=False)

        def fake_find_spec(name):
            if name in {'faiss', 'openai', 'numpy'}:
                return object()
            return None

        with patch('app.routes.demo.build_locomo_suite_metadata') as build_meta, \
             patch('importlib.util.find_spec', side_effect=fake_find_spec), \
             env:
            build_meta.return_value = ({'dataset': {'selected_samples': 1, 'selected_qa_cases': 1}}, [], [], {})
            c = TestClient(app)
            res = c.get('/api/demo/benchmark/preflight?suite=locomo_qa&semantic_mode=required&answer_mode=none')

        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertTrue(body['ok'], body)
        self.assertEqual('locomo_qa', body['suite'])
        self.assertEqual('local-faiss', body['semantic']['vector_backend'])
        self.assertTrue(body['semantic']['required_ready'])
        self.assertEqual([], body['semantic']['config_errors'])
        self.assertTrue(any(row['name'] == 'faiss' for row in body['semantic']['dependencies']))

    def test_preflight_honors_benchmark_embeddings_provider_override(self):
        from fastapi.testclient import TestClient
        from app.main import app

        env = patch.dict(os.environ, {
            'CORE_MEMORY_VECTOR_BACKEND': 'qdrant',
            'CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS': '1',
            'CORE_MEMORY_DEMO_BENCHMARK_EMBEDDINGS_PROVIDER': 'openai',
            'CORE_MEMORY_EMBEDDINGS_MODEL': 'text-embedding-3-large',
            'OPENAI_API_KEY': 'test-key',
        }, clear=True)

        def fake_find_spec(name):
            if name in {'qdrant_client', 'openai', 'numpy', 'pydantic_ai'}:
                return object()
            return None

        with patch('app.routes.demo.build_locomo_suite_metadata') as build_meta, \
             patch('importlib.util.find_spec', side_effect=fake_find_spec), \
             env:
            build_meta.return_value = ({'dataset': {'selected_samples': 1, 'selected_qa_cases': 1}}, [], [], {})
            c = TestClient(app)
            res = c.get('/api/demo/benchmark/preflight?semantic_mode=required&answer_mode=llm&generator_model=openai:gpt-4o-mini')

        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertTrue(body['ok'], body)
        self.assertEqual('openai', body['semantic']['provider'])
        self.assertEqual([], body['semantic']['config_errors'])

    def test_preflight_honors_explicit_embeddings_provider_param(self):
        from fastapi.testclient import TestClient
        from app.main import app

        env = patch.dict(os.environ, {
            'CORE_MEMORY_VECTOR_BACKEND': 'qdrant',
            'CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS': '1',
            'CORE_MEMORY_EMBEDDINGS_MODEL': 'text-embedding-3-large',
            'OPENAI_API_KEY': 'test-key',
        }, clear=True)

        def fake_find_spec(name):
            if name in {'qdrant_client', 'openai', 'numpy', 'pydantic_ai'}:
                return object()
            return None

        with patch('app.routes.demo.build_locomo_suite_metadata') as build_meta, \
             patch('importlib.util.find_spec', side_effect=fake_find_spec), \
             env:
            build_meta.return_value = ({'dataset': {'selected_samples': 1, 'selected_qa_cases': 1}}, [], [], {})
            c = TestClient(app)
            res = c.get('/api/demo/benchmark/preflight?semantic_mode=required&answer_mode=llm&generator_model=openai:gpt-4o-mini&embeddings_provider=openai')

        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertTrue(body['ok'], body)
        self.assertEqual('openai', body['semantic']['provider'])
        self.assertEqual([], body['semantic']['config_errors'])

    def test_preflight_defaults_to_lifecycle_suite(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with patch('app.routes.demo.build_locomo_suite_metadata') as build_meta:
            build_meta.return_value = ({'dataset': {'selected_samples': 1, 'selected_qa_cases': 1}}, [], [], {})
            c = TestClient(app)
            res = c.get('/api/demo/benchmark/preflight')

        self.assertEqual(200, res.status_code)
        self.assertEqual('locomo_native_lifecycle', build_meta.call_args.kwargs.get('suite'))


if __name__ == '__main__':
    unittest.main()
