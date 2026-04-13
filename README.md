# core-memory-demo

Standalone deployable demo surface for Core Memory.

## Scope status

- ✅ T0/T1 bootstrap complete
- 🚧 T2 backend contract + volume hardening in progress

Current structure:
- `frontend/` → Vite + React + TypeScript app with tabbed demo shell and HTTP wiring
- `backend/` → FastAPI service with inspect/chat/flush/seed/benchmark/entity routes
- `shared/` → shared contract placeholders
- `docs/` → execution notes and ticket plan

This repo is intentionally separate from `Core-Memory` to protect OSS engine clarity.

## Local run

### Backend

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Note: requirements currently pin `core-memory` directly from GitHub `master` for MVP speed.
Before production cut, pin to a tag/commit SHA.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Set frontend env:

```bash
cp .env.example .env
# edit VITE_API_BASE_URL
```

## Deploy target (from PRD)

- Frontend: Vercel (root `frontend/`)
- Backend: Render (single instance) + persistent disk mounted at `/var/data`
- Storage roots:
  - `CORE_MEMORY_ROOT=/var/data/core-memory`
  - `CORE_MEMORY_DEMO_BENCHMARK_ROOT=/var/data/core-memory-bench`
  - `CORE_MEMORY_DEMO_ARTIFACTS_ROOT=/var/data/core-memory-artifacts`

## Deployment artifacts

- `render.yaml` included for backend service bootstrap
- `docs/deploy-checklist.md` contains step-by-step Render/Vercel rollout checks

## Next pause point

### PAUSE B (you)
When I call T2/T3 MVP stable, you'll need to:
1. Create Render web service for `backend/`
2. Attach persistent disk mounted at `/var/data`
3. Set env vars (roots, model key, allowed origin)
4. Keep replicas at exactly 1
