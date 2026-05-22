# LoCoMo seed-source contract for benchmark tab

> Phase 0 fencing note: seed-source contracts are fixture/demo plumbing unless explicitly routed through `locomo_native_lifecycle` guardrails. See `../../docs/locomo-lifecycle-benchmark-prd.md` and `locomo-benchmark-mode-matrix.md`.

Status: design/spec
Depends on:
- `backend/docs/adapter-only-integration-research.md`
- `backend/docs/locomo-integration-research.md`
- `backend/docs/locomo-replay-adapter-design.md`
- `backend/docs/benchmark-tab-seeding-and-locomo-ux-seams.md`

## Goal

Define the exact UI and backend contract for making LoCoMo run from the **Benchmark** tab using the same replay-oriented Seed UX family as the current story-pack seeding flow.

This is the concrete handoff point between research and implementation.

---

## Product objective

User intent:
- LoCoMo should be runnable from the benchmark tab
- it should feel like current bead seeding
- it should operate over a fixed corpus
- it should not introduce a separate awkward control plane

Therefore:
- LoCoMo becomes a **Seed source** under the Benchmark tab
- Seed remains the ingestion/replay action
- Run LOCOMO Test remains the evaluation action

---

## Current UX model to preserve

We are preserving the operational semantics already used by Seed:
- optional fresh session reset
- optional memory wipe
- bounded replay count
- progress message in chat/system stream
- wait-for-idle semantics
- auto-flush semantics
- queue/drain reporting
- state refresh after replay

The contract below extends that model instead of replacing it.

---

## Frontend contract changes

### 1. Add a Seed source selector in Benchmark tab

Current controls already present:
- root mode
- preload max
- preload from demo
- Seed button
- Run LOCOMO Test button

### Proposed control addition

Add:
- `seed-source` select

Options:
- `story_pack`
- `default_demo`
- `locomo`

### Default

Recommended default:
- `story_pack`

Reason:
- preserves current visible behavior for existing users

---

## Source-specific control model

### Source: `default_demo`

Maps to current `/api/seed` behavior.

Visible controls:
- none beyond shared replay controls

### Source: `story_pack`

Maps to current `/api/story-pack/replay` behavior.

Visible controls:
- current preload max
- continue story cursor behavior

### Source: `locomo`

New fixed-corpus replay mode.

Visible controls should initially be minimal and focused.

#### Required initial controls

- `locomo-sample-mode`
  - `single`
  - `all`

- `locomo-sample-id` or sample selector
  - visible only when sample mode is `single`
  - initial options can be sample ids from `locomo10.json`

- `locomo-max-turns`
  - optional numeric cap for bounded replay testing

- `locomo-replay-mode`
  - initial value and only supported value at first: `transcript_only`

#### Optional future controls

- `locomo-max-sessions`
- `locomo-start-session`
- `locomo-continue-corpus-cursor`
- retrieval-view mode switches for comparative replay modes

### UX note

Keep the visible control count small at first.
The important thing is that LoCoMo feels like just another replay source, not a mini dashboard.

---

## Shared session-control behavior

The existing session popover controls must continue to apply to LoCoMo seeding:
- `seed-reset-before-run`
- `seed-wipe-memory`
- possibly continue-story remains story-pack specific

### Rule

For LoCoMo:
- reset and wipe behavior remain shared
- story cursor behavior should not apply directly unless a LoCoMo-specific bookmark is later added

### Initial frontend rule

When `seed-source=locomo`:
- ignore `seed-continue-story`
- optionally show a small note that story cursor applies only to story-pack source

---

## Frontend orchestration behavior

### Update `seedMemory()` selection logic

Current branching is roughly:
- if preload enabled -> story-pack replay
- else -> default demo seed

### New branching shape

Branch first by `seed-source`:
- `default_demo` -> call `/api/seed`
- `story_pack` -> call `/api/story-pack/replay`
- `locomo` -> call new `/api/locomo/replay`

This is cleaner than overloading `bench-preload-enabled`.

### Recommended compatibility behavior

We can keep existing controls working while migrating by:
- defaulting `seed-source` based on existing preload checkbox state initially if needed
- but long term, source selector should become the main authority

---

## New backend route contract

### Proposed route

- `POST /api/locomo/replay`

This should live alongside:
- `/api/seed`
- `/api/story-pack/replay`

It should be handled by demo route layer and delegated to demo runtime, just like current replay endpoints.

---

## Request payload contract for `/api/locomo/replay`

### Required fields

- `sample_mode: "single" | "all"`
- `replay_mode: "transcript_only"`

