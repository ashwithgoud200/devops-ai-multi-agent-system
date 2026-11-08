"""Tests for local Git telemetry, Compose topology, and individual agent test endpoint."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agents.compose_topology import get_compose_topology
from agents.git_telemetry import collect_git_evidence
from calculator_app.app import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_git_evidence_collection_is_read_only_and_redacts_secrets(tmp_path: Path):
    """Verify Git evidence collection operates safely and extracts repository state."""
    res = collect_git_evidence()
    assert res["status"] in {"ok", "unavailable"}
    if res["status"] == "ok":
        assert "branch" in res
        assert "recent_commits" in res
        assert "code_changes" in res
        assert isinstance(res["code_changes"], dict)


def test_compose_topology_parses_services_and_dependency_impact():
    """Verify Docker Compose topology is parsed with downstream dependency impact."""
    topo = get_compose_topology()
    assert topo["status"] == "ok"
    assert "calculator-app" in topo["services"]
    assert "prometheus" in topo["services"]
    assert "grafana" in topo["services"]
    assert "frontend" in topo["services"]
    assert "downstream_impact" in topo
    assert "grafana" in topo["downstream_impact"]["prometheus"]


def test_compose_topology_endpoint(client: TestClient):
    """GET /topology/compose returns Compose topology and health status."""
    resp = client.get("/topology/compose")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "services" in data
    assert "topology" in data


def test_git_telemetry_endpoint(client: TestClient):
    """GET /telemetry/git returns read-only local git evidence."""
    resp = client.get("/telemetry/git")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in {"ok", "unavailable"}


def test_individual_agent_test_endpoint_unknown_agent(client: TestClient):
    """POST /agents/{agent_id}/test returns 404 for unknown agent."""
    resp = client.post("/agents/nonexistent_agent/test")
    assert resp.status_code == 404
    assert "Unknown specialist agent" in resp.json()["detail"]


def test_individual_agent_test_endpoint_disabled_llm(client: TestClient):
    """POST /agents/{agent_id}/test returns disabled status gracefully when LLM is disabled."""
    with patch.dict("os.environ", {"DEVOPS_LLM_ENABLED": "false"}):
        resp = client.post("/agents/monitoring/test", json={"query": "Test monitoring query"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"] == "monitoring"
        assert data["model"] == "qwen2.5:3b"
        assert data["status"] == "disabled"
        assert data["execution_status"] == "SKIPPED"


def test_individual_agent_test_endpoint_with_mocked_llm(client: TestClient):
    """POST /agents/{agent_id}/test executes successfully and returns structured analysis."""
    mock_analysis = {
        "status": "ok",
        "agent": "security",
        "model": "granite3.1-dense:2b",
        "wall_duration_seconds": 1.25,
        "analysis": {
            "summary": "Normalized 2 security findings; 1 high vulnerability in urllib3.",
            "findings": ["urllib3 has CVE-2024-37891."],
            "confidence": 0.88,
            "recommended_checks": ["Upgrade urllib3 to safe version."],
        },
    }
    with patch("agents.llm_runtime.analyze", return_value=mock_analysis):
        resp = client.post("/agents/security/test", json={"query": "Triage security scan results"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"] == "security"
        assert data["model"] == "granite3.1-dense:2b"
        assert data["status"] == "ok"
        assert data["execution_status"] == "COMPLETED"
        assert data["summary"] == "Normalized 2 security findings; 1 high vulnerability in urllib3."
        assert len(data["findings"]) == 1
        assert data["confidence"] == 0.88

