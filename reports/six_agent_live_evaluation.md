# Six-Agent Live Ollama Evaluation

- **Run time (UTC):** 2026-11-01T21:52:03.898114+00:00
- **Ollama URL:** `http://127.0.0.1:11434`
- **Ollama reachable:** True
- **Python:** 3.12.3
- **GPU:** NVIDIA GeForce RTX 3050 6GB Laptop GPU, 6144, 82, 30
- **Runtime limits:** `{"context_length": 2048, "keep_alive": "0s", "max_output_tokens": 384, "max_parallel_models": 1, "request_timeout_seconds": 120, "temperature": 0.1}`
- **Installed models:** granite3.1-dense:2b, phi3.5:3.8b, stablelm-zephyr:3b, qwen2.5-coder:3b, llama3.2:3b, qwen2.5:3b
- **Inference execution:** sequential; overlap detected: False
- **Evidence:** synthetic test fixtures only; no deployment, rollback, or remediation executed.

## Results

| Specialist | Assigned model | Available | Selected | Inference | JSON/schema | Grounding summary | Latency (s) | Retries | Result |
|---|---|---:|---:|---|---|---|---:|---:|---|
| monitoring | qwen2.5:3b | Yes | Yes | ok | Valid | 1 unverified; 0 hypotheses | 9.66 | 0 | PARTIAL |
| incident | llama3.2:3b | Yes | Yes | ok | Valid | 1 unverified; 0 hypotheses | 5.46 | 0 | PARTIAL |
| code | qwen2.5-coder:3b | Yes | Yes | ok | Valid | 2 unverified; 0 hypotheses | 6.33 | 0 | PASS |
| cicd | stablelm-zephyr:3b | Yes | Yes | ok | Valid | 5 unverified; 0 hypotheses | 6.94 | 0 | PARTIAL |
| infrastructure | phi3.5:3.8b | Yes | Yes | ok | Valid | 0 unverified; 0 hypotheses | 7.49 | 0 | PARTIAL |
| security | granite3.1-dense:2b | Yes | Yes | ok | Valid | 1 unverified; 0 hypotheses | 7.31 | 0 | PARTIAL |

## Monitoring — PARTIAL

- **Scenario:** Assess the supplied synthetic Prometheus observations. Identify the measured request/error rates, p95 latency, and process CPU. Keep observations separate from possible explanations; do not claim a confirmed root cause. Recommend checks only; take no action.
- **Routing:** selected; graph-selected agents: `['monitoring', 'infrastructure']`.
- **Model mapping:** assigned `qwen2.5:3b`, response model `qwen2.5:3b`.
- **Inference:** `ok`; JSON/schema valid: `True`; latency: `9.66s`; retries: `0`.

### Expected evaluation criteria

- Reports the observed error request rate and elevated error behavior.
- Reports the observed 850 ms p95 latency.
- Reports 88% process CPU as an observation, not a proven cause.
- Does not invent host/container measurements or assert a confirmed root cause.

### Parsed model response

```json
{
  "summary": "Prometheus synthetic observations have been reviewed. The request rate is 10 requests/second for successful operations and 2 requests/second for error operations. The HTTP error rate is 16.67 percent. The 95th percentile latency is 0.85 seconds. The CPU utilization is 88 percent of one CPU. The memory usage is 78,643,200 bytes.",
  "findings": [
    "Insufficient evidence: CPU utilization is 88 percent_of_one_cpu.",
    "Insufficient evidence: Memory usage is 78643200 bytes.",
    "Insufficient evidence: HTTP error rate is 16.6667 percent.",
    "Insufficient evidence: Request rate for error operations is 2 requests/second.",
    "Insufficient evidence: Latency p95 is 0.85 seconds."
  ],
  "confidence": 0.9,
  "recommended_checks": [
    "Verify the Prometheus synthetic evaluation fixture to ensure it is functioning correctly.",
    "Check the actual Prometheus metrics for the synthetic evaluation to confirm the values are accurate.",
    "Review the system for any recent changes that could affect the observed metrics.",
    "Monitor the system for any anomalies that might correlate with the observed metrics.",
    "Inspect the Docker containers for any resource usage that could explain the observed CPU and memory usage."
  ]
}
```

