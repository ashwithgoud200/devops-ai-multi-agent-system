# Agent responsibilities and model configuration

The supervisor in `agents/graph.py` selects relevant roles from the incident and available evidence. The following model assignments are preserved in `config/models.json`:

| Agent key | Responsibility | Ollama model |
|---|---|---|
| `monitoring` | Explain observed application, host, Prometheus, and Docker metric anomalies. | `qwen2.5:3b` |
| `incident` | Correlate new errors, logs, metric deltas, and deployment changes; propose root-cause hypotheses. | `llama3.2:3b` |
| `code` | Review supplied code-change evidence for likely regressions. Git diff retrieval is not connected, so code evidence may be unavailable. | `qwen2.5-coder:3b` |
| `cicd` | Interpret deployment/version and pipeline evidence. | `stablelm-zephyr:3b` |
| `infrastructure` | Assess infrastructure health and safe, evidence-backed operational checks. | `phi3.5:3.8b` |
| `security` | Triage security-related signals in supplied logs. No dedicated security event source or scanner is connected. | `granite3.1-dense:2b` |

## Runtime configuration

| Setting | Default | Meaning |
|---|---:|---|
| `enabled` | `false` | Persistent model inference stays disabled unless the operator opts in for the current process/session. |
| `max_parallel_models` | `1` | Agents run sequentially; Ollama calls also share a process-wide lock. |
| `keep_alive` | `0s` | Request unloading after a response to reduce retained model memory. |
| `context_length` | `2048` | Configured Ollama context (`num_ctx`). |
| `max_output_tokens` | `384` | Configured Ollama output budget (`num_predict`). |
| `request_timeout_seconds` | `120` | Per-request timeout. |
| `temperature` | `0.1` | Configured generation temperature. |

Do not edit assignments or budgets to make setup work. Ollama must already be installed and the six tags must already be present before inference can run. The app does not download models. `scripts/pull_models.ps1` is an explicit, optional download action invoked by the operator.

On Windows PowerShell, opt into model calls only in the current terminal:

```powershell
$env:DEVOPS_LLM_ENABLED = "true"
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
ollama list
```

Clear the override or start a fresh terminal to return to the disabled-by-default configuration. A successful local API health check does not demonstrate that an Ollama model is installed or working. Individual model inference was not re-run as part of the Prompt 8 offline checks.

## Output contract and safety

Each model response must satisfy the shared JSON schema (`summary`, `findings`, `confidence`, `recommended_checks`). Invalid responses, unavailable models, and timeouts are represented as agent results; they do not become evidence. Findings are checked against the supplied specialist evidence and retain source references. Unsupported claims remain explicitly unverified. Only the deterministic supervisor and a separate human approval decision can reach the existing rollback action.
