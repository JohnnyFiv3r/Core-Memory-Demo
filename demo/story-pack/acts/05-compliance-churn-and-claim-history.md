# Act 05: Compliance Churn and Claim History

This act turns the earlier OAuth2 goal into a real timeline with slips, exceptions, and vendor conflict. Use `Claims` history, `as_of` replay, and `Graph` provenance as the read authority throughout. Suggested session id: `cm-story-s2`.

## Turn 067: Pin the original deadline
**Send:** `Record that the original OAuth2 cutover target was June 30, 2026.`
**Point out:**
- Claims should show the first dated auth deadline as an active or current value at this point in the timeline.
- This date becomes important later when the slot changes.
- Provenance should clearly anchor the original deadline to this turn.
**Say:** "We are making the original commitment inspectable."

## Turn 068: Add the temporary pilot exception
**Send:** `Record that legal granted a Mercury-only exception through July 31, 2026 so the pilot could continue while auth work finished.`
**Point out:**
- Claims should add a scoped exception rather than overwriting the broader OAuth2 goal.
- Graph should connect the exception back to the legal finding and Mercury pilot context.
- The answer surface should keep this as pilot-only, not general policy.
**Say:** "The exception is real, but it is narrow and temporary."

## Turn 069: Separate pilot exception from launch policy
**Send:** `Record that general availability cannot rely on the Mercury-only exception.`
**Point out:**
- Claims should distinguish pilot policy from launch policy.
- Graph should make clear that the exception does not resolve the overall compliance problem.
- This becomes useful later when launch readiness is discussed.
**Say:** "The exception buys pilot time, not launch approval."

## Turn 070: Add the first vendor candidate
**Send:** `Record that Auth0 became the first serious OAuth2 vendor candidate on June 24, 2026.`
**Point out:**
- Claims should add Auth0 to the vendor timeline with a dated provenance trail.
- This should appear as current or leading only for the appropriate historical slice.
- The vendor slot should not be final just because the first candidate is recorded.
**Say:** "Auth0 enters first, but not as a permanent winner."

## Turn 071: Add Maya's recommendation
**Send:** `Record that Maya Chen recommended WorkOS on July 1, 2026 because its audit trails and SCIM support fit the compliance model better.`
**Point out:**
- Claims should now show a competing vendor recommendation with a concrete rationale.
- Graph should tie Maya's role to the auth/compliance path, not treat this as anonymous input.
- This is where the vendor slot begins to drift toward conflict.
**Say:** "A stronger technical fit has now entered the record."

## Turn 072: Add procurement pressure
**Send:** `Record that procurement pushed for Okta on July 3, 2026 because the company already has a master agreement.`
**Point out:**
- Claims should now show a third vendor path with a procurement rationale.
- The vendor slot should be visibly moving toward `conflict`, not a clean single value.
- This creates a useful contrast between technical and commercial pressure.
**Say:** "The vendor slot is now contested for different reasons."

## Turn 073: Inspect the vendor slot status
**Send:** `Show the current auth vendor claim slot and tell me whether it is active or conflict.`
**Point out:**
- Claims should surface the vendor slot status directly rather than forcing a prose summary.
- History and conflict counts should now be non-trivial.
- The answer should prefer saying `conflict` over pretending a final choice exists.
**Say:** "This slot should now look explicitly conflicted."

## Turn 074: Replay the earlier vendor state
**Send:** `As of June 25, 2026, which auth vendor looked current in memory?`
**Point out:**
- `as_of` replay should return Auth0 without leaking later WorkOS or Okta context into the answer.
- This is the first meaningful historical vendor question in the pack.
- Claims timeline should make the result auditable.
**Say:** "Historical truth should be time-scoped, not rewritten."

## Turn 075: Replay the midweek vendor state
**Send:** `As of July 2, 2026, which auth vendor looked strongest in memory?`
**Point out:**
- `as_of` replay should now surface WorkOS as the strongest current direction for that slice.
- The answer should still preserve that the slot is not yet finalized overall.
- This shows why timelines matter more than a single latest-value summary.
**Say:** "The answer should change because the time slice changed."

