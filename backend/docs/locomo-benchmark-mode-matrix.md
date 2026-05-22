# LoCoMo Benchmark Mode Matrix

Status: Phase 0 implementation/fencing note  
Authoritative plan: `../../docs/locomo-lifecycle-benchmark-prd.md`

## Purpose

This file fences existing LoCoMo/demo benchmark behavior from the new faithful lifecycle benchmark path. Existing work remains useful, but it must be labeled by mode so fixture/demo shortcuts cannot be mistaken for authoritative benchmark behavior.

## Modes

| Mode | Purpose | Lifecycle faithful? | Allowed shortcuts | Should drive benchmark claims? |
| --- | --- | --- | --- | --- |
| `fixture_smoke` | Fast CI/demo plumbing validation | No | Synthetic fixtures, direct bead setup, seeded crawler updates, manual adjacency edges | No |
| `demo_bead_direct` | Historical/demo compatibility and UI artifact comparison | No | Bead-direct ingest, demo-specific sample limiting, legacy report compatibility | No |
| `locomo_native_lifecycle` | Authoritative LoCoMo benchmark execution | Yes | None by default; debug overrides must be explicit in report metadata | Yes |

## Required Report Fields

Every LoCoMo-related report should include enough metadata to identify its mode:

```json
{
  "dataset_mode": "fixture_smoke | demo_bead_direct | locomo_native_lifecycle",
  "lifecycle_faithful": false,
  "shortcut_guards": {
    "synthetic_crawler_updates": false,
    "synthetic_temporal_edges": false,
    "bead_direct_ingest": false,
    "oracle_gold_used": false,
    "benchmark_aware_answer_prompt": false
  }
}
```

For `locomo_native_lifecycle`, `lifecycle_faithful` must be `true` and every shortcut guard must be `false` unless a named debug override is intentionally enabled and surfaced in the report.

## Shortcut Classification

### Fixture/demo only

The following are valid only outside `locomo_native_lifecycle`:

- Directly materializing LoCoMo source conversation content as beads.
- Injecting benchmark-generated `metadata.crawler_updates` for source turns.
- Adding manual temporal/adjacency graph edges to make coverage look better.
- Keying ingestion/dedupe by raw `dia_id` without sample scoping.
- Running only one retrieval effort for a QA case.
- Using tiny fixture `k` values as authoritative benchmark retrieval limits.

### Faithful lifecycle only

The authoritative path must:

- Adapt native LoCoMo samples into normalized conversations and QA cases.
- Replay every source turn through `process_turn_finalized`.
- Let capture, claims, crawler, and association graph behavior emerge from runtime hooks.
- Run `process_flush` after replay and before QA.
- Run retrieval efforts in exact order: `low`, `medium`, `high`.
- Keep QA retrieval scoped to the full relevant bead corpus, not just rolling-window context.
- Optionally write one QA bead per QA case after retrieval/answer generation.

## Implementation Guardrail

Any new code that enters `locomo_native_lifecycle` should construct a shortcut flag object equivalent to:

```python
{
    "synthetic_crawler_updates": False,
    "synthetic_temporal_edges": False,
    "bead_direct_ingest": False,
    "oracle_gold_used": False,
    "benchmark_aware_answer_prompt": False,
}
```

If any flag is true in faithful mode, the run should fail fast or be downgraded to an explicitly non-authoritative debug mode.

## Relationship to Existing Docs

- `locomo-replay-adapter-design.md` remains useful for LoCoMo source-shape and provenance notes, but any older mapping that conflicts with the PRD should yield to `locomo_native_lifecycle` requirements.
- `benchmark-tab-seeding-and-locomo-ux-seams.md` remains useful for UI orchestration, but seed-like UX must not imply seed-like shortcut ingestion in faithful mode.
- `locomo-integration-research.md` and `locomo-seed-source-contract.md` should be treated as historical/context docs unless updated to reference the mode matrix.
