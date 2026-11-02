# devops-ai-multi-agent-system

## AI DevOps Multi-Agent System

This project combines a FastAPI sample service with a LangGraph incident-response workflow, deterministic evidence extraction, six sequential Ollama specialists, Prometheus/Grafana observability, optional read-only Docker telemetry, and human-approved remediation. Specialist output is advisory; only observed evidence supports diagnosis, and rollback cannot run without an explicit decision.

The local API is documented in [docs/api.md](./docs/api.md), roles and model configuration in [docs/agents.md](./docs/agents.md), and the workflow diagram in [docs/architecture.md](./docs/architecture.md). FastAPI's interactive API reference is available at `http://127.0.0.1:8100/docs`.

## Phase 2 capabilities

- GitHub Actions runs API regression tests on Python 3.11 and 3.12 for pull requests and pushes.
- Docker builds a small, non-root application image with a container health check.
- Successful builds on `main`/`master` and version tags are published to GitHub Container Registry (GHCR).
- An optional server deployment runs after a push to `main` when deployment secrets are configured. Failed health checks stop the job; no image rollback is automatic, and an operator must investigate/recover.
- `/health` is used by Docker and the deployment workflow for readiness verification.

## Windows PowerShell setup

Use Python 3.11 or 3.12. These commands install only Python dependencies; they do not download LLM models or enable inference.

```powershell
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

If PowerShell blocks environment activation, either allow it for the current process with `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` or call `.\.venv\Scripts\python.exe` and `.\.venv\Scripts\uvicorn.exe` directly.

Start the local API (keep this terminal open):

```powershell
python -m uvicorn calculator_app.app:app --host 127.0.0.1 --port 8100
```

In another PowerShell terminal, verify readiness and open the interactive API documentation:

```powershell
Invoke-RestMethod http://127.0.0.1:8100/health
Start-Process http://127.0.0.1:8100/docs
```

Save a baseline and start a diagnosis using the endpoints documented in [docs/api.md](./docs/api.md). `/health`, `/metrics`, `/telemetry/docker`, `/telemetry/prometheus`, `/baseline`, and `/incidents` are useful entry points.

## Synthetic end-to-end demo

The demo generates healthy traffic, saves a baseline, injects a synthetic v1.1 division regression, collects evidence, and pauses for the operator's decision before rollback. The default is interactive; it does not auto-approve.

```powershell
python run_demo.py
```

To explicitly choose a path without the interactive prompt, run `python run_demo.py --reject` or `python run_demo.py --approve`. The demo API binds to loopback. If port 8100 is in use, select an unused port, for example `$env:DEVOPS_DEMO_PORT = "18100"` before running it.

## Docker Compose observability stack

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8100/health
Invoke-RestMethod http://127.0.0.1:9090/-/healthy
Invoke-RestMethod http://127.0.0.1:3000/api/health
docker compose down
```

The app, Prometheus, and Grafana ports bind to loopback. Compose persists its baseline and audit/log files in named volumes. The app container has no Docker Engine socket/CLI, so its Docker telemetry endpoint correctly reports `unavailable`; run the app on the host to use Docker Desktop telemetry. Grafana's `.env.example` credentials are development placeholders; change them before local shared use.

## GitHub Actions and GHCR setup

1. Push this repository to GitHub, using `main` as the default branch.
2. In **Settings → Actions → General**, allow the workflow to create and write packages (the workflow requests `packages: write` for the publish job).
3. Push to `main` or create a version tag such as `v1.0.0`.
4. Open **Actions** to inspect test, build, and publish results. The image is published as `ghcr.io/<owner>/<repository>` with branch/tag/SHA tags and `latest` on the default branch.
5. For a private GHCR package, configure package access for the server's pull identity. For a public package, the server can pull without authentication.

## Optional automatic server deployment

The `deploy` job runs only on pushes to `main`. Add these repository **Actions secrets**:

