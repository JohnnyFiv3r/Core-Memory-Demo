# Adapter-only integration research

Status: research checkpoint on `feat/adapter-only-rebuild`

## Scope

This document maps the real integration seams between:
- the demo app in `core-memory-demo`
- the library/runtime in `Core-Memory`

Goal: rebuild from this reset point using an adapter-only architecture, where the demo owns app wiring and benchmarking UX, while `Core-Memory` remains the canonical owner of turn finalization, session start, flush, continuity, retrieval, and async job semantics.

This is intentionally research-first. It documents exact hooks, current behavior, ownership boundaries, and the safest adapter insertion points before any behavior changes.

---

## Repositories and ownership split

### Demo app
Repo: `/home/node/.openclaw/workspace/core-memory-demo`

Primary surfaces inspected:
- `backend/app/main.py`
- `backend/app/routes/demo.py`
- `backend/app/routes/inspect.py`
- `backend/app/core/runtime.py`
- `backend/app/core/config.py`
- `frontend/src/api.ts`
- `frontend/src/App.tsx`

### Core runtime library
Repo: `/home/node/.openclaw/workspace/Core-Memory`

Primary surfaces inspected:
- `core_memory/runtime/engine.py`
- `core_memory/runtime/turn_flow.py`
- `core_memory/runtime/ingress.py`
- `core_memory/runtime/worker.py`
- `core_memory/runtime/agent_crawler_invoke.py`
- `core_memory/runtime/association_pass.py`
- `core_memory/runtime/session_start_flow.py`
- `core_memory/runtime/session_surface.py`
- `core_memory/runtime/jobs.py`
- `core_memory/runtime/agent_authored_contract.py`
- `core_memory/association/crawler_contract.py`
- `core_memory/write_pipeline/continuity_injection.py`
- `core_memory/integrations/pydanticai/memory_tools.py`
- `core_memory/integrations/pydanticai/run.py`
- `core_memory/integrations/api.py`
- `core_memory/retrieval/tools/memory.py`

---

## Executive summary

The real adapter-only seam already exists.

The demo backend currently calls directly into the canonical `Core-Memory` runtime boundaries instead of reimplementing them. The important architecture fact is that the canonical write path is not the demo route layer and not the PydanticAI adapter wrapper by itself. The canonical write path is:

1. demo runtime gathers request/session state
2. demo agent run completes
3. demo calls `core_memory.integrations.pydanticai.run.run_with_memory(...)` or directly calls canonical engine hooks
4. `Core-Memory` executes the runtime-owned turn boundary:
   - `process_turn_finalized(...)`
   - `process_turn_finalized_impl(...)`
   - `maybe_emit_finalize_memory_event(...)`
   - `process_memory_event(...)`
   - `invoke_turn_crawler_agent(...)`
   - `run_association_pass(...)`
5. async queues and continuity state are observed separately via canonical runtime helpers

The correct rebuild path is therefore:
- keep demo logic thin
- do not recreate alternate finalize or association semantics in demo code
- wire demo-specific agent/crawler/benchmark behavior as adapters around these canonical boundaries
- preserve `Core-Memory` as source of truth for write/read/session-start/flush state transitions

---

## Actual demo app surface at this reset point

### Important note on benchmark files at this commit

At this rollback point (`core-memory-demo` HEAD `8d4253a`), the source tree under `backend/app/benchmarks/` currently contains only `__pycache__` entries and no checked-in `.py` benchmark source files.

Observed current file state:
- `backend/app/benchmarks/__pycache__/fixture_smoke.cpython-311.pyc`
- `backend/app/benchmarks/__pycache__/locomo_answer.cpython-311.pyc`
- `backend/app/benchmarks/__pycache__/locomo_ingest.cpython-311.pyc`
- `backend/app/benchmarks/__pycache__/locomo_loader.cpython-311.pyc`
- `backend/app/benchmarks/__pycache__/locomo_runner.cpython-311.pyc`
- `backend/app/benchmarks/__pycache__/locomo_scoring.cpython-311.pyc`
- `backend/app/benchmarks/__pycache__/locomo_suite.cpython-311.pyc`

