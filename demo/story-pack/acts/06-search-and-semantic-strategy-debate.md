# Act 06: Search and Semantic Strategy Debate

This act moves from compliance churn into retrieval architecture. Keep the story grounded in claim timelines, runtime expectations, and graph-linked rationale rather than treating the backend choice as a single static fact. Suggested session id: `cm-story-s2`.

## Turn 087: Record the simple default
**Send:** `Record that the simplest initial semantic plan was pgvector inside PostgreSQL so the team could stay on one operational stack.`
**Point out:**
- Claims should add pgvector as the first clean semantic direction.
- Graph should link this choice to the simplicity and single-stack rationale.
- This should not yet erase the possibility of a future production-specific backend.
**Say:** "The first semantic answer is simplicity."

## Turn 088: Record the dev fallback rule
**Send:** `Record that local development must still work with lexical fallback when no semantic backend is configured.`
**Point out:**
- Claims should make lexical fallback an explicit rule, not hidden behavior.
- Runtime expectations should later reflect this degraded-but-intended path.
- This is a design principle that outlives any single backend choice.
**Say:** "Fallback is now a deliberate part of the story."

## Turn 089: Record staging guidance
**Send:** `Record that staging is allowed to stay on pgvector while the team evaluates a separate production backend.`
**Point out:**
- Claims should now distinguish staging from production.
- Graph should connect staging tolerance to evaluation rather than final decision.
- This introduces environment-specific truth without causing immediate conflict.
**Say:** "Staging and production are starting to diverge on purpose."

## Turn 090: Record the leading production candidate
**Send:** `Record that Qdrant became the leading production candidate after load tests showed cleaner isolation for semantic rebuilds.`
**Point out:**
- Claims should add Qdrant as a stronger production direction with concrete evidence.
- The semantic backend slot should now begin to look contested or evolving.
- This creates the historical trail needed for later `as_of` replay.
**Say:** "Production is now leaning toward a different answer than the simple default."

## Turn 091: Record the multi-worker constraint
**Send:** `Record that multi-worker safety matters because semantic rebuilds should not starve other side effects.`
**Point out:**
- Claims should add a runtime-driven constraint to the backend decision.
- Graph should connect backend choice to worker safety and future queue behavior.
- This sets up the incident story in later acts.
**Say:** "The backend debate is now tied to runtime safety, not just taste."

## Turn 092: Record the connectivity expectation
**Send:** `Record that external semantic connectivity will exist in production but should surface clearly in Runtime diagnostics.`
**Point out:**
- Claims should make observability part of the backend plan.
- Runtime should later expose backend health instead of hiding dependency failures.
- This bridges architectural choice and operator visibility.
**Say:** "Production connectivity needs explicit observability."

## Turn 093: Inspect semantic slot status
**Send:** `Show the current semantic backend claim slots and tell me which ones are active versus conflict.`
**Point out:**
- Claims should show pgvector history and a stronger Qdrant production direction without flattening them together.
- The answer should be honest if parts of the slot are still in conflict.
- This is the first direct claim-first inspection of the semantic debate.
**Say:** "The slot should now show both history and tension."

## Turn 094: Replay the early semantic truth
**Send:** `As of the first proposal, what was the semantic direction?`
**Point out:**
- `as_of` replay should return the simple pgvector plan for the earliest slice.
- The answer should not leak later Qdrant conclusions backward into history.
- This is the semantic equivalent of the vendor timeline checks from Act 5.
**Say:** "Historical backend truth should stay time-scoped."

## Turn 095: Replay the post-load-test truth
**Send:** `As of after the load test, what changed about the production recommendation?`
**Point out:**
- `as_of` replay should surface Qdrant as the stronger production direction for that slice.
- Graph should connect the change to the load-test and isolation rationale.
- This proves the semantic debate is evolving, not contradictory noise.
**Say:** "The recommendation should move because the evidence changed."

## Turn 096: Ask about dev behavior under missing backend
**Send:** `What is the current guidance for local development if Qdrant is unavailable?`
**Point out:**
- Chat should ground the answer in the lexical-fallback rule and dev/staging distinction.
- Runtime expectations should keep degraded behavior visible.
- The answer should stay practical and narrow.
**Say:** "Development should stay usable even without the full semantic stack."

## Turn 097: Ask about staging versus production
**Send:** `What is the current guidance for staging versus production?`
**Point out:**
- Chat should distinguish staging on pgvector from production leaning toward Qdrant.
- Claims should support the environment split explicitly.
- This is a good test of environment-scoped current state.
**Say:** "The answer should preserve the environment boundary cleanly."

## Turn 098: Inspect runtime expectations
**Send:** `Show the Runtime expectations we should care about for semantic backend health and degraded mode.`
**Point out:**
- Runtime should be framed in terms of backend status, warnings, and degraded visibility.
- This act is now preparing the operator to reason about degraded mode later.
- The answer should stay on observability surfaces rather than implementation internals.
**Say:** "We are turning architecture into operator-visible expectations."

## Turn 099: Ask which claim is strongest right now
**Send:** `Which claim is stronger right now: pgvector everywhere, or pgvector local plus Qdrant in production?`
**Point out:**
- Claims should show why the split-environment answer has become stronger.
- If the slot is not fully resolved, the answer should still say so.
- This is a direct current-state versus history judgment call.
**Say:** "The system should prefer the stronger current reading without rewriting history."

## Turn 100: Connect the backend debate to worker safety
**Send:** `Explain how the semantic backend debate intersects with the queue and worker model.`
**Point out:**
- Graph should connect backend choice, rebuild behavior, and shared-worker safety.
- This creates a causal chain that later incident reasoning can reuse.
- The answer should stay grounded in stored constraints and evidence.
**Say:** "The backend story is already touching runtime operations."

## Turn 101: Test conservative current-state answering
**Send:** `If someone asks whether Qdrant is final right now, should the answer be active or partial? Explain from claim history.`
**Point out:**
- Chat should answer conservatively if the current production direction is still not fully finalized here.
- Claims history should explain why Qdrant is strong but not yet absolute.
- This mirrors the cautious vendor-answer pattern from Act 5.
**Say:** "Strong direction is not the same thing as final truth."

## Turn 102: Inspect the causal graph for the backend shift
**Send:** `Show the Graph chain from simplicity goals to load-test evidence to the production-backend recommendation.`
**Point out:**
- Graph should connect pgvector's simplicity to later Qdrant evidence cleanly.
- Provenance should still trace back to the turns that introduced each step.
- This is a structural proof that the debate is explainable, not ad hoc.
**Say:** "The backend shift should already be visible as a reasoned chain."

## Turn 103: Inspect current, historical, and tentative pieces
**Send:** `Which parts of the semantic strategy are current, which are historical, and which are still tentative?`
**Point out:**
- Claims should separate dev fallback, staging posture, and production direction clearly.
- Historical pgvector reasoning should stay visible even as Qdrant strengthens.
- Any remaining uncertainty should be explicit instead of flattened away.
**Say:** "This act should leave a clean layered state behind."

## Turn 104: Close the semantic debate state
**Send:** `Close Act 6 with a grounded summary of the search and semantic strategy debate.`
**Point out:**
- Chat should summarize pgvector simplicity, lexical fallback, staging tolerance, and Qdrant's stronger production case.
- Claims and Graph should make the summary auditable.
- This is the setup for degraded retrieval week in the next act.
**Say:** "The semantic story is now layered enough to survive stress."