| Secret | Purpose |
|---|---|
| `DEPLOY_HOST` | Public DNS name or IP of the Linux Docker host |
| `DEPLOY_USER` | SSH user on that host |
| `DEPLOY_SSH_KEY` | Private SSH key; install its public key in `authorized_keys` |
| `DEPLOY_KNOWN_HOSTS` | Recommended pinned `known_hosts` entry for the host |

The deploy job uses the workflow's temporary `GITHUB_TOKEN` to log in to GHCR, pulls the newly built `latest` image, runs `scripts/deploy_remote.sh`, and checks `/health`. On failed health checks the workflow stops without automatically restoring an image; inspect the failed container and manually deploy a known-good immutable image if needed. The GitHub Actions job itself runs automatically on pushes to `main` when deployment secrets are present. Ensure the server has Docker Engine installed and allows inbound SSH plus TCP port 8100. Restrict port 8100 with a firewall or reverse proxy in real deployments; do not expose the sample admin endpoints publicly.

For a private production deployment, prefer a dedicated read-only GHCR token on the server rather than relying on a broadly privileged personal token. Also use a staging environment and approval protection before production.

## Current boundaries

This phase delivers CI, test automation, Docker image build/publish, and an optional single-host container deployment. It does **not** yet provide a full production release strategy, Kubernetes rollout, database migration orchestration, secrets vault, signed image provenance, or automated multi-environment promotion. The incident workflow reads the calculator service's health, Prometheus-format `/metrics` exporter, version history, and a local JSON log file; CI/CD still builds and deploys the calculator service image.

## Existing agent demo

The LangGraph demo runs the calculator service itself. It collects available health, metrics, version-history, host CPU/memory, and local JSONL-log evidence; compares it with `data/baseline.json`; and writes the baseline atomically when `save_baseline()` is called. The baseline records the log file identity and byte cursor so comparisons examine appended events, including entries without timestamps; if the file is replaced or truncated, the incremental window is marked unavailable rather than misclassifying old entries as new. Legacy baselines without a cursor use timestamps conservatively. Unavailable integrations and a missing baseline are reported rather than treated as empty or healthy evidence.

```powershell
python run_demo.py
```

The demo verifies that its own API subprocess starts and becomes ready before generating traffic; it fails instead of using an unrelated service if startup fails. On a host where port 8100 is already in use, choose a free port, for example in PowerShell: `$env:DEVOPS_DEMO_PORT = "18100"` before running the commands.

For a version change accompanied by new request errors or error logs, the workflow may propose rollback. It pauses for an explicit human decision; the demo prompts interactively by default, while `--approve` is an explicit opt-in and `--reject` exercises rejection. Approval is followed by health/version verification. Rejection never sends a rollback request. Specialist findings are recorded as hypotheses and cannot authorize actions.

## Six specialized local-model agents (RTX 3050 8GB profile)

The LangGraph workflow routes relevant evidence to these specialist roles through the shared `agents/llm_runtime.py` Ollama client:

| Agent | Default Ollama model | Focus |
|---|---|---|
| Monitoring | `qwen2.5:3b` | Explain metric anomalies |
| Incident | `llama3.2:3b` | Triage error logs and root-cause hypotheses |
| Code/Repo | `qwen2.5-coder:3b` | Review supplied code-change evidence |
| CI/CD | `stablelm-zephyr:3b` | Analyze deployment/pipeline evidence |
| Infrastructure | `phi3.5:3.8b` | Review safe remediation proposals |
| Security | `granite3.1-dense:2b` | Defensive security-signal triage |

**Parameter-size note:** this practical six-model set is in the compact ~2B–3.8B class; it is not six models that are each exactly 3.0B parameters. The exact model tags are configurable in `config/models.json`. Check Ollama's model library for tag availability before pulling; replace a tag in that file if a tag is unavailable in your Ollama version.

### Optional Ollama setup on Windows

