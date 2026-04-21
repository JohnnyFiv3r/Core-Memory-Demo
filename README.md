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

Note: requirements pin `core-memory` to an explicit commit SHA for deploy stability.

Local auth behavior:
- `DEMO_AUTH_ENABLED=false` (default) keeps local evaluation simple with no Auth0 setup.
- Set `DEMO_AUTH_ENABLED=true` only when you want JWT/admin-email enforcement.

### Backend regression checks

```bash
cd backend
python -m unittest tests/test_api_smoke.py tests/test_retrieval_regressions.py
python scripts/check_retrieval_health.py --base-url http://127.0.0.1:8000
```

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
- Backend: Render + persistent disk mounted at `/var/data`
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
4. Set instance count in Render dashboard for your environment (start conservative, then tune based on workload)
