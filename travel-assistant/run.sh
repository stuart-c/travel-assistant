#!/usr/bin/with-contenv bashio

export LOG_LEVEL=$(bashio::config 'log_level')
bashio::log.info "Starting Travel Assistant with log level: ${LOG_LEVEL}"

# Set Ingress port
export PORT=8099

# Run with Gunicorn WSGI server
exec gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level "${LOG_LEVEL:-info}" \
    --logger-class "app.main.GunicornLogger" \
    "app.main:app"
