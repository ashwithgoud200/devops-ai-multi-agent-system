import copy
import json

import pytest
from fastapi.testclient import TestClient

from agents import graph
from agents import incident_api
from calculator_app.app import app


def _snapshots():
    current = {
        "captured_at": 300,
        "health": {
            "status": "ok",
            "data": {"status": "ok", "version": "1.1"},
            "timestamp": 300,
        },
        "metrics": {
            "status": "ok",
            "request_counters": {"status": "ok"},
            "requests": {"div": {"ok": 60, "error": 4}},
            "request_totals": {"div": 64},
            "latency_observations": {
                "status": "ok",
                "by_operation": {"div": 0.2},
            },
            "timestamp": 300,
        },
        "system_metrics": {
            "status": "unavailable",
            "measurements": {},
            "timestamp": 300,
            "detail": "Not configured in this synthetic test.",
        },
        "docker": {
            "status": "unavailable",
            "containers": [],
            "timestamp": 300,
            "detail": "Docker unavailable in this synthetic test.",
        },
        "prometheus": {
            "status": "unavailable",
            "metrics": {},
            "timestamp": 300,
            "detail": "Prometheus unavailable in this synthetic test.",
        },
        "version": {
            "status": "ok",
            "data": {
                "version": "1.1",
                "history": [
                    {"version": "1.0", "ts": 100},
                    {"version": "1.1", "ts": 200},
                ],
            },
            "timestamp": 300,
        },
        "logs": {
            "status": "ok",
            "events": [{
                "ts": 250,
                "level": "ERROR",
                "msg": "v1.1 division handler crashed",
            }],
            "timestamp": 300,
        },
    }
    baseline = copy.deepcopy(current)
    baseline.update({
        "captured_at": 100,
        "health": {
            "status": "ok",
            "data": {"status": "ok", "version": "1.0"},
            "timestamp": 100,
        },
        "metrics": {
            "status": "ok",
            "request_counters": {"status": "ok"},
            "requests": {"div": {"ok": 60, "error": 0}},
            "request_totals": {"div": 60},
            "latency_observations": {
                "status": "ok",
                "by_operation": {"div": 0.01},
            },
            "timestamp": 100,
        },
        "version": {
            "status": "ok",
            "data": {
                "version": "1.0",
                "history": [{"version": "1.0", "ts": 100}],
            },
            "timestamp": 100,
        },
        "logs": {"status": "ok", "events": [], "timestamp": 100},
    })
    return current, baseline


