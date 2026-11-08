# SRE-103: Performance Drift & Latency Degradation Playbook

## Metadata
- **ID:** SRE-103
- **Severity:** High
- **Target Service:** `calculator-app`
- **Category:** Performance Drift / Latency Spike

## Symptoms
- 95th and 99th percentile request latency exceeding 250ms threshold.
- Prometheus histogram metric `calc_latency_seconds_bucket` skewing toward upper boundaries.
- Distributed traces in Tempo show elevated span duration in middleware or specific route handlers.
- Baseline comparison flags statistically significant duration deviation (>200%).

## Diagnostic Steps
1. Query Tempo traces with filter `minDuration=200ms` to identify slow operations.
2. Check Prometheus system metrics: CPU usage (`system_metrics.cpu_percent`) and memory consumption.
3. Review `/scenarios` status to verify if synthetic latency injection is active.
4. Check downstream Prometheus scrape intervals and log volume in Loki.

## Remediation Protocol
1. **Immediate Action:**
   - If synthetic latency scenario is active, reset via `POST /scenarios/reset`.
   - If CPU or container thread contention is detected, restart affected container via Compose.
2. **Investigation:**
   - Profile slow endpoints using inspect signature and runtime benchmarks.
   - Ensure timeout settings in upstream reverse proxy or frontend are bounded.

