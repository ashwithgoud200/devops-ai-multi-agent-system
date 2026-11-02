# Stage 1 — Six-Agent Ollama Model Verification Report

**Project:** AI-Based DevOps Automation and Monitoring — Multi-Agent System  
**Project Directory:** `D:\devops-agents-six-model-agents\devops-agents`  
**Date:** 2026-11-02  
**Verification Scope:** Verification of local Ollama availability, specialist agent model mappings, sequential live inference execution, test-suite regression, and configuration integrity.

---

## 1. Executive Summary

- **Overall Verification Status:** **PASS**
- **Number of Specialist Agents Configured:** 6
- **Number of Specialist Agents Verified:** 6 of 6 (100%)
- **Number of Target Models Installed:** 6 of 6 (100%)
- **Number of Successful Live Inference Calls:** 6 of 6 (100%)
- **Total In-Flight Retries Required:** 0 (all 6 models returned valid schema on attempt 1)
- **Total Test Suite Results:** 160 passed, 0 failed, 0 skipped (100% pass rate in 2.82s)

All six specialist agents successfully invoked their assigned local Ollama models through the existing `agents.llm_runtime.analyze()` runtime without architecture changes or configuration drift.

---

## 2. Ollama Environment

- **Ollama CLI Version:** `0.40.13`
- **Ollama Service Status:** Active and responsive at `http://127.0.0.1:11434`
- **Python Environment:** `D:\devops-agents-six-model-agents\devops-agents\.venv\Scripts\python.exe`
- **Python Version:** 3.12.3 (64-bit Windows)
- **Pytest Version:** 9.2.0

### Installed Ollama Models (`ollama list`)

| Model Tag | Model ID | Size | Modified | Verification Status |
|---|---|---|---|---|
| `qwen2.5:3b` | `357c53fb659c` | 1.9 GB | 16 hours ago | Installed & Verified |
| `llama3.2:3b` | `a80c4f17acd5` | 2.0 GB | 16 hours ago | Installed & Verified |
| `qwen2.5-coder:3b` | `f72c60cabf62` | 1.9 GB | 16 hours ago | Installed & Verified |
| `stablelm-zephyr:3b` | `0a108dbd846e` | 1.6 GB | 15 hours ago | Installed & Verified |
| `phi3.5:3.8b` | `61819fb370a3` | 2.2 GB | 15 hours ago | Installed & Verified |
| `granite3.1-dense:2b` | `fba1ad01113e` | 1.6 GB | 15 hours ago | Installed & Verified |

*Note: No models were pulled or downloaded during this verification; all six models were pre-installed.*

---

## 3. Model Mapping Verification

Verification of specialist agent implementations against `config/models.json` and `agents/graph.py`:

| Agent | Expected Model | Actual Configured Model | Runtime Invocation Path | Mapping Status |
|---|---|---|---|---|
| **Monitoring** | `qwen2.5:3b` | `qwen2.5:3b` | `graph._specialists_node()` -> `llm_runtime.analyze("monitoring", ...)` | **MATCH** |
| **Incident** | `llama3.2:3b` | `llama3.2:3b` | `graph._specialists_node()` -> `llm_runtime.analyze("incident", ...)` | **MATCH** |
| **Code** | `qwen2.5-coder:3b` | `qwen2.5-coder:3b` | `graph._specialists_node()` -> `llm_runtime.analyze("code", ...)` | **MATCH** |
| **CI/CD** | `stablelm-zephyr:3b` | `stablelm-zephyr:3b` | `graph._specialists_node()` -> `llm_runtime.analyze("cicd", ...)` | **MATCH** |
| **Infrastructure** | `phi3.5:3.8b` | `phi3.5:3.8b` | `graph._specialists_node()` -> `llm_runtime.analyze("infrastructure", ...)` | **MATCH** |
| **Security** | `granite3.1-dense:2b` | `granite3.1-dense:2b` | `graph._specialists_node()` -> `llm_runtime.analyze("security", ...)` | **MATCH** |

**Mapping Discrepancies:** None. All configured models match expected role assignments.

---

## 4. Live Inference Results

Live inference was executed sequentially (1-by-1, guarded by process lock and `max_parallel_models: 1`). Memory was freed after each call via `keep_alive: "0s"`.

