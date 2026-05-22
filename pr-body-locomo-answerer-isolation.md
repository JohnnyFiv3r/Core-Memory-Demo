## Summary
- isolate LoCoMo LLM answer generation from the benchmark Core Memory root by using a no-tools/plain PydanticAI agent over the retrieved evidence block
- prevent answer generation from writing prior answer JSON back into the benchmark memory root and dirtying the semantic index between QA cases
- filter benchmark retrieval candidates to replayed LoCoMo transcript rows, excluding `claim_state` answer artifacts and non-sample rows

## Why
`bench-4449672145` showed corpus coverage was finally healthy (`semantic_entries=664`, `sample_scoped_turn_ids_visible=629`), but QA still degraded after the first case:
- 9/10 inspected cases had `semantic_index_stale`
- several cases retrieved a prior answer JSON from `claim_state` as evidence
- raw retrieval was empty in some cases even though the corpus was present

The LLM answerer was running through `run_agent_for_root(..., root=<benchmark_root>)`, which writes the answer turn into the same benchmark memory root. That contaminates the retrieval corpus and marks semantic dirty between QA cases.

## Verification
- `python3 -m py_compile backend/app/benchmarks/locomo_answer.py backend/app/benchmarks/locomo_runner.py`
- `cd backend && .venv/bin/python -m unittest tests.test_locomo_answer tests.test_locomo_answer_grounding tests.test_locomo_runner_retrieval`
- `cd backend && .venv/bin/python -m unittest tests.test_locomo_benchmark_fidelity tests.test_locomo_replay tests.test_locomo_turn_crawler`
