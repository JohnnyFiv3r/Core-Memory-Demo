# T0/T1 Execution (MVP)

## T0 — Repo contract locked

Decisions:

1. Standalone repo (`core-memory-demo`) separate from engine repo.
2. Frontend and backend communicate over HTTP only.
3. Backend storage paths come from env vars (no monorepo-relative assumptions).
4. Deployment-specific glue belongs here, not in Core-Memory.

## T1 — Skeleton created

Structure:

```text
core-memory-demo/
  frontend/
  backend/
  shared/
  docs/
```

- Frontend scaffolded with Vite + React + TS shell and API base URL wiring.
- Backend scaffolded with FastAPI, CORS, health endpoint, runtime root checks.
- Demo API endpoints are stubbed for next-ticket implementation.

## Immediate next tickets (minimum viable)

- T2.1: Implement backend endpoint contract using Core-Memory dependency.
- T2.2: Add startup writable-volume enforcement and explicit root creation.
- T3.1: Port current tab UI behavior from monolith HTML into React components.
- T3.2: Wire chat + inspect + benchmark HTTP data flows.

## Pause needed from user

### PAUSE A (required)

Please provide:

1. New GitHub repo URL for `core-memory-demo`
2. Default branch (`main` expected)
3. Whether repo should be public or private

Once provided, I will:
- initialize git in this folder
- commit T0/T1 bootstrap
- push initial branch
