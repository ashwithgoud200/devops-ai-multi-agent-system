"""Read-only, bounded time-series collection from the Prometheus HTTP API."""
from __future__ import annotations

import math
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

SOURCE = "Prometheus HTTP API"
DEFAULT_URL = "http://127.0.0.1:9090"
DEFAULT_TIMEOUT_SECONDS = 3.0
MAX_TIMEOUT_SECONDS = 15.0
RANGE_SECONDS = 300
STEP_SECONDS = 60
STALE_AFTER_SECONDS = 300

QUERIES: dict[str, dict[str, str]] = {
    "request_rate": {
        "query": "sum by (op, status) (rate(calc_requests_total[5m]))",
        "unit": "requests/second",
    },
    "http_error_rate": {
        "query": (
            "100 * sum(rate(calc_requests_total{status=~\"error|client_error\"}[5m])) "
            "/ sum(rate(calc_requests_total[5m]))"
        ),
        "unit": "percent",
    },
    "latency_p95": {
        "query": (
            "histogram_quantile(0.95, "
            "sum by (le, op) (rate(calc_latency_seconds_bucket[5m])))"
        ),
        "unit": "seconds",
    },
    "cpu_utilization": {
        "query": "rate(process_cpu_seconds_total[5m]) * 100",
        "unit": "percent_of_one_cpu",
    },
    "memory_usage": {
        "query": "process_resident_memory_bytes",
        "unit": "bytes",
    },
    "host_cpu_utilization": {
        "query": (
            "100 * (1 - avg by (instance) "
            "(rate(node_cpu_seconds_total{mode=\"idle\"}[5m])))"
        ),
        "unit": "percent",
    },
    "host_memory_utilization": {
        "query": (
            "100 * (1 - node_memory_MemAvailable_bytes "
            "/ node_memory_MemTotal_bytes)"
        ),
        "unit": "percent",
    },
    "container_cpu": {
        "query": (
            "sum by (container, image) "
            "(rate(container_cpu_usage_seconds_total[5m])) * 100"
        ),
        "unit": "percent_of_one_cpu",
    },
    "container_memory": {
        "query": "container_memory_working_set_bytes",
        "unit": "bytes",
    },
    "container_memory_utilization": {
        "query": (
            "100 * container_memory_working_set_bytes "
            "/ (container_spec_memory_limit_bytes > 0)"
        ),
        "unit": "percent",
    },
}


def _safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        hostname = parts.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        if parts.port is not None:
            hostname = f"{hostname}:{parts.port}"
        return urlunsplit((parts.scheme, hostname, parts.path.rstrip("/"), "", ""))
    except ValueError:
        return "<invalid PROMETHEUS_URL>"


def _safe_error(error: Exception | str) -> str:
    message = str(error)
    message = re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1", message)
    message = re.sub(r"([?&][^=&#]*(?:token|key|password|secret)[^=]*=)[^&#\s]+", r"\1<redacted>", message, flags=re.I)
    return message[:1000]


def _request_timeout() -> float:
    value = float(os.getenv(
        "PROMETHEUS_TIMEOUT_SECONDS",
        str(DEFAULT_TIMEOUT_SECONDS),
    ))
    if not math.isfinite(value) or value <= 0 or value > MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"PROMETHEUS_TIMEOUT_SECONDS must be between 0 and {MAX_TIMEOUT_SECONDS:g}"
        )
    return value


def _unavailable_query(name: str, query: str, detail: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "query": query,
        "unit": QUERIES[name]["unit"],
        "observations": [],
        "detail": detail,
    }


