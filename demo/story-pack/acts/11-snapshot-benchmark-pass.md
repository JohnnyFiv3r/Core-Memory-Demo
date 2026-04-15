# Act 11: Snapshot Benchmark Pass

This act prepares and interprets an isolated snapshot benchmark without mutating live demo memory. Use `Benchmark` controls and benchmark drilldown surfaces as the authority for this chapter. Suggested session id: `cm-story-s2`.

## Turn 175: Summarize the snapshot target
**Send:** `Before we run a benchmark, summarize the current canon that a snapshot root should preserve: Compass naming, WorkOS, Qdrant, queue mitigations, and Mercury as pilot customer.`
**Point out:**
- Chat should summarize the current-state canon clearly before any benchmark run starts.
- This creates the benchmark expectation set without touching live memory.
- The summary should stay grounded in the current claim model.
**Say:** "We need to know exactly what the snapshot should preserve."

## Turn 176: Explain why snapshot mode is safe
**Send:** `Explain why a snapshot benchmark is safer than a live-memory benchmark for this story pack.`
**Point out:**
- Benchmark reasoning should emphasize isolation from live demo memory.
- The answer should frame snapshot mode as copied state, not live mutation.
- This is the guardrail explanation for the chapter.
**Say:** "Benchmark safety matters as much as the score."

## Turn 177: Predict likely weak buckets
**Send:** `What question buckets are most likely to fail in snapshot benchmark mode: temporal, entity, causal, or exact factual?`
**Point out:**
- Chat should predict temporal and entity questions as the likeliest stress points.
- The answer should distinguish concentrated weakness from overall failure.
- This sets up the later drilldown categories.
**Say:** "We care about the shape of failure, not just pass rate."

## Turn 178: Explain the weakness shape
**Send:** `Why are temporal and entity questions the most likely weak spots after this many turns?`
**Point out:**
- Chat should ground the answer in historical layering and alias complexity.
- The explanation should stay tied to the story's actual conflict and merge history.
- This is a theory-of-failure turn, not a run result yet.
**Say:** "The hardest questions should line up with the richest history."

## Turn 179: Test a temporal benchmark case
**Send:** `If a benchmark case asks what the product was called before Compass, what should the system rely on?`
**Point out:**
- Chat should point to `as_of` naming history rather than current-state alias flattening.
- This is the clearest example of a temporal benchmark case.
- The answer should stay benchmark-oriented and precise.
**Say:** "Temporal benchmark cases should lean on the historical naming path."

## Turn 180: Test a provenance-heavy benchmark case
**Send:** `If a benchmark case asks who approved degraded mode, what chain should the system traverse?`
**Point out:**
- Chat should rely on the degraded-week approval chain involving Maya Chen.
- This mixes entity identity, runtime history, and causal explanation.
- It is a good benchmark example because it is not a single flat fact.
**Say:** "Some benchmark cases are really chain-traversal tests."

## Turn 181: Test a current-state benchmark case
**Send:** `If a benchmark case asks what the current auth vendor is, what current-state slot should dominate?`
**Point out:**
- Chat should answer with WorkOS from the active auth-vendor slot.
- The answer should still preserve older candidates as history only if asked.
- This is the positive-control style benchmark question.
**Say:** "Current-state cases should be clean and unambiguous now."

## Turn 182: Test a historical-backend benchmark case
**Send:** `If a benchmark case asks what we used before Qdrant, how should historical context be surfaced?`
**Point out:**
- Chat should name pgvector as the earlier direction and local/staging fallback context.
- The answer should rely on history rather than treating pgvector as current production truth.
- This is the backend-focused benchmark example.
**Say:** "The benchmark needs to reward historical accuracy, not just current-state recall."

## Turn 183: Ask what to inspect on a miss
**Send:** `What Runtime or diagnostics fields should we inspect when a benchmark answer fails?`
**Point out:**
- Benchmark drilldown should highlight answer outcome, source surface, and anchor reason.
- The answer should stay on benchmark and answer-diagnostic surfaces, not internal code paths.
- This is the operator workflow question for failing cases.
**Say:** "A miss should tell us where to look next."

## Turn 184: Ask how to read drilldown fields
**Send:** `How should source_surface, anchor_reason, and answer_outcome guide failing-case drilldown?`
**Point out:**
- Chat should explain how these fields help separate current-state misses from historical and entity misses.
- The answer should give the operator language for interpreting failure shape.
- This is the benchmark-analysis policy turn.
**Say:** "The drilldown labels should make the miss legible immediately."

## Turn 185: Ask which facts should not be benchmarked as current truth
**Send:** `Which facts would you refuse to benchmark as current truth because they are only historical?`
**Point out:**
- Chat should name earlier Northstar naming, Auth0 leadership, and pgvector-as-production as historical-only truths.
- This protects the benchmark from grading historical facts as current canon.
- The answer should remain precise and grounded.
**Say:** "Benchmarks need the right truth target before they need a good score."

## Turn 186: Close the pre-run benchmark expectations
**Send:** `Close Act 11 with benchmark expectations and the key areas to watch in snapshot mode.`
**Point out:**
- Chat should summarize isolation, temporal/entity weak spots, and the current-state control cases.
- This is the handoff into the actual snapshot benchmark checkpoint.
- The chapter should end with operator expectations, not just product summary.
**Say:** "We now know what the snapshot run should prove and where it may struggle."

## Checkpoint: Snapshot Benchmark Run

Run the benchmark in `snapshot` mode now. This checkpoint does not count as a turn.

- Operator action: use the Benchmark controls to run against a copied snapshot root.
- Expected result: benchmark results and drilldown appear without mutating live story memory.
- Review focus: temporal misses, entity/alias misses, `source_surface`, `anchor_reason`, and `answer_outcome`.
