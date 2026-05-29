# PRD: Core Memory Demo — Migrate to Default Qdrant + Kuzu Path

**Trigger:** Core Memory PR #164 / master `46a00645`
**Branch:** `claude/core-memory-demo-plan-UyVD4`
**Status:** Planning

---

## Background & Motivation

Core Memory master (`46a00645`) ships the architectural work from PR #164: the library's
default storage path is now **Qdrant (embedded) + Kuzu (in-process)**. FAISS is explicitly
deprecated with a warning, and pgvector is now a niche extra rather than the expected
production path.

The demo currently hardwires the old path:

- `requirements.txt` installs `[semantic,pgvector,mcp]` (numpy+faiss-cpu + psycopg)
- `semantic_env.py` bridges `BENCHMARK_DATABASE_URL → CORE_MEMORY_PG_DSN` and forces
  `CORE_MEMORY_VECTOR_BACKEND=pgvector` + `CORE_MEMORY_EMBEDDINGS_PROVIDER=openai`
- `render.yaml` declares those same vars on both the web service and the cron job
- The graph backend was never configured, so it silently used `NullGraphBackend` — no
  native graph traversal

The new path removes both external service dependencies for semantic search (Postgres,
OpenAI embeddings key) and enables full `BackendCapabilities`:
`vector_search=True` (Qdrant hybrid: sparse+dense) and `graph_traversal=True`
(native Kuzu queries instead of Python-side fallback).

---

## What PR #164 Introduced

### `BackendCapabilities` dataclass (`core_memory/persistence/backend.py`)

```python
@dataclass
class BackendCapabilities:
    vector_search: bool = False     # True only when CORE_MEMORY_VECTOR_BACKEND=qdrant
    graph_traversal: bool = False   # True when CORE_MEMORY_GRAPH_BACKEND=kuzu|neo4j
    full_text_search: bool = False  # True when CORE_MEMORY_VECTOR_BACKEND=qdrant
    transcript_hydration: bool = False
```

Constructed by `get_backend_capabilities(beads_dir)` which reads env vars with new
defaults:

- `CORE_MEMORY_VECTOR_BACKEND` → default `"qdrant"` (was `"local-faiss"`)
- `CORE_MEMORY_GRAPH_BACKEND` → default `"kuzu"` (was unset → NullGraphBackend)

### Retrieval pipeline routing (`retrieval/pipeline/canonical.py`)

```python
_caps = get_backend_capabilities(rp / ".beads")
if _caps.vector_search:
    sem = hybrid_lookup(rp, query, k=sem_k)           # Qdrant: sparse+dense in one shot
else:
    sem = semantic_lookup(rp, query, k=sem_k, mode=…) # FAISS/pgvector fallback
if _caps.graph_traversal:
    _graph = create_graph_backend(Path(root))          # Kuzu native traversal
else:
    trav = causal_traverse(Path(root), …)              # Python-side fallback
```

### New env vars introduced by PR #164

| Variable | Default | Purpose |
|---|---|---|
| `CORE_MEMORY_VECTOR_BACKEND` | `qdrant` | Vector backend selector |
| `CORE_MEMORY_GRAPH_BACKEND` | `kuzu` | Graph backend selector |
| `CORE_MEMORY_QDRANT_URL` | _(unset = local)_ | Remote Qdrant URL |
| `CORE_MEMORY_QDRANT_PATH` | `.beads/qdrant` | Local Qdrant storage path |
| `CORE_MEMORY_KUZU_PATH` | `.beads/kuzu` | Local Kuzu storage path |
| `CORE_MEMORY_SEMANTIC_AUTODRAIN` | `on` | Daemon thread per dirty root |

### FastEmbed

Bundled with `qdrant-client[fastembed]`. Downloads `BAAI/bge-small-en-v1.5` (~50 MB)
on first use to `~/.cache/fastembed/`. No `OPENAI_API_KEY` needed for embeddings.
`CORE_MEMORY_EMBEDDINGS_PROVIDER` is irrelevant for the Qdrant path — FastEmbed operates
inside the Qdrant client and bypasses that env var entirely.

### `CORE_MEMORY_SEMANTIC_AUTODRAIN`

