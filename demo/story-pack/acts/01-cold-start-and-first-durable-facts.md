# Act 01: Cold Start and First Durable Facts

Start on a clean memory root. These turns establish the first durable Northstar facts and use public inspect surfaces (`Claims`, `Graph`, `Entities`, `Runtime`) as the only read authority. Suggested session id: `cm-story-s1`.

## Turn 001: Show the cold-start baseline
**Send:** `Before I give you any project context, what database are we using and why?`
**Point out:**
- Chat should answer generically or partially because no durable Claims exist yet.
- Runtime last-answer diagnostics should show weak grounding and no durable anchor.
- This is the baseline before canonical turn writing starts.
**Say:** "We are starting with no durable project memory."

## Turn 002: Establish the product entity
**Send:** `Northstar is a regulated analytics SaaS platform. Record that as a stable product fact.`
**Point out:**
- Claims should now show a stable product fact for Northstar.
- Entities should add `Northstar` as the primary product entity.
- Graph should treat this as foundational context for later decisions.
**Say:** "Northstar is now an anchored product entity."

## Turn 003: Capture the database decision
**Send:** `We chose PostgreSQL over MySQL and SQLite. Record that as the current database decision for Northstar.`
**Point out:**
- Claims should show PostgreSQL as the active database choice.
- Graph should attach the decision to the Northstar product entity.
- Provenance should point back to this turn as the source of record.
**Say:** "The database decision is now durable."

## Turn 004: Add the database rationale
**Send:** `PostgreSQL won because JSONB fit our tenant configuration data and it was about 2x faster on a representative JSON workload. Record that rationale too.`
**Point out:**
- Claims should enrich the database decision with concrete supporting reasons.
- Graph should connect evidence and rationale back to the PostgreSQL decision.
- This turn should strengthen later causal answers instead of leaving the choice unexplained.
**Say:** "The why is now stored with the decision."

## Turn 005: Record the compliance issue
**Send:** `Legal flagged our session token storage as non-compliant. Record that compliance issue for Northstar.`
**Point out:**
- Claims should add a compliance or risk fact tied to session token storage.
- Entities should now include the risky auth pattern as something inspectable.
- Graph should show the first compliance pressure entering the story.
**Say:** "Compliance pressure is now part of memory."

## Turn 006: Record the migration goal
**Send:** `We need to migrate authentication to OAuth2 by June 30, 2026 because of that finding. Record the goal and deadline.`
**Point out:**
- Claims should show OAuth2 as the current auth target with a dated deadline.
- Graph should link the legal finding to the migration goal.
- The deadline should be inspectable later through claim history.
**Say:** "The auth goal is now explicit and dated."

## Turn 007: Inspect the first claim set
**Send:** `Show the current Claims view for Northstar and separate product, database, and compliance slots.`
**Point out:**
- Claims should now separate product identity, database decision, compliance issue, and auth goal.
- Any missing slot should be obvious without reading raw storage.
- This is the first claim-first proof that the read model is live.
**Say:** "The claim model should already be organizing the facts."

## Turn 008: Inspect the first graph chain
**Send:** `Open the Graph reasoning for the PostgreSQL decision and tell me which source turns anchor it.`
**Point out:**
- Graph should show the PostgreSQL node connected to its rationale.
- Provenance should reference the turns that introduced the decision and supporting evidence.
- The explanation should stay on public inspect surfaces, not file inspection.
**Say:** "We can already trace this decision back to its source turns."

## Turn 009: Ask a grounded factual question
**Send:** `What database are we using now, and why? Ground the answer only in remembered facts.`
**Point out:**
- Chat should now answer specifically with PostgreSQL, JSONB, and the representative workload result.
- Runtime last-answer diagnostics should show a grounded source surface instead of generic guessing.
- This is the first clear behavior change from durable memory.
**Say:** "The answer should now be specific because memory exists."

## Turn 010: Ask a grounded compliance question
**Send:** `What auth problem are we trying to solve right now?`
**Point out:**
- Chat should ground the answer in the stored legal finding and OAuth2 goal.
- Claims should still show the compliance fact as active, not historical.
- Diagnostics should prefer a grounded answer over a broad security lecture.
**Say:** "The auth answer should stay anchored to the legal finding."

## Turn 011: Test a contradiction against memory
**Send:** `If someone proposed MySQL because it sounds simpler, what would memory say against that?`
**Point out:**
- Chat should rebut the suggestion with the stored PostgreSQL decision and rationale.
- Graph should support a causal answer from evidence to decision.
- The answer should stay narrow and not invent new tradeoffs.
**Say:** "Memory should push back with the actual recorded reasons."

## Turn 012: Record the benchmark lesson
**Send:** `Add this lesson: representative benchmarks matter more than synthetic benchmarks when we choose infrastructure.`
**Point out:**
- Claims should add a lesson-like fact distinct from the database decision itself.
- Graph should connect the lesson to the PostgreSQL decision as supporting precedent.
- This gives later causal answers a reusable learning, not just a one-off fact.
**Say:** "We are storing the lesson, not just the result."

## Turn 013: Trace the lesson back to the decision
**Send:** `Explain how the benchmark lesson relates to the PostgreSQL decision in the Graph.`
**Point out:**
- Graph should show a clean path from lesson to decision.
- Chat should answer causally rather than restating both facts side by side.
- Provenance should still stay turn-linked and inspectable.
**Say:** "The lesson should already have structural context."

## Turn 014: Inspect the first entity set
**Send:** `Show the Entities that should exist so far: Northstar, PostgreSQL, OAuth2, Legal, and session token storage.`
**Point out:**
- Entities should now include the product, database, auth target, and compliance-related concepts.
- Alias counts may still be minimal, which is fine at this stage.
- This proves entity awareness starts early, not only after merge review.
**Say:** "The entity registry should be small but already meaningful."

## Turn 015: Check durability before a session break
**Send:** `Which of the current facts look durable enough to carry into the next session, and which ones would you still avoid overstating?`
**Point out:**
- Chat should clearly separate durable facts from anything still too thinly supported.
- Claims should make it easy to identify the strongest active slots.
- This is a good place to emphasize partial over overclaiming.
**Say:** "We want durable recall without pretending to know more than we do."

## Turn 016: Close the first canon
**Send:** `Close Act 1 with a grounded summary of Northstar's first durable facts.`
**Point out:**
- Chat should summarize Northstar, PostgreSQL, the benchmark rationale, the legal finding, and the OAuth2 goal.
- Runtime diagnostics should still indicate a grounded answer path.
- This summary becomes the anchor for the next act.
**Say:** "The first durable canon is now locked in."
