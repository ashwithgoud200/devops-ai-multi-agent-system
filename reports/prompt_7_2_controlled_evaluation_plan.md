# Prompt 7.2 — Controlled Evaluation Plan

This plan is a preflight only. No Ollama inference has been run.

## Preconditions

- Obtain explicit user authorization before invoking `--prompt7-2-live --confirm-live`.
- Keep `config/models.json` disabled by default; enable inference only through a temporary process override.
- Preserve `max_parallel_models=1`, `num_ctx=2048`, and `num_predict=384`.
- Verify the six configured model mappings listed in the companion measurement report; do not switch models or load concurrently.
- Confirm the local Ollama endpoint is reachable, all six models are installed, and no model is loaded before starting.

## Run protocol

1. Load the recorded Prompt 6.0 scenarios and their `environment.run_utc` reference timestamp; do not rewrite their evidence, questions, or expected findings.
2. Run 3 sequential repetitions (minimum); use the same serialized scenario inputs and scenario reference time in every repetition.
3. Run the explicitly unavailable-Docker negative control with the infrastructure specialist in each repetition.
4. Record each attempt's Ollama metrics, configuration, prompt hash, status, schema, grounding, automated interpretation, and failures without storing credentials or full prompts.
5. Aggregate timing and numeric scores per agent; report missing/failed runs separately and keep the three score types independent.
6. Leave manual semantic audit as `not_performed` unless a human actually performs and records it.

## Output and stop conditions

- Preserve Prompt 6.0, Prompt 7.1, evidence-extraction, and grounding-improvement reports unchanged.
- Write any authorized repeated inference output only to the separate Prompt 7.2 repeated-evaluation report paths.
- Stop and report configuration mismatch, loaded models, missing expected models, or any overlap between requests.
- Approval-gated remediation remains unchanged; no remediation or rollback is part of evaluation.

## Current result

- Live inference: **not run**.
- Authorization: **pending**.
