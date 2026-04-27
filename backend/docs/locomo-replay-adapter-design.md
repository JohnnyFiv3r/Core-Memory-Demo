# LoCoMo replay adapter design

Status: design/research checkpoint
Depends on:
- `backend/docs/adapter-only-integration-research.md`
- `backend/docs/locomo-integration-research.md`

## Goal

Define the exact adapter contract for replaying upstream LoCoMo transcript data into canonical Core Memory surfaces, without forking Core Memory semantics and without losing LoCoMo evidence/provenance needed for QA evaluation.

This document is the bridge between high-level seam research and actual implementation.

---

## Design principles

1. Transcript is authority.
2. LoCoMo replay is an adapter/orchestration problem, not a Core Memory contract rewrite.
3. Preserve LoCoMo `dia_id` exactly.
4. Preserve session ordering and session timestamps exactly.
5. Route writes through canonical Core Memory boundaries where possible.
6. Keep benchmark-specific retrieval modes separate from canonical memory authority.
7. Do not make generated observations or session summaries the ingestion source of truth.

---

## Upstream raw input shape to support

Source file:
- `/home/node/.openclaw/workspace/locomo/data/locomo10.json`

Observed row structure:
- top level is a list of samples
- each sample contains:
  - `sample_id`
  - `conversation`
  - `qa`
  - `observation`
  - `session_summary`
  - `event_summary`

Observed raw turn shape from first transcript row:
- `speaker`
- `dia_id`
- `text`
- sometimes optional image metadata in other rows, such as:
  - `img_url`
  - `blip_caption`
  - related image/query fields

Observed first example:
- session key: `session_1`
- first turn keys: `['dia_id', 'speaker', 'text']`
- first row:
  - `speaker='Caroline'`
  - `dia_id='D1:1'`
  - `text='Hey Mel! Good to see you! How have you been?'`

This confirms the adapter must handle plain transcript rows first, with optional multimodal metadata as additive fields.

---

## Replay target architecture

The replay adapter should write into Core Memory in two layers:

### Layer 1, authoritative transcript/turn archive

Canonical target surfaces:
- `.turns/session-<session_id>.jsonl`
- `.turns/session-<session_id>.idx.json`

Canonical implementation file:
- `Core-Memory/core_memory/runtime/turn_archive.py`

Important functions:
- `append_turn_record(...)`
- `get_turn_record(...)`
- `find_turn_record(...)`
- `get_adjacent_turns(...)`

Why this matters:
- LoCoMo QA evidence is dialog-id based
- transcript fidelity and turn-level hydration matter more than immediately manufacturing rich semantic memory
- transcript archive is the cleanest place to preserve original turn payloads and provenance

### Layer 2, canonical memory/write/runtime surfaces

Canonical target surfaces:
- `process_session_start(...)`
- `process_turn_finalized(...)`
- session surface append and bead/index updates driven by the normal runtime flow

Why this matters:
- benchmark replay should not bypass canonical memory behavior forever
- downstream retrieval and inspect surfaces expect canonical runtime artifacts

### Recommended interpretation

The replay adapter should be capable of two write modes:

1. **Transcript-sync mode**
   - prioritize faithful ingestion of LoCoMo turns into authoritative transcript/history surfaces
   - minimal semantic side effects
   - best for debugging provenance and benchmark parity

2. **Canonical-turn mode**
   - replay each LoCoMo row through canonical finalized-turn processing
   - builds normal beads/associations/continuity artifacts
   - best for true Core Memory benchmark evaluation

These are complementary, not conflicting.

---

## Session identity strategy

LoCoMo sample ids and sessions need a deterministic Core Memory session model.

### Proposed Core Memory session id

For each LoCoMo sample:
- core session id base: `locomo:<sample_id>`

For per-session segmentation within the sample, two viable models exist.

#### Option A, one Core session per LoCoMo sample

Example:
- `locomo:sample_001`

