# Core-Memory patches (apply to JohnnyFiv3r/Core-Memory)

Patches destined for the **Core-Memory** repo, staged here because the demo
automation can only push to `core-memory-demo`. Apply them to a fresh
Core-Memory `master`.

## `coremem-qdrant-external-embeddings.patch`

**Why:** the conv-26 benchmark showed Qdrant's top-1 cosine scores at ~0.3
(median 0.31) where a good semantic match should be 0.6-0.85+, and gold evidence
landing in the Qdrant top-8 only 14/25 times. Root cause: when
`CORE_MEMORY_VECTOR_BACKEND=qdrant`, Core-Memory **always** uses Qdrant's
built-in FastEmbed (a small ~384-dim `bge` model), regardless of
`CORE_MEMORY_EMBEDDINGS_PROVIDER=openai`. Weak anchors cap everything downstream
— graph traversal, answer F1, all of it. (Confirmed in code: the write path
hardwired `client.add()`/FastEmbed and forced the manifest provider to
`fastembed`; the read path queried by `query_text`.)

**What it adds:** `CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS=1` (default off; needs a
provider key like `OPENAI_API_KEY`):
- **Write** (`semantic_index.py`): embed the corpus with the configured external
  provider (e.g. OpenAI `text-embedding-3-large`, 3072-dim) via `_embed_vectors`,
  create the collection with `VectorParams(size=dim)`, and upsert pre-computed
  vectors. The manifest records the real provider/model/dimension.
- **Read** (`hybrid._qdrant_hybrid_rows`): when the manifest provider isn't
  `fastembed`, embed the query the same way and Qdrant **search-by-vector**;
  otherwise keep the native FastEmbed hybrid query. Reuses the existing
  `QdrantBackend.search`/`upsert` plumbing — no backend API change.
- **Collection isolation** (`_vector_collection_name`): external mode appends an
  `_ext_<model>` suffix. Qdrant collections have fixed vector params, so
  FastEmbed (~384-dim) and OpenAI (3072-dim) get **distinct collections** —
  enabling the flag (or later changing the model) targets a fresh,
  correctly-dimensioned collection instead of failing to upsert 3072-dim vectors
  into the existing ~384-dim FastEmbed collection. No manual drop required;
  switching back is non-destructive. (Addresses the dimension-mismatch a
  re-seed-alone would hit on an existing FastEmbed store.)

Default-off preserves the zero-API-key FastEmbed behaviour.

**Files:** `core_memory/retrieval/semantic_index.py`,
`core_memory/retrieval/hybrid.py`,
`tests/test_qdrant_external_embeddings.py` (new).

**Validation:** verified `git apply --check` on a fresh `master` clone; 231
retrieval tests pass with the change applied; 3 new tests cover the flag + both
query routes. (Real Qdrant+OpenAI not exercised locally — not installed — so the
routing is tested with mocks; the true proof is a deployed re-embed + benchmark.)

## How to apply

```bash
git clone https://github.com/JohnnyFiv3r/Core-Memory.git
cd Core-Memory
git checkout -b feat/qdrant-external-embeddings master
git am /path/to/coremem-qdrant-external-embeddings.patch
git show --stat HEAD          # expect: semantic_index.py, hybrid.py, + new test
python -m pytest tests/test_qdrant_external_embeddings.py -v
git push -u origin feat/qdrant-external-embeddings
```

## After it merges (demo side)
1. Bump the demo pin in `backend/requirements.txt` to the merge SHA.
2. In `render.yaml` (web + worker) add:
   ```
   - key: CORE_MEMORY_QDRANT_EXTERNAL_EMBEDDINGS
     value: "1"
   - key: CORE_MEMORY_EMBEDDINGS_PROVIDER
     value: openai
   - key: CORE_MEMORY_EMBEDDINGS_MODEL
     value: text-embedding-3-large
   ```
   (`OPENAI_API_KEY` is already configured.)
3. Re-seed / rebuild the semantic index so the corpus is re-embedded with the
   new provider, then re-run conv-26 to measure the recall lift.

## TODO: complete external embeddings on the live write path (`_mirror_bead_to_backends`)

