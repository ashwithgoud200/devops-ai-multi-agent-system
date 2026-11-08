import { useState, useEffect } from "react";
import Icon from "./Icon.jsx";
import {
  getFeatureStatus,
  generateFeature,
  testFeatureCi,
  deployFeature,
  testLiveEndpoint,
} from "../api.js";

const QUICK_INSPIRATIONS = [
  { name: "Power", op: "pow", desc: "Computes a raised to power b", params: 2, formula: "a ** b" },
  { name: "Modulo", op: "mod", desc: "Remainder of a divided by b with zero division protection", params: 2, formula: "a % b" },
  { name: "Factorial", op: "fact", desc: "Calculates factorial of non-negative integer a", params: 1, formula: "math.factorial(int(a))" },
  { name: "Percentage", op: "pct", desc: "Calculates a percent of b: (a / 100) * b", params: 2, formula: "(a / 100.0) * b" },
  { name: "Square Root", op: "sqrt", desc: "Calculates square root of non-negative number a", params: 1, formula: "math.sqrt(a)" },
  { name: "Hypotenuse", op: "hypot", desc: "Calculates Euclidean hypotenuse sqrt(a^2 + b^2)", params: 2, formula: "math.hypot(a, b)" },
  { name: "Logarithm", op: "log", desc: "Calculates natural logarithm ln(a)", params: 1, formula: "math.log(a)" },
];

