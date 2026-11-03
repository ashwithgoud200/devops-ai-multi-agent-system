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
    provider_cfg = provider["providers"][0]
    assert provider_cfg["options"]["path"] == "/etc/grafana/dashboards"
    assert provider_cfg["disableDeletion"] is True
    assert provider_cfg["updateIntervalSeconds"] == 30


def test_dashboard_json_contains_expected_groups_queries_and_units():
    dashboard_path = GRAFANA_ROOT / "dashboards" / "devops-overview.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panels = dashboard["panels"]
    panels_by_title = {panel["title"]: panel for panel in panels}

    assert dashboard["title"] == "AI DevOps — System Monitoring Overview"
    assert dashboard["time"] == {"from": "now-15m", "to": "now"}
    assert dashboard["refresh"] == "30s"
    row_titles = {panel["title"] for panel in panels if panel["type"] == "row"}
    assert {
        "Application Overview",
        "Application Resource Usage",
        "Docker Container Monitoring (optional)",
        "Host Monitoring (optional)",
        "System Overview",
        "API Performance",
        "Six-Agent Performance",
        "Incident Monitoring",
        "Human Approval and Audit",
        "LLM Runtime",
        "Infrastructure and Container Health",
    } <= row_titles

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
        "Backend Target Up": 'up{job="calculator-app"}',
        "Application Health Status": "devops_app_health_status",
        "LLM Inference Enabled": "devops_llm_enabled",
        "Active Pending Approvals":
            'sum(devops_incidents_current_status{status="pending_approval"})',
        "HTTP Request Rate by Endpoint":
            "sum by (endpoint, method, status) (rate(devops_http_requests_total[5m]))",
        "HTTP Request P95 Latency by Endpoint":
            "histogram_quantile(0.95, sum by (le, endpoint, method) (rate(devops_http_request_duration_seconds_bucket[5m])))",
        "Specialist Agent Executions by Outcome":
            "sum by (agent, outcome) (increase(devops_agent_executions_total[15m]))",
        "Specialist Agent P95 Execution Duration":
            "histogram_quantile(0.95, sum by (le, agent) (rate(devops_agent_execution_duration_seconds_bucket[15m])))",
        "Total Incidents Created": "sum(devops_incidents_created_total)",
        "Current Incidents by Status":
            "sum by (status) (devops_incidents_current_status)",
        "Incidents by Lifecycle Status":
            "sum by (status) (devops_incidents_by_status_total)",
        "Incident Diagnoses by Proposed Remediation":
            "sum by (remediation_action) (devops_incident_diagnoses_total)",
        "Human Approval vs Rejection Decisions":
            "sum by (decision, action) (devops_human_decisions_total)",
        "Audit Log Events by Type": "sum by (event) (devops_audit_events_total)",
        "LLM Inference Calls by Model & Status":
            "sum by (agent, model, status) (increase(devops_llm_requests_total[15m]))",
        "LLM Inference P95 Latency by Model":
            "histogram_quantile(0.95, sum by (le, agent, model) (rate(devops_llm_request_duration_seconds_bucket[15m])))",
        "Prometheus Scrape Sample Count":
            'scrape_samples_scraped{job="calculator-app"}',
        "Prometheus Scrape Duration":
            'scrape_duration_seconds{job="calculator-app"}',
    }
    for title, expression in expected_queries.items():
        panel = panels_by_title[title]
        assert panel["targets"][0]["expr"] == expression
        assert panel["targets"][0]["datasource"]["uid"] == "prometheus"
        assert panel.get("description"), f"Panel {title} must include a description"

    assert panels_by_title["Process CPU Usage"]["fieldConfig"]["defaults"]["unit"] == "percent"
    assert panels_by_title["Process Memory Usage"]["fieldConfig"]["defaults"]["unit"] == "mebibytes"
    assert panels_by_title["Application Error Rate"]["fieldConfig"]["defaults"]["noValue"] == "No Data"
    for title in ("Container Restarts", "Container Health / Status"):
        assert panels_by_title[title]["targets"] == []
        assert "No Data" == panels_by_title[title]["fieldConfig"]["defaults"]["noValue"]
    assert "transitions" in panels_by_title["Incidents by Lifecycle Status"]["description"].lower()
    assert "not current incident" in panels_by_title["Incidents by Lifecycle Status"]["description"].lower()
    assert len({panel["id"] for panel in panels}) == len(panels)


