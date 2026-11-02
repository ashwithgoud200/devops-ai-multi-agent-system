"""Deterministic, source-traceable extraction from collected AIOps evidence."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1
OBSERVATION_STATUSES = {
    "observed", "derived", "stale", "partial", "unavailable", "invalid",
}
OBSERVATION_FIELDS = {
    "evidence_id",
    "category",
    "metric_or_event",
    "value",
    "unit",
    "timestamp",
    "source",
    "source_path",
    "status",
    "confidence",
    "baseline_value",
    "current_value",
    "change",
    "evidence_text",
}
ROLE_CATEGORIES = {
    "monitoring": {"application_metrics", "infrastructure"},
    "incident": {
        "application_metrics", "deployment", "infrastructure",
        "application_log", "security", "code",
    },
    "code": {"code", "application_log"},
    "cicd": {"deployment", "application_metrics", "application_log"},
    "infrastructure": {"infrastructure", "application_metrics"},
    "security": {"security"},
}
FRESHNESS_SECONDS = {
    "application_metrics": 300.0,
    "deployment": 86400.0,
    "infrastructure": 300.0,
    "security": 86400.0,
    "code": 86400.0,
    "application_log": 86400.0,
}
PROMETHEUS_UNITS = {
    "request_rate": "requests/second",
    "http_error_rate": "percent",
    "latency_p95": "seconds",
    "cpu_utilization": "percent_of_one_cpu",
    "memory_usage": "bytes",
    "host_cpu_utilization": "percent",
    "host_memory_utilization": "percent",
    "container_cpu": "percent_of_one_cpu",
    "container_memory": "bytes",
    "container_memory_utilization": "percent",
}


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _timestamp_seconds(value: Any) -> float | None:
    if _is_number(value):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _json_value(item)
            for key, item in value.items()
        )
    return False


def validate_observation(observation: Any) -> dict[str, Any]:
    """Validate and normalize one observation; reject unknown or malformed fields."""
    if not isinstance(observation, dict):
        raise ValueError("An observation must be an object")
    if set(observation) != OBSERVATION_FIELDS:
        missing = sorted(OBSERVATION_FIELDS - set(observation))
        extra = sorted(set(observation) - OBSERVATION_FIELDS)
        raise ValueError(f"Invalid observation fields; missing={missing}, extra={extra}")
    for field in ("evidence_id", "category", "metric_or_event", "status"):
        if not isinstance(observation[field], str) or not observation[field]:
            raise ValueError(f"{field} must be a non-empty string")
    if observation["status"] not in OBSERVATION_STATUSES:
        raise ValueError(f"Unsupported observation status: {observation['status']}")
    if not _is_number(observation["confidence"]) or not (
        0 <= observation["confidence"] <= 1
    ):
        raise ValueError("confidence must be a finite number between 0 and 1")
    if observation["source"] is not None and not isinstance(observation["source"], str):
        raise ValueError("source must be a string or null")
    if observation["source_path"] is not None and not isinstance(
        observation["source_path"], str
    ):
        raise ValueError("source_path must be a string or null")
    if observation["unit"] is not None and not isinstance(observation["unit"], str):
        raise ValueError("unit must be a string or null")
    if observation["evidence_text"] is not None and not isinstance(
        observation["evidence_text"], str
    ):
        raise ValueError("evidence_text must be a string or null")
    for field in ("value", "baseline_value", "current_value", "change"):
        if not _json_value(observation[field]):
            raise ValueError(f"{field} must contain finite JSON-compatible values")
    return dict(observation)


class _Extractor:
    def __init__(
        self,
        evidence: dict[str, Any],
        baseline: dict[str, Any],
        comparison: dict[str, Any],
        now: float,
    ) -> None:
        self.evidence = evidence
        self.baseline_result = baseline
        self.baseline = (
            baseline.get("snapshot", {})
            if baseline.get("status") == "ok"
            and isinstance(baseline.get("snapshot"), dict)
            else {}
        )
        self.comparison = comparison
        self.now = now
        self.observations: list[dict[str, Any]] = []
        self.missing: list[dict[str, Any]] = []
        self.invalid_count = 0

    def add(
        self,
        category: str,
        metric_or_event: str,
        value: Any,
        source_path: str,
        source: Any,
        timestamp: Any,
        unit: str | None = None,
        status: str | None = None,
        evidence_text: str | None = None,
        baseline_value: Any = None,
        current_value: Any = None,
        change: Any = None,
    ) -> None:
        if not _json_value(value):
            self.invalid_count += 1
            self.missing.append({
                "category": category,
                "source_path": source_path,
                "status": "invalid",
                "detail": "Source value is not finite JSON-compatible data.",
            })
            return
        if status is None:
            if value is None:
                status = "unavailable"
            else:
                seconds = _timestamp_seconds(timestamp)
                max_age = FRESHNESS_SECONDS.get(category)
                status = (
                    "stale"
                    if seconds is not None and max_age is not None
                    and (self.now - seconds > max_age or seconds > self.now + 5)
                    else "observed"
                )
        identity = "\0".join((
            category, metric_or_event, source_path, str(timestamp), repr(value),
        ))
        evidence_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        item = {
            "evidence_id": evidence_id,
            "category": category,
            "metric_or_event": metric_or_event,
            "value": value,
            "unit": unit,
            "timestamp": timestamp,
            "source": source if isinstance(source, str) else None,
            "source_path": source_path,
            "status": status,
            "confidence": 1.0,
            "baseline_value": baseline_value,
            "current_value": current_value,
            "change": change,
            "evidence_text": evidence_text,
        }
        try:
            self.observations.append(validate_observation(item))
        except ValueError as exc:
            self.invalid_count += 1
            self.missing.append({
                "category": category,
                "source_path": source_path,
                "status": "invalid",
                "detail": str(exc),
            })

    def source_missing(self, category: str, name: str, payload: Any) -> None:
        status = payload.get("status") if isinstance(payload, dict) else None
        if status not in {"ok", "partial"}:
            self.missing.append({
                "category": category,
                "source_path": name,
                "status": status if status in OBSERVATION_STATUSES else "unavailable",
                "detail": (
                    payload.get("detail")
                    if isinstance(payload, dict) and isinstance(payload.get("detail"), str)
                    else "Evidence source did not provide an available observation."
                ),
            })

    def extract_metrics(self) -> None:
        metrics = self.evidence.get("metrics")
        if not isinstance(metrics, dict):
            self.source_missing("application_metrics", "metrics", metrics)
            return
        self.source_missing("application_metrics", "metrics", metrics)
        timestamp = metrics.get("timestamp", self.evidence.get("captured_at"))
        source = metrics.get("source")
        counter_status = metrics.get("request_counters", {})
        requests = metrics.get("requests")
        if (
            isinstance(requests, dict)
            and metrics.get("status") in {"ok", "partial"}
            and isinstance(counter_status, dict)
            and counter_status.get("status", "ok") == "ok"
        ):
            for operation, counters in requests.items():
                if not isinstance(counters, dict):
                    self._invalid("application_metrics", f"metrics.requests.{operation}")
                    continue
                valid: dict[str, float] = {}
                for result, value in counters.items():
                    path = f"metrics.requests.{operation}.{result}"
                    if not _is_number(value) or value < 0:
                        self._invalid("application_metrics", path)
                        continue
                    if result not in {"ok", "error", "client_error"}:
                        continue
                    valid[result] = float(value)
                    self.add(
                        "application_metrics", f"{operation}_{result}_request_count",
                        value, path, source, timestamp, "requests",
                    )
                if valid:
                    total = sum(valid.values())
                    self.add(
                        "application_metrics", f"{operation}_total_request_count",
                        total, f"metrics.requests.{operation}", source, timestamp,
                        "requests", status="derived",
                    )
                    failed = valid.get("error", 0) + valid.get("client_error", 0)
                    if total > 0 and ("error" in valid or "client_error" in valid):
                        self.add(
                            "application_metrics", f"{operation}_error_rate",
                            failed / total * 100,
                            f"metrics.requests.{operation}", source, timestamp,
                            "percent", status="derived",
                            baseline_value={
                                "failed_requests": failed,
                                "total_requests": total,
                            },
                        )
        else:
            self.source_missing(
                "application_metrics", "metrics.request_counters",
                counter_status if isinstance(counter_status, dict)
                else {"status": "unavailable"},
            )

        latency_source = metrics.get("latency_observations", {})
        latency_values = (
            latency_source.get("by_operation", {})
            if isinstance(latency_source, dict) else {}
        )
        if isinstance(latency_values, dict) and latency_source.get("status", "ok") in {
            "ok", "partial",
        }:
            for operation, value in latency_values.items():
                path = f"metrics.latency_observations.by_operation.{operation}"
                if not _is_number(value) or value < 0:
                    self._invalid("application_metrics", path)
                    continue
                self.add(
                    "application_metrics", f"{operation}_p95_latency",
                    value, path, source, timestamp, "seconds",
                )
        elif isinstance(latency_source, dict):
            self.source_missing(
                "application_metrics", "metrics.latency_observations",
                latency_source,
            )

        direct_metrics = (
            ("request_rate", "request_rate", "requests/second"),
            ("error_rate_percent", "error_rate", "percent"),
            ("p95_latency_seconds", "p95_latency", "seconds"),
            ("cpu_utilization_percent", "cpu_utilization", "percent"),
            ("memory_usage_bytes", "memory_usage", "bytes"),
        )
        for field, event, unit in direct_metrics:
            value = metrics.get(field)
            if value is None:
                continue
            path = f"metrics.{field}"
            if not _is_number(value) or value < 0:
                self._invalid("application_metrics", path)
                continue
            self.add(
                "application_metrics", event, value, path, source, timestamp, unit,
            )

        totals = metrics.get("request_totals")
        if isinstance(totals, dict):
            for operation, value in totals.items():
                if _is_number(value) and value >= 0:
                    self.add(
                        "application_metrics", f"{operation}_total_request_count",
                        value, f"metrics.request_totals.{operation}", source,
                        timestamp, "requests",
                    )

    def extract_prometheus(self) -> None:
        prometheus = self.evidence.get("prometheus")
        if not isinstance(prometheus, dict):
            self.source_missing("application_metrics", "prometheus", prometheus)
            return
        metrics = prometheus.get("metrics")
        source = prometheus.get("source")
        if not isinstance(metrics, dict):
            self.source_missing("application_metrics", "prometheus.metrics", prometheus)
            return
        for metric_name, metric in metrics.items():
            path = f"prometheus.metrics.{metric_name}"
            if not isinstance(metric, dict):
                self._invalid("application_metrics", path)
                continue
            if metric.get("status") not in {"ok", "partial"}:
                self.source_missing("application_metrics", path, metric)
                continue
            expected_unit = PROMETHEUS_UNITS.get(metric_name)
            unit = metric.get("unit")
            if expected_unit is not None and unit != expected_unit:
                self._invalid("application_metrics", f"{path}.unit")
                continue
            observations = metric.get("observations")
            if not isinstance(observations, list):
                self._invalid("application_metrics", f"{path}.observations")
                continue
            for index, observation in enumerate(observations):
                item_path = f"{path}.observations[{index}]"
                if not isinstance(observation, dict):
                    self._invalid("application_metrics", item_path)
                    continue
                value = observation.get("latest_value")
                if not _is_number(value):
                    self._invalid("application_metrics", f"{item_path}.latest_value")
                    continue
                timestamp = observation.get("latest_timestamp")
                stale = observation.get("stale") is True
                self.add(
                    "application_metrics", metric_name, value, item_path,
                    source, timestamp, unit,
                    status="stale" if stale else None,
                    evidence_text=(
                        json.dumps(observation.get("labels", {}), sort_keys=True)
                        if isinstance(observation.get("labels"), dict) else None
                    ),
                )

    def extract_deployment(self) -> None:
        current_version = self.evidence.get("version")
        version_data = (
            current_version.get("data", {})
            if isinstance(current_version, dict) else {}
        )
        if (
            isinstance(current_version, dict)
            and current_version.get("status") == "ok"
            and isinstance(version_data, dict)
        ):
            timestamp = current_version.get("timestamp", self.evidence.get("captured_at"))
            source = current_version.get("source")
            for field, event in (
                ("version", "current_application_version"),
                ("deployment_status", "deployment_status"),
                ("previous_version", "previous_application_version"),
            ):
                value = version_data.get(field)
                if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                    self.add(
                        "deployment", event, value, f"version.data.{field}",
                        source, timestamp, evidence_text=str(value),
                    )
            history = version_data.get("history")
            if isinstance(history, list) and len(history) >= 2:
                previous = history[-2]
                if isinstance(previous, dict) and previous.get("version") is not None:
                    self.add(
                        "deployment", "previous_application_version",
                        previous["version"], "version.data.history[-2].version",
                        source, previous.get("ts", timestamp),
                    )
        else:
            self.source_missing("deployment", "version", current_version)

        health = self.evidence.get("health")
        if isinstance(health, dict) and health.get("status") == "ok":
            health_data = health.get("data", {})
            if isinstance(health_data, dict):
                for field in ("status", "http_status"):
                    value = health_data.get(field)
                    if value is not None:
                        self.add(
                            "deployment",
                            "health_status" if field == "status" else "health_http_status",
                            value,
                            f"health.data.{field}",
                            health.get("source"),
                            health.get("timestamp"),
                            "HTTP status" if field == "http_status" else None,
                        )
        else:
            self.source_missing("deployment", "health", health)

        baseline_version = self._baseline_version()
        current_value = (
            version_data.get("version") if isinstance(version_data, dict) else None
        )
        if baseline_version is not None:
            self.add(
                "deployment", "baseline_application_version", baseline_version,
                "baseline.snapshot.version.data.version",
                self._source(self.baseline.get("version")),
                self.baseline.get("captured_at"),
            )
        if baseline_version is not None and current_value is not None:
            self.add(
                "deployment", "application_version_change",
                {"baseline": baseline_version, "current": current_value},
                "baseline_comparison.baseline_version/current_version",
                "baseline comparison", self.evidence.get("captured_at"),
                status="derived", baseline_value=baseline_version,
                current_value=current_value,
                change=baseline_version != current_value,
            )
        events = self.comparison.get("deployment_events", [])
        if isinstance(events, list):
            for index, event in enumerate(events):
                if isinstance(event, dict):
                    self.add(
                        "deployment", str(event.get("action", "deployment_event")),
                        event.get("event", event), f"baseline_comparison.deployment_events[{index}]",
                        event.get("source"), event.get("timestamp"),
                        status="observed",
                    )
        logs = self.evidence.get("logs")
        log_events = logs.get("events", []) if isinstance(logs, dict) else []
        if isinstance(log_events, list):
            deployment_pattern = re.compile(
                r"\b(deploy(?:ed|ment)?|rollback|rolled back)\b", re.IGNORECASE
            )
            for index, event in enumerate(log_events):
                if not isinstance(event, dict):
                    continue
                message = event.get("msg")
                if isinstance(message, str) and deployment_pattern.search(message):
                    self.add(
                        "deployment", "deployment_log_event", dict(event),
                        f"logs.events[{index}]", logs.get("source"),
                        event.get("ts"), evidence_text=message,
                    )

    def extract_infrastructure(self) -> None:
        docker = self.evidence.get("docker")
        if not isinstance(docker, dict):
            self.source_missing("infrastructure", "docker", docker)
            return
        self.source_missing("infrastructure", "docker", docker)
        containers = docker.get("containers", [])
        if not isinstance(containers, list):
            self._invalid("infrastructure", "docker.containers")
            return
        container_fields = (
            ("id", None), ("name", None), ("image", None), ("status", None),
            ("health_status", None), ("cpu_usage_percent", "percent"),
            ("memory_usage_bytes", "bytes"), ("memory_limit_bytes", "bytes"),
            ("memory_usage_percent", "percent"), ("network_rx_bytes", "bytes"),
            ("network_tx_bytes", "bytes"), ("block_read_bytes", "bytes"),
            ("block_write_bytes", "bytes"), ("restart_count", "restarts"),
            ("started_at", None), ("uptime_seconds", "seconds"),
        )
        for index, container in enumerate(containers):
            if not isinstance(container, dict):
                self._invalid("infrastructure", f"docker.containers[{index}]")
                continue
            timestamp = container.get("timestamp", docker.get("timestamp"))
            source = container.get("source", docker.get("source"))
            for field, unit in container_fields:
                if field not in container:
                    continue
                value = container[field]
                if value is None:
                    continue
                if field in {
                    "cpu_usage_percent", "memory_usage_bytes", "memory_limit_bytes",
                    "memory_usage_percent", "network_rx_bytes", "network_tx_bytes",
                    "block_read_bytes", "block_write_bytes", "restart_count",
                    "uptime_seconds",
                } and (not _is_number(value) or value < 0):
                    self._invalid("infrastructure", f"docker.containers[{index}].{field}")
                    continue
                self.add(
                    "infrastructure", f"container_{field}", value,
                    f"docker.containers[{index}].{field}", source, timestamp, unit,
                    status=(
                        "partial" if container.get("metrics_status") == "partial"
                        and field not in {"id", "name", "image", "status", "health_status"}
                        else None
                    ),
                )
        host = self.evidence.get("system_metrics")
        if isinstance(host, dict):
            self.source_missing("infrastructure", "system_metrics", host)
            measurements = host.get("measurements", {})
            if isinstance(measurements, dict):
                for key, value in measurements.items():
                    if value is None:
                        continue
                    if not _is_number(value):
                        self._invalid("infrastructure", f"system_metrics.measurements.{key}")
                        continue
                    unit = "percent" if key.endswith("_percent") else (
                        "bytes" if key.endswith("_bytes") else None
                    )
                    self.add(
                        "infrastructure", key, value,
                        f"system_metrics.measurements.{key}", host.get("source"),
                        host.get("timestamp"), unit,
                    )
        process = self.evidence.get("process")
        if isinstance(process, dict):
            for key, value in process.items():
                if key in {"source", "timestamp", "status", "detail"} or value is None:
                    continue
                self.add(
                    "infrastructure", key, value, f"process.{key}",
                    process.get("source"), process.get("timestamp"),
                    "MiB" if key.endswith("_mib") else (
                        "bytes" if key.endswith("_bytes") else None
                    ),
                )

    def extract_logs(self) -> None:
        logs = self.evidence.get("logs")
        if not isinstance(logs, dict):
            self.source_missing("application_log", "logs", logs)
            return
        self.source_missing("application_log", "logs", logs)
        events = logs.get("events", [])
        if not isinstance(events, list):
            self._invalid("application_log", "logs.events")
            return
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                self._invalid("application_log", f"logs.events[{index}]")
                continue
            message = event.get("msg")
            if not isinstance(message, str):
                continue
            timestamp = event.get("ts")
            source = logs.get("source")
            path = f"logs.events[{index}]"
            if str(event.get("level", "")).upper() in {"WARN", "ERROR"}:
                self.add(
                    "application_log", "application_log_event", dict(event),
                    path, source, timestamp, evidence_text=message,
                )
            exception_matches = list(re.finditer(
                r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Interrupt|Exit))\b",
                message,
            ))
            for match in exception_matches:
                self.add(
                    "code", "exception_type", match.group(1), path,
                    source, timestamp, evidence_text=message,
                )
            file_matches = list(re.finditer(
                r'File ["\']([^"\']+)["\'], line (\d+)(?:, in ([\w.<>-]+))?',
                message,
            ))
            for match in file_matches:
                self.add(
                    "code", "stack_trace_frame",
                    {
                        "file": match.group(1),
                        "line": int(match.group(2)),
                        "function": match.group(3),
                    },
                    path, source, timestamp, evidence_text=message,
                )

    def extract_code_source(self) -> None:
        code = self.evidence.get("code_changes")
        if not isinstance(code, dict):
            self.source_missing("code", "code_changes", code)
            return
        source = code.get("source")
        timestamp = code.get("timestamp", self.evidence.get("captured_at"))
        for key in ("exception_type", "error_type", "error_message", "observed_failure"):
            value = code.get(key)
            if isinstance(value, str) and value:
                metric = "exception_type" if key in {"exception_type", "error_type"} else "error_message"
                self.add(
                    "code", metric, value, f"code_changes.{key}",
                    source, timestamp, evidence_text=value,
                )
        for key in ("stack_trace", "traceback"):
            value = code.get(key)
            if isinstance(value, str) and value:
                self.add(
                    "code", "stack_trace", value, f"code_changes.{key}",
                    source, timestamp, evidence_text=value,
                )
                for match in re.finditer(
                    r'File ["\']([^"\']+)["\'], line (\d+)(?:, in ([\w.<>-]+))?',
                    value,
                ):
                    self.add(
                        "code", "stack_trace_frame",
                        {
                            "file": match.group(1),
                            "line": int(match.group(2)),
                            "function": match.group(3),
                        },
                        f"code_changes.{key}", source, timestamp,
                    )
        source_code = code.get("source_code")
        if isinstance(source_code, str) and source_code:
            self.add(
                "code", "source_code", source_code, "code_changes.source_code",
                source, timestamp,
            )

    def extract_security(self) -> None:
        logs = self.evidence.get("logs")
        if not isinstance(logs, dict):
            self.source_missing("security", "logs", logs)
            return
        events = logs.get("events", [])
        if not isinstance(events, list):
            self._invalid("security", "logs.events")
            return
        auth_pattern = re.compile(
            r"\b(authentication|auth(?:entication)?|login|log-in|"
            r"sign[\s-]?in|failed password)\b",
            re.IGNORECASE,
        )
        failures = []
        successful = []
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            message = event.get("msg")
            if not isinstance(message, str) or not auth_pattern.search(message):
                continue
            path = f"logs.events[{index}]"
            timestamp = event.get("ts")
            failed = bool(re.search(
                r"\b(fail(?:ed|ure)?|denied|invalid credentials?)\b",
                message, re.IGNORECASE,
            ))
            succeeded = bool(re.search(
                r"\b(success(?:ful(?:ly)?)?|accepted|logged in)\b",
                message, re.IGNORECASE,
            ))
            event_kind = "authentication_failure" if failed else (
                "authentication_success" if succeeded else "authentication_event"
            )
            if failed:
                failures.append((index, event))
            if succeeded:
                successful.append((index, event))
            self.add(
                "security", event_kind, dict(event), path, logs.get("source"),
                timestamp, evidence_text=message,
            )
            for ip_match in re.finditer(
                r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)", message
            ):
                self.add(
                    "security", "source_ip", ip_match.group(0), path,
                    logs.get("source"), timestamp, evidence_text=message,
                )
        if len(failures) >= 2 and successful:
            latest_failure_time = max(
                (_timestamp_seconds(event.get("ts")) for _, event in failures),
                default=None,
            )
            later_success = [
                (index, event) for index, event in successful
                if latest_failure_time is None
                or (
                    _timestamp_seconds(event.get("ts")) is not None
                    and _timestamp_seconds(event.get("ts")) > latest_failure_time
                )
            ]
            if later_success:
                self.add(
                    "security", "repeated_failures_followed_by_success",
                    {
                        "failed_event_count": len(failures),
                        "success_event_count": len(later_success),
                    },
                    "logs.events", logs.get("source"),
                    later_success[0][1].get("ts"), status="derived",
                    evidence_text=(
                        "Repeated authentication failures precede a later "
                        "successful event; this sequence alone does not establish "
                        "malicious intent or compromise."
                    ),
                )

    def extract_baseline_comparison(self) -> None:
        deltas = self.comparison.get("request_deltas")
        if not isinstance(deltas, dict):
            return
        current_requests = self.evidence.get("metrics", {}).get("requests", {})
        baseline_requests = self.baseline.get("metrics", {}).get("requests", {})
        for operation, statuses in deltas.items():
            if not isinstance(statuses, dict):
                continue
            for status, change in statuses.items():
                if not _is_number(change):
                    continue
                current_value = (
                    current_requests.get(operation, {}).get(status)
                    if isinstance(current_requests, dict)
                    and isinstance(current_requests.get(operation), dict) else None
                )
                baseline_value = (
                    baseline_requests.get(operation, {}).get(status)
                    if isinstance(baseline_requests, dict)
                    and isinstance(baseline_requests.get(operation), dict) else None
                )
                self.add(
                    "application_metrics", f"{operation}_{status}_counter_change",
                    change,
                    f"comparison.request_deltas.{operation}.{status}",
                    "baseline comparison", self.evidence.get("captured_at"),
                    "requests", status="derived",
                    baseline_value=baseline_value,
                    current_value=current_value,
                    change=change,
                )

    def _baseline_version(self) -> Any:
        data = self.baseline.get("version", {})
        data = data.get("data", {}) if isinstance(data, dict) else {}
        return data.get("version") if isinstance(data, dict) else None

    @staticmethod
    def _source(source: Any) -> Any:
        return source.get("source") if isinstance(source, dict) else None

    def _invalid(self, category: str, path: str) -> None:
        self.invalid_count += 1
        self.missing.append({
            "category": category,
            "source_path": path,
            "status": "invalid",
            "detail": "Malformed or unsupported source value.",
        })

    def run(self) -> dict[str, Any]:
        for extractor in (
            self.extract_metrics,
            self.extract_prometheus,
            self.extract_deployment,
            self.extract_infrastructure,
            self.extract_logs,
            self.extract_code_source,
            self.extract_security,
            self.extract_baseline_comparison,
        ):
            try:
                extractor()
            except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
                self.invalid_count += 1
                self.missing.append({
                    "category": "unknown",
                    "source_path": extractor.__name__,
                    "status": "invalid",
                    "detail": f"Malformed evidence prevented extraction: {exc}",
                })
        if not self.observations:
            status = "unavailable"
        elif self.missing or self.invalid_count:
            status = "partial"
        else:
            status = "ok"
        return {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "source": "deterministic extraction from collected evidence",
            "timestamp": self.now,
            "observations": self.observations,
            "missing_evidence": self.missing,
        }


def extract_evidence(
    evidence: Any,
    baseline: Any = None,
    comparison: Any = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Extract validated facts without mutating or replacing the supplied evidence."""
    current = evidence if isinstance(evidence, dict) else {}
    baseline_data = baseline if isinstance(baseline, dict) else {}
    comparison_data = comparison if isinstance(comparison, dict) else {}
    instant = now if _is_number(now) else datetime.now(timezone.utc).timestamp()
    return _Extractor(current, baseline_data, comparison_data, float(instant)).run()


