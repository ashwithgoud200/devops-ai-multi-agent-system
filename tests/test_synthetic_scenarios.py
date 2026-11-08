"""
Comprehensive automated test suite for the Five Synthetic Incident Scenarios:
1. DEPLOYMENT_REGRESSION
2. PERFORMANCE_DRIFT
3. INFRASTRUCTURE_FAILURE
4. SECURITY_AUDIT
5. GENERAL_INCIDENT

Verifies:
- Scenario classification & natural-language intent detection
- Multi-incident category detection
- Six-agent routing logic
- Fault injection activation & reset
- Metric drift & latency detection
- Docker telemetry unavailable handling (no false failures)
- DevSecOps offline report ingestion (Trivy, Semgrep, TruffleHog)
- Specialist agent fallback on missing Ollama models / invalid JSON
- Strict human-in-the-loop approval gate (no remediation before approval)
"""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from agents import (
    scenarios,
    intent_classifier,
    scenario_api,
    ci_security_normalizer,
    docker_telemetry,
    runtime_evidence,
    graph,
    llm_runtime,
)

ROOT = Path(__file__).resolve().parents[1]


# ==============================================================================
# 1. SCENARIO CLASSIFICATION TESTS
# ==============================================================================

def test_classify_all_five_exact_queries():
    queries = {
        "DEPLOYMENT_REGRESSION": "Investigate elevated HTTP 500 errors and division handler crash following the version 1.1 deployment.",
        "PERFORMANCE_DRIFT": "Analyze calculator request rates, latency spikes, and anomalous HTTP error distributions against baseline.",
        "INFRASTRUCTURE_FAILURE": "Check Docker container health, host memory and CPU utilization, and Prometheus scrape target readiness.",
        "SECURITY_AUDIT": "Review recent build artifacts for container image CVEs, static code vulnerabilities, and leaked secrets.",
        "GENERAL_INCIDENT": "Calculator is throwing errors, what is wrong and how do we fix it?",
    }
    for expected_id, query in queries.items():
        res = intent_classifier.classify_incident_intent(query)
        assert res["primary_scenario"] == expected_id, f"Query '{query}' expected {expected_id}, got {res['primary_scenario']}"
        assert res["confidence"] >= 0.7
        assert expected_id in res["detected_scenarios"]


def test_classify_multi_intent_query():
    query = "Elevated HTTP 500 errors and high memory pressure alongside leaked test secrets in build."
    res = intent_classifier.classify_incident_intent(query)
    detected = set(res["detected_scenarios"])
    assert "DEPLOYMENT_REGRESSION" in detected
    assert "INFRASTRUCTURE_FAILURE" in detected
    assert "SECURITY_AUDIT" in detected
    assert len(detected) >= 2


def test_classify_conversational_variations():
    variations = [
        ("The calculator app is super slow and latency is spiking massively", "PERFORMANCE_DRIFT"),
        ("Docker container crashed and Prometheus scrape target is offline", "INFRASTRUCTURE_FAILURE"),
        ("New version 1.1 broke the div endpoint and throws internal server error", "DEPLOYMENT_REGRESSION"),
        ("Trivy CVE vulnerability in base image and leaked tokens in git", "SECURITY_AUDIT"),
    ]
    for query, expected_id in variations:
        res = intent_classifier.classify_incident_intent(query)
        assert res["primary_scenario"] == expected_id, f"Query '{query}' expected {expected_id}, got {res['primary_scenario']}"


# ==============================================================================
# 2. SIX-AGENT ROUTING LOGIC
# ==============================================================================

