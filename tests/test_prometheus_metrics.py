"""Tests for Stage 5 Prometheus metric registration, updates, failure paths, and bounded labels."""
from __future__ import annotations

import copy
import json

import pytest
import requests
from fastapi.testclient import TestClient

from agents import graph, incident_api, llm_runtime
from agents import metrics as app_metrics
from calculator_app.app import app


def _counter_value(counter, **labels) -> float:
    if labels:
        return float(counter.labels(**labels)._value.get())
    return float(counter._value.get())


def _gauge_value(gauge, **labels) -> float:
    if labels:
        return float(gauge.labels(**labels)._value.get())
    return float(gauge._value.get())


def _histogram_count(histogram, **labels) -> float:
    return float(histogram.labels(**labels)._sum.get())


def test_all_required_prometheus_metric_families_are_registered_and_exposed():
    with TestClient(app) as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text

    expected_families = (
        "calc_requests_total",
        "calc_latency_seconds",
        "devops_app_health_status",
        "devops_llm_enabled",
        "devops_http_requests_total",
        "devops_http_request_duration_seconds",
        "devops_agent_executions_total",
        "devops_agent_execution_duration_seconds",
        "devops_incidents_created_total",
        "devops_incident_diagnoses_total",
        "devops_incidents_by_status_total",
        "devops_incidents_current_status",
        "devops_human_decisions_total",
        "devops_audit_events_total",
        "devops_llm_requests_total",
        "devops_llm_request_duration_seconds",
    )
    for family in expected_families:
        assert f"# TYPE {family} " in text, f"Missing Prometheus metric family: {family}"


def test_metrics_enforce_bounded_labels_and_reject_sensitive_or_dynamic_values():
    secret_incident_id = "inc-99999999-secret-uuid"
    raw_prompt = "Investigate password=super-secret-value stacktrace line 42"
    dynamic_path = f"/incidents/{secret_incident_id}"
    arbitrary_exception = "RuntimeError: database connection failed at host 10.0.0.99"

    app_metrics.record_http_request(
        endpoint=dynamic_path,
        method="invalid_method_xyz",
        status_code="999_custom",
        duration_seconds=0.05,
    )
    app_metrics.record_agent_execution(
        agent=raw_prompt,
        outcome=arbitrary_exception,
        duration_seconds=0.12,
    )
    app_metrics.record_llm_call(
        agent=secret_incident_id,
        model="untrusted-custom-model:99b",
        status=arbitrary_exception,
        duration_seconds=0.25,
    )
    app_metrics.record_incident_diagnosis(
        remediation_action=raw_prompt,
        incident_status=secret_incident_id,
    )
    app_metrics.record_human_decision(
        decision=raw_prompt,
        action=secret_incident_id,
        outcome_status=arbitrary_exception,
    )
    app_metrics.record_audit_event(event=secret_incident_id)

    with TestClient(app) as client:
        # Also trigger an HTTP 404 on an arbitrary URL path and an incident ID path
        client.get(f"/incidents/{secret_incident_id}")
        client.get("/arbitrary-unmatched-path/with-secret-token-12345")
        exposition = client.get("/metrics").text

    for forbidden in (
        secret_incident_id,
        "super-secret-value",
        "invalid_method_xyz",
        "999_custom",
        "untrusted-custom-model",
        "10.0.0.99",
        "arbitrary-unmatched-path",
        "with-secret-token-12345",
    ):
        assert forbidden not in exposition

    # Verify the parameterized route template and unmatched fallback were recorded instead
    assert 'devops_http_requests_total{endpoint="/incidents/{incident_id}",method="GET",status="404"}' in exposition
    assert 'devops_http_requests_total{endpoint="unmatched",method="GET",status="404"}' in exposition


