# Act 10: Historical Reconciliation

This act makes `as_of` replay explicit and resolves the remaining auth and semantic conflicts into stable current-state canon. Keep historical truth and current truth clearly separated at every step. Suggested session id: `cm-story-s2`.

## Turn 157: Replay the early auth state
**Send:** `As of June 25, 2026, which auth vendor looked current?`
**Point out:**
- `as_of` replay should surface Auth0 as the leading vendor for that date.
- The answer should not leak later WorkOS or Okta context backward into history.
- Claims timeline should make the result auditable.
**Say:** "Historical vendor truth should be isolated to its time slice."

## Turn 158: Replay the mid-shift auth state
**Send:** `As of July 2, 2026, which auth vendor looked strongest?`
**Point out:**
- `as_of` replay should now surface WorkOS as the stronger technical direction.
- The answer should still preserve that no final decision existed yet at that moment.
- This is the second checkpoint in the vendor timeline.
**Say:** "The answer should change because the history changed."

## Turn 159: Replay the conflict state
**Send:** `As of July 4, 2026, why should the auth vendor slot be treated as conflicted?`
**Point out:**
- Claims should show Auth0, WorkOS, and Okta as competing entries by this date.
- Chat should explain the conflict using stored rationales, not generic uncertainty.
- This is the last pre-resolution vendor history check.
**Say:** "By July 4, the slot should still look contested."

## Turn 160: Finalize the auth vendor
**Send:** `Record that on July 22, 2026 the team chose WorkOS as the current auth vendor for launch.`
**Point out:**
- Claims should now promote WorkOS to the current auth-vendor value.
- Auth0 and Okta should remain visible in history rather than disappearing.
- This is the first major conflict-resolution turn in the act.
**Say:** "The auth vendor is now finally resolved."

## Turn 161: Inspect the resolved vendor slot
**Send:** `Show the auth vendor claim slot now with WorkOS active and Auth0 and Okta preserved as historical or conflicting context.`
**Point out:**
- Claims should show a clean current-state value plus preserved timeline context.
- The answer surface should now distinguish active from historical confidently.
- This is the proof that resolution did not erase history.
**Say:** "We want a stable current answer without flattening the past."

## Turn 162: Replay the early backend state
**Send:** `As of early planning, what semantic backend direction did the team prefer?`
**Point out:**
- `as_of` replay should return the simple pgvector-first direction.
- The answer should not leak later Qdrant decisions into the earliest slice.
- This is the semantic counterpart to the vendor replay checks.
**Say:** "The early backend truth should still be easy to recover."

## Turn 163: Finalize the production backend
**Send:** `Record that on July 24, 2026 Qdrant became the production semantic backend decision, while pgvector remained the local and staging fallback path.`
**Point out:**
- Claims should now promote Qdrant to the production current-state value.
- Pgvector should remain preserved as local/staging fallback and historical rationale.
- This resolves the second major open conflict in the pack.
**Say:** "Production now has a stable semantic answer without losing the earlier path."

## Turn 164: Inspect the resolved backend slot
**Send:** `Show the semantic backend claim slot now with Qdrant current and pgvector preserved as historical context.`
**Point out:**
- Claims should clearly separate production current state from historical and environment-specific context.
- The answer should remain explicit about pgvector's continued local/staging role.
- This confirms that resolution can coexist with layered truth.
**Say:** "Current state and fallback context should now coexist cleanly."

## Turn 165: Replay degraded-week runtime truth
**Send:** `As of July 9, 2026, what retrieval mode was active during the embeddings outage?`
**Point out:**
- `as_of` replay should recover degraded mode and lexical fallback for that slice.
- The answer should not project today's stable backend posture backward onto outage week.
- This proves runtime history survived reconciliation too.
**Say:** "Historical runtime truth should stay anchored to the outage week."

## Turn 166: Replay pre-rebrand naming truth
**Send:** `As of before the rebrand, what product and service names should historical answers use?`
**Point out:**
- `as_of` replay should recover Northstar, Northstar API, and NS Console for that slice.
- The answer should keep later Compass names out of the historical surface.
- This is the naming equivalent of the vendor and backend checks.
**Say:** "Historical naming should stay true to its own moment."

## Turn 167: Replay post-rebrand naming truth
**Send:** `As of after the rebrand, what names should current-state answers use?`
**Point out:**
- `as_of` replay should now favor Compass, Compass API, and Compass Console.
- The answer should reflect the rebrand without losing historical alias resolution.
- This is the paired check against Turn 166.
**Say:** "Current naming should switch cleanly after the rebrand slice."

## Turn 168: Ask for the current auth story
**Send:** `What is the current auth vendor, and how would you explain the earlier Auth0 and Okta claims without losing history?`
**Point out:**
- Chat should answer with WorkOS as current while preserving Auth0 and Okta as historical contenders.
- Claims timeline should make this explanation straightforward and inspectable.
- This is the current-state explanation test after resolution.
**Say:** "Current truth should be clear without rewriting the timeline."

## Turn 169: Ask for the current backend story
**Send:** `What is the current production semantic backend, and how would you explain the earlier pgvector proposal without losing history?`
**Point out:**
- Chat should answer with Qdrant as current production direction.
- Pgvector should still appear as the earlier simple default and local/staging fallback.
- This is the backend version of Turn 168.
**Say:** "The backend answer should now be stable and still historically honest."

## Turn 170: Inspect final slot states together
**Send:** `Which claims are now active, which are historical, and which still remain conflict after these reconciliations?`
**Point out:**
- Claims should show the vendor and backend slots as resolved, while preserving historical entries.
- Any remaining conflicts should be explicit rather than implied.
- This is the broadest claim-state check in the act.
**Say:** "We should now have more active truth and less unresolved conflict."

## Turn 171: Inspect the multi-slot timeline
**Send:** `Show the claim timeline for auth vendor, auth deadline, product name, and semantic backend in one historical view.`
**Point out:**
- Claims should expose all four timelines in a way that makes `as_of` reasoning obvious.
- This is the clearest single proof that claim history is first-class in the story pack.
- The operator should be able to compare multiple evolving slots side by side.
**Say:** "The timeline should now look like a real project history."

## Turn 172: Ask how answer policy should differ by question type
**Send:** `What answer_outcome should you prefer for historical as_of questions versus current-state questions?`
**Point out:**
- Chat should explain that current-state questions prefer active-slot answers while historical questions must respect the requested slice.
- The answer should still prefer partial or abstain if the slice is under-supported.
- This is an explicit answer-policy turn.
**Say:** "Question type should change how the system grounds, not whether it stays honest."

## Turn 173: Summarize the reconciliation
**Send:** `Give me a grounded historical reconciliation summary that distinguishes past truth from current truth.`
**Point out:**
- Chat should summarize the rebrand, vendor shift, backend shift, and degraded-week history without collapsing them together.
- Claims and Graph should support this as a structured answer, not a loose recap.
- This is the penultimate synthesis before the pack's benchmark phase.
**Say:** "The system should now be able to explain change over time cleanly."

## Turn 174: Close the reconciled canon
**Send:** `Close Act 10 with the current canon after auth, semantic, and naming reconciliation.`
**Point out:**
- Chat should summarize Compass, WorkOS, Qdrant, historical Northstar naming, and preserved vendor/backend history.
- The answer should feel stable while remaining historically accountable.
- This becomes the current-state canon entering the benchmark acts.
**Say:** "We now have a stable present and a preserved past."
