# Prompt 7.0 — Deterministic Evidence Extraction

- **Generated (UTC):** 2026-11-02T04:36:28.494951+00:00
- **Execution:** offline deterministic evaluation; no Ollama calls
- **Offline tests:** 128 passed, 0 failed, 0 skipped
- **Live Ollama inference:** not run, as requested.
- **Operational actions:** no deployment, rollback, or remediation executed.

## Previous live evaluation: observed causes of PARTIAL results

This analysis uses the latest persisted live-evaluation JSON. It records model omissions and validator findings from that run; it does not treat the old model response as verified evidence.
- **monitoring (PARTIAL):** missing response criteria: none recorded; unsupported-claim findings: 1.
- **incident (PARTIAL):** missing response criteria: Previous version, Current version, Previous error count, Current error count, Baseline latency, Current latency, Timeout log evidence; unsupported-claim findings: 0.
- **cicd (PARTIAL):** missing response criteria: Previous version, Current version, Deployment completion, Health response, Post-deployment error rate; unsupported-claim findings: 2.
- **infrastructure (PARTIAL):** missing response criteria: Healthy state, Zero restarts; unsupported-claim findings: 0.
- **security (PARTIAL):** missing response criteria: none recorded; unsupported-claim findings: 1.

## Deterministic extraction and role delivery

| Specialist | Model | Extracted required facts | Delivered required facts | Delivery complete | Prior result | Current interpretation |
|---|---|---:|---:|---|---|---|
| monitoring | qwen2.5:3b | 5/5 | 5/5 | True | PARTIAL | NOT RUN |
| incident | llama3.2:3b | 5/5 | 5/5 | True | PARTIAL | NOT RUN |
| code | qwen2.5-coder:3b | 3/3 | 3/3 | True | PASS | NOT RUN |
| cicd | stablelm-zephyr:3b | 6/6 | 6/6 | True | PARTIAL | NOT RUN |
| infrastructure | phi3.5:3.8b | 7/7 | 7/7 | True | PARTIAL | NOT RUN |
| security | granite3.1-dense:2b | 4/4 | 4/4 | True | PARTIAL | NOT RUN |

## Aggregate results

- Agents evaluated: 6
- Extraction/delivery complete: 6
- Extraction/delivery partial: 0
- Required facts extracted: 30/30 (100.0%)
- Required facts delivered: 30/30 (100.0%)
- Interpretation completeness: not measured; live inference was not run.

## Architecture and safety

- Collected evidence remains unchanged and accessible.
- A strict deterministic extractor records source-traceable observations.
- Role packaging filters observations before the specialist request.
- Specialist results preserve extracted facts independently of model output.
- RCA separates verified observations, interpretations, hypotheses, recommendations, and unverified claims.

- Persisted model enablement: `False`.
- `max_parallel_models`: `1`.
- Model mappings: `{"cicd": "stablelm-zephyr:3b", "code": "qwen2.5-coder:3b", "incident": "llama3.2:3b", "infrastructure": "phi3.5:3.8b", "monitoring": "qwen2.5:3b", "security": "granite3.1-dense:2b"}`.
- Source values, timestamps, units, and paths are preserved in JSON. Stale/unavailable/invalid values remain explicitly marked.
- Verified observations are kept separate from LLM interpretations and cannot be overwritten by specialist output.

## Limitations

- This report validates deterministic extraction and role delivery only; model interpretation completeness is not evaluated because live inference was not run.
- Derived error rates are computed only when observed successful/error counters provide a non-zero denominator.
- A suspicious authentication sequence is a deterministic sequence description, not a threat classification or proof of compromise.

The companion JSON contains per-fact extraction and delivery results, source paths, missing-source records, prior model-result diagnostics, model mapping, and safety settings.
