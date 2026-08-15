#!/bin/bash
set -e

TOP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE_TAG="${1:-travel-assistant:local}"

echo "=== Building Local Docker Image: ${IMAGE_TAG} ==="
docker build \
    --build-arg BUILD_FROM="ghcr.io/home-assistant/amd64-base-debian:bookworm" \
    -t "${IMAGE_TAG}" \
    -f "$TOP_DIR/travel-assistant/Dockerfile" \
    "$TOP_DIR/travel-assistant"

echo "Docker build completed successfully: ${IMAGE_TAG}"
