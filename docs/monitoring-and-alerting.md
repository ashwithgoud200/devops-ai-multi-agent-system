# Prometheus Metrics, Grafana Dashboards & Alert Rules Reference

## 1. Application-Level Prometheus Metrics (`agents/metrics.py` & `calculator_app/app.py`)

All metrics exposed at `GET /metrics` (`http://127.0.0.1:8100/metrics`) enforce **strictly bounded label allowlists**. Dynamic values such as incident UUIDs, raw user queries, LLM prompts, stack traces, file paths, or exception messages are never used as Prometheus labels.

| Metric Name | Type | Bounded Labels | Description |
|---|---|---|---|
| `calc_requests_total` | Counter | `op` (`add`, `sub`, `mul`, `div`, `pow`), `status` (`ok`, `client_error`, `error`) | Cumulative calculator operation requests by outcome. |
| `calc_latency_seconds` | Histogram | `op` | Calculator operation execution latency in seconds. |
| `devops_app_health_status` | Gauge | *(none)* | Application health status (`1` = healthy, `0` = unhealthy). |
| `devops_llm_enabled` | Gauge | *(none)* | Whether local Ollama specialist inference is enabled (`1` = enabled, `0` = disabled). |
| `devops_http_requests_total` | Counter | `endpoint` (route template or `unmatched`), `method`, `status` | Total HTTP requests across bounded FastAPI route templates. |
| `devops_http_request_duration_seconds` | Histogram | `endpoint`, `method` | HTTP request latency in seconds by bounded route template and method. |
| `devops_agent_executions_total` | Counter | `agent` (`monitoring`, `incident`, `code`, `cicd`, `infrastructure`, `security`), `outcome` (`ok`, `disabled`, `unavailable`, `invalid_response`, `timeout`, `configuration_error`, `error`, `not_selected`) | Specialist AI agent executions by agent ID and bounded outcome. |
| `devops_agent_execution_duration_seconds` | Histogram | `agent` | Specialist AI agent execution duration in seconds. |
| `devops_incidents_created_total` | Counter | *(none)* | Total incident investigations initiated via `POST /incidents`. |
| `devops_incident_diagnoses_total` | Counter | `remediation_action` (`rollback`, `investigate`, `none`, `error`) | Completed incident diagnoses grouped by proposed remediation action. |
| `devops_incidents_by_status_total` | Counter | `status` (`pending_approval`, `completed`, `failed`, `rejected`) | Cumulative incident lifecycle state transitions by bounded status (tracks transitions, not current incident totals). |
| `devops_incidents_current_status` | Gauge | `status` (`pending_approval`, `completed`, `failed`, `rejected`) | Current count of incidents in each lifecycle status, reconstructed from `incident_audit.jsonl` on startup. |
| `devops_human_decisions_total` | Counter | `decision` (`approve`, `reject`), `action` (`rollback`, `none`, `other`) | Explicit human operator approval and rejection decisions. |
| `devops_audit_events_total` | Counter | `event` (`baseline_saved`, `incident_started`, `diagnosis_finished`, `approval_decision`, `action_finished`, `other`) | Total append-only audit events persisted to `incident_audit.jsonl`. |
| `devops_llm_requests_total` | Counter | `agent`, `model` (6 pinned specialist models), `status` (`success`, `failure`, `timeout`, `unavailable`, `disabled`, `configuration_error`) | Ollama LLM inference calls by specialist agent, model, and status. |
| `devops_llm_request_duration_seconds` | Histogram | `agent`, `model` | Wall-clock duration in seconds of Ollama LLM inference attempts. |

### Startup Metric Pre-initialization & Audit-Log Status Reconstruction

- **Bounded Series Pre-initialization:** `initialize_metric_series()` in `agents/metrics.py` pre-initializes all `ALLOWED_AGENT_OUTCOMES` (`ok`, `disabled`, `unavailable`, `invalid_response`, `timeout`, `configuration_error`, `error`, `not_selected`) for all 6 agents, all `ALLOWED_LLM_STATUSES` (`success`, `failure`, `timeout`, `unavailable`, `disabled`, `configuration_error`) for all 6 agent-model pairs, and bounded HTTP status series (`200`, `400`, `404`, `409`, `422`, `500`) across all known route templates at `0.0` so Prometheus `rate()` / `increase()` alert rules have a baseline immediately upon startup.
  - *Note:* `calc_requests_total` is intentionally not pre-initialized with zero-valued series because `agents/graph.py` treats an empty `calc_requests_total` family as `"partial"` (no calculator requests observed yet) rather than zero errors.
- **Reconstructing `devops_incidents_current_status` After Restart:** `sync_incident_current_status_from_audit()` reads the persisted `DEVOPS_AUDIT_LOG_PATH` (`logs/incident_audit.jsonl`) on startup and calls `reconstruct_incident_current_status(events)`:
  - Each unique `incident_id` is counted at most once in its latest established status (`pending_approval`, `completed`, `failed`, or `rejected`), preventing duplicate counting across multiple audit events for the same incident and avoiding counting historical transitions as current incidents.
  - **Documented Limitations:**
    1. If an incident in `incident_audit.jsonl` has only `incident_started` (with no `diagnosis_finished`) or has `approval_decision="approve"` without a subsequent `action_finished`, its current status cannot be reliably established from the audit log alone (for example, if the process terminated mid-execution) and is left indeterminate (`None`) rather than inventing a status.
    2. LangGraph checkpoints use in-memory `MemorySaver()` in `agents/graph.py`. While `sync_incident_current_status_from_audit()` restores the `devops_incidents_current_status{status="pending_approval"}` gauge from `incident_audit.jsonl` after a restart, an interrupted in-memory LangGraph thread from before a container restart cannot be resumed via `POST /incidents/{id}/approval`.

