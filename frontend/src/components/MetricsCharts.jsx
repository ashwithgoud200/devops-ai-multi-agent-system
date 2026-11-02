function collectSeries(metrics) {
  const observations = metrics?.metrics?.request_rate?.observations;
  if (!Array.isArray(observations)) return null;
  const grouped = new Map();
  for (const series of observations) {
    const status = series.labels?.status;
    if (!["ok", "error", "client_error"].includes(status)) continue;
    for (const point of series.values || []) {
      if (point.stale || !Number.isFinite(point.timestamp) || !Number.isFinite(point.value)) continue;
      const sample = grouped.get(point.timestamp) || { timestamp: point.timestamp, success: 0, failed: 0 };
      if (status === "ok") sample.success += point.value;
      else sample.failed += point.value;
      grouped.set(point.timestamp, sample);
    }
  }
  const points = [...grouped.values()].sort((a, b) => a.timestamp - b.timestamp);
  return points.length ? points : null;
}

function linePoints(points, key, width, height, max) {
  if (points.length === 1) return `${width / 2},${height - (points[0][key] / max) * height}`;
  return points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - (point[key] / max) * height;
      return `${x},${y}`;
    })
    .join(" ");
}

export function RequestTrend({ metrics }) {
  const points = collectSeries(metrics);
  if (!points) {
    return (
      <div className="chart-empty">
        <span className="empty-dot" />
        Request-rate trend unavailable
        <small>{metrics?.metrics?.request_rate?.detail || "No fresh Prometheus samples were returned."}</small>
      </div>
    );
  }
  const max = Math.max(0.01, ...points.flatMap((point) => [point.success, point.failed]));
  return (
    <div className="chart-wrap">
      <div className="chart-legend">
        <span><i className="legend-success" />Successful</span>
        <span><i className="legend-failed" />Failed</span>
        <span className="chart-window">Last 5 minutes · requests/sec</span>
      </div>
      <svg className="trend-chart" viewBox="0 0 640 190" role="img" aria-label="Prometheus request success and failure rate over time">
        {[0, 1, 2, 3].map((line) => <line key={line} x1="0" x2="640" y1={25 + line * 48} y2={25 + line * 48} className="chart-gridline" />)}
        <polyline points={linePoints(points, "success", 640, 155, max)} transform="translate(0 15)" className="chart-success" />
        <polyline points={linePoints(points, "failed", 640, 155, max)} transform="translate(0 15)" className="chart-failed" />
      </svg>
      <div className="chart-axis"><span>Oldest sample</span><span>Latest sample</span></div>
    </div>
  );
}

export function MetricBars({ counters }) {
  if (!counters) return <p className="muted-copy">Application metrics are unavailable.</p>;
  const maximum = Math.max(counters.successful, counters.failed, 1);
  return (
    <div className="metric-bars">
      <div className="bar-row">
        <div><span>Successful</span><strong>{counters.successful.toLocaleString()}</strong></div>
        <div className="bar-track"><span className="bar-success" style={{ width: `${(counters.successful / maximum) * 100}%` }} /></div>
      </div>
      <div className="bar-row">
        <div><span>Failed</span><strong>{counters.failed.toLocaleString()}</strong></div>
        <div className="bar-track"><span className="bar-failed" style={{ width: `${(counters.failed / maximum) * 100}%` }} /></div>
      </div>
    </div>
  );
}
