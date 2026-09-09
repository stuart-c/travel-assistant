#!/usr/bin/with-contenv bashio

export LOG_LEVEL=$(bashio::config 'log_level')
bashio::log.info "Starting Travel Assistant with log level: ${LOG_LEVEL}"

# Set Ingress port
export PORT=8099

MCP_PID=""
if bashio::config.true 'enable_mcp'; then
    MCP_PORT=$(bashio::config 'mcp_port')
    MCP_TOKEN=$(bashio::config 'mcp_api_token')
    bashio::log.info "Starting optional MCP service on port ${MCP_PORT:-8098}..."
    python3 -m app.mcp --port "${MCP_PORT:-8098}" --token "${MCP_TOKEN:-}" --log-level "${LOG_LEVEL:-info}" &
    MCP_PID=$!
fi

shutdown() {
    bashio::log.info "Stopping Travel Assistant services..."
    if [ -n "${MCP_PID}" ]; then
        kill -TERM "${MCP_PID}" 2>/dev/null || true
    fi
    if [ -n "${GUNICORN_PID}" ]; then
        kill -TERM "${GUNICORN_PID}" 2>/dev/null || true
    fi
    exit 0
}

trap shutdown SIGTERM SIGINT

# Run Gunicorn WSGI server
gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level "${LOG_LEVEL:-info}" \
    --logger-class "app.main.GunicornLogger" \
    "app.main:app" &
GUNICORN_PID=$!

wait "${GUNICORN_PID}"
