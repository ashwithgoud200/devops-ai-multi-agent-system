# SRE-104: Container Infrastructure Pressure & Resource Saturation

## Metadata
- **ID:** SRE-104
- **Severity:** Critical
- **Target Service:** `docker-compose` / `calculator-app`
- **Category:** Infrastructure Failure

## Symptoms
- Container healthchecks failing or showing `unhealthy` status in Docker Compose.
- `/health` endpoint returning `{"status": "degraded"}` or connection timeout.
- Docker telemetry indicates elevated memory consumption approaching container cgroup limits.
- Downstream services (Prometheus, Loki, Tempo) reporting connection refusal.

## Diagnostic Steps
1. Fetch compose topology via `GET /topology/compose` to identify degraded containers.
2. Review Docker container exit codes and restart counts (`docker ps -a`).
3. Check host memory and disk headroom to ensure `/logs` volume is not filling disk.
4. Verify port bindings remain strictly on loopback `127.0.0.1`.

## Remediation Protocol
1. **Container Recycling:**
   - Execute targeted service restart: `docker compose restart calculator-app`.
   - Never run `docker compose down -v` to prevent volume data destruction.
2. **Health Gate:**
   - Confirm all 6 services (`calculator-app`, `prometheus`, `grafana`, `frontend`, `loki`, `tempo`) return `healthy`.

