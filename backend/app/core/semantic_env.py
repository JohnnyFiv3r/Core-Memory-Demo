from __future__ import annotations

import os
from typing import Any


def _env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def configure_shared_semantic_backend_env() -> dict[str, Any]:
    """Configure Core Memory's embedded Qdrant + Kuzu defaults for the demo.

    The benchmark queue still reads BENCHMARK_DATABASE_URL directly. This bridge
    only sets Core Memory retrieval defaults when the deployment has not provided
    explicit overrides.
    """

    keys = (
        "CORE_MEMORY_VECTOR_BACKEND",
        "CORE_MEMORY_GRAPH_BACKEND",
        "CORE_MEMORY_PG_DSN",
        "CORE_MEMORY_CANONICAL_SEMANTIC_MODE",
        "CORE_MEMORY_SEMANTIC_AUTODRAIN",
        "CORE_MEMORY_EMBEDDINGS_PROVIDER",
    )
    before = {key: os.environ.get(key) for key in keys}

    changed: dict[str, str] = {}

    if not _env_value("CORE_MEMORY_VECTOR_BACKEND"):
        os.environ["CORE_MEMORY_VECTOR_BACKEND"] = "qdrant"
        changed["CORE_MEMORY_VECTOR_BACKEND"] = "qdrant"

    if not _env_value("CORE_MEMORY_GRAPH_BACKEND"):
        os.environ["CORE_MEMORY_GRAPH_BACKEND"] = "kuzu"
        changed["CORE_MEMORY_GRAPH_BACKEND"] = "kuzu"

    if (
        _env_value("CORE_MEMORY_VECTOR_BACKEND").lower() == "qdrant"
        and not _env_value("CORE_MEMORY_CANONICAL_SEMANTIC_MODE")
    ):
        os.environ["CORE_MEMORY_CANONICAL_SEMANTIC_MODE"] = "required"
        changed["CORE_MEMORY_CANONICAL_SEMANTIC_MODE"] = "required"

    if _env_value("CORE_MEMORY_VECTOR_BACKEND").lower() in {"pgvector", "postgres", "postgresql"}:
        if not _env_value("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"):
            os.environ["CORE_MEMORY_CANONICAL_SEMANTIC_MODE"] = "required"
            changed["CORE_MEMORY_CANONICAL_SEMANTIC_MODE"] = "required"
        if os.environ.get("OPENAI_API_KEY") and not _env_value("CORE_MEMORY_EMBEDDINGS_PROVIDER"):
            os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
            changed["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"

    if not _env_value("CORE_MEMORY_SEMANTIC_AUTODRAIN"):
        os.environ["CORE_MEMORY_SEMANTIC_AUTODRAIN"] = "off"
        changed["CORE_MEMORY_SEMANTIC_AUTODRAIN"] = "off"

    after = {
        "CORE_MEMORY_VECTOR_BACKEND": os.environ.get("CORE_MEMORY_VECTOR_BACKEND"),
        "CORE_MEMORY_GRAPH_BACKEND": os.environ.get("CORE_MEMORY_GRAPH_BACKEND"),
        "CORE_MEMORY_PG_DSN": "set" if os.environ.get("CORE_MEMORY_PG_DSN") else "",
        "CORE_MEMORY_CANONICAL_SEMANTIC_MODE": os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"),
        "CORE_MEMORY_SEMANTIC_AUTODRAIN": os.environ.get("CORE_MEMORY_SEMANTIC_AUTODRAIN"),
        "CORE_MEMORY_EMBEDDINGS_PROVIDER": os.environ.get("CORE_MEMORY_EMBEDDINGS_PROVIDER"),
    }
    return {"changed": changed, "before": before, "after": after}