def test_prometheus_alert_rules_are_configured_and_cover_required_conditions():
    prom_cfg = yaml.safe_load((ROOT / "prometheus.yml").read_text(encoding="utf-8"))
    assert "/etc/prometheus/alert_rules.yml" in prom_cfg["rule_files"]

    rules_doc = yaml.safe_load(
        (ROOT / "prometheus" / "alert_rules.yml").read_text(encoding="utf-8")
    )
    rules_by_name = {
        rule["alert"]: rule
        for group in rules_doc["groups"]
        for rule in group["rules"]
    }
    expected_alerts = {
        "BackendUnavailable",
        "PrometheusScrapeFailure",
        "ElevatedHttpErrorRate",
        "HighApiLatencyP95",
        "AgentExecutionFailures",
        "LlmTimeoutOrFailureRate",
        "ServiceTargetUnavailableOrRestarting",
    }
    assert expected_alerts == set(rules_by_name)
    for name in expected_alerts:
        rule = rules_by_name[name]
        assert rule.get("expr")
        assert rule.get("for")
        assert rule["labels"].get("severity") in {"warning", "critical"}
        assert rule["labels"].get("component")
        assert rule["annotations"].get("summary")
        assert rule["annotations"].get("description")


def test_alert_rules_reference_only_exported_or_builtin_prometheus_metrics():
    import re
    from fastapi.testclient import TestClient
    from calculator_app.app import app

    with TestClient(app) as client:
        client.get("/calc/add?a=1&b=2")
        exposition = client.get("/metrics").text

    exported_metrics = set(
        re.findall(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{| )", exposition, flags=re.M)
    ) | set(
        re.findall(r"^# TYPE ([a-zA-Z_:][a-zA-Z0-9_:]*) ", exposition, flags=re.M)
    )
    prometheus_builtin_metrics = {
        "up",
        "scrape_samples_scraped",
        "scrape_duration_seconds",
        "process_start_time_seconds",
    }
    allowed_metrics = exported_metrics | prometheus_builtin_metrics

    rules_doc = yaml.safe_load(
        (ROOT / "prometheus" / "alert_rules.yml").read_text(encoding="utf-8")
    )
    promql_keywords = {
        "sum",
        "by",
        "rate",
        "increase",
        "histogram_quantile",
        "clamp_min",
        "changes",
        "and",
        "or",
        "le",
        "job",
        "status",
        "endpoint",
        "agent",
    }
    for group in rules_doc["groups"]:
        for rule in group["rules"]:
            expr = re.sub(r"\{[^}]*\}", "", rule["expr"])
            expr = re.sub(r'"[^"]*"', '""', expr)
            expr = re.sub(r"\[[0-9]+[smhd]\]", "", expr)
            identifiers = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr))
            metric_refs = identifiers - promql_keywords
            missing = metric_refs - allowed_metrics
            assert not missing, (
                f"Alert {rule['alert']} references unexported metrics: {missing}"
            )


def test_compose_provisions_grafana_with_local_binding_and_persistent_storage():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    grafana = compose["services"]["grafana"]
    prometheus = compose["services"]["prometheus"]

    assert grafana["image"].startswith("grafana/grafana:")
    assert grafana["ports"] == ["127.0.0.1:3000:3000"]
    assert grafana["depends_on"]["prometheus"]["condition"] == "service_started"
    assert "GF_SECURITY_ADMIN_USER" in grafana["environment"]
    assert "GF_SECURITY_ADMIN_PASSWORD" in grafana["environment"]
    assert any("grafana_data:/var/lib/grafana" in volume for volume in grafana["volumes"])
    assert "grafana_data" in compose["volumes"]
    assert any("provisioning" in volume for volume in grafana["volumes"])
    assert any("dashboards" in volume for volume in grafana["volumes"])
    assert any("alert_rules.yml" in volume for volume in prometheus["volumes"])


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
