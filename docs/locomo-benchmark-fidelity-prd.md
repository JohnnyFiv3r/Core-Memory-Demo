# PRD: LoCoMo Benchmark Fidelity

| | |
|---|---|
| **Status** | Draft — pending decision on scoring contract |
| **Owner** | Benchmark / Core Memory demo |
| **Date** | 2026-05-21 |
| **Core Memory pin** | `JohnnyFiv3r/Core-Memory.git@b4e71675cbf09cbf8baef9ddaba6e8776b15ad36` |

## 1. Summary

The demo's LoCoMo benchmark scores near zero (4% evidence recall, ~0.02 answer
F1). The cause is not a Core Memory regression — it is that the demo built a
**demo-owned adapter** around Core Memory that drifted from Core Memory's
ingestion, retrieval, and scoring contracts. Both sides "work" in isolation but
speak different benchmark contracts.

This PRD defines the work to make the LoCoMo benchmark a **faithful run of the
Core Memory pipeline** whose numbers can be cited as benchmark claims. It is
sequenced as: fix the adapter in the demo repo now, then move harness ownership
upstream into Core Memory.

## 2. Problem statement

A run over `conv-26` (419 transcript turns, 50 QA cases) produced:

- `semantic_build.entries: 1` — the semantic index held a single bead.
- Every one of 50 questions retrieved the **same** bead
  (`bead-C214830F0475`, the conversation's opening greeting).
- Every retrieved row had empty `dia_ids` / `metadata_source: "none"` →
  retrieval projection dropped 100% of results → `raw_result_count: 0`.
- The answerer abstained on all 50 cases (`unsupported: true`).

The benchmark is not measuring Core Memory. It is measuring a broken adapter.

## 3. Background — current architecture

The demo depends on Core Memory as a pinned pip dependency and calls real
Core Memory APIs, but owns three things it should not own:

| Stage | Demo-owned today | Core Memory canonical |
|---|---|---|
| Ingestion | `ingest_locomo_samples_through_core_memory` → `_replay_locomo_row` → `_process_user_assistant_turn_finalized` | `ingest_transcript` / `process_turn_finalized` |
| Retrieval | `memory_tools.execute` + custom trace traversal + custom rerank (`locomo_runner.py`) | `core_recall` (retrieval agent) |
| Scoring | `compute_evidence_recall` over `metadata.locomo_dia_id` side-channel | `benchmarks/locomo_like` answer-class + grounding-hash |

Core Memory ships its own canonical harness at `benchmarks/locomo_like/`
(`runner.py` has `run_case`, `run_benchmark`, `main()` with argparse). The demo
imports **nothing** from it.

## 4. Root cause analysis

All references verified against the checked-out source.

| # | Root cause | Evidence |
|---|---|---|
| RC1 | All 419 turns are crammed into **one** Core Memory session. `session_id` is keyed on `sample_id` only, ignoring `session_index`. conv-26's 32 LoCoMo sessions collapse into one ~419-turn session — ~30× a normal session window. | `backend/app/core/runtime.py:449` |
| RC2 | The demo **force-runs** aggressive compaction during the post-ingest drain (`max_compaction>=4`) instead of letting Core Memory's natural policy decide. Combined with RC1, compaction merges 419 turn-beads into 1. | `backend/app/core/runtime.py:569` |
| RC3 | Every LoCoMo turn is faked as a user/assistant pair with a **constant** user query `"[LoCoMo transcript replay]"`. The real speaker is stringified into the assistant text and buried in metadata. Core Memory's entity/claim/salience layers see identical garbage input 419×. | `_process_user_assistant_turn_finalized`, `backend/app/core/runtime.py:82-94` |
| RC4 | Compaction does not union `source_turn_ids` from merged members. Per-turn beads get `source_turn_ids=[turn_id]` (`engine.py:87,284`) but `store_compaction_ops.py` has zero `source_turn_ids` references — a compacted bead loses turn-level provenance. | Core Memory `core_memory/persistence/store_compaction_ops.py` |
| RC5 | The scorer keys evidence on a `metadata.locomo_dia_id` side-channel + a brittle `_bead_for_turn` reverse lookup, not the bead's native `source_turn_ids`. | `backend/app/benchmarks/locomo_runner.py`, `locomo_replay.py` |
| RC6 | Retrieval calls the lower-level `memory_tools.execute`, not the canonical `core_recall` agent, then bolts on a demo-specific trace/hydrate/rerank stack. | `backend/app/benchmarks/locomo_runner.py:364` |
| RC7 | `claims_written: 0` in the report is a **hardcoded literal**, not a measurement. | `backend/app/core/runtime.py:585` |

**Key insight:** Core Memory's per-turn provenance works correctly (the run's
`requested_turn_ids: ["locomo:conv-26:D1:1"]` is a real `source_turn_id`).
Compaction is the only thing that destroys it — and compaction only ran amok
because RC1 + RC2 built one oversized session and forced compaction over it.
Compaction should not fire within a session window; the adapter created a
session 30× too large.