@pytest.fixture
def incident_client(monkeypatch, tmp_path):
    current, baseline = _snapshots()
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "false")
    monkeypatch.setenv("DEVOPS_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(incident_api, "_WORKFLOW", graph.build())
    monkeypatch.setattr(graph, "_load_baseline", lambda: {
        "status": "ok",
        "snapshot": baseline,
    })
    monkeypatch.setattr(graph, "_collect_evidence", lambda *args: current)
    with TestClient(app) as client:
        yield client


def test_synthetic_incident_requires_human_decision_and_persists_audit(
    incident_client,
):
    started = incident_client.post(
        "/incidents",
        json={"query": "Calculator errors increased after deployment"},
    )

    assert started.status_code == 200
    result = started.json()
    assert result["status"] == "pending_approval"
    assert result["baseline_comparison"]["regression_signal"] is True
    assert result["diagnosis"]["verified_observations"]
    assert result["proposed_remediation"]["action"] == "rollback"
    assert result["approval_request"]["action"] == "rollback"

    details = incident_client.get(f"/incidents/{result['incident_id']}")
    assert details.status_code == 200
    assert details.json()["status"] == "pending_approval"
    assert details.json()["evidence"]["docker"]["status"] == "unavailable"

    rejected = incident_client.post(
        f"/incidents/{result['incident_id']}/approval",
        json={"decision": "reject", "reviewed_by": "local operator"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["outcome"]["status"] == "rejected"

    audit = incident_client.get(f"/incidents/{result['incident_id']}/audit")
    assert audit.status_code == 200
    assert [event["event"] for event in audit.json()["events"]] == [
        "incident_started",
        "diagnosis_finished",
        "approval_decision",
        "action_finished",
    ]
    assert audit.json()["events"][2]["reviewed_by"] == "local operator"
    assert audit.json()["events"][2]["decision"] == "reject"


def test_approved_action_executes_only_after_explicit_decision(
    incident_client, monkeypatch,
):
    rollback_calls = []
    monkeypatch.setattr(
        graph,
        "_rollback",
        lambda: rollback_calls.append(True) or {
            "status": "ok",
            "data": {"rolled_back_to": "1.0"},
        },
    )
    monkeypatch.setattr(
        graph,
        "_get_json",
        lambda path: {
            "status": "ok",
            "data": {"status": "ok", "version": "1.0"},
        } if path == "/health" else {"status": "unavailable"},
    )

    started = incident_client.post(
        "/incidents",
        json={"query": "Investigate calculator errors after deployment"},
    ).json()
    assert rollback_calls == []

    approved = incident_client.post(
        f"/incidents/{started['incident_id']}/approval",
        json={"decision": "approve", "reviewed_by": "release operator"},
    )

    assert approved.status_code == 200
    assert approved.json()["outcome"]["status"] == "succeeded"
    assert rollback_calls == [True]
    audit = incident_client.get(
        f"/incidents/{started['incident_id']}/audit"
    ).json()["events"]
    assert audit[-2]["decision"] == "approve"
    assert audit[-1]["outcome_status"] == "succeeded"


def test_incident_api_rejects_approval_without_pending_action(incident_client):
    pending = incident_client.post(
        "/incidents",
        json={"query": "Check current calculator health"},
    ).json()
    rejected = incident_client.post(
        f"/incidents/{pending['incident_id']}/approval",
        json={"decision": "reject", "reviewed_by": "operator"},
    )
    assert rejected.status_code == 200

    response = incident_client.post(
        f"/incidents/{pending['incident_id']}/approval",
        json={"decision": "approve", "reviewed_by": "operator"},
    )

    assert response.status_code == 409


def test_incident_api_validates_nonblank_query_and_reviewer(incident_client):
    blank_query = incident_client.post("/incidents", json={"query": "   "})
    assert blank_query.status_code == 422

    started = incident_client.post(
        "/incidents",
        json={"query": "Check calculator deployment errors"},
    ).json()
    blank_reviewer = incident_client.post(
        f"/incidents/{started['incident_id']}/approval",
        json={"decision": "reject", "reviewed_by": "   "},
    )
    assert blank_reviewer.status_code == 422
    assert incident_client.get("/openapi.json").status_code == 200


def test_audit_file_contains_only_workflow_metadata(incident_client, tmp_path):
    incident = incident_client.post(
        "/incidents",
        json={"query": "Check calculator deployment errors"},
    ).json()
    audit_path = tmp_path / "audit.jsonl"
    audit_events = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]

    assert all("query" not in event for event in audit_events)
    assert all(event["incident_id"] == incident["incident_id"] for event in audit_events)


def test_global_audit_endpoint_lists_metadata_for_all_incidents(incident_client):
    first = incident_client.post(
        "/incidents",
        json={"query": "Check calculator deployment errors"},
    ).json()
    second = incident_client.post(
        "/incidents",
        json={"query": "Investigate current calculator health"},
    ).json()

    response = incident_client.get("/audit")

    assert response.status_code == 200
    events = response.json()["events"]
    incident_ids = {event["incident_id"] for event in events}
    assert {first["incident_id"], second["incident_id"]} <= incident_ids
    assert all("query" not in event for event in events)


def test_agents_endpoint_reads_existing_model_assignments(incident_client):
    response = incident_client.get("/agents")

    assert response.status_code == 200
    result = response.json()
    assert result["enabled"] is False
    assert {
        agent["id"]: agent["model"]
        for agent in result["agents"]
    } == {
        "monitoring": "qwen2.5:3b",
        "incident": "llama3.2:3b",
        "code": "qwen2.5-coder:3b",
        "cicd": "stablelm-zephyr:3b",
        "infrastructure": "phi3.5:3.8b",
        "security": "granite3.1-dense:2b",
    }
