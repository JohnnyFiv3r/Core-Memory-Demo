# Qdrant + Kuzu migration plan for demo and LoCoMo benchmark

## Current state

- Core Memory default path is Qdrant for vector search and Kuzu for graph traversal.
- The live demo currently forces semantic retrieval toward shared Postgres/pgvector through `backend/app/core/semantic_env.py` when a Postgres DSN exists.
- Runtime UI currently reports `Semantic Backend: backend: pgvector · provider: openai`.
- LoCoMo benchmark paths share the same runtime/config helpers, so benchmark runs inherit the pgvector bridge unless explicitly isolated.
- The dependency pin has been moved to Core Memory commit `21dafdb9c8c357adbb7c47a465d5a5b72a4866fd` with `qdrant` and `kuzu` extras installed, while temporarily retaining `pgvector` for rollback/current compatibility.

## Goals

1. Make Qdrant + Kuzu the normal/default backend for the live demo.
2. Make LoCoMo benchmark runs use the same backend family by default, while keeping benchmark roots isolated and repeatable.
3. Preserve pgvector as an explicit fallback/legacy mode during rollout, not as the implicit path.
4. Expose enough UI/runtime diagnostics to prove which vector and graph backends are active.
5. Keep Render deployment operationally simple: embedded Qdrant + embedded Kuzu first, optional remote Qdrant later.

## Proposed target behavior

### Demo runtime

- `CORE_MEMORY_VECTOR_BACKEND` defaults to `qdrant` unless explicitly set.
- `CORE_MEMORY_GRAPH_BACKEND` defaults to `kuzu` unless explicitly set.
- Embedded paths default under the demo memory root:
  - Qdrant: `<core_memory_root>/.beads/qdrant`
  - Kuzu: `<core_memory_root>/.beads/kuzu`
- `BENCHMARK_DATABASE_URL` remains available for benchmark reports/history if needed, but no longer implies `CORE_MEMORY_VECTOR_BACKEND=pgvector`.
- Runtime panel reports both:
  - semantic/vector backend, provider, path/url, collection, row/point count, connectivity
  - graph backend, path/url, bead/node count, edge count, health

### LoCoMo benchmark

- Each benchmark run gets an isolated root and therefore isolated embedded Qdrant/Kuzu directories.
- Runs should be reproducible: root path and collection names include suite/run/session identifiers, not a global mutable path.
- Benchmark reports include backend metadata: vector backend, graph backend, vector count, graph node/edge counts, degraded/fallback flags.
- Comparison mode can run `pgvector` vs `qdrant+kuzu` only when explicitly requested.

## Implementation phases

### Phase 1 — Dependency and config foundation

1. Update `backend/requirements.txt` to install `core-memory[semantic,pgvector,qdrant,kuzu,mcp]` at the latest Core Memory pin during migration; remove `pgvector` only after the live demo and benchmark no longer need the rollback path.
2. Replace `configure_shared_semantic_backend_env()` with a more general backend selection helper:
   - if `CORE_MEMORY_VECTOR_BACKEND` is set, honor it;
   - otherwise default to `qdrant`;
   - if `CORE_MEMORY_GRAPH_BACKEND` is set, honor it;
   - otherwise default to `kuzu`;
   - only set pgvector when `CORE_MEMORY_VECTOR_BACKEND=pgvector` or `CORE_MEMORY_DEMO_BACKEND_PROFILE=pgvector` is explicit.
3. Keep `CORE_MEMORY_PG_DSN` bridging available for explicit pgvector mode only.
4. Add `.env.example` entries documenting:
   - `CORE_MEMORY_VECTOR_BACKEND=qdrant`
   - `CORE_MEMORY_GRAPH_BACKEND=kuzu`
   - `CORE_MEMORY_QDRANT_PATH`
   - `CORE_MEMORY_QDRANT_URL`
   - `CORE_MEMORY_KUZU_PATH`
   - `CORE_MEMORY_DEMO_BACKEND_PROFILE=qdrant_kuzu|pgvector`

### Phase 2 — Runtime diagnostics and UI proof

