"""RAG Engine for Knowledge Retrieval and Agent Context Augmentation (Box 5).

Fetches relevant SRE runbooks, queries episodic memory of past incidents,
extracts service topology from the Knowledge Graph, and formats grounded citations
for specialist AI agents.
"""
from __future__ import annotations

from typing import Any

from agents.knowledge_graph import get_knowledge_graph
from agents.vector_memory import get_vector_memory


class RagEngine:
    """Retrieves relevant DevOps knowledge and builds grounded citations for LLM agents."""

    def __init__(self) -> None:
        self.vector_store = get_vector_memory()
        self.knowledge_graph = get_knowledge_graph()

    def retrieve_grounded_context(
        self,
        query: str,
        target_service: str = "calculator-app",
        top_k: int = 2,
    ) -> dict[str, Any]:
        """Retrieve top runbooks, episodic memories, and graph relationships for an incident query."""
        # 1. Vector Search for SRE Runbooks
        matching_runbooks = self.vector_store.search(
            query=query,
            top_k=top_k,
            doc_type="runbook",
            min_score=0.08,
        )

        # 2. Vector Search for Past Incident Episodes
        past_episodes = self.vector_store.search(
            query=query,
            top_k=2,
            doc_type="incident_episode",
            min_score=0.06,
        )

        # 3. Knowledge Graph Service Relationships
        graph_impact = self.knowledge_graph.analyze_change_impact(target_service)
        graph_deps = self.knowledge_graph.get_service_dependencies(target_service)

        # 4. Build Formatted Markdown Context & Citations for LLM Prompts
        citations: list[dict[str, str]] = []
        prompt_lines: list[str] = [
            "### SRE RUNBOOK & EPISODIC MEMORY CONTEXT (Box 5 RAG)",
            "Use the following authoritative operational knowledge to ground your diagnosis and recommendations:\n",
        ]

        if matching_runbooks:
            prompt_lines.append("#### Authoritative SRE Playbooks:")
            for rb in matching_runbooks:
                citation_tag = f"Runbook {rb['id']}: {rb['title']} (Similarity: {rb['similarity_score']})"
                citations.append({"type": "runbook", "id": rb["id"], "citation": citation_tag})
                prompt_lines.append(f"- **[{rb['id']}] {rb['title']}** (Category: {rb['category']})")
                prompt_lines.append(f"  Summary: {rb['summary']}")
                prompt_lines.append(f"  Playbook Guidance:\n  {rb['content_snippet']}\n")
        else:
            prompt_lines.append("No specific SRE runbook matched with high similarity.\n")

        if past_episodes:
            prompt_lines.append("#### Episodic Memory (Past Resolved Incidents):")
            for ep in past_episodes:
                citation_tag = f"Past Incident {ep['id']} (Similarity: {ep['similarity_score']})"
                citations.append({"type": "past_incident", "id": ep["id"], "citation": citation_tag})
                prompt_lines.append(f"- **{ep['title']}**")
                prompt_lines.append(f"  Past Outcome: {ep['summary']}\n")

        prompt_lines.append("#### Knowledge Graph Service Topology:")
        prompt_lines.append(f"- Target Service: `{target_service}` (Blast Radius: {graph_impact.get('blast_radius', 'Medium')})")
        prompt_lines.append(f"- Downstream Consumers: {', '.join(graph_deps.get('downstream_consumers', [])) or 'None'}")
        prompt_lines.append(f"- Upstream Dependencies: {', '.join(graph_deps.get('upstream_dependencies', [])) or 'None'}\n")

        formatted_prompt = "\n".join(prompt_lines)

        return {
            "query": query,
            "target_service": target_service,
            "has_relevant_knowledge": bool(matching_runbooks or past_episodes),
            "citations": citations,
            "matching_runbooks": matching_runbooks,
            "past_episodes": past_episodes,
            "knowledge_graph": {
                "impact": graph_impact,
                "dependencies": graph_deps,
            },
            "formatted_prompt_context": formatted_prompt,
        }


_RAG_ENGINE = RagEngine()


def get_rag_engine() -> RagEngine:
    return _RAG_ENGINE