### Claim classifications (existing graph validator)

- **Unsupported or unverified claim** (summary): Prometheus synthetic observations have been reviewed. The request rate is 10 requests/second for successful operations and 2 requests/second for error operations. The HTTP error rate is 16.67 percent. The 95th percentile latency is 0.85 seconds. The CPU utilization is 88 percent of one CPU. The memory usage is 78,643,200 bytes. — evidence refs: `prometheus.metrics.cpu_utilization.observations[0].latest_value, prometheus.metrics.cpu_utilization.observations[0].values[0].value, prometheus.metrics.latency_p95.observations[0].latest_value, prometheus.metrics.latency_p95.observations[0].values[0].value, prometheus.metrics.request_rate.observations[0].latest_value, prometheus.metrics.request_rate.observations[0].values[0].value, prometheus.metrics.request_rate.observations[1].latest_value, prometheus.metrics.request_rate.observations[1].values[0].value`
  - Validator notes: numeric claim 16.67% cannot be matched to supplied error_rate evidence; numeric claim 78 cannot be matched to supplied memory evidence; numeric claim 643 cannot be matched to supplied memory evidence; numeric claim 200 cannot be matched to supplied memory evidence
- **Supported observation / evidence-linked claim** (findings): Insufficient evidence: CPU utilization is 88 percent_of_one_cpu. — evidence refs: `prometheus.metrics.cpu_utilization.observations[0].latest_value, prometheus.metrics.cpu_utilization.observations[0].values[0].value`
- **Supported observation / evidence-linked claim** (findings): Insufficient evidence: Memory usage is 78643200 bytes. — evidence refs: `prometheus.metrics.memory_usage.observations[0].latest_value, prometheus.metrics.memory_usage.observations[0].values[0].value`
- **Supported observation / evidence-linked claim** (findings): Insufficient evidence: HTTP error rate is 16.6667 percent. — evidence refs: `prometheus.metrics.http_error_rate.observations[0].latest_value, prometheus.metrics.http_error_rate.observations[0].values[0].value`
- **Supported observation / evidence-linked claim** (findings): Insufficient evidence: Request rate for error operations is 2 requests/second. — evidence refs: `prometheus.metrics.request_rate.observations[1].latest_value, prometheus.metrics.request_rate.observations[1].values[0].value`
- **Supported observation / evidence-linked claim** (findings): Insufficient evidence: Latency p95 is 0.85 seconds. — evidence refs: `prometheus.metrics.latency_p95.observations[0].latest_value, prometheus.metrics.latency_p95.observations[0].values[0].value`
- **Recommendation (not executed)** (recommended_check): Verify the Prometheus synthetic evaluation fixture to ensure it is functioning correctly. — evidence refs: `none`
- **Recommendation (not executed)** (recommended_check): Check the actual Prometheus metrics for the synthetic evaluation to confirm the values are accurate. — evidence refs: `none`
- **Recommendation (not executed)** (recommended_check): Review the system for any recent changes that could affect the observed metrics. — evidence refs: `none`
- **Recommendation (not executed)** (recommended_check): Monitor the system for any anomalies that might correlate with the observed metrics. — evidence refs: `none`
- **Recommendation (not executed)** (recommended_check): Inspect the Docker containers for any resource usage that could explain the observed CPU and memory usage. — evidence refs: `none`

### Retry/diagnostic record

