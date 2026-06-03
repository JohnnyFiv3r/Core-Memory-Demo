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
