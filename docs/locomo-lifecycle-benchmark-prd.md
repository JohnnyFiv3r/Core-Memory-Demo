# LoCoMo Faithful Lifecycle Benchmark Plan

Status: implemented with validation notes; authoritative lifecycle path is available as `locomo_native_lifecycle`  
Scope: Core Memory Demo benchmark harness; LoCoMo first, LongMemEval and other long-context memory benchmarks later  
Audience: benchmark, backend, runtime, and demo implementation agents

## Implementation Status

Current implementation status:

- **Phase 0 — Documentation and fencing:** implemented. `fixture_smoke` remains non-authoritative; `locomo_native_lifecycle` reports lifecycle fidelity and shortcut guards.
- **Phase 1 — Normalized contracts:** implemented via benchmark-agnostic conversation/turn/QA dataclasses.
- **Phase 2 — LoCoMo native adapter:** implemented. Turn and QA IDs are sample-scoped, including bare QA IDs such as `q0001`.
- **Phase 3 — Lifecycle replay runner:** implemented. Source turns replay through `process_turn_finalized`; capture calls and replay counts are reported.
- **Phase 4 — Pre-QA flush:** implemented. `process_flush` runs after replay and before QA; pre-QA corpus snapshots are reported.
- **Phase 5 — Multi-effort QA:** implemented. Every QA runs `low`, `medium`, and `high` in order and reports/scored efforts independently.
- **Phase 6 — QA bead lifecycle:** implemented. Shared QA mode and isolated QA mode are both available; reports identify `qa_session_mode`.
- **Phase 7 — UI and artifact compatibility:** implemented for report/artifact visibility and live progress; fixture reports remain compatible.

Validation notes from a real native LoCoMo smoke run (`sample_limit=1`, `qa_limit=2`):

- Shared mode completed and proved lifecycle invariants, but QA bead writes dirtied the shared root between QA cases and produced `semantic_index_stale` warnings on later QA retrieval. Retrieval rows were not contaminated by `claim_state` or previous answer JSON.
- Isolated mode completed with the same lifecycle invariants and **no `semantic_index_stale` warnings**. For clean benchmark evaluation, prefer `qa_session_mode=isolated`; shared mode remains useful when intentionally measuring continuous QA-session effects.
- The small local environment used degraded/hash semantic mode, so retrieval quality was not meaningful (`semantic_backend_unavailable_degraded` warnings and zero retrieved rows). Use a real semantic backend for score-bearing runs.

## Operator Instructions

Recommended clean lifecycle run:

```bash
python - <<'PY'
from app.core.runtime import run_benchmark

out = run_benchmark(
    semantic_mode_name="required",          # or degraded_allowed for plumbing-only smoke
    root_mode="clean",
    preload_from_demo=False,
    preload_turns_max=0,
    suite="locomo_native_lifecycle",
    sample_limit=1,                         # raise for real runs
    qa_limit=2,                             # raise for real runs
    retrieval_k=8,
    qa_session_mode="isolated",            # recommended for clean eval
    embeddings_provider="openai",          # use configured production provider
)
print(out["summary"])
print(out["report"].get("artifact_download_url"))
PY
```

Checklist for accepting a lifecycle run artifact:

- `report.lifecycle.lifecycle_faithful == true`
- `report.lifecycle.turns_replayed == report.lifecycle.capture_hook_calls`
- `report.lifecycle.pre_qa_flush_ran == true`
- `report.lifecycle.retrieval_efforts_per_qa == ["low", "medium", "high"]`
- all `report.shortcut_guards` values are `false`
- `report.corpus_after_replay`, `report.corpus_after_pre_qa_flush`, `report.corpus_after_qa`, and `report.corpus_after_suite` are present
- case `retrieval_order` is exactly `["low", "medium", "high"]`
- retrieved evidence rows, if any, are transcript evidence rows, not `claim_state` or previous QA-answer artifacts
- no `semantic_index_stale` warnings for clean isolated runs

## Executive Summary

The benchmark harness must adapt external benchmark datasets to the real Core Memory lifecycle instead of bypassing it with benchmark-specific shortcuts. LoCoMo should be replayed as an ordered conversation: each source turn is ingested through the same capture hooks that production agents use, associations are built live as the session evolves, a pre-QA session flush/compact boundary prepares rolling-window context for the QA answering session, and every QA question runs all retrieval effort levels in order: `low`, then `medium`, then `high`.

