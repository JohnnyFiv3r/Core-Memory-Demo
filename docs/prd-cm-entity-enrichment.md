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

**Reframed (per maintainer guidance):** every field in the bead schema should be
**LLM-judged each turn** — treat the bead as a *form* the agent fills to the best
of its ability from the turn + shared metadata + inference. Core-Memory has the
bones of this (`policy/bead_judge.py::judge_bead_fields`, an LLM "author every
semantic field" pass) but it is **incomplete, fragmented, and bypassed** — the
three failure modes called out by the maintainer:

**① Lacking instructions — the form is half-blank.** The `bead_judge` prompt
enumerates only ~17 of the bead schema's ~55 fields
(`type, title, summary, detail, because, supporting_facts, evidence_refs,
entities, topics, state_change, validity, retrieval_eligible, retrieval_title,
retrieval_facts, effective_from, effective_to, observed_at`). It **never asks the
LLM to fill** the inference fields the schema exists to hold:
`cause_candidates`, `effect_candidates`, `mechanism`, `impact_level`, the six key
families (`incident_keys`/`decision_keys`/`goal_keys`/`action_keys`/
`outcome_keys`/`time_keys`), `what_almost_happened`, `what_was_rejected`,
`what_felt_risky`, `assumption`, `uncertainty`, `links`, richer `claims`.

**② Fragmented — a bead is assembled by 3+ disjoint mechanisms.** `bead_judge`
(LLM or regex fallback) for some fields; `claim/extraction.py` (a separate fixed
set of regex extractors — `_extract_timezone`/`_extract_location`/… → `claims: 0`
on casual chat) for claims; `association/crawler_contract.py` (a
`shared_tag_overlap` heuristic) for entities/associations. There is no single
coherent form-fill; there is **no** NER/noun-phrase pass anywhere in
`core_memory/` outside the caller-supplied crawler.

**③ Not happening in practice — the judge is bypassed.** When a caller passes
`metadata.crawler_updates` (the demo's `locomo_turn_crawler` always does),
`runtime/engine.py` (≈ line 317) uses that payload for the bead's create-fields
and **does not** use `judge_bead_fields`. So in the benchmark, beads are authored
by the demo's capitalization-regex crawler, not the LLM. Even on the non-crawler
path, the judge only runs in `auto`/`llm` mode with a **chat** provider
configured (`resolve_chat_config` → `CORE_MEMORY_CHAT_PROVIDER`/
`CORE_MEMORY_CHAT_MODEL`); the demo configures an *embeddings* provider but no
chat provider, so the judge would fall back to heuristics regardless.

Net: the inspected `D2:2` bead (title==summary==detail, entities just
`["Caroline","locomo:conv-26"]`, `associated_with`/`shared_tag_overlap` edges,
`retrieval_eligible:false`) is the output of regex extraction, **not** an LLM
form-fill — even though `judge_bead_fields` exists to do exactly that.

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

Make `judge_bead_fields` author the **entire bead schema as one coherent LLM
pass every turn** ("fill the form"), and make the canonical write path actually
use it — so that, feeding **only raw turns**, beads are richly populated and the
LoCoMo benchmark reaches competitive recall.

Success:
- **S1** — recall@5 on conv-26 (and full LoCoMo) materially improves over the
  0.44 baseline with no demo-side extraction (demo feeds raw turns).
- **S2** — the judge prompt covers the **full schema** (the ~38 currently-omitted
  fields incl. `cause_candidates`/`effect_candidates`/`mechanism`/`impact_level`,
  the `*_keys` families, the counterfactual/reflection fields, `uncertainty`,
  `links`, richer `claims`), and for `D2:2` fills salient entities
  (`charity race`, `mental health`, `awareness`) — not capitalized tokens; junk
  (`Making`, `That`) excluded.
- **S3** — associations reflect **real shared entities**, not run-level tags;
  `shared_tag_overlap` is no longer the dominant edge type.
- **S4** — judged beads are `retrieval_eligible: true` (they now carry the
  quality signals `can_be_retrieval_eligible` requires).
- **S5** — the LLM judge **actually runs on the canonical write path**, including
  when a caller supplies `crawler_updates` (today that bypasses the judge); and a
  chat provider is resolvable in the benchmark/demo so it isn't silently
  heuristic.
- **S6** — gated/fail-open so adopters without a chat provider keep today's
  zero-dependency heuristic behaviour; no hard new runtime dependency by default.

Non-goals: changing the retrieval/traversal stack (already done); LoCoMo-specific
shaping (must be general conversational ingest); replacing the heuristic fallback
(it stays as the no-provider default).

---

## 3. Options

The work is three coordinated parts (complete the form, unify the fillers, wire
it in). The options below differ in how far to take it.

### Option A — Full-schema LLM bead-field judge, wired into the canonical path (recommended)
1. **Complete the form:** expand the `judge_bead_fields` prompt + output schema
   to cover the full bead schema (add the ~38 omitted fields), with explicit
   per-field instructions and grounding/`inferred` rules (the prompt already does
   this well for `because` — extend that rigor to every field).
2. **Unify the fillers:** route claim/entity/association authoring through the
   single judge output instead of the separate regex extractors, so a turn's
   bead is one coherent form-fill (heuristic remains the fallback only).
3. **Wire it in:** ensure the canonical write path uses the judge even when a
   caller passes `crawler_updates` (today `engine.py` ≈ L317 bypasses it), e.g.
   judge first, let caller updates *augment* rather than *replace*; and make a
   chat provider resolvable so it isn't silently heuristic.

- **Pros:** realizes the "fill the form" model; benchmark genuinely reflects CM;
  every field carries judged signal → better embeddings, edges, eligibility.
- **Cons:** per-turn LLM cost + latency (175 calls/conversation — batch/cache);
  prompt-size growth; determinism needs temp 0 + model pinning; must stay
  gated + fail-open.

### Option B — Complete the form but keep heuristic default (no new hard dep)
Same prompt/schema completion as A, but the LLM judge stays opt-in behind a chat
provider; when absent, an improved heuristic (noun-phrase/keyphrase instead of
the capitalization regex) fills as much of the form as it can.

- **Pros:** no API cost by default; still lifts the no-provider baseline.
- **Cons:** heuristic ceiling well below LLM; won't reach competitive recall
  without the LLM path enabled (so this is really "A's fallback," not a standalone
  answer to the benchmark goal).

### Option C — Keep caller-supplied extraction (rejected)
Leave authoring to the caller's `crawler_updates` (CM's current de-facto
behaviour) and just document the contract. Rejected: the benchmark would measure
the *demo's* extractor, contradicting the "prove Core-Memory itself" decision, and
it leaves the schema-as-form vision unrealized.

### Recommendation
**A**, with **B's improved heuristic as the no-provider fallback** (S6). The
defining change vs. today is not "add entity extraction" — it is **make the
existing LLM judge author the whole schema and stop bypassing it.**

---

## 4. Contract the judge output must satisfy

The judge is a **full-schema form-fill**: every turn it emits one coherent
`crawler_updates`-shaped payload (already consumed by `merge_crawler_updates`)
in which **every bead field it can responsibly infer is populated**, each marked
grounded-vs-`inferred` per the existing `because` discipline. Concretely it must
fill, not leave blank:

- **Distinct narrative fields** — `title` / `summary` / `detail` that carry
  *different* signal (gist vs. one-line vs. full), ending the current
  title==summary==detail triplication so beads spread in vector space.
- `entities` — salient entities/noun-phrases (not just caps), deduped,
  stopword-filtered, ~≤12 (e.g. `charity race`, `mental health`, `awareness`).
- `topics` — semantic topics (not run-level `sample:`/`session:` tags).
- `supporting_facts` + the other quality signals (`because`, `state_change`,
  `evidence_refs`) so beads pass `can_be_retrieval_eligible` (the reason seed
  beads currently get `retrieval_eligible: false`).
- **The inference fields the schema exists to hold and the prompt omits today:**
  `cause_candidates`, `effect_candidates`, `mechanism`, `impact_level`, the six
  `*_keys` families (`incident`/`decision`/`goal`/`action`/`outcome`/`time`),
  `what_almost_happened`, `what_was_rejected`, `what_felt_risky`, `assumption`,
  `uncertainty`, `links`.
- `associations[]` — entity/topic-overlap edges with a relationship better than
  `associated_with` where inferable; **do not** derive edges from run-level tags.
- Richer `claims[]` for the claim layer (addresses `claims: 0` on casual chat).

Fields the LLM genuinely cannot ground are left empty (not hallucinated) — but
"empty because half the form was never on the prompt" (today's failure mode ①)
must end. The bar is *the agent attempts every field every turn.*

Embedding text (`schema/bead_projection.build_retrieval_text`) then composes
**distinct** signal (utterance + entities + gist) from the now-populated fields,
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