So the earlier names are still useful as historical seam hints, but they are not available to inspect as current source in this branch tip. That means benchmark/LoCoMo adapter documentation below is limited to:
- routes and runtime entrypoints that still reference benchmark operations
- naming evidence from cached modules
- required adapter shape implied by route contracts

This matters because the rebuild should not assume those previous benchmark implementation files still exist.

---

## Demo backend wiring

### `backend/app/main.py`

Role:
- FastAPI assembly root
- background async-job ticker owner for demo process
- fallback wrapper for inspect/state endpoints

Important integration points:
- imports `run_async_jobs` from `core_memory.runtime.jobs`
- mounts:
  - demo public routes
  - demo admin routes
  - inspect routes
- starts a background thread that periodically calls:
  - `run_async_jobs(root=settings.core_memory_root, ...)`

This is a key adapter seam.

Meaning:
- demo app is not implementing its own queue semantics
- demo app is only scheduling canonical queue draining from `Core-Memory`
- adapter-only rebuild should preserve this pattern: demo owns process scheduling, `Core-Memory` owns queue meaning

Exact hook:
- `backend/app/main.py::_async_jobs_tick_loop()`
- calls `core_memory.runtime.jobs.run_async_jobs(...)`

Implication:
- benchmark or chat adapters should enqueue canonical work or rely on canonical queue state, not invent separate background maintenance semantics

### `backend/app/routes/demo.py`

Role:
- HTTP contract for demo operations
- thin request parsing and response shaping over `app.core.runtime`

Important imported runtime entrypoints from demo runtime:
- `run_chat`
- `run_flush`
- `reset_test_session`
- `seed_demo_history`
- `replay_story_pack`
- `run_benchmark`
- `inspect_state_payload`
- `inspect_bead_payload`
- `inspect_bead_hydration_payload`
- `inspect_claim_slot_payload`
- `inspect_turns_payload`
- `get_story_pack_meta`
- `list_demo_model_options`
- `set_demo_model_override`
- benchmark comparison/history helpers

Important HTTP surfaces:
- `GET /api/demo/state`
- `GET /api/demo/claims`
- `GET /api/demo/entities`
- `GET /api/demo/runtime`
- `GET /api/demo/models`
- `POST /api/demo/model`
- `GET /api/demo/bead/{bead_id}`
- `GET /api/demo/bead/{bead_id}/hydrate`
- `GET /api/demo/claim-slot/{subject}/{slot}`
- `GET /api/demo/turns`
- `POST /api/chat/start`
- `GET /api/chat/status/{job_id}`
- `POST /api/chat`
- `POST /api/flush`
- `POST /api/session/reset`
- `POST /api/seed`
- `GET /api/story-pack/meta`
- `POST /api/story-pack/replay`
- `POST /api/benchmark-run`
- `GET /api/demo/benchmark/last`
- `GET /api/demo/benchmark/history`
- `GET /api/demo/benchmark/compare/{left_run_id}/{right_run_id}`
- merge suggestion/decision endpoints

Architecture note:
- route layer is mostly transport only
- the real adapter decisions belong in `backend/app/core/runtime.py`

### `backend/app/routes/inspect.py`

Role:
- exposes a second inspect namespace:
  - `/v1/memory/inspect/*`

These endpoints are thin wrappers around demo runtime inspect helpers, which in turn call canonical `Core-Memory` inspect APIs.

This is an important read-path adapter seam because it means:
- UI is not reading raw files
- UI is already talking to a stable inspect surface
- rebuild should keep adapter-owned read APIs on top of canonical inspect helpers

### `backend/app/core/config.py`

Role:
- demo config surface
- selects roots and runtime tick behavior

Key fields tied to adapter behavior:
- `core_memory_root`
- `core_memory_demo_benchmark_root`
- `core_memory_demo_artifacts_root`
- `demo_model_id`
- `demo_context_budget`
- `async_jobs_tick_enabled`
- `async_jobs_tick_interval_seconds`
- `async_jobs_tick_max_compaction`
- `async_jobs_tick_max_side_effects`
- `async_jobs_tick_run_semantic`
- `demo_chat_sync_semantic_on_write`

