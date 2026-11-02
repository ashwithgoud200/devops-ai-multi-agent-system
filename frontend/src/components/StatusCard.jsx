export default function StatusCard({
  label,
  value,
  detail,
  icon,
  tone = "neutral",
}) {
  return (
    <article className={`status-card tone-${tone}`}>
      <div className="status-card-top">
        <span className="eyebrow">{label}</span>
        <span className="status-card-icon">{icon}</span>
      </div>
      <strong className="status-card-value">{value}</strong>
      <span className="status-card-detail">{detail}</span>
    </article>
  );
}
