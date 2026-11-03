from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_ci_workflow_is_valid_yaml_and_has_least_privilege_permissions():
    ci_path = WORKFLOWS / "ci.yml"
    assert ci_path.exists(), ".github/workflows/ci.yml must exist"
    workflow = yaml.safe_load(ci_path.read_text(encoding="utf-8"))

    assert workflow["name"] == "Continuous Integration"
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["env"]["DEVOPS_LLM_ENABLED"] == "false"

    triggers = workflow.get("on") or workflow.get(True)
    assert "push" in triggers
    assert "pull_request" in triggers
    assert "main" in triggers["push"]["branches"]
    assert "main" in triggers["pull_request"]["branches"]


def test_ci_workflow_validates_backend_frontend_and_docker_without_ollama_or_ssh():
    ci_path = WORKFLOWS / "ci.yml"
    raw = ci_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    jobs = workflow["jobs"]

    assert {"backend-ci", "frontend-ci", "docker-validation"} <= set(jobs)

    # Backend CI checks
    backend_steps = [step.get("run", "") for step in jobs["backend-ci"]["steps"]]
    assert any("pytest" in step for step in backend_steps)
    assert any("compileall" in step for step in backend_steps)
    assert jobs["backend-ci"]["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]

    # Frontend CI checks
    assert jobs["frontend-ci"]["defaults"]["run"]["working-directory"] == "frontend"
    frontend_steps = [step.get("run", "") for step in jobs["frontend-ci"]["steps"]]
    assert any("npm ci" in step for step in frontend_steps)
    assert any("npm run build" in step for step in frontend_steps)

    # Docker validation checks
    docker_steps = jobs["docker-validation"]["steps"]
    docker_runs = [step.get("run", "") for step in docker_steps]
    assert any("docker compose config --quiet" in step for step in docker_runs)
    build_step = next(
        step for step in docker_steps
        if str(step.get("uses", "")).startswith("docker/build-push-action@")
    )
    assert build_step["with"]["push"] is False

    # Ensure CI does not require Ollama models or perform SSH/cloud deployment
    assert "ollama pull" not in raw
    assert "pull_models" not in raw
    assert "DEPLOY_SSH_KEY" not in raw
    assert "scp " not in raw


def test_security_workflow_runs_secret_python_node_and_trivy_scans():
    security_path = WORKFLOWS / "security.yml"
    assert security_path.exists(), ".github/workflows/security.yml must exist"
    raw = security_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)

    assert workflow["name"] == "Security Scanning"
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["env"]["DEVOPS_LLM_ENABLED"] == "false"

    triggers = workflow.get("on") or workflow.get(True)
    assert "push" in triggers
    assert "pull_request" in triggers

    jobs = workflow["jobs"]
    assert {
        "secret-scan",
        "python-dependency-scan",
        "node-dependency-scan",
        "docker-trivy-scan",
    } <= set(jobs)

    # Secret scan
    secret_uses = [step.get("uses", "") for step in jobs["secret-scan"]["steps"]]
    assert any(u.startswith("gitleaks/gitleaks-action@") for u in secret_uses)

    # Python pip-audit
    py_runs = "\n".join(step.get("run", "") for step in jobs["python-dependency-scan"]["steps"])
    assert "pip-audit" in py_runs or "pip_audit" in py_runs

    # Node npm audit
    node_runs = "\n".join(step.get("run", "") for step in jobs["node-dependency-scan"]["steps"])
    assert "npm audit" in node_runs

    # Docker Trivy scan
    trivy_uses = [step.get("uses", "") for step in jobs["docker-trivy-scan"]["steps"]]
    assert any(u.startswith("aquasecurity/trivy-action@") for u in trivy_uses)
    assert "DEPLOY_SSH_KEY" not in raw


def _eval_github_if_condition(condition: str, event_name: str, ref: str) -> bool:
    """Evaluate the docker-publish job `if:` expression for a simulated GitHub context."""
    expected_clause = (
        "github.event_name != 'pull_request' && "
        "github.event_name != 'pull_request_target' && "
        "(github.ref == 'refs/heads/main' || "
        "github.ref == 'refs/heads/master' || "
        "startsWith(github.ref, 'refs/tags/v'))"
    )
    normalized = " ".join(condition.split())
    assert normalized == expected_clause, f"Unexpected job if condition: {normalized}"
    return (
        event_name != "pull_request"
        and event_name != "pull_request_target"
        and (
            ref == "refs/heads/main"
            or ref == "refs/heads/master"
            or ref.startswith("refs/tags/v")
        )
    )


