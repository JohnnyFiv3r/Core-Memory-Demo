# Act 12: Launch, Clean Benchmark, Final Flush

This final act closes the product story, compares a clean benchmark to the earlier snapshot run, and ends with a final session flush. Keep current-state answers grounded in `Claims` and use checkpoint sections for the benchmark and final boundary. Suggested session id: `cm-story-s2`.

## Turn 187: Record the final auth cutover
**Send:** `Record that on August 15, 2026 the WorkOS cutover completed and Compass stopped relying on the old session token pattern.`
**Point out:**
- Claims should now show WorkOS as completed launch-state auth, not just selected vendor.
- Graph should connect the final cutover back to the original legal finding.
- This closes the longest compliance arc in the pack.
**Say:** "The auth migration is now complete, not just planned."

## Turn 188: Record the first launch customer
**Send:** `Record that Mercury Health went live on Compass after the WorkOS cutover completed.`
**Point out:**
- Claims should move Mercury from pilot-only context into a launch outcome.
- Graph should connect Mercury's launch to the resolved auth work.
- This is the first customer outcome of the final act.
**Say:** "The pilot customer has now crossed into launch reality."

## Turn 189: Record the second launch customer
**Send:** `Record that Redwood Clinics became the second launch customer for Compass.`
**Point out:**
- Claims should add Redwood Clinics as a new launch-stage customer entity.
- Entities should keep Redwood distinct from Mercury while still under the Compass product.
- This expands the launch state beyond the original pilot.
**Say:** "Launch is now bigger than the original pilot customer."

## Turn 190: Record which mitigations survived into launch
**Send:** `Record that the queue-splitting and batch-cap mitigations stayed in place for launch week.`
**Point out:**
- Claims should make the incident mitigations part of the launch posture.
- Graph should connect the postmortem decisions to present-day operations.
- This is the operational continuity payoff from Act 8.
**Say:** "The launch posture is built on what the incident taught us."

## Turn 191: Record the launch backend posture
**Send:** `Record that Compass launched with Qdrant in production and pgvector reserved for local and staging workflows.`
**Point out:**
- Claims should now show the resolved backend choice in the actual launch state.
- Historical pgvector context should remain preserved without confusing current production.
- This is the backend equivalent of the final auth cutover.
**Say:** "The production backend story is now fully current-state."

## Turn 192: Ask for the launch-state summary
**Send:** `What is the current launch-state summary for Compass right now?`
**Point out:**
- Chat should summarize Compass naming, WorkOS, Qdrant, Mercury launch, Redwood launch, and the stable runtime posture.
- The answer should stay cleanly current-state and grounded.
- This is the first big synthesis after the launch facts land.
**Say:** "Current-state answers should now feel stable and complete."

## Turn 193: Ask for the current owner map
**Send:** `Who are the current named owners for security, product, and platform?`
**Point out:**
- Chat should answer with Maya Chen, Priya Nair, and Luis Ortega.
- Entities should still resolve aliases correctly after all the history and rebrand work.
- This is a long-range entity continuity check near the end of the pack.
**Say:** "The people canon should still be intact at launch."

## Turn 194: Ask whether the original database decision still stands
**Send:** `What was the original database decision, and does it still remain current at launch?`
**Point out:**
- Chat should still recover PostgreSQL, JSONB, and the representative-workload rationale.
- Claims should show this as one of the earliest facts that stayed current the whole time.
- This is a long-range architecture continuity check.
**Say:** "Some early facts should survive the whole story unchanged."

## Turn 195: Ask for the compliance arc
**Send:** `What was the path from the legal finding to final WorkOS cutover?`
**Point out:**
- Graph should support a full causal answer from non-compliant tokens to OAuth2 goal, slip, conflict, vendor resolution, and cutover.
- The answer should be timeline-aware instead of flattened.
- This is the longest chain-tracing question in the whole pack.
**Say:** "The auth journey should now be fully explainable from memory."

## Turn 196: Ask for the operations arc
**Send:** `What was the path from degraded week and queue backpressure to a stable launch posture?`
**Point out:**
- Graph should connect degraded-week caution, the incident, mitigations, and launch-state runtime posture.
- Chat should keep the two operational events distinct while relating them properly.
- This is the operational counterpart to Turn 195.
**Say:** "The launch posture should now reflect what operations learned."

