# LoCoMo seam and integration research

> Phase 0 fencing note: treat this as historical/context research. Authoritative lifecycle implementation guidance now lives in `../../docs/locomo-lifecycle-benchmark-prd.md`; mode boundaries live in `locomo-benchmark-mode-matrix.md`.

Status: research-only documentation for adapter planning
Source repo cloned at: `/home/node/.openclaw/workspace/locomo`
Observed branch/commit: `main` @ `3eb6f2c`

## Scope

This document maps the real seam surfaces in the upstream LoCoMo repository so we can wire LoCoMo into the adapter-only Core Memory rebuild without inventing fake boundaries.

Primary goals:
- identify LoCoMo data contracts
- identify LoCoMo evaluation entrypoints
- identify LoCoMo retrieval database construction seams
- identify where LoCoMo assumes transcript, session-summary, and observation authority
- map those seams onto the canonical Core Memory adapter surfaces already documented in `adapter-only-integration-research.md`

This is research-first and does not change behavior.

---

## Repo overview

Top-level relevant files:
- `README.MD`
- `data/locomo10.json`
- `generative_agents/generate_conversations.py`
- `generative_agents/memory_utils.py`
- `generative_agents/conversation_utils.py`
- `task_eval/evaluate_qa.py`
- `task_eval/evaluation.py`
- `task_eval/rag_utils.py`
- `task_eval/get_facts.py`
- `task_eval/get_session_summaries.py`
- evaluation shell scripts under `scripts/`

What LoCoMo is, per repo/readme:
- a benchmark of 10 very long multi-session conversations
- main released task here is question answering
- also includes generated observations and session summaries used as RAG databases
- event-summary annotations exist as a separate task surface

---

## Canonical upstream LoCoMo data contract

Primary dataset file:
- `data/locomo10.json`

Observed top-level structure:
- JSON list
- length: `10`
- each row keys:
  - `sample_id`
  - `conversation`
  - `observation`
  - `session_summary`
  - `event_summary`
  - `qa`

### Conversation structure

Per `README.MD` and direct inspection, `conversation` contains:
- `speaker_a`
- `speaker_b`
- repeating session fields:
  - `session_<n>_date_time`
  - `session_<n>`

Each `session_<n>` is a list of turn dicts that may include:
- `speaker`
- `dia_id`
- `text`
- optional image-related fields such as:
  - `img_url`
  - `blip_caption`
  - image retrieval query metadata

This is the most important LoCoMo authority surface for adapter work.

Why it matters:
- this is the source transcript, not an already-memory-shaped representation
- any Core Memory ingestion adapter should treat LoCoMo `conversation` as transcript input, not as pre-built beads or associations

### QA structure

Observed `qa` rows contain:
- `question`
- `answer`
- `category`
- `evidence`

Example:
- question: `When did Caroline go to the LGBTQ support group?`
- answer: `7 May 2023`
- evidence: `['D1:3']`
- category: `2`

Meaning of evidence shape:
- evidence anchors are dialog identifiers, not memory object ids
- adapter implication: if we want faithful evaluation, we must preserve a mapping from LoCoMo dialog ids into Core Memory source-turn provenance

### Observation structure

Observed shape:
- dict with keys like `session_1_observation`, `session_2_observation`, ...

Per README:
- observations are generated from each session and used as one RAG database

### Session summary structure

Observed shape:
- dict with keys like `session_1_summary`, `session_2_summary`, ...

Per README:
- generated summaries are used as another RAG database
- these are explicitly different from annotated `event_summary`

### Event summary structure

Observed shape:
- dict with keys like `events_session_1`, `events_session_2`, ...

Per README:
- annotated significant events per speaker, per session
- event summarization task ground truth

---

## Upstream LoCoMo evaluation seam

### Main QA entrypoint: `task_eval/evaluate_qa.py`

This is the top-level evaluator driver.

Arguments:
- `--out-file`
- `--model`
- `--data-file`
- `--use-rag`
- `--use-4bit`
- `--batch-size`
- `--rag-mode`
- `--emb-dir`
- `--top-k`
- `--retriever`
- `--overwrite`

Behavior:
1. selects model backend by name family
   - GPT
   - Claude
   - Gemini
   - HF local models like Gemma/Llama/Mistral
2. loads dataset from `data-file`
3. builds prediction key naming scheme
4. iterates sample-by-sample
5. delegates answer generation to backend-specific helpers:
   - `get_gpt_answers(...)`
   - `get_claude_answers(...)`
   - `get_gemini_answers(...)`
   - `get_hf_answers(...)`
