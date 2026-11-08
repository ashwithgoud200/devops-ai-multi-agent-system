export function classifyStatus(status) {
  if (status === undefined || status === null || String(status).trim() === "") {
    return "unlabelled";
  }
  const s = String(status).trim().toLowerCase();
  if (s === "ok" || s === "200" || /^2\d\d$/.test(s)) {
    return "success";
  }
  if (
    s === "error" ||
    s === "client_error" ||
    s === "500" ||
    /^5\d\d$/.test(s) ||
    /^4\d\d$/.test(s)
  ) {
    return "failed";
  }
  return "other";
}

export function collectSeries(metrics) {
  const observations = metrics?.metrics?.request_rate?.observations;
  if (!Array.isArray(observations) || observations.length === 0) return null;

  // Determine if status information is present across the observations
  const hasStatusInfo = observations.some((series) => {
    const kind = classifyStatus(series?.labels?.status);
    return kind === "success" || kind === "failed" || kind === "other";
  });

  const grouped = new Map();

  for (const series of observations) {
    const kind = classifyStatus(series?.labels?.status);

    for (const point of series?.values || []) {
      if (point.stale || !Number.isFinite(point.timestamp) || !Number.isFinite(point.value)) {
        continue;
      }
      const sample = grouped.get(point.timestamp) || {
        timestamp: point.timestamp,
        total: 0,
        success: 0,
        failed: 0,
      };

      sample.total += point.value;
      if (hasStatusInfo) {
        if (kind === "success") {
          sample.success += point.value;
        } else {
          sample.failed += point.value;
        }
      }

      grouped.set(point.timestamp, sample);
    }
  }

  const points = [...grouped.values()].sort((a, b) => a.timestamp - b.timestamp);
  if (!points.length) return null;

  return { points, hasStatus: hasStatusInfo };
}

export function linePoints(points, key, width, height, max) {
  if (points.length === 1) return `${width / 2},${height - (points[0][key] / max) * height}`;
  return points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - (point[key] / max) * height;
      return `${x},${y}`;
    })
    .join(" ");
}

