import json

from langgraph.types import Command

from agents import graph


def _snapshot(version="1.1", errors=3, captured_at=200):
    history = [
        {"version": "1.0", "ts": 90},
        {"version": version, "ts": 150},
    ]
    return {
        "captured_at": captured_at,
        "health": {"status": "ok", "data": {"status": "ok", "version": version}},
        "metrics": {
            "status": "ok",
            "requests": {"div": {"ok": 60, "error": errors}},
            "latency_observations": {"div": 63},
        },
        "version": {
            "status": "ok",
            "data": {"version": version, "history": history},
        },
        "logs": {
            "status": "ok",
            "events": [
                {"ts": 210, "level": "ERROR", "msg": "division handler failed"},
                {"ts": 220, "level": "INFO", "msg": "request completed"},
            ],
        },
    }


def _security_fixture():
    return {
        "captured_at": "2026-11-02T01:00:00+05:30",
        "health": {"status": "unavailable", "detail": "Not part of this fixture"},
        "metrics": {"status": "unavailable", "detail": "Not part of this fixture"},
        "system_metrics": {
            "status": "unavailable",
            "detail": "Not part of this fixture",
        },
        "version": {"status": "unavailable", "detail": "Not part of this fixture"},
        "logs": {
            "status": "ok",
            "source": "synthetic test fixture",
            "events": [
                {
                    "ts": "2026-11-02T00:58:00+05:30",
                    "level": "WARN",
                    "msg": "Suspicious login attempt observed; source address not recorded.",
                },
                {
                    "ts": "2026-11-02T00:59:00+05:30",
                    "level": "ERROR",
                    "msg": "Authentication failed for synthetic test account.",
                },
            ],
        },
    }


def _save_baseline(monkeypatch, tmp_path, snapshot):
    baseline_path = tmp_path / "baseline.json"
    monkeypatch.setattr(graph, "BASELINE_PATH", baseline_path)
    baseline_path.write_text(
        json.dumps({
            "schema_version": 1,
            "snapshot": {
                **snapshot,
                "captured_at": 100,
                "health": {
                    "status": "ok",
                    "data": {"status": "ok", "version": "1.0"},
                },
                "metrics": {
                    "status": "ok",
                    "requests": {"div": {"ok": 60, "error": 0}},
                    "latency_observations": {"div": 60},
                },
                "version": {
                    "status": "ok",
                    "data": {
                        "version": "1.0",
                        "history": [{"version": "1.0", "ts": 90}],
                    },
                },
                "logs": {"status": "ok", "events": []},
            },
        }),
        encoding="utf-8",
    )
    return baseline_path


def _run_to_interrupt(compiled, config, query):
    updates = list(
        compiled.stream(
            {"query": query, "trace": []},
            config,
            stream_mode="updates",
        )
    )
    interrupt_update = next(
        update["__interrupt__"][0].value
        for update in updates
        if "__interrupt__" in update
    )
    return interrupt_update


def test_save_baseline_persists_the_collected_snapshot(monkeypatch, tmp_path):
    expected = _snapshot(version="1.0", errors=0)
    baseline_path = tmp_path / "nested" / "data" / "baseline.json"
    monkeypatch.setattr(graph, "BASELINE_PATH", baseline_path)
    monkeypatch.setattr(graph, "_collect_evidence", lambda: expected)

    saved = graph.save_baseline()

    assert saved == expected
    stored = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert stored["schema_version"] == 1
    assert stored["snapshot"] == expected


def test_compare_uses_only_observed_metric_log_and_version_deltas():
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100,
            "metrics": {
                "status": "ok",
                "requests": {"div": {"ok": 60, "error": 1}},
                "latency_observations": {"div": 11},
            },
            "version": {"status": "ok", "data": {"version": "1.0"}},
        },
    }
    current = _snapshot(version="1.1", errors=4)

    comparison = graph._compare_snapshots(baseline, current)

    assert comparison["status"] == "ok"
    assert comparison["comparable_sources"] == ["metrics", "version", "logs"]
    assert comparison["request_deltas"] == {"div": {"error": 3}}
    assert comparison["latency_observation_deltas"] == {"div": 52}
    assert len(comparison["new_error_logs"]) == 1
    assert comparison["deployment_changed"] is True
    assert comparison["regression_signal"] is True


