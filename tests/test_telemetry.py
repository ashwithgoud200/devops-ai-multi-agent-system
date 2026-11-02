import json
import io

import requests

from agents import graph, telemetry


class _Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def _prometheus_response(monkeypatch, text):
    monkeypatch.setattr(graph.requests, "get", lambda *args, **kwargs: _Response(text))


def test_prometheus_request_counters_and_histogram_are_collected(monkeypatch):
    _prometheus_response(
        monkeypatch,
        "\n".join(
            [
                "# TYPE calc_requests_total counter",
                'calc_requests_total{op="add",status="ok"} 12',
                'calc_requests_total{op="add",status="error"} 3',
                "# TYPE calc_latency_seconds histogram",
                'calc_latency_seconds_count{op="add"} 15',
            ]
        ),
    )

    result = graph._get_metrics()

    assert result["status"] == "ok"
    assert result["request_counters"]["status"] == "ok"
    assert result["requests"] == {"add": {"ok": 12, "error": 3}}
    assert result["request_totals"] == {"add": 15}
    assert result["latency_observations"]["by_operation"] == {"add": 15}
    assert result["source"].endswith("/metrics")
    assert isinstance(result["timestamp"], float)


def test_prometheus_unavailable_and_incomplete_metrics_are_not_zero(monkeypatch):
    monkeypatch.setattr(
        graph.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.ConnectionError("Prometheus exporter unavailable")
        ),
    )
    unavailable = graph._get_metrics()
    assert unavailable["status"] == "unavailable"
    assert unavailable["request_counters"]["status"] == "unavailable"

    _prometheus_response(
        monkeypatch,
        "# TYPE calc_requests_total counter\n# TYPE calc_latency_seconds histogram\n",
    )
    empty = graph._get_metrics()
    assert empty["status"] == "partial"
    assert empty["request_counters"]["status"] == "partial"
    assert empty["latency_observations"]["status"] == "partial"
    assert empty["requests"] == {}
    assert not graph._request_metrics_available(empty)


def test_invalid_prometheus_sample_is_reported_as_unavailable(monkeypatch):
    _prometheus_response(
        monkeypatch,
        "\n".join(
            [
                "# TYPE calc_requests_total counter",
                'calc_requests_total{op="add",status="ok"} NaN',
                "# TYPE calc_latency_seconds histogram",
            ]
        ),
    )

    result = graph._get_metrics()

    assert result["status"] == "unavailable"
    assert "invalid counter samples" in result["detail"]

    _prometheus_response(
        monkeypatch,
        "\n".join(
            [
                "# TYPE calc_requests_total counter",
                'calc_requests_total{op="add",status="ok"} 1',
                "# TYPE calc_latency_seconds histogram",
                'calc_latency_seconds_count{op="add"} -1',
            ]
        ),
    )
    invalid_latency_count = graph._get_metrics()
    assert invalid_latency_count["status"] == "unavailable"
    assert "invalid counter samples" in invalid_latency_count["detail"]


def test_system_metrics_collect_cpu_memory_and_timestamp(monkeypatch):
    cpu_samples = iter([(100, 25), (200, 45)])
    monkeypatch.setattr(telemetry, "_read_cpu_times", lambda: next(cpu_samples))
    monkeypatch.setattr(telemetry, "_read_memory", lambda: (1000, 250))
    monkeypatch.setattr(telemetry.time, "sleep", lambda _: None)
    monkeypatch.setattr(telemetry.time, "time", lambda: 123.0)

    result = telemetry.collect_system_metrics(sample_interval=0)

    assert result["status"] == "ok"
    assert result["measurements"]["cpu_utilization_percent"] == 80
    assert result["measurements"]["memory_utilization_percent"] == 75
    assert result["measurements"]["memory_total_bytes"] == 1000
    assert result["timestamp"] == 123.0
    assert result["source"]