### Conditional fields

- `sample_id: string`
  - required when `sample_mode == "single"`

### Optional fields

- `max_turns: int | null`
- `max_sessions: int | null`
- `start_session: int | null`
- `reset_session: bool`
- `wait_for_idle: bool`
- `idle_timeout_ms: int`
- `idle_poll_ms: int`
- `auto_flush: bool`
- `flush_threshold_ratio: float`
- `flush_every_turns: int`
- `max_compaction_per_pass: int`
- `max_side_effects_per_pass: int`

### Recommended initial payload example

```json
{
  "sample_mode": "single",
  "sample_id": "0",
  "replay_mode": "transcript_only",
  "max_turns": 200,
  "wait_for_idle": true,
  "idle_timeout_ms": 120000,
  "idle_poll_ms": 250,
  "auto_flush": true,
  "flush_threshold_ratio": 0.8,
  "flush_every_turns": 0,
  "reset_session": false
}
```

### Design note

Session reset/wipe should still usually happen in the existing frontend prep path before the replay request, not be fully duplicated inside this route.
But `reset_session` may still be accepted for parity and future server-driven use.

---

## Response payload contract for `/api/locomo/replay`

This should intentionally resemble existing Seed replay result shapes.

### Required fields

- `ok: bool`
- `seeded: int`
- `seeded_turns: int`
- `requested_turns: int`
- `failed_turns: int`
- `errors: list`
- `mode: "locomo_replay"`
- `locomo_mode: "transcript_only"`
- `queue_idle: bool`
- `queue: object`
- `queue_wait_checks: list`
- `auto_flush: bool`
- `flush_count: int`
- `flushes: list`
- `session: object`

### Required LoCoMo-specific metadata

- `sample_mode`
- `sample_ids`
- `session_range`
- `turn_range`
- `corpus_stats`

### Recommended fields

- `sample_mode: "single" | "all"`
- `sample_ids: ["0"]`
- `session_range: {"first": 1, "last": 12}`
- `turn_range: {"first": 1, "last": 200}`
- `corpus_stats: {
    "samples_requested": 1,
    "samples_replayed": 1,
    "sessions_replayed": 12,
    "turns_available": 234,
    "turns_replayed": 200
  }`

### Recommended success response example

```json
{
  "ok": true,
  "seeded": 200,
  "seeded_turns": 200,
  "requested_turns": 200,
  "failed_turns": 0,
  "errors": [],
  "mode": "locomo_replay",
  "locomo_mode": "transcript_only",
  "sample_mode": "single",
  "sample_ids": ["0"],
  "session_range": {"first": 1, "last": 12},
  "turn_range": {"first": 1, "last": 200},
  "queue_idle": true,
  "queue": {"ok": true},
  "queue_wait_checks": [],
  "auto_flush": true,
  "flush_count": 2,
  "flushes": [],
  "corpus_stats": {
    "samples_requested": 1,
    "samples_replayed": 1,
    "sessions_replayed": 12,
    "turns_available": 234,
    "turns_replayed": 200
  },
  "session": {
    "session_id": "locomo:0",
    "token_usage": 0,
    "context_budget": 128000
  }
}
```

---

## Runtime helper contract

### New demo runtime helper

Proposed function:
- `replay_locomo_corpus(...)`

Location:
- `backend/app/core/runtime.py`

### Responsibilities

1. load LoCoMo corpus metadata and sample data
2. normalize sample/session/turn ordering
3. choose deterministic Core Memory session id(s)
4. optionally call session-start boundary
5. replay rows one by one through transcript-oriented benchmark replay primitive
6. apply same queue-idle + auto-flush lifecycle control used by existing Seed replay
7. emit structured response matching Seed-style result shape

### Important non-responsibilities

- should not run QA benchmark scoring directly
- should not own evaluation metrics logic
- should not overload benchmark-run reporting

---

## Supporting runtime helper surfaces

### `get_locomo_meta()`

Recommended helper for frontend control population.

Responsibilities:
- load `locomo10.json`
- return sample ids, counts, and lightweight stats

Possible response:

```json
{
  "ok": true,
  "dataset": "locomo10",
  "samples": [
    {"sample_id": "0", "sessions": 12, "turns": 234, "qa": 199},
    {"sample_id": "1", "sessions": 10, "turns": 198, "qa": 105}
  ],
  "sample_count": 10
}
```

### `iter_locomo_replay_rows(...)`

Responsibilities:
- normalize LoCoMo transcript rows into replay row objects
- enforce deterministic order
- apply optional max/session filters

