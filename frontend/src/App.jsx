import { useCallback, useEffect, useMemo, useState } from "react";
import {
  buildIncidentHistory,
  decideIncident,
  formatTimestamp,
  getIntegrationsStatus,
  getJson,
  getLatestCiRun,
  getMetricsText,
  getOllamaStatus,
  getSecurityFindings,
  getServiceStatus,
  parseApplicationMetrics,
  startIncident,
} from "./api.js";
import AgentGrid from "./components/AgentGrid.jsx";
import CiSecurityView from "./components/CiSecurityView.jsx";
import AuditLog from "./components/AuditLog.jsx";
import Icon from "./components/Icon.jsx";
import IncidentDetails from "./components/IncidentDetails.jsx";
import { MetricBars, RequestTrend } from "./components/MetricsCharts.jsx";
import StatusCard from "./components/StatusCard.jsx";

const navigation = [
  { id: "overview", label: "Overview", icon: "grid" },
  { id: "agents", label: "Six AI Agents", icon: "agents" },
  { id: "incidents", label: "Incident Management", icon: "incident" },
  { id: "ci-security", label: "CI/CD & Security", icon: "shield" },
  { id: "approval", label: "Human Approval", icon: "approval" },
  { id: "monitoring", label: "Monitoring", icon: "chart" },
  { id: "audit", label: "Audit Log", icon: "audit" },
];

const pageTitles = {
  overview: ["Overview", "Operational status and incident activity at a glance."],
  agents: ["Six AI Agents", "Specialist execution details from the selected incident."],
  incidents: ["Incident Management", "Investigate using live application and observability evidence."],
  "ci-security": ["CI/CD & Security", "GitHub integration, CI pipeline results, and normalized security scanner findings."],
  approval: ["Human Approval", "Review proposed remediation before explicitly deciding."],
  monitoring: ["Monitoring", "Application counters and Prometheus time-series telemetry."],
  audit: ["Audit Log", "Metadata-only incident, approval, and action records."],
};

function call(promise) {
  return promise.then((value) => ({ value, error: null })).catch((error) => ({
    value: null,
    error: error instanceof Error ? error.message : "Request failed",
  }));
}

function latestIncidentId(events) {
  return [...events].reverse().find((event) => event.event === "incident_started")?.incident_id || null;
}

function ServiceIndicator({ label, status, detail }) {
  const up = status === "online" || status === "ok" || status === "partial";
  return (
    <div className="service-indicator">
      <span className={`service-dot ${up ? "is-up" : "is-down"}`} />
      <span className="service-name">{label}</span>
      <strong className={up ? "text-green" : "text-muted"}>{status || "checking"}</strong>
      {detail && <span className="service-detail">{detail}</span>}
    </div>
  );
}

function SectionTitle({ eyebrow, title, action }) {
  return <div className="section-heading"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div>{action}</div>;
}

function formatCounter(value) {
  return Number.isFinite(value) ? value.toLocaleString() : "Unavailable";
}

