"""Deterministic infrastructure analysis, resource thresholding, risk scoring,
remediation eligibility, and post-action verification policy engine.

Strict safety policy:
- No LLM generation for infrastructure math, thresholds, or critical policy decisions.
- All decisions are deterministic, auditable, and traceable to observed evidence.
- Approval is strictly required for any remediation action.
- Verification is observational only (/health, metrics, container status).
"""
from __future__ import annotations

import time
from typing import Any


def evaluate_infrastructure_health(
    docker_data: dict[str, Any] | None,
    compose_topology: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deterministically inspect container health, running status, and restart counts."""
    configured_services = (
        compose_topology.get("configured_services", ["calculator-app", "prometheus", "grafana", "frontend"])
        if isinstance(compose_topology, dict) else ["calculator-app", "prometheus", "grafana", "frontend"]
    )
    
    containers = docker_data.get("containers", []) if isinstance(docker_data, dict) else []
    container_map = {c.get("name"): c for c in containers if isinstance(c, dict)}
    
    service_statuses = {}
    unhealthy_services = []
    stopped_services = []
    
    for svc in configured_services:
        c_name = f"devops-{svc}" if not svc.startswith("devops-") else svc
        c = container_map.get(c_name) or container_map.get(svc)
        if c:
            status = c.get("status", "unknown")
            health = c.get("health") or c.get("health_status") or "unknown"
            restarts = c.get("restart_count", 0)
            service_statuses[svc] = {
                "container": c_name,
                "status": status,
                "health": health,
                "restarts": restarts,
                "metrics_status": c.get("metrics_status", "ok" if c.get("cpu_percent") is not None else "unavailable"),
            }
            if health == "unhealthy":
                unhealthy_services.append(svc)
            if status != "running":
                stopped_services.append(svc)
        else:
            service_statuses[svc] = {
                "container": c_name,
                "status": "not_running",
                "health": "unavailable",
                "restarts": 0,
                "metrics_status": "unavailable",
            }
            stopped_services.append(svc)

    overall_health = "healthy" if not unhealthy_services and not stopped_services else (
        "unhealthy" if unhealthy_services else "degraded"
    )

    return {
        "status": "ok" if docker_data and docker_data.get("status") == "ok" else "unavailable",
        "overall_health": overall_health,
        "configured_services": configured_services,
        "service_statuses": service_statuses,
        "unhealthy_services": unhealthy_services,
        "stopped_services": stopped_services,
    }


def evaluate_resource_thresholds(
    system_metrics: dict[str, Any] | None,
    docker_data: dict[str, Any] | None,
    cpu_warning_pct: float = 80.0,
    cpu_critical_pct: float = 95.0,
    mem_warning_pct: float = 80.0,
    mem_critical_pct: float = 95.0,
) -> list[dict[str, Any]]:
    """Deterministically evaluate host and container resource pressure against fixed thresholds."""
    alerts = []
    
    # Host System Metrics
    if isinstance(system_metrics, dict):
        measurements = system_metrics.get("measurements", {})
        cpu = measurements.get("cpu_percent")
        if isinstance(cpu, (int, float)):
            if cpu >= cpu_critical_pct:
                alerts.append({
                    "target": "host_system",
                    "resource": "cpu",
                    "level": "CRITICAL",
                    "value": cpu,
                    "threshold": cpu_critical_pct,
                    "message": f"Host CPU utilization is critical at {cpu:.1f}% (threshold: {cpu_critical_pct}%)",
                })
            elif cpu >= cpu_warning_pct:
                alerts.append({
                    "target": "host_system",
                    "resource": "cpu",
                    "level": "WARNING",
                    "value": cpu,
                    "threshold": cpu_warning_pct,
                    "message": f"Host CPU utilization is elevated at {cpu:.1f}% (threshold: {cpu_warning_pct}%)",
                })
                
    # Container metrics
    containers = docker_data.get("containers", []) if isinstance(docker_data, dict) else []
    for c in containers:
        if not isinstance(c, dict):
            continue
        c_name = c.get("name", "unknown")
        c_cpu = c.get("cpu_percent")
        if isinstance(c_cpu, (int, float)):
            if c_cpu >= cpu_critical_pct:
                alerts.append({
                    "target": c_name,
                    "resource": "cpu",
                    "level": "CRITICAL",
                    "value": c_cpu,
                    "threshold": cpu_critical_pct,
                    "message": f"Container {c_name} CPU is critical at {c_cpu:.1f}%",
                })
            elif c_cpu >= cpu_warning_pct:
                alerts.append({
                    "target": c_name,
                    "resource": "cpu",
                    "level": "WARNING",
                    "value": c_cpu,
                    "threshold": cpu_warning_pct,
                    "message": f"Container {c_name} CPU is elevated at {c_cpu:.1f}%",
                })

    return alerts


def evaluate_evidence_completeness(evidence: dict[str, Any]) -> dict[str, Any]:
    """Deterministically score and categorize evidence completeness across all available sources."""
    sources = {
        "metrics": bool(evidence.get("metrics", {}).get("status") in {"ok", "partial"}),
        "prometheus": bool(evidence.get("prometheus", {}).get("status") in {"ok", "partial"}),
        "health": bool(evidence.get("health", {}).get("status") == "ok"),
        "logs": bool(isinstance(evidence.get("logs", {}).get("events"), list) and len(evidence.get("logs", {}).get("events", [])) > 0),
        "docker": bool(evidence.get("docker", {}).get("status") in {"ok", "partial"}),
        "git": bool(evidence.get("git", {}).get("status") in {"ok", "partial"}),
        "ci_pipeline": bool(evidence.get("ci_pipeline", {}).get("status") in {"ok", "stale", "completed"}),
        "security_scans": bool(evidence.get("security_scans", {}).get("status") in {"clean", "findings", "ok"}),
    }
    
    total = len(sources)
    present = sum(1 for v in sources.values() if v)
    score = round(present / total, 2)
    
    return {
        "completeness_score": score,
        "available_sources": [k for k, v in sources.items() if v],
        "unavailable_sources": [k for k, v in sources.items() if not v],
        "status": "complete" if score >= 0.85 else ("partial" if score >= 0.4 else "sparse"),
    }


def calculate_risk_score(
    severity: str,
    blast_radius: dict[str, Any],
    security_findings: list[dict[str, Any]],
    health_status: str,
    regression_signal: bool,
) -> dict[str, Any]:
    """Deterministically calculate numerical incident risk score (0-100) and risk level."""
    score = 0
    factors = []
    
    # 1. Severity weight (0-30)
    sev = severity.lower()
    if sev == "critical":
        score += 30
        factors.append("Critical incident severity (+30)")
    elif sev == "high":
        score += 20
        factors.append("High incident severity (+20)")
    elif sev == "medium":
        score += 10
        factors.append("Medium incident severity (+10)")
    else:
        score += 5
        factors.append("Low incident severity (+5)")

    # 2. Application Health (0-25)
    if health_status != "ok":
        score += 25
        factors.append("Application /health is not responding OK (+25)")
    elif regression_signal:
        score += 15
        factors.append("Regression signal detected in request counters / error rates (+15)")

    # 3. Blast radius & affected endpoints (0-20)
    affected = blast_radius.get("affected_endpoints", [])
    if affected:
        impact_score = min(20, len(affected) * 10)
        score += impact_score
        factors.append(f"{len(affected)} endpoint(s) impacted (+{impact_score})")

    # 4. Security findings impact (0-25)
    critical_sec = sum(1 for f in security_findings if str(f.get("severity", "")).lower() == "critical")
    high_sec = sum(1 for f in security_findings if str(f.get("severity", "")).lower() == "high")
    if critical_sec > 0:
        score += 25
        factors.append(f"{critical_sec} critical security finding(s) (+25)")
    elif high_sec > 0:
        score += min(20, high_sec * 10)
        factors.append(f"{high_sec} high security finding(s) (+{min(20, high_sec * 10)})")

    final_score = min(100, max(0, score))
    level = "CRITICAL" if final_score >= 80 else ("HIGH" if final_score >= 60 else ("MEDIUM" if final_score >= 35 else "LOW"))
    
    return {
        "risk_score": final_score,
        "risk_level": level,
        "risk_factors": factors,
    }


def evaluate_remediation_policy(
    state: dict[str, Any],
    diagnosis: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically determine remediation eligibility (e.g. rollback criteria)."""
    evidence = state.get("evidence", {})
    version_data = evidence.get("version", {}).get("data", {}) if isinstance(evidence.get("version"), dict) else {}
    current_version = version_data.get("version")
    history = version_data.get("history", [])
    
    has_rollback_target = len(history) >= 2 and history[-2].get("version") is not None
    target_version = history[-2]["version"] if has_rollback_target else None
    
    regression_signal = state.get("comparison", {}).get("regression_signal", False)
    deployment_changed = state.get("comparison", {}).get("deployment_changed", False)
    
    if regression_signal and deployment_changed and has_rollback_target:
        eligible = True
        action = "rollback"
        rationale = (
            f"Observed error regression correlated with version upgrade to v{current_version}. "
            f"Rollback to previous stable version v{target_version} is eligible for human review."
        )
    elif regression_signal and not deployment_changed:
        eligible = False
        action = "investigate"
        rationale = "Regression signal detected, but no deployment version transition was recorded. Manual investigation recommended."
    else:
        eligible = False
        action = "investigate"
        rationale = "Incident criteria for automated rollback proposal were not met. Observational monitoring recommended."

    return {
        "eligible": eligible,
        "action": action,
        "target_version": target_version,
        "current_version": current_version,
        "rationale": rationale,
        "approval_required": True,  # Approval is ALWAYS strictly required
    }


def evaluate_approval_requirement(
    risk_score: dict[str, Any],
    proposed_remediation: dict[str, Any],
) -> dict[str, Any]:
    """Strictly enforce human approval requirement for any actionable remediation."""
    action = proposed_remediation.get("action", "investigate")
    requires_approval = action in {"rollback", "restart", "deploy", "patch"}
    
    return {
        "requires_approval": requires_approval,
        "approval_policy": "Strict Human-in-the-Loop Gate. Destructive and mutating actions must never execute automatically.",
        "risk_level": risk_score.get("risk_level", "MEDIUM"),
        "status": "pending_human_review" if requires_approval else "not_required",
    }


def verify_post_remediation(
    before_health: dict[str, Any],
    current_health: dict[str, Any],
) -> dict[str, Any]:
    """Perform observational verification of system state following an action."""
    status_ok = current_health.get("status") == "ok"
    version = current_health.get("version") or current_health.get("data", {}).get("version")
    
    return {
        "timestamp": time.time(),
        "verified": status_ok,
        "health_status": current_health.get("status", "unknown"),
        "version": version,
        "details": f"Observational verification against /health returned HTTP 200 (version={version})" if status_ok else "Verification failed: /health is unhealthy or unreachable",
    }