**Status:** spec only (no `.patch` yet — needs a Core-Memory checkout at the pinned
commit to generate accurate hunks).

**Why:** the original external-embeddings patch covered the batch *build* path
(`build_semantic_index`) and the *read* path (`hybrid._qdrant_hybrid_rows`), but
**not** the live per-bead write path. `core_memory/persistence/store_add_bead_ops.py:
_mirror_bead_to_backends` constructs the Qdrant backend at the manifest dimension
(e.g. 3072 for `text-embedding-3-large`) but always upserts via
`upsert_texts()` → `client.add()` → **FastEmbed (384-dim)**. Every live bead write
then throws:

```
qdrant upsert failed for bead <id>: Collection have incompatible vector params: size=3072 ...
```

It's swallowed (logged at WARNING), so live mirroring silently no-ops in external
mode and the worker logs are flooded during benchmark replay/flush/QA-bead writes.

**Fix:** make `_mirror_bead_to_backends` provider-aware, mirroring
`_qdrant_hybrid_rows`. Read `provider`/`model` from the manifest; when
`provider != "fastembed"`, embed the bead text with that provider and `upsert()`
the pre-computed vector instead of `upsert_texts()`:

```python
from core_memory.retrieval.semantic_index import (
    _create_external_backend, _paths, _embed_vectors, _vector_rows,
    _default_embedding_model,
)
manifest_file, *_ = _paths(root_path)
dimension, provider, model = 1536, "fastembed", ""
try:
    m = json.loads(manifest_file.read_text(encoding="utf-8"))
    dimension = int(m.get("dimension") or 1536)
    provider = str(m.get("provider") or "fastembed").strip().lower() or "fastembed"
    model = str(m.get("model") or "").strip()
except Exception:
    pass
vec_backend = _create_external_backend(root=root_path, backend=VECTOR_BACKEND_QDRANT, dimension=dimension)
payload, text, bead_id = _bead_payload(bead), _embed_text(bead), str(bead.get("id") or "")
if provider != "fastembed":
    vecs = _embed_vectors(texts=[text], provider=provider,
                          model=(model or _default_embedding_model(provider)), hash_dim=dimension)
    vec_backend.upsert(bead_id=bead_id, embedding=list(list(_vector_rows(vecs))[0]), metadata=payload)
else:
    vec_backend.upsert_texts(bead_ids=[bead_id], texts=[text], metadatas=[payload])
```

**Note (demo side):** the benchmark no longer depends on this. The lifecycle
runner rebuilds the semantic index per isolated QA root, so recall is served by
the authoritative `build_semantic_index` (which already embeds externally). This
upstream fix stops the log spam and makes *live* (non-benchmark) writes use the
configured external provider for incremental indexing instead of silently
falling back to FastEmbed.

## DONE: request-scoped bead-judge directive (`CORE_MEMORY_BEAD_JUDGE_FALLBACK` was process-global)

**Status:** ✅ landed upstream as **Core-Memory #182** (`97df332`) — `metadata["bead_judge"]`
/ `req["_bead_judge"]` is now honored by `_judge_fallback_enabled(req)` and
`judge_bead_fields(..., mode=)` (and forwarded in `_judged_turn_bead`), falling
back to env when absent. Demo wired to it: pin bumped to `97df332`,
`benchmark_enrich_mode` no longer touches env, and the replay + QA write paths set
`metadata["bead_judge"]="llm"` per-request in judge mode. The spec below is kept
for the record.

**Why:** the judge-fallback decision is read from process-global env mid-turn and
applied to *supplied* crawler_updates rows, so it can't be scoped to one job:

- `runtime/engine.py:_judge_fallback_enabled()` reads `CORE_MEMORY_BEAD_JUDGE_FALLBACK`.
- `runtime/engine.py:_ensure_turn_creation_update()` calls
  `_maybe_apply_judge_fallback(row, ...)` on **every supplied `beads_create` row**
  when that env is set, LLM-filling any missing semantic field.
- `policy/bead_judge.py:judge_bead_fields()` reads `CORE_MEMORY_BEAD_FIELD_JUDGE_MODE`.

