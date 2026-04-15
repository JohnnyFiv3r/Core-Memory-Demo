# Act 09: Rebrand and Merge Review

This act renames Northstar to Compass and uses reviewer-driven merge flow to keep identity clean without collapsing unlike entities together. Keep the operator focused on `Entities`, merge proposals, and graph-preserved provenance. Suggested session id: `cm-story-s2`.

## Turn 139: Record the product rename
**Send:** `Record that on July 18, 2026 the product name changed from Northstar to Compass.`
**Point out:**
- Claims should add Compass as the current product name while preserving Northstar historically.
- Entities should show this as a rename or alias evolution, not a brand-new product.
- This starts the rebrand without erasing earlier provenance.
**Say:** "The product now has a new current name and an old historical one."

## Turn 140: Preserve the old shorthand as history
**Send:** `Record that NS should now be treated as a historical alias for Compass, not a separate product.`
**Point out:**
- Entities should keep `NS` attached to the product row rather than splitting it into a second record.
- Historical alias coverage should remain inspectable for lookup and audit.
- This is a clean alias decision, not a cross-entity merge.
**Say:** "The shorthand survives, but only as product history."

## Turn 141: Rename the public API
**Send:** `Record that Northstar API is now Compass API.`
**Point out:**
- Entities should update the service name while preserving the older service label as historical context.
- Claims should keep the service entity distinct from the product entity.
- This prepares the service-name surface for merge review.
**Say:** "Service names are now joining the rebrand too."

## Turn 142: Rename the admin console
**Send:** `Record that NS Console is now Compass Console.`
**Point out:**
- Entities should show the console rename distinctly from the API rename.
- The answer surface should not collapse console and API into the same entity.
- This sets up a later rejected merge path.
**Say:** "The console gets its own rename path, not a shared service identity."

## Turn 143: Inspect the renamed product entity
**Send:** `Show the entity row for Compass and tell me whether Northstar and NS are proposed merges or accepted aliases.`
**Point out:**
- Entities should make the product rename and alias history visible in one place.
- The row detail should preserve provenance across old and new names.
- This is the first direct entity inspection after the rebrand.
**Say:** "We want to see the rename as structured state, not just remember it."

## Turn 144: Accept the product merge path
**Send:** `Accept the merge proposal that Northstar, NS, and Compass refer to the same product entity.`
**Point out:**
- Entities should now consolidate the product naming family under one canonical product row.
- Historical names should remain recoverable even after acceptance.
- This is a reviewer-driven merge, not an automatic collapse.
**Say:** "The product entity is now explicitly unified."

## Turn 145: Accept the customer alias merge
**Send:** `Accept the merge proposal that Mercury Health and Mercury refer to the same customer entity.`
**Point out:**
- Entities should now consolidate the pilot customer into one canonical customer row.
- Historical references should still hydrate correctly to the merged entity.
- This is the clean customer-side version of the product rename logic.
**Say:** "The customer alias is now formally resolved."

## Turn 146: Add the umbrella launch label
**Send:** `Record that Compass Platform is the umbrella product name used in launch materials.`
**Point out:**
- Entities should add `Compass Platform` as a product-level alias or related naming surface.
- This introduces a subtle risk of false merges with service names.
- The answer surface should keep product and service scopes distinct.
**Say:** "Launch language now adds one more name to the product family."

## Turn 147: Reject a bad product-to-service merge
**Send:** `Reject any merge proposal that treats Compass API as the same entity as Compass Platform.`
**Point out:**
- Entities should preserve service-versus-product boundaries explicitly.
- This is the first deliberate reject path in the review flow.
- The operator should be able to explain the rejection in entity-type terms.
**Say:** "Not every name overlap should become one entity."

## Turn 148: Reject a second bad service merge
**Send:** `Reject any merge proposal that treats Compass Console as the same entity as Compass API.`
**Point out:**
- Entities should keep the console and API as separate service rows.
- This reinforces that rename cleanup is not license to flatten the service catalog.
- The rejected proposal should remain reviewer-observable.
**Say:** "The console and API stay separate even after the rebrand."

## Turn 149: Ask for the current canonical name
**Send:** `What is the current canonical product name, and which historical aliases should still resolve to it?`
**Point out:**
- Chat should answer with Compass as current and Northstar plus NS as historical aliases.
- Entities should provide a clean basis for that answer.
- This is the first current-state naming question after merge review.
**Say:** "Current-state answers should now prefer Compass cleanly."

## Turn 150: Ask how historical lookup should behave
**Send:** `If I ask about Northstar now, how should the answer surface both the current name and the historical alias?`
**Point out:**
- Chat should explain the rename without losing the current-state preference for Compass.
- Historical lookup should remain accessible through alias resolution.
- This is a direct test of renamed-entity answer behavior.
**Say:** "We want current truth plus historical continuity in one answer."

## Turn 151: Inspect the merge-review result
**Send:** `Show the Entities and merge-proposal state after the accept and reject decisions.`
**Point out:**
- Entities should show accepted merges for the product and customer names.
- Rejected service merges should remain visibly rejected rather than disappearing.
- This is the audit view of the review flow.
**Say:** "The review trail should be inspectable after each decision."

## Turn 152: Ask what changed in the graph
**Send:** `What changed in the Graph when the product entity was renamed but the provenance stayed intact?`
**Point out:**
- Graph should preserve causal history while updating current labels.
- The answer should emphasize continuity of identity, not replacement of evidence.
- This is a structural proof that rebrand does not break provenance.
**Say:** "A rename should change labels, not destroy history."

## Turn 153: Ask which names operators should use
**Send:** `Which names should an operator use for the product, the API, and the console right now?`
**Point out:**
- Chat should answer with Compass, Compass API, and Compass Console for current-state usage.
- Historical aliases should be mentioned only as lookup helpers.
- Entities should support a crisp operational naming answer.
**Say:** "Operators need current names without losing historical traceability."

## Turn 154: Replay pre-rebrand naming
**Send:** `As of before July 18, 2026, what product name should a historical answer use?`
**Point out:**
- `as_of` replay should return Northstar for that slice.
- The answer should not leak Compass into the pre-rebrand answer as current truth.
- This confirms the rename preserved historical layers correctly.
**Say:** "Historical naming should obey the time slice."

## Turn 155: Replay post-rebrand naming
**Send:** `As of after July 18, 2026, what product name should current-state answers use?`
**Point out:**
- `as_of` replay should now return Compass as the active name.
- This is the paired check against Turn 154.
- Claims and Entities should align cleanly on the answer.
**Say:** "Current naming should now switch over cleanly."

## Turn 156: Close the rebrand state
**Send:** `Close Act 9 with a grounded summary of the rebrand and merge-review outcomes.`
**Point out:**
- Chat should summarize Compass as current, Northstar/NS as historical aliases, Mercury alias resolution, and the rejected service merges.
- Entities and Graph should support the whole summary without ambiguity.
- This closes the naming arc before historical reconciliation begins.
**Say:** "The rename is now durable, inspectable, and not over-merged."