def test_rollback_is_not_proposed_when_endpoint_target_differs_from_baseline():
    state = {
        "trace": [],
        "comparison": {
            "status": "ok",
            "deployment_changed": True,
            "regression_signal": True,
            "baseline_version": "1.0",
            "current_version": "1.2",
        },
        "evidence": {
            "version": {
                "status": "ok",
                "data": {
                    "version": "1.2",
                    "history": [
                        {"version": "1.0"},
                        {"version": "1.1"},
                        {"version": "1.2"},
                    ],
                },
            },
        },
    }

    proposed = graph._propose_node(state)

    assert proposed["remediation"]["action"] == "investigate"


def test_rejection_never_sends_rollback_and_partial_models_are_reported(
    monkeypatch, tmp_path
):
    current = _snapshot()
    _save_baseline(monkeypatch, tmp_path, current)
    monkeypatch.setattr(graph, "_collect_evidence", lambda: current)
    calls = []

    def analyze(agent, task, evidence):
        calls.append(agent)
        if agent == "incident":
            return {"status": "unavailable", "agent": agent, "detail": "offline"}
        return {
            "status": "ok",
            "agent": agent,
            "raw_content": f'{{"audit":"original {agent} response"}}',
            "analysis": {
                "summary": f"{agent} analysis",
                "findings": [f"{agent} hypothesis"],
                "confidence": 0.8,
                "recommended_checks": [],
            },
        }

    rollback_calls = []
    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)
    monkeypatch.setattr(graph, "_rollback", lambda: rollback_calls.append(True))
    compiled = graph.build()
    config = {"configurable": {"thread_id": "rejection"}}

    pending = _run_to_interrupt(
        compiled, config, "calculator security incident errors after deployment"
    )
    assert pending["action"] == "rollback"
    assert calls == list(graph.SPECIALIST_ORDER)
    assert pending["root_cause"]

    list(compiled.stream(Command(resume=False), config, stream_mode="updates"))
    final = compiled.get_state(config).values

    assert final["outcome"]["status"] == "rejected"
    assert rollback_calls == []
    assert final["specialists"]["results"]["incident"]["status"] == "unavailable"
    assert final["specialists"]["results"]["monitoring"]["original_model_output"] == (
        '{"audit":"original monitoring response"}'
    )
    assert all(
        item["source"].endswith(("model hypothesis", "model summary"))
        for item in final["diagnosis"]["specialist_hypotheses"]
    )


def test_invalid_specialist_response_is_advisory_failure_and_others_continue(monkeypatch):
    evidence = _snapshot()
    evidence["metrics"]["request_counters"] = {"status": "ok"}
    comparison = {
        "status": "ok",
        "regression_signal": True,
        "deployment_changed": True,
        "request_deltas": {},
        "new_error_logs": [],
    }
    calls = []

    def analyze(agent, task, supplied_evidence):
        calls.append(agent)
        if agent == "monitoring":
            return {
                "status": "invalid_response",
                "agent": agent,
                "model": "qwen2.5:3b",
                "detail": "confidence must be between 0 and 1",
                "diagnostic": {
                    "validation_error": "confidence must be between 0 and 1",
                    "raw_excerpt": '{"confidence":100}',
                },
                "retry": {"attempted": True, "status": "invalid_response"},
            }
        return {"status": "disabled", "agent": agent}

    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)
    state = {
        "query": "incident",
        "evidence": evidence,
        "comparison": comparison,
        "trace": [],
    }

    results = graph._specialists_node(state)["specialists"]["results"]

    assert calls == list(graph.SPECIALIST_ORDER[:5])
    assert results["monitoring"]["status"] == "invalid_response"
    assert results["monitoring"]["diagnostic"]["validation_error"] == (
        "confidence must be between 0 and 1"
    )
    assert all(results[name]["status"] == "disabled" for name in calls[1:])


def test_security_events_select_security_specialist():
    state = {
        "query": "Review these recorded events.",
        "evidence": _security_fixture(),
        "comparison": {"regression_signal": False, "deployment_changed": False},
    }

    selected = graph._select_specialists(state)

    assert selected == ["security"]


def test_ordinary_calculator_incident_does_not_select_security():
    state = {
        "query": "Diagnose the calculator division error.",
        "evidence": _snapshot(),
        "comparison": {"regression_signal": False, "deployment_changed": False},
    }

    assert "security" not in graph._select_specialists(state)


