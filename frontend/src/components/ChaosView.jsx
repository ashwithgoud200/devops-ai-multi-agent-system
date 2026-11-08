import { useState, useEffect } from "react";
import Icon from "./Icon";
import {
  getChaosStatus,
  triggerCpuStress,
  triggerMemoryStress,
  injectChaosLatency,
  armChaosCrash,
  runChaosSecurityAudit,
  stopAllChaos,
  startIncident,
} from "../api";

export default function ChaosView({ onNavigate }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState("");
  const [cpuThreads, setCpuThreads] = useState(2);
  const [cpuDuration, setCpuDuration] = useState(15);
  const [memoryMb, setMemoryMb] = useState(250);
  const [memoryDuration, setMemoryDuration] = useState(15);
  const [latencySec, setLatencySec] = useState(0.45);
  const [latencyDuration, setLatencyDuration] = useState(20);
  const [crashMessage, setCrashMessage] = useState(
    "Real Chaos Exception: unhandled ZeroDivisionError in calculation pipeline"
  );

  const fetchStatus = async () => {
    try {
      const data = await getChaosStatus();
      setStatus(data);
    } catch (err) {
      console.error("Failed to fetch chaos status:", err);
    }
  };

  useEffect(() => {
    fetchStatus();
    const timer = setInterval(fetchStatus, 3000);
    return () => clearInterval(timer);
  }, []);

  const handleAction = async (fn, label) => {
    setLoading(true);
    setActionMessage("");
    try {
      const res = await fn();
      setActionMessage(`${label} successfully triggered!`);
      await fetchStatus();
    } catch (err) {
      setActionMessage(`Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleLaunchInvestigation = async () => {
    setLoading(true);
    try {
      let query = "Investigate live system telemetry anomalies, high resource utilization, and runtime exceptions.";
      if (status?.crash_mode_armed) {
        query = "Calculator application is throwing unhandled exceptions and crashing under request traffic.";
      } else if (status?.current_latency_seconds > 0) {
        query = "Analyze severe latency degradation and slow response times across calculator endpoints.";
      } else if (status?.cpu_workers_active > 0 || status?.memory_allocated_mb > 0) {
        query = "Investigate host container resource saturation, elevated CPU percent, and memory pressure.";
      }
      const res = await startIncident(query);
      if (onNavigate) {
        onNavigate("incidents");
      }
    } catch (err) {
      setActionMessage(`Failed to trigger incident investigation: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const host = status?.host_telemetry?.measurements || {};
  const isAnyChaosActive =
    (status?.active_experiments_count || 0) > 0 ||
    status?.crash_mode_armed ||
    status?.current_latency_seconds > 0;

  return (
    <div className="chaos-container">
      {/* Hero Header Card */}
      <section className="chaos-hero-card">
        <div className="chaos-hero-info">
          <span className="eyebrow">PHYSICAL FAULT INJECTION & RESILIENCE</span>
          <p>
            Replaces synthetic mocks with <strong>real physical OS and runtime faults</strong>. Spawns multi-threaded CPU
            burners, allocates physical RAM, injects real request latency, and triggers genuine Python exceptions.
          </p>
        </div>
        <div className="chaos-hero-actions">
          {isAnyChaosActive && (
            <button
              className="button button-danger"
              onClick={() => handleAction(stopAllChaos, "Stop All Chaos")}
              disabled={loading}
            >
              <Icon name="close" size={15} /> Stop All Chaos Experiments
            </button>
          )}
          <button className="button button-secondary" onClick={fetchStatus} disabled={loading}>
            <Icon className={loading ? "spin" : ""} name="refresh" size={15} /> Refresh Telemetry
          </button>
        </div>
      </section>

      {/* Live Physical Host Telemetry Banner */}
      <section className="chaos-telemetry-panel">
        <div className="chaos-panel-header">
          <h3>
            <Icon name="telemetry" size={18} /> Real Host Telemetry (Live OS Kernel)
          </h3>
          <span className={`pill ${isAnyChaosActive ? "pill-amber" : "pill-green"}`}>
            {isAnyChaosActive ? `Active Chaos (${status?.active_experiments_count} running)` : "System Nominal"}
          </span>
        </div>

        <div className="chaos-metrics-grid">
          <div className="chaos-metric-box">
            <div className="chaos-metric-label">Physical CPU Load</div>
            <div
              className="chaos-metric-value"
              style={{ color: (host.cpu_utilization_percent || 0) > 70 ? "#ef4444" : "#10b981" }}
            >
              {typeof host.cpu_utilization_percent === "number"
                ? `${host.cpu_utilization_percent.toFixed(1)}%`
                : "Reading..."}
            </div>
            <div className="chaos-metric-sub">
              {status?.cpu_workers_active ? `${status.cpu_workers_active} stress threads active` : "Idle OS load"}
            </div>
          </div>

          <div className="chaos-metric-box">
            <div className="chaos-metric-label">Physical Memory Used</div>
            <div
              className="chaos-metric-value"
              style={{ color: (host.memory_utilization_percent || 0) > 85 ? "#f59e0b" : "#10b981" }}
            >
              {typeof host.memory_utilization_percent === "number"
                ? `${host.memory_utilization_percent.toFixed(1)}%`
                : "Reading..."}
            </div>
            <div className="chaos-metric-sub">
              {status?.memory_allocated_mb
                ? `${status.memory_allocated_mb} MB chaos allocated`
                : "No artificial memory load"}
            </div>
          </div>

          <div className="chaos-metric-box">
            <div className="chaos-metric-label">HTTP Injected Delay</div>
            <div
              className="chaos-metric-value"
              style={{ color: status?.current_latency_seconds > 0 ? "#f59e0b" : "#10b981" }}
            >
              {status?.current_latency_seconds ? `${status.current_latency_seconds}s` : "0 ms"}
            </div>
            <div className="chaos-metric-sub">
              {status?.current_latency_seconds > 0 ? "Real I/O delay active" : "Baseline latency"}
            </div>
          </div>

          <div className="chaos-metric-box">
            <div className="chaos-metric-label">Application Crash Mode</div>
            <div
              className="chaos-metric-value"
              style={{ color: status?.crash_mode_armed ? "#ef4444" : "#10b981" }}
            >
              {status?.crash_mode_armed ? "ARMED" : "Nominal"}
            </div>
            <div className="chaos-metric-sub">
              {status?.crash_mode_armed ? "Exceptions throwing 500s" : "Normal handling"}
            </div>
          </div>
        </div>

        {actionMessage && (
          <div className="chaos-alert-banner">
            {actionMessage}
          </div>
        )}
      </section>

      {/* Chaos Triggers Grid */}
      <div className="chaos-cards-grid">
        {/* 1. Real CPU Stress */}
        <div className="chaos-experiment-card">
          <div>
            <div className="chaos-card-title">
              <span>🔥</span>
              <span>Real CPU Stress Worker</span>
            </div>
            <p className="chaos-card-desc">
              Spawns background arithmetic threads that actively calculate hashes/primes, genuinely elevating physical CPU percentage.
            </p>
          </div>

          <div className="chaos-input-group">
            <label className="chaos-label">
              <span>Threads:</span>
              <input
                type="number"
                min="1"
                max="8"
                value={cpuThreads}
                onChange={(e) => setCpuThreads(parseInt(e.target.value) || 2)}
                className="chaos-input"
              />
            </label>
            <label className="chaos-label">
              <span>Duration (s):</span>
              <input
                type="number"
                min="5"
                max="60"
                value={cpuDuration}
                onChange={(e) => setCpuDuration(parseInt(e.target.value) || 15)}
                className="chaos-input"
              />
            </label>
          </div>

          <button
            className="chaos-btn-warn"
            onClick={() => handleAction(() => triggerCpuStress(cpuDuration, cpuThreads), "CPU Stress")}
            disabled={loading}
          >
            Burn Real CPU ({cpuThreads} threads, {cpuDuration}s)
          </button>
        </div>

        {/* 2. Real Memory Pressure */}
        <div className="chaos-experiment-card">
          <div>
            <div className="chaos-card-title">
              <span>💾</span>
              <span>Real Memory Pressure</span>
            </div>
            <p className="chaos-card-desc">
              Allocates real non-zero bytearrays in RAM, forcing the OS kernel to commit real memory pages and elevating RAM usage.
            </p>
          </div>

          <div className="chaos-input-group">
            <label className="chaos-label">
              <span>RAM (MB):</span>
              <input
                type="number"
                min="50"
                max="500"
                step="50"
                value={memoryMb}
                onChange={(e) => setMemoryMb(parseInt(e.target.value) || 200)}
                className="chaos-input"
              />
            </label>
            <label className="chaos-label">
              <span>Duration (s):</span>
              <input
                type="number"
                min="5"
                max="60"
                value={memoryDuration}
                onChange={(e) => setMemoryDuration(parseInt(e.target.value) || 15)}
                className="chaos-input"
              />
            </label>
          </div>

          <button
            className="chaos-btn-warn"
            onClick={() => handleAction(() => triggerMemoryStress(memoryMb, memoryDuration), "Memory Pressure")}
            disabled={loading}
          >
            Allocate {memoryMb} MB Physical RAM ({memoryDuration}s)
          </button>
        </div>

        {/* 3. Real HTTP Latency */}
        <div className="chaos-experiment-card">
          <div>
            <div className="chaos-card-title">
              <span>⏱️</span>
              <span>Real Request Latency Delay</span>
            </div>
            <p className="chaos-card-desc">
              Injects real delays into request pipelines, driving up Prometheus latency histograms and OpenTelemetry trace spans.
            </p>
          </div>

          <div className="chaos-input-group">
            <label className="chaos-label">
              <span>Delay (s):</span>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="3.0"
                value={latencySec}
                onChange={(e) => setLatencySec(parseFloat(e.target.value) || 0.45)}
                className="chaos-input"
              />
            </label>
            <label className="chaos-label">
              <span>Duration (s):</span>
              <input
                type="number"
                min="5"
                max="60"
                value={latencyDuration}
                onChange={(e) => setLatencyDuration(parseInt(e.target.value) || 20)}
                className="chaos-input"
              />
            </label>
          </div>

          <button
            className="chaos-btn-warn"
            onClick={() => handleAction(() => injectChaosLatency(latencySec, latencyDuration), "Latency Injection")}
            disabled={loading}
          >
            Inject {latencySec}s Request Delay ({latencyDuration}s)
          </button>
        </div>

        {/* 4. Real App Crash & Exception */}
        <div className="chaos-experiment-card wide-card">
          <div>
            <div className="chaos-card-title">
              <span>💥</span>
              <span>Real Application Crash & Exception</span>
            </div>
            <p className="chaos-card-desc">
              Arms the Calculator service to raise genuine unhandled Python exceptions, logging real stack traces to <code>logs/app.log</code> and Loki.
            </p>
          </div>

          <label className="chaos-label">
            <span>Exception Message:</span>
            <input
              type="text"
              value={crashMessage}
              onChange={(e) => setCrashMessage(e.target.value)}
              className="chaos-input"
            />
          </label>

          <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.5rem" }}>
            <button
              className="chaos-btn-danger"
              style={{ flex: 1 }}
              onClick={() => handleAction(() => armChaosCrash(true, crashMessage), "Arm Crash Mode")}
              disabled={loading || status?.crash_mode_armed}
            >
              Arm Real 500 Crash Mode
            </button>
            {status?.crash_mode_armed && (
              <button
                className="chaos-btn-ghost"
                onClick={() => handleAction(() => armChaosCrash(false), "Disarm Crash Mode")}
                disabled={loading}
              >
                Disarm Crash Mode
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Investigation Bridge Footer */}
      <div className="chaos-bridge-panel">
        <div className="chaos-bridge-info">
          <h4>🤖 Trigger Multi-Agent AI Investigation on Live Telemetry</h4>
          <p>
            The Supervisor and Specialist Agents will analyze live Prometheus metrics, query Loki logs for real tracebacks,
            and query Box 5 RAG runbooks to remediate the real issue.
          </p>
        </div>
        <button
          className="button button-primary"
          style={{ whiteSpace: "nowrap", padding: "0.6rem 1.25rem" }}
          onClick={handleLaunchInvestigation}
          disabled={loading}
        >
          Diagnose Live Incident with AI →
        </button>
      </div>
    </div>
  );
}
