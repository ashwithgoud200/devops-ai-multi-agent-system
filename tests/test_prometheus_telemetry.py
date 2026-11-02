import time

import pytest
import requests

from agents import graph, prometheus_telemetry


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _success_payload(value=2.5, timestamp=None):
    timestamp = timestamp or time.time() - 5
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [{
                "metric": {"op": "div", "status": "error"},
                "values": [[timestamp, str(value)]],
            }],
        },
    }


def test_prometheus_queries_use_read_only_bounded_http_api_and_hide_credentials(
    monkeypatch,
):
    calls = []

    def get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return _Response(_success_payload())

    monkeypatch.setattr(prometheus_telemetry.requests, "get", get)
    monkeypatch.setenv(
        "PROMETHEUS_URL",
        "http://user:password@prometheus.local:9090/?token=hidden",
    )

    result = prometheus_telemetry.collect_prometheus_metrics()

    assert result["status"] == "ok"
    assert result["url"] == "http://prometheus.local:9090"
    assert "password" not in str(result)
    assert "hidden" not in str(result)
    assert len(calls) == len(prometheus_telemetry.QUERIES)
    assert all(url == "http://user:password@prometheus.local:9090//api/v1/query_range"
               or url.endswith("/api/v1/query_range") for url, _, _ in calls)
    assert all(params["step"] == prometheus_telemetry.STEP_SECONDS
               for _, params, _ in calls)
    assert all(params["end"] - params["start"] == prometheus_telemetry.RANGE_SECONDS
               for _, params, _ in calls)
    assert all(timeout == prometheus_telemetry.DEFAULT_TIMEOUT_SECONDS
               for _, _, timeout in calls)
    assert all(item["query"] == prometheus_telemetry.QUERIES[name]["query"]
               for name, item in result["metrics"].items())


@pytest.mark.parametrize(
    "response",
    [
        _Response({
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        }),
        _Response({"status": "success", "data": {"resultType": "vector", "result": []}}),
        _Response(ValueError("invalid JSON")),
        _Response({}, status_code=503),
    ],
)
def test_empty_invalid_json_and_http_errors_are_unavailable(monkeypatch, response):
    monkeypatch.setattr(
        prometheus_telemetry.requests,
        "get",
        lambda *args, **kwargs: response,
    )

    result = prometheus_telemetry.collect_prometheus_metrics()

    assert result["status"] == "unavailable"
    assert all(item["status"] == "unavailable" for item in result["metrics"].values())
    assert all(item["observations"] == [] for item in result["metrics"].values())
    assert all(
        "latest_value" not in observation
        for item in result["metrics"].values()
        for observation in item["observations"]
    )


@pytest.mark.parametrize(
    "error, expected",
    [
        (requests.ConnectionError("connection refused"), "HTTP request failed"),
        (requests.Timeout("request timed out"), "timed out"),
    ],
)
def test_connection_failure_and_timeout_are_reported(monkeypatch, error, expected):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(prometheus_telemetry.requests, "get", fail)

    result = prometheus_telemetry.collect_prometheus_metrics()

    assert result["status"] == "unavailable"
    assert all(expected in item["detail"] for item in result["metrics"].values())


def test_partial_collection_preserves_successful_observations(monkeypatch):
    def get(url, *, params, timeout):
        if params["query"] == prometheus_telemetry.QUERIES["request_rate"]["query"]:
            return _Response(_success_payload())
        return _Response({
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        })

    monkeypatch.setattr(prometheus_telemetry.requests, "get", get)

    result = prometheus_telemetry.collect_prometheus_metrics()

    assert result["status"] == "partial"
    assert result["metrics"]["request_rate"]["status"] == "ok"
    assert result["metrics"]["request_rate"]["observations"][0]["latest_value"] == 2.5
    assert result["metrics"]["container_cpu"]["status"] == "unavailable"
    assert result["metrics"]["container_cpu"]["observations"] == []


def test_stale_samples_are_retained_but_not_marked_available(monkeypatch):
    stale_payload = _success_payload(
        timestamp=time.time() - prometheus_telemetry.STALE_AFTER_SECONDS - 20
    )
    monkeypatch.setattr(
        prometheus_telemetry.requests,
        "get",
        lambda *args, **kwargs: _Response(stale_payload),
    )

    result = prometheus_telemetry.collect_prometheus_metrics()

    assert result["status"] == "unavailable"
    observation = result["metrics"]["request_rate"]["observations"][0]
    assert observation["stale"] is True
    assert observation["values"][0]["stale"] is True
    assert "stale" in result["metrics"]["request_rate"]["detail"].lower()


