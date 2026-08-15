#!/bin/bash
set -e

TOP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_PATH="$TOP_DIR/.venv"

echo "=== Setting up Python Virtual Environment ==="

if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
fi

source "$VENV_PATH/bin/activate"

echo "Upgrading pip..."
pip install --upgrade pip setuptools wheel

echo "Installing production and test dependencies..."
pip install -r "$TOP_DIR/travel-assistant/app/requirements.txt" \
            -r "$TOP_DIR/travel-assistant/app/requirements_test.txt"

echo "Virtual environment ready at $VENV_PATH"