6. evaluates returned answers with `eval_question_answering(...)`
7. writes augmented output JSON
8. computes aggregate stats via `analyze_aggr_acc(...)`

Key seam conclusion:
- upstream LoCoMo cleanly separates answer generation from answer scoring
- for adapter rebuild, the safest insertion point is to replace the answer-generation backend with a Core Memory-backed runner while keeping LoCoMo scoring semantics intact

### QA scoring contract: `task_eval/evaluation.py`

Canonical evaluator function:
- `eval_question_answering(qas, eval_key='prediction', metric='f1')`

Observed category handling:
- category `2, 3, 4`: single-hop/temporal/open-domain style, scored by token-level F1-like function
- category `1`: multi-hop, scored with split multi-answer F1
- category `5`: adversarial/no-info style, judged by detecting answers like `no information available` or `not mentioned`

Observed retrieval-recall contract:
- if a prediction context field exists and evidence exists, recall is computed by checking whether gold evidence anchors appear in returned context ids
- context ids can be:
  - session ids like `S<n>`
  - dialog ids like `D1:3`

Adapter consequence:
- if we want comparable LoCoMo evaluation, our adapter should preserve or emulate these context-id surfaces:
  - dialog-level retrieval ids for transcript retrieval
  - session-level ids for summary retrieval

This is one of the most important seam findings.

---

## Upstream LoCoMo RAG/database seams

### 1. Observation generation: `task_eval/get_facts.py`

Role:
- generate observation database from transcript sessions
- then embed that database for retrieval

Arguments:
- `--out-file`
- `--data-file`
- `--emb-dir`
- `--prompt-dir`
- `--use-date`
- `--overwrite`
- `--retriever`

Core behavior:
1. load conversation samples
2. iterate sessions in each sample
3. generate `session_<n>_observation` if missing via:
   - `generative_agents.memory_utils.get_session_facts(...)`
4. flatten facts into retrieval database rows
5. attach date string and `dia_id` per fact
6. embed with `get_embeddings(...)`
7. write per-sample pickle database with:
   - `embeddings`
   - `date_time`
   - `dia_id`
   - `context`

Important seam:
- observations are not authoritative annotations, they are generated derived retrieval corpora
- they are closer to a benchmark-specific retrieval database than to canonical memory state

Adapter implication:
- in Core Memory integration, these should likely remain benchmark-owned derivative artifacts, not canonical beads unless we intentionally model them as generated summaries/notes

### 2. Session summary generation: `task_eval/get_session_summaries.py`

Role:
- generate one summary per session
- embed summaries for session-level retrieval

Core behavior:
1. iterate sessions
2. generate `session_<n>_summary` via `get_session_summary(...)`
3. assign context ids as `S<n>`
4. embed summaries
5. write per-sample pickle database with:
   - `embeddings`
   - `date_time`
   - `dia_id` as session ids
   - `context` summaries

Important seam:
- session summaries are generated text abstractions over session transcript
- they are benchmark-side retrieval views, not the raw evaluation authority

Adapter implication:
- these map conceptually to continuity/session-summary retrieval layers, but should not replace transcript provenance for QA evidence alignment

### 3. Retrieval utility layer: `task_eval/rag_utils.py`

Role:
- embedding/retriever abstraction
- building dialog/session retrieval matrices

Important functions:
- `init_context_model(retriever)`
- `init_query_model(retriever)`
- `get_embeddings(retriever, inputs, mode='context')`
- `get_context_embeddings(retriever, data, context_tokenizer, context_encoder, captions=None)`

Important design assumptions:
- retrieval contexts are flat text chunks with explicit external ids
- chunk ids are often LoCoMo-native dialog ids (`dia_id`) or session ids (`S<n>`)
- several retriever backends are supported:
  - dpr
  - contriever
  - dragon
  - openai embeddings

Adapter implication:
- LoCoMo’s evaluation is retrieval-backend-agnostic as long as chunk identity is preserved
- for Core Memory adapter work, we can swap the retrieval engine, but must preserve enough id/provenance mapping for QA recall comparability

---

## Upstream generated-memory seam

### `generative_agents/memory_utils.py`

This file is not Core Memory, but it is LoCoMo’s internal notion of generated memory artifacts.

Important functions:
- `get_session_facts(...)`
- `get_session_reflection(...)`
- `get_recent_context(...)`
- `get_relevant_context(...)`

### `get_session_facts(...)`

Role:
- converts one session transcript into a structured set of speaker observations using prompting

Inputs:
- conversation session transcript
- prompt examples from `prompt_examples/fact_generation_examples_new.json`