def test_linux_cpu_counter_avoids_double_counting_guest_time(monkeypatch):
    cpu_line = "cpu 100 20 30 400 10 5 5 2 50 4\n"
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(cpu_line))

    total, idle = telemetry._linux_cpu_times()

    assert total == sum([100, 20, 30, 400, 10, 5, 5, 2])
    assert idle == 410


def test_partial_system_metric_failure_preserves_available_measurement(monkeypatch):
    monkeypatch.setattr(
        telemetry, "_read_cpu_times",
        lambda: (_ for _ in ()).throw(OSError("CPU counters unavailable")),
    )
    monkeypatch.setattr(telemetry, "_read_memory", lambda: (1000, 250))
    monkeypatch.setattr(telemetry.time, "time", lambda: 123.0)

    result = telemetry.collect_system_metrics()

    assert result["status"] == "partial"
    assert "cpu_utilization_percent" not in result["measurements"]
    assert result["measurements"]["memory_utilization_percent"] == 75
    assert "CPU counters unavailable" in result["detail"]


def test_system_telemetry_failure_does_not_discard_application_evidence(monkeypatch):
    monkeypatch.setattr(
        graph,
        "collect_system_metrics",
        lambda: (_ for _ in ()).throw(OSError("host counters unavailable")),
    )
    monkeypatch.setattr(graph, "_get_json", lambda path: {"status": "ok", "data": {}})
    monkeypatch.setattr(
        graph,
        "_get_metrics",
        lambda: {"status": "ok", "request_counters": {"status": "ok"}},
    )
    monkeypatch.setattr(
        graph,
        "_read_logs",
        lambda: {"status": "ok", "events": [], "source": "logs/app.log"},
    )
    docker = {
        "status": "unavailable",
        "source": "Docker Engine via read-only Docker CLI",
        "timestamp": 123.0,
        "containers": [],
        "errors": ["Docker Engine stopped"],
        "detail": "Docker Engine stopped",
    }
    monkeypatch.setattr(graph, "collect_docker_metrics", lambda: docker)
    monkeypatch.setattr(
        graph,
        "collect_prometheus_metrics",
        lambda: {
            "status": "unavailable",
            "source": "Prometheus HTTP API",
            "metrics": {},
            "detail": "not collected in this offline test",
        },
    )

    evidence = graph._collect_evidence()

    assert evidence["health"]["status"] == "ok"
    assert evidence["metrics"]["status"] == "ok"
    assert evidence["logs"]["status"] == "ok"
    assert evidence["system_metrics"]["status"] == "unavailable"
    assert evidence["docker"] == docker
    assert "host counters unavailable" in evidence["system_metrics"]["detail"]


def test_timestamped_json_logs_are_collected_and_malformed_lines_are_partial(
    monkeypatch, tmp_path
):
    log_path = tmp_path / "app.log"
    log_path.write_text(
        json.dumps({"ts": 1700000000, "level": "ERROR", "msg": "failed"}) + "\n"
        "{invalid json\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEVOPS_LOG_PATH", str(log_path))

    result = graph._read_logs()

    assert result["status"] == "partial"
    assert result["source"] == str(log_path)
    assert result["events"] == [
        {"ts": 1700000000, "level": "ERROR", "msg": "failed"}
    ]
    assert result["malformed_lines"] == 1


def test_log_reader_preserves_valid_neighbors_and_entries_without_timestamps(
    monkeypatch, tmp_path
):
    log_path = tmp_path / "events.jsonl"
    log_path.write_bytes(
        b'{"ts": 100, "level": "INFO", "version": "1.0"}\n'
        b'{malformed json\n'
        b'{"level": "ERROR", "msg": "missing timestamp"}\n'
        b'\xff\n'
        b'{"ts": 200, "level": "INFO", "msg": "after malformed lines"}\n'
    )
    monkeypatch.setenv("DEVOPS_LOG_PATH", str(log_path))

    result = graph._read_logs()

    assert result["status"] == "partial"
    assert result["malformed_lines"] == 2
    assert [event.get("msg") for event in result["events"]] == [
        None,
        "missing timestamp",
        "after malformed lines",
    ]
    assert result["events"][1].get("ts") is None
    assert result["source"] == str(log_path.resolve())
    assert result["file_cursor"]["offset"] == log_path.stat().st_size


