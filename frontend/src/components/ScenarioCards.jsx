import { useState, useEffect } from "react";
import { getScenarios, activateScenario, resetScenario } from "../api.js";
import Icon from "./Icon.jsx";

const FALLBACK_SCENARIOS = [
  {
    id: "DEPLOYMENT_REGRESSION",
    name: "Scenario 1: Deployment Regression",
    description: "Calculator v1.1 release with faulty division handler throwing HTTP 500.",
    symptoms: [
      "Division endpoint (/calc/div) returns HTTP 500",
      "Division handler raises ZeroDivisionError/ValueError exception",
      "Elevated HTTP 5xx error rate in Prometheus",
      "Version history confirms v1.0 followed by v1.1 release",
    ],
    expected_agents: ["Monitoring Agent", "Incident Agent", "Code/Repository Agent", "CI/CD Agent", "Infrastructure Agent"],
    remediation_action: "Rollback Calculator from v1.1 to v1.0",
    sample_query: "Investigate elevated HTTP 500 errors and division handler crash following the version 1.1 deployment.",
  },
  {
    id: "PERFORMANCE_DRIFT",
    name: "Scenario 2: Performance and Metric Drift",
    description: "High calculator request volume and 450ms injected latency spike.",
    symptoms: [
      "Significant increase in calculator request rate",
      "P95 response latency spike (+450ms synthetic delay)",
      "Elevated CPU utilization under simulated traffic",
      "Latency divergence when compared against baseline snapshot",
    ],
    expected_agents: ["Monitoring Agent", "Incident Agent", "Infrastructure Agent", "Code/Repository Agent"],
    remediation_action: "Rate limiting and performance optimization review",
    sample_query: "Analyze calculator request rates, latency spikes, and anomalous HTTP error distributions against baseline.",
  },
  {
    id: "INFRASTRUCTURE_FAILURE",
    name: "Scenario 3: Infrastructure and Container Health",
    description: "Simulated container memory/CPU pressure, scrape target down, and degraded health.",
    symptoms: [
      "Application health-check reports degraded / infrastructure warning",
      "Simulated container memory / CPU pressure",
      "Prometheus scrape target readiness alerts",
      "Host telemetry degradation",
    ],
    expected_agents: ["Infrastructure Agent", "Monitoring Agent", "Incident Agent"],
    remediation_action: "Safe service restart and container health check",
    sample_query: "Check Docker container health, host memory and CPU utilization, and Prometheus scrape target readiness.",
  },
  {
    id: "SECURITY_AUDIT",
    name: "Scenario 4: DevSecOps Security Audit",
    description: "Offline ingestion of Trivy CVEs, Semgrep SAST flaws, and TruffleHog test secrets.",
    symptoms: [
      "Trivy reports HIGH CVE-2024-21626 in runc container runtime",
      "Semgrep reports HIGH SQL injection flaw in auth helper",
      "TruffleHog reports mock API key in test configuration",
      "Clearly isolated synthetic findings without production secrets",
    ],
    expected_agents: ["Security Agent", "CI/CD Agent", "Code/Repository Agent"],
    remediation_action: "Security patch review and mock credential rotation",
    sample_query: "Review recent build artifacts for container image CVEs, static code vulnerabilities, and leaked secrets.",
  },
  {
    id: "GENERAL_INCIDENT",
    name: "Scenario 5: General Natural-Language Incident",
    description: "Ambiguous production incident query engaging all six specialist models.",
    symptoms: [
      "Broad natural-language incident symptom description",
      "Full cross-domain multi-agent investigation",
      "Independent analysis from Monitoring, Incident, Code, CI/CD, Infra, Security",
      "Synthesized root-cause correlation without duplicate reporting",
    ],
    expected_agents: [
      "Monitoring (qwen2.5:3b)",
      "Incident (llama3.2:3b)",
      "Code (qwen2.5-coder:3b)",
      "CI/CD (stablelm-zephyr:3b)",
      "Infrastructure (phi3.5:3.8b)",
      "Security (granite3.1-dense:2b)",
    ],
    remediation_action: "Full multi-agent synthesized remediation",
    sample_query: "Calculator is throwing errors. What is wrong and how do we fix it?",
  },
];

