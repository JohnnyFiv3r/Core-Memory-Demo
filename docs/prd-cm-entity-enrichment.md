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

A bead should be a **small typed memory object**: enough signal to land in
semantic search, link to its causes/effects, and mark current truth — and no
more. The conv-26 evidence shows Core-Memory failing that bar in **two opposite
directions at once**:

**① The few fields that actually drive retrieval are weakly filled.** Recall
depends on a short list: **entities** (so a turn lands in the initial Qdrant
search), **causal associations** (so traversal can expand from an anchor to its
real neighbours), distinct **title/summary** (so beads spread in vector space),
and the **promotion/quality signals** that make a bead `retrieval_eligible`.
These are exactly the fields that are heuristic and weak today —
`_text_entities` is a capitalized-token regex (caught `Caroline`/`Mel`, missed
`charity race`/`mental health`/`awareness`, grabbed junk like `Making`);
associations are `shared_tag_overlap` (every bead shares run-level
`sample:`/`session:` tags, so the graph links everything to everything); and
`title == summary == detail` collapses three fields into one utterance, so beads
don't spread in embedding space.

**② The schema has drifted too wide.** The bead carries ~55 fields, most of them
speculative inference the retrieval path never reads —
`cause_candidates`, `effect_candidates`, `mechanism`, `impact_level`, the six
`*_keys` families (`incident`/`decision`/`goal`/`action`/`outcome`/`time`),
`what_almost_happened`, `what_was_rejected`, `what_felt_risky`, `assumption`,
`uncertainty`, `links`. Filling them (by LLM or regex) spends tokens/latency to
turn a small typed object into an **aspirationally-littered, confusion-generating
one** without moving recall. The win is *fewer, better-filled* fields — not more.