```json
{
  "retry": {
    "attempted": false,
    "status": "not_needed"
  },
  "attempts": [
    {
      "attempt": 1,
      "status": "ok",
      "detail": null,
      "done_reason": "stop",
      "total_duration": 9654473500,
      "wall_duration_seconds": 9.657315100019332
    }
  ],
  "raw_excerpt": "{\n  \"summary\": \"Prometheus synthetic observations have been reviewed. The request rate is 10 requests/second for successful operations and 2 requests/second for error operations. The HTTP error rate is 16.67 percent. The 95th percentile latency is 0.85 seconds. The CPU utilization is 88 percent of one CPU. The memory usage is 78,643,200 bytes.\",\n  \"findings\": [\n    \"Insufficient evidence: CPU utilization is 88 percent_of_one_cpu.\",\n    \"Insufficient evidence: Memory usage is 78643200 bytes.\",\n    \"Insufficient evidence: HTTP error rate is 16.6667 percent.\",\n    \"Insufficient evidence: Request rate for error operations is 2 requests/second.\",\n    \"Insufficient evidence: Latency p95 is 0.85 seconds.\"\n  ],\n  \"confidence\": 0.9,\n  \"recommended_checks\": [\n    \"Verify the Prometheus synthetic evaluation fixture to ensure it is functioning correctly.\",\n    \"Check the actual Prometheus metrics for the synthetic evaluation to confirm the values are accurate.\",\n    \"Review the system for any recent changes that could affect the observed metrics.\",\n    \"Monitor the system for any anomalies that might correlate with the observed metrics.\",\n    \"Inspect the Docker containers for any resource usage that could explain the observed CPU and memory usage.\"\n  ]\n}",
  "raw_excerpt_truncated": false
}
```

## Incident — PARTIAL

- **Scenario:** Triage this synthetic incident. Correlate deployment, counters, latency, and timestamped logs. Distinguish temporal correlation from confirmed causation. Recommend investigation only.
- **Routing:** selected; graph-selected agents: `['monitoring', 'incident', 'code', 'cicd', 'infrastructure']`.
- **Model mapping:** assigned `llama3.2:3b`, response model `llama3.2:3b`.
- **Inference:** `ok`; JSON/schema valid: `True`; latency: `5.46s`; retries: `0`.

### Expected evaluation criteria

- Connects the version transition and increased errors/latency with repeated timeout logs.
- Treats the timing as correlation rather than confirmed causation.
- Does not invent infrastructure failure evidence.
- Recommends verification without executing rollback or remediation.

### Parsed model response

```json
{
  "summary": "Synthetic incident triage",
  "findings": [],
  "confidence": 0.0,
  "recommended_checks": []
}
```

### Claim classifications (existing graph validator)

- **Unsupported or unverified claim** (summary): Synthetic incident triage — evidence refs: `none`
  - Validator notes: natural-language claim cannot be fully verified by conservative evidence checks

### Retry/diagnostic record

```json
{
  "retry": {
    "attempted": false,
    "status": "not_needed"
  },
  "attempts": [
    {
      "attempt": 1,
      "status": "ok",
      "detail": null,
      "done_reason": "stop",
      "total_duration": 5445610800,
      "wall_duration_seconds": 5.460390300024301
    }
  ],
  "raw_excerpt": "{\"summary\": \"Synthetic incident triage\", \"findings\": [], \"confidence\": 0, \"recommended_checks\": []}",
  "raw_excerpt_truncated": false
}
```

## Code — PASS

- **Scenario:** Review only the supplied synthetic source snippet and observed stack trace. Identify the edge case and suggest a safe code-level correction without claiming it has been applied. Do not invent other code changes.
- **Routing:** selected; graph-selected agents: `['incident', 'code']`.
- **Model mapping:** assigned `qwen2.5-coder:3b`, response model `qwen2.5-coder:3b`.
- **Inference:** `ok`; JSON/schema valid: `True`; latency: `6.33s`; retries: `0`.

### Expected evaluation criteria

- Identifies the empty-list division-by-zero edge case.
- Suggests a safe correction while stating it is only a suggestion.
- Does not claim any change was applied or invent additional modifications.

### Parsed model response

