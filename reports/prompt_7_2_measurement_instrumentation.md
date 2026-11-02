# Prompt 7.2 — Measurement Instrumentation

- **Status:** `instrumentation_implemented; live_inference_not_run`
- **Report generated (UTC):** 2026-11-02T07:00:31.830897+00:00
- **Live Ollama inference:** not run.

## Preflight configuration

- Persistent models enabled: `False`.
- `max_parallel_models`: `1`; context: `2048`; output budget: `384`.
- Context/output/parallelism match Prompt 6.0 configuration: `True`.
- `monitoring`: `qwen2.5:3b`
- `incident`: `llama3.2:3b`
- `code`: `qwen2.5-coder:3b`
- `cicd`: `stablelm-zephyr:3b`
- `infrastructure`: `phi3.5:3.8b`
- `security`: `granite3.1-dense:2b`

## Captured measurement fields

- `prompt_eval_count`
- `eval_count`
- `done_reason`
- `total_duration`
- `load_duration`
- `prompt_eval_duration`
- `eval_duration`
- Each attempt also records attempt number, agent/model, configured context/output limits, inference status, wall duration, and prompt character count/delta.
- Missing numeric measurements and missing `done_reason` are `null`; zero remains a measured zero.

## Context-budget calculation

- Estimated remaining budget: `configured_num_ctx - prompt_eval_count - configured_num_predict`.
- `within_budget`: required values exist, prompt tokens are below configured context, and estimated remaining budget is non-negative.
- `potential_context_pressure`: prompt tokens are below context size, but reserving the full output budget yields a negative remainder.
- `context_pressure`: Ollama-reported prompt tokens are at least the configured context size.
- `measurement_unavailable`: prompt count or a required configuration value is missing/invalid.
- **Caveat:** A negative estimate is a risk indicator only. prompt_eval_count + num_predict does not prove truncation; done_reason=length is recorded separately and is not proof of context exhaustion.

## Historical observations and audit hypotheses

- Prompt 7.1 attempts inspected: 7; attempts with `done_reason=length`: 1.
- Historical prompt-token measurements: 0/7; context status therefore `measurement_unavailable`.
- Exact verified/deterministic observation overlap: 0 across 75 verified and 45 deterministic observation records.
- Raw/derived overlap by exact source path and value: 23 of 27 resolved deterministic paths match raw-source values; 23 also share a verified source/timestamp reference. Raw-value overlap requires the deterministic source_path to resolve in graph-shaped evidence and its value to occur exactly within that source subtree. The three-section count additionally requires a verified observation with the same source path and timestamp; this is reference/value overlap, not semantic equivalence.
- Retry prompt growth: Not measured per historical attempt. New attempts record prompt character count and delta, and Ollama prompt_eval_count when returned.
- Rubric probe: `The p95 latency is 850 milliseconds.` matches the existing P95 lexical pattern: `False`.

## Evaluation score separation

- Historical automated interpretation: Prompt 6.0 61.9%; Prompt 7.1 12.7%.
- Historical grounding validator: Prompt 6.0 92.9%; Prompt 7.1 83.3%.
- Historical manual semantic audit: Prompt 6.0 21/35 (60.0%); Prompt 7.1 10/35 (28.6%); these are historical manual results, not new audit work.
- Current automated interpretation will use the existing required-observation criteria.
- Current grounding validator remains separately calculated with the existing graph validator.
- Manual semantic audit: **not performed**; score is `null`.

## Repetitions and negative control

- Minimum/default repetitions: 3; sequential execution.
- Per-agent timing and numeric scores include mean/minimum/maximum and sample standard deviation when at least two values exist; failures and excluded measurements remain explicit.
- Negative control `negative-control-container-health` asks about unavailable Docker health; unsupported statuses, invented names, restarts, and CPU values are flagged.

## Validation

- `python -m py_compile agents/llm_runtime.py tests/live_agent_evaluation.py tests/test_llm_runtime.py tests/test_live_agent_evaluation.py` — compiled successfully
- `python -m pytest -q tests/test_llm_runtime.py tests/test_live_agent_evaluation.py` — 49 passed, 0 failed, 0 skipped
- `python -m pytest -q` — 151 passed, 0 failed, 0 skipped
- `python -m pytest -q tests/test_live_agent_evaluation.py` — 28 passed, 0 failed, 0 skipped

## Changed files

- `agents/llm_runtime.py`
- `tests/live_agent_evaluation.py`
- `tests/test_llm_runtime.py`
- `tests/test_live_agent_evaluation.py`
- `reports/prompt_7_2_measurement_instrumentation.md`
- `reports/prompt_7_2_measurement_instrumentation.json`
- `reports/prompt_7_2_controlled_evaluation_plan.md`

## Limitations

- No live Ollama inference was run; current context pressure is not measured.
- The historical Prompt 7.1 attempts lack token counts, so the historical truncation cause cannot be assigned to context exhaustion.
- The rubric diagnostic is one explicitly known unit-equivalent example, not a general semantic evaluation.
- Manual semantic audit remains unperformed and has no score.
- Exact source-path/value overlap does not quantify semantic equivalence or facts whose source paths cannot be resolved.
