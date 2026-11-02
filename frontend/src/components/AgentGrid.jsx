const labels = {
  monitoring: "Monitoring",
  incident: "Incident",
  code: "Code",
  cicd: "CI/CD",
  infrastructure: "Infrastructure",
  security: "Security",
};

function validationFor(result) {
  const statuses = [
    result?.validated_summary?.validation_status,
    ...(result?.validated_findings || []).map((finding) => finding.validation_status),
  ].filter(Boolean);
  if (!statuses.length) return "Not available";
  if (statuses.includes("unverified")) return "Unverified claims";
  if (statuses.includes("verified")) return "Verified";
  return statuses[0];
}

export default function AgentGrid({ configuredAgents = [], results = {} }) {
  const byId = Object.fromEntries(configuredAgents.map((agent) => [agent.id, agent]));
  const ids = ["monitoring", "incident", "code", "cicd", "infrastructure", "security"];
  return (
    <div className="agent-grid">
      {ids.map((id, index) => {
        const agent = byId[id];
        const result = results[id];
        const status = result?.status || (agent ? "not selected" : "configuration unavailable");
        const output = result?.analysis?.summary
          || result?.validated_summary?.claim
          || result?.detail
          || "This agent has not returned an output for the selected incident.";
        const validation = validationFor(result);
        const findings = result?.validated_findings || [];
        return (
          <article className="agent-card" key={id}>
            <div className="agent-card-head">
              <span className={`agent-avatar avatar-${index}`}>{labels[id].slice(0, 1)}</span>
              <div className="agent-heading">
                <h3>{labels[id]}</h3>
                <span>{agent?.model || "Model assignment unavailable"}</span>
              </div>
              <span className={`pill ${status === "ok" ? "pill-green" : status === "not selected" ? "pill-muted" : "pill-amber"}`}>{status}</span>
            </div>
            <p className="agent-role">{agent?.role || "Configured specialist role is unavailable."}</p>
            <div className="agent-output">
              <span className="eyebrow">Latest output</span>
              <p>{output}</p>
            </div>
            <div className="agent-meta">
              <span>Duration <strong>{Number.isFinite(result?.wall_duration_seconds) ? `${result.wall_duration_seconds.toFixed(2)}s` : "—"}</strong></span>
              <span>Validation <strong className={validation === "Unverified claims" ? "text-amber" : ""}>{validation}</strong></span>
            </div>
            {findings.length > 0 && (
              <details className="agent-findings">
                <summary>{findings.length} validated finding{findings.length === 1 ? "" : "s"}</summary>
                {findings.map((finding, findingIndex) => (
                  <p key={`${id}-${findingIndex}`}>
                    <span className={`validation-mark validation-${finding.validation_status || "advisory"}`} />
                    {finding.claim}
                  </p>
                ))}
              </details>
            )}
          </article>
        );
      })}
    </div>
  );
}
