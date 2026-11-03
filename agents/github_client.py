"""Read-only GitHub REST API client for CI/CD workflow runs and security artifacts.

Security & Execution Rules:
- Strictly read-only: performs only HTTP GET requests.
- No workflow triggering, dispatching, cancelling, rerunning, or repository mutations.
- Ingestion is disabled by default via DEVOPS_GITHUB_ENABLED=false.
- Safe zip archive extraction in memory with path traversal and size protections.
- Never ingests raw step logs, tokens, or unredacted secrets.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from typing import Any

import requests

from agents.ci_security_normalizer import normalize_security_scans
from agents.untrusted_text import (
    sanitize_identifier,
    sanitize_location,
    sanitize_text,
    MAX_PACKAGE_LENGTH,
    MAX_VERSION_LENGTH,
)

logger = logging.getLogger("github_client")

DEFAULT_GITHUB_ENABLED = False
DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_GITHUB_TIMEOUT = 10.0
DEFAULT_MAX_ARTIFACT_BYTES = 10 * 1024 * 1024  # 10 MB per zip archive
DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB per decompressed file


def get_github_enabled() -> bool:
    """Return whether GitHub API integration is enabled."""
    return os.getenv("DEVOPS_GITHUB_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def get_github_repo() -> str:
    """Return the configured GitHub repository in owner/repo format."""
    return os.getenv("DEVOPS_GITHUB_REPO", "").strip()


def get_github_token() -> str | None:
    """Return the configured GitHub token if available."""
    token = os.getenv("DEVOPS_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    if token and token.strip():
        return token.strip()
    return None


def get_github_api_url() -> str:
    """Return the GitHub REST API base URL."""
    return os.getenv("DEVOPS_GITHUB_API_URL", DEFAULT_GITHUB_API_URL).rstrip("/")


def get_github_timeout() -> float:
    """Return HTTP request timeout in seconds."""
    try:
        return float(os.getenv("DEVOPS_GITHUB_TIMEOUT_SECONDS", str(DEFAULT_GITHUB_TIMEOUT)))
    except (ValueError, TypeError):
        return DEFAULT_GITHUB_TIMEOUT


class GitHubClient:
    """Safe read-only client for GitHub Actions workflow runs and artifacts."""

    def __init__(
        self,
        repo: str | None = None,
        token: str | None = None,
        api_url: str | None = None,
        timeout: float | None = None,
        enabled: bool | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.enabled = get_github_enabled() if enabled is None else enabled
        self.repo = (repo or get_github_repo()).strip()
        self.token = get_github_token() if token is None else token
        self.api_url = (api_url or get_github_api_url()).rstrip("/")
        self.timeout = get_github_timeout() if timeout is None else timeout
        self.session = session or requests.Session()

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "DevOps-MultiAgent-System",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request_get(
        self,
        endpoint_or_url: str,
        *,
        accept: str = "application/vnd.github+json",
        params: dict[str, Any] | None = None,
        allow_redirects: bool = True,
    ) -> tuple[requests.Response | None, str | None, str]:
        """Perform a safe read-only GET request.

        Returns (response, error_detail, status_code_or_tag).
        """
        if not self.enabled:
            return None, "GitHub integration is disabled (DEVOPS_GITHUB_ENABLED=false)", "disabled"
        if not self.repo:
            return None, "No GitHub repository configured (DEVOPS_GITHUB_REPO is empty)", "unconfigured"

        if endpoint_or_url.startswith("http://") or endpoint_or_url.startswith("https://"):
            url = endpoint_or_url
        else:
            clean_endpoint = endpoint_or_url.lstrip("/")
            url = f"{self.api_url}/{clean_endpoint}"

        headers = self._headers(accept=accept)
        try:
            resp = self.session.get(
                url,
                headers=headers,
                params=params,
                timeout=self.timeout,
                allow_redirects=allow_redirects,
            )
            # Check rate limiting
            remaining = resp.headers.get("x-ratelimit-remaining")
            if resp.status_code in (403, 429) and remaining == "0":
                reset_ts = resp.headers.get("x-ratelimit-reset", "unknown")
                return resp, f"GitHub API rate limit exceeded (resets at {reset_ts})", "rate_limited"

            if resp.status_code == 401:
                return resp, "GitHub API authentication failed (invalid or expired token)", "unauthorized"
            if resp.status_code == 404:
                return resp, f"Resource not found at {url}", "not_found"
            if not resp.ok:
                return resp, f"GitHub API error HTTP {resp.status_code}: {resp.text[:200]}", "api_error"

            return resp, None, "ok"
        except requests.Timeout as exc:
            return None, f"GitHub API timeout after {self.timeout}s: {exc}", "timeout"
        except requests.ConnectionError as exc:
            return None, f"GitHub API connection failed: {exc}", "connection_error"
        except requests.RequestException as exc:
            return None, f"GitHub API request failed: {exc}", "error"

    def get_status(self) -> dict[str, Any]:
        """Return connectivity and rate limit status of the GitHub integration."""
        if not self.enabled:
            return {
                "status": "disabled",
                "enabled": False,
                "configured": bool(self.repo),
                "repo": self.repo or None,
                "authenticated": bool(self.token),
                "detail": "GitHub integration is disabled (DEVOPS_GITHUB_ENABLED=false).",
            }
        if not self.repo:
            return {
                "status": "unconfigured",
                "enabled": True,
                "configured": False,
                "repo": None,
                "authenticated": bool(self.token),
                "detail": "DEVOPS_GITHUB_REPO is not configured.",
            }

        # Query rate limit endpoint
        resp, error, status_tag = self._request_get(f"repos/{self.repo}")
        if resp is None:
            return {
                "status": status_tag,
                "enabled": True,
                "configured": True,
                "repo": self.repo,
                "authenticated": bool(self.token),
                "detail": error,
            }

        rate_limit = {
            "limit": resp.headers.get("x-ratelimit-limit"),
            "remaining": resp.headers.get("x-ratelimit-remaining"),
            "reset": resp.headers.get("x-ratelimit-reset"),
            "used": resp.headers.get("x-ratelimit-used"),
        }

        if status_tag != "ok":
            return {
                "status": status_tag,
                "enabled": True,
                "configured": True,
                "repo": self.repo,
                "authenticated": bool(self.token),
                "rate_limit": rate_limit,
                "detail": error,
            }

        repo_data = resp.json() if isinstance(resp.json(), dict) else {}
        return {
            "status": "connected",
            "enabled": True,
            "configured": True,
            "repo": self.repo,
            "default_branch": repo_data.get("default_branch", "main"),
            "private": repo_data.get("private", False),
            "authenticated": bool(self.token),
            "rate_limit": rate_limit,
            "detail": "Successfully connected to GitHub REST API.",
        }

    def list_workflow_runs(
        self,
        workflow_id_or_file: str | None = None,
        *,
        per_page: int = 5,
    ) -> tuple[list[dict[str, Any]], str | None, str]:
        """Retrieve recent workflow runs for the repository."""
        if workflow_id_or_file:
            endpoint = f"repos/{self.repo}/actions/workflows/{workflow_id_or_file}/runs"
        else:
            endpoint = f"repos/{self.repo}/actions/runs"

        resp, error, status = self._request_get(endpoint, params={"per_page": min(per_page, 20)})
        if error or resp is None:
            return [], error, status

        try:
            data = resp.json()
            runs = data.get("workflow_runs", [])
            return runs, None, "ok"
        except (ValueError, TypeError) as exc:
            return [], f"Invalid JSON in workflow runs response: {exc}", "api_error"

    def get_run_jobs(self, run_id: int | str) -> tuple[list[dict[str, Any]], str | None]:
        """Retrieve jobs and step status metadata for a workflow run without ingesting raw logs."""
        endpoint = f"repos/{self.repo}/actions/runs/{run_id}/jobs"
        resp, error, _ = self._request_get(endpoint, params={"per_page": 30})
        if error or resp is None:
            return [], error

        try:
            data = resp.json()
            jobs_list = data.get("jobs", [])
            sanitized_jobs: list[dict[str, Any]] = []
            for j in jobs_list:
                if not isinstance(j, dict):
                    continue
                job_name = sanitize_text(j.get("name") or "job", max_length=100)
                job_status = sanitize_text(j.get("status") or "unknown", max_length=50)
                job_conclusion = sanitize_text(j.get("conclusion") or "unknown", max_length=50)

                raw_steps = j.get("steps", [])
                steps_meta: list[dict[str, Any]] = []
                for s in raw_steps:
                    if not isinstance(s, dict):
                        continue
                    # Metadata only: NO raw logs or step outputs
                    steps_meta.append({
                        "name": sanitize_text(s.get("name") or "step", max_length=100),
                        "status": sanitize_text(s.get("status") or "unknown", max_length=50),
                        "conclusion": sanitize_text(s.get("conclusion") or "unknown", max_length=50),
                        "number": s.get("number"),
                        "started_at": s.get("started_at"),
                        "completed_at": s.get("completed_at"),
                    })

                sanitized_jobs.append({
                    "id": j.get("id"),
                    "name": job_name,
                    "status": job_status,
                    "conclusion": job_conclusion,
                    "started_at": j.get("started_at"),
                    "completed_at": j.get("completed_at"),
                    "steps": steps_meta,
                })
            return sanitized_jobs, None
        except Exception as exc:
            return [], f"Failed to parse jobs: {exc}"

    def list_run_artifacts(self, run_id: int | str) -> tuple[list[dict[str, Any]], str | None]:
        """List artifacts available for a workflow run."""
        endpoint = f"repos/{self.repo}/actions/runs/{run_id}/artifacts"
        resp, error, _ = self._request_get(endpoint)
        if error or resp is None:
            return [], error

        try:
            data = resp.json()
            return data.get("artifacts", []), None
        except Exception as exc:
            return [], f"Failed to parse artifacts list: {exc}"

    def download_artifact_zip_files(
        self,
        artifact_id: int | str,
        *,
        max_zip_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> tuple[dict[str, Any], str | None]:
        """Safely download and extract JSON files from an artifact ZIP in memory.

        Enforces path traversal defenses and file size bounds.
        Returns a dict mapping filename -> parsed JSON object.
        """
        endpoint = f"repos/{self.repo}/actions/artifacts/{artifact_id}/zip"
        resp, error, _ = self._request_get(endpoint, accept="application/vnd.github+json")
        if error or resp is None:
            return {}, error

        content = resp.content
        if len(content) > max_zip_bytes:
            return {}, f"Artifact zip size ({len(content)} bytes) exceeds limit ({max_zip_bytes} bytes)"

        extracted_files: dict[str, Any] = {}
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for file_info in zf.infolist():
                    name = file_info.filename
                    # Security checks: prevent directory traversal in zip archive
                    if ".." in name or name.startswith("/") or name.startswith("\\"):
                        logger.warning("Skipping suspicious zip member path: %s", name)
                        continue
                    if file_info.file_size > max_file_bytes:
                        logger.warning("Skipping oversized zip member: %s (%s bytes)", name, file_info.file_size)
                        continue
                    if not name.endswith(".json"):
                        continue

                    # Read and parse JSON safely
                    with zf.open(file_info) as member:
                        member_bytes = member.read(max_file_bytes + 1)
                        if len(member_bytes) > max_file_bytes:
                            continue
                        try:
                            parsed = json.loads(member_bytes.decode("utf-8"))
                            base_name = name.split("/")[-1].split("\\")[-1]
                            extracted_files[base_name] = parsed
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            logger.warning("Failed to decode JSON from zip member %s", name)
                            continue
            return extracted_files, None
        except zipfile.BadZipFile as exc:
            return {}, f"Malformed artifact zip archive: {exc}"

    def fetch_ci_evidence(self) -> dict[str, Any]:
        """Fetch the latest CI pipeline evidence from GitHub Actions."""
        if not self.enabled:
            return {
                "status": "unavailable",
                "detail": "GitHub integration is disabled (DEVOPS_GITHUB_ENABLED=false).",
            }
        if not self.repo:
            return {
                "status": "unavailable",
                "detail": "No GitHub repository configured (DEVOPS_GITHUB_REPO is empty).",
            }

        # Find latest CI run (look for ci.yml or workflow runs with CI in name)
        runs, error, status = self.list_workflow_runs(per_page=10)
        if error:
            return {
                "status": "scanner_error" if status == "rate_limited" else "unavailable",
                "detail": f"GitHub API error fetching CI workflow runs: {error}",
            }

        ci_runs = [
            r for r in runs
            if "ci" in (r.get("name") or "").lower() or (r.get("path") or "").endswith("ci.yml")
        ]
        if not ci_runs:
            return {
                "status": "not_run",
                "detail": "No CI workflow runs found in repository.",
            }

        latest_run = ci_runs[0]
        run_id = latest_run.get("id")
        wf_name = sanitize_text(latest_run.get("name") or "CI Pipeline", max_length=100)
        branch = sanitize_identifier(latest_run.get("head_branch") or "")
        commit_sha = sanitize_identifier(latest_run.get("head_sha") or "")
        raw_conclusion = str(latest_run.get("conclusion") or latest_run.get("status") or "unknown").lower()
        conclusion = (
            "success" if raw_conclusion in ("success", "passed", "ok")
            else "failure" if raw_conclusion in ("failure", "failed", "error")
            else "cancelled" if raw_conclusion == "cancelled"
            else "partial" if raw_conclusion == "partial"
            else "unknown"
        )

        # Parse run jobs and steps
        jobs, _ = self.get_run_jobs(run_id)

        # Download CI summary artifact if available
        artifacts, _ = self.list_run_artifacts(run_id)
        ci_summary_data: dict[str, Any] = {}
        for art in artifacts:
            art_name = (art.get("name") or "").lower()
            if "ci" in art_name or "summary" in art_name or "test" in art_name:
                files, _ = self.download_artifact_zip_files(art.get("id"))
                for fname, parsed in files.items():
                    if "summary" in fname or fname == "ci-summary.json":
                        if isinstance(parsed, dict):
                            ci_summary_data = parsed
                            break
            if ci_summary_data:
                break

        test_summary = {
            "total": ci_summary_data.get("tests", ci_summary_data.get("test_count", 0)),
            "failed": ci_summary_data.get("failures", ci_summary_data.get("failed_count", 0)),
            "errors": ci_summary_data.get("errors", ci_summary_data.get("error_count", 0)),
            "skipped": ci_summary_data.get("skipped", ci_summary_data.get("skipped_count", 0)),
        }
        test_summary["passed"] = max(0, test_summary["total"] - (test_summary["failed"] + test_summary["errors"] + test_summary["skipped"]))

        # Calculate timestamp and freshness
        updated_at_str = latest_run.get("updated_at") or latest_run.get("created_at")
        run_ts = time.time()
        if updated_at_str:
            try:
                run_ts = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass

        max_age = float(os.getenv("DEVOPS_EVIDENCE_MAX_AGE_HOURS", "168")) * 3600.0
        freshness = "stale" if (time.time() - run_ts > max_age) else "observed"

        return {
            "status": "stale" if freshness == "stale" else "ok",
            "freshness": freshness,
            "source": f"github:{self.repo}#run={run_id}",
            "timestamp": run_ts,
            "workflow_name": wf_name,
            "workflow_run_id": str(run_id),
            "branch": branch or None,
            "commit_sha": commit_sha or None,
            "conclusion": conclusion,
            "test_summary": test_summary,
            "jobs": jobs,
            "raw_logs_ingested": False,
        }

    def fetch_security_evidence(self) -> dict[str, Any]:
        """Fetch the latest security scanner reports from GitHub Actions artifacts."""
        if not self.enabled:
            return {
                "status": "unavailable",
                "detail": "GitHub integration is disabled (DEVOPS_GITHUB_ENABLED=false).",
            }
        if not self.repo:
            return {
                "status": "unavailable",
                "detail": "No GitHub repository configured (DEVOPS_GITHUB_REPO is empty).",
            }

        # Find latest security run
        runs, error, status = self.list_workflow_runs(per_page=10)
        if error:
            return {
                "status": "scanner_error" if status == "rate_limited" else "unavailable",
                "detail": f"GitHub API error fetching security workflow runs: {error}",
            }

        sec_runs = [
            r for r in runs
            if "secur" in (r.get("name") or "").lower() or (r.get("path") or "").endswith("security.yml")
        ]
        if not sec_runs:
            return {
                "status": "not_run",
                "detail": "No Security workflow runs found in repository.",
            }

        latest_run = sec_runs[0]
        run_id = latest_run.get("id")
        artifacts, _ = self.list_run_artifacts(run_id)

        report_payloads: dict[str, Any] = {
            "pip_audit": None,
            "npm_audit": None,
            "trivy_image": None,
            "trivy_config": None,
            "gitleaks": None,
        }

        scanner_name_mapping = {
            "pip_audit": ["pip_audit.json", "pip-audit.json"],
            "npm_audit": ["npm_audit.json", "npm-audit.json"],
            "trivy_image": ["trivy_image.json", "trivy-image.json"],
            "trivy_config": ["trivy_config.json", "trivy-config.json"],
            "gitleaks": ["gitleaks.json"],
        }

        for art in artifacts:
            files, _ = self.download_artifact_zip_files(art.get("id"))
            for target_key, filenames in scanner_name_mapping.items():
                for fname in filenames:
                    if fname in files and report_payloads[target_key] is None:
                        report_payloads[target_key] = files[fname]

        # Calculate timestamp and freshness
        updated_at_str = latest_run.get("updated_at") or latest_run.get("created_at")
        run_ts = time.time()
        if updated_at_str:
            try:
                run_ts = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass

        max_age = float(os.getenv("DEVOPS_EVIDENCE_MAX_AGE_HOURS", "168")) * 3600.0
        is_stale = (time.time() - run_ts > max_age)

        # Normalize via Stage 7 Phase 2 normalizer
        normalized = normalize_security_scans(report_payloads, is_stale=is_stale)
        normalized["source"] = f"github:{self.repo}#run={run_id}"
        normalized["timestamp"] = run_ts
        normalized["freshness"] = "stale" if is_stale else "observed"

        return normalized
