# PRD: Production-Fidelity LoCoMo Seeding and Benchmark QA

## Status
Draft for implementation. This PRD is authoritative for the benchmark simplification work and supersedes prior LoCoMo benchmark fork behavior for official/product benchmark runs.

## Problem
The current LoCoMo benchmark path has drifted into a parallel implementation of Core Memory. It can seed, retrieve, enrich, and score through code paths that are not equivalent to the live PydanticAI demo. That makes benchmark results hard to trust and has led to repeated fixes for symptoms of the fork instead of measuring the real product.

## Goal
Make LoCoMo seeding and benchmark QA measure Core Memory at production fidelity:

1. Seeding ingests LoCoMo as real conversation turns, one turn at a time.
2. Each turn is finalized through the same Core Memory runtime path as the demo.
3. The LLM-powered crawler/judge is used everywhere; no dumb deterministic LoCoMo crawler is used in official paths.
4. The crawler/judge sees the session window and applies bead labels, fields, and associations wherever they apply.
5. After seeding all turns, the corpus receives a final association/crawler drain and a real `process_flush` flow to construct a rolling window from the bead store.
6. Benchmark QA runs only against the already-seeded, flushed corpus.
7. Benchmark QA invokes the real PydanticAI agent and real Core Memory retrieval tools.
8. Gold answers/evidence never pollute retrieval, prompts, memory writes, or generated answers before scoring.
9. Any degraded semantic, heuristic, fallback, or partial-fidelity mode hard-fails official LoCoMo runs.

## Non-goals
- Optimizing latency or cost.
- Preserving deterministic LoCoMo benchmark behavior in product/UI paths.
- Reporting benchmark results when semantic retrieval is degraded.
- Tuning graph quality before the benchmark faithfully measures the product.
- Allowing gold labels to influence retrieval or generation.

A small deterministic smoke path may remain only for CI/unit tests and must be explicitly named as smoke/test-only.

---

# Definitions

## Official LoCoMo run
Any user-facing or deployment benchmark run using `locomo_native_lifecycle` or its replacement authoritative LoCoMo benchmark mode.

## Smoke/test-only path
A small deterministic path used only by CI/unit tests to avoid LLM/network dependencies. It must not be reachable from the product UI or deployment benchmark button.

## Production-fidelity seed
A seed that processes each LoCoMo turn through Core Memory's finalized-turn runtime with LLM-powered bead authoring/crawler/judge, live associations, live embeddings, and real flush/rolling-window construction.

## Gold pollution
Any exposure of gold answer text, gold evidence IDs, expected `dia_id`s, scoring labels, or scoring-only metadata to retrieval, agent prompts, tools, memory writes, or answer generation before scoring.

---

# Functional Requirements and Acceptance Criteria

## 1. Seed splits LoCoMo corpus into turns with stable IDs

### Requirement
The seed path must break selected LoCoMo samples into individual turns before they enter Core Memory. Each turn must carry stable provenance IDs for scoring after QA completes.

### Implementation expectations
- Use existing LoCoMo loader/normalizer where possible.
- Each turn must include:
  - `sample_id`
  - LoCoMo `dia_id`
  - stable Core Memory `turn_id`
  - session index/window identifier
  - turn index
  - speaker
  - timestamp/session date when available
- `dia_id` provenance must be stored in metadata/source references in a way hydration/scoring can recover later.

### Acceptance criteria
- Given one selected sample, seed preparation emits one normalized turn per LoCoMo dialogue turn.
- Every emitted turn has a non-empty stable `turn_id` and original `dia_id`.
- Turn IDs are unique across samples even when `dia_id`s repeat.
- The same input corpus produces the same `turn_id`/`dia_id` mapping across runs.
- No QA gold answer/evidence fields are included in seed-turn metadata supplied to Core Memory.
- Unit test proves duplicate `dia_id`s from different samples do not collide.
- Unit test proves missing/empty LoCoMo turn text fails with a clear validation error instead of silently creating junk memory.

---

## 2. Seed writes beads turn by turn through Core Memory runtime

### Requirement
Each LoCoMo turn must be finalized through the real Core Memory runtime path, one turn at a time. Official seeding must not write direct synthetic evidence beads as a substitute for runtime-authored beads.

