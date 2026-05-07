import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'Core-Memory'))

if importlib.util.find_spec('pydantic_settings') is not None:
    from fastapi import HTTPException
    from app.routes import demo as demo_routes
else:
    HTTPException = Exception
    demo_routes = None


class TestBenchmarkArtifactRoute(unittest.TestCase):
    def test_comparison_artifact_is_allowed(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        with tempfile.TemporaryDirectory() as td:
            old_root = demo_routes.settings.core_memory_demo_artifacts_root
            demo_routes.settings.core_memory_demo_artifacts_root = td
            try:
                root = Path(td) / 'locomo-runs' / 'bench-test123'
                root.mkdir(parents=True, exist_ok=True)
                path = root / 'comparison.json'
                path.write_text('{"ok": true}', encoding='utf-8')
                resp = demo_routes.benchmark_artifact_download('bench-test123', 'comparison.json')
            finally:
                demo_routes.settings.core_memory_demo_artifacts_root = old_root
        self.assertEqual(str(path), resp.path)

    def test_unknown_artifact_still_rejected(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        with self.assertRaises(HTTPException):
            demo_routes.benchmark_artifact_download('bench-test123', 'not-allowed.json')

    def test_artifact_falls_back_to_benchmark_store(self):
        if demo_routes is None:
            self.skipTest('pydantic_settings unavailable')
        with tempfile.TemporaryDirectory() as td:
            old_root = demo_routes.settings.core_memory_demo_artifacts_root
            old_read = demo_routes.benchmark_store.read_artifact
            demo_routes.settings.core_memory_demo_artifacts_root = td
            demo_routes.benchmark_store.read_artifact = lambda run_id, filename: {
                'content_type': 'application/json',
                'body': b'{"ok": true}',
                'size_bytes': 12,
            }
            try:
                resp = demo_routes.benchmark_artifact_download('bench-test123', 'report.json')
            finally:
                demo_routes.settings.core_memory_demo_artifacts_root = old_root
                demo_routes.benchmark_store.read_artifact = old_read
        self.assertEqual(resp.media_type, 'application/json')


if __name__ == '__main__':
    unittest.main()
