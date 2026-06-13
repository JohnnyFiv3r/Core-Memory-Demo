from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

# Fail-fast preflight for the external embeddings backend.
#
# The benchmark worker re-embeds its whole corpus in-process. If the embeddings
# key is wrong, every per-turn Qdrant upsert fails with the SAME error and the
# worker still seeds all ~5.9k turns before the required-semantic gate finally
# aborts the run — ~90s of identical "qdrant upsert failed ... http_401" noise
# with no hint of the cause. This probes the backend with ONE tiny embed call
# before seeding and turns that into an instant, actionable diagnostic.
#
# Resolution intentionally mirrors core_memory.provider_config for the
# openai-compatible adapter (which "openai" aliases to): explicit embeddings key
# vars first, then OPENAI_API_KEY, then OPENROUTER_API_KEY. The last fallback is
# a known trap — an OpenRouter key (sk-or-…) sent to api.openai.com 401s every
# time — so the diagnostic calls it out by name.

_EXTERNAL_PROVIDERS = {"openai", "openai-compatible", "openai_compatible", "openrouter", "azure", "gemini", "google"}
_KEY_VARS = (
    "CORE_MEMORY_EMBEDDINGS_API_KEY",
    "CORE_MEMORY_EMBEDDING_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)

# HTTP statuses that are deterministic credential/endpoint problems: re-running
# will not help, so the job should fail immediately with the diagnostic.
_FATAL_HTTP = {400, 401, 403, 404}


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _mask_key(key: str) -> str:
    k = str(key or "").strip()
    if not k:
        return "(empty)"
    if len(k) <= 12:
        return f"{k[0]}…{k[-1]} (len={len(k)})"
    return f"{k[:7]}…{k[-4:]} (len={len(k)})"


def resolve_embedding_key() -> tuple[str, str]:
    """Return (var_name, value) the embeddings backend will actually send."""
    for name in _KEY_VARS:
        value = _env(name)
        if value:
            return name, value
    return "", ""


def embedding_key_env_audit() -> list[dict[str, Any]]:
    """Masked snapshot of every candidate key var, in resolution order.

    The decisive diagnostic when a freshly-rotated OPENAI_API_KEY still 401s:
    it shows which vars are set and which one actually wins, so a stale
    CORE_MEMORY_EMBEDDINGS_API_KEY silently shadowing OPENAI_API_KEY is obvious
    at a glance instead of invisible.
    """
    _, winner_value = resolve_embedding_key()
    winner_name, _ = resolve_embedding_key()
    rows: list[dict[str, Any]] = []
    for name in _KEY_VARS:
        present = bool(_env(name))
        rows.append({
            "var": name,
            "present": present,
            "value": _mask_key(_env(name)) if present else "(unset)",
            "used": present and name == winner_name,
        })
    return rows


def _read_api_error(exc: urllib.error.HTTPError) -> dict[str, str]:
    """Pull OpenAI's structured error out of an HTTPError body.

    OpenAI returns the real reason in the response JSON, e.g.
    ``{"error": {"code": "insufficient_permissions", "message": "... Missing
    scopes: model.request"}}`` with HTTP 401. Without reading it, a
    scope-restricted project key is indistinguishable from a plain bad key.
    """
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:
        return {}
    try:
        err = (json.loads(raw) or {}).get("error") or {}
    except Exception:
        return {"message": raw.strip()[:300]}
    return {
        "message": str(err.get("message") or "").strip(),
        "code": str(err.get("code") or "").strip(),
        "type": str(err.get("type") or "").strip(),
    }


def _probe_openai_embeddings(*, base_url: str, model: str, key: str, timeout: float) -> dict[str, Any]:
    data = json.dumps({"model": model, "input": "preflight"}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    req = urllib.request.Request(base_url + "/embeddings", data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - provider-configured endpoint
        body = json.loads(resp.read().decode("utf-8"))
    rows = list(body.get("data") or [])
    vec = list((rows[0] or {}).get("embedding") or []) if rows else []
    if not vec:
        return {"ok": False, "error": "empty_embedding_response"}
    return {"ok": True, "dim": len(vec)}


def preflight_embedding_backend(
    *,
    timeout: float = 20.0,
    probe: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate the external embeddings backend before a benchmark seeds a corpus.

    Returns a dict with at least ``ok`` (bool) and ``fatal`` (bool). ``fatal``
    is True only for deterministic credential/endpoint failures the caller
    should abort on; transient/unknown probe failures are non-fatal so a flaky
    network does not block an otherwise-valid run.
    """
    provider = (_env("CORE_MEMORY_EMBEDDINGS_PROVIDER") or _env("CORE_MEMORY_EMBEDDING_PROVIDER")).lower()
    external = provider in _EXTERNAL_PROVIDERS or bool(_env("CORE_MEMORY_EMBEDDINGS_BASE_URL") or _env("CORE_MEMORY_EMBEDDING_BASE_URL"))
    if not external:
        return {"ok": True, "fatal": False, "skipped": True, "reason": f"provider={provider or 'default'} uses no external embedding key"}

    if provider in {"gemini", "google"}:
        # Gemini uses its own key var and endpoint; only flag a missing key here.
        if not (_env("CORE_MEMORY_EMBEDDINGS_API_KEY") or _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")):
            return {"ok": False, "fatal": True, "error": "missing_embedding_api_key", "provider": provider,
                    "hint": "Embeddings provider is gemini/google but no GEMINI_API_KEY/GOOGLE_API_KEY is set on this service."}
        return {"ok": True, "fatal": False, "skipped": True, "reason": "gemini key present (not live-probed)"}

    key_var, key = resolve_embedding_key()
    model = (_env("CORE_MEMORY_EMBEDDINGS_MODEL") or _env("CORE_MEMORY_EMBEDDING_MODEL") or "text-embedding-3-large")
    base_url = (_env("CORE_MEMORY_EMBEDDINGS_BASE_URL") or _env("CORE_MEMORY_EMBEDDING_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    on_openai = "openai.com" in base_url
    audit = embedding_key_env_audit()

    if not key:
        return {
            "ok": False, "fatal": True, "error": "missing_embedding_api_key",
            "provider": provider, "base_url": base_url, "model": model, "key_audit": audit,
            "hint": ("No embeddings API key is set on THIS service. On Render, OPENAI_API_KEY is a "
                     "per-service secret (sync:false): set it on the core-memory-demo-benchmark-worker "
                     "cron service, not only on the web service."),
        }

    hints: list[str] = []
    # Stale explicit embeddings key shadowing a freshly-rotated OPENAI_API_KEY:
    # the resolver prefers CORE_MEMORY_EMBEDDINGS_API_KEY/EMBEDDING_API_KEY, so a
    # leftover value there is sent instead of the new OPENAI_API_KEY. This is the
    # prime suspect when the worker "has the fresh key" but still 401s.
    if key_var in {"CORE_MEMORY_EMBEDDINGS_API_KEY", "CORE_MEMORY_EMBEDDING_API_KEY"} and _env("OPENAI_API_KEY"):
        hints.append(f"{key_var} is set and takes precedence over OPENAI_API_KEY — the OpenAI key you rotated is "
                     f"being IGNORED. Clear {key_var} on the worker (or put the fresh key there instead).")
    if key.startswith("sk-or-") and on_openai:
        hints.append("Key looks like an OpenRouter key (sk-or-…) but base_url is api.openai.com, which has no "
                     "/embeddings for it — this 401s every time. Set a real OpenAI key in OPENAI_API_KEY, or "
                     "unset OPENROUTER_API_KEY on the worker so it stops shadowing OPENAI_API_KEY.")
    if not on_openai:
        hints.append(f"base_url is {base_url} (a custom/override endpoint, not api.openai.com): an OpenAI key sent "
                     f"there will 401. Check CORE_MEMORY_EMBEDDINGS_BASE_URL on the worker.")
    raw = os.environ.get(key_var) or ""
    if raw != raw.strip() or (raw.strip()[:1] in {'"', "'"}):
        hints.append(f"{key_var} has surrounding whitespace or quotes in the dashboard value; remove them.")

    runner = probe or _probe_openai_embeddings
    try:
        result = runner(base_url=base_url, model=model, key=key, timeout=timeout)
    except urllib.error.HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        api_err = _read_api_error(exc)
        api_code = (api_err.get("code") or "").lower()
        api_msg = api_err.get("message") or ""
        # OpenAI returns 401 for a scope-restricted project key (sk-proj-…), not
        # just for an invalid one. The body disambiguates: surface it verbatim.
        if "insufficient_permissions" in api_code or "missing scopes" in api_msg.lower() or "model.request" in api_msg.lower():
            hints.insert(0, "This is a permissions problem, NOT a bad key: the key authenticates but its project "
                            "role lacks model/embeddings access (missing scope model.request). It is almost "
                            "certainly a Restricted project key (sk-proj-…). In the OpenAI dashboard, give this key "
                            "'Model capabilities' write access (or use an unrestricted/all-permissions key).")
        elif "invalid_api_key" in api_code or code == 401:
            hints.insert(0, "OpenAI returned 401 Unauthorized: the key is invalid, revoked, or for the wrong "
                            "project/org. Verify the exact value on the benchmark-worker service.")
        elif code == 403:
            hints.insert(0, "OpenAI returned 403: the key lacks access to this embedding model, or billing/quota "
                            "is disabled for its project.")
        elif code == 404:
            hints.insert(0, f"404 from {base_url}/embeddings: base_url does not serve an OpenAI-style embeddings endpoint.")
        if api_msg:
            hints.append(f"OpenAI said: {api_msg}")
        return {"ok": False, "fatal": code in _FATAL_HTTP, "error": f"http_{code or 'error'}",
                "key_source": key_var, "key": _mask_key(key), "provider": provider,
                "base_url": base_url, "model": model, "key_audit": audit,
                "api_error": api_err, "hint": " ".join(hints).strip()}
    except Exception as exc:  # noqa: BLE001 - transient/network: advise but don't block the run
        return {"ok": False, "fatal": False, "error": f"probe_failed:{type(exc).__name__}:{exc}",
                "key_source": key_var, "key": _mask_key(key), "provider": provider,
                "base_url": base_url, "model": model, "key_audit": audit, "hint": " ".join(hints).strip()}

    if bool((result or {}).get("ok")):
        return {"ok": True, "fatal": False, "key_source": key_var, "key": _mask_key(key),
                "provider": provider, "base_url": base_url, "model": model, "key_audit": audit,
                "dim": int((result or {}).get("dim") or 0)}
    return {"ok": False, "fatal": True, "error": str((result or {}).get("error") or "embedding_probe_failed"),
            "key_source": key_var, "key": _mask_key(key), "provider": provider,
            "base_url": base_url, "model": model, "key_audit": audit, "hint": " ".join(hints).strip()}


def format_preflight_failure(result: dict[str, Any]) -> str:
    """One-line, log-friendly rendering of a failed preflight result."""
    parts = [f"embedding_preflight_failed:{result.get('error') or 'unknown'}"]
    if result.get("key_source"):
        parts.append(f"key_source={result['key_source']}")
    if result.get("key"):
        parts.append(f"key={result['key']}")
    if result.get("provider"):
        parts.append(f"provider={result['provider']}")
    if result.get("base_url"):
        parts.append(f"base_url={result['base_url']}")
    if result.get("model"):
        parts.append(f"model={result['model']}")
    line = " ".join(parts)
    hint = str(result.get("hint") or "").strip()
    return f"{line} | {hint}" if hint else line


def format_preflight_report(result: dict[str, Any]) -> str:
    """Multi-line human report for the CLI: status, env audit, and hint."""
    lines: list[str] = []
    status = "OK" if result.get("ok") else ("FATAL" if result.get("fatal") else "WARN")
    lines.append(f"embedding preflight: {status}")
    if result.get("skipped"):
        lines.append(f"  skipped: {result.get('reason')}")
        return "\n".join(lines)
    if result.get("error"):
        lines.append(f"  error:     {result['error']}")
    if result.get("provider"):
        lines.append(f"  provider:  {result['provider']}")
    if result.get("base_url"):
        lines.append(f"  base_url:  {result['base_url']}")
    if result.get("model"):
        lines.append(f"  model:     {result['model']}")
    audit = result.get("key_audit") or []
    if audit:
        lines.append("  key vars (resolution order — first present wins):")
        for row in audit:
            marker = " <-- USED" if row.get("used") else ""
            lines.append(f"    {row['var']}: {row['value']}{marker}")
    hint = str(result.get("hint") or "").strip()
    if hint:
        lines.append(f"  fix: {hint}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m app.core.embedding_preflight`` — probe the live env now.

    Run this on the benchmark worker shell to see, instantly and without
    queuing a job, which key var is actually used and why a probe fails.
    """
    from app.core.semantic_env import configure_shared_semantic_backend_env

    configure_shared_semantic_backend_env()
    result = preflight_embedding_backend()
    print(format_preflight_report(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