---

## 2. Grafana Provisioned Dashboard (`grafana/dashboards/devops-overview.json`)

- **Dashboard Title:** `AI DevOps — System Monitoring Overview` (`uid: ai-devops-overview`)
- **Provisioning Config:** `grafana/provisioning/dashboards/dashboards.yml` (`disableDeletion: true`, `updateIntervalSeconds: 30`, `editable: false`) so dashboards survive container restarts and cannot be accidentally deleted.
- **Dashboard Sections (11 Row Groups, 41 Panels Total):**
  1. `Application Overview` (Calculator request rate, successful request rate, error rate %, P95 latency)
  2. `Application Resource Usage` (Process CPU %, Process resident memory MiB)
  3. `Docker Container Monitoring (optional)` (Container CPU, memory, restarts, health status — *optional cAdvisor/container exporter metrics are not installed in this stack and intentionally display `No Data`*)
  4. `Host Monitoring (optional)` (Host CPU %, Host memory % — *optional `node_exporter` metrics are not installed in this stack and intentionally display `No Data`*)
  5. `System Overview` (Backend target `up`, `devops_app_health_status`, `devops_llm_enabled`, active `pending_approval` count)
  6. `API Performance` (`devops_http_requests_total` rate by endpoint/method/status, P95 HTTP latency by endpoint)
  7. `Six-Agent Performance` (`devops_agent_executions_total` by agent & outcome, P95 agent execution duration)
  8. `Incident Monitoring` (`devops_incidents_created_total`, `Current Incidents by Status` via `devops_incidents_current_status`, `Incidents by Lifecycle Status` cumulative transitions via `devops_incidents_by_status_total`, `devops_incident_diagnoses_total`)
  9. `Human Approval and Audit` (`devops_human_decisions_total`, `devops_audit_events_total`)
  10. `LLM Runtime` (`devops_llm_requests_total` by model & status, P95 LLM inference latency by model)
  11. `Infrastructure and Container Health` (`scrape_samples_scraped`, `scrape_duration_seconds`)

---

## 3. Prometheus Alert Rules (`prometheus/alert_rules.yml`)

Loaded by Prometheus via `rule_files: ["/etc/prometheus/alert_rules.yml"]` in `prometheus.yml` and evaluated every `15s`. Every alert rule references only metrics that are actively exported by `calculator-app:8100/metrics` or built into Prometheus.

| Alert Name | Component | Severity | Threshold & Expression Summary | Evaluation Window (`for`) | False-Positive Guard & Scope Note |
|---|---|---|---|---|---|
| `BackendUnavailable` | `backend` | `critical` | `up{job="calculator-app"} == 0 or devops_app_health_status == 0` | `1m` | Requires 4 consecutive failed 15s checks before firing. |
| `PrometheusScrapeFailure` | `prometheus` | `warning` | `up{job="calculator-app"} == 0 or scrape_samples_scraped{job="calculator-app"} == 0` | `45s` | Requires 3 consecutive 15s scrape failures. |
| `ElevatedHttpErrorRate` | `api` | `warning` | HTTP `5xx` rate > `5%` or `calc_requests_total{status="error"}` rate > `5%` over `5m` | `2m` | Requires minimum request traffic `> 0.05 req/s` (`clamp_min` denominator) to avoid firing during idle periods or single-request tests. |
| `HighApiLatencyP95` | `api` | `warning` | Non-incident HTTP P95 latency > `1.0s` or calculator P95 latency > `0.5s` over `5m` | `2m` | Excludes long-running `/incidents*` orchestration routes and requires `> 0.05 req/s` traffic. |
| `AgentExecutionFailures` | `agents` | `warning` | `sum by (agent) (increase(devops_agent_executions_total{outcome=~"error\|invalid_response\|timeout\|configuration_error"}[10m])) >= 2` | `1m` | Ignores `disabled` and `unavailable` (offline Ollama) states; requires `>= 2` actual failures in `10m`. |
| `LlmTimeoutOrFailureRate` | `llm_runtime` | `warning` | `timeout\|failure\|unavailable` rate > `25%` of enabled LLM calls over `10m` | `2m` | Excludes `status="disabled"` and requires `>= 2` active LLM calls in `10m` so disabled mode never triggers alerts. |
| `ServiceTargetUnavailableOrRestarting` | `service_target` | `critical` | `up{job="calculator-app"} == 0 or changes(process_start_time_seconds{job="calculator-app"}[10m]) >= 2` | `1m` | Monitors HTTP scrape target availability and Python process restarts (`process_start_time_seconds`). Does not mount `/var/run/docker.sock` or require cAdvisor. |
