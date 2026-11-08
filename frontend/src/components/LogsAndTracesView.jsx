import { useCallback, useEffect, useState } from "react";
import Icon from "./Icon.jsx";
import StatusCard from "./StatusCard.jsx";
import { getLokiTelemetry, getTempoTelemetry, getTraceDetails } from "../api.js";

export default function LogsAndTracesView({ integrations }) {
  const [activeTab, setActiveTab] = useState("logs"); // "logs" | "traces"
  
  // Loki logs state
  const [logQuery, setLogQuery] = useState('{service_name="calculator-app"}');
  const [logLevel, setLogLevel] = useState("ALL");
  const [logSince, setLogSince] = useState("1h");
  const [logData, setLogData] = useState(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logError, setLogError] = useState("");
  const [expandedLogIdx, setExpandedLogIdx] = useState(null);

  // Tempo traces state
  const [tracesData, setTracesData] = useState(null);
  const [tracesLoading, setTracesLoading] = useState(false);
  const [traceError, setTraceError] = useState("");
  const [selectedTraceId, setSelectedTraceId] = useState(null);
  const [traceDetail, setTraceDetail] = useState(null);
  const [traceDetailLoading, setTraceDetailLoading] = useState(false);

  const lokiStatus = integrations?.loki || { status: "offline", healthy: false };
  const tempoStatus = integrations?.tempo || { status: "offline", healthy: false };

  // Fetch Loki logs
  const fetchLogs = useCallback(async (queryOverride) => {
    setLogsLoading(true);
    setLogError("");
    try {
      const q = queryOverride !== undefined ? queryOverride : logQuery;
      const res = await getLokiTelemetry(q, 100, logSince);
      setLogData(res);
    } catch (err) {
      setLogError(err instanceof Error ? err.message : "Failed to load Loki logs");
    } finally {
      setLogsLoading(false);
    }
  }, [logQuery, logSince]);

  // Fetch Tempo traces
  const fetchTraces = useCallback(async () => {
    setTracesLoading(true);
    setTraceError("");
    try {
      const res = await getTempoTelemetry(50, "calculator-app");
      setTracesData(res);
    } catch (err) {
      setTraceError(err instanceof Error ? err.message : "Failed to load Tempo traces");
    } finally {
      setTracesLoading(false);
    }
  }, []);

  // Fetch specific trace detail
  const selectTrace = useCallback(async (traceId) => {
    setSelectedTraceId(traceId);
    setTraceDetailLoading(true);
    try {
      const res = await getTraceDetails(traceId);
      setTraceDetail(res);
    } catch {
      setTraceDetail(null);
    } finally {
      setTraceDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLogs();
    fetchTraces();
  }, [fetchLogs, fetchTraces]);

  // Filter logs by level
  const displayedLogs = (logData?.entries || []).filter((entry) => {
    if (logLevel === "ALL") return true;
    return (entry.level || "INFO").toUpperCase() === logLevel;
  });

  // Jump from log to trace
  const handleTraceClick = (traceId) => {
    if (!traceId) return;
    setActiveTab("traces");
    selectTrace(traceId);
  };

  // Jump from trace to logs
  const handleLogsForTrace = (traceId) => {
    if (!traceId) return;
    setActiveTab("logs");
    const newQuery = `{service_name="calculator-app"} |= "${traceId}"`;
    setLogQuery(newQuery);
    fetchLogs(newQuery);
  };

  return (
    <div className="telemetry-view">
      {/* 1. Observability Health Header */}
      <div className="status-grid">
        <StatusCard
          label="Loki Log Aggregator"
          value={lokiStatus.healthy ? "Healthy" : lokiStatus.status === "online" ? "Online" : "Fallback (Local)"}
          detail={`Port 3100 · ${logData?.source === "loki" ? "Streaming from Loki" : "Serving local application logs"}`}
          icon="◉"
          tone={lokiStatus.healthy || logData?.source === "loki" ? "green" : "neutral"}
        />
        <StatusCard
          label="Tempo Distributed Tracing"
          value={tempoStatus.healthy ? "Healthy" : tempoStatus.status === "online" ? "Online" : "In-Memory Buffer"}
          detail={`Port 3200 (OTLP: 4318) · ${tracesData?.traces?.length || 0} traces tracked`}
          icon="↗"
          tone={tempoStatus.healthy || tempoStatus.status === "online" ? "green" : "blue"}
        />
        <StatusCard
          label="Total Logs Ingested"
          value={logData?.total_entries != null ? logData.total_entries.toLocaleString() : "0"}
          detail={`Filtered view: ${displayedLogs.length} logs`}
          icon="✓"
          tone="neutral"
        />
        <StatusCard
          label="Traces Available"
          value={tracesData?.total_traces != null ? tracesData.total_traces.toLocaleString() : "0"}
          detail="W3C TraceContext Propagation"
          icon="!"
          tone={tracesData?.traces?.some((t) => t.status_code >= 500) ? "amber" : "neutral"}
        />
      </div>

      {/* 2. Navigation Tabs & Quick Links */}
      <div className="telemetry-tabs-bar">
        <div className="telemetry-tab-buttons">
          <button
            className={`button ${activeTab === "logs" ? "button-primary" : "button-secondary"}`}
            onClick={() => setActiveTab("logs")}
          >
            Loki Logs ({displayedLogs.length})
          </button>
          <button
            className={`button ${activeTab === "traces" ? "button-primary" : "button-secondary"}`}
            onClick={() => setActiveTab("traces")}
          >
            Tempo Traces ({tracesData?.traces?.length || 0})
          </button>
        </div>
        <div className="telemetry-external-links">
          <a
            href="http://127.0.0.1:3000/explore"
            target="_blank"
            rel="noreferrer"
            className="link-button"
          >
            Explore in Grafana <Icon name="arrow" size={14} />
          </a>
        </div>
      </div>

      {/* 3. Tab Content */}
      {activeTab === "logs" ? (
        <section className="panel telemetry-panel">
          <div className="telemetry-controls">
            <div className="telemetry-query-box">
              <label htmlFor="logql-input">LogQL Query</label>
              <div className="query-input-row">
                <input
                  id="logql-input"
                  className="code-input"
                  value={logQuery}
                  onChange={(e) => setLogQuery(e.target.value)}
                  placeholder='{service_name="calculator-app"}'
                />
                <button
                  className="button button-primary"
                  onClick={() => fetchLogs()}
                  disabled={logsLoading}
                >
                  {logsLoading ? "Querying..." : "Execute"}
                </button>
              </div>
            </div>

            <div className="telemetry-filter-row">
              <div className="filter-group">
                <span className="filter-label">Level:</span>
                {["ALL", "INFO", "WARNING", "ERROR"].map((lvl) => (
                  <button
                    key={lvl}
                    className={`pill-button ${logLevel === lvl ? "active" : ""}`}
                    onClick={() => setLogLevel(lvl)}
                  >
                    {lvl}
                  </button>
                ))}
              </div>
              <div className="filter-group">
                <span className="filter-label">Time:</span>
                {["15m", "1h", "6h", "24h"].map((s) => (
                  <button
                    key={s}
                    className={`pill-button ${logSince === s ? "active" : ""}`}
                    onClick={() => setLogSince(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <div className="source-badge">
                Source: <strong>{logData?.source || "unknown"}</strong>
              </div>
            </div>
          </div>

          {logError && <div className="form-error" role="alert">{logError}</div>}

          {/* Logs List */}
          <div className="logs-stream-container">
            {displayedLogs.length === 0 ? (
              <div className="inline-empty">
                <span className="empty-dot" />
                {logsLoading ? "Loading logs from Loki / disk..." : "No log entries found for the selected query and filters."}
              </div>
            ) : (
              <div className="logs-table">
                {displayedLogs.map((entry, index) => {
                  const isExpanded = expandedLogIdx === index;
                  const lvl = (entry.level || "INFO").toUpperCase();
                  const isErr = lvl === "ERROR" || lvl === "CRITICAL";
                  const isWarn = lvl === "WARNING" || lvl === "WARN";

                  return (
                    <div
                      key={index}
                      className={`log-entry-row ${isExpanded ? "expanded" : ""} ${isErr ? "level-error" : isWarn ? "level-warn" : ""}`}
                    >
                      <div className="log-row-header" onClick={() => setExpandedLogIdx(isExpanded ? null : index)}>
                        <span className="log-timestamp">
                          {entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : "--:--:--"}
                        </span>
                        <span className={`log-level-badge ${isErr ? "badge-red" : isWarn ? "badge-amber" : "badge-blue"}`}>
                          {lvl}
                        </span>
                        <span className="log-message" title={entry.message}>
                          {entry.message}
                        </span>
                        {entry.trace_id && (
                          <button
                            className="trace-link-pill"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleTraceClick(entry.trace_id);
                            }}
                            title={`Inspect Trace ${entry.trace_id}`}
                          >
                            <span className="pill-dot" /> trace:{entry.trace_id.slice(0, 8)}
                          </button>
                        )}
                        <span className="expand-indicator">{isExpanded ? "▲" : "▼"}</span>
                      </div>

                      {isExpanded && (
                        <div className="log-expanded-details">
                          <div className="log-meta-grid">
                            <div><span className="meta-label">Full Timestamp:</span> <code>{entry.timestamp}</code></div>
                            {entry.trace_id && (
                              <div>
                                <span className="meta-label">Trace ID:</span>{" "}
                                <code>{entry.trace_id}</code>{" "}
                                <button className="small-link-btn" onClick={() => handleTraceClick(entry.trace_id)}>
                                  View Trace Waterfall &rarr;
                                </button>
                              </div>
                            )}
                          </div>
                          <div className="log-raw-box">
                            <span className="meta-label">Raw Record:</span>
                            <pre>{entry.raw || JSON.stringify(entry, null, 2)}</pre>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </section>
      ) : (
        /* TEMPO TRACES TAB */
        <section className="panel telemetry-panel">
          <div className="traces-layout">
            {/* Traces List Table */}
            <div className="traces-list-panel">
              <div className="traces-list-header">
                <h3>Recorded Spans & Traces</h3>
                <div className="traces-header-actions">
                  <span className="source-badge">
                    Source: <strong>{tracesData?.source || "tempo"}</strong>
                  </span>
                  <button className="icon-button" onClick={fetchTraces} disabled={tracesLoading} aria-label="Refresh traces">
                    <Icon name="refresh" className={tracesLoading ? "spin" : ""} size={14} />
                  </button>
                </div>
              </div>

              {traceError && <div className="form-error" role="alert">{traceError}</div>}

              {(!tracesData?.traces || tracesData.traces.length === 0) ? (
                <div className="inline-empty">
                  <span className="empty-dot" />
                  {tracesLoading ? "Loading traces..." : "No traces recorded yet. Make calculator requests to populate traces."}
                </div>
              ) : (
                <div className="traces-table-container">
                  <table className="traces-table">
                    <thead>
                      <tr>
                        <th>Trace ID</th>
                        <th>Endpoint / Root Span</th>
                        <th>Duration</th>
                        <th>Status</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tracesData.traces.map((tr) => {
                        const isSelected = selectedTraceId === tr.trace_id;
                        const isErr = (tr.status_code || 200) >= 400;
                        return (
                          <tr
                            key={tr.trace_id}
                            className={`trace-row ${isSelected ? "selected" : ""} ${isErr ? "row-error" : ""}`}
                            onClick={() => selectTrace(tr.trace_id)}
                          >
                            <td>
                              <code className="trace-id-code">{tr.trace_id.slice(0, 10)}...</code>
                            </td>
                            <td>
                              <span className="trace-name-text">{tr.root_trace_name || "HTTP Request"}</span>
                            </td>
                            <td>
                              <span className="trace-duration">{(tr.duration_ms || 0).toFixed(2)} ms</span>
                            </td>
                            <td>
                              <span className={`status-pill ${isErr ? "pill-red" : "pill-green"}`}>
                                {tr.status_code || 200}
                              </span>
                            </td>
                            <td>
                              <small className="trace-time">
                                {tr.timestamp ? new Date(tr.timestamp).toLocaleTimeString() : "--:--:--"}
                              </small>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Trace Waterfall / Detail View */}
            <div className="trace-detail-panel">
              <div className="trace-detail-header">
                <h3>Span Waterfall Details</h3>
                {selectedTraceId && (
                  <button
                    className="button button-secondary"
                    onClick={() => handleLogsForTrace(selectedTraceId)}
                    title="Find matching logs in Loki"
                  >
                    View Logs for Trace &rarr;
                  </button>
                )}
              </div>

              {!selectedTraceId ? (
                <div className="empty-state">
                  <h4>Select a trace</h4>
                  <p>Click on any trace in the list to view its span breakdown and latency timeline.</p>
                </div>
              ) : traceDetailLoading ? (
                <div className="inline-empty">
                  <span className="empty-dot" /> Loading span telemetry...
                </div>
              ) : !traceDetail || !traceDetail.spans || traceDetail.spans.length === 0 ? (
                <div className="inline-empty">
                  <span className="empty-dot" /> No spans found for Trace ID {selectedTraceId}
                </div>
              ) : (
                <div className="trace-waterfall-view">
                  <div className="trace-summary-card">
                    <div>
                      <span className="meta-label">Trace ID</span>
                      <code className="full-trace-id">{traceDetail.trace_id}</code>
                    </div>
                    <div>
                      <span className="meta-label">Spans</span>
                      <strong>{traceDetail.spans.length}</strong>
                    </div>
                    <div>
                      <span className="meta-label">Root Duration</span>
                      <strong>{(traceDetail.spans[0]?.duration_ms || 0).toFixed(2)} ms</strong>
                    </div>
                  </div>

                  {/* Waterfall Spans */}
                  <div className="spans-waterfall-list">
                    {traceDetail.spans.map((span, sIdx) => {
                      const dur = span.duration_ms || 0;
                      const isSpanErr = (span.status_code || 200) >= 400;
                      return (
                        <div key={span.span_id || sIdx} className="span-waterfall-item">
                          <div className="span-header-line">
                            <span className="span-name">{span.name}</span>
                            <span className={`status-pill ${isSpanErr ? "pill-red" : "pill-green"}`}>
                              {span.status_code || 200}
                            </span>
                            <span className="span-duration">{dur.toFixed(2)} ms</span>
                          </div>

                          {/* Graphical Waterfall Bar */}
                          <div className="waterfall-bar-track">
                            <div
                              className={`waterfall-bar-fill ${isSpanErr ? "bar-error" : "bar-ok"}`}
                              style={{ width: "100%" }}
                            />
                          </div>

                          {/* Span Attributes / Tags */}
                          {span.attributes && Object.keys(span.attributes).length > 0 && (
                            <div className="span-attributes-box">
                              {Object.entries(span.attributes).map(([k, v]) => (
                                <div key={k} className="attr-chip">
                                  <span className="attr-key">{k}:</span>
                                  <span className="attr-val">{String(v)}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