### Implementation expectations
- Use `process_turn_finalized` or the same wrapper used by live demo turn finalization.
- Do not bypass runtime bead authoring with hand-written LoCoMo bead files.
- Maintain per-turn transaction/trace IDs for diagnostics.
- Record per-turn results, latency, bead IDs, and errors.

### Acceptance criteria
- For N selected corpus turns, official seed invokes the runtime finalized-turn path exactly N times.
- Each finalized-turn invocation has the expected `session_id`, `turn_id`, transaction ID, trace ID, origin, and LoCoMo provenance metadata.
- Official seed does not call direct deterministic LoCoMo evidence-bead writers.
- Official seed fails if any turn finalization returns `ok=false`.
- Official seed report includes per-turn success/failure diagnostics.
- A test with a mocked finalizer verifies one call per turn and failure on partial turn errors.
- A test verifies no official seed metadata contains deterministic `crawler_updates` from `locomo_turn_crawler`.

---

## 3. Seed runs the LLM-powered crawler/judge per turn

### Requirement
For every seeded turn, the LLM-powered crawler/judge must run as the authoring authority. The dumb deterministic LoCoMo crawler must not be used in official paths.

### Implementation expectations
- Apply request-scoped LLM bead/crawler/judge directive per turn, e.g. `bead_judge=llm` or successor API.
- Remove official dependency on `locomo_turn_crawler.py`.
- If `locomo_turn_crawler.py` remains, it must be isolated to smoke/test-only code.
- Disable structural/deterministic fallback for official runs.

### Acceptance criteria
- Official seed metadata contains the LLM-authoring directive for every turn.
- Official seed never imports or calls `locomo_turn_crawler_callable`.
- If the LLM authoring path is unavailable, official seed hard-fails before reporting success.
- Seeded beads include evidence that they were LLM/judge-authored, through metadata, tags, diagnostics, or runtime result fields.
- Test proves official seed path omits deterministic `crawler_updates` and sets the LLM directive.
- Test proves product/UI benchmark route cannot request `enrich_mode=deterministic` for official LoCoMo.
- Test proves deterministic crawler remains accessible only from explicitly named smoke/test helpers, if kept at all.

---

## 4. Crawler/judge sees session window and builds associations/labels per turn

### Requirement
For every new turn/bead, the LLM-powered crawler/judge must receive enough session-window context to apply labels, fields, and associations across all relevant beads in the current rolling/session window.

### Implementation expectations
- The crawler/judge should see all beads in the active session window that production would expose.
- Association writing must happen incrementally as the corpus grows.
- Labels/fields/associations should be applied to all eligible beads, not only the newest bead, when the crawler/judge determines they apply.
- Association outputs must be persisted in the graph/association store used by retrieval.

### Acceptance criteria
- For each turn after the first, crawler/judge diagnostics show the available session-window bead count or equivalent context evidence.
- Associations can be created involving the newest bead and prior session-window beads.
- A seeded multi-turn sample produces non-zero associations unless the LLM explicitly returns none with a valid reason.
- Association pass failures hard-fail official seed.
- A test with mocked crawler/judge output proves associations between current and prior beads are persisted.
- A test proves labels/metadata updates can apply to prior session-window beads, not only the newest bead.
- Seed report includes association counts per turn and final association totals.

---

## 5. Seed performs final crawler/association drain after all turns

### Requirement
After all selected turns are seeded, the system must run one final crawler/association/drain pass so the complete seeded corpus has a final opportunity to link and label across the full seeded session/corpus state allowed by production rules.

### Implementation expectations
- Drain any async crawler/association/side-effect queues.
- Sync graph backend if retrieval uses a separate graph backend.
- Report final queue state.

### Acceptance criteria
- Official seed does not complete while crawler/association/side-effect queues remain pending.
- Official seed report includes final drain status, queue depths, and graph sync status.
- If final drain fails or times out, official seed status is failed.
- If graph sync is required and fails, official seed status is failed.
- Test proves a pending queue causes seed to wait/drain before success.
- Test proves drain failure prevents benchmark eligibility.

---

## 6. Seed runs `process_flush` to construct rolling window