function DashboardHome({ data, counters, history, onNavigate, onSelectIncident }) {
  const latest = history[0];
  const agentCount = data.agents?.agents?.length || 0;
  const appHealthy = data.health?.status === "ok";
  const promStatus = data.prometheus?.status;
  return (
    <>
      <div className="welcome-strip">
        <div><span className="eyebrow">DEVOPS CONTROL CENTER</span><h2>Good operations start with clear signals.</h2><p>Live application and incident data from your local multi-agent system.</p></div>
        <div className="welcome-meta"><span className="live-indicator" />Refreshing every 30 seconds<span className="welcome-divider" />{data.lastUpdated ? `Updated ${formatTimestamp(data.lastUpdated)}` : "Waiting for first API response"}</div>
      </div>
      <div className="status-grid">
        <StatusCard label="Application health" value={appHealthy ? "Healthy" : data.health ? "Unhealthy" : "Unavailable"} detail={data.health?.version ? `Version ${data.health.version}` : "Health endpoint not responding"} icon="◉" tone={appHealthy ? "green" : "amber"} />
        <StatusCard label="Total requests" value={formatCounter(counters?.total)} detail="Cumulative application counter" icon="↗" tone="blue" />
        <StatusCard label="Successful requests" value={formatCounter(counters?.successful)} detail="Status: ok" icon="✓" tone="green" />
        <StatusCard label="Failed requests" value={formatCounter(counters?.failed)} detail="Error and client-error statuses" icon="!" tone={counters?.failed ? "amber" : "neutral"} />
      </div>
      <div className="content-grid overview-grid">
        <section className="panel chart-panel">
          <SectionTitle eyebrow="REQUEST PERFORMANCE" title="Request rate" action={<span className={`pill ${promStatus === "ok" ? "pill-green" : promStatus === "partial" ? "pill-amber" : "pill-muted"}`}>Prometheus · {promStatus || "unavailable"}</span>} />
          <RequestTrend metrics={data.prometheus} />
        </section>
        <section className="panel">
          <SectionTitle eyebrow="SYSTEM STATUS" title="Connected services" />
          <div className="service-list">
            <ServiceIndicator label="Calculator API" status={appHealthy ? "online" : "unavailable"} detail={data.health?.version ? `v${data.health.version}` : null} />
            <ServiceIndicator label="Ollama runtime" status={data.ollama ? "online" : "unavailable"} detail={data.ollama?.models?.length != null ? `${data.ollama.models.length} models available` : null} />
            <ServiceIndicator label="Prometheus" status={data.prometheusService ? promStatus || "online" : "unavailable"} />
            <ServiceIndicator label="Grafana" status={data.grafana ? "online" : "unavailable"} />
            <ServiceIndicator label="GitHub API" status={data.integrations?.github?.status || "disabled"} detail={data.integrations?.github?.repo || "Read-only API"} />
            <ServiceIndicator label="CI Pipeline" status={data.ciRun?.conclusion || data.ciRun?.status || "unavailable"} detail={data.ciRun?.workflow_name || null} />
            <ServiceIndicator label="Security Scans" status={data.securityFindings?.status || "unavailable"} detail={data.securityFindings?.summary?.total_findings != null ? `${data.securityFindings.summary.total_findings} findings` : null} />
            <ServiceIndicator label="Specialist agents" status={data.agents?.enabled ? "enabled" : data.agents ? "disabled" : "unavailable"} detail={agentCount ? `${agentCount} configured` : null} />
          </div>
          <div className="service-links"><a href="http://127.0.0.1:9090" target="_blank" rel="noreferrer">Prometheus <Icon name="arrow" size={14} /></a><a href="http://127.0.0.1:3000" target="_blank" rel="noreferrer">Grafana <Icon name="arrow" size={14} /></a></div>
        </section>
      </div>
      <div className="content-grid lower-grid">
        <section className="panel">
          <SectionTitle eyebrow="INCIDENT RESPONSE" title="Current incident" action={<button className="link-button" onClick={() => onNavigate("incidents")}>Open incident workspace <Icon name="arrow" size={14} /></button>} />
          {data.incident ? (
            <button className="current-incident" onClick={() => onNavigate("incidents")}>
              <span className="incident-symbol">!</span>
              <span className="incident-main"><strong>{data.incident.diagnosis?.summary || data.incident.query || "Incident investigation"}</strong><small>{data.incident.incident_id}</small></span>
              <span className={`pill ${data.incident.status === "pending_approval" ? "pill-amber" : "pill-green"}`}>{data.incident.status}</span>
            </button>
          ) : <div className="inline-empty"><span className="empty-dot" />No recent incident loaded from the audit history.</div>}
        </section>
        <section className="panel">
          <SectionTitle eyebrow="RECENT ACTIVITY" title="Incident history" action={<button className="link-button" onClick={() => onNavigate("audit")}>View audit log <Icon name="arrow" size={14} /></button>} />
          {history.length ? <div className="history-list">{history.slice(0, 4).map((incident) => (
            <button className="history-row" key={incident.incident_id} onClick={() => onSelectIncident(incident.incident_id)}>
              <span className={`history-mark ${incident.status === "succeeded" ? "history-success" : incident.status === "pending_approval" ? "history-pending" : ""}`} />
              <span className="history-copy"><strong>{incident.status.replaceAll("_", " ")}</strong><small>{incident.incident_id.slice(0, 14)}{incident.decision ? ` · ${incident.decision}` : ""}</small></span>
              <time>{formatTimestamp(incident.started_at)}</time>
            </button>
          ))}</div> : <div className="inline-empty">No incident history returned by the audit API.</div>}
        </section>
      </div>
      {data.errors?.metrics && <p className="inline-warning">Request counters unavailable: {data.errors.metrics}</p>}
      {data.errors?.audit && <p className="inline-warning">Incident history unavailable: {data.errors.audit}</p>}
    </>
  );
}

