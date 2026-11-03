"""Runtime evidence collection for CI/CD pipelines and security scanner reports.

Provides read-only, path-validated, and size-limited ingestion of:
- Structured CI/CD pipeline summaries and test results (for cicd specialist).
- Normalized security vulnerability and secret scan reports (for security specialist).
- Summarized security finding counts (for incident specialist).
"""
from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger("runtime_evidence")
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.ci_security_normalizer import (
    ALLOWED_CATEGORIES,
    ALLOWED_SEVERITIES,
    ALLOWED_STATUSES,
    normalize_security_scans,
)
from agents.untrusted_text import (
    sanitize_identifier,
    sanitize_location,
    sanitize_text,
    MAX_DESCRIPTION_LENGTH,
    MAX_PACKAGE_LENGTH,
    MAX_VERSION_LENGTH,
)

# Configuration defaults
DEFAULT_CI_ENABLED = False
DEFAULT_SECURITY_ENABLED = False
DEFAULT_IMPORT_DIR = "/app/data/ci-security-reports"
DEFAULT_MAX_AGE_HOURS = 168.0  # 7 days
DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB


def get_ci_evidence_enabled() -> bool:
    """Return whether CI evidence collection is enabled."""
    return os.getenv("DEVOPS_CI_EVIDENCE_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def get_security_evidence_enabled() -> bool:
    """Return whether security evidence collection is enabled."""
    return os.getenv("DEVOPS_SECURITY_EVIDENCE_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def get_evidence_import_dir() -> Path:
    """Return the configured import directory path."""
    configured = os.getenv("DEVOPS_EVIDENCE_IMPORT_DIR", DEFAULT_IMPORT_DIR)
    return Path(configured).resolve()


def get_evidence_max_age_seconds() -> float:
    """Return maximum allowed evidence age in seconds."""
    try:
        hours = float(os.getenv("DEVOPS_EVIDENCE_MAX_AGE_HOURS", str(DEFAULT_MAX_AGE_HOURS)))
        return max(0.0, hours * 3600.0)
    except (ValueError, TypeError):
        return DEFAULT_MAX_AGE_HOURS * 3600.0


def get_evidence_max_file_bytes() -> int:
    """Return maximum allowed file size in bytes."""
    try:
        return int(os.getenv("DEVOPS_EVIDENCE_MAX_FILE_BYTES", str(DEFAULT_MAX_FILE_BYTES)))
    except (ValueError, TypeError):
        return DEFAULT_MAX_FILE_BYTES


def _is_safe_path(base_dir: Path, target_path: Path) -> bool:
    """Verify that target_path is located within base_dir to prevent directory traversal."""
    try:
        resolved_base = base_dir.resolve()
        resolved_target = target_path.resolve()
        return (
            resolved_target == resolved_base
            or resolved_base in resolved_target.parents
        )
    except (OSError, RuntimeError):
        return False


def _safe_read_json(
    path: Path,
    base_dir: Path,
    max_bytes: int,
) -> tuple[Any | None, str | None, str]:
    """Safely read and parse a JSON file with path-traversal and size protections.

    Returns (data, error_detail, status).
    """
    if not _is_safe_path(base_dir, path):
        return None, f"Security violation: path traversal detected outside {base_dir}", "scanner_error"

    if not path.is_file():
        return None, f"File does not exist: {path.name}", "not_run"

    try:
        stat_result = path.stat()
        file_size = stat_result.st_size
    except OSError as exc:
        return None, f"Failed to access file {path.name}: {exc}", "scanner_error"

    if file_size > max_bytes:
        return None, f"File {path.name} exceeds maximum allowed size of {max_bytes} bytes ({file_size} bytes)", "scanner_error"

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return None, f"Failed to read file {path.name}: {exc}", "scanner_error"

    if len(raw_bytes) > max_bytes:
        return None, f"Payload {path.name} exceeds maximum allowed size of {max_bytes} bytes", "scanner_error"

    try:
        decoded = raw_bytes.decode("utf-8")
        parsed = json.loads(decoded)
        return parsed, None, "ok"
    except UnicodeDecodeError as exc:
        return None, f"File {path.name} is not valid UTF-8: {exc}", "scanner_error"
    except json.JSONDecodeError as exc:
        return None, f"Malformed JSON in {path.name}: {exc}", "scanner_error"


def _check_freshness(timestamp: float | None, max_age_seconds: float, now: float) -> str:
    """Return 'observed' or 'stale' based on evidence timestamp."""
    if timestamp is None:
        return "observed"
    if now - timestamp > max_age_seconds:
        return "stale"
    return "observed"


# ============================================================================
# CI/CD Pipeline Evidence
# ============================================================================

def collect_ci_evidence(
    import_dir: Path | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Collect structured CI/CD pipeline evidence without ingesting raw log tails.

    Tries GitHub REST API if enabled; falls back to offline import directory.
    """
    from agents.github_client import GitHubClient, get_github_enabled

    if get_github_enabled() and import_dir is None:
        try:
            gh_client = GitHubClient()
            gh_res = gh_client.fetch_ci_evidence()
            if gh_res.get("status") in ("ok", "stale", "scanner_error"):
                return gh_res
            # If GitHub reported not_run or unavailable, fall back to offline import if enabled
        except Exception as exc:
            logger.warning("GitHub CI evidence fetch failed: %s", exc)

    if not get_ci_evidence_enabled() and import_dir is None:
        return {
            "status": "unavailable",
            "detail": "CI/CD evidence collection is disabled (DEVOPS_CI_EVIDENCE_ENABLED=false).",
        }

    base_dir = (import_dir or get_evidence_import_dir()).resolve()
    max_bytes = get_evidence_max_file_bytes()
    max_age = get_evidence_max_age_seconds()
    current_time = now if now is not None else time.time()

    if not base_dir.is_dir():
        return {
            "status": "unavailable",
            "source": str(base_dir),
            "timestamp": current_time,
            "detail": f"Import directory does not exist: {base_dir}",
        }

    # Locate CI summary file (e.g. ci-summary.json or ci-summary-*.json)
    summary_files = sorted(list(base_dir.glob("ci-summary*.json")))
    if not summary_files:
        return {
            "status": "not_run",
            "source": str(base_dir),
            "timestamp": current_time,
            "detail": "No CI summary JSON report found in import directory.",
        }

    # Use latest summary file
    target_file = summary_files[-1]
    parsed, error, status = _safe_read_json(target_file, base_dir, max_bytes)

    if status == "scanner_error" or error:
        return {
            "status": "scanner_error",
            "source": target_file.name,
            "timestamp": current_time,
            "error": error,
            "detail": error,
        }

    if not isinstance(parsed, dict):
        return {
            "status": "scanner_error",
            "source": target_file.name,
            "timestamp": current_time,
            "error": f"Invalid CI summary structure in {target_file.name}: expected JSON object",
            "detail": "Invalid CI summary structure",
        }

    # Extract timestamp from report or file mtime
    file_mtime = target_file.stat().st_mtime
    report_ts_raw = parsed.get("timestamp")
    report_ts = None
    if isinstance(report_ts_raw, (int, float)):
        report_ts = float(report_ts_raw)
    elif isinstance(report_ts_raw, str):
        try:
            report_ts = datetime.fromisoformat(report_ts_raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            report_ts = file_mtime
    else:
        report_ts = file_mtime

    freshness = _check_freshness(report_ts, max_age, current_time)

    # Sanitize untrusted text fields
    workflow_name = sanitize_text(parsed.get("workflow_name") or parsed.get("job") or "CI Pipeline", max_length=100)
    workflow_run_id = sanitize_identifier(parsed.get("workflow_run_id") or parsed.get("run_id") or "")
    branch = sanitize_identifier(parsed.get("branch") or "")
    commit_sha = sanitize_identifier(parsed.get("commit_sha") or "")
    raw_conclusion = str(parsed.get("conclusion") or parsed.get("status") or "unknown").strip().lower()

    conclusion = (
        "success" if raw_conclusion in ("success", "passed", "ok")
        else "failure" if raw_conclusion in ("failure", "failed", "error")
        else "cancelled" if raw_conclusion == "cancelled"
        else "partial" if raw_conclusion == "partial"
        else "unknown"
    )

    # Test metrics validation
    def _parse_count(val: Any) -> int:
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return max(0, int(val))
        return 0

    total_tests = _parse_count(parsed.get("tests", parsed.get("test_count")))
    failed_tests = _parse_count(parsed.get("failures", parsed.get("failed_count")))
    error_tests = _parse_count(parsed.get("errors", parsed.get("error_count")))
    skipped_tests = _parse_count(parsed.get("skipped", parsed.get("skipped_count")))

    # Jobs and steps metadata without raw log tails
    raw_jobs = parsed.get("jobs", [])
    jobs_meta: list[dict[str, Any]] = []
    if isinstance(raw_jobs, list):
        for j in raw_jobs:
            if isinstance(j, dict):
                job_name = sanitize_text(j.get("name") or "job", max_length=100)
                job_status = sanitize_text(j.get("status") or "unknown", max_length=50)
                steps_meta: list[dict[str, Any]] = []
                for s in j.get("steps", []):
                    if isinstance(s, dict):
                        steps_meta.append({
                            "name": sanitize_text(s.get("name") or "step", max_length=100),
                            "status": sanitize_text(s.get("status") or "unknown", max_length=50),
                            "conclusion": sanitize_text(s.get("conclusion") or "unknown", max_length=50),
                            "duration_seconds": s.get("duration_seconds"),
                            # NOTE: Raw log tails are NEVER ingested or preserved
                        })
                jobs_meta.append({
                    "name": job_name,
                    "status": job_status,
                    "steps": steps_meta,
                })

    effective_status = "stale" if freshness == "stale" else "ok"

    return {
        "status": effective_status,
        "freshness": freshness,
        "source": target_file.name,
        "timestamp": report_ts,
        "workflow_name": workflow_name,
        "workflow_run_id": workflow_run_id if workflow_run_id else None,
        "branch": branch if branch else None,
        "commit_sha": commit_sha if commit_sha else None,
        "conclusion": conclusion,
        "test_summary": {
            "total": total_tests,
            "failed": failed_tests,
            "errors": error_tests,
            "skipped": skipped_tests,
            "passed": max(0, total_tests - (failed_tests + error_tests + skipped_tests)),
        },
        "jobs": jobs_meta,
        "raw_logs_ingested": False,
    }


# ============================================================================
# Security Scanner Evidence
# ============================================================================

def collect_security_evidence(
    import_dir: Path | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Collect and normalize security reports across pip-audit, npm audit, Trivy, and Gitleaks.

    Tries GitHub REST API if enabled; falls back to offline import directory.
    """
    from agents.github_client import GitHubClient, get_github_enabled

    if get_github_enabled() and import_dir is None:
        try:
            gh_client = GitHubClient()
            gh_res = gh_client.fetch_security_evidence()
            if gh_res.get("status") in ("clean", "findings", "stale", "scanner_error"):
                return gh_res
            # If GitHub reported not_run or unavailable, fall back to offline import if enabled
        except Exception as exc:
            logger.warning("GitHub security evidence fetch failed: %s", exc)

    if not get_security_evidence_enabled() and import_dir is None:
        return {
            "status": "unavailable",
            "detail": "Security evidence collection is disabled (DEVOPS_SECURITY_EVIDENCE_ENABLED=false).",
        }

    base_dir = (import_dir or get_evidence_import_dir()).resolve()
    max_bytes = get_evidence_max_file_bytes()
    max_age = get_evidence_max_age_seconds()
    current_time = now if now is not None else time.time()

    if not base_dir.is_dir():
        return {
            "status": "unavailable",
            "source": str(base_dir),
            "timestamp": current_time,
            "detail": f"Import directory does not exist: {base_dir}",
        }

    # Map scanner report file patterns
    scanner_patterns = {
        "pip_audit": ["pip_audit.json", "pip-audit.json"],
        "npm_audit": ["npm_audit.json", "npm-audit.json"],
        "trivy_image": ["trivy_image.json", "trivy-image.json"],
        "trivy_config": ["trivy_config.json", "trivy-config.json"],
        "gitleaks": ["gitleaks.json"],
    }

    report_payloads: dict[str, Any] = {}
    timestamps: list[float] = []
    has_file = False

    for scanner_key, filenames in scanner_patterns.items():
        found_path: Path | None = None
        for fname in filenames:
            candidate = base_dir / fname
            if candidate.is_file():
                found_path = candidate
                break

        if found_path is not None:
            has_file = True
            parsed, error, status = _safe_read_json(found_path, base_dir, max_bytes)
            if status == "scanner_error":
                report_payloads[scanner_key] = {"_raw_error": error, "_status": "scanner_error"}
            elif parsed is not None:
                report_payloads[scanner_key] = parsed
                timestamps.append(found_path.stat().st_mtime)
        else:
            report_payloads[scanner_key] = None

    if not has_file:
        return {
            "status": "not_run",
            "source": str(base_dir),
            "timestamp": current_time,
            "detail": "No security scanner JSON reports found in import directory.",
        }

    latest_ts = max(timestamps) if timestamps else current_time
    is_stale = (current_time - latest_ts > max_age)

    # Pass safely to Phase 2 normalizer
    # Normalize handles deduplication, categories, severities, and Gitleaks Secret/Match exclusion
    normalized = normalize_security_scans(
        report_payloads,
        is_stale=is_stale,
    )

    # Attach evidence provenance and freshness
    normalized["timestamp"] = latest_ts
    normalized["freshness"] = "stale" if is_stale else "observed"
    normalized["source"] = str(base_dir)

    return normalized


# ============================================================================
# Incident Agent Security Summary
# ============================================================================

def summarize_security_for_incident(security_evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Create a minimal summarized view of security findings strictly for the incident agent.

    Contains ONLY counts and status; NEVER exposes raw findings or secret values.
    """
    if not isinstance(security_evidence, dict):
        return {
            "status": "unavailable",
            "detail": "Security evidence unavailable",
        }
    if security_evidence.get("status") == "unavailable":
        return {
            "status": "unavailable",
            "detail": security_evidence.get("detail", "Security evidence unavailable"),
        }

    status = security_evidence.get("status", "unknown")
    freshness = security_evidence.get("freshness", "observed")
    summary = security_evidence.get("summary", {})

    by_severity = summary.get("by_severity", {})
    return {
        "status": status,
        "freshness": freshness,
        "total_findings": summary.get("total_findings", 0),
        "critical": by_severity.get("critical", 0),
        "high": by_severity.get("high", 0),
        "medium": by_severity.get("medium", 0),
        "low": by_severity.get("low", 0),
        "unknown": by_severity.get("unknown", 0),
    }
