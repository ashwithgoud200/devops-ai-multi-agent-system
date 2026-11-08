"""Automated tests for specialist agent evidence provenance, quality separation,
fixture vs live discrimination, non-empty findings, and measurement validity.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agents import ci_security_normalizer, compose_topology, graph, incident_api, runtime_evidence
from calculator_app.app import app

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def test_monitoring_provenance_and_measurement_tagging():
    """Verify monitoring evidence includes explicit provenance and valid measurements."""
    default_ev = incident_api._default_test_evidence("monitoring")
    assert default_ev.get("provenance") == "synthetic_fixture"
    metrics = default_ev.get("metrics", {})
    assert metrics.get("status") == "ok"
    assert metrics.get("provenance") == "synthetic_fixture"
    sys_metrics = metrics.get("system_metrics", {})
    assert sys_metrics.get("cpu_percent") == 68.5
    assert sys_metrics.get("memory_used_bytes") == 128000000
    assert "source" in sys_metrics
    assert sys_metrics.get("provenance") == "synthetic_fixture"
    assert "unavailable" in default_ev


def test_incident_agent_prevents_empty_findings_and_zero_confidence():
    """Verify incident agent never returns an empty successful analysis."""
    # When given empty findings, test_individual_agent must enforce INSUFFICIENT_EVIDENCE
    resp = client.post(
        "/agents/incident/test",
        json={"query": "Triage incident with missing telemetry", "evidence": {"version": {"status": "unavailable"}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent"] == "incident"
    assert data["execution_status"] in {"COMPLETED", "FAILED", "SKIPPED"}
    # Findings must never be empty
    assert len(data["findings"]) > 0
    assert any("INSUFFICIENT_EVIDENCE:" in f or "insufficient" in f.lower() for f in data["findings"])
    assert data["analysis_quality"] == "insufficient_evidence"
    assert len(data["recommended_checks"]) > 0
    assert data["confidence"] > 0.0


def test_code_agent_includes_diff_and_observed_failure():
    """Verify code evidence provides supporting error context alongside code diff."""
    default_ev = incident_api._default_test_evidence("code")
    code = default_ev.get("code_changes", {})
    assert code.get("status") == "ok"
    assert code.get("provenance") == "synthetic_fixture"
    assert "calculator_app/app.py" in code.get("modified_files", [])
    assert "diff" in code
    assert "observed_failure" in code
    assert "stack_trace" in code


def test_cicd_agent_fixture_provenance_and_report_identity():
    """Verify CI/CD pipeline results identify report file, identity, and fixture provenance."""
    default_ev = incident_api._default_test_evidence("cicd")
    pipeline = default_ev.get("ci_pipeline", {})
    assert pipeline.get("provenance") == "seeded_offline_fixture"
    assert pipeline.get("report_file") == "ci-summary.json"
    assert pipeline.get("report_identity") == "fixture:ci-summary.json"
    assert pipeline.get("conclusion") == "failure"
    assert pipeline.get("test_summary", {}).get("total") == 245
    assert pipeline.get("test_summary", {}).get("passed") == 244
    assert pipeline.get("test_summary", {}).get("failed") == 1


def test_infrastructure_enumerates_all_compose_services():
    """Verify infrastructure analysis enumerates all 4 configured Compose services and marks uncollected metrics."""
    default_ev = incident_api._default_test_evidence("infrastructure")
    docker = default_ev.get("docker", {})
    assert docker.get("provenance") == "synthetic_fixture"
    configured = docker.get("configured_services", [])
    assert set(configured) == {"calculator-app", "prometheus", "grafana", "frontend"}

    containers = docker.get("containers", [])
    assert len(containers) == 4
    services_in_containers = {c.get("service") for c in containers}
    assert services_in_containers == {"calculator-app", "prometheus", "grafana", "frontend"}

    # Services without live container stats must be marked unavailable
    grafana_c = next(c for c in containers if c.get("service") == "grafana")
    assert grafana_c.get("metrics_status") == "unavailable"
    assert grafana_c.get("cpu_percent") is None

    # Compose topology module verification
    topo = compose_topology.get_compose_topology()
    assert topo.get("status") == "ok"
    assert set(topo.get("configured_services", [])) == {"calculator-app", "prometheus", "grafana", "frontend"}


def test_security_retains_scanner_origin_and_verification_status():
    """Verify security findings retain scanner, report_origin, CVE/rule ID, and verification_status."""
    default_ev = incident_api._default_test_evidence("security")
    sec_scans = default_ev.get("security_scans", {})
    assert sec_scans.get("provenance") == "seeded_offline_fixture"
    assert sec_scans.get("report_origin") == "seeded_offline_fixture"
    findings = sec_scans.get("findings", [])
    assert len(findings) == 2

    # pip-audit finding
    pip_f = next(f for f in findings if f.get("scanner") == "pip-audit")
    assert pip_f.get("identifier") == "CVE-2024-37891"
    assert pip_f.get("report_origin") == "seeded_offline_fixture"
    assert pip_f.get("verification_status") == "unverified_fixture"

    # gitleaks finding
    git_f = next(f for f in findings if f.get("scanner") == "gitleaks")
    assert git_f.get("identifier") == "generic-api-key"
    assert git_f.get("report_origin") == "seeded_offline_fixture"
    assert git_f.get("verification_status") == "unverified_fixture"


def test_separation_of_execution_status_and_analysis_quality():
    """Verify execution_status (COMPLETED) is distinct from analysis_quality (insufficient_evidence)."""
    resp = client.post(
        "/agents/monitoring/test",
        json={
            "query": "Assess telemetry",
            "evidence": {
                "system_metrics": {"status": "unavailable"},
                "metrics": {"status": "unavailable"},
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_status"] in {"COMPLETED", "FAILED", "SKIPPED"}
    assert data["analysis_quality"] == "insufficient_evidence"
    assert len(data["findings"]) > 0
    assert any("INSUFFICIENT_EVIDENCE:" in f or "insufficient" in f.lower() for f in data["findings"])


def test_invalid_measurement_handling():
    """Verify negative or invalid container measurements are treated as invalid."""
    from agents.evidence_extractor import validate_observation
    # Valid observation
    valid = {
        "evidence_id": "test01",
        "category": "infrastructure",
        "metric_or_event": "container_cpu_usage_percent",
        "value": 25.0,
        "unit": "percent",
        "timestamp": time.time(),
        "source": "docker",
        "source_path": "docker.containers[0].cpu_usage_percent",
        "status": "observed",
        "confidence": 1.0,
        "baseline_value": None,
        "current_value": 25.0,
        "change": None,
        "evidence_text": "25.0 percent",
    }
    assert validate_observation(valid)["value"] == 25.0

    # Invalid negative cpu
    invalid_neg = dict(valid, value=-5.0)
    with pytest.raises(ValueError, match="non-negative"):
        validate_observation(invalid_neg)

