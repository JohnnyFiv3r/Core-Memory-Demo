# Problem statement: bead authoring caps conversational recall in Core-Memory

**Purpose:** a precise, evidence-first description of a bead-quality problem
observed while benchmarking Core-Memory on LoCoMo via `core-memory-demo`. It is
written to be picked up in a **Core-Memory workspace with write access** — it
describes *what we observe and where it originates*, not a prescribed fix.

**Scope:** the issue is in **bead authoring / enrichment** (how a turn becomes a
bead), upstream of retrieval. The retrieval/traversal stack has already been
tuned and is not the bottleneck (see §6).

---

## 1. One-paragraph summary

When Core-Memory ingests conversational turns, the resulting beads are
low-signal: the `title`, `summary`, and `detail` are the same utterance
triplicated; entity extraction is a capitalized-token regex that misses the
salient noun-phrases and captures junk; and associations are dominated by a
`shared_tag_overlap` heuristic that links every bead in a run to every other
(because they all carry the same run-level tags). Because semantic search lands
on entities/text and graph traversal expands along associations, weak beads cap
recall *no matter how good the embeddings or traversal tuning are*. Separately,
the bead schema is very wide (~55 fields), most of which the retrieval path never
reads — so effort spent populating them does not help, while the few fields that
matter are weakly filled.

---

## 2. Observed evidence (conv-26, bead `D2:2`)

Source utterance (LoCoMo conv-26):

> "That charity race sounds great, Mel! … raising awareness for mental health …"

The bead Core-Memory produced (abridged to the salient fields):

```json
{
  "id": "D2:2",
  "title":   "That charity race sounds great, Mel! ...",
  "summary": "That charity race sounds great, Mel! ...",
  "detail":  "That charity race sounds great, Mel! ...",
  "entities": ["Caroline", "locomo:conv-26"],
  "associations": [
    {"target": "...", "relationship": "associated_with",
     "reason_code": "shared_tag_overlap"}
  ],
  "retrieval_eligible": false
}
```

Four concrete defects in this single bead:

1. **Triplicated text.** `title == summary == detail` — one utterance copied
   into three fields. The bead carries no distinct gist/short/full signal, so it
   does not spread in vector space relative to its neighbours.
2. **Weak entities.** Extraction captured the speaker (`Caroline`) and a
   boilerplate run tag (`locomo:conv-26`). It **missed** the salient
   noun-phrases that a query would match on — `charity race`, `mental health`,
   `awareness` — and in other beads captures junk tokens like `Making`, `That`.
3. **Noise associations.** The only edge type is `associated_with` with
   `reason_code: shared_tag_overlap`. Every bead in the conversation shares the
   same `sample:`/`session:` tags, so this heuristic links everything to
   everything — the graph is near-complete and carries no real structure.
4. **Not retrieval-eligible.** The bead is `retrieval_eligible: false` because it
   lacks the quality signals the eligibility gate requires (see §4) — so it is
   excluded from recall entirely.

This bead is representative, not cherry-picked: it is the standard output of the
built-in heuristic authoring path for casual conversational turns.

---

## 3. What a good bead would look like (desired end state)

For the same utterance, a useful bead would carry a **tight, well-filled core**:

- **Distinct** `title` (gist) and short `summary` — not the raw utterance copied.
- **Effective entities** for semantic landing: `charity race`, `mental health`,
  `awareness`, `Mel` — noun-phrases, junk excluded.
- **Verifiable causal associations** — edges to beads that are actually related
  (same entities / a real asserted relation), not run-tag overlap.
- **Promotion/quality signals** sufficient to be `retrieval_eligible: true`.
- **Claims** only where the turn asserts a state that participates in a
  supersession chain ("current truth").
- Metadata: turn reference, session-ID reference, promotion state.

The point is *fewer, better-filled* fields — a small typed memory object — not a
larger form.

---

## 4. Where this originates in Core-Memory

The defects map to specific mechanisms in `core_memory/`. (Line numbers are
approximate, from investigation against the pinned commit
`c0c85606ddb3799b171f6fea9a67d35c2bfea66e`.)

**Entities — capitalized-token regex.** The only entity extraction reachable on
the conversational path is a capitalization regex (in the demo's crawler,
`_text_entities`, mirrored by Core-Memory's heuristic fallback
`_heuristic_entities`). It keys on `[A-Z]...` tokens, which is why it gets
speaker names and misses lowercase noun-phrases (`charity race`,
`mental health`). There is **no** NER / noun-phrase extraction anywhere in
`core_memory/` outside the caller-supplied crawler.

