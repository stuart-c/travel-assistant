#!/bin/bash
set -e

TOP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_PATH="$TOP_DIR/.venv"

if [ ! -d "$VENV_PATH" ]; then
    echo "--- Virtual environment not found. Initialising... ---"
    bash "$TOP_DIR/scripts/make_venv.sh"
fi

source "$VENV_PATH/bin/activate"

export PYTHONPATH="$TOP_DIR/travel-assistant"

echo "=== Running Automated UI & Route Verification Suite ==="
python3 "$TOP_DIR/scripts/run_ui_tests.py" "$@"
