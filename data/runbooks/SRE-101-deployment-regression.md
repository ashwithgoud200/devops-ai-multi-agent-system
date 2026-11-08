# SRE-101: Deployment Regression & Crash Triage Playbook

## Metadata
- **ID:** SRE-101
- **Severity:** High / Critical
- **Target Service:** `calculator-app`
- **Category:** Deployment Regression

## Symptoms
- Elevated HTTP 500 error rates immediately following a new release (e.g., version 1.1).
- Unhandled exceptions or handler crashes in core API endpoints (e.g., `/calc/div`).
- Spike in Prometheus metric `calc_requests_total{status="error"}`.
- Regression detected in comparison with baseline telemetry.

## Diagnostic Steps
1. Verify current application version from `/admin/version` or `/health`.
2. Review recent Git commits (`git log -n 5`) to identify suspect patch.
3. Inspect Prometheus error rates and Loki log streams for stack traces (`RuntimeError`, `division handler crashed`).
4. Validate container status in Docker Compose topology.

## Remediation Protocol
1. **Immediate Mitigation:**
   - Execute an immediate rollback to the previous known stable version (typically `1.0`).
   - Human approval is required prior to executing `POST /admin/rollback`.
2. **Post-Rollback Verification:**
   - Confirm `/health` returns HTTP 200 with status `ok` and version `1.0`.
   - Verify `/calc/add` and `/calc/div` respond with status 200 for valid inputs.
3. **Permanent Resolution:**
   - Dispatch Code Agent (`qwen2.5-coder:3b`) to synthesize fix (v1.1.1).
   - Validate fix against GitHub Actions CI matrix before redeploying.