All LoCoMo `session_n` transcript rows become turns within one Core Memory session.

Pros:
- best match for long-running memory across many meetings
- lets continuity/flush/association logic operate across the whole longitudinal conversation
- most faithful to the benchmark’s intent of long-term memory

Cons:
- need explicit metadata to preserve original LoCoMo session boundaries inside one session

#### Option B, one Core session per LoCoMo session

Example:
- `locomo:sample_001:session_1`
- `locomo:sample_001:session_2`

Pros:
- easier operational batching

Cons:
- breaks long-term memory continuity unless extra bridge logic is added
- less faithful to the benchmark’s core challenge

### Recommendation

Use **Option A** as canonical benchmark mode:
- one Core Memory session per LoCoMo sample

Preserve LoCoMo session boundaries as metadata fields rather than splitting Core session identity.

---

## Turn identity strategy

LoCoMo already has dialog identifiers like:
- `D1:1`
- `D1:2`
- `D3:7`

These are gold-evidence anchors and must survive replay.

### Proposed turn id strategy

Use a deterministic Core turn id that embeds LoCoMo identity without ambiguity.

Recommended format:
- `locomo:<sample_id>:<dia_id>`

Example:
- `locomo:0:D1:1`
- `locomo:0:D1:2`

Why not use raw `D1:1` directly?
- could collide across different samples
- less robust for multi-benchmark usage

### Required provenance metadata

Each replayed turn should include metadata such as:
- `benchmark_name: "locomo"`
- `locomo_sample_id: <sample_id>`
- `locomo_session_index: <n>`
- `locomo_session_date_time: <original string>`
- `locomo_dia_id: <original dia_id>`
- `locomo_speaker: <speaker>`
- `locomo_has_image: bool`
- optional raw image fields where present

This is the minimum needed to preserve benchmark traceability.

---

## Transcript row mapping contract

LoCoMo turns are speaker utterances, not user/assistant pairs. Core Memory finalized-turn pipeline expects a pair:
- `user_query`
- `assistant_final`

So the replay adapter needs an explicit mapping policy.

### Candidate policies

#### Policy 1, pairwise conversational folding

Convert adjacent LoCoMo turns into one finalized turn:
- current speaker turn -> `user_query`
- next speaker reply -> `assistant_final`

Example:
- turn A: Caroline says X
- turn B: Mel says Y
- replay as one finalized turn for session:
  - `user_query = "Caroline: X"`
  - `assistant_final = "Mel: Y"`

Pros:
- fits canonical finalized-turn shape naturally
- closer to actual assistant exchange semantics

Cons:
- loses one-to-one raw turn granularity unless transcript archive is also preserved separately
- awkward when same speaker has multiple consecutive turns
- end-of-session odd turn needs special handling

#### Policy 2, narrator-style single-turn folding

Replay each raw LoCoMo dialog row as a synthetic finalized turn with:
- `user_query = "[LoCoMo replay metadata/context]"`
- `assistant_final = "<speaker>: <text>"`

Pros:
- preserves 1:1 row mapping
- easier provenance
- each LoCoMo row gets a unique canonical turn boundary

Cons:
- less naturally aligned with normal chat semantics
- may distort crawler semantics if not marked clearly in metadata

#### Policy 3, transcript archive first plus optional semantic synthesis

Step A:
- append raw transcript rows into authoritative turn archive or replay transcript surface

Step B:
- separately create canonical memory turns or beads from grouped session windows, not necessarily 1:1 with raw transcript rows

Pros:
- cleanest separation of transcript truth from memory abstraction
- best for debugging and future flexibility

Cons:
- more implementation work
- need explicit benchmark retrieval/read mode to use transcript archive

### Recommendation

Use a hybrid of Policy 2 and Policy 3:

**Immediate implementation mode**
- preserve every raw LoCoMo row 1:1 in transcript-oriented surfaces
- for canonical turn processing, replay each row as a synthetic finalized turn with strong benchmark metadata