Starts a daemon thread (`_autodrain_worker`) when `mark_semantic_dirty()` is called.
The demo already manages semantic sync via (a) `_sync_semantic_on_write()` after each
chat turn and (b) `_async_jobs_tick_loop()` every 60 s. The autodrain daemon adds a
third mechanism — redundant and potentially racing with the demo's explicit sync.
**Must be disabled** (`off`) in the demo via the env bridge.

---

## Goals

1. Pin `requirements.txt` to `core-memory[qdrant,kuzu,mcp] @ ...@46a00645`
2. Replace `semantic_env.py`'s pgvector bridge with an Qdrant + Kuzu bridge
3. Change demo chat semantic mode default from `degraded_allowed` → `required`
   (FastEmbed makes semantic always available; `required` gives observability when
   things actually break)
4. Update `render.yaml` env vars on both services; add FastEmbed cache path to
   persistent disk on the cron job
5. Update `backend/.env.example` comments
6. Rewrite `test_semantic_env.py` for the new env bridge contract

## Non-Goals

- Remote Qdrant (keep embedded)
- Making the web service memory root persistent (stays `/tmp/` — intentional; the
  chat demo is stateless)
- Changing the benchmark job queue (still Postgres / `BENCHMARK_DATABASE_URL`)
- Frontend changes
- Changing `_resolve_benchmark_embeddings_provider` (returns `hash` as default, which
  is a no-op when Qdrant provides embeddings via FastEmbed internally)

---

## Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| FastEmbed model cache ephemeral on web service (`/tmp`) | Medium | Web service restart re-downloads ~50 MB — acceptable. Cron job pins `FASTEMBED_CACHE_PATH=/var/data/fastembed-cache` to avoid re-download every minute. |
| `CORE_MEMORY_SEMANTIC_AUTODRAIN=on` (library default) races with demo's explicit sync | High | Bridge unconditionally sets `off`; demo manages sync explicitly. |
| Qdrant collection name sanitization for benchmark roots | Low | Core Memory library sanitizes path → collection name internally; no demo code touches collection names. |
| `test_retrieval_regressions.py::test_pgvector_search_parameter_order` imports `PgvectorBackend` | Low | PR #164 adds 50+ backward-compat shims; class still exists. Test has `skipTest` guard as double safety. |
| Disk exhaustion from Qdrant collections per benchmark run | Low | 20 GB disk; locomo10 vectors ≈ 1 MB per run; `benchmark_runs_max_keep=80` → ceiling ≈ 80 MB vector data. |
| `required` mode breaks chat if Qdrant not yet initialized | Low | Empty Qdrant collection is valid; `semantic_lookup` returns empty results, not an error. First write initializes the collection. |

---

## Execution Plan

### Step 1 — `backend/requirements.txt`

**Change:** Swap extras and bump SHA.

```diff
-core-memory[semantic,pgvector,mcp] @ git+https://github.com/JohnnyFiv3r/Core-Memory.git@8fb3332a9a2d2e0a320b33bc269df9a9814a1d87
+core-memory[qdrant,kuzu,mcp] @ git+https://github.com/JohnnyFiv3r/Core-Memory.git@46a00645fbe5e41cae46315b742d093c87815bb1
```

`semantic` (numpy + faiss-cpu) and `pgvector` (psycopg[binary]) are replaced by
`qdrant` (qdrant-client[fastembed]≥1.9) and `kuzu` (kuzu≥0.4).

**Risk:** LOW.

---

### Step 2 — `backend/app/core/semantic_env.py`

**Change:** Full replacement of `configure_shared_semantic_backend_env()`.

Old function: bridges `BENCHMARK_DATABASE_URL → CORE_MEMORY_PG_DSN`, forces pgvector,
forces `CORE_MEMORY_EMBEDDINGS_PROVIDER=openai`.

New function contract:
- Sets `CORE_MEMORY_VECTOR_BACKEND=qdrant` if unset
- Sets `CORE_MEMORY_GRAPH_BACKEND=kuzu` if unset
- Sets `CORE_MEMORY_CANONICAL_SEMANTIC_MODE=required` if unset AND vector backend is
  `qdrant` (FastEmbed = always available)