def test_unavailable_log_path_is_explicit(monkeypatch, tmp_path):
    log_path = tmp_path / "missing.jsonl"
    monkeypatch.setenv("DEVOPS_LOG_PATH", str(log_path))

    result = graph._read_logs()

    assert result["status"] == "unavailable"
    assert result["events"] == []
    assert result["source"] == str(log_path)
    assert result["detail"]
    assert "file_cursor" not in result


def test_replaced_log_file_does_not_make_old_entries_appear_new(monkeypatch, tmp_path):
    log_path = tmp_path / "app.log"
    monkeypatch.setenv("DEVOPS_LOG_PATH", str(log_path))
    log_path.write_text(
        "".join(
            json.dumps({"ts": 100 + index, "level": "ERROR", "msg": f"old-{index}-" + "x" * 80})
            + "\n"
            for index in range(120)
        ),
        encoding="utf-8",
    )
    baseline_logs = graph._read_logs()
    baseline_cursor = baseline_logs["file_cursor"]
    assert baseline_cursor["offset"] > 0

    log_path.write_text(
        "".join(
            json.dumps({"ts": 10000 + index, "level": "ERROR", "msg": f"replacement-{index}-" + "y" * 100})
            + "\n"
            for index in range(150)
        ),
        encoding="utf-8",
    )
    current_logs = graph._read_logs(baseline_cursor)
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 200,
            "version": {"status": "ok", "data": {"version": "1.0"}},
            "metrics": {"status": "unavailable"},
            "logs": baseline_logs,
        },
    }
    comparison = graph._compare_snapshots(
        baseline,
        {
            "version": {"status": "ok", "data": {"version": "1.0"}},
            "metrics": {"status": "unavailable"},
            "logs": current_logs,
        },
    )

    assert current_logs["window_mode"] == "tail"
    assert comparison["logs_window_status"] == "unavailable"
    assert comparison["new_logs"] == []
    assert comparison["new_error_logs"] == []


