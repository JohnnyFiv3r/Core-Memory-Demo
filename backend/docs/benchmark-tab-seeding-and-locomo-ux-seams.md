# Benchmark tab seeding and LoCoMo UX seams

Status: research/design note

> Phase 0 fencing note: this document describes useful UX seams. It does not authorize seed-like shortcut ingestion for authoritative LoCoMo runs. `locomo_native_lifecycle` must follow `../../docs/locomo-lifecycle-benchmark-prd.md` and the mode boundaries in `locomo-benchmark-mode-matrix.md`.

## User requirement captured

Desired UX:
- LoCoMo should be runnable from the **Benchmark** tab
- it should feel like the existing **Seed** flow
- specifically, LoCoMo should behave like benchmark-tab seeding now behaves: a replay/orchestration action over a fixed corpus, not a separate disconnected workflow

This document maps the current seeding path carefully so the LoCoMo integration can slot into the same control and lifecycle model.

---

## High-level conclusion

The existing benchmark-tab **Seed** button is already the right UX template for LoCoMo.

It is not merely a static fixture importer. It is a controlled replay pipeline with:
- optional reset/wipe behavior
- cursor/resume behavior
- bounded replay size
- wait-for-idle semantics
- auto-flush semantics
- queue-drain verification
- status/progress reporting in the chat/system pane

That is extremely close to what a LoCoMo fixed-corpus replay should be.

So the correct UX direction is:
- keep LoCoMo under the Benchmark tab
- make LoCoMo a new replay source/mode behind the same orchestration model as Seed
- avoid creating a separate standalone benchmark runner UX for ingestion

---

## Frontend control surface today

### Benchmark tab layout

File:
- `frontend/dist/chat.html`

Current Benchmark tab controls:
- `bench-root-mode` select
  - `snapshot`
  - `clean`
- `bench-preload-max` numeric input
- `bench-preload-enabled` checkbox, labeled `from demo`
- `btn-seed`
- `btn-benchmark`, labeled `Run LOCOMO Test`

Important observation:
- there is already a visible distinction between:
  - **Seed**, which prepares memory state by replaying content into the live demo memory system
  - **Run LOCOMO Test**, which runs evaluation

That split is useful and should remain.

For LoCoMo UX, the correct design is likely:
- Seed-like action for ingesting a fixed LoCoMo corpus into memory
- Benchmark-run action for asking/evaluating LoCoMo questions afterward

This matches the current mental model.

---

## Session-control UX that Seed already uses

Also in `frontend/dist/chat.html`, session popover controls affect Seed behavior:
- `seed-reset-before-run`
- `seed-wipe-memory`
- `seed-continue-story`
- story cursor label and reset actions

These are not just cosmetic. They directly shape replay behavior.

### What they mean today

- **Start fresh session before Seed**
  - reset session identity before replay
- **Clear memory store too**
  - hard reset storage before replay
- **Continue story-pack from last turn**
  - replay resumes from a bookmark instead of restarting

This is the most important UX seam for LoCoMo.

It suggests LoCoMo ingestion should expose analogous replay semantics:
- start fresh vs continue existing benchmark session
- optional wipe before import
- progress over a fixed corpus range
- possibly a corpus cursor or per-sample progress bookmark

---

## Frontend orchestration logic for Seed

File:
- `frontend/dist/chat-app.js`
- function: `seedMemory()`

This is the key client-side UX orchestrator.

### Current behavior sequence

1. disable Seed button and show `Seeding...`
2. read benchmark-tab preload settings:
   - `bench-preload-enabled`
   - `bench-preload-max`
3. read session/replay preferences:
   - continue story
   - reset before run
   - wipe before run
4. reconcile conflicting options
   - if preload-enabled and continue-story, fresh reset/wipe is skipped
5. optionally reset session via `resetSessionForSeed({ wipeMemory })`
6. choose one of two replay modes:
   - story-pack replay mode when preload is enabled
   - default chat replay mode when preload is disabled
7. show progress system messages
8. call backend replay endpoint
9. display replay results including seeded count, queue idle status, fallback counts
10. refresh memory state/UI

This is already a generic replay-control shape.

### Why this matters for LoCoMo

LoCoMo replay should reuse this same orchestration pattern rather than inventing a different workflow.

Specifically, a LoCoMo ingest action should probably:
- live in the same Benchmark tab area
- respect fresh-session/hard-reset preferences
- run as bounded replay over a fixed corpus/sample subset
- report seeded count/range/queue idle/fallbacks in the same style
- refresh state using the same post-run flow

---

## Existing Seed backend modes

The current Seed UX has two backend paths.

### Mode A, story-pack replay

Frontend trigger:
- `preloadEnabled === true`