## 5. Goals / Non-goals

### Goals

- The LoCoMo benchmark is a faithful run of the Core Memory pipeline at the
  pinned commit — no demo-specific ingestion/retrieval/scoring semantics.
- Evidence provenance flows through Core Memory's native `source_turn_ids`, not
  a metadata side-channel.
- Benchmark numbers are reproducible and citable as benchmark claims.
- Harness ownership moves upstream into Core Memory; the demo only dispatches.

### Non-goals

- Improving Core Memory's retrieval quality. This PRD makes the benchmark
  *honest*, not the model *better*.
- Changing the LoCoMo dataset or QA set.
- Re-architecting the benchmark job queue / worker (covered separately).

## 6. Requirements

Ownership decision (locked): **fix in the demo repo now, move upstream after.**

### Phase 1 — Faithful conversation replay (demo repo)

This delivers the intended adapter behavior — replaying the LoCoMo transcript
as a real turn-by-turn conversation — done correctly instead of faked.

- **R1.1** One Core Memory session per LoCoMo session: key `session_id` on
  `sample_id` + `session_index`. conv-26 becomes 32 sessions of ~13 turns, each
  within a normal session window.
- **R1.2** Ingest each LoCoMo turn as a genuine `Turn(speaker=<real speaker>,
  role="other", content=<text>)`. Remove the constant `[LoCoMo transcript
  replay]` user query. The `Turn` schema explicitly supports multi-speaker
  turns.
- **R1.3** Ingest via Core Memory's canonical `ingest_transcript`
  (`core_memory/transcript_ingest.py`) rather than hand-rolled
  `process_turn_finalized` calls.
- **R1.4** Carry the LoCoMo `dia_id` as the turn id so it lands in the bead's
  native `source_turn_ids`.
- **R1.5** Stop forcing `max_compaction`. Let Core Memory's natural compaction
  policy run; with correctly-sized sessions it will not mass-collapse.
- **R1.6** Drain async jobs after ingest before the semantic build (current
  behavior — retain).

### Phase 2 — Canonical retrieval & scoring (demo repo)

- **R2.1** Retrieve per question via the canonical `core_recall` agent, not
  `memory_tools.execute`. Remove the demo-specific trace/hydrate/rerank stack.
- **R2.2** Score evidence recall by intersecting each retrieved bead's native
  `source_turn_ids` with the gold `dia_id` set. Delete the
  `metadata.locomo_dia_id` side-channel and `_bead_for_turn` reverse lookup.
- **R2.3** Report real `claims_written` counts; remove the hardcoded `0`.
- **R2.4** The run report must record the compaction policy in effect, the
  number of visible beads in the semantic index, and the ingestion/retrieval
  API versions, so a reader can audit fidelity.

### Phase 3 — Move harness ownership upstream (Core Memory repo)

- **R3.1** Add a real-LoCoMo benchmark to the Core-Memory repo (new
  `benchmarks/locomo/`, or extend `benchmarks/locomo_like/`) that owns
  ingestion, retrieval, and scoring semantics and runs in Core Memory CI.
- **R3.2** Re-pin the demo to the new Core Memory commit.
- **R3.3** Reduce the demo's `app/benchmarks/locomo_*` to dataset provisioning,
  job dispatch, and report rendering. Delete demo-owned ingestion/retrieval/
  scoring code.

