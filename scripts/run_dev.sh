#!/bin/bash
set -e

TOP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_PATH="$TOP_DIR/.venv"

if [ ! -d "$VENV_PATH" ]; then
    echo "--- Virtual environment not found. Initialising... ---"
    bash "$TOP_DIR/scripts/make_venv.sh"
fi

source "$VENV_PATH/bin/activate"

PORT="${PORT:-8099}"
export FLASK_DEBUG=true
export PYTHONPATH="$TOP_DIR/travel-assistant"

for arg in "$@"; do
    if [ "$arg" == "--sample-db" ] || [ "$arg" == "-s" ]; then
        export USE_SAMPLE_DB=1
    fi
done

if [ "${USE_SAMPLE_DB:-0}" == "1" ]; then
    SAMPLE_DB="$TOP_DIR/instance/sample_travel_assistant.db"
    if [ ! -f "$SAMPLE_DB" ]; then
        echo "--- Sample database not found. Generating... ---"
        bash "$TOP_DIR/scripts/seed_sample_db.sh" "$SAMPLE_DB"
    fi
    export DATABASE_PATH="$SAMPLE_DB"
    echo "=== Running against Sample Database: $SAMPLE_DB ==="
fi

echo "=== Starting Travel Assistant Development Server on http://localhost:${PORT} ==="
python3 "$TOP_DIR/travel-assistant/app/main.py"
