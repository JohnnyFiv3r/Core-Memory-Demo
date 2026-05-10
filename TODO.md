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

## 2. One-command service startup (`core-memory serve`)

**What mnemory does:** `uvx mnemory` — zero build steps, running in under 30 seconds.

**What Core Memory has:** `pip install "core-memory[http]"` then
`python3 -m core_memory.integrations.http.server` (or a uvicorn invocation). Two steps,
and the module path is not memorable.

**Gap:** No single discoverable command to start the HTTP companion service.

**Tasks:**
- [ ] Add `core-memory serve` as a CLI subcommand in `core_memory/cli.py` that starts
      the HTTP server (equivalent to the uvicorn invocation, with `--host`/`--port` flags)
- [ ] Make `core-memory serve` the canonical "getting started with service mode" path
      in README.md and update the Service Mode section accordingly
- [ ] Verify `uvx core-memory serve` works (requires the `scripts` entrypoint is already
      in `pyproject.toml` — check that `core-memory` CLI is registered there)

---

## 3. Fire-and-forget async write path as the default HTTP pattern

**What mnemory does:** `POST /api/remember` returns `202 Accepted` immediately; extraction
and embedding happen in the background. Integrations never block on write latency.

**What Core Memory has:** `POST /v1/memory/turn-finalized` processes synchronously and
returns the full result inline. An async jobs system exists (`/v1/ops/async-jobs/`) but
it's not the default write pattern — it's an ops surface.

**Gap:** The primary HTTP write path is synchronous. This blocks real-time chat integrations
on the full write pipeline latency (extraction + embedding + store).

**Tasks:**
- [ ] Add `async: true` flag to `POST /v1/memory/turn-finalized` — when set, enqueue
      the turn via the existing async jobs system and return `202 Accepted` with a `job_id`
- [ ] Make `async: true` the documented default for HTTP integrations (the sync path stays
      for callers that need confirmation)
- [ ] Update `GET /v1/ops/async-jobs/status` docs to clarify it's also the job status
      endpoint for async write confirmation

---

## 4. Friendlier entry-point aliases for the two canonical verbs

**What mnemory does:** Two verbs cover 80% of integrations: `remember(messages)` to write,
`recall(query)` to read. New users have one mental model.

**What Core Memory has:** `process_turn_finalized(...)` (write) and `memory_execute(...)`
(read) — correct and powerful, but `process_turn_finalized` is a mouthful and signals
"internal machinery" rather than "start here."

**Gap:** The canonical verbs are not approachable for first-touch integration. The README
quickstart already shows them, but there's no alias that matches the mental model a new
integrator arrives with.

**Tasks:**
- [ ] Add `remember(...)` as a public alias for `process_turn_finalized(...)` in
      `core_memory/__init__.py` — same signature, same behavior, zero new logic
- [ ] Add `recall(...)` as a public alias for `memory_execute(...)` with `intent="remember"`
      as the default — matches the most common read pattern
- [ ] Export both from the top-level `core_memory` package
- [ ] Add a "fastest path" README example using `remember` / `recall` above the existing
      `process_turn_finalized` / `memory_execute` examples (keep both; aliases are additive)

---

## 5. Built-in management UI served from the HTTP server

**What mnemory does:** A zero-dependency dashboard at `/ui` — memory browser, semantic
search, graph visualization, fsck scanner. Served as static files from the server itself.
Evaluators inspect state without running separate tools.

**What Core Memory has:** A sophisticated React/Vite demo app in a separate repo
(`Core-Memory-Demo`) that requires its own frontend dev server. No inspection surface
baked into the HTTP server itself.

**Gap:** When someone runs `core-memory serve`, there's nothing to open in a browser
to verify the memory state. The demo is a showpiece, not an inspection tool.

**Tasks:**
- [ ] Add a static `/ui` route to `core_memory/integrations/http/server.py` serving
      a minimal HTML page (single file, no build step, vanilla JS)
- [ ] Include: bead list with search box (calls `/v1/memory/search`), session browser
      (calls `/v1/memory/inspect/turns`), and a flush trigger button
- [ ] Wire `/ui/graph` to a lightweight graph visualization of associations
      (can use the same D3.js force-directed approach from the demo's `graph.html`)
- [ ] This is a developer/evaluator inspection surface — the full React demo stays
      as the polished showpiece for external audiences

---

## Priority order for the week

| # | Task | Effort | Adoption Impact |
|---|------|--------|-----------------|
| 1 | MCP protocol server at `/mcp` | M | Very High |
| 2 | `remember` / `recall` aliases | XS | High |
| 3 | `core-memory serve` CLI command | XS | High |
| 4 | Async write flag on turn-finalized | S | Medium |
| 5 | Built-in `/ui` inspection page | L | Medium |

**Week plan:** #2 and #3 are hours each — ship them first for immediate demo polish.
#1 (MCP protocol server) is the unlock for Claude Code / Cursor integrations and is
the biggest adoption surface; worth prioritizing even though it's the most work.
#4 and #5 follow once the primary integration path is solid.
