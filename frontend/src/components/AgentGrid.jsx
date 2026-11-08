import { useState } from "react";
import { testSpecialistAgent } from "../api.js";
import Icon from "./Icon.jsx";

const labels = {
  monitoring: "Monitoring Agent",
  incident: "Incident Agent",
  code: "Code Agent",
  cicd: "CI/CD Agent",
  infrastructure: "Infrastructure Agent",
  security: "Security Agent",
};

const defaultModels = {
  monitoring: "qwen2.5:3b",
  incident: "llama3.2:3b",
  code: "qwen2.5-coder:3b",
  cicd: "stablelm-zephyr:3b",
  infrastructure: "phi3.5:3.8b",
  security: "granite3.1-dense:2b",
};

function validationFor(result) {
  const statuses = [
    result?.validated_summary?.validation_status,
    ...(result?.validated_findings || []).map((finding) => finding.validation_status),
  ].filter(Boolean);
  if (!statuses.length) {
    if (result?.validation_status) return result.validation_status;
    return "Not available";
  }
  if (statuses.includes("unverified")) return "Unverified claims";
  if (statuses.includes("verified")) return "Verified";
  return statuses[0];
}

function resolveStatus(res, skipped, running, queued) {
  if (running) return "RUNNING";
  if (queued) return "QUEUED";
  if (res) {
    if (res.execution_status) return res.execution_status;
    const s = String(res.status || "").toLowerCase();
    if (s === "ok") return "COMPLETED";
    if (s === "timeout") return "TIMEOUT";
    if (s === "skipped" || s === "disabled") return "SKIPPED";
    if (["error", "failed", "invalid_response", "configuration_error", "unavailable"].includes(s)) return "FAILED";
    if (s === "running") return "RUNNING";
    return "COMPLETED";
  }
  if (skipped) return "SKIPPED";
  return "IDLE";
}

function statusPillClass(status) {
  switch (status) {
    case "COMPLETED":
      return "pill-green";
    case "RUNNING":
      return "pill-blue pulse-badge";
    case "QUEUED":
      return "pill-amber";
    case "TIMEOUT":
      return "pill-amber";
    case "FAILED":
      return "pill-red";
    case "SKIPPED":
      return "pill-muted";
    default:
      return "pill-muted";
  }
}

