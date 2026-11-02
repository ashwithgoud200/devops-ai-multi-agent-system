#!/usr/bin/env bash
# Deploy a new image on one Docker host; unhealthy deployments require manual recovery.
set -Eeuo pipefail

: "${APP_IMAGE:?APP_IMAGE must be set}"
CONTAINER_NAME="${CONTAINER_NAME:-devops-calculator}"
HOST_PORT="${HOST_PORT:-8100}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${HOST_PORT}/health}"

echo "Pulling ${APP_IMAGE}"
docker pull "$APP_IMAGE"
if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  docker rm -f "$CONTAINER_NAME"
fi

echo "Starting ${CONTAINER_NAME}"
docker run -d --name "$CONTAINER_NAME" --restart unless-stopped \
  -p "${HOST_PORT}:8100" "$APP_IMAGE" >/dev/null

for attempt in $(seq 1 24); do
  if curl --fail --silent "$HEALTH_URL" >/dev/null; then
    echo "Deployment healthy: ${APP_IMAGE}"
    exit 0
  fi
  sleep 5
done

echo "New deployment failed health checks; no automatic rollback was performed." >&2
echo "Inspect the failed container and manually deploy a known-good image if needed." >&2
exit 1