def test_log_cursor_and_graph_comparison_detect_deploy_errors_without_metrics(
    monkeypatch, tmp_path
):
    log_path = tmp_path / "app.log"
    baseline_path = tmp_path / "baseline.json"
    monkeypatch.setenv("DEVOPS_LOG_PATH", str(log_path))
    monkeypatch.setattr(graph, "BASELINE_PATH", baseline_path)
    log_path.write_text(
        json.dumps({"ts": 10, "level": "ERROR", "msg": "old error", "version": "0.9"}) + "\n"
        + json.dumps({"ts": 20, "level": "INFO", "msg": "normal v1.0 operation", "version": "1.0"}) + "\n",
        encoding="utf-8",
    )

    app = {
        "version": "1.0",
        "history": [{"version": "1.0", "ts": 5}],
    }

    def get_json(path):
        data = (
            {"status": "ok", "version": app["version"]}
            if path == "/health"
            else {"version": app["version"], "history": app["history"]}
        )
        return {
            "status": "ok",
            "source": f"http://service{path}",
            "timestamp": 100.0 if app["version"] == "1.0" else 200.0,
            "data": data,
        }

    unavailable_metrics = {
        "status": "partial",
        "request_counters": {"status": "unavailable"},
        "latency_observations": {"status": "unavailable"},
        "source": "http://service/metrics",
    }
    monkeypatch.setattr(graph, "_get_json", get_json)
    monkeypatch.setattr(graph, "_get_metrics", lambda: unavailable_metrics)
    monkeypatch.setattr(
        graph,
        "collect_system_metrics",
        lambda: {
            "status": "unavailable",
            "source": "host OS",
            "timestamp": 100.0,
            "measurements": {},
            "detail": "not available in this test",
        },
    )
    monkeypatch.setattr(
        graph,
        "collect_docker_metrics",
        lambda: {
            "status": "unavailable",
            "source": "Docker Engine test stub",
            "timestamp": 100.0,
            "containers": [],
            "errors": ["not collected in this offline test"],
            "detail": "not collected in this offline test",
        },
    )
    monkeypatch.setattr(
        graph,
        "collect_prometheus_metrics",
        lambda: {
            "status": "unavailable",
            "source": "Prometheus HTTP API",
            "metrics": {},
            "detail": "not collected in this offline test",
        },
    )

    baseline = graph.save_baseline()
    assert baseline["version"]["data"]["version"] == "1.0"
    assert baseline["logs"]["file_cursor"]["offset"] == log_path.stat().st_size

    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps({
            "level": "INFO",
            "msg": "normal version 1.0 operation without timestamp",
            "version": "1.0",
        }) + "\n")
        log_file.write(json.dumps({
            "ts": 150,
            "level": "INFO",
            "msg": "deployed v1.1",
        }) + "\n")
        log_file.write(json.dumps({
            "ts": 160,
            "level": "ERROR",
            "msg": "v1.1 regression: div handler crashed",
            "version": "1.1",
        }) + "\n")
        log_file.write(json.dumps({
            "ts": 170,
            "level": "ERROR",
            "msg": "v1.1 regression: div handler crashed",
            "version": "1.1",
        }) + "\n")
    app.update(
        version="1.1",
        history=[
            {"version": "1.0", "ts": 5},
            {"version": "1.1", "ts": 150},
        ],
    )

    collected = graph._collect_node({})
    compared = graph._compare_node(collected)
    comparison = compared["comparison"]

    assert compared["baseline"]["snapshot"]["version"]["data"]["version"] == "1.0"
    assert comparison["baseline_version"] == "1.0"
    assert comparison["current_version"] == "1.1"
    assert comparison["detected_deployment_version"] == "1.1"
    assert comparison["deployment_changed"] is True
    assert [event["msg"] for event in comparison["new_error_logs"]] == [
        "v1.1 regression: div handler crashed",
        "v1.1 regression: div handler crashed",
    ]
    assert all(event.get("msg") != "old error" for event in comparison["new_logs"])
    assert comparison["regression_signal"] is True
    assert comparison["status"] == "partial"
    assert comparison["comparable_sources"] == ["version", "logs"]
    assert comparison["baseline_metrics_status"] == "partial"
    assert comparison["current_metrics_status"] == "partial"
    assert comparison["request_deltas"] == {}
    assert collected["evidence"]["metrics"]["request_counters"]["status"] == "unavailable"
    assert collected["evidence"]["system_metrics"]["status"] == "unavailable"

    facts = graph._observed_facts(
        collected["evidence"],
        compared["baseline"],
        comparison,
    )
    assert any("Explicit deploy event records version '1.1'" in fact["statement"] for fact in facts)
    assert any("div handler crashed" in fact["statement"] for fact in facts)


def test_deployment_events_require_explicit_deployment_message():
    assert graph._deployment_log_event(
        {"msg": "deployed v1.1", "version": "1.1"}
    ) == {"action": "deploy", "version": "1.1"}
    assert graph._deployment_log_event(
        {"msg": "v1.1 regression: div handler crashed", "version": "1.1"}
    ) is None
    assert graph._deployment_log_event({"version": "1.1"}) is None


def test_version_and_deployment_remain_distinct_when_endpoint_disagrees_with_log():
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100,
            "version": {"status": "ok", "data": {"version": "1.0"}},
            "metrics": {"status": "unavailable"},
            "logs": {
                "status": "ok",
                "timestamp": 100,
                "events": [{"ts": 150, "level": "ERROR", "msg": "old future-dated error"}],
            },
        },
    }
    current = {
        "captured_at": 200,
        "version": {"status": "ok", "data": {"version": "1.0"}},
        "metrics": {"status": "unavailable"},
        "logs": {
            "status": "ok",
            "events": [{"ts": 150, "level": "INFO", "msg": "deployed v1.1"}],
        },
    }

    comparison = graph._compare_snapshots(baseline, current)

    assert comparison["baseline_version"] == "1.0"
    assert comparison["current_version"] == "1.0"
    assert comparison["detected_deployment_version"] == "1.1"
    assert comparison["deployment_changed"] is True


