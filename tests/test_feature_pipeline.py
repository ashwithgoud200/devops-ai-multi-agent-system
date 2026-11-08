"""Unit tests for Dynamic Code Agent feature addition, CI/CD verification, and deployment."""
from __future__ import annotations

import time
from calculator_app.app import app, calc, OPS, STATE
from agents.feature_api import (
    generate_custom_feature,
    validate_feature_ci,
    deploy_feature,
    get_feature_status,
    FeatureRequest,
    CiValidationRequest,
    DeployFeatureRequest,
)


def test_code_agent_generate_custom_user_feature():
    """Verify Code Agent dynamically synthesizes any feature specified by the user."""
    # User specifies custom power function
    req = FeatureRequest(
        feature_name="Power Function",
        op="pow_custom",
        description="Calculates a raised to the power b",
        param_count=2,
        formula="a ** b",
    )
    res = generate_custom_feature(req)
    assert res["status"] == "generated"
    assert res["op"] == "pow_custom"
    assert 'OPS["pow_custom"]' in res["code_snippet"]
    assert "run_test_pow_custom" in res["test_code"]
    assert "ashwithgoud200/Code-Agent" in res["github_repo"]
    assert res["branch_name"] == "feature/calc-pow_custom"
    assert res["agent"] == "code"


def test_code_agent_generate_unary_factorial_feature():
    """Verify Code Agent dynamically synthesizes unary factorial with boundary checks."""
    req = FeatureRequest(
        feature_name="Factorial",
        op="fact",
        description="Computes factorial of a non-negative integer",
        param_count=1,
    )
    res = generate_custom_feature(req)
    assert res["status"] == "generated"
    assert res["op"] == "fact"
    assert "math.factorial" in res["code_snippet"]
    assert "run_test_fact" in res["test_code"]


def test_cicd_agent_validates_feature_and_github_reporting():
    """Verify CI/CD pipeline validates syntax, executes tests, and reports GitHub details."""
    gen = generate_custom_feature(FeatureRequest(
        feature_name="Modulo Remainder",
        op="mod",
        description="Remainder of a / b with zero check",
        param_count=2,
    ))
    ci_req = CiValidationRequest(
        feature_name=gen["feature_name"],
        op=gen["op"],
        code_snippet=gen["code_snippet"],
        test_code=gen["test_code"],
        branch_name=gen["branch_name"],
        description=gen["description"],
    )
    ci_res = validate_feature_ci(ci_req)
    assert ci_res["status"] == "success"
    assert ci_res["pipeline_status"] == "passed"
    assert ci_res["tests_summary"]["total"] > 0
    assert ci_res["tests_summary"]["failed"] == 0
    assert any("Backend Quality" in job["name"] for job in ci_res["jobs"])
    assert any("Security" in job["name"] for job in ci_res["jobs"])
    assert "ashwithgoud200/Code-Agent" in ci_res["github"]["repo"]
    assert ci_res["agent"] == "cicd"


def test_deploy_custom_feature_end_to_end_and_live_execution():
    """Verify human approval deploys user's custom feature and activates endpoint live."""
    initial_version = STATE["version"]

    gen = generate_custom_feature(FeatureRequest(
        feature_name="Modulo",
        op="mod",
        description="a % b",
        param_count=2,
    ))

    deploy_req = DeployFeatureRequest(
        op=gen["op"],
        feature_name=gen["feature_name"],
        code_snippet=gen["code_snippet"],
        reviewer="lead-architect",
    )
    deploy_res = deploy_feature(deploy_req)

    assert deploy_res["status"] == "deployed"
    assert deploy_res["op"] == "mod"
    assert deploy_res["version"] != initial_version
    assert deploy_res["reviewer"] == "lead-architect"
    assert deploy_res["github_repo"] == "ashwithgoud200/Code-Agent"
    assert deploy_res["smoke_test"]["status"] == "ok"

    # Verify live calc execution directly
    calc_res = calc("mod", 14.0, 4.0)
    assert calc_res["result"] == 2.0
    assert calc_res["op"] == "mod"

    # Verify division-by-zero is caught
    try:
        calc("mod", 10.0, 0.0)
        assert False, "Should raise HTTPException 400"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400

    # Verify status endpoint reflects repo and operations
    status = get_feature_status()
    assert "mod" in status["available_operations"]
    assert status["github"]["repo"] == "ashwithgoud200/Code-Agent"
    assert status["github"]["enabled"] is True
