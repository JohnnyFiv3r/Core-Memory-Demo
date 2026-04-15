# Core Memory Demo Story Pack

This pack is a standalone set of Markdown demo-script messages for a Core Memory testing harness. It contains 12 chapter-style act files totaling 204 sendable user turns, plus a master outline, an index, and a replay manifest.

## What This Pack Assumes

- The harness primarily sends user-side prompts rather than deterministic full turn pairs.
- The operator validates behavior through public read-model surfaces such as `Claims`, `Graph`, `Entities`, `Runtime`, hydration, and `Benchmark`.
- Benchmark runs use isolated roots and must not mutate the live demo memory.

## Pack Layout

- `acts/01-cold-start-and-first-durable-facts.md`
- `acts/02-architecture-expansion.md`
- `acts/03-entity-seeding-and-naming-drift.md`
- `acts/04-first-flush-and-reset-proof-recall.md`
- `acts/05-compliance-churn-and-claim-history.md`
- `acts/06-search-and-semantic-strategy-debate.md`
- `acts/07-degraded-retrieval-week.md`
- `acts/08-queue-backpressure-postmortem.md`
- `acts/09-rebrand-and-merge-review.md`
- `acts/10-historical-reconciliation.md`
- `acts/11-snapshot-benchmark-pass.md`
- `acts/12-launch-clean-benchmark-final-flush.md`
- `MASTER_OUTLINE.md`
- `INDEX.md`
- `replay-order.json`

## Story Shape

- Acts `01-04` build the initial Northstar canon and cross the first session boundary from `cm-story-s1` to `cm-story-s2`.
- Acts `05-10` create the conflict-heavy middle: auth churn, backend debate, degraded retrieval, queue backpressure, rebrand, and historical reconciliation.
- Acts `11-12` focus on isolated benchmarking, launch-state verification, and final flush behavior.

## Checkpoint Semantics

- After Turn `058`: flush the session and continue in `cm-story-s2`.
- After Turn `186`: run a `snapshot` benchmark against copied state.
- After Turn `200`: run a `clean` benchmark against a fresh isolated root.
- After Turn `204`: run the final session flush.

Checkpoint sections do not count as turns.

## Schema

Every turn uses the same normalized chapter format:

```md
## Turn 001: [Outcome title]
**Send:** `[exact user prompt]`
**Point out:**
- [expected Claims / Graph / Entities / Runtime / Benchmark evidence]
- [expected observability note]
**Say:** "[short interpretation line]"
```

Some acts also include explicit checkpoint sections for flushes or benchmark runs.

## Recommended Harness Flow

1. Start with `MASTER_OUTLINE.md` if you want the narrative arc first.
2. Use `INDEX.md` to jump to a specific turn range or behavior.
3. Replay acts in the order defined by `replay-order.json`.
4. Treat checkpoint sections as operator actions, not chat turns.

## Guardrails

- Prefer grounded, partial, or abstaining answers over overclaiming.
- Use `as_of` replay for historical truth instead of flattening the timeline into a single current-state answer.
- Keep product, service, person, and customer entities distinct unless the act explicitly calls for merge adjudication.
- Keep benchmark interpretation isolated from live-memory mutation claims.