The existing LoCoMo-specific work remains useful, but it must be fenced as fixture/demo/smoke infrastructure. The new lifecycle-faithful path must not depend on synthetic crawler updates, bead-direct dataset shortcuts, oracle answer copying, or benchmark-aware retrieval behavior.

## Goals

1. Faithfully exercise Core Memory lifecycle hooks:
   - capture/write path
   - association crawler and association graph building
   - session end / compact / flush boundary
   - retrieval with `low`, `medium`, and `high` effort for every QA step
2. Convert LoCoMo native data into ordered turns and QA cases without losing sample/session identity.
3. Build association graphs live during replay instead of pre-materializing benchmark-only graph state.
4. Ensure pre-QA flush/compaction happens after turn replay and before QA so the QA session starts with rolling-window context from ingested turns.
5. Ensure QA retrieval can access the full relevant bead corpus, not only rolling-window beads.
6. Preserve existing LoCoMo fixture/demo work as clearly labeled non-authoritative smoke coverage.
7. Produce reports that prove lifecycle fidelity and expose old shortcut leakage.

## Non-Goals

- Do not delete existing fixture smoke tests or demo UI plumbing.
- Do not tune LoCoMo scores with benchmark-specific answer prompts or gold-answer copying.
- Do not preserve legacy demo shortcuts in the faithful benchmark path for compatibility if they conflict with lifecycle truth.
- Do not make LoCoMo assumptions part of the generic benchmark runner contract.

## Current Risk in Existing Flow

Existing LoCoMo-related work can undermine the new effort if it leaks into faithful mode. Known risk areas:

- Synthetic fixture setup can create beads directly instead of exercising capture.
- Heuristic `crawler_updates` can seed graph data instead of letting the live association path do the work.
- Manual temporal edges such as synthetic `follows` can make graph coverage look better than runtime behavior.
- Bead-direct ingest paths can bypass session lifecycle semantics.
- QA may be case-oriented instead of conversation-oriented, causing the same conversation to be replayed repeatedly or incompletely.
- Retrieval currently may run only `high` effort, hiding effort-level regressions.
- Small fixture `k` values can accidentally constrain benchmark recall.
- LoCoMo IDs such as `dia_id` can repeat across samples; all keys must be sample-scoped.

## Benchmark Modes

The harness must expose distinct modes with explicit report metadata.

### `fixture_smoke`

Purpose: fast deterministic CI/demo plumbing validation.

Allowed:

- synthetic fixtures
- direct bead setup
- seeded crawler updates
- manual adjacency edges
- small local gold packs

Required metadata:

```json
{
  "dataset_mode": "fixture_smoke",
  "lifecycle_faithful": false,
  "synthetic_crawler_updates": true,
  "synthetic_temporal_edges": true,
  "bead_direct_ingest": true
}
```

### `locomo_native_lifecycle`

Purpose: authoritative LoCoMo benchmark path.

Allowed:

- native LoCoMo dataset adaptation
- per-turn replay through `process_turn_finalized`
- normal runtime/crawler/association behavior
- pre-QA `process_flush`
- full-corpus recall
- low/medium/high effort retrieval per QA

Forbidden unless an explicit debug flag is set and reflected in report metadata:

- synthetic crawler updates
- manual synthetic graph edges
- direct bead materialization for LoCoMo conversation content
- oracle/gold answer injection
- benchmark-aware retrieval prompts or answer rewriting

Required metadata:

```json
{
  "dataset_mode": "locomo_native_lifecycle",
  "lifecycle_faithful": true,
  "synthetic_crawler_updates": false,
  "synthetic_temporal_edges": false,
  "bead_direct_ingest": false,
  "oracle_gold_used": false,
  "retrieval_effort_order": ["low", "medium", "high"]
}
```

## Normalized Benchmark Contract

Create a benchmark-agnostic intermediate representation so LoCoMo is one adapter, not the runner design.

```python
@dataclass(frozen=True)
class BenchmarkConversation:
    benchmark_name: str
    conversation_id: str
    session_id: str
    turns: list[BenchmarkTurn]
    qa_cases: list[BenchmarkQA]
    metadata: dict[str, Any]

@dataclass(frozen=True)
class BenchmarkTurn:
    turn_id: str
    speaker: str
    role: str
    content: str
    timestamp: str | None
    metadata: dict[str, Any]

@dataclass(frozen=True)
class BenchmarkQA:
    qa_id: str
    question: str
    expected_answer: str | None
    gold_evidence: list[str]
    category: str | None
    bucket_labels: tuple[str, ...]
    metadata: dict[str, Any]
```