## Turn 197: Test renamed-product recall at launch
**Send:** `If I ask about Northstar now, how should you answer at launch without losing the historical alias?`
**Point out:**
- Chat should answer with Compass as current while preserving Northstar as historical.
- Entities should support renamed lookup cleanly.
- This is a final rename-behavior check in current state.
**Say:** "Historical names should still resolve cleanly after launch."

## Turn 198: Test historical vendor recall at launch
**Send:** `If I ask about Auth0 now, how should you explain its role in the story without treating it as current?`
**Point out:**
- Chat should explain Auth0 as an earlier leading candidate, not the current vendor.
- Claims history should make that explanation easy and precise.
- This is a final historical-vendor honesty check.
**Say:** "Old contenders should stay visible without becoming present truth."

## Turn 199: Test historical backend recall at launch
**Send:** `If I ask about pgvector now, how should you explain its role without treating it as the current production backend?`
**Point out:**
- Chat should answer with pgvector as early/simple default and local-staging context.
- Claims should keep Qdrant as current production without losing pgvector history.
- This is the final backend honesty check.
**Say:** "Past backend choices should stay queryable but not current."

## Turn 200: Summarize the current canon before the clean run
**Send:** `Give me a grounded current-state summary that includes Compass, WorkOS, Qdrant, Mercury Health, Redwood Clinics, and the launch posture.`
**Point out:**
- Chat should summarize the stable launch-state canon compactly and correctly.
- This is the final current-state baseline before the clean benchmark checkpoint.
- The answer should feel definitive without overstating unknowns.
**Say:** "We want one clean launch-state snapshot before the comparison run."

## Checkpoint: Clean Benchmark Run

Run the benchmark in `clean` mode now. This checkpoint does not count as a turn.

- Operator action: run the benchmark against a fresh clean root with no snapshot preload.
- Expected result: a control run that can be compared to the earlier snapshot benchmark without touching live memory.
- Review focus: score deltas, temporal/entity miss shape, and whether the clean baseline changes conclusions.

## Turn 201: Compare the clean run to the snapshot run
**Send:** `Compare the clean benchmark to the earlier snapshot run. Which buckets improved and which still need attention?`
**Point out:**
- Benchmark drilldown should compare isolated clean results to the earlier snapshot run clearly.
- The answer should focus on bucket shape, especially temporal and entity cases.
- This is the only direct clean-vs-snapshot comparison turn in the pack.
**Say:** "The comparison should explain the difference in shape, not just the difference in score."

## Turn 202: Ask what stayed current versus changed
**Send:** `What long-range facts from the beginning of the story are still current and what changed over time?`
**Point out:**
- Chat should distinguish stable truths like PostgreSQL from changed truths like product name, auth vendor, and production backend.
- This is the broadest whole-pack continuity check.
- The answer should stay organized and grounded in claim history.
**Say:** "The system should now be able to separate continuity from change cleanly."

## Turn 203: Ask what not to overclaim
**Send:** `What should an operator still avoid claiming even after launch because the memory only supports a narrower statement?`
**Point out:**
- Chat should still surface areas where history or scope makes a narrower answer safer.
- This keeps the pack aligned with the demo's honesty-first posture.
- The answer should not invent uncertainty, only preserve real limits.
**Say:** "Launch does not remove the need for careful wording."

## Turn 204: Close the full story pack
**Send:** `Close the full story pack with a grounded end-to-end summary from the PostgreSQL decision to Compass launch.`
**Point out:**
- Chat should summarize the entire arc: database decision, compliance pressure, auth conflict, semantic strategy, degraded week, queue postmortem, rebrand, launch, and final current state.
- The answer should feel comprehensive but still traceable to memory surfaces.
- This is the final recall proof before the last flush.
**Say:** "The whole story should now be recoverable as one grounded arc."

## Checkpoint: Final Flush

Flush the session after Turn 204. This checkpoint does not count as a turn.

- Operator action: flush `cm-story-s2` after the final summary.
- Expected result: the end state is archived cleanly, continuity is rebuilt, and the full story remains retrievable.
- Review focus: final archive continuity, stable current-state canon, and post-boundary recall if you choose to continue testing.