- Sets `CORE_MEMORY_SEMANTIC_AUTODRAIN=off` if unset
- Explicit env overrides always win — bridge never overwrites an already-set var
- `BENCHMARK_DATABASE_URL` is no longer touched here (job queue reads it directly)
- Return shape `{"changed": {...}, "before": {...}, "after": {...}}` is preserved

**Risk:** MEDIUM — called at startup; any exception breaks startup.

---

### Step 3 — `backend/app/core/runtime.py`

**Change:** One line in the `os.environ.setdefault` block (~line 147).

```diff
-os.environ.setdefault("CORE_MEMORY_DEMO_CHAT_SEMANTIC_MODE", "degraded_allowed")
+os.environ.setdefault("CORE_MEMORY_DEMO_CHAT_SEMANTIC_MODE", "required")
```

`degraded_allowed` was a safety valve for the unreliable pgvector path. FastEmbed makes
semantic unavailability impossible in normal operation; `required` surfaces real failures
instead of silently falling back to lexical retrieval.

**Risk:** LOW.

---

### Step 4 — `render.yaml`

**Web service (`core-memory-demo-backend`) — remove:**
```yaml
- key: CORE_MEMORY_VECTOR_BACKEND
  value: pgvector
- key: CORE_MEMORY_CANONICAL_SEMANTIC_MODE
  value: required
- key: CORE_MEMORY_EMBEDDINGS_PROVIDER
  value: openai
```

**Web service — add:**
```yaml
- key: CORE_MEMORY_VECTOR_BACKEND
  value: qdrant
- key: CORE_MEMORY_GRAPH_BACKEND
  value: kuzu
```

No FastEmbed cache path on the web service — root is `/tmp/`, the ~50 MB model
re-download on restart is acceptable for an ephemeral stateless service.

**Cron job (`core-memory-demo-benchmark-worker`) — remove:**
```yaml
- key: CORE_MEMORY_VECTOR_BACKEND
  value: pgvector
- key: CORE_MEMORY_CANONICAL_SEMANTIC_MODE
  value: required
- key: CORE_MEMORY_EMBEDDINGS_PROVIDER
  value: openai
```

**Cron job — add:**
```yaml
- key: CORE_MEMORY_VECTOR_BACKEND
  value: qdrant
- key: CORE_MEMORY_GRAPH_BACKEND
  value: kuzu
- key: FASTEMBED_CACHE_PATH
  value: /var/data/fastembed-cache
```

The cron job wakes fresh every minute; without a persistent cache path it would
re-download the FastEmbed model on every invocation.

**Keep on both services:**
- `BENCHMARK_DATABASE_URL: sync: false` — job queue Postgres untouched
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` — still needed for chat LLM

**Disk:** `core-memory-demo-data` stays at 20 GB. Qdrant collections for benchmark
runs live at `/var/data/core-memory-bench/<run_id>/.beads/qdrant/`, Kuzu graphs at
`/var/data/core-memory-bench/<run_id>/.beads/kuzu/`. Both are within the existing
mount; no disk resize needed.

**Risk:** MEDIUM — infrastructure change; wrong config = broken Render deploy.

---

### Step 5 — `backend/.env.example`

**Remove:** `CORE_MEMORY_EMBEDDINGS_PROVIDER=hash` comment block (FastEmbed is
automatic with Qdrant; the provider env var is ignored on this path).

**Add:**
```
# Vector + graph backend (defaults: qdrant + kuzu — no external services needed)
# CORE_MEMORY_VECTOR_BACKEND=qdrant
# CORE_MEMORY_GRAPH_BACKEND=kuzu