The demo runs benchmarks in worker threads in one process (inline mode). If a
judge-mode run sets the env and is then orphaned by the watchdog/supersede path
while stuck in an un-timed LLM call, a concurrently-starting *deterministic* run
on another thread sees the leaked env and has its supplied beads LLM-augmented →
corrupted, non-deterministic results. (The deployed queue/cron path runs one job
per process, so it is not exposed — this is for inline/local correctness, and so
the demo can pass judge intent per-request instead of mutating global env.)

**Fix:** honor a per-request `bead_judge` directive carried on `req`/`metadata`,
falling back to env for backward compat:

```python
# runtime/engine.py
def _req_judge_directive(req: dict | None) -> str | None:
    md = dict((req or {}).get("metadata") or {})
    val = str((req or {}).get("_bead_judge") or md.get("bead_judge") or "").strip().lower()
    return val or None  # "llm" | "heuristic" | "off" | None(=use env)

def _judge_fallback_enabled(req: dict | None = None) -> bool:
    d = _req_judge_directive(req)
    if d is not None:
        return d in {"llm", "heuristic", "1", "true", "on"}
    return str(os.getenv("CORE_MEMORY_BEAD_JUDGE_FALLBACK", "0")).strip().lower() in {"1","true","yes","on"}

def _maybe_apply_judge_fallback(row, user_query, assistant_final, *, req: dict | None = None):
    if not _judge_fallback_enabled(req):
        return row
    judged = judge_bead_fields(user_query, assistant_final, mode=_req_judge_directive(req))
    ...
```

- Thread `req` into `_maybe_apply_judge_fallback` / `_judged_turn_bead` /
  `_default_crawler_updates` calls in `_ensure_turn_creation_update` (it already
  has `req`).
- `policy/bead_judge.judge_bead_fields(user_query, assistant_final, mode=None)` —
  add the optional `mode`; when `None`, read `CORE_MEMORY_BEAD_FIELD_JUDGE_MODE`.

Default-None preserves today's env behavior. Then the demo passes
`metadata["bead_judge"]="llm"` per replay turn (request-scoped) and stops setting
`CORE_MEMORY_BEAD_JUDGE_FALLBACK` / `CORE_MEMORY_BEAD_FIELD_JUDGE_MODE` process-wide,
eliminating the cross-job leak entirely.

**After it merges (demo side):** bump the pin; in `benchmark_enrich_mode` drop the
env writes; in `_locomo_replay_metadata` set `metadata["bead_judge"]="llm"` (judge
mode) and keep omitting `crawler_updates`. The thread-local mode flag can then be
removed in favor of the per-request metadata directive.

## SPEC: engine findings from benchmark run `bench-c25084e5c4` (conv-26, LoCoMo)

Three engine-side issues surfaced by an end-to-end diagnosis of a 20-QA conv-26
run. (The run was deterministic — `enrich_mode` was not set to `judge` — so #182
is still unvalidated; these are orthogonal to the judge and limit recall even with
it. Demo-side guards for "judge requested but not engaged" and these symptoms have
landed, but the fixes below are engine-side.)

### 1. Retrieval effort tiers are a no-op (`recall(req, effort=...)`)
`core_memory.retrieval.agent.recall` returns an **identical candidate set** for
`effort ∈ {low, medium, high}` — verified across **20/20 QA** (same bead IDs, same
order). The benchmark calls recall three times per QA (only `high` is used to
answer), so this is ~3× retrieval latency for one usable result.

**Ask:** make effort monotonically widen recall, or drop the parameter:
- `low` = vector top-k only;
- `medium` = + 1-hop association expansion;
- `high` = + multi-hop graph traversal / claim expansion.
If effort is intentionally answer-only and never affects retrieval, document that
so callers can collapse the tiers.

### 2. `causal_crawler` over-types beads to `reflection`/`meta_analysis`
Deterministic crawler_updates author `type:"context"`. The engine's causal_crawler
then re-types **91/92 beads** to `reflection` (`reflection_type=meta_analysis`) on
the first causal edge. Each bead's `type_log` shows
`context (initial_write) → reflection (causal_crawler, edge_count=1)`. Typing nearly
every chat turn as a meta-analytical reflection is implausible and degrades
type-aware ranking (and any per-type retrieval gating).

