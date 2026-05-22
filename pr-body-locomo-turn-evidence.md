## Summary
- persist one promoted/retrievable LoCoMo evidence bead per replayed transcript turn, carrying only observed transcript text plus native `source_turn_ids`
- remove the stale exact `session_id: locomo:<sample>` retrieval facet so session-indexed LoCoMo beads are not hidden
- tighten benchmark corpus validation to reject session-head-only corpora like `32` semantic entries for `663` ingested turns

## Why
The latest `bench-b836ea775e` artifacts showed the previous fix was only partial: `semantic_build.entries` rose to `32`, but retrieved evidence was still mostly first turns (`D*:1`) from each LoCoMo session. Gold evidence often points to later turns such as `D13:16`, so this run shape should not pass validation or publish scores.

## Verification
- `python3 -m py_compile backend/app/core/runtime.py backend/app/benchmarks/locomo_runner.py`
- `cd backend && .venv/bin/python -m unittest tests.test_locomo_benchmark_fidelity tests.test_locomo_runner_retrieval`
- `cd backend && .venv/bin/python -m unittest tests.test_locomo_replay tests.test_locomo_turn_crawler`