Backend endpoint:
- `POST /api/story-pack/replay`

Payload includes:
- `start_turn`
- `max_turns`
- `auto_flush: true`
- `flush_threshold_ratio`
- `run_checkpoints: false`
- `reset_session: false`
- `use_manifest_sessions: false`
- `wait_for_idle: true`
- `idle_timeout_ms: 120000`
- `idle_poll_ms: 250`

UX semantics:
- replay a bounded fixed corpus slice
- use bookmark/cursor behavior
- wait for background queues to settle
- report turn range replayed

This is the closest existing model to LoCoMo ingest.

### Mode B, default chat replay seed

Frontend trigger:
- `preloadEnabled === false`

Backend endpoint:
- `POST /api/seed`

Payload includes:
- `wait_for_idle: true`
- `auto_flush: true`
- `flush_threshold_ratio`

UX semantics:
- replay a short default prompt set through the full chat pipeline
- less corpus-oriented than story-pack replay

For LoCoMo, Mode A is the stronger template.

---

## Backend route seams used by Seed

File:
- `backend/app/routes/demo.py`

Relevant endpoints:
- `POST /api/seed` -> `seed_demo_history(...)`
- `GET /api/story-pack/meta`
- `POST /api/story-pack/replay` -> `replay_story_pack(...)`
- `POST /api/session/reset` -> `reset_test_session(...)`

This confirms that current seeding is route-layer thin and runtime-layer heavy.

LoCoMo should follow the same pattern:
- new route surface only if needed
- most behavior should live in demo runtime orchestration helpers

---

## Runtime seam: default seed path

File:
- `backend/app/core/runtime.py`
- function: `seed_demo_history(...)`

### What it does

`seed_demo_history(...)` is not a bulk import hack. It is a managed replay loop over prompts.

Observed sequence:
1. normalize configured or supplied user messages
2. compute target turn count
3. loop messages one-by-one
4. call `await run_chat(user_query)` for each turn
5. inspect diagnostics and fallback usage
6. optionally wait until async queues are idle after each turn
7. decide whether to flush based on:
   - turn count since last flush
   - session token usage ratio vs context budget
8. call `run_flush()` when needed
9. optionally wait for idle again after flush
10. return structured replay result including:
   - seeded count
   - failed turns
   - queue status
   - queue wait checks
   - flush count/details
   - fallback counts
   - session details

### Architectural meaning

This function is a **replay orchestrator** over the normal chat path.

That is the core insight for LoCoMo UX.

LoCoMo ingestion should be implemented as a sibling replay orchestrator, not as a one-off import utility.

---

## Runtime seam: story-pack replay path

File:
- `backend/app/core/runtime.py`
- function: `replay_story_pack(...)`

### What it does

This is even closer to the desired LoCoMo UX than `seed_demo_history(...)`.

Observed behavior:
1. load bundle from story-pack manifest
2. optionally filter by start/end/max turns
3. optionally reset session
4. maintain selected turn set and checkpoint behavior
5. iterate fixed corpus turns in order
6. manage queue waits, flushes, fallback counts, errors
7. return replay metadata such as turn range and counts

### Why it matters

This is effectively a benchmark-tab corpus replay engine already.

LoCoMo should be modeled as another fixed-corpus replay source with the same operational semantics:
- bounded corpus selection
- optional reset semantics
- optional continuation/cursor semantics where sensible
- wait-for-idle and auto-flush support
- structured replay result for UI

### Strong recommendation

Do not model LoCoMo ingest after `run_benchmark(...)`.
Model it after `replay_story_pack(...)`.

That directly matches the UX request: “Essentially the way that the bead seeding works now.”

---

## Runtime seam: actual chat replay primitive

File:
- `backend/app/core/runtime.py`
- function: `run_chat(...)`

### Why it matters

All seeding currently relies on the normal turn path by calling `run_chat(...)`, which:
- creates a turn id
- prepares crawler updates
- runs PydanticAI + `run_with_memory(...)`
- falls back to retrieval-based answer if model unavailable
- may directly call `process_turn_finalized(...)` in fallback mode
- performs semantic sync
- collects retrieval diagnostics
- updates token accounting
- populates `LAST_TURN_DIAGNOSTICS`

This matters because current seed replay is not bypassing the real demo memory runtime.
It is using it.

For LoCoMo ingest, we need to decide whether the replay primitive is:
- `run_chat(...)`, if the benchmark replay is meant to generate model answers during ingest, or
- a new transcript replay primitive, if the benchmark replay is meant to ingest a fixed historical corpus

Given LoCoMo is transcript-first, the latter is more appropriate.

But the orchestration shell around it should still look like `seed_demo_history(...)` and `replay_story_pack(...)`.

---

