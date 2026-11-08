"""HTTP API for integrations status, CI/CD pipeline runs, and normalized security findings."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from agents import metrics as app_metrics
from agents.compose_topology import get_compose_topology
from agents.git_telemetry import collect_git_evidence
from agents.github_client import GitHubClient, get_github_enabled
from agents.loki_client import get_loki_status, query_loki_logs
from agents.tempo_client import get_tempo_status, query_trace, search_traces
from agents.runtime_evidence import (
    collect_ci_evidence,
    collect_security_evidence,
    get_ci_evidence_enabled,
    get_evidence_import_dir,
    get_security_evidence_enabled,
)

router = APIRouter(tags=["integrations and telemetry"])


@router.get("/topology/compose", summary="Get Docker Compose service topology and health")
def get_docker_compose_topology() -> dict[str, Any]:
    """Return configured Docker Compose services, container status, and dependency impact."""
    return get_compose_topology()


@router.get("/telemetry/git", summary="Get read-only local Git repository evidence")
def get_git_telemetry() -> dict[str, Any]:
    """Return current branch, recent commits, and sanitized diff without repository mutations."""
    return collect_git_evidence()


@router.get("/integrations/status", summary="Get status of external integrations")
def get_integrations_status() -> dict[str, Any]:
    """Return connectivity, authentication, and report availability across GitHub and offline stores."""
    # 1. GitHub Integration Status
    gh_client = GitHubClient()
    gh_status = gh_client.get_status()
    app_metrics.record_integration_status("github", gh_status.get("status") == "connected")

    # 2. Offline Evidence Directory Status
    import_dir = get_evidence_import_dir()
    dir_exists = import_dir.is_dir()
    ci_files = list(import_dir.glob("ci-summary*.json")) if dir_exists else []
    sec_patterns = ["pip*audit*.json", "npm*audit*.json", "trivy*.json", "gitleaks*.json"]
    sec_files = []
    if dir_exists:
        for p in sec_patterns:
            sec_files.extend(list(import_dir.glob(p)))

    ci_offline_status = {
        "enabled": get_ci_evidence_enabled(),
        "import_dir": str(import_dir),
        "dir_exists": dir_exists,
        "reports_found": len(ci_files),
        "status": "ready" if (dir_exists and ci_files) else "no_reports" if dir_exists else "dir_missing",
    }
    app_metrics.record_integration_status(
        "offline_ci",
        get_ci_evidence_enabled() and bool(ci_files),
    )

    sec_offline_status = {
        "enabled": get_security_evidence_enabled(),
        "import_dir": str(import_dir),
        "dir_exists": dir_exists,
        "reports_found": len(sec_files),
        "status": "ready" if (dir_exists and sec_files) else "no_reports" if dir_exists else "dir_missing",
    }
    app_metrics.record_integration_status(
        "offline_security",
        get_security_evidence_enabled() and bool(sec_files),
    )

    loki_stat = get_loki_status()
    tempo_stat = get_tempo_status()

    return {
        "github": gh_status,
        "offline_ci": ci_offline_status,
        "offline_security": sec_offline_status,
        "loki": loki_stat,
        "tempo": tempo_stat,
    }


@router.get("/ci/runs/latest", summary="Get latest CI/CD workflow run summary")
def get_latest_ci_run() -> dict[str, Any]:
    """Return the latest structured CI pipeline run result, test summary, and job metadata."""
    evidence = collect_ci_evidence()
    wf_name = evidence.get("workflow_name", "CI Pipeline")
    failed_tests = evidence.get("test_summary", {}).get("failed", 0)
    app_metrics.record_ci_run_metrics(wf_name, failed_tests)
    return evidence


@router.get("/security/findings", summary="Get normalized security scanner findings")
def get_security_findings() -> dict[str, Any]:
    """Return normalized security findings grouped by severity and category without secret values."""
    evidence = collect_security_evidence()
    summary = evidence.get("summary", {})
    app_metrics.record_security_findings_metrics(summary)

    # Double-check redaction: Gitleaks secrets/matches must never appear in response
    findings = evidence.get("findings", [])
    sanitized_findings = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        safe_f = dict(f)
        safe_f.pop("Secret", None)
        safe_f.pop("Match", None)
        sanitized_findings.append(safe_f)

    return {
        "status": evidence.get("status", "unavailable"),
        "freshness": evidence.get("freshness", "observed"),
        "source": evidence.get("source"),
        "timestamp": evidence.get("timestamp"),
        "summary": summary,
        "scanners": evidence.get("scanners", {}),
        "findings": sanitized_findings,
        "detail": evidence.get("detail"),
    }


@router.get("/telemetry/loki", summary="Query Loki aggregated logs or local file fallback")
def get_loki_telemetry(query: str = '{app="calculator-app"}', limit: int = 50, since: int = 3600) -> dict[str, Any]:
    """Query logs from Loki via LogQL with fallback to local application log file."""
    return query_loki_logs(query=query, limit=limit, since_seconds=since)


@router.get("/telemetry/tempo", summary="Search distributed traces from Tempo or local buffer")
def get_tempo_telemetry(limit: int = 25, service: str = "calculator-app") -> dict[str, Any]:
    """Search recent distributed traces and latency spans from Tempo or in-memory fallback."""
    return search_traces(limit=limit, service_name=service)


@router.get("/telemetry/traces/{trace_id}", summary="Get trace details and span breakdown")
def get_trace_details(trace_id: str) -> dict[str, Any]:
    """Query span waterfall breakdown for a given trace_id."""
    trace_res = query_trace(trace_id)
    if trace_res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found.")
    return trace_res
