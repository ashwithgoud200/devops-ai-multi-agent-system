"""Unit tests for Memory & Knowledge Layer (Box 5): Vector DB, SRE Runbooks, and Knowledge Graph."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.knowledge_graph import DevOpsKnowledgeGraph, get_knowledge_graph
from agents.rag_engine import RagEngine, get_rag_engine
from agents.vector_memory import VectorMemoryStore, get_vector_memory
from calculator_app.app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def memory_store() -> VectorMemoryStore:
    store = get_vector_memory()
    store.rebuild_index()
    return store


def test_vector_memory_store_indexes_sre_runbooks(memory_store: VectorMemoryStore):
    stats = memory_store.get_stats()
    assert stats["runbooks_indexed"] >= 5
    assert stats["total_documents"] >= 5
    runbooks = memory_store.list_runbooks()
    ids = [rb["id"] for rb in runbooks]
    assert "SRE" in ids or any("SRE" in i for i in ids)


def test_vector_search_zero_division_query(memory_store: VectorMemoryStore):
    results = memory_store.search("division by zero crash error in div handler", top_k=2)
    assert len(results) >= 1
    top_result = results[0]
    assert top_result["similarity_score"] > 0.15
    # Should match either SRE-101 (regression) or SRE-102 (zero division)
    assert any(term in top_result["title"].lower() or term in top_result["summary"].lower() for term in ("division", "regression", "crash"))


def test_vector_search_latency_query(memory_store: VectorMemoryStore):
    results = memory_store.search("95th percentile latency drift degradation slow response", top_k=2)
    assert len(results) >= 1
    top_result = results[0]
    assert top_result["similarity_score"] > 0.15
    assert "latency" in top_result["title"].lower() or "performance" in top_result["title"].lower()


def test_vector_search_security_query(memory_store: VectorMemoryStore):
    results = memory_store.search("critical vulnerability CVE in dependencies pip audit trivy scan", top_k=2)
    assert len(results) >= 1
    top_result = results[0]
    assert top_result["similarity_score"] > 0.15
    assert "security" in top_result["title"].lower() or "vulnerability" in top_result["title"].lower()


def test_knowledge_graph_structure():
    kg = get_knowledge_graph()
    graph = kg.get_graph()
    assert graph["total_nodes"] >= 5
    assert graph["total_edges"] >= 5

    # Test calculator-app dependencies
    deps = kg.get_service_dependencies("calculator-app")
    assert "prometheus" in deps["downstream_consumers"]
    assert "loki" in deps["upstream_dependencies"] or "tempo" in deps["upstream_dependencies"]

    # Test blast radius
    impact = kg.analyze_change_impact("calculator-app")
    assert impact["blast_radius"] == "High"
    assert impact["impacted_services_count"] >= 2


def test_rag_engine_retrieval():
    rag = get_rag_engine()
    ctx = rag.retrieve_grounded_context("Investigate calculator crash after release", target_service="calculator-app")
    assert ctx["has_relevant_knowledge"] is True
    assert len(ctx["matching_runbooks"]) >= 1
    assert "### SRE RUNBOOK & EPISODIC MEMORY CONTEXT" in ctx["formatted_prompt_context"]
    assert len(ctx["citations"]) >= 1
    assert ctx["knowledge_graph"]["impact"]["blast_radius"] == "High"


def test_memory_api_endpoints(client: TestClient):
    # 1. Status endpoint
    status_resp = client.get("/memory/status")
    assert status_resp.status_code == 200
    s_data = status_resp.json()
    assert s_data["vector_database"]["runbooks_indexed"] >= 5
    assert s_data["knowledge_graph"]["total_nodes"] >= 5

    # 2. Runbooks list
    rb_resp = client.get("/memory/runbooks")
    assert rb_resp.status_code == 200
    rbs = rb_resp.json()
    assert len(rbs) >= 5

    # 3. Specific runbook detail
    first_id = rbs[0]["id"]
    detail_resp = client.get(f"/memory/runbooks/{first_id}")
    assert detail_resp.status_code == 200
    assert "full_content" in detail_resp.json()

    # 4. Semantic search endpoint
    search_resp = client.post("/memory/search", json={"query": "elevated HTTP 500 error on division", "top_k": 2})
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert search_data["has_relevant_knowledge"] is True
    assert len(search_data["matching_runbooks"]) >= 1

    # 5. Knowledge Graph endpoint
    graph_resp = client.get("/memory/graph")
    assert graph_resp.status_code == 200
    assert len(graph_resp.json()["nodes"]) >= 5