## Turn 076: Replay the conflict state
**Send:** `As of July 4, 2026, is the vendor slot now conflicted, and why?`
**Point out:**
- Claims should show multiple contemporaneous vendor candidates by this date.
- The answer should explain the conflict using stored rationales, not vague ambiguity language.
- This is a strong test of claim history plus current-state replay.
**Say:** "By July 4, the slot should look openly contested."

## Turn 077: Ask for the current deadline
**Send:** `What deadline is currently attached to the OAuth2 goal: June 30 or July 31? Ground the answer in claim history.`
**Point out:**
- Claims should answer from the deadline timeline instead of collapsing both dates together.
- If the deadline has not yet been formally updated, the answer should say that carefully.
- This is a good partial-over-overclaim check.
**Say:** "Deadlines should come from history, not vibe."

## Turn 078: Record the deadline slip
**Send:** `Record that the June 30 target slipped and the operational target became July 31, 2026.`
**Point out:**
- Claims should update the deadline slot while preserving June 30 as historical context.
- Graph should connect the slip to the compliance and vendor-churn context.
- This makes the deadline timeline explicit for future `as_of` questions.
**Say:** "The missed date is now part of the permanent record."

## Turn 079: Inspect deadline history
**Send:** `Show the claim history for the auth deadline slot with the old and current values side by side.`
**Point out:**
- Claims should display June 30 and July 31 as distinct states with provenance.
- The timeline should make it obvious which value is current versus historical.
- This is the most direct proof that claim history is first-class.
**Say:** "The deadline change should be inspectable, not just remembered."

## Turn 080: Tighten the exception scope
**Send:** `Record that the Mercury-only exception does not apply to general availability.`
**Point out:**
- Claims should reinforce the scope boundary around the exception.
- This should not overwrite the pilot exception itself; it narrows its applicability.
- Graph should connect the exception to Mercury specifically.
**Say:** "The exception is narrow by design."

## Turn 081: Ask for a conservative current-state answer
**Send:** `What would you answer if someone asked whether auth is fully resolved right now? Prefer partial over overclaiming.`
**Point out:**
- Chat should answer conservatively because the vendor slot remains unresolved here.
- Claims should show why a fully confident answer would be misleading.
- Runtime answer diagnostics should favor a careful, grounded response.
**Say:** "This is the moment to show conservative grounding."

## Turn 082: Trace the auth conflict graph
**Send:** `What does the Graph show as the chain from legal finding to deadline slip to vendor debate?`
**Point out:**
- Graph should connect compliance pressure, deadline change, pilot exception, and vendor conflict.
- The answer should be causal, not just a flat list of facts.
- Provenance should remain tied to the turns that introduced each step.
**Say:** "The auth story should already look like a chain, not a pile."

## Turn 083: Inspect auth slot states together
**Send:** `Which auth facts are active, which are conflict, and which are now historical?`
**Point out:**
- Claims should clearly separate the current OAuth2 goal, the conflicted vendor slot, and historical deadlines.
- This is the best single readout of claim-first state in this act.
- The answer should stay categorical and inspectable.
**Say:** "Current, conflict, and historical should now all be visible."

## Turn 084: Add product pressure
**Send:** `Record that Priya wants the pilot to stay on schedule even if launch has to wait for final auth cutover.`
**Point out:**
- Claims should connect Priya's product ownership to the launch tradeoff.
- Graph should link Mercury, launch sequencing, and auth readiness.
- This sets up later launch-versus-compliance reasoning.
**Say:** "Product pressure is now part of the auth story too."

## Turn 085: Ask who owns the decision
**Send:** `Who currently owns the final vendor recommendation, and who owns the launch tradeoff?`
**Point out:**
- Chat should answer with Maya on the vendor/compliance path and Priya on the launch tradeoff.
- Entities and Graph should support that separation of responsibility.
- This is a people-and-claims grounding check, not a freeform org chart.
**Say:** "The decision path should already have named owners."

## Turn 086: Close the compliance-churn state
**Send:** `Close Act 5 with a grounded summary of the auth conflict, the slipped deadline, and the Mercury exception.`
**Point out:**
- Chat should summarize the unresolved vendor slot, the June-to-July deadline change, and the pilot-only exception.
- Claims should still be the authority for current state and history.
- This closeout becomes the baseline for the semantic-strategy debate in the next act.
**Say:** "The auth story is now officially timeline-shaped."