Yielded row fields should include:
- `sample_id`
- `session_index`
- `session_date_time`
- `turn_index`
- `dia_id`
- `speaker`
- `text`
- optional image metadata

### `replay_locomo_row(...)`

Responsibilities:
- map one normalized LoCoMo row into canonical replay write call
- preserve required provenance metadata

---

## Canonical provenance contract during LoCoMo replay

Every replayed row must preserve at least:
- `benchmark_name = "locomo"`
- `locomo_sample_id`
- `locomo_session_index`
- `locomo_session_date_time`
- `locomo_turn_index`
- `locomo_dia_id`
- `locomo_speaker`
- `locomo_raw_text`
- `replay_mode = "locomo_transcript_row"`

### Required projection behavior for evaluation later

When later answering QA and returning supporting contexts:
- transcript-backed contexts must project back to original `locomo_dia_id`
- session-summary comparative mode must project to `S<n>`

This is mandatory for compatibility with existing LoCoMo recall/evidence scoring.

---

## Session-id contract for Seed UX

### Initial recommended session strategy

One Core Memory session per LoCoMo sample:
- `locomo:<sample_id>`

This aligns with long-term conversational memory evaluation.

### What happens when `sample_mode = all`

Two choices exist:

#### Choice A, replay all samples into separate sessions in one run

Recommended.

Meaning:
- same replay request can process multiple sample sessions
- response `sample_ids` becomes multiple values
- `session.session_id` in response may be the last active session or omitted in favor of `sessions` list

#### Choice B, merge all samples into one session

Not recommended.

Reason:
- destroys benchmark identity boundaries
- creates nonsense cross-sample memory leakage

### Recommendation

When `sample_mode = all`, replay each LoCoMo sample into its own benchmark session namespace.

---

## UI progress text contract

To match current Seed UX, frontend should display concise progress messages like:

### For LoCoMo success
- `Seeded 200 turn(s) via LoCoMo replay · sample=0 · queue_idle=true`
- `Seeded 1834 turn(s) via LoCoMo replay · samples=10 · queue_idle=true`

### For partial replay
- `Seeded 200 turn(s) via LoCoMo replay · sample=0 · range=1-200 · queue_idle=true`

### For warning states
- `Warning: LoCoMo replay completed with 3 failed turn(s).`
- `Warning: queue did not settle before timeout during LoCoMo replay.`

This should stay visually and semantically aligned with current Seed feedback.

---

## Error contract

Recommended stable error strings for route/runtime responses:
- `locomo_dataset_not_found`
- `locomo_sample_not_found`
- `locomo_no_turns_selected`
- `locomo_invalid_sample_mode`
- `locomo_invalid_replay_mode`
- `locomo_queue_not_idle_timeout`
- `locomo_replay_row_failed`

These should be surfaced in structured `error` or `errors[]` fields, just like current replay functions.

---

## Benchmark-tab evaluation relationship

The current `Run LOCOMO Test` button should remain conceptually separate.

### Rule

- `Seed` prepares state
- `Run LOCOMO Test` measures performance

### Near-term implication

LoCoMo seeding does **not** need to immediately change `run_benchmark(...)`

Instead, we should first make it possible to:
- seed LoCoMo transcript corpus into memory via Benchmark tab
- inspect resulting memory state
- then later decide whether the benchmark runner evaluates:
  - seeded live state
  - isolated per-case roots
  - both

This sequencing keeps the implementation controlled.

---

## First implementation slice

### Frontend

1. Add `seed-source` select.
2. Add minimal LoCoMo source controls.
3. Update `seedMemory()` to branch on source.
4. Keep existing reset/wipe workflow unchanged.

### Backend routes

1. Add `GET /api/locomo/meta`.
2. Add `POST /api/locomo/replay`.

### Backend runtime

1. Add LoCoMo metadata loader.
2. Add LoCoMo row iterator/normalizer.
3. Add `replay_locomo_corpus(...)` orchestrator.
4. Reuse existing queue-idle and auto-flush lifecycle helpers.

### Out of scope for first slice

- fancy comparative retrieval modes
- all-sample resume bookmarks
- UI analytics dashboards
- direct benchmark scoring integration changes

---

## Bottom line

The right contract is simple:
- LoCoMo becomes a new **Seed source** in the Benchmark tab
- it gets a new replay endpoint and replay runtime helper
- it preserves the same session/reset/flush/queue UX as existing Seed behavior
- it preserves LoCoMo provenance exactly so later QA evaluation remains valid

That gives us a clean path from current UX to implementation without breaking the adapter-only architecture.
