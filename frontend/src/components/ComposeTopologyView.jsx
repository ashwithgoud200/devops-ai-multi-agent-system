import Icon from "./Icon.jsx";

export default function ComposeTopologyView({ topologyData }) {
  if (!topologyData) {
    return (
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">DOCKER COMPOSE TOPOLOGY</span>
            <h2>Service Architecture & Containers</h2>
          </div>
        </div>
        <div className="inline-empty">Loading Docker Compose service topology…</div>
      </section>
    );
  }

  const { services = {}, downstream_impact = {}, docker_available = false } = topologyData;
  const serviceEntries = Object.entries(services);

  return (
    <section className="panel compose-topology-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">DOCKER COMPOSE TOPOLOGY</span>
          <h2>Configured Services & Live Container Health</h2>
        </div>
        <div className="topology-badge-row">
          <span className={`pill ${docker_available ? "pill-green" : "pill-muted"}`}>
            Docker Engine {docker_available ? "Active" : "Unavailable on Host"}
          </span>
          <span className="pill pill-blue">{serviceEntries.length} Configured Services</span>
        </div>
      </div>

      <div className="compose-grid">
        {serviceEntries.map(([name, svc]) => {
          const isUp = svc.live_status === "running";
          const downstream = downstream_impact[name] || [];
          return (
            <article className="compose-card" key={name}>
              <div className="compose-card-head">
                <span className={`service-dot ${isUp ? "is-up" : "is-down"}`} />
                <div className="compose-title">
                  <strong>{svc.container_name || name}</strong>
                  <small>{svc.service_name}</small>
                </div>
                <span className={`pill ${isUp ? "pill-green" : "pill-muted"}`}>
                  {svc.live_status}
                </span>
              </div>

              <div className="compose-meta">
                <div>
                  <span className="eyebrow">Ports:</span>
                  <code>{svc.ports?.join(", ") || "internal"}</code>
                </div>
                <div>
                  <span className="eyebrow">Healthcheck:</span>
                  <span>{svc.has_healthcheck ? "Configured" : "None"}</span>
                </div>
                {svc.live_cpu != null && (
                  <div>
                    <span className="eyebrow">CPU:</span>
                    <span>{svc.live_cpu}%</span>
                  </div>
                )}
                {svc.live_memory && (
                  <div>
                    <span className="eyebrow">Memory:</span>
                    <span>{svc.live_memory}</span>
                  </div>
                )}
              </div>

              {svc.dependencies?.length > 0 && (
                <div className="compose-deps">
                  <span className="eyebrow">Depends On:</span>
                  <div className="tag-row">
                    {svc.dependencies.map((dep) => (
                      <span className="dep-tag" key={dep}>
                        ← {dep}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {downstream.length > 0 && (
                <div className="compose-impact">
                  <span className="eyebrow">Downstream Impact If Degraded:</span>
                  <div className="tag-row">
                    {downstream.map((down) => (
                      <span className="impact-tag" key={down}>
                        → {down}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

