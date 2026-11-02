import pytest

from agents import evidence_extractor as extractor, graph


def _available_fixture():
    return {
        "captured_at": 200,
        "metrics": {
            "status": "ok",
            "source": "application /metrics",
            "timestamp": 195,
            "request_counters": {"status": "ok"},
            "requests": {"div": {"ok": 8, "error": 2}},
            "request_totals": {"div": 10},
            "latency_observations": {
                "status": "ok",
                "by_operation": {"div": 0.85},
            },
        },
        "prometheus": {
            "status": "ok",
            "source": "Prometheus HTTP API",
            "timestamp": 198,
            "metrics": {
                "request_rate": {
                    "status": "ok",
                    "unit": "requests/second",
                    "observations": [{
                        "labels": {"op": "div", "status": "error"},
                        "latest_value": 2.0,
                        "latest_timestamp": 198,
                        "stale": False,
                    }],
                },
                "latency_p95": {
                    "status": "ok",
                    "unit": "seconds",
                    "observations": [{
                        "labels": {},
                        "latest_value": 0.85,
                        "latest_timestamp": 198,
                        "stale": False,
                    }],
                },
            },
        },
        "version": {
            "status": "ok",
            "source": "calculator /admin/version",
            "timestamp": 190,
            "data": {
                "version": "1.1",
                "deployment_status": "completed",
                "history": [
                    {"version": "1.0", "ts": 100},
                    {"version": "1.1", "ts": 190},
                ],
            },
        },
        "health": {
            "status": "ok",
            "source": "calculator /health",
            "timestamp": 198,
            "data": {"status": "ok", "http_status": 200},
        },
        "docker": {
            "status": "ok",
            "source": "Docker Engine fixture",
            "timestamp": 198,
            "containers": [{
                "id": "container-id-001",
                "name": "calculator",
                "image": "calculator:1.1",
                "status": "running",
                "health_status": "healthy",
                "cpu_usage_percent": 92.0,
                "memory_usage_bytes": 734003200,
                "memory_limit_bytes": 1073741824,
                "memory_usage_percent": 68.36,
                "network_rx_bytes": 1000,
                "network_tx_bytes": 2000,
                "block_read_bytes": 3000,
                "block_write_bytes": 4000,
                "restart_count": 0,
                "started_at": 150,
                "uptime_seconds": 48,
                "metrics_status": "ok",
                "source": "Docker Engine fixture",
                "timestamp": 198,
            }],
        },
        "system_metrics": {
            "status": "ok",
            "source": "host operating system",
            "timestamp": 198,
            "measurements": {
                "cpu_utilization_percent": 40.0,
                "memory_utilization_percent": 50.0,
            },
        },
        "process": {
            "source": "application process fixture",
            "timestamp": 198,
            "cpu_percent": 5.0,
            "resident_memory_bytes": 62914560,
        },
        "logs": {
            "status": "ok",
            "source": "logs/app.log",
            "timestamp": 198,
            "events": [
                {
                    "ts": "2026-11-02T09:00:00+05:30",
                    "level": "ERROR",
                    "msg": (
                        "ZeroDivisionError: division by zero at "
                        "File \"calculator_app/service.py\", line 18, in calculate"
                    ),
                },
                {
                    "ts": "2026-11-02T09:01:00+05:30",
                    "level": "WARN",
                    "msg": "authentication failed for user=test source_ip=192.0.2.10",
                },
                {
                    "ts": "2026-11-02T09:02:00+05:30",
                    "level": "WARN",
                    "msg": "authentication failed for user=test source_ip=192.0.2.10",
                },
                {
                    "ts": "2026-11-02T09:03:00+05:30",
                    "level": "INFO",
                    "msg": "authentication successful for user=test source_ip=192.0.2.10",
                },
                {
                    "ts": "2026-11-02T09:04:00+05:30",
                    "level": "INFO",
                    "msg": "deployed v1.1",
                },
            ],
        },
        "code_changes": {
            "status": "provided",
            "source": "synthetic code fixture",
            "timestamp": 198,
            "exception_type": "ZeroDivisionError",
            "error_message": "division by zero",
            "source_code": "def calculate(values): return 1 / len(values)",
            "stack_trace": (
                "Traceback (most recent call last):\n"
                "  File \"calculator_app/service.py\", line 18, in calculate\n"
                "ZeroDivisionError: division by zero"
            ),
        },
    }


def _select(result, category, metric_or_event):
    return [
        item for item in result["observations"]
        if item["category"] == category
        and item["metric_or_event"] == metric_or_event
    ]