### Requirement
After all turns are seeded and the final crawler/association drain completes, the seed flow must run the real Core Memory `process_flush` flow to construct the rolling window from the bead store.

### Implementation expectations
- Use the same `process_flush` runtime path as production.
- Flush must run after all selected turns are ingested, not before benchmark QA.
- Flush metadata must identify LoCoMo seed and selected sample(s).
- Flush output must be recorded and used as benchmark eligibility evidence.

### Acceptance criteria
- Official seed invokes `process_flush` at least once after final turn ingestion and final association drain.
- Official seed fails if `process_flush` returns failure.
- Official seed report contains flush transaction ID, session ID(s), promoted/rolling-window count or equivalent output, and flush status.
- Benchmark cannot start unless the selected seeded corpus has a successful flush record.
- Test proves benchmark start fails for seeded-but-unflushed corpus.
- Test proves benchmark start succeeds only when seed status includes successful flush/rolling-window construction.

---

## 7. Seed verifies semantic/vector health at production fidelity

### Requirement
Official seed must verify the semantic backend is truly usable and production-fidelity before allowing benchmark QA.

### Implementation expectations
- Hard require Qdrant backend.
- Hard require external OpenAI embeddings.
- Hard require `text-embedding-3-large` and 3072-dimensional vectors.
- Hard require semantic mode `required`.
- Hard require semantic manifest `semantic_ready=true`.
- Hard fail on lexical/hash/FastEmbed/degraded fallback.

### Acceptance criteria
- Seed fails if semantic backend is lexical, hash, FastEmbed, missing, or degraded.
- Seed fails if manifest dimension is not 3072.
- Seed fails if embeddings model is absent or not exactly `text-embedding-3-large`.
- Seed fails if `semantic_ready=false` or `last_build_error` is non-empty.
- `/demo/runtime` reports `usable_backend=false` and the actual error when degraded.
- UI/API surfaces a loud semantic degraded signal when degraded.
- Tests cover degraded manifest, wrong dimension, wrong model, lexical fallback, and healthy Qdrant/OpenAI state.

---

## 8. Run Benchmark button requires an already seeded and flushed corpus

### Requirement
The benchmark button must not seed. It must run QA only against an already seeded, finalized, flushed, semantic-ready corpus.

### Implementation expectations
- Benchmark request resolves selected sample(s).
- Before starting QA, check seed eligibility record for those sample(s).
- Required eligibility:
  - seed completed
  - all selected turns finalized
  - final crawler/association drain completed
  - process flush completed
  - semantic backend healthy
  - no pending mutation queues that would alter corpus during QA

### Acceptance criteria
- Pressing Run Benchmark without a matching seed record fails with `benchmark_requires_seeded_corpus` or equivalent clear error.
- Pressing Run Benchmark after seed but before flush fails with `benchmark_requires_flushed_corpus` or equivalent clear error.
- Pressing Run Benchmark when async mutation queues are pending fails or waits according to explicit implementation, but must not silently run against moving state.
- Benchmark start response includes the seed record ID/hash it is measuring.
- Benchmark report includes seed provenance and flush provenance.
- Test covers unseeded, seeded-unflushed, degraded, and eligible corpus cases.

---

## 9. Benchmark runs QA one question at a time

### Requirement
Benchmark QA must execute selected questions sequentially, one at a time, against the fixed seeded/flushed corpus.

### Implementation expectations
- No parallel QA execution for official LoCoMo.
- Capture per-QA start/end timestamps and status.
- Stop or mark failed on first hard-fail condition, depending on explicit run policy.

### Acceptance criteria
- For Q selected QA items, report contains Q ordered QA case entries unless a hard-fail aborts the run.
- QA case `n+1` does not start before QA case `n` completes.
- Run progress reports current QA index and total selected QA count.
- Test proves sequential execution order using mocked QA runner.

---

## 10. Benchmark invokes the real PydanticAI agent

### Requirement
Each QA question must be answered by the real PydanticAI agent configured with Core Memory tools. The benchmark must not replace the agent with direct `core_recall`, deterministic search, or synthetic answer generation in official paths.