export default function ScenarioCards({ onRunInvestigation }) {
  const [scenarios, setScenarios] = useState(FALLBACK_SCENARIOS);
  const [activeScenarioId, setActiveScenarioId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);

  const fetchStatus = async () => {
    try {
      const res = await getScenarios();
      if (res && res.scenarios) {
        setScenarios(res.scenarios);
        setActiveScenarioId(res.active_scenario || null);
      }
    } catch {
      // fallback scenarios are preserved
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleActivate = async (scenarioId) => {
    setLoading(true);
    setActionMessage(null);
    try {
      const res = await activateScenario(scenarioId);
      setActiveScenarioId(res.active_scenario || scenarioId);
      setActionMessage({ type: "success", text: `Activated ${res.name || scenarioId}. Fault is now active.` });
    } catch (err) {
      setActionMessage({ type: "error", text: err.message || "Failed to activate scenario." });
    } finally {
      setLoading(false);
      fetchStatus();
    }
  };

  const handleReset = async (scenarioId) => {
    setLoading(true);
    setActionMessage(null);
    try {
      const target = scenarioId || "active";
      await resetScenario(target);
      setActiveScenarioId(null);
      setActionMessage({ type: "success", text: "Scenario reset. System returned to normal operating state." });
    } catch (err) {
      setActionMessage({ type: "error", text: err.message || "Failed to reset scenario." });
    } finally {
      setLoading(false);
      fetchStatus();
    }
  };

  const handleCopyPrompt = (scenario) => {
    const text = scenario.sample_query || scenario.sample_queries?.[0];
    if (text) {
      navigator.clipboard.writeText(text);
      setCopiedId(scenario.id);
      setTimeout(() => setCopiedId(null), 2000);
    }
  };

  const handleInvestigate = (scenario) => {
    const text = scenario.sample_query || scenario.sample_queries?.[0];
    if (onRunInvestigation && text) {
      onRunInvestigation(text);
    }
  };

  return (
    <div className="scenarios-container">
      <div className="panel scenario-header-panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">DETERMINISTIC FAULT INJECTION ENGINE</span>
            <h2>Synthetic Incident Scenarios</h2>
            <p className="scenario-subhead">
              Simulate realistic production failures, test natural-language scenario detection, and verify six-agent cross-domain investigations.
            </p>
          </div>
          <div className="scenario-header-actions">
            {activeScenarioId ? (
              <button
                className="button button-danger"
                disabled={loading}
                onClick={() => handleReset(activeScenarioId)}
              >
                Reset Active Fault ({activeScenarioId})
              </button>
            ) : (
              <span className="pill pill-green">All Scenarios Normal</span>
            )}
          </div>
        </div>

        {actionMessage && (
          <div className={`scenario-banner ${actionMessage.type === "success" ? "banner-success" : "banner-error"}`}>
            <span>{actionMessage.type === "success" ? "✓" : "!"}</span>
            <span>{actionMessage.text}</span>
          </div>
        )}
      </div>

      <div className="scenario-card-grid">
        {scenarios.map((sc) => {
          const isActive = activeScenarioId === sc.id;
          const queryText = sc.sample_query || sc.sample_queries?.[0];
          return (
            <article
              key={sc.id}
              className={`panel scenario-card ${isActive ? "scenario-active-card" : ""}`}
            >
              <div className="scenario-card-header">
                <div>
                  <span className="eyebrow">{sc.id}</span>
                  <h3>{sc.name}</h3>
                </div>
                <span className={`pill ${isActive ? "pill-amber" : "pill-muted"}`}>
                  {isActive ? "ACTIVE FAULT" : "INACTIVE"}
                </span>
              </div>

              <p className="scenario-desc">{sc.description}</p>

              <div className="scenario-section">
                <span className="eyebrow">Observable Symptoms:</span>
                <ul className="scenario-symptoms">
                  {(sc.symptoms || []).map((symptom, i) => (
                    <li key={i}>{symptom}</li>
                  ))}
                </ul>
              </div>

              <div className="scenario-section">
                <span className="eyebrow">Engaged Specialist Agents:</span>
                <div className="scenario-agents">
                  {(sc.expected_agents || []).map((agent, i) => (
                    <span key={i} className="agent-badge">
                      {agent}
                    </span>
                  ))}
                </div>
              </div>

              <div className="scenario-section">
                <span className="eyebrow">Proposed Safe Remediation:</span>
                <p className="scenario-remediation">
                  <strong>{sc.remediation_action || sc.recommended_remediation}</strong>
                </p>
              </div>

              <div className="scenario-prompt-box">
                <span className="eyebrow">Investigation Prompt:</span>
                <code className="scenario-prompt-code">{queryText}</code>
              </div>

              <div className="scenario-card-actions">
                {isActive ? (
                  <button
                    className="button button-danger button-sm"
                    disabled={loading}
                    onClick={() => handleReset(sc.id)}
                  >
                    Reset Fault
                  </button>
                ) : (
                  <button
                    className="button button-primary button-sm"
                    disabled={loading}
                    onClick={() => handleActivate(sc.id)}
                  >
                    Activate Fault
                  </button>
                )}

                <button
                  className="button button-secondary button-sm"
                  onClick={() => handleCopyPrompt(sc)}
                >
                  {copiedId === sc.id ? "✓ Copied" : "Copy Prompt"}
                </button>

                <button
                  className="button button-secondary button-sm"
                  onClick={() => handleInvestigate(sc)}
                >
                  Investigate →
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

