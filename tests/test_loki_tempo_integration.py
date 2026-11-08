"""Tests for Loki log aggregation and Tempo distributed tracing integration."""
from __future__ import annotations

import time
import pytest
from fastapi.testclient import TestClient

from calculator_app.app import app
from agents.loki_client import get_loki_status, query_loki_logs
from agents.tempo_client import (
    get_tempo_status,
    record_trace_span,
    search_traces,
    query_trace,
    generate_trace_id,
    generate_span_id,
)

from unittest.mock import patch

client = TestClient(app)


def test_loki_status_check():
    """Verify get_loki_status returns status dictionary."""
    status = get_loki_status()
    assert isinstance(status, dict)
    assert "status" in status
    assert "url" in status
    assert "healthy" in status
    assert status["status"] in ("online", "unavailable", "offline")


def test_tempo_status_check():
    """Verify get_tempo_status returns status dictionary."""
    status = get_tempo_status()
    assert isinstance(status, dict)
    assert "status" in status
    assert "url" in status
    assert "healthy" in status
    assert status["status"] in ("online", "unavailable", "offline")


def test_loki_logs_fallback_or_query():
    """Verify query_loki_logs returns valid entries even when Loki is not running."""
    res = query_loki_logs(query='{service_name="calculator-app"}', limit=10)
    assert isinstance(res, dict)
    assert "status" in res
    assert "source" in res
    assert "file" in res["source"] or "loki" in res["source"]
    assert "entries" in res
    assert isinstance(res["entries"], list)


def test_tempo_span_recording_and_retrieval():
    """Verify in-memory buffer stores and retrieves trace spans."""
    test_trace_id = generate_trace_id()
    test_span_id = generate_span_id()
    start_time = time.time()
    time.sleep(0.01)
    end_time = time.time()

    record_trace_span(
        trace_id=test_trace_id,
        span_id=test_span_id,
        name="GET /test/endpoint",
        start_time=start_time,
        end_time=end_time,
        status_code=200,
        attributes={"test.key": "test_val", "http.status_code": 200},
    )

    # Search traces
    res = search_traces(limit=20)
    traces = res.get("traces", [])
    assert any(t["trace_id"] == test_trace_id for t in traces)

    # Query specific trace
    trace_data = query_trace(test_trace_id)
    assert trace_data["trace_id"] == test_trace_id
    assert len(trace_data["spans"]) >= 1
    span = trace_data["spans"][0]
    assert span["span_id"] == test_span_id
    assert span["name"] == "GET /test/endpoint"
    assert span["attributes"].get("test.key") == "test_val"


def test_integrations_status_includes_loki_and_tempo():
    """Verify GET /integrations/status includes both loki and tempo."""
    with patch("agents.integration_api.GitHubClient.get_status", return_value={"status": "disabled"}):
        resp = client.get("/integrations/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "loki" in data
        assert "tempo" in data
        assert "status" in data["loki"]
        assert "status" in data["tempo"]


def test_telemetry_loki_endpoint():
    """Verify GET /telemetry/loki returns logs."""
    resp = client.get("/telemetry/loki?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "fallback")
    assert "file" in data["source"] or "loki" in data["source"]
    assert "entries" in data


def test_telemetry_tempo_endpoint():
    """Verify GET /telemetry/tempo returns trace list."""
    resp = client.get("/telemetry/tempo?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "fallback")
    assert "traces" in data
    assert isinstance(data["traces"], list)


def test_calc_request_trace_id_header_and_recording():
    """Verify calculator requests inject X-Trace-ID header and record span."""
    resp = client.get("/calc/add?a=12&b=8")
    assert resp.status_code == 200
    assert "X-Trace-ID" in resp.headers
    trace_id = resp.headers["X-Trace-ID"]
    assert len(trace_id) == 32

    # Query the trace detail endpoint
    trace_resp = client.get(f"/telemetry/traces/{trace_id}")
    assert trace_resp.status_code == 200
    t_data = trace_resp.json()
    assert t_data["trace_id"] == trace_id
    assert len(t_data["spans"]) >= 1
    assert t_data["spans"][0]["status_code"] == 200
    assert "add" in t_data["spans"][0]["name"]


def test_calc_error_trace_id_propagation():
    """Verify calculator error responses also record trace span with status code."""
    resp = client.get("/calc/div?a=10&b=0")
    assert resp.status_code == 400
    assert "X-Trace-ID" in resp.headers
    trace_id = resp.headers["X-Trace-ID"]

    trace_resp = client.get(f"/telemetry/traces/{trace_id}")
    assert trace_resp.status_code == 200
    t_data = trace_resp.json()
    assert t_data["trace_id"] == trace_id
    assert len(t_data["spans"]) >= 1
    assert t_data["spans"][0]["status_code"] == 400
