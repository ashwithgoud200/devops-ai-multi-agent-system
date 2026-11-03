#!/usr/bin/env bash
# Safe local Docker Compose deployment and health verification script.
# Preserves all existing Docker volumes and data; never performs automatic rollback or destructive actions.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

export DEVOPS_LLM_ENABLED="${DEVOPS_LLM_ENABLED:-false}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-90}"

echo "==> [1/7] Validating Docker Compose configuration..."
docker compose config --quiet

if [[ "${PULL_IMAGE:-false}" == "true" && -n "${APP_IMAGE:-}" ]]; then
  echo "==> [2/7] Pulling published image ${APP_IMAGE}..."
  docker pull "${APP_IMAGE}"
  if [[ "${SKIP_BUILD:-false}" != "true" ]]; then
    docker compose build frontend
  fi
elif [[ "${SKIP_BUILD:-false}" != "true" ]]; then
  echo "==> [2/7] Building local application and frontend Docker images..."
  docker compose build calculator-app frontend
else
  echo "==> [2/7] Skipping image build/pull as requested."
fi

echo "==> [3/7] Starting Docker Compose stack (preserving named volumes)..."
docker compose up -d

echo "==> [4/7] Verifying backend /health and /admin/version..."
for ((i=1; i<=TIMEOUT_SECONDS/2; i++)); do
  if curl --fail --silent "http://127.0.0.1:8100/health" | grep -q '"status":"ok"'; then
    echo "    /health OK"
    break
  fi
  if (( i == TIMEOUT_SECONDS/2 )); then
    echo "ERROR: Application /health did not become ready within ${TIMEOUT_SECONDS}s." >&2
    exit 1
  fi
  sleep 2
done

curl --fail --silent "http://127.0.0.1:8100/admin/version" | grep -q '"version"'
echo "    /admin/version OK"

echo "==> [5/7] Verifying /agents (six specialist model assignments)..."
curl --fail --silent "http://127.0.0.1:8100/agents" | grep -q '"qwen2.5:3b"'
curl --fail --silent "http://127.0.0.1:8100/agents" | grep -q '"granite3.1-dense:2b"'
echo "    /agents OK"

echo "==> [6/7] Verifying /metrics and Prometheus scrape target (up == 1)..."
curl --fail --silent "http://127.0.0.1:8100/metrics" | grep -q 'calc_requests_total'
curl --fail --silent "http://127.0.0.1:9090/-/healthy" >/dev/null

SCRAPE_OK="false"
LAST_UP_RESPONSE=""
for ((attempt=1; attempt<=15; attempt++)); do
  LAST_UP_RESPONSE="$(curl --fail --silent 'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob=%22calculator-app%22%7D' || true)"
  if echo "${LAST_UP_RESPONSE}" | grep -Eq '"value":\[[^]]*,"1"\]'; then
    SCRAPE_OK="true"
    break
  fi
  sleep 2
done

if [[ "${SCRAPE_OK}" != "true" ]]; then
  echo "ERROR: Prometheus scrape validation failed for up{job=\"calculator-app\"}: expected value \"1\", got: ${LAST_UP_RESPONSE:-empty response}" >&2
  exit 1
fi
echo "    /metrics and Prometheus scrape (up == 1) OK"

echo "==> [7/7] Verifying Grafana and Frontend (127.0.0.1:4173) readiness..."
curl --fail --silent "http://127.0.0.1:3000/api/health" | grep -q '"ok"'
echo "    Grafana /api/health OK"

curl --fail --silent "http://127.0.0.1:4173/" | grep -q 'OpsPilot'
curl --fail --silent "http://127.0.0.1:4173/api/health" | grep -q '"status":"ok"'
echo "    Frontend http://127.0.0.1:4173/ and /api/health proxy OK"

docker compose ps
echo "Local deployment and health validation completed successfully."
