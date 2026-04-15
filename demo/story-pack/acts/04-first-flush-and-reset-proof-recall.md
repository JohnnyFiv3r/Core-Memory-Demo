# Act 04: First Flush and Reset-Proof Recall

This act crosses the first session boundary. Use the public inspect surfaces to show what is archived, what survives in continuity, and how grounded answers still work after the reset. Starts in `cm-story-s1`, then switches to `cm-story-s2` after the flush checkpoint.

## Turn 053: Review what looks durable before the boundary
**Send:** `Before we flush, list the durable facts most likely to survive a session reset.`
**Point out:**
- Chat should name the strongest active facts: PostgreSQL, the benchmark lesson, the OAuth2 goal, core architecture, and named owners.
- Claims should make clear why these facts are durable enough to carry forward.
- This sets expectations before the boundary is crossed.
**Say:** "We are naming what should survive before we test it."

## Turn 054: Inspect claim history before the flush
**Send:** `Open the claim history for the database and auth-goal slots before we cross the boundary.`
**Point out:**
- Claims should show the database slot as stable and the auth goal with its deadline.
- This is a good moment to show that temporal replay already exists even before later conflicts.
- The operator should be able to inspect history through the read model alone.
**Say:** "We can inspect the current state and its history before resetting."

## Turn 055: Inspect a causal graph edge before the flush
**Send:** `Show the graph edge that links the benchmark lesson to the PostgreSQL decision.`
**Point out:**
- Graph should show the lesson-to-decision relationship explicitly.
- Provenance should stay visible at the edge or node detail level.
- This gives a concrete structural artifact to compare after the reset.
**Say:** "We are checking one causal edge before it gets archived."

## Turn 056: Check entity readiness before continuity
**Send:** `Which aliases or entities are already normalized strongly enough to survive a reset cleanly?`
**Point out:**
- Entities should highlight the safest alias resolutions so far.
- The answer should stay explicit if some alias relationships are still tentative.
- This is a pre-reset entity confidence check.
**Say:** "Continuity should preserve strong identities without over-merging."

## Turn 057: Inspect runtime state before the flush
**Send:** `What does the current Runtime view say about queue state and pending side effects before the flush?`
**Point out:**
- Runtime should show a healthy or understandable queue state before the boundary.
- This reinforces that flush is an inspectable lifecycle event, not a hidden transition.
- The answer should stay on public runtime diagnostics.
**Say:** "We are observing runtime state before the boundary event."

## Turn 058: Predict the boundary outcome
**Send:** `Summarize what should be archived versus carried into continuity if we flush right now.`
**Point out:**
- Chat should distinguish archived detail from the rolling continuity summary.
- Hydration should be framed as recoverable detail after the boundary.
- This is the operator's prediction before the actual session flush.
**Say:** "We know what should move to archive and what should stay recallable."

## Checkpoint: Flush Session Boundary

Run the session flush now. This checkpoint does not count as a turn.

- Operator action: flush the current session after Turn 058.
- Expected effect: archive and hydration surfaces become relevant, continuity is rebuilt, and the suggested session id changes to `cm-story-s2`.
- Read authority reminder: verify the result through `Claims`, `Graph`, `Entities`, `Runtime`, hydration, and rolling/continuity surfaces only.

## Turn 059: Prove the database decision survived the reset
**Send:** `We are in a new session now. What database did we choose and why?`
**Point out:**
- Chat should still answer with PostgreSQL, JSONB, and the representative-workload rationale.
- Runtime diagnostics should show a grounded answer even though live chat history was reset.
- This is the clearest proof that continuity is working.
**Say:** "The reset should not erase durable architectural memory."

## Turn 060: Prove the auth goal survived the reset
**Send:** `In this new session, what auth goal and deadline are currently remembered?`
**Point out:**
- Chat should still recover the OAuth2 goal and June 30, 2026 deadline.
- Claims should remain the authority for current state, not remembered transcript text.
- This validates cross-session recall for a deadline-bearing fact.
**Say:** "The auth goal should survive the session boundary too."

## Turn 061: Prove the owner entities survived the reset
**Send:** `Who are Maya Chen, Priya Nair, and Luis Ortega in this project?`
**Point out:**
- Chat should still recover each owner's role from durable memory.
- Entities should resolve the named people without needing prior live context.
- This demonstrates cross-session entity continuity, not just fact carry-forward.
**Say:** "Named owners should still be retrievable after the reset."

## Turn 062: Prove the customer alias survived the reset
**Send:** `Who is Mercury, and how is that entity related to Northstar?`
**Point out:**
- Chat should resolve `Mercury` back to Mercury Health as the pilot customer.
- Entities should show the alias relationship surviving into the new session.
- This is a strong alias-continuity check.
**Say:** "Aliases should still resolve cleanly after the flush."

## Turn 063: Ask which source surfaces are active now
**Send:** `Which answer surfaces are you relying on right now: live session content, claims, graph, or archived hydration?`
**Point out:**
- Chat should describe the dominant source surface honestly.
- Runtime diagnostics should make it clear that live session history is no longer the main authority.
- This is the moment to explain archive and continuity without overclaiming.
**Say:** "We want the system to name its current grounding surface."

## Turn 064: Inspect one archived detail path
**Send:** `Show me one example of a claim or answer that is now grounded through archive or continuity instead of live chat history.`
**Point out:**
- Hydration or turn-linked provenance should make the archived source recoverable.
- The example should stay concrete rather than theoretical.
- This is a direct proof that archived detail is still inspectable.
**Say:** "Archived detail should still be reachable when we need it."

## Turn 065: Probe what did not survive as strongly
**Send:** `What stable facts survived the reset, and what details would you still avoid claiming?`
**Point out:**
- Chat should separate durable canon from details still too weak or too sparse to assert.
- Claims should support the confident facts; uncertainty should stay explicit.
- This keeps the demo honest after the continuity proof.
**Say:** "Continuity should preserve truth, not false certainty."

## Turn 066: Close the reset-proof proof
**Send:** `Close Act 4 with a reset-proof grounded summary of Northstar so far.`
**Point out:**
- Chat should summarize durable facts from Acts 1-3 using current read surfaces.
- The answer should feel continuous even though the session has changed.
- This closes the first major lifecycle proof in the pack.
**Say:** "We have now proven that durable memory survives the first reset."