def test_invalid_samples_do_not_become_zero_or_discard_neighboring_values(monkeypatch):
    payload = _success_payload()
    payload["data"]["result"].append({
        "metric": {"op": "add"},
        "values": [["invalid", "not-a-number"]],
    })
    monkeypatch.setattr(
        prometheus_telemetry.requests,
        "get",
        lambda *args, **kwargs: _Response(payload),
    )

    result = prometheus_telemetry.collect_prometheus_metrics()

    assert result["status"] == "partial"
    request_rate = result["metrics"]["request_rate"]
    assert request_rate["status"] == "partial"
    assert len(request_rate["observations"]) == 1
    assert request_rate["observations"][0]["latest_value"] == 2.5
    assert all(
        point["value"] != 0
        for observation in request_rate["observations"]
        for point in observation["values"]
    )


def _prom_snapshot(value, timestamp, status="ok", unit="requests/second"):
    return {
        "captured_at": timestamp,
        "prometheus": {
            "status": status,
            "source": "Prometheus HTTP API",
            "metrics": {
                "request_rate": {
                    "status": status,
                    "unit": unit,
                    "query": "rate(calc_requests_total[5m])",
                    "observations": [{
                        "labels": {"op": "div"},
                        "latest_value": value,
                        "latest_timestamp": timestamp,
                        "stale": False,
                        "values": [{"timestamp": timestamp, "value": value, "stale": False}],
                    }],
                },
            },
        },
    }


def test_prometheus_delta_requires_compatible_fresh_series_and_units():
    baseline = _prom_snapshot(2.0, 100.0)
    current = _prom_snapshot(3.0, 200.0)

    comparison = graph._compare_prometheus(baseline, current)

    assert comparison["status"] == "ok"
    assert comparison["deltas"] == [{
        "metric": "request_rate",
        "labels": {"op": "div"},
        "unit": "requests/second",
        "baseline_value": 2.0,
        "current_value": 3.0,
        "delta": 1.0,
        "baseline_timestamp": 100.0,
        "current_timestamp": 200.0,
        "source": "Prometheus HTTP API",
    }]
    current["prometheus"]["metrics"]["request_rate"]["unit"] = "bytes"
    assert graph._compare_prometheus(baseline, current)["deltas"] == []


def test_missing_or_stale_prometheus_series_are_not_compared():
    baseline = _prom_snapshot(2.0, 100.0)
    current = _prom_snapshot(3.0, 200.0)
    current["prometheus"]["metrics"]["request_rate"]["observations"][0]["stale"] = True

    comparison = graph._compare_prometheus(baseline, current)

    assert comparison["status"] == "partial"
    assert comparison["deltas"] == []


def test_prometheus_only_delta_does_not_create_regression_or_rollback():
    baseline = {
        "status": "ok",
        "snapshot": {
            **_prom_snapshot(2.0, 100.0),
            "metrics": {"status": "unavailable"},
            "version": {"status": "unavailable"},
            "logs": {"status": "unavailable"},
        },
    }
    current = {
        **_prom_snapshot(3.0, 200.0),
        "metrics": {"status": "unavailable"},
        "version": {"status": "unavailable"},
        "logs": {"status": "unavailable"},
    }

    comparison = graph._compare_snapshots(baseline, current)

    assert comparison["prometheus_comparison"]["deltas"][0]["delta"] == 1.0
    assert comparison["regression_signal"] is False
    assert comparison["status"] == "partial"
    proposal = graph._propose_node({
        "evidence": current,
        "comparison": comparison,
    })["remediation"]
    assert proposal["action"] != "rollback"