Adapter requirements:

- Preserve source sample/conversation identity.
- Preserve source turn order.
- Preserve speaker names/roles.
- Preserve QA category/bucket metadata.
- Generate stable IDs that cannot collide across samples.

For LoCoMo, IDs should be scoped like:

```text
conversation_id = "locomo:{sample_id}"
turn_id = "locomo:{sample_id}:{dia_id}:{turn_index}"
qa_id = "locomo:{sample_id}:{qa_id}"
session_id = "bench:locomo:{sample_id}:replay"
```

Never key only by `dia_id`; LoCoMo dialogue IDs can repeat across samples.

## Lifecycle Architecture

### Phase 1: Dataset Adaptation

Input: LoCoMo native data files.  
Output: `list[BenchmarkConversation]`.

Validation:

- Every conversation has at least one turn.
- Every QA case belongs to exactly one conversation.
- Turn IDs are globally unique within a run.
- QA IDs are globally unique within a run.
- Adapter reports skipped/invalid rows with reasons.

### Phase 2: Conversation Replay / Capture

For each conversation, replay each source turn through Core Memory's capture boundary.

Expected call shape:

```python
process_turn_finalized(
    root=benchmark_root,
    session_id=conversation.session_id,
    turn_id=turn.turn_id,
    transaction_id=f"tx:{turn.turn_id}",
    trace_id=f"trace:{turn.turn_id}",
    turns=[
        {
            "speaker": turn.speaker,
            "role": turn.role,
            "content": turn.content,
        }
    ],
    metadata={
        "benchmark_name": conversation.benchmark_name,
        "benchmark_phase": "conversation_replay",
        "conversation_id": conversation.conversation_id,
        "source_turn_id": turn.turn_id,
        **turn.metadata,
    },
    origin="BENCHMARK_REPLAY",
)
```

Implementation notes:

- Use the normal capture/write path.
- Do not pre-create LoCoMo content beads in faithful mode.
- Do not inject heuristic crawler updates in faithful mode.
- Allow normal runtime association/crawler behavior to create graph edges.
- Drain bounded side effects only in ways that production lifecycle supports.

### Phase 3: Live Association Graph Building

Association graph construction should happen as a consequence of replayed turns.

The runner should record after replay:

- bead count
- association count
- non-temporal semantic association count
- entity count
- claim count
- warnings/errors emitted by lifecycle hooks
- semantic backend status

Do not count synthetic fixture edges as lifecycle graph coverage.

### Phase 4: Pre-QA Flush / Compaction Boundary

After all conversation turns are replayed and before any QA case runs, fire the session flush boundary.

Expected call shape:

```python
process_flush(
    root=benchmark_root,
    session_id=conversation.session_id,
    promote=True,
    token_budget=pre_qa_token_budget,
    max_beads=pre_qa_max_beads,
    source="benchmark_pre_qa",
    flush_tx_id=f"bench-preqa:{conversation.conversation_id}",
)
```

Then drain async work if configured:

```python
run_async_jobs(
    root=benchmark_root,
    run_semantic=True,
    max_compaction=max_compaction,
    max_side_effects=max_side_effects,
)
```

Clarification:

- This phase exists so the QA-answering session has rolling-window/context-injection material from the ingested turns.
- It is not a retrieval scope limiter.
- Retrieval during QA must still access the full relevant bead corpus.

Report pre-QA context:

```json
{
  "pre_qa_flush": {
    "ran": true,
    "flush_tx_id": "bench-preqa:...",
    "source": "benchmark_pre_qa",
    "token_budget": 1200,
    "max_beads": 12,
    "result_ok": true
  }
}
```

### Phase 5: QA Session Setup

The QA pass should run after pre-QA flush in a QA-answering session.

Supported modes:

#### Shared QA Session (default initially)

All QA cases for a conversation run in one QA session.

Pros:

- Mirrors an agent answering a sequence of questions.
- Allows QA beads from earlier questions to become context for later questions.

Cons:

- Later QA can be affected by earlier QA content.