export default function AgentGrid({
  configuredAgents = [],
  results = {},
  skipped = {},
  incidentBusy = false,
}) {
  const byId = Object.fromEntries(configuredAgents.map((agent) => [agent.id, agent]));
  const ids = ["monitoring", "incident", "code", "cicd", "infrastructure", "security"];

  // Local state for on-demand individual agent testing
  const [testingId, setTestingId] = useState(null);
  const [testResults, setTestResults] = useState({});
  const [testErrors, setTestErrors] = useState({});

  const handleTestAgent = async (id) => {
    setTestingId(id);
    setTestErrors((prev) => ({ ...prev, [id]: null }));
    try {
      const res = await testSpecialistAgent(id);
      setTestResults((prev) => ({ ...prev, [id]: res }));
    } catch (err) {
      setTestErrors((prev) => ({
        ...prev,
        [id]: err instanceof Error ? err.message : "Inference test failed",
      }));
    } finally {
      setTestingId(null);
    }
  };

  return (
    <div className="agent-grid">
      {ids.map((id, index) => {
        const agent = byId[id];
        const assignedModel = agent?.model || defaultModels[id];

        // Incident result or single-agent test result
        const individualTest = testResults[id];
        const individualError = testErrors[id];
        const isRunning = testingId === id || (incidentBusy && !results[id] && !skipped[id]);

        const rawResult = individualTest || results[id];
        const skippedInfo = skipped[id] || (rawResult?.status === "skipped" ? rawResult : null);

        const status = resolveStatus(rawResult, skippedInfo, isRunning, false);

        const output =
          rawResult?.analysis?.summary ||
          rawResult?.summary ||
          rawResult?.validated_summary?.claim ||
          (skippedInfo ? `Skipped: ${skippedInfo.reason || "Not selected by dynamic workflow."}` : null) ||
          rawResult?.detail ||
          individualError ||
          "Agent is idle. Run an investigation or test individually.";

        const validation = validationFor(rawResult);
        const findings = rawResult?.validated_findings || rawResult?.analysis?.findings || rawResult?.findings || [];
        const duration = rawResult?.wall_duration_seconds;
        const evidenceCategories =
          rawResult?.evidence_delivery?.available_categories ||
          (rawResult?.deterministic_evidence ? Object.keys(rawResult.deterministic_evidence) : []);
        const errorDetail = individualError || rawResult?.detail || rawResult?.validation_error;

        return (
          <article className={`agent-card ${isRunning ? "agent-card-running" : ""}`} key={id}>
            <div className="agent-card-head">
              <span className={`agent-avatar avatar-${index}`}>{labels[id].slice(0, 1)}</span>
              <div className="agent-heading">
                <h3>{labels[id]}</h3>
                <span className="agent-model-tag">
                  <code>{assignedModel}</code>
                </span>
              </div>
              <span className={`pill ${statusPillClass(status)}`}>
                {isRunning ? (
                  <>
                    <span className="button-spinner mini" /> RUNNING
                  </>
                ) : (
                  status
                )}
              </span>
            </div>

            <p className="agent-role">{agent?.role || `Specialist for ${id} DevOps reasoning.`}</p>

            {/* Evidence received tags */}
            {evidenceCategories.length > 0 && (
              <div className="agent-evidence-tags">
                <span className="eyebrow">Evidence received:</span>
                <div className="tag-row">
                  {evidenceCategories.slice(0, 4).map((cat) => (
                    <span className="evidence-tag" key={cat}>
                      {cat}
                    </span>
                  ))}
                  {evidenceCategories.length > 4 && (
                    <span className="evidence-tag">+{evidenceCategories.length - 4} more</span>
                  )}
                </div>
              </div>
            )}

            {/* Output */}
            <div className="agent-output">
              <span className="eyebrow">Agent Output</span>
              <p className={skippedInfo ? "muted-copy" : ""}>{output}</p>
            </div>

            {/* Metadata (Duration, Validation, Status) */}
            <div className="agent-meta">
              <span>
                Duration:{" "}
                <strong>{Number.isFinite(duration) ? `${duration.toFixed(2)}s` : status === "SKIPPED" ? "0.00s" : "—"}</strong>
              </span>
              <span>
                Validation:{" "}
                <strong className={validation === "Unverified claims" ? "text-amber" : validation === "Verified" ? "text-green" : ""}>
                  {validation}
                </strong>
              </span>
            </div>

            {/* Error detail if failed or timeout */}
            {(status === "FAILED" || status === "TIMEOUT") && errorDetail && (
              <div className="agent-error-box">
                <span className="error-icon">!</span>
                <small>{errorDetail}</small>
              </div>
            )}

            {/* Validated Findings */}
            {Array.isArray(findings) && findings.length > 0 && (
              <details className="agent-findings">
                <summary>
                  {findings.length} finding{findings.length === 1 ? "" : "s"}
                </summary>
                {findings.map((finding, findingIndex) => (
                  <p key={`${id}-${findingIndex}`}>
                    <span
                      className={`validation-mark validation-${finding.validation_status || "advisory"}`}
                    />
                    {typeof finding === "string" ? finding : finding.claim || JSON.stringify(finding)}
                  </p>
                ))}
              </details>
            )}

            {/* Interactive individual agent test action */}
            <div className="agent-actions">
              <button
                className="button button-secondary button-sm"
                onClick={() => handleTestAgent(id)}
                disabled={testingId === id || incidentBusy}
              >
                {testingId === id ? (
                  <>
                    <span className="button-spinner mini" /> Running model…
                  </>
                ) : (
                  <>
                    <Icon name="arrow" size={12} /> Test Agent
                  </>
                )}
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );
}