| Agent | Model | Installed | Inference Status | Latency | Retries | Output / Prompt Tokens | Done Reason |
|---|---|---|---|---|---|---|---|
| **Monitoring** | `qwen2.5:3b` | Yes | **ok** | 6.854s | 0 (`not_needed`) | 100 / 416 | `stop` |
| **Incident** | `llama3.2:3b` | Yes | **ok** | 7.399s | 0 (`not_needed`) | 86 / 428 | `stop` |
| **Code** | `qwen2.5-coder:3b` | Yes | **ok** | 6.916s | 0 (`not_needed`) | 89 / 399 | `stop` |
| **CI/CD** | `stablelm-zephyr:3b` | Yes | **ok** | 6.243s | 0 (`not_needed`) | 163 / 445 | `stop` |
| **Infrastructure** | `phi3.5:3.8b` | Yes | **ok** | 7.401s | 0 (`not_needed`) | 169 / 465 | `stop` |
| **Security** | `granite3.1-dense:2b` | Yes | **ok** | 5.477s | 0 (`not_needed`) | 133 / 467 | `stop` |

- **Sequential execution total duration:** 40.29s.
- **Failures / HTTP errors / Timeouts:** 0.

---

## 5. Runtime Metrics

Detailed metrics captured directly from Ollama `/api/chat` responses:

| Agent | Model | Prompt Tokens (`prompt_eval_count`) | Output Tokens (`eval_count`) | Done Reason | Total Duration | Load Duration | Prompt Eval Duration | Eval Duration |
|---|---|---|---|---|---|---|---|---|
| **Monitoring** | `qwen2.5:3b` | 416 | 100 | `stop` | 6.838s (6,838,489,800 ns) | 4.909s (4,909,086,900 ns) | 0.347s (347,419,000 ns) | 1.536s (1,536,039,000 ns) |
| **Incident** | `llama3.2:3b` | 428 | 86 | `stop` | 7.395s (7,395,440,200 ns) | 5.392s (5,391,987,900 ns) | 0.499s (498,614,000 ns) | 1.442s (1,442,113,000 ns) |
| **Code** | `qwen2.5-coder:3b` | 399 | 89 | `stop` | 6.886s (6,885,906,000 ns) | 5.095s (5,094,651,600 ns) | 0.344s (344,181,000 ns) | 1.414s (1,414,131,000 ns) |
| **CI/CD** | `stablelm-zephyr:3b` | 445 | 163 | `stop` | 6.238s (6,237,509,600 ns) | 3.534s (3,533,848,100 ns) | 0.211s (211,266,000 ns) | 2.397s (2,396,962,000 ns) |
| **Infrastructure** | `phi3.5:3.8b` | 465 | 169 | `stop` | 7.395s (7,395,353,700 ns) | 4.046s (4,046,394,100 ns) | 0.259s (258,603,000 ns) | 3.040s (3,039,649,000 ns) |
| **Security** | `granite3.1-dense:2b` | 467 | 133 | `stop` | 5.474s (5,474,191,900 ns) | 3.357s (3,357,434,300 ns) | 0.289s (288,977,000 ns) | 1.678s (1,678,011,000 ns) |

### Context Budget Analysis
All six inference calls stayed well within the configured 2,048 context length:
- **Remaining headroom:** ~1,197 to 1,265 tokens per request.
- **Context pressure risk:** `false` across all 6 models.

---

## 6. Response Quality & Task Solving Observations

While all six models satisfied the JSON output schema (`summary`, `findings`, `confidence`, `recommended_checks`) and completed inference successfully, inspection of the actual content reveals meaningful qualitative distinctions:

1. **Monitoring (`qwen2.5:3b`) — High Grounding Adherence:**
   - Addressed the prompt by identifying CPU alert implications while correctly labeling the lack of concrete CPU telemetry as `"Insufficient evidence: CPU utilization alert details."` Confidence was calibrated at 0.5. Recommended appropriate checks.
2. **Incident (`llama3.2:3b`) — Relevant Operational Reasoning:**
   - Synthesized plausible root-cause hypotheses for HTTP 500 errors (insufficient memory allocation) with specific diagnostic checks.
3. **Code (`qwen2.5-coder:3b`) — Specialist Evidence Constraint:**
   - Prompt requested: *"Write a simple Python function that checks whether a number is even."*
   - Because the runtime system prompt strictly instructs the agent to *"Review only supplied code_changes"* and *"Never invent or estimate"*, the model strictly refused to hallucinate code changes, returning: `"The provided code change does not address the task of checking if a number is even."` with confidence 0.0. This demonstrates strict adherence to the role's grounding guardrails, though it did not answer the prompt's coding request in isolation.
