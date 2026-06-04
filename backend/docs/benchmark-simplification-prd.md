# PRD: Simplify the LoCoMo demo to run Core Memory at production fidelity

## Context / problem

The LoCoMo benchmark grew into a **fork** of the real product. Instead of ingesting and
retrieving the way the live PydanticAI demo does, it built a parallel path:

- A bespoke `lifecycle_runner` that re-implements replay/flush/QA/scoring next to the
  real seed path (`replay_locomo_corpus`).
- Ingestion that hands Core Memory a **deterministic, hand-built `crawler_updates` bead**
  (`locomo_turn_crawler`) — bypassing the engine's own LLM authoring → thin beads, no claims.
- A `deterministic` vs `judge` `enrich_mode` toggle, a `bead_judge` directive, a fail-closed
  guard, effort tiers, and a multi-hop `k` hack — all built to compensate for bypassing the
  real path.
- Retrieval done as a **one-shot `core_recall(effort=...)`** call — the agent and its tools
  are never used, so the "agent judges and re-queries" behavior of the real product is absent.

Net: the benchmark measures a synthetic pipeline, not the demo. (Confirmed real, separate
issues along the way: the *live web instance* had a truncated embeddings model name and ran
**lexical** for days while reporting healthy — the benchmark worker was correct, so benchmark
numbers were valid. That masking is its own fix, below.)

## Goal

Make the demo **be** the product and the benchmark **measure** the product, at maximum
fidelity. One ingestion path, one retrieval path, both identical to production. Latency is
explicitly not a concern — always use the richest LLM-driven path, never a heuristic fallback.

## Non-goals

- Reproducibility/cost optimization (we accept LLM calls per turn and per QA).
- Tuning graph-traversal heuristics before we can measure where evidence is lost.
- Changing the Core Memory library CLI runner (we don't use it; the demo already forces
  `qdrant` + `required` + external OpenAI embeddings + fail-closed).

---

## Target architecture

### 1. Seed = production-faithful, per-turn ingestion
- Ingest **one turn at a time** through the same `process_turn_finalized` the live chat uses.
- For **every new bead, the association pass runs live** (`run_association_pass`) — edges are
  written per turn as the corpus grows, exactly as in production.
- **LLM at every step, no fallbacks:**
  - Bead authoring via the native LLM judge (`bead_judge=llm`) — **stop supplying the
    deterministic `crawler_updates` bead**.
  - Claim extraction `CLAIM_EXTRACTION_MODE=llm` (currently `heuristic`).
  - Live OpenAI embeddings per bead (`store_add_bead_ops` external path — works now).
- Tag each turn with its LoCoMo `dia_id` in metadata/`source_turn_ids` for scoring provenance.

### 2. Benchmark = QA only, agent-driven retrieval
The benchmark run does **only** the QA questions against the already-seeded corpus. For each
question, run the **real PydanticAI agent** with Core Memory's three tools and let it drive an
iterative loop, in series, judging between calls:

1. **`memory_search`** — semantic vector search (top-k candidates).
2. **`memory_trace`** — causal-chain traversal from the candidates; the agent judges the
   returned context and re-traces deeper frontiers as needed — **adaptive, capped ~6 hops**
   (whatever it takes to reach the gold/full context, not a fixed number).
3. **`hydrate` / `get_turn`** — pull the source transcript for the top-k + every traversed bead
   and hydrate the answer context with all of it.

Then generate the answer from the hydrated context and score F1 + evidence-recall against the
`dia_id`s the agent actually retrieved/traced/hydrated.

### 3. Qdrant floor test + candidate-survival diagnostics
Per QA, emit a survival trace so we can prove *where* (if anywhere) Core Memory underperforms
its own retrieval floor:

| Stage | Recorded |
|---|---|
| Raw Qdrant top-k (the floor) | gold in top 5/10/20? (pure vector, no pipeline) |
| CM `search`-only over Qdrant | gold survives rerank/boosts/filters? |
| + causal traversal (agent `trace`, ≤6 hops) | gold added/preserved? |
| + hydration → answer | gold in final context the LLM saw? in the answer? |

