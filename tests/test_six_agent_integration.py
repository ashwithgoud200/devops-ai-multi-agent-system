"""Stage 6 — Six-Agent Integration, Cross-Agent Reasoning, and Safety Validation Tests.

All tests in this module use deterministic mocked LLM responses and synthetic
telemetry fixtures so CI runs without requiring a live Ollama server or executing
real deployments, fault injection, or rollbacks.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient
from langgraph.types import Command

from agents import evidence_extractor, graph, incident_api, llm_runtime
from agents import metrics as app_metrics
from calculator_app.app import app

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SIX_MODELS = {
    "monitoring": "qwen2.5:3b",
    "incident": "llama3.2:3b",
    "code": "qwen2.5-coder:3b",
    "cicd": "stablelm-zephyr:3b",
    "infrastructure": "phi3.5:3.8b",
    "security": "granite3.1-dense:2b",
}


def _counter_value(counter, **labels) -> float:
    if labels:
        return float(counter.labels(**labels)._value.get())
    return float(counter._value.get())


def _histogram_count(histogram, **labels) -> float:
    # Sum all finite + Inf bucket counters to get exact observation count
    buckets = histogram.labels(**labels)._buckets
    return float(buckets[-1].get()) if buckets else 0.0


def _valid_mock_analysis(
    summary: str,
    findings: list[str],
    confidence: float = 0.85,
    recommended_checks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "summary": summary,
        "findings": findings,
        "confidence": confidence,
        "recommended_checks": recommended_checks or ["Review the observed telemetry."],
    }


# ============================================================================
# Phase 2: Six-Agent Integration & Runtime Constraints Tests
# ============================================================================


def test_six_agent_model_assignments_and_hardware_runtime_constraints_preserved():
    """Verify Phase 1 & Phase 6 model assignments and laptop VRAM runtime constraints."""
    config = llm_runtime.load_config()
    assert config["provider"] == "ollama"
    assert config["enabled"] is False

    runtime = config["runtime"]
    assert runtime["max_parallel_models"] == 1
    assert runtime["keep_alive"] == "0s"
    assert runtime["context_length"] == 2048
    assert runtime["max_output_tokens"] == 384
    assert runtime["request_timeout_seconds"] == 120
    assert runtime["temperature"] == 0.1

    agents_cfg = config["agents"]
    assert list(agents_cfg.keys()) == list(graph.SPECIALIST_ORDER)
    for agent_id, expected_model in EXPECTED_SIX_MODELS.items():
        assert agents_cfg[agent_id]["model"] == expected_model
        assert isinstance(agents_cfg[agent_id]["role"], str)
        assert len(agents_cfg[agent_id]["role"]) > 10


def test_all_six_agents_selected_and_invoked_sequentially_with_correct_models(
    monkeypatch,
):
    """Prove all 6 agents can be selected and invoked sequentially without overlap."""
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    invocation_log: list[dict[str, Any]] = []
    active_calls = 0
    max_concurrent_calls = 0

    agent_findings = {
        "monitoring": (
            "Observed div error counter is 8 and CPU utilization is 92%.",
            ["Current div/error request counter is 8.", "CPU utilization is 92%."],
        ),
        "incident": (
            "Errors increased after version 1.1 deployment.",
            ["Observed 8 division errors after version 1.1 deployment."],
        ),
        "code": (
            "Division operation in calculate_average lacks zero-denominator check.",
            ["Observed failure: division handler failed on zero denominator."],
        ),
        "cicd": (
            "Version changed from 1.0 to 1.1 with deployment_status completed.",
            ["Current application version is '1.1' and baseline version is '1.0'."],
        ),
        "infrastructure": (
            "Container calculator is running and healthy with CPU at 92%.",
            ["Container calculator health_status is 'healthy' and restart_count is 0."],
        ),
        "security": (
            "Recorded suspicious authentication failure event in logs.",
            ["Suspicious login attempt observed for user=demo."],
        ),
    }

    class _MockResponse:
        def __init__(self, payload: dict[str, Any]):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "message": {"content": json.dumps(self._payload)},
                "done_reason": "stop",
                "prompt_eval_count": 512,
                "eval_count": 96,
                "total_duration": 100_000_000,
            }

    def fake_post(url: str, json: dict[str, Any], timeout: float):
        nonlocal active_calls, max_concurrent_calls
        active_calls += 1
        max_concurrent_calls = max(max_concurrent_calls, active_calls)
        started_at = time.perf_counter()
        try:
            model_used = json["model"]
            matching_agents = [
                a for a, m in EXPECTED_SIX_MODELS.items() if m == model_used
            ]
            assert len(matching_agents) == 1
            agent_id = matching_agents[0]
            assert json["keep_alive"] == "0s"
            assert json["options"]["num_ctx"] == 2048
            assert json["options"]["num_predict"] == 384
            assert json["options"]["temperature"] == 0.1
            assert timeout == 120.0
            summary, findings = agent_findings[agent_id]
            analysis = _valid_mock_analysis(summary, findings, confidence=0.85)
            invocation_log.append({
                "agent": agent_id,
                "model": model_used,
                "started_at": started_at,
                "ended_at": time.perf_counter(),
            })
            return _MockResponse(analysis)
        finally:
            active_calls -= 1

    monkeypatch.setattr(llm_runtime.requests, "post", fake_post)

    evidence = {
        "captured_at": 200.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.1"}},
        "metrics": {
            "status": "ok",
            "measurements": {"cpu_usage_percent": 92, "memory_usage_percent": 80},
            "requests": {"div": {"ok": 92, "error": 8}},
            "latency_observations": {"div": 100},
        },
        "system_metrics": {
            "status": "ok",
            "measurements": {"cpu_usage_percent": 92, "memory_usage_percent": 80},
        },
        "version": {
            "status": "ok",
            "data": {
                "version": "1.1",
                "deployment_status": "completed",
                "history": [
                    {"version": "1.0", "ts": 90},
                    {"version": "1.1", "ts": 150},
                ],
            },
        },
        "logs": {
            "status": "ok",
            "events": [
                {"ts": 175, "level": "ERROR", "msg": "division handler failed"},
                {"ts": 180, "level": "WARN", "msg": "Suspicious login attempt observed for user=demo."},
            ],
        },
        "docker": {
            "status": "ok",
            "containers": [{
                "id": "calc-001",
                "name": "calculator",
                "status": "running",
                "health_status": "healthy",
                "restart_count": 0,
                "cpu_usage_percent": 92,
                "memory_usage_mib": 256,
            }],
        },
        "code_changes": {
            "status": "provided",
            "source_code": "def div(a, b): return a / b",
            "observed_failure": "division handler failed on zero denominator.",
        },
    }
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100.0,
            "metrics": {"status": "ok", "requests": {"div": {"ok": 80, "error": 0}}},
            "version": {"status": "ok", "data": {"version": "1.0"}},
            "logs": {"status": "ok", "events": []},
        },
    }
    comparison = graph._compare_snapshots(baseline, evidence)
    state: graph.IncidentState = {
        "query": "Diagnose incident and suspicious authentication after deployment",
        "evidence": evidence,
        "baseline": baseline,
        "comparison": comparison,
        "trace": [],
    }

    before_exec = {
        agent: _counter_value(app_metrics.AGENT_EXECUTIONS_TOTAL, agent=agent, outcome="ok")
        for agent in graph.SPECIALIST_ORDER
    }
    before_llm = {
        agent: _counter_value(
            app_metrics.LLM_REQUESTS_TOTAL,
            agent=agent,
            model=EXPECTED_SIX_MODELS[agent],
            status="success",
        )
        for agent in graph.SPECIALIST_ORDER
    }

    state.update(graph._specialists_node(state))
    state.update(graph._diagnose_node(state))

    # 1. All 6 agents selected and executed in strict SPECIALIST_ORDER
    assert state["specialists"]["selected"] == list(graph.SPECIALIST_ORDER)
    assert [entry["agent"] for entry in invocation_log] == list(graph.SPECIALIST_ORDER)
    assert max_concurrent_calls == 1
    for idx in range(len(invocation_log) - 1):
        assert invocation_log[idx]["ended_at"] <= invocation_log[idx + 1]["started_at"]

    # 2. Each agent used its exact assigned model and returned schema-valid output
    results = state["specialists"]["results"]
    for agent in graph.SPECIALIST_ORDER:
        res = results[agent]
        assert res["status"] == "ok"
        assert res["model"] == EXPECTED_SIX_MODELS[agent]
        assert graph._valid_analysis(res)
        assert res["evidence_delivery"]["delivery_complete"] is True
        assert (
            _counter_value(app_metrics.AGENT_EXECUTIONS_TOTAL, agent=agent, outcome="ok")
            == before_exec[agent] + 1
        )
        assert (
            _counter_value(
                app_metrics.LLM_REQUESTS_TOTAL,
                agent=agent,
                model=EXPECTED_SIX_MODELS[agent],
                status="success",
            )
            == before_llm[agent] + 1
        )

    # 3. All 6 agents contributed to the final diagnosis
    diagnosis = state["diagnosis"]
    interpreted_agents = [item["agent"] for item in diagnosis["llm_interpretations"]]
    assert interpreted_agents == list(graph.SPECIALIST_ORDER)
    assert set(diagnosis["specialist_evidence_delivery"].keys()) == set(
        graph.SPECIALIST_ORDER
    )


def test_unselected_agents_are_not_invoked_or_counted_as_executed(monkeypatch):
    """Prove unselected agents do not run and do not increment execution counters."""
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "false")
    invoked: list[str] = []

    def tracking_analyze(agent: str, task: str, evidence: dict[str, Any]):
        invoked.append(agent)
        return {
            "status": "disabled",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", tracking_analyze)

    # Only system_metrics is provided; no health, no regression, no deployment change, no security
    state: graph.IncidentState = {
        "query": "Check current CPU usage",
        "evidence": {
            "health": {"status": "unavailable"},
            "metrics": {"status": "unavailable"},
            "system_metrics": {
                "status": "ok",
                "measurements": {"cpu_utilization_percent": 35.0},
            },
            "version": {"status": "unavailable"},
            "logs": {"status": "ok", "events": []},
            "docker": {"status": "unavailable", "containers": []},
            "prometheus": {"status": "unavailable", "metrics": {}},
        },
        "comparison": {"status": "unavailable", "regression_signal": False, "deployment_changed": False},
        "trace": [],
    }

    unselected = [a for a in graph.SPECIALIST_ORDER if a != "monitoring"]
    before_unselected_counts = {
        agent: sum(
            _counter_value(app_metrics.AGENT_EXECUTIONS_TOTAL, agent=agent, outcome=outcome)
            for outcome in app_metrics.ALLOWED_AGENT_OUTCOMES
        )
        for agent in unselected
    }
    before_unselected_hist = {
        agent: _histogram_count(app_metrics.AGENT_EXECUTION_DURATION_SECONDS, agent=agent)
        for agent in unselected
    }
    before_mon = _counter_value(
        app_metrics.AGENT_EXECUTIONS_TOTAL, agent="monitoring", outcome="disabled"
    )

    out = graph._specialists_node(state)
    assert out["specialists"]["selected"] == ["monitoring"]
    assert list(out["specialists"]["results"].keys()) == ["monitoring"]
    assert invoked == ["monitoring"]
    assert (
        _counter_value(
            app_metrics.AGENT_EXECUTIONS_TOTAL, agent="monitoring", outcome="disabled"
        )
        == before_mon + 1
    )

    for agent in unselected:
        after_count = sum(
            _counter_value(app_metrics.AGENT_EXECUTIONS_TOTAL, agent=agent, outcome=outcome)
            for outcome in app_metrics.ALLOWED_AGENT_OUTCOMES
        )
        assert after_count == before_unselected_counts[agent], (
            f"Unselected agent {agent} should not have incremented execution counters"
        )
        assert (
            _histogram_count(app_metrics.AGENT_EXECUTION_DURATION_SECONDS, agent=agent)
            == before_unselected_hist[agent]
        )


def test_agent_failures_and_malformed_outputs_never_silently_become_success(monkeypatch):
    """Prove timeout, unavailable, invalid_response, non-dict, and exception paths stay distinct from ok."""
    evidence = {
        "captured_at": 200.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.1"}},
        "metrics": {"status": "ok", "requests": {"div": {"ok": 50, "error": 5}}},
        "version": {
            "status": "ok",
            "data": {
                "version": "1.1",
                "history": [{"version": "1.0", "ts": 90}, {"version": "1.1", "ts": 150}],
            },
        },
        "logs": {
            "status": "ok",
            "events": [{"ts": 180, "level": "WARN", "msg": "Suspicious authentication failure"}],
        },
    }
    comparison = {
        "status": "ok",
        "regression_signal": True,
        "deployment_changed": True,
        "baseline_version": "1.0",
        "current_version": "1.1",
        "comparable_sources": ["metrics", "version", "logs"],
    }

    def mixed_analyze(agent: str, task: str, supplied_evidence: dict[str, Any]):
        if agent == "monitoring":
            return {
                "status": "timeout",
                "agent": agent,
                "model": EXPECTED_SIX_MODELS[agent],
                "detail": "ReadTimeout after 120s",
            }
        if agent == "incident":
            return {
                "status": "unavailable",
                "agent": agent,
                "model": EXPECTED_SIX_MODELS[agent],
                "detail": "Connection refused",
            }
        if agent == "code":
            # Claims status="ok" but analysis violates contract (confidence > 1)
            return {
                "status": "ok",
                "agent": agent,
                "model": EXPECTED_SIX_MODELS[agent],
                "analysis": {
                    "summary": "Bad confidence",
                    "findings": ["item"],
                    "confidence": 1.5,
                    "recommended_checks": [],
                },
            }
        if agent == "cicd":
            # Non-dict return value
            return "malformed-non-dict-output"  # type: ignore[return-value]
        if agent == "infrastructure":
            raise RuntimeError("unexpected runtime crash in infrastructure agent")
        # security succeeds with valid schema
        analysis = _valid_mock_analysis(
            "Suspicious authentication failure was recorded in logs.",
            ["Suspicious authentication failure at ts=180."],
            confidence=0.75,
        )
        return {
            "status": "ok",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
            "analysis": analysis,
            "raw_content": json.dumps(analysis),
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", mixed_analyze)

    state: graph.IncidentState = {
        "query": "Diagnose incident and suspicious authentication failure",
        "evidence": evidence,
        "comparison": comparison,
        "trace": [],
    }
    state.update(graph._specialists_node(state))
    state.update(graph._diagnose_node(state))

    results = state["specialists"]["results"]
    assert results["monitoring"]["status"] == "timeout"
    assert results["incident"]["status"] == "unavailable"
    assert results["code"]["status"] == "invalid_response"
    assert results["cicd"]["status"] == "invalid_response"
    assert results["infrastructure"]["status"] == "error"
    assert results["security"]["status"] == "ok"

    # Every agent result still carries its assigned model
    for agent, expected_model in EXPECTED_SIX_MODELS.items():
        assert results[agent]["model"] == expected_model

    # Only the single successful agent (security) is included in llm_interpretations
    diagnosis = state["diagnosis"]
    assert [item["agent"] for item in diagnosis["llm_interpretations"]] == ["security"]


# ============================================================================
# Phase 3: Cross-Agent Reasoning Across All 7 Required Scenarios
# ============================================================================


def test_cross_agent_scenario_1_cpu_utilization_spike(monkeypatch):
    """Scenario 1: CPU utilization spike selects monitoring, incident, infrastructure."""
    evidence = {
        "captured_at": 300.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.0"}},
        "metrics": {
            "status": "ok",
            "measurements": {"cpu_usage_percent": 94.0, "memory_usage_percent": 42.0},
            "requests": {"add": {"ok": 120, "error": 0}},
        },
        "system_metrics": {
            "status": "ok",
            "measurements": {"cpu_usage_percent": 94.0, "memory_usage_percent": 42.0},
        },
        "version": {"status": "ok", "data": {"version": "1.0", "history": [{"version": "1.0", "ts": 100}]}},
        "logs": {"status": "ok", "events": []},
        "docker": {
            "status": "ok",
            "containers": [{
                "id": "calc-1",
                "name": "calculator",
                "status": "running",
                "health_status": "healthy",
                "restart_count": 0,
                "cpu_usage_percent": 94.0,
                "memory_usage_mib": 120.0,
            }],
        },
    }
    baseline = {"status": "ok", "snapshot": copy.deepcopy(evidence)}
    comparison = graph._compare_snapshots(baseline, evidence)

    def analyze(agent: str, task: str, supplied: dict[str, Any]):
        if agent == "monitoring":
            analysis = _valid_mock_analysis(
                "CPU utilization is 94%.",
                ["CPU utilization is 94%."],
            )
        elif agent == "incident":
            analysis = _valid_mock_analysis(
                "CPU utilization is 94%.",
                ["CPU utilization is 94%."],
            )
        else:
            analysis = _valid_mock_analysis(
                "Container CPU usage is 94%.",
                ["Container CPU usage is 94%."],
            )
        return {
            "status": "ok",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
            "analysis": analysis,
            "raw_content": json.dumps(analysis),
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)
    state: graph.IncidentState = {
        "query": "Diagnose high CPU utilization spike",
        "evidence": evidence,
        "baseline": baseline,
        "comparison": comparison,
        "trace": [],
    }
    state.update(graph._specialists_node(state))
    state.update(graph._diagnose_node(state))
    state.update(graph._propose_node(state))

    assert state["specialists"]["selected"] == ["monitoring", "incident", "infrastructure"]
    assert len(state["diagnosis"]["llm_interpretations"]) == 3
    assert state["diagnosis"]["specialist_conflicts"] == []
    assert state[" diagnosis" if False else "diagnosis"]["unverified_claims"] == []
    assert state["remediation"]["action"] == "none"
    assert state["remediation"]["requires_approval"] is False


def test_cross_agent_scenario_2_memory_pressure_flags_invented_root_cause(monkeypatch):
    """Scenario 2: Memory pressure links 88% / 750 MiB facts and flags invented leak claims."""
    evidence = {
        "captured_at": 300.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.0"}},
        "metrics": {
            "status": "ok",
            "measurements": {"cpu_usage_percent": 30.0, "memory_usage_percent": 88.0},
            "requests": {"mul": {"ok": 80, "error": 0}},
        },
        "system_metrics": {
            "status": "ok",
            "measurements": {"cpu_usage_percent": 30.0, "memory_usage_percent": 88.0},
        },
        "docker": {
            "status": "ok",
            "containers": [{
                "id": "calc-1",
                "name": "calculator",
                "status": "running",
                "health_status": "healthy",
                "restart_count": 0,
                "cpu_usage_percent": 30.0,
                "memory_usage_mib": 750.0,
                "memory_usage_bytes": 786432000,
            }],
        },
        "logs": {"status": "ok", "events": []},
    }
    comparison = {"status": "ok", "regression_signal": False, "deployment_changed": False}

    def analyze(agent: str, task: str, supplied: dict[str, Any]):
        if agent == "monitoring":
            analysis = _valid_mock_analysis(
                "Memory utilization is 88%.",
                ["Memory utilization is 88%."],
            )
        elif agent == "infrastructure":
            analysis = _valid_mock_analysis(
                "Container memory usage is 750 MiB (786432000 bytes).",
                [
                    "Container memory usage is 750 MiB.",
                    # Invented unsupported numeric threshold claim:
                    "Memory usage exceeds the configured 512 MiB limit.",
                ],
            )
        else:
            analysis = _valid_mock_analysis(
                "Memory utilization is 88% with no error logs.",
                ["Memory utilization is 88%."],
            )
        return {
            "status": "ok",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
            "analysis": analysis,
            "raw_content": json.dumps(analysis),
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)
    state: graph.IncidentState = {
        "query": "Diagnose memory pressure on service",
        "evidence": evidence,
        "comparison": comparison,
        "trace": [],
    }
    state.update(graph._specialists_node(state))
    state.update(graph._diagnose_node(state))

    assert state["specialists"]["selected"] == ["monitoring", "incident", "infrastructure"]
    unverified = state["diagnosis"]["unverified_claims"]
    assert any("512" in item["claim"] for item in unverified)


def test_cross_agent_scenario_3_application_http_errors_with_code_evidence(monkeypatch):
    """Scenario 3: Application HTTP errors without version change selects monitoring, incident, code, infrastructure and proposes investigate."""
    evidence = {
        "captured_at": 300.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.0"}},
        "metrics": {
            "status": "ok",
            "requests": {"div": {"ok": 48, "error": 12}},
            "latency_observations": {"div": 60},
        },
        "version": {
            "status": "ok",
            "data": {"version": "1.0", "history": [{"version": "1.0", "ts": 100}]},
        },
        "logs": {
            "status": "ok",
            "events": [{"ts": 250, "level": "ERROR", "msg": "ZeroDivisionError in div endpoint"}],
        },
        "code_changes": {
            "status": "provided",
            "source_code": "def div(a, b): return a / b",
            "observed_failure": "ZeroDivisionError when b == 0",
        },
    }
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100.0,
            "metrics": {"status": "ok", "requests": {"div": {"ok": 48, "error": 0}}},
            "version": {"status": "ok", "data": {"version": "1.0"}},
            "logs": {"status": "ok", "events": []},
        },
    }
    comparison = graph._compare_snapshots(baseline, evidence)

    monkeypatch.setattr(
        graph.llm_runtime,
        "analyze",
        lambda agent, task, supplied: {
            "status": "ok",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
            "analysis": _valid_mock_analysis(
                f"{agent} observed 12 div errors (20% error rate).",
                ["Observed application error rate is 20%."],
            ),
            "raw_content": "{}",
        },
    )
    state: graph.IncidentState = {
        "query": "Application HTTP errors on div endpoint",
        "evidence": evidence,
        "baseline": baseline,
        "comparison": comparison,
        "trace": [],
    }
    state.update(graph._specialists_node(state))
    state.update(graph._diagnose_node(state))
    state.update(graph._propose_node(state))

    assert state["specialists"]["selected"] == [
        "monitoring",
        "incident",
        "code",
        "infrastructure",
    ]
    assert state["diagnosis"]["summary"] == (
        "New application errors were observed; no deployment cause was established."
    )
    assert state["remediation"]["action"] == "investigate"
    assert state["remediation"]["requires_approval"] is False


def test_cross_agent_scenario_4_dependency_failure_does_not_invent_root_cause(monkeypatch):
    """Scenario 4: Dependency timeout log without deployment change recommends investigation without inventing root cause."""
    evidence = {
        "captured_at": 300.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.0"}},
        "metrics": {
            "status": "ok",
            "requests": {"add": {"ok": 95, "error": 5}},
        },
        "version": {"status": "ok", "data": {"version": "1.0", "history": [{"version": "1.0", "ts": 100}]}},
        "logs": {
            "status": "ok",
            "events": [
                {"ts": 280, "level": "ERROR", "msg": "upstream dependency connection timeout after 3000ms"}
            ],
        },
    }
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100.0,
            "metrics": {"status": "ok", "requests": {"add": {"ok": 95, "error": 0}}},
            "version": {"status": "ok", "data": {"version": "1.0"}},
            "logs": {"status": "ok", "events": []},
        },
    }
    comparison = graph._compare_snapshots(baseline, evidence)

    monkeypatch.setattr(
        graph.llm_runtime,
        "analyze",
        lambda agent, task, supplied: {
            "status": "ok",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
            "analysis": _valid_mock_analysis(
                "Upstream dependency connection timeout was logged; root cause in external dependency cannot be confirmed from local telemetry.",
                ["Current add/error request counter is 5."],
            ),
            "raw_content": "{}",
        },
    )
    state: graph.IncidentState = {
        "query": "Diagnose dependency failure timeouts",
        "evidence": evidence,
        "baseline": baseline,
        "comparison": comparison,
        "trace": [],
    }
    state.update(graph._specialists_node(state))
    state.update(graph._diagnose_node(state))
    state.update(graph._propose_node(state))

    assert "incident" in state["specialists"]["selected"]
    assert "monitoring" in state["specialists"]["selected"]
    assert state["remediation"]["action"] == "investigate"
    assert state["remediation"]["requires_approval"] is False


def test_cross_agent_scenario_5_cicd_deployment_failure_and_post_deploy_regression(
    monkeypatch,
):
    """Scenario 5: Verify both (a) failed CI/CD pipeline before version promotion and (b) post-deploy regression correlation."""
    # Part A: Pipeline failed before version change (deployment_changed=False, pipeline.status="failed")
    pipeline_fail_evidence = {
        "captured_at": 300.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.0"}},
        "metrics": {"status": "ok", "requests": {"add": {"ok": 50, "error": 0}}},
        "version": {
            "status": "ok",
            "data": {"version": "1.0", "deployment_status": "failed"},
        },
        "pipeline": {
            "status": "failed",
            "stage": "unit-tests",
            "detail": "CI build failed on commit abc1234",
        },
        "logs": {"status": "ok", "events": []},
    }
    state_a: graph.IncidentState = {
        "query": "Investigate CI/CD deployment failure",
        "evidence": pipeline_fail_evidence,
        "comparison": {"status": "ok", "regression_signal": False, "deployment_changed": False},
        "trace": [],
    }
    selected_a = graph._select_specialists(state_a)
    assert "cicd" in selected_a
    assert "incident" in selected_a

    # Part B: Post-deployment error regression (version 1.0 -> 1.1 + new errors)
    post_deploy_evidence = {
        "captured_at": 300.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.1"}},
        "metrics": {"status": "ok", "requests": {"div": {"ok": 50, "error": 10}}},
        "version": {
            "status": "ok",
            "data": {
                "version": "1.1",
                "deployment_status": "completed",
                "history": [{"version": "1.0", "ts": 100}, {"version": "1.1", "ts": 200}],
            },
        },
        "logs": {
            "status": "ok",
            "events": [{"ts": 220, "level": "ERROR", "msg": "v1.1 regression error"}],
        },
    }
    baseline_b = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100.0,
            "metrics": {"status": "ok", "requests": {"div": {"ok": 50, "error": 0}}},
            "version": {"status": "ok", "data": {"version": "1.0"}},
            "logs": {"status": "ok", "events": []},
        },
    }
    comparison_b = graph._compare_snapshots(baseline_b, post_deploy_evidence)
    monkeypatch.setattr(
        graph.llm_runtime,
        "analyze",
        lambda agent, task, supplied: {
            "status": "ok",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
            "analysis": _valid_mock_analysis(
                f"{agent}: version 1.1 correlates with 10 div errors.",
                ["Current application version is '1.1'."],
            ),
            "raw_content": "{}",
        },
    )
    state_b: graph.IncidentState = {
        "query": "Diagnose post-deployment errors",
        "evidence": post_deploy_evidence,
        "baseline": baseline_b,
        "comparison": comparison_b,
        "trace": [],
    }
    state_b.update(graph._specialists_node(state_b))
    state_b.update(graph._diagnose_node(state_b))
    state_b.update(graph._propose_node(state_b))

    assert state_b["specialists"]["selected"] == [
        "monitoring",
        "incident",
        "code",
        "cicd",
        "infrastructure",
    ]
    assert "correlation does not establish causation" in (
        state_b["diagnosis"]["deterministic_hypotheses"][0]["statement"]
    )
    assert state_b["remediation"]["action"] == "rollback"
    assert state_b["remediation"]["target_version"] == "1.0"
    assert state_b["remediation"]["requires_approval"] is True


def test_cross_agent_scenario_6_infrastructure_problem_and_conflict_detection(
    monkeypatch,
):
    """Scenario 6: Unhealthy container with restarts selects infrastructure/incident/monitoring and flags conflicting numeric claims."""
    evidence = {
        "captured_at": 300.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.0"}},
        "metrics": {
            "status": "ok",
            "measurements": {"cpu_usage_percent": 92.0},
            "requests": {"add": {"ok": 40, "error": 0}},
        },
        "docker": {
            "status": "ok",
            "containers": [{
                "id": "calc-001",
                "name": "calculator",
                "status": "running",
                "health_status": "unhealthy",
                "restart_count": 4,
                "cpu_usage_percent": 92.0,
                "memory_usage_mib": 512.0,
            }],
        },
        "logs": {"status": "ok", "events": []},
    }
    comparison = {"status": "ok", "regression_signal": False, "deployment_changed": False}

    def conflicting_analyze(agent: str, task: str, supplied: dict[str, Any]):
        if agent == "monitoring":
            finding = "CPU utilization is 92%."
        elif agent == "infrastructure":
            # Contradictory numeric claim on CPU topic
            finding = "CPU utilization is 45%."
        else:
            finding = "Container calculator restart_count is 4."
        analysis = _valid_mock_analysis(f"{agent} report", [finding], confidence=0.8)
        return {
            "status": "ok",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
            "analysis": analysis,
            "raw_content": json.dumps(analysis),
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", conflicting_analyze)
    state: graph.IncidentState = {
        "query": "Check infrastructure container health",
        "evidence": evidence,
        "comparison": comparison,
        "trace": [],
    }
    state.update(graph._specialists_node(state))
    state.update(graph._diagnose_node(state))

    assert state["specialists"]["selected"] == ["monitoring", "incident", "infrastructure"]
    conflicts = state["diagnosis"]["specialist_conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["topic"] == "cpu"
    assert "observed evidence remains authoritative" in conflicts[0]["resolution"]
    assert any(
        "45%" in item["claim"] for item in state["diagnosis"]["unverified_claims"]
    )


def test_cross_agent_scenario_7_security_incident_scoping_and_grounding(monkeypatch):
    """Scenario 7: Security incident scopes evidence to security_events and flags unsupported attribution."""
    evidence = {
        "captured_at": "2026-11-02T10:00:00Z",
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.0"}},
        "metrics": {"status": "ok", "requests": {"add": {"ok": 20, "error": 0}}},
        "logs": {
            "status": "ok",
            "source": "synthetic security fixture",
            "events": [
                {
                    "ts": "2026-11-02T09:58:00Z",
                    "level": "WARN",
                    "msg": "authentication failed login user=admin source_ip=192.0.2.50",
                },
                {
                    "ts": "2026-11-02T09:59:00Z",
                    "level": "WARN",
                    "msg": "Suspicious unauthorized access attempt from source_ip=192.0.2.50",
                },
            ],
        },
        "docker": {
            "status": "ok",
            "containers": [{"name": "calculator", "status": "running", "health_status": "healthy"}],
        },
    }
    comparison = {"status": "ok", "regression_signal": False, "deployment_changed": False}
    captured_security_evidence: dict[str, Any] = {}

    def security_analyze(agent: str, task: str, supplied: dict[str, Any]):
        if agent == "security":
            captured_security_evidence.update(supplied)
            analysis = _valid_mock_analysis(
                "Observed authentication failed login from source_ip=192.0.2.50.",
                [
                    "Observed source IP: 192.0.2.50.",
                    "Threat intelligence confirms a credential stuffing botnet.",
                ],
                confidence=0.7,
            )
        else:
            analysis = _valid_mock_analysis(
                f"{agent} observed healthy application status.",
                ["Health endpoint status is 'ok'."],
                confidence=0.8,
            )
        return {
            "status": "ok",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
            "analysis": analysis,
            "raw_content": json.dumps(analysis),
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", security_analyze)
    state: graph.IncidentState = {
        "query": "Triage security authentication events",
        "evidence": evidence,
        "comparison": comparison,
        "trace": [],
    }
    state.update(graph._specialists_node(state))
    state.update(graph._diagnose_node(state))
    state.update(graph._propose_node(state))

    assert "security" in state["specialists"]["selected"]
    assert "docker" not in captured_security_evidence
    assert "prometheus" not in captured_security_evidence
    assert len(captured_security_evidence["security_events"]["events"]) == 2
    assert any(
        "threat intelligence" in item["claim"].lower()
        for item in state["diagnosis"]["unverified_claims"]
    )
    assert state["remediation"]["action"] == "none"


# ============================================================================
# Phase 4: Safety and Human Approval Gate Validation
# ============================================================================


def test_safety_and_approval_gate_invariants_across_all_failure_and_decision_paths(
    monkeypatch, tmp_path
):
    """Verify all 7 Phase 4 safety requirements using isolated mocked endpoints."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "test_incident_api_ref", Path(__file__).parent / "test_incident_api.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    current, baseline = mod._snapshots()

    audit_path = tmp_path / "safety_audit.jsonl"
    monkeypatch.setenv("DEVOPS_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setattr(incident_api, "_WORKFLOW", graph.build())
    monkeypatch.setattr(
        graph, "_load_baseline", lambda: {"status": "ok", "snapshot": baseline}
    )
    monkeypatch.setattr(graph, "_collect_evidence", lambda *args: copy.deepcopy(current))

    rollback_calls: list[bool] = []
    monkeypatch.setattr(
        graph,
        "_rollback",
        lambda: rollback_calls.append(True)
        or {"status": "ok", "data": {"rolled_back_to": "1.0"}},
    )
    monkeypatch.setattr(
        graph,
        "_get_json",
        lambda path: (
            {"status": "ok", "data": {"status": "ok", "version": "1.0"}}
            if path == "/health"
            else {"status": "unavailable"}
        ),
    )

    # Even if an agent is unavailable/timed out and others return confidence=1.0,
    # rollback MUST still pause at pending_approval and never auto-execute.
    def specialist_mix(agent: str, task: str, supplied: dict[str, Any]):
        if agent == "incident":
            return {
                "status": "unavailable",
                "agent": agent,
                "model": EXPECTED_SIX_MODELS[agent],
                "detail": "Ollama offline",
            }
        analysis = _valid_mock_analysis(
            f"{agent} recommends human review of v1.1 regression.",
            ["Current div/error request counter is 4."],
            confidence=1.0,
        )
        return {
            "status": "ok",
            "agent": agent,
            "model": EXPECTED_SIX_MODELS[agent],
            "analysis": analysis,
            "raw_content": json.dumps(analysis),
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", specialist_mix)

    with TestClient(app) as client:
        # 1. Start incident -> pauses at pending_approval, zero automatic rollbacks
        res1 = client.post(
            "/incidents",
            json={"query": "Calculator security and division errors after v1.1 deployment"},
        )
        assert res1.status_code == 200
        inc1 = res1.json()
        assert inc1["status"] == "pending_approval"
        assert inc1["proposed_remediation"]["action"] == "rollback"
        assert inc1["proposed_remediation"]["requires_approval"] is True
        assert rollback_calls == []

        # 2. Rejecting prevents rollback and records audit trail
        rej = client.post(
            f"/incidents/{inc1['incident_id']}/approval",
            json={"decision": "reject", "reviewed_by": "safety-auditor"},
        )
        assert rej.status_code == 200
        assert rej.json()["outcome"]["status"] == "rejected"
        assert rollback_calls == []

        # 3. Duplicate approval on already-decided incident is rejected with HTTP 409
        dup = client.post(
            f"/incidents/{inc1['incident_id']}/approval",
            json={"decision": "approve", "reviewed_by": "safety-auditor"},
        )
        assert dup.status_code == 409
        assert rollback_calls == []

        # 4. Second incident: explicit approval executes rollback once, and duplicate approval is blocked
        res2 = client.post(
            "/incidents",
            json={"query": "Calculator errors after v1.1 deployment"},
        ).json()
        assert res2["status"] == "pending_approval"
        assert rollback_calls == []

        app_res = client.post(
            f"/incidents/{res2['incident_id']}/approval",
            json={"decision": "approve", "reviewed_by": "release-lead"},
        )
        assert app_res.status_code == 200
        assert app_res.json()["outcome"]["status"] == "succeeded"
        assert len(rollback_calls) == 1

        dup2 = client.post(
            f"/incidents/{res2['incident_id']}/approval",
            json={"decision": "approve", "reviewed_by": "release-lead"},
        )
        assert dup2.status_code == 409
        assert len(rollback_calls) == 1

        # 5. Incomplete / unavailable baseline cannot trigger rollback or approval gate
        monkeypatch.setattr(
            graph, "_load_baseline", lambda: {"status": "unavailable", "detail": "missing"}
        )
        res3 = client.post(
            "/incidents",
            json={"query": "Diagnose with missing baseline"},
        ).json()
        assert res3["status"] == "completed"
        assert res3["proposed_remediation"]["action"] == "none"
        assert res3["approval_request"] is None
        assert len(rollback_calls) == 1


# ============================================================================
# Phase 5: Measured Evaluation Report Invariants (Read-Only Historical Check)
# ============================================================================


def test_measured_evaluation_metrics_from_preserved_historical_reports():
    """Verify measured live evaluation metrics in preserved reports/ without modifying them."""
    reports_dir = ROOT / "reports"
    r72 = json.loads(
        (reports_dir / "prompt_7_2_repeated_evaluation.json").read_text(encoding="utf-8")
    )
    r71 = json.loads(
        (reports_dir / "prompt_7_1_live_evaluation.json").read_text(encoding="utf-8")
    )
    r6 = json.loads(
        (reports_dir / "six_agent_live_evaluation.json").read_text(encoding="utf-8")
    )

    assert r72["repetitions_per_agent"] == 3
    assert r72["execution"]["sequential_overlap_detected"] is False
    assert r72["execution"]["max_parallel_models"] == 1
    assert r72["execution"]["operational_actions_executed"] is False
    assert r72["summary"]["run_count"] == 21
    assert r72["summary"]["successful_inference_count"] == 21
    assert r72["summary"]["failed_inference_count"] == 0
    assert r72["summary"]["schema_invalid_count"] == 0

    assert r71["summary"]["agents_total"] == 6
    assert r71["summary"]["inference_ok"] == 6
    assert r71["summary"]["prompt7_schema_valid"] == 6
    assert r71["summary"]["prompt7_evidence_facts_total"] == 30
    assert r71["summary"]["prompt7_evidence_facts_extracted"] == 30
    assert r71["summary"]["prompt7_evidence_facts_delivered"] == 30

    assert r6["summary"]["total"] == 6
    assert r6["summary"]["inference_ok"] == 6
    assert r6["summary"]["schema_valid"] == 6