@pytest.mark.parametrize(
    "docker_status,prometheus_status",
    [
        ("ok", "unavailable"),
        ("unavailable", "ok"),
    ],
)
def test_docker_and_prometheus_availability_are_independent(
    monkeypatch, docker_status, prometheus_status
):
    docker = {
        "status": docker_status,
        "containers": [{
            "id": "container-id",
            "name": "calculator",
            "cpu_usage_percent": 20.0 if docker_status == "ok" else None,
        }] if docker_status == "ok" else [],
    }
    prometheus = _prom_snapshot(2.0, time.time(), status=prometheus_status)["prometheus"]
    if prometheus_status == "unavailable":
        prometheus["metrics"]["request_rate"]["observations"] = []
    evidence = {
        "captured_at": time.time(),
        "health": {"status": "unavailable"},
        "metrics": {"status": "unavailable"},
        "system_metrics": {"status": "unavailable"},
        "version": {"status": "unavailable"},
        "logs": {"status": "ok", "events": []},
        "docker": docker,
        "prometheus": prometheus,
    }
    state = {
        "query": "diagnose incident",
        "evidence": evidence,
        "comparison": {"deployment_changed": False, "regression_signal": False},
    }

    selected = graph._select_specialists(state)
    monitoring = graph._specialist_evidence("monitoring", state)
    incident = graph._specialist_evidence("incident", state)
    infrastructure = graph._specialist_evidence("infrastructure", state)
    security = graph._specialist_evidence("security", state)

    if prometheus_status == "ok" or docker_status == "ok":
        assert "monitoring" in selected
        assert "infrastructure" in selected
    else:
        assert "monitoring" not in selected
        assert "infrastructure" not in selected
    if prometheus_status == "ok":
        assert monitoring["prometheus"] == prometheus
        assert incident["prometheus"] == prometheus
        assert infrastructure["prometheus"] == prometheus
    else:
        assert monitoring["prometheus"]["status"] == "unavailable"
        assert incident["prometheus"]["status"] == "unavailable"
    assert "prometheus" not in security
    assert "docker" not in security


def test_cicd_receives_prometheus_only_when_deployment_changed():
    evidence = {
        "health": {"status": "unavailable"},
        "metrics": {"status": "unavailable"},
        "system_metrics": {"status": "unavailable"},
        "version": {"status": "unavailable"},
        "logs": {"status": "unavailable"},
        "prometheus": _prom_snapshot(1.0, 100.0)["prometheus"],
    }
    state = {
        "evidence": evidence,
        "comparison": {
            "deployment_changed": False,
            "prometheus_comparison": {"status": "ok", "deltas": ["sample"]},
        },
    }

    cicd = graph._specialist_evidence("cicd", state)
    assert "prometheus" not in cicd
    assert "prometheus_comparison" not in cicd["baseline_comparison"]
    state["comparison"]["deployment_changed"] = True
    cicd = graph._specialist_evidence("cicd", state)
    assert cicd["prometheus"] == evidence["prometheus"]
    assert "prometheus_comparison" in cicd["baseline_comparison"]


def test_prometheus_observations_are_source_linked_facts():
    timestamp = time.time()
    evidence = _prom_snapshot(4.0, timestamp)

    facts = graph._observed_facts(evidence, {"status": "unavailable"}, {})

    assert len(facts) == 1
    assert facts[0]["source"] == "prometheus.metrics.request_rate.observations[0]"
    assert facts[0]["timestamp"] == timestamp
    assert "4 requests/second" in facts[0]["statement"]


def test_prometheus_evidence_reaches_selected_model_calls(monkeypatch):
    timestamp = time.time()
    prometheus = _prom_snapshot(4.0, timestamp)["prometheus"]
    state = {
        "query": "diagnose incident",
        "evidence": {
            "captured_at": timestamp,
            "health": {"status": "unavailable"},
            "metrics": {"status": "unavailable"},
            "system_metrics": {"status": "unavailable"},
            "version": {"status": "unavailable"},
            "logs": {"status": "ok", "events": []},
            "docker": {"status": "unavailable", "containers": []},
            "prometheus": prometheus,
        },
        "comparison": {
            "status": "partial",
            "deployment_changed": False,
            "regression_signal": False,
        },
    }
    calls = {}

    def analyze(agent, task, evidence):
        calls[agent] = evidence
        return {
            "status": "ok",
            "agent": agent,
            "analysis": {
                "summary": "Insufficient evidence to establish a cause.",
                "findings": [],
                "confidence": 0.1,
                "recommended_checks": [],
            },
        }

    monkeypatch.setattr(graph.llm_runtime, "analyze", analyze)

    result = graph._specialists_node(state)

    assert set(result["specialists"]["selected"]) == {
        "monitoring", "incident", "infrastructure"
    }
    assert all(calls[agent]["prometheus"] == prometheus for agent in calls)
    assert "prometheus" not in graph._specialist_evidence("security", state)