def test_security_event_claims_are_linked_but_attack_claims_are_unverified():
    evidence = _security_fixture()
    observed = graph._validate_finding(
        "Suspicious login attempt and failed authentication were recorded.",
        evidence,
    )
    unsupported = graph._validate_finding(
        "Credential stuffing came from 203.0.113.77 at "
        "2031-02-03T04:05:06Z and matches threat intelligence.",
        evidence,
    )
    invented_absence = graph._validate_finding(
        "No timestamps were recorded for these login events.",
        evidence,
    )

    assert observed["validation_status"] == "evidence_linked"
    assert "logs.events[0].msg" in observed["evidence_refs"]
    assert "logs.events[1].msg" in observed["evidence_refs"]
    assert observed["evidence_refs"] == ["logs.events[0].msg", "logs.events[1].msg"]
    assert unsupported["validation_status"] == "unverified"
    assert any("credential stuffing" in reason.lower() for reason in unsupported["reasons"])
    assert any("203.0.113.77" in reason for reason in unsupported["reasons"])
    assert any("2031-02-03T04:05:06Z" in reason for reason in unsupported["reasons"])
    assert any(
        "threat intelligence" in reason.lower()
        for reason in unsupported["reasons"]
    )
    assert invented_absence["validation_status"] == "unverified"
    assert any("timestamp absence claim conflicts" in reason
               for reason in invented_absence["reasons"])
    assert "logs.events[0].ts" in invented_absence["evidence_refs"]


def test_security_agent_failure_does_not_stop_selected_monitoring_agent(monkeypatch):
    evidence = _security_fixture()
    evidence["metrics"] = {
        "status": "ok",
        "requests": {"calculator": {"ok": 4, "error": 1}},
    }
    calls = []

    def analyze(agent, task, supplied_evidence):
        calls.append(agent)
        if agent == "security":
            return {"status": "unavailable", "agent": agent, "detail": "model offline"}
        return {"status": "disabled", "agent": agent}

    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)
    state = {
        "query": "Check the calculator behavior.",
        "evidence": evidence,
        "comparison": {"regression_signal": False, "deployment_changed": False},
        "trace": [],
    }

    result = graph._specialists_node(state)["specialists"]

    assert result["selected"] == ["monitoring", "security"]
    assert calls == result["selected"]
    assert result["results"]["security"]["status"] == "unavailable"
    assert result["results"]["monitoring"]["status"] == "disabled"


def test_explicit_approval_rolls_back_and_verifies_expected_version(
    monkeypatch, tmp_path
):
    current = _snapshot()
    _save_baseline(monkeypatch, tmp_path, current)
    monkeypatch.setattr(graph, "_collect_evidence", lambda: current)
    monkeypatch.setattr(
        graph.llm_runtime,
        "analyze",
        lambda agent, task, evidence: {"status": "disabled", "agent": agent},
    )
    rollback_calls = []
    health_versions = iter(["1.0"])
    monkeypatch.setattr(
        graph,
        "_rollback",
        lambda: rollback_calls.append(True) or {"status": "ok", "data": {"rolled_back_to": "1.0"}},
    )
    monkeypatch.setattr(
        graph,
        "_get_json",
        lambda path: {
            "status": "ok",
            "data": {"status": "ok", "version": next(health_versions)},
        },
    )
    compiled = graph.build()
    config = {"configurable": {"thread_id": "approval"}}

    pending = _run_to_interrupt(compiled, config, "calculator errors after deployment")
    assert pending["target_version"] == "1.0"
    list(compiled.stream(Command(resume=True), config, stream_mode="updates"))

    final = compiled.get_state(config).values
    assert rollback_calls == [True]
    assert final["outcome"]["status"] == "succeeded"
    assert final["report"]["outcome"]["verification"]["data"]["version"] == "1.0"


def test_missing_baseline_and_unavailable_sources_are_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(graph, "BASELINE_PATH", tmp_path / "missing.json")
    unavailable = {
        "captured_at": 200,
        "health": {"status": "unavailable", "detail": "connection refused"},
        "metrics": {"status": "unavailable", "detail": "connection refused"},
        "version": {"status": "unavailable", "detail": "connection refused"},
        "logs": {"status": "unavailable", "detail": "file missing", "events": []},
    }
    monkeypatch.setattr(graph, "_collect_evidence", lambda: unavailable)
    compiled = graph.build()
    config = {"configurable": {"thread_id": "unavailable"}}

    list(
        compiled.stream(
            {"query": "diagnose service", "trace": []},
            config,
            stream_mode="updates",
        )
    )
    final = compiled.get_state(config).values

    assert final["comparison"]["status"] == "unavailable"
    assert final["diagnosis"]["evidence_availability"] == {
        "health": "unavailable",
        "metrics": "unavailable",
        "version": "unavailable",
        "logs": "unavailable",
    }
    assert final["outcome"]["status"] == "not_required"


