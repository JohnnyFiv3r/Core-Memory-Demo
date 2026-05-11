# TODO: Adoption-Ready Ergonomics (mnemory learnings)

Mnemory (https://github.com/fpytloun/mnemory) is an MCP-server-first persistent memory layer.
After reading both codebases, Core Memory already has hybrid search, MCP-typed operations,
a full HTTP server (`/v1/mcp/*`, `/v1/memory/*`, `/healthz`, `/v1/metrics`), multi-tenant
header routing, and integrations for LangChain/PydanticAI/CrewAI/SpringAI/Neo4j.

These are the genuine remaining gaps — things mnemory does that Core Memory hasn't nailed yet.

---

## 1. MCP protocol server endpoint (`/mcp`)

**What mnemory does:** Runs as a proper MCP streamable-HTTP server at `/mcp`. Any client
(Claude Code, Cursor, Windsurf, Open WebUI) wires it up with one JSON snippet and talks
the MCP protocol natively. No custom glue code.

**What Core Memory has:** `/v1/mcp/*` REST endpoints that wrap MCP-typed operations —
but these are plain REST, not MCP protocol. Clients can't point at them with a standard
MCP config block.

**Gap:** Core Memory has the logic; it just hasn't been surfaced as a proper MCP transport.

**Tasks:**
- [ ] Add an MCP streamable-HTTP server endpoint at `/mcp` (mount alongside the existing
      FastAPI app in `core_memory/integrations/http/server.py`)
- [ ] Expose the existing typed-read tools (`query_current_state`, `query_temporal_window`,
      `query_causal_chain`, `query_contradictions`) as MCP tools through the protocol server
- [ ] Expose the existing typed-write tools (`write_turn_finalized`,
      `apply_reviewed_proposal`, `submit_entity_merge_proposal`) as MCP tools
- [ ] Document the Claude Code config snippet in README.md:
      ```json
      { "mcpServers": { "core-memory": { "type": "streamable-http",
        "url": "http://localhost:8000/mcp" } } }
      ```

---

## 2. Friendlier entry-point aliases for the two canonical verbs

**What mnemory does:** Two verbs cover 80% of integrations: `remember(messages)` to write,
`recall(query)` to read. New users have one mental model.

**What Core Memory has:** `process_turn_finalized(...)` (write) and `memory_execute(...)`
(read) — correct and powerful, but `process_turn_finalized` is a mouthful and signals
"internal machinery" rather than "start here."

**Gap:** The canonical verbs are not approachable for first-touch integration.

**Tasks:**
- [ ] Add `remember(...)` as a public alias for `process_turn_finalized(...)` in
      `core_memory/__init__.py` — same signature, same behavior, zero new logic
- [ ] Add `recall(...)` as a public alias for `memory_execute(...)` with `intent="remember"`
      as the default — matches the most common read pattern
- [ ] Export both from the top-level `core_memory` package
- [ ] Add a "fastest path" README example using `remember` / `recall` above the existing
      `process_turn_finalized` / `memory_execute` examples (keep both; aliases are additive)

---

## 3. Async transcript ingestion pipeline

**What mnemory does:** `POST /api/remember` returns `202 Accepted` immediately; ingestion
happens in the background. Integrations never block on write latency.

**What Core Memory has:** The benchmark harness in `Core-Memory-Demo` is already most of
the way there. The infrastructure exists and is production-quality — it just needs to be
generalized from LoCoMo-specific to generic transcript input.

**Reuse directly (no changes needed):**
- `benchmark_store.py` — Postgres job queue with `enqueue_job` → `claim_next_job`
  (`FOR UPDATE SKIP LOCKED`) → `finish_job`. Already the right pattern for async ingestion.
- `benchmark_worker.py` — claim-one-job-and-run dispatch loop. Keep as-is.
- `replay_locomo_sample()` in `transcript_only` mode — the turn iteration, `emit_turn_finalized()`
  + `process_memory_event()` per turn, `per_session`/`end_only` flush policy, and
  `_synthesize_locomo_associations()` for temporal order and entity-overlap edges. All of
  this is generic enough to keep.

**What needs to change:**
- [ ] Write a **thin input normalizer** that maps a generic transcript schema
      (`[{role, content, timestamp?}]`) to the same `_turn_envelope()` dict that the
      LoCoMo replay already produces. The envelope fields (`session_id`, `turn_id`,
      `user_query`, `assistant_final`, `metadata`) don't change — only the source schema does.
- [ ] **Pair user+assistant turns** before the per-turn loop. The harness treats each
      utterance as a separate bead; real transcript ingestion should group consecutive
      `user`/`assistant` pairs so `user_query` and `assistant_final` are populated correctly.
- [ ] **Replace `_extract_locomo_claims()`** with a generic pass — either a simple
      NER/pattern step or just omit it initially. The harness works fine without claims;
      they're an enrichment layer, not structural.
- [ ] **Generalize the job `kwargs` schema** from LoCoMo params (`sample_id`, `sessions`)
      to `{transcript_id, turns: [...], session_id, flush_policy}`.
- [ ] **Add `POST /ingest/transcript`** to the demo backend that enqueues a job and
      returns `{job_id}` — callers poll `benchmark_store.read_job(job_id)` for status.

**Do not use** `ingest_locomo_turns()` / `MemoryStore.add_bead()` directly — that path
bypasses the canonical runtime. Stay on `emit_turn_finalized()` + `process_memory_event()`.

---

## Priority order for the week

| # | Task | Effort | Adoption Impact |
|---|------|--------|-----------------|
| 1 | MCP protocol server at `/mcp` | M | Very High |
| 2 | `remember` / `recall` aliases | XS | High |
| 3 | Async transcript ingestion pipeline | S | High |

**Week plan:** #2 is hours — ship it first. #1 unlocks Claude Code / Cursor integrations
and is the biggest adoption surface. #3 is mostly assembly work given the benchmark
harness already provides the job queue, worker, turn loop, flush policy, and association
synthesis; the real work is the normalizer and the pairing step.