def test_specialist_agent_routing_per_scenario():
    # Scenario 1 routes to monitoring, incident, code, cicd, infrastructure
    r1 = intent_classifier.get_specialist_routing_for_query("Investigate elevated HTTP 500 errors following v1.1 deployment")
    assert "code" in r1["selected_specialists"]
    assert "monitoring" in r1["selected_specialists"]

    # Scenario 2 routes to monitoring, incident, infrastructure, code
    r2 = intent_classifier.get_specialist_routing_for_query("Analyze calculator request rates, latency spikes against baseline")
    assert "monitoring" in r2["selected_specialists"]
    assert "infrastructure" in r2["selected_specialists"]

    # Scenario 3 routes to infrastructure, monitoring, incident
    r3 = intent_classifier.get_specialist_routing_for_query("Check Docker container health and memory pressure")
    assert "infrastructure" in r3["selected_specialists"]

    # Scenario 4 routes to security, cicd, code
    r4 = intent_classifier.get_specialist_routing_for_query("Review recent build artifacts for container image CVEs and leaked secrets")
    assert "security" in r4["selected_specialists"]
    assert "cicd" in r4["selected_specialists"]

    # Scenario 5 (General) routes to ALL six agents
    r5 = intent_classifier.get_specialist_routing_for_query("Calculator is throwing errors, what is wrong and how do we fix it?")
    expected_all_six = {"monitoring", "incident", "code", "cicd", "infrastructure", "security"}
    assert set(r5["selected_specialists"]) == expected_all_six


def test_graph_select_specialists_node():
    # Verify LangGraph supervisor node logic uses intent routing
    state = {
        "incident_id": "test-inc-1",
        "query": "Calculator is throwing errors, what is wrong and how do we fix it?",
        "comparison": {"regression_signal": False},
        "evidence": {},
        "trace": [],
    }
    selected_list = graph._select_specialists(state)
    assert set(selected_list) == {"monitoring", "incident", "code", "cicd", "infrastructure", "security"}


# ==============================================================================
# 3. FAULT INJECTION ACTIVATION & RESET ENGINE
# ==============================================================================

def test_scenario_activation_and_reset():
    # Ensure starting clean
    scenarios.reset_scenario()
    assert scenarios.get_active_scenario() is None
    assert not scenarios.is_fault_active("DEPLOYMENT_REGRESSION")

    # Activate DEPLOYMENT_REGRESSION
    meta = scenarios.activate_scenario("DEPLOYMENT_REGRESSION")
    assert meta["id"] == "DEPLOYMENT_REGRESSION"
    assert scenarios.get_active_scenario() == "DEPLOYMENT_REGRESSION"
    assert scenarios.is_fault_active("DEPLOYMENT_REGRESSION")

    # Activate PERFORMANCE_DRIFT
    meta_drift = scenarios.activate_scenario("PERFORMANCE_DRIFT")
    assert meta_drift["id"] == "PERFORMANCE_DRIFT"
    assert scenarios.get_active_scenario() == "PERFORMANCE_DRIFT"
    assert scenarios.is_fault_active("PERFORMANCE_DRIFT")
    assert scenarios.get_injected_latency() > 0.4

    # Reset
    scenarios.reset_scenario()
    assert scenarios.get_active_scenario() is None
    assert not scenarios.is_fault_active("PERFORMANCE_DRIFT")


def test_scenario_api_endpoints():
    scenarios.reset_scenario()

    # List scenarios
    listing = scenario_api.list_scenarios()
    scenarios_list = listing if isinstance(listing, list) else listing.get("scenarios", [])
    assert len(scenarios_list) == 5
    assert any(s["id"] == "DEPLOYMENT_REGRESSION" for s in scenarios_list)

    # Get details
    details = scenario_api.get_scenario_details("DEPLOYMENT_REGRESSION")
    assert details["id"] == "DEPLOYMENT_REGRESSION"

    # Activate via API function
    act = scenario_api.activate_scenario_endpoint("DEPLOYMENT_REGRESSION")
    assert act["status"] in {"active", "activated"}
    assert act["active_scenario"] == "DEPLOYMENT_REGRESSION"

    # Status
    status = scenario_api.scenario_status()
    assert status["active_scenario"] == "DEPLOYMENT_REGRESSION"

    # Reset via API function
    rst = scenario_api.reset_scenario_endpoint("DEPLOYMENT_REGRESSION")
    assert rst["status"] == "reset"
    assert rst["active_scenario"] is None