function MetricsPage({ data, counters }) {
  const health = data.health;
  const requestMetrics = data.prometheus?.metrics || {};
  const p95 = requestMetrics.latency_p95;
  const errors = requestMetrics.http_error_rate;
  const formatValue = (metric, suffix = "") => {
    const value = metric?.observations?.[0]?.latest_value;
    return metric?.status === "ok" && Number.isFinite(value) ? `${value.toFixed(2)}${suffix}` : "Unavailable";
  };
  return (
    <>
      <div className="status-grid monitoring-cards">
        <StatusCard label="Application status" value={health?.status === "ok" ? "Healthy" : "Unavailable"} detail={health?.version ? `Current version ${health.version}` : "No health response"} icon="◉" tone={health?.status === "ok" ? "green" : "amber"} />
        <StatusCard label="Request total" value={formatCounter(counters?.total)} detail={`HTTP API total: ${formatCounter(counters?.httpTotal)}`} icon="↗" tone="blue" />
        <StatusCard label="HTTP error rate" value={formatValue(errors, "%")} detail="Prometheus 5-minute query" icon="!" tone="amber" />
        <StatusCard label="Latency p95" value={formatValue(p95, "s")} detail="Prometheus histogram quantile" icon="◷" tone="neutral" />
      </div>
      <div className="status-grid monitoring-cards">
        <StatusCard label="Incidents created" value={formatCounter(counters?.incidentsCreated)} detail={`Pending approval: ${formatCounter(counters?.incidentsByStatus?.pending_approval ?? 0)}`} icon="!" tone="blue" />
        <StatusCard label="Human decisions" value={counters ? `${counters.approvals.approve} / ${counters.approvals.reject}` : "Unavailable"} detail="Approved / Rejected" icon="✓" tone="green" />
        <StatusCard label="Agent executions" value={formatCounter(counters?.agentExecutionsTotal)} detail={`OK: ${formatCounter(counters?.agentByOutcome?.ok ?? 0)} · Disabled: ${formatCounter(counters?.agentByOutcome?.disabled ?? 0)}`} icon="◉" tone="neutral" />
        <StatusCard label="LLM inference calls" value={counters ? `${counters.llmCalls.success} ok` : "Unavailable"} detail={counters ? `Fail/Timeout: ${(counters.llmCalls.failure || 0) + (counters.llmCalls.timeout || 0)} · Unavail: ${counters.llmCalls.unavailable || 0}` : "From /metrics"} icon="↗" tone="neutral" />
      </div>
      <section className="panel">
        <SectionTitle eyebrow="PROMETHEUS TIME SERIES" title="Request success and failure trend" action={<span className={`pill ${data.prometheus?.status === "ok" ? "pill-green" : "pill-muted"}`}>{data.prometheus?.status || "unavailable"}</span>} />
        <RequestTrend metrics={data.prometheus} />
      </section>
      <div className="content-grid monitoring-grid">
        <section className="panel"><SectionTitle eyebrow="APPLICATION COUNTERS" title="Request outcomes" /><MetricBars counters={counters} /><p className="panel-footnote">Values are cumulative counters exposed by the live application. They are not estimated.</p></section>
        <section className="panel"><SectionTitle eyebrow="SERVICE LINKS" title="Observability tools" /><div className="tool-link-list">
          <a href="http://127.0.0.1:9090" target="_blank" rel="noreferrer"><span><strong>Prometheus</strong><small>Explore metrics, alert rules, and targets</small></span><Icon name="arrow" /></a>
          <a href="http://127.0.0.1:3000" target="_blank" rel="noreferrer"><span><strong>Grafana</strong><small>Open provisioned dashboards (40 panels across 7+ sections)</small></span><Icon name="arrow" /></a>
        </div>{data.prometheus?.detail && <p className="inline-warning">{data.prometheus.detail}</p>}</section>
      </div>
    </>
  );
}

