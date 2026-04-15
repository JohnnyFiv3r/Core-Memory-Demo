# Act 08: Queue Backpressure Postmortem

This act explains the operational incident using an evidence -> decision -> lesson -> outcome chain that stays inspectable in `Graph`, `Runtime`, and `Claims`. Suggested session id: `cm-story-s2`.

## Turn 121: Record the incident start
**Send:** `Record that on July 11, 2026 Mercury's tenant backfill caused queue backpressure during degraded week.`
**Point out:**
- Claims should add a dated incident fact tied to Mercury's backfill.
- Graph should connect this incident to the earlier degraded-week context.
- This anchors the postmortem in a specific operational event.
**Say:** "The incident now has a named trigger and date."

## Turn 122: Record the shared-worker evidence
**Send:** `Record the evidence that semantic rebuilds and side effects were sharing one worker path and contending with each other.`
**Point out:**
- Claims should store the observed contention explicitly, not just a vague slowdown.
- Runtime and Graph should later be able to point back to this evidence.
- This is the core root-cause signal entering memory.
**Say:** "We are recording the contention, not just the symptom."

## Turn 123: Record the latency impact
**Send:** `Record that flush latency spiked above 14 minutes during the incident window.`
**Point out:**
- Claims should now include a concrete operational consequence.
- Runtime history should make this metric feel grounded rather than anecdotal.
- This fact will later support the recovery outcome comparison.
**Say:** "The impact now has a measurable number attached to it."

## Turn 124: Record the user-facing effect
**Send:** `Record that no data was lost, but answer freshness lagged because side effects were delayed.`
**Point out:**
- Claims should separate freshness lag from data loss explicitly.
- This helps later answers avoid overstating the incident.
- Graph should connect runtime delay to the 5-minute freshness SLO already in canon.
**Say:** "The incident hurt freshness, not data integrity."

## Turn 125: Inspect the incident graph chain
**Send:** `Show the Graph chain from the backfill event to the shared-worker contention evidence to the freshness impact.`
**Point out:**
- Graph should already support an evidence-to-impact chain.
- Provenance should remain visible across the incident nodes.
- This demonstrates that the postmortem is structural, not just narrative.
**Say:** "The incident should already look traceable in the graph."

## Turn 126: Inspect runtime breakdown
**Send:** `What does Runtime show for queue breakdown, retry readiness, and recent flush history when you reason about this incident?`
**Point out:**
- Runtime should surface queue state, retry timing, and flush history as part of the explanation.
- The answer should stay on public diagnostics instead of internal queue implementation details.
- This is the operator-facing runtime readout for the incident.
**Say:** "The runtime should tell the same story the graph does."

## Turn 127: Record the first mitigation decision
**Send:** `Record the decision to split queue priorities so semantic rebuilds stop blocking side effects.`
**Point out:**
- Claims should add a durable mitigation decision with clear operational intent.
- Graph should connect the decision to the shared-worker root cause evidence.
- This becomes the first permanent operational change from the incident.
**Say:** "Priority splitting is now a recorded mitigation."

## Turn 128: Record the batch-cap decision
**Send:** `Record the decision to cap backfill batch size at 500 items.`
**Point out:**
- Claims should add a second durable mitigation with a concrete threshold.
- This should connect to the lesson that large catch-up work must be bounded.
- The decision should remain inspectable for later recall and review.
**Say:** "The mitigation now has an enforceable cap."

## Turn 129: Record the retry-visibility decision
**Send:** `Record the decision to expose retry visibility more clearly in Runtime.`
**Point out:**
- Claims should tie observability changes directly to the incident outcome.
- Runtime should later be expected to surface retry state as a first-class operator signal.
- This links postmortem learning back to UI-facing diagnostics.
**Say:** "We are turning one lesson into a durable runtime surface."

## Turn 130: Inspect decision state versus observations
**Send:** `Show the current incident-response decision set and tell me which items are active fixes versus observations.`
**Point out:**
- Claims should separate evidence, decisions, and outcomes cleanly.
- This is a good test that the postmortem is structured, not blended.
- The answer should remain category-aware and inspectable.
**Say:** "We want the postmortem organized by role in the chain."

## Turn 131: Ask for the rooted cause
**Send:** `What is the root cause of the July 11 backpressure incident according to the grounded memory chain?`
**Point out:**
- Chat should answer with shared-worker contention between semantic rebuilds and side effects.
- The answer should avoid blaming degraded mode itself unless evidence supports it.
- Graph provenance should make the cause auditable.
**Say:** "The root cause should come back as a grounded chain, not a guess."

## Turn 132: Ask for the durable lesson
**Send:** `What lesson did the team take from the incident about shared worker paths?`
**Point out:**
- Chat should generalize carefully from the recorded evidence and decisions.
- Claims should support the lesson with concrete operational context.
- This is the bridge from incident to reusable memory.
**Say:** "We are storing the lesson, not just the incident facts."

## Turn 133: Record the first recovery outcome
**Send:** `Record the outcome that p95 flush latency fell below 3 minutes after queue splitting and batch caps were deployed.`
**Point out:**
- Claims should now show a measurable recovery outcome.
- Graph should connect the mitigation decisions to the improved latency result.
- This enables before-versus-after recall later.
**Say:** "Recovery now has a measurable success criterion."

## Turn 134: Record the SLO recovery
**Send:** `Record the outcome that answer freshness returned inside the 5 minute SLO after the mitigation.`
**Point out:**
- Claims should reconnect the incident resolution to the customer-facing SLO.
- This closes the loop between runtime behavior and product promise.
- The answer surface should keep this as an observed outcome, not a blanket guarantee.
**Say:** "The product promise is now part of the recovery record."

## Turn 135: Inspect the full evidence-to-outcome chain
**Send:** `Show the evidence -> decision -> lesson -> outcome chain for the incident in the Graph.`
**Point out:**
- Graph should now contain the full postmortem arc in a single inspectable path.
- Provenance should still make each step traceable to specific turns.
- This is the structural proof that the incident is fully represented.
**Say:** "The postmortem should now read like a chain, not a recap."

## Turn 136: Test overclaim resistance
**Send:** `If someone asked whether degraded mode caused the incident, how would memory answer without overclaiming?`
**Point out:**
- Chat should distinguish degraded retrieval context from the separate queue-contention root cause.
- Claims and Graph should support a careful answer that does not blur the two incidents together.
- This is another important honesty test.
**Say:** "Correlation should not get promoted to cause."

## Turn 137: Ask which facts are now durable
**Send:** `Which runtime facts from the incident are now durable enough to guide future operations?`
**Point out:**
- Chat should name the root cause, key mitigations, and recovery outcomes as reusable truths.
- Claims should make those durable operational facts easy to inspect.
- This is the operational-memory payoff of the act.
**Say:** "The postmortem should leave durable operating guidance behind."

## Turn 138: Close the postmortem
**Send:** `Close Act 8 with a grounded postmortem summary of the queue backpressure incident.`
**Point out:**
- Chat should summarize trigger, evidence, decisions, lessons, and outcomes without inventing extra detail.
- Runtime, Graph, and Claims should all support the same story.
- This closes the second major operational arc in the pack.
**Say:** "The incident is now preserved as inspectable operational memory."