Interpretation:
- root selection and operational policy belong in demo config
- memory semantics still belong in `Core-Memory`

---

## Demo runtime integration map

File: `backend/app/core/runtime.py`

This is the main adapter surface in the demo app.

### What it owns

Demo runtime owns:
- demo session id lifecycle (`SESSION.session_id`)
- model choice and model override UX
- story pack loading/replay logic
- demo-only diagnostics payload composition
- route-facing payload projection for current UI
- direct use of PydanticAI agent wrapper
- optional demo heuristics like token estimates and retrieval spike timestamps

### What it does not own semantically

It does not own canonical memory semantics for:
- turn finalization
- session start continuity boundary
- flush boundary
- continuity authority order
- retrieval contract execution
- async queue status/drain semantics
- association append/merge semantics
- agent-authored update validation rules

Those belong to `Core-Memory`.

### Core imports proving canonical ownership

`backend/app/core/runtime.py` imports these directly from `Core-Memory`:
- `core_memory.integrations.api.get_turn`
- `core_memory.integrations.api.inspect_bead`
- `core_memory.integrations.api.inspect_bead_hydration`
- `core_memory.integrations.api.inspect_claim_slot`
- `core_memory.integrations.api.inspect_state`
- `core_memory.integrations.api.list_turn_summaries`
- `core_memory.integrations.pydanticai.memory_tools.continuity_prompt`
- `core_memory.integrations.pydanticai.memory_tools.memory_execute_tool`
- `core_memory.integrations.pydanticai.memory_tools.memory_search_tool`
- `core_memory.integrations.pydanticai.memory_tools.memory_trace_tool`
- `core_memory.integrations.pydanticai.run.run_with_memory`
- `core_memory.retrieval.tools.memory` as canonical retrieval facade
- `core_memory.persistence.store.MemoryStore`
- `core_memory.persistence.store_claim_ops.write_claim_updates_to_bead`
- `core_memory.persistence.store_claim_ops.write_claims_to_bead`
- `core_memory.runtime.engine.process_flush`
- `core_memory.runtime.engine.process_turn_finalized`
- `core_memory.runtime.jobs.async_jobs_status`
- `core_memory.runtime.jobs.run_async_jobs`
- `core_memory.runtime.association_pass.run_association_pass`
- `core_memory.association.crawler_contract.merge_crawler_updates`
- `core_memory.write_pipeline.continuity_injection.load_continuity_injection`

That import set is the clearest proof that the rebuild should be adapter-only, not a semantics fork.

### Agent construction seam

Function:
- `create_agent(model_id: str)`

Behavior:
- creates a PydanticAI `Agent`
- injects canonical memory tools:
  - `memory_execute_tool(root=settings.core_memory_root)`
  - `memory_search_tool(root=settings.core_memory_root)`
  - `memory_trace_tool(root=settings.core_memory_root)`
- injects continuity prompt via:
  - `continuity_prompt(root=settings.core_memory_root, session_id=SESSION.session_id)`

Meaning:
- read-path integration is already adapter-owned but canonical-tool-backed
- session-start continuity can be triggered implicitly from the prompt helper
- demo should keep this shape, but any adapter cleanup should make the boundary explicit and unsurprising

### Inspect payload seam

Function:
- `inspect_state_payload(...)`

Behavior:
- calls canonical `inspect_state(...)`
- supplements result with demo session metadata
- separately reads continuity through `load_continuity_injection(...)`
- projects backward-compatible UI fields like `beads`, `associations`, `rolling_window`, `claim_state`, `stats`

Meaning:
- inspect payload is an adapter projection layer over canonical state
- safe rebuild rule: preserve projection compatibility while avoiding new state authority in demo

---

## Canonical write-path hooks in `Core-Memory`

### 1. Engine entrypoint: `process_turn_finalized(...)`