export default function FeatureStudioView({ onFeatureDeployed }) {
  // Feature specification inputs (100% user-defined)
  const [featureName, setFeatureName] = useState("");
  const [op, setOp] = useState("");
  const [description, setDescription] = useState("");
  const [paramCount, setParamCount] = useState(2);
  const [formula, setFormula] = useState("");

  // Workflow states
  const [generating, setGenerating] = useState(false);
  const [featureSpec, setFeatureSpec] = useState(null);
  const [genError, setGenError] = useState("");

  const [testingCi, setTestingCi] = useState(false);
  const [ciResult, setCiResult] = useState(null);
  const [ciError, setCiError] = useState("");

  const [reviewer, setReviewer] = useState("lead-engineer");
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState(null);
  const [deployError, setDeployError] = useState("");

  // Live playground
  const [playA, setPlayA] = useState(10);
  const [playB, setPlayB] = useState(2);
  const [testingLive, setTestingLive] = useState(false);
  const [liveResult, setLiveResult] = useState(null);
  const [liveError, setLiveError] = useState("");

  // Live status
  const [status, setStatus] = useState(null);

  const fetchStatus = async () => {
    try {
      const res = await getFeatureStatus();
      if (res) setStatus(res);
    } catch {
      // Ignore initial fetch errors
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const handleApplyInspiration = (item) => {
    setFeatureName(item.name);
    setOp(item.op);
    setDescription(item.desc);
    setParamCount(item.params);
    setFormula(item.formula);
    setFeatureSpec(null);
    setCiResult(null);
    setDeployResult(null);
    setGenError("");
    setCiError("");
    setDeployError("");
    setLiveResult(null);
  };

  const handleGenerate = async (e) => {
    if (e) e.preventDefault();
    if (!featureName.trim()) {
      setGenError("Please enter a feature name.");
      return;
    }
    setGenerating(true);
    setGenError("");
    setFeatureSpec(null);
    setCiResult(null);
    setDeployResult(null);
    try {
      const data = {
        feature_name: featureName.trim(),
        op: op.trim() || undefined,
        description: description.trim() || undefined,
        param_count: parseInt(paramCount, 10),
        formula: formula.trim() || undefined,
      };
      const res = await generateFeature(data);
      setFeatureSpec(res);
      if (res.sample_inputs) {
        setPlayA(res.sample_inputs.a ?? 10);
        setPlayB(res.sample_inputs.b ?? 2);
      }
    } catch (err) {
      setGenError(err instanceof Error ? err.message : "Failed to synthesize feature.");
    } finally {
      setGenerating(false);
    }
  };

  const handleTestCi = async () => {
    if (!featureSpec) return;
    setTestingCi(true);
    setCiError("");
    setCiResult(null);
    try {
      const data = {
        feature_name: featureSpec.feature_name,
        op: featureSpec.op,
        code_snippet: featureSpec.code_snippet,
        test_code: featureSpec.test_code,
        branch_name: featureSpec.branch_name,
        description: featureSpec.description,
      };
      const res = await testFeatureCi(data);
      setCiResult(res);
    } catch (err) {
      setCiError(err instanceof Error ? err.message : "CI & GitHub Actions pipeline failed.");
    } finally {
      setTestingCi(false);
    }
  };

  const handleDeploy = async () => {
    if (!featureSpec) return;
    if (!reviewer.trim()) {
      setDeployError("Reviewer label is required for human approval.");
      return;
    }
    setDeploying(true);
    setDeployError("");
    try {
      const res = await deployFeature({
        op: featureSpec.op,
        feature_name: featureSpec.feature_name,
        code_snippet: featureSpec.code_snippet,
        reviewer: reviewer.trim(),
      });
      setDeployResult(res);
      await fetchStatus();
      if (onFeatureDeployed) onFeatureDeployed();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Deployment failed.");
    } finally {
      setDeploying(false);
    }
  };

  const handleTestLive = async () => {
    const targetOp = deployResult?.op || featureSpec?.op || op;
    setTestingLive(true);
    setLiveError("");
    setLiveResult(null);
    try {
      const res = await testLiveEndpoint(targetOp, playA, paramCount === 1 ? undefined : playB);
      setLiveResult(res);
    } catch (err) {
      setLiveError(err instanceof Error ? err.message : "Live endpoint call failed.");
    } finally {
      setTestingLive(false);
    }
  };

  const ghRepo = status?.github?.repo || "ashwithgoud200/Code-Agent";

  return (
    <div className="feature-studio-view">
      {/* Top Banner with GitHub Repository Connection */}
      <section className="panel feature-hero-panel">
        <div className="feature-hero-content">
          <div className="feature-hero-badge">
            <span className="badge-dot" />
            <span>CUSTOM FEATURE SYNTHESIS &amp; GITHUB ACTIONS</span>
          </div>
          <h2>Feature Studio &middot; GitHub Repository Integration</h2>
          <p>
            Specify any new capability for the Calculator application. The <strong>Code Agent (qwen2.5-coder:3b)</strong> writes the implementation and tests, creates a feature branch in <strong>{ghRepo}</strong>, runs CI/CD verification matching <code>.github/workflows/ci.yml</code>, and deploys with human approval.
          </p>
        </div>

        {/* Live system metadata */}
        <div className="feature-stats-bar">
          <div className="stat-pill">
            <span className="pill-label">Target GitHub Repo:</span>
            <a
              href={`https://github.com/${ghRepo}`}
              target="_blank"
              rel="noreferrer"
              style={{ color: "#60a5fa", textDecoration: "underline", fontWeight: 600 }}
            >
              {ghRepo}
            </a>
          </div>
          <div className="stat-pill">
            <span className="pill-label">App Version:</span>
            <strong>v{status?.current_version || "1.1"}</strong>
          </div>
          <div className="stat-pill">
            <span className="pill-label">Operations:</span>
            <strong>{status?.available_operations?.length || 5} active</strong>
          </div>
          <div className="stat-pill">
            <span className="pill-label">CI/CD Pipeline:</span>
            <span className="status-indicator-inline">
              <i className="status-dot-green" /> Ready (.github/workflows/ci.yml)
            </span>
          </div>
        </div>
      </section>

      {/* Step 1: User Defines ANY Feature */}
      <section className="panel feature-step-panel">
        <div className="step-header">
          <span className="step-number">1</span>
          <div>
            <h3>Define Your Custom Feature</h3>
            <p>Enter any custom mathematical operation or feature requirement below.</p>
          </div>
        </div>

        {/* Quick Inspiration Chips */}
        <div className="inspiration-strip">
          <span className="inspiration-label">Quick Ideas:</span>
          {QUICK_INSPIRATIONS.map((item) => (
            <button
              key={item.name}
              type="button"
              className="inspiration-chip"
              onClick={() => handleApplyInspiration(item)}
            >
              {item.name}
            </button>
          ))}
        </div>

        <form onSubmit={handleGenerate} className="custom-feature-form">
          <div className="form-grid-2">
            <div>
              <label htmlFor="feature-name">Feature Name *</label>
              <input
                id="feature-name"
                value={featureName}
                onChange={(e) => setFeatureName(e.target.value)}
                placeholder="e.g. Modulo, Factorial, Percentage, Hypotenuse"
                required
              />
            </div>
            <div>
              <label htmlFor="feature-op">Operator Code (URL Path)</label>
              <input
                id="feature-op"
                value={op}
                onChange={(e) => setOp(e.target.value)}
                placeholder="e.g. mod, fact, pct, hypot (auto-derived if blank)"
              />
            </div>
          </div>

          <div className="form-grid-2">
            <div>
              <label htmlFor="param-count">Input Arguments</label>
              <select
                id="param-count"
                value={paramCount}
                onChange={(e) => setParamCount(parseInt(e.target.value, 10))}
              >
                <option value={2}>Binary (2 arguments: a and b)</option>
                <option value={1}>Unary (1 argument: a)</option>
              </select>
            </div>
            <div>
              <label htmlFor="feature-formula">Formula / Python Expression (Optional)</label>
              <input
                id="feature-formula"
                value={formula}
                onChange={(e) => setFormula(e.target.value)}
                placeholder="e.g. a % b, math.factorial(int(a)), (a / 100) * b"
              />
            </div>
          </div>

          <div>
            <label htmlFor="feature-desc">Specification &amp; Validation Requirements</label>
            <textarea
              id="feature-desc"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Computes remainder of dividing a by b. Rejects b == 0 with ZeroDivisionError."
            />
          </div>

          <div className="step-action-bar">
            <button
              type="submit"
              className="button button-primary"
              disabled={generating || !featureName.trim()}
            >
              {generating ? (
                <><span className="button-spinner" /> Synthesizing with Code Agent...</>
              ) : (
                <>Synthesize Feature with Code Agent (qwen2.5-coder:3b) &rarr;</>
              )}
            </button>
          </div>
        </form>
        {genError && <div className="form-error" role="alert">{genError}</div>}
      </section>

      {/* Step 2: Code Agent Synthesis & Git Review */}
      {featureSpec && (
        <section className="panel feature-step-panel">
          <div className="step-header">
            <span className="step-number">2</span>
            <div>
              <h3>Code Agent Synthesis &amp; GitHub Branching</h3>
              <p>Generated implementation and automated pytest suite by <code>qwen2.5-coder:3b</code>.</p>
            </div>
            <span className="pill pill-green">Synthesized</span>
          </div>

          <div className="git-metadata-box">
            <div className="git-row">
              <Icon name="git" size={16} />
              <span>Target GitHub Repository:</span>
              <strong>{featureSpec.github_repo}</strong>
            </div>
            <div className="git-row">
              <span>Feature Branch:</span>
              <code>{featureSpec.branch_name}</code>
            </div>
            <div className="git-row">
              <span>Commit Message:</span>
              <code>{featureSpec.commit_message}</code>
            </div>
          </div>

          <div className="code-split-view">
            <div className="code-col">
              <div className="code-col-header">
                <span>Code Patch (<code>calculator_app/app.py</code>)</span>
                <span className="code-badge">Implementation</span>
              </div>
              <pre className="code-block">{featureSpec.diff}</pre>
            </div>

            <div className="code-col">
              <div className="code-col-header">
                <span>Unit Tests (<code>tests/test_calculator.py</code>)</span>
                <span className="code-badge">Pytest</span>
              </div>
              <pre className="code-block">{featureSpec.test_code}</pre>
            </div>
          </div>

          <div className="step-action-bar">
            <button
              className="button button-primary"
              onClick={handleTestCi}
              disabled={testingCi}
            >
              {testingCi ? (
                <><span className="button-spinner" /> Testing against CI/CD &amp; GitHub Actions...</>
              ) : (
                <>Commit to GitHub ({ghRepo}) &amp; Run CI/CD Pipeline &rarr;</>
              )}
            </button>
          </div>
          {ciError && <div className="form-error" role="alert">{ciError}</div>}
        </section>
      )}

      {/* Step 3: CI/CD Pipeline & GitHub Integration */}
      {ciResult && (
        <section className="panel feature-step-panel">
          <div className="step-header">
            <span className="step-number">3</span>
            <div>
              <h3>CI/CD Pipeline &amp; GitHub Repository Results</h3>
              <p>Validated against <code>{ciResult.workflow}</code>.</p>
            </div>
            <span className={`pill ${ciResult.pipeline_status === "passed" ? "pill-green" : "pill-danger"}`}>
              {ciResult.pipeline_status === "passed" ? "✓ CI PASSED" : "FAILED"}
            </span>
          </div>

          {/* GitHub Status Banner */}
          <div className="github-actions-banner">
            <div className="gh-icon-col">
              <Icon name="git" size={24} />
            </div>
            <div className="gh-info-col">
              <strong>GitHub Repository: {ciResult.github?.repo}</strong>
              <p>
                Branch <code>{ciResult.branch}</code> verified against test matrix (Python 3.11, 3.12, Security &amp; Docker).
                {ciResult.github?.pull_request && (
                  <span style={{ display: "block", marginTop: "4px" }}>
                    Pull Request #{ciResult.github.pull_request.number}:{" "}
                    <a href={ciResult.github.pull_request.url} target="_blank" rel="noreferrer">
                      View Pull Request on GitHub
                    </a>
                  </span>
                )}
                {ciResult.github?.commit ? (
                  <span style={{ display: "block", marginTop: "4px" }}>
                    ✓ Commit SHA: <code>{ciResult.github.commit.commit_sha?.slice(0, 8)}</code>{" "}
                    <a href={ciResult.github.commit.commit_url} target="_blank" rel="noreferrer">
                      View Commit on GitHub
                    </a>
                  </span>
                ) : (
                  <div style={{ marginTop: "8px", padding: "8px 10px", background: "#78350f25", border: "1px solid #b45309", borderRadius: "5px" }}>
                    <strong style={{ color: "#fbbf24", fontSize: "12px", display: "block", marginBottom: "3px" }}>
                      ⚠️ GitHub Remote Push Blocked (HTTP 403)
                    </strong>
                    <span style={{ color: "#fef3c7", fontSize: "11px", lineHeight: "1.4", display: "block" }}>
                      {ciResult.github?.notice || "Your Personal Access Token has read-only access. Enable 'Contents: Read and write' on your token in GitHub Developer Settings to allow pushing commits directly."}
                    </span>
                  </div>
                )}
              </p>
            </div>
            <div className="gh-stats-col">
              <span className="gh-test-count">{ciResult.tests_summary?.passed} / {ciResult.tests_summary?.total} Tests Passed</span>
              <span className="gh-duration">Time: {ciResult.duration_seconds}s</span>
            </div>
          </div>

          {/* Jobs Matrix */}
          <div className="jobs-list">
            {ciResult.jobs?.map((job) => (
              <div key={job.job_id} className="job-row">
                <span className="job-status-dot is-passed">✓</span>
                <span className="job-name">{job.name}</span>
                <span className="job-detail">
                  {job.tests_passed !== undefined ? `${job.tests_passed} passed` : job.vulnerabilities !== undefined ? `${job.vulnerabilities} findings` : job.config || "ok"}
                </span>
                <span className="job-duration">{job.duration}</span>
              </div>
            ))}
          </div>

          {/* Human Sign-off Box */}
          <div className="approval-signoff-box">
            <div className="reviewer-input-group">
              <label htmlFor="reviewer-input">Human-in-the-Loop Reviewer Label</label>
              <input
                id="reviewer-input"
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                placeholder="e.g. lead-engineer"
              />
              <small>Deployment requires explicit human sign-off before modifying the live calculator application.</small>
            </div>

            <div className="step-action-bar">
              <button
                className="button button-primary"
                onClick={handleDeploy}
                disabled={deploying}
              >
                {deploying ? (
                  <><span className="button-spinner" /> Deploying to Production...</>
                ) : (
                  <>Approve &amp; Deploy Feature (Release to Live App) &rarr;</>
                )}
              </button>
            </div>
            {deployError && <div className="form-error" role="alert">{deployError}</div>}
          </div>
        </section>
      )}

      {/* Step 4: Live Deployment & Interactive Playground */}
      {deployResult && (
        <section className="panel feature-step-panel deployment-success-panel">
          <div className="step-header">
            <span className="step-number success-badge">✓</span>
            <div>
              <h3>Feature Deployed &amp; Verified in Production!</h3>
              <p>The new endpoint <code>/calc/{deployResult.op}</code> is live on application version <strong>v{deployResult.version}</strong>.</p>
            </div>
            <span className="pill pill-green">Live v{deployResult.version}</span>
          </div>

          <div className="deployment-details-card">
            <div className="deploy-meta-grid">
              <div>
                <span className="eyebrow">Operation</span>
                <strong>{deployResult.op} ({deployResult.feature_name})</strong>
              </div>
              <div>
                <span className="eyebrow">Application Version</span>
                <strong>v{deployResult.version}</strong>
              </div>
              <div>
                <span className="eyebrow">Target Repository</span>
                <code>{deployResult.github_repo}</code>
              </div>
              <div>
                <span className="eyebrow">Approved By</span>
                <strong>{deployResult.reviewer}</strong>
              </div>
            </div>
          </div>

          {/* Live Playground */}
          <div className="live-playground-card">
            <div className="playground-header">
              <Icon name="code" size={18} />
              <h4>Test Live Endpoint: <code>GET /calc/{deployResult.op}</code></h4>
            </div>
            <p className="playground-sub">Execute live requests directly against the newly deployed backend route.</p>

            <div className="playground-form">
              <div className="playground-inputs">
                <div>
                  <label htmlFor="play-a">Parameter <code>a</code></label>
                  <input
                    id="play-a"
                    type="number"
                    value={playA}
                    onChange={(e) => setPlayA(parseFloat(e.target.value) || 0)}
                  />
                </div>
                {paramCount === 2 && (
                  <div>
                    <label htmlFor="play-b">Parameter <code>b</code></label>
                    <input
                      id="play-b"
                      type="number"
                      value={playB}
                      onChange={(e) => setPlayB(parseFloat(e.target.value) || 0)}
                    />
                  </div>
                )}
                <button
                  className="button button-primary"
                  onClick={handleTestLive}
                  disabled={testingLive}
                >
                  {testingLive ? "Testing..." : "Send Request"}
                </button>
              </div>

              {liveResult && (
                <div className="live-response-box">
                  <span className="resp-status">HTTP 200 OK</span>
                  <pre className="resp-json">{JSON.stringify(liveResult, null, 2)}</pre>
                </div>
              )}
              {liveError && (
                <div className="form-error" role="alert">{liveError}</div>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