def test_comparison_is_unavailable_when_all_comparison_sources_are_unavailable():
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100,
            "health": {"status": "unavailable"},
            "metrics": {"status": "unavailable"},
            "version": {"status": "unavailable"},
            "logs": {"status": "unavailable", "events": []},
        },
    }
    current = {
        "captured_at": 200,
        "health": {"status": "unavailable"},
        "metrics": {"status": "unavailable"},
        "version": {"status": "unavailable"},
        "logs": {"status": "unavailable", "events": []},
        "docker": {
            "status": "ok",
            "containers": [],
            "source": "Docker Engine",
        },
    }

    comparison = graph._compare_snapshots(baseline, current)

    assert comparison["status"] == "unavailable"
    assert comparison["comparable_sources"] == []
    assert set(comparison["unavailable_sources"]) == {"metrics", "version", "logs"}
    assert comparison["request_deltas"] == {}
    assert comparison["regression_signal"] is False


def test_comparison_marks_one_comparable_source_as_partial_not_success():
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100,
            "metrics": {"status": "unavailable"},
            "version": {"status": "unavailable"},
            "logs": {
                "status": "ok",
                "timestamp": 100,
                "events": [{"ts": 90, "level": "INFO", "msg": "baseline"}],
            },
        },
    }
    current = {
        "captured_at": 200,
        "metrics": {"status": "unavailable"},
        "version": {"status": "unavailable"},
        "logs": {
            "status": "ok",
            "timestamp": 200,
            "events": [{"ts": 150, "level": "ERROR", "msg": "new error"}],
        },
        "docker": {
            "status": "ok",
            "containers": [],
            "source": "Docker Engine",
        },
    }

    comparison = graph._compare_snapshots(baseline, current)

    assert comparison["status"] == "partial"
    assert comparison["comparable_sources"] == ["logs"]
    assert set(comparison["unavailable_sources"]) == {"metrics", "version"}
    assert comparison["new_error_logs"] == current["logs"]["events"]
    assert comparison["regression_signal"] is True


def test_partial_comparison_can_propose_only_evidence_supported_approved_rollback():
    current = _snapshot(version="1.1", errors=3)
    evidence = {
        **current,
        "version": {
            "status": "ok",
            "data": {
                "version": "1.1",
                "history": [
                    {"version": "1.0", "ts": 90},
                    {"version": "1.1", "ts": 150},
                ],
            },
        },
    }
    comparison = {
        "status": "partial",
        "comparable_sources": ["version", "logs"],
        "unavailable_sources": ["metrics"],
        "deployment_changed": True,
        "regression_signal": True,
        "baseline_version": "1.0",
        "current_version": "1.1",
    }

    proposal = graph._propose_node({
        "evidence": evidence,
        "comparison": comparison,
    })["remediation"]

    assert proposal["action"] == "rollback"
    assert proposal["requires_approval"] is True
    assert proposal["status"] == "proposed"


def test_partial_comparison_without_version_evidence_cannot_propose_rollback():
    evidence = {
        "version": {
            "status": "ok",
            "data": {
                "version": "1.1",
                "history": [
                    {"version": "1.0"},
                    {"version": "1.1"},
                ],
            },
        },
    }
    comparison = {
        "status": "partial",
        "comparable_sources": ["logs"],
        "unavailable_sources": ["metrics", "version"],
        "deployment_changed": True,
        "regression_signal": True,
        "baseline_version": "1.0",
        "current_version": "1.1",
    }

    proposal = graph._propose_node({
        "evidence": evidence,
        "comparison": comparison,
    })["remediation"]

    assert proposal["action"] == "investigate"
    assert proposal.get("requires_approval") is False


