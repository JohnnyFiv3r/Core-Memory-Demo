from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Deque

from fastapi import HTTPException, Request, status

from app.core.config import settings


class _SlidingWindowLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, Deque[float]] = {}

    def allow(self, *, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - max(1, int(window_seconds))
        limit = max(1, int(max_requests))
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                q = deque()
                self._hits[key] = q
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


class _HeavyGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_total = 0
        self._active_by_identity: dict[str, int] = {}

    def acquire(self, identity_key: str) -> bool:
        with self._lock:
            max_active = int(getattr(settings, "abuse_heavy_max_concurrent", 0) or 0)
            max_per_identity = max(1, int(getattr(settings, "abuse_heavy_max_concurrent_per_identity", 1) or 1))
            key = str(identity_key or "unknown").strip() or "unknown"

            if max_active > 0 and self._active_total >= max_active:
                return False
            if int(self._active_by_identity.get(key) or 0) >= max_per_identity:
                return False

            self._active_total += 1
            self._active_by_identity[key] = int(self._active_by_identity.get(key) or 0) + 1
            return True

    def release(self, identity_key: str) -> None:
        with self._lock:
            key = str(identity_key or "unknown").strip() or "unknown"
            self._active_total = max(0, self._active_total - 1)
            active_for_key = max(0, int(self._active_by_identity.get(key) or 0) - 1)
            if active_for_key <= 0:
                self._active_by_identity.pop(key, None)
            else:
                self._active_by_identity[key] = active_for_key


_LIMITER = _SlidingWindowLimiter()
_HEAVY_GATE = _HeavyGate()


def _identity(request: Request) -> str:
    header_id = str(request.headers.get("x-core-memory-session") or "").strip()
    if header_id:
        return f"sess:{header_id[:128]}"

    principal = getattr(request.state, "principal", None)
    if isinstance(principal, dict):
        sub = str(principal.get("sub") or "").strip()
        if sub:
            return f"sub:{sub}"
    ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}"


def _rate_limit_or_429(*, request: Request, bucket: str, max_requests: int, window_seconds: int) -> None:
    key = f"{bucket}:{_identity(request)}"
    if not _LIMITER.allow(key=key, max_requests=max_requests, window_seconds=window_seconds):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"rate_limit_exceeded:{bucket}")


async def rate_limit_general(request: Request) -> None:
    _rate_limit_or_429(
        request=request,
        bucket="general",
        max_requests=settings.abuse_general_max_requests,
        window_seconds=settings.abuse_general_window_seconds,
    )


async def rate_limit_chat(request: Request) -> None:
    _rate_limit_or_429(
        request=request,
        bucket="chat",
        max_requests=settings.abuse_chat_max_requests,
        window_seconds=settings.abuse_chat_window_seconds,
    )


async def rate_limit_heavy(request: Request) -> None:
    _rate_limit_or_429(
        request=request,
        bucket="heavy",
        max_requests=settings.abuse_heavy_max_requests,
        window_seconds=settings.abuse_heavy_window_seconds,
    )


@contextmanager
def heavy_operation_slot(request: Request, *, slot_key: str | None = None) -> None:
    key = str(slot_key or "").strip() or _identity(request)
    if not _HEAVY_GATE.acquire(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="heavy_operation_in_progress",
            headers={"Retry-After": "2"},
        )
    try:
        yield
    finally:
        _HEAVY_GATE.release(key)