def test_docker_publish_workflow_enforces_least_privilege_and_blocks_pull_requests():
    publish_path = WORKFLOWS / "docker-publish.yml"
    assert publish_path.exists(), ".github/workflows/docker-publish.yml must exist"
    raw = publish_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)

    assert workflow["name"] == "Publish Docker Image to GHCR"
    assert workflow["permissions"] == {"contents": "read"}

    triggers = workflow.get("on") or workflow.get(True)
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers
    assert "push" in triggers
    assert triggers["push"]["branches"] == ["main", "master"]
    assert "v*.*.*" in triggers["push"]["tags"]

    jobs = workflow["jobs"]
    assert {"validate", "publish-ghcr"} <= set(jobs)

    validate_job = jobs["validate"]
    publish_job = jobs["publish-ghcr"]
    assert publish_job["needs"] == "validate"
    assert validate_job["permissions"] == {"contents": "read"}
    assert publish_job["permissions"] == {"contents": "read", "packages": "write"}

    for job in (validate_job, publish_job):
        cond = job["if"]
        # Allowed: main branch, master branch, and valid version tags
        assert _eval_github_if_condition(cond, "push", "refs/heads/main") is True
        assert _eval_github_if_condition(cond, "workflow_dispatch", "refs/heads/main") is True
        assert _eval_github_if_condition(cond, "push", "refs/heads/master") is True
        assert _eval_github_if_condition(cond, "workflow_dispatch", "refs/heads/master") is True
        assert _eval_github_if_condition(cond, "push", "refs/tags/v1.0.0") is True
        assert _eval_github_if_condition(cond, "workflow_dispatch", "refs/tags/v1.2.3") is True

        # Blocked: feature branches, manual dispatch on feature branch, and pull requests
        assert _eval_github_if_condition(cond, "push", "refs/heads/feature/test") is False
        assert _eval_github_if_condition(cond, "workflow_dispatch", "refs/heads/feature/test") is False
        assert _eval_github_if_condition(cond, "workflow_dispatch", "refs/heads/dev") is False
        assert _eval_github_if_condition(cond, "pull_request", "refs/heads/main") is False
        assert _eval_github_if_condition(cond, "pull_request_target", "refs/heads/main") is False

    steps = publish_job["steps"]
    login_step = next(
        s for s in steps if str(s.get("uses", "")).startswith("docker/login-action@")
    )
    assert login_step["with"]["registry"] == "ghcr.io"
    assert login_step["with"]["password"] == "${{ secrets.GITHUB_TOKEN }}"

    meta_step = next(
        s for s in steps if str(s.get("uses", "")).startswith("docker/metadata-action@")
    )
    tags_cfg = meta_step["with"]["tags"]
    assert "type=sha,prefix=sha-" in tags_cfg
    assert "type=semver" in tags_cfg
    assert "type=ref,event=tag" in tags_cfg

    push_step = next(
        s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action@")
    )
    assert push_step["with"]["push"] is True
    assert "DEPLOY_SSH_KEY" not in raw
    assert "ssh " not in raw


def test_legacy_cicd_workflow_is_retired_without_duplicate_ci_publish_or_ssh():
    legacy_path = WORKFLOWS / "ci-cd.yml"
    if legacy_path.exists():
        raw = legacy_path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(raw)
        triggers = workflow.get("on") or workflow.get(True)
        assert "push" not in triggers
        assert "pull_request" not in triggers
        assert "deploy" not in workflow.get("jobs", {})
        assert "build-and-push" not in workflow.get("jobs", {})
        assert "packages: write" not in raw
        assert "DEPLOY_SSH_KEY" not in raw
        assert "DEPLOY_HOST" not in raw
        assert "ssh " not in raw
        assert "scp " not in raw