# ==============================================================================
# 4. SCENARIO 1: DEPLOYMENT REGRESSION & ROLLBACK WORKFLOW
# ==============================================================================

def test_scenario_1_deployment_regression_proposal():
    scenarios.reset_scenario()
    state = {
        "incident_id": "test-reg-1",
        "query": "Investigate elevated HTTP 500 errors and division handler crash following the version 1.1 deployment.",
        "scenario": "DEPLOYMENT_REGRESSION",
        "comparison": {
            "status": "partial",
            "current_version": "1.1",
            "baseline_version": "1.0",
            "deployment_changed": True,
            "regression_signal": True,
            "comparable_sources": ["version", "metrics", "logs"],
        },
        "evidence": {
            "version": {
                "status": "ok",
                "data": {
                    "version": "1.1",
                    "history": [{"version": "1.0", "ts": 100}, {"version": "1.1", "ts": 200}],
                },
            },
            "metrics": {
                "status": "ok",
                "requests": {"div": {"ok": 0, "error": 5}},
            },
        },
        "trace": [],
    }
    proposal = graph._propose_node(state)
    remediation = proposal["remediation"]
    assert remediation["action"] == "rollback"
    assert remediation["target_version"] == "1.0"
    assert remediation["requires_approval"] is True

    # Routing must mandate approval
    next_node = graph._route_remediation({"remediation": remediation})
    assert next_node == "approval"


def test_scenario_1_human_approval_and_execution():
    state = {
        "incident_id": "test-reg-1",
        "query": "Investigate elevated HTTP 500 errors following v1.1",
        "scenario": "DEPLOYMENT_REGRESSION",
        "remediation": {
            "action": "rollback",
            "target_version": "1.0",
            "requires_approval": True,
        },
        "approval": True,  # Human approved
        "trace": [],
    }

    with patch("agents.graph._rollback", return_value={"status": "ok", "data": {"rolled_back_to": "1.0"}}), \
         patch("agents.graph._get_json", return_value={"status": "ok", "data": {"status": "ok", "version": "1.0"}}):
        apply_res = graph._apply_node(state)
        assert apply_res["outcome"]["status"] == "succeeded"
        assert apply_res["outcome"]["action"] == "rollback"
        assert apply_res["outcome"]["verification"]["data"]["version"] == "1.0"


def test_scenario_1_human_rejection_prevents_rollback():
    state = {
        "incident_id": "test-reg-1",
        "remediation": {"action": "rollback", "target_version": "1.0", "requires_approval": True},
        "approval": False,  # Human rejected
        "trace": [],
    }
    with patch("agents.graph._rollback") as mock_rollback:
        apply_res = graph._apply_node(state)
        mock_rollback.assert_not_called()
        assert apply_res["outcome"]["status"] == "not_executed"
        assert "Explicit approval was not received" in apply_res["outcome"]["reason"]


# ==============================================================================
# 5. SCENARIO 2: PERFORMANCE AND METRIC DRIFT
# ==============================================================================

def test_scenario_2_performance_drift_proposal():
    state = {
        "incident_id": "test-perf-1",
        "query": "Analyze calculator request rates, latency spikes, and anomalous HTTP error distributions against baseline.",
        "scenario": "PERFORMANCE_DRIFT",
        "comparison": {
            "status": "ok",
            "current_version": "1.1",
            "baseline_version": "1.1",
            "deployment_changed": False,
            "regression_signal": False,
        },
        "evidence": {
            "metrics": {
                "status": "ok",
                "latency_observations": {"by_operation": {"div": 0.48, "add": 0.45}},
            },
            "version": {"status": "ok", "data": {"version": "1.1", "history": []}},
        },
        "trace": [],
    }
    proposal = graph._propose_node(state)
    remediation = proposal["remediation"]
    assert remediation["action"] == "rate_limit"
    assert remediation["requires_approval"] is True
    assert "Elevated latency and anomalous request rate observed" in remediation["rationale"]

    # Route to approval
    assert graph._route_remediation({"remediation": remediation}) == "approval"