This keeps implementation tractable while preserving row-level provenance.

Then later, if needed, we can introduce grouped pairing/window modes for better semantic realism.

---

## Proposed canonical replay payload

For each LoCoMo raw row, create replay input fields like:

- `session_id = "locomo:<sample_id>"`
- `turn_id = "locomo:<sample_id>:<dia_id>"`
- `transaction_id = "locomo-tx:<sample_id>:<dia_id>"`
- `trace_id = "locomo-tr:<sample_id>:<dia_id>"`
- `origin = "BENCHMARK_REPLAY"`
- `trace_depth = 0`
- `user_query = "[LoCoMo transcript replay]"`
- `assistant_final = "<speaker>: <text>"`
- `metadata = { ... locomo provenance ... }`

Recommended extra metadata:
- `adapter_kind: "benchmark_replay"`
- `adapter_runtime: "locomo"`
- `adapter_status: "research" | "benchmark"`
- `replay_mode: "locomo_transcript_row"`
- `replay_row_type: "dialog"`
- `locomo_raw_text: <text>`
- `locomo_display_text: "<speaker>: <text>"`

Optional multimodal fields if present:
- `locomo_img_url`
- `locomo_blip_caption`
- `locomo_image_query`

This makes replay explicit and auditable.

---

## Session-start handling

Before replaying the first LoCoMo row for a sample, the adapter should call canonical session-start boundary:
- `process_session_start(root, session_id, source="locomo_replay", max_items=...)`

Why:
- keeps lifecycle behavior canonical
- ensures continuity/session-start artifacts exist in the same way as normal runtime sessions

Important caveat:
- because LoCoMo is historical import, continuity before the first imported turn should usually be empty or benchmark-controlled
- replay adapter should not inject unrelated demo continuity into a fresh benchmark session root

Recommendation:
- benchmark replay should use isolated benchmark root or clean per-run root namespace

---

## Timestamp and chronology strategy

LoCoMo gives session-level timestamps, not necessarily per-turn timestamps.

Observed field:
- `session_<n>_date_time`

### Required chronology properties

We need to preserve:
- session order
- turn order within session
- reproducible ingestion order

### Proposed strategy

For canonical ordering:
- use LoCoMo session index + turn position as the primary ordering authority

Metadata should store:
- original `session_<n>_date_time` string unchanged
- session index `n`
- turn ordinal within session

If a strict timestamp string is required during replay, derive a synthetic monotonic timestamp per turn using:
- parsed session datetime as base
- add small deterministic per-turn increments, for example seconds by turn ordinal

This should be explicit metadata, for example:
- `locomo_time_policy: "synthetic_turn_offsets_from_session_timestamp"`

This avoids pretending LoCoMo gave true per-turn timestamps when it did not.

---

## Evidence and retrieval context id strategy

LoCoMo scoring expects evidence alignment.

### Required benchmark-compatible ids

Dialog-level retrieval mode should emit context ids in original LoCoMo form:
- `D1:3`
- `D7:12`

Session-summary retrieval mode should emit ids like:
- `S1`
- `S2`

### Core Memory provenance mapping rule

Every replayed memory artifact that originates from a LoCoMo turn should retain the original `locomo_dia_id` in provenance metadata.

When benchmark answer mode returns supporting contexts, it should expose benchmark-facing ids by projection:
- transcript-backed context -> original `locomo_dia_id`
- session-summary-backed context -> `S<n>`

This lets existing LoCoMo recall/evidence scoring remain unchanged.

---

## Replay modes to support

### Mode 1, `transcript_only`

Purpose:
- ingest transcript and answer using transcript-grounded retrieval only

Characteristics:
- transcript authority only
- no generated observation/session-summary database required
- best initial benchmark mode

### Mode 2, `observation_view`

Purpose:
- compare against LoCoMo-style generated observation retrieval

