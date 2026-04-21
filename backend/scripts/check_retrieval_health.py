#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError


def _get_json(url: str, token: str = "") -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, headers=headers)
    with request.urlopen(req, timeout=30) as res:
        raw = res.read().decode("utf-8", "replace")
    return json.loads(raw or "{}")


def evaluate_runtime_payload(payload: dict[str, Any], *, fail_on_spike: bool = True) -> dict[str, Any]:
    diag = dict(((payload.get("last_turn") or {}).get("diagnostics") or {}))
    warnings = [str(w or "").strip().lower() for w in list(diag.get("warnings") or [])]
    result_count = int(diag.get("result_count") or 0)
    flags = [str(x or "").strip().lower() for x in list(diag.get("retrieval_alert_flags") or [])]

    issues: list[str] = []
    if any("semantic_backend_query_error:programmingerror" in w for w in warnings):
        issues.append("semantic_backend_programmingerror")
    if result_count == 0 and any("semantic_backend_unavailable" in w for w in warnings):
        issues.append("empty_results_with_semantic_backend_unavailable")

    if fail_on_spike and bool(diag.get("retrieval_alert_spike")):
        issues.append("retrieval_alert_spike")

    return {
        "ok": not bool(issues),
        "issues": issues,
        "result_count": result_count,
        "warnings": warnings,
        "retrieval_alert_flags": flags,
        "retrieval_alert_recent_count": int(diag.get("retrieval_alert_recent_count") or 0),
        "retrieval_alert_spike": bool(diag.get("retrieval_alert_spike")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Check demo retrieval diagnostics for critical regression signals.")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    ap.add_argument("--token", default="", help="Optional bearer token")
    ap.add_argument("--allow-spike", action="store_true", help="Do not fail when retrieval_alert_spike=true")
    args = ap.parse_args()

    url = args.base_url.rstrip("/") + "/api/demo/runtime"
    try:
        payload = _get_json(url, token=str(args.token or ""))
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "url": url}, indent=2))
        return 2

    out = evaluate_runtime_payload(payload, fail_on_spike=not bool(args.allow_spike))
    out["url"] = url
    print(json.dumps(out, indent=2))
    return 0 if bool(out.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
