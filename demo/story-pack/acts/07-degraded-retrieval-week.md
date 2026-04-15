# Act 07: Degraded Retrieval Week

This act pairs the story with an observable runtime problem: embeddings are unavailable, degraded mode is active, and the system must prefer partial or abstain over hallucination. Keep the operator focused on `Runtime` and last-answer diagnostics. Suggested session id: `cm-story-s2`.

## Turn 105: Record the outage week
**Send:** `Record that on July 9, 2026 the embeddings provider started timing out and Runtime dropped into degraded_allowed mode for demo week.`
**Point out:**
- Claims should add a dated runtime incident fact rather than leaving degraded mode as an unspoken state.
- Runtime should now be expected to show backend warnings and degraded posture.
- This sets the frame for the rest of the act.
**Say:** "Degraded mode is now part of the story, not just the UI."

## Turn 106: Record the fallback behavior
**Send:** `Record that lexical fallback carried exact factual answers, but fuzzy recall quality dropped during the outage.`
**Point out:**
- Claims should distinguish what still worked from what degraded.
- Runtime expectations should line up with lexical-only or degraded retrieval behavior.
- This becomes the explanation for later `answer_partial` results.
**Say:** "The system stayed honest by narrowing what it could answer well."

## Turn 107: Inspect the degraded runtime state
**Send:** `Show the Runtime view for degraded mode, connectivity diagnostics, and the current semantic backend status.`
**Point out:**
- Runtime should show a degraded banner or equivalent semantic-backend warning.
- Connectivity diagnostics should make the failure visible without implying data loss.
- This is the operator's first direct runtime proof in this act.
**Say:** "The runtime should say exactly why retrieval is degraded."

## Turn 108: Ask a precise factual question
**Send:** `What database did we choose, and why?`
**Point out:**
- Chat should still answer correctly because exact factual recall can ride lexical grounding here.
- Last-answer diagnostics should show a grounded answer even in degraded mode.
- This is the positive control for the outage week.
**Say:** "Exact facts should still come back cleanly."

## Turn 109: Ask a fuzzy recall question
**Send:** `What was the spirit of our recent auth vendor debate?`
**Point out:**
- Chat should become partial or conservative because the question needs more semantic synthesis.
- Runtime diagnostics should explain the thinner grounding path.
- This is the contrast case against Turn 108.
**Say:** "Fuzzier questions should expose the real cost of degraded mode."

## Turn 110: Inspect last-answer diagnostics
**Send:** `Open the last-answer diagnostics and explain the difference between the precise and fuzzy answers.`
**Point out:**
- Runtime should expose fields such as `answer_outcome`, `retrieval_mode`, `source_surface`, and `anchor_reason`.
- The operator should be able to explain why one answer was strong and the other was partial.
- This is the observability centerpiece of the act.
**Say:** "The diagnostics should tell us why the answer shape changed."

## Turn 111: Record the demo-week posture
**Send:** `Record that demo week continued in degraded mode because availability mattered more than perfect semantic recall.`
**Point out:**
- Claims should make this a deliberate operating choice, not an accidental omission.
- Graph should connect the outage to the decision to keep the demo running.
- This preserves the operational tradeoff for later review.
**Say:** "The team chose availability with honest degradation."

## Turn 112: Inspect the strong-answer diagnostics
**Send:** `What are the current answer_outcome, source_surface, anchor_reason, and retrieval_mode for the last precise answer?`
**Point out:**
- Runtime should show that the exact answer still had a credible anchor.
- The operator should be able to name the dominant source surface clearly.
- This is the drilldown on the successful degraded-mode case.
**Say:** "Even degraded answers can still be well grounded."

## Turn 113: Ask a second fuzzy question
**Send:** `Remind me what changed around vendors recently. Prefer partial or abstain if grounding is weak.`
**Point out:**
- Chat should stay conservative because the question spans timeline and conflict.
- Diagnostics should make weak grounding explicit instead of hiding it.
- This reinforces the outage-week discipline.
**Say:** "This is where we want caution, not bravado."

## Turn 114: Inspect the weak-answer diagnostics
**Send:** `What do the last-answer diagnostics say for that fuzzy vendor prompt?`
**Point out:**
- Runtime should show why the answer was partial or abstained.
- The operator should be able to see warning and anchor details directly.
- This is the mirror image of Turn 112.
**Say:** "The diagnostics should justify the caution."

## Turn 115: Record explicit approval
**Send:** `Record that Maya Chen explicitly approved degraded mode for demo week as long as compliance answers stayed conservative.`
**Point out:**
- Claims should attach the degraded-mode posture to Maya's security role.
- Graph should connect the operational choice to compliance risk management.
- This creates a named-owner path for later questions.
**Say:** "Degraded mode now has a named approver and condition."

## Turn 116: Ask who approved and why
**Send:** `Who approved the degraded-mode posture, and under what condition?`
**Point out:**
- Chat should answer with Maya Chen and the requirement for conservative compliance answers.
- Entities and Graph should support the answer without ambiguity.
- This is a people-plus-runtime grounding check.
**Say:** "Operational posture should have a named owner and a clear rule."

## Turn 117: Replay the auth state during degraded week
**Send:** `As of degraded week, what was the safest current statement about the auth vendor decision?`
**Point out:**
- `as_of` replay should still keep the vendor slot unresolved at this moment in the story.
- Chat should prefer a partial, conflict-aware answer if needed.
- This combines temporal reasoning with degraded-mode caution.
**Say:** "Historical truth and degraded caution should reinforce each other."

## Turn 118: Ask which facts remain trustworthy
**Send:** `Which claims remain trustworthy in lexical-only retrieval, and which ones become risky?`
**Point out:**
- Chat should separate strong exact facts from fuzzier interpretive or cross-timeline questions.
- Claims should support this distinction with active slots versus conflicted history.
- This is a direct explanation of degraded answer policy.
**Say:** "Not every fact degrades equally."

## Turn 119: Inspect operator warning surfaces
**Send:** `Show the Runtime queue and warning surfaces that an operator should watch while degraded mode is active.`
**Point out:**
- Runtime should surface backend warnings clearly without conflating them with queue failure yet.
- This keeps retrieval health and queue health distinct before the next act.
- The answer should stay operational and inspectable.
**Say:** "Operators should know exactly which surfaces matter during degraded mode."

## Turn 120: Close degraded retrieval week
**Send:** `Close Act 7 with a grounded summary of degraded retrieval week and its answer-quality guardrails.`
**Point out:**
- Chat should summarize the outage, lexical fallback, partial/abstain behavior, and Maya's approval condition.
- Runtime and Claims should both support the closeout.
- This becomes the precursor to the queue postmortem in Act 8.
**Say:** "The key lesson is honesty under degraded conditions."
