from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Core-Memory PR #169 changed the canonical retrieval projection so association
# anchors (entities/topics/*_keys/candidates/etc.) are now embedded and included
# in lexical scoring. Existing Render disks can still hold a manifest built with
# the older projection, so queue one reconcile rebuild per persistent root.
_UNIFIED_BEAD_PROJECTION_UPGRADE = "core-memory-pr-169-unified-bead-projection"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def queue_semantic_projection_upgrade_once(root: str | Path) -> dict[str, Any]:
    """Queue the PR #169 projection rebuild once for a persistent demo root.

    The newest Core-Memory package automatically uses the richer projection for
    new writes/rebuilds, but persisted demo indexes need a full reconcile so the
    background semantic worker refreshes existing Qdrant/FastEmbed rows through
    the full rebuild path instead of the default semantic delta path.
    """
    root_p = Path(root)
    marker_path = root_p / ".beads" / "semantic" / "projection-upgrades.json"
    marker = _read_json(marker_path)
    applied = {str(v) for v in list(marker.get("applied") or []) if str(v).strip()}
    if _UNIFIED_BEAD_PROJECTION_UPGRADE in applied:
        return {"ok": True, "queued": False, "already_applied": True, "upgrade": _UNIFIED_BEAD_PROJECTION_UPGRADE}

    try:
        from core_memory.retrieval.lifecycle import enqueue_semantic_rebuild

        queue = enqueue_semantic_rebuild(root_p, mode="reconcile")
    except Exception as exc:  # pragma: no cover - startup should not hard-fail
        logger.warning("semantic_projection_upgrade_queue_failed: %s", exc)
        return {"ok": False, "queued": False, "error": str(exc), "upgrade": _UNIFIED_BEAD_PROJECTION_UPGRADE}

    applied.add(_UNIFIED_BEAD_PROJECTION_UPGRADE)
    marker["applied"] = sorted(applied)
    marker["last_queued_upgrade"] = _UNIFIED_BEAD_PROJECTION_UPGRADE
    _write_json(marker_path, marker)

    queue = dict(queue or {})
    return {
        "ok": True,
        "queued": bool(queue.get("queued", True)),
        "already_applied": False,
        "upgrade": _UNIFIED_BEAD_PROJECTION_UPGRADE,
        "queue": queue,
    }