Characteristics:
- benchmark-owned observation retrieval view
- still preserve transcript truth underneath

### Mode 3, `session_summary_view`

Purpose:
- compare against LoCoMo summary retrieval baseline

Characteristics:
- retrieval chunks keyed by `S<n>`
- generated or upstream provided summaries

### Mode 4, `hybrid`

Purpose:
- combine transcript + observations + summaries

Characteristics:
- useful for later experimentation
- not required for the first canonical replay implementation

### Recommendation

Implement `transcript_only` first.

---

## Replay adapter API proposal

Suggested demo-side adapter surface, conceptual only:

### `load_locomo_sample(...)`

Responsibilities:
- open `locomo10.json`
- select one sample or subset
- normalize session ordering
- yield replay-ready row objects

### `iter_locomo_turn_rows(...)`

Yields normalized rows like:
- `sample_id`
- `session_index`
- `session_date_time`
- `turn_index`
- `speaker`
- `dia_id`
- `text`
- optional image metadata

### `replay_locomo_sample(...)`

Responsibilities:
1. choose root/session id
2. call `process_session_start(...)`
3. replay each normalized row through canonical turn path
4. optionally run flush/async jobs between chunks or after sample completion
5. return replay diagnostics including mapping stats

### `answer_locomo_questions(...)`

Responsibilities:
- iterate `qa`
- answer via Core Memory-backed retrieval/agent logic
- emit benchmark-compatible answer/context payloads

This keeps ingestion and evaluation separate.

---

## Diagnostics and inspect requirements

Replay must be debuggable.

Minimum diagnostics per replay run:
- sample id
- session id
- number of sessions replayed
- number of turns replayed
- number of turns skipped/failed
- mapping from `dia_id` to Core turn id
- whether session-start created or reused
- flush status if performed
- async job status snapshots if relevant

Useful inspect helpers:
- inspect turns by session
- hydrate bead sources back to original `locomo_dia_id`
- inspect benchmark replay metadata on turn records

---

## Risks and mitigations

### Risk 1, semantic distortion from synthetic `user_query`

Problem:
- replaying every row as finalized turn with synthetic `user_query` may create odd semantic patterns

Mitigation:
- mark replay mode clearly in metadata
- start with transcript-only benchmark mode
- keep option open for later pairwise or grouped-turn replay modes

### Risk 2, evidence mismatch

Problem:
- if `dia_id` provenance is lost, LoCoMo recall scoring becomes invalid

Mitigation:
- require `locomo_dia_id` everywhere in replay metadata
- test context-id projections explicitly

### Risk 3, imported history mixing with normal demo session continuity
n
Problem:
- benchmark replay could accidentally inherit unrelated continuity

Mitigation:
- use isolated benchmark roots or clean sample namespaces
- call session-start on clean benchmark sessions only

### Risk 4, generated views overshadowing transcript truth

Problem:
- observations/summaries may be mistaken for primary truth

Mitigation:
- transcript_only first
- keep observation/session-summary modes explicitly named as comparative retrieval views

---

## Recommended first implementation slice

1. Build a LoCoMo row normalizer over `locomo10.json`.
2. Implement deterministic session and turn id mapping.
3. Replay one sample in `transcript_only` mode into isolated benchmark root.
4. Preserve `locomo_dia_id` and session metadata in every turn.
5. Expose a simple diagnostic report and inspectable turn archive.
6. Only after replay is solid, wire QA answer evaluation.

This matches the research-first, adapter-only approach and minimizes contract drift.

---

## Bottom line

The clean replay design is:
- one Core Memory session per LoCoMo sample
- deterministic turn ids derived from sample id + `dia_id`
- preserved raw `dia_id` provenance on every replayed turn
- canonical session-start and turn-finalized boundaries used for replay
- `transcript_only` as the first benchmark mode
- observations and session summaries treated as optional comparative retrieval views later

That gives us a benchmark-faithful ingestion path without corrupting the Core Memory architecture.
