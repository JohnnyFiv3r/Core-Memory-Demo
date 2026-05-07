from __future__ import annotations

import os
from typing import Any


def configure_shared_semantic_backend_env() -> dict[str, Any]:
    """Wire demo semantic retrieval to the shared Postgres/pgvector backend.

    The benchmark system already has a durable Render Postgres DSN via
    BENCHMARK_DATABASE_URL. Core-Memory's pgvector backend intentionally reads a
    separate CORE_MEMORY_PG_DSN, so bridge it here unless the deployment provides
    an explicit semantic DSN. This keeps benchmark storage tables separate
    (`benchmarks.*`) while using the same database service for real semantic
    retrieval.
    """

    before = {
        "CORE_MEMORY_VECTOR_BACKEND": os.environ.get("CORE_MEMORY_VECTOR_BACKEND"),
        "CORE_MEMORY_PG_DSN": os.environ.get("CORE_MEMORY_PG_DSN"),
        "CORE_MEMORY_CANONICAL_SEMANTIC_MODE": os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"),
        "CORE_MEMORY_EMBEDDINGS_PROVIDER": os.environ.get("CORE_MEMORY_EMBEDDINGS_PROVIDER"),
    }

    shared_dsn = str(
        os.environ.get("CORE_MEMORY_PG_DSN")
        or os.environ.get("CORE_MEMORY_SHARED_PG_DSN")
        or os.environ.get("BENCHMARK_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()

    changed: dict[str, str] = {}
    if shared_dsn and not str(os.environ.get("CORE_MEMORY_PG_DSN") or "").strip():
        os.environ["CORE_MEMORY_PG_DSN"] = shared_dsn
        changed["CORE_MEMORY_PG_DSN"] = "shared_postgres_dsn"

    if str(os.environ.get("CORE_MEMORY_PG_DSN") or "").strip() and not str(os.environ.get("CORE_MEMORY_VECTOR_BACKEND") or "").strip():
        os.environ["CORE_MEMORY_VECTOR_BACKEND"] = "pgvector"
        changed["CORE_MEMORY_VECTOR_BACKEND"] = "pgvector"

    if str(os.environ.get("CORE_MEMORY_VECTOR_BACKEND") or "").strip().lower() in {"pgvector", "postgres", "postgresql"}:
        if not str(os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE") or "").strip():
            os.environ["CORE_MEMORY_CANONICAL_SEMANTIC_MODE"] = "required"
            changed["CORE_MEMORY_CANONICAL_SEMANTIC_MODE"] = "required"
        if os.environ.get("OPENAI_API_KEY") and not str(os.environ.get("CORE_MEMORY_EMBEDDINGS_PROVIDER") or "").strip():
            os.environ["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"
            changed["CORE_MEMORY_EMBEDDINGS_PROVIDER"] = "openai"

    after = {
        "CORE_MEMORY_VECTOR_BACKEND": os.environ.get("CORE_MEMORY_VECTOR_BACKEND"),
        "CORE_MEMORY_PG_DSN": "set" if os.environ.get("CORE_MEMORY_PG_DSN") else "",
        "CORE_MEMORY_CANONICAL_SEMANTIC_MODE": os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"),
        "CORE_MEMORY_EMBEDDINGS_PROVIDER": os.environ.get("CORE_MEMORY_EMBEDDINGS_PROVIDER"),
    }
    return {"changed": changed, "before": before, "after": after}