File:
- `core_memory/runtime/engine.py`

Function:
- `process_turn_finalized(...)`

Role:
- stable canonical turn-finalized boundary
- delegates implementation to `process_turn_finalized_impl(...)`
- wires all required collaborators into the implementation function

This is a crucial architecture seam because the implementation is dependency-injected by function arguments. That makes it explicit what the canonical pipeline depends on.

Injected collaborators include:
- `normalize_turn_request`
- `mark_turn_checkpoint`
- `maybe_emit_finalize_memory_event`
- `build_crawler_context`
- `invoke_turn_crawler_agent`
- `resolve_reviewed_updates`
- `emit_agent_turn_quality_metric`
- `session_visible_bead_ids`
- `non_temporal_semantic_association_count`
- `agent_min_semantic_associations_after_first`
- `try_claim_memory_pass`
- `mark_memory_pass`
- `process_memory_event`
- `default_crawler_updates`
- `ensure_turn_creation_update`
- `run_association_pass`
- `queue_preview_associations`
- `merge_crawler_updates`
- `run_session_decision_pass`
- claim-layer optional hooks

Adapter implication:
- adapters should call this engine boundary, not attempt to manually sequence these internals themselves

### 2. Turn flow implementation: `process_turn_finalized_impl(...)`

File:
- `core_memory/runtime/turn_flow.py`

Role:
- canonical in-process write pipeline

Observed sequence:
1. normalize request
2. mark turn checkpoint
3. emit normalized finalized-turn event via `maybe_emit_finalize_memory_event(...)`
4. attempt claim pass reservation via `try_claim_memory_pass(...)`
5. execute mechanical worker pass via `process_memory_event(...)`
6. build crawler context from post-write session state
7. invoke agent-authored crawler callable via `invoke_turn_crawler_agent(...)`
8. resolve and gate reviewed updates
9. ensure canonical bead creation row exists
10. rebuild crawler context again from post-write state
11. enforce semantic coverage gate on non-initial turns
12. run runtime-owned association pass
13. queue preview associations / merge updates / run decision passes downstream

This is the actual source of truth for write orchestration.

Adapter-only rule:
- demo code may prepare metadata and choose the crawler callable, but should not fork this sequence

### 3. Event ingress: `maybe_emit_finalize_memory_event(...)`

File:
- `core_memory/runtime/ingress.py`

Role:
- canonical event emission normalizer and idempotency gate for top-level finalized turns

Important behavior:
- skips emission when `trace_depth != 0`
- skips emission when `origin == MEMORY_PASS`
- normalizes tool trace and mesh trace
- optionally stores full assistant text or redacted reference depending on metadata/env
- hashes envelope
- uses prior memory-pass state for idempotency and mutation handling
- writes event and returns payload containing event + envelope

Important adapter consequence:
- external/demo adapters should not write ad hoc event rows
- they should call this hook indirectly through engine or directly through stable integration API only

### 4. Mechanical event worker: `process_memory_event(...)`

File:
- `core_memory/runtime/worker.py`

Role:
- canonical bookkeeping executor for finalized-turn events
- explicitly mechanical only, not semantic authority

Current observed behavior:
- marks memory pass done
- appends runtime metric through `MemoryStore`
- does not decide semantic associations itself

Architecture significance:
- this confirms that semantic authority is intentionally separate from event bookkeeping
- the semantic layer is the crawler-reviewed association flow, not this worker

### 5. Agent crawler invocation seam: `invoke_turn_crawler_agent(...)`

File:
- `core_memory/runtime/agent_crawler_invoke.py`

Role:
- adapter-callable invocation seam for turn-time semantic updates

Callable contract:
- env var: `CORE_MEMORY_AGENT_CRAWLER_CALLABLE="module.submodule:function"`
- receives payload:
  - `root`
  - `request`
  - `crawler_context`
- may return either:
  - updates dict directly, or
  - `{ "crawler_updates": updates_dict }`