### Implementation expectations
- Use the same agent creation path as the live demo, or a benchmark-specific wrapper that uses the same PydanticAI tool interfaces and model runtime.
- Agent prompt must instruct the agent to use the Core Memory tools before answering.
- Tool-call transcript must be captured.
- Answer must be the agent's final answer.

### Acceptance criteria
- Official QA path invokes PydanticAI agent for every question.
- Official QA path does not call direct `core_recall` as the answer source.
- Per-QA report includes agent model, prompt/run metadata, tool call transcript, and final answer.
- If the agent fails, benchmark case fails; no extractive/no-op fallback answer is used.
- Test uses a mocked PydanticAI agent to prove invocation and transcript capture.
- Test proves `answer_mode=none` and `answer_mode=extractive` are rejected for official LoCoMo.

---

## 11. Agent uses all three retrieval tool levels before answering

### Requirement
For each QA, the real agent must use all three retrieval levels in series before producing an answer:

1. Semantic vector search.
2. Causal trace/traversal from semantic candidates.
3. Hydration/get-turn/source retrieval for semantic candidates plus traced beads.

The agent may adapt between tool calls, but all three phases must occur.

### Implementation expectations
- Core Memory PydanticAI tools must expose:
  - search
  - trace with configurable/adaptive depth cap
  - hydrate/get-turn source retrieval
- Benchmark prompt/instructions must require series usage.
- Benchmark validator must inspect tool transcript and fail if any required phase is missing.

### Acceptance criteria
- Every successful QA case has at least one semantic search tool call.
- Every successful QA case has at least one causal trace tool call.
- Every successful QA case has at least one hydration/get-turn/source retrieval tool call.
- Hydration input includes both top semantic candidates and traced bead IDs where available.
- Final answer is generated only after required tool calls complete.
- If any phase is missing, the QA case fails with `required_tool_phase_missing`.
- Test proves phase-order validation rejects answer-before-hydration.
- Test proves phase-order validation rejects search-only and search+trace-only runs.

---

## 12. Causal trace supports adaptive capped depth

### Requirement
Core Memory must expose causal trace depth control to the PydanticAI agent. Initial cap is 6 hops unless changed later. The agent does not have to always use exactly 6; it should adapt and stop when enough context is found, but it must be able to go deeper than the historical 2-hop cap.

### Implementation expectations
- Core Memory trace APIs accept request-level max depth/cap.
- PydanticAI trace tool exposes the depth parameter.
- Trace diagnostics report effective depth cap and reached depth.
- Safe absolute max may be enforced to avoid walking entire corpus.

### Acceptance criteria
- Core Memory `trace_request` accepts `max_depth` or equivalent field.
- PydanticAI `trace_memory` tool accepts `max_depth` or equivalent argument.
- Trace diagnostics include requested cap, effective cap, selected/reached depth, and chain counts.
- Default official benchmark cap is 6.
- If engine cannot support requested cap, benchmark report must say the effective cap and fail if below required official cap after this PR is complete.
- Unit tests prove max-depth argument reaches graph traversal backend.
- Unit tests prove PydanticAI tool forwards max-depth argument.

---

## 13. Benchmark prevents gold pollution until scoring

### Requirement
Gold answers and gold evidence are used only after the agent has completed retrieval and answer generation for a QA item.

### Implementation expectations
- QA runner separates public QA input from scoring-only data.
- Agent receives question text and allowed runtime metadata only.
- Agent/tool requests do not receive expected answer, gold evidence IDs, category labels if they imply evidence, or scoring hints.
- Memory writes are disabled during QA or isolated so QA cannot contaminate the seeded corpus.

### Acceptance criteria
- Agent prompt for each QA contains no gold answer text.
- Agent prompt for each QA contains no gold evidence IDs/dia IDs.
- Tool call inputs contain no gold evidence IDs/dia IDs.
- QA phase writes no benchmark QA beads into the measured corpus before scoring.
- Scoring function receives gold only after agent final answer and tool transcript are complete.
- Test scans captured prompts/tool inputs and fails if gold answer/evidence appears before scoring.
- Test proves QA does not mutate bead store used for subsequent QA retrieval.

---

## 14. Benchmark scoring happens automatically at the end of each QA item and run

### Requirement
After each QA answer completes, scoring runs automatically using gold labels kept out of the retrieval/answer path. Aggregate scoring runs after the selected QA set completes.