1. Extend backend runtime diagnostics to call Core Memory semantic/vector health and graph health.
2. Add graph health summary to the Runtime control panel.
3. Rename UI text from “Semantic Backend” to “Vector Backend” where appropriate, and add a separate “Graph Backend” card.
4. Add a smoke assertion path that fails if default mode is not `qdrant+kuzu`.
5. Keep degraded warnings visible when Qdrant/Kuzu fail and the runtime falls back to Python/local behavior.

### Phase 3 — Write path and migration/rebuild

1. Ensure demo bead writes call Core Memory APIs that trigger Qdrant upsert and Kuzu projection side effects.
2. Add a startup/rebuild command or admin endpoint for existing demo roots:
   - dry-run counts beads/associations;
   - build vectors into Qdrant;
   - build bead/association graph into Kuzu;
   - report failures without corrupting local bead storage.
3. Decide whether live demo reset should wipe embedded Qdrant/Kuzu directories along with JSON/session state.
4. Make `Flush Session`/reset behavior explicit: reset current session only vs reset all backend projections.

### Phase 4 — LoCoMo benchmark isolation

1. Thread backend profile into LoCoMo runners (`locomo_runner`, `locomo_replay`, lifecycle runner).
2. For each run, set:
   - `CORE_MEMORY_VECTOR_BACKEND=qdrant`
   - `CORE_MEMORY_GRAPH_BACKEND=kuzu`
   - `CORE_MEMORY_QDRANT_PATH=<run_root>/.beads/qdrant`
   - `CORE_MEMORY_KUZU_PATH=<run_root>/.beads/kuzu`
3. Add benchmark result metadata fields:
   - `vector_backend`
   - `graph_backend`
   - `vector_health`
   - `graph_health`
   - `projection_rebuild_counts`
   - `fallback_or_degraded_warnings`
4. Add benchmark tests that assert isolated directories are created and populated.
5. Add comparison fixtures for explicit legacy pgvector mode, but keep it non-default.

### Phase 5 — Tests and gates

Minimum tests before deploy:

- unit: backend selection helper defaults to `qdrant+kuzu` with no env overrides;
- unit: explicit `pgvector` profile still bridges `BENCHMARK_DATABASE_URL` to `CORE_MEMORY_PG_DSN`;
- unit: explicit env vars are never overwritten;
- unit/integration: writing a bead creates or updates Qdrant and Kuzu artifacts under an isolated temp root;
- LoCoMo: fixture smoke suite runs with `qdrant+kuzu` and reports backend metadata;
- browser smoke: Runtime panel shows Qdrant + Kuzu, chat answer remains grounded, no console errors.

### Phase 6 — Deployment rollout

1. Deploy with embedded Qdrant/Kuzu and no `CORE_MEMORY_VECTOR_BACKEND` override.
2. Verify Render disk persistence for the embedded directories; if persistence is not guaranteed, move to either:
   - mounted persistent disk paths; or
   - remote Qdrant URL while keeping embedded Kuzu on persistent disk.
3. Run rebuild/migration for any retained demo beads.
4. Smoke test:
   - login
   - Runtime panel shows Qdrant + Kuzu
   - queue idle
   - grounded answer returns bead evidence
   - LoCoMo fixture smoke completes
5. Keep pgvector env/profile documented as rollback.

## Rollback

- Set `CORE_MEMORY_DEMO_BACKEND_PROFILE=pgvector` or `CORE_MEMORY_VECTOR_BACKEND=pgvector` with the existing Postgres DSN.
- Set `CORE_MEMORY_GRAPH_BACKEND=none` if Kuzu causes startup/runtime issues.
- Revert the requirement line to the previous Core Memory pin only if API compatibility breaks; otherwise prefer keeping the newer pin and selecting legacy backends through env.

## Open decisions

1. Should the live demo use embedded Qdrant on Render disk, or remote Qdrant from day one?
2. Should demo “hard reset” wipe Qdrant/Kuzu projections too, or only sessions/current bead state?
3. Should LoCoMo published numbers compare against legacy pgvector for one transition window?
4. Do we want Graph View to read directly from Kuzu, or keep reading the existing association projection until the UI shape is updated?