Behavior:
- if metadata already contains `crawler_updates`, uses that and does not invoke callable
- decides whether invocation should happen based on flags/env
- retries up to configured max attempts
- returns `(updates_or_none, diag)`

Adapter implication:
- this is the primary adapter-owned semantic write seam
- the rebuild should plug benchmark/demo/LoCoMo-specific generation logic into this callable contract, not into engine internals

### 6. Agent-authored contract gate: `validate_agent_authored_updates(...)`

File:
- `core_memory/runtime/agent_authored_contract.py`

Error codes:
- `ERROR_AGENT_UPDATES_MISSING`
- `ERROR_AGENT_UPDATES_INVALID`
- `ERROR_AGENT_ASSOCIATIONS_MISSING`
- `ERROR_AGENT_BEAD_FIELDS_MISSING`
- `ERROR_AGENT_INVOCATION_EXHAUSTED`
- `ERROR_AGENT_CALLABLE_MISSING`
- `ERROR_AGENT_SEMANTIC_COVERAGE_MISSING`

Current contract requirements:
- `beads_create` must be a list of exactly one row
- required bead fields:
  - `type`
  - `title`
  - `summary`
- `associations` must be present and non-empty
- each association requires:
  - `source_bead_id` or `source_bead`
  - `target_bead_id` or `target_bead`
  - `relationship`
  - `reason_text`
  - `confidence` in `[0,1]`

Adapter implication:
- adapters generating crawler updates must emit this shape exactly
- any demo benchmark harness or LoCoMo replay generator should be treated as producer of this contract, not as direct store mutator

### 7. Runtime-owned association pass: `run_association_pass(...)`

File:
- `core_memory/runtime/association_pass.py`

Role:
- orchestration owner wrapper
- delegates to `core_memory.association.crawler_contract.apply_crawler_updates(...)`

Why it matters:
- adapter code should call runtime association entrypoints, not storage helpers directly

### 8. Association application contract: `apply_crawler_updates(...)`

File:
- `core_memory/association/crawler_contract.py`

This file is a major semantic contract surface.

Observed responsibilities:
- normalize reviewed rows
- normalize creation rows
- construct crawler context from session surface
- define writing contract and append-only rules
- merge crawler side logs into index projection
- validate and quarantine bad association payloads
- enforce session-local source/target scope
- append association rows using canonical dedupe/inference checks

Important helper seams:
- `_normalize_review_rows(...)`
- `_normalize_creation_rows(...)`
- `build_crawler_context(...)`
- `merge_crawler_updates(...)`

Important design facts:
- session surface is read through `read_session_surface(...)`
- source must be a session-local bead
- target must be visible in the session surface set
- semantic append semantics are append-only
- uncertainty belongs in confidence fields, not invented relation names

Adapter implication:
- semantic producers can be demo-specific
- semantic application rules must remain canonical here

---

## Canonical session-start and continuity seams

### 1. Explicit session-start boundary: `process_session_start(...)`

File:
- `core_memory/runtime/engine.py`
- delegates to `core_memory/runtime/session_start_flow.py::process_session_start_impl(...)`

Role:
- canonical session-start lifecycle hook

### 2. Session-start implementation: `process_session_start_impl(...)`

Behavior:
- checks for existing `session_start` bead for session
- if present, returns existing bead and does not duplicate
- otherwise loads continuity injection state
- builds a session-start snapshot bead
- writes that bead via `MemoryStore.add_bead(...)`

Important design:
- session-start creation is explicit and idempotent
- it is not hidden inside the read-only continuity loader

### 3. Continuity loader: `load_continuity_injection(...)`

File:
- `core_memory/write_pipeline/continuity_injection.py`

Canonical authority order:
1. `rolling-window.records.json`
2. `promoted-context.meta.json`
3. empty

Explicitly not an authority surface:
- `promoted-context.md`

Important note in code:
- function is read-only by design
- `session_id` and `ensure_session_start` params are retained only for adapter compatibility
- session-start creation is intentionally not performed there

Adapter implication:
- rebuild should not smuggle writes into continuity reads
- if demo wants guaranteed session-start behavior, call explicit session-start boundary