**Associations — `shared_tag_overlap`.** `association/crawler_contract.py`
derives edges from shared tags. Because run-level tags (`sample:`, `session:`)
are attached to every bead, the dominant edge is `associated_with` /
`shared_tag_overlap`, producing a near-complete, structureless graph.

**Triplication — projection re-uses one field.** The retrieval text builder
(`schema/bead_projection.build_retrieval_text`) composes from fields that are
themselves the same utterance, so the embedded text is the triplicated string.

**Eligibility gate — needs signals the heuristic doesn't produce.**
`schema/models.py::can_be_retrieval_eligible` (≈ line 585) requires
`is_retrieval_rich()` **and** at least one quality signal
(`because` / `supporting_facts` / `state_change` / `evidence_refs` /
`supersedes` / `superseded_by`). The heuristic path doesn't populate these, so
beads land at `retrieval_eligible: false`.

**An LLM authoring pass exists but is fragmented and bypassed.**
`policy/bead_judge.py::judge_bead_fields` is an LLM pass that authors semantic
fields — but:
  - It is **fragmented** from the other authoring mechanisms: claims come from a
    separate fixed regex set (`claim/extraction.py` —
    `_extract_timezone`/`_extract_location`/… → `claims: 0` on casual chat) and
    entities/edges come from `crawler_contract.py`. There is no single coherent
    authoring pass.
  - It is **bypassed** on the canonical write path: when a caller supplies
    `metadata.crawler_updates` (the demo's `locomo_turn_crawler` always does),
    `runtime/engine.py` (≈ line 317) uses that caller payload and does **not**
    call `judge_bead_fields`.
  - Even off that path it only runs in `auto`/`llm` mode with a **chat** provider
    configured (`resolve_chat_config` → `CORE_MEMORY_CHAT_PROVIDER` /
    `CORE_MEMORY_CHAT_MODEL`). A deployment that configures only an *embeddings*
    provider gets the heuristic fallback silently.

**The schema is very wide.** `schema/models.py` `Bead` carries ~55 fields,
including inference fields the retrieval path never reads:
`cause_candidates`, `effect_candidates`, `mechanism`, `impact_level`, the six
`*_keys` families (`incident`/`decision`/`goal`/`action`/`outcome`/`time`),
`what_almost_happened`, `what_was_rejected`, `what_felt_risky`, `assumption`,
`uncertainty`, `links`. These do not contribute to recall but widen the surface
that authoring must reason about.

---

## 5. Why this caps recall (downstream effect)

The retrieval pipeline reads exactly the fields that are weak:

- **Semantic landing** (`retrieval/pipeline/canonical.py::_qdrant_hybrid_rows`):
  the initial anchor set comes from a vector search over the bead's projected
  text + entities. Triplicated text and missing noun-phrases mean the right
  beads don't rank as anchors.
- **Graph expansion** (`trace_request` / causal traversal): traversal expands
  from anchors **along associations**. When associations are
  `shared_tag_overlap` noise, expansion adds noise rather than the true
  neighbours.
- **Eligibility**: `retrieval_eligible: false` beads are excluded outright.

So the ceiling is set at authoring time. On LoCoMo this shows up as recall@5
stuck at ≈ 0.44 with low answer F1, against competitive systems at 0.8+.

---

## 6. What has already been ruled out

So the Core-Memory chat does not re-chase these — each was fixed and did **not**
move the recall number, which is what localized the problem to authoring:

- **Traversal never ran on hosted Kuzu** — fixed (recall traversal seed/merge +
  backend path scoping). Traversal now runs.
- **Weak FastEmbed anchors (~0.3 cosine)** — switched Qdrant to external OpenAI
  embeddings (`text-embedding-3-large`); vectors isolated in an `_ext_<model>`
  collection.
- **Benchmark silently using `hash` embeddings** — fixed; the benchmark now
  inherits the configured embeddings provider.
- **Trace seed/merge tuning** — widened seed anchors and chain-merge budget.

None of these changed the outcome, because they all operate on a corpus of
low-signal beads.

---

## 7. How to reproduce / inspect

- Corpus: LoCoMo conv-26; the representative bead is `D2:2`.
- Inspect any bead's `title`/`summary`/`detail`, `entities`, `associations[]`
  (`relationship` + `reason_code`), and `retrieval_eligible`. The four defects in
  §2 recur across casual conversational turns.
- The authoring path can be exercised directly in a Core-Memory workspace by
  ingesting raw conversational turns (no caller-supplied `crawler_updates`) and
  examining the resulting beads.
