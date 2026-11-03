# Stage 6 — Six-Agent Integration and Evaluation Report

## 1. Architecture & Integration Audit (Phase 1)

### 1.1 Six Specialist Agent Assignments (`config/models.json`)

| Order | Specialist Agent ID | Assigned Ollama Model | Role & Scoped Evidence Sources (`_specialist_evidence`) | Expected Role Categories (`ROLE_CATEGORIES`) |
|---:|---|---|---|---|
| 1 | `monitoring` | `qwen2.5:3b` | Analyze monitoring metrics and explain anomalies (`metrics`, `system_metrics`, `docker`, `prometheus`, `baseline_comparison`) | `application_metrics`, `infrastructure` |
| 2 | `incident` | `llama3.2:3b` | Triage incident logs and summarize likely root causes (`health`, `metrics`, `system_metrics`, `deployment`, `logs`, `docker`, `prometheus`, `baseline_comparison`) | `application_metrics`, `deployment`, `infrastructure`, `application_log`, `security`, `code` |
| 3 | `code` | `qwen2.5-coder:3b` | Review supplied code-change evidence and identify likely regressions (`code_changes` only) | `code`, `application_log` |
| 4 | `cicd` | `stablelm-zephyr:3b` | Analyze CI/CD deployment and pipeline evidence (`health`, `metrics`, `deployment`, `pipeline`, `logs`, `docker`, `baseline_comparison`, plus `prometheus` when `deployment_changed=True`) | `deployment`, `application_metrics`, `application_log` |
| 5 | `infrastructure` | `phi3.5:3.8b` | Recommend safe infrastructure remediation (`health`, `system_metrics`, `docker`, `prometheus`, `baseline_comparison`) | `infrastructure`, `application_metrics` |
| 6 | `security` | `granite3.1-dense:2b` | Triage security signals and recommend defensive checks (`security_events`, `security_telemetry` only — excludes `docker` and `prometheus`) | `security` |

### 1.2 Agent Selection Logic (`_select_specialists` in `agents/graph.py`)

Agents are selected deterministically from collected evidence, baseline comparison, and operator query before executing in strict `SPECIALIST_ORDER` (`monitoring -> incident -> code -> cicd -> infrastructure -> security`):

- **`monitoring`:** Selected when request metrics (`_request_metrics_available`), host system metrics (`_system_metrics_available`), Docker container metrics (`_docker_metrics_available`), or Prometheus time-series observations (`_prometheus_observations_available`) are available.
- **`incident`:** Selected when `comparison["regression_signal"]` is `True`, the query contains incident keywords (`incident`, `error`, `failure`, `diagnos`), or Docker container incident signals (`_docker_incident_signal`: non-running, unhealthy, or restarted containers) are present.
- **`code`:** Selected when `comparison["regression_signal"]` is `True` or `evidence["code_changes"]["status"]` is in `{"ok", "provided"}`.
- **`cicd`:** Selected when `comparison["deployment_changed"]` is `True`, `evidence["pipeline"]["status"]` is in `{"ok", "failed", "degraded"}`, or `version.data.deployment_status` is in `{"failed", "degraded", "rolled_back"}`.
- **`infrastructure`:** Selected when `health.status == "ok"`, `comparison["deployment_changed"]` is `True`, Prometheus observations are available, or Docker container inventory is available (`status in {"ok", "partial"}` with containers).
- **`security`:** Selected only when security-related terms (`security`, `secure`, `unauthorized`, `forbidden`, `permission`, `injection`, `exploit`, `suspicious`, `authentication`) match the operator query or `logs.events[*].msg`.

### 1.3 Shared LangGraph State (`IncidentState`) & Orchestration Order

The workflow in `agents/graph.py` is compiled with `StateGraph(IncidentState)` and `MemorySaver()`:

1. `collect_evidence` (`_collect_node`) -> Queries `/health`, `/metrics`, `/admin/version`, `logs/app.log`, `collect_system_metrics()`, `collect_docker_metrics()`, and `collect_prometheus_metrics()`.
2. `compare_baseline` (`_compare_node`) -> Compares current evidence against `data/baseline.json` (`_compare_snapshots`), computing `request_deltas`, `new_error_logs`, `deployment_changed`, and `regression_signal`.
3. `analyze_specialists` (`_specialists_node`) -> Extracts deterministic observations via `extract_evidence()`, packages role-scoped evidence via `_specialist_evidence()` / `package_for_role()`, invokes each selected agent **sequentially** via `llm_runtime.analyze()`, validates claims via `_validate_finding()`, and records Prometheus metrics (`devops_agent_executions_total`, `devops_agent_execution_duration_seconds`).
4. `diagnose` (`_diagnose_node`) -> Combines deterministic facts (`_observed_facts`), validated specialist hypotheses (`specialist_hypotheses`), unverified claims (`unverified_claims`), and cross-agent numeric contradictions (`_specialist_conflicts`).
5. `propose_remediation` (`_propose_node`) -> Proposes `rollback` (with `requires_approval: True`) **only** when `comparison.status in {"ok", "partial"}`, `version` and `{"metrics", "logs"}` are comparable, `deployment_changed` and `regression_signal` are both `True`, and the version history target matches `baseline_version`. Otherwise proposes `investigate` (when `regression_signal` is `True`) or `none`.
6. Conditional routing (`_route_remediation`):
   - If `remediation.action == "rollback"` -> `request_approval` (`_approval_node`), which calls LangGraph `interrupt(...)` to pause execution for human review.
   - Otherwise -> `record_outcome` (`_record_node`) -> `final_report` (`_report_node`) -> `END`.
7. Upon `POST /incidents/{id}/approval` (`Command(resume=approved)`):
   - If `approved is True` -> `apply_remediation` (`_apply_node`) calls `POST /admin/rollback` and verifies `/health` version matches `target_version`.
   - If `approved is False` -> `record_outcome` records `status: "rejected"` without calling `/admin/rollback`.

### 1.4 Error Handling & Retry Behavior (`agents/llm_runtime.py`)

- **Strict Output Contract (`RESPONSE_SCHEMA`):** Every specialist must return a JSON object with exactly four fields (`summary: str`, `findings: list[str]`, `confidence: float` in `[0, 1]`, `recommended_checks: list[str]`) and `additionalProperties: False`.
- **Single Validation Retry:** If attempt 1 returns malformed JSON, fails schema validation, or is truncated at the token limit (`done_reason == "length"`), `llm_runtime.analyze()` appends a validation-error correction prompt and retries **at most once** (max 2 attempts total).
- **Transport Failure Isolation:** `requests.Timeout` (`status="timeout"`), `requests.ConnectionError` (`status="unavailable"`), and other `requests.RequestException` errors do not retry and never crash the workflow; `_specialists_node` records the agent status and continues to the next selected specialist.

### 1.5 Integration Gaps Identified and Resolved in Stage 6

1. **Direct `code_changes` and `pipeline` Selection Signals (`agents/graph.py`):** Previously, `_select_specialists()` selected `code` only when `comparison["regression_signal"]` was `True` and `cicd` only when `comparison["deployment_changed"]` was `True`. If `code_changes` was explicitly supplied without a baseline comparison delta, or if a CI/CD pipeline failed before promoting a new version (`deployment_changed=False`, `pipeline.status="failed"`), those specialists were skipped. Updated `_select_specialists()` to also select `code` when `code_changes.status in {"ok", "provided"}` and `cicd` when `pipeline.status in {"ok", "failed", "degraded"}` or `version.data.deployment_status in {"failed", "degraded", "rolled_back"}`.
2. **Guaranteed Model Attribution on Specialist Results (`agents/graph.py`):** Updated `_specialists_node()` so every specialist entry in `state["specialists"]["results"][agent]` always includes `"model": configured_model` even if an unexpected exception or non-dict return occurs.

---

## 2. Cross-Agent Reasoning Evaluation Across 7 Scenarios (Phase 3)