def test_extracts_application_counts_rates_latency_and_prometheus_series():
    evidence = _available_fixture()

    extracted = extractor.validate_extraction(
        extractor.extract_evidence(evidence, now=200)
    )

    assert _select(extracted, "application_metrics", "div_total_request_count")[0]["value"] == 10
    assert _select(extracted, "application_metrics", "div_error_rate")[0]["value"] == 20
    assert _select(extracted, "application_metrics", "div_p95_latency")[0]["unit"] == "seconds"
    assert _select(extracted, "application_metrics", "request_rate")[0]["value"] == 2.0
    assert _select(extracted, "application_metrics", "latency_p95")[0]["source_path"] == (
        "prometheus.metrics.latency_p95.observations[0]"
    )


def test_extracts_deployment_baseline_event_and_timestamped_log():
    evidence = _available_fixture()
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100,
            "version": {"status": "ok", "source": "baseline", "data": {"version": "1.0"}},
        },
    }

    result = extractor.extract_evidence(
        evidence, baseline, {"deployment_events": [{
            "action": "rollback",
            "version": "1.0",
            "timestamp": 120,
            "source": "application log",
        }]}, now=200,
    )

    assert _select(result, "deployment", "previous_application_version")[0]["value"] == "1.0"
    assert _select(result, "deployment", "application_version_change")[0]["change"] is True
    assert _select(result, "deployment", "rollback")[0]["timestamp"] == 120
    assert _select(result, "deployment", "deployment_log_event")[0]["evidence_text"] == (
        "deployed v1.1"
    )


def test_extracts_container_host_process_and_source_metadata():
    result = extractor.extract_evidence(_available_fixture(), now=200)

    cpu = _select(result, "infrastructure", "container_cpu_usage_percent")[0]
    assert cpu["value"] == 92
    assert cpu["source"] == "Docker Engine fixture"
    assert cpu["source_path"] == "docker.containers[0].cpu_usage_percent"
    assert cpu["unit"] == "percent"
    assert _select(result, "infrastructure", "container_restart_count")[0]["value"] == 0
    assert _select(result, "infrastructure", "cpu_utilization_percent")[0]["source_path"] == (
        "system_metrics.measurements.cpu_utilization_percent"
    )
    assert _select(result, "infrastructure", "resident_memory_bytes")[0]["unit"] == "bytes"


def test_extracts_authentication_events_ip_timestamps_and_noncausal_sequence():
    result = extractor.extract_evidence(_available_fixture(), now=200)

    failures = _select(result, "security", "authentication_failure")
    success = _select(result, "security", "authentication_success")
    sequence = _select(result, "security", "repeated_failures_followed_by_success")

    assert len(failures) == 2
    assert success[0]["timestamp"] == "2026-11-02T09:03:00+05:30"
    assert _select(result, "security", "source_ip")[0]["value"] == "192.0.2.10"
    assert sequence[0]["value"] == {"failed_event_count": 2, "success_event_count": 1}
    assert "does not establish malicious intent" in sequence[0]["evidence_text"]


def test_extracts_exception_stack_frame_and_preserves_original_log_path():
    result = extractor.extract_evidence(_available_fixture(), now=200)

    exception = _select(result, "code", "exception_type")
    frame = _select(result, "code", "stack_trace_frame")

    assert any(item["value"] == "ZeroDivisionError" for item in exception)
    assert any(
        item["value"] == {
            "file": "calculator_app/service.py",
            "line": 18,
            "function": "calculate",
        }
        for item in frame
    )
    assert any(item["source_path"] == "code_changes.stack_trace" for item in frame)


def test_unavailable_values_are_missing_not_zero_and_stale_is_explicit():
    evidence = {
        "captured_at": 1000,
        "metrics": {"status": "unavailable", "detail": "scrape failed"},
        "prometheus": {
            "status": "partial",
            "source": "Prometheus",
            "metrics": {
                "request_rate": {
                    "status": "ok",
                    "unit": "requests/second",
                    "observations": [{
                        "latest_value": 5,
                        "latest_timestamp": 100,
                        "stale": True,
                    }],
                },
            },
        },
        "docker": {"status": "unavailable", "containers": []},
        "logs": {"status": "unavailable"},
    }

    result = extractor.extract_evidence(evidence, now=1000)

    assert result["status"] == "partial"
    assert not any(
        item["value"] == 0
        for item in result["observations"]
        if item["category"] == "application_metrics"
    )
    assert _select(result, "application_metrics", "request_rate")[0]["status"] == "stale"
    assert any(item["source_path"] == "metrics" for item in result["missing_evidence"])
    assert any(item["category"] == "infrastructure" for item in result["missing_evidence"])


