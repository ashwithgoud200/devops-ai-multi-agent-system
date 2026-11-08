async function request(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string" ? detail : `Request failed (${response.status})`,
    );
  }
  return body;
}

export function getJson(path) {
  return request(path);
}

export function getMetricsText() {
  return fetch("/api/metrics", { headers: { Accept: "text/plain" } }).then(
    async (response) => {
      if (!response.ok) throw new Error(`Metrics request failed (${response.status})`);
      return response.text();
    },
  );
}

export function startIncident(query) {
  return request("/incidents", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

export function decideIncident(incidentId, decision, reviewedBy) {
  return request(`/incidents/${encodeURIComponent(incidentId)}/approval`, {
    method: "POST",
    body: JSON.stringify({ decision, reviewed_by: reviewedBy }),
  });
}

export function getComposeTopology() {
  return request("/topology/compose");
}

export function getGitTelemetry() {
  return request("/telemetry/git");
}

export function testSpecialistAgent(agentId, query) {
  return request(`/agents/${encodeURIComponent(agentId)}/test`, {
    method: "POST",
    body: JSON.stringify({ query: query || "Diagnose the observed application behavior." }),
  });
}

export async function getOllamaStatus() {
  const response = await fetch("/ollama/api/tags", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`Ollama returned ${response.status}`);
  return response.json();
}

export async function getServiceStatus(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Service returned ${response.status}`);
  return response.text();
}

function parseLabels(labelText) {
  if (!labelText) return {};
  return Object.fromEntries(
    [...labelText.matchAll(/(\w+)="((?:\\.|[^"])*)"/g)].map((item) => [
      item[1],
      item[2].replace(/\\"/g, '"').replace(/\\\\/g, "\\"),
    ]),
  );
}

export function parseApplicationMetrics(text) {
  const counters = {
    total: 0,
    successful: 0,
    failed: 0,
    byStatus: {},
    httpTotal: 0,
    incidentsCreated: 0,
    incidentsByStatus: {
      pending_approval: 0,
      completed: 0,
      failed: 0,
      rejected: 0,
    },
    approvals: { approve: 0, reject: 0 },
    agentExecutionsTotal: 0,
    agentByOutcome: {},
    llmCalls: {
      success: 0,
      failure: 0,
      timeout: 0,
      unavailable: 0,
      disabled: 0,
    },
  };
  for (const line of text.split(/\r?\n/)) {
    if (!line || line.startsWith("#")) continue;
    const match = line.match(
      /^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)/i,
    );
    if (!match) continue;
    const [, metricName, rawLabels, rawVal] = match;
    const value = Number(rawVal);
    if (!Number.isFinite(value)) continue;
    const labels = parseLabels(rawLabels);

    if (metricName === "calc_requests_total") {
      const status = labels.status || "unknown";
      counters.total += value;
      counters.byStatus[status] = (counters.byStatus[status] || 0) + value;
      if (status === "ok") counters.successful += value;
      else counters.failed += value;
    } else if (metricName === "devops_http_requests_total") {
      counters.httpTotal += value;
    } else if (metricName === "devops_incidents_created_total") {
      counters.incidentsCreated += value;
    } else if (metricName === "devops_incidents_by_status_total") {
      const st = labels.status || "unknown";
      counters.incidentsByStatus[st] = (counters.incidentsByStatus[st] || 0) + value;
    } else if (metricName === "devops_human_decisions_total") {
      const dec = labels.decision;
      if (dec === "approve" || dec === "reject") {
        counters.approvals[dec] = (counters.approvals[dec] || 0) + value;
      }
    } else if (metricName === "devops_agent_executions_total") {
      counters.agentExecutionsTotal += value;
      const out = labels.outcome || "unknown";
      counters.agentByOutcome[out] = (counters.agentByOutcome[out] || 0) + value;
    } else if (metricName === "devops_llm_requests_total") {
      const st = labels.status || "unknown";
      counters.llmCalls[st] = (counters.llmCalls[st] || 0) + value;
    }
  }
  return counters;
}

export function buildIncidentHistory(events) {
  const incidents = new Map();
  for (const event of events) {
    if (!event?.incident_id) continue;
    const record = incidents.get(event.incident_id) || {
      incident_id: event.incident_id,
      started_at: event.timestamp,
      status: "started",
      decision: null,
      outcome: null,
      target_version: null,
      events: [],
    };
    record.events.push(event);
    if (event.event === "incident_started") record.started_at = event.timestamp;
    if (event.event === "diagnosis_finished") {
      record.status = event.status || "completed";
      record.target_version = event.target_version || record.target_version;
    }
    if (event.event === "approval_decision") {
      record.decision = event.decision;
      record.target_version = event.target_version || record.target_version;
      record.status = event.decision === "approve" ? "approved" : "rejected";
    }
    if (event.event === "action_finished") {
      record.outcome = event.outcome_status || null;
      record.status = event.outcome_status || record.status;
    }
    incidents.set(event.incident_id, record);
  }
  return [...incidents.values()].sort(
    (left, right) => Date.parse(right.started_at) - Date.parse(left.started_at),
  );
}

export function formatTimestamp(value) {
  if (!value) return "Timestamp unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Timestamp unavailable" : date.toLocaleString();
}

export function getIntegrationsStatus() {
  return request("/integrations/status");
}

export function getLatestCiRun() {
  return request("/ci/runs/latest");
}

export function getSecurityFindings() {
  return request("/security/findings");
}

export function getScenarios() {
  return request("/scenarios");
}

export function getScenarioStatus() {
  return request("/scenarios/status");
}

export function getScenario(id) {
  return request(`/scenarios/${encodeURIComponent(id)}`);
}

export function activateScenario(id) {
  return request(`/scenarios/${encodeURIComponent(id)}/activate`, {
    method: "POST",
  });
}

export function resetScenario(id) {
  return request(`/scenarios/${encodeURIComponent(id)}/reset`, {
    method: "POST",
  });
}

export function getLokiTelemetry(query, limit = 100, since = "1h") {
  const params = new URLSearchParams();
  if (query) params.append("query", query);
  if (limit) params.append("limit", limit.toString());
  if (since) params.append("since", since);
  return request(`/telemetry/loki?${params.toString()}`);
}

export function getTempoTelemetry(limit = 50, service = "calculator-app") {
  const params = new URLSearchParams();
  if (limit) params.append("limit", limit.toString());
  if (service) params.append("service", service);
  return request(`/telemetry/tempo?${params.toString()}`);
}

export function getTraceDetails(traceId) {
  return request(`/telemetry/traces/${encodeURIComponent(traceId)}`);
}

export function fixAndDeployIncident(incidentId) {
  return request(`/incidents/${encodeURIComponent(incidentId)}/fix-and-deploy`, {
    method: "POST",
  });
}

export function getFeatureStatus() {
  return request("/features/status");
}

export function generateFeature(data) {
  return request("/features/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function testFeatureCi(data) {
  return request("/features/test-ci", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function deployFeature(data) {
  return request("/features/deploy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function getFeatureHistory() {
  return request("/features/history");
}

export function testLiveEndpoint(op, a, b) {
  const params = new URLSearchParams({ a: a.toString() });
  if (b !== undefined && b !== null && b !== "") {
    params.append("b", b.toString());
  }
  return request(`/calc/${encodeURIComponent(op)}?${params.toString()}`);
}

export function getChatOpsStatus() {
  return request("/chatops/status");
}

export function getChatOpsHistory(limit = 50) {
  return request(`/chatops/history?limit=${limit}`);
}

export function dispatchChatOps(data) {
  return request("/chatops/dispatch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function sendChatOpsInteraction(incidentId, decision, reviewedBy = "web-chatops") {
  return request("/chatops/interactive", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      incident_id: incidentId,
      decision,
      reviewed_by: reviewedBy,
    }),
  });
}

export function updateChatOpsConfig(config) {
  return request("/chatops/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export function sendChatOpsTestPing() {
  return request("/chatops/test", {
    method: "POST",
  });
}

export function getMemoryStatus() {
  return request("/memory/status");
}

export function listRunbooks() {
  return request("/memory/runbooks");
}

export function getRunbookDetail(id) {
  return request(`/memory/runbooks/${encodeURIComponent(id)}`);
}

export function searchMemory(query, top_k = 3) {
  return request("/memory/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k }),
  });
}

export function getMemoryGraph() {
  return request("/memory/graph");
}

export function getChaosStatus() {
  return request("/chaos/status");
}

export function triggerCpuStress(durationSeconds = 15, numThreads = 2) {
  return request("/chaos/stress/cpu", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration_seconds: durationSeconds, num_threads: numThreads }),
  });
}

export function triggerMemoryStress(megabytes = 200, durationSeconds = 15) {
  return request("/chaos/stress/memory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ megabytes, duration_seconds: durationSeconds }),
  });
}

export function injectChaosLatency(latencySeconds = 0.45, durationSeconds = 20) {
  return request("/chaos/inject/latency", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ latency_seconds: latencySeconds, duration_seconds: durationSeconds }),
  });
}

export function armChaosCrash(arm = true, message = "Real Chaos Exception: unhandled runtime fault") {
  return request("/chaos/trigger/crash", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ arm, message }),
  });
}

export function runChaosSecurityAudit() {
  return request("/chaos/run/security-audit", {
    method: "POST",
  });
}

export function stopAllChaos() {
  return request("/chaos/stop", {
    method: "POST",
  });
}