def test_llm_metrics_track_disabled_unavailable_timeout_failure_and_success(monkeypatch):
    # 1. Disabled mode
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "false")
    before_disabled = _counter_value(
        app_metrics.LLM_REQUESTS_TOTAL,
        agent="monitoring",
        model="qwen2.5:3b",
        status="disabled",
    )
    res_disabled = llm_runtime.analyze("monitoring", "check metrics", {})
    assert res_disabled["status"] == "disabled"
    assert _gauge_value(app_metrics.LLM_ENABLED_STATUS) == 0.0
    assert (
        _counter_value(
            app_metrics.LLM_REQUESTS_TOTAL,
            agent="monitoring",
            model="qwen2.5:3b",
            status="disabled",
        )
        == before_disabled + 1
    )

    # 2. Ollama unavailable (ConnectionError)
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    before_unavail = _counter_value(
        app_metrics.LLM_REQUESTS_TOTAL,
        agent="code",
        model="qwen2.5-coder:3b",
        status="unavailable",
    )
    monkeypatch.setattr(
        llm_runtime.requests,
        "post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("connection refused")),
    )
    res_unavail = llm_runtime.analyze("code", "review diff", {})
    assert res_unavail["status"] == "unavailable"
    assert _gauge_value(app_metrics.LLM_ENABLED_STATUS) == 1.0
    assert (
        _counter_value(
            app_metrics.LLM_REQUESTS_TOTAL,
            agent="code",
            model="qwen2.5-coder:3b",
            status="unavailable",
        )
        == before_unavail + 1
    )

    # 3. Ollama timeout (Timeout)
    before_timeout = _counter_value(
        app_metrics.LLM_REQUESTS_TOTAL,
        agent="incident",
        model="llama3.2:3b",
        status="timeout",
    )
    monkeypatch.setattr(
        llm_runtime.requests,
        "post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.ReadTimeout("read timed out")),
    )
    res_timeout = llm_runtime.analyze("incident", "build timeline", {})
    assert res_timeout["status"] == "timeout"
    assert res_timeout["attempts"][0]["inference_status"] == "timeout"
    assert res_timeout["retry"]["status"] == "timeout"
    assert (
        _counter_value(
            app_metrics.LLM_REQUESTS_TOTAL,
            agent="incident",
            model="llama3.2:3b",
            status="timeout",
        )
        == before_timeout + 1
    )

    # 4. Invalid response (2 failed attempts -> +2 failure counts)
    before_failure = _counter_value(
        app_metrics.LLM_REQUESTS_TOTAL,
        agent="security",
        model="granite3.1-dense:2b",
        status="failure",
    )

    class _BadResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "{malformed"}, "done_reason": "stop"}

    monkeypatch.setattr(llm_runtime.requests, "post", lambda *a, **kw: _BadResponse())
    res_invalid = llm_runtime.analyze("security", "check logs", {})
    assert res_invalid["status"] == "invalid_response"
    assert (
        _counter_value(
            app_metrics.LLM_REQUESTS_TOTAL,
            agent="security",
            model="granite3.1-dense:2b",
            status="failure",
        )
        == before_failure + 2
    )

    # 5. Successful response
    before_success = _counter_value(
        app_metrics.LLM_REQUESTS_TOTAL,
        agent="cicd",
        model="stablelm-zephyr:3b",
        status="success",
    )

    class _GoodResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": json.dumps({
                        "summary": "Deployment verified.",
                        "findings": ["Health check is ok."],
                        "confidence": 0.8,
                        "recommended_checks": ["Continue monitoring."],
                    })
                },
                "done_reason": "stop",
            }

    monkeypatch.setattr(llm_runtime.requests, "post", lambda *a, **kw: _GoodResponse())
    res_ok = llm_runtime.analyze("cicd", "check deploy", {})
    assert res_ok["status"] == "ok"
    assert (
        _counter_value(
            app_metrics.LLM_REQUESTS_TOTAL,
            agent="cicd",
            model="stablelm-zephyr:3b",
            status="success",
        )
        == before_success + 1
    )


