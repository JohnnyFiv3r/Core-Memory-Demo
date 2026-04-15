# Act 02: Architecture Expansion

This act expands Northstar from the initial durable facts into operating architecture and customer context. Keep all readback grounded in `Claims`, `Graph`, `Entities`, and `Runtime`, not direct store inspection. Suggested session id: `cm-story-s1`.

## Turn 017: Add multi-tenant ingestion
**Send:** `Record that Northstar uses multi-tenant ingestion with tenant-scoped API keys.`
**Point out:**
- Claims should add a clear architecture fact for multi-tenant ingestion.
- Entities should now reflect tenant-aware ingestion as part of the platform design.
- This fact should become important later when reasoning about pilots and backfills.
**Say:** "The ingestion model is now part of canon."

## Turn 018: Add immutable audit logging
**Send:** `Record that Northstar keeps immutable audit logs and retains them for seven years.`
**Point out:**
- Claims should treat immutability and retention as architecture constraints, not optional notes.
- Graph should connect this requirement to the regulated-product framing.
- Later compliance answers should be able to cite this directly.
**Say:** "Audit immutability is now a first-class constraint."

## Turn 019: Add the raw retention window
**Send:** `Record that raw ingestion payloads stay hot for 30 days before they age into archive storage.`
**Point out:**
- Claims should distinguish raw payload retention from audit-log retention.
- This introduces the first timeline-sensitive storage policy.
- The answer surface should avoid collapsing different retention windows into one.
**Say:** "Retention windows now have structure."

## Turn 020: Add the regional topology
**Send:** `Record that the primary region is us-east-1 and disaster recovery is us-west-2.`
**Point out:**
- Claims should capture a primary region and a separate DR region.
- Graph should attach both regions to the Northstar entity with different roles.
- This should support later historical and failover questions.
**Say:** "The region topology is now explicit."

## Turn 021: Add the customer-facing SLO
**Send:** `Record that the dashboard freshness SLO is 5 minutes.`
**Point out:**
- Claims should add a dated, inspectable freshness target.
- The answer surface should keep customer-facing freshness separate from internal processing details.
- This fact will matter later when incident outcomes are evaluated.
**Say:** "The visible SLO is now part of memory."

## Turn 022: Add the pilot customer
**Send:** `Mercury Health, also called Mercury, is our pilot customer. Record that entity and alias.`
**Point out:**
- Entities should add `Mercury Health` with `Mercury` as an alias candidate or linked label.
- Claims should show the pilot relationship as an active customer fact.
- This is the first customer entity that later merge review will revisit.
**Say:** "The pilot customer is now a named entity."

## Turn 023: Inspect the architecture claim set
**Send:** `Show the current architecture Claims for ingestion, audit, retention, regions, and freshness.`
**Point out:**
- Claims should now separate ingestion, audit, retention, region, and SLO facts cleanly.
- Any ambiguity between hot retention and audit retention should be visible here.
- This confirms the read model is organizing architecture, not just storing prose.
**Say:** "We should already have a structured architecture view."

## Turn 024: Probe SLO interpretation
**Send:** `How does the 5 minute dashboard SLO relate to ingestion versus read-model freshness?`
**Point out:**
- Chat should answer from stored architecture facts rather than generic observability advice.
- The answer should distinguish customer-visible freshness from lower-level mechanics.
- Diagnostics should still show a grounded answer path.
**Say:** "The SLO should be interpreted, not guessed."

## Turn 025: Probe the pilot customer boundary
**Send:** `What do we currently know about Mercury Health, and what do we not know yet?`
**Point out:**
- Chat should keep the answer narrow: pilot customer plus alias, nothing more unless later supported.
- Entities should show the customer exists even if many customer details are still absent.
- This is a deliberate test of restraint.
**Say:** "We want grounded customer recall, not invented account detail."

## Turn 026: Inspect the customer graph edge
**Send:** `Show the Graph edges that connect Northstar, Mercury Health, and the pilot relationship.`
**Point out:**
- Graph should show a direct product-to-customer relationship.
- The alias should not fragment Mercury into a false second customer.
- Provenance should remain inspectable at the edge or node level.
**Say:** "The pilot relationship should already be visible structurally."

## Turn 027: Probe failover expectations
**Send:** `If us-east-1 fails, what does memory currently say about us-west-2?`
**Point out:**
- Chat should answer with the stored DR role, not invent a full disaster-recovery runbook.
- Claims should make the primary-versus-DR distinction recoverable.
- This is another good partial-over-hallucination check.
**Say:** "The answer should stay within the stored topology."

## Turn 028: Inspect the entity registry again
**Send:** `List the stable Entities and aliases that exist so far.`
**Point out:**
- Entities should now include Northstar, PostgreSQL, OAuth2, Mercury Health, and several architecture concepts.
- Alias coverage should include Mercury at minimum.
- This sets up the more explicit alias work in Act 3.
**Say:** "The entity registry should be growing in a controlled way."

## Turn 029: Make audit logging causal
**Send:** `Explain why immutable audit logs are a first-class architecture requirement, not just an implementation detail.`
**Point out:**
- Chat should connect regulated analytics to the audit-log requirement.
- Graph should support a causal answer from product context to architecture constraint.
- The explanation should stay grounded in recorded facts, not external policy text.
**Say:** "The answer should show why this fact matters."

## Turn 030: Inspect provenance across architecture facts
**Send:** `For the architecture facts now in memory, show me the provenance or origin for each one if you have it.`
**Point out:**
- Claims and Graph should make it possible to trace each architecture fact back to a turn.
- The answer should be explicit about what is directly recorded versus merely inferred.
- This is a provenance audit, not a recap.
**Say:** "Every durable fact should still have a visible origin."

## Turn 031: Add a pilot requirement
**Send:** `Record that Mercury requires tenant-level audit exports during the pilot.`
**Point out:**
- Claims should add a customer-specific requirement without overwriting broader platform facts.
- Graph should connect Mercury to the audit-related architecture already in memory.
- This gives later compliance and launch reasoning more texture.
**Say:** "The pilot now has a concrete customer requirement."

## Turn 032: Inspect customer versus platform scope
**Send:** `Show the claim slot history for customer requirements versus platform architecture so we do not confuse the two.`
**Point out:**
- Claims should keep Mercury-specific requirements distinct from platform-wide canon.
- This is a good place to verify slot boundaries before conflicts arrive later.
- The answer surface should make the separation inspectable.
**Say:** "Customer-specific facts should not quietly become platform defaults."

## Turn 033: Summarize the expanded architecture
**Send:** `Give me a grounded architecture summary of Northstar as of now.`
**Point out:**
- Chat should summarize tenancy, audit retention, regions, freshness, and Mercury as pilot customer.
- The answer should remain compact and grounded in the stored read model.
- This becomes the working baseline before heavier entity work begins.
**Say:** "We should now have a reusable architecture snapshot."

## Turn 034: Close the expanded canon
**Send:** `Close Act 2 by separating product, compliance, architecture, and customer canon.`
**Point out:**
- Chat should organize the canon into categories instead of blending them together.
- Claims should still support each category with active slots or linked facts.
- This closeout makes later conflicts easier to inspect.
**Say:** "The canon is now broader, but still structured."