Local model inference is opt-in. The application starts with `enabled: false`; no models are downloaded automatically. Install Ollama separately and verify `ollama --version` and `ollama list`. Only if you choose to download the configured models, run this explicit command from the repository root:

```powershell
.\scripts\pull_models.ps1
```

The script downloads the six configured model tags. Review [docs/agents.md](./docs/agents.md) and `config/models.json` first. Do not edit the mappings, parallelism, or context/output settings as part of setup.

To opt into local inference for the current PowerShell session only:

```powershell
$env:DEVOPS_LLM_ENABLED = "true"
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
```

Then run the service or synthetic demo in that same session. Return to deterministic-only behavior by setting `$env:DEVOPS_LLM_ENABLED = "false"` or closing the terminal. Do not enable inference in a permanent config file.

### Sequential inference configuration

- The six agents have separate model assignments and role instructions, but **do not load six models simultaneously**.
- Ollama requests are serialized by a process-wide lock; the default `keep_alive: "0s"` asks Ollama to unload each model after its response.
- `max_parallel_models` is fixed at `1`; `context_length` is `2048`; `max_output_tokens` is `384`. See [docs/agents.md](./docs/agents.md) for all settings.
- Actual GPU placement depends on Ollama's installed build, runtime defaults, and available VRAM.
- No model-to-agent mappings, context length, or output budget are changed by this project setup.

### LLM response reliability (implemented)

- Every `/api/chat` request now supplies a JSON Schema through Ollama's `format` field.
- Responses are parsed and validated against a shared contract: `summary`, string-array `findings`, numeric `confidence` from 0 to 1, and string-array `recommended_checks`.
- Specialist prompts prohibit invented measurements, timestamps, deployment events, and unconfigured industry thresholds; findings are asked to cite exact evidence paths or say when evidence is insufficient.
- The graph preserves each raw model response for audit and conservatively checks numeric findings against topic-matched evidence. Unsupported numerical and threshold claims are retained as unverified, not facts. Natural-language validation is intentionally incomplete; model findings remain hypotheses even when their numbers match evidence.
- Markdown-fenced JSON is tolerated, but malformed, incomplete, out-of-range, or token-truncated output is reported as `invalid_response` rather than a successful analysis.
- Repetitive log evidence is passed as valid, bounded JSON that prioritizes recent explicit deployment events and errors. Invalid model output receives one same-model correction retry; both attempt statuses, validation errors, durations, and redacted/truncated raw excerpts are retained for diagnosis. Unexpected fields are rejected, and raw invalid output is never converted into facts or remediation.
- Successful calls include a parsed `analysis` object and a normalized JSON `content` string. Existing graph tracing can continue to display `content`.
- Invalid or unavailable LLM output remains advisory-only; the deterministic incident workflow continues without allowing model output to authorize or execute actions.

### Safety and current integration boundaries

LLM responses are advisory summaries only. The RCA separates source-linked observed facts from specialist hypotheses and unsupported claims; confidence is not proof. Error rates are calculated only when error and denominator counters are available. Deployment changes are correlations, not causal findings.

Telemetry collection uses the existing calculator `/health`, `/metrics`, and `/admin/version` endpoints plus `DEVOPS_LOG_PATH` (default `logs/app.log`). `/metrics` is the Prometheus-format application exporter scraped directly by the workflow and by the local Prometheus Compose service. Request counters and latency histogram observations are collected when present and valid. Host CPU and memory utilization are sampled independently using the operating system (`/proc` on Linux or Windows system APIs); these are system-level measurements, not calculator-process/container resource metrics. Missing or partial sources remain explicitly unavailable in the diagnosis. The version-history endpoint does not expose deployment status.