function ApprovalPage({ incident, reviewer, setReviewer, onDecision, busy }) {
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setConfirm(false); setError(""); }, [incident?.incident_id, incident?.status]);
  const remediation = incident?.proposed_remediation;
  const pending = incident?.status === "pending_approval" && remediation?.action === "rollback";
  const submitDecision = async (decision) => {
    if (!reviewer.trim()) {
      setError("Enter a reviewer label before recording a decision.");
      return;
    }
    setError("");
    try {
      await onDecision(decision);
      setConfirm(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Decision could not be recorded.");
    }
  };
  return (
    <>
      <section className="panel approval-panel">
        <SectionTitle eyebrow="HUMAN-IN-THE-LOOP GATE" title="Review proposed remediation" />
        {!incident ? <div className="empty-state"><h3>No incident selected</h3><p>Start an incident investigation before reviewing a proposed action.</p></div>
          : pending ? <>
            <div className="approval-alert"><span className="approval-alert-icon">!</span><div><strong>Approval required</strong><p>Rollback will not run unless you explicitly approve this proposal.</p></div></div>
            <div className="proposal-grid">
              <div><span className="eyebrow">Action</span><strong>{remediation.action}</strong></div>
              <div><span className="eyebrow">Target application version</span><strong>{remediation.target_version ? `v${remediation.target_version}` : "Not provided"}</strong></div>
              <div className="proposal-rationale"><span className="eyebrow">Rationale</span><p>{remediation.rationale || "No rationale was returned."}</p></div>
            </div>
            <div className="reviewer-field"><label htmlFor="reviewer">Reviewer label</label><input id="reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="e.g. local operator" /><small>This is recorded as a self-reported audit label, not an authenticated identity.</small></div>
            <div className="approval-actions"><button className="button button-danger" disabled={busy} onClick={() => submitDecision("reject")}>Reject proposal</button><button className="button button-primary" disabled={busy} onClick={() => setConfirm(true)}>{busy ? "Recording…" : "Approve rollback"}</button></div>
          </> : <div className="decision-result"><span className={`decision-icon ${incident.outcome?.status === "succeeded" ? "decision-success" : ""}`}>{incident.outcome?.status === "succeeded" ? "✓" : "i"}</span><h3>{incident.outcome?.status === "succeeded" ? "Approved rollback completed" : incident.outcome?.status === "rejected" ? "Proposal rejected" : `No pending approval · ${incident.status || "unknown"}`}</h3><p>{incident.outcome?.reason || incident.outcome?.rollback?.data?.rolled_back_to || remediation?.rationale || "No action is awaiting approval."}</p><small>Incident {incident.incident_id}</small></div>}
        {error && <div className="form-error" role="alert">{error}</div>}
      </section>
      {confirm && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <button className="modal-close" aria-label="Close confirmation" onClick={() => setConfirm(false)}><Icon name="close" /></button>
        <span className="modal-warning">!</span><h2 id="confirm-title">Confirm rollback approval</h2>
        <p>You are approving rollback to <strong>v{remediation?.target_version || "unknown"}</strong>. The existing workflow will execute the action and verify application health.</p>
        <p className="modal-caution">This is an explicit action. Do not approve unless you have reviewed the evidence and proposal.</p>
        <div className="modal-actions"><button className="button button-secondary" onClick={() => setConfirm(false)}>Cancel</button><button className="button button-primary" disabled={busy} onClick={() => submitDecision("approve")}>{busy ? "Recording…" : "Confirm approval"}</button></div>
      </section></div>}
    </>
  );
}

