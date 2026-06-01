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
