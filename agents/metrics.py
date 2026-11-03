"""Application-level Prometheus metrics with strictly bounded label sets.

Security & cardinality policy:
- Never use incident IDs, raw user queries, prompts, stack traces, file paths,
  or arbitrary exception text as Prometheus label values.
- Every label value is validated against a closed, finite allowlist and falls
  back to a safe constant ("other" or "unknown") if outside the allowlist.

Persistence & restart note:
- On startup (`initialize_metric_series` / `sync_incident_current_status_from_audit`),
  `devops_incidents_current_status` is reconstructed from the persisted audit log
  (`DEVOPS_AUDIT_LOG_PATH`, default `logs/incident_audit.jsonl`) so each unique
  incident is counted at most once in its latest established status.
- If an incident has only `incident_started` (or `approval_decision="approve"`
  without `action_finished`), its current state is indeterminate from the audit
  log and is not invented.
- Restoring the `pending_approval` gauge after a process restart reflects audit
  history only; it does not restore LangGraph's in-memory `MemorySaver`
  checkpoint or make an interrupted workflow resumable after restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_LOG_PATH = ROOT / "logs" / "incident_audit.jsonl"

ALLOWED_AGENTS = (
    "monitoring",
    "incident",
    "code",
    "cicd",
    "infrastructure",
    "security",
)
ALLOWED_AGENT_OUTCOMES = (
    "ok",
    "disabled",
    "unavailable",
    "invalid_response",
    "timeout",
    "configuration_error",
    "error",
    "not_selected",
)
ALLOWED_MODELS = (
    "qwen2.5:3b",
    "llama3.2:3b",
    "qwen2.5-coder:3b",
    "stablelm-zephyr:3b",
    "phi3.5:3.8b",
    "granite3.1-dense:2b",
)
ALLOWED_LLM_STATUSES = (
    "success",
    "failure",
    "timeout",
    "unavailable",
    "disabled",
    "configuration_error",
)
ALLOWED_INCIDENT_STATUSES = (
    "pending_approval",
    "completed",
    "failed",
    "rejected",
)
ALLOWED_REMEDIATION_ACTIONS = (
    "rollback",
    "investigate",
    "none",
    "error",
)
ALLOWED_APPROVAL_DECISIONS = (
    "approve",
    "reject",
)
ALLOWED_AUDIT_EVENTS = (
    "baseline_saved",
    "incident_started",
    "diagnosis_finished",
    "approval_decision",
    "action_finished",
)
ALLOWED_HTTP_METHODS = (
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "PATCH",
    "OPTIONS",
    "HEAD",
)
ALLOWED_HTTP_ENDPOINTS = (
    "/calc/{op}",
    "/health",
    "/metrics",
    "/telemetry/docker",
    "/telemetry/prometheus",
    "/admin/version",
    "/admin/deploy",
    "/admin/rollback",
    "/baseline",
    "/agents",
    "/incidents",
    "/incidents/{incident_id}",
    "/incidents/{incident_id}/approval",
    "/incidents/{incident_id}/audit",
    "/audit",
    "/integrations/status",
    "/ci/runs/latest",
    "/security/findings",
    "/openapi.json",
    "/docs",
    "/redoc",
    "unmatched",
)
ALLOWED_HTTP_STATUSES = (
    "200",
    "400",
    "404",
    "405",
    "409",
    "422",
    "500",
    "502",
    "503",
    "other",
)

AGENT_DEFAULT_MODELS: dict[str, str] = {
    "monitoring": "qwen2.5:3b",
    "incident": "llama3.2:3b",
    "code": "qwen2.5-coder:3b",
    "cicd": "stablelm-zephyr:3b",
    "infrastructure": "phi3.5:3.8b",
    "security": "granite3.1-dense:2b",
}

# 1. System & Health Gauges
APP_HEALTH_STATUS = Gauge(
    "devops_app_health_status",
    "Application health status (1 = healthy, 0 = unhealthy).",
)
LLM_ENABLED_STATUS = Gauge(
    "devops_llm_enabled",
    "Whether local Ollama LLM specialist inference is enabled (1 = enabled, 0 = disabled).",
)

# 2. HTTP Request Metrics (bounded endpoint template, method, status)
HTTP_REQUESTS_TOTAL = Counter(
    "devops_http_requests_total",
    "Total HTTP requests handled by the FastAPI backend.",
    ["endpoint", "method", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "devops_http_request_duration_seconds",
    "HTTP request execution latency in seconds by bounded endpoint and method.",
    ["endpoint", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# 3. Six Specialist Agent Execution Metrics
AGENT_EXECUTIONS_TOTAL = Counter(
    "devops_agent_executions_total",
    "Total specialist AI agent executions by agent ID and bounded outcome.",
    ["agent", "outcome"],
)
AGENT_EXECUTION_DURATION_SECONDS = Histogram(
    "devops_agent_execution_duration_seconds",
    "Execution duration in seconds for each specialist AI agent.",
    ["agent"],
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# 4. Incident Creation, Diagnosis, and Status Metrics
INCIDENTS_CREATED_TOTAL = Counter(
    "devops_incidents_created_total",
    "Total incident investigations initiated.",
)
INCIDENT_DIAGNOSES_TOTAL = Counter(
    "devops_incident_diagnoses_total",
    "Total completed incident diagnoses grouped by proposed remediation action.",
    ["remediation_action"],
)
INCIDENTS_BY_STATUS_TOTAL = Counter(
    "devops_incidents_by_status_total",
    "Total incident lifecycle transitions by bounded status (pending_approval, completed, failed, rejected).",
    ["status"],
)
INCIDENTS_CURRENT_STATUS = Gauge(
    "devops_incidents_current_status",
    "Current count of incidents in each bounded lifecycle status.",
    ["status"],
)

# 5. Human Approval & Audit Metrics
HUMAN_DECISIONS_TOTAL = Counter(
    "devops_human_decisions_total",
    "Total explicit human approval and rejection decisions.",
    ["decision", "action"],
)
AUDIT_EVENTS_TOTAL = Counter(
    "devops_audit_events_total",
    "Total persisted audit log events by bounded event type.",
    ["event"],
)

# 6. LLM Runtime Inference Metrics
LLM_REQUESTS_TOTAL = Counter(
    "devops_llm_requests_total",
    "Total LLM inference calls by specialist agent, model, and bounded outcome status.",
    ["agent", "model", "status"],
)
LLM_REQUEST_DURATION_SECONDS = Histogram(
    "devops_llm_request_duration_seconds",
    "Wall-clock duration of Ollama LLM inference attempts in seconds.",
    ["agent", "model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# 7. Integration & Security Metrics
GITHUB_API_REQUESTS_TOTAL = Counter(
    "devops_github_api_requests_total",
    "Total GitHub REST API calls performed by the read-only integration.",
    ["endpoint", "status"],
)
INTEGRATION_STATUS = Gauge(
    "devops_integration_status",
    "Availability status of external integrations (1 = connected/active, 0 = disabled/error).",
    ["integration"],
)
SECURITY_FINDINGS_TOTAL = Gauge(
    "devops_security_findings_total",
    "Normalized security scanner findings count by severity and category.",
    ["severity", "category"],
)
CI_TEST_FAILURES_TOTAL = Gauge(
    "devops_ci_test_failures_total",
    "Number of failed tests reported in the latest CI pipeline run.",
    ["workflow"],
)


def _bound(value: str | None, allowlist: tuple[str, ...], fallback: str) -> str:
    if isinstance(value, str) and value in allowlist:
        return value
    return fallback


def bound_endpoint(path_template: str | None) -> str:
    return _bound(path_template, ALLOWED_HTTP_ENDPOINTS, "unmatched")


def bound_method(method: str | None) -> str:
    upper = method.upper() if isinstance(method, str) else ""
    return _bound(upper, ALLOWED_HTTP_METHODS, "OTHER")


def bound_http_status(status_code: int | str | None) -> str:
    code_str = str(status_code) if status_code is not None else "500"
    return _bound(code_str, ALLOWED_HTTP_STATUSES, "other")


def bound_agent(agent: str | None) -> str:
    return _bound(agent, ALLOWED_AGENTS, "unknown")


def bound_model(model: str | None, agent: str | None = None) -> str:
    if isinstance(model, str) and model in ALLOWED_MODELS:
        return model
    if isinstance(agent, str) and agent in AGENT_DEFAULT_MODELS:
        return AGENT_DEFAULT_MODELS[agent]
    return "unknown"


def record_http_request(
    endpoint: str | None,
    method: str | None,
    status_code: int | str | None,
    duration_seconds: float,
) -> None:
    safe_endpoint = bound_endpoint(endpoint)
    safe_method = bound_method(method)
    safe_status = bound_http_status(status_code)
    HTTP_REQUESTS_TOTAL.labels(
        endpoint=safe_endpoint,
        method=safe_method,
        status=safe_status,
    ).inc()
    if duration_seconds >= 0:
        HTTP_REQUEST_DURATION_SECONDS.labels(
            endpoint=safe_endpoint,
            method=safe_method,
        ).observe(duration_seconds)


def record_agent_execution(
    agent: str | None,
    outcome: str | None,
    duration_seconds: float | None = None,
) -> None:
    safe_agent = bound_agent(agent)
    safe_outcome = _bound(outcome, ALLOWED_AGENT_OUTCOMES, "error")
    AGENT_EXECUTIONS_TOTAL.labels(agent=safe_agent, outcome=safe_outcome).inc()
    if duration_seconds is not None and duration_seconds >= 0:
        AGENT_EXECUTION_DURATION_SECONDS.labels(agent=safe_agent).observe(
            duration_seconds
        )


def record_llm_call(
    agent: str | None,
    model: str | None,
    status: str | None,
    duration_seconds: float | None = None,
) -> None:
    safe_agent = bound_agent(agent)
    safe_model = bound_model(model, safe_agent)
    safe_status = _bound(status, ALLOWED_LLM_STATUSES, "failure")
    LLM_REQUESTS_TOTAL.labels(
        agent=safe_agent,
        model=safe_model,
        status=safe_status,
    ).inc()
    if duration_seconds is not None and duration_seconds >= 0:
        LLM_REQUEST_DURATION_SECONDS.labels(
            agent=safe_agent,
            model=safe_model,
        ).observe(duration_seconds)


def record_incident_created() -> None:
    INCIDENTS_CREATED_TOTAL.inc()


def record_incident_diagnosis(
    remediation_action: str | None,
    incident_status: str | None,
) -> None:
    safe_action = _bound(remediation_action, ALLOWED_REMEDIATION_ACTIONS, "none")
    INCIDENT_DIAGNOSES_TOTAL.labels(remediation_action=safe_action).inc()
    safe_status = _bound(incident_status, ALLOWED_INCIDENT_STATUSES, "completed")
    INCIDENTS_BY_STATUS_TOTAL.labels(status=safe_status).inc()
    INCIDENTS_CURRENT_STATUS.labels(status=safe_status).inc()


def record_incident_failed() -> None:
    INCIDENT_DIAGNOSES_TOTAL.labels(remediation_action="error").inc()
    INCIDENTS_BY_STATUS_TOTAL.labels(status="failed").inc()
    INCIDENTS_CURRENT_STATUS.labels(status="failed").inc()


def record_human_decision(
    decision: str | None,
    action: str | None,
    outcome_status: str | None,
) -> None:
    safe_decision = _bound(decision, ALLOWED_APPROVAL_DECISIONS, "reject")
    safe_action = (
        action if isinstance(action, str) and action in {"rollback", "none"} else "other"
    )
    HUMAN_DECISIONS_TOTAL.labels(decision=safe_decision, action=safe_action).inc()
    current_pending = INCIDENTS_CURRENT_STATUS.labels(status="pending_approval")._value.get()
    if current_pending > 0:
        INCIDENTS_CURRENT_STATUS.labels(status="pending_approval").dec()

    if safe_decision == "reject" or outcome_status == "rejected":
        INCIDENTS_BY_STATUS_TOTAL.labels(status="rejected").inc()
        INCIDENTS_CURRENT_STATUS.labels(status="rejected").inc()
    elif outcome_status == "failed":
        INCIDENTS_BY_STATUS_TOTAL.labels(status="failed").inc()
        INCIDENTS_CURRENT_STATUS.labels(status="failed").inc()
    else:
        INCIDENTS_BY_STATUS_TOTAL.labels(status="completed").inc()
        INCIDENTS_CURRENT_STATUS.labels(status="completed").inc()


def record_audit_event(event: str | None) -> None:
    safe_event = _bound(event, ALLOWED_AUDIT_EVENTS, "other")
    AUDIT_EVENTS_TOTAL.labels(event=safe_event).inc()


def record_github_api_request(endpoint: str, status: str) -> None:
    safe_endpoint = endpoint if endpoint in ("/actions/runs", "/actions/jobs", "/actions/artifacts", "/rate_limit", "/repo") else "other"
    safe_status = status if status in ("ok", "rate_limited", "unauthorized", "not_found", "api_error", "timeout", "connection_error", "error") else "other"
    GITHUB_API_REQUESTS_TOTAL.labels(endpoint=safe_endpoint, status=safe_status).inc()


def record_integration_status(integration: str, active: bool) -> None:
    safe_integration = integration if integration in ("github", "offline_ci", "offline_security") else "other"
    INTEGRATION_STATUS.labels(integration=safe_integration).set(1 if active else 0)


def record_security_findings_metrics(summary: dict[str, Any]) -> None:
    by_severity = summary.get("by_severity", {})
    by_category = summary.get("by_category", {})
    if isinstance(by_severity, dict):
        for sev, count in by_severity.items():
            if isinstance(count, (int, float)):
                SECURITY_FINDINGS_TOTAL.labels(severity=str(sev), category="all").set(count)
    if isinstance(by_category, dict):
        for cat, count in by_category.items():
            if isinstance(count, (int, float)):
                SECURITY_FINDINGS_TOTAL.labels(severity="all", category=str(cat)).set(count)


def record_ci_run_metrics(workflow_name: str, failed_count: int) -> None:
    safe_wf = workflow_name[:50] if workflow_name else "CI Pipeline"
    CI_TEST_FAILURES_TOTAL.labels(workflow=safe_wf).set(max(0, failed_count))


def reconstruct_incident_current_status(
    events: list[dict[str, Any]],
) -> dict[str, int]:
    """Reconstruct current incident counts by status from persisted audit events.

    Each unique incident_id is counted at most once in its latest established
    status. Historical transitions (e.g., pending_approval followed by rejected
    or succeeded) are not counted as current pending_approval incidents.
    If an incident has only incident_started (or approval_decision='approve'
    without action_finished), its current state cannot be reliably established
    from the audit log and is left indeterminate (None) rather than invented.
    """
    counts: dict[str, int] = {status: 0 for status in ALLOWED_INCIDENT_STATUSES}
    incident_states: dict[str, str | None] = {}

    for record in events:
        if not isinstance(record, dict):
            continue
        incident_id = record.get("incident_id")
        event_type = record.get("event")
        if not isinstance(incident_id, str) or not incident_id.strip():
            continue
        if event_type == "baseline_saved":
            continue

        if event_type == "incident_started":
            incident_states.setdefault(incident_id, None)
        elif event_type == "diagnosis_finished":
            diag_status = record.get("status")
            outcome_status = record.get("outcome_status")
            if outcome_status == "failed" or diag_status == "failed":
                incident_states[incident_id] = "failed"
            elif diag_status in ALLOWED_INCIDENT_STATUSES:
                incident_states[incident_id] = diag_status
            else:
                incident_states.setdefault(incident_id, None)
        elif event_type == "approval_decision":
            decision = record.get("decision")
            if decision == "reject":
                incident_states[incident_id] = "rejected"
            elif decision == "approve":
                incident_states[incident_id] = None
        elif event_type == "action_finished":
            decision = record.get("decision")
            outcome_status = record.get("outcome_status")
            if decision == "reject" or outcome_status == "rejected":
                incident_states[incident_id] = "rejected"
            elif outcome_status == "failed":
                incident_states[incident_id] = "failed"
            elif outcome_status in {"succeeded", "completed", "not_required"}:
                incident_states[incident_id] = "completed"
            else:
                incident_states[incident_id] = None

    for status in incident_states.values():
        if status in counts:
            counts[status] += 1
    return counts


def sync_incident_current_status_from_audit(
    audit_path: Path | str | None = None,
) -> dict[str, int]:
    """Read persisted audit JSONL and update INCIDENTS_CURRENT_STATUS gauges."""
    resolved = (
        Path(audit_path)
        if audit_path is not None
        else Path(os.getenv("DEVOPS_AUDIT_LOG_PATH", str(DEFAULT_AUDIT_LOG_PATH)))
    )
    events: list[dict[str, Any]] = []
    if resolved.exists():
        try:
            with resolved.open(encoding="utf-8") as stream:
                for line in stream:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        parsed = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        events.append(parsed)
        except OSError:
            events = []

    counts = reconstruct_incident_current_status(events)
    for status, count in counts.items():
        INCIDENTS_CURRENT_STATUS.labels(status=status).set(count)
    return counts


def initialize_metric_series(audit_path: Path | str | None = None) -> None:
    """Pre-initialize bounded label combinations and restore current status gauges."""
    APP_HEALTH_STATUS.set(1)
    LLM_ENABLED_STATUS.set(0)
    for agent, model in AGENT_DEFAULT_MODELS.items():
        for outcome in ALLOWED_AGENT_OUTCOMES:
            AGENT_EXECUTIONS_TOTAL.labels(agent=agent, outcome=outcome)
        AGENT_EXECUTION_DURATION_SECONDS.labels(agent=agent)
        for status in ALLOWED_LLM_STATUSES:
            LLM_REQUESTS_TOTAL.labels(agent=agent, model=model, status=status)
        LLM_REQUEST_DURATION_SECONDS.labels(agent=agent, model=model)
    for endpoint, method in (
        ("/calc/{op}", "GET"),
        ("/health", "GET"),
        ("/metrics", "GET"),
        ("/agents", "GET"),
        ("/baseline", "GET"),
        ("/baseline", "POST"),
        ("/incidents", "POST"),
        ("/incidents/{incident_id}", "GET"),
        ("/incidents/{incident_id}/approval", "POST"),
        ("/audit", "GET"),
        ("/integrations/status", "GET"),
        ("/ci/runs/latest", "GET"),
        ("/security/findings", "GET"),
        ("unmatched", "GET"),
    ):
        HTTP_REQUEST_DURATION_SECONDS.labels(endpoint=endpoint, method=method)
        for status_code in ("200", "400", "404", "409", "422", "500"):
            HTTP_REQUESTS_TOTAL.labels(
                endpoint=endpoint, method=method, status=status_code
            )
    for integration in ("github", "offline_ci", "offline_security"):
        INTEGRATION_STATUS.labels(integration=integration).set(0)
    for status in ALLOWED_INCIDENT_STATUSES:
        INCIDENTS_BY_STATUS_TOTAL.labels(status=status)
    for action in ALLOWED_REMEDIATION_ACTIONS:
        INCIDENT_DIAGNOSES_TOTAL.labels(remediation_action=action)
    for decision in ALLOWED_APPROVAL_DECISIONS:
        HUMAN_DECISIONS_TOTAL.labels(decision=decision, action="rollback")
    for event in ALLOWED_AUDIT_EVENTS:
        AUDIT_EVENTS_TOTAL.labels(event=event)
    sync_incident_current_status_from_audit(audit_path)


initialize_metric_series()