def _fact_evidence():
    current = {
        "captured_at": 200.0,
        "health": {"status": "ok", "data": {"status": "ok", "version": "1.1"}},
        "metrics": {
            "status": "ok",
            "measurements": {
                "cpu_usage_percent": 92,
                "memory_usage_percent": 85,
            },
            "requests": {"div": {"ok": 92, "error": 8}},
            "latency_observations": {"div": 100},
        },
        "version": {
            "status": "ok",
            "data": {
                "version": "1.1",
                "deployment_status": "failed",
                "history": [
                    {"version": "1.0", "ts": 90},
                    {"version": "1.1", "ts": 150},
                ],
            },
        },
        "logs": {
            "status": "ok",
            "events": [
                {"ts": 175, "level": "ERROR", "msg": "application request failed"},
                {"ts": 180, "level": "WARN", "msg": "one suspicious login event"},
                {"level": "WARN", "msg": "warning with no timestamp"},
            ],
        },
    }
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100.0,
            "version": {"status": "ok", "data": {"version": "1.0"}},
        },
    }
    comparison = {
        "status": "ok",
        "request_deltas": {"div": {"ok": 9, "error": 8}},
        "deployment_changed": True,
        "regression_signal": True,
        "new_error_logs": [current["logs"]["events"][0]],
        "baseline_version": "1.0",
        "current_version": "1.1",
    }
    return current, baseline, comparison


def test_facts_include_cpu_memory_counts_rates_versions_status_and_logs():
    current, baseline, comparison = _fact_evidence()

    facts = graph._observed_facts(current, baseline, comparison)
    statements = [fact["statement"] for fact in facts]

    assert any("CPU utilization is 92%" in statement for statement in statements)
    assert any("Memory utilization is 85%" in statement for statement in statements)
    assert any("Current div/error request counter is 8" in statement for statement in statements)
    assert any("8 errors / 100 reported requests" in statement for statement in statements)
    assert any("Health endpoint status is 'ok'" in statement for statement in statements)
    assert any("Current application version is '1.1'" in statement for statement in statements)
    assert any("Baseline application version is '1.0'" in statement for statement in statements)
    assert any("Deployment status is 'failed'" in statement for statement in statements)
    assert any("Security alert:" in statement for statement in statements)
    assert any("application request failed" in statement for statement in statements)
    assert all({"source", "timestamp"} <= fact.keys() for fact in facts)
    assert next(f for f in facts if "application request failed" in f["statement"])["timestamp"] == 175


def test_missing_telemetry_and_timestamps_are_not_invented():
    current = {
        "captured_at": 10,
        "health": {"status": "unavailable"},
        "metrics": {"status": "unavailable"},
        "version": {"status": "unavailable"},
        "logs": {"status": "ok", "events": [{"level": "WARN", "msg": "no timestamp"}]},
    }

    facts = graph._observed_facts(current, {"status": "unavailable"}, {"status": "unavailable"})

    assert not any("CPU utilization" in fact["statement"] for fact in facts)
    assert not any("Memory utilization" in fact["statement"] for fact in facts)
    assert not any("error rate" in fact["statement"] for fact in facts)
    assert facts[0]["timestamp"] is None


def test_error_rate_requires_error_numerator_and_total_denominator():
    current = {
        "captured_at": 15,
        "metrics": {"status": "ok", "requests": {"div": {"error": 4}}},
    }

    facts = graph._observed_facts(current, {"status": "unavailable"}, {})

    assert not any("error rate" in fact["statement"] for fact in facts)
    assert any("counter is 4" in fact["statement"] for fact in facts)


def test_finding_validation_rejects_invented_rate_and_unconfigured_threshold():
    evidence = {
        "metrics": {
            "status": "ok",
            "measurements": {"cpu_usage_percent": 92, "memory_usage_percent": 85},
            "requests": {"app": {"ok": 25, "error": 8}},
        },
        "baseline_comparison": {"request_deltas": {}},
    }

    invented_rate = graph._validate_finding(
        "Application error rate is 85%.", evidence
    )
    invented_threshold = graph._validate_finding(
        "CPU is above the typical threshold of 70%.", evidence
    )

    assert invented_rate["validation_status"] == "unverified"
    assert "85%" in invented_rate["reasons"][0]
    assert invented_threshold["validation_status"] == "unverified"
    assert any("threshold value 70" in reason for reason in invented_threshold["reasons"])


def test_supported_cpu_and_memory_claims_link_to_exact_evidence_paths():
    evidence = {
        "metrics": {
            "measurements": {
                "cpu_usage_percent": 92,
                "memory_usage_percent": 85,
            },
        },
    }

    cpu = graph._validate_finding("CPU utilization is 92%.", evidence)
    memory = graph._validate_finding("Memory utilization is 85%.", evidence)

    assert cpu["validation_status"] == "numbers_supported"
    assert cpu["evidence_refs"] == ["metrics.measurements.cpu_usage_percent"]
    assert memory["validation_status"] == "numbers_supported"
    assert memory["evidence_refs"] == ["metrics.measurements.memory_usage_percent"]


