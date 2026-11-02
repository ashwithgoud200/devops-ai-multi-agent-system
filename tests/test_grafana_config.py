import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
GRAFANA_ROOT = ROOT / "grafana"


def test_grafana_provisioning_yaml_is_valid_and_configures_default_prometheus():
    datasource_path = (
        GRAFANA_ROOT / "provisioning" / "datasources" / "prometheus.yml"
    )
    dashboard_provider_path = (
        GRAFANA_ROOT / "provisioning" / "dashboards" / "dashboards.yml"
    )
    datasource = yaml.safe_load(datasource_path.read_text(encoding="utf-8"))
    provider = yaml.safe_load(dashboard_provider_path.read_text(encoding="utf-8"))

    assert datasource["apiVersion"] == 1
    configured = datasource["datasources"][0]
    assert configured["name"] == "Prometheus"
    assert configured["uid"] == "prometheus"
    assert configured["type"] == "prometheus"
    assert configured["access"] == "proxy"
    assert configured["url"] == "http://prometheus:9090"
    assert configured["isDefault"] is True
    assert provider["providers"][0]["options"]["path"] == "/etc/grafana/dashboards"


def test_dashboard_json_contains_expected_groups_queries_and_units():
    dashboard_path = GRAFANA_ROOT / "dashboards" / "devops-overview.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panels = dashboard["panels"]
    panels_by_title = {panel["title"]: panel for panel in panels}

    assert dashboard["title"] == "AI DevOps — System Monitoring Overview"
    assert dashboard["time"] == {"from": "now-15m", "to": "now"}
    assert dashboard["refresh"] == "30s"
    assert {
        "Application Overview",
        "Application Resource Usage",
        "Docker Container Monitoring (optional)",
        "Host Monitoring (optional)",
    } <= {panel["title"] for panel in panels if panel["type"] == "row"}

    expected_queries = {
        "Application Request Rate":
            "sum by (op, status) (rate(calc_requests_total[5m]))",
        "Successful Request Rate":
            'sum by (op) (rate(calc_requests_total{status="ok"}[5m]))',
        "Application Error Rate":
            '100 * sum(rate(calc_requests_total{status=~"error|client_error"}[5m])) / sum(rate(calc_requests_total[5m]))',
        "P95 Request Latency":
            "histogram_quantile(0.95, sum by (le, op) (rate(calc_latency_seconds_bucket[5m])))",
        "Process CPU Usage": "rate(process_cpu_seconds_total[5m]) * 100",
        "Process Memory Usage": "process_resident_memory_bytes / 1024 / 1024",
        "Container CPU Usage":
            "sum by (container, image) (rate(container_cpu_usage_seconds_total[5m])) * 100",
        "Container Memory Usage":
            "sum by (container, image) (container_memory_working_set_bytes)",
        "Host CPU Utilization":
            '100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])))',
        "Host Memory Utilization":
            "100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)",
    }
    for title, expression in expected_queries.items():
        panel = panels_by_title[title]
        assert panel["targets"][0]["expr"] == expression
        assert panel["targets"][0]["datasource"]["uid"] == "prometheus"

    assert panels_by_title["Process CPU Usage"]["fieldConfig"]["defaults"]["unit"] == "percent"
    assert panels_by_title["Process Memory Usage"]["fieldConfig"]["defaults"]["unit"] == "mebibytes"
    assert panels_by_title["Application Error Rate"]["fieldConfig"]["defaults"]["noValue"] == "No Data"
    for title in ("Container Restarts", "Container Health / Status"):
        assert panels_by_title[title]["targets"] == []
        assert "No Data" == panels_by_title[title]["fieldConfig"]["defaults"]["noValue"]
    assert len({panel["id"] for panel in panels}) == len(panels)


def test_compose_provisions_grafana_with_local_binding_and_persistent_storage():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    grafana = compose["services"]["grafana"]

    assert grafana["image"].startswith("grafana/grafana:")
    assert grafana["ports"] == ["127.0.0.1:3000:3000"]
    assert grafana["depends_on"]["prometheus"]["condition"] == "service_started"
    assert "GF_SECURITY_ADMIN_USER" in grafana["environment"]
    assert "GF_SECURITY_ADMIN_PASSWORD" in grafana["environment"]
    assert any("grafana_data:/var/lib/grafana" in volume for volume in grafana["volumes"])
    assert "grafana_data" in compose["volumes"]
    assert any("provisioning" in volume for volume in grafana["volumes"])
    assert any("dashboards" in volume for volume in grafana["volumes"])


def test_compose_binds_app_to_loopback_and_persists_baseline_and_audit_logs():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    app = compose["services"]["calculator-app"]

    assert app["ports"] == ["127.0.0.1:8100:8100"]
    assert "DEVOPS_BASELINE_PATH=/app/data/baseline.json" in app["environment"]
    assert "DEVOPS_AUDIT_LOG_PATH=/app/logs/incident_audit.jsonl" in app["environment"]
    assert {"app_data", "app_logs"} <= {
        volume.split(":", 1)[0] for volume in app["volumes"]
    }


def test_environment_example_uses_development_only_grafana_credentials():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "GRAFANA_ADMIN_USER=admin" in example
    assert "GRAFANA_ADMIN_PASSWORD=local-dev-change-me" in example
