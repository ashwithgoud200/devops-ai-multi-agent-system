"""Read-only Docker Compose topology inspector and service dependency analyzer.

Strict safety rules:
- Read-only inspection of docker-compose.yml configuration and container status.
- Never starts, stops, restarts, or modifies Docker containers or volumes.
- Maps service-level dependencies and potential failure blast radius.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from agents.docker_telemetry import collect_docker_metrics

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.yml"


def get_compose_topology() -> dict[str, Any]:
    """Inspect configured Docker Compose services, dependencies, and live container mapping."""
    if not COMPOSE_FILE.is_file():
        return {
            "status": "unavailable",
            "source": "docker-compose.yml",
            "detail": f"docker-compose.yml not found at {COMPOSE_FILE}",
            "services": {},
            "topology": [],
        }

    try:
        with COMPOSE_FILE.open("r", encoding="utf-8") as f:
            compose_data = yaml.safe_load(f) or {}
    except Exception as exc:
        return {
            "status": "error",
            "source": "docker-compose.yml",
            "detail": f"Failed to parse docker-compose.yml: {exc}",
            "services": {},
            "topology": [],
        }

    raw_services = compose_data.get("services", {})
    docker_data = collect_docker_metrics()
    live_containers = {
        c.get("name"): c for c in docker_data.get("containers", [])
    }

    services_info: dict[str, Any] = {}
    service_names = list(raw_services.keys())

    for name, svc in raw_services.items():
        depends_on = svc.get("depends_on", [])
        if isinstance(depends_on, dict):
            dependencies = list(depends_on.keys())
        elif isinstance(depends_on, list):
            dependencies = list(depends_on)
        else:
            dependencies = []

        container_name = svc.get("container_name", f"devops-{name}")
        live = live_containers.get(container_name) or live_containers.get(name)

        ports = svc.get("ports", [])
        healthcheck = svc.get("healthcheck") is not None

        services_info[name] = {
            "service_name": name,
            "container_name": container_name,
            "image": svc.get("image", "custom build"),
            "ports": ports,
            "dependencies": dependencies,
            "has_healthcheck": healthcheck,
            "restart_policy": svc.get("restart", "no"),
            "live_status": live.get("status") if live else "not_running",
            "live_health": live.get("health") if live else "unavailable",
            "live_memory": live.get("memory") if live else None,
            "live_cpu": live.get("cpu_percent") if live else None,
            "metrics_status": "ok" if (live and live.get("cpu_percent") is not None) else "unavailable",
            "metrics_unavailable_reason": None if (live and live.get("cpu_percent") is not None) else ("Container not running" if not live else "Container metrics not collected"),
        }

    # Dependency / Blast Radius mapping
    # downstream[A] = services that depend on A
    downstream: dict[str, list[str]] = {name: [] for name in service_names}
    for name, info in services_info.items():
        for dep in info["dependencies"]:
            if dep in downstream:
                downstream[dep].append(name)

    return {
        "status": "ok",
        "source": "docker-compose.yml & Docker Engine",
        "total_services": len(services_info),
        "configured_services": service_names,
        "docker_available": docker_data.get("status") == "ok",
        "services": services_info,
        "downstream_impact": downstream,
        "topology": [
            {
                "service": name,
                "dependencies": info["dependencies"],
                "impacts": downstream.get(name, []),
                "live_status": info["live_status"],
            }
            for name, info in services_info.items()
        ],
    }

