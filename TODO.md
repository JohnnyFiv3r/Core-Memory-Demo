# TODO: Adoption-Ready Ergonomics

Core Memory already has hybrid search, MCP-typed operations,
a full HTTP server (`/v1/mcp/*`, `/v1/memory/*`, `/healthz`, `/v1/metrics`), multi-tenant
header routing, and integrations for LangChain/PydanticAI/CrewAI/SpringAI/Neo4j.

These are the genuine remaining adoption-readiness gaps to close.

---

## 1. MCP protocol server endpoint (`/mcp`)

**Adopter expectation:** A proper MCP streamable-HTTP server at `/mcp`. Any client
(Claude Code, Cursor, Windsurf, Open WebUI) wires it up with one JSON snippet and talks
the MCP protocol natively. No custom glue code.

**What Core Memory has:** `/v1/mcp/*` REST endpoints that wrap MCP-typed operations —
but these are plain REST, not MCP protocol. Clients can't point at them with a standard
MCP config block.

**Gap:** Core Memory has the logic; it just hasn't been surfaced as a proper MCP transport.

**Status:** Closed, deployed, and smoke-tested. Core-Memory PR #136
(`feb08489f05074c315007d83e55881b1f79b3041`) added the protocol server; hosted demo
follow-ups mounted it, started the MCP session manager lifespan, and included the public
host allow-list from Core-Memory PR #137 (`cd6904e1bc7133c8229c04b7b0be5fe452ec01f3`).
Final hosted smoke passed against Render and the public demo: `/mcp/healthz`, MCP
`initialize`, `list_tools`, `list_prompts`, and `call_tool("status")`. The public
Vercel URL for protocol clients is `https://demo.usecorememory.com/mcp` (no trailing
slash); direct Render also accepts `/mcp/`. The shipped MCP v1 surface mirrors the
public verbs (`capture`, `recall`, `ingest`, `status`) rather than the older REST-only
typed operation names; `/v1/mcp/*` REST endpoints remain unchanged.

**Tasks:**
- [x] Add an MCP streamable-HTTP server endpoint at `/mcp` (mount alongside the existing
      FastAPI app in `core_memory/integrations/http/server.py`)
- [x] Expose the existing typed-read tools (`query_current_state`, `query_temporal_window`,
      `query_causal_chain`, `query_contradictions`) as MCP tools through the protocol server
- [x] Expose the existing typed-write tools (`write_turn_finalized`,
      `apply_reviewed_proposal`, `submit_entity_merge_proposal`) as MCP tools
- [x] Document the Claude Code config snippet in README.md:
      ```json
      { "mcpServers": { "core-memory": { "type": "streamable-http",
        "url": "http://localhost:8000/mcp" } } }
      ```

---

## 2. Friendlier entry-point aliases for the two canonical verbs

**Adopter expectation:** Two verbs cover 80% of integrations: `remember(messages)` to write,
`recall(query)` to read. New users have one mental model.

**What Core Memory has:** `process_turn_finalized(...)` (write) and `memory_execute(...)`
(read) — correct and powerful, but `process_turn_finalized` is a mouthful and signals
"internal machinery" rather than "start here."

**Gap:** The canonical verbs are not approachable for first-touch integration.

**Status:** Closed in Core-Memory PR #131 (`bd5beca`) and included in the current
demo backend pin (`9913643cd61aeec3ff7956cd70d1abed5a449277`). Keep future
`remember(text, type=...)` declarative-write work separate from this closed alias slice.

