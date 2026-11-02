# Prompt 7.2 — Repeated Controlled Evaluation

- **Evaluation time (UTC):** 2026-11-02T06:55:32.367569+00:00
- **Repetitions per agent:** 3
- **Runs:** 21; successes: 21; failures: 0; schema-invalid: 0; incomplete: 0; quality failures: 3.
- **Sequential overlap detected:** False
- **Operational actions:** none.

## Context-budget measurements

- Attempts with prompt token measurements: 22/22.
- `within_budget`: 22
- `potential_context_pressure`: 0
- `context_pressure`: 0
- `measurement_unavailable`: 0

## Per-agent aggregates

| Agent | Runs | Failed/incomplete | Wall mean (s) | Wall min (s) | Wall max (s) | Wall stddev (s) | Interpretation mean | Grounding mean | Manual audit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| monitoring | 3 | 0 | 14.24 | 10.33 | 18.64 | 4.18 | 0.83 | 0.91 | not performed |
| incident | 3 | 0 | 10.24 | 7.00 | 16.04 | 5.04 | 0.00 | 1.00 | not performed |
| code | 3 | 0 | 7.90 | 7.52 | 8.61 | 0.62 | 0.78 | 0.67 | not performed |
| cicd | 3 | 0 | 12.39 | 7.71 | 19.88 | 6.55 | 0.00 | 0.85 | not performed |
| infrastructure | 3 | 0 | 10.35 | 10.05 | 10.72 | 0.34 | 0.29 | 0.67 | not performed |
| security | 3 | 0 | 9.17 | 8.86 | 9.70 | 0.46 | 0.24 | 0.76 | not performed |

## Negative control

{
  "run_count": 3,
  "scores": [
    1.0,
    1.0,
    1.0
  ],
  "score_statistics": {
    "count": 3,
    "excluded_count": null,
    "mean": 1.0,
    "minimum": 1.0,
    "maximum": 1.0,
    "standard_deviation": 0.0
  },
  "failed_or_incomplete_count": 0,
  "unsupported_claim_count": 0
}

## Individual runs

- Repetition 1, `prompt6-monitoring`: inference `ok`, schema `True`, failure reasons `['Error rate']`.
- Repetition 1, `prompt6-incident`: inference `ok`, schema `True`, failure reasons `['Previous version', 'Current version', 'Previous error count', 'Current error count', 'Baseline latency', 'Current latency', 'Timeout log evidence']`.
- Repetition 1, `prompt6-code`: inference `ok`, schema `True`, failure reasons `['Supplied function']`.
- Repetition 1, `prompt6-cicd`: inference `ok`, schema `True`, failure reasons `['Previous version', 'Current version', 'Deployment completion', 'Health response', 'Post-deployment error rate']`.
- Repetition 1, `prompt6-infrastructure`: inference `ok`, schema `True`, failure reasons `['Container name', 'Running state', 'Healthy state', 'Zero restarts', 'Container memory']`.
- Repetition 1, `prompt6-security`: inference `ok`, schema `True`, failure reasons `['Subsequent successful login', 'Event timestamp 2026-11-01T21:51:09Z', 'Event timestamp 2026-11-01T21:51:14Z', 'Event timestamp 2026-11-01T21:51:19Z', 'Event timestamp 2026-11-01T21:51:24Z']`.
- Repetition 1, `negative-control-container-health`: inference `ok`, schema `True`, failure reasons `['Container name', 'Running state', 'Healthy state', 'Zero restarts', 'Container CPU', 'Container memory', 'Process memory']`.
- Repetition 2, `prompt6-monitoring`: inference `ok`, schema `True`, failure reasons `['Error rate']`.
- Repetition 2, `prompt6-incident`: inference `ok`, schema `True`, failure reasons `['Previous version', 'Current version', 'Previous error count', 'Current error count', 'Baseline latency', 'Current latency', 'Timeout log evidence']`.
- Repetition 2, `prompt6-code`: inference `ok`, schema `True`, failure reasons `[]`.
- Repetition 2, `prompt6-cicd`: inference `ok`, schema `True`, failure reasons `['Previous version', 'Current version', 'Deployment completion', 'Health response', 'Post-deployment error rate']`.
- Repetition 2, `prompt6-infrastructure`: inference `ok`, schema `True`, failure reasons `['Container name', 'Running state', 'Healthy state', 'Zero restarts', 'Container memory']`.
- Repetition 2, `prompt6-security`: inference `ok`, schema `True`, failure reasons `['Repeated failed logins', 'Subsequent successful login', 'Event timestamp 2026-11-01T21:51:09Z', 'Event timestamp 2026-11-01T21:51:14Z', 'Event timestamp 2026-11-01T21:51:19Z', 'Event timestamp 2026-11-01T21:51:24Z']`.
- Repetition 2, `negative-control-container-health`: inference `ok`, schema `True`, failure reasons `['Container name', 'Running state', 'Healthy state', 'Zero restarts', 'Container CPU', 'Container memory', 'Process memory']`.
- Repetition 3, `prompt6-monitoring`: inference `ok`, schema `True`, failure reasons `['Error rate']`.
- Repetition 3, `prompt6-incident`: inference `ok`, schema `True`, failure reasons `['Previous version', 'Current version', 'Previous error count', 'Current error count', 'Baseline latency', 'Current latency', 'Timeout log evidence']`.
- Repetition 3, `prompt6-code`: inference `ok`, schema `True`, failure reasons `['Empty input edge case']`.
- Repetition 3, `prompt6-cicd`: inference `ok`, schema `True`, failure reasons `['Previous version', 'Current version', 'Deployment completion', 'Health response', 'Post-deployment error rate']`.
- Repetition 3, `prompt6-infrastructure`: inference `ok`, schema `True`, failure reasons `['Container name', 'Running state', 'Healthy state', 'Zero restarts', 'Container memory']`.
- Repetition 3, `prompt6-security`: inference `ok`, schema `True`, failure reasons `['Subsequent successful login', 'Event timestamp 2026-11-01T21:51:09Z', 'Event timestamp 2026-11-01T21:51:14Z', 'Event timestamp 2026-11-01T21:51:19Z', 'Event timestamp 2026-11-01T21:51:24Z']`.
- Repetition 3, `negative-control-container-health`: inference `ok`, schema `True`, failure reasons `['Container name', 'Running state', 'Healthy state', 'Zero restarts', 'Container CPU', 'Container memory', 'Process memory']`.
