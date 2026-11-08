"""Read-only Tempo distributed tracing client with in-memory fallback buffer.

Strict safety policy:
- Passive, read-only trace inspection.
- Emits non-blocking OTLP HTTP spans to Tempo.
- Buffers recent spans in memory for high-availability trace inspection.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
import uuid
from typing import Any
import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger("tempo_client")

DEFAULT_TEMPO_URL = os.getenv("TEMPO_URL", "http://127.0.0.1:3200").rstrip("/")
DEFAULT_TEMPO_OTLP_URL = os.getenv("TEMPO_OTLP_URL", "http://127.0.0.1:4318").rstrip("/")

_TEMPO_SESSION = requests.Session()
_TEMPO_SESSION.mount("http://", HTTPAdapter(max_retries=0))
_TEMPO_SESSION.mount("https://", HTTPAdapter(max_retries=0))
_STATUS_CACHE: dict[str, Any] = {}
_STATUS_CACHE_TIME: float = 0.0

# Thread-safe in-memory buffer of recent trace summaries
_RECENT_TRACES: collections.deque[dict[str, Any]] = collections.deque(maxlen=100)
_BUFFER_LOCK = threading.Lock()


def generate_trace_id() -> str:
    """Generate 128-bit W3C compliant hex trace ID."""
    return uuid.uuid4().hex


def generate_span_id() -> str:
    """Generate 64-bit W3C compliant hex span ID."""
    return uuid.uuid4().hex[:16]


def record_trace_span(
    trace_id: str,
    span_id: str,
    name: str,
    start_time: float,
    end_time: float,
    status_code: int = 200,
    attributes: dict[str, Any] | None = None,
    error: str | None = None,
    service_name: str = "calculator-app",
) -> dict[str, Any]:
    """Record an operational span into the in-memory buffer and asynchronously ship to Tempo."""
    duration_ms = round((end_time - start_time) * 1000.0, 2)
    attrs = dict(attributes or {})
    attrs["http.status_code"] = status_code
    if error:
        attrs["error.message"] = str(error)

    span_record = {
        "trace_id": trace_id,
        "span_id": span_id,
        "name": name,
        "service_name": service_name,
        "start_time": start_time,
        "end_time": end_time,
        "duration_ms": duration_ms,
        "status": "error" if (status_code >= 500 or error) else "ok",
        "status_code": status_code,
        "attributes": attrs,
    }

    with _BUFFER_LOCK:
        _RECENT_TRACES.appendleft(span_record)

    # Ship asynchronously to Tempo OTLP HTTP receiver
    threading.Thread(
        target=_ship_otlp_span,
        args=(span_record,),
        daemon=True,
    ).start()

    return span_record


def _ship_otlp_span(span: dict[str, Any]) -> None:
    """Send single span to Tempo OTLP HTTP receiver (4318) in standard OpenTelemetry JSON format."""
    if "PYTEST_CURRENT_TEST" in os.environ or "PYTEST_VERSION" in os.environ or (os.name == "nt" and "SystemRoot" not in os.environ):
        return
    otlp_url = f"{DEFAULT_TEMPO_OTLP_URL}/v1/traces"
    start_nano = int(span["start_time"] * 1e9)
    end_nano = int(span["end_time"] * 1e9)

    otlp_attrs = []
    for k, v in span.get("attributes", {}).items():
        if isinstance(v, (int, float)):
            val_node = {"intValue": int(v)} if isinstance(v, int) else {"doubleValue": float(v)}
        elif isinstance(v, bool):
            val_node = {"boolValue": v}
        else:
            val_node = {"stringValue": str(v)}
        otlp_attrs.append({"key": k, "value": val_node})

    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": span["service_name"]}},
                        {"key": "service.version", "value": {"stringValue": "1.0"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "calculator-tracer", "version": "1.0"},
                        "spans": [
                            {
                                "traceId": span["trace_id"],
                                "spanId": span["span_id"],
                                "name": span["name"],
                                "kind": 1,  # SPAN_KIND_SERVER
                                "startTimeUnixNano": str(start_nano),
                                "endTimeUnixNano": str(end_nano),
                                "attributes": otlp_attrs,
                                "status": {
                                    "code": 2 if span["status"] == "error" else 1,
                                    "message": span.get("attributes", {}).get("error.message", ""),
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }

    try:
        requests.post(
            otlp_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=0.5,
        )
    except Exception as exc:
        logger.debug("Tempo OTLP ingestion bypassed: %s", exc)


def get_tempo_status(tempo_url: str | None = None) -> dict[str, Any]:
    """Check whether Tempo is reachable and healthy."""
    global _STATUS_CACHE, _STATUS_CACHE_TIME
    now = time.time()
    if _STATUS_CACHE and (now - _STATUS_CACHE_TIME < 5.0):
        return dict(_STATUS_CACHE)

    base_url = (tempo_url or DEFAULT_TEMPO_URL).rstrip("/")
    if os.name == "nt" and "SystemRoot" not in os.environ:
        result = {
            "status": "unavailable",
            "healthy": False,
            "url": base_url,
            "source": f"tempo:{base_url}",
            "detail": "Network unavailable",
            "timestamp": now,
        }
        _STATUS_CACHE = result
        _STATUS_CACHE_TIME = now
        return dict(result)
    try:
        resp = _TEMPO_SESSION.get(f"{base_url}/ready", headers={"Accept": "text/plain"}, timeout=0.2)
        ready = resp.status_code == 200
        result = {
            "status": "online" if ready else "unavailable",
            "healthy": ready,
            "url": base_url,
            "source": f"tempo:{base_url}",
            "detail": "Tempo is ready to receive and query traces",
            "timestamp": now,
        }
    except Exception as exc:
        result = {
            "status": "unavailable",
            "healthy": False,
            "url": base_url,
            "source": f"tempo:{base_url}",
            "detail": f"Tempo server unavailable ({exc}); in-memory trace buffer active",
            "timestamp": now,
        }
    _STATUS_CACHE = result
    _STATUS_CACHE_TIME = now
    return dict(result)


def search_traces(
    limit: int = 20,
    service_name: str = "calculator-app",
    tempo_url: str | None = None,
) -> dict[str, Any]:
    """Search recent traces from live Tempo or fallback to in-memory trace buffer."""
    base_url = (tempo_url or DEFAULT_TEMPO_URL).rstrip("/")
    if os.name == "nt" and "SystemRoot" not in os.environ:
        result = {
            "status": "unavailable",
            "healthy": False,
            "url": base_url,
            "source": f"tempo:{base_url}",
            "detail": "Network unavailable",
            "timestamp": now,
        }
        _STATUS_CACHE = result
        _STATUS_CACHE_TIME = now
        return dict(result)

    # 1. Try querying Tempo search API
    try:
        url = f"{base_url}/api/search?limit={limit}&service={service_name}"
        resp = _TEMPO_SESSION.get(url, headers={"Accept": "application/json"}, timeout=0.2)
        if resp.status_code == 200:
            data = resp.json()
            traces = data.get("traces", [])
            return {
                "status": "ok",
                "source": f"tempo:{base_url}",
                "traces": traces[:limit],
                "count": len(traces[:limit]),
                "timestamp": time.time(),
            }
    except Exception:
        pass

    # 2. Fallback to in-memory trace buffer
    with _BUFFER_LOCK:
        buffered = list(_RECENT_TRACES)[:limit]

    return {
        "status": "ok" if buffered else "unavailable",
        "source": "in-memory trace buffer (fallback)",
        "traces": buffered,
        "count": len(buffered),
        "timestamp": time.time(),
    }


def query_trace(trace_id: str, tempo_url: str | None = None) -> dict[str, Any]:
    """Retrieve full trace details and span breakdown by trace_id."""
    clean_id = (trace_id or "").strip().lower()
    base_url = (tempo_url or DEFAULT_TEMPO_URL).rstrip("/")
    if os.name == "nt" and "SystemRoot" not in os.environ:
        result = {
            "status": "unavailable",
            "healthy": False,
            "url": base_url,
            "source": f"tempo:{base_url}",
            "detail": "Network unavailable",
            "timestamp": now,
        }
        _STATUS_CACHE = result
        _STATUS_CACHE_TIME = now
        return dict(result)

    # 1. Try Tempo API
    try:
        url = f"{base_url}/api/traces/{clean_id}"
        resp = _TEMPO_SESSION.get(url, headers={"Accept": "application/json"}, timeout=0.2)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": "ok",
                "source": f"tempo:{base_url}",
                "trace_id": clean_id,
                "data": data,
                "timestamp": time.time(),
            }
    except Exception:
        pass

    # 2. Fallback to in-memory trace buffer
    with _BUFFER_LOCK:
        spans = [s for s in _RECENT_TRACES if s["trace_id"] == clean_id]

    if spans:
        return {
            "status": "ok",
            "source": "in-memory trace buffer",
            "trace_id": clean_id,
            "spans": spans,
            "total_duration_ms": sum(s.get("duration_ms", 0.0) for s in spans),
            "timestamp": time.time(),
        }

    return {
        "status": "not_found",
        "source": "tempo & buffer",
        "trace_id": clean_id,
        "spans": [],
        "detail": f"Trace {clean_id} not found in Tempo or local buffer.",
        "timestamp": time.time(),
    }
