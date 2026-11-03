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