All 7 scenarios are deterministically verified in [`tests/test_six_agent_integration.py`](file:///d:/devops-agents-six-model-agents/devops-agents/tests/test_six_agent_integration.py):

| # | Scenario | Selected Specialists | Unselected Specialists | Key Findings & Cross-Agent Synthesis | Remediation & Grounding Outcome |
|---:|---|---|---|---|---|
| 1 | **CPU Utilization Spike** (`94%` CPU, `0` errors) | `monitoring`, `incident`, `infrastructure` | `code`, `cicd`, `security` | All 3 selected agents link `94%` CPU to `system_metrics.measurements.cpu_usage_percent` and `docker.containers[0].cpu_usage_percent`; no error regression detected. | `action: "none"`, `unverified_claims: []`, `specialist_conflicts: []`. |
| 2 | **Memory Pressure** (`88%` host memory, `750 MiB` container memory) | `monitoring`, `incident`, `infrastructure` | `code`, `cicd`, `security` | Links `88%` memory and `750 MiB` (`786432000` bytes) to source paths. An invented `512 MiB` limit claim by `infrastructure` is caught by `_validate_finding`. | Flagged in `diagnosis.unverified_claims`; not promoted to `verified_observations`. |
| 3 | **Application HTTP Errors** (`12` `div` errors / `20%` error rate + `code_changes`) | `monitoring`, `incident`, `code`, `infrastructure` | `cicd`, `security` | `monitoring` & `incident` link `20%` error rate (`12/60`); `code` reviews `ZeroDivisionError` snippet. Because version stayed `1.0` (`deployment_changed=False`), no rollback is proposed. | `action: "investigate"`, `requires_approval: False`. |
| 4 | **Dependency Failure** (`upstream dependency connection timeout` in logs) | `monitoring`, `incident`, `infrastructure` | `code`, `cicd`, `security` | Correlates `5` `add/error` requests with timeout logs while keeping external dependency cause as an unconfirmed hypothesis. | `action: "investigate"`, no invented root cause. |
| 5 | **CI/CD Deployment Failure & Post-Deploy Regression** | Part A (failed pipeline): `monitoring`, `incident`, `cicd`, `infrastructure`<br>Part B (`v1.0 -> v1.1` + errors): `monitoring`, `incident`, `code`, `cicd`, `infrastructure` | `security` | Part A selects `cicd` on `pipeline.status="failed"`. Part B correlates `v1.0 -> v1.1` with `10` `div` errors and emits deterministic hypothesis `"correlation does not establish causation"`. | Part B proposes `action: "rollback"`, `target_version: "1.0"`, `requires_approval: True`. |
| 6 | **Infrastructure Configuration Problem & Conflict Detection** (`unhealthy` container, `4` restarts, conflicting CPU claims `92%` vs `45%`) | `monitoring`, `incident`, `infrastructure` | `code`, `cicd`, `security` | `_specialist_conflicts()` detects the numeric contradiction on topic `cpu` (`92.0%` vs `45.0%`) and flags `45%` as `unverified`. | Conflict recorded in `diagnosis.specialist_conflicts` with `"observed evidence remains authoritative"`. |
| 7 | **Security-Related Incident** (`authentication failed` + `unauthorized access` from `192.0.2.50`) | `monitoring`, `incident`, `infrastructure`, `security` | `code`, `cicd` | `security` receives only `security_events` (no `docker`/`prometheus`). Links `192.0.2.50` to `security_events.events[0].msg` and flags unsupported `"threat intelligence confirms a credential stuffing botnet"` claim. | Unsupported attribution isolated in `diagnosis.unverified_claims`; `action: "none"`. |

---

## 3. Safety & Human Approval Gate Verification (Phase 4)

Verified in [`test_safety_and_approval_gate_invariants_across_all_failure_and_decision_paths`](file:///d:/devops-agents-six-model-agents/devops-agents/tests/test_six_agent_integration.py#L961-L1157):

1. **No Automatic Remediation:** `POST /incidents` never invokes `_rollback()`, even when specialists return `confidence: 1.0`.
2. **Rollback Behind Explicit Human Approval:** Rollback proposals pause at LangGraph `interrupt()` with `status: "pending_approval"` until `POST /incidents/{id}/approval` is called.
3. **Rejection Blocks Execution:** `decision: "reject"` transitions the incident to `outcome.status == "rejected"` with zero calls to `/admin/rollback`.
4. **Duplicate Approval Prevention:** Calling `POST /incidents/{id}/approval` a second time on a decided or completed incident returns HTTP `409 Conflict`.
5. **Accurate Audit Trail:** Every lifecycle step (`incident_started`, `diagnosis_finished`, `approval_decision`, `action_finished`) is appended to `incident_audit.jsonl` without raw queries or secrets.
6. **Unavailable Specialist Safety:** When `incident` (`llama3.2:3b`) is `unavailable`, the workflow still enforces the `pending_approval` gate for rollback.
7. **Incomplete Diagnosis Safety:** When baseline comparison is `unavailable`, `_propose_node` returns `action: "none"` (`requires_approval: False`) and cannot trigger rollback.

---

## 4. Measured Evaluation Metrics & Reporting (Phase 5)

### 4.1 Measured Historical Live Ollama Evaluation Results (Preserved in `reports/`)

The table below reports **exact measured metrics** from the preserved 3-repetition controlled live evaluation ([`reports/prompt_7_2_repeated_evaluation.json`](file:///d:/devops-agents-six-model-agents/devops-agents/reports/prompt_7_2_repeated_evaluation.json), `21` total live runs = `18` specialist scenario runs + `3` negative-control runs) and single-pass evaluations ([`reports/six_agent_live_evaluation.json`](file:///d:/devops-agents-six-model-agents/devops-agents/reports/six_agent_live_evaluation.json), [`reports/prompt_7_1_live_evaluation.json`](file:///d:/devops-agents-six-model-agents/devops-agents/reports/prompt_7_1_live_evaluation.json)):

| Specialist Agent | Model | Live Runs (`Prompt 7.2`) | Inference Success Rate | Inference Failure / Timeout Rate | Schema-Valid Output Rate | Correction Retries | Mean Wall Duration (s) | Min / Max Duration (s) | Measured P95 Duration (s) | Evidence Extraction / Delivery Rate | Rubric Interpretation Mean | Validator Grounding Mean | Unsupported Claims / Total Claims |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `monitoring` | `qwen2.5:3b` | 3 | `100.0%` (3/3) | `0.0%` (0/3) | `100.0%` (3/3) | 0 | `14.24s` | `10.33s` / `18.64s` | `18.65s` | `100.0%` | `83.3%` | `90.9%` | `3 / 33` (`9.1%`) |
| `incident` | `llama3.2:3b` | 3 | `100.0%` (3/3) | `0.0%` (0/3) | `100.0%` (3/3) | 0 | `10.24s` | `7.00s` / `16.04s` | `16.04s` | `100.0%` | `0.0%` | `100.0%` | `0 / 3` (`0.0%`) |
| `code` | `qwen2.5-coder:3b` | 3 | `100.0%` (3/3) | `0.0%` (0/3) | `100.0%` (3/3) | 0 | `7.90s` | `7.52s` / `8.61s` | `8.61s` | `100.0%` | `77.8%` | `66.7%` | `3 / 9` (`33.3%`) |
| `cicd` | `stablelm-zephyr:3b` | 3 | `100.0%` (3/3) | `0.0%` (0/3) | `100.0%` (3/3) | 1 | `12.39s` | `7.71s` / `19.88s` | `19.88s` | `100.0%` | `0.0%` | `84.8%` | `5 / 27` (`18.5%`) |
| `infrastructure` | `phi3.5:3.8b` | 3 | `100.0%` (3/3) | `0.0%` (0/3) | `100.0%` (3/3) | 0 | `10.35s` | `10.05s` / `10.72s` | `10.73s` | `100.0%` | `28.6%` | `66.7%` | `7 / 21` (`33.3%`) |
| `security` | `granite3.1-dense:2b` | 3 | `100.0%` (3/3) | `0.0%` (0/3) | `100.0%` (3/3) | 0 | `9.17s` | `8.86s` / `9.70s` | `9.70s` | `100.0%` | `24.0%` | `76.2%` | `3 / 13` (`23.1%`) |
| **Negative Control (`infrastructure`)** | `phi3.5:3.8b` | 3 | `100.0%` (3/3) | `0.0%` (0/3) | `100.0%` (3/3) | 0 | — | — | — | `100.0%` | `100.0%` | `100.0%` | `0 / 9` (`0.0%`) |

*Verified aggregate:* 21 of 106 claims were unsupported across 18 specialist runs.

### 4.2 Measured Deterministic CI Integration Suite Metrics (`tests/test_six_agent_integration.py`)

- **End-to-End Workflow Success Rate (Mocked CI Suite):** `100.0%` (`13/13` tests in `test_six_agent_integration.py`, `191/191` total backend tests passing).
- **Deterministic Evidence Extraction & Delivery Completeness:** `30/30` (`100.0%`) required facts extracted and delivered across all 6 specialist roles (`test_prompt7_offline_report_tracks_extraction_delivery_without_inference`).
- **Cross-Agent Conflict Detection Rate:** `100.0%` on injected numeric contradictions (`_specialist_conflicts` flags conflicting numeric claims on the same topic and preserves observed telemetry as authoritative).

---

## 5. Hardware & Runtime Constraints Verification (Phase 6)

- **Configuration (`config/models.json`):**
  - `max_parallel_models`: `1`
  - `keep_alive`: `"0s"` (each specialist model is unloaded from VRAM immediately after generating its response)
  - `context_length`: `2048` tokens (`num_ctx: 2048`)
  - `max_output_tokens`: `384` tokens (`num_predict: 384`)
  - `request_timeout_seconds`: `120` seconds
  - `temperature`: `0.1`
- **Measured Hardware Observations (`reports/prompt_7_1_live_evaluation.json` & `reports/prompt_7_2_repeated_evaluation.json`):**
  - **Local GPU:** NVIDIA GeForce RTX 3050 Laptop GPU, 6 GB (6144 MiB) (`Ollama 0.40.13`, `Python 3.12.3`).
  - **Sequential Overlap:** `sequential_overlap_detected = False` across all historical live runs (`6/6` in Prompt 6.0, `6/6` in Prompt 7.1, `21/21` in Prompt 7.2).
  - **VRAM Unload Verification:** `models_loaded_before = 0` and `models_loaded_after = 0` (`keep_alive="0s"` verified).
  - **Context Budget Compliance:** `22/22` (`100.0%`) measured attempts in Prompt 7.2 remained `within_budget` (`0` `potential_context_pressure`, `0` `context_pressure`).

---

## 6. Remaining Limitations

1. **Small-Model (2B–3.8B) Omission & Rounding Variance:** While schema validity (`21/21`) and evidence delivery (`30/30`) are `100%`, small 2B–3.8B models occasionally omit secondary rubric facts (e.g., `incident` and `cicd` summarizing high-level conclusions without repeating every baseline number) or round `16.6667%` to `16.67%` (which the strict numeric validator flags as `unverified`).
2. **Heuristic Grounding Validator:** `_validate_finding()` in `agents/graph.py` validates numeric claims, evidence paths, IP addresses, timestamps, and source-availability statements against supplied evidence, but natural-language claims without numeric/path anchors are conservatively marked `unverified` (`confidence_is_proof: False`).
3. **In-Memory Workflow Checkpoints (`MemorySaver`):** LangGraph state checkpoints are stored in memory, so an interrupted `pending_approval` thread cannot be resumed after a container restart (though `devops_incidents_current_status` gauges are reconstructed from `incident_audit.jsonl`).