# Optional: override local storage paths
# CORE_MEMORY_QDRANT_PATH=./var/qdrant
# CORE_MEMORY_KUZU_PATH=./var/kuzu
```

**Risk:** LOW — documentation only.

---

### Step 6 — `backend/tests/test_semantic_env.py`

Full rewrite. The three existing tests (`test_bridges_benchmark_database_to_core_memory_pgvector`,
`test_explicit_semantic_dsn_and_backend_are_preserved`, `test_no_database_url_leaves_backend_unset`)
are all pgvector-contract tests and become obsolete.

**New test cases:**

1. `test_sets_qdrant_and_kuzu_defaults_when_unset`
   - Env: empty
   - Assert: `CORE_MEMORY_VECTOR_BACKEND=qdrant`, `CORE_MEMORY_GRAPH_BACKEND=kuzu`,
     `CORE_MEMORY_CANONICAL_SEMANTIC_MODE=required`,
     `CORE_MEMORY_SEMANTIC_AUTODRAIN=off`
   - Assert: all four keys appear in `out["changed"]`

2. `test_explicit_backend_is_preserved`
   - Env: `CORE_MEMORY_VECTOR_BACKEND=pgvector`, `CORE_MEMORY_GRAPH_BACKEND=neo4j`,
     `CORE_MEMORY_CANONICAL_SEMANTIC_MODE=degraded_allowed`,
     `CORE_MEMORY_SEMANTIC_AUTODRAIN=on`
   - Assert: none of the four vars are changed
   - Assert: `out["changed"] == {}`

3. `test_benchmark_database_url_not_bridged_to_pg_dsn`
   - Env: `BENCHMARK_DATABASE_URL=postgresql://demo/db`
   - Assert: `CORE_MEMORY_PG_DSN` is **not set** (bridge no longer touches it)
   - Assert: `CORE_MEMORY_VECTOR_BACKEND=qdrant` (normal defaults still apply)

**Risk:** LOW — test-only.

---

### Step 7 — Verify tests pass

```bash
cd backend && python -m pytest tests/ -x -q
```

Expected outcomes:
- `test_semantic_env.py` — all 3 new tests pass
- `test_retrieval_regressions.py::test_pgvector_search_parameter_order` — passes
  (PR #164 backward-compat shim keeps `PgvectorBackend` importable) or self-skips
- `test_locomo_runtime_semantic_mode.py` — passes unchanged (tests `semantic_mode()`
  context manager and `_resolve_benchmark_embeddings_provider`, neither of which change)
- All other tests — unchanged

---

## What Does NOT Change

| Component | Reason |
|---|---|
| `backend/app/main.py` | Still calls `configure_shared_semantic_backend_env()` — signature unchanged |
| `backend/app/routes/` | No direct semantic or graph backend references |
| `backend/app/benchmarks/` | `build_semantic_index()` / `semantic_lookup()` route to Qdrant transparently via Core Memory library |
| `_resolve_benchmark_embeddings_provider()` | Returns `hash` as default; `CORE_MEMORY_EMBEDDINGS_PROVIDER` is a no-op with Qdrant (FastEmbed is internal to qdrant-client) |
| `semantic_mode()` context manager | Sets `CORE_MEMORY_EMBEDDINGS_PROVIDER` — harmless no-op with Qdrant |
| `benchmark_store.py` | Reads `BENCHMARK_DATABASE_URL` directly; job queue Postgres path untouched |
| Frontend | Zero impact |
| Disk size | 20 GB sufficient |

---

## Execution Order

Steps 1–6 have no inter-dependencies and can be written in a single pass.
Step 7 is the verification gate before commit.

```
Step 1: requirements.txt     (no deps)
Step 2: semantic_env.py      (no deps)
Step 3: runtime.py           (no deps)
Step 4: render.yaml          (no deps)
Step 5: .env.example         (no deps)
Step 6: test_semantic_env.py (depends on Step 2 — tests the new contract)
Step 7: pytest               (verification gate)
```

---

## Post-Deploy Validation Checklist

- [ ] `GET /healthz` → `ok: true`
- [ ] `GET /api/demo/state` → non-error state, zero beads (fresh start expected)
- [ ] `POST /api/demo/chat` → response with `tier_path` including `semantic` tier
  (confirms Qdrant hybrid search active)
- [ ] `diagnostics.retrieval_mode` does **not** contain `lexical_only`
- [ ] `diagnostics.semantic_sync_ran: true` on first turn (Qdrant index built on write)
- [ ] Benchmark preflight route healthy (Postgres job queue still accessible)
- [ ] Cron job logs: no "faiss deprecated" warnings, no pgvector import errors
- [ ] Cron job logs: Qdrant collection initialized on first benchmark run
- [ ] `FASTEMBED_CACHE_PATH` directory exists on `/var/data` after first cron run
