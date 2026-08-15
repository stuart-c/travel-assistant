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

echo "=== Starting Travel Assistant Development Server on http://localhost:${PORT} ==="
python3 "$TOP_DIR/travel-assistant/app/main.py"
