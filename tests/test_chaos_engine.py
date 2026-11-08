"""Tests for Chaos Engineering & Real Fault Injection Engine."""
import time
import pytest
from fastapi.testclient import TestClient

from agents.chaos_engine import chaos_engine
from calculator_app.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_chaos():
    """Ensure all chaos experiments are stopped before and after every test."""
    chaos_engine.stop_all()
    yield
    chaos_engine.stop_all()


def test_chaos_engine_singleton_and_initial_status():
    status = chaos_engine.get_status()
    assert status["active_experiments_count"] == 0
    assert status["crash_mode_armed"] is False
    assert status["current_latency_seconds"] == 0.0
    assert "host_telemetry" in status
    assert status["host_telemetry"]["status"] in ("ok", "partial")
    assert "measurements" in status["host_telemetry"]


def test_cpu_stress_experiment():
    exp = chaos_engine.trigger_cpu_stress(duration_seconds=2, num_threads=2)
    assert exp["experiment"] == "cpu_stress"
    assert exp["status"] == "running"
    assert exp["num_threads"] >= 1

    status = chaos_engine.get_status()
    assert status["cpu_workers_active"] >= 1
    assert "cpu_stress" in status["active_experiments"]

    chaos_engine.stop_cpu_stress()
    status_after = chaos_engine.get_status()
    assert status_after["cpu_workers_active"] == 0
    assert "cpu_stress" not in status_after["active_experiments"]


def test_memory_stress_experiment():
    exp = chaos_engine.trigger_memory_stress(megabytes=50, duration_seconds=2)
    assert exp["experiment"] == "memory_stress"
    assert exp["status"] == "running"
    assert exp["allocated_mb"] >= 50

    status = chaos_engine.get_status()
    assert status["memory_allocated_mb"] >= 50
    assert "memory_stress" in status["active_experiments"]

    chaos_engine.stop_memory_stress()
    status_after = chaos_engine.get_status()
    assert status_after["memory_allocated_mb"] == 0


def test_latency_injection():
    exp = chaos_engine.trigger_latency_spike(latency_seconds=0.2, duration_seconds=5)
    assert exp["experiment"] == "latency_spike"
    assert chaos_engine.get_active_latency() == 0.2

    # Verify actual request latency
    t0 = time.time()
    resp = client.get("/calc/add?a=10&b=20")
    elapsed = time.time() - t0
    assert resp.status_code == 200
    assert resp.json()["result"] == 30
    assert elapsed >= 0.18  # Proves real delay was applied

    chaos_engine.stop_latency_spike()
    assert chaos_engine.get_active_latency() == 0.0


def test_real_crash_mode_injection():
    chaos_engine.trigger_crash_mode(active=True, message="Physical chaos fault triggered")
    armed, msg = chaos_engine.is_crash_mode_active()
    assert armed is True
    assert "Physical chaos" in msg

    # Calling calculator endpoint should result in real HTTP 500
    resp = client.get("/calc/add?a=5&b=5")
    assert resp.status_code == 500
    assert "Physical chaos" in resp.json()["detail"]

    # Disarm
    chaos_engine.trigger_crash_mode(active=False)
    resp_healthy = client.get("/calc/add?a=5&b=5")
    assert resp_healthy.status_code == 200
    assert resp_healthy.json()["result"] == 10


def test_health_endpoint_reflects_chaos_degradation():
    # Nominal health
    resp1 = client.get("/health")
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "ok"

    # Start memory stress
    chaos_engine.trigger_memory_stress(megabytes=50, duration_seconds=5)
    resp2 = client.get("/health")
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "degraded"
    assert "Active chaos experiments" in resp2.json()["detail"]

    # Stop all
    chaos_engine.stop_all()
    resp3 = client.get("/health")
    assert resp3.status_code == 200
    assert resp3.json()["status"] == "ok"


def test_chaos_api_rest_endpoints():
    # 1. GET /chaos/status
    res = client.get("/chaos/status")
    assert res.status_code == 200
    data = res.json()
    assert "active_experiments_count" in data

    # 2. POST /chaos/stress/cpu
    res = client.post("/chaos/stress/cpu", json={"duration_seconds": 2, "num_threads": 1})
    assert res.status_code == 200
    assert res.json()["experiment"] == "cpu_stress"

    # 3. POST /chaos/inject/latency
    res = client.post("/chaos/inject/latency", json={"latency_seconds": 0.1, "duration_seconds": 2})
    assert res.status_code == 200
    assert res.json()["latency_seconds"] == 0.1

    # 4. POST /chaos/stop
    res = client.post("/chaos/stop")
    assert res.status_code == 200
    assert res.json()["status"] == "all_chaos_stopped"

