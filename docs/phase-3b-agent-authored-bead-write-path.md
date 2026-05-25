# Phase 3B — Restore Agent-Authored Bead Write Path

Demo repo implementation notes for the Phase 3B ownership boundary:

> Agent/adapters author semantic memory. Core Memory validates, normalizes structural fields, persists, links, and indexes. Core Memory does not silently re-author meaning by default.

## Demo obligations

- Inject Core Memory's public bead-authoring spec into the primary PydanticAI demo agent when available (`core_memory.integrations.bead_authoring.agent_authored_bead_spec`).
- Mark request-scoped adapter-authored `metadata.crawler_updates` with `_crawler_updates_source` so Core Memory can preserve authored semantic fields.
- Ensure demo-authored and LoCoMo-authored bead rows include retrieval-quality fields when `retrieval_eligible=true`:
  - `retrieval_title`
  - `retrieval_facts`
  - `entities`
- LoCoMo lifecycle replay must use the same request-scoped authored update contract instead of relying on Core Memory's internal bead-field judge fallback.

## Non-goals

- The demo app does not make Core Memory's internal judge the normal writer.
- Benchmark scoring remains mechanical-only: token F1 and dia-id evidence recall, not an LLM judge.
