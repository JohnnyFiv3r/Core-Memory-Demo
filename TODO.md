# TODO: Adoption-Ready Ergonomics (mnemory learnings)

Mnemory (https://github.com/fpytloun/mnemory) is an MCP-server-first persistent memory layer
for AI agents. It stops short of Core Memory's thesis on temporal replay, structured graph
traversal, and claim/evidence chains — but it clears a bar on developer ergonomics that
Core Memory hasn't hit yet. These tasks close that gap.

---

## 1. Quickstart in one command

**Why:** mnemory ships `uvx mnemory` — zero build steps, zero database setup, one env var
(`OPENAI_API_KEY`), running on `localhost:8050/mcp` in under 30 seconds. Our local run
currently requires activating a venv, copying `.env.example`, and wiring two separate
servers (backend + frontend). New evaluators give up before they see the demo.

**Tasks:**
- [ ] Add a top-level `Makefile` target (or shell script) that handles: venv creation,
      dep install, `.env` copy from example, and launching both backend + frontend
- [ ] Confirm `DEMO_AUTH_ENABLED=false` default is enforced so no Auth0 config is needed
- [ ] Document the one-command path at the top of `README.md` before anything else

---

## 2. Expose an MCP server endpoint

**Why:** mnemory's entire adoption surface is the MCP protocol — Claude Code, Cursor,
Windsurf, Open WebUI all integrate via a single URL in their config. Core Memory has
no published MCP surface, which means integrators can't wire it into their own toolchains
without writing custom glue code.

**Tasks:**
- [ ] Add an `/mcp` route (streamable-HTTP MCP server) to `backend/app/main.py`
- [ ] Expose at minimum: `initialize_memory`, `search_memories`, `add_memory`, `recall`
      equivalents as MCP tools
- [ ] Document the Claude Code snippet in `README.md`:
      ```json
      { "mcpServers": { "core-memory": { "type": "streamable-http",
        "url": "http://localhost:8000/mcp" } } }
      ```
- [ ] (Stretch) Add `X-Agent-Id` header support for multi-agent scoping

---

## 3. Two-verb public API: `remember` + `recall`

**Why:** mnemory's entire integration story is two HTTP calls. `POST /api/remember` ingests
a conversation (fire-and-forget, async extraction). `POST /api/recall` returns context +
core memories ready to prepend to a system prompt. Everything else is power-user surface.
Core Memory's routes are fine internally but there is no clear primary entry point for
someone writing an integration from scratch.

**Tasks:**
- [ ] Add `POST /remember` — accepts raw `messages[]`, triggers async extraction +
      storage, returns `202 Accepted`
- [ ] Add `POST /recall` — accepts optional `query` string, returns:
      `{ instructions, core_memories, relevant_memories }` ready to inject into a prompt
- [ ] Make these the canonical "getting started" examples in `README.md`
- [ ] Existing granular routes (`/seed`, `/flush`, `/inspect`, etc.) stay as power-user surface

---

## 4. Inference-first ingestion (no client-side metadata required)

**Why:** mnemory's `infer=true` (default) means developers pass raw facts and the server
handles classification, importance scoring, and deduplication. Our current API requires
callers to know the schema. That's a per-integration tax that kills adoption.

**Tasks:**
- [ ] Make all write endpoints accept a bare `content: str` with all metadata optional
- [ ] Server-side: LLM call to extract `category`, `importance`, `type`, entity links
      when metadata is absent
- [ ] Add `infer=true` flag (default true) to `/remember` and `/add_memory` so callers
      can opt out if they're providing structured data themselves
- [ ] Contradiction detection: when adding a fact that conflicts with an existing one,
      update in-place rather than appending a duplicate (e.g., "using Qdrant" after
      "using pgvector" should merge, not duplicate)

---

## 5. Fire-and-forget async writes

**Why:** mnemory's `POST /api/remember` returns immediately; extraction and embedding
happen in the background. Blocking integrations on write latency (LLM call + embed +
store) is a deal-breaker for real-time chat applications.

**Tasks:**
- [ ] `/remember` returns `202 Accepted` with a `job_id`, does not block on LLM extraction
- [ ] Background task queue (start with FastAPI `BackgroundTasks`, upgrade to Celery/ARQ
      if needed) handles extraction, dedup, embedding, storage
- [ ] `/jobs/{job_id}` status endpoint so callers can poll if they care
- [ ] Write path failures should not surface to the integration caller — log internally

---

## 6. Hybrid search by default (vectors + BM25)

**Why:** mnemory scores 73-78% on LoCoMo benchmarks using Reciprocal Rank Fusion of
dense vector search + BM25 keyword search. Pure vector search misses exact-match queries
("Project MetricsHub", "WorkOS"). Pure BM25 misses semantic fuzzy queries. Both are
needed and the caller shouldn't have to choose.

**Tasks:**
- [ ] Implement BM25 index alongside the existing vector store (can start with `rank-bm25`
      Python lib over in-memory corpus, then swap for Tantivy/Elasticsearch)
- [ ] Fuse results via Reciprocal Rank Fusion before returning from `/search`
- [ ] Importance score as secondary tiebreaker only (not primary ranking signal)
- [ ] Expose `mode=hybrid|semantic|keyword` param on `/search` for explicit override
- [ ] Verify against existing `test_retrieval_regressions.py` — hybrid should not regress
      any currently-passing cases

---

## 7. Built-in management UI (zero external deps)

**Why:** mnemory bundles a management dashboard at `/ui` — memory browser, semantic
search, graph visualization, fsck consistency scanner, session browser. It uses only
vendored JS (Alpine.js, Tailwind, D3.js, Chart.js). Evaluators can inspect the memory
state without running separate tools. Our frontend demo is sophisticated but requires
a separate Vite dev server to run.

**Tasks:**
- [ ] Serve a static `/ui` from the FastAPI backend (no Vite required for basic inspection)
- [ ] Include: memory list with inline search, entity browser, flush/seed triggers
- [ ] Wire the existing graph visualization (`graph.html`) so it loads from `/ui/graph`
      served off the backend
- [ ] fsck equivalent: `/ui/health` view showing duplicate count, orphaned entities,
      contradiction candidates
- [ ] This is for evaluator/developer inspection — the full React demo (`frontend/`) stays
      as the showpiece experience

---

## 8. Observability out of the box

**Why:** mnemory ships Prometheus metrics at `/metrics` and Kubernetes health probes at
`/health` on a separate management port. No Grafana config needed — dashboard templates
are provided. Operators should not need to instrument the service themselves.

**Tasks:**
- [ ] `/health` already exists (`backend/app/routes/health.py`) — verify it returns
      liveness + readiness separately (Kubernetes convention)
- [ ] Add `prometheus-client` to `requirements.txt`, expose `/metrics` with:
      - Write op counters (remember, add, flush)
      - Search op counters + p50/p99 latency histograms
      - Memory count gauge (total, by type)
      - Extraction job queue depth
- [ ] Separate `MGMT_PORT` env var so health + metrics run on a different port in
      production (avoids exposing ops endpoints through the public-facing port)
- [ ] Add a Grafana dashboard JSON template to `docs/grafana-dashboard.json`

---

## 9. Environment-only configuration

**Why:** mnemory has no config files — everything is an environment variable, all with
sensible defaults. Our project uses `.env.example` (good) but some defaults require
manual discovery. Evaluators should get a working system with zero env editing.

**Tasks:**
- [ ] Audit all config in `backend/app/core/config.py` — identify any setting without
      a safe default
- [ ] Every setting that can default to a local/dev-safe value should do so
- [ ] `.env.example` should contain only overrides, not required vars — if a var is
      required with no safe default, it must be called out prominently with a reason
- [ ] Document the full env var reference table in `README.md` (name, default, purpose)

---

## 10. Batch ingestion endpoint

**Why:** mnemory's `add_memories` (plural) accepts a list of facts in one call, avoiding
N round-trips for bulk ingestion. Our story-pack replay ingests 204 turns — batching
would cut ingestion time significantly and is necessary for any integration that pre-loads
a knowledge base.

**Tasks:**
- [ ] Add `POST /memories/batch` accepting `[{content, metadata?}]`
- [ ] Respect the same `infer=true` flag as the single-add endpoint
- [ ] Process in parallel (asyncio gather) up to a configurable `batch_concurrency` limit
- [ ] Return `{ accepted: N, failed: [{ index, reason }] }` — partial failure is OK

---

## Priority order for the week

| # | Task | Effort | Adoption Impact |
|---|------|--------|-----------------|
| 1 | Two-verb API (`/remember` + `/recall`) | S | Very High |
| 2 | Quickstart one-command | XS | Very High |
| 3 | Inference-first ingestion | M | High |
| 4 | Fire-and-forget async writes | S | High |
| 5 | MCP server endpoint | M | High |
| 6 | Hybrid search (BM25 + vectors) | L | High |
| 7 | Environment-only config audit | XS | Medium |
| 8 | Batch ingestion | S | Medium |
| 9 | Observability (`/metrics`, mgmt port) | S | Medium |
| 10 | Built-in management UI | L | Medium |

**Week plan:** Ship #1–#5 first. They are the things mnemory does that any serious
integration will hit immediately. #6 (hybrid search) is the retrieval quality lever
that makes Core Memory's benchmark story stronger than mnemory's — worth the effort
in week 1 if time allows. #7–#10 are polish; don't let them block the above.