**Ask:** causal_crawler should not change a bead's type merely because an edge was
added. Re-type to `reflection` only when the bead content is actually reflective;
otherwise preserve the authored/inferred type. (In judge mode, the bead-field judge
assigns the real type — so this mainly bites the deterministic/non-judge path, but
the "any edge ⇒ reflection" rule looks wrong in both.)

### 3. Multi-hop recall breadth
Evidence recall@5 by LoCoMo category on this run: **cat-2 (single-fact) 0.90** vs
**cat-1 (multi-hop) 0.34**. Questions whose gold evidence spans 2–4 turns retrieve
at most one of them in the top-k; the single-vector query can't gather
complementary evidence (e.g. "moved 4 years ago" + "from Sweden" live in different
turns and only one is recalled). Even when both are retrieved, the answer can't be
synthesized without a bridging claim.

**Ask:** when a query's anchors fan out to multiple beads, expand recall along the
association/claim graph (k-hop) so co-required evidence is co-retrieved, rather than
returning the top-k nearest single vectors. This is the primary lever for multi-hop
F1 and composes directly with judge-authored claims/entities (#182): claims give the
graph the bridges, traversal gathers them.

**Demo-side (already landed, for context):** the report now records
`config.enrich_mode` + `enrich_mode_engaged`; a `judge` run that authors 0 claims
fails closed (`benchmark_judge_requested_but_not_engaged`); and the report carries
`scores.retrieval_varies_by_effort=false` + warnings `retrieval_identical_across_efforts`
and `bead_type_skew:<type>:<share>` so #1 and #2 are visible in artifacts.

## DONE: #183 follow-up — make effort-hop evidence rank competitively

**Status:** ✅ landed upstream as **Core-Memory #185** (`11b706c`). Hop items are
now scored `seed_score × rel_weight × confidence × HOP_DECAY` (causal/semantic
edges 0.82–0.90 > associative 0.55–0.60 > temporal 0.35; 0.80 decay/hop), the full
evidence list is re-sorted post-expansion, and the strongest causal neighbours are
kept when capping. Both asks below are addressed. Demo pinned to `11b706c`; the
`MULTI_HOP_RETRIEVAL_K=12` floor stays as a complementary lever. Spec kept for
the record.

After #183 landed (pin `4f8929b`), a deterministic conv-26 re-run confirmed the
two fixes work but **recall@5 did not move** (0.6625, byte-identical to the prior
run; cat-1 multi-hop still 0.344). Diagnosis of the retrieved rows shows why:

1. **Hop items are scored below the vector floor and never rank into top-k.**
   `retrieved_count` grew 8→24 at `high` (2-hop expansion is firing), but every
   hop item sits at a flat `min_vector_score − 0.05` (≈0.35) at ranks 9–24. So
   they don't affect recall@5/@8 and only nudge `hit_any` (0.80→0.85). The
   co-required multi-hop evidence is retrieved-but-buried.
   **Ask:** score hop items on association strength × source score (and hop
   distance decay) so a strongly-linked 1-hop neighbour can rank among the top-k,
   instead of pinning all hop items to a constant sub-floor. They should be able
   to displace weak vector matches when the association is strong.

2. **The association graph is too sparse to reach multi-hop gold.** For the hard
   misses (e.g. q0008 gold `D3:13`/`D2:14`), the gold is not within 2 hops at all,
   so expansion adds noise neighbours rather than the answer. In the deterministic
   path the graph is entity-overlap only (≤3 `supports` edges/turn). Judge mode
   (#182) should help by authoring richer entities/claims, but the traversal also
   needs to follow semantic/claim edges, not just lexical entity overlap.
   **Ask:** when expanding, prefer association edges that connect
   semantically-related-but-lexically-different beads (claim/temporal/causal),
   not only shared-surface-entity edges.

**Demo-side mitigation already shipped:** multi-hop questions (LoCoMo cat 1) now
use a higher retrieval-k floor (`MULTI_HOP_RETRIEVAL_K=12` vs the single-hop
default 8) so vector-near gold at ranks 9–12 is no longer cut off. This is a
partial lever only — it can't surface evidence the graph never reaches (#2) or
re-rank sub-floor hop items (#1); those remain engine-side.