### Implementation expectations
- Per-QA scoring computes:
  - answer F1 or configured answer metric
  - evidence recall by `dia_id`
  - whether gold appeared in hydrated context
  - whether gold appeared in final answer/citations where applicable
- Aggregate scoring computes averages and failure summaries.

### Acceptance criteria
- Each completed QA case has per-case answer score and evidence score.
- Run report has aggregate answer score and evidence recall summaries.
- Scoring includes the seed record ID/hash and retrieval transcript ID used.
- If scoring fails, the benchmark run is failed, not reported as successful with missing scores.
- Test proves scoring occurs after answer generation.
- Test proves report fails validation if scores are missing for completed QA cases.

---

## 15. Benchmark includes floor/survival diagnostics

### Requirement
The benchmark report must identify where gold evidence is found or lost through the retrieval pipeline.

### Implementation expectations
For each QA, report:
- Raw Qdrant top-k floor: gold in top 5/10/20.
- Core Memory search result: gold survives search/rerank/filter.
- Trace result: gold added/preserved by causal traversal.
- Hydrated context: gold source turn is in final context.
- Final answer/citations: gold is cited or answer is supported where measurable.

### Acceptance criteria
- Each QA report includes a `survival_trace` or equivalent object with all required stages.
- If raw Qdrant retrieved gold but Core Memory search dropped it, case flags `gold_dropped_after_qdrant`.
- If search had gold but trace/hydration lost it, case flags the specific loss stage.
- If hydrated context had gold but answer missed it, case flags answer-policy/generation failure.
- Aggregate report summarizes drop counts by stage.
- Test proves a synthetic dropped-gold scenario produces the correct flag.

---

## 16. Hard fail on fallbacks and degraded modes

### Requirement
Official LoCoMo seed and benchmark must never silently fall back to heuristic, lexical, hash, FastEmbed, extractive answer, or no-answer modes.

### Implementation expectations
- Startup/preflight validates config.
- Seed validates runtime semantic health.
- Benchmark validates seed health and current runtime health.
- Any fallback path must be either removed or guarded as smoke/test-only.

### Acceptance criteria
- Official run fails when `CLAIM_EXTRACTION_MODE != llm`.
- Official run fails when semantic mode is not `required`.
- Official run fails when embeddings provider/model/backend are not production-fidelity values.
- Official run fails if answer generation falls back to extractive/no-op/fallback answer.
- Official run fails if any retrieval tool reports degraded semantic backend.
- Tests cover each forbidden fallback.

---

## 17. Repo-level config enforcement and manual env reporting

### Requirement
The repo must enforce and document required production-fidelity configuration. After implementation, the assistant must report any manual deployment env changes required.

### Required env/config values
```bash
CORE_MEMORY_VECTOR_BACKEND=qdrant
CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS=1
CORE_MEMORY_EMBEDDINGS_PROVIDER=openai
CORE_MEMORY_EMBEDDINGS_MODEL=text-embedding-3-large
CORE_MEMORY_CANONICAL_SEMANTIC_MODE=required
CORE_MEMORY_CLAIM_LAYER=1
CORE_MEMORY_CLAIM_EXTRACTION_MODE=llm
```

### Acceptance criteria
- Repo contains a single documented source of truth for official LoCoMo env requirements.
- Preflight route/API reports missing/wrong values clearly.
- Official seed/benchmark refuses to run when required values are wrong.
- Final implementation report includes a manual env-change checklist for web and worker services.
- Tests prove wrong env values produce actionable errors.

---

## 18. UI behavior

### Requirement
The UI must reflect the simplified model: seed first, then benchmark QA. No product-facing deterministic/judge toggle should remain for official LoCoMo.

### Implementation expectations
- Remove/retire `enrich_mode` UI control for official LoCoMo.
- Seed UI shows seed status and flush/rolling-window status.
- Run Benchmark button is disabled or fails clearly until seed eligibility is satisfied.
- Runtime health/degraded semantic state is loud.

