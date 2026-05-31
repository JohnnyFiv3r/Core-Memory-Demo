from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _qdrant_path_for_root(root: str | Path) -> Path:
    raw = _env_value("CORE_MEMORY_QDRANT_PATH")
    if raw:
        return Path(raw)
    return Path(root) / ".beads" / "qdrant"


def normalize_embedded_qdrant_summary(summary: dict[str, Any], *, root: str | Path) -> dict[str, Any]:
    """Fix semantic doctor output for embedded Qdrant path mode.

    Core Memory's Qdrant backend supports embedded local-path mode when
    CORE_MEMORY_QDRANT_URL is unset, but the current semantic doctor probes the
    server-mode default (localhost:6333).  The hosted demo intentionally uses
    embedded Qdrant on Render's persistent disk, so treat a writable qdrant path
    as reachable and let rows_count decide whether the backend has been built.
    """

    out = dict(summary or {})
    vector_backend = _env_value("CORE_MEMORY_VECTOR_BACKEND").lower() or "qdrant"
    if vector_backend != "qdrant" or _env_value("CORE_MEMORY_QDRANT_URL"):
        return out

    path = _qdrant_path_for_root(root)
    try:
        path.mkdir(parents=True, exist_ok=True)
        path_ok = path.is_dir() and os.access(path, os.W_OK)
        path_error = "" if path_ok else f"qdrant_path_not_writable:{path}"
    except Exception as exc:  # pragma: no cover - defensive filesystem guard
        path_ok = False
        path_error = f"qdrant_path_unavailable:{exc}"

    backend = str(out.get("backend") or "not_built")
    rows_count = int(out.get("rows_count") or 0)
    if backend == "not_built" and rows_count > 0:
        backend = "qdrant"

    out.update(
        {
            "backend": backend,
            "connectivity_checked": True,
            "connectivity_ok": bool(path_ok),
            "connectivity_error": path_error,
            "deployment_profile": "embedded_qdrant_path",
            "multi_worker_safe": False,
        }
    )
    if path_ok and backend == "qdrant" and rows_count > 0:
        out["usable_backend"] = True
        out["concurrency_warning"] = ""
        out["next_step"] = "Embedded Qdrant semantic backend is ready."
    elif path_ok:
        out["concurrency_warning"] = str(out.get("concurrency_warning") or "")
    return out


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
        "CORE_MEMORY_QDRANT_PATH",
        "CORE_MEMORY_KUZU_PATH",
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

    if _env_value("CORE_MEMORY_VECTOR_BACKEND").lower() == "qdrant":
        if not _env_value("CORE_MEMORY_QDRANT_URL") and not _env_value("CORE_MEMORY_QDRANT_PATH"):
            root = _env_value("CORE_MEMORY_ROOT") or "./var/core-memory"
            os.environ["CORE_MEMORY_QDRANT_PATH"] = str(_qdrant_path_for_root(root))
            changed["CORE_MEMORY_QDRANT_PATH"] = os.environ["CORE_MEMORY_QDRANT_PATH"]
        if not _env_value("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"):
            os.environ["CORE_MEMORY_CANONICAL_SEMANTIC_MODE"] = "required"
            changed["CORE_MEMORY_CANONICAL_SEMANTIC_MODE"] = "required"

    if _env_value("CORE_MEMORY_GRAPH_BACKEND").lower() == "kuzu" and not _env_value("CORE_MEMORY_KUZU_PATH"):
        root = _env_value("CORE_MEMORY_ROOT") or "./var/core-memory"
        os.environ["CORE_MEMORY_KUZU_PATH"] = str(Path(root) / ".beads" / "kuzu")
        changed["CORE_MEMORY_KUZU_PATH"] = os.environ["CORE_MEMORY_KUZU_PATH"]

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
        "CORE_MEMORY_QDRANT_PATH": os.environ.get("CORE_MEMORY_QDRANT_PATH"),
        "CORE_MEMORY_KUZU_PATH": os.environ.get("CORE_MEMORY_KUZU_PATH"),
        "CORE_MEMORY_CANONICAL_SEMANTIC_MODE": os.environ.get("CORE_MEMORY_CANONICAL_SEMANTIC_MODE"),
        "CORE_MEMORY_SEMANTIC_AUTODRAIN": os.environ.get("CORE_MEMORY_SEMANTIC_AUTODRAIN"),
        "CORE_MEMORY_EMBEDDINGS_PROVIDER": os.environ.get("CORE_MEMORY_EMBEDDINGS_PROVIDER"),
    }
    return {"changed": changed, "before": before, "after": after}
