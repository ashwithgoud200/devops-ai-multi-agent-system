from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_unhealthy_remote_deployment_does_not_automatically_restore_an_image():
    script = (ROOT / "scripts" / "deploy_remote.sh").read_text(encoding="utf-8")

    assert "no automatic rollback was performed" in script
    assert "PREVIOUS_IMAGE" not in script
    assert "Restoring previous image" not in script
    assert script.count("docker run -d") == 1


def test_local_deployment_scripts_and_workflow_preserve_volumes_and_verify_health():
    ps_script = (ROOT / "scripts" / "deploy_local.ps1").read_text(encoding="utf-8")
    sh_script = (ROOT / "scripts" / "deploy_local.sh").read_text(encoding="utf-8")
    deploy_wf_path = ROOT / ".github" / "workflows" / "docker-deploy.yml"

    assert deploy_wf_path.exists()
    deploy_wf = yaml.safe_load(deploy_wf_path.read_text(encoding="utf-8"))
    assert deploy_wf["permissions"] == {"contents": "read", "packages": "read"}
    assert deploy_wf["env"]["DEVOPS_LLM_ENABLED"] == "false"

    job = deploy_wf["jobs"]["deploy-local-compose"]
    steps_by_name = {step["name"]: step for step in job["steps"]}
    exec_step = steps_by_name["Execute safe local deployment script"]
    assert exec_step["env"]["INPUT_IMAGE_TAG"] == "${{ inputs.image_tag }}"
    assert 'export APP_IMAGE="${INPUT_IMAGE_TAG}"' in exec_step["run"]

    stop_step = steps_by_name[
        "Stop ephemeral containers on GitHub-hosted runner only (preserving volumes)"
    ]
    assert "runner.environment == 'github-hosted'" in stop_step["if"]

    for script in (ps_script, sh_script):
        assert "docker compose config --quiet" in script
        assert "docker compose up -d" in script
        assert "http://127.0.0.1:8100/health" in script
        assert "http://127.0.0.1:8100/agents" in script
        assert "http://127.0.0.1:8100/metrics" in script
        assert "http://127.0.0.1:8100/admin/version" in script
        assert "http://127.0.0.1:9090/-/healthy" in script
        assert "http://127.0.0.1:3000/api/health" in script
        assert "http://127.0.0.1:4173/" in script
        assert "http://127.0.0.1:4173/api/health" in script
        assert "Prometheus scrape validation failed" in script
        # Must never delete volumes
        assert "down -v" not in script
        assert "--volumes" not in script
        assert "volume rm" not in script


def test_compose_services_all_bind_to_loopback_and_define_healthchecks():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert {"calculator-app", "prometheus", "grafana", "frontend"} == set(services)
    assert services["frontend"]["ports"] == ["127.0.0.1:4173:4173"]
    for name, svc in services.items():
        for port_mapping in svc.get("ports", []):
            assert str(port_mapping).startswith("127.0.0.1:"), (
                f"Service {name} exposes non-loopback port: {port_mapping}"
            )
        assert "healthcheck" in svc, f"Service {name} must define a container healthcheck"
