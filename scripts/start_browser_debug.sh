#!/bin/bash
# scripts/start_browser_debug.sh
# Initialises a headless Chromium / Google Chrome process with remote debugging enabled
# for Google Antigravity /browser agent sessions.

set -e

DEBUG_PORT="${1:-9222}"
USER_DATA_DIR="$HOME/.config/google-chrome"
mkdir -p "$USER_DATA_DIR"

echo "=== Initialising Browser Remote Debugging on Port ${DEBUG_PORT} ==="

# Check if browser is already listening on the target port
if curl -s "http://127.0.0.1:${DEBUG_PORT}/json/version" > /dev/null 2>&1; then
    echo "Active Chrome/Chromium remote debugging instance already responding on port ${DEBUG_PORT}."
    exit 0
fi

# Locate browser binary
BROWSER_BIN=""
for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
    if command -v "$candidate" >/dev/null 2>&1; then
        BROWSER_BIN=$(command -v "$candidate")
        break
    fi
done

if [ -z "$BROWSER_BIN" ]; then
    echo "ERROR: Neither Chromium nor Google Chrome was found on PATH." >&2
    exit 1
fi

echo "Starting browser (${BROWSER_BIN}) in background..."
nohup "$BROWSER_BIN" \
    --headless=new \
    --no-sandbox \
    --disable-gpu \
    --disable-dev-shm-usage \
    --remote-debugging-port="${DEBUG_PORT}" \
    --user-data-dir="$USER_DATA_DIR" > /dev/null 2>&1 &

# Wait for DevToolsActivePort to be created
for i in {1..15}; do
    if [ -f "$USER_DATA_DIR/DevToolsActivePort" ]; then
        echo "DevToolsActivePort detected."
        break
    fi
    # Also check if written under chromium config
    if [ -f "$HOME/.config/chromium/DevToolsActivePort" ]; then
        ln -sf "$HOME/.config/chromium/DevToolsActivePort" "$USER_DATA_DIR/DevToolsActivePort"
        echo "Linked Chromium DevToolsActivePort."
        break
    fi
    sleep 0.5
done

# Verify DevTools HTTP endpoint
if curl -s "http://127.0.0.1:${DEBUG_PORT}/json/version" > /dev/null 2>&1; then
    echo "=== Browser Remote Debugging Ready on ws://127.0.0.1:${DEBUG_PORT} ==="
    echo "DevTools profile: ${USER_DATA_DIR}"
else
    echo "WARNING: Browser process launched, but HTTP endpoint is not yet responding on port ${DEBUG_PORT}."
fi