The calculator writes JSON logs to its local `logs/app.log`, and the workflow reads that local path. Compose does not mount this file into the host, so a workflow running outside a calculator container cannot see that container's log file unless the operator configures a shared path with `DEVOPS_LOG_PATH`. An unavailable model or Ollama service does not stop diagnosis. Code analysis receives an explicit unavailable status because Git diff retrieval is not connected. Security analysis is selected only when the request or observed logs contain security-related signals; no dedicated security event source is connected, and this does not replace SAST, dependency, or container scanning. A missing baseline or unavailable telemetry is surfaced and cannot by itself authorize a rollback.

### Docker container telemetry

The workflow collects read-only telemetry for running containers using the installed Docker CLI, which queries the Docker Engine. No Docker Python package or additional service is required. The collector records container ID/name, image and tag, running and health status, CPU, memory usage/limit/percentage, network and block I/O counters, start time/uptime, restart count, source, timestamp, and per-container errors. Host CPU/memory remains a separate `system_metrics` source. A failed container query does not discard other containers; missing fields remain `null` and collection is marked partial or unavailable rather than converted to zero.

Prerequisites: install Docker Desktop with Linux container support on Windows, start its engine, and confirm `docker info` succeeds in the same environment that runs the app or incident workflow. The optional `DEVOPS_DOCKER_CLI` environment variable can specify a non-default Docker executable. Docker commands have a five-second timeout. The `/telemetry/docker` API endpoint is GET-only and exposes no start/stop/restart/delete operations.

```powershell
docker info
uvicorn calculator_app.app:app --host 127.0.0.1 --port 8100
Invoke-RestMethod http://127.0.0.1:8100/telemetry/docker | ConvertTo-Json -Depth 8
python -m pytest -q
```

Illustrative response shape (values below are examples, not collected telemetry):

```json
{
  "status": "ok",
  "source": "Docker Engine via read-only Docker CLI",
  "timestamp": 1793577600.0,
  "containers": [{
    "id": "<engine-reported-container-id>",
    "name": "calculator",
    "image": "example/calculator:1.2",
    "image_name": "example/calculator",
    "image_tag": "1.2",
    "status": "running",
    "health_status": "healthy",
    "cpu_usage_percent": 12.5,
    "memory_usage_bytes": 134217728,
    "memory_limit_bytes": 1073741824,
    "memory_usage_percent": 12.5,
    "network_rx_bytes": 1500,
    "network_tx_bytes": 2048,
    "block_read_bytes": 3000000,
    "block_write_bytes": 4194304,
    "started_at": 1793574000.0,
    "uptime_seconds": 3600.0,
    "restart_count": 0,
    "metrics_status": "ok",
    "source": "Docker Engine via read-only Docker CLI",
    "timestamp": 1793577600.0
  }],
  "errors": [],
  "detail": null
}
```

Docker telemetry is passed to the monitoring, incident, infrastructure, and CI/CD specialists as evidence; the security specialist receives only security-related log events. The RCA records container observations as source-linked facts and keeps model statements as hypotheses subject to conservative checks for numeric claims and container IDs. Docker statistics are point-in-time CLI snapshots, not historical time series. The current Compose service does not install the Docker CLI or mount the host Engine socket, so `/telemetry/docker` from inside that container reports Docker unavailable. Run the application/agent on the host for local Docker Desktop telemetry; do not mount an unrestricted Docker socket into the application container just to enable monitoring.

### Prometheus time-series telemetry

Prometheus is an additional, read-only evidence source. The graph continues collecting the calculator's `/metrics` exposition directly, host CPU/memory, Docker Engine telemetry, logs, health, and deployment version independently. Prometheus API samples and compatible baseline deltas are included separately as `prometheus`; they do not replace those sources or independently establish a root cause or rollback signal.

The Compose stack adds the official `prom/prometheus:v3.5.0` service, a named `prometheus_data` volume, and a scrape job for `calculator-app:8100/metrics`. Port 9090 is published only on `127.0.0.1`. Start the project services with:

