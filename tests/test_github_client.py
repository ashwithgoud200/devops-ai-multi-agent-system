"""Unit and integration tests for the read-only GitHub REST API client."""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from agents.github_client import (
    GitHubClient,
    get_github_api_url,
    get_github_enabled,
    get_github_repo,
    get_github_timeout,
    get_github_token,
)


def test_github_client_disabled_by_default():
    """Client is disabled by default without environment variables."""
    with patch.dict(os.environ, {}, clear=True):
        assert get_github_enabled() is False
        assert get_github_repo() == ""
        assert get_github_token() is None

        client = GitHubClient()
        status = client.get_status()
        assert status["status"] == "disabled"
        assert status["enabled"] is False

        # Calls fail gracefully with status 'disabled' or 'unavailable'
        runs, error, tag = client.list_workflow_runs()
        assert runs == []
        assert tag == "disabled"
        assert "disabled" in error

        ci_res = client.fetch_ci_evidence()
        assert ci_res["status"] == "unavailable"

        sec_res = client.fetch_security_evidence()
        assert sec_res["status"] == "unavailable"


def test_github_client_unconfigured_repo():
    """Client enabled but missing repo returns unconfigured status."""
    with patch.dict(os.environ, {"DEVOPS_GITHUB_ENABLED": "true", "DEVOPS_GITHUB_REPO": ""}):
        client = GitHubClient()
        status = client.get_status()
        assert status["status"] == "unconfigured"
        assert status["configured"] is False


def test_github_client_headers_with_and_without_token():
    """Authorization header is added only when token is present."""
    client_no_token = GitHubClient(repo="owner/repo", enabled=True, token="")
    headers_no_token = client_no_token._headers()
    assert "Authorization" not in headers_no_token
    assert headers_no_token["X-GitHub-Api-Version"] == "2022-11-28"

    client_with_token = GitHubClient(repo="owner/repo", enabled=True, token="ghp_test12345")
    headers_with_token = client_with_token._headers()
    assert headers_with_token["Authorization"] == "Bearer ghp_test12345"


def test_github_client_rate_limiting_handling():
    """Rate limit 403 response with x-ratelimit-remaining=0 returns rate_limited."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.ok = False
    mock_resp.headers = {
        "x-ratelimit-remaining": "0",
        "x-ratelimit-limit": "60",
        "x-ratelimit-reset": "1710000000",
    }
    mock_resp.text = "API rate limit exceeded"

    session = MagicMock()
    session.get.return_value = mock_resp

    client = GitHubClient(repo="owner/repo", enabled=True, session=session)
    runs, error, tag = client.list_workflow_runs()
    assert tag == "rate_limited"
    assert "rate limit exceeded" in error


def test_github_client_timeout_handling():
    """Network timeouts return status 'timeout' without crashing."""
    session = MagicMock()
    session.get.side_effect = requests.Timeout("Connection timed out")

    client = GitHubClient(repo="owner/repo", enabled=True, session=session)
    runs, error, tag = client.list_workflow_runs()
    assert tag == "timeout"
    assert "timeout" in error.lower()


def test_github_client_safe_zip_extraction():
    """Safe zip in-memory extraction parses JSON files while preventing directory traversal."""
    # Build a test zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("ci-summary.json", json.dumps({"workflow_name": "Test", "tests": 42}))
        zf.writestr("nested/report.json", json.dumps({"nested": True}))
        # Attempted directory traversal: should be ignored
        zf.writestr("../escaped.json", json.dumps({"evil": True}))
        zf.writestr("/root.json", json.dumps({"evil": True}))
        # Non-JSON file: should be ignored
        zf.writestr("plain.txt", "some plain text")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.content = zip_buffer.getvalue()
    mock_resp.headers = {"x-ratelimit-remaining": "5000"}

    session = MagicMock()
    session.get.return_value = mock_resp

    client = GitHubClient(repo="owner/repo", enabled=True, session=session)
    files, error = client.download_artifact_zip_files(12345)
    assert error is None
    assert "ci-summary.json" in files
    assert files["ci-summary.json"]["tests"] == 42
    assert "report.json" in files

    # Malicious paths must NOT be present
    assert "../escaped.json" not in files
    assert "escaped.json" not in files
    assert "/root.json" not in files
    assert "plain.txt" not in files


def test_github_client_oversized_zip_rejected():
    """Artifact zip exceeding byte limit is rejected gracefully."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.content = b"x" * 2000
    mock_resp.headers = {}

    session = MagicMock()
    session.get.return_value = mock_resp

    client = GitHubClient(repo="owner/repo", enabled=True, session=session)
    files, error = client.download_artifact_zip_files(12345, max_zip_bytes=1000)
    assert files == {}
    assert "exceeds limit" in error


def test_github_client_jobs_parsing_omits_raw_logs():
    """Run jobs parsing extracts status metadata and strictly omits raw step logs."""
    jobs_payload = {
        "jobs": [
            {
                "id": 101,
                "name": "build-and-test",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-03-01T10:00:00Z",
                "completed_at": "2026-03-01T10:05:00Z",
                "steps": [
                    {
                        "name": "Run tests",
                        "status": "completed",
                        "conclusion": "success",
                        "number": 1,
                        "raw_log_tail": "SECRET_KEY=supersecret\nStack trace...",
                    }
                ],
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = jobs_payload
    mock_resp.headers = {"x-ratelimit-remaining": "5000"}

    session = MagicMock()
    session.get.return_value = mock_resp

    client = GitHubClient(repo="owner/repo", enabled=True, session=session)
    jobs, error = client.get_run_jobs(999)
    assert error is None
    assert len(jobs) == 1
    assert jobs[0]["name"] == "build-and-test"
    step = jobs[0]["steps"][0]
    assert step["name"] == "Run tests"
    assert step["conclusion"] == "success"
    # Ensure logs/raw contents are stripped
    assert "raw_log_tail" not in step
    assert "log" not in step
    assert "SECRET_KEY" not in str(step)
