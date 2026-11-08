"""HTTP API for Memory & Knowledge Layer (Box 5): Vector DB, SRE Runbooks, and Knowledge Graph."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agents.knowledge_graph import get_knowledge_graph
from agents.rag_engine import get_rag_engine
from agents.vector_memory import get_vector_memory

router = APIRouter(prefix="/memory", tags=["memory and knowledge layer"])


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=10)
    doc_type: str | None = None


@router.get("/status", summary="Get Memory & Knowledge Layer status and stats")
def get_memory_status() -> dict[str, Any]:
    """Return counts of indexed SRE runbooks, episodic incident memories, and graph nodes."""
    vector_store = get_vector_memory()
    kg = get_knowledge_graph()
    stats = vector_store.get_stats()
    graph_data = kg.get_graph()

    return {
        "status": "ready",
        "vector_database": {
            "total_documents": stats["total_documents"],
            "runbooks_indexed": stats["runbooks_indexed"],
            "past_incidents_indexed": stats["past_incidents_indexed"],
            "indexed_at": stats["indexed_at"],
            "store_path": stats["store_path"],
        },
        "knowledge_graph": {
            "total_nodes": graph_data["total_nodes"],
            "total_edges": graph_data["total_edges"],
        },
    }


@router.get("/runbooks", summary="List all indexed SRE runbooks")
def list_runbooks() -> list[dict[str, Any]]:
    """Return all authoritative SRE runbooks available to agents."""
    vector_store = get_vector_memory()
    return vector_store.list_runbooks()


@router.get("/runbooks/{runbook_id}", summary="Get full markdown content of an SRE runbook")
def get_runbook_detail(runbook_id: str) -> dict[str, Any]:
    """Return full markdown playbook content by ID."""
    vector_store = get_vector_memory()
    clean_id = runbook_id.strip().upper()
    for doc in vector_store.documents:
        if doc.get("type") == "runbook" and doc.get("id") == clean_id:
            return {
                "id": doc["id"],
                "title": doc["title"],
                "category": doc["category"],
                "severity": doc["severity"],
                "service": doc["service"],
                "summary": doc["summary"],
                "full_content": doc["content"],
            }
    raise HTTPException(status_code=404, detail=f"Runbook {clean_id} not found.")


@router.post("/search", summary="Perform semantic vector search over SRE runbooks and past incidents")
def search_memory(request: MemorySearchRequest) -> dict[str, Any]:
    """Search SRE playbooks and past incident episodes using vector similarity."""
    rag = get_rag_engine()
    context = rag.retrieve_grounded_context(
        query=request.query,
        target_service="calculator-app",
        top_k=request.top_k,
    )
    return context


@router.get("/graph", summary="Get service relationship knowledge graph")
def get_knowledge_graph_data() -> dict[str, Any]:
    """Return service nodes and directed dependency edges."""
    kg = get_knowledge_graph()
    return kg.get_graph()


@router.post("/reindex", summary="Re-index runbooks and episodic memory from disk")
def trigger_reindex() -> dict[str, Any]:
    """Reload all SRE runbooks and parse latest audit log episodes."""
    vector_store = get_vector_memory()
    vector_store.rebuild_index()
    return get_memory_status()

