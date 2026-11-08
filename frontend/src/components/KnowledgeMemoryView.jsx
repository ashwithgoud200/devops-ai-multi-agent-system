import { useEffect, useState } from "react";
import {
  getMemoryStatus,
  listRunbooks,
  getRunbookDetail,
  searchMemory,
  getMemoryGraph,
} from "../api.js";
import Icon from "./Icon.jsx";

export default function KnowledgeMemoryView() {
  const [activeTab, setActiveTab] = useState("search");
  const [status, setStatus] = useState(null);
  const [runbooks, setRunbooks] = useState([]);
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Search tab state
  const [searchQuery, setSearchQuery] = useState("division by zero crash error");
  const [searchResults, setSearchResults] = useState(null);
  const [searching, setSearching] = useState(false);

  // Selected runbook detail view
  const [selectedRunbook, setSelectedRunbook] = useState(null);
  const [loadingRunbook, setLoadingRunbook] = useState(false);

  const loadInitialData = async () => {
    setLoading(true);
    setError("");
    try {
      const [statRes, rbRes, graphRes] = await Promise.all([
        getMemoryStatus(),
        listRunbooks(),
        getMemoryGraph(),
      ]);
      setStatus(statRes);
      setRunbooks(rbRes || []);
      setGraphData(graphRes);

      // Perform default search
      const defSearch = await searchMemory("division by zero crash error", 3);
      setSearchResults(defSearch);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load memory store.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadInitialData();
  }, []);

  const handleSearch = async (e) => {
    if (e) e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setError("");
    try {
      const res = await searchMemory(searchQuery.trim(), 3);
      setSearchResults(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setSearching(false);
    }
  };

  const handleSelectRunbook = async (id) => {
    setLoadingRunbook(true);
    try {
      const detail = await getRunbookDetail(id);
      setSelectedRunbook(detail);
      setActiveTab("runbooks");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load runbook details.");
    } finally {
      setLoadingRunbook(false);
    }
  };

  if (loading) {
    return (
      <div className="panel loading-panel">
        <span className="button-spinner" /> Loading Memory &amp; Knowledge Layer (Box 5)...
      </div>
    );
  }

  const vStats = status?.vector_database || {};
  const gStats = status?.knowledge_graph || {};

  return (
    <div className="memory-view-container">
      {/* Top Banner */}
      <section className="panel memory-hero-panel">
        <div className="memory-hero-badge">
          <span className="badge-dot" />
          <span>BOX 5 &middot; MEMORY &amp; KNOWLEDGE LAYER (RAG)</span>
        </div>
        <h2>DevOps Memory &amp; SRE Knowledge Base</h2>
        <p>
          Authoritative operational knowledge layer for the 6 specialized AI agents. Provides
          <strong> semantic vector search over SRE runbooks</strong>, <strong>episodic memory of past incidents</strong>,
          and a <strong>service relationship knowledge graph</strong> for blast-radius impact analysis.
        </p>

        {/* 4 Stat Badges */}
        <div className="memory-stats-grid">
          <div className="mem-stat-card">
            <span className="mem-stat-label">SRE Runbooks Indexed</span>
            <strong className="mem-stat-val text-green">{vStats.runbooks_indexed || runbooks.length}</strong>
            <small>Authoritative Playbooks</small>
          </div>

          <div className="mem-stat-card">
            <span className="mem-stat-label">Episodic Memories</span>
            <strong className="mem-stat-val text-blue">{vStats.past_incidents_indexed || 0}</strong>
            <small>Past Resolved Incidents</small>
          </div>

          <div className="mem-stat-card">
            <span className="mem-stat-label">Knowledge Graph</span>
            <strong className="mem-stat-val text-purple">{gStats.total_nodes || 7} Nodes</strong>
            <small>{gStats.total_edges || 8} Dependency Edges</small>
          </div>

          <div className="mem-stat-card">
            <span className="mem-stat-label">Vector Store Engine</span>
            <strong className="mem-stat-val text-amber">Local Subword Cosine</strong>
            <small>Loopback 127.0.0.1 (Fast &amp; Private)</small>
          </div>
        </div>
      </section>

      {error && (
        <div className="global-error" role="alert">
          {error}
          <button onClick={() => setError("")}>Dismiss</button>
        </div>
      )}

      {/* Navigation Sub-Tabs */}
      <div className="memory-tabs-nav">
        <button
          type="button"
          className={`mem-tab-btn ${activeTab === "search" ? "active" : ""}`}
          onClick={() => setActiveTab("search")}
        >
          <Icon name="telemetry" size={16} />
          Semantic Vector Search (RAG Tester)
        </button>
        <button
          type="button"
          className={`mem-tab-btn ${activeTab === "runbooks" ? "active" : ""}`}
          onClick={() => setActiveTab("runbooks")}
        >
          <Icon name="book" size={16} />
          SRE Runbooks Library ({runbooks.length})
        </button>
        <button
          type="button"
          className={`mem-tab-btn ${activeTab === "graph" ? "active" : ""}`}
          onClick={() => setActiveTab("graph")}
        >
          <Icon name="git" size={16} />
          Service Knowledge Graph
        </button>
      </div>

      {/* TAB 1: SEMANTIC VECTOR SEARCH (RAG TESTER) */}
      {activeTab === "search" && (
        <section className="panel memory-search-panel">
          <div className="search-header">
            <h3>Test Semantic Runbook Retrieval</h3>
            <p className="panel-subtitle">
              Enter any incident symptom or question to see which SRE playbooks and past episodes are retrieved for the AI agents.
            </p>
          </div>

          <form onSubmit={handleSearch} className="mem-search-form">
            <div className="search-input-wrap">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="e.g. division by zero, elevated HTTP 500 latency spike, trivy vulnerability"
                required
              />
              <button type="submit" className="button button-primary" disabled={searching}>
                {searching ? "Searching..." : "Vector Search"}
              </button>
            </div>
            <div className="quick-search-queries">
              <span className="quick-label">Sample Incident Queries:</span>
              <button
                type="button"
                className="quick-query-btn"
                onClick={() => {
                  setSearchQuery("division by zero crash error in div handler");
                  searchMemory("division by zero crash error in div handler", 3).then(setSearchResults);
                }}
              >
                Zero Division (SRE-102)
              </button>
              <button
                type="button"
                className="quick-query-btn"
                onClick={() => {
                  setSearchQuery("elevated 95th percentile latency drift slow calculator response");
                  searchMemory("elevated 95th percentile latency drift slow calculator response", 3).then(setSearchResults);
                }}
              >
                Latency Drift (SRE-103)
              </button>
              <button
                type="button"
                className="quick-query-btn"
                onClick={() => {
                  setSearchQuery("container infrastructure pressure degraded healthcheck failure");
                  searchMemory("container infrastructure pressure degraded healthcheck failure", 3).then(setSearchResults);
                }}
              >
                Infra Failure (SRE-104)
              </button>
              <button
                type="button"
                className="quick-query-btn"
                onClick={() => {
                  setSearchQuery("critical vulnerability CVE in dependencies pip audit trivy");
                  searchMemory("critical vulnerability CVE in dependencies pip audit trivy", 3).then(setSearchResults);
                }}
              >
                Security CVE (SRE-105)
              </button>
            </div>
          </form>

          {/* Search Results Display */}
          {searchResults && (
            <div className="search-results-area">
              <div className="results-meta-bar">
                <span className="results-count">
                  Retrieved {searchResults.matching_runbooks?.length || 0} Playbooks &middot; Blast Radius:{" "}
                  <strong className="text-amber">{searchResults.knowledge_graph?.impact?.blast_radius || "Medium"}</strong>
                </span>
                <span className="grounded-badge">
                  {searchResults.has_relevant_knowledge ? "✓ Grounded Knowledge Found" : "Low Similarity"}
                </span>
              </div>

              {/* Matched Runbooks List */}
              <div className="matched-runbooks-list">
                {searchResults.matching_runbooks?.map((rb) => (
                  <div key={rb.id} className="matched-runbook-card">
                    <div className="rb-card-top">
                      <div className="rb-id-group">
                        <span className="rb-tag">{rb.id}</span>
                        <h4>{rb.title}</h4>
                      </div>
                      <div className="rb-score-wrap">
                        <span className="similarity-pill">
                          {(rb.similarity_score * 100).toFixed(1)}% Match
                        </span>
                        <button
                          type="button"
                          className="button button-sm button-outline"
                          onClick={() => handleSelectRunbook(rb.id)}
                        >
                          View Playbook &rarr;
                        </button>
                      </div>
                    </div>
                    <p className="rb-summary">{rb.summary}</p>
                    <div className="rb-snippet-box">
                      <pre>{rb.content_snippet}</pre>
                    </div>
                  </div>
                ))}
              </div>

              {/* Formatted Markdown Context Preview */}
              <div className="prompt-preview-box">
                <div className="prompt-preview-header">
                  <Icon name="code" size={16} />
                  <span>Agent Prompt Context Preview (Injected into LLM)</span>
                </div>
                <pre className="prompt-preview-code">
                  {searchResults.formatted_prompt_context}
                </pre>
              </div>
            </div>
          )}
        </section>
      )}

      {/* TAB 2: SRE RUNBOOKS LIBRARY */}
      {activeTab === "runbooks" && (
        <section className="panel memory-runbooks-panel">
          <div className="runbooks-header">
            <div>
              <h3>Authoritative SRE Playbook Library</h3>
              <p className="panel-subtitle">
                Official runbooks indexed into the Vector DB. These guide the autonomous Incident and Remediation agents.
              </p>
            </div>
          </div>

          {selectedRunbook ? (
            <div className="runbook-detail-view">
              <div className="detail-top-bar">
                <button
                  type="button"
                  className="button button-outline"
                  onClick={() => setSelectedRunbook(null)}
                >
                  &larr; Back to Runbooks Library
                </button>
                <span className="pill pill-green">{selectedRunbook.category}</span>
              </div>
              <div className="runbook-full-content">
                <pre className="markdown-render-pre">{selectedRunbook.full_content}</pre>
              </div>
            </div>
          ) : (
            <div className="runbooks-grid">
              {runbooks.map((rb) => (
                <div key={rb.id} className="runbook-summary-card">
                  <div className="rb-header">
                    <span className="rb-id-badge">{rb.id}</span>
                    <span className={`pill ${rb.severity === "critical" ? "pill-danger" : "pill-amber"}`}>
                      {rb.severity.toUpperCase()}
                    </span>
                  </div>
                  <h4>{rb.title}</h4>
                  <p>{rb.summary}</p>
                  <div className="rb-card-footer">
                    <span className="rb-category">{rb.category}</span>
                    <button
                      type="button"
                      className="button button-sm button-primary"
                      onClick={() => handleSelectRunbook(rb.id)}
                    >
                      Read Playbook
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* TAB 3: KNOWLEDGE GRAPH TOPOLOGY */}
      {activeTab === "graph" && (
        <section className="panel memory-graph-panel">
          <div className="graph-header">
            <div>
              <h3>Service Relationship Knowledge Graph</h3>
              <p className="panel-subtitle">
                Deterministic mapping of microservice dependencies, observability links, and telemetry data flows.
              </p>
            </div>
          </div>

          <div className="graph-cards-grid">
            {graphData?.nodes?.map((node) => (
              <div key={node.id} className="graph-node-card">
                <div className="node-card-top">
                  <span className={`node-tier-pill tier-${node.tier}`}>
                    {node.tier}
                  </span>
                  <span className="node-type">{node.type}</span>
                </div>
                <h4>{node.name}</h4>
                <p>{node.description}</p>
                {node.ports && (
                  <div className="node-ports">
                    <span>Ports:</span> <code>{node.ports.join(", ")}</code>
                  </div>
                )}
                {node.health_endpoint && (
                  <div className="node-health">
                    <small>{node.health_endpoint}</small>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="graph-edges-table-card">
            <h4>Knowledge Graph Dependency Edges</h4>
            <div className="table-responsive">
              <table className="graph-table">
                <thead>
                  <tr>
                    <th>Source Node</th>
                    <th>Relationship</th>
                    <th>Target Node</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {graphData?.edges?.map((edge, idx) => (
                    <tr key={idx}>
                      <td><strong>{edge.source}</strong></td>
                      <td><span className="edge-relation-pill">{edge.relation}</span></td>
                      <td><strong>{edge.target}</strong></td>
                      <td>{edge.desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

