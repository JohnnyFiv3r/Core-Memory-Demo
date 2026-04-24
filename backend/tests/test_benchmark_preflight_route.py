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

        with patch('app.routes.demo.build_locomo_suite_metadata') as build_meta:
            build_meta.return_value = ({'dataset': {'selected_samples': 1, 'selected_qa_cases': 1}}, [], [], {})
            os.environ['CORE_MEMORY_EMBEDDINGS_PROVIDER'] = 'openai'
            os.environ['CORE_MEMORY_EMBEDDINGS_MODEL'] = 'text-embedding-3-small'
            c = TestClient(app)
            res = c.get('/api/demo/benchmark/preflight?semantic_mode=required&answer_mode=llm&generator_model=openai:gpt-4o-mini')

        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertTrue(body['dataset']['ok'])
        self.assertEqual('openai', body['semantic']['provider'])
        self.assertTrue(any(row['name'] == 'openai' for row in body['semantic']['dependencies']))
        self.assertTrue(any(row['name'] == 'pydantic_ai' for row in body['answering']['dependencies']))


if __name__ == '__main__':
    unittest.main()
