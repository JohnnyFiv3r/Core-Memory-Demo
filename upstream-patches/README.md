# Core-Memory patch: recall traversal prereqs (C + A)

This directory carries patches destined for the **Core-Memory** repo
(`JohnnyFiv3r/Core-Memory`), not the demo. They live here because the demo's
automation can only push to `core-memory-demo`; apply them to Core-Memory by
hand (or hand the branch to whoever has push access there).

## `coremem-recall-traversal-CA.patch`

Fixes the root cause of the stuck LoCoMo recall@5 (~0.47): causal graph
traversal runs at `prefer_grounded` effort but could not surface gold-adjacent
beads. Two prereqs for the larger agentic recall loop:

**C — seed + merge fixes**
- Seed causal traversal from the top-N semantic anchors
  (`CORE_MEMORY_TRACE_SEED_ANCHORS`, default **12**) instead of a hardcoded 5.
  The gold-adjacent bead routinely ranks just outside the top 5 on
  conversational corpora, so it never seeded traversal.
- Give chain beads a merge budget **beyond k**
  (`CORE_MEMORY_TRACE_CHAIN_MERGE_BONUS`, default **8**) so traversal evidence
  is not crowded out of the scored top-k by the k semantic anchors. This was the
  single biggest reason traversal "ran" but did not move recall@5.
- Depth / chain count are also env-tunable
  (`CORE_MEMORY_TRACE_MAX_DEPTH`=3, `CORE_MEMORY_TRACE_MAX_CHAINS`=12).

**A — active query parser**
- `recall()` parses soft structural hints from the query
  (e.g. *"what caused the outage"* → `caused_by` / `led_to`) and passes them as
  `facets.structural_hint_relations`. These only **reorder** traversal chains
  (prefer matching relations); they never filter, so a wrong parse cannot reduce
  recall. Explicit `relation_types` still hard-filter as before.

Defaults preserve prior behaviour where it matters; the knobs let the demo tune
seed breadth / merge budget without a Core-Memory redeploy.

### Files touched
- `core_memory/retrieval/pipeline/canonical.py` — tunables, wider seed, merge
  budget, soft-hint chain reorder.
- `core_memory/retrieval/agent.py` — parse + attach `structural_hint_relations`.
- `tests/test_agentic_traversal_prereqs.py` — new; proves seed-beyond-top-5,
  merge-past-k, env tunables, reorder-not-filter.
- `tests/test_capture_recall_aliases.py` — updated for the new (intended) facet
  on causal queries.

Base: applies cleanly on Core-Memory `master`
(tip `48d2179`, which is the demo's current pin `fcf29b8`'s ancestor line —
verified with `git apply --check`).

## How to apply

```bash
git clone https://github.com/JohnnyFiv3r/Core-Memory.git
cd Core-Memory
git checkout -b feat/agentic-recall-traversal master
git am < coremem-recall-traversal-CA.patch   # or: git apply + commit
python -m pytest tests/ -k "trace or recall or causal or traversal"   # 242 pass
git push -u origin feat/agentic-recall-traversal
# open the PR, then bump backend/requirements.txt in the demo to the merge SHA.
```

## After it merges
Bump the demo pin in `backend/requirements.txt`:
```
core-memory[qdrant,kuzu,mcp] @ git+https://github.com/JohnnyFiv3r/Core-Memory.git@<merge-sha>
```
and (optionally) set the tunables in `render.yaml`, e.g.
`CORE_MEMORY_TRACE_SEED_ANCHORS=12`, `CORE_MEMORY_TRACE_CHAIN_MERGE_BONUS=8`.

The agentic loop (B: `effort="dynamic"` iterative expand-on-miss) builds on top
of this and is intentionally a separate follow-up — worth measuring the C+A
recall@5 lift on conv-26 first.
