# Deploy Checklist (Render backend + Vercel frontend)

## Backend (Render)

1. Create Render Web Service from this repo (`rootDir=backend`).
2. Attach persistent disk mounted at `/var/data`.
3. Confirm env vars:
   - `CORE_MEMORY_ROOT=/var/data/core-memory`
   - `CORE_MEMORY_DEMO_BENCHMARK_ROOT=/var/data/core-memory-bench`
   - `CORE_MEMORY_DEMO_ARTIFACTS_ROOT=/var/data/core-memory-artifacts`
   - one model key (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`)
   - `ALLOWED_ORIGIN=https://<your-vercel-domain>`
4. Keep **instance count = 1**.
5. Verify:
   - `/healthz` returns 200
   - `/api/demo/state` returns 200
   - `/v1/memory/inspect/state` returns 200

## Frontend (Vercel)

1. Import repo into Vercel.
2. Set **Root Directory** = `frontend`.
3. Set env var:
   - `VITE_API_BASE_URL=https://<render-backend-domain>`
4. Deploy preview, then production.
5. Validate tabs:
   - Chat / Memory / Graph / Claims / Entities / Runtime / Benchmark

## Post-deploy smoke

1. Click **Seed** in frontend.
2. Send one chat turn.
3. Run benchmark once.
4. Flush session once.
5. Restart backend service and confirm seeded state still visible.