## Runtime seam: reset and flush behavior

### `reset_test_session(...)`

Role:
- creates a fresh demo session id
- optionally wipes memory root
- resets token usage and diagnostics

This is directly part of Seed UX and should also apply to LoCoMo corpus replay.

### `run_flush(...)`

Role:
- runs canonical `process_flush(...)`
- rotates to a new session id afterward
- resets token usage

This is part of current Seed replay resilience and context-budget control.

LoCoMo replay should support the same auto-flush lifecycle model, especially for longer sample or multi-sample imports.

---

## Benchmark-run seam is different from seed seam

File:
- `backend/app/core/runtime.py`
- function: `run_benchmark(...)`

### What it does today

`run_benchmark(...)` currently:
- creates an isolated run root
- optionally snapshots the live root
- optionally preloads live demo turns into the benchmark root using `process_turn_finalized(...)`
- loads benchmark fixture cases via `_load_locomo_cases(...)`
- materializes case setup into per-case isolated roots
- runs `memory_tools.execute(...)` for each case
- compares actual results against expected checks
- aggregates pass/fail metrics

### Why this is not the right UX model for LoCoMo ingest

This function is an **evaluation runner**, not an ingestion replay controller.

It is per-case, isolated, and metric-oriented.
The Seed UX is replay-oriented and state-building.

So the right UX split is:
- **Seed-like action**: ingest fixed LoCoMo corpus into memory
- **Benchmark-run action**: evaluate QA cases over that seeded corpus or isolated replay roots

This is exactly in line with the user request.

---

## UX design implications for LoCoMo

### Best fit

LoCoMo should be added as a **Seed source / replay source** in the Benchmark tab.

Not as a hidden subroutine of the current `Run LOCOMO Test` button.

### Suggested UX structure

Under Benchmark tab, extend Seed controls with corpus source selection, for example:
- Source: `story-pack | default-demo | locomo`

When `locomo` is selected, show source-specific controls such as:
- LoCoMo sample selector or subset selector
- max sessions or max turns
- replay mode: `transcript_only` initially
- maybe continue cursor/bookmark per sample later

But keep these operational controls shared:
- Start fresh session before Seed
- Clear memory store too
- wait-for-idle semantics
- auto-flush semantics
- seeded count / queue idle reporting

That way LoCoMo feels like the same system, not a bolt-on.

---

## Recommended backend shape for LoCoMo seeding

### New runtime helper

Add a runtime orchestrator sibling to:
- `seed_demo_history(...)`
- `replay_story_pack(...)`

Example conceptual name:
- `replay_locomo_corpus(...)`

### Expected responsibilities

1. load LoCoMo sample(s)
2. optionally reset session/wipe memory handled by existing route/UI flow
3. iterate a fixed corpus in deterministic order
4. use transcript replay primitive for each row
5. respect:
   - `max_turns`
   - optional sample selection
   - wait-for-idle
   - auto-flush
   - flush thresholds
6. return structured replay result compatible with Seed UX patterns

### Expected result shape

To match current Seed UX, include fields like:
- `ok`
- `seeded`
- `seeded_turns`
- `requested_turns`
- `failed_turns`
- `errors`
- `mode`
- `queue_idle`
- `queue`
- `queue_wait_checks`
- `auto_flush`
- `flush_count`
- `flushes`
- `fallback_turns` if relevant
- `session`
- corpus-specific extras such as:
  - `sample_id`
  - `session_range`
  - `turn_range`
  - `locomo_mode`

This keeps frontend adaptation minimal.

---

## Documentation-level answer to the UX note

The current bead seeding code is best understood as:
- a benchmark-tab replay orchestrator over a chosen corpus source
- with session/reset/flush/queue lifecycle management
- using either the live chat path or the fixed story-pack corpus path

Therefore, LoCoMo should be integrated as:
- another fixed corpus replay source under the same Seed UX family
- not as a standalone import wizard
- not as only a hidden part of benchmark evaluation

That is the cleanest way to honor the current product shape.

---

## Concrete next implementation move implied by this research

1. Add source-selection design for Seed in Benchmark tab.
2. Implement `replay_locomo_corpus(...)` as a sibling of `replay_story_pack(...)`.
3. Keep `Run LOCOMO Test` as the evaluation action.
4. Let LoCoMo seed build memory state the same way current replay seeding does, with the same operational controls.

---

## Bottom line

If the requirement is “make LoCoMo runnable from the benchmark tab like bead seeding”, the correct architecture is:
- **LoCoMo ingest should follow the Seed/replay path, not the benchmark-eval path**
- specifically, it should mirror `replay_story_pack(...)` far more than `run_benchmark(...)`

That gives us the right UX and keeps the implementation aligned with the existing control model.
