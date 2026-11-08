"""Knowledge Graph for Service Relationships, Infrastructure Topology, and Change Impact (Box 5).

Provides deterministic graph traversal of microservice dependencies, observability links,
and blast-radius impact analysis.
"""
from __future__ import annotations

from typing import Any


class DevOpsKnowledgeGraph:
    """In-memory Knowledge Graph of service relationships, data flows, and infrastructure dependencies."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {
            "calculator-app": {
                "id": "calculator-app",
                "name": "Calculator Service",
                "type": "microservice",
                "tier": "backend",
                "ports": [8100],
                "health_endpoint": "http://127.0.0.1:8100/health",
                "description": "Core arithmetic API with live telemetry and admin controls.",
            },
            "frontend": {
                "id": "frontend",
                "name": "OpsPilot Dashboard",
                "type": "web_ui",
                "tier": "presentation",
                "ports": [5173, 4173],
                "health_endpoint": "http://127.0.0.1:5173",
                "description": "React control center with incident triage, topologies, and ChatOps.",
            },
            "prometheus": {
                "id": "prometheus",
                "name": "Prometheus Monitoring",
                "type": "observability",
                "tier": "telemetry",
                "ports": [9090],
                "health_endpoint": "http://127.0.0.1:9090/-/healthy",
                "description": "Time-series database scraping application counters and latency histograms.",
            },
            "grafana": {
                "id": "grafana",
                "name": "Grafana Dashboards",
                "type": "visualization",
                "tier": "presentation",
                "ports": [3000],
                "health_endpoint": "http://127.0.0.1:3000/api/health",
                "description": "Unified metrics, logs, and trace visualization dashboards.",
            },
            "loki": {
                "id": "loki",
                "name": "Grafana Loki",
                "type": "observability",
                "tier": "telemetry",
                "ports": [3100],
                "health_endpoint": "http://127.0.0.1:3100/ready",
                "description": "Log aggregation engine ingesting structured JSON application logs.",
            },
            "tempo": {
                "id": "tempo",
                "name": "Grafana Tempo",
                "type": "observability",
                "tier": "telemetry",
                "ports": [3200, 4318],
                "health_endpoint": "http://127.0.0.1:3200/ready",
                "description": "High-volume distributed tracing backend ingesting OTLP spans.",
            },
            "github-repo": {
                "id": "github-repo",
                "name": "Code-Agent Repository",
                "type": "version_control",
                "tier": "pipeline",
                "repo": "ashwithgoud200/Code-Agent",
                "description": "GitHub target repository for Code Agent PRs and CI/CD workflows.",
            },
        }

        # Directed relationship edges: (source, relation, target, description)
        self.edges: list[dict[str, str]] = [
            {"source": "frontend", "relation": "proxies_to", "target": "calculator-app", "desc": "API proxy for user queries and admin actions"},
            {"source": "prometheus", "relation": "scrapes_metrics", "target": "calculator-app", "desc": "Scrapes /metrics on 15s interval"},
            {"source": "calculator-app", "relation": "ships_logs_to", "target": "loki", "desc": "Asynchronously ships JSON logs to /loki/api/v1/push"},
            {"source": "calculator-app", "relation": "ships_traces_to", "target": "tempo", "desc": "Ships OTLP spans to /v1/traces via port 4318"},
            {"source": "grafana", "relation": "queries_datasource", "target": "prometheus", "desc": "PromQL metrics visualization"},
            {"source": "grafana", "relation": "queries_datasource", "target": "loki", "desc": "LogQL log exploration"},
            {"source": "grafana", "relation": "queries_datasource", "target": "tempo", "desc": "TraceQL distributed trace inspection"},
            {"source": "calculator-app", "relation": "version_controlled_by", "target": "github-repo", "desc": "Target repo for patches and CI matrix tests"},
        ]

    def get_graph(self) -> dict[str, Any]:
        """Return the complete Knowledge Graph nodes and edges."""
        return {
            "nodes": list(self.nodes.values()),
            "edges": self.edges,
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
        }

    def get_service_dependencies(self, service_id: str) -> dict[str, Any]:
        """Return upstream dependencies and downstream consumers for a service."""
        upstream = [e["target"] for e in self.edges if e["source"] == service_id]
        downstream = [e["source"] for e in self.edges if e["target"] == service_id]
        return {
            "service_id": service_id,
            "upstream_dependencies": upstream,
            "downstream_consumers": downstream,
        }

    def analyze_change_impact(self, service_id: str) -> dict[str, Any]:
        """Perform change impact analysis (blast radius) if a service is modified or degraded."""
        impacted_downstream = []
        for e in self.edges:
            if e["target"] == service_id:
                impacted_downstream.append({
                    "service": e["source"],
                    "relationship": e["relation"],
                    "risk": "High" if e["source"] == "frontend" else "Medium",
                    "impact": f"May experience degraded functionality or missing telemetry if {service_id} restarts.",
                })

        return {
            "target_service": service_id,
            "blast_radius": "High" if len(impacted_downstream) >= 2 else "Low",
            "impacted_services_count": len(impacted_downstream),
            "impact_details": impacted_downstream,
        }


_KNOWLEDGE_GRAPH = DevOpsKnowledgeGraph()


def get_knowledge_graph() -> DevOpsKnowledgeGraph:
    return _KNOWLEDGE_GRAPH