### Acceptance criteria
- UI has no deterministic/judge dropdown for official LoCoMo benchmark.
- UI shows whether selected sample is seeded, flushed, semantic-ready, and benchmark-eligible.
- Clicking Run Benchmark before eligibility shows a clear reason and does not start a job.
- Clicking Run Benchmark after eligibility starts QA-only benchmark.
- Frontend build passes.
- UI tests or static assertions cover removal of official `enrich_mode` control and display of eligibility state.

---

## 19. Data/report contracts

### Requirement
Seed and benchmark outputs must have explicit, reviewable contracts so missing fields do not silently pass.

### Seed report required fields
- `seed_id` or deterministic seed record key
- selected sample IDs
- selected turn count
- per-turn finalized results
- LLM/judge authoring status
- association counts per turn and final totals
- final drain status
- flush status and flush transaction ID
- semantic manifest/backend health
- eligibility boolean and failure reasons

### Benchmark report required fields
- benchmark run ID
- referenced seed ID/key
- selected QA IDs/count
- per-QA tool transcript
- per-QA final answer
- per-QA scoring
- per-QA survival trace
- aggregate scores
- hard-fail/degraded warnings, if any

### Acceptance criteria
- Seed report validation fails if any required field is missing.
- Benchmark report validation fails if any required field is missing.
- Existing durable benchmark storage persists these reports or stores artifact references.
- Tests validate minimal valid reports and invalid missing-field reports.

---

## 20. Cleanup and retirement

### Requirement
Old forked behavior must be removed or explicitly fenced so it cannot be mistaken for official benchmark behavior.

### Items to remove/retire from official paths
- `locomo_turn_crawler.py` deterministic crawler.
- `enrich_mode` deterministic/judge toggle.
- `_assert_judge_engaged` fail-closed guard, once LLM authoring is the only path.
- Effort-tier benchmark loop as official QA mechanism.
- `MULTI_HOP_RETRIEVAL_K` hack as official retrieval mechanism.
- QA bead writes during benchmark QA.
- Direct `core_recall` as official answer source.

### Acceptance criteria
- Grep/static tests prove official LoCoMo path does not import/use deterministic crawler.
- Grep/static tests prove official product UI does not expose `enrich_mode`.
- Official benchmark report no longer reports deterministic/judge mode as a runtime choice.
- Any remaining old code is marked smoke/test-only and unreachable from product routes.
- Tests using old official behavior are updated or deleted.

---

# Implementation Plan

## Phase 1: Core Memory trace-depth support
- Add request-level trace depth/cap to Core Memory trace APIs.
- Expose depth through PydanticAI `trace_memory` tool.
- Add diagnostics and tests.
- Open/merge Core Memory PR.
- Update demo Core Memory pin.

## Phase 2: Demo seed rewrite
- Refactor LoCoMo seed to official production-fidelity flow.
- Remove deterministic crawler from official seed.
- Add final drain + flush eligibility record.
- Add semantic/config preflight.
- Add tests.

## Phase 3: Demo benchmark QA rewrite
- Run only against eligible seed.
- Invoke real PydanticAI agent per QA.
- Validate required tool phases.
- Prevent gold pollution.
- Score after answer.
- Add report contract and diagnostics.

## Phase 4: UI and route cleanup
- Remove official `enrich_mode` toggle.
- Add seed/flush/semantic eligibility status.
- Ensure Run Benchmark is QA-only.
- Add health banner for degraded semantic state.

## Phase 5: Verification and deployment report
- Run backend tests.
- Run frontend build.
- Run smoke-only CI tests.
- Run at least one small official LoCoMo seed+QA validation if credentials/env allow.
- Report manual env changes required for web and worker.

---

# Completion Definition

This project is complete only when all are true:

1. Official seed path is production-fidelity and LLM-powered.
2. Official seed path writes turns one by one, runs crawler/associations, drains, flushes, and records eligibility.
3. Official benchmark path refuses unseeded/unflushed/degraded corpora.
4. Official benchmark QA invokes the real PydanticAI agent and required Core Memory tools.
5. Gold evidence is inaccessible until scoring.
6. Reports include required seed/benchmark fields and survival diagnostics.
7. Deterministic/fallback behavior is impossible in official product paths.
8. Tests and build pass.
9. Manual deployment env changes are reported.
10. No item above is left as TODO, partial, or undocumented exception.
