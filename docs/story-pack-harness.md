# Story Pack Harness (Demo)

The expanded demo script pack is embedded at:

- `demo/story-pack/`
- manifest: `demo/story-pack/replay-order.json`

## API

### Inspect pack metadata

`GET /api/story-pack/meta`

Returns pack name, act ranges, total turns, checkpoint count, and session hints.

### Replay the pack

`POST /api/story-pack/replay`

Example:

```json
{
  "max_turns": 204,
  "run_checkpoints": true,
  "reset_session": true,
  "use_manifest_sessions": true,
  "wait_for_idle": true,
  "benchmark_semantic_mode": "required"
}
```

Optional controls:

- `start_turn`, `end_turn`, `max_turns`
- `run_checkpoints` (default `true`)
- `reset_session` (default `true`)
- `use_manifest_sessions` (default `true`)
- `wait_for_idle`, `idle_timeout_ms`, `idle_poll_ms`
- `max_compaction_per_pass`, `max_side_effects_per_pass`
- `benchmark_semantic_mode` (`required`/`degraded_allowed`)
- `benchmark_limit`

## Checkpoint behavior

The harness executes manifest checkpoints at the configured turn boundaries:

- `session_flush` uses `run_flush(...)` and honors `next_session` when present.
- `benchmark` runs isolated benchmark mode (`snapshot` or `clean`) with `preload_from_demo=false`.

This keeps benchmark runs isolated and non-mutating for live demo memory.
