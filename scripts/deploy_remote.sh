#!/usr/bin/env bash
# Deploy a new image on a single Docker host and restore the previous image if health fails.
set -Eeuo pipefail

: "${APP_IMAGE:?APP_IMAGE must be set}"
CONTAINER_NAME="${CONTAINER_NAME:-devops-calculator}"
HOST_PORT="${HOST_PORT:-8100}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${HOST_PORT}/health}"
PREVIOUS_IMAGE=""

if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  PREVIOUS_IMAGE="$(docker inspect --format='{{.Config.Image}}' "$CONTAINER_NAME")"
fi

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

echo "New deployment failed health checks" >&2
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
if [ -n "$PREVIOUS_IMAGE" ]; then
  echo "Restoring previous image: ${PREVIOUS_IMAGE}" >&2
  docker run -d --name "$CONTAINER_NAME" --restart unless-stopped \
    -p "${HOST_PORT}:8100" "$PREVIOUS_IMAGE" >/dev/null
else
  echo "No previous image was available to restore" >&2
fi
exit 1
