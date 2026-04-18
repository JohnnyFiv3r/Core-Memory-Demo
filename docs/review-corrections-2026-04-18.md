# Core Memory Demo review corrections (2026-04-18)

This note captures stale/inaccurate items observed in `core-memory-demo-fix-list` when compared against `MidwestJohn/corememorydemo` at `43b2d8c` plus follow-up corrections landed today.

## Corrected / stale assertions

- **D2 (Auth0 blocks local eval) is partially stale**
  - `demo_auth_enabled` defaults to `false` in backend settings, so local eval does not require Auth0 unless explicitly enabled.
  - `.env.example` and README now document this default.

- **D14 (rate limits are global-anonymous) is stale**
  - Rate limiter identity key is scoped by client session header when present (`sess:<id>`), then principal sub, then client IP (`sub:<id>` / `ip:<host>`), not a single global bucket.

- **D6 context update**
  - `heavy_operation_slot()` supports per-identity-only gating by default (`ABUSE_HEAVY_MAX_CONCURRENT=0`, `ABUSE_HEAVY_MAX_CONCURRENT_PER_IDENTITY=1`), so one caller's heavy run does not globally block all others.

## Additional hardening applied in this correction pass

- **Pinned backend dependency**
  - `backend/requirements.txt` now pins Core-Memory to a concrete commit SHA instead of `@master`.

- **Removed hidden React parity switch from primary app path**
  - `frontend/src/App.tsx` no longer branches on `#react` into `ReactParityApp`.
  - This prevents accidental drift from a hidden side-route and clarifies the live surface.

## Remaining concern from the review

- Deploy config still advertises single-replica runtime in `render.yaml`.

## Additional follow-up corrections

- Benchmark "last run" surfaces now use a disk-backed snapshot fallback (`benchmark-history.jsonl`) and mutable in-process cache updates (no stale imported-global rebinds).
- Root app no longer uses iframe embedding as the primary delivery path and now defaults to the chat surface (`chat.html`).
- Graph View no longer redirects away from chat; it opens as an in-app overlay (`graph.html` iframe modal) and closes back to the same chat session.

## Follow-up items completed after this correction pass

- Landing defaults to chat (`/chat.html`) with Graph as an in-app overlay modal (no redirect/route swap).
- Turn token tracking no longer uses `(chars + 500) // 4`; runtime now uses model-aware estimation (tiktoken when available, deterministic byte/segment fallback otherwise).
- Demo now exposes model selection (`/api/demo/models`, `/api/demo/model`) and a chat-header model picker with credential-aware options.
- Chat now exposes live pipeline progress via async endpoints (`POST /api/chat/start`, `GET /api/chat/status/{job_id}`), and the UI surfaces retrieval/generation/linking/diagnostics stages instead of static typing dots.
