"""Tests for the integration and evidence endpoints: /integrations/status, /ci/runs/latest, /security/findings."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from calculator_app.app import app

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scanners"


def test_integrations_status_endpoint_disabled_by_default():
    """GET /integrations/status reports GitHub disabled and offline status without crashing."""
    with patch.dict(os.environ, {}, clear=True):
        resp = client.get("/integrations/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "github" in data
        assert "offline_ci" in data
        assert "offline_security" in data

        assert data["github"]["status"] == "disabled"
        assert data["github"]["enabled"] is False
        assert data["offline_ci"]["enabled"] is False
        assert data["offline_security"]["enabled"] is False


def test_integrations_status_with_mocked_github_connected():
    """GET /integrations/status reports connected when GitHub client responds successfully."""
    mock_gh_status = {
        "status": "connected",
        "enabled": True,
        "configured": True,
        "repo": "owner/repo",
        "default_branch": "main",
        "authenticated": True,
        "rate_limit": {"limit": "5000", "remaining": "4950", "reset": "1710000000"},
        "detail": "Connected",
    }
    with patch("agents.integration_api.GitHubClient.get_status", return_value=mock_gh_status):
        resp = client.get("/integrations/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["github"]["status"] == "connected"
        assert data["github"]["repo"] == "owner/repo"


def test_latest_ci_run_offline_fallback(tmp_path: Path):
    """GET /ci/runs/latest serves offline CI summary when GitHub is disabled."""
    ci_data = {
        "workflow_name": "CI Build",
        "workflow_run_id": "456",
        "conclusion": "failure",
        "tests": 25,
        "failures": 2,
        "errors": 0,
        "skipped": 1,
    }
    report_file = tmp_path / "ci-summary.json"
    report_file.write_text(json.dumps(ci_data), encoding="utf-8")

    env = {
        "DEVOPS_GITHUB_ENABLED": "false",
        "DEVOPS_CI_EVIDENCE_ENABLED": "true",
        "DEVOPS_EVIDENCE_IMPORT_DIR": str(tmp_path),
    }
    with patch.dict(os.environ, env):
        resp = client.get("/ci/runs/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["conclusion"] == "failure"
        assert data["test_summary"]["total"] == 25
        assert data["test_summary"]["failed"] == 2
        assert data["raw_logs_ingested"] is False


def test_security_findings_offline_fallback(tmp_path: Path):
    """GET /security/findings serves normalized findings and redacts any secret fields."""
    for fixture_name in ("pip_audit.json", "npm_audit.json", "trivy_image.json", "trivy_config.json", "gitleaks.json"):
        src = FIXTURES_DIR / fixture_name
        dest = tmp_path / fixture_name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    env = {
        "DEVOPS_GITHUB_ENABLED": "false",
        "DEVOPS_SECURITY_EVIDENCE_ENABLED": "true",
        "DEVOPS_EVIDENCE_IMPORT_DIR": str(tmp_path),
    }
    with patch.dict(os.environ, env):
        resp = client.get("/security/findings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("findings", "clean")
        assert "summary" in data
        assert "findings" in data
        assert "scanners" in data

        # Absolute secret redaction check
        for f in data["findings"]:
            assert "Secret" not in f
            assert "Match" not in f
            assert "secret" not in f or f["category"] == "secret"


def test_endpoints_registered_in_prometheus_metrics():
    """Requests to the new endpoints increment devops_http_requests_total."""
    resp = client.get("/integrations/status")
    assert resp.status_code == 200

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    metrics_text = metrics_resp.text
    assert 'endpoint="/integrations/status"' in metrics_text
