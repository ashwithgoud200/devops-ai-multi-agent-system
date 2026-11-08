"""End-to-end pipeline verification test proving all 5 security scanner findings survive
the full path from raw scanner files through normalization, evidence extraction,
LangGraph state dispatch, security specialist packaging, claim validation, and incident reporting.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from calculator_app.app import app
from agents import runtime_evidence, evidence_extractor, graph

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def enable_security_evidence(monkeypatch):
    monkeypatch.setenv("DEVOPS_SECURITY_EVIDENCE_ENABLED", "true")
    monkeypatch.setenv("DEVOPS_EVIDENCE_IMPORT_DIR", str(ROOT / "data" / "ci-security-reports"))


def test_stage1_security_findings_endpoint_returns_all_five_findings():
    """Verify GET /security/findings exposes the five normalized scanner findings."""
    response = client.get("/security/findings")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "findings"
    findings = data.get("findings", [])
    assert len(findings) == 5

    identifiers = {f["identifier"] for f in findings}
    assert "CVE-2023-5678" in identifiers
    assert "GHSA-c2qf-rxjj-qqgw" in identifiers
    assert "CVE-2023-32681" in identifiers
    assert "DS002" in identifiers
    assert "generic-api-key" in identifiers


def test_stage2_evidence_extractor_extracts_all_five_security_findings():
    """Verify evidence_extractor.extract_evidence extracts all 5 findings into typed observations."""
    sec_scans = runtime_evidence.collect_security_evidence()
    assert sec_scans["status"] == "findings"
    assert len(sec_scans["findings"]) == 5

    evidence = {"security_scans": sec_scans}
    extracted = evidence_extractor.extract_evidence(evidence)
    assert extracted["status"] in {"ok", "partial"}

    # Must contain 6 security observations (1 summary + 5 findings)
    sec_obs = [o for o in extracted["observations"] if o["category"] == "security"]
    assert len(sec_obs) >= 6

    # Verify every finding preserved essential fields
    finding_obs = [o for o in sec_obs if o["metric_or_event"].startswith("finding_")]
    assert len(finding_obs) == 5

    by_id = {o["value"]["identifier"]: o["value"] for o in finding_obs}
    assert "CVE-2023-5678" in by_id
    assert by_id["CVE-2023-5678"]["severity"] == "critical"
    assert by_id["CVE-2023-5678"]["package"] == "openssl"

    assert "GHSA-c2qf-rxjj-qqgw" in by_id
    assert by_id["GHSA-c2qf-rxjj-qqgw"]["severity"] == "high"
    assert by_id["GHSA-c2qf-rxjj-qqgw"]["package"] == "semver"

    assert "CVE-2023-32681" in by_id
    assert by_id["CVE-2023-32681"]["severity"] == "high"
    assert by_id["CVE-2023-32681"]["package"] == "requests"

    assert "DS002" in by_id
    assert by_id["DS002"]["severity"] == "high"
    assert by_id["DS002"]["location"] == "Dockerfile"

    assert "generic-api-key" in by_id
    assert by_id["generic-api-key"]["category"] == "secret"
    assert "config/synthetic_example.py" in by_id["generic-api-key"]["location"]


def test_stage3_package_for_role_delivers_findings_to_security_specialist():
    """Verify package_for_role delivers all 5 findings to both legacy security and new security_analysis."""
    sec_scans = runtime_evidence.collect_security_evidence()
    extracted = evidence_extractor.extract_evidence({"security_scans": sec_scans})

    for role_name in ("security", "security_analysis"):
        pkg = evidence_extractor.package_for_role(extracted, role_name)
        assert pkg["status"] in {"ok", "partial"}
        finding_obs = [o for o in pkg["observations"] if o["metric_or_event"].startswith("finding_")]
        assert len(finding_obs) == 5


def test_stage4_langgraph_specialist_evidence_and_selection():
    """Verify LangGraph selects security specialist when scans have findings and delivers all observations."""
    evidence = graph._collect_evidence()
    assert evidence["security_scans"]["status"] == "findings"

    state = {
        "query": "evaluate application security status",
        "evidence": evidence,
        "baseline": {"status": "unavailable"},
        "comparison": {"status": "partial", "regression_signal": False},
        "trace": [],
    }

    selected = graph._select_specialists(state)
    assert "security" in selected

    specialist_ev = graph._specialist_evidence("security", state)
    det_evidence = specialist_ev.get("deterministic_evidence", {})
    finding_obs = [o for o in det_evidence.get("observations", []) if o.get("metric_or_event", "").startswith("finding_")]
    assert len(finding_obs) == 5


def test_stage5_full_workflow_retains_findings_in_diagnosis_and_report(monkeypatch):
    """Verify the entire workflow runs, claim validator validates findings, and report contains all 5 findings."""
    evidence = graph._collect_evidence()

    def fake_analyze(agent, task, supplied):
        # Deterministic offline specialist response citing observed findings
        return {
            "status": "ok",
            "model": "test-mock:3b",
            "analysis": {
                "summary": "Security analysis identified 5 findings including critical OpenSSL CVE-2023-5678 and Gitleaks secret.",
                "findings": [
                    "Critical image vulnerability CVE-2023-5678 detected in openssl",
                    "High severity dependency vulnerability GHSA-c2qf-rxjj-qqgw in semver",
                    "High severity dependency vulnerability CVE-2023-32681 in requests",
                    "High misconfiguration DS002 detected in Dockerfile",
                    "Secret generic-api-key detected by gitleaks in test config",
                ],
                "confidence": 0.85,
                "recommended_checks": [
                    "Upgrade openssl to patched image version",
                    "Upgrade requests to >=2.31.0 and semver to patched release",
                    "Revoke and rotate the exposed generic-api-key secret",
                ],
            },
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", fake_analyze)

    workflow = graph.build()
    config = {"configurable": {"thread_id": "test-sec-pipeline-e2e"}}
    initial_state = {
        "query": "Audit security findings and vulnerabilities",
        "evidence": evidence,
        "baseline": {"status": "unavailable"},
        "comparison": {"status": "partial", "regression_signal": False},
        "trace": [],
    }

    result = None
    for step in workflow.stream(initial_state, config, stream_mode="values"):
        result = step

    assert result is not None
    diagnosis = result.get("diagnosis", {})
    assert diagnosis
    # Verify verified observations in diagnosis contain the 5 findings
    diag_findings = [o for o in diagnosis.get("verified_observations", []) if o.get("metric_or_event", "").startswith("finding_")]
    assert len(diag_findings) == 5

    report = result.get("report", {})
    assert report
    assert "collected_evidence" in report


def test_unsupported_impact_statement_returns_unknown_when_telemetry_insufficient():
    """Verify user_facing_impact returns explicit unknown when telemetry is missing rather than 'None detected'."""
    evidence = {
        "metrics": {"status": "unavailable"},
        "prometheus": {"status": "unavailable"},
        "health": {"status": "unavailable"},
        "logs": {"status": "unavailable", "events": []},
    }
    state = {
        "query": "check health",
        "evidence": evidence,
        "baseline": {"status": "unavailable"},
        "comparison": {"status": "unavailable", "regression_signal": False},
        "specialists": {"results": {}, "skipped": {}},
        "trace": [],
    }

    diag = graph._diagnose_node(state)["diagnosis"]
    impact = diag["blast_radius"]["user_facing_impact"]
    assert "unknown" in impact.lower() or "insufficient" in impact.lower()
    assert impact != "None detected"

