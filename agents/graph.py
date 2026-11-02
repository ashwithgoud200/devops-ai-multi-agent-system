"""LangGraph incident workflow for the calculator demo."""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, TypedDict

import requests
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents import llm_runtime
from agents.docker_telemetry import collect_docker_metrics
from agents.evidence_extractor import (
    ROLE_CATEGORIES,
    extract_evidence,
    package_for_role,
    validate_extraction,
)
from agents.prometheus_telemetry import collect_prometheus_metrics
from agents.telemetry import collect_system_metrics

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "data" / "baseline.json"
REQUEST_TIMEOUT = 3.0
MAX_LOG_LINES = 500
SPECIALIST_ORDER = (
    "monitoring",
    "incident",
    "code",
    "cicd",
    "infrastructure",
    "security",
)


class IncidentState(TypedDict, total=False):
    query: str
    trace: list[str]
    evidence: dict[str, Any]
    baseline: dict[str, Any]
    comparison: dict[str, Any]
    evidence_extraction: dict[str, Any]
    specialists: dict[str, Any]
    diagnosis: dict[str, Any]
    remediation: dict[str, Any]
    approval: bool
    outcome: dict[str, Any]
    report: dict[str, Any]


def _base_url() -> str:
    return os.getenv("DEVOPS_APP_URL", "http://127.0.0.1:8100").rstrip("/")