def test_malformed_evidence_is_reported_without_stopping_other_extraction():
    evidence = _available_fixture()
    evidence["metrics"]["requests"]["div"]["error"] = float("nan")
    evidence["docker"]["containers"].append("malformed container entry")

    result = extractor.extract_evidence(evidence, now=200)

    assert result["status"] == "partial"
    assert any(
        item["status"] == "invalid"
        and item["source_path"] == "metrics.requests.div.error"
        for item in result["missing_evidence"]
    )
    assert any(
        item["metric_or_event"] == "container_cpu_usage_percent"
        for item in result["observations"]
    )


def test_incorrect_prometheus_units_are_invalid_not_silently_normalized():
    result = extractor.extract_evidence({
        "prometheus": {
            "status": "ok",
            "metrics": {
                "latency_p95": {
                    "status": "ok",
                    "unit": "milliseconds",
                    "observations": [{
                        "latest_value": 850,
                        "latest_timestamp": 100,
                        "stale": False,
                    }],
                },
            },
        },
    }, now=100)

    assert not _select(result, "application_metrics", "latency_p95")
    assert any(
        item["source_path"] == "prometheus.metrics.latency_p95.unit"
        and item["status"] == "invalid"
        for item in result["missing_evidence"]
    )


def test_role_packaging_delivers_only_relevant_deterministic_observations():
    result = extractor.extract_evidence(_available_fixture(), now=200)
    by_role = {
        role: extractor.package_for_role(result, role, raw_evidence=_available_fixture())
        for role in extractor.ROLE_CATEGORIES
    }

    assert all(package["observations"] for package in by_role.values())
    assert all(
        item["category"] in extractor.ROLE_CATEGORIES[role]
        for role, package in by_role.items()
        for item in package["observations"]
    )
    assert not any(
        item["category"] in {"security", "infrastructure"}
        for item in by_role["code"]["observations"]
    )
    assert not any(
        item["category"] != "security"
        for item in by_role["security"]["observations"]
    )
    assert by_role["security"]["raw_evidence_available"] is True


def test_strict_schema_rejects_bad_types_extra_fields_and_invalid_confidence():
    result = extractor.extract_evidence(_available_fixture(), now=200)
    observation = dict(result["observations"][0])

    with pytest.raises(ValueError, match="confidence"):
        extractor.validate_observation({**observation, "confidence": True})
    with pytest.raises(ValueError, match="Invalid observation fields"):
        extractor.validate_observation({**observation, "unexpected": "value"})
    with pytest.raises(ValueError, match="finite JSON-compatible"):
        extractor.validate_observation({**observation, "value": float("inf")})


def test_all_six_graph_roles_receive_extraction_and_missing_evidence_records(monkeypatch):
    calls = {}
    evidence = _available_fixture()

    def analyze(agent, task, supplied):
        calls[agent] = supplied
        return {
            "status": "ok",
            "analysis": {
                "summary": "Observed evidence retained.",
                "findings": [],
                "confidence": 0.5,
                "recommended_checks": [],
            },
            "raw_content": "{}",
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)
    state = {
        "query": "security authentication error after deployment",
        "evidence": evidence,
        "baseline": {"status": "unavailable", "detail": "not saved"},
        "comparison": {
            "status": "partial",
            "deployment_changed": True,
            "regression_signal": True,
        },
        "trace": [],
    }
    results = graph._specialists_node(state)["specialists"]["results"]

    assert set(calls) == set(graph.SPECIALIST_ORDER)
    for role, supplied in calls.items():
        package = supplied["deterministic_evidence"]
        assert package["role"] == role
        assert package["observations"]
        assert results[role]["evidence_delivery"]["delivery_complete"] is True
        assert results[role]["deterministic_evidence"]["observations"] == package["observations"]
    assert "docker" not in calls["security"]
    assert all(
        item["category"] == "security"
        for item in calls["security"]["deterministic_evidence"]["observations"]
    )


def test_final_diagnosis_keeps_deterministic_observations_when_model_omits_them(
    monkeypatch,
):
    evidence = _available_fixture()

    def analyze(agent, task, supplied):
        return {
            "status": "ok",
            "analysis": {
                "summary": "No details.",
                "findings": [],
                "confidence": 0.1,
                "recommended_checks": [],
            },
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)
    state = {
        "query": "monitor calculator metrics",
        "evidence": evidence,
        "baseline": {"status": "unavailable"},
        "comparison": {"status": "partial", "regression_signal": False},
        "trace": [],
    }
    state.update(graph._specialists_node(state))
    diagnosis = graph._diagnose_node(state)["diagnosis"]

    assert any(
        item["category"] == "infrastructure"
        and item["metric_or_event"] == "container_cpu_usage_percent"
        for item in diagnosis["verified_observations"]
    )
    assert diagnosis["llm_interpretations"]
    assert diagnosis["recommendations"] == []
    assert diagnosis["specialist_evidence_delivery"]["monitoring"]["delivery_complete"]
