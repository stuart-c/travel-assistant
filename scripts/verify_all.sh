#!/bin/bash
set -e

TOP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

echo "================================================"
echo "    Travel Assistant - Full Verification Suite    "
echo "================================================"

echo ""
echo "[1/3] Running Unit Tests & Linters..."
bash "$TOP_DIR/scripts/run_tests.sh"

echo ""
echo "[2/3] Running Automated UI & Route Verification..."
bash "$TOP_DIR/scripts/run_ui_tests.sh"

echo ""
echo "[3/3] Validating Add-on Docker Packaging..."
if command -v docker &> /dev/null; then
    bash "$TOP_DIR/scripts/make_docker.sh" "travel-assistant:verify"
    docker rmi "travel-assistant:verify" >/dev/null 2>&1 || true
    echo "Docker package verification succeeded."
else
    echo "Docker not available in environment; skipping container build step."
fi

echo ""
echo "================================================"
echo "      All Pre-Push Verifications PASSED!        "
echo "================================================"