Output shape:
- JSON facts grouped by speaker name
- each fact paired with a dialog id

Important architecture fact:
- this is a benchmark-specific information extraction pass over transcript, not canonical memory state

For adapter planning, this means:
- if we ingest LoCoMo transcript into Core Memory, this function is better thought of as an optional auxiliary observation generator, analogous to a benchmark-owned crawler or derived retrieval view
- it should not be treated as the authority source of memory truth

### Reflection helpers

Functions:
- `get_session_reflection(...)`
- `get_recent_context(...)`
- `get_relevant_context(...)`

These belong to LoCoMo’s synthetic-agent conversation-generation stack, not its released QA benchmark contract.

Adapter implication:
- useful for understanding how upstream authors thought about memory-like abstractions
- probably out of scope for the first adapter-only benchmark rebuild unless we intentionally support conversation regeneration or benchmark extensions

---

## Upstream conversation-generation seam

### `generative_agents/generate_conversations.py`

Role:
- upstream synthetic conversation generator for creating long-term multi-session chats

This is not required for basic QA benchmarking, but it clarifies the data lineage.

Observed responsibilities:
- persona loading/generation
- event generation and date assignment
- session generation over time
- optional BLIP captions / images
- optional reflection and summaries
- writes updated agent state over multiple sessions

Why this matters:
- the released LoCoMo dataset is transcript-first and comes from this broader generation pipeline
- but the benchmark integration surface we care about for Core Memory is still the released dataset contract, not this full generation stack

Adapter conclusion:
- do not bind the first integration to the generative pipeline
- treat generation code as ancillary research context, not as the primary adapter seam

---

## Real authority surfaces in LoCoMo

For adapter design, LoCoMo has multiple layers. They should not be confused.

### Authority level 1: transcript + QA annotations

Primary benchmark authority:
- `conversation`
- `qa`

These define:
- what happened
- what questions are asked
- what answers and evidence are gold

This should be the primary ingestion and evaluation authority.

### Authority level 2: event-summary annotations

Secondary authority for a different task:
- `event_summary`

This is not the main QA authority, but it is human annotation and may later be useful for testing summarization/event extraction quality.

### Authority level 3: generated retrieval views

Derived, non-authoritative benchmark helper layers:
- `observation`
- `session_summary`
- pickled embedding databases from `get_facts.py` and `get_session_summaries.py`

These are useful for RAG-style baselines, but they are not the underlying truth.

Adapter implication:
- Core Memory integration should ingest from transcript authority first
- generated observations/summaries can be optional comparative retrieval surfaces or benchmark artifacts

---

## Mapping LoCoMo to canonical Core Memory seams

This section maps the upstream LoCoMo surfaces to the real Core Memory seams documented separately.

### A. LoCoMo transcript ingestion

LoCoMo source:
- `conversation.session_<n>[turn]`
- fields include `speaker`, `dia_id`, `text`, optional image metadata

Best Core Memory seam:
- transcript/turn ingestion should flow through canonical turn boundary:
  - `process_turn_finalized(...)`
  - or adapter wrapper `run_with_memory(...)` when using live agent output

But for benchmark replay, there is an important nuance:
- LoCoMo transcript rows are already historical turns
- they are not queries waiting for model answers

So the adapter likely needs a benchmark replay ingestion mode that:
- maps each LoCoMo dialog row into a turn/transcript record in canonical memory surfaces
- preserves original `dia_id` in metadata or source-turn provenance
- preserves session boundaries from `session_<n>` and `session_<n>_date_time`

Design rule:
- ingest transcript as transcript history, not as direct bead fabrication bypassing canonical write surfaces

### B. Evidence alignment

LoCoMo gold QA evidence uses dialog ids like `D1:3`.

Best Core Memory seam:
- retain LoCoMo `dia_id` in turn metadata and in any source-turn mapping
- use canonical hydration/inspect APIs to expose provenance

Required adapter property:
- every memory artifact derived from a LoCoMo turn should remain traceable back to original `dia_id`

Without that, recall comparisons to LoCoMo evidence become mushy.

### C. Observation database mapping

LoCoMo source:
- `get_session_facts(...)`
- `session_<n>_observation`

Best Core Memory interpretation:
- benchmark-specific derived retrieval corpus
- conceptually similar to extracted observation notes or optional benchmark-owned summaries

Recommendation:
- keep this as an optional adapter-layer comparative retrieval database, not as canonical memory authority
- if we eventually ingest them, mark clearly as generated/derived artifacts with provenance

### D. Session summary mapping

LoCoMo source:
- `session_<n>_summary`
- retrieval id `S<n>`

