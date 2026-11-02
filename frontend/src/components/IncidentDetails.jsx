import { formatTimestamp } from "../api.js";

function valueText(value) {
  if (value === null || value === undefined || value === "") return "Not available";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function EvidenceCard({ title, data }) {
  const status = data?.status || "unavailable";
  const detail = data?.detail || data?.source || "No additional detail supplied.";
  return (
    <article className="evidence-card">
      <div className="evidence-heading">
        <h4>{title}</h4>
        <span className={`pill ${status === "ok" ? "pill-green" : status === "partial" ? "pill-amber" : "pill-muted"}`}>{status}</span>
      </div>
      <p>{detail}</p>
      {data?.events?.length > 0 && (
        <ul className="evidence-list">{data.events.slice(-4).reverse().map((event, index) => <li key={index}><b>{event.level || "LOG"}</b> {event.msg || event.message || valueText(event)}</li>)}</ul>
      )}
      {data?.metrics && <pre className="evidence-json">{valueText(data.metrics)}</pre>}
    </article>
  );
}

export function IncidentTimeline({ incident }) {
  const steps = [
    ["Evidence collected", Boolean(incident?.evidence)],
    ["Diagnosis completed", Boolean(incident?.diagnosis)],
    ["Human decision", incident?.status === "pending_approval" || Boolean(incident?.outcome)],
    ["Action outcome", Boolean(incident?.outcome)],
  ];
  return (
    <div className="lifecycle">
      {steps.map(([label, complete], index) => (
        <div className={`lifecycle-step ${complete ? "complete" : ""}`} key={label}>
          <span className="lifecycle-node">{complete ? "✓" : index + 1}</span>
          <span>{label}</span>
        </div>
      ))}
    </div>
  );
}

export default function IncidentDetails({ incident, onSelectIncident, history = [] }) {
  if (!incident) {
    return (
      <section className="panel empty-panel">
        <div className="empty-icon">!</div>
        <h3>No incident selected</h3>
        <p>Submit an incident investigation to collect live telemetry and specialist analysis.</p>
        {history.length > 0 && (
          <label className="select-incident">
            Recent incident
            <select onChange={(event) => onSelectIncident(event.target.value)} defaultValue="">
              <option value="" disabled>Select an incident</option>
              {history.map((item) => <option value={item.incident_id} key={item.incident_id}>{item.incident_id.slice(0, 8)} · {item.status}</option>)}
            </select>
          </label>
        )}
      </section>
    );
  }
  const diagnosis = incident.diagnosis || {};
  const evidence = incident.evidence || {};
  const hypotheses = diagnosis.hypotheses || [];
  const observations = diagnosis.verified_observations || diagnosis.verified_observed_facts || [];
  const remediation = incident.proposed_remediation || incident.report?.recommended_remediation;

  return (
    <div className="incident-detail">
      <section className="panel incident-summary">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Incident investigation</span>
            <h2>{incident.incident_id}</h2>
          </div>
          <span className={`pill ${incident.status === "pending_approval" ? "pill-amber" : incident.status === "completed" ? "pill-green" : "pill-muted"}`}>{incident.status || "unknown"}</span>
        </div>
        <p className="incident-query">{incident.query || "Incident query is not present in the API response."}</p>
        <IncidentTimeline incident={incident} />
        {diagnosis.summary && <div className="diagnosis-callout"><span className="eyebrow">Diagnosis summary · hypothesis, not proof</span><p>{diagnosis.summary}</p></div>}
        {incident.outcome && <div className={`outcome-callout outcome-${incident.outcome.status || "unknown"}`}><strong>Outcome: {incident.outcome.status}</strong><p>{incident.outcome.reason || incident.outcome.rollback?.data?.rolled_back_to || incident.outcome.rollback?.detail || "Workflow returned an outcome."}</p></div>}
        {remediation && <div className="remediation-inline"><span className="eyebrow">Proposed action</span><strong>{remediation.action}{remediation.target_version ? ` → v${remediation.target_version}` : ""}</strong><p>{remediation.rationale || "No rationale supplied."}</p></div>}
      </section>

      <section className="panel">
        <div className="section-heading">
          <div><span className="eyebrow">Observed data</span><h2>Evidence collected</h2></div>
          <span className="subtle-count">{Object.keys(evidence).length} sources</span>
        </div>
        <div className="evidence-grid">
          <EvidenceCard title="Application metrics" data={evidence.metrics} />
          <EvidenceCard title="Application logs" data={evidence.logs} />
          <EvidenceCard title="Prometheus" data={evidence.prometheus} />
          <EvidenceCard title="Application health" data={evidence.health} />
          <EvidenceCard title="Deployment history" data={evidence.version} />
        </div>
        <div className="claim-block">
          <div className="claim-heading"><h3>Verified observations</h3><span className="pill pill-green">Evidence-backed</span></div>
          {observations.length ? observations.map((item, index) => (
            <div className="claim-row" key={`observation-${index}`}>
              <span className="validation-mark validation-verified" />
              <div><p>{item.statement || item.description || item.claim || valueText(item)}</p><small>{item.source || item.evidence_id || "Deterministic evidence"}</small></div>
            </div>
          )) : <p className="muted-copy">No verified observations were returned.</p>}
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div><span className="eyebrow">Advisory analysis</span><h2>Root-cause hypotheses</h2></div>
          <span className="pill pill-amber">Not established facts</span>
        </div>
        {hypotheses.length ? (
          <div className="hypothesis-list">
            {hypotheses.map((item, index) => (
              <article className="hypothesis-card" key={`hypothesis-${index}`}>
                <div className="hypothesis-status"><span className={`validation-mark validation-${item.validation_status || "advisory"}`} />{item.validation_status || item.hypothesis_type || "advisory"}</div>
                <p>{item.statement || item.claim || valueText(item)}</p>
                <div className="hypothesis-meta">
                  <span>{item.source || "Incident analysis"}</span>
                  {Number.isFinite(item.confidence) && <span>Confidence {(item.confidence * 100).toFixed(0)}% · not proof</span>}
                </div>
                {item.validation_reasons?.length > 0 && <small>{item.validation_reasons.join(" ")}</small>}
              </article>
            ))}
          </div>
        ) : <p className="muted-copy">No root-cause hypotheses were returned.</p>}
      </section>
      <p className="incident-created">Incident {incident.incident_id} · response received {formatTimestamp(incident.timestamp)}</p>
    </div>
  );
}
