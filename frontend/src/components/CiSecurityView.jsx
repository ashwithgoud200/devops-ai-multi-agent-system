import { useState } from "react";
import Icon from "./Icon.jsx";
import StatusCard from "./StatusCard.jsx";

export default function CiSecurityView({ integrations, ciRun, securityFindings }) {
  const [severityFilter, setSeverityFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");

  const gh = integrations?.github || { status: "disabled", enabled: false };
  const offlineCi = integrations?.offline_ci || {};
  const offlineSec = integrations?.offline_security || {};

  const ci = ciRun || { status: "unavailable", conclusion: "unknown" };
  const testSummary = ci.test_summary || { total: 0, passed: 0, failed: 0, errors: 0, skipped: 0 };
  const jobs = Array.isArray(ci.jobs) ? ci.jobs : [];

  const sec = securityFindings || { status: "unavailable", findings: [], summary: {} };
  const secSummary = sec.summary || {};
  const bySeverity = secSummary.by_severity || { critical: 0, high: 0, medium: 0, low: 0, unknown: 0 };
  const byCategory = secSummary.by_category || {};
  const scanners = sec.scanners || {};
  const allFindings = Array.isArray(sec.findings) ? sec.findings : [];

  const filteredFindings = allFindings.filter((item) => {
    if (severityFilter !== "all" && item.severity !== severityFilter) return false;
    if (categoryFilter !== "all" && item.category !== categoryFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchId = (item.identifier || "").toLowerCase().includes(q);
      const matchPkg = (item.package || "").toLowerCase().includes(q);
      const matchTitle = (item.title || "").toLowerCase().includes(q);
      const matchLoc = (item.location || "").toLowerCase().includes(q);
      if (!matchId && !matchPkg && !matchTitle && !matchLoc) return false;
    }
    return true;
  });

  const ghConnected = gh.status === "connected";
  const ciSuccess = ci.conclusion === "success";
  const ciFailed = ci.conclusion === "failure" || testSummary.failed > 0 || testSummary.errors > 0;
  const secClean = sec.status === "clean" || (secSummary.total_findings === 0 && sec.status !== "unavailable" && sec.status !== "disabled");
  const secHasFindings = (secSummary.total_findings || 0) > 0;

  return (
    <div className="ci-security-view">
      {/* 1. Integration Status Header Cards */}
      <div className="status-grid">
        <StatusCard
          label="GitHub integration"
          value={ghConnected ? "Connected" : gh.status === "rate_limited" ? "Rate Limited" : gh.status === "disabled" ? "Disabled" : "Unavailable"}
          detail={gh.repo ? `${gh.repo} · ${gh.authenticated ? "Token auth" : "Anonymous"}` : "DEVOPS_GITHUB_ENABLED=false"}
          icon="◉"
          tone={ghConnected ? "green" : gh.status === "rate_limited" ? "amber" : "neutral"}
        />
        <StatusCard
          label="Latest CI pipeline"
          value={ciSuccess ? "Passed" : ciFailed ? "Failed" : ci.status === "not_run" ? "Not Run" : "Unavailable"}
          detail={ci.workflow_name ? `${ci.workflow_name} ${ci.branch ? `(${ci.branch})` : ""}` : "No run recorded"}
          icon="↗"
          tone={ciSuccess ? "green" : ciFailed ? "amber" : "neutral"}
        />
        <StatusCard
          label="Test results"
          value={testSummary.total > 0 ? `${testSummary.passed} / ${testSummary.total} passed` : "No tests"}
          detail={`${testSummary.failed} failed · ${testSummary.errors} errors · ${testSummary.skipped} skipped`}
          icon="✓"
          tone={testSummary.failed > 0 || testSummary.errors > 0 ? "amber" : testSummary.total > 0 ? "green" : "neutral"}
        />
        <StatusCard
          label="Security findings"
          value={secClean ? "0 clean" : secHasFindings ? `${secSummary.total_findings} findings` : sec.status === "disabled" ? "Disabled" : "Unavailable"}
          detail={`${bySeverity.critical || 0} crit · ${bySeverity.high || 0} high · ${bySeverity.medium || 0} med · ${bySeverity.low || 0} low`}
          icon="!"
          tone={bySeverity.critical > 0 || bySeverity.high > 0 ? "amber" : secClean ? "green" : "neutral"}
        />
      </div>

      {/* Integration details strip */}
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">INTEGRATION & INGESTION SOURCES</span>
            <h2>Pipeline & Report Provenance</h2>
          </div>
          <span className={`pill ${ghConnected ? "pill-green" : "pill-muted"}`}>
            GitHub · {gh.status || "disabled"}
          </span>
        </div>
        <div className="provenance-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem" }}>
          <div className="card" style={{ padding: "1rem", background: "rgba(255,255,255,0.02)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.06)" }}>
            <h4 style={{ margin: "0 0 0.5rem 0" }}>GitHub REST API (Read-only)</h4>
            <p style={{ margin: "0 0 0.5rem 0", fontSize: "0.85rem", color: "#888" }}>
              Status: <strong style={{ color: ghConnected ? "#4ade80" : "#aaa" }}>{gh.status}</strong>
            </p>
            {gh.rate_limit && (
              <p style={{ margin: 0, fontSize: "0.8rem", color: "#666" }}>
                API Rate limit: {gh.rate_limit.remaining} remaining of {gh.rate_limit.limit}
              </p>
            )}
            <p style={{ margin: "0.25rem 0 0 0", fontSize: "0.8rem", color: "#666" }}>
              Repo: {gh.repo || "None"} · Authentication: {gh.authenticated ? "Bearer Token" : "Unauthenticated"}
            </p>
          </div>
          <div className="card" style={{ padding: "1rem", background: "rgba(255,255,255,0.02)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.06)" }}>
            <h4 style={{ margin: "0 0 0.5rem 0" }}>Offline CI Summary Store</h4>
            <p style={{ margin: "0 0 0.5rem 0", fontSize: "0.85rem", color: "#888" }}>
              Status: <strong>{offlineCi.status || "unknown"}</strong> · Reports found: <strong>{offlineCi.reports_found ?? 0}</strong>
            </p>
            <p style={{ margin: 0, fontSize: "0.8rem", color: "#666" }}>
              Directory: <code>{offlineCi.import_dir || "/app/data/ci-security-reports"}</code>
            </p>
            <p style={{ margin: "0.25rem 0 0 0", fontSize: "0.8rem", color: "#666" }}>
              Enabled: {offlineCi.enabled ? "true" : "false"} (DEVOPS_CI_EVIDENCE_ENABLED)
            </p>
          </div>
          <div className="card" style={{ padding: "1rem", background: "rgba(255,255,255,0.02)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.06)" }}>
            <h4 style={{ margin: "0 0 0.5rem 0" }}>Offline Security Scanner Store</h4>
            <p style={{ margin: "0 0 0.5rem 0", fontSize: "0.85rem", color: "#888" }}>
              Status: <strong>{offlineSec.status || "unknown"}</strong> · Reports found: <strong>{offlineSec.reports_found ?? 0}</strong>
            </p>
            <p style={{ margin: 0, fontSize: "0.8rem", color: "#666" }}>
              Scanners: pip-audit, npm-audit, trivy (image/config), gitleaks
            </p>
            <p style={{ margin: "0.25rem 0 0 0", fontSize: "0.8rem", color: "#666" }}>
              Enabled: {offlineSec.enabled ? "true" : "false"} (DEVOPS_SECURITY_EVIDENCE_ENABLED)
            </p>
          </div>
        </div>
      </section>

      {/* 2. Latest CI Pipeline & Job Breakdown */}
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">CONTINUOUS INTEGRATION</span>
            <h2>Latest CI Run & Jobs Breakdown</h2>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <span className={`pill ${ciSuccess ? "pill-green" : ciFailed ? "pill-amber" : "pill-muted"}`}>
              Conclusion: {ci.conclusion || "unknown"}
            </span>
            <span className={`pill ${ci.freshness === "stale" ? "pill-amber" : "pill-green"}`}>
              {ci.freshness || "observed"}
            </span>
          </div>
        </div>

        {ci.status === "unavailable" || ci.status === "not_run" ? (
          <div className="inline-empty">
            <span className="empty-dot" />
            {ci.detail || "No CI pipeline evidence currently collected."}
          </div>
        ) : (
          <div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "1.5rem", marginBottom: "1rem", fontSize: "0.85rem", color: "#888" }}>
              <div>Workflow: <strong style={{ color: "#eee" }}>{ci.workflow_name}</strong></div>
              {ci.workflow_run_id && <div>Run ID: <strong style={{ color: "#eee" }}>{ci.workflow_run_id}</strong></div>}
              {ci.branch && <div>Branch: <strong style={{ color: "#eee" }}>{ci.branch}</strong></div>}
              {ci.commit_sha && <div>Commit: <code>{ci.commit_sha.slice(0, 10)}</code></div>}
              <div>Source: <span style={{ color: "#aaa" }}>{ci.source || "offline"}</span></div>
            </div>

            {/* Jobs list */}
            {jobs.length > 0 ? (
              <div style={{ border: "1px solid rgba(255,255,255,0.06)", borderRadius: "6px", overflow: "hidden" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                  <thead>
                    <tr style={{ background: "rgba(255,255,255,0.03)", textAlign: "left", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                      <th style={{ padding: "0.6rem 1rem" }}>Job / Step</th>
                      <th style={{ padding: "0.6rem 1rem" }}>Status</th>
                      <th style={{ padding: "0.6rem 1rem" }}>Conclusion</th>
                      <th style={{ padding: "0.6rem 1rem" }}>Steps</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job, idx) => (
                      <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                        <td style={{ padding: "0.6rem 1rem", fontWeight: "600" }}>{job.name}</td>
                        <td style={{ padding: "0.6rem 1rem" }}>{job.status}</td>
                        <td style={{ padding: "0.6rem 1rem" }}>
                          <span className={`pill ${job.conclusion === "success" ? "pill-green" : job.conclusion === "failure" ? "pill-amber" : "pill-muted"}`}>
                            {job.conclusion || "completed"}
                          </span>
                        </td>
                        <td style={{ padding: "0.6rem 1rem", color: "#888" }}>
                          {Array.isArray(job.steps) ? (
                            <span>
                              {job.steps.length} steps (
                              {job.steps.filter((s) => s.conclusion === "success").length} passed,{" "}
                              {job.steps.filter((s) => s.conclusion === "failure").length} failed)
                            </span>
                          ) : "None"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p style={{ fontSize: "0.85rem", color: "#888" }}>No granular job steps available in summary artifact.</p>
            )}
            <p style={{ marginTop: "0.5rem", fontSize: "0.75rem", color: "#666" }}>
              Note: Raw step log tails are strictly excluded from ingestion to prevent prompt injection and context exhaustion.
            </p>
          </div>
        )}
      </section>

      {/* 3. Security Scanner Overview & Findings */}
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">VULNERABILITY & SECRET SCANNING</span>
            <h2>Normalized Security Scanner Findings</h2>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <span className={`pill ${secClean ? "pill-green" : secHasFindings ? "pill-amber" : "pill-muted"}`}>
              Scans: {sec.status || "unavailable"}
            </span>
            <span className={`pill ${sec.freshness === "stale" ? "pill-amber" : "pill-green"}`}>
              {sec.freshness || "observed"}
            </span>
          </div>
        </div>

        {/* Severity & Category Badges */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1rem" }}>
          <span style={{ fontSize: "0.85rem", alignSelf: "center", marginRight: "0.5rem", color: "#888" }}>Severity:</span>
          {["all", "critical", "high", "medium", "low", "unknown"].map((sev) => {
            const count = sev === "all" ? secSummary.total_findings || 0 : bySeverity[sev] || 0;
            return (
              <button
                key={sev}
                onClick={() => setSeverityFilter(sev)}
                style={{
                  padding: "0.25rem 0.6rem",
                  borderRadius: "999px",
                  fontSize: "0.75rem",
                  border: severityFilter === sev ? "1px solid #3b82f6" : "1px solid rgba(255,255,255,0.1)",
                  background: severityFilter === sev ? "rgba(59,130,246,0.2)" : "rgba(255,255,255,0.03)",
                  color: severityFilter === sev ? "#fff" : "#aaa",
                  cursor: "pointer",
                }}
              >
                {sev.toUpperCase()}: {count}
              </button>
            );
          })}
        </div>

        {/* Scanners Status Row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "0.5rem", marginBottom: "1.25rem" }}>
          {[
            { id: "pip_audit", name: "pip-audit" },
            { id: "npm_audit", name: "npm audit" },
            { id: "trivy_image", name: "Trivy (Image)" },
            { id: "trivy_config", name: "Trivy (Config)" },
            { id: "gitleaks", name: "Gitleaks (Secrets)" },
          ].map((sc) => {
            const st = scanners[sc.id] || { status: "not_run", findings_count: 0 };
            const isClean = st.status === "clean" || st.findings_count === 0;
            const hasFindings = st.status === "findings" || st.findings_count > 0;
            return (
              <div
                key={sc.id}
                style={{
                  padding: "0.6rem",
                  background: "rgba(255,255,255,0.02)",
                  border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: "6px",
                  fontSize: "0.8rem",
                }}
              >
                <div style={{ fontWeight: "600", color: "#ddd" }}>{sc.name}</div>
                <div style={{ color: hasFindings ? "#f59e0b" : isClean ? "#4ade80" : "#888", marginTop: "0.2rem" }}>
                  {st.status}: {st.findings_count} findings
                </div>
              </div>
            );
          })}
        </div>

        {/* Filter / Search input */}
        {allFindings.length > 0 && (
          <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
            <input
              type="text"
              placeholder="Search findings by CVE, package, title, location..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                flex: 1,
                padding: "0.5rem 0.8rem",
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: "6px",
                color: "#eee",
                fontSize: "0.85rem",
              }}
            />
            {searchQuery && (
              <button
                className="button button-secondary"
                onClick={() => setSearchQuery("")}
                style={{ padding: "0.4rem 0.8rem", fontSize: "0.8rem" }}
              >
                Clear
              </button>
            )}
          </div>
        )}

        {/* Findings Table */}
        {secClean ? (
          <div className="inline-empty" style={{ color: "#4ade80" }}>
            <span className="empty-dot" style={{ background: "#4ade80" }} />
            Zero vulnerabilities or secrets detected. Security scans are clean.
          </div>
        ) : filteredFindings.length > 0 ? (
          <div style={{ border: "1px solid rgba(255,255,255,0.06)", borderRadius: "6px", overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
              <thead>
                <tr style={{ background: "rgba(255,255,255,0.03)", textAlign: "left", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                  <th style={{ padding: "0.6rem 0.8rem" }}>Severity</th>
                  <th style={{ padding: "0.6rem 0.8rem" }}>Identifier</th>
                  <th style={{ padding: "0.6rem 0.8rem" }}>Category</th>
                  <th style={{ padding: "0.6rem 0.8rem" }}>Package / Location</th>
                  <th style={{ padding: "0.6rem 0.8rem" }}>Remediation</th>
                </tr>
              </thead>
              <tbody>
                {filteredFindings.map((f, idx) => (
                  <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <td style={{ padding: "0.6rem 0.8rem" }}>
                      <span className={`pill ${f.severity === "critical" || f.severity === "high" ? "pill-amber" : "pill-muted"}`}>
                        {f.severity}
                      </span>
                    </td>
                    <td style={{ padding: "0.6rem 0.8rem", fontWeight: "600" }}>
                      {f.identifier || "N/A"}
                      {Array.isArray(f.aliases) && f.aliases.length > 0 && (
                        <div style={{ fontSize: "0.7rem", color: "#777" }}>
                          {f.aliases.join(", ")}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: "0.6rem 0.8rem", color: "#aaa" }}>
                      {(f.category || "").replaceAll("_", " ")}
                    </td>
                    <td style={{ padding: "0.6rem 0.8rem" }}>
                      <div>{f.package || f.location || "N/A"}</div>
                      {f.installed_version && (
                        <small style={{ color: "#777" }}>installed: {f.installed_version}</small>
                      )}
                    </td>
                    <td style={{ padding: "0.6rem 0.8rem", color: "#aaa" }}>
                      {f.remediation_hint || (f.fixed_versions ? `Fixed in: ${f.fixed_versions.join(", ")}` : "Review scanner report")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="inline-empty">
            <span className="empty-dot" />
            {allFindings.length > 0
              ? "No findings match the selected filters."
              : sec.detail || "No normalized security scanner reports currently loaded."}
          </div>
        )}
      </section>
    </div>
  );
}
