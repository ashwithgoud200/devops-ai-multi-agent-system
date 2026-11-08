"""Deterministic scenario management and fault injection engine for the Calculator application.

Supports five reproducible synthetic incident scenarios:
1. DEPLOYMENT_REGRESSION - v1.1 deployed with division exception and error spike
2. PERFORMANCE_DRIFT - High request rate, latency injection, and metric drift
3. INFRASTRUCTURE_FAILURE - Container pressure, scrape target degradation, or health failure
4. SECURITY_AUDIT - DevSecOps offline reports (Trivy, Semgrep, TruffleHog)
5. GENERAL_INCIDENT - Multi-domain investigation triggering all six specialist agents
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from agents import metrics as app_metrics
from agents.chaos_engine import chaos_engine

logger = logging.getLogger("scenarios")

# Scenario IDs
SCENARIO_DEPLOYMENT_REGRESSION = "DEPLOYMENT_REGRESSION"
SCENARIO_PERFORMANCE_DRIFT = "PERFORMANCE_DRIFT"
SCENARIO_INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
SCENARIO_SECURITY_AUDIT = "SECURITY_AUDIT"
SCENARIO_GENERAL_INCIDENT = "GENERAL_INCIDENT"

ALL_SCENARIOS = (
    SCENARIO_DEPLOYMENT_REGRESSION,
    SCENARIO_PERFORMANCE_DRIFT,
    SCENARIO_INFRASTRUCTURE_FAILURE,
    SCENARIO_SECURITY_AUDIT,
    SCENARIO_GENERAL_INCIDENT,
)

# In-memory scenario state
_SCENARIO_STATE: dict[str, Any] = {
    "active_scenario": None,
    "activated_at": None,
    "faults": {
        "division_bug": False,
        "latency_injection_seconds": 0.0,
        "cpu_pressure_simulated": False,
        "infra_degraded": False,
        "scrape_target_down": False,
        "security_reports_active": True,
    },
    "history": [],
}

SCENARIO_DEFINITIONS: dict[str, dict[str, Any]] = {
    SCENARIO_DEPLOYMENT_REGRESSION: {
        "id": SCENARIO_DEPLOYMENT_REGRESSION,
        "name": "Deployment Regression",
        "description": "Deploy Calculator v1.1 with a synthetic division-handler bug returning HTTP 500 errors.",
        "expected_root_cause": "Synthetic division handler regression in Calculator v1.1 release",
        "expected_agents": ["monitoring", "incident", "code", "cicd", "infrastructure"],
        "recommended_remediation": "rollback",
        "remediation_action": "rollback",
        "target_version": "1.0",
        "requires_approval": True,
        "symptoms": [
            "HTTP 500 Internal Server Error on /calc/div",
            "RuntimeError logged in app.log: v1.1 regression: div handler crashed",
            "Spike in calc_requests_total with status='error'",
            "Deployment history showing v1.0 followed by v1.1",
        ],
        "verification_procedure": "Verify rollback restores version 1.0, bug=false, and /calc/div returns HTTP 200.",
        "sample_queries": [
            "Investigate elevated HTTP 500 errors and division handler crash following the version 1.1 deployment.",
            "Calculator division endpoint is crashing with HTTP 500 after the latest release.",
            "Deployment regression detected on v1.1 calculator service.",
        ],
    },
    SCENARIO_PERFORMANCE_DRIFT: {
        "id": SCENARIO_PERFORMANCE_DRIFT,
        "name": "Performance and Metric Drift",
        "description": "Simulate increased calculator traffic, elevated latency (450ms), and metric drift against baseline.",
        "expected_root_cause": "High request volume combined with unoptimized computation leading to latency elevation",
        "expected_agents": ["monitoring", "incident", "infrastructure", "code"],
        "recommended_remediation": "rate_limit",
        "remediation_action": "rate_limit",
        "target_version": None,
        "requires_approval": True,
        "symptoms": [
            "Endpoint response latency increased to >400ms (P95 spike)",
            "Prometheus request rate divergence from baseline snapshot",
            "Simulated CPU resource saturation under request load",
            "Elevated latency observations across /calc/pow and arithmetic endpoints",
        ],
        "verification_procedure": "Verify latency injection reset returns response time below 10ms.",
        "sample_queries": [
            "Analyze calculator request rates, latency spikes, and anomalous HTTP error distributions against baseline.",
            "Investigate high P95 latency and degraded performance across calculator endpoints.",
            "Why is the calculator experiencing severe response time degradation compared to baseline?",
        ],
    },
    SCENARIO_INFRASTRUCTURE_FAILURE: {
        "id": SCENARIO_INFRASTRUCTURE_FAILURE,
        "name": "Infrastructure and Container Failure",
        "description": "Simulate container degradation, memory pressure, and Prometheus scrape target unavailability.",
        "expected_root_cause": "Container memory saturation and telemetry scrape target connectivity degradation",
        "expected_agents": ["infrastructure", "monitoring", "incident"],
        "recommended_remediation": "restart",
        "remediation_action": "restart",
        "target_version": None,
        "requires_approval": True,
        "symptoms": [
            "Container health reporting degraded or memory pressure threshold exceeded",
            "Prometheus target scrape warning or elevated container memory utilization",
            "Application /health response reporting infrastructure pressure",
        ],
        "verification_procedure": "Verify container metrics and scrape target status return to healthy.",
        "sample_queries": [
            "Check Docker container health, host memory and CPU utilization, and Prometheus scrape target readiness.",
            "Investigate infrastructure alert: container memory pressure and degraded target health.",
            "Are Docker containers and Prometheus scrape targets operating within healthy operational parameters?",
        ],
    },
    SCENARIO_SECURITY_AUDIT: {
        "id": SCENARIO_SECURITY_AUDIT,
        "name": "DevSecOps Security Audit",
        "description": "Ingest and analyze offline Trivy, Semgrep, and TruffleHog reports with synthetic security findings.",
        "expected_root_cause": "Detected synthetic dependency vulnerabilities (CVEs), static code flaws, and test secrets",
        "expected_agents": ["security", "cicd", "code"],
        "recommended_remediation": "patch",
        "remediation_action": "patch",
        "target_version": None,
        "requires_approval": True,
        "symptoms": [
            "Trivy container image report reporting high-severity package vulnerabilities",
            "Semgrep SAST finding identifying unvalidated arithmetic input patterns",
            "TruffleHog finding reporting exposed test credential tokens",
        ],
        "verification_procedure": "Verify scanner report deduplication and remediation guidance generation.",
        "sample_queries": [
            "Review recent build artifacts for container image CVEs, static code vulnerabilities, and leaked secrets.",
            "Perform a security triage on latest Trivy, Semgrep, and TruffleHog scanner findings.",
            "Are there any critical or high-severity vulnerabilities in the latest build artifacts?",
        ],
    },
    SCENARIO_GENERAL_INCIDENT: {
        "id": SCENARIO_GENERAL_INCIDENT,
        "name": "General Incident Investigation",
        "description": "Comprehensive cross-domain incident requiring all six specialist agents to analyze the entire stack.",
        "expected_root_cause": "Multi-domain operational incident requiring comprehensive cross-specialist triage",
        "expected_agents": ["monitoring", "incident", "code", "cicd", "infrastructure", "security"],
        "recommended_remediation": "investigate",
        "remediation_action": "investigate",
        "target_version": None,
        "requires_approval": False,
        "symptoms": [
            "Multiple disparate anomalies across logs, metrics, deployments, and security reports",
            "Ambiguous error signals requiring multi-perspective hypothesis generation",
            "Full engagement of all six specialist LLM agents",
        ],
        "verification_procedure": "Verify all six agents contribute validated, non-duplicate analyses to the final report.",
        "sample_queries": [
            "Calculator is throwing errors, what is wrong and how do we fix it?",
            "Run a complete investigation across all systems and specialist agents.",
            "Perform an end-to-end incident diagnosis of all application, infrastructure, and security signals.",
        ],
    },
}


def get_all_scenarios() -> list[dict[str, Any]]:
    """Return all scenario definitions annotated with current activation status."""
    active_id = _SCENARIO_STATE.get("active_scenario")
    result = []
    for sid in ALL_SCENARIOS:
        defn = dict(SCENARIO_DEFINITIONS[sid])
        defn["is_active"] = (sid == active_id)
        defn["activated_at"] = (
            _SCENARIO_STATE.get("activated_at") if sid == active_id else None
        )
        result.append(defn)
    return result


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    """Return a single scenario definition by ID."""
    sid = scenario_id.strip().upper()
    if sid in SCENARIO_DEFINITIONS:
        defn = dict(SCENARIO_DEFINITIONS[sid])
        defn["is_active"] = (_SCENARIO_STATE.get("active_scenario") == sid)
        defn["activated_at"] = (
            _SCENARIO_STATE.get("activated_at") if defn["is_active"] else None
        )
        return defn
    return None


def get_scenario_status() -> dict[str, Any]:
    """Return current active scenario and fault states."""
    active_id = _SCENARIO_STATE.get("active_scenario")
    return {
        "active_scenario": active_id,
        "activated_at": _SCENARIO_STATE.get("activated_at"),
        "active_definition": SCENARIO_DEFINITIONS.get(active_id) if active_id else None,
        "faults": dict(_SCENARIO_STATE["faults"]),
        "history_count": len(_SCENARIO_STATE["history"]),
    }


def activate_scenario(
    scenario_id: str,
    calculator_state: dict[str, Any] | None = None,
    log_func: Any = None,
) -> dict[str, Any]:
    """Activate a synthetic incident scenario and inject corresponding faults."""
    sid = scenario_id.strip().upper()
    if sid not in SCENARIO_DEFINITIONS:
        raise ValueError(f"Unknown scenario ID: {scenario_id}. Allowed: {list(ALL_SCENARIOS)}")

    now = time.time()
    _SCENARIO_STATE["active_scenario"] = sid
    _SCENARIO_STATE["activated_at"] = now

    # Reset any previous faults first
    _SCENARIO_STATE["faults"] = {
        "division_bug": False,
        "latency_injection_seconds": 0.0,
        "cpu_pressure_simulated": False,
        "infra_degraded": False,
        "scrape_target_down": False,
        "security_reports_active": True,
    }

    # Inject specific scenario faults
    if sid == SCENARIO_DEPLOYMENT_REGRESSION:
        _SCENARIO_STATE["faults"]["division_bug"] = True
        if calculator_state is not None:
            calculator_state["version"] = "1.1"
            calculator_state["bug"] = True
            history = calculator_state.setdefault("history", [])
            if not history or history[-1].get("version") != "1.1":
                history.append({"version": "1.1", "ts": now})
        if log_func:
            log_func("INFO", msg="deployed v1.1 (synthetic regression active)")

    elif sid == SCENARIO_PERFORMANCE_DRIFT:
        _SCENARIO_STATE["faults"]["latency_injection_seconds"] = 0.45
        _SCENARIO_STATE["faults"]["cpu_pressure_simulated"] = True
        try:
            chaos_engine.trigger_cpu_stress(duration_seconds=30, num_threads=2)
            chaos_engine.trigger_latency_spike(latency_seconds=0.45, duration_seconds=30)
        except Exception as e:
            logger.warning("Chaos engine cpu/latency trigger note: %s", e)
        if log_func:
            log_func("WARN", msg="Performance drift injected: latency=450ms, load_spike=true (real CPU stress active)")

    elif sid == SCENARIO_INFRASTRUCTURE_FAILURE:
        _SCENARIO_STATE["faults"]["infra_degraded"] = True
        _SCENARIO_STATE["faults"]["scrape_target_down"] = True
        try:
            chaos_engine.trigger_memory_stress(megabytes=200, duration_seconds=30)
            chaos_engine.trigger_cpu_stress(duration_seconds=30, num_threads=1)
        except Exception as e:
            logger.warning("Chaos engine memory trigger note: %s", e)
        if log_func:
            log_func("WARN", msg="Infrastructure fault injected: target_degraded, memory_pressure=true (real RAM allocated)")

    elif sid == SCENARIO_SECURITY_AUDIT:
        _SCENARIO_STATE["faults"]["security_reports_active"] = True
        if log_func:
            log_func("INFO", msg="Security audit scenario active: offline scanner evidence available")

    elif sid == SCENARIO_GENERAL_INCIDENT:
        _SCENARIO_STATE["faults"]["division_bug"] = True
        _SCENARIO_STATE["faults"]["latency_injection_seconds"] = 0.15
        _SCENARIO_STATE["faults"]["security_reports_active"] = True
        if calculator_state is not None:
            calculator_state["version"] = "1.1"
            calculator_state["bug"] = True
            history = calculator_state.setdefault("history", [])
            if not history or history[-1].get("version") != "1.1":
                history.append({"version": "1.1", "ts": now})
        if log_func:
            log_func("INFO", msg="General incident scenario active: cross-domain anomalies primed")

    record = {
        "event": "scenario_activated",
        "scenario_id": sid,
        "timestamp": now,
        "faults": dict(_SCENARIO_STATE["faults"]),
    }
    _SCENARIO_STATE["history"].append(record)
    logger.info("Activated scenario: %s", sid)
    return {
        "id": sid,
        "scenario_id": sid,
        "active_scenario": sid,
        "status": "active",
        "activated_at": now,
        "faults": dict(_SCENARIO_STATE["faults"]),
        "definition": SCENARIO_DEFINITIONS[sid],
    }


def reset_scenario(
    scenario_id: str | None = None,
    calculator_state: dict[str, Any] | None = None,
    log_func: Any = None,
) -> dict[str, Any]:
    """Reset the active scenario and clean up all injected faults."""
    sid = scenario_id.strip().upper() if scenario_id else _SCENARIO_STATE.get("active_scenario")
    now = time.time()

    # Clear faults
    _SCENARIO_STATE["active_scenario"] = None
    _SCENARIO_STATE["activated_at"] = None
    _SCENARIO_STATE["faults"] = {
        "division_bug": False,
        "latency_injection_seconds": 0.0,
        "cpu_pressure_simulated": False,
        "infra_degraded": False,
        "scrape_target_down": False,
        "security_reports_active": True,
    }
    try:
        chaos_engine.stop_all()
    except Exception as e:
        logger.warning("Chaos engine stop_all note: %s", e)

    # Reset calculator state back to clean v1.0
    if calculator_state is not None:
        calculator_state["version"] = "1.0"
        calculator_state["bug"] = False
        history = calculator_state.setdefault("history", [])
        if not history or history[-1].get("version") != "1.0":
            history.append({"version": "1.0", "ts": now})

    if log_func:
        log_func("INFO", msg="Scenario reset: all synthetic faults cleared, version=1.0")

    record = {
        "event": "scenario_reset",
        "scenario_id": sid or "ALL",
        "timestamp": now,
    }
    _SCENARIO_STATE["history"].append(record)
    logger.info("Reset scenario: %s", sid)
    return {
        "scenario_id": sid or "ALL",
        "status": "inactive",
        "reset_at": now,
        "faults": dict(_SCENARIO_STATE["faults"]),
    }


def get_injected_latency() -> float:
    """Return currently active latency injection in seconds."""
    return float(_SCENARIO_STATE["faults"].get("latency_injection_seconds", 0.0))


def get_synthetic_latency(scenario_id: str | None = None) -> float:
    """Return active latency injection in seconds for scenario tests."""
    return get_injected_latency()


def get_active_scenario() -> str | None:
    """Return ID of currently active synthetic scenario, or None."""
    return _SCENARIO_STATE.get("active_scenario")


def is_fault_active(fault_name: str) -> bool:
    """Check if a specific fault flag or scenario ID is currently active."""
    s = fault_name.strip().upper()
    if s == _SCENARIO_STATE.get("active_scenario"):
        return True
    return bool(_SCENARIO_STATE["faults"].get(fault_name, False))
