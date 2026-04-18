# Core Memory Demo review corrections (2026-04-18)

This note captures stale/inaccurate items observed in `core-memory-demo-fix-list` when compared against `MidwestJohn/corememorydemo` at `43b2d8c` plus follow-up corrections landed today.

## Corrected / stale assertions

- **D2 (Auth0 blocks local eval) is partially stale**
  - `demo_auth_enabled` defaults to `false` in backend settings, so local eval does not require Auth0 unless explicitly enabled.
  - `.env.example` and README now document this default.

- **D14 (rate limits are global-anonymous) is stale**
  - Rate limiter identity key is scoped by principal sub when available, otherwise client IP (`sub:<id>` or `ip:<host>`), not a single global bucket.

- **D6 context update**
  - `heavy_operation_slot()` still enforces shared heavy-slot concurrency (default 1), but now returns explicit `429 heavy_operation_in_progress` + `Retry-After` and avoids burning heavy rate bucket for slot-collisions due to routing changes already in `43b2d8c`.

## Additional hardening applied in this correction pass

- **Pinned backend dependency**
  - `backend/requirements.txt` now pins Core-Memory to a concrete commit SHA instead of `@master`.

- **Removed hidden React parity switch from primary app path**
  - `frontend/src/App.tsx` no longer branches on `#react` into `ReactParityApp`.
  - This prevents accidental drift from a hidden side-route and clarifies the live surface.

## Remaining concern from the review

- heavy operation slot default remains 1 total slot (now caller-scoped with per-identity concurrency controls).

## Additional follow-up corrections

- Benchmark "last run" surfaces now use a disk-backed snapshot fallback (`benchmark-history.jsonl`) and mutable in-process cache updates (no stale imported-global rebinds).
- Root app no longer uses iframe embedding as the primary delivery path and now defaults to the chat surface (`chris-demo.html`).
- Graph View no longer redirects away from chat; it opens as an in-app overlay (`graph.html` iframe modal) and closes back to the same chat session.

## Follow-up items completed after this correction pass

- Graph-first landing shipped (`/` now defaults to `/graph.html`, with `?view=demo` legacy fallback).
- Turn token tracking no longer uses `(chars + 500) // 4`; runtime now uses model-aware estimation (tiktoken when available, deterministic byte/segment fallback otherwise).
