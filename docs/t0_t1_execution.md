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

## T2 — Current progress (in branch)

Implemented in-progress MVP backend contract:

- inspect routes (`/v1/memory/inspect/*`)
- demo compatibility routes (`/api/demo/*`)
- chat/flush/seed routes
- benchmark run/history/compare routes
- entity merge suggest/decide routes
- startup writable-root enforcement with separated roots

Remaining for T2 closeout:

- tighten benchmark report schema parity with prior monolith
- add backend tests for endpoint smoke + root isolation assertions
- pin Core-Memory dependency to commit SHA (currently `master`)

## Immediate next tickets (minimum viable)

- T2.3: Endpoint smoke tests + volume-path failure tests
- T2.4: Benchmark/live-root contamination guard tests
- T3.1: Port current tab UI behavior from monolith HTML into React components (starter shell now active)
- T3.2: Wire chat + inspect + benchmark HTTP data flows in React (starter wiring landed; parity polish pending)

## Pause needed from user

### PAUSE A (done)

Repo created and bootstrap pushed.

### PAUSE B (upcoming)

After T2 stabilization, user action required:

1. Create Render web service for `backend/`
2. Attach persistent disk at `/var/data`
3. Set required backend env vars
4. Keep replica count = 1