**③ Authoring is fragmented across separate classes.** Even the core signal is
assembled by 3+ disjoint mechanisms: `policy/bead_judge.py` (LLM-or-regex) for
some fields; `claim/extraction.py` (a fixed set of regex extractors —
`_extract_timezone`/`_extract_location`/… → `claims: 0` on casual chat); and
`association/crawler_contract.py` (the `shared_tag_overlap` heuristic) for
entities/edges. There is no single coherent pass — and the one LLM pass that
exists (`judge_bead_fields`) is **bypassed**: when a caller supplies
`metadata.crawler_updates` (the demo's `locomo_turn_crawler` always does),
`runtime/engine.py` (≈ line 317) uses that payload and skips the judge; and even
off that path the judge needs a **chat** provider (`resolve_chat_config` →
`CORE_MEMORY_CHAT_PROVIDER`/`CORE_MEMORY_CHAT_MODEL`) the demo never configures,
so it falls back to heuristics regardless.

Net: the inspected `D2:2` bead (title==summary==detail, entities just
`["Caroline","locomo:conv-26"]`, `associated_with`/`shared_tag_overlap` edges,
`retrieval_eligible:false`) is the output of weak regex extraction against a
bloated schema. The fix is to **tighten the bead to its retrieval-bearing core
and fill that core well** — not to fill 55 fields. `_text_entities` is
*representative* of what a Core-Memory adopter gets from the built-in heuristic
path, so the weak extraction is **Core-Memory's**, surfaced by the demo, not a
demo shortcut.

### Why this matters for the benchmark

Decision (from review): the benchmark must **prove stock Core-Memory** — raw
turns in, CM does enrichment + retrieval. Under that bar, CM's current
conversational extraction caps the achievable recall/F1 well below competitive
(0.8+) systems, regardless of embedding model or traversal tuning.

---

## 2. Goal & success criteria

Make the bead a **tight typed memory object** and fill its retrieval-bearing core
well — one coherent authoring pass per turn — so that, feeding **only raw turns**,
beads land in semantic search, link by real causation, and the LoCoMo benchmark
reaches competitive recall. The target bead carries exactly:

- **Metadata (always present):** turn reference, session-ID reference, `title`,
  short `summary`, and **promotion state** (`retrieval_eligible` /
  supersession status).
- **Entities** — effective extraction for semantic landing on the initial search.
- **Associations** — *verifiable causal* edges between beads.
- **Claims** — narrow: marks a bead as "current truth" via its supersession chain.

Everything beyond that collapses into this structure; the deep inference fields
(`cause_candidates`/`mechanism`/`impact_level`/`*_keys`/counterfactuals/
`assumption`/`uncertainty`/`links`) and the separate extractor *classes* are
removed or folded in.

Success:
- **S1** — recall@5 on conv-26 (and full LoCoMo) materially improves over the
  0.44 baseline with the demo feeding **raw turns** (no demo-side extraction).
- **S2** — entities are **effective for semantic landing**: for `D2:2` they
  include `charity race`, `mental health`, `awareness` (noun-phrases, not just
  capitalized tokens); junk (`Making`, `That`) excluded.
- **S3** — associations are **verifiable causal** edges, not run-level tags;
  `shared_tag_overlap` is no longer the dominant edge type.
- **S4** — beads carry distinct `title`/`summary` (no title==summary==detail
  triplication) and the quality signals that make them `retrieval_eligible: true`.
- **S5** — `claims` correctly mark current truth through the supersession chain
  (the claim layer stops being empty on substantive turns).
- **S6** — the authoring pass **actually runs on the canonical write path**
  (including when a caller supplies `crawler_updates`, which bypasses it today),
  is gated/fail-open, and keeps a zero-dependency heuristic fallback for adopters
  without a chat provider.
- **S7** — the schema **slims**: the deep inference fields are removed or
  collapsed; a bead stays a small typed object, not a 55-field form.

Non-goals: changing the retrieval/traversal stack (already done); LoCoMo-specific
shaping (must be general conversational ingest); adding *more* fields — the goal
is fewer, better-filled ones.

---

## 3. Options

The work is three coordinated parts: **tighten** the schema to its core,
**fill** that core well in one pass, and **wire** that pass into the canonical
write path. The options differ in how aggressively to slim and where the LLM is
spent.

### Option A — Tighten the bead + LLM-judge the core, wired into the canonical path (recommended)
1. **Tighten:** collapse the schema to the retrieval-bearing core — metadata
   (turn ref, session ref, `title`, short `summary`, promotion state), `entities`,
   causal `associations`, `claims` (supersession). Remove or fold the deep
   inference fields (`cause_candidates`/`mechanism`/`impact_level`/`*_keys`/
   counterfactuals/`assumption`/`uncertainty`/`links`) so a bead stays small.
2. **Fill the core well:** one coherent authoring pass per turn (reuse
   `judge_bead_fields`, retargeted to the tight schema) — effective noun-phrase
   entity extraction, verifiable causal edges, distinct title/summary, and the
   quality signals for promotion — replacing the separate regex extractors.
3. **Wire it in:** ensure the canonical write path uses that pass even when a
   caller supplies `crawler_updates` (today `engine.py` ≈ L317 bypasses it):
   author first, let caller updates *augment* rather than *replace*; make a chat
   provider resolvable so it isn't silently heuristic.

- **Pros:** keeps beads small typed objects while fixing the fields recall
  actually reads; less prompt/latency than a 55-field form; benchmark reflects CM.
- **Cons:** per-turn LLM cost + latency (≈175 calls/conversation — batch/cache);
  determinism needs temp 0 + model pinning; must stay gated + fail-open; schema
  slim is a migration (existing corpora carry the dropped fields).

### Option B — Tighten + improved heuristic only (no new hard dep)
Same schema tightening as A, but authoring stays heuristic by default — a
noun-phrase/keyphrase extractor and entity/causal-overlap edges replacing the
capitalization regex and `shared_tag_overlap`; the LLM pass is opt-in behind a
chat provider.

- **Pros:** no API cost by default; still lifts the no-provider baseline; smallest
  surface.
- **Cons:** heuristic causal-edge inference is the hard part — a keyphrase
  heuristic likely won't reach competitive recall without the LLM path enabled
  (so this is really "A's fallback," not a standalone answer to the goal).

### Option C — Keep caller-supplied extraction (rejected)
Leave authoring to the caller's `crawler_updates` (CM's current de-facto
behaviour) and just document the contract. Rejected: the benchmark would measure
the *demo's* extractor, contradicting the "prove Core-Memory itself" decision.

