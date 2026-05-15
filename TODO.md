# TODO: Adoption-Ready Ergonomics (mnemory learnings)

Mnemory (https://github.com/fpytloun/mnemory) is an MCP-server-first persistent memory layer.
After reading both codebases, Core Memory already has hybrid search, MCP-typed operations,
a full HTTP server (`/v1/mcp/*`, `/v1/memory/*`, `/healthz`, `/v1/metrics`), multi-tenant
header routing, and integrations for LangChain/PydanticAI/CrewAI/SpringAI/Neo4j.

These are the genuine remaining gaps — things mnemory does that Core Memory hasn't nailed yet.

**Status updated after PR #144 (merged 2026-05-15).**
Items #1, #2, and #7 are fully shipped. Items #4, #5, #6 have major engine-side progress
but still need demo-backend wiring. Item #3 (async write path) remains the most urgent
remaining gap vs. mnemory's shape. Two new gaps identified below.

---

## 1. ~~MCP protocol server endpoint (`/mcp`)~~ ✓ SHIPPED

**Shipped in PRs #127–#143.** `core_memory/integrations/mcp/protocol_server.py` builds a
FastMCP streamable-HTTP app with 12 tools: `capture`, `recall`, `ingest`, `status`,
`query_current_state`, `query_temporal_window`, `query_causal_chain`, `query_contradictions`,
`write_turn_finalized`, `apply_reviewed_proposal`, `submit_entity_merge_proposal`.
DNS rebinding protection covers localhost and the hosted demo domains.
One-command client installer: `core-memory mcp install --client cursor|claude-code|windsurf|open-webui`.

All tasks complete:
- [x] MCP streamable-HTTP server at `/mcp`
- [x] All typed-read and typed-write tools exposed as MCP tools
- [x] Claude Code config snippet in docs (`docs/integrations/mcp/quickstart.md`)

---

## 2. ~~Friendlier entry-point aliases for the two canonical verbs~~ ✓ SHIPPED

**Shipped in PRs #127–#143.** `core_memory/__init__.py` exports `capture`, `recall`,
`ingest_transcript`, `normalize_transcript_payload`, `RecallResult`, and the full
`RecallPlanning`/`RecallStep`/`EvidenceItem`/`SourceItem` contract types.
`Memory(root).capture(user=..., assistant=...)` shortcut form works. Verb taxonomy locked:
`capture` = observed-conversation write, `recall(query, effort=low|medium|high)` = single
read verb, `remember(text, type=…)` = declarative user-authored write (future item).

All tasks complete:
- [x] `capture` / `recall` exported from `core_memory`
- [x] `recall` wired to the agentic orchestrator with `effort` knob
- [x] `Memory` class shortcut form (`capture(user=..., assistant=...)`)

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

**Engine-side status after PR #144:** `transcript_ingest.py` gained session window
continuity: when `session_id` is supplied, the ingest path now calls
`_session_visible_bead_ids(root, session_id)` and merges prior visible bead IDs into
`window_bead_ids` so each ingested turn inherits the session's rolling window context.
The return value now includes an `associations_created` summary (`count`, `by_type`,
`items`) built from the index post-ingest. These are production-quality improvements
reusable directly by the generic pipeline below.

**Do not use** `ingest_locomo_turns()` / `MemoryStore.add_bead()` directly — that path
bypasses the canonical runtime. Stay on `emit_turn_finalized()` + `process_memory_event()`.

---

## 4. Shared `RecallResult` output contract across surfaces

**What mnemory does:** Single response shape for memory queries — what was retrieved
and what to do with it. Stable across MCP, REST, and direct-library so integrators
write one parser.

**Engine-side status after PR #144:** `RecallResult` in `core_memory/retrieval/contracts.py`
now carries `evidence: [EvidenceItem]` (each with `bead_id`, `type`, `title`, `grounding_hash`),
`sources: [SourceItem]`, `tier_path`, `steps: [RecallStep]`, `planning: RecallPlanning`,
plus two new PR #144 fields: `resolved_goals: [ResolvedGoalItem]` (resolved goal state
surfaced by recall without new writes) and `claim_slots: {key: ClaimSlotItem}` (current
resolved state per subject+slot claim chain). Significantly richer than mnemory's flat list.

**Gap (demo side only):** `/api/chat` still returns ad-hoc Reagraph-shaped JSON; no
`POST /api/recall` endpoint returns the contract.

