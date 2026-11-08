import { useEffect, useState } from "react";
import {
  getChatOpsStatus,
  getChatOpsHistory,
  dispatchChatOps,
  sendChatOpsInteraction,
  updateChatOpsConfig,
  sendChatOpsTestPing,
} from "../api.js";
import Icon from "./Icon.jsx";

export default function ChatOpsView() {
  const [status, setStatus] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actionError, setActionError] = useState("");
  const [feedbackMsg, setFeedbackMsg] = useState("");

  // Config form state
  const [showConfig, setShowConfig] = useState(false);
  const [slackUrl, setSlackUrl] = useState("");
  const [discordUrl, setDiscordUrl] = useState("");
  const [genericUrl, setGenericUrl] = useState("");
  const [savingConfig, setSavingConfig] = useState(false);

  // Manual dispatch form state
  const [showDispatch, setShowDispatch] = useState(false);
  const [dispatchTitle, setDispatchTitle] = useState("");
  const [dispatchSummary, setDispatchSummary] = useState("");
  const [dispatchSeverity, setDispatchSeverity] = useState("warning");
  const [dispatchType, setDispatchType] = useState("incident_alert");
  const [dispatchIncidentId, setDispatchIncidentId] = useState("");
  const [dispatchActionable, setDispatchActionable] = useState(false);
  const [dispatching, setDispatching] = useState(false);

  // Active platform preview tab for cards
  const [previewPlatform, setPreviewPlatform] = useState("slack");

  const loadData = async (silent = false) => {
    if (!silent) setRefreshing(true);
    setActionError("");
    try {
      const [statRes, histRes] = await Promise.all([
        getChatOpsStatus(),
        getChatOpsHistory(50),
      ]);
      setStatus(statRes);
      setHistory(histRes || []);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to load ChatOps telemetry");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(() => loadData(true), 15000);
    return () => clearInterval(interval);
  }, []);

  const handleSaveConfig = async (e) => {
    e.preventDefault();
    setSavingConfig(true);
    setActionError("");
    try {
      const res = await updateChatOpsConfig({
        slack_url: slackUrl,
        discord_url: discordUrl,
        generic_url: genericUrl,
      });
      setStatus(res);
      setFeedbackMsg("ChatOps webhook endpoints updated successfully.");
      setShowConfig(false);
      setTimeout(() => setFeedbackMsg(""), 4000);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to update configuration");
    } finally {
      setSavingConfig(false);
    }
  };

  const handleTestPing = async () => {
    setRefreshing(true);
    setActionError("");
    try {
      await sendChatOpsTestPing();
      setFeedbackMsg("Test notification dispatched across channels.");
      await loadData(true);
      setTimeout(() => setFeedbackMsg(""), 4000);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Test ping failed");
    } finally {
      setRefreshing(false);
    }
  };

  const handleManualDispatch = async (e) => {
    e.preventDefault();
    if (!dispatchTitle.trim() || !dispatchSummary.trim()) return;
    setDispatching(true);
    setActionError("");
    try {
      await dispatchChatOps({
        title: dispatchTitle.trim(),
        summary: dispatchSummary.trim(),
        severity: dispatchSeverity,
        event_type: dispatchType,
        incident_id: dispatchIncidentId.trim() || undefined,
        actionable: dispatchActionable,
      });
      setFeedbackMsg("ChatOps card dispatched.");
      setDispatchTitle("");
      setDispatchSummary("");
      setShowDispatch(false);
      await loadData(true);
      setTimeout(() => setFeedbackMsg(""), 4000);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Dispatch failed");
    } finally {
      setDispatching(false);
    }
  };

  const handleInteractiveDecision = async (incidentId, decision) => {
    setActionError("");
    try {
      await sendChatOpsInteraction(incidentId, decision, "chatops-dashboard-lead");
      setFeedbackMsg(`Action '${decision.toUpperCase()}' recorded via ChatOps callback.`);
      await loadData(true);
      setTimeout(() => setFeedbackMsg(""), 4000);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Interactive decision failed");
    }
  };

  if (loading && !status) {
    return (
      <div className="panel loading-panel">
        <span className="button-spinner" /> Loading ChatOps & Webhook Gateway...
      </div>
    );
  }

  const platforms = status?.platforms || {};
  const isSimulation = status?.simulation_mode;

  return (
    <div className="chatops-container">
      {/* Top Banner & Control Strip */}
      <div className="chatops-hero panel">
        <div className="chatops-hero-info">
          <div className="chatops-badge-row">
            <span className={`pill ${isSimulation ? "pill-amber" : "pill-green"}`}>
              {isSimulation ? "Simulation Mode · Local Loopback" : "Live Webhooks Active"}
            </span>
            <span className="chatops-meta-pill">
              {history.length} Messages in Buffer
            </span>
          </div>
          <h2>ChatOps & Webhook Gateway</h2>
          <p>
            Bidirectional Slack & Discord notification engine with interactive
            human-in-the-loop approvals. Alerts are dispatched autonomously as agents diagnose
            incidents, request remediation, or complete rollbacks.
          </p>
        </div>

        <div className="chatops-hero-actions">
          <button
            type="button"
            className="button button-outline"
            onClick={() => setShowConfig(!showConfig)}
          >
            <Icon name="shield" size={15} />
            {showConfig ? "Hide Config" : "Webhook Settings"}
          </button>
          <button
            type="button"
            className="button button-outline"
            onClick={() => setShowDispatch(!showDispatch)}
          >
            <Icon name="code" size={15} />
            Simulate Alert
          </button>
          <button
            type="button"
            className="button button-primary"
            onClick={handleTestPing}
            disabled={refreshing}
          >
            <Icon name="chatops" size={15} />
            Send Test Ping
          </button>
        </div>
      </div>

      {feedbackMsg && (
        <div className="notice-bar notice-green">
          <span className="notice-icon">✓</span>
          <span>{feedbackMsg}</span>
        </div>
      )}

      {actionError && (
        <div className="global-error" role="alert">
          {actionError}
          <button onClick={() => setActionError("")}>Dismiss</button>
        </div>
      )}

      {/* Webhook Configuration Modal / Card */}
      {showConfig && (
        <section className="panel chatops-config-panel">
          <h3>Webhook Endpoints Configuration</h3>
          <p className="panel-subtitle">
            Configure incoming webhook URLs for your team channels. Leave blank to run in safe
            offline simulation mode (persisted to local audit log).
          </p>
          <form onSubmit={handleSaveConfig} className="chatops-config-form">
            <div className="form-group">
              <label htmlFor="slack-url">
                Slack Incoming Webhook URL
                {platforms.slack?.configured && (
                  <span className="text-green text-sm"> (Connected: {platforms.slack.masked_url})</span>
                )}
              </label>
              <input
                id="slack-url"
                type="url"
                placeholder="https://hooks.slack.com/services/..."
                value={slackUrl}
                onChange={(e) => setSlackUrl(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label htmlFor="discord-url">
                Discord Webhook URL
                {platforms.discord?.configured && (
                  <span className="text-green text-sm"> (Connected: {platforms.discord.masked_url})</span>
                )}
              </label>
              <input
                id="discord-url"
                type="url"
                placeholder="https://discord.com/api/webhooks/..."
                value={discordUrl}
                onChange={(e) => setDiscordUrl(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label htmlFor="generic-url">
                Generic HTTP Webhook URL (Teams / PagerDuty / Automation)
                {platforms.generic?.configured && (
                  <span className="text-green text-sm"> (Connected: {platforms.generic.masked_url})</span>
                )}
              </label>
              <input
                id="generic-url"
                type="url"
                placeholder="https://your-webhook-endpoint.com/..."
                value={genericUrl}
                onChange={(e) => setGenericUrl(e.target.value)}
              />
            </div>

            <div className="form-actions">
              <button
                type="button"
                className="button button-outline"
                onClick={() => setShowConfig(false)}
              >
                Cancel
              </button>
              <button type="submit" className="button button-primary" disabled={savingConfig}>
                {savingConfig ? "Saving..." : "Save Endpoints"}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Manual Dispatch Card */}
      {showDispatch && (
        <section className="panel chatops-dispatch-panel">
          <h3>Simulate ChatOps Notification</h3>
          <p className="panel-subtitle">
            Manually trigger an alert card to preview formatting and test webhook delivery.
          </p>
          <form onSubmit={handleManualDispatch} className="chatops-dispatch-form">
            <div className="form-row">
              <div className="form-group flex-2">
                <label>Card Title</label>
                <input
                  type="text"
                  placeholder="e.g. Memory Pressure on Calculator Pod"
                  value={dispatchTitle}
                  onChange={(e) => setDispatchTitle(e.target.value)}
                  required
                />
              </div>
              <div className="form-group flex-1">
                <label>Event Type</label>
                <select
                  value={dispatchType}
                  onChange={(e) => setDispatchType(e.target.value)}
                >
                  <option value="incident_alert">Incident Alert</option>
                  <option value="approval_requested">Approval Requested</option>
                  <option value="incident_resolved">Incident Resolved</option>
                  <option value="decision_recorded">Decision Recorded</option>
                </select>
              </div>
              <div className="form-group flex-1">
                <label>Severity</label>
                <select
                  value={dispatchSeverity}
                  onChange={(e) => setDispatchSeverity(e.target.value)}
                >
                  <option value="critical">Critical</option>
                  <option value="warning">Warning</option>
                  <option value="info">Info</option>
                  <option value="success">Success</option>
                </select>
              </div>
            </div>

            <div className="form-group">
              <label>Summary Message</label>
              <textarea
                rows={2}
                placeholder="Detailed findings or diagnostic observations..."
                value={dispatchSummary}
                onChange={(e) => setDispatchSummary(e.target.value)}
                required
              />
            </div>

            <div className="form-row">
              <div className="form-group flex-2">
                <label>Optional Incident ID</label>
                <input
                  type="text"
                  placeholder="e.g. 4cd04355-9ce8-4f2b-b6d3"
                  value={dispatchIncidentId}
                  onChange={(e) => setDispatchIncidentId(e.target.value)}
                />
              </div>
              <div className="form-group flex-1 checkbox-group">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={dispatchActionable}
                    onChange={(e) => setDispatchActionable(e.target.checked)}
                  />
                  <span>Include Approve/Reject Buttons</span>
                </label>
              </div>
            </div>

            <div className="form-actions">
              <button
                type="button"
                className="button button-outline"
                onClick={() => setShowDispatch(false)}
              >
                Cancel
              </button>
              <button type="submit" className="button button-primary" disabled={dispatching}>
                {dispatching ? "Dispatching..." : "Send to Webhooks"}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Platform Status Pill Grid */}
      <div className="chatops-platforms-grid">
        <div className="platform-card">
          <div className="platform-header">
            <span className="platform-name">Slack Webhook</span>
            <span
              className={`platform-dot ${
                platforms.slack?.configured ? "is-connected" : "is-simulated"
              }`}
            />
          </div>
          <div className="platform-meta">
            <strong>
              {platforms.slack?.configured ? "Connected" : "Simulated (Local)"}
            </strong>
            <small>{platforms.slack?.masked_url || "Logs to JSONL"}</small>
          </div>
        </div>

        <div className="platform-card">
          <div className="platform-header">
            <span className="platform-name">Discord Webhook</span>
            <span
              className={`platform-dot ${
                platforms.discord?.configured ? "is-connected" : "is-simulated"
              }`}
            />
          </div>
          <div className="platform-meta">
            <strong>
              {platforms.discord?.configured ? "Connected" : "Simulated (Local)"}
            </strong>
            <small>{platforms.discord?.masked_url || "Logs to JSONL"}</small>
          </div>
        </div>

        <div className="platform-card">
          <div className="platform-header">
            <span className="platform-name">Generic Webhook</span>
            <span
              className={`platform-dot ${
                platforms.generic?.configured ? "is-connected" : "is-simulated"
              }`}
            />
          </div>
          <div className="platform-meta">
            <strong>
              {platforms.generic?.configured ? "Connected" : "Simulated (Local)"}
            </strong>
            <small>{platforms.generic?.masked_url || "Teams / PagerDuty / n8n"}</small>
          </div>
        </div>
      </div>

      {/* Live ChatOps Feed */}
      <section className="panel chatops-feed-panel">
        <div className="feed-header">
          <div>
            <h3>Live ChatOps Broadcast Stream</h3>
            <p className="panel-subtitle">
              Interactive preview of rich messages dispatched by OpsPilot AI agents.
            </p>
          </div>
          <div className="platform-switcher">
            <button
              type="button"
              className={`platform-switch-btn ${previewPlatform === "slack" ? "active" : ""}`}
              onClick={() => setPreviewPlatform("slack")}
            >
              Slack Preview
            </button>
            <button
              type="button"
              className={`platform-switch-btn ${previewPlatform === "discord" ? "active" : ""}`}
              onClick={() => setPreviewPlatform("discord")}
            >
              Discord Preview
            </button>
            <button
              type="button"
              className={`platform-switch-btn ${previewPlatform === "generic" ? "active" : ""}`}
              onClick={() => setPreviewPlatform("generic")}
            >
              Raw Payload
            </button>
          </div>
        </div>

        {history.length === 0 ? (
          <div className="empty-state">
            <Icon name="chatops" size={32} />
            <h4>No ChatOps Messages Yet</h4>
            <p>Dispatched notifications and interactive approval requests will appear here in real-time.</p>
            <button type="button" className="button button-outline" onClick={handleTestPing}>
              Send First Test Message
            </button>
          </div>
        ) : (
          <div className="chatops-feed-list">
            {history.map((item) => (
              <div key={item.event_id} className="chatops-feed-item">
                <div className="feed-item-meta">
                  <span className={`event-type-badge ${item.event_type}`}>
                    {item.event_type.replace("_", " ").toUpperCase()}
                  </span>
                  <span className="feed-item-timestamp">
                    {new Date(item.timestamp).toLocaleTimeString()} · {new Date(item.timestamp).toLocaleDateString()}
                  </span>
                  <span className="feed-item-sim-tag">
                    {item.delivery?.slack?.status === "delivered" ? "Live" : "Simulated"}
                  </span>
                </div>

                {/* SLACK BLOCK KIT PREVIEW */}
                {previewPlatform === "slack" && (
                  <div className="slack-card">
                    <div className="slack-header">
                      <strong>{item.slack_preview?.blocks?.[0]?.text?.text || item.title}</strong>
                    </div>
                    <div className="slack-body">
                      <p>{item.summary}</p>
                      {item.slack_preview?.blocks?.[2]?.fields && (
                        <div className="slack-fields-grid">
                          {item.slack_preview.blocks[2].fields.map((f, idx) => (
                            <div key={idx} className="slack-field">
                              <span dangerouslySetInnerHTML={{ __html: f.text.replace(/\*(.*?)\*/g, "<strong>$1</strong>").replace(/`(.*?)`/g, "<code>$1</code>") }} />
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Interactive Action Buttons */}
                    {item.actionable && item.incident_id && (
                      <div className="slack-actions">
                        <button
                          type="button"
                          className="slack-btn slack-btn-primary"
                          onClick={() => handleInteractiveDecision(item.incident_id, "approve")}
                        >
                          Approve Remediation
                        </button>
                        <button
                          type="button"
                          className="slack-btn slack-btn-danger"
                          onClick={() => handleInteractiveDecision(item.incident_id, "reject")}
                        >
                          Reject Remediation
                        </button>
                      </div>
                    )}

                    <div className="slack-footer">
                      <small>OpsPilot Multi-Agent System · Local Loopback · Click buttons to execute approvals</small>
                    </div>
                  </div>
                )}

                {/* DISCORD EMBED PREVIEW */}
                {previewPlatform === "discord" && (
                  <div
                    className="discord-card"
                    style={{
                      borderLeftColor:
                        item.severity === "critical"
                          ? "#DC2626"
                          : item.severity === "warning"
                          ? "#D97706"
                          : item.severity === "success"
                          ? "#059669"
                          : "#2563EB",
                    }}
                  >
                    <div className="discord-title">
                      <strong>{item.discord_preview?.embeds?.[0]?.title || item.title}</strong>
                    </div>
                    <div className="discord-desc">
                      {item.discord_preview?.embeds?.[0]?.description || item.summary}
                    </div>
                    {item.discord_preview?.embeds?.[0]?.fields && (
                      <div className="discord-fields">
                        {item.discord_preview.embeds[0].fields.map((f, idx) => (
                          <div key={idx} className="discord-field">
                            <span className="discord-field-name">{f.name}</span>
                            <span className="discord-field-val">{f.value}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {item.actionable && item.incident_id && (
                      <div className="discord-actions">
                        <button
                          type="button"
                          className="button button-sm button-primary"
                          onClick={() => handleInteractiveDecision(item.incident_id, "approve")}
                        >
                          Approve via Callback
                        </button>
                        <button
                          type="button"
                          className="button button-sm button-outline"
                          onClick={() => handleInteractiveDecision(item.incident_id, "reject")}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                    <div className="discord-footer">
                      <small>OpsPilot Multi-Agent System · 127.0.0.1</small>
                    </div>
                  </div>
                )}

                {/* GENERIC JSON PREVIEW */}
                {previewPlatform === "generic" && (
                  <pre className="generic-payload-code">
                    {JSON.stringify(item.generic_preview || item, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

