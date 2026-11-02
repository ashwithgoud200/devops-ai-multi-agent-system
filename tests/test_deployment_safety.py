from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_unhealthy_remote_deployment_does_not_automatically_restore_an_image():
    script = (ROOT / "scripts" / "deploy_remote.sh").read_text(encoding="utf-8")

    assert "no automatic rollback was performed" in script
    assert "PREVIOUS_IMAGE" not in script
    assert "Restoring previous image" not in script
    assert script.count("docker run -d") == 1