**Tasks:**
- [x] `RecallResult` defined in engine (`core_memory/retrieval/contracts.py`) with
      `evidence`, `sources`, `tier_path`, `steps`, `planning`
- [x] `RecallResult` expanded with `resolved_goals`, `claim_slots`, `grounding_hash` (PR #144)
- [ ] Update demo `/api/chat` to return `RecallResult` (preserve existing fields as aliases)
- [ ] Parity test: same query against `core-memory recall ... --json` and demo
      `POST /api/recall` returns identical `evidence[].bead_id` set

---

## 5. POST /api/recall — single-verb recall endpoint with internal scaling

**What mnemory does:** Single recall verb. Integrators don't have to know which retrieval
primitive fits their question.

**Engine-side status after PR #144:** `core_memory/retrieval/agent.py` expanded by +159 lines.
The `recall(query, effort=..., root=..., include_raw=...) -> RecallResult` entrypoint now
internally resolves: association evidence grounding via `_add_evidence_grounding()`,
goal resolution via `_resolved_goals_for_result()`, claim slot enrichment via
`resolve_current_state()`, and causal/temporal hints via `_looks_causal_or_temporal()`.
Public control is `effort=low|medium|high` (the renamed `budget` knob). The benchmark
runner calls `recall(query, effort="high", root=root, explain=True)` as the canonical path.

**Gap (demo side only):** No `POST /api/recall` demo endpoint; `/api/chat` still uses
ad-hoc routing and doesn't return `RecallResult`.

**Tasks:**
- [x] Orchestrator built in engine (`core_memory/retrieval/agent.py`) with `effort` knob
- [x] Internal escalation: causal/temporal routing, goal resolution, claim slot enrichment (PR #144)
- [ ] Add `POST /api/recall` to demo backend (`backend/app/`) wired to `recall()`.
- [ ] Return the `RecallResult` shape from item #4.
- [ ] Update `/api/chat` to call the same orchestrator so demo and CLI behave identically.
- [ ] Frontend: expandable evidence/sources cards; tier-path indicator for power-user visibility.

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

**Engine-side status after PR #144:** `benchmarks/locomo_like/runner.py` gained slot
validation (`_slot_validation()`), grounding hash tracking (`_evidence_grounding_hashes()`),
`_run_recall_for_benchmark()` using `recall(effort="high", explain=True, include_raw=True)`,
and `_engine_state_slots()` with SHA-256 state hashing for reproducibility. The runner
now produces per-case diagnostics with expected vs. actual slot, grounding hash, and
`chain_seq`. The scoring infrastructure exists; what remains is gold-file parsing and
the comparison baselines doc.

**Tasks:**
- [x] Runner uses `recall(effort="high")` as the canonical benchmark path (not flat search)
- [x] Per-case diagnostics: slot validation, grounding hash, answer class matching (PR #144)
- [x] `_engine_state_slots()` SHA-256 hash for reproducibility gate
- [ ] Score against gold under `data/locomo/gold/` per LoCoMo's published format.
- [ ] Report: total score, per-category breakdown, per-case provenance.
- [ ] Comparison artifact `docs/benchmarks/locomo/baselines.md` vs. mem0/Memanto/baseline-RAG.
- [ ] Same shape for LongMemEval.
- [ ] Feature-flag the run: causal on/off, claims on/off — document what was on in the report.

**Do not use** flat-search-only recall for benchmark queries — that bypasses Core
Memory's differentiators (causal traversal, multi-hop chains). Stay on
`recall(query, effort="high")` so the orchestrator brings the full feature set to bear.

---

## 7. ~~Wire agent instructions into every live integration path~~ ✓ SHIPPED

**Shipped in PRs #127–#143.** Both fix paths landed:

- [x] **Option A (MCP prompt resource):** `core-memory.agent-guide` registered as a
      named MCP prompt in `protocol_server.py` via `@mcp.prompt(name=PROMPT_NAME)`.
      Every MCP client gets the 46-line canonical agent guide at `core_memory/integrations/mcp/core-memory-agent-guide.md`
      injected at session start — zero per-client wiring required.
- [x] **Option C (bridge injection):** `plugins/openclaw-core-memory-bridge/index.js`
      calls `loadSkillInstructions()` (reads `core-memory-skill-instructions.md` via
      `readFileSync`) at plugin register time and passes it to
      `api.registerMemoryPromptSupplement()` as "## Core Memory Bridge Instructions".
      Graceful degradation: logs warning and continues if file load fails or API unavailable.

The behavioral spec is no longer a stranded doc for either MCP or OpenClaw clients.

---

---

## 8. Async write path (capture returns 202)

**What mnemory does:** `POST /api/remember` returns `202 Accepted` immediately; the
write pipeline runs in the background. Integrations never block on write latency, which
matters when `capture` is called mid-conversation before the user's next turn arrives.

**What Core Memory has:** `capture(...)` is synchronous end-to-end —
`process_turn_finalized()` → `emit_turn_finalized()` → `process_memory_event()` → index
update all in-path. PR #144's enrichment delta pipeline queues enrichment work separately,
but the core write boundary still blocks.

**Gap:** The comparison to mnemory's `202 Accepted` pattern holds. This is the top
remaining ergonomic gap vs. mnemory's shape.

**Tasks:**
- [ ] Add `POST /ingest/transcript` to demo backend that enqueues via `benchmark_store`
      and returns `{job_id}` immediately. Callers poll `read_job(job_id)`.
      (This is item #3's demo endpoint — completing #3 also completes this.)
- [ ] Consider whether `capture()` itself should return fast with the enrichment delta
      pipeline already handling the heavy work (associations, claims, goals) async.
      The enrichment delta quarantine in PR #144 is the foundation; wire `202` on top.

---

## 9. Semantic backend first-run friction

**What mnemory does:** Works with just `OPENAI_API_KEY` set. One env var, full semantic
recall.

**What Core Memory has:** Requires knowing to set
`CORE_MEMORY_CANONICAL_SEMANTIC_MODE=degraded_allowed` for lexical-only mode if no
embedding provider is configured, or wiring up FAISS/Qdrant/pgvector explicitly. Error
message is clear (`semantic_index.py:167`) but the friction is real compared to
mnemory's zero-config path. PR #144 added `core-memory semantic doctor` / `status` /
`rebuild` CLI commands which significantly help debugging — but don't eliminate the
first-run env var requirement.

**Tasks:**
- [ ] Auto-detect `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` at first run and configure
      the embedding provider without requiring additional env vars.
- [ ] If no embedding key and no `CORE_MEMORY_CANONICAL_SEMANTIC_MODE` set, auto-set
      `degraded_allowed` and print a one-time hint rather than hard-failing.
- [ ] `core-memory mcp install` already handles client config; extend it to print the
      semantic setup hint if no provider is detected.

---

## Priority order (updated after PR #144)

| # | Task | Status | Effort | Adoption Impact |
|---|------|--------|--------|-----------------|
| 1 | MCP protocol server at `/mcp` | ✓ Done | — | Very High |
| 2 | `capture` / `recall` aliases | ✓ Done | — | High |
| 7 | Agent instructions → live path | ✓ Done | — | Very High |
| 5 | `POST /api/recall` demo endpoint | In progress (engine done) | S | Very High |
| 4 | `RecallResult` → demo surfaces | In progress (engine done) | S | Medium-High |
| 3 | Async transcript ingest pipeline | In progress (engine improved) | S | High |
| 6 | LoCoMo scoring harness (gold + report) | In progress (diagnostics done) | M | High |
| 8 | Async write path (`202 Accepted`) | Not started | M | High |
| 9 | Semantic first-run friction | Not started | S | High |

**Revised week plan:** Engine-side work for #1, #2, #4, #5, #7 is done after PR #144.
The week's remaining output is demo-backend wiring: add `POST /api/recall` returning
`RecallResult` (#5), wire `/api/chat` to the same orchestrator (#4/#5), complete the
async ingest endpoint (#3/#8), then gold-file scoring for the benchmark harness (#6).
Items #8 and #9 are the two genuine ergonomic gaps vs. mnemory that remain unaddressed
in the engine — #9 is a one-afternoon change; #8 needs a decision on whether to extend
the enrichment delta queue or add a separate write queue.

**Cross-repo note on naming (locked):** The verb taxonomy across both repos is
`capture` (canonical write — observed conversation), `remember(text, type=…)`
(declarative user-authored write — future, separate item), `recall(query, effort=…)`
(single read verb). The richer `Memory` class API ships in the main repo with the same
verb names plus maintenance methods (`compact`, `myelinate`).