```json
{
  "summary": "Identified edge case and suggested correction for division by zero in calculate_average function.",
  "findings": [
    "Insufficient evidence: The provided code snippet does not include any checks for an empty list before performing the division operation."
  ],
  "confidence": 0.5,
  "recommended_checks": [
    "Add a check to ensure the input list is not empty before calling calculate_average."
  ]
}
```

### Claim classifications (existing graph validator)

- **Unsupported or unverified claim** (summary): Identified edge case and suggested correction for division by zero in calculate_average function. — evidence refs: `none`
  - Validator notes: natural-language claim cannot be fully verified by conservative evidence checks
- **Unsupported or unverified claim** (findings): Insufficient evidence: The provided code snippet does not include any checks for an empty list before performing the division operation. — evidence refs: `none`
  - Validator notes: natural-language claim cannot be fully verified by conservative evidence checks
- **Recommendation (not executed)** (recommended_check): Add a check to ensure the input list is not empty before calling calculate_average. — evidence refs: `none`

### Retry/diagnostic record

```json
{
  "retry": {
    "attempted": false,
    "status": "not_needed"
  },
  "attempts": [
    {
      "attempt": 1,
      "status": "ok",
      "detail": null,
      "done_reason": "stop",
      "total_duration": 6321726600,
      "wall_duration_seconds": 6.3278589000110514
    }
  ],
  "raw_excerpt": "{\n  \"summary\": \"Identified edge case and suggested correction for division by zero in calculate_average function.\",\n  \"findings\": [\n    \"Insufficient evidence: The provided code snippet does not include any checks for an empty list before performing the division operation.\"\n  ],\n  \"confidence\": 0.5,\n  \"recommended_checks\": [\n    \"Add a check to ensure the input list is not empty before calling calculate_average.\"\n  ]\n}",
  "raw_excerpt_truncated": false
}
```

## Cicd — PARTIAL

- **Scenario:** Analyze this synthetic deployment evidence. Distinguish deployment success from application health and pipeline status. Recommend verification steps only; do not deploy or roll back.
- **Routing:** selected; graph-selected agents: `['monitoring', 'incident', 'code', 'cicd', 'infrastructure']`.
- **Model mapping:** assigned `stablelm-zephyr:3b`, response model `stablelm-zephyr:3b`.
- **Inference:** `ok`; JSON/schema valid: `True`; latency: `6.94s`; retries: `0`.

### Expected evaluation criteria

- Identifies successful deployment followed by increased errors.
- Does not claim pipeline failure.
- Distinguishes HTTP 200/health status from error-rate behavior.
- Recommends investigation without executing deployment or rollback.

### Parsed model response

```json
{
  "summary": "Analyzing synthetic deployment evidence",
  "findings": [
    "Deployment status is 'ok'.",
    "Application health status is 'ok'.",
    "Pipeline status is unavailable.",
    "Health check status is unavailable.",
    "Post-deployment error rate increased from pre-deployment (16.666.7%).",
    "Baseline comparison indicates a regression signal and deployment has changed.",
    "Prometheus metrics are unavailable."
  ],
  "confidence": 0.9,
  "recommended_checks": [
    "Check if there are any pipeline failures by reviewing the pipeline status.",
    "Check if the health check is working correctly by running a health check manually.",
    "Monitor post-deployment error rate over time to assess if it's increasing or decreasing.",
    "Check if the baseline comparison indicates any issues with the new deployment."
  ]
}
```

### Claim classifications (existing graph validator)

- **Unsupported or unverified claim** (summary): Analyzing synthetic deployment evidence — evidence refs: `none`
  - Validator notes: natural-language claim cannot be fully verified by conservative evidence checks
- **Unsupported or unverified claim** (findings): Deployment status is 'ok'. — evidence refs: `none`
  - Validator notes: natural-language claim cannot be fully verified by conservative evidence checks