**Tasks:**
- [x] Add `capture(...)` as a public alias for `process_turn_finalized(...)` in
      `core_memory/__init__.py` — same signature, same behavior, zero new logic.
      (Note: the locked verb taxonomy uses `capture` for canonical write — observed-from-conversation —
      and reserves `remember(text, type=…)` for **declarative user-authored memory writes** in a
      later item. Don't conflate them.)
- [x] Add `recall(...)` as a public alias that wires through the new agentic recall
      orchestrator (see item #5 below) — single-verb read that internally scales across
      tiers. Until the orchestrator lands, `recall` can be a thin wrapper over
      `memory_execute(...)` with `intent="remember"` as the default; swap to the
      orchestrator when #5 ships.
- [x] Export `capture` and `recall` from the top-level `core_memory` package
- [x] Add a "fastest path" README example using `capture` / `recall` above the existing
      `process_turn_finalized` / `memory_execute` examples (keep both; aliases are additive)

---

## 3. Async transcript ingestion pipeline

**Adopter expectation:** `POST /api/ingest/transcript` returns `202 Accepted` immediately;
ingestion happens in the background. Integrations never block on write latency.

**What Core Memory has:** The benchmark harness in `Core-Memory-Demo` is already most of
the way there. The infrastructure exists and is production-quality — it just needs to be
generalized from LoCoMo-specific to generic transcript input.

**Reuse directly (no changes needed):**
- `benchmark_store.py` — Postgres job queue with `enqueue_job` → `claim_next_job`
  (`FOR UPDATE SKIP LOCKED`) → `finish_job`. Already the right pattern for async ingestion.
- `benchmark_worker.py` — claim-one-job-and-run dispatch loop. Keep as-is.
- `replay_locomo_sample()` in `transcript_only` mode — the turn iteration, canonical
  turn-finalization boundary, `per_session`/`end_only` flush policy, and
  `_synthesize_locomo_associations()` for temporal order and entity-overlap edges. All of
  this is generic enough to keep.

**What needs to change:**
- [x] Write a **thin input normalizer** that maps a generic transcript schema
      (`[{role, content, timestamp?}]`) to canonical turn-envelope dicts. Current Core
      Memory envelopes carry `turns=[{speaker, role, content, ts, metadata}]` plus
      `session_id`, `turn_id`, and envelope `metadata`.
- [x] **Pair user+assistant turns** before the per-turn loop. The harness treats each
      utterance as a separate bead; real transcript ingestion should group consecutive
      `user`/`assistant` pairs so canonical `turns` preserve the completed exchange.
- [x] **Replace `_extract_locomo_claims()`** with a generic pass — either a simple
      NER/pattern step or just omit it initially. The first implementation omits generic
      claim extraction; claims remain an enrichment layer, not structural.
- [x] **Generalize the job `kwargs` schema** from LoCoMo params (`sample_id`, `sessions`)
      to `{transcript_id, turns: [...], session_id, flush_policy}`.
- [x] **Add `POST /ingest/transcript`** to the demo backend that enqueues a job and
      returns `{job_id}` — callers poll `/api/ingest/jobs/{job_id}` for status; queued
      deployments persist through `benchmark_store.read_job(job_id)`.

**Status:** Closed, deployed, and smoke-tested. Hosted demo PRs added generic
transcript normalization/pairing, `POST /api/ingest/transcript`, job status polling,
and inline production execution via `TRANSCRIPT_INGEST_RUN_MODE` while preserving the
queue path. Deployed smoke ingested a transcript and recalled the imported fact from
chat.

**Do not use** `ingest_locomo_turns()` / `MemoryStore.add_bead()` directly — that path
bypasses the canonical runtime. Stay on Core Memory's canonical turn-finalization boundary.

---

## 4. Shared `RecallResult` output contract across surfaces

**Adopter expectation:** Single response shape for memory queries — what was retrieved
and what to do with it. Stable across MCP, REST, and direct-library so integrators
write one parser.

**What Core Memory has:** `/api/chat` returns ad-hoc JSON shaped for the current Reagraph
demo UI. Retrieval primitives return their own shapes. CLI commands return text. No
common contract.

**Gap:** Adopters writing against Core Memory hit different shapes per surface; demos
and CLI drift over time.

**Status:** Partially implemented. Core-Memory now has `core_memory.retrieval.contracts.RecallResult`
and the demo has `POST /api/recall` returning the contract, but #4 remains open until
CLI JSON, `/api/chat`, REST, MCP, and direct-library parity are locked by tests and the
frontend consumes the same evidence/source model.

**Tasks:**
- [x] Define `RecallResult` in `shared/contracts.py` (or main-repo equivalent) with fields:
      `answer`, `why`, `evidence: [{bead_id, type, title, content_excerpt}]`,
      `sources: [{turn_id, session_id, speaker, ts}]`, plus `tier_path` and `steps`
      (observability into which internal tier the orchestrator hit — see item #5)
- [ ] Update `/api/chat` to return `RecallResult` (preserve existing fields as deprecated
      aliases until callers migrate)
- [ ] Add a CLI `--json` flag (in `core-memory` CLI in the main repo) that emits the same
      shape
- [ ] Parity test: same query against `core-memory recall ... --json` and demo
      `POST /api/recall` returns identical `evidence[].bead_id` set and identical
      `answer`/`why` strings (modulo LLM nondeterminism)

---

## 5. POST /api/recall — single-verb recall endpoint with internal scaling

**Adopter expectation:** Single recall verb. Integrators don't have to know which retrieval
primitive fits their question.

**What Core Memory has:** Three primitives (`memory_search`, `memory_trace`, `memory_execute`)
but no orchestrator. Callers have to pick. `/api/chat` does some routing but it's
bespoke per-demo logic.

**Gap:** No grounded multi-hop recall endpoint that surfaces evidence + sources behind a
single verb. The demo's headline feature can't be wired without it.

**Status:** Partially implemented and deployed. Core-Memory has `core_memory.retrieval.agent.recall(...)`,
public `capture`/`recall` aliases, MCP `recall`, and hosted demo `POST /api/recall`.
Remaining closeout is parity and productization: `/api/chat` must emit/use the same
contract without bespoke drift, CLI JSON must match, MCP structured output needs parity
tests, effort semantics need tightening, and the UI needs evidence/source transparency.

**Tasks:**
- [x] Build the orchestrator in the main Core-Memory repo (see Core-Memory item #5 /
      `core_memory/retrieval/agent.py`) — public entrypoint
      `recall(query, root, *, effort="medium", speaker=None) -> RecallResult`.
      Public effort modes are `"low" | "medium" | "high"`; internal tier choice is
      reported via `tier_path` but not exposed as separate verbs.
- [ ] Effort semantics for the first implementation:
  - `low`: direct lookup only (`memory_execute` with `grounding_mode="search_only"`,
        small `k`, no required causal expansion); intended for low-latency UI/preview use.
  - `medium`: default grounded recall (`prefer_grounded`, modest `k`, source hydration);
        use causal expansion when query intent or wording suggests why/how/decision/history.
  - `high`: deeper grounded recall (`prefer_grounded`, larger `k`, broader hydration);
        benchmark/audit/thorough mode, but still bounded and deterministic.
- [ ] Keep `effort="dynamic"` out of the first orchestrator behavior except as a documented
      future mode; do not let MVP adoption depend on opaque LLM-chosen effort.
- [x] Add `POST /api/recall` to the demo backend wired to the orchestrator.
- [x] Return the `RecallResult` shape from item #4.
- [ ] Update `/api/chat` to call the same orchestrator internally so demo and CLI
      behave identically for grounded recall queries.
- [ ] Next visible demo feature: answer transparency UI.
  - [ ] Frontend: expandable evidence/source cards under answer results.
  - [ ] Show retrieval tier path / diagnostics in the UI (which tiers ran, why they ran,
        and which evidence items grounded the answer).
- [ ] Public effort naming: prefer adopter-friendly `effort="low|medium|high"`
      because it matches Claude/Codex mental models; document them behaviorally as
      low=fast direct lookup, medium=default grounded recall, high=deep multi-hop /
      temporal / benchmark-grade recall.
- [ ] Add a later `effort="dynamic"` mode where query parsing chooses low/medium/high
      from query complexity, expected evidence shape, time constraints, and confidence.
- [ ] Add query-planning metadata that fuzzy-defines the expected result shape before
      retrieval, e.g. "why did we make decision X last week?" should expect decision
      beads in the inferred date range plus linked supersession/update beads for current
      context.
- [ ] Once the recall orchestrator lands, tighten `recall(...)` request kwargs by either
      accepting only known top-level recall params or namespacing extras under something
      like `filters={...}` / `constraints={...}`.

---

## 6. Reproducible LoCoMo + LongMemEval scoring harness

**Adopter expectation:** Published, reproducible memory benchmarks with an in-repo runner and citable reports.

**What Core Memory has:** The benchmark harness in this repo runs LoCoMo replay
end-to-end and produces edges/claims. Scoring and category breakdown are not yet
packaged as a reproducible report.

**Gap:** "Top LoCoMo with Core Memory's full feature set" is the defensible competitive
lever, but only if running `core-memory benchmark run locomo` produces a stable,
citable number.

**Tasks:**
- [ ] Wrap the existing benchmark harness with a scoring layer at
      `backend/benchmarks/<name>/runner.py` (or similar). The runner is a thin adapter:
      parse → ingest → run questions through `m.recall(query, budget="full")` →
      score against gold → write report.
- [ ] Score against gold under `data/locomo/gold/` per LoCoMo's published format.
- [ ] Report includes: total score, per-category breakdown (single-hop, multi-hop,
      temporal, open-ended, adversarial for LoCoMo; equivalent categories for
      LongMemEval), per-case provenance (which beads retrieved, which edges walked,
      tier_path actually hit, why scored that way).
- [ ] Comparison artifact `docs/benchmarks/locomo/baselines.md` — Core Memory vs
      published baseline-RAG / long-context-LLM / memory-system numbers.
- [ ] Same shape for LongMemEval.
- [ ] Feature-flag the run: causal edges on/off, claims on/off, agent-judged
      myelination on/off — document what was on in the report so reproducers match.
- [ ] Stretch (not gate-blocking): exceed published SOTA on at least one category per
      benchmark; document where we don't with a brief diagnosis.

**Do not use** flat-search-only recall for benchmark queries — that bypasses Core
Memory's differentiators (causal traversal, multi-hop chains). Stay on
`m.recall(query, budget="full")` so the orchestrator brings the full feature set to bear.

---

## 7. Wire agent instructions into every live integration path

**The problem:** `docs/integrations/openclaw/core-memory-skill-instructions.md` is 296 lines
of agent-facing behavioral spec — authority boundaries, canonical verb rules, when to
abstain, how to handle degraded retrieval. Nine other `.md` files in that folder add
~1,420 more lines. None of it is loaded at runtime. `grep -rn "core-memory-skill-instructions"`
across every `.py`, `.js`, `.json`, `.toml`, `.yaml` in the repo returns zero hits.

The OpenClaw plugin (`plugins/openclaw-core-memory-bridge/index.js`) is a pure event
bridge — spawns Python subprocesses, parses JSON, reads no `.md` files. The manifest
(`openclaw.plugin.json`) has no `skillInstructions`, no `systemPromptAddendum`, no docs
reference. Any OpenClaw user installing the plugin gets the wiring but not the behavior
spec. The model has no idea the rules in that doc exist.

**Fix path — in order of preference:**

- [x] **Option A — MCP prompt resource (right answer, do alongside item #1):**
      Closed in Core-Memory PR #136 as MCP prompt `core-memory.agent-guide`,
      included in this demo backend pin. Post-deploy smoke should verify `/mcp/healthz`
      advertises the prompt and MCP prompt enumeration returns it.
      When the `/mcp` server ships, register the skill instructions as a named MCP prompt
      resource (`core_memory_skill`). MCP has first-class support for prompts and resources;
      every MCP client gets injection-by-default with zero per-client wiring. The `.md`
      becomes a first-class resource instead of a stranded doc, and the problem is solved
      for all future clients in one shot.

- [x] **Option B — OpenClaw manifest (cheapest short-term fix):**
      Closed in Core-Memory PR #129: the OpenClaw bridge loads the canonical skill
      instructions into the plugin prompt supplement/skill path for existing users.
      Check whether `openclaw.plugin.json` supports an `instructions` or
      `systemPromptAddendum` field per the OpenClaw plugin spec. If yes, add
      `"instructions": "@docs/integrations/openclaw/core-memory-skill-instructions.md"`
      (or inline the text). One-line fix. If OpenClaw exposes no such field, file an
      upstream issue and fall back to Option C.

- [ ] **Option C — bridge injection at register time:**
      Add a `bridge.get_skill_instructions()` Python entry that returns the `.md` contents
      as a string. Have `index.js` call it once at plugin registration and pass the text
      to whatever system-prompt addendum API OpenClaw exposes.

**Recommended:** Do Option B now (30 minutes) to stop the bleeding for existing OpenClaw
users. Do Option A when item #1 ships — it solves this permanently across all clients.

---

## 8. Promote async transcript ingest to Core-Memory demo, CLI, and MCP surfaces

**Adopter expectation:** The hosted demo proves async transcript ingestion first, but
users should eventually get the same capability from local Core Memory surfaces: the
in-repo demo, CLI, MCP, and direct-library APIs.

**What the hosted demo will have after item #3:** A source-adapter layer that accepts
generic transcript-like input, enqueues a background job, normalizes/pairs turns, and
runs them through the canonical Core Memory turn-finalization pipeline.

**Gap:** If this stays only in the hosted demo backend, the operational behavior and
data contract become another demo-only feature instead of the durable ingestion model.

**Tasks:**
- [x] After hosted demo item #3 lands, copy the stable request/response contract into
      `Core-Memory/demo` so the local demo exercises the same async ingest path. The
      local demo now exposes `POST /api/ingest/transcript` and
      `GET /api/ingest/jobs/{job_id}` with an in-memory async worker over the shared
      Core-Memory transcript ingest helper.
- [x] Identify the boundary between demo-owned operational queueing and Core-Memory-owned
      ingestion semantics; keep memory behavior in Core Memory, keep hosted deployment
      plumbing in demo repos. Core Memory now owns synchronous normalization/pairing and
      canonical turn-finalization; hosted demo keeps Postgres queue/run-mode plumbing.
- [x] Add a direct-library helper once the contract is proven, e.g.
      `ingest_transcript(...)` or `capture_many(...)`, implemented on top of canonical
      turn finalization rather than direct bead writes.
- [x] Add CLI support for file-based ingestion, e.g.
      `core-memory ingest transcript path.json --root ...`, returning a synchronous
      summary locally and documenting how hosted async jobs differ.
- [x] Extend the MCP `ingest` tool to accept the same transcript schema or a file/path
      reference, so MCP clients can import conversation history without custom REST glue.
- [x] Preserve the locked verb taxonomy: `capture` for observed conversation turns,
      future `remember(text, type=...)` for declarative user-authored memory, and
      `recall(query, effort=...)` for read. Transcript ingest stays an observed-turn import
      path and does not perform direct declarative memory writes.
- [x] Add parity tests showing a tiny transcript ingested through hosted demo, local demo,
      CLI, and MCP surfaces yields recallable evidence with the same bead/source IDs where
      deterministic IDs are available. Core-Memory now has parity coverage for direct
      library, CLI, MCP, and local demo async surfaces using the same deterministic
      transcript/session/turn contract. Hosted demo coverage landed with item #3 smoke;
      future semantic-index "recallable without manual rebuild" polish remains tracked in
      `Core-Memory/demo/TODO.md` #7 rather than this adoption-surface item.

**Status:** Closed. The stable transcript normalization/pairing contract has been promoted
into the library as `ingest_transcript(...)`, exported from the public package, exposed via
`core-memory ingest transcript <path>`, reused by the MCP `ingest` tool for both inline
transcript turns and local file imports, and copied into the in-repo local demo as async
`/api/ingest/transcript` + job-status endpoints. Cross-surface parity tests cover direct
library, CLI, MCP, and local demo behavior with deterministic transcript IDs, session IDs,
and turn IDs.

**Non-goals:** Do not move the hosted demo's Postgres job queue wholesale into the library.
Core Memory should own normalization/canonical ingestion semantics; each deployment
surface can choose sync vs async execution and its own queue backend.

## Cross-repo dependencies / references

Keep this TODO focused on adoption surfaces in `Core-Memory-Demo`, but track the main
`Core-Memory` engine work it depends on. The paired engine TODO lives at
`Core-Memory/demo/TODO.md`.

- **#2 `capture` / `recall` aliases** depends on Core-Memory semantic lifecycle ergonomics
  (`Core-Memory/demo/TODO.md` #7). `capture(...)` should not just write a bead; it should
  reliably mark semantic state dirty/enqueue deltas so the memory is recallable without
  manual rebuild rituals.
- **#3 async transcript ingestion** reuses the LoCoMo replay loop, so it should inherit
  Core-Memory association correctness work (`Core-Memory/demo/TODO.md` #3) and semantic
  lifecycle work (#7). Generic transcript edges must use canonical relationship types
  (`associated_with`, `supports`, `follows`, `precedes`, etc.), with heuristic details in
  `reason_text`/`reason_code`, not invented relationship labels.
- **#5 `POST /api/recall` / `recall(query, budget=...)`** depends on Core-Memory goal
  lifecycle (#2), grounding hashes for judged validation (#5), and monotonic claim
  sequencing (#6). Those engine fixes make the single recall verb stable enough to expose
  across REST, CLI, MCP, and direct-library surfaces.
- **#6 reproducible LoCoMo / LongMemEval scoring** depends on Core-Memory causal-quality
  fixes: extracted `because` reasoning (#1), canonical association relationship types (#3),
  grounding hashes (#5), and monotonic claim supersede ordering (#6). Benchmark runs should
  stay on full Core Memory recall/trace paths rather than flat-search-only shortcuts.
  Core-Memory #1 is closed as of 2026-05-13: `because` is defined in the live prompt path as
  grounded free-text support for applied semantic labels/state, with short user-text quotes
  allowed when they are the actual support and weak filler/speculation rejected.
- **#7 agent instructions in live integrations** should reference Core-Memory behavior
  guardrails from #1/#3/#4: treat `because` as grounded label/state support rather than
  guessed filler, treat user questions as retrieval/context rather than declarative memory,
  and use only canonical relationship types. Core-Memory #4 is closed as of 2026-05-13:
  question and retrieval-imperative turns are forced to `context` before LLM bead typing and
  field-judge output cannot promote them.

---

## Priority order for the week

| # | Task | Effort | Adoption Impact |
|---|------|--------|-----------------|
| 1 | MCP protocol server at `/mcp` | Done | Very High |
| 2 | `capture` / `recall` aliases | Done | High |
| 3 | Async transcript ingestion pipeline | Done | High |
| 4 | Shared `RecallResult` output contract | S | Medium-High |
| 5 | `POST /api/recall` (single-verb recall) | M | Very High |
| 6 | LoCoMo / LongMemEval scoring harness | M | High (competitive lever) |
| 7a | Agent instructions → OpenClaw manifest (Option B) | Done | High |
| 7b | Agent instructions → MCP prompt resource (Option A) | Done | Very High |
| 8 | Promote async transcript ingest to Core-Memory demo/CLI/MCP | Done | High |

**Week plan status:** #1, #2, #3, #7a, #7b, and #8 are closed in code/TODO tracking
and have deployed or local parity evidence. #4 and #5 remain the active closeout focus for
making `RecallResult` the single contract across direct-library, CLI, REST, chat, MCP, and
UI. Benchmark scoring #6 should stay separate and use the engine-correctness dependencies
listed in `Core-Memory/demo/TODO.md`.

**Sequence after the original three (#1–#3):** #4 ships the shared contract that #5
depends on. #5 ships `/api/recall` and the single-verb orchestrator (paired with the
Core-Memory main-repo agentic-retrieval work). #6 wraps the existing benchmark harness
with scoring — pairs naturally with #3 once async ingest is generic. #8 is the follow-on
promotion path for #3: prove async transcript ingest in the hosted demo first, then
carry the stable contract into `Core-Memory/demo`, CLI, MCP, and direct-library surfaces.

**Cross-repo note on naming (locked):** The verb taxonomy across both repos is
`capture` (canonical write — observed conversation), `remember(text, type=…)`
(declarative user-authored write — future, separate item), `recall(query, budget=…)`
(single read verb with internal scaling). The functional aliases in item #2 of this
TODO use this taxonomy. The richer `Memory` class API ships in the main repo with the
same verb names plus maintenance methods (`compact`, `myelinate`).
