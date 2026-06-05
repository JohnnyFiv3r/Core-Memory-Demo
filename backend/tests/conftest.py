from __future__ import annotations

import os

import pytest


_ENV_KEYS_TO_RESTORE = (
    "CORE_MEMORY_CANONICAL_SEMANTIC_MODE",
    "CORE_MEMORY_EMBEDDINGS_PROVIDER",
    "CORE_MEMORY_VECTOR_BACKEND",
    "CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS",
    "CORE_MEMORY_EMBEDDINGS_MODEL",
    "CORE_MEMORY_GRAPH_BACKEND",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def restore_benchmark_env():
    before = {key: os.environ.get(key) for key in _ENV_KEYS_TO_RESTORE}
    yield
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
