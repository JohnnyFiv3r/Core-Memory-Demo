# core-memory-demo

Standalone deployable demo surface for Core Memory.

## Scope (T0/T1 bootstrap)

- `frontend/` → Vite + React + TypeScript shell
- `backend/` → FastAPI service shell
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
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
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
- Backend: Render (single instance) + persistent disk mounted at `/var/data`
- Storage roots:
  - `CORE_MEMORY_ROOT=/var/data/core-memory`
  - `CORE_MEMORY_DEMO_BENCHMARK_ROOT=/var/data/core-memory-bench`
  - `CORE_MEMORY_DEMO_ARTIFACTS_ROOT=/var/data/core-memory-artifacts`