ID:

```text
qa_session_id = "bench:locomo:{sample_id}:qa"
```

#### Isolated QA Case Session

Each QA case runs with a cloned pre-QA root or isolated QA session.

Pros:

- Cleaner per-question measurement.
- Prevents cross-QA contamination.

Cons:

- More expensive.
- Less like a continuous agent QA session.

CLI/API:

```text
--qa-session-mode shared|isolated
```

Implementation recommendation:

- Build shared mode first.
- Add isolated mode by copying the post-flush benchmark root per QA case for strict isolation.

### Phase 6: Retrieval Effort Execution

Every QA case must run all effort levels in order:

```python
for effort in ["low", "medium", "high"]:
    result = core_recall(
        request,
        effort=effort,
        root=benchmark_root,
        explain=True,
        include_raw=True,
    )
```

Requirements:

- Preserve execution order in telemetry.
- Store each effort result independently.
- Score each effort independently.
- Report effort deltas and monotonicity diagnostics where useful.
- Do not short-circuit `medium` or `high` just because `low` succeeds.

Recall request requirements:

- Include question text.
- Include intent/category if available.
- Include benchmark metadata for traceability.
- Do not pass rolling-window bead IDs as a hard search filter.
- Use full-corpus retrieval unless a named debug mode says otherwise.

Recommended default request shape:

```python
request = {
    "raw_query": qa.question,
    "intent": qa.metadata.get("intent", "remember"),
    "constraints": {
        "benchmark_name": conversation.benchmark_name,
        "conversation_id": conversation.conversation_id,
        "qa_id": qa.qa_id,
        "recall_scope": "full_bead_corpus",
    },
    "k": benchmark_retrieval_k,
}
```

`benchmark_retrieval_k` should not inherit tiny fixture defaults. Use Core Memory effort defaults or a generous benchmark default.

### Phase 7: QA Bead Writing

The QA phase may write beads too, because a real agent answering questions creates context.

Recommended behavior:

1. Run `low`, `medium`, and `high` retrieval.
2. Generate or select the benchmark answer for the QA case.
3. Write one QA turn through `process_turn_finalized`, not one per effort.

Expected call shape:

```python
process_turn_finalized(
    root=benchmark_root,
    session_id=qa_session_id,
    turn_id=f"qa:{qa.qa_id}",
    transaction_id=f"tx:qa:{qa.qa_id}",
    trace_id=f"trace:qa:{qa.qa_id}",
    turns=[
        {"role": "user", "speaker": "benchmark_user", "content": qa.question},
        {"role": "assistant", "speaker": "benchmark_agent", "content": final_answer},
    ],
    metadata={
        "benchmark_name": conversation.benchmark_name,
        "benchmark_phase": "qa",
        "conversation_id": conversation.conversation_id,
        "qa_id": qa.qa_id,
        "retrieval_efforts": ["low", "medium", "high"],
        "selected_answer_effort": "high",
    },
    origin="BENCHMARK_QA",
)
```

If shared QA mode hurts performance, run isolated mode and compare. Do not silently change the default without report metadata.

## Reporting Requirements

Top-level lifecycle metadata:

```json
{
  "lifecycle": {
    "dataset_mode": "locomo_native_lifecycle",
    "lifecycle_faithful": true,
    "conversations": 10,
    "turns_replayed": 5882,
    "capture_hook_calls": 5882,
    "pre_qa_flush_ran": true,
    "qa_session_mode": "shared",
    "qa_cases": 50,
    "retrieval_efforts_per_qa": ["low", "medium", "high"]
  }
}
```

Shortcut guard metadata:

```json
{
  "shortcut_guards": {
    "synthetic_crawler_updates": false,
    "synthetic_temporal_edges": false,
    "bead_direct_ingest": false,
    "oracle_gold_used": false,
    "benchmark_aware_answer_prompt": false
  }
}
```

Corpus snapshots:

```json
{
  "corpus_after_replay": {
    "beads": 0,
    "associations": 0,
    "semantic_associations": 0,
    "entities": 0,
    "claims": 0
  },
  "corpus_after_pre_qa_flush": {
    "beads": 0,
    "associations": 0,
    "semantic_associations": 0,
    "entities": 0,
    "claims": 0
  },
  "corpus_after_qa": {
    "beads": 0,
    "associations": 0,
    "semantic_associations": 0,
    "entities": 0,
    "claims": 0
  }
}
```

