import { formatTimestamp } from "../api.js";

const eventLabels = {
  incident_started: "Incident started",
  diagnosis_finished: "Diagnosis completed",
  approval_decision: "Approval decision",
  action_finished: "Action finished",
  baseline_saved: "Baseline saved",
};

export default function AuditLog({ events = [], onSelectIncident }) {
  if (!events.length) {
    return <div className="empty-state"><h3>No audit events available</h3><p>The API has not returned any audit records.</p></div>;
  }
  return (
    <div className="audit-table-wrap">
      <table className="audit-table">
        <thead><tr><th>Event</th><th>Incident</th><th>Decision / result</th><th>Target</th><th>Timestamp</th></tr></thead>
        <tbody>
          {[...events].reverse().map((event, index) => (
            <tr key={`${event.incident_id}-${event.event}-${event.timestamp}-${index}`}>
              <td><span className="audit-event-dot" />{eventLabels[event.event] || event.event || "Unknown event"}</td>
              <td><button className="text-button mono" onClick={() => onSelectIncident(event.incident_id)}>{event.incident_id?.slice(0, 12) || "—"}</button></td>
              <td>{event.decision || event.outcome_status || event.status || event.action || "—"}</td>
              <td>{event.target_version ? `v${event.target_version}` : "—"}</td>
              <td>{formatTimestamp(event.timestamp)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="audit-footnote">Audit entries are the API’s local metadata-only records. Reviewer labels are self-reported, not authenticated identities.</p>
    </div>
  );
}