### 4. PydanticAI continuity helper: `ensure_session_start_boundary(...)`

File:
- `core_memory/integrations/pydanticai/memory_tools.py`

Role:
- adapter-owned convenience wrapper over canonical `process_session_start(...)`

Used by:
- `continuity_prompt(...)`

Behavior:
- if `ensure_session_start=True` and `session_id` is present, continuity prompt tries to create session-start boundary first
- then loads continuity injection in read-only mode

Adapter implication:
- this helper is the current read-path convenience seam
- rebuild can either keep this implicit behavior or make session-start explicit in demo runtime before agent execution
- either option should still route through `process_session_start(...)`

---

## Canonical read-path seams

### 1. PydanticAI memory tools

File:
- `core_memory/integrations/pydanticai/memory_tools.py`

Exposed adapter factories:
- `continuity_prompt(...)`
- `memory_search_tool(...)`
- `memory_trace_tool(...)`
- `memory_execute_tool(...)`
- hydration helpers like `get_turn_tool(...)`

Ownership model:
- `Core-Memory` provides tool factories
- caller owns actual agent wiring
- retrieval execution remains canonical inside the retrieval package

### 2. Unified retrieval facade

File:
- `core_memory/retrieval/tools/memory.py`

Canonical public functions:
- `search(...)`
- `trace(...)`
- `execute(...)`

Contracts:
- `search` returns `memory_search_result.v1`
- `execute` and `trace` return `memory_execute_result.v1`
- `execute` can be disabled via env flags
- causal execute intent can be independently disabled

Adapter implication:
- adapters should call this facade, not internal retrieval pipeline pieces directly, unless intentionally extending the retrieval engine itself

### 3. Stable integration read API

File:
- `core_memory/integrations/api.py`

Important functions:
- `_resolve_root(...)`
- `emit_turn_finalized(...)`
- `emit_turn_finalized_from_envelope(...)`
- `get_turn(...)`
- `get_turn_tools(...)`
- `get_adjacent_turns(...)`
- `hydrate_bead_sources(...)`

Why this matters:
- this file is the stable external integration port for adapters and orchestration layers
- transcript hydration should go through here
- demo inspect surfaces should stay layered on this API instead of reading storage directly

### 4. Session live surface

File:
- `core_memory/runtime/session_surface.py`

Function:
- `read_session_surface(root, session_id)`

Role:
- reads append-only `session-{session_id}.jsonl`
- described as groundwork for session-authority cutover

Implication:
- crawler context and association logic already prefer a session-authoritative surface rather than only index projection
- adapter rebuild should not bypass this by constructing fake visible-state models elsewhere

---

## Canonical async and flush seams

### 1. Flush boundary

File:
- `core_memory/runtime/engine.py`
- `core_memory/integrations/pydanticai/run.py`

Entry points:
- `process_flush(...)`
- `flush_session(...)`
- `flush_session_async(...)`

Ownership:
- adapter decides when flush occurs
- `Core-Memory` decides what flush means

### 2. Async queue observability and draining

File:
- `core_memory/runtime/jobs.py`

Important functions:
- `async_jobs_status(...)`
- `run_async_jobs(...)`
- `enqueue_async_job(...)`
- queue-specific helpers for semantic rebuild, compaction, side effects

Meaning:
- demo can inspect and tick canonical queues
- demo should not create parallel queue formats for the same concepts

### 3. Demo process integration

`backend/app/main.py` background thread is already the demo-side process adapter for `run_async_jobs(...)`.

This is the correct ownership split.

---

## PydanticAI adapter write seam

File:
- `core_memory/integrations/pydanticai/run.py`

Important functions:
- `run_with_memory(...)`
- `run_with_memory_sync(...)`
- `flush_session(...)`
- `flush_session_async(...)`

Observed `run_with_memory(...)` sequence:
1. resolve root and turn id
2. execute agent `run(...)`
3. extract assistant final text
4. if core memory disabled, stop there
5. build adapter metadata including:
   - `framework=pydanticai`
   - `adapter_kind=native`
   - `adapter_runtime=pydanticai`
   - `adapter_status=production_ready`
   - `fail_open=True`
   - runtime flags snapshot
