import copy
import importlib

import pytest
from fastapi.testclient import TestClient

calculator = importlib.import_module("calculator_app.app")


@pytest.fixture
def client(monkeypatch):
    original_state = copy.deepcopy(calculator.STATE)
    monkeypatch.setattr(calculator.logger, "disabled", True)
    calculator.STATE.clear()
    calculator.STATE.update({
        "version": "1.0",
        "bug": False,
        "history": [{"version": "1.0", "ts": 1}],
    })
    with TestClient(calculator.app) as test_client:
        yield test_client
    calculator.STATE.clear()
    calculator.STATE.update(original_state)


def test_calculator_operations_health_and_metrics(client):
    response = client.get("/calc/add", params={"a": 2, "b": 3})

    assert response.status_code == 200
    assert response.json() == {"op": "add", "result": 5, "version": "1.0"}
    assert client.get("/health").json() == {"status": "ok", "version": "1.0"}
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "calc_requests_total" in metrics.text


def test_docker_telemetry_endpoint_is_read_only_and_returns_collection(monkeypatch, client):
    collection = {
        "status": "unavailable",
        "source": "Docker Engine via read-only Docker CLI",
        "timestamp": 123.0,
        "containers": [],
        "errors": ["Docker Engine unavailable: daemon stopped"],
        "detail": "Docker Engine unavailable: daemon stopped",
    }
    monkeypatch.setattr(calculator, "collect_docker_metrics", lambda: collection)

    response = client.get("/telemetry/docker")

    assert response.status_code == 200
    assert response.json() == collection
    assert client.post("/telemetry/docker").status_code == 405


def test_prometheus_telemetry_endpoint_is_read_only_and_returns_collection(
    monkeypatch, client
):
    collection = {
        "status": "unavailable",
        "source": "Prometheus HTTP API",
        "url": "http://127.0.0.1:9090",
        "timestamp": 123.0,
        "metrics": {},
        "errors": ["Prometheus connection refused"],
        "detail": "Prometheus connection refused",
    }
    monkeypatch.setattr(calculator, "collect_prometheus_metrics", lambda: collection)

    response = client.get("/telemetry/prometheus")

    assert response.status_code == 200
    assert response.json() == collection
    assert client.post("/telemetry/prometheus").status_code == 405


def test_calculator_errors_preserve_existing_http_behavior(client):
    assert client.get("/calc/unknown", params={"a": 1, "b": 2}).status_code == 404
    division = client.get("/calc/div", params={"a": 1, "b": 0})

    assert division.status_code == 400
    assert division.json()["detail"] == "division by zero"


def test_deploy_history_and_rollback_endpoints(client):
    deployed = client.post(
        "/admin/deploy", params={"version": "1.1", "bug": "true"}
    )
    assert deployed.status_code == 200
    assert client.get("/admin/version").json()["version"] == "1.1"

    rolled_back = client.post("/admin/rollback")

    assert rolled_back.status_code == 200
    assert rolled_back.json() == {"rolled_back_to": "1.0"}
    assert client.get("/health").json() == {"status": "ok", "version": "1.0"}