def test_agent_and_incident_metrics_across_pending_approval_rejection_and_agent_failure(
    monkeypatch, tmp_path
):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "test_incident_api_local", Path(__file__).parent / "test_incident_api.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    current, baseline = mod._snapshots()
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "false")
    monkeypatch.setenv("DEVOPS_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(incident_api, "_WORKFLOW", graph.build())
    monkeypatch.setattr(
        graph, "_load_baseline", lambda: {"status": "ok", "snapshot": baseline}
    )
    monkeypatch.setattr(graph, "_collect_evidence", lambda *args: copy.deepcopy(current))

    # Simulate one agent raising an unexpected exception while others return disabled
    def fake_analyze(agent, task, evidence):
        if agent == "monitoring":
            raise RuntimeError("simulated specialist crash")
        return {"status": "disabled", "agent": agent, "model": "test"}

    monkeypatch.setattr(graph.llm_runtime, "analyze", fake_analyze)

    before_created = _counter_value(app_metrics.INCIDENTS_CREATED_TOTAL)
    before_pending_total = _counter_value(
        app_metrics.INCIDENTS_BY_STATUS_TOTAL, status="pending_approval"
    )
    before_pending_gauge = _gauge_value(
        app_metrics.INCIDENTS_CURRENT_STATUS, status="pending_approval"
    )
    before_rejected_total = _counter_value(
        app_metrics.INCIDENTS_BY_STATUS_TOTAL, status="rejected"
    )
    before_reject_decisions = _counter_value(
        app_metrics.HUMAN_DECISIONS_TOTAL, decision="reject", action="rollback"
    )
    before_mon_err = _counter_value(
        app_metrics.AGENT_EXECUTIONS_TOTAL, agent="monitoring", outcome="error"
    )

    with TestClient(app) as client:
        started = client.post(
            "/incidents",
            json={"query": "Calculator errors increased after deployment"},
        )
        assert started.status_code == 200
        incident_id = started.json()["incident_id"]

        assert _counter_value(app_metrics.INCIDENTS_CREATED_TOTAL) == before_created + 1
        assert (
            _counter_value(
                app_metrics.INCIDENTS_BY_STATUS_TOTAL, status="pending_approval"
            )
            == before_pending_total + 1
        )
        assert (
            _gauge_value(
                app_metrics.INCIDENTS_CURRENT_STATUS, status="pending_approval"
            )
            == before_pending_gauge + 1
        )
        assert (
            _counter_value(
                app_metrics.AGENT_EXECUTIONS_TOTAL, agent="monitoring", outcome="error"
            )
            == before_mon_err + 1
        )

        rejected = client.post(
            f"/incidents/{incident_id}/approval",
            json={"decision": "reject", "reviewed_by": "qa-reviewer"},
        )
        assert rejected.status_code == 200

        assert (
            _gauge_value(
                app_metrics.INCIDENTS_CURRENT_STATUS, status="pending_approval"
            )
            == before_pending_gauge
        )
        assert (
            _counter_value(
                app_metrics.HUMAN_DECISIONS_TOTAL, decision="reject", action="rollback"
            )
            == before_reject_decisions + 1
        )
        assert (
            _counter_value(app_metrics.INCIDENTS_BY_STATUS_TOTAL, status="rejected")
            == before_rejected_total + 1
        )


def test_agent_timeout_and_configuration_error_propagated_to_agent_execution_metrics(
    monkeypatch,
):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    monkeypatch.setattr(
        graph, "_select_specialists", lambda state: state["selected_agents"]
    )

    # 1. Timeout in Ollama propagates status="timeout" to devops_agent_executions_total
    monkeypatch.setattr(
        llm_runtime.requests,
        "post",
        lambda *a, **kw: (_ for _ in ()).throw(requests.ReadTimeout("ollama timed out")),
    )
    before_agent_timeout = _counter_value(
        app_metrics.AGENT_EXECUTIONS_TOTAL, agent="monitoring", outcome="timeout"
    )
    before_llm_timeout = _counter_value(
        app_metrics.LLM_REQUESTS_TOTAL,
        agent="monitoring",
        model="qwen2.5:3b",
        status="timeout",
    )
    state = {
        "selected_agents": ["monitoring"],
        "evidence": {"metrics": {"status": "ok"}},
        "comparison": {},
        "trace": [],
    }
    out = graph._specialists_node(state)
    assert out["specialists"]["results"]["monitoring"]["status"] == "timeout"
    assert (
        _counter_value(
            app_metrics.LLM_REQUESTS_TOTAL,
            agent="monitoring",
            model="qwen2.5:3b",
            status="timeout",
        )
        == before_llm_timeout + 1
    )
    assert (
        _counter_value(
            app_metrics.AGENT_EXECUTIONS_TOTAL, agent="monitoring", outcome="timeout"
        )
        == before_agent_timeout + 1
    )

    # 2. Configuration error propagates status="configuration_error"
    monkeypatch.setattr(
        llm_runtime, "load_config", lambda: {"enabled": True, "agents": {}}
    )
    before_agent_cfg_err = _counter_value(
        app_metrics.AGENT_EXECUTIONS_TOTAL,
        agent="security",
        outcome="configuration_error",
    )
    before_llm_cfg_err = _counter_value(
        app_metrics.LLM_REQUESTS_TOTAL,
        agent="security",
        model="granite3.1-dense:2b",
        status="configuration_error",
    )
    state_cfg = {
        "selected_agents": ["security"],
        "evidence": {"logs": {"events": []}},
        "comparison": {},
        "trace": [],
    }
    out_cfg = graph._specialists_node(state_cfg)
    assert out_cfg["specialists"]["results"]["security"]["status"] == "configuration_error"
    assert (
        _counter_value(
            app_metrics.LLM_REQUESTS_TOTAL,
            agent="security",
            model="granite3.1-dense:2b",
            status="configuration_error",
        )
        == before_llm_cfg_err + 1
    )
    assert (
        _counter_value(
            app_metrics.AGENT_EXECUTIONS_TOTAL,
            agent="security",
            outcome="configuration_error",
        )
        == before_agent_cfg_err + 1
    )


def test_incident_current_status_reconstructed_from_audit_after_restart_without_duplicate_counting(
    tmp_path,
):
    audit_file = tmp_path / "incident_audit.jsonl"
    events = [
        {"ts": "2026-11-02T00:00:00Z", "event": "baseline_saved", "incident_id": "baseline"},
        # Incident 1: pending_approval -> reject -> action_finished(rejected) => current: rejected
        {"ts": "2026-11-02T00:01:00Z", "event": "incident_started", "incident_id": "inc-1"},
        {
            "ts": "2026-11-02T00:01:01Z",
            "event": "diagnosis_finished",
            "incident_id": "inc-1",
            "status": "pending_approval",
            "remediation_action": "rollback",
        },
        {
            "ts": "2026-11-02T00:01:02Z",
            "event": "approval_decision",
            "incident_id": "inc-1",
            "decision": "reject",
        },
        {
            "ts": "2026-11-02T00:01:03Z",
            "event": "action_finished",
            "incident_id": "inc-1",
            "decision": "reject",
            "outcome_status": "rejected",
        },
        # Incident 2: pending_approval -> approve -> action_finished(succeeded) => current: completed
        {"ts": "2026-11-02T00:02:00Z", "event": "incident_started", "incident_id": "inc-2"},
        {
            "ts": "2026-11-02T00:02:01Z",
            "event": "diagnosis_finished",
            "incident_id": "inc-2",
            "status": "pending_approval",
            "remediation_action": "rollback",
        },
        {
            "ts": "2026-11-02T00:02:02Z",
            "event": "approval_decision",
            "incident_id": "inc-2",
            "decision": "approve",
        },
        {
            "ts": "2026-11-02T00:02:03Z",
            "event": "action_finished",
            "incident_id": "inc-2",
            "decision": "approve",
            "outcome_status": "succeeded",
        },
        # Incident 3: diagnosis_finished(completed) => current: completed
        {"ts": "2026-11-02T00:03:00Z", "event": "incident_started", "incident_id": "inc-3"},
        {
            "ts": "2026-11-02T00:03:01Z",
            "event": "diagnosis_finished",
            "incident_id": "inc-3",
            "status": "completed",
            "remediation_action": "investigate",
        },
        # Incident 4: pending_approval -> approve -> action_finished(failed) => current: failed
        {"ts": "2026-11-02T00:04:00Z", "event": "incident_started", "incident_id": "inc-4"},
        {
            "ts": "2026-11-02T00:04:01Z",
            "event": "diagnosis_finished",
            "incident_id": "inc-4",
            "status": "pending_approval",
            "remediation_action": "rollback",
        },
        {
            "ts": "2026-11-02T00:04:02Z",
            "event": "approval_decision",
            "incident_id": "inc-4",
            "decision": "approve",
        },
        {
            "ts": "2026-11-02T00:04:03Z",
            "event": "action_finished",
            "incident_id": "inc-4",
            "decision": "approve",
            "outcome_status": "failed",
        },
        # Incident 5: diagnosis_finished(pending_approval) with no decision yet => current: pending_approval
        {"ts": "2026-11-02T00:05:00Z", "event": "incident_started", "incident_id": "inc-5"},
        {
            "ts": "2026-11-02T00:05:01Z",
            "event": "diagnosis_finished",
            "incident_id": "inc-5",
            "status": "pending_approval",
            "remediation_action": "rollback",
        },
        # Incident 6: only incident_started (indeterminate, must NOT be invented)
        {"ts": "2026-11-02T00:06:00Z", "event": "incident_started", "incident_id": "inc-6"},
        # Incident 7: approval_decision=approve without action_finished (indeterminate, must NOT stay pending_approval)
        {"ts": "2026-11-02T00:07:00Z", "event": "incident_started", "incident_id": "inc-7"},
        {
            "ts": "2026-11-02T00:07:01Z",
            "event": "diagnosis_finished",
            "incident_id": "inc-7",
            "status": "pending_approval",
            "remediation_action": "rollback",
        },
        {
            "ts": "2026-11-02T00:07:02Z",
            "event": "approval_decision",
            "incident_id": "inc-7",
            "decision": "approve",
        },
    ]
    audit_file.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )

    try:
        app_metrics.initialize_metric_series(audit_file)
        assert _gauge_value(
            app_metrics.INCIDENTS_CURRENT_STATUS, status="pending_approval"
        ) == 1.0
        assert _gauge_value(
            app_metrics.INCIDENTS_CURRENT_STATUS, status="completed"
        ) == 2.0
        assert _gauge_value(
            app_metrics.INCIDENTS_CURRENT_STATUS, status="failed"
        ) == 1.0
        assert _gauge_value(
            app_metrics.INCIDENTS_CURRENT_STATUS, status="rejected"
        ) == 1.0
    finally:
        app_metrics.sync_incident_current_status_from_audit()


def test_all_bounded_metric_series_are_pre_initialized_at_startup():
    with TestClient(app) as client:
        exposition = client.get("/metrics").text

    for agent, model in app_metrics.AGENT_DEFAULT_MODELS.items():
        for outcome in app_metrics.ALLOWED_AGENT_OUTCOMES:
            assert (
                f'devops_agent_executions_total{{agent="{agent}",outcome="{outcome}"}}'
                in exposition
            )
        for status in app_metrics.ALLOWED_LLM_STATUSES:
            assert (
                f'devops_llm_requests_total{{agent="{agent}",model="{model}",status="{status}"}}'
                in exposition
            )

    for status in app_metrics.ALLOWED_INCIDENT_STATUSES:
        assert f'devops_incidents_by_status_total{{status="{status}"}}' in exposition
        assert f'devops_incidents_current_status{{status="{status}"}}' in exposition

    for status_code in ("200", "400", "404", "409", "422", "500"):
        assert (
            f'devops_http_requests_total{{endpoint="/incidents",method="POST",status="{status_code}"}}'
            in exposition
        )