6. call canonical turn pipeline via `_run_turn_pipeline(...)`
7. `_run_turn_pipeline(...)` calls `process_turn_finalized(...)`
8. failures are fail-open and do not break the agent result

Adapter implication:
- this is already the proper adapter-only write wrapper for normal PydanticAI turns
- demo-specific rebuild should extend metadata/crawler callable wiring, not replace this wrapper

---

## Frontend surfaces

### `frontend/src/api.ts`

Current frontend contract depends on:
- inspect endpoints
- runtime endpoint
- entities endpoint
- benchmark endpoint
- chat endpoint
- seed endpoint
- flush endpoint

This means adapter-only rebuild should preserve route-level response compatibility where practical.

### `frontend/src/App.tsx`

Current app simply redirects to `chat.html` or `graph.html` with `api_base` and `ui_rev` params.

Meaning:
- frontend root is not the architectural concern here
- backend contract stability matters more than root React app logic

---

## Benchmark and LoCoMo seams at this reset point

Because benchmark source files are missing in this branch tip, only the remaining route/runtime contracts can be documented with certainty.

### What still exists

Routes still expose:
- `POST /api/benchmark-run`
- `GET /api/demo/benchmark/last`
- `GET /api/demo/benchmark/history`
- `GET /api/demo/benchmark/compare/{left_run_id}/{right_run_id}`
- `POST /api/story-pack/replay`
- `GET /api/story-pack/meta`

Demo runtime still imports and exposes benchmark-related names:
- `run_benchmark(...)`
- `compare_benchmark_runs(...)`
- `get_last_benchmark_snapshot(...)`
- `read_benchmark_history(...)`
- `replay_story_pack(...)`
- story-pack manifest loader helpers

### What the missing benchmark files imply

The cached module names strongly suggest a former benchmark decomposition:
- `fixture_smoke`
- `locomo_answer`
- `locomo_ingest`
- `locomo_loader`
- `locomo_runner`
- `locomo_scoring`
- `locomo_suite`

But because source is not present now, the rebuild should not anchor new architecture to those old file boundaries.

### Safe benchmark adapter conclusion

The benchmark/LoCoMo adapter seam should be defined at the runtime boundary level, not at historic file names.

Recommended benchmark adapter responsibilities:
- prepare benchmark session/reset inputs
- feed replay turns or questions through the same canonical chat/turn-finalize path where possible
- if benchmark-specific crawler updates are produced, emit them through the agent crawler callable contract
- collect benchmark scoring/history outside canonical memory semantics

In other words:
- benchmark harness = adapter/orchestrator
- memory write/read semantics = canonical runtime

---

## Exact adapter seams to use in the rebuild

### A. Session start adapter seam

Use:
- `core_memory.runtime.engine.process_session_start(...)`
or adapter wrapper:
- `core_memory.integrations.pydanticai.memory_tools.ensure_session_start_boundary(...)`

Do not:
- create session-start beads manually in demo code
- hide stateful writes inside continuity loader forks

### B. Turn write adapter seam

Use:
- `core_memory.integrations.pydanticai.run.run_with_memory(...)`
for standard PydanticAI turns
or directly:
- `core_memory.runtime.engine.process_turn_finalized(...)`
for custom orchestration

Do not:
- write direct bead rows from demo route handlers for normal turn finalization
- recreate event emission/idempotency logic in demo code

### C. Agent-authored semantic update seam

Use:
- `CORE_MEMORY_AGENT_CRAWLER_CALLABLE`
- `core_memory.runtime.agent_crawler_invoke.invoke_turn_crawler_agent(...)`
- `core_memory.runtime.agent_authored_contract.validate_agent_authored_updates(...)`

Do not:
- mutate associations/promotions directly from demo-specific heuristic code paths
- create a separate non-canonical semantic merge path in the demo

### D. Association application seam