def package_for_role(
    extracted: Any,
    role: str,
    *,
    raw_evidence: Any = None,
) -> dict[str, Any]:
    """Return only role-relevant observations while preserving source metadata."""
    if role not in ROLE_CATEGORIES:
        raise ValueError(f"Unknown evidence role: {role}")
    extraction = extracted if isinstance(extracted, dict) else {}
    observations = extraction.get("observations", [])
    if not isinstance(observations, list):
        observations = []
    selected = [
        item for item in observations
        if isinstance(item, dict) and item.get("category") in ROLE_CATEGORIES[role]
    ]
    missing = extraction.get("missing_evidence", [])
    selected_missing = [
        item for item in missing
        if isinstance(item, dict) and item.get("category") in ROLE_CATEGORIES[role]
    ] if isinstance(missing, list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "unavailable" if not selected and selected_missing
            else "partial" if selected_missing
            else "ok" if selected else "unavailable"
        ),
        "role": role,
        "observations": selected,
        "missing_evidence": selected_missing,
        "raw_evidence_available": isinstance(raw_evidence, dict),
    }


def validate_extraction(value: Any) -> dict[str, Any]:
    """Strictly validate the extractor envelope and every contained observation."""
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "status", "source", "timestamp",
        "observations", "missing_evidence",
    }:
        raise ValueError("Invalid extraction envelope")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported extraction schema version")
    if value["status"] not in {"ok", "partial", "unavailable"}:
        raise ValueError("Invalid extraction status")
    if not isinstance(value["source"], str) or not value["source"]:
        raise ValueError("Extraction source must be a non-empty string")
    if not _is_number(value["timestamp"]):
        raise ValueError("Extraction timestamp must be finite")
    if not isinstance(value["observations"], list):
        raise ValueError("Extraction observations must be an array")
    if not isinstance(value["missing_evidence"], list):
        raise ValueError("Missing evidence must be an array")
    observations = [validate_observation(item) for item in value["observations"]]
    missing = []
    for item in value["missing_evidence"]:
        if not isinstance(item, dict) or set(item) != {
            "category", "source_path", "status", "detail",
        }:
            raise ValueError("Invalid missing evidence record")
        if (
            not isinstance(item["category"], str)
            or not isinstance(item["source_path"], str)
            or item["status"] not in OBSERVATION_STATUSES
            or not isinstance(item["detail"], str)
        ):
            raise ValueError("Malformed missing evidence record")
        missing.append(dict(item))
    return {**value, "observations": observations, "missing_evidence": missing}