**Hard assertion:** flag/fail if Core Memory drops gold evidence that raw Qdrant retrieved —
that pinpoints loss in rerank/traversal/answer-policy vs. embedding/index quality.

### 4. Honest health (no silent degradation)
- `/demo/runtime` `semantic_backend` must reflect `semantic_ready` + `last_build_error` from
  the manifest and report `usable_backend: false` + the error when the build failed — instead
  of "ready" because Qdrant has a connection and some rows. (This masked a 3-day lexical
  fallback.)
- Surface a loud "SEMANTIC DEGRADED → lexical: <error>" banner/health signal in the demo when
  the live store isn't truly semantic.

### 5. Config (max fidelity, no fallbacks) — both web + worker
```
CORE_MEMORY_VECTOR_BACKEND=qdrant
CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS=1
CORE_MEMORY_EMBEDDINGS_PROVIDER=openai
CORE_MEMORY_EMBEDDINGS_MODEL=text-embedding-3-large   # verify exact value on BOTH services
CORE_MEMORY_CANONICAL_SEMANTIC_MODE=required
CORE_MEMORY_CLAIM_LAYER=1
CORE_MEMORY_CLAIM_EXTRACTION_MODE=llm                 # was heuristic
# bead_judge=llm applied per request; agent-authored gate set so the LLM-judged path is the
# authority (no structural fallback)
```

---

## Teardown (delete / retire)
- `app/benchmarks/locomo_turn_crawler.py` — the deterministic `crawler_updates` bead.
- `enrich_mode` (deterministic/judge) toggle + the UI control + `benchmark_enrich_mode`.
- The fail-closed **judge guard** `_assert_judge_engaged` (the "0 claims" masquerade check) —
  no longer meaningful once LLM authoring is the only path.
- Effort tiers in the benchmark + the `MULTI_HOP_RETRIEVAL_K` hack — replaced by agent-driven,
  adaptive retrieval.
- The second replay engine: fold benchmark ingestion onto the real seed path
  (`replay_locomo_corpus`) so there is **one** LoCoMo ingestion implementation.

## Upstream (Core Memory) asks — gaps the demo can't fill alone
1. **Deep causal traversal with a cap.** `recall`/`trace` currently maxes at 2 hops
   (`_EFFORT_DEFAULTS`); expose a depth/cap parameter so the agent can re-trace frontiers up to
   ~6 hops without walking the whole corpus.
2. **Confirm associations are LLM-authored** (the user wants LLM associations, not just
   entity/embedding-overlap edges). If not, add an LLM association mode.
3. **Embedded-Qdrant doctor honesty.** `semantic_doctor()` may mark embedded Qdrant usable on
   connectivity + row count while the build actually failed; it must respect `semantic_ready`.

---

## Acceptance criteria
- One ingestion path; `lifecycle_runner` fork and `locomo_turn_crawler` removed.
- A seeded sample shows, per turn: an LLM-authored bead, claims (LLM), live associations, and a
  3072-dim OpenAI vector in Qdrant (`manifest.dimension == 3072`, `semantic_ready: true`).
- Benchmark QA runs the real agent + 3 tools; transcripts of its tool calls are captured.
- Report includes the floor-test/survival table per QA and flags any gold dropped below the
  Qdrant floor.
- `/demo/runtime` reports `usable_backend: false` + the error when the build is degraded.

## Open decisions
1. Cap exact value (we're starting at **6**, adaptive — confirm).
2. Whether to keep any cheap/deterministic "smoke" mode at all, or go LLM-only everywhere.
3. Sequencing: build demo-side (seed rewrite + agent QA + diagnostics, capping hops at the
   current engine max) in parallel with the upstream deep-traversal PR, then wire the 6-hop cap
   when it lands.