### Phase 4 — Optional Core Memory fix

- **R4.1** If recall@k scoring must work with compaction **on**: make compaction
  union `source_turn_ids` from merged members so compacted beads remain
  evidence-addressable (closes RC4). Only required if Decision D1 selects a
  recall@k contract and a compaction-on eval mode is desired.

## 7. Open decisions

- **D1 — Scoring contract (UNRESOLVED).** Options:
  - **(a) LoCoMo-paper recall@k + F1** — current report format, comparable to
    published LoCoMo numbers. Requires turn-addressable beads (Phase 1
    delivers this); needs Phase 4 if compaction is ever on.
  - **(b) Core Memory answer-class scoring** — adopt the canonical
    `locomo_like` contract (answer_current / historical / partial / abstain +
    grounding-hash). Compaction-compatible, but not comparable to published
    LoCoMo recall numbers.
  - **(c) Both, side by side** — report retrieval quality and end-to-end
    answer quality independently.

  **Recommendation:** (a) as the headline metric — it is what "benchmark
  claims" implies and what the demo already surfaces — with (b) added later if
  an answer-quality view is wanted. This PRD's Phase 1/2 requirements assume (a).

## 8. Acceptance criteria

- A `locomo_mini` run over `conv-26` produces a semantic index with one visible
  bead **per surviving memory unit**, not 1 total (expect tens–hundreds).
- Across 50 QA cases, retrieved beads span **multiple distinct bead ids**, not 1.
- `raw_result_count > 0` for the large majority of cases.
- Evidence recall and answer F1 are materially non-zero and stable across two
  identical runs (single-run variance noted).
- No code path stamps or reads `metadata.locomo_dia_id` for scoring; provenance
  comes from `source_turn_ids`.
- The report records compaction policy, visible-bead count, and API versions.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Per-session ingest still overflows a window for long LoCoMo sessions | Measure session sizes; if any session exceeds the window, that is correct Core Memory behavior — score through it (Phase 4) rather than suppress it. |
| `core_recall` returns a different result shape than `memory_tools.execute` | Phase 2 adapts the scorer to the canonical `RecallResult` contract; this is expected adapter surface. |
| Phase 3 needs Core-Memory repo write access not available from the demo session | Prepare the upstream harness as a PR-ready patch; land it in the Core-Memory repo separately, then re-pin. |
| Disabling forced compaction changes other demo flows that reuse the path | `ingest_locomo_samples_through_core_memory` is benchmark-specific; verify no shared caller depends on `max_compaction>=4`. |

## 10. Sequencing

1. **M1** — Phase 1 (R1.1–R1.6). One PR. Exit: faithful turn-by-turn ingest;
   semantic index holds many beads.
2. **M2** — Phase 2 (R2.1–R2.4). One PR. Exit: non-zero, reproducible scores
   via canonical retrieval + native provenance.
3. **M3** — Phase 3 (R3.1–R3.3). Cross-repo: upstream harness PR, then demo
   re-pin + delete demo-owned semantics.
4. **M4** — Phase 4 (R4.1), only if D1 requires compaction-on recall@k.

## Appendix — key references

Demo repo (`Core-Memory-Demo`):
- `backend/app/core/runtime.py` — `ingest_locomo_samples_through_core_memory`
  (490), `_replay_locomo_row` (443), `_process_user_assistant_turn_finalized`
  (70).
- `backend/app/benchmarks/locomo_runner.py` — retrieval + scoring.

Core Memory (pinned `b4e7167`):
- `core_memory/transcript_ingest.py` — `ingest_transcript` (295).
- `core_memory/runtime/engine.py` — `process_turn_finalized`, `source_turn_ids`
  population (87, 284).
- `core_memory/retrieval/agent.py` — `core_recall`.
- `core_memory/persistence/store_compaction_ops.py` — compaction (no
  `source_turn_ids` union — RC4).
- `benchmarks/locomo_like/runner.py` — canonical harness (`run_benchmark` 809,
  `main` 931).
