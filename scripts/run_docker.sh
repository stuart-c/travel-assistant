#!/bin/bash
set -e

TOP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE_TAG="travel-assistant:local"
CONTAINER_NAME="travel-assistant-dev"
PORT="${PORT:-8099}"

if [ "$(docker images -q ${IMAGE_TAG} 2> /dev/null)" == "" ]; then
    echo "Image ${IMAGE_TAG} not found. Building..."
    bash "$TOP_DIR/scripts/make_docker.sh" "${IMAGE_TAG}"
fi

echo "Stopping any existing container..."
docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

echo "=== Starting Travel Assistant Container on http://localhost:${PORT} ==="
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p "${PORT}:8099" \
    "${IMAGE_TAG}"

echo "Container running. View logs with: docker logs -f ${CONTAINER_NAME}"
echo "Open browser: http://localhost:${PORT}"
