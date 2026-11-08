import { classifyStatus, collectSeries, linePoints } from "./metricsData.js";

export { classifyStatus, collectSeries, linePoints };

export function RequestTrend({ metrics }) {
  const seriesData = collectSeries(metrics);
  const points = seriesData?.points;
  const hasStatus = Boolean(seriesData?.hasStatus);

  if (!points || !points.length) {
    return (
      <div className="chart-empty">
        <span className="empty-dot" />
        Request-rate trend unavailable
        <small>{metrics?.metrics?.request_rate?.detail || "No fresh Prometheus samples were returned."}</small>
      </div>
    );
  }

  const max = Math.max(
    0.01,
    ...points.flatMap((point) => (hasStatus ? [point.success, point.failed] : [point.total]))
  );

  return (
    <div className="chart-wrap">
      <div className="chart-legend">
        {hasStatus ? (
          <>
            <span><i className="legend-success" />Successful</span>
            <span><i className="legend-failed" />Failed</span>
          </>
        ) : (
          <span><i className="legend-total" />Total requests</span>
        )}
        <span className="chart-window">Last 5 minutes · requests/sec</span>
      </div>
      <svg className="trend-chart" viewBox="0 0 640 190" role="img" aria-label="Prometheus request rate over time">
        {[0, 1, 2, 3].map((line) => (
          <line key={line} x1="0" x2="640" y1={25 + line * 48} y2={25 + line * 48} className="chart-gridline" />
        ))}
        {hasStatus ? (
          <>
            <polyline points={linePoints(points, "success", 640, 155, max)} transform="translate(0 15)" className="chart-success" />
            <polyline points={linePoints(points, "failed", 640, 155, max)} transform="translate(0 15)" className="chart-failed" />
          </>
        ) : (
          <polyline points={linePoints(points, "total", 640, 155, max)} transform="translate(0 15)" className="chart-total" />
        )}
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
