from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _patch_pgvector_search() -> bool:
    try:
        from core_memory.retrieval import vector_backend as vb  # type: ignore
    except Exception as exc:
        logger.warning("hotfix_pgvector_import_failed: %s", exc)
        return False

    cls = getattr(vb, "PgvectorBackend", None)
    if cls is None:
        return False

    if bool(getattr(cls, "_cmdemo_search_hotfix_applied", False)):
        return True

    def patched_search(
        self,
        query_embedding: list[float],
        k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        where_params: list[Any] = []
        query_vec = str(query_embedding)

        if filters:
            if "type" in filters:
                conditions.append("type = %s")
                where_params.append(filters["type"])
            if "status" in filters:
                conditions.append("status = %s")
                where_params.append(filters["status"])
            if "session_id" in filters:
                conditions.append("session_id = %s")
                where_params.append(filters["session_id"])
            if "created_after" in filters:
                conditions.append("created_at >= %s")
                where_params.append(filters["created_after"])
            if "created_before" in filters:
                conditions.append("created_at <= %s")
                where_params.append(filters["created_before"])

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        params: list[Any] = [query_vec] + where_params + [query_vec, max(1, int(k))]

        cur = self._conn.execute(
            f"""
            SELECT bead_id, 1 - (embedding <=> %s::vector) AS score, metadata
            FROM {self._table}{where}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            params,
        )

        results: list[dict[str, Any]] = []
        for row in cur.fetchall():
            results.append(
                {
                    "bead_id": row[0],
                    "score": float(row[1]),
                    "metadata": json.loads(row[2]) if isinstance(row[2], str) else dict(row[2] or {}),
                }
            )
        return results

    setattr(cls, "search", patched_search)
    setattr(cls, "_cmdemo_search_hotfix_applied", True)
    logger.warning("hotfix_applied: core_memory.retrieval.vector_backend.PgvectorBackend.search")
    return True


def apply_runtime_hotfixes() -> dict[str, Any]:
    return {
        "pgvector_search_param_order": _patch_pgvector_search(),
    }