4. **CI/CD (`stablelm-zephyr:3b`) — Evidence Conflation:**
   - The model conflated the test fixture metadata (`"Agent-specific live inference verification test"`) with production pipeline behavior, summarizing: `"A CI/CD pipeline might fail during its test stage due to agent-specific live inference verification test failures."` While schema-compliant, the reasoning reflected prompt/context bleed.
5. **Infrastructure (`phi3.5:3.8b`) — Synthetic Path Invention:**
   - The model explained the container health check concept clearly but generated a fabricated JSON path (`"live_verification/docker.containers/container_id/health_check"`) to satisfy the schema's citation constraint.
6. **Security (`granite3.1-dense:2b`) — Sound Defensive Triage:**
   - Identified exposure risk for unauthenticated APIs, calibrated confidence at 0.9, and recommended proper authentication checks and log audits.

---

## 7. Test Results

### Focused Test Results
- **LLM Runtime Unit Tests (`tests/test_llm_runtime.py`):** 21 passed (0.07s)
- **Specialist Evidence Extractor (`tests/test_evidence_extractor.py`):** 12 passed (0.71s)
- **LangGraph Supervisor & Specialists (`tests/test_graph.py`):** 33 passed (1.03s)
- **Telemetry Collection Tests (`tests/test_telemetry.py`):** 20 passed (0.85s)
- **Prometheus Telemetry Tests (`tests/test_prometheus_telemetry.py`):** 18 passed (0.85s)
- **Docker Telemetry Tests (`tests/test_docker_telemetry.py`):** 10 passed (1.06s)
- **Grafana Configuration Tests (`tests/test_grafana_config.py`):** 5 passed (0.07s)
- **Deployment Safety Tests (`tests/test_deployment_safety.py`):** 1 passed (0.03s)
- **Demo Runner Tests (`tests/test_run_demo.py`):** 2 passed (0.71s)
- **Live Evaluation Fixtures (`tests/test_live_agent_evaluation.py`):** 28 passed (1.22s)
- **Calculator App API Tests (`tests/test_app.py`):** 5 passed (1.01s)
- **Incident API Approval Tests (`tests/test_incident_api.py`):** 5 passed (0.78s)

### Complete Offline Test Suite
Executed via `.venv\Scripts\python.exe -m pytest -q`:
- **Total Tests Collected:** 160
- **Passed:** 160
- **Failed:** 0
- **Skipped:** 0
- **Duration:** 2.82 seconds

---

## 8. Configuration Integrity

Integrity verification of `config/models.json`:
- **Six Model Mappings:** Confirmed identical and unchanged.
- **Default `enabled` Setting:** Confirmed `false`.
- **`max_parallel_models`:** Confirmed `1`.
- **`keep_alive`:** Confirmed `"0s"`.
- **`context_length`:** Confirmed `2048`.
- **`max_output_tokens`:** Confirmed `384`.
- **`request_timeout_seconds`:** Confirmed `120`.
- **`temperature`:** Confirmed `0.1`.

---

## 9. Known Limitations

1. **Local Socket Permissions in Sandboxed Test Execution:**
   - Starlette `TestClient` (used in `test_app.py` and `test_incident_api.py`) relies on `anyio` and Windows `socket.socketpair()` on `127.0.0.1` to initialize the asyncio runner. In Windows standard sandbox mode without socket/network permissions, local loopback connection fails to complete, causing `TestClient` to hang indefinitely. Running with socket permission (`BypassSandbox: true`) executes all tests in under 2 seconds.
2. **Context-Grounding Tradeoff:**
   - As observed with `qwen2.5-coder:3b`, strict negative-constraint system prompts prevent the specialist from generating generic code when no code diff is provided in the input evidence.
3. **Evidence Conflation on Small Models:**
   - Smaller models (e.g., `stablelm-zephyr:3b` and `phi3.5:3.8b`) occasionally blend fixture metadata strings into their natural language explanations or fabricate evidence paths to meet citation requirements.

---

## 10. Final Status

### **PASS**

All six specialist agents successfully connected to their assigned local Ollama models (`qwen2.5:3b`, `llama3.2:3b`, `qwen2.5-coder:3b`, `stablelm-zephyr:3b`, `phi3.5:3.8b`, `granite3.1-dense:2b`), executed live inference sequentially through `agents.llm_runtime.analyze()`, and returned valid, non-empty, schema-compliant responses without errors. All 160 offline unit tests pass, and configuration integrity was fully maintained.