def _parse_query_response(
    name: str,
    query: str,
    payload: Any,
    collected_at: float,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("status") != "success":
        detail = (
            payload.get("error", "Prometheus query did not succeed")
            if isinstance(payload, dict)
            else "Prometheus response must be a JSON object"
        )
        return _unavailable_query(name, query, str(detail))
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "matrix":
        return _unavailable_query(
            name, query, "Prometheus response data must contain a matrix result"
        )
    results = data.get("result")
    if not isinstance(results, list):
        return _unavailable_query(
            name, query, "Prometheus matrix result must be an array"
        )

    observations = []
    errors = []
    stale_observations = 0
    for index, result in enumerate(results):
        if not isinstance(result, dict) or not isinstance(result.get("metric"), dict):
            errors.append(f"Series {index} has an invalid metric label set")
            continue
        values = result.get("values")
        if not isinstance(values, list):
            errors.append(f"Series {index} has no valid values array")
            continue
        points = []
        for point_index, point in enumerate(values):
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                errors.append(f"Series {index} point {point_index} is malformed")
                continue
            try:
                timestamp = float(point[0])
                value = float(point[1])
            except (TypeError, ValueError):
                errors.append(f"Series {index} point {point_index} is not numeric")
                continue
            if not math.isfinite(timestamp) or not math.isfinite(value):
                errors.append(f"Series {index} point {point_index} is not finite")
                continue
            stale = collected_at - timestamp > STALE_AFTER_SECONDS
            stale_observations += int(stale)
            points.append({
                "timestamp": timestamp,
                "value": value,
                "stale": stale,
            })
        if points:
            observations.append({
                "labels": result["metric"],
                "values": points,
                "latest_timestamp": points[-1]["timestamp"],
                "latest_value": points[-1]["value"],
                "stale": points[-1]["stale"],
            })

    fresh = [item for item in observations if not item["stale"]]
    if fresh and not errors and stale_observations == 0:
        status = "ok"
        detail = None
    elif fresh:
        status = "partial"
        details = errors[:]
        if stale_observations:
            details.append(f"{stale_observations} returned samples are stale")
        detail = "; ".join(details)
    elif observations:
        status = "unavailable"
        detail = "All returned observations are stale"
    elif errors:
        status = "unavailable"
        detail = "; ".join(errors)
    else:
        status = "unavailable"
        detail = "Prometheus query returned no observations"
    return {
        "status": status,
        "query": query,
        "unit": QUERIES[name]["unit"],
        "observations": observations,
        "detail": detail,
        "stale_observation_count": stale_observations,
    }


def collect_prometheus_metrics() -> dict[str, Any]:
    """Query a fixed set of bounded time-series using read-only HTTP GET requests."""
    collection_time = time.time()
    base_url = os.getenv("PROMETHEUS_URL", DEFAULT_URL).rstrip("/")
    source_url = _safe_url(base_url)
    try:
        timeout = _request_timeout()
        parts = urlsplit(base_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("PROMETHEUS_URL must be an absolute HTTP(S) URL")
    except (TypeError, ValueError) as exc:
        detail = _safe_error(exc)
        unavailable = {
            name: _unavailable_query(name, spec["query"], detail)
            for name, spec in QUERIES.items()
        }
        return {
            "status": "unavailable",
            "source": SOURCE,
            "url": source_url,
            "timestamp": collection_time,
            "range_seconds": RANGE_SECONDS,
            "step_seconds": STEP_SECONDS,
            "metrics": unavailable,
            "errors": [detail],
            "detail": detail,
        }

    end = time.time()
    start = end - RANGE_SECONDS
    metrics: dict[str, Any] = {}
    errors = []
    for name, spec in QUERIES.items():
        query = spec["query"]
        try:
            response = requests.get(
                f"{base_url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start,
                    "end": end,
                    "step": STEP_SECONDS,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            result = _parse_query_response(name, query, payload, time.time())
        except requests.Timeout as exc:
            detail = f"Prometheus query timed out: {_safe_error(exc)}"
            result = _unavailable_query(name, query, detail)
        except requests.RequestException as exc:
            detail = f"Prometheus HTTP request failed: {_safe_error(exc)}"
            result = _unavailable_query(name, query, detail)
        except (ValueError, TypeError, AttributeError) as exc:
            detail = f"Invalid Prometheus response: {_safe_error(exc)}"
            result = _unavailable_query(name, query, detail)
        metrics[name] = result
        if result["status"] != "ok":
            errors.append({"metric": name, "detail": result.get("detail")})

    statuses = [item["status"] for item in metrics.values()]
    if all(status == "ok" for status in statuses):
        status = "ok"
    elif any(status in {"ok", "partial"} for status in statuses):
        status = "partial"
    else:
        status = "unavailable"
    return {
        "status": status,
        "source": SOURCE,
        "url": source_url,
        "timestamp": time.time(),
        "range_seconds": RANGE_SECONDS,
        "step_seconds": STEP_SECONDS,
        "metrics": metrics,
        "errors": errors,
        "detail": "; ".join(
            f"{error['metric']}: {error['detail']}"
            for error in errors
            if error.get("detail")
        ) or None,
    }