Use:
- `core_memory.runtime.association_pass.run_association_pass(...)`
which delegates to:
- `core_memory.association.crawler_contract.apply_crawler_updates(...)`

Do not:
- append raw association rows to storage from adapter code

### E. Continuity read seam

Use:
- `core_memory.write_pipeline.continuity_injection.load_continuity_injection(...)`
for read-only continuity loading

Respect authority order exactly:
1. `rolling-window.records.json`
2. `promoted-context.meta.json`
3. empty

Do not:
- treat `promoted-context.md` as runtime authority

### F. Retrieval tool seam

Use:
- `core_memory.retrieval.tools.memory.execute(...)`
- `core_memory.retrieval.tools.memory.search(...)`
- `core_memory.retrieval.tools.memory.trace(...)`

or their PydanticAI tool factories in `memory_tools.py`

Do not:
- wire agents straight to internal retrieval pipeline modules unless intentionally extending core retrieval behavior

### G. Inspect/hydration seam

Use:
- `core_memory.integrations.api.*`
- demo runtime projection helpers on top of that

Do not:
- make the frontend read raw storage files

### H. Flush and background jobs seam

Use:
- `core_memory.runtime.engine.process_flush(...)`
- `core_memory.runtime.jobs.async_jobs_status(...)`
- `core_memory.runtime.jobs.run_async_jobs(...)`

Do not:
- invent demo-specific equivalents for compaction/semantic rebuild queue semantics

---

## Adapter-only rebuild design rules derived from research

1. Keep demo runtime as adapter/orchestrator, not semantics owner.
2. Preserve canonical write boundaries in `Core-Memory`.
3. Put benchmark, LoCoMo, and demo-specific semantic generation behind the crawler callable contract.
4. Keep inspect/UI payload shaping in demo code, but keep state authority in canonical inspect/read APIs.
5. Make session-start explicit where practical, but still call canonical boundary helpers.
6. Never elevate `promoted-context.md` to an authority surface.
7. Treat `session-{session_id}.jsonl` session surface as canonical live crawler context input.
8. Respect agent-authored update validation and semantic coverage gates instead of bypassing them for benchmarks.
9. Keep async work observable and drained via canonical runtime job helpers.
10. Rebuild benchmark harnesses around surviving route/runtime contracts, not vanished historical file splits.

---

## Concrete next implementation steps

1. Add a demo-owned crawler adapter module in `core-memory-demo` that implements the callable contract expected by:
   - `CORE_MEMORY_AGENT_CRAWLER_CALLABLE`
2. Ensure demo chat path uses explicit session-start boundary before first turn when appropriate.
3. Audit `backend/app/core/runtime.py` for any direct semantic writes that bypass canonical runtime boundaries.
4. Recreate benchmark/LoCoMo source modules only as thin orchestrators around:
   - canonical turn path
   - canonical retrieval path
   - canonical inspect/history surfaces
5. Keep current route contract stable while swapping internals to adapter-owned wrappers.
6. After wiring, validate with story-pack replay and benchmark endpoints.

---

## Known gaps from this checkpoint

1. The prior benchmark/LoCoMo source files named in earlier inspection are absent in the current rollback commit, so this document cannot map their exact internal functions from checked-in source.
2. `backend/app/core/runtime.py` is large and contains more demo-specific helpers beyond the subset read during this checkpoint. Additional implementation pass should inspect any remaining lower sections before final adapter coding.
3. There may be pycache residue reflecting stale module names. Those names are evidence only, not source of truth.

---

## Bottom line

The adapter-only path is the right path.

The real `Core-Memory` runtime already exposes the boundaries we need:
- `process_session_start(...)`
- `process_turn_finalized(...)`
- `process_flush(...)`
- `load_continuity_injection(...)`
- retrieval tool facades
- inspect/hydration APIs
- async job helpers
- crawler callable and validation contract

So the rebuild should focus on:
- making demo code thinner
- moving demo-specific generation into adapter callables
- restoring benchmark harnesses around canonical boundaries
- avoiding any new semantic fork inside the demo app