```powershell
docker compose up --build -d calculator-app prometheus
docker compose ps
Invoke-RestMethod http://127.0.0.1:9090/-/healthy
Invoke-RestMethod http://127.0.0.1:8100/telemetry/prometheus | ConvertTo-Json -Depth 10
```

The collector uses GET requests to the Prometheus HTTP `query_range` API. It queries a fixed five-minute range at 60-second steps, and reports each PromQL expression, unit, returned labels/values/timestamps, staleness, and per-query errors. Configure it with:

| Environment variable | Default | Description |
|---|---|---|
| `PROMETHEUS_URL` | `http://127.0.0.1:9090` | Prometheus base URL. Inside Compose, the app service uses `http://prometheus:9090`. Credentials and URL query strings are omitted from API responses. |
| `PROMETHEUS_TIMEOUT_SECONDS` | `3` | Per-query HTTP timeout; valid values are greater than 0 and at most 15 seconds. |

Implemented queries and expected units:

| Evidence field | PromQL | Unit |
|---|---|---|
| `request_rate` | `sum by (op, status) (rate(calc_requests_total[5m]))` | requests/second |
| `http_error_rate` | `100 * sum(rate(calc_requests_total{status=~"error|client_error"}[5m])) / sum(rate(calc_requests_total[5m]))` | percent |
| `latency_p95` | `histogram_quantile(0.95, sum by (le, op) (rate(calc_latency_seconds_bucket[5m])))` | seconds |
| `cpu_utilization` | `rate(process_cpu_seconds_total[5m]) * 100` | percent of one CPU |
| `memory_usage` | `process_resident_memory_bytes` | bytes |
| `host_cpu_utilization` | `100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])))` | percent |
| `host_memory_utilization` | `100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)` | percent |
| `container_cpu` | `sum by (container, image) (rate(container_cpu_usage_seconds_total[5m])) * 100` | percent of one CPU |
| `container_memory` | `container_memory_working_set_bytes` | bytes |
| `container_memory_utilization` | `100 * container_memory_working_set_bytes / (container_spec_memory_limit_bytes > 0)` | percent |

The app's `calc_*` and process metrics can be scraped from the configured app target. Host `node_*` and container `container_*` metrics are queried only as optional series: this Compose setup does not add node-exporter or cAdvisor, so they remain unavailable unless an existing scrape target provides them. Process resident memory is reported as bytes, not a utilization percentage, because this target does not expose a process memory limit. Missing or stale series remain unavailable; a successful empty query is never converted to zero. A Prometheus-only delta is recorded as an observation but cannot set the graph's regression signal or independently justify rollback.

Example response shape (placeholder values are illustrative, not telemetry):

```json
{
  "status": "partial",
  "source": "Prometheus HTTP API",
  "url": "http://127.0.0.1:9090",
  "timestamp": "<collection Unix timestamp>",
  "range_seconds": 300,
  "step_seconds": 60,
  "metrics": {
    "request_rate": {
      "status": "ok",
      "query": "sum by (op, status) (rate(calc_requests_total[5m]))",
      "unit": "requests/second",
      "observations": [{
        "labels": {"op": "add", "status": "ok"},
        "latest_value": "<Prometheus-returned value>",
        "latest_timestamp": "<Prometheus-returned Unix timestamp>",
        "stale": false,
        "values": [{"timestamp": "<Unix timestamp>", "value": "<sample>", "stale": false}]
      }]
    },
    "container_cpu": {
      "status": "unavailable",
      "query": "sum by (container, image) (rate(container_cpu_usage_seconds_total[5m])) * 100",
      "unit": "percent_of_one_cpu",
      "observations": [],
      "detail": "Prometheus query returned no observations"
    }
  },
  "errors": []
}
```

