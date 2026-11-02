# Local API reference

The app's OpenAPI/Swagger UI is at `http://127.0.0.1:8100/docs`; the schema is `/openapi.json`. The API is a local demonstration service, not an authenticated production service. Keep it bound to loopback and do not expose its admin or approval routes to an untrusted network. `reviewed_by` is an audit label, not authenticated identity.

## Health, sample application, and telemetry

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | App readiness and current sample-app version. |
| `GET` | `/metrics` | Prometheus exposition for application counters/histograms. |
| `GET` | `/agents` | Current configured specialist IDs, model assignments, roles, and runtime-enabled flag. |
| `GET` | `/calc/{op}?a=2&b=3` | Generate sample app traffic (`add`, `sub`, `mul`, `div`, `pow`). |
| `GET` | `/telemetry/prometheus` | Read-only Prometheus time-series collection. Missing integration is returned as `unavailable`/`partial`. |
| `GET` | `/telemetry/docker` | Read-only Docker CLI telemetry; missing Engine/CLI remains `unavailable`. |
| `GET` | `/admin/version` | Sample app's current version and deployment history. |

## Baselines and incident workflow

### Save and inspect baseline

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8100/baseline
Invoke-RestMethod http://127.0.0.1:8100/baseline
```

Saving a baseline collects a snapshot and atomically writes it to `data/baseline.json` by default. In Compose this is retained in the `app_data` named volume. It is local demonstration state, not a shared or production database.

### Start a diagnosis

```powershell
$incident = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8100/incidents `
  -ContentType 'application/json' `
  -Body (@{ query = 'Investigate errors after the latest deployment' } | ConvertTo-Json)
$incident | ConvertTo-Json -Depth 12
```

The workflow collects telemetry, compares the saved baseline, runs selected specialists sequentially, validates claims against deterministic evidence, builds a diagnosis and proposes an action. The response includes an `incident_id`, trace, evidence availability, baseline comparison, specialist outcomes, verified observations, hypotheses, proposed remediation, and status. Query strings are not copied into the audit log.

If `status` is `pending_approval`, inspect the `approval_request` and `proposed_remediation` before deciding. Model output by itself cannot create approval. If there is no justified action, the incident completes without pausing.

### Approve or reject a pending action

Use the returned incident ID and submit an explicit decision:

```powershell
$decision = @{
  decision = 'reject'
  reviewed_by = 'local operator'
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8100/incidents/$($incident.incident_id)/approval" `
  -ContentType 'application/json' `
  -Body $decision
```

Set `decision` to `approve` only after review. `reviewed_by` must be a nonblank string. A second decision or a decision when no proposal is pending returns HTTP `409`. Approval resumes only the supported rollback path; rejection records a rejected outcome and sends no rollback request.

### Read status and audit history

```powershell
Invoke-RestMethod "http://127.0.0.1:8100/incidents/$($incident.incident_id)" |
  ConvertTo-Json -Depth 12
Invoke-RestMethod "http://127.0.0.1:8100/incidents/$($incident.incident_id)/audit" |
  ConvertTo-Json -Depth 8
Invoke-RestMethod http://127.0.0.1:8100/audit |
  ConvertTo-Json -Depth 8
```

`GET /audit` returns all metadata-only audit events for the dashboard's incident history. `GET /incidents/{incident_id}/audit` remains available for a single incident.

The JSONL audit file is `logs/incident_audit.jsonl` by default, configurable with `DEVOPS_AUDIT_LOG_PATH`; Compose stores it on the `app_logs` named volume. It records timestamps, incident IDs, decision labels, supplied reviewer labels, action/outcome status, and baseline-save events. It excludes incident query text and evidence payloads. The file is local and append-only by this API, but is not tamper-proof or a substitute for a centralized audit service.

## Sample-only administrative controls

`POST /admin/deploy` and `POST /admin/rollback` control the in-memory calculator used by the synthetic demo. They are unauthenticated sample-app controls, not production deployment APIs. The incident graph does not call rollback until its pending proposal receives an explicit approval through the workflow. Compose publishes the app only on loopback; do not expose these routes publicly.

## Runtime limitations

- LangGraph checkpoints are in-memory. Use a single Uvicorn worker and do not restart the process while approvals are pending; pending state is lost on restart.
- The reviewer label is self-reported, not authenticated. Add proper authentication/authorization and durable shared checkpoint/audit storage before any shared or production deployment.
- Some specialist results may be `disabled`, `unavailable`, or `invalid_response`; deterministic evidence/diagnosis still reports what could be established.
