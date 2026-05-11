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
- [ ] Add `capture(...)` as a public alias for `process_turn_finalized(...)` in
      `core_memory/__init__.py` — same signature, same behavior, zero new logic.
      (Note: the locked verb taxonomy uses `capture` for canonical write — observed-from-conversation —
      and reserves `remember(text, type=…)` for **declarative user-authored memory writes** in a
      later item. Don't conflate them.)
- [ ] Add `recall(...)` as a public alias that wires through the new agentic recall
      orchestrator (see item #5 below) — single-verb read that internally scales across
      tiers. Until the orchestrator lands, `recall` can be a thin wrapper over
      `memory_execute(...)` with `intent="remember"` as the default; swap to the
      orchestrator when #5 ships.
- [ ] Export `capture` and `recall` from the top-level `core_memory` package
- [ ] Add a "fastest path" README example using `capture` / `recall` above the existing
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

## 4. Shared `RecallResult` output contract across surfaces

**What mnemory does:** Single response shape for memory queries — what was retrieved
and what to do with it. Stable across MCP, REST, and direct-library so integrators
write one parser.

**What Core Memory has:** `/api/chat` returns ad-hoc JSON shaped for the current Reagraph
demo UI. Retrieval primitives return their own shapes. CLI commands return text. No
common contract.

**Gap:** Adopters writing against Core Memory hit different shapes per surface; demos
and CLI drift over time.

**Tasks:**
- [ ] Define `RecallResult` in `shared/contracts.py` (or main-repo equivalent) with fields:
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

**What mnemory does:** Single recall verb. Integrators don't have to know which retrieval
primitive fits their question.

**What Core Memory has:** Three primitives (`memory_search`, `memory_trace`, `memory_execute`)
but no orchestrator. Callers have to pick. `/api/chat` does some routing but it's
bespoke per-demo logic.

**Gap:** No grounded multi-hop recall endpoint that surfaces evidence + sources behind a
single verb. The demo's headline feature can't be wired without it.

**Tasks:**
- [ ] Build the orchestrator in the main Core-Memory repo (see Core-Memory item #5 /
      `core_memory/retrieval/agent.py`) — public entrypoint
      `recall(query, root, *, budget="default", speaker=None) -> RecallResult`.
      Internal three-tier escalation (flat semantic → causal trace → transcript lookup);
      tier choice is INTERNAL, not exposed as separate verbs.
- [ ] `budget` knob is the only public control: `"cheap"` (flat search, no LLM),
      `"default"` (5-step / 8k token cap), `"full"` (10-step / 16k for benchmark sweeps).
- [ ] Add `POST /api/recall` to the demo backend wired to the orchestrator.
- [ ] Return the `RecallResult` shape from item #4.
- [ ] Update `/api/chat` to call the same orchestrator internally so demo and CLI
      behave identically for grounded recall queries.
- [ ] Frontend: expandable evidence/sources cards under the answer card; tier-path
      indicator (which tiers ran) for power-user visibility.

---

## 6. Reproducible LoCoMo + LongMemEval scoring harness

**What mnemory does:** Doesn't have a published-and-reproducible memory benchmark.
Memanto claims SOTA but ships no in-repo runner.

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
      published mem0 / Memanto / baseline-RAG / Long-LLM-only numbers.
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

- [ ] **Option A — MCP prompt resource (right answer, do alongside item #1):**
      When the `/mcp` server ships, register the skill instructions as a named MCP prompt
      resource (`core_memory_skill`). MCP has first-class support for prompts and resources;
      every MCP client gets injection-by-default with zero per-client wiring. The `.md`
      becomes a first-class resource instead of a stranded doc, and the problem is solved
      for all future clients in one shot.

- [ ] **Option B — OpenClaw manifest (cheapest short-term fix):**
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
- **#7 agent instructions in live integrations** should reference Core-Memory behavior
  guardrails from #1/#3/#4: do not echo user text as `because`, treat user questions as
  retrieval/context rather than declarative memory, and use only canonical relationship
  types.

---

## Priority order for the week

| # | Task | Effort | Adoption Impact |
|---|------|--------|-----------------|
| 1 | MCP protocol server at `/mcp` | M | Very High |
| 2 | `capture` / `recall` aliases | XS | High |
| 3 | Async transcript ingestion pipeline | S | High |
| 4 | Shared `RecallResult` output contract | S | Medium-High |
| 5 | `POST /api/recall` (single-verb recall) | M | Very High |
| 6 | LoCoMo / LongMemEval scoring harness | M | High (competitive lever) |
| 7a | Agent instructions → OpenClaw manifest (Option B) | XS | High |
| 7b | Agent instructions → MCP prompt resource (Option A) | XS | Very High |

**Week plan:** #2 and #7a are hours each — ship them first. #7a stops the behavioral
spec from being a stranded doc for existing OpenClaw users. #1 unlocks Claude Code /
Cursor integrations and is the biggest adoption surface; fold #7b in when #1 ships
(they're the same PR). #3 is assembly work — the benchmark harness already provides
the job queue, worker, turn loop, flush policy, and association synthesis; the real
work is the normalizer and the pairing step.

**Sequence after the original three (#1–#3):** #4 ships the shared contract that #5
depends on. #5 ships `/api/recall` and the single-verb orchestrator (paired with the
Core-Memory main-repo agentic-retrieval work). #6 wraps the existing benchmark harness
with scoring — pairs naturally with #3 once async ingest is generic.

**Cross-repo note on naming (locked):** The verb taxonomy across both repos is
`capture` (canonical write — observed conversation), `remember(text, type=…)`
(declarative user-authored write — future, separate item), `recall(query, budget=…)`
(single read verb with internal scaling). The functional aliases in item #2 of this
TODO use this taxonomy. The richer `Memory` class API ships in the main repo with the
same verb names plus maintenance methods (`compact`, `myelinate`).