- **Supported observation / evidence-linked claim** (findings): Application health status is 'ok'. — evidence refs: `health.data.status`
- **Supported observation / evidence-linked claim** (findings): Pipeline status is unavailable. — evidence refs: `pipeline.status`
- **Unsupported or unverified claim** (findings): Health check status is unavailable. — evidence refs: `none`
  - Validator notes: health is not reported unavailable; supplied status health.status=ok, health.data.status=ok; natural-language claim cannot be fully verified by conservative evidence checks
- **Unsupported or unverified claim** (findings): Post-deployment error rate increased from pre-deployment (16.666.7%). — evidence refs: `none`
  - Validator notes: numeric claim 16.666 cannot be matched to supplied deployment evidence
- **Unsupported or unverified claim** (findings): Baseline comparison indicates a regression signal and deployment has changed. — evidence refs: `none`
  - Validator notes: natural-language claim cannot be fully verified by conservative evidence checks
- **Supported observation / evidence-linked claim** (findings): Prometheus metrics are unavailable. — evidence refs: `prometheus.status`
- **Recommendation (not executed)** (recommended_check): Check if there are any pipeline failures by reviewing the pipeline status. — evidence refs: `none`
- **Recommendation (not executed)** (recommended_check): Check if the health check is working correctly by running a health check manually. — evidence refs: `none`
- **Recommendation (not executed)** (recommended_check): Monitor post-deployment error rate over time to assess if it's increasing or decreasing. — evidence refs: `none`
- **Recommendation (not executed)** (recommended_check): Check if the baseline comparison indicates any issues with the new deployment. — evidence refs: `none`

### Retry/diagnostic record

```json
{
  "retry": {
    "attempted": false,
    "status": "not_needed"
  },
  "attempts": [
    {
      "attempt": 1,
      "status": "ok",
      "detail": null,
      "done_reason": "stop",
      "total_duration": 6939755400,
      "wall_duration_seconds": 6.942304900003364
    }
  ],
  "raw_excerpt": "{\n  \"summary\": \"Analyzing synthetic deployment evidence\",\n  \"findings\": [\n    \"Deployment status is 'ok'.\",\n    \"Application health status is 'ok'.\",\n    \"Pipeline status is unavailable.\",\n    \"Health check status is unavailable.\",\n    \"Post-deployment error rate increased from pre-deployment (16.666.7%).\",\n    \"Baseline comparison indicates a regression signal and deployment has changed.\",\n    \"Prometheus metrics are unavailable.\"\n  ],\n  \"confidence\": 0.9,\n  \"recommended_checks\": [\n    \"Check if there are any pipeline failures by reviewing the pipeline status.\",\n    \"Check if the health check is working correctly by running a health check manually.\",\n    \"Monitor post-deployment error rate over time to assess if it's increasing or decreasing.\",\n    \"Check if the baseline comparison indicates any issues with the new deployment.\"\n  ]\n}",
  "raw_excerpt_truncated": false
}
```

## Infrastructure — PARTIAL

- **Scenario:** Interpret this synthetic Docker and process telemetry. Keep container and host-process memory separate. State resource pressure as an observation and do not invent root causes or unprovided metrics. Recommend checks only.
- **Routing:** selected; graph-selected agents: `['monitoring', 'infrastructure']`.
- **Model mapping:** assigned `phi3.5:3.8b`, response model `phi3.5:3.8b`.
- **Inference:** `ok`; JSON/schema valid: `True`; latency: `7.49s`; retries: `0`.

### Expected evaluation criteria

- Reports running/healthy status and zero restarts accurately.
- Identifies 92% CPU as observed resource pressure without calling the container unhealthy.
- Distinguishes 700 MiB container memory from 60 MiB process memory.
- Does not invent disk, network, or root-cause evidence.

### Parsed model response

```json
{
  "summary": "Container 'synthetic-calculator' (ID: synthetic-container-001) is running with a CPU usage of 92% and memory usage of 734003200 bytes (700 MiB). The host process memory usage is 60 MiB. No health status, restart count, or Prometheus metrics are available.",
  "findings": [
    "Container ID: synthetic-container-001 (evidence: {"
  ],
  "confidence": 1.0,
  "recommended_checks": [
    "Check if the high CPU usage of the container is within acceptable limits for the application's requirements."
  ]
}
```

