# PRD: Conversational entity & enrichment extraction in Core-Memory

**Status:** Draft for roadmap decision
**Owner:** Core-Memory maintainers (decision needed before implementation)
**Author:** Core-Memory-Demo benchmark investigation
**Repos:** capability lands in `JohnnyFiv3r/Core-Memory`; measured by `core-memory-demo` LoCoMo benchmark

---

## 1. Problem

LoCoMo benchmark recall on the hosted demo is stuck (recall@5 ≈ 0.44, answer F1
low) **after** fixing every downstream retrieval layer:

- recall traversal seed/merge + soft hints (CM #170/#171)
- OpenAI embeddings for Qdrant (CM #173)
- benchmark no longer silently using `hash` embeddings (demo #158)
- benchmark worker env aligned to OpenAI (demo #157)

A single-bead inspection (conv-26, `D2:2`) shows **why** — the bottleneck is
upstream of retrieval, in **bead/corpus quality**:

```
title  == summary == detail  (the same one-line utterance, triplicated)
entities: ["Caroline", "locomo:conv-26"]      # speaker + a boilerplate tag
associations: all "associated_with" via reason_code "shared_tag_overlap"
              (every bead in the conversation shares sample:/session: tags)
retrieval_eligible: false                      # on seed-path beads (no quality signal)
```

For the utterance *"That charity race sounds great, Mel! … raising awareness for
mental health …"*, the extractor captured **`Caroline`, `Mel`** and missed
**`charity race`, `mental health`, `awareness`** — and grabbed junk like
`Making`. Because graph edges are built from entity overlap, weak entities →
weak/empty edges; and because every bead carries the same run-level tags, the
`shared_tag_overlap` fallback links everything to everything (graph = noise).

### Root cause

**Core-Memory ships no real entity extraction, and only heuristic (regex) claim
extraction.** Entity/topic extraction is **delegated to the caller's
`crawler_updates`**. Evidence in the current pinned source:

- `core_memory/claim/extraction.py` — claim extraction is a fixed set of regex
  extractors (`_extract_timezone`, `_extract_location`, `_extract_preference`,
  …). On casual conversation it captures almost nothing → `claims: 0`.
- There is **no** `extract_entities` / NER / noun-phrase pass anywhere in
  `core_memory/` outside the caller-supplied crawler path.
- `core_memory/association/crawler_contract.py` consumes whatever
  `entities`/`associations` the crawler emits, plus a `shared_tag_overlap`
  fallback when no stronger relationship is inferred.
- `core_memory/runtime/passes/enrichment.py::run_turn_enrichment` stages are:
  association pass, claim extraction (heuristic), preview associations, crawler
  merge, decision pass, claim updates, memory outcome, goal lifecycle, quality
  metric — **none of which extract entities from raw text.**

The demo's `locomo_turn_crawler._text_entities` (a capitalized-token regex) is
therefore *representative* of what a Core-Memory adopter gets from the built-in
heuristic path — i.e. the weak extraction is **Core-Memory's**, surfaced by the
demo, not a demo shortcut.

### Why this matters for the benchmark

Decision (from review): the benchmark must **prove stock Core-Memory** — raw
turns in, CM does enrichment + retrieval. Under that bar, CM's current
conversational extraction caps the achievable recall/F1 well below competitive
(0.8+) systems, regardless of embedding model or traversal tuning.

---

## 2. Goal & success criteria

Give Core-Memory a real conversational extraction capability so that, feeding
**only raw turns**, the LoCoMo benchmark reaches competitive recall.

Success:
- **S1** — recall@5 on conv-26 (and the full LoCoMo set) materially improves
  over the 0.44 baseline with no demo-side extraction (demo feeds raw turns).
- **S2** — extracted entities for the `D2:2` example include the salient
  noun-phrases (`charity race`, `mental health`, `awareness`), not just
  capitalized tokens; junk tokens (`Making`, `That`) excluded.
- **S3** — associations between beads reflect **real shared entities**, not
  run-level tags; `shared_tag_overlap` is no longer the dominant edge type.
- **S4** — beads carrying real extracted signal are `retrieval_eligible: true`
  (they pass `can_be_retrieval_eligible` because they now have quality signals).
- **S5** — opt-in / gated so adopters without a provider key keep today's
  zero-dependency behaviour; no hard new runtime dependency by default.

Non-goals: changing the retrieval/traversal stack (already done); LoCoMo-specific
shaping (must be general conversational ingest).

---

## 3. Options

### Option A — Optional LLM-backed enrichment pass (recommended for the number)
Add an entity/claim extractor to `run_turn_enrichment`, gated by the adopter's
embedding/LLM provider key, that calls the configured model to extract entities,
topics, and richer claims from each turn, then feeds them through the existing
`crawler_updates` → `merge_crawler_updates` contract (so associations,
`retrieval_eligible`, and embedding text all improve without touching downstream
code).

- **Pros:** highest quality; benchmark genuinely reflects CM; reuses the
  existing enrichment/crawler contract as the insertion point.
- **Cons:** per-turn LLM cost + latency; needs batching/caching; new provider
  call path in the hot ingest loop; must stay gated + fail-open.
- **Insertion point:** new stage in `run_turn_enrichment` (before crawler merge);
  emits the same shape `locomo_turn_crawler` emits today.

### Option B — Better built-in heuristic (no LLM dependency)
Replace the capitalization regex with a noun-phrase/keyphrase extractor (e.g.
lightweight POS/noun-chunking, or a dependency-light keyphrase algorithm) as the
default entity extractor inside CM.

- **Pros:** no API cost/latency; helps every adopter by default; no provider dep.
- **Cons:** ceiling below LLM; still misses paraphrase/coref; another dependency
  (spaCy model) unless a pure-python approach is used.

### Option C — Formalize the crawler-extraction contract (adopter-supplied)
Keep extraction caller-supplied (CM's current design), but document/standardize
the contract and ship a reference LLM extractor adopters can opt into.

- **Pros:** matches CM's existing delegation design; smallest CM core change.
- **Cons:** the benchmark would then measure the *demo's* extractor, which
  contradicts the "prove Core-Memory itself" decision. Rejected on that basis,
  documented for completeness.

### Recommendation
**A**, with **B as the zero-dependency default** when no provider is configured
(so S5 holds): LLM extraction when a key is present, improved heuristic when not.
C is rejected against the stated benchmark intent.

---

## 4. Contract the extractor must satisfy (for A or B)

Emit, per turn, a `crawler_updates`-shaped payload (already consumed by
`merge_crawler_updates`):
- `beads_create[].entities` — salient entities/noun-phrases (not just caps),
  deduped, stopword-filtered, ~≤12.
- `beads_create[].topics` — semantic topics (not run-level `sample:`/`session:`).
- `beads_create[].supporting_facts` — so beads pass `can_be_retrieval_eligible`
  (currently the reason seed beads get `retrieval_eligible: false`).
- `associations[]` — entity/topic-overlap edges with a relationship better than
  `associated_with` where inferable; **do not** derive edges from run-level tags.
- Optionally richer `claims[]` for the claim layer (addresses `claims: 0`).

Embedding text (`schema/bead_projection.build_retrieval_text`) should compose
**distinct** signal (utterance + entities + gist) rather than the current
title==summary==detail triplication, so beads spread in vector space.

---

## 5. Risks & open questions

- **Cost/latency:** per-turn LLM extraction on a 175-turn conversation = 175
  calls. Batch per session? Cache by turn hash? Acceptable ceiling?
- **Determinism:** benchmark reproducibility with an LLM in the ingest loop —
  pin model + temperature 0; record provider/model in the manifest.
- **Dependency surface:** Option B's noun-phrase approach — pure-python vs spaCy
  model download (CI/deploy weight).
- **Where the heuristic-vs-LLM switch lives:** reuse
  `CORE_MEMORY_CLAIM_EXTRACTION_MODE` (already `heuristic` in the demo) or a new
  `CORE_MEMORY_ENRICHMENT_MODE`?
- **Backfill:** existing corpora embedded under the old extractor need a rebuild;
  define a re-enrichment path.

---

## 6. Validation plan

1. Offline on conv-26: re-extract entities + recompose bead text with the chosen
   approach, re-embed (OpenAI), recompute recall@5 / answer F1 vs. the 0.44
   baseline — establishes the ceiling before full implementation (S1/S2).
2. Full LoCoMo run via the demo benchmark with the demo feeding **raw turns only**
   (no `locomo_turn_crawler` extraction) once the CM capability lands.
3. Assert S2–S4 on the `D2:2` bead specifically (entities, edge types,
   retrieval_eligible).

---

## 7. Delivery

CM capability → patch in `core-memory-demo/upstream-patches/` (push access to
Core-Memory is not available from the demo automation) → Core-Memory PR → demo
pin bump. Demo-side change: **remove** `locomo_turn_crawler` extraction so the
benchmark exercises CM's native path (gated behind the new pin).
