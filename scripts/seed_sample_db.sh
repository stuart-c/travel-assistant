#!/bin/bash
set -e

TOP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_PATH="$TOP_DIR/.venv"

if [ ! -d "$VENV_PATH" ]; then
    echo "--- Virtual environment not found. Initialising... ---"
    bash "$TOP_DIR/scripts/make_venv.sh"
fi

source "$VENV_PATH/bin/activate"

OUTPUT_PATH="${1:-$TOP_DIR/instance/sample_travel_assistant.db}"
export PYTHONPATH="$TOP_DIR/travel-assistant"

python3 "$TOP_DIR/scripts/seed_sample_db.py" --output "$OUTPUT_PATH"