Per-QA result shape:

```json
{
  "qa_id": "locomo:sample:q0001",
  "conversation_id": "locomo:sample",
  "question": "...",
  "expected_answer": "...",
  "bucket_labels": ["..."],
  "efforts": {
    "low": {
      "answer": "...",
      "score": {},
      "latency_ms": 0,
      "evidence_bead_ids": [],
      "grounding_hashes": [],
      "warnings": []
    },
    "medium": {},
    "high": {}
  },
  "qa_bead_written": true,
  "qa_session_id": "bench:locomo:sample:qa"
}
```

Rollups:

```json
{
  "accuracy_by_effort": {
    "low": 0.0,
    "medium": 0.0,
    "high": 0.0
  },
  "evidence_recall_by_effort": {
    "low": 0.0,
    "medium": 0.0,
    "high": 0.0
  },
  "latency_by_effort_ms": {
    "low": {"p50": 0, "p95": 0},
    "medium": {"p50": 0, "p95": 0},
    "high": {"p50": 0, "p95": 0}
  }
}
```

## Guardrails Against Existing LoCoMo Shortcut Leakage

Implement hard checks in `locomo_native_lifecycle` mode:

1. Fail if direct bead materialization is used for source conversation turns.
2. Fail if synthetic `crawler_updates` are injected by the benchmark adapter.
3. Fail if synthetic temporal edges are added outside normal runtime association behavior.
4. Fail if any report field indicates oracle/gold answer use during answer generation.
5. Fail if only one retrieval effort ran for a QA case.
6. Fail if retrieval effort order is not exactly `low`, `medium`, `high`.
7. Fail if turn IDs are not sample-scoped.
8. Warn if no associations are produced after replay, but do not patch the result with synthetic edges.
9. Warn if no claims/entities are produced, but do not patch the result with synthetic data.
10. Report every debug override explicitly.

Recommended internal flag object:

```python
@dataclass
class BenchmarkShortcutFlags:
    synthetic_crawler_updates: bool = False
    synthetic_temporal_edges: bool = False
    bead_direct_ingest: bool = False
    oracle_gold_used: bool = False
    benchmark_aware_answer_prompt: bool = False
```

In faithful mode:

```python
if dataset_mode == "locomo_native_lifecycle" and any(shortcut_flags):
    raise BenchmarkLifecycleError("faithful mode forbids benchmark shortcuts")
```

## CLI / API Proposal

CLI:

```bash
python -m app.benchmarks.locomo_runner \
  --dataset-mode locomo_native_lifecycle \
  --locomo-path /path/to/locomo.json \
  --qa-session-mode shared \
  --pre-qa-flush on \
  --retrieval-efforts low,medium,high \
  --recall-scope full_bead_corpus \
  --out /path/to/report.json
```

Debug/compatibility:

```bash
python -m app.benchmarks.locomo_runner --dataset-mode fixture_smoke
```

Required defaults:

- `--dataset-mode fixture_smoke` for current fast CI if needed.
- `--retrieval-efforts low,medium,high` in lifecycle mode.
- `--pre-qa-flush on` in lifecycle mode.
- `--recall-scope full_bead_corpus` in lifecycle mode.

## Testing Plan

### Unit Tests

1. LoCoMo adapter emits conversations, ordered turns, and QA cases.
2. Adapter IDs are sample-scoped and collision-free.
3. Fixture smoke mode still validates existing fixtures.
4. Faithful mode rejects synthetic crawler updates.
5. Faithful mode rejects bead-direct source turn materialization.
6. Effort runner invokes recall in `low`, `medium`, `high` order.
7. Report includes all three effort results per QA case.
8. Pre-QA flush runs after replay and before QA.
9. Shared QA mode writes QA beads into one QA session.
10. Isolated QA mode prevents cross-QA contamination.

### Integration Tests

1. Minimal LoCoMo-native sample replays multiple turns and produces beads through capture.
2. Pre-QA flush creates a flush checkpoint/report.
3. QA recall can retrieve evidence from the full bead corpus.
4. Report shortcut flags are false in lifecycle mode.
5. Existing fixture smoke report shape remains compatible with UI expectations.

### Regression Tests from Prior LoCoMo Work