def _get_json(path: str) -> dict[str, Any]:
    timestamp = time.time()
    url = _base_url() + path
    try:
        response = requests.get(
            url,
            timeout=float(os.getenv("DEVOPS_APP_TIMEOUT_SECONDS", REQUEST_TIMEOUT)),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("API response must be a JSON object")
        return {
            "status": "ok",
            "source": url,
            "timestamp": time.time(),
            "data": data,
        }
    except (requests.RequestException, ValueError) as exc:
        return {
            "status": "unavailable",
            "source": url,
            "timestamp": timestamp,
            "detail": str(exc),
        }


def _get_metrics() -> dict[str, Any]:
    url = _base_url() + "/metrics"
    try:
        response = requests.get(
            url,
            timeout=float(os.getenv("DEVOPS_APP_TIMEOUT_SECONDS", REQUEST_TIMEOUT)),
        )
        response.raise_for_status()
        text = response.text
        requests_metrics = _parse_request_metrics(text)
        latency_metrics = _parse_latency_metrics(text)
        request_family = (
            bool(requests_metrics)
            or re.search(r"^# TYPE calc_requests_total counter\s*$", text, re.M) is not None
        )
        latency_family = (
            bool(latency_metrics)
            or re.search(r"^# TYPE calc_latency_seconds histogram\s*$", text, re.M) is not None
        )
        malformed_samples = []
        parsed_samples = _parse_metric_samples(text, "calc_requests_total")
        for line in text.splitlines():
            if line.startswith("calc_requests_total") and not re.match(
                r"^calc_requests_total\{[^}]*\}\s+[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*$",
                line,
            ):
                malformed_samples.append(line)
        valid_request_samples = [
            (labels, value)
            for name, labels, value in parsed_samples
            if name == "calc_requests_total"
            and "op" in labels and "status" in labels and value >= 0
        ]
        if (
            malformed_samples
            or any(value < 0 for _, _, value in parsed_samples)
            or any(value < 0 for value in latency_metrics.values())
        ):
            return {
                "status": "unavailable",
                "request_counters": {"status": "unavailable"},
                "latency_observations": {"status": "unavailable"},
                "source": url,
                "timestamp": time.time(),
                "detail": "Prometheus exposition contains invalid counter samples",
            }
        if not request_family:
            return {
                "status": "unavailable",
                "request_counters": {"status": "unavailable"},
                "latency_observations": {
                    "status": (
                        "ok" if latency_metrics
                        else "partial" if latency_family else "unavailable"
                    )
                },
                "source": url,
                "timestamp": time.time(),
                "detail": "Prometheus exposition is missing calc_requests_total",
            }
        # A family declaration with no series is a valid scrape, but not a zero-valued counter.
        request_status = "ok" if valid_request_samples else "partial"
        latency_status = (
            "ok" if latency_metrics else "partial" if latency_family else "unavailable"
        )
        overall_status = (
            "ok"
            if request_status == "ok" and latency_status == "ok"
            else "partial"
        )
        return {
            "status": overall_status,
            "request_counters": {"status": request_status},
            "requests": requests_metrics,
            "request_totals": _request_totals(requests_metrics),
            "latency_observations": {
                "status": latency_status,
                "by_operation": latency_metrics,
            },
            "source": url,
            "timestamp": time.time(),
            "detail": None if latency_family else "Latency histogram family is missing",
        }
    except requests.RequestException as exc:
        return {
            "status": "unavailable",
            "request_counters": {"status": "unavailable"},
            "latency_observations": {"status": "unavailable"},
            "source": url,
            "timestamp": time.time(),
            "detail": str(exc),
        }
    except (AttributeError, TypeError, ValueError) as exc:
        return {
            "status": "unavailable",
            "request_counters": {"status": "unavailable"},
            "latency_observations": {"status": "unavailable"},
            "source": url,
            "timestamp": time.time(),
            "detail": f"Invalid Prometheus exposition: {exc}",
        }


def _request_totals(
    requests_metrics: dict[str, dict[str, float]],
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for operation, statuses in requests_metrics.items():
        counts = [
            value for status, value in statuses.items()
            if status in {"ok", "error", "client_error"}
        ]
        if counts:
            totals[operation] = sum(counts)
    return totals


def _parse_metric_samples(text: str, prefix: str) -> list[tuple[str, dict[str, str], float]]:
    samples = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        metric_match = re.match(
            r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([^\s]+)", line
        )
        if not metric_match or not metric_match.group(1).startswith(prefix):
            continue
        labels: dict[str, str] = {}
        label_text = metric_match.group(2) or ""
        for label in re.finditer(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"', label_text):
            labels[label.group(1)] = bytes(label.group(2), "utf-8").decode("unicode_escape")
        try:
            value = float(metric_match.group(3))
        except ValueError:
            continue
        if math.isfinite(value):
            samples.append((metric_match.group(1), labels, value))
    return samples


def _parse_request_metrics(text: str) -> dict[str, dict[str, float]]:
    counts: dict[str, dict[str, float]] = {}
    for _, labels, value in _parse_metric_samples(text, "calc_requests_total"):
        operation, status = labels.get("op"), labels.get("status")
        if operation is None or status is None:
            continue
        counts.setdefault(operation, {})[status] = value
    return counts


def _parse_latency_metrics(text: str) -> dict[str, float]:
    observations: dict[str, float] = {}
    for name, labels, value in _parse_metric_samples(text, "calc_latency_seconds_count"):
        operation = labels.get("op")
        if name == "calc_latency_seconds_count" and operation is not None:
            observations[operation] = value
    return observations


def _read_logs(
    start_cursor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(os.getenv("DEVOPS_LOG_PATH", str(ROOT / "logs" / "app.log")))
    timestamp = time.time()
    try:
        resolved_path = str(path.resolve())
        with path.open("rb") as log_file:
            file_stat = os.fstat(log_file.fileno())
            cursor_identity_matches = (
                isinstance(start_cursor, dict)
                and start_cursor.get("source") == resolved_path
                and start_cursor.get("device") == file_stat.st_dev
                and start_cursor.get("inode") == file_stat.st_ino
                and isinstance(start_cursor.get("offset"), int)
                and not isinstance(start_cursor.get("offset"), bool)
                and 0 <= start_cursor["offset"] <= file_stat.st_size
            )
            use_cursor = False
            if cursor_identity_matches:
                cursor_offset = start_cursor["offset"]
                expected_boundary = start_cursor.get("boundary_digest")
                if isinstance(expected_boundary, str):
                    boundary_start = max(0, cursor_offset - 256)
                    log_file.seek(boundary_start)
                    boundary = log_file.read(cursor_offset - boundary_start)
                    use_cursor = hashlib.sha256(boundary).hexdigest() == expected_boundary
                else:
                    use_cursor = True
            if use_cursor:
                start_offset = start_cursor["offset"]
                log_file.seek(start_offset)
                file_bytes = log_file.read()
            else:
                file_bytes = log_file.read()
                start_offset = 0
            end_offset = start_offset + len(file_bytes)
            boundary_start = max(0, end_offset - 256)
            log_file.seek(boundary_start)
            boundary = log_file.read(end_offset - boundary_start)
            boundary_digest = hashlib.sha256(boundary).hexdigest()
    except OSError as exc:
        return {
            "status": "unavailable", "source": str(path),
            "timestamp": timestamp, "detail": str(exc), "events": [],
        }

    raw_lines = file_bytes.splitlines(keepends=True)
    if not use_cursor and len(raw_lines) > MAX_LOG_LINES:
        raw_lines = raw_lines[-MAX_LOG_LINES:]
        start_offset = len(file_bytes) - sum(map(len, raw_lines))

    events = []
    event_offsets = []
    malformed_lines = 0
    offset = start_offset
    for line in raw_lines:
        try:
            event = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            malformed_lines += 1
            offset += len(line)
            continue
        if isinstance(event, dict):
            events.append(event)
            event_offsets.append(offset)
        else:
            malformed_lines += 1
        offset += len(line)
    result: dict[str, Any] = {
        "status": "partial" if malformed_lines else "ok",
        "source": resolved_path,
        "timestamp": time.time(),
        "events": events,
        "event_offsets": event_offsets,
        "window_mode": "after_cursor" if use_cursor else "tail",
        "window_start_offset": start_offset,
        "file_cursor": {
            "source": resolved_path,
            "device": file_stat.st_dev,
            "inode": file_stat.st_ino,
            "offset": end_offset,
            "boundary_digest": boundary_digest,
        },
    }
    if malformed_lines:
        result["malformed_lines"] = malformed_lines
    return result


def _collect_evidence(log_cursor: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collect only observations available from the existing app integrations."""
    try:
        system_metrics = collect_system_metrics()
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        system_metrics = {
            "status": "unavailable",
            "source": "host operating system telemetry",
            "timestamp": time.time(),
            "measurements": {},
            "detail": str(exc),
        }
    logs = _read_logs(log_cursor) if log_cursor is not None else _read_logs()
    return {
        "captured_at": time.time(),
        "health": _get_json("/health"),
        "metrics": _get_metrics(),
        "system_metrics": system_metrics,
        "docker": collect_docker_metrics(),
        "prometheus": collect_prometheus_metrics(),
        "version": _get_json("/admin/version"),
        "logs": logs,
    }


def save_baseline() -> dict[str, Any]:
    """Capture and persist a local evidence snapshot for later comparison."""
    snapshot = _collect_evidence()
    path = Path(os.getenv("DEVOPS_BASELINE_PATH", str(BASELINE_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps({"schema_version": 1, "snapshot": snapshot}, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)
    return snapshot


def _load_baseline() -> dict[str, Any]:
    path = Path(os.getenv("DEVOPS_BASELINE_PATH", str(BASELINE_PATH)))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "unavailable", "detail": str(exc)}
    if not isinstance(data, dict) or not isinstance(data.get("snapshot"), dict):
        return {"status": "unavailable", "detail": "Baseline file has an invalid format"}
    return {"status": "ok", "snapshot": data["snapshot"]}


def _metric_deltas(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, dict[str, float]]:
    before = baseline.get("requests", {})
    after = current.get("requests", {})
    deltas: dict[str, dict[str, float]] = {}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return deltas
    for operation in sorted(set(before) & set(after)):
        prior_statuses = before.get(operation, {})
        current_statuses = after.get(operation, {})
        if not isinstance(prior_statuses, dict) or not isinstance(current_statuses, dict):
            continue
        for status in sorted(set(prior_statuses) & set(current_statuses)):
            previous = prior_statuses[status]
            latest = current_statuses[status]
            if not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
                for value in (previous, latest)
            ):
                continue
            delta = float(latest) - float(previous)
            if delta > 0:
                deltas.setdefault(operation, {})[status] = delta
    return deltas


def _request_metrics_available(metrics: dict[str, Any]) -> bool:
    counters = metrics.get("request_counters", {})
    return (
        metrics.get("status") in {"ok", "partial"}
        and isinstance(counters, dict)
        and counters.get("status", "ok") == "ok"
    )


def _system_metrics_available(metrics: dict[str, Any]) -> bool:
    if metrics.get("status") not in {"ok", "partial"}:
        return False
    measurements = metrics.get("measurements", {})
    if not isinstance(measurements, dict):
        return False
    return any(
        isinstance(measurements.get(key), (int, float))
        and not isinstance(measurements.get(key), bool)
        and math.isfinite(measurements[key])
        and 0 <= measurements[key] <= 100
        for key in ("cpu_utilization_percent", "memory_utilization_percent")
    )


def _docker_containers(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    docker = evidence.get("docker", {})
    docker = docker if isinstance(docker, dict) else {}
    containers = docker.get("containers", []) if isinstance(docker, dict) else []
    return [
        container for container in containers
        if isinstance(container, dict)
    ] if isinstance(containers, list) else []


def _docker_metrics_available(docker: dict[str, Any]) -> bool:
    if not isinstance(docker, dict):
        return False
    containers = docker.get("containers", [])
    if not isinstance(containers, list):
        return False
    if docker.get("status") not in {"ok", "partial"}:
        return False
    return any(
        any(
            isinstance(container.get(key), (int, float))
            and not isinstance(container.get(key), bool)
            and math.isfinite(container[key])
            for key in ("cpu_usage_percent", "memory_usage_percent")
        )
        for container in containers
        if isinstance(container, dict)
    )


def _prometheus_observations_available(prometheus: dict[str, Any]) -> bool:
    if not isinstance(prometheus, dict) or prometheus.get("status") not in {"ok", "partial"}:
        return False
    metric_data = prometheus.get("metrics", {})
    if not isinstance(metric_data, dict):
        return False
    for metric in metric_data.values():
        if not isinstance(metric, dict) or metric.get("status") not in {"ok", "partial"}:
            continue
        observations = metric.get("observations", [])
        if not isinstance(observations, list):
            continue
        for observation in observations:
            if not isinstance(observation, dict) or observation.get("stale") is not False:
                continue
            value = observation.get("latest_value")
            timestamp = observation.get("latest_timestamp")
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and isinstance(timestamp, (int, float))
                and not isinstance(timestamp, bool)
                and math.isfinite(timestamp)
            ):
                return True
    return False


def _prometheus_points(snapshot: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    prometheus = snapshot.get("prometheus", {})
    if not isinstance(prometheus, dict):
        return {}
    metric_data = prometheus.get("metrics", {})
    if not isinstance(metric_data, dict):
        return {}
    collected_at = prometheus.get("timestamp", snapshot.get("captured_at"))
    if (
        not isinstance(collected_at, (int, float))
        or isinstance(collected_at, bool)
        or not math.isfinite(collected_at)
    ):
        return {}
    points = {}
    for metric_name, metric in metric_data.items():
        if (
            not isinstance(metric, dict)
            or metric.get("status") not in {"ok", "partial"}
            or not isinstance(metric.get("unit"), str)
        ):
            continue
        observations = metric.get("observations", [])
        if not isinstance(observations, list):
            continue
        for observation in observations:
            if not isinstance(observation, dict) or observation.get("stale") is not False:
                continue
            value = observation.get("latest_value")
            timestamp = observation.get("latest_timestamp")
            labels = observation.get("labels")
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not isinstance(timestamp, (int, float))
                or isinstance(timestamp, bool)
                or not math.isfinite(timestamp)
                or timestamp > collected_at + 5
                or collected_at - timestamp > 300
                or not isinstance(labels, dict)
            ):
                continue
            label_key = json.dumps(labels, sort_keys=True, separators=(",", ":"))
            points[(metric_name, label_key)] = {
                "metric": metric_name,
                "labels": labels,
                "unit": metric["unit"],
                "value": float(value),
                "timestamp": float(timestamp),
            }
    return points


def _compare_prometheus(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    baseline_source = baseline.get("prometheus", {})
    current_source = current.get("prometheus", {})
    baseline_points = _prometheus_points(baseline)
    current_points = _prometheus_points(current)
    deltas = []
    for key in sorted(set(baseline_points) & set(current_points)):
        before = baseline_points[key]
        after = current_points[key]
        if before["unit"] != after["unit"]:
            continue
        deltas.append({
            "metric": after["metric"],
            "labels": after["labels"],
            "unit": after["unit"],
            "baseline_value": before["value"],
            "current_value": after["value"],
            "delta": after["value"] - before["value"],
            "baseline_timestamp": before["timestamp"],
            "current_timestamp": after["timestamp"],
            "source": current_source.get("source"),
        })

    both_available = (
        isinstance(baseline_source, dict)
        and baseline_source.get("status") in {"ok", "partial"}
        and isinstance(current_source, dict)
        and current_source.get("status") in {"ok", "partial"}
    )
    if deltas and both_available:
        complete = (
            baseline_source.get("status") == "ok"
            and current_source.get("status") == "ok"
        )
        status = "ok" if complete else "partial"
        detail = None if complete else "Some Prometheus query results are incomplete."
    elif both_available:
        status = "partial"
        detail = "No compatible fresh Prometheus series were available in both snapshots."
    else:
        status = "unavailable"
        detail = "Prometheus observations are unavailable in the baseline or current snapshot."
    return {"status": status, "detail": detail, "deltas": deltas}


def _docker_incident_signal(docker: dict[str, Any]) -> bool:
    if not isinstance(docker, dict):
        return False
    if docker.get("status") not in {"ok", "partial"}:
        return False
    containers = docker.get("containers", [])
    if not isinstance(containers, list):
        return False
    for container in containers:
        if not isinstance(container, dict):
            continue
        restart_count = container.get("restart_count")
        if (
            container.get("health_status") == "unhealthy"
            or container.get("status") not in {None, "running"}
            or (
                isinstance(restart_count, (int, float))
                and not isinstance(restart_count, bool)
                and restart_count > 0
            )
        ):
            return True
    return False


def _latency_values(metrics: dict[str, Any]) -> dict[str, float]:
    value = metrics.get("latency_observations", {})
    if isinstance(value, dict) and isinstance(value.get("by_operation"), dict):
        return value["by_operation"]
    return value if isinstance(value, dict) else {}


def _deployment_log_event(event: dict[str, Any]) -> dict[str, Any] | None:
    message = event.get("msg")
    if not isinstance(message, str):
        return None
    match = re.fullmatch(
        r"\s*(deployed|rolled back to)\s+v?([A-Za-z0-9][A-Za-z0-9._+-]*)\s*",
        message,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return {
        "action": "deploy" if match.group(1).lower() == "deployed" else "rollback",
        "version": match.group(2),
    }


def _log_cursors_match(baseline_logs: dict[str, Any], current_logs: dict[str, Any]) -> bool:
    baseline_cursor = baseline_logs.get("file_cursor")
    current_cursor = current_logs.get("file_cursor")
    return (
        isinstance(baseline_cursor, dict)
        and isinstance(current_cursor, dict)
        and current_logs.get("window_mode") == "after_cursor"
        and current_logs.get("window_start_offset") == baseline_cursor.get("offset")
        and all(
            baseline_cursor.get(key) == current_cursor.get(key)
            for key in ("source", "device", "inode")
        )
    )


def _new_log_events(baseline: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    baseline_logs = baseline.get("logs", {})
    current_logs = current.get("logs", {})
    if current_logs.get("status") not in {"ok", "partial"}:
        return []

    baseline_cursor = baseline_logs.get("file_cursor")
    cursor_matches = _log_cursors_match(baseline_logs, current_logs)
    events = current_logs.get("events", [])
    if not isinstance(events, list):
        return []
    if cursor_matches:
        return [event for event in events if isinstance(event, dict)]
    if isinstance(baseline_cursor, dict):
        return []

    baseline_time = baseline_logs.get("timestamp", baseline.get("captured_at"))
    if (
        not isinstance(baseline_time, (int, float))
        or isinstance(baseline_time, bool)
        or not math.isfinite(baseline_time)
    ):
        return []
    baseline_events = baseline_logs.get("events", [])
    existing_counts = Counter(
        json.dumps(event, sort_keys=True, separators=(",", ":"))
        for event in baseline_events
        if isinstance(event, dict)
    ) if isinstance(baseline_events, list) else Counter()
    new_events = []
    for event in events:
        if not isinstance(event, dict):
            continue
        fingerprint = json.dumps(event, sort_keys=True, separators=(",", ":"))
        if existing_counts[fingerprint]:
            existing_counts[fingerprint] -= 1
            continue
        event_timestamp = event.get("ts")
        if (
            isinstance(event_timestamp, (int, float))
            and not isinstance(event_timestamp, bool)
            and math.isfinite(event_timestamp)
            and event_timestamp > baseline_time
        ):
            new_events.append(event)
    return new_events


def _compare_snapshots(
    baseline_result: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    if baseline_result.get("status") != "ok":
        unavailable_sources = ["metrics", "version", "logs"]
        if "prometheus" in current:
            unavailable_sources.append("prometheus")
        return {
            "status": "unavailable",
            "detail": baseline_result.get("detail", "Baseline is unavailable"),
            "comparable_sources": [],
            "unavailable_sources": unavailable_sources,
            "request_deltas": {},
            "latency_observation_deltas": {},
            "prometheus_comparison": {
                "status": "unavailable",
                "detail": "A baseline snapshot is unavailable.",
                "deltas": [],
            },
            "new_error_logs": [],
            "deployment_changed": False,
            "regression_signal": False,
        }

    baseline = baseline_result["snapshot"]
    baseline_metrics = baseline.get("metrics", {})
    current_metrics = current.get("metrics", {})
    if _request_metrics_available(baseline_metrics) and _request_metrics_available(current_metrics):
        request_deltas = _metric_deltas(baseline_metrics, current_metrics)
        before_latency = _latency_values(baseline_metrics)
        after_latency = _latency_values(current_metrics)
        latency_deltas = {}
        for operation in sorted(set(before_latency) & set(after_latency)):
            previous = before_latency[operation]
            latest = after_latency[operation]
            if not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
                for value in (previous, latest)
            ):
                continue
            delta = float(latest) - float(previous)
            if delta > 0:
                latency_deltas[operation] = delta
    else:
        request_deltas = {}
        latency_deltas = {}

    current_logs = current.get("logs", {})
    new_logs = _new_log_events(baseline, current)
    new_error_logs = [
        event for event in new_logs if str(event.get("level", "")).upper() == "ERROR"
    ]

    baseline_version_data = baseline.get("version", {}).get("data", {})
    current_version_data = current.get("version", {}).get("data", {})
    baseline_version = (
        baseline_version_data.get("version")
        if baseline.get("version", {}).get("status") == "ok"
        and isinstance(baseline_version_data, dict)
        else None
    )
    current_version = (
        current_version_data.get("version")
        if current.get("version", {}).get("status") == "ok"
        and isinstance(current_version_data, dict)
        else None
    )
    version_changed = (
        baseline.get("version", {}).get("status") == "ok"
        and current.get("version", {}).get("status") == "ok"
        and isinstance(baseline_version, str)
        and bool(baseline_version)
        and isinstance(current_version, str)
        and bool(current_version)
        and baseline_version != current_version
    )
    deployment_events = []
    for event in new_logs:
        parsed = _deployment_log_event(event)
        if parsed is not None:
            deployment_events.append({
                **parsed,
                "timestamp": event.get("ts"),
                "source": current_logs.get("source", "application logs"),
                "event": event,
            })
    explicit_version_change = any(
        isinstance(baseline_version, str)
        and bool(baseline_version)
        and deployment["version"] != baseline_version
        for deployment in deployment_events
    )
    deployment_changed = bool(version_changed or explicit_version_change)
    history = current_version_data.get("history", [])
    previous_deployment_version = None
    if (
        current.get("version", {}).get("status") == "ok"
        and isinstance(history, list)
        and len(history) >= 2
        and isinstance(history[-2], dict)
    ):
        previous_deployment_version = history[-2].get("version")
    error_delta = sum(
        max(0.0, count)
        for statuses in request_deltas.values()
        for status, count in statuses.items()
        if status == "error"
    )
    comparable_sources = []
    unavailable_sources = []
    if (
        _request_metrics_available(baseline_metrics)
        and _request_metrics_available(current_metrics)
    ):
        comparable_sources.append("metrics")
    else:
        unavailable_sources.append("metrics")

    baseline_version_valid = (
        baseline.get("version", {}).get("status") == "ok"
        and isinstance(baseline_version, str)
        and bool(baseline_version)
    )
    current_version_valid = (
        current.get("version", {}).get("status") == "ok"
        and isinstance(current_version, str)
        and bool(current_version)
    )
    if baseline_version_valid and current_version_valid:
        comparable_sources.append("version")
    else:
        unavailable_sources.append("version")

    baseline_logs = baseline.get("logs", {})
    current_logs_status = current_logs.get("status")
    baseline_logs_status = baseline_logs.get("status")
    baseline_log_time = baseline_logs.get(
        "timestamp", baseline.get("captured_at")
    )
    has_legacy_log_window = (
        not isinstance(baseline_logs.get("file_cursor"), dict)
        and baseline_logs_status in {None, "ok", "partial"}
        and isinstance(baseline_log_time, (int, float))
        and not isinstance(baseline_log_time, bool)
        and math.isfinite(baseline_log_time)
    )
    logs_comparable = (
        current_logs_status in {"ok", "partial"}
        and baseline_logs_status in {None, "ok", "partial"}
        and (
            _log_cursors_match(baseline_logs, current_logs)
            or has_legacy_log_window
        )
    )
    if logs_comparable:
        comparable_sources.append("logs")
    else:
        unavailable_sources.append("logs")

    prometheus_comparison = {"status": "unavailable", "deltas": []}
    if "prometheus" in baseline or "prometheus" in current:
        prometheus_comparison = _compare_prometheus(baseline, current)
        if prometheus_comparison["deltas"]:
            comparable_sources.append("prometheus")
        if prometheus_comparison["status"] != "ok":
            unavailable_sources.append("prometheus")

    if not comparable_sources:
        comparison_status = "unavailable"
        comparison_detail = "No baseline evidence sources were comparable."
    elif unavailable_sources:
        comparison_status = "partial"
        comparison_detail = (
            "Baseline comparison is partial; unavailable or incomparable sources: "
            + ", ".join(unavailable_sources)
        )
    else:
        comparison_status = "ok"
        comparison_detail = None
    return {
        "status": comparison_status,
        "detail": comparison_detail,
        "comparable_sources": comparable_sources,
        "unavailable_sources": unavailable_sources,
        "request_deltas": request_deltas,
        "latency_observation_deltas": latency_deltas,
        "prometheus_comparison": prometheus_comparison,
        "new_logs": new_logs,
        "new_error_logs": new_error_logs,
        "baseline_version": baseline_version,
        "current_version": current_version,
        "previous_deployment_version": previous_deployment_version,
        "deployment_events": deployment_events,
        "detected_deployment_version": (
            deployment_events[-1]["version"] if deployment_events else None
        ),
        "deployment_changed": deployment_changed,
        "regression_signal": error_delta > 0 or bool(new_error_logs),
        "baseline_metrics_status": baseline_metrics.get("status", "unavailable"),
        "current_metrics_status": current_metrics.get("status", "unavailable"),
        "logs_status": current_logs.get("status", "unavailable"),
        "logs_window_mode": current_logs.get("window_mode", "timestamp_fallback"),
        "logs_window_status": (
            "cursor"
            if _log_cursors_match(baseline.get("logs", {}), current_logs)
            else "timestamp_fallback"
            if not isinstance(baseline.get("logs", {}).get("file_cursor"), dict)
            and isinstance(
                baseline.get("logs", {}).get("timestamp", baseline.get("captured_at")),
                (int, float),
            )
            else "unavailable"
        ),
        "metrics_window": {
            "baseline_timestamp": baseline_metrics.get("timestamp"),
            "current_timestamp": current_metrics.get("timestamp"),
        },
    }


def _trace(state: IncidentState, message: str) -> list[str]:
    return [message]


def _collect_node(state: IncidentState) -> dict[str, Any]:
    baseline = _load_baseline()
    baseline_logs = baseline.get("snapshot", {}).get("logs", {})
    log_cursor = baseline_logs.get("file_cursor")
    evidence = (
        _collect_evidence(log_cursor)
        if isinstance(log_cursor, dict)
        else _collect_evidence()
    )
    available = [
        name for name, value in evidence.items()
        if isinstance(value, dict) and value.get("status") == "ok"
    ]
    return {
        "baseline": baseline,
        "evidence": evidence,
        "trace": _trace(
            state,
            "Collected application health, app-exported request/latency metrics, "
            "Prometheus time series, host CPU/memory, Docker container telemetry, "
            "deployment version, and local logs; "
            f"available integrations: {', '.join(available) or 'none'}.",
        ),
    }


def _compare_node(state: IncidentState) -> dict[str, Any]:
    baseline = state.get("baseline")
    if not isinstance(baseline, dict):
        baseline = _load_baseline()
    comparison = _compare_snapshots(baseline, state["evidence"])
    if comparison["status"] == "ok":
        trace = "Compared current observations with the saved baseline."
    elif comparison["status"] == "partial":
        trace = "Baseline comparison is partial: " + comparison["detail"]
    else:
        trace = "Baseline comparison unavailable: " + comparison.get(
            "detail", "No comparable evidence sources were available."
        )
    return {
        "baseline": baseline,
        "comparison": comparison,
        "trace": _trace(state, trace),
    }


def _select_specialists(state: IncidentState) -> list[str]:
    evidence = state["evidence"]
    comparison = state["comparison"]
    query = state.get("query", "")
    selected = []
    prometheus = evidence.get("prometheus", {})
    docker = evidence.get("docker", {})
    docker = docker if isinstance(docker, dict) else {}
    if (
        _request_metrics_available(evidence.get("metrics", {}))
        or _system_metrics_available(evidence.get("system_metrics", {}))
        or _docker_metrics_available(docker)
        or _prometheus_observations_available(prometheus)
    ):
        selected.append("monitoring")
    if comparison.get("regression_signal") or any(
        word in query.lower() for word in ("incident", "error", "failure", "diagnos")
    ) or _docker_incident_signal(docker):
        selected.append("incident")
    if comparison.get("regression_signal"):
        selected.append("code")
    if comparison.get("deployment_changed"):
        selected.append("cicd")
    if (
        evidence.get("health", {}).get("status") == "ok"
        or comparison.get("deployment_changed")
        or _prometheus_observations_available(prometheus)
        or (
            docker.get("status") in {"ok", "partial"}
            and bool(_docker_containers(evidence))
        )
    ):
        selected.append("infrastructure")

    security_pattern = re.compile(
        r"\b(secur(?:ity|e)|unauthori[sz]ed|forbidden|permission|injection|"
        r"exploit|suspicious|authentication)\b",
        re.IGNORECASE,
    )
    log_text = " ".join(
        str(event.get("msg", "")) for event in evidence.get("logs", {}).get("events", [])
    )
    if security_pattern.search(query) or security_pattern.search(log_text):
        selected.append("security")
    return [agent for agent in SPECIALIST_ORDER if agent in selected]


def _specialist_evidence(agent: str, state: IncidentState) -> dict[str, Any]:
    evidence = state["evidence"]
    comparison = state["comparison"]
    extraction = state.get("evidence_extraction")
    if not isinstance(extraction, dict):
        extraction = extract_evidence(
            evidence,
            state.get("baseline", {"status": "unavailable"}),
            comparison,
        )
    else:
        extraction = validate_extraction(extraction)
    role_evidence = package_for_role(extraction, agent, raw_evidence=evidence)
    role_observations = []
    for observation in role_evidence["observations"]:
        value_text = json.dumps(observation["value"], ensure_ascii=False, sort_keys=True)
        statement = observation.get("evidence_text") or (
            f"{observation['metric_or_event']} = {value_text}"
            + (f" {observation['unit']}" if observation["unit"] else "")
        )
        role_observations.append({
            "statement": statement,
            "source": observation["source_path"],
            "timestamp": observation["timestamp"],
            "status": observation["status"],
            "evidence_id": observation["evidence_id"],
        })

    def attach_extraction(payload: dict[str, Any]) -> dict[str, Any]:
        existing = payload.get("verified_observations", [])
        if not isinstance(existing, list):
            existing = []
        seen = {
            (item.get("source"), item.get("timestamp"), item.get("statement"))
            for item in existing if isinstance(item, dict)
        }
        existing.extend(
            item for item in role_observations
            if (item["source"], item["timestamp"], item["statement"]) not in seen
        )
        payload["verified_observations"] = existing
        payload["deterministic_evidence"] = role_evidence
        return payload

    unavailable = {"status": "unavailable", "detail": "Not collected"}
    if agent == "code":
        return attach_extraction({
            "code_changes": evidence.get(
                "code_changes",
                {
                    "status": "unavailable",
                    "detail": "No source-control diff integration is configured.",
                },
            )
        })
    if agent == "security":
        security_pattern = re.compile(
            r"\b(secur(?:ity|e)|unauthori[sz]ed|forbidden|permission|injection|"
            r"exploit|suspicious|authentication|login alert)\b",
            re.IGNORECASE,
        )
        logs = evidence.get("logs", {"status": "unavailable", "events": []})
        events = logs.get("events", []) if isinstance(logs, dict) else []
        security_events = [
            event for event in events
            if isinstance(event, dict)
            and security_pattern.search(str(event.get("msg", "")))
        ] if isinstance(events, list) else []
        return attach_extraction({
            "security_events": {
                "status": logs.get("status", "unavailable"),
                "source": logs.get("source"),
                "timestamp": logs.get("timestamp", evidence.get("captured_at")),
                "events": security_events,
                "detail": (
                    "Only security-related log events are supplied; no dedicated "
                    "security event source is configured."
                ),
            },
            "security_telemetry": {
                "status": "unavailable",
                "detail": "No dedicated security event source is configured.",
            },
            "verified_observations": [
                {
                    "statement": str(event.get("msg", "")),
                    "source": f"security_events.events[{index}].msg",
                    "timestamp": event.get("ts"),
                }
                for index, event in enumerate(security_events)
            ],
        })
    version_evidence = evidence.get("version", unavailable)
    version_data = (
        version_evidence.get("data", {})
        if isinstance(version_evidence, dict) else {}
    )
    pipeline_evidence = evidence.get(
        "pipeline",
        version_data.get("pipeline", unavailable)
        if isinstance(version_data, dict) else unavailable,
    )
    if not isinstance(pipeline_evidence, dict):
        pipeline_evidence = unavailable
    sources = {
        "health": evidence.get("health", unavailable),
        "metrics": evidence.get("metrics", unavailable),
        "system_metrics": evidence.get("system_metrics", unavailable),
        "deployment": version_evidence,
        "pipeline": pipeline_evidence,
        "logs": evidence.get(
            "logs", {"status": "unavailable", "events": [], "detail": "Not collected"}
        ),
        "docker": evidence.get(
            "docker",
            {"status": "unavailable", "containers": [], "detail": "Not collected"},
        ),
        "prometheus": evidence.get(
            "prometheus",
            {"status": "unavailable", "metrics": {}, "detail": "Not collected"},
        ),
        "baseline_comparison": comparison,
    }
    relevant_sources = {
        "monitoring": (
            "metrics", "system_metrics", "docker", "prometheus",
            "baseline_comparison",
        ),
        "incident": (
            "health", "metrics", "system_metrics", "deployment", "logs",
            "docker", "prometheus", "baseline_comparison",
        ),
        "cicd": (
            "health", "metrics", "deployment", "pipeline", "logs", "docker",
            "baseline_comparison",
        ),
        "infrastructure": (
            "health", "system_metrics", "docker", "prometheus",
            "baseline_comparison",
        ),
    }
    if agent not in relevant_sources:
        raise ValueError(f"Unknown specialist '{agent}'")
    selected_sources = list(relevant_sources[agent])
    if agent == "cicd" and comparison.get("deployment_changed"):
        selected_sources.append("prometheus")
    result = {key: sources[key] for key in selected_sources}
    if agent == "cicd" and not comparison.get("deployment_changed"):
        result["baseline_comparison"] = {
            key: value for key, value in comparison.items()
            if key != "prometheus_comparison"
        }
    relevant_fact_prefixes = {
        "monitoring": (
            "metrics.", "system_metrics.", "docker.", "prometheus.",
            "baseline_comparison.",
        ),
        "incident": (
            "health.", "metrics.", "system_metrics.", "deployment.",
            "version.", "logs.", "docker.", "prometheus.",
            "baseline_comparison.",
        ),
        "cicd": (
            "health.", "metrics.", "deployment.", "version.", "pipeline.", "logs.",
            "docker.", "prometheus.", "baseline_comparison.",
        ),
        "infrastructure": (
            "health.", "system_metrics.", "docker.", "prometheus.",
            "baseline_comparison.",
        ),
    }[agent]
    observed_facts = _observed_facts(
        evidence,
        state.get("baseline", {"status": "unavailable"}),
        comparison,
    )
    result["verified_observations"] = [
        fact for fact in observed_facts
        if fact.get("source", "").startswith(relevant_fact_prefixes)
    ]
    return attach_extraction(result)


def _valid_analysis(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("status") != "ok":
        return False
    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        return False
    confidence = analysis.get("confidence")
    return (
        isinstance(analysis.get("summary"), str)
        and isinstance(analysis.get("findings"), list)
        and all(isinstance(item, str) for item in analysis["findings"])
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(confidence)
        and 0 <= confidence <= 1
        and isinstance(analysis.get("recommended_checks"), list)
        and all(isinstance(item, str) for item in analysis["recommended_checks"])
    )


def _flatten_evidence(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    flattened: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.extend(_flatten_evidence(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            flattened.extend(_flatten_evidence(child, f"{prefix}[{index}]"))
    else:
        flattened.append((prefix, value))
    return flattened


_NUMBER_PATTERN = re.compile(
    r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?!\w)"
    r"(?:\s*%|\s+percent(?:age)?)?",
    re.IGNORECASE,
)


def _number_from_claim(match: re.Match[str]) -> tuple[float, bool]:
    token = match.group(0).strip()
    is_percent = "%" in token or bool(re.search(r"\bpercent(?:age)?\b", token, re.I))
    token = re.sub(r"\s*(?:%|percent(?:age)?)$", "", token, flags=re.I)
    return float(token), is_percent


def _claim_topic(text: str, start: int, end: int) -> str | None:
    patterns = {
        "cpu": r"\b(?:cpu|processor)(?:[\s_-]+(?:usage|utilization|percent))?\b",
        "memory": r"\b(?:memory|ram)(?:[\s_-]+(?:usage|utilization|percent))?\b",
        "latency": (
            r"\b(?:latency(?:[\s_-]+p\d{2})?|p\d{2}[\s_-]+latency|"
            r"response[\s_-]+time|p\d{2})\b"
        ),
        "network": r"\b(network|received bytes|transmitted bytes|"
                   r"network receive|network transmit)\b",
        "block_io": r"\b(block[\s-]?i/?o|block read|block write|"
                    r"read bytes|write bytes)\b",
        "error_rate": (
            r"\b(?:http[\s_-]+)?(?:error|failure)[\s_-]+rate\b"
        ),
        "request_count": r"\b(request counter|request count|requests)\b",
        "http_status": r"\b(?:http[\s_-]*status|status[\s_-]+code)\b",
        "restart_count": r"\b(restart(?:s| count)?|restarted)\b",
        "version": r"\b(version|release)\b",
        "timestamp": r"\b(timestamp|time|at \d{1,2}:?\d{0,2})\b",
        "deployment": r"\bdeployment\b",
    }
    midpoint = (start + end) / 2
    candidates = []
    for topic, pattern in patterns.items():
        for match in re.finditer(pattern, text, re.IGNORECASE):
            distance = max(match.start() - midpoint, 0, midpoint - match.end())
            candidates.append((distance, topic))
    return min(candidates)[1] if candidates else None


def _normalized_key(path: str) -> str:
    return re.sub(r"[^a-z0-9]", "", path.lower().split(".")[-1].split("[")[0])


def _same_number(left: Any, right: float) -> bool:
    if isinstance(left, bool) or not isinstance(left, (int, float)):
        return False
    return math.isclose(float(left), right, rel_tol=1e-9, abs_tol=1e-9)


def _numeric_evidence_paths(
    topic: str | None, evidence: dict[str, Any], value: float, is_percent: bool
) -> list[str]:
    aliases = {
        "cpu": ("cpu", "cpuusage", "cpuusagepercent", "cpuutilization", "cpupercent",
                "processorusage", "processorutilization", "cpupct"),
        "memory": ("memory", "memoryusage", "memoryusagepercent", "memoryutilization",
                   "memorypercent", "memoryusagebytes", "memorylimitbytes",
                   "memoryusagemib", "hostprocessmemorymib", "ramusage", "rampercent"),
        "latency": ("latency", "latencyseconds", "p95latency", "p95latencyseconds"),
        "network": (
            "networkrxbytes", "networktxbytes",
            "networkreceivedbytes", "networktransmittedbytes",
        ),
        "block_io": ("blockreadbytes", "blockwritebytes"),
        "error_rate": ("errorrate", "errorratepercent", "applicationerrorrate",
                       "applicationerrorratepercent", "failurerate"),
        "request_count": (),
        "restart_count": ("restartcount", "restarts"),
        "version": (),
        "timestamp": (),
        "deployment": (),
        "http_status": ("httpstatus", "statuscode"),
    }
    matches = []
    for path, observed in _flatten_evidence(evidence):
        key = _normalized_key(path)
        path_key = re.sub(r"[^a-z0-9]", "", path.lower())
        if topic in aliases and aliases[topic] and key in aliases[topic]:
            if _same_number(observed, value) and (
                not is_percent
                or key.endswith("percent")
                or key.endswith("percentage")
            ):
                matches.append(path)
        elif topic == "request_count" and key in {
            "ok", "error", "clienterror", "requests", "requestcount"
        } and _same_number(observed, value):
            matches.append(path)
        elif topic == "request_count" and (
            "requestrate" in path_key
            or "successfulrequestrate" in path_key
            or "errorrequestrate" in path_key
        ) and _same_number(observed, value):
            matches.append(path)
        elif topic in {"cpu", "memory", "latency", "error_rate"} and key in {
            "latestvalue", "value"
        } and _same_number(observed, value):
            metric_tokens = {
                "cpu": ("cpu", "processor"),
                "memory": ("memory", "resident"),
                "latency": ("latency", "p95", "response"),
                "error_rate": ("errorrate", "httperror", "failure"),
            }[topic]
            if any(token in path_key for token in metric_tokens):
                matches.append(path)
        elif topic == "restart_count" and key in {"restartcount", "restarts"}:
            if _same_number(observed, value):
                matches.append(path)
        elif topic in {"network", "block_io"} and key in aliases[topic]:
            if _same_number(observed, value):
                matches.append(path)
        elif topic == "version" and key in {"version", "release"}:
            if isinstance(observed, (int, float)) and _same_number(observed, value):
                matches.append(path)
            elif isinstance(observed, str) and observed == str(value):
                matches.append(path)
        elif topic == "timestamp" and key in {"ts", "timestamp", "capturedat"}:
            if _same_number(observed, value):
                matches.append(path)
        elif topic == "deployment" and key in {"deploymentstatus", "status"}:
            if _same_number(observed, value):
                matches.append(path)
    if topic == "request_count":
        request_sets = [
            ("metrics.requests", evidence.get("metrics", {}).get("requests", {})),
            (
                "baseline_comparison.request_deltas",
                evidence.get("baseline_comparison", {}).get("request_deltas", {}),
            ),
        ]
        for root, operations in request_sets:
            if not isinstance(operations, dict):
                continue
            for operation, statuses in operations.items():
                if not isinstance(statuses, dict):
                    continue
                counts = [
                    item for item in statuses.values()
                    if isinstance(item, (int, float))
                    and not isinstance(item, bool)
                    and math.isfinite(item)
                    and item >= 0
                ]
                if counts and _same_number(sum(counts), value):
                    matches.extend(
                        f"{root}.{operation}.{status}"
                        for status, item in statuses.items()
                        if isinstance(item, (int, float))
                        and not isinstance(item, bool)
                        and math.isfinite(item)
                        and item >= 0
                    )
    return matches


def _derived_error_rates(evidence: dict[str, Any]) -> list[tuple[float, str]]:
    rates: list[tuple[float, str]] = []
    for path, observed in _flatten_evidence(evidence):
        key = _normalized_key(path)
        if key in {"errorrate", "errorratepercent", "applicationerrorrate",
                   "applicationerrorratepercent", "failurerate"}:
            if isinstance(observed, (int, float)) and not isinstance(observed, bool):
                value = float(observed)
                if key.endswith("percent") or key.endswith("percentage"):
                    rates.append((value, path))

    metrics = evidence.get("metrics", {})
    for source_name, counter_sets in (
        ("metrics.requests", metrics.get("requests", {})),
        ("baseline_comparison.request_deltas",
         evidence.get("baseline_comparison", {}).get("request_deltas", {})),
    ):
        if not isinstance(counter_sets, dict):
            continue
        for operation, statuses in counter_sets.items():
            if not isinstance(statuses, dict) or "error" not in statuses:
                continue
            values = [
                float(count) for count in statuses.values()
                if isinstance(count, (int, float)) and not isinstance(count, bool)
            ]
            denominator = sum(values)
            numerator = statuses.get("error")
            if (
                len(values) > 1
                and denominator > 0
                and isinstance(numerator, (int, float))
                and not isinstance(numerator, bool)
            ):
                rates.append((
                    float(numerator) / denominator * 100,
                    f"{source_name}.{operation} (error={numerator:g}, total={denominator:g})",
                ))
    return rates


def _validate_finding(finding: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Conservatively check numeric claims; prose remains a model hypothesis."""
    evidence = {
        key: value for key, value in evidence.items()
        if key != "verified_observations"
    }
    numbers = []
    reasons = []
    evidence_refs: list[str] = []
    flattened = _flatten_evidence(evidence)
    lowered = finding.lower()
    non_numeric_refs: list[str] = []
    evidence_strings = [
        (path, value)
        for path, value in flattened
        if isinstance(value, str)
    ]
    event_strings = [
        (path, value)
        for path, value in evidence_strings
        if re.search(r"\.events\[\d+\]\.msg$", path)
    ]
    docker_evidence = evidence.get("docker", {})
    docker_containers = (
        docker_evidence.get("containers", [])
        if isinstance(docker_evidence, dict) else []
    )
    docker_containers = (
        [container for container in docker_containers if isinstance(container, dict)]
        if isinstance(docker_containers, list) else []
    )
    container_id_matches = list(re.finditer(
        r"(?<![A-Fa-f0-9])(?:[A-Fa-f0-9]{12,64})(?![A-Fa-f0-9])",
        finding,
    ))
    container_identifier_matches = list(re.finditer(
        r"\b(?:container\s+)?id\s*(?:is|[:=])\s*[\"'`]?([A-Za-z0-9][A-Za-z0-9_.-]*)",
        finding,
        re.IGNORECASE,
    ))
    for match in container_id_matches:
        exact_paths = [
            f"docker.containers[{index}].id"
            for index, container in enumerate(docker_containers)
            if isinstance(container.get("id"), str)
            and container["id"].lower() == match.group(0).lower()
        ]
        if exact_paths:
            evidence_refs.extend(exact_paths)
        else:
            reasons.append(
                f"container ID {match.group(0)} is not present in the supplied evidence"
            )
    for match in container_identifier_matches:
        identifier = match.group(1)
        if identifier.lower() in {"unavailable", "unknown", "not-provided"}:
            continue
        exact_paths = [
            f"docker.containers[{index}].id"
            for index, container in enumerate(docker_containers)
            if isinstance(container.get("id"), str)
            and container["id"].lower() == identifier.lower()
        ]
        if exact_paths:
            evidence_refs.extend(exact_paths)
        else:
            reasons.append(
                f"container ID {identifier} is not present in the supplied evidence"
            )
    for match in re.finditer(
        r"\bcontainer\s+name\s*[:=]\s*[\"'`]?([A-Za-z0-9][A-Za-z0-9_.-]*)",
        finding,
        re.IGNORECASE,
    ):
        exact_paths = [
            f"docker.containers[{index}].name"
            for index, container in enumerate(docker_containers)
            if isinstance(container.get("name"), str)
            and container["name"].lower() == match.group(1).lower()
        ]
        if exact_paths:
            evidence_refs.extend(exact_paths)
        else:
            reasons.append(
                f"container name {match.group(1)} is not present in the supplied evidence"
            )
    for match in re.finditer(
        r"\bcontainer\s+(?!id\b|identifier\b)([A-Za-z][A-Za-z0-9_.-]*)\s+"
        r"(?:is|has|shows|uses|reports)\b",
        finding,
        re.IGNORECASE,
    ):
        exact_paths = [
            f"docker.containers[{index}].name"
            for index, container in enumerate(docker_containers)
            if isinstance(container.get("name"), str)
            and container["name"].lower() == match.group(1).lower()
        ]
        if exact_paths:
            evidence_refs.extend(exact_paths)
        else:
            reasons.append(
                f"container name {match.group(1)} is not present in the supplied evidence"
            )
    ip_matches = list(re.finditer(
        r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)",
        finding,
    ))
    timestamp_matches = list(re.finditer(
        r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}"
        r"(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
        r"|\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?(?:AM|PM))?\b",
        finding,
        re.IGNORECASE,
    ))
    for match in ip_matches:
        exact_refs = [
            path for path, value in evidence_strings
            if match.group(0) in value
        ]
        if exact_refs:
            evidence_refs.extend(exact_refs)
        else:
            reasons.append(
                f"IP address {match.group(0)} is not present in the supplied evidence"
            )
    for match in timestamp_matches:
        exact_refs = [
            path for path, value in evidence_strings
            if match.group(0) in value
        ]
        if exact_refs:
            evidence_refs.extend(exact_refs)
        else:
            reasons.append(
                f"timestamp {match.group(0)} is not present in the supplied evidence"
            )

    observed_security_event_patterns = (
        r"\bsuspicious login\b",
        r"\b(?:failed authentication|authentication failed|authentication failure)\b",
        r"\b(?:successful authentication|authentication successful|successful login)\b",
        r"\bsecurity alert\b",
        r"\bunauthorized login\b",
        r"\bunauthorised login\b",
    )
    for pattern in observed_security_event_patterns:
        for match in re.finditer(pattern, finding, re.IGNORECASE):
            exact_refs = [
                path for path, value in event_strings
                if re.search(pattern, value, re.IGNORECASE)
            ]
            if exact_refs:
                non_numeric_refs.extend(exact_refs)
            else:
                reasons.append(
                    "security event claim "
                    f"{match.group(0)!r} is not present in the supplied evidence"
                )

    classification_pattern = (
        r"\b(?:brute[\s-]?force|credential[\s-]?stuffing|password[\s-]?spraying|"
        r"phishing|malware|ransomware|botnet|exfiltration|"
        r"command[\s-]+and[\s-]+control|c2|zero[\s-]?day|"
        r"apt(?:\s+\d+)?|threat actor|threat intelligence|"
        r"malicious (?:ip|address|domain)|compromised account)\b"
    )
    for match in re.finditer(classification_pattern, finding, re.IGNORECASE):
        exact_refs = [
            path for path, value in event_strings
            if re.search(re.escape(match.group(0)), value, re.IGNORECASE)
        ]
        if exact_refs:
            non_numeric_refs.extend(exact_refs)
        else:
            reasons.append(
                "security classification or threat attribution claim "
                f"{match.group(0)!r} is not verified by the supplied evidence"
            )

    availability_sources = (
        ("docker", r"\b(?:docker|container)(?:\s+(?:metrics|telemetry|data|containers?))?\b"),
        ("prometheus", r"\bprometheus(?:\s+(?:metrics|observations|data|telemetry))?\b"),
        ("system_metrics", r"\b(?:host|system)\s+(?:cpu|memory|resource)?\s*metrics\b"),
        ("metrics", r"\b(?:application\s+)?(?:request\s+)?metrics\b"),
        ("deployment", r"\bdeployment(?:\s+(?:status|evidence|record))?\b"),
        ("pipeline", r"\b(?:ci/?cd\s+)?pipeline(?:\s+(?:status|evidence|results?))?\b"),
        ("health", r"\bhealth(?:-check)?(?:\s+(?:status|result|check))?\b"),
        ("logs", r"\b(?:application\s+)?logs?\b"),
        ("security_telemetry", r"\b(?:dedicated\s+)?security\s+(?:event\s+)?(?:source|telemetry)\b"),
        ("security_events", r"\bsecurity\s+(?:events?|logs?)\b"),
    )
    claims_source_unavailable = bool(re.search(
        r"\b(?:unavailable|not available|not supplied|not provided|"
        r"not recorded|missing)\b",
        lowered,
    ))
    claims_source_absent = bool(re.search(
        r"\bno\b[^.\n]{0,80}\b(?:evidence|metrics|observations?|data|"
        r"events?|logs?|records?|source|telemetry)\b",
        lowered,
    ))
    if claims_source_unavailable or claims_source_absent:
        availability_clauses = re.split(r"(?<=[.!?;])\s+|,\s*|\n+", finding)
        availability_marker = re.compile(
            r"\b(?:unavailable|not available|not supplied|not provided|"
            r"not recorded|missing|no\b)",
            re.IGNORECASE,
        )
        specific_source_mentioned = bool(re.search(
            r"\b(?:docker|container|prometheus|host|system)\b",
            lowered,
        ))
        for source_name, source_pattern in availability_sources:
            source_clauses = [
                clause for clause in availability_clauses
                if re.search(source_pattern, clause, re.IGNORECASE)
                and availability_marker.search(clause)
            ]
            if not source_clauses:
                continue
            if source_name == "metrics" and specific_source_mentioned:
                continue
            source_statuses = [
                (path, value)
                for path, value in flattened
                if path.split(".", 1)[0] == source_name
                and _normalized_key(path) == "status"
                and isinstance(value, str)
            ]
            unavailable_statuses = [
                (path, value) for path, value in source_statuses
                if value.lower() == "unavailable"
            ]
            if unavailable_statuses:
                evidence_refs.extend(path for path, _ in unavailable_statuses)
            elif source_statuses:
                reasons.append(
                    f"{source_name} is not reported unavailable; supplied status "
                    + ", ".join(f"{path}={value}" for path, value in source_statuses)
                )
            else:
                reasons.append(
                    f"unavailability of {source_name} cannot be confirmed from the supplied evidence"
                )

    state_claims = {
        "running": ("status", "running"),
        "stopped": ("status", "stopped"),
        "healthy": ("health_status", "healthy"),
        "unhealthy": ("health_status", "unhealthy"),
    }
    for state_word, (field_name, expected) in state_claims.items():
        if not re.search(rf"\b{state_word}\b", lowered):
            continue
        matching_paths = [
            path for path, value in flattened
            if path.startswith("docker.containers[")
            and _normalized_key(path) == field_name
            and isinstance(value, str)
            and value.lower() == expected
        ]
        if matching_paths:
            evidence_refs.extend(matching_paths)
        elif "container" in lowered:
            reasons.append(
                f"container {state_word} state is not supported by the supplied Docker evidence"
            )

    health_ok_claim = re.search(
        r"\bhealth(?:\s+status)?\s+(?:is\s+)?(?:okay|ok|healthy)\b",
        lowered,
    )
    if health_ok_claim:
        health_statuses = [
            (path, value)
            for path, value in flattened
            if path in {"health.data.status", "health.status"}
            or (
                path.startswith("docker.containers[")
                and _normalized_key(path) == "healthstatus"
            )
        ]
        valid_health = [
            (path, value) for path, value in health_statuses
            if isinstance(value, str) and value.lower() in {"ok", "healthy"}
        ]
        if valid_health:
            evidence_refs.extend(path for path, _ in valid_health)
        elif health_statuses:
            reasons.append("health is not reported healthy in the supplied evidence")

    timestamp_absence_pattern = (
        r"\bno\b[^.\n]{0,100}\b(?:timestamps?|times?)\b"
        r"[^.\n]{0,50}\b(?:recorded|available|provided|present)\b"
        r"|\b(?:timestamps?|times?)\b[^.\n]{0,35}"
        r"\b(?:not recorded|unavailable|not available|not provided|missing)\b"
    )
    for match in re.finditer(timestamp_absence_pattern, finding, re.IGNORECASE):
        timestamp_refs = [
            path for path, value in flattened
            if _normalized_key(path) in {"ts", "timestamp", "capturedat", "time"}
            and value is not None
        ]
        if timestamp_refs:
            evidence_refs.extend(timestamp_refs)
            reasons.append(
                "timestamp absence claim conflicts with supplied timestamps at "
                + ", ".join(sorted(timestamp_refs))
            )
        else:
            reasons.append(
                "timestamp absence cannot be confirmed from the supplied evidence"
            )

    deployment_status_patterns = (
        (r"\b(?:failed|failure|unsuccessful)\s+deployment\b|\bdeployment\s+(?:(?:was|has been|is|status is)\s+)?(?:failed|failure|unsuccessful)\b",
         {"failed", "failure", "unsuccessful"}),
        (r"\b(?:successful|succeeded|completed)\s+deployment\b|\bdeployment\s+(?:(?:was|has been|is|status is)\s+)?(?:successful|succeeded|completed)\b",
         {"successful", "succeeded", "completed"}),
        (r"\b(?:rolled back|rollback)\s+(?:the\s+)?deployment\b|\bdeployment\s+(?:was\s+)?rolled back\b",
         {"rolled back", "rollback"}),
        (r"\bdeployment\s+(?:(?:was|has been|is)\s+)?(?:started|promoted|deployed|occurred)\b",
         {"started", "promoted", "deployed", "occurred"}),
    )
    deployment_claims = [
        statuses for pattern, statuses in deployment_status_patterns
        if re.search(pattern, lowered)
    ]
    for expected_statuses in deployment_claims:
        status_paths = [
            path for path, value in flattened
            if _normalized_key(path) in {"deploymentstatus", "status"}
            and ("deployment" in path.lower() or "version" in path.lower())
            and isinstance(value, str) and value.lower() in expected_statuses
        ]
        event_paths = [
            path for path, value in flattened
            if path.endswith(".msg") and isinstance(value, str)
            and any(
                re.search(pattern, value.lower())
                for pattern, statuses in deployment_status_patterns
                if statuses == expected_statuses
            )
        ]
        if status_paths or event_paths:
            evidence_refs.extend(status_paths + event_paths)
        else:
            reasons.append(
                "deployment event is not present in the supplied evidence: "
                + ", ".join(sorted(expected_statuses))
            )

    if "health" in lowered:
        for path, observed in flattened:
            if path == "health.data.status" and isinstance(observed, str):
                if observed.lower() in lowered:
                    non_numeric_refs.append(path)
    for match in _NUMBER_PATTERN.finditer(finding):
        if any(
            protected.start() <= match.start() < protected.end()
            for protected in [
                *ip_matches,
                *timestamp_matches,
                *container_id_matches,
                *container_identifier_matches,
            ]
        ):
            continue
        value, is_percent = _number_from_claim(match)
        context = finding[max(0, match.start() - 70):min(len(finding), match.end() + 40)]
        if re.search(r"\bconfidence\b", context, re.IGNORECASE):
            continue
        topic = _claim_topic(finding, match.start(), match.end())
        threshold_claim = bool(re.search(
            r"\b(threshold|limit|target|industry|typical|normal|acceptable)\b",
            context,
            re.IGNORECASE,
        ))
        claim = {
            "value": value,
            "unit": "percent" if is_percent else "number",
            "topic": topic or "unknown",
        }
        numbers.append(claim)
        if threshold_claim:
            threshold_paths = [
                path for path, observed in flattened
                if "threshold" in _normalized_key(path)
                and _same_number(observed, value)
            ]
            if threshold_paths:
                evidence_refs.extend(threshold_paths)
            else:
                reasons.append(
                    f"threshold value {value:g} is not configured in the supplied evidence"
                )
            continue

        paths = _numeric_evidence_paths(topic, evidence, value, is_percent)
        if topic == "error_rate" and is_percent:
            paths.extend(
                path for rate, path in _derived_error_rates(evidence)
                if math.isclose(rate, value, rel_tol=0.005, abs_tol=0.05)
            )
        if paths:
            evidence_refs.extend(paths)
        else:
            reasons.append(
                f"numeric claim {value:g}{'%' if is_percent else ''} "
                f"cannot be matched to supplied {topic or 'field-specific'} evidence"
            )

    if not numbers and not deployment_claims and not non_numeric_refs and not evidence_refs:
        reasons.append(
            "natural-language claim cannot be fully verified by conservative evidence checks"
        )
    evidence_refs.extend(non_numeric_refs)
    if reasons:
        status = "unverified"
    elif numbers:
        status = "numbers_supported"
    else:
        status = "evidence_linked"
    return {
        "claim": finding,
        "validation_status": status,
        "reasons": reasons,
        "evidence_refs": sorted(set(evidence_refs)),
        "numeric_claims": [
            {**claim, "is_threshold": bool(re.search(
                r"\b(threshold|limit|target|industry|typical|normal|acceptable)\b",
                finding[max(0, match.start() - 70):min(len(finding), match.end() + 40)],
                re.IGNORECASE,
            ))}
            for claim, match in zip(numbers, _NUMBER_PATTERN.finditer(finding))
        ],
    }


def _make_fact(
    statement: str, source: str, timestamp: Any
) -> dict[str, Any]:
    return {"statement": statement, "source": source, "timestamp": timestamp}


def _version_timestamp(version_data: dict[str, Any], captured_at: Any) -> Any:
    history = version_data.get("history", [])
    if isinstance(history, list):
        for event in reversed(history):
            if isinstance(event, dict) and event.get("version") == version_data.get("version"):
                return event.get("ts", captured_at)
    return captured_at


def _measurement_values(metrics: dict[str, Any]) -> list[tuple[str, str, Any]]:
    accepted = {
        "cpu", "cpuusage", "cpuusagepercent", "cpuutilization", "cpupercent",
        "cpuutilizationpercent", "processorusage", "processorutilization",
        "memory", "memoryusage", "memoryusagepercent", "memoryutilization",
        "memoryutilizationpercent", "memorypercent", "ramusage", "rampercent",
    }
    found = []
    for path, value in _flatten_evidence(metrics):
        key = _normalized_key(path)
        if key in accepted and isinstance(value, (int, float)) and not isinstance(value, bool):
            found.append((path, key, value))
    return found


def _observed_facts(
    evidence: dict[str, Any],
    baseline: dict[str, Any],
    comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build facts only from explicit source values and calculations with inputs."""
    facts: list[dict[str, Any]] = []
    captured_at = evidence.get("captured_at")
    metrics = evidence.get("metrics", {})
    if _request_metrics_available(metrics):
        metrics_timestamp = metrics.get("timestamp", captured_at)
        for path, key, value in _measurement_values(metrics):
            label = "CPU utilization" if "cpu" in key or "processor" in key else "Memory utilization"
            unit = "%" if "percent" in key else ""
            facts.append(_make_fact(
                f"{label} is {value:g}{unit}.",
                f"metrics.{path}",
                metrics_timestamp,
            ))
        requests_data = metrics.get("requests", {})
        if isinstance(requests_data, dict):
            for operation, statuses in requests_data.items():
                if not isinstance(statuses, dict):
                    continue
                known_counts = {
                    status: value for status, value in statuses.items()
                    if status in {"ok", "error", "client_error"}
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and value >= 0
                }
                if known_counts:
                    total_count = sum(known_counts.values())
                    facts.append(_make_fact(
                        f"Cumulative {operation} request total is {total_count:g} "
                        "from reported status counters.",
                        f"metrics.requests.{operation}",
                        metrics_timestamp,
                    ))
                for status, value in statuses.items():
                    if (
                        status in {"error", "client_error"}
                        and isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and value >= 0
                    ):
                        facts.append(_make_fact(
                            f"Current {operation}/{status} request counter is {value:g}.",
                            f"metrics.requests.{operation}.{status}",
                            metrics_timestamp,
                        ))
                error_count = statuses.get("error")
                counts = [
                    float(count) for count in statuses.values()
                    if isinstance(count, (int, float))
                    and not isinstance(count, bool)
                    and count >= 0
                ]
                total = sum(counts)
                if (
                    isinstance(error_count, (int, float))
                    and not isinstance(error_count, bool)
                    and len(counts) > 1
                    and total > 0
                ):
                    facts.append(_make_fact(
                        f"Cumulative {operation} error rate is "
                        f"{float(error_count) / total * 100:.2f}% "
                        f"({error_count:g} errors / {total:g} reported requests).",
                        f"metrics.requests.{operation}",
                        metrics_timestamp,
                    ))
    system_metrics = evidence.get("system_metrics", {})
    system_measurements = system_metrics.get("measurements", {})
    if (
        system_metrics.get("status") in {"ok", "partial"}
        and isinstance(system_measurements, dict)
    ):
        for key, label in (
            ("cpu_utilization_percent", "Host CPU utilization"),
            ("memory_utilization_percent", "Host memory utilization"),
        ):
            value = system_measurements.get(key)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and 0 <= value <= 100
            ):
                facts.append(_make_fact(
                    f"{label} is {value:.2f}%.",
                    f"system_metrics.measurements.{key}",
                    system_metrics.get("timestamp"),
                ))
    prometheus = evidence.get("prometheus", {})
    if isinstance(prometheus, dict):
        prometheus_metrics = prometheus.get("metrics", {})
        if isinstance(prometheus_metrics, dict):
            for metric_name, metric in prometheus_metrics.items():
                if (
                    not isinstance(metric, dict)
                    or metric.get("status") not in {"ok", "partial"}
                    or not isinstance(metric.get("observations"), list)
                ):
                    continue
                for index, observation in enumerate(metric["observations"]):
                    if (
                        not isinstance(observation, dict)
                        or observation.get("stale") is not False
                        or not isinstance(observation.get("latest_value"), (int, float))
                        or isinstance(observation.get("latest_value"), bool)
                        or not math.isfinite(observation["latest_value"])
                    ):
                        continue
                    labels = observation.get("labels", {})
                    label_detail = (
                        f" for labels {json.dumps(labels, sort_keys=True)}"
                        if isinstance(labels, dict) and labels else ""
                    )
                    unit = metric.get("unit", "unknown unit")
                    facts.append(_make_fact(
                        f"Prometheus {metric_name} is "
                        f"{observation['latest_value']:.9g} {unit}{label_detail}.",
                        f"prometheus.metrics.{metric_name}.observations[{index}]",
                        observation.get("latest_timestamp"),
                    ))
    prometheus_deltas = comparison.get("prometheus_comparison", {}).get("deltas", [])
    if isinstance(prometheus_deltas, list):
        for index, delta in enumerate(prometheus_deltas):
            if not isinstance(delta, dict):
                continue
            numeric_delta = delta.get("delta")
            if (
                not isinstance(numeric_delta, (int, float))
                or isinstance(numeric_delta, bool)
                or not math.isfinite(numeric_delta)
            ):
                continue
            labels = delta.get("labels", {})
            label_detail = (
                f" for labels {json.dumps(labels, sort_keys=True)}"
                if isinstance(labels, dict) and labels else ""
            )
            facts.append(_make_fact(
                f"Prometheus {delta.get('metric')} changed by "
                f"{numeric_delta:g} {delta.get('unit', 'unknown unit')}"
                f"{label_detail} between the compared snapshots.",
                f"baseline_comparison.prometheus_comparison.deltas[{index}]",
                delta.get("current_timestamp"),
            ))
    docker = evidence.get("docker", {})
    if isinstance(docker, dict):
        docker_timestamp = docker.get("timestamp", captured_at)
        for index, container in enumerate(_docker_containers(evidence)):
            timestamp = container.get("timestamp", docker_timestamp)
            for key, label in (
                ("id", "Container ID"),
                ("name", "Container name"),
                ("image", "Container image"),
                ("status", "Container status"),
                ("health_status", "Container health status"),
                ("restart_count", "Container restart count"),
                ("started_at", "Container start time"),
                ("uptime_seconds", "Container uptime"),
                ("cpu_usage_percent", "Container CPU usage"),
                ("memory_usage_bytes", "Container memory usage bytes"),
                ("memory_limit_bytes", "Container memory limit bytes"),
                ("memory_usage_percent", "Container memory usage"),
                ("network_rx_bytes", "Container network received bytes"),
                ("network_tx_bytes", "Container network transmitted bytes"),
                ("block_read_bytes", "Container block read bytes"),
                ("block_write_bytes", "Container block write bytes"),
            ):
                value = container.get(key)
                if value is None:
                    continue
                if key == "cpu_usage_percent":
                    statement = f"{label} is {value:.9g}%."
                elif key == "memory_usage_percent":
                    statement = f"{label} is {value:.9g}%."
                elif key in {
                    "restart_count", "uptime_seconds", "memory_usage_bytes",
                    "memory_limit_bytes", "network_rx_bytes", "network_tx_bytes",
                    "block_read_bytes", "block_write_bytes",
                }:
                    statement = f"{label} is {value:.9g}."
                else:
                    statement = f"{label} is {value!r}."
                facts.append(_make_fact(
                    statement,
                    f"docker.containers[{index}].{key}",
                    timestamp,
                ))
    deltas = comparison.get("request_deltas", {})
    if isinstance(deltas, dict):
        for operation, statuses in deltas.items():
            if not isinstance(statuses, dict):
                continue
            for status, value in statuses.items():
                if status in {"error", "client_error"} and isinstance(value, (int, float)):
                    facts.append(_make_fact(
                        f"Baseline-period {operation}/{status} request counter changed by {value:g}.",
                        f"baseline_comparison.request_deltas.{operation}.{status}",
                        captured_at,
                    ))
            error_count = statuses.get("error")
            counts = [
                float(count) for count in statuses.values()
                if isinstance(count, (int, float)) and not isinstance(count, bool)
            ]
            total = sum(counts)
            if (
                isinstance(error_count, (int, float))
                and not isinstance(error_count, bool)
                and len(counts) > 1
                and total > 0
                and error_count >= 0
                and all(count >= 0 for count in counts)
            ):
                facts.append(_make_fact(
                    f"Baseline-period {operation} error rate is "
                    f"{float(error_count) / total * 100:.2f}% "
                    f"({error_count:g} errors / {total:g} changed requests).",
                    f"baseline_comparison.request_deltas.{operation}",
                    captured_at,
                ))

    health = evidence.get("health", {})
    if health.get("status") == "ok":
        data = health.get("data", {})
        health_timestamp = health.get("timestamp", captured_at)
        if "status" in data:
            facts.append(_make_fact(
                f"Health endpoint status is {data['status']!r}.",
                "health.data.status",
                health_timestamp,
            ))
        if "version" in data:
            facts.append(_make_fact(
                f"Health endpoint reports version {data['version']!r}.",
                "health.data.version",
                health_timestamp,
            ))

    current_version_data = evidence.get("version", {}).get("data", {})
    if evidence.get("version", {}).get("status") == "ok":
        version_ts = _version_timestamp(current_version_data, captured_at)
        if "version" in current_version_data:
            facts.append(_make_fact(
                f"Current application version is {current_version_data['version']!r}.",
                "version.data.version",
                version_ts,
            ))
        history = current_version_data.get("history", [])
        if (
            isinstance(history, list)
            and len(history) >= 2
            and isinstance(history[-2], dict)
            and history[-2].get("version") is not None
        ):
            facts.append(_make_fact(
                "Previous deployment version recorded by the application is "
                f"{history[-2]['version']!r}.",
                "version.data.history[-2].version",
                history[-2].get("ts", captured_at),
            ))
        deployment_status = current_version_data.get("deployment_status")
        if isinstance(deployment_status, str):
            facts.append(_make_fact(
                f"Deployment status is {deployment_status!r}.",
                "version.data.deployment_status",
                version_ts,
            ))

    for index, deployment in enumerate(comparison.get("deployment_events", [])):
        if not isinstance(deployment, dict):
            continue
        facts.append(_make_fact(
            f"Explicit {deployment.get('action', 'deployment')} event records "
            f"version {deployment.get('version')!r}.",
            f"baseline_comparison.deployment_events[{index}].event",
            deployment.get("timestamp"),
        ))

    baseline_snapshot = baseline.get("snapshot", {}) if baseline.get("status") == "ok" else {}
    baseline_version_data = baseline_snapshot.get("version", {}).get("data", {})
    baseline_version = baseline_version_data.get(
        "version", comparison.get("baseline_version")
    )
    if baseline_version is not None:
        facts.append(_make_fact(
            f"Baseline application version is {baseline_version!r}.",
            "baseline.snapshot.version.data.version",
            _version_timestamp(baseline_version_data, baseline_snapshot.get("captured_at")),
        ))

    for event_index, event in enumerate(evidence.get("logs", {}).get("events", [])):
        if not isinstance(event, dict):
            continue
        level = str(event.get("level", "")).upper()
        message = str(event.get("msg", ""))
        security_event = bool(re.search(
            r"\b(secur(?:ity|e)|suspicious|unauthori[sz]ed|authentication|login alert)\b",
            message,
            re.IGNORECASE,
        ))
        if level == "ERROR" or level == "WARN" or security_event:
            category = "Security alert" if security_event else f"{level or 'Log'} event"
            facts.append(_make_fact(
                f"{category}: {json.dumps(event, sort_keys=True)}",
                f"logs.events[{event_index}]",
                event.get("ts"),
            ))

    alerts = evidence.get("security_alerts", [])
    if isinstance(alerts, list):
        for index, alert in enumerate(alerts):
            facts.append(_make_fact(
                f"Security alert: {json.dumps(alert, sort_keys=True)}",
                f"security_alerts[{index}]",
                alert.get("ts") if isinstance(alert, dict) else captured_at,
            ))
    return facts


def _telemetry_availability(evidence: dict[str, Any]) -> dict[str, Any]:
    metrics = evidence.get("metrics", {})
    counters = metrics.get("request_counters", {})
    system_metrics = evidence.get("system_metrics", {})
    measurements = system_metrics.get("measurements", {})
    version = evidence.get("version", {})
    version_data = version.get("data", {})
    history = version_data.get("history", [])
    logs = evidence.get("logs", {})
    docker = evidence.get("docker", {})
    docker = docker if isinstance(docker, dict) else {}
    prometheus = evidence.get("prometheus", {})
    prometheus = prometheus if isinstance(prometheus, dict) else {}

    def item(status: str, source: Any, detail: str | None = None) -> dict[str, Any]:
        value = {"status": status, "source": source}
        if detail:
            value["detail"] = detail
        return value

    def valid_percentage(key: str) -> bool:
        value = measurements.get(key) if isinstance(measurements, dict) else None
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and 0 <= value <= 100
        )

    previous_available = (
        isinstance(history, list)
        and len(history) >= 2
        and isinstance(history[-2], dict)
        and "version" in history[-2]
    )
    deployment_status_available = isinstance(version_data.get("deployment_status"), str)
    return {
        "health": item(
            evidence.get("health", {}).get("status", "unavailable"),
            evidence.get("health", {}).get("source"),
            evidence.get("health", {}).get("detail"),
        ),
        "request_counters": item(
            counters.get("status", metrics.get("status", "unavailable"))
            if isinstance(counters, dict) else "unavailable",
            metrics.get("source"),
            metrics.get("detail"),
        ),
        "cpu_utilization": item(
            "ok" if valid_percentage("cpu_utilization_percent") else "unavailable",
            system_metrics.get("source"),
            system_metrics.get("detail")
            if not valid_percentage("cpu_utilization_percent") else None,
        ),
        "memory_utilization": item(
            "ok" if valid_percentage("memory_utilization_percent") else "unavailable",
            system_metrics.get("source"),
            system_metrics.get("detail")
            if not valid_percentage("memory_utilization_percent") else None,
        ),
        "application_version": item(
            "ok" if version.get("status") == "ok" and "version" in version_data
            else "unavailable",
            version.get("source"),
            version.get("detail"),
        ),
        "previous_deployment_version": item(
            "ok" if previous_available else "unavailable",
            version.get("source"),
            None if previous_available else "No previous deployment entry is recorded.",
        ),
        "deployment_status": item(
            "ok" if deployment_status_available else "unavailable",
            version.get("source"),
            None if deployment_status_available
            else "The application version API does not expose deployment status.",
        ),
        "application_logs": item(
            logs.get("status", "unavailable"),
            logs.get("source"),
            logs.get("detail"),
        ),
        "docker_containers": item(
            docker.get("status", "unavailable"),
            docker.get("source"),
            docker.get("detail"),
        ),
        "prometheus": item(
            prometheus.get("status", "unavailable"),
            prometheus.get("source"),
            prometheus.get("detail"),
        ),
    }


def _specialist_conflicts(specialists: dict[str, Any]) -> list[dict[str, Any]]:
    claims_by_topic: dict[str, list[dict[str, Any]]] = {}
    for agent, result in specialists.get("results", {}).items():
        for validation in result.get("validated_findings", []):
            for claim in validation.get("numeric_claims", []):
                topic = claim.get("topic")
                if topic in {"cpu", "memory", "error_rate"} and not claim.get("is_threshold"):
                    claims_by_topic.setdefault(topic, []).append({
                        "agent": agent,
                        "value": claim["value"],
                        "unit": claim["unit"],
                        "claim": validation["claim"],
                        "validation_status": validation["validation_status"],
                    })
    conflicts = []
    for topic, claims in claims_by_topic.items():
        values = {(claim["value"], claim["unit"]) for claim in claims}
        if len(values) > 1:
            conflicts.append({
                "topic": topic,
                "claims": claims,
                "resolution": "Conflicting specialist claims are unresolved; observed evidence remains authoritative.",
            })
    return conflicts


def _specialists_node(state: IncidentState) -> dict[str, Any]:
    selected = _select_specialists(state)
    results: dict[str, Any] = {}
    extraction = extract_evidence(
        state["evidence"],
        state.get("baseline", {"status": "unavailable"}),
        state.get("comparison", {}),
    )
    specialist_state = {**state, "evidence_extraction": extraction}
    for agent in selected:
        supplied_evidence = _specialist_evidence(agent, specialist_state)
        role_package = supplied_evidence["deterministic_evidence"]
        expected_categories = sorted(ROLE_CATEGORIES[agent])
        available_categories = sorted({
            item["category"]
            for item in role_package["observations"]
        })
        missing_categories = sorted(set(expected_categories) - set(available_categories))
        category_missing_details = [
            item for item in role_package["missing_evidence"]
            if item.get("category") in expected_categories
        ]
        delivered_ids = {
            item["evidence_id"] for item in role_package["observations"]
        }
        source_ids = {
            item["evidence_id"] for item in extraction["observations"]
            if item["category"] in ROLE_CATEGORIES[agent]
        }
        delivery_complete = delivered_ids == source_ids
        evidence_delivery = {
            "expected_categories": expected_categories,
            "available_categories": available_categories,
            "missing_categories": missing_categories,
            "extracted_observation_count": len(source_ids),
            "delivered_observation_count": len(delivered_ids),
            "delivery_complete": delivery_complete,
            "extraction_complete": (
                not missing_categories and not category_missing_details
            ),
            "missing_evidence": category_missing_details,
            "verified_observations": role_package["observations"],
        }
        try:
            result = llm_runtime.analyze(
                agent,
                state.get("query", "Diagnose the observed application behavior."),
                supplied_evidence,
            )
        except Exception as exc:
            result = {"status": "error", "agent": agent, "detail": str(exc)}
        if not isinstance(result, dict):
            result = {
                "status": "invalid_response",
                "agent": agent,
                "detail": "Runtime returned a non-object result",
            }
        elif result.get("status") == "ok" and not _valid_analysis(result):
            result = {
                "status": "invalid_response",
                "agent": agent,
                "model": result.get("model"),
                "detail": "Runtime result did not match the specialist analysis contract",
            }
        result = {
            **result,
            "deterministic_evidence": role_package,
            "evidence_delivery": evidence_delivery,
        }
        if result.get("status") == "ok":
            analysis = result["analysis"]
            validated_summary = _validate_finding(analysis["summary"], supplied_evidence)
            validated_findings = [
                _validate_finding(finding, supplied_evidence)
                for finding in analysis["findings"]
            ]
            validated_recommended_checks = []
            for recommendation in analysis["recommended_checks"]:
                validation = _validate_finding(recommendation, supplied_evidence)
                material_reasons = [
                    reason for reason in validation["reasons"]
                    if not reason.startswith(
                        "natural-language claim cannot be fully verified"
                    )
                ]
                validated_recommended_checks.append({
                    **validation,
                    "validation_status": (
                        "unverified" if material_reasons else "advisory"
                    ),
                    "reasons": material_reasons,
                })
            result = {
                **result,
                "original_model_output": result.get(
                    "initial_raw_content", result.get("raw_content", analysis)
                ),
                "original_analysis": analysis,
                "validated_summary": validated_summary,
                "validated_findings": validated_findings,
                "validated_recommended_checks": validated_recommended_checks,
                "unverified_claims": [
                    item for item in [validated_summary, *validated_findings]
                    if item["validation_status"] == "unverified"
                ] + [
                    item for item in validated_recommended_checks
                    if item["validation_status"] == "unverified"
                ],
            }
            if not analysis["findings"]:
                result["unverified_claims"].append({
                    "claim": "Insufficient evidence: the specialist returned no findings.",
                    "validation_status": "unverified",
                    "reasons": ["The model supplied no finding to validate."],
                    "evidence_refs": [],
                    "numeric_claims": [],
                })
        results[agent] = result

    statuses = ", ".join(f"{name}={results[name]['status']}" for name in selected)
    return {
        "specialists": {"selected": selected, "results": results},
        "trace": _trace(
            state,
            "Ran relevant specialist models sequentially"
            + (f" ({statuses})." if statuses else "; none had sufficient evidence."),
        ),
    }


def _diagnose_node(state: IncidentState) -> dict[str, Any]:
    evidence = state["evidence"]
    comparison = state["comparison"]
    baseline = state.get("baseline", {"status": "unavailable"})
    extraction = state.get("evidence_extraction")
    if not isinstance(extraction, dict):
        extraction = extract_evidence(evidence, baseline, comparison)
    else:
        extraction = validate_extraction(extraction)
    observed_facts = _observed_facts(evidence, baseline, comparison)
    specialist_hypotheses: list[dict[str, Any]] = []
    deterministic_hypotheses: list[dict[str, Any]] = []
    unverified_claims: list[dict[str, Any]] = []
    model_interpretations: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    delivery_results: dict[str, Any] = {}

    if comparison.get("deployment_changed") and comparison.get("regression_signal"):
        correlation = {
            "statement": (
                "The observed errors may be associated with the version change; "
                "correlation does not establish causation."
            ),
            "basis": [
                "A version change was observed after the saved baseline.",
                "New request-error metrics or error logs were observed.",
            ],
            "source": "deterministic correlation",
            "hypothesis_type": "correlation",
            "confidence_is_proof": False,
        }
        deterministic_hypotheses.append(correlation)

    for agent, result in state.get("specialists", {}).get("results", {}).items():
        if isinstance(result.get("evidence_delivery"), dict):
            delivery_results[agent] = result["evidence_delivery"]
        if result.get("status") != "ok":
            continue
        analysis = result["analysis"]
        model_interpretations.append({
            "agent": agent,
            "summary": analysis["summary"],
            "findings": list(analysis["findings"]),
            "confidence": analysis["confidence"],
            "source": "LLM interpretation; advisory and not a verified observation",
        })
        for item in result.get("validated_recommended_checks", []):
            recommendations.append({
                "agent": agent,
                "recommendation": item["claim"],
                "validation_status": item["validation_status"],
                "evidence_refs": item["evidence_refs"],
                "executed": False,
            })
        summary_validation = result.get("validated_summary")
        if summary_validation:
            summary_hypothesis = {
                "statement": summary_validation["claim"],
                "source": f"{agent} model summary",
                "confidence": analysis["confidence"],
                "confidence_is_proof": False,
                "validation_status": summary_validation["validation_status"],
                "evidence_refs": summary_validation["evidence_refs"],
                "validation_reasons": summary_validation["reasons"],
            }
            specialist_hypotheses.append(summary_hypothesis)
            if summary_validation["validation_status"] == "unverified":
                unverified_claims.append({
                    **summary_hypothesis,
                    "claim": summary_validation["claim"],
                    "original_model_output": summary_validation["claim"],
                })
        for validation in result.get("validated_findings", []):
            hypothesis = {
                "statement": validation["claim"],
                "source": f"{agent} model hypothesis",
                "confidence": analysis["confidence"],
                "confidence_is_proof": False,
                "validation_status": validation["validation_status"],
                "evidence_refs": validation["evidence_refs"],
                "validation_reasons": validation["reasons"],
            }
            specialist_hypotheses.append(hypothesis)
            if validation["validation_status"] == "unverified":
                unverified_claims.append({
                    **hypothesis,
                    "claim": validation["claim"],
                    "original_model_output": validation["claim"],
                })
        for validation in result.get("validated_recommended_checks", []):
            if validation.get("validation_status") == "unverified":
                unverified_claims.append({
                    "claim": validation["claim"],
                    "source": f"{agent} model recommendation",
                    "validation_status": "unverified",
                    "evidence_refs": validation["evidence_refs"],
                    "validation_reasons": validation["reasons"],
                    "original_model_output": validation["claim"],
                })
        if not result.get("validated_findings"):
            unverified_claims.extend(
                {
                    **claim,
                    "source": f"{agent} model output",
                    "original_model_output": claim["claim"],
                }
                for claim in result.get("unverified_claims", [])
                if claim.get("claim", "").startswith("Insufficient evidence:")
            )

    conflicts = _specialist_conflicts(state.get("specialists", {}))
    hypotheses = [*deterministic_hypotheses, *specialist_hypotheses]

    if comparison.get("deployment_changed") and comparison.get("regression_signal"):
        summary = (
            "Observed request errors after a version change; the deployment is a "
            "possible correlate, not a confirmed root cause."
        )
    elif comparison.get("regression_signal"):
        summary = "New application errors were observed; no deployment cause was established."
    elif evidence.get("health", {}).get("status") != "ok":
        summary = "Application health could not be verified from the available endpoint."
    elif comparison.get("status") == "partial":
        summary = (
            "Current health is observable, but baseline comparison is partial: "
            + comparison.get("detail", "some comparison sources are unavailable.")
        )
    elif comparison.get("status") != "ok":
        summary = "Current health is observable, but no baseline is available for comparison."
    else:
        summary = "No new error signal was observed in the available evidence."

    return {
        "diagnosis": {
            "summary": summary,
            "evidence_extraction": extraction,
            "verified_observations": extraction["observations"],
            "verified_observed_facts": observed_facts,
            "observed_facts": observed_facts,
            "specialist_evidence_delivery": delivery_results,
            "llm_interpretations": model_interpretations,
            "recommendations": recommendations,
            "specialist_hypotheses": specialist_hypotheses,
            "deterministic_hypotheses": deterministic_hypotheses,
            "unverified_claims": unverified_claims,
            "specialist_conflicts": conflicts,
            "hypotheses": hypotheses,
            "evidence_availability": {
                name: value.get("status", "unavailable")
                for name, value in evidence.items()
                if isinstance(value, dict)
            },
            "telemetry_availability": _telemetry_availability(evidence),
        },
        "trace": _trace(state, "Correlated observed facts and kept model findings as hypotheses."),
    }


def _propose_node(state: IncidentState) -> dict[str, Any]:
    comparison = state["comparison"]
    version_data = state["evidence"].get("version", {}).get("data", {})
    history = version_data.get("history", [])
    rollback_target_matches = (
        isinstance(history, list)
        and len(history) >= 2
        and isinstance(history[-1], dict)
        and isinstance(history[-2], dict)
        and history[-1].get("version") == comparison.get("current_version")
        and history[-2].get("version") == comparison.get("baseline_version")
    )
    comparable_sources = set(comparison.get("comparable_sources", []))
    regression_source_comparable = bool(
        {"metrics", "logs"} & comparable_sources
    )
    can_rollback = (
        comparison.get("status") in {"ok", "partial"}
        and "version" in comparable_sources
        and regression_source_comparable
        and comparison.get("deployment_changed")
        and comparison.get("regression_signal")
        and state["evidence"].get("version", {}).get("status") == "ok"
        and rollback_target_matches
    )
    if can_rollback:
        remediation = {
            "action": "rollback",
            "target_version": comparison["baseline_version"],
            "rationale": (
                "A version change and new error evidence were both observed after "
                "the baseline; rollback is proposed for human review."
            ),
            "requires_approval": True,
            "status": "proposed",
        }
        trace = "Proposed the existing application rollback endpoint; human approval is required."
    elif comparison.get("regression_signal"):
        remediation = {
            "action": "investigate",
            "rationale": "Errors were observed, but available evidence does not justify an automatic rollback.",
            "requires_approval": False,
            "status": "recommended",
        }
        trace = "Recommended further investigation; rollback criteria were not met."
    else:
        remediation = {
            "action": "none",
            "rationale": "No observed evidence justifies a remediation action.",
            "requires_approval": False,
            "status": "not_required",
        }
        trace = "No remediation action was justified by the available evidence."
    return {"remediation": remediation, "trace": _trace(state, trace)}


def _route_remediation(state: IncidentState) -> str:
    return "approval" if state["remediation"]["action"] == "rollback" else "record_outcome"


def _approval_node(state: IncidentState) -> dict[str, Any]:
    decision = interrupt({
        "action": state["remediation"]["action"],
        "root_cause": state["diagnosis"]["summary"],
        "target_version": state["remediation"].get("target_version"),
        "rationale": state["remediation"]["rationale"],
    })
    approved = decision is True
    return {
        "approval": approved,
        "trace": _trace(
            state,
            "Human approval received." if approved else "Human rejected remediation.",
        ),
    }


def _route_approval(state: IncidentState) -> str:
    return "apply_remediation" if state.get("approval") is True else "record_outcome"


def _rollback() -> dict[str, Any]:
    try:
        response = requests.post(
            _base_url() + "/admin/rollback",
            timeout=float(os.getenv("DEVOPS_APP_TIMEOUT_SECONDS", REQUEST_TIMEOUT)),
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            return {"status": "failed", "detail": "Rollback response was not a JSON object"}
        return {"status": "ok", "data": result}
    except (requests.RequestException, ValueError) as exc:
        return {"status": "failed", "detail": str(exc)}


def _apply_node(state: IncidentState) -> dict[str, Any]:
    if state.get("approval") is not True:
        return {
            "outcome": {"status": "not_executed", "reason": "Explicit approval was not received."},
            "trace": _trace(state, "Remediation was not executed without explicit approval."),
        }
    if state["remediation"].get("action") != "rollback":
        return {
            "outcome": {"status": "not_executed", "reason": "No supported safe action was proposed."},
            "trace": _trace(state, "No supported remediation action was executed."),
        }

    rollback_result = _rollback()
    verification = _get_json("/health")
    expected_version = state["remediation"].get("target_version")
    verified = (
        rollback_result.get("status") == "ok"
        and verification.get("status") == "ok"
        and verification.get("data", {}).get("status") == "ok"
        and verification.get("data", {}).get("version") == expected_version
    )
    outcome = {
        "status": "succeeded" if verified else "failed",
        "action": "rollback",
        "rollback": rollback_result,
        "verification": verification,
        "expected_version": expected_version,
    }
    return {
        "outcome": outcome,
        "trace": _trace(
            state,
            "Rollback completed and the expected version passed health verification."
            if verified
            else "Rollback or post-action health/version verification failed.",
        ),
    }


def _record_node(state: IncidentState) -> dict[str, Any]:
    if state.get("outcome") is not None:
        return {"outcome": state["outcome"]}
    if state["remediation"]["action"] == "rollback":
        outcome = {
            "status": "rejected",
            "action": "rollback",
            "reason": "Human approval was not explicitly granted.",
        }
        trace = "Recorded rejected remediation; no rollback request was sent."
    else:
        outcome = {
            "status": "not_required",
            "action": state["remediation"]["action"],
            "reason": state["remediation"]["rationale"],
        }
        trace = "Recorded that no remediation execution was required."
    return {"outcome": outcome, "trace": _trace(state, trace)}


def _report_node(state: IncidentState) -> dict[str, Any]:
    report = {
        "query": state.get("query", ""),
        "diagnosis": state["diagnosis"],
        "evidence": state["evidence"],
        "baseline_comparison": state["comparison"],
        "specialists": state["specialists"],
        "recommended_remediation": state["remediation"],
        "outcome": state["outcome"],
    }
    return {
        "report": report,
        "trace": _trace(state, f"Final outcome: {state['outcome']['status']}."),
    }


def build():
    """Build the interruptible workflow with in-memory LangGraph checkpoints."""
    workflow = StateGraph(IncidentState)
    workflow.add_node("collect_evidence", _collect_node)
    workflow.add_node("compare_baseline", _compare_node)
    workflow.add_node("analyze_specialists", _specialists_node)
    workflow.add_node("diagnose", _diagnose_node)
    workflow.add_node("propose_remediation", _propose_node)
    workflow.add_node("request_approval", _approval_node)
    workflow.add_node("apply_remediation", _apply_node)
    workflow.add_node("record_outcome", _record_node)
    workflow.add_node("final_report", _report_node)

    workflow.add_edge(START, "collect_evidence")
    workflow.add_edge("collect_evidence", "compare_baseline")
    workflow.add_edge("compare_baseline", "analyze_specialists")
    workflow.add_edge("analyze_specialists", "diagnose")
    workflow.add_edge("diagnose", "propose_remediation")
    workflow.add_conditional_edges(
        "propose_remediation",
        _route_remediation,
        {"approval": "request_approval", "record_outcome": "record_outcome"},
    )
    workflow.add_conditional_edges(
        "request_approval",
        _route_approval,
        {"apply_remediation": "apply_remediation", "record_outcome": "record_outcome"},
    )
    workflow.add_edge("apply_remediation", "final_report")
    workflow.add_edge("record_outcome", "final_report")
    workflow.add_edge("final_report", END)
    return workflow.compile(checkpointer=MemorySaver())