# ==============================================================================
# 6. SCENARIO 3: INFRASTRUCTURE & DOCKER TELEMETRY UNAVAILABLE HANDLING
# ==============================================================================

def test_scenario_3_docker_unavailable_handling(monkeypatch):
    # When Docker Engine is stopped, collect_docker_metrics returns status 'unavailable' without crashing or inventing zero metrics
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=["docker"],
            returncode=1,
            stdout="",
            stderr="error during connect: Docker Desktop is stopped",
        )

    monkeypatch.setattr(docker_telemetry.subprocess, "run", fake_run)
    result = docker_telemetry.collect_docker_metrics()

    assert result["status"] == "unavailable"
    assert result["containers"] == []
    assert "Docker Engine unavailable" in result["detail"]


def test_scenario_3_infrastructure_failure_proposal():
    state = {
        "incident_id": "test-infra-1",
        "query": "Check Docker container health, host memory and CPU utilization, and Prometheus scrape target readiness.",
        "scenario": "INFRASTRUCTURE_FAILURE",
        "comparison": {"status": "ok"},
        "evidence": {
            "version": {"status": "ok", "data": {"version": "1.1", "history": []}},
        },
        "trace": [],
    }
    proposal = graph._propose_node(state)
    remediation = proposal["remediation"]
    assert remediation["action"] == "restart"
    assert remediation["requires_approval"] is True


# ==============================================================================
# 7. SCENARIO 4: DEVSECOPS SECURITY REPORT INGESTION
# ==============================================================================

def test_scenario_4_security_report_ingestion():
    reports_dir = ROOT / "data" / "ci-security-reports"
    semgrep_file = reports_dir / "semgrep-results.json"
    trufflehog_file = reports_dir / "trufflehog-results.json"
    trivy_file = reports_dir / "trivy-results.json"

    assert semgrep_file.exists(), "Sample semgrep report must exist"
    assert trufflehog_file.exists(), "Sample trufflehog report must exist"
    assert trivy_file.exists(), "Sample trivy report must exist"

    # Test Semgrep parser
    semgrep_result = ci_security_normalizer.parse_semgrep(semgrep_file)
    semgrep_findings = semgrep_result["findings"]
    assert len(semgrep_findings) >= 1
    assert any("insecure-math" in f.get("identifier", "") or "calculator_app" in f.get("location", "") for f in semgrep_findings)

    # Test TruffleHog parser
    th_result = ci_security_normalizer.parse_trufflehog(trufflehog_file)
    th_findings = th_result["findings"]
    assert len(th_findings) >= 1
    assert any("trufflehog" in f.get("scanners", []) or "GENERIC" in f.get("identifier", "") for f in th_findings)

    # Test overall normalizer via runtime evidence collection
    scans = runtime_evidence.collect_security_evidence(import_dir=reports_dir)
    assert scans["status"] == "findings"
    # Find all scanners mentioned across findings
    all_scanners = set()
    for f in scans.get("findings", []):
        all_scanners.update(f.get("scanners", []))
    assert "semgrep" in all_scanners
    assert "trufflehog" in all_scanners
    assert "trivy" in all_scanners or "trivy_image" in all_scanners


def test_scenario_4_security_proposal():
    state = {
        "incident_id": "test-sec-1",
        "query": "Review recent build artifacts for container image CVEs, static code vulnerabilities, and leaked secrets.",
        "scenario": "SECURITY_AUDIT",
        "comparison": {"status": "ok"},
        "evidence": {
            "version": {"status": "ok", "data": {"version": "1.1", "history": []}},
        },
        "trace": [],
    }
    proposal = graph._propose_node(state)
    remediation = proposal["remediation"]
    assert remediation["action"] == "patch"
    assert remediation["requires_approval"] is True


# ==============================================================================
# 8. SCENARIO 5: GENERAL INCIDENT INVESTIGATION
# ==============================================================================