export default function App() {
  const [page, setPage] = useState("overview");
  const [data, setData] = useState({ errors: {}, audit: [], lastUpdated: null });
  const [counters, setCounters] = useState(null);
  const [incident, setIncident] = useState(null);
  const [activeIncidentId, setActiveIncidentId] = useState(null);
  const [query, setQuery] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [incidentBusy, setIncidentBusy] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [incidentError, setIncidentError] = useState("");
  const [actionError, setActionError] = useState("");

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setRefreshing(true);
    const [health, metrics, version, prometheus, audit, agents, grafana, prometheusService, ollama, integrations, ciRun, securityFindings] = await Promise.all([
      call(getJson("/health")),
      call(getMetricsText()),
      call(getJson("/admin/version")),
      call(getJson("/telemetry/prometheus")),
      call(getJson("/audit")),
      call(getJson("/agents")),
      call(getServiceStatus("/grafana/api/health")),
      call(getServiceStatus("/prometheus/-/healthy")),
      call(getOllamaStatus()),
      call(getIntegrationsStatus()),
      call(getLatestCiRun()),
      call(getSecurityFindings()),
    ]);
    const results = { health, metrics, version, prometheus, audit, agents, grafana, prometheusService, ollama, integrations, ciRun, securityFindings };
    const errors = Object.fromEntries(Object.entries(results).filter(([, result]) => result.error).map(([key, result]) => [key, result.error]));
    const auditEvents = audit.value?.events;
    setData((previous) => ({
      ...previous,
      health: health.value,
      version: version.value,
      prometheus: prometheus.value,
      audit: Array.isArray(auditEvents) ? auditEvents : previous.audit,
      agents: agents.value,
      grafana: grafana.value,
      prometheusService: prometheusService.value,
      ollama: ollama.value,
      integrations: integrations.value,
      ciRun: ciRun.value,
      securityFindings: securityFindings.value,
      errors,
      lastUpdated: new Date().toISOString(),
    }));
    setCounters(metrics.value ? parseApplicationMetrics(metrics.value) : null);

    const targetId = activeIncidentId || (Array.isArray(auditEvents) ? latestIncidentId(auditEvents) : null);
    if (targetId) {
      const result = await call(getJson(`/incidents/${encodeURIComponent(targetId)}`));
      if (result.value) {
        setIncident(result.value);
        setActiveIncidentId(targetId);
      } else {
        setIncident(null);
        setIncidentError(result.error || "Incident details are unavailable.");
      }
    } else if (Array.isArray(auditEvents) && auditEvents.length === 0) {
      setIncident(null);
    }
    if (!silent) setRefreshing(false);
  }, [activeIncidentId]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => refresh(true), 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const history = useMemo(() => buildIncidentHistory(data.audit || []), [data.audit]);
  const selectedHistory = history.find((item) => item.incident_id === activeIncidentId);
  const currentPage = pageTitles[page];

  const submitIncident = async (event) => {
    event.preventDefault();
    if (query.trim().length < 3) {
      setIncidentError("Enter an incident query with at least three characters.");
      return;
    }
    setIncidentBusy(true);
    setIncidentError("");
    setActionError("");
    try {
      const result = await startIncident(query.trim());
      setIncident(result);
      setActiveIncidentId(result.incident_id);
      setQuery("");
      setPage(result.status === "pending_approval" ? "approval" : "incidents");
      await refresh(true);
    } catch (error) {
      setIncidentError(error instanceof Error ? error.message : "Incident could not be submitted.");
    } finally {
      setIncidentBusy(false);
    }
  };

  const recordDecision = async (decision) => {
    if (!incident?.incident_id) throw new Error("Select an incident before recording a decision.");
    setDecisionBusy(true);
    setActionError("");
    try {
      const result = await decideIncident(incident.incident_id, decision, reviewer.trim());
      setIncident(result);
      await refresh(true);
      return result;
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Decision could not be recorded.");
      throw error;
    } finally {
      setDecisionBusy(false);
    }
  };

  const selectIncident = async (incidentId) => {
    setPage("incidents");
    setActiveIncidentId(incidentId);
    setIncidentError("");
    const result = await call(getJson(`/incidents/${encodeURIComponent(incidentId)}`));
    if (result.value) setIncident(result.value);
    else {
      setIncident(null);
      setIncidentError(result.error || "Incident details are unavailable. In-memory workflow state may have been lost after a restart.");
    }
  };

  const agentResults = incident?.specialists?.results || incident?.report?.specialists?.results || {};
  const configuredAgents = data.agents?.agents || [];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><span /></div><div><strong>OpsPilot</strong><small>DEVOPS CONTROL</small></div></div>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="main-nav" aria-label="Main navigation">
          {navigation.map((item) => <button key={item.id} className={`nav-item ${page === item.id ? "active" : ""}`} onClick={() => setPage(item.id)}><Icon name={item.icon} /><span>{item.label}</span>{item.id === "approval" && incident?.status === "pending_approval" && <i className="nav-alert" />}</button>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="environment-badge"><span className="environment-dot" /><span><small>ENVIRONMENT</small><strong>Local · Loopback</strong></span></div>
          <p>Human approval is required for every remediation action.</p>
          <span className="sidebar-version">Multi-agent incident response</span>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><b>/</b><strong>{currentPage[0]}</strong></div>
          <div className="topbar-actions"><span className="api-indicator"><i className={data.health ? "is-up" : "is-down"} />API {data.health ? "connected" : "checking"}</span><button className="icon-button" onClick={() => refresh()} disabled={refreshing} aria-label="Refresh dashboard"><Icon className={refreshing ? "spin" : ""} name="refresh" /></button></div>
        </header>
        <div className="page-content">
          <div className="page-heading"><div><h1>{currentPage[0]}</h1><p>{currentPage[1]}</p></div>{page === "overview" && <button className="button button-primary" onClick={() => setPage("incidents")}><span>＋</span> New investigation</button>}</div>
          {actionError && <div className="global-error" role="alert">{actionError}<button onClick={() => setActionError("")}>Dismiss</button></div>}
          {page === "overview" && <DashboardHome data={data} counters={counters} history={history} onNavigate={setPage} onSelectIncident={selectIncident} />}
          {page === "ci-security" && <CiSecurityView integrations={data.integrations} ciRun={data.ciRun} securityFindings={data.securityFindings} />}
          {page === "agents" && <><div className="notice-bar"><span className="notice-icon">i</span><span>Agent statuses and outputs below come from the selected incident response. Agents not selected by the workflow are marked accordingly.</span><span className={`pill ${data.agents?.enabled ? "pill-green" : "pill-muted"}`}>Inference {data.agents?.enabled ? "enabled" : "disabled"}</span></div><AgentGrid configuredAgents={configuredAgents} results={agentResults} /></>}
          {page === "incidents" && <div className="incident-page">
            <section className="panel incident-form-panel"><SectionTitle eyebrow="NEW INVESTIGATION" title="Submit an incident" /><form className="incident-form" onSubmit={submitIncident}><label htmlFor="incident-query">What should the system investigate?</label><textarea id="incident-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. Investigate increased calculator errors after the latest deployment" maxLength={2000} rows={3} /><div className="form-footer"><small>Evidence collection and agent execution may take a few moments. No remediation runs without human approval.</small><button className="button button-primary" disabled={incidentBusy || query.trim().length < 3}>{incidentBusy ? <><span className="button-spinner" /> Investigating…</> : "Run investigation"}</button></div></form>{incidentError && <div className="form-error" role="alert">{incidentError}</div>}</section>
            {history.length > 0 && <section className="panel incident-picker"><label htmlFor="incident-history">Viewing incident</label><select id="incident-history" value={activeIncidentId || ""} onChange={(event) => selectIncident(event.target.value)}><option value="" disabled>Select an incident</option>{history.map((item) => <option key={item.incident_id} value={item.incident_id}>{item.incident_id.slice(0, 12)} · {item.status.replaceAll("_", " ")}</option>)}</select><span className="incident-picker-note">Details are loaded from the existing LangGraph incident API.</span></section>}
            {incidentError && activeIncidentId && <div className="inline-warning">{incidentError}</div>}
            <IncidentDetails incident={incident} onSelectIncident={selectIncident} history={history} />
            {incident && <section className="panel agent-results-panel"><SectionTitle eyebrow="SPECIALIST ANALYSIS" title="Agent execution results" /><AgentGrid configuredAgents={configuredAgents} results={agentResults} /></section>}
          </div>}
          {page === "approval" && <ApprovalPage incident={incident} reviewer={reviewer} setReviewer={setReviewer} onDecision={recordDecision} busy={decisionBusy} />}
          {page === "monitoring" && <MetricsPage data={data} counters={counters} />}
          {page === "audit" && <section className="panel"><SectionTitle eyebrow="APPEND-ONLY LOCAL RECORDS" title="Incident audit events" action={<span className="pill pill-muted">{data.audit?.length || 0} events</span>} />{data.errors?.audit && <p className="inline-warning">Audit API unavailable: {data.errors.audit}</p>}<AuditLog events={data.audit || []} onSelectIncident={selectIncident} /></section>}
          <footer className="page-footer"><span>OpsPilot · Local DevOps Monitoring</span><span>Backend <code>127.0.0.1:8100</code> · Refresh interval 30s</span></footer>
        </div>
      </main>
    </div>
  );
}