### Claim classifications (existing graph validator)

- **Supported observation / evidence-linked claim** (summary): Container 'synthetic-calculator' (ID: synthetic-container-001) is running with a CPU usage of 92% and memory usage of 734003200 bytes (700 MiB). The host process memory usage is 60 MiB. No health status, restart count, or Prometheus metrics are available. — evidence refs: `docker.containers[0].cpu_usage_percent, docker.containers[0].id, docker.containers[0].memory_usage_bytes, docker.containers[0].memory_usage_mib, docker.containers[0].status, health.status, system_metrics.host_process_memory_mib`
- **Supported observation / evidence-linked claim** (findings): Container ID: synthetic-container-001 (evidence: { — evidence refs: `docker.containers[0].id`
- **Recommendation (not executed)** (recommended_check): Check if the high CPU usage of the container is within acceptable limits for the application's requirements. — evidence refs: `none`

### Retry/diagnostic record

```json
{
  "retry": {
    "attempted": false,
    "status": "not_needed"
  },
  "attempts": [
    {
      "attempt": 1,
      "status": "ok",
      "detail": null,
      "done_reason": "stop",
      "total_duration": 7479635400,
      "wall_duration_seconds": 7.4870153999945614
    }
  ],
  "raw_excerpt": "{\n  \"summary\": \"Container 'synthetic-calculator' (ID: synthetic-container-001) is running with a CPU usage of 92% and memory usage of 734003200 bytes (700 MiB). The host process memory usage is 60 MiB. No health status, restart count, or Prometheus metrics are available.\",\n  \"findings\": [\n    \"Container ID: synthetic-container-001 (evidence: {\"\n   \t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t],\"confidence\": 1,\n    \"recommended_checks\": [\"Check if the high CPU usage of the container is within acceptable limits for the application's requirements.\"]\n  }",
  "raw_excerpt_truncated": false
}
```

## Security — PARTIAL

- **Scenario:** Triage only the synthetic authentication events. Identify the recorded failed and successful login sequence. Treat suspicious intent as a hypothesis, not confirmed compromise. Do not invent geolocation, reputation, threat intelligence, or attacker attribution.
- **Routing:** selected; graph-selected agents: `['security']`.
- **Model mapping:** assigned `granite3.1-dense:2b`, response model `granite3.1-dense:2b`.
- **Inference:** `ok`; JSON/schema valid: `True`; latency: `7.31s`; retries: `0`.

### Expected evaluation criteria

- Identifies the repeated failed logins and subsequent successful login.
- Treats the sequence as potentially suspicious, not confirmed malicious or compromised.
- Preserves supplied timestamps and the synthetic source IP accurately.
- Does not invent geolocation, reputation, or threat-intelligence claims.

### Parsed model response

```json
{
  "summary": "Synthetic authentication events indicate repeated failed login attempts for user 'demo' from IP 192.0.2.10, followed by a successful login.",
  "findings": [
    "Repeated failed authentication attempts for user 'demo' from IP 192.0.2.10 at timestamps 2026-11-01T21:51:09Z, 2026-11-01T21:51:14Z, and 2026-11-01T21:51:19Z.",
    "Successful authentication for user 'demo' from IP 192.0.2.10 at timestamp 2026-11-01T21:51:24Z."
  ],
  "confidence": 1.0,
  "recommended_checks": [
    "Verify the configuration of the synthetic security log fixture to ensure it accurately captures authentication events.",
    "Investigate the source of repeated failed login attempts, including potential brute force attacks or unauthorized access attempts.",
    "Review the security policies and access controls for user 'demo' to ensure they are appropriately configured and enforced."
  ]
}
```

### Claim classifications (existing graph validator)

- **Supported observation / evidence-linked claim** (summary): Synthetic authentication events indicate repeated failed login attempts for user 'demo' from IP 192.0.2.10, followed by a successful login. — evidence refs: `security_events.events[0].msg, security_events.events[1].msg, security_events.events[2].msg, security_events.events[3].msg`
- **Supported observation / evidence-linked claim** (findings): Repeated failed authentication attempts for user 'demo' from IP 192.0.2.10 at timestamps 2026-11-01T21:51:09Z, 2026-11-01T21:51:14Z, and 2026-11-01T21:51:19Z. — evidence refs: `security_events.events[0].msg, security_events.events[0].ts, security_events.events[1].msg, security_events.events[1].ts, security_events.events[2].msg, security_events.events[2].ts, security_events.events[3].msg`
- **Supported observation / evidence-linked claim** (findings): Successful authentication for user 'demo' from IP 192.0.2.10 at timestamp 2026-11-01T21:51:24Z. — evidence refs: `security_events.events[0].msg, security_events.events[1].msg, security_events.events[2].msg, security_events.events[3].msg, security_events.events[3].ts`
- **Recommendation (not executed)** (recommended_check): Verify the configuration of the synthetic security log fixture to ensure it accurately captures authentication events. — evidence refs: `none`
- **Recommendation with unsupported premise** (recommended_check): Investigate the source of repeated failed login attempts, including potential brute force attacks or unauthorized access attempts. — evidence refs: `none`
  - Validator notes: security classification or threat attribution claim 'brute force' is not verified by the supplied evidence
- **Recommendation (not executed)** (recommended_check): Review the security policies and access controls for user 'demo' to ensure they are appropriately configured and enforced. — evidence refs: `none`

### Retry/diagnostic record

```json
{
  "retry": {
    "attempted": false,
    "status": "not_needed"
  },
  "attempts": [
    {
      "attempt": 1,
      "status": "ok",
      "detail": null,
      "done_reason": "stop",
      "total_duration": 7301479500,
      "wall_duration_seconds": 7.304444399982458
    }
  ],
  "raw_excerpt": "{\n  \"summary\": \"Synthetic authentication events indicate repeated failed login attempts for user 'demo' from IP 192.0.2.10, followed by a successful login.\",\n  \"findings\": [\n    \"Repeated failed authentication attempts for user 'demo' from IP 192.0.2.10 at timestamps 2026-11-01T21:51:09Z, 2026-11-01T21:51:14Z, and 2026-11-01T21:51:19Z.\",\n    \"Successful authentication for user 'demo' from IP 192.0.2.10 at timestamp 2026-11-01T21:51:24Z.\"\n  ],\n  \"confidence\": 1,\n  \"recommended_checks\": [\n    \"Verify the configuration of the synthetic security log fixture to ensure it accurately captures authentication events.\",\n    \"Investigate the source of repeated failed login attempts, including potential brute force attacks or unauthorized access attempts.\",\n    \"Review the security policies and access controls for user 'demo' to ensure they are appropriately configured and enforced.\"\n  ]\n}",
  "raw_excerpt_truncated": false
}
```

## Failure handling and limitations

Offline runtime tests cover Ollama unavailable, malformed/truncated JSON, one correction retry, retry failure, strict schema failures, and invalid responses. The live harness did not stop Ollama or induce a live timeout/server failure. One specialist failure continuing through the graph is covered by offline graph tests; live inference here calls each runtime specialist sequentially rather than running remediation or the full interrupt/approval graph.

Claim grounding uses the existing conservative `graph._validate_finding` function. It is not a general natural-language fact checker: unmatched numerical/unit claims and prose without recognized evidence links are reported unverified. A model's confidence is not proof. Synthetic fixture performance does not establish real-world diagnostic accuracy.

Sequentiality was enforced by serial calls to `llm_runtime.analyze` plus its process-wide lock. Per-model start/end wall timestamps are recorded; no calls overlap. The runtime exposes total inference duration and request wall duration, but not Ollama load/unload duration fields. `/api/ps` was sampled before and after each inference; keep-alive is configured as `0s`.