Best Core Memory mapping:
- conceptually resembles session-level continuity or summary notes
- but upstream LoCoMo uses them as benchmark retrieval chunks, not canonical runtime continuity

Recommendation:
- keep session summaries as optional benchmark retrieval view
- do not let them override transcript-grounded canonical continuity surfaces

### E. QA generation seam

LoCoMo source seam:
- answer-generation functions called by `task_eval/evaluate_qa.py`

Best Core Memory adapter seam:
- replace or wrap answer generation with a benchmark runner that queries Core Memory-backed retrieval/agent logic
- leave `eval_question_answering(...)` scoring unchanged for apples-to-apples comparison

This is the cleanest adapter-only evaluation seam.

### F. Retrieval seam

LoCoMo source seam:
- `task_eval/rag_utils.py`

Best Core Memory adapter seam:
- either map LoCoMo benchmark retrieval requests into canonical retrieval tool facade:
  - `core_memory.retrieval.tools.memory.execute(...)`
  - `search(...)`
  - `trace(...)`
- or build a thin benchmark runner around inspect/hydration surfaces

Important constraint:
- preserve chunk identity and provenance expected by LoCoMo scoring

---

## Recommended adapter-only integration strategy for LoCoMo

### Phase 1, transcript-authority benchmark integration

1. Treat LoCoMo `conversation` as the only ingestion authority for QA benchmarking.
2. Replay transcript into canonical Core Memory runtime/session surfaces while preserving:
   - session number
   - session date/time
   - speaker
   - original `dia_id`
3. Keep LoCoMo QA scoring logic unchanged.
4. Build a Core Memory-backed answer runner that answers `qa.question` from the ingested conversation state.
5. Use canonical inspect/hydration APIs to support provenance debugging.

### Phase 2, optional comparative retrieval views

Add optional benchmark modes that compare:
- transcript-grounded Core Memory retrieval
- LoCoMo observation database retrieval
- LoCoMo session-summary retrieval
- hybrid modes

But keep those clearly labeled as benchmark retrieval modes, not canonical memory authority.

### Phase 3, optional event-summary or observation synthesis evaluation

Only later, if useful:
- compare Core Memory-generated summaries/associations against `event_summary`
- compare derived retrieval notes to LoCoMo observations

This should not block initial QA integration.

---

## Concrete adapter seams to preserve

### Must preserve from LoCoMo

- `sample_id`
- session ordering
- `session_<n>_date_time`
- turn-level `dia_id`
- QA `question`
- QA `answer`
- QA `category`
- QA `evidence`
- session-summary id scheme `S<n>` if reproducing summary-retrieval baselines

### Must preserve from Core Memory

- canonical session-start boundary
- canonical turn-finalized boundary
- canonical continuity authority order
- canonical retrieval tool facades
- canonical inspect/hydration APIs
- canonical async/flush boundaries
- crawler-callable semantic extension seam

---

## What not to do

1. Do not ingest LoCoMo by directly fabricating final bead/index state as the primary path.
2. Do not treat LoCoMo generated observations or session summaries as transcript authority.
3. Do not lose `dia_id` provenance during ingestion.
4. Do not rewrite LoCoMo scoring semantics when first benchmarking Core Memory.
5. Do not bind the first integration to upstream generative-agent code unless we are explicitly regenerating datasets.

---

## Practical next steps

1. Add a benchmark research subsection to the main adapter rebuild plan tying LoCoMo transcript ingestion to canonical Core Memory boundaries.
2. Design a LoCoMo replay adapter that converts:
   - sample conversation sessions
   - dialog ids
   - timestamps
   into canonical session/turn ingestion calls.
3. Design a QA answer adapter that plugs into the `evaluate_qa.py` style loop while using Core Memory as the recall engine.
4. Preserve output context ids in a LoCoMo-compatible format so existing recall/evidence scoring still works.
5. Add benchmark mode definitions explicitly:
   - transcript_only
   - observation_view
   - session_summary_view
   - hybrid

---

## Bottom line

LoCoMo is transcript-first.

Its real benchmark authority is:
- multi-session transcript data in `conversation`
- QA annotations in `qa`

Its observation and session-summary layers are generated retrieval views, not the source of truth.

That aligns well with the adapter-only Core Memory rebuild, because the right integration is:
- ingest LoCoMo transcript through canonical Core Memory boundaries
- preserve dialog-id provenance
- answer LoCoMo QA through Core Memory-backed retrieval/agent paths
- keep LoCoMo scoring unchanged
- optionally compare against observation/summary retrieval modes later
