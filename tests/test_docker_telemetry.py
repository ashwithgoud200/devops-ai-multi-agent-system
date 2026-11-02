import json
import subprocess

from agents import docker_telemetry, graph

CONTAINER_ONE = "a" * 64
CONTAINER_TWO = "b" * 64


def _process(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _inspect(container_id, *, health="healthy", restarts=0, status="running"):
    return [{
        "Id": container_id,
        "Name": f"/container-{container_id[0]}",
        "Config": {"Image": "example/calculator:1.2"},
        "State": {
            "Status": status,
            "StartedAt": "2026-11-02T00:00:00Z",
            **({"Health": {"Status": health}} if health else {}),
        },
        "RestartCount": restarts,
    }]


def _stats(
    *,
    cpu="12.50%",
    memory="128MiB / 1GiB",
    memory_percent="12.50%",
    network="1.5kB / 2KiB",
    block="3MB / 4MiB",
):
    return json.dumps({
        "CPUPerc": cpu,
        "MemUsage": memory,
        "MemPerc": memory_percent,
        "NetIO": network,
        "BlockIO": block,
    })


def _cli(monkeypatch, handler):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return handler(command)

    monkeypatch.setattr(docker_telemetry.subprocess, "run", run)
    monkeypatch.setattr(docker_telemetry.time, "time", lambda: 1793577600.0)
    return calls


def test_docker_engine_unavailable_is_reported_without_fake_zeroes(monkeypatch):
    def handler(command):
        return _process(stderr="error during connect: Docker Desktop is stopped", returncode=1)

    _cli(monkeypatch, handler)

    result = docker_telemetry.collect_docker_metrics()

    assert result["status"] == "unavailable"
    assert result["containers"] == []
    assert "Docker Engine unavailable" in result["detail"]
    assert not any(key.endswith("_bytes") for key in result)


def test_no_running_containers_is_a_successful_empty_collection(monkeypatch):
    calls = _cli(monkeypatch, lambda command: _process())

    result = docker_telemetry.collect_docker_metrics()

    assert result["status"] == "ok"
    assert result["containers"] == []
    assert result["errors"] == []
    assert len(calls) == 1


def test_healthy_container_collects_identity_health_and_all_stats(monkeypatch):
    def handler(command):
        if command[1] == "ps":
            return _process(f"{CONTAINER_ONE}\n")
        if command[1] == "inspect":
            return _process(json.dumps(_inspect(CONTAINER_ONE)))
        if command[1] == "stats":
            return _process(_stats())
        raise AssertionError(command)

    _cli(monkeypatch, handler)

    result = docker_telemetry.collect_docker_metrics()
    container = result["containers"][0]

    assert result["status"] == "ok"
    assert container["id"] == CONTAINER_ONE
    assert container["name"] == "container-a"
    assert container["image"] == "example/calculator:1.2"
    assert container["image_name"] == "example/calculator"
    assert container["image_tag"] == "1.2"
    assert container["status"] == "running"
    assert container["health_status"] == "healthy"
    assert container["cpu_usage_percent"] == 12.5
    assert container["memory_usage_bytes"] == 128 * 1024**2
    assert container["memory_limit_bytes"] == 1024**3
    assert container["network_rx_bytes"] == 1500
    assert container["network_tx_bytes"] == 2 * 1024
    assert container["block_read_bytes"] == 3_000_000
    assert container["block_write_bytes"] == 4 * 1024**2
    assert container["restart_count"] == 0
    assert container["started_at"] is not None
    assert container["uptime_seconds"] is not None
    assert container["metrics_status"] == "ok"
    assert container["timestamp"] == result["timestamp"]


def test_high_cpu_and_memory_are_reported_without_threshold_assumptions(monkeypatch):
    def handler(command):
        if command[1] == "ps":
            return _process(f"{CONTAINER_ONE}\n")
        if command[1] == "inspect":
            return _process(json.dumps(_inspect(CONTAINER_ONE)))
        if command[1] == "stats":
            return _process(_stats(
                cpu="245.75%",
                memory="900MiB / 1GiB",
                memory_percent="87.89%",
            ))
        raise AssertionError(command)

    _cli(monkeypatch, handler)

    container = docker_telemetry.collect_docker_metrics()["containers"][0]

    assert container["cpu_usage_percent"] == 245.75
    assert container["memory_usage_bytes"] == 900 * 1024**2
    assert container["memory_usage_percent"] == 87.89


def test_unhealthy_container_and_restart_count_are_explicit(monkeypatch):
    def handler(command):
        if command[1] == "ps":
            return _process(f"{CONTAINER_ONE}\n")
        if command[1] == "inspect":
            return _process(json.dumps(_inspect(
                CONTAINER_ONE, health="unhealthy", restarts=4
            )))
        if command[1] == "stats":
            return _process(_stats())
        raise AssertionError(command)

    _cli(monkeypatch, handler)

    container = docker_telemetry.collect_docker_metrics()["containers"][0]

    assert container["health_status"] == "unhealthy"
    assert container["restart_count"] == 4
    assert graph._docker_incident_signal({"status": "ok", "containers": [container]})


def test_missing_stats_are_unavailable_not_zero_and_partial(monkeypatch):
    def handler(command):
        if command[1] == "ps":
            return _process(f"{CONTAINER_ONE}\n")
        if command[1] == "inspect":
            return _process(json.dumps(_inspect(CONTAINER_ONE)))
        if command[1] == "stats":
            return _process(json.dumps({"CPUPerc": "bad", "MemUsage": "unknown"}))
        raise AssertionError(command)

    _cli(monkeypatch, handler)

    result = docker_telemetry.collect_docker_metrics()
    container = result["containers"][0]

    assert result["status"] == "partial"
    assert container["metrics_status"] == "unavailable"
    assert container["cpu_usage_percent"] is None
    assert container["memory_usage_bytes"] is None
    assert container["network_rx_bytes"] is None
    assert result["errors"]


def test_one_container_failure_does_not_discard_other_container_metrics(monkeypatch):
    def handler(command):
        if command[1] == "ps":
            return _process(f"{CONTAINER_ONE}\n{CONTAINER_TWO}\n")
        if command[1] == "inspect" and command[-1] == CONTAINER_ONE:
            return _process(json.dumps(_inspect(CONTAINER_ONE)))
        if command[1] == "inspect" and command[-1] == CONTAINER_TWO:
            return _process(stderr="permission denied", returncode=1)
        if command[1] == "stats":
            return _process(_stats())
        raise AssertionError(command)

    calls = _cli(monkeypatch, handler)

    result = docker_telemetry.collect_docker_metrics()

    assert result["status"] == "partial"
    assert result["containers"][0]["metrics_status"] == "ok"
    assert result["containers"][1]["metrics_status"] == "unavailable"
    assert "Docker permission error" in result["errors"][0]["detail"]
    assert any(call[-1] == CONTAINER_ONE for call in calls if call[1] == "stats")


def test_docker_timeout_is_explicit(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=5)

    monkeypatch.setattr(docker_telemetry.subprocess, "run", timeout)

    result = docker_telemetry.collect_docker_metrics()

    assert result["status"] == "unavailable"
    assert "Docker command timed out" in result["detail"]


def test_graph_passes_docker_evidence_to_relevant_agents_only(monkeypatch):
    docker = {
        "status": "ok",
        "source": "synthetic Docker fixture",
        "timestamp": 1793577600.0,
        "containers": [{
            "id": CONTAINER_ONE,
            "name": "container-a",
            "status": "running",
            "health_status": "healthy",
            "cpu_usage_percent": 85.0,
            "memory_usage_bytes": 1000,
            "memory_limit_bytes": 2000,
            "memory_usage_percent": 50.0,
            "restart_count": 0,
            "metrics_status": "ok",
        }],
        "errors": [],
    }
    state = {
        "query": "container performance issue",
        "evidence": {
            "health": {"status": "unavailable"},
            "metrics": {"status": "unavailable"},
            "system_metrics": {"status": "unavailable"},
            "version": {"status": "unavailable"},
            "logs": {
                "status": "ok",
                "source": "synthetic fixture",
                "events": [{
                    "ts": 1793577500.0,
                    "level": "WARN",
                    "msg": "Suspicious login event in fixture",
                }],
            },
            "docker": docker,
        },
        "comparison": {"regression_signal": False, "deployment_changed": False},
    }

    selected = graph._select_specialists(state)
    monitoring = graph._specialist_evidence("monitoring", state)
    incident = graph._specialist_evidence("incident", state)
    infrastructure = graph._specialist_evidence("infrastructure", state)
    security = graph._specialist_evidence("security", state)
    facts = graph._observed_facts(
        state["evidence"], {"status": "unavailable"}, state["comparison"]
    )

    assert "monitoring" in selected
    assert "infrastructure" in selected
    assert monitoring["docker"] == docker
    assert incident["docker"] == docker
    assert infrastructure["docker"] == docker
    assert "docker" not in security
    assert security["security_events"]["events"] == state["evidence"]["logs"]["events"]
    assert any(
        fact["source"] == "docker.containers[0].cpu_usage_percent"
        and fact["timestamp"] == docker["timestamp"]
        for fact in facts
    )
    assert any(
        fact["source"] == "docker.containers[0].restart_count"
        and "0" in fact["statement"]
        for fact in facts
    )


def test_docker_claim_validation_flags_unknown_values_ids_and_restart_counts():
    evidence = {
        "docker": {
            "containers": [{
                "id": CONTAINER_ONE,
                "name": "calculator",
                "cpu_usage_percent": 82.0,
                "memory_usage_percent": 70.0,
                "restart_count": 2,
            }]
        }
    }

    supported = graph._validate_finding(
        f"Container ID {CONTAINER_ONE} has CPU usage 82%.", evidence
    )
    invented = graph._validate_finding(
        f"Container ID {CONTAINER_TWO} has CPU usage 99% and restarted 5 times.",
        evidence,
    )

    assert supported["validation_status"] == "numbers_supported"
    assert f"docker.containers[0].id" in supported["evidence_refs"]
    assert invented["validation_status"] == "unverified"
    assert any("container ID" in reason for reason in invented["reasons"])
    assert any("numeric claim 99%" in reason for reason in invented["reasons"])
    assert any("numeric claim 5" in reason for reason in invented["reasons"])