- Repeated `dia_id` values across samples must not cause skipped turns.
- Gold-answer copying/oracle paths must remain absent from lifecycle mode.
- Noncanonical relationship labels from old deterministic crawler experiments must not be emitted by faithful mode.
- `fixture_smoke` remains distinct from native LoCoMo suite metadata.

## Implementation Phases

### Phase 0: Documentation and Fencing

- Add this PRD to demo repos.
- Add a short mode matrix to existing benchmark docs.
- Identify all existing LoCoMo shortcut paths and label them fixture/demo only.

Acceptance:

- Developers can tell which code path is authoritative.
- Reports expose dataset mode and shortcut flags.

### Phase 1: Normalized Contracts

- Add benchmark conversation/turn/QA dataclasses.
- Add adapter interface.
- Add report lifecycle metadata schema.

Acceptance:

- Fixture smoke can be represented in the normalized contract.
- LoCoMo adapter tests can run without Core Memory side effects.

### Phase 2: LoCoMo Native Adapter

- Parse native LoCoMo data into normalized conversations.
- Preserve sample/session IDs.
- Preserve turn order and QA metadata.
- Enforce sample-scoped IDs.

Acceptance:

- Native sample fixture produces expected turn/QA counts.
- No ID collisions across samples.

### Phase 3: Lifecycle Replay Runner

- Replay each turn through `process_turn_finalized`.
- Collect lifecycle call counts and corpus snapshots.
- Remove synthetic graph/crawler seeding from lifecycle mode.

Acceptance:

- Capture hook calls equal replayed turns.
- Beads are created through runtime hooks.
- Faithful mode fails if shortcut flags are set.

### Phase 4: Pre-QA Flush

- Add explicit `process_flush` call after replay.
- Drain async jobs according to configured profile.
- Capture pre-QA context metadata.

Acceptance:

- Flush happens before first QA recall.
- Report contains flush result and checkpoint metadata.

### Phase 5: Multi-Effort QA

- Run `low`, `medium`, and `high` recall per QA.
- Store and score each effort independently.
- Add full-corpus retrieval scope guard.

Acceptance:

- Every QA case has all three effort payloads.
- Report rollups by effort are populated.
- No QA case is scored from only high effort.

### Phase 6: QA Bead Lifecycle

- Write one QA turn bead per QA case after retrieval/answer generation.
- Support shared QA session mode.
- Add isolated mode if shared QA context hurts or for cleaner evals.

Acceptance:

- Shared mode accumulates QA beads.
- Isolated mode can run without cross-QA contamination.
- Report identifies selected mode.

### Phase 7: UI and Artifact Compatibility

- Keep existing UI report readers working for fixture smoke.
- Add lifecycle report fields to UI artifacts where useful.
- Ensure old demo benchmark artifacts do not masquerade as lifecycle-faithful runs.

Acceptance:

- Existing demo benchmark tab does not regress.
- New lifecycle reports are visible and clearly labeled.

## Open Questions

1. Should answer generation use high effort only, or should each effort produce its own generated answer for effort-specific scoring?
   - Recommendation: score each effort independently; use high effort as the final QA bead answer initially.
2. Should isolated QA mode clone the entire post-flush root or use separate QA session IDs over the same bead corpus?
   - Recommendation: clone root for strict isolation; separate session IDs are cheaper but less strict.
3. What default `k` should lifecycle LoCoMo use?
   - Recommendation: do not inherit fixture `k`; use Core Memory effort defaults or a generous benchmark default.
4. Should no-association/no-claim outcomes fail lifecycle mode?
   - Recommendation: warn and report, but do not synthesize missing data. The benchmark should expose the runtime gap.

## Definition of Done

The new benchmark path is done when:

- Native LoCoMo data is adapted into conversations and QA cases.
- Every source turn is replayed through `process_turn_finalized`.
- Associations/claims/entities arise from runtime lifecycle behavior, not fixture shortcuts.
- `process_flush` runs after replay and before QA.
- Every QA runs `low`, `medium`, and `high` retrieval in order.
- QA retrieval is full-corpus by default.
- QA beads can be written in shared mode, with isolated mode available or planned behind a flag.
- Reports include lifecycle proof, corpus snapshots, effort-specific scores, and shortcut guard flags.
- Existing LoCoMo fixture/demo paths remain available but cannot be mistaken for authoritative lifecycle benchmark results.