def test_legacy_log_window_requires_timestamp_and_missing_versions_stay_unavailable():
    baseline = {
        "status": "ok",
        "snapshot": {
            "captured_at": 100,
            "version": {"status": "ok", "data": {"history": []}},
            "metrics": {"status": "unavailable"},
            "logs": {
                "status": "ok",
                "timestamp": 100,
                "events": [{"ts": 150, "level": "ERROR", "msg": "old future-dated error"}],
            },
        },
    }
    current = {
        "captured_at": 200,
        "version": {"status": "ok", "data": {"history": []}},
        "metrics": {"status": "unavailable"},
        "logs": {
            "status": "ok",
            "events": [
                {"level": "ERROR", "msg": "no timestamp"},
                {"ts": 150, "level": "ERROR", "msg": "old future-dated error"},
                {"ts": 90, "level": "ERROR", "msg": "old error"},
                {"ts": 150, "level": "INFO", "version": "1.1"},
            ],
        },
    }

    comparison = graph._compare_snapshots(baseline, current)

    assert comparison["baseline_version"] is None
    assert comparison["current_version"] is None
    assert comparison["deployment_changed"] is False
    assert comparison["new_logs"] == [
        {"ts": 150, "level": "INFO", "version": "1.1"}
    ]
    assert comparison["new_error_logs"] == []
    assert comparison["regression_signal"] is False


def test_telemetry_availability_marks_missing_host_and_deployment_data():
    availability = graph._telemetry_availability(
        {
            "health": {"status": "ok", "source": "http://service/health"},
            "metrics": {
                "status": "partial",
                "request_counters": {"status": "partial"},
                "source": "http://service/metrics",
            },
            "system_metrics": {
                "status": "partial",
                "source": "/proc/stat and /proc/meminfo",
                "measurements": {"memory_utilization_percent": 42.0},
            },
            "version": {
                "status": "ok",
                "source": "http://service/admin/version",
                "data": {"version": "1.2", "history": [{"version": "1.2"}]},
            },
            "logs": {"status": "unavailable", "source": "logs/app.log"},
        }
    )

    assert availability["cpu_utilization"]["status"] == "unavailable"
    assert availability["memory_utilization"]["status"] == "ok"
    assert availability["previous_deployment_version"]["status"] == "unavailable"
    assert availability["deployment_status"]["status"] == "unavailable"
    assert availability["application_logs"]["status"] == "unavailable"
    assert "does not expose deployment status" in availability["deployment_status"]["detail"]


def test_monitoring_specialist_is_selected_for_host_metrics_without_prometheus():
    selected = graph._select_specialists({
        "query": "review host monitoring",
        "evidence": {
            "metrics": {"status": "unavailable"},
            "system_metrics": {
                "status": "partial",
                "measurements": {"cpu_utilization_percent": 44.0},
            },
            "health": {"status": "unavailable"},
            "logs": {"events": []},
        },
        "comparison": {},
    })

    assert selected == ["monitoring"]


def test_system_measurements_are_facts_only_when_present_and_valid():
    evidence = {
        "captured_at": 200,
        "system_metrics": {
            "status": "partial",
            "source": "host operating system",
            "timestamp": 199,
            "measurements": {
                "memory_utilization_percent": 56.5,
                "cpu_utilization_percent": float("nan"),
            },
        },
        "metrics": {"status": "unavailable"},
    }

    facts = graph._observed_facts(
        evidence, {"status": "unavailable"}, {"status": "unavailable"}
    )

    assert [fact["statement"] for fact in facts] == [
        "Host memory utilization is 56.50%."
    ]
    assert facts[0]["source"] == "system_metrics.measurements.memory_utilization_percent"
    assert facts[0]["timestamp"] == 199