### Recommendation
**A**, with **B's improved heuristic as the no-provider fallback** (S6). The
defining change vs. today is not "fill more fields" — it is **tighten the bead to
its retrieval-bearing core, fill that core well in one pass, and stop bypassing
it.**

---

## 4. Contract the authoring pass must satisfy

Per turn, emit one coherent `crawler_updates`-shaped payload (already consumed by
`merge_crawler_updates`) that fills the **tight core** — nothing more. Fields the
pass cannot ground are left empty, never hallucinated:

- **Metadata** — turn reference, session-ID reference, distinct `title` and short
  `summary` (carrying *different* signal — ends the title==summary==detail
  triplication so beads spread in vector space), and promotion state.
- `entities` — salient entities/noun-phrases (not just caps), deduped,
  stopword-filtered, ~≤12 (e.g. `charity race`, `mental health`, `awareness`);
  these are what land a turn in the initial semantic search.
- `associations[]` — **verifiable causal** edges with a relationship better than
  `associated_with` where inferable; **do not** derive edges from run-level tags.
- quality signals (`supporting_facts`/`because`/`state_change`/`evidence_refs`)
  sufficient for `can_be_retrieval_eligible` — so beads stop landing at
  `retrieval_eligible: false`.
- `claims[]` — only where the turn asserts a state that participates in a
  supersession chain ("current truth"); not a dumping ground (addresses both
  `claims: 0` on substantive turns and over-claiming on casual chat).

Explicitly **out of contract** (collapsed by S7): `cause_candidates`,
`effect_candidates`, `mechanism`, `impact_level`, the `*_keys` families,
`what_almost_happened`/`what_was_rejected`/`what_felt_risky`, `assumption`,
`uncertainty`, `links`, and `detail` (folds into `summary`).

Embedding text (`schema/bead_projection.build_retrieval_text`) then composes
**distinct** signal (utterance + entities + summary) from the populated core,
rather than re-projecting one triplicated utterance.

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
- **Causal-edge inference is the hard part:** "verifiable causal" must not become
  a softer `shared_tag_overlap`. Define what makes an edge verifiable (shared
  salient entity + temporal/conversational adjacency + an asserted relation) and
  how the heuristic fallback approximates it without the LLM.
- **Schema slim is a breaking migration:** removing the deep inference fields
  changes the `Bead` dataclass and on-disk projections. Sequence it (deprecate →
  stop writing → drop) and define a re-projection path for existing corpora.
- **Backfill:** existing corpora embedded under the old extractor need a rebuild;
  define a re-enrichment path alongside the slim migration.

---

## 6. Validation plan

1. Offline on conv-26: re-extract entities + recompose bead text with the chosen
   approach, re-embed (OpenAI), recompute recall@5 / answer F1 vs. the 0.44
   baseline — establishes the ceiling before full implementation (S1/S2).
2. Full LoCoMo run via the demo benchmark with the demo feeding **raw turns only**
   (no `locomo_turn_crawler` extraction) once the CM capability lands.
3. Assert S2–S5 on the `D2:2` bead specifically (entities, causal edge types,
   distinct title/summary, retrieval_eligible, claim/supersession).
4. Confirm S7: the slimmed `Bead` no longer carries the dropped inference fields,
   and recall holds or improves without them (proving they weren't load-bearing).

---

## 7. Delivery

CM capability → patch in `core-memory-demo/upstream-patches/` (push access to
Core-Memory is not available from the demo automation) → Core-Memory PR → demo
pin bump. Two coordinated CM changes: (a) the tight authoring pass + wire-in, and
(b) the schema slim (sequenced deprecate → stop-writing → drop, with a
re-projection path). Demo-side change: **remove** `locomo_turn_crawler`
extraction so the benchmark exercises CM's native path (gated behind the new pin).