def test_security_workflow_generates_json_reports_and_uploads_artifacts_with_short_retention():
    """Verify security workflow produces scanner-native JSON reports and uploads them with 7-day retention."""
    security_path = WORKFLOWS / "security.yml"
    raw = security_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    jobs = workflow["jobs"]

    # 1. Gitleaks secret scan outputs JSON, sanitizes Secret/Match, and uploads artifact
    secret_steps = jobs["secret-scan"]["steps"]
    gitleaks_step = next(s for s in secret_steps if "gitleaks-action" in str(s.get("uses", "")))
    assert gitleaks_step["env"]["GITLEAKS_REPORT_PATH"] == "reports/gitleaks-raw.json"
    sanitize_step = next(s for s in secret_steps if "Sanitize Gitleaks report" in s.get("name", ""))
    assert sanitize_step["if"] == "always()"
    assert "Secret" in sanitize_step["run"] and "Match" in sanitize_step["run"]
    gitleaks_upload = next(s for s in secret_steps if "upload-artifact" in str(s.get("uses", "")))
    assert gitleaks_upload["if"] == "always()"
    assert gitleaks_upload["with"]["name"] == "security-gitleaks-report"
    assert gitleaks_upload["with"]["retention-days"] == 7
    assert gitleaks_upload["with"]["path"] == "reports/gitleaks.json"

    # 2. pip-audit outputs JSON and uploads artifact
    py_steps = jobs["python-dependency-scan"]["steps"]
    py_audit = next(s for s in py_steps if "pip_audit" in str(s.get("run", "")))
    assert "-f json -o reports/pip_audit.json" in py_audit["run"]
    assert "exit $EXIT_CODE" in py_audit["run"]
    py_upload = next(s for s in py_steps if "upload-artifact" in str(s.get("uses", "")))
    assert py_upload["if"] == "always()"
    assert py_upload["with"]["name"] == "security-pip-audit-report"
    assert py_upload["with"]["retention-days"] == 7

    # 3. npm audit outputs JSON and uploads artifact
    node_steps = jobs["node-dependency-scan"]["steps"]
    npm_audit = next(s for s in node_steps if "npm audit" in str(s.get("run", "")))
    assert "npm audit --json > ../reports/npm_audit.json" in npm_audit["run"]
    assert "npm audit --audit-level=high" in npm_audit["run"]
    node_upload = next(s for s in node_steps if "upload-artifact" in str(s.get("uses", "")))
    assert node_upload["if"] == "always()"
    assert node_upload["with"]["name"] == "security-npm-audit-report"
    assert node_upload["with"]["retention-days"] == 7

    # 4. Trivy config and image scans output JSON and enforce exit code 1 gates
    trivy_steps = jobs["docker-trivy-scan"]["steps"]
    config_json = next(
        s for s in trivy_steps
        if s.get("with", {}).get("scan-type") == "config" and s.get("with", {}).get("format") == "json"
    )
    assert config_json["with"]["output"] == "reports/trivy_config.json"
    config_gate = next(
        s for s in trivy_steps
        if s.get("with", {}).get("scan-type") == "config" and s.get("with", {}).get("format") == "table"
    )
    assert config_gate["with"]["exit-code"] == "1"

    image_json = next(
        s for s in trivy_steps
        if "image-ref" in s.get("with", {}) and s.get("with", {}).get("format") == "json"
    )
    assert image_json["with"]["output"] == "reports/trivy_image.json"
    image_gate = next(
        s for s in trivy_steps
        if "image-ref" in s.get("with", {}) and s.get("with", {}).get("format") == "table"
    )
    assert image_gate["with"]["exit-code"] == "1"

    trivy_upload = next(s for s in trivy_steps if "upload-artifact" in str(s.get("uses", "")))
    assert trivy_upload["if"] == "always()"
    assert trivy_upload["with"]["name"] == "security-trivy-reports"
    assert trivy_upload["with"]["retention-days"] == 7


def test_ci_workflow_generates_junit_xml_and_summary_with_short_retention():
    """Verify CI workflow produces JUnit XML and machine-readable summary with 7-day retention."""
    ci_path = WORKFLOWS / "ci.yml"
    raw = ci_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    backend_steps = workflow["jobs"]["backend-ci"]["steps"]

    # 1. pytest includes --junitxml flag
    pytest_step = next(s for s in backend_steps if "pytest" in str(s.get("run", "")))
    assert "--junitxml=reports/junit/test-results-${{ matrix.python-version }}.xml" in pytest_step["run"]

    # 2. Machine-readable CI summary JSON generation
    summary_step = next(s for s in backend_steps if "Generate machine-readable CI summary JSON" in s.get("name", ""))
    assert summary_step["if"] == "always()"
    assert "ci-summary-${{ matrix.python-version }}.json" in summary_step["run"]

    # 3. Artifact upload configuration
    upload_step = next(s for s in backend_steps if "upload-artifact" in str(s.get("uses", "")))
    assert upload_step["if"] == "always()"
    assert upload_step["with"]["name"] == "ci-backend-results-${{ matrix.python-version }}"
    assert upload_step["with"]["retention-days"] == 7


def test_third_party_actions_pinned_to_verified_full_commit_shas():
    """Verify every third-party action in CI and Security workflows is pinned to a 40-character commit SHA."""
    import re
    sha_pattern = re.compile(r"^[0-9a-f]{40}$")

    for workflow_file in ("ci.yml", "security.yml"):
        workflow_path = WORKFLOWS / workflow_file
        raw = workflow_path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(raw)

        for job_name, job in workflow.get("jobs", {}).items():
            for step in job.get("steps", []):
                uses = step.get("uses")
                if not uses or str(uses).startswith(("./", "actions/")):
                    # Check actions/* as well since third-party to this repo
                    pass
                if uses:
                    action_part, _, ref = str(uses).partition("@")
                    assert sha_pattern.match(ref), (
                        f"Action '{uses}' in {workflow_file} job '{job_name}' must be pinned to full 40-char SHA"
                    )

        # Also verify raw text contains version comments for transparency
        lines = [line.strip() for line in raw.splitlines() if "uses:" in line and "@" in line]
        for line in lines:
            assert "#" in line, f"Pinned action line must include version comment: '{line}'"


def test_least_privilege_permissions_and_no_security_events_write():
    """Verify workflows maintain contents: read and do not request security-events: write or SARIF upload."""
    for workflow_file in ("ci.yml", "security.yml"):
        workflow_path = WORKFLOWS / workflow_file
        raw = workflow_path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(raw)

        assert workflow.get("permissions") == {"contents": "read"}
        assert "security-events: write" not in raw
        assert "security-events:write" not in raw
        assert "upload-sarif" not in raw
