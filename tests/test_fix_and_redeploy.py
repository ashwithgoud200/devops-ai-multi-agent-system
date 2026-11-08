"""Tests for the post-rollback Code Agent fix and CI/CD redeploy lifecycle."""
from __future__ import annotations

import time
from calculator_app.app import app, STATE
from agents.incident_api import fix_and_redeploy, _read_audit_events
from agents.scenarios import activate_scenario, reset_scenario, SCENARIO_DEPLOYMENT_REGRESSION


def test_fix_and_redeploy_lifecycle():
    """Verify that after a rollback, the Code Agent fixes the defect and CI/CD redeploys v1.1.1."""
    # 1. Activate deployment regression (v1.1 with bug)
    activate_scenario(SCENARIO_DEPLOYMENT_REGRESSION, calculator_state=STATE)
    assert STATE["version"] == "1.1"
    assert STATE["bug"] is True

    # 2. Simulate rollback to v1.0
    STATE["version"] = "1.0"
    STATE["bug"] = False
    STATE["history"].append({"version": "1.0", "ts": time.time()})

    # 3. Call fix_and_redeploy
    result = fix_and_redeploy("test-incident-uuid-1234")
    assert result["status"] == "succeeded"
    assert result["incident_id"] == "test-incident-uuid-1234"

    # Step 1: verify mitigation record
    assert result["step_1_mitigation"]["action"] == "rollback"
    assert result["step_1_mitigation"]["restored_version"] == "1.0"

    # Step 2: verify Code Agent fix
    code_fix = result["step_2_code_fix"]
    assert code_fix["agent"] == "code"
    assert code_fix["model"] == "qwen2.5-coder:3b"
    assert code_fix["target_version"] == "1.1.1"
    assert "patch" in code_fix

    # Step 3: verify CI/CD deployment
    cicd = result["step_3_cicd_deployment"]
    assert cicd["agent"] == "cicd"
    assert cicd["deployed_version"] == "1.1.1"
    assert cicd["pipeline_status"] == "success"
    assert cicd["health_verification"]["status"] == "ok"
    assert cicd["health_verification"]["version"] == "1.1.1"

    # Verify live application state
    assert STATE["version"] == "1.1.1"
    assert STATE["bug"] is False

    # Verify audit log contains hotfix_deployed
    audit_events = _read_audit_events()
    assert any(
        e.get("event") == "hotfix_deployed" and e.get("deployed_version") == "1.1.1"
        for e in audit_events
    )

    # Clean up state
    reset_scenario(calculator_state=STATE)

