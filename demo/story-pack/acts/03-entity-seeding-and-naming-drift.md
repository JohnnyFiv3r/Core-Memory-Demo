# Act 03: Entity Seeding and Naming Drift

This act seeds recurring people, services, and aliases so the entity registry has enough texture for merge review later. Keep all observations grounded in `Entities`, `Claims`, and `Graph`. Suggested session id: `cm-story-s1`.

## Turn 035: Add the core owners
**Send:** `Add the people who keep appearing in this project: Maya Chen is security lead, Priya Nair is product lead, and Luis Ortega is platform lead.`
**Point out:**
- Entities should now include three named people with distinct roles.
- Claims should attach each person to a stable responsibility area.
- This creates the first human-owned relationships in the graph.
**Say:** "The story now has named owners, not just product facts."

## Turn 036: Add Maya's alias
**Send:** `Record that Maya Chen is often referenced in notes as M. Chen.`
**Point out:**
- Entities should surface `M. Chen` as an alias candidate for Maya Chen.
- Alias normalization should stay observable rather than silently collapsing names.
- This sets up merge and provenance review later.
**Say:** "We are intentionally introducing naming drift."

## Turn 037: Add the product shorthand
**Send:** `Record that Northstar is often shortened to NS in internal notes.`
**Point out:**
- Entities should show `NS` as a likely alias for the Northstar product.
- Graph should still keep the product entity canonical.
- This will later matter when the product is renamed.
**Say:** "The product shorthand is now on record."

## Turn 038: Add the customer shorthand
**Send:** `Record that Mercury Health is frequently shortened to Mercury by the team.`
**Point out:**
- Entities should reinforce `Mercury` as a customer alias, not a new account.
- Alias counts should begin to rise for the pilot customer row.
- This is another merge-readiness seed.
**Say:** "Customer shorthand is now part of the entity story."

## Turn 039: Inspect Maya's entity row
**Send:** `Show the entity row for Maya Chen and tell me whether M. Chen normalizes to the same person yet.`
**Point out:**
- Entities should show Maya Chen with alias or normalization evidence.
- The answer should be explicit if the system is confident versus only suggestive.
- This demonstrates entity observability before any merge adjudication.
**Say:** "We want to see the alias logic, not hide it."

## Turn 040: Inspect the product alias row
**Send:** `Show the entity row for Northstar and tell me whether NS looks like an alias or a separate entity.`
**Point out:**
- Entities should prefer alias treatment for `NS`, or at least surface it as a proposal.
- The answer should not invent a second product unless the registry says so.
- This is a direct test of alias normalization.
**Say:** "The product shorthand should not fragment the product."

## Turn 041: Probe Priya's role
**Send:** `What does memory currently know about Priya Nair's role?`
**Point out:**
- Chat should answer with product ownership and nothing broader than the stored facts.
- Entities should show Priya as a stable person row.
- This is a small factual recall test using the new people entities.
**Say:** "The answer should stay narrow and grounded."

## Turn 042: Probe Luis's role
**Send:** `What does memory currently know about Luis Ortega's role?`
**Point out:**
- Chat should answer with platform ownership grounded in the recorded role.
- Claims should make the role inspectable without freeform guessing.
- This provides another grounded people-recall check.
**Say:** "Named owners should already be retrievable."

## Turn 043: Deepen responsibility mapping
**Send:** `Record that Luis owns the ingestion and runtime path, while Maya owns auth and compliance review.`
**Point out:**
- Claims should refine responsibility boundaries for platform versus security work.
- Graph should connect Luis to ingestion/runtime and Maya to auth/compliance.
- This makes future incident and vendor questions more attributable.
**Say:** "Ownership boundaries are now more concrete."

## Turn 044: Add launch ownership
**Send:** `Record that Priya owns pilot scope and launch sequencing for Mercury.`
**Point out:**
- Claims should attach Priya to Mercury-related launch decisions.
- Graph should connect Priya, Mercury, and launch sequencing.
- This becomes useful when auth work starts affecting launch timing.
**Say:** "Product ownership now touches the pilot directly."

## Turn 045: Inspect people-to-customer relationships
**Send:** `Show the graph path from Mercury Health back to the people currently responsible for the pilot.`
**Point out:**
- Graph should show Mercury connected to Priya and indirectly to the platform/compliance owners.
- The answer should be structural, not just a list of names.
- Provenance should remain visible from the relationship edges.
**Say:** "Responsibility should already be visible in the graph."

## Turn 046: Add the public API service
**Send:** `Northstar API is the current public service name for the customer-facing API. Record it as a service entity.`
**Point out:**
- Entities should add a service-level row distinct from the product row.
- Claims should make it clear this is a service name, not the product name.
- This distinction matters later during rebrand merge review.
**Say:** "We are now tracking service entities separately from the product."

## Turn 047: Add the console shorthand
**Send:** `NS Console is the shorthand name some internal docs use for the Northstar admin console. Record that naming drift.`
**Point out:**
- Entities should add a console/service row with shorthand language attached.
- Alias ambiguity should be visible rather than prematurely merged.
- This seeds a later reject path if the console and API get conflated.
**Say:** "The registry now has enough naming drift to be interesting."

## Turn 048: Probe merge readiness
**Send:** `Which entities look merge-ready already, and which ones still need reviewer judgment?`
**Point out:**
- Entities should surface likely merges for Maya/M. Chen, Northstar/NS, and Mercury Health/Mercury.
- Service names should remain more tentative because false merges are riskier there.
- This is the first explicit merge-readiness check.
**Say:** "Not every alias should collapse automatically."

## Turn 049: Test alias recall for Maya
**Send:** `If I ask about M. Chen, do you answer with Maya Chen's facts or do you hedge? Explain why.`
**Point out:**
- Chat should either resolve confidently or explain the alias uncertainty explicitly.
- Entities should provide the evidence behind that choice.
- This tests entity-aware grounding in the answer path.
**Say:** "Alias handling should be explainable."

## Turn 050: Test alias recall for the product
**Send:** `If I ask about NS, do you treat it as Northstar or do you surface ambiguity?`
**Point out:**
- Chat should resolve or hedge based on actual alias evidence in the registry.
- The answer should not invent a second product story.
- This sets a baseline before the later Compass rename arrives.
**Say:** "Product shorthand should be handled carefully."

## Turn 051: Inspect merge proposals without changing them
**Send:** `Show the current Entities and any merge-proposal signals without adjudicating them yet.`
**Point out:**
- Entities should surface proposals or at least merge-like hints for the seeded aliases.
- No proposal should be silently accepted at this stage.
- This is the pre-review snapshot before harder decisions arrive later.
**Say:** "We are observing the merge surface, not changing it yet."

## Turn 052: Close the entity canon
**Send:** `Close Act 3 with the stable people, service, and alias canon we should carry forward.`
**Point out:**
- Chat should summarize Maya, Priya, Luis, Northstar/NS, Mercury/Mercury Health, and the service names.
- The answer should note which alias relationships are strongly supported versus still under review.
- This becomes the entity baseline before the flush boundary.
**Say:** "The entity registry now has durable structure and visible drift."
