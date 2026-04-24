import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.runtime import semantic_mode


class TestRuntimeSemanticMode(unittest.TestCase):
    def test_semantic_mode_can_override_and_restore_build_on_read_and_provider(self):
        os.environ.pop("CORE_MEMORY_CANONICAL_SEMANTIC_MODE", None)
        os.environ.pop("CORE_MEMORY_SEMANTIC_BUILD_ON_READ", None)
        os.environ.pop("CORE_MEMORY_EMBEDDINGS_PROVIDER", None)

        with semantic_mode("required", build_on_read=True, embeddings_provider="hash"):
            self.assertEqual("required", os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"))
            self.assertEqual("1", os.environ.get("CORE_MEMORY_SEMANTIC_BUILD_ON_READ"))
            self.assertEqual("hash", os.environ.get("CORE_MEMORY_EMBEDDINGS_PROVIDER"))

        self.assertIsNone(os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"))
        self.assertIsNone(os.environ.get("CORE_MEMORY_SEMANTIC_BUILD_ON_READ"))
        self.assertIsNone(os.environ.get("CORE_MEMORY_EMBEDDINGS_PROVIDER"))


if __name__ == "__main__":
    unittest.main()
