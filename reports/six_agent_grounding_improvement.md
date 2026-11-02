# Six-Agent Evidence Grounding Evaluation

- **Run time (UTC):** 2026-11-01T21:52:03.898114+00:00
- **Ollama endpoint:** `http://127.0.0.1:11434`
- **Models installed:** granite3.1-dense:2b, phi3.5:3.8b, stablelm-zephyr:3b, qwen2.5-coder:3b, llama3.2:3b, qwen2.5:3b
- **Sequential inference:** overlap detected: `False`
- **Total model inference:** 43.14 seconds
- **Offline suite:** `python -m pytest -q` — 114 passed, 0 failed, 0 skipped
- **Operational actions:** none; only synthetic fixtures were sent to Ollama.

## Root-cause analysis

- The previous live harness hand-translated synthetic fixtures into graph state and inserted generic unavailable-source placeholders. This did not match the production evidence contract and let unrelated missing-source text distract from supplied observations.
- The shared prompt requested citations but did not require a fixed observations-first pass or say that an unavailable source must not override another source's valid measurements.
- Graph evidence shaping sent broad bundles to multiple specialists; code evaluation bypassed graph shaping, while the other routes received irrelevant health, deployment, logs, or source-availability fields.
- The prior harness did not evaluate its stated acceptance criteria and assigned PARTIAL to every successful response. Its status labels were therefore not a content-quality comparison.
- The claim validator accepted security terms found in any evidence string, including negative telemetry details, and did not verify recommendation premises. Its numeric aliases also missed several observed units and Prometheus query-value paths.
- The monitoring fixture initially placed Prometheus rates in application counter fields, creating a false cumulative-total observation; the corrected fixture now keeps those independent sources separate.
- The offline pytest summary parser previously matched an all-optional empty pattern, reporting zero tests despite a passing suite; it now extracts actual passed/failed/skipped counts and rejects missing summaries.
- Validation also needed to recognize underscore-separated Prometheus names, scientific notation, percentile labels, punctuated IPv4 addresses, and container IDs without confusing them for container names.

## Changes made

- `agents/graph.py` — Scope specialist evidence by role, route CI/CD pipeline availability, add source-path observations, and validate Prometheus metrics, availability claims, container IDs, and recommendations against original source evidence.
- `agents/llm_runtime.py` — Use an observations-first reasoning contract that directs specialists to retain exact source paths and timestamps without changing the JSON schema, model mappings, limits, retries, or sequential lock.
- `tests/live_agent_evaluation.py` — Use production-shaped independent telemetry fixtures, preserve source/shaped evidence and sanitized prompts, record prompt sizes, grade explicit criteria, and parse pytest summaries strictly.
- `tests/test_graph.py` — Add regressions for role-scoped evidence, source-path observation indexing, and unsupported source-availability/security claims and recommendation premises.
- `tests/test_llm_runtime.py` — Test the shared evidence-first prompt, deterministic observation-index guidance, and independent source handling.
- `tests/test_telemetry.py` — Update Security evidence-routing expectations to include the deterministic observation index.
- `tests/test_live_agent_evaluation.py` — Test scenario grading and credential-safe diagnostics/report generation offline.
- `reports/six_agent_grounding_improvement.md and .json` — Record the before/after synthetic evaluation, exact sanitized prompts, evidence payloads, and validation details.

## Six-agent evaluation

| Specialist | Model | Inference | Schema | Evidence criteria | Material unsupported claims | Latency (s) | Retries | Result |
|---|---|---|---|---:|---:|---:|---:|---|
| monitoring | qwen2.5:3b | ok | valid | 6/6 | 1 | 9.66 | 0 | PARTIAL |
| incident | llama3.2:3b | ok | valid | 0/7 | 0 | 5.46 | 0 | PARTIAL |
| code | qwen2.5-coder:3b | ok | valid | 3/3 | 0 | 6.33 | 0 | PASS |
| cicd | stablelm-zephyr:3b | ok | valid | 0/5 | 2 | 6.94 | 0 | PARTIAL |
| infrastructure | phi3.5:3.8b | ok | valid | 5/7 | 0 | 7.49 | 0 | PARTIAL |
| security | granite3.1-dense:2b | ok | valid | 7/7 | 1 | 7.31 | 0 | PARTIAL |

## Before versus after

- **Prior run:** 2026-11-01T21:11:29.548160+00:00; 6 inference successes, 6 schema-valid responses.
- **Prior rubric note:** The original run had six schema-valid responses and no overlap, but the harness labeled every response PARTIAL without checking acceptance criteria. These values come from the original report and are not a content-quality score.

| Specialist | Prior model | Prior result | Prior latency (s) | Current model | Current result | Current latency (s) |
|---|---|---|---:|---|---|---:|
| monitoring | qwen2.5:3b | PARTIAL | 6.16 | qwen2.5:3b | PARTIAL | 9.66 |
| incident | llama3.2:3b | PARTIAL | 6.55 | llama3.2:3b | PARTIAL | 5.46 |
| code | qwen2.5-coder:3b | PARTIAL | 6.51 | qwen2.5-coder:3b | PASS | 6.33 |
| cicd | stablelm-zephyr:3b | PARTIAL | 4.60 | stablelm-zephyr:3b | PARTIAL | 6.94 |
| infrastructure | phi3.5:3.8b | PARTIAL | 8.17 | phi3.5:3.8b | PARTIAL | 7.49 |
| security | granite3.1-dense:2b | PARTIAL | 8.50 | granite3.1-dense:2b | PARTIAL | 7.31 |
- **Current run:** 6 inference successes, 6 schema-valid responses; 1 PASS, 5 PARTIAL, 0 FAIL, 0 SKIPPED.

The prior run's synthetic evidence had been manually translated into graph state, included unrelated unavailable-source placeholders, and the harness did not grade its stated acceptance criteria. Baseline labels therefore cannot be used as evidence of improvement. The current report records both the original synthetic fixture and the final shaped evidence/prompt for each model so evidence-flow differences are inspectable.

## Limitations

- Offline tests use mocks and do not establish live model behavior.
- Live calls evaluate synthetic fixtures only, not a real incident or production telemetry.
- Anchor checks are explicit regression checks, not a general natural-language reasoning benchmark.
- The existing finding validator is conservative and does not prove semantic truth.
- LLM recommendations remain advisory; no deployment, rollback, or remediation ran.

## Configuration and safety

- Persistent `config/models.json` SHA-256 unchanged: `True`.
- Persistent LLM configuration enabled: `False`.
- Runtime `max_parallel_models`: `1`.
- `keep_alive`: `0s`.
- Ollama had models loaded after the run: `0`.
- No model mappings or persistent enablement settings were changed.

Per-agent original evidence, shaped evidence, exact sanitized prompts, model outputs, claim validation, and truncation/size measurements are in the companion JSON report.