def test_prometheus_identifier_aliases_and_scientific_notation_are_validated():
    evidence = {
        "prometheus": {
            "metrics": {
                "http_error_rate": {"observations": [{"latest_value": 16.6667}]},
                "latency_p95": {"observations": [{"latest_value": 0.85}]},
                "cpu_utilization": {"observations": [{"latest_value": 88}]},
                "memory_usage": {"observations": [{"latest_value": 78643200}]},
            },
        },
    }

    findings = (
        "Prometheus http_error_rate is 16.6667 percent.",
        "Prometheus latency_p95 is 0.85 seconds.",
        "P95 latency is 0.85 seconds.",
        "Prometheus cpu_utilization is 88 percent_of_one_cpu.",
        "Prometheus memory_usage is 7.86432e+07 bytes.",
    )
    results = [graph._validate_finding(finding, evidence) for finding in findings]

    assert all(result["validation_status"] == "numbers_supported" for result in results)
    assert all(result["evidence_refs"] for result in results)


def test_specialist_evidence_is_scoped_without_dropping_source_observations():
    evidence = {
        "health": {"status": "ok", "data": {"status": "ok"}},
        "metrics": {
            "status": "ok",
            "requests": {"div": {"ok": 10, "error": 2}},
            "latency_observations": {"div": 0.85},
        },
        "system_metrics": {
            "status": "ok",
            "measurements": {"cpu_usage_percent": 88},
        },
        "version": {
            "status": "ok",
            "data": {"version": "1.1", "deployment_status": "completed"},
        },
        "logs": {
            "status": "ok",
            "events": [{"ts": 123, "level": "ERROR", "msg": "request timeout"}],
        },
        "docker": {
            "status": "ok",
            "containers": [{
                "name": "calculator",
                "status": "running",
                "health_status": "healthy",
                "cpu_usage_percent": 92,
                "memory_usage_mib": 700,
                "restart_count": 0,
            }],
        },
        "prometheus": {
            "status": "ok",
            "metrics": {"http_error_rate": {"status": "ok", "value": 20}},
        },
        "code_changes": {
            "status": "provided",
            "source_code": "def calculate_average(values): return sum(values) / len(values)",
        },
    }
    comparison = {
        "status": "partial",
        "deployment_changed": True,
        "regression_signal": True,
        "request_deltas": {"div": {"ok": -2, "error": 2}},
    }
    state = {"evidence": evidence, "comparison": comparison}

    monitoring = graph._specialist_evidence("monitoring", state)
    incident = graph._specialist_evidence("incident", state)
    cicd = graph._specialist_evidence("cicd", state)
    infrastructure = graph._specialist_evidence("infrastructure", state)
    code = graph._specialist_evidence("code", state)

    assert monitoring["metrics"]["requests"]["div"]["error"] == 2
    assert monitoring["prometheus"]["metrics"]["http_error_rate"]["value"] == 20
    assert any(
        fact["source"] == "metrics.requests.div.error"
        for fact in monitoring["verified_observations"]
    )
    assert any(
        fact["source"] == "docker.containers[0].health_status"
        for fact in infrastructure["verified_observations"]
    )
    assert "logs" not in monitoring and "deployment" not in monitoring
    assert incident["deployment"]["data"]["version"] == "1.1"
    assert incident["logs"]["events"][0]["msg"] == "request timeout"
    assert incident["baseline_comparison"]["request_deltas"]["div"]["error"] == 2
    assert cicd["deployment"]["data"]["deployment_status"] == "completed"
    assert cicd["health"]["data"]["status"] == "ok"
    assert cicd["pipeline"]["status"] == "unavailable"
    assert "system_metrics" not in cicd
    assert infrastructure["docker"]["containers"][0]["restart_count"] == 0
    assert infrastructure["system_metrics"]["measurements"]["cpu_usage_percent"] == 88
    assert code["code_changes"] == evidence["code_changes"]
    assert code["deterministic_evidence"]["role"] == "code"
    assert any(
        item["category"] == "code"
        for item in code["deterministic_evidence"]["observations"]
    )