def test_structured_evidence_is_passed_to_each_selected_specialist(monkeypatch):
    evidence = {
        "health": {"status": "ok", "source": "health"},
        "metrics": {"status": "ok", "request_counters": {"status": "ok"}},
        "system_metrics": {
            "status": "ok",
            "source": "host OS",
            "timestamp": 10,
            "measurements": {"cpu_utilization_percent": 40.0},
        },
        "version": {"status": "ok", "data": {"version": "1.1"}},
        "logs": {"status": "ok", "events": [{"ts": 10, "msg": "suspicious login"}]},
        "docker": {
            "status": "partial",
            "source": "Docker Engine fixture",
            "timestamp": 10,
            "containers": [{
                "id": "a" * 64,
                "name": "calculator",
                "cpu_usage_percent": 70.0,
                "metrics_status": "partial",
            }],
            "errors": [{"detail": "another container unavailable"}],
        },
    }
    comparison = {
        "status": "ok",
        "regression_signal": True,
        "deployment_changed": True,
    }
    received = {}

    def analyze(agent, task, supplied_evidence):
        received[agent] = supplied_evidence
        return {"status": "disabled", "agent": agent}

    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)
    state = {
        "query": "security incident with error after deployment",
        "evidence": evidence,
        "comparison": comparison,
        "trace": [],
    }

    graph._specialists_node(state)

    assert list(received) == list(graph.SPECIALIST_ORDER)
    assert all(
        item["system_metrics"] == evidence["system_metrics"]
        for agent, item in received.items()
        if agent in {"monitoring", "incident", "infrastructure"}
    )
    assert all(
        item["metrics"] == evidence["metrics"]
        for agent, item in received.items()
        if agent in {"monitoring", "incident", "cicd"}
    )
    assert all(
        item["docker"] == evidence["docker"]
        for agent, item in received.items()
        if agent in {"monitoring", "incident", "infrastructure", "cicd"}
    )
    assert "docker" not in received["code"]
    assert "system_metrics" not in received["code"]
    assert received["code"]["code_changes"]["status"] == "unavailable"
    assert "system_metrics" not in received["cicd"]
    assert "metrics" not in received["infrastructure"]
    assert set(received["security"]) == {
        "security_events",
        "security_telemetry",
        "verified_observations",
        "deterministic_evidence",
    }
    assert received["security"]["deterministic_evidence"]["role"] == "security"
    assert "docker" not in received["security"]


def test_unverified_specialist_claim_never_enters_verified_observed_facts(monkeypatch):
    evidence = {
        "captured_at": 100,
        "health": {"status": "unavailable"},
        "metrics": {
            "status": "ok",
            "request_counters": {"status": "ok"},
            "requests": {},
        },
        "system_metrics": {
            "status": "unavailable",
            "measurements": {},
        },
        "version": {"status": "unavailable"},
        "logs": {"status": "unavailable", "events": []},
    }

    def analyze(agent, task, supplied_evidence):
        analysis = {
            "summary": "CPU usage is 70%.",
            "findings": ["CPU utilization is 70%."],
            "confidence": 0.99,
            "recommended_checks": [],
        }
        return {
            "status": "ok",
            "agent": agent,
            "raw_content": json.dumps(analysis),
            "analysis": analysis,
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)
    state = {
        "query": "monitor CPU",
        "evidence": evidence,
        "baseline": {"status": "unavailable"},
        "comparison": {"status": "unavailable"},
        "trace": [],
    }
    state.update(graph._specialists_node(state))
    result = graph._diagnose_node(state)["diagnosis"]

    assert result["verified_observed_facts"] == []
    assert result["unverified_claims"]
    assert all(
        "CPU utilization is 70%" not in fact["statement"]
        for fact in result["verified_observed_facts"]
    )
