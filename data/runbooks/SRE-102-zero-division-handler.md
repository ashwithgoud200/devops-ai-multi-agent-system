# SRE-102: Zero Division & Arithmetic Boundary Playbook

## Metadata
- **ID:** SRE-102
- **Severity:** Medium
- **Target Service:** `calculator-app`
- **Category:** Client Input / Application Edge Case

## Symptoms
- Spikes in HTTP 400 Bad Request or HTTP 500 when users provide `b=0` on division.
- Metric increase in `calc_requests_total{op="div", status="client_error"}`.
- Loki logs show `WARN: division by zero (user input)`.

## Diagnostic Steps
1. Determine whether the division error is treated as a client error (HTTP 400) or server crash (HTTP 500).
2. If returning 500, check `app.py` division handler logic for missing `ZeroDivisionError` translation.
3. Verify test coverage in `tests/test_app.py` for edge cases (`a=0`, `b=0`, negative numbers).

## Remediation Protocol
1. **Application Logic Hardening:**
   - Ensure `app.py` catches `ZeroDivisionError` and returns clean HTTP 400 with detail `"division by zero"`.
2. **Deterministic Policy:**
   - Do not perform rollback if the error is an unhandled client error. Instead, propose code patch.
3. **Verification:**
   - Execute `GET /calc/div?a=10&b=0` and confirm response is HTTP 400, not HTTP 500.