def test_unavailable_source_claims_must_match_that_sources_status():
    evidence = {
        "metrics": {"status": "ok", "error_rate_percent": 16.7},
        "system_metrics": {"status": "unavailable"},
        "docker": {"status": "unavailable", "containers": []},
        "prometheus": {"status": "ok", "metrics": {"request_rate": {"status": "ok"}}},
    }

    docker = graph._validate_finding("Docker metrics are unavailable.", evidence)
    host = graph._validate_finding("System metrics are unavailable.", evidence)
    prometheus = graph._validate_finding(
        "Prometheus metrics are unavailable.", evidence
    )
    pipeline = graph._validate_finding(
        "Pipeline status is unavailable.",
        {"pipeline": {"status": "unavailable"}},
    )

    assert docker["validation_status"] == "evidence_linked"
    assert "docker.status" in docker["evidence_refs"]
    assert host["validation_status"] == "evidence_linked"
    assert "system_metrics.status" in host["evidence_refs"]
    assert prometheus["validation_status"] == "unverified"
    assert any("not reported unavailable" in reason for reason in prometheus["reasons"])
    assert pipeline["validation_status"] == "evidence_linked"
    assert pipeline["evidence_refs"] == ["pipeline.status"]


def test_source_availability_claims_do_not_cross_unrelated_sentences():
    evidence = {
        "system_metrics": {"status": "unavailable"},
        "docker": {"status": "unavailable"},
        "prometheus": {"status": "ok"},
    }

    result = graph._validate_finding(
        "No host or container metrics were provided. "
        "Prometheus telemetry is functioning correctly.",
        evidence,
    )

    assert not any("prometheus is not reported unavailable" in reason
                   for reason in result["reasons"])


def test_container_id_is_not_mistaken_for_a_container_name_or_number():
    evidence = {
        "docker": {
            "containers": [{
                "id": "synthetic-container-001",
                "name": "synthetic-calculator",
                "cpu_usage_percent": 92,
                "memory_usage_bytes": 734003200,
            }],
        },
    }

    result = graph._validate_finding(
        "Container ID is 'synthetic-container-001'; CPU usage is 92% and "
        "memory usage is 734003200 bytes.",
        evidence,
    )

    assert result["validation_status"] == "numbers_supported"
    assert "docker.containers[0].id" in result["evidence_refs"]
    assert not any("container name ID" in reason for reason in result["reasons"])


def test_health_status_does_not_change_the_topic_of_a_memory_value():
    evidence = {
        "health": {"status": "unavailable"},
        "docker": {
            "containers": [{
                "memory_usage_bytes": 734003200,
                "memory_usage_mib": 700,
            }],
        },
    }

    result = graph._validate_finding(
        "Container memory usage is 734003200 bytes (700 MiB). "
        "No health status was included.",
        evidence,
    )

    assert result["validation_status"] == "numbers_supported"
    assert any("memory_usage_mib" in path for path in result["evidence_refs"])


def test_prompt_observation_index_is_not_treated_as_source_evidence():
    evidence = {
        "metrics": {"status": "unavailable"},
        "verified_observations": [{
            "statement": "CPU utilization is 99%.",
            "source": "metrics.measurements.cpu_usage_percent",
            "timestamp": 10,
        }],
    }

    result = graph._validate_finding("CPU utilization is 99%.", evidence)

    assert result["validation_status"] == "unverified"
    assert any("99%" in reason for reason in result["reasons"])


def test_security_classification_cannot_be_supported_by_unavailability_detail():
    evidence = {
        "security_events": {
            "status": "ok",
            "events": [{
                "ts": "2026-11-02T10:00:00Z",
                "msg": "authentication failed for user=demo",
            }],
        },
        "security_telemetry": {
            "status": "unavailable",
            "detail": "No threat intelligence evidence supplied.",
        },
    }

    unsupported = graph._validate_finding(
        "Threat intelligence confirms malicious activity.", evidence
    )
    observed = graph._validate_finding(
        "Authentication failed at 2026-11-02T10:00:00Z.", evidence
    )

    assert unsupported["validation_status"] == "unverified"
    assert any(
        "threat intelligence" in reason.lower()
        for reason in unsupported["reasons"]
    )
    assert observed["validation_status"] == "evidence_linked"
    assert "security_events.events[0].msg" in observed["evidence_refs"]
    assert "security_events.events[0].ts" in observed["evidence_refs"]