To check the API and scrape target, open `http://127.0.0.1:9090/targets` or query `/api/v1/targets`; the `calculator-app` target should report `up`. If `/telemetry/prometheus` is unavailable, confirm Prometheus is running, the app target is reachable from its container network, `PROMETHEUS_URL` is correct for where the app process runs, and the query response includes the expected metric family. When the calculator runs outside Compose, change the target in `prometheus.yml` from `calculator-app:8100` to a host-reachable address such as `host.docker.internal:8100` on Docker Desktop. When running the agent on the host, use `PROMETHEUS_URL=http://127.0.0.1:9090`.

The monitoring, incident, and infrastructure payloads can use Prometheus evidence; CI/CD receives its dedicated Prometheus evidence only when a deployment change is observed. Security receives only security-related logs and no Prometheus infrastructure metrics. Grafana below is a separate visualization layer and is not connected to the agent evidence flow.

### Grafana dashboard

The local dashboard follows **Calculator Application → Prometheus → Grafana**. Grafana is visualization-only: it is not an agent dependency, does not change specialist routing, and is not a telemetry source for the RCA.

Provisioning is committed in this structure and loaded automatically on startup:

```text
grafana/
├── provisioning/
│   ├── datasources/prometheus.yml
│   └── dashboards/dashboards.yml
└── dashboards/devops-overview.json
```

The default Prometheus datasource uses Grafana's internal Compose URL `http://prometheus:9090`. Dashboard state is persisted in the named `grafana_data` volume. Grafana is bound only to `127.0.0.1:3000`; Prometheus is likewise local-only on `127.0.0.1:9090`.

Set `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` in an untracked local `.env` file or the process environment. `.env.example` contains **development-only placeholders**, not production credentials. Do not copy those defaults into a production deployment; supply secrets through your deployment's secret-management mechanism. The setup does not overwrite an existing `.env`.

Start the services and open [http://127.0.0.1:3000](http://127.0.0.1:3000):

```powershell
docker compose up --build -d calculator-app prometheus grafana
docker compose ps
Invoke-RestMethod 'http://127.0.0.1:8100/health'
Invoke-WebRequest 'http://127.0.0.1:9090/-/healthy' -UseBasicParsing
Invoke-WebRequest 'http://127.0.0.1:3000/api/health' -UseBasicParsing
```

The provisioned **AI DevOps — System Monitoring Overview** dashboard defaults to the last 15 minutes and refreshes every 30 seconds. Application panels show request rate by operation/status, successful request rate, error rate, and p95 latency. Process panels show CPU as a percentage of one CPU (not total host CPU) and resident memory in MiB. The error-rate panel uses only observed `error`/`client_error` counters and displays No Data when the matching counter series does not exist; it does not turn an absent error counter into zero.

Optional container CPU/memory panels use cAdvisor-compatible `container_cpu_usage_seconds_total` and `container_memory_working_set_bytes`; container restart and health/status panels intentionally have no query because no compatible Prometheus series is currently configured. Optional host panels use `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`, and `node_memory_MemTotal_bytes`. No cAdvisor or Node Exporter is added here, so all these optional panels display No Data until an existing Prometheus target supplies the respective series. The separate Docker telemetry API/agent collector is not a Prometheus scrape target and does not populate these Grafana panels.

If the datasource is unavailable, check the Prometheus service and `http://127.0.0.1:9090/targets`; the `calculator-app` scrape target should be `up`. If app panels are empty, generate traffic, wait for the scrape interval, and confirm the Prometheus query has returned series. Empty error-rate results are expected until an error counter series has actually been observed. Host/container No Data is expected without compatible exporters. To stop the stack without deleting persistent volumes:

```powershell
docker compose stop grafana prometheus calculator-app
```

For offline validation, run `docker compose config --quiet` and `python -m pytest -q`.

### Run tests

```powershell
python -m pytest -q
```

The test suite checks the calculator API, direct metrics and Prometheus time-series collection, baseline comparisons, specialist routing and partial failures, approval/rejection safety, and the six-model registry/runtime behavior without requiring Ollama, Docker, or Prometheus to be running.