def test_scenario_5_general_incident_structured_report():
    state = {
        "incident_id": "test-gen-1",
        "query": "Calculator is throwing errors, what is wrong and how do we fix it?",
        "scenario": "GENERAL_INCIDENT",
        "detected_scenarios": ["GENERAL_INCIDENT", "DEPLOYMENT_REGRESSION"],
        "comparison": {
            "status": "ok",
            "current_version": "1.1",
            "baseline_version": "1.0",
            "deployment_changed": True,
            "regression_signal": True,
        },
        "evidence": {
            "version": {"status": "ok", "data": {"version": "1.1", "history": [{"version": "1.0"}, {"version": "1.1"}]}},
            "metrics": {"status": "ok", "requests": {"div": {"ok": 0, "error": 3}}},
        },
        "diagnosis": {
            "summary": "Division handler regression observed in v1.1",
            "confidence": 0.85,
            "severity": "high",
            "blast_radius": {
                "affected_endpoints": ["/calc/div"],
                "impacted_services": ["calculator-app"],
                "user_facing_impact": "Division requests failing with HTTP 500",
            },
            "verified_observations": [{"statement": "Division error rate 100% in v1.1"}],
        },
        "remediation": {
            "action": "rollback",
            "target_version": "1.0",
            "requires_approval": True,
            "rationale": "Rollback to v1.0",
        },
        "selected_specialists": ["monitoring", "incident", "code", "cicd", "infrastructure", "security"],
        "specialists": {
            "results": {
                "monitoring": {"findings": ["Error spike observed"]},
                "incident": {"findings": ["High severity incident"]},
                "code": {"findings": ["ZeroDivisionError in div handler"]},
                "cicd": {"findings": ["v1.1 deployed 5m ago"]},
                "infrastructure": {"findings": ["Container healthy"]},
                "security": {"findings": ["No security anomalies"]},
            },
            "skipped": {},
        },
        "outcome": {"status": "pending_approval"},
        "trace": [],
    }

    report_result = graph._report_node(state)
    report = report_result["report"]

    assert report["scenario"] == "GENERAL_INCIDENT"
    assert report["current_version"] == "1.1"
    assert report["recommended_action"]["to_version"] == "1.0"
    assert "/calc/div" in report["blast_radius"]["affected_endpoints"]
    assert report["recommended_action"]["requires_approval"] is True
    assert "monitoring" in report["specialists"]["results"]
    assert "security" in report["specialists"]["results"]


# ==============================================================================
# 9. LLM RESILIENCE & ERROR HANDLING
# ==============================================================================

def test_missing_ollama_models_handled_gracefully(monkeypatch):
    # When DEVOPS_LLM_ENABLED is disabled
    monkeypatch.delenv("DEVOPS_LLM_ENABLED", raising=False)
    result = llm_runtime.analyze("monitoring", "Test query", {})
    assert result["status"] == "disabled"
    assert result["model"] == "qwen2.5:3b"

    # When Ollama server is unreachable
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    with patch("agents.llm_runtime.requests.post", side_effect=requests.ConnectionError("Connection refused")):
        res_unavail = llm_runtime.analyze("code", "Test query", {})
        assert res_unavail["status"] == "unavailable"


def test_invalid_llm_json_repaired_or_handled():
    valid = {
        "summary": "High latency detected",
        "findings": ["Observed P95 spike"],
        "confidence": 0.85,
        "recommended_checks": ["Review logs"],
    }
    # Markdown fenced JSON is extracted cleanly
    raw_markdown = "```json\n" + json.dumps(valid) + "\n```"
    parsed = llm_runtime._parse_json_object(raw_markdown)
    assert parsed["summary"] == "High latency detected"
    assert parsed["confidence"] == 0.85

    # Malformed JSON raises ValueError (which triggers Ollama retry / fallback)
    with pytest.raises(ValueError):
        llm_runtime._parse_json_object("{unbalanced json: missing closing brace")
