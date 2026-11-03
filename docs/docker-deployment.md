# Local Docker Compose Deployment & Operations Guide

## 1. Overview & Architecture

The local observability and multi-agent application stack runs via Docker Compose (`docker-compose.yml`) and consists of four services bound strictly to `127.0.0.1` (loopback):

| Service | Container Name | Image | Loopback Port | Health Check Endpoint | Named Volumes |
|---|---|---|---|---|---|
| `calculator-app` | `devops-calculator` | `devops-agents-calculator:local` (or `${APP_IMAGE}`) | `127.0.0.1:8100->8100/tcp` | `http://127.0.0.1:8100/health` | `app_data` (`/app/data`), `app_logs` (`/app/logs`) |
| `prometheus` | `devops-prometheus` | `prom/prometheus:v3.5.0` | `127.0.0.1:9090->9090/tcp` | `http://127.0.0.1:9090/-/healthy` | `prometheus_data` (`/prometheus`) |
| `grafana` | `devops-agents-grafana-1` | `grafana/grafana:11.6.1` | `127.0.0.1:3000->3000/tcp` | `http://127.0.0.1:3000/api/health` | `grafana_data` (`/var/lib/grafana`) |
| `frontend` | `devops-frontend` | `devops-agents-frontend:local` (or `${FRONTEND_IMAGE}`) | `127.0.0.1:4173->4173/tcp` | `http://127.0.0.1:4173/` | *(stateless Nginx static + reverse proxy)* |

### Safety & Security Guarantees
- **Loopback-Only Binding:** All published ports explicitly bind to `127.0.0.1`. No service is exposed to external networks.
- **Non-Root Application Container:** `Dockerfile` runs the FastAPI application as the unprivileged `app` system user.
- **Volume Preservation:** Baseline snapshots (`app_data`), audit/application logs (`app_logs`), Prometheus TSDB blocks (`prometheus_data`), and Grafana state (`grafana_data`) are stored in named Docker volumes. Never run `docker compose down -v`.
- **Optional Local LLM Inference:** `DEVOPS_LLM_ENABLED` defaults to `false`. Container readiness, CI checks, and deterministic diagnosis work when Ollama is offline or unavailable.

---

## 2. Automated Local Deployment Script

Use `scripts/deploy_local.ps1` (Windows PowerShell) or `scripts/deploy_local.sh` (Linux/macOS/Git Bash) to validate, build/pull, start the Compose stack, and verify all health and telemetry endpoints without deleting volumes:

```powershell
# Build local image, start Compose stack, and verify all endpoints:
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_local.ps1

# Or start/verify using existing built image (skip rebuild):
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_local.ps1 -SkipBuild

# Or pull a published GHCR image and deploy locally:
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_local.ps1 -AppImage "ghcr.io/ashwithgoud200/devops-ai-multi-agent-system:latest" -Pull
```

---

## 3. Manual Startup, Shutdown, and Restart Commands

### Start the Stack
```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

### Restart Services Safely (Preserving Volumes)
```powershell
docker compose restart calculator-app prometheus grafana
docker compose ps
```

### Stop the Stack Safely (Preserving Volumes and Containers)
```powershell
docker compose stop
```

### Recreate Containers Safely (Preserving Named Volumes)
```powershell
docker compose down
docker compose up -d
```
*(Never pass `-v` or `--volumes` to `docker compose down`, so `app_data`, `app_logs`, `prometheus_data`, and `grafana_data` remain intact.)*

---

## 4. Health-Check & Verification Commands

### Backend Application Endpoints
```powershell
# 1. Application readiness & version
Invoke-RestMethod http://127.0.0.1:8100/health

# 2. Six specialist agent mappings & enabled status
Invoke-RestMethod http://127.0.0.1:8100/agents | ConvertTo-Json -Depth 5

# 3. Prometheus exposition metrics
(Invoke-WebRequest http://127.0.0.1:8100/metrics -UseBasicParsing).Content

# 4. Deployment version history
Invoke-RestMethod http://127.0.0.1:8100/admin/version | ConvertTo-Json -Depth 5
```

### Prometheus Verification
```powershell
# Verify Prometheus server health
Invoke-WebRequest http://127.0.0.1:9090/-/healthy -UseBasicParsing

# Verify Prometheus scrape target (up == 1)
Invoke-RestMethod 'http://127.0.0.1:9090/api/v1/query?query=up{job="calculator-app"}' | ConvertTo-Json -Depth 6
```

### Grafana Verification
```powershell
# Verify Grafana server & database health
Invoke-RestMethod http://127.0.0.1:3000/api/health

# Verify Grafana can query Prometheus via its provisioned datasource (uid: prometheus)
$pair = "admin:local-dev-change-me"
$bytes = [System.Text.Encoding]::ASCII.GetBytes($pair)
$base64 = [System.Convert]::ToBase64String($bytes)
Invoke-RestMethod -Uri 'http://127.0.0.1:3000/api/datasources/proxy/uid/prometheus/api/v1/query?query=up{job="calculator-app"}' `
  -Headers @{ Authorization = "Basic $base64" } | ConvertTo-Json -Depth 6
```

---

## 5. Optional Self-Hosted Runner Setup for Local Deployment

Because GitHub-hosted runners execute in isolated cloud VMs and cannot directly access a personal Windows Docker Desktop daemon (and exposing the Docker daemon TCP port publicly is insecure), local deployment from GitHub Actions (`docker-deploy.yml`) supports two safe modes:
1. **Isolated CI Validation on GitHub-Hosted Runner:** Runs `scripts/deploy_local.sh` inside the runner's isolated Docker environment to verify image startup, `/health`, `/agents`, `/metrics`, and Prometheus scraping (`up == 1`).
2. **Optional Self-Hosted Runner on the Local Machine:**
   - In GitHub repository **Settings → Actions → Runners**, click **New self-hosted runner** and configure it on the local host with Docker Desktop running.
   - Restrict the runner to private/trusted branches (`main` / `v*` tags only, never public fork PRs).
   - Trigger `.github/workflows/docker-deploy.yml` via `workflow_dispatch`.

---

## 6. Troubleshooting

- **`calculator-app` healthcheck reports `starting` or `unhealthy`:**
  Run `docker compose logs calculator-app --tail 50` to inspect Uvicorn startup errors or port conflicts on `127.0.0.1:8100`.
- **Prometheus target `calculator-app` shows `down` (`up == 0`):**
  Verify both `devops-calculator` and `devops-prometheus` are on the same Compose network (`docker network inspect devops-agents_default`) and that `http://127.0.0.1:8100/metrics` responds with HTTP 200.
- **Grafana login fails:**
  Check `.env` or environment variables `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` (default development placeholders: `admin` / `local-dev-change-me`).
- **Ollama is offline or unreachable:**
  With `DEVOPS_LLM_ENABLED=false` (the default), the application and incident workflow run deterministically without contacting Ollama. If `DEVOPS_LLM_ENABLED=true` is set while Ollama is stopped, each selected specialist reports `status: "unavailable"` cleanly without crashing the incident diagnosis or bypassing human approval.
