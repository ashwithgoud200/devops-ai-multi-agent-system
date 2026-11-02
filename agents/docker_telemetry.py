"""Read-only Docker container telemetry collected through the Docker CLI."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

SOURCE = "Docker Engine via read-only Docker CLI"
COMMAND_TIMEOUT_SECONDS = 5.0
_BYTE_UNITS = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "pb": 1000**5,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "pib": 1024**5,
}


def _docker_command(*arguments: str) -> subprocess.CompletedProcess[str]:
    executable = os.getenv("DEVOPS_DOCKER_CLI", "docker")
    return subprocess.run(
        [executable, *arguments],
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )


def _error_detail(error: Exception | str) -> str:
    message = str(error).strip()
    if not message and isinstance(error, Exception):
        message = error.__class__.__name__
    lowered = message.lower()
    if "permission denied" in lowered or "access is denied" in lowered or "forbidden" in lowered:
        category = "Docker permission error"
    elif isinstance(error, subprocess.TimeoutExpired):
        category = "Docker command timed out"
    elif isinstance(error, FileNotFoundError):
        category = "Docker CLI is not installed or not on PATH"
    else:
        category = "Docker Engine unavailable"
    return f"{category}: {message}"


def _run(*arguments: str) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    try:
        result = _docker_command(*arguments)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, _error_detail(exc)
    if result.returncode:
        return None, _error_detail(result.stderr or result.stdout or "command failed")
    return result, None


def _parse_bytes(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)\s*",
        value,
    )
    if not match:
        return None
    unit = match.group(2).lower()
    multiplier = _BYTE_UNITS.get(unit)
    if multiplier is None:
        return None
    number = float(match.group(1))
    if not math.isfinite(number) or number < 0:
        return None
    return int(number * multiplier)


def _parse_pair(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, str) or "/" not in value:
        return None, None
    left, right = value.split("/", 1)
    return _parse_bytes(left), _parse_bytes(right)


def _parse_percent(value: Any, maximum: float | None = 100) -> float | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*", value)
    if not match:
        return None
    number = float(match.group(1))
    return number if (
        math.isfinite(number)
        and number >= 0
        and (maximum is None or number <= maximum)
    ) else None


def _image_parts(image: Any) -> tuple[str | None, str | None]:
    if not isinstance(image, str) or not image:
        return None, None
    name = image.split("@", 1)[0]
    last_component = name.rsplit("/", 1)[-1]
    if ":" not in last_component:
        return name, None
    image_name, tag = name.rsplit(":", 1)
    return image_name, tag or None


def _start_details(value: Any, collected_at: float) -> tuple[float | None, float | None]:
    if not isinstance(value, str) or not value:
        return None, None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.year <= 1:
            return None, None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        timestamp = parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return None, None
    return timestamp, max(0.0, collected_at - timestamp)


def _empty_container(
    container_id: str | None,
    name: str | None,
    timestamp: float,
) -> dict[str, Any]:
    return {
        "id": container_id,
        "name": name,
        "image": None,
        "image_name": None,
        "image_tag": None,
        "status": None,
        "health_status": None,
        "cpu_usage_percent": None,
        "memory_usage_bytes": None,
        "memory_limit_bytes": None,
        "memory_usage_percent": None,
        "network_rx_bytes": None,
        "network_tx_bytes": None,
        "block_read_bytes": None,
        "block_write_bytes": None,
        "started_at": None,
        "uptime_seconds": None,
        "restart_count": None,
        "metrics_status": "unavailable",
        "source": SOURCE,
        "timestamp": timestamp,
    }


def _inspect_container(
    container_id: str,
    timestamp: float,
) -> tuple[dict[str, Any], str | None]:
    result, error = _run("inspect", "--type", "container", container_id)
    if error or result is None:
        return _empty_container(container_id, None, timestamp), (
            error or "Docker inspect returned no result"
        )
    try:
        items = json.loads(result.stdout)
        details = items[0]
        state = details["State"]
        image = details.get("Config", {}).get("Image")
        image_name, image_tag = _image_parts(image)
        started_at, uptime = _start_details(state.get("StartedAt"), timestamp)
        health = state.get("Health")
        return {
            "id": details.get("Id"),
            "name": str(details.get("Name", "")).lstrip("/") or None,
            "image": image,
            "image_name": image_name,
            "image_tag": image_tag,
            "status": state.get("Status"),
            "health_status": (
                health.get("Status") if isinstance(health, dict) else "not_configured"
            ),
            "cpu_usage_percent": None,
            "memory_usage_bytes": None,
            "memory_limit_bytes": None,
            "memory_usage_percent": None,
            "network_rx_bytes": None,
            "network_tx_bytes": None,
            "block_read_bytes": None,
            "block_write_bytes": None,
            "started_at": started_at,
            "uptime_seconds": uptime,
            "restart_count": details.get("RestartCount"),
            "metrics_status": "unavailable",
            "source": SOURCE,
            "timestamp": timestamp,
        }, None
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return _empty_container(container_id, None, timestamp), (
            f"Invalid Docker inspect response: {exc}"
        )


def _add_stats(container: dict[str, Any], timestamp: float) -> str | None:
    container_id = container.get("id")
    result, error = _run(
        "stats",
        "--no-stream",
        "--format",
        "{{json .}}",
        str(container_id),
    )
    if error or result is None:
        return error or "Docker stats returned no result"
    try:
        stats = json.loads(result.stdout.strip())
        if not isinstance(stats, dict):
            raise ValueError("stats response must be a JSON object")
        cpu = _parse_percent(stats.get("CPUPerc"), maximum=None)
        memory_usage, memory_limit = _parse_pair(stats.get("MemUsage"))
        memory_percent = _parse_percent(stats.get("MemPerc"), maximum=None)
        if (
            memory_percent is None
            and memory_usage is not None
            and memory_limit is not None
            and memory_limit > 0
        ):
            memory_percent = memory_usage / memory_limit * 100
        network_rx, network_tx = _parse_pair(stats.get("NetIO"))
        block_read, block_write = _parse_pair(stats.get("BlockIO"))
        metrics = {
            "cpu_usage_percent": cpu,
            "memory_usage_bytes": memory_usage,
            "memory_limit_bytes": memory_limit,
            "memory_usage_percent": memory_percent,
            "network_rx_bytes": network_rx,
            "network_tx_bytes": network_tx,
            "block_read_bytes": block_read,
            "block_write_bytes": block_write,
        }
        container.update(metrics)
        missing = [key for key, value in metrics.items() if value is None]
        container["metrics_status"] = "partial" if missing else "ok"
        container["timestamp"] = timestamp
        return (
            "Unavailable Docker stats fields: " + ", ".join(missing)
            if missing else None
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return f"Invalid Docker stats response: {exc}"


def collect_docker_metrics() -> dict[str, Any]:
    """Collect read-only telemetry for running containers, preserving partial results."""
    timestamp = time.time()
    result, error = _run("ps", "--no-trunc", "--quiet")
    if error or result is None:
        error = error or "Docker container listing returned no result"
        return {
            "status": "unavailable",
            "source": SOURCE,
            "timestamp": timestamp,
            "containers": [],
            "errors": [error],
            "detail": error,
        }

    container_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    containers = []
    errors = []
    for container_id in container_ids:
        inspected, inspect_error = _inspect_container(container_id, timestamp)
        if inspect_error:
            errors.append({"container_id": container_id, "detail": inspect_error})
            containers.append(inspected)
            continue
        stats_error = _add_stats(inspected, timestamp)
        if stats_error:
            inspected["metrics_status"] = "partial" if any(
                inspected.get(key) is not None
                for key in ("cpu_usage_percent", "memory_usage_bytes", "network_rx_bytes")
            ) else "unavailable"
            errors.append({
                "container_id": inspected.get("id") or container_id,
                "name": inspected.get("name"),
                "detail": stats_error,
            })
        containers.append(inspected)

    status = "partial" if errors else "ok"
    detail = "; ".join(error["detail"] for error in errors) if errors else None
    return {
        "status": status,
        "source": SOURCE,
        "timestamp": timestamp,
        "containers": containers,
        "errors": errors,
        "detail": detail,
    }