def test_ip_addresses_followed_by_sentence_punctuation_remain_grounded():
    evidence = {
        "security_events": {
            "events": [{
                "ts": "2026-11-02T10:00:00Z",
                "msg": "authentication failed from source_ip=192.0.2.10",
            }],
        },
    }

    result = graph._validate_finding(
        "Observed source IP: 192.0.2.10.",
        evidence,
    )

    assert result["validation_status"] == "evidence_linked"
    assert "security_events.events[0].msg" in result["evidence_refs"]
    assert not result["reasons"]


def test_unsupported_factual_claim_in_recommendation_is_flagged(monkeypatch):
    evidence = _security_fixture()
    state = {
        "query": "triage suspicious authentication events",
        "evidence": evidence,
        "comparison": {"regression_signal": False, "deployment_changed": False},
        "trace": [],
    }

    def mocked_analyze(agent, task, supplied_evidence):
        assert agent == "security"
        assert len(supplied_evidence["security_events"]["events"]) == 2
        analysis = {
            "summary": "Authentication events require review.",
            "findings": ["Authentication failed for the synthetic test account."],
            "confidence": 0.7,
            "recommended_checks": [
                "Configure a source that will provide threat intelligence for the IP."
            ],
        }
        return {
            "status": "ok",
            "agent": agent,
            "analysis": analysis,
            "raw_content": json.dumps(analysis),
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", mocked_analyze)

    result = graph._specialists_node(state)["specialists"]["results"]["security"]

    recommendation = result["validated_recommended_checks"][0]
    assert recommendation["validation_status"] == "unverified"
    assert any(
        "threat intelligence" in reason.lower()
        for reason in recommendation["reasons"]
    )


def test_error_rate_claim_is_supported_only_by_matching_counter_calculation():
    evidence = {
        "metrics": {
            "requests": {"app": {"ok": 25, "error": 8}},
        },
        "baseline_comparison": {"request_deltas": {}},
    }

    supported = graph._validate_finding(
        "Observed application error rate is 24.24%.", evidence
    )

    assert supported["validation_status"] == "numbers_supported"
    assert any("error=8, total=33" in path for path in supported["evidence_refs"])


def test_failed_deployment_claim_requires_explicit_deployment_evidence():
    missing = graph._validate_finding(
        "The deployment failed.", {"version": {"data": {"version": "1.1"}}}
    )
    observed = graph._validate_finding(
        "The deployment failed.",
        {"version": {"data": {"deployment_status": "failed"}}},
    )
    invented_success = graph._validate_finding(
        "Deployment succeeded for version 1.1.",
        {"version": {"data": {"version": "1.1"}}},
    )

    assert missing["validation_status"] == "unverified"
    assert observed["validation_status"] == "evidence_linked"
    assert observed["evidence_refs"] == ["version.data.deployment_status"]
    assert invented_success["validation_status"] == "unverified"


def test_conflicting_specialist_numeric_claims_are_reported_not_resolved(monkeypatch):
    current, _, comparison = _fact_evidence()
    calls = []

    def mocked_analyze(agent, task, supplied_evidence):
        calls.append(agent)
        if agent == "monitoring":
            finding = "CPU utilization is 92%."
        elif agent == "incident":
            finding = "CPU utilization is 70%."
        else:
            finding = "Insufficient evidence: no additional metric-specific finding."
        output = {
            "summary": f"{agent} specialist response",
            "findings": [finding],
            "confidence": 0.9,
            "recommended_checks": [],
        }
        return {
            "status": "ok",
            "agent": agent,
            "raw_content": json.dumps(output),
            "analysis": output,
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", mocked_analyze)
    state = {
        "query": "synthetic incident error security",
        "evidence": current,
        "baseline": {"status": "ok", "snapshot": {"captured_at": 100}},
        "comparison": comparison,
        "trace": [],
    }
    state.update(graph._specialists_node(state))

    diagnosis = graph._diagnose_node(state)["diagnosis"]

    assert calls == list(graph.SPECIALIST_ORDER)
    assert diagnosis["specialist_conflicts"][0]["topic"] == "cpu"
    assert "observed evidence remains authoritative" in diagnosis["specialist_conflicts"][0]["resolution"]
    assert any("CPU utilization is 70%" in claim["claim"] for claim in diagnosis["unverified_claims"])
    assert state["specialists"]["results"]["monitoring"]["original_model_output"] == (
        json.dumps({
            "summary": "monitoring specialist response",
            "findings": ["CPU utilization is 92%."],
            "confidence": 0.9,
            "recommended_checks": [],
        })
    )
