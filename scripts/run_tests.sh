#!/bin/bash
set -e

TOP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_PATH="$TOP_DIR/.venv"

if [ ! -d "$VENV_PATH" ]; then
    echo "--- Virtual environment not found. Initialising... ---"
    bash "$TOP_DIR/scripts/make_venv.sh"
fi

source "$VENV_PATH/bin/activate"

echo "=== Running Code Formatting Check (black) ==="
black --check "$TOP_DIR/travel-assistant/app"

echo "=== Running Linter (flake8) ==="
flake8 "$TOP_DIR/travel-assistant/app" --max-line-length=100 --extend-ignore=E203,W503

echo "=== Running Unit Tests & Coverage (pytest) ==="
if [ $# -gt 0 ]; then
    PYTHONPATH="$TOP_DIR/travel-assistant" pytest "$@"
else
    PYTHONPATH="$TOP_DIR/travel-assistant" pytest \
        "$TOP_DIR/travel-assistant/app/tests" \
        --cov="$TOP_DIR/travel-assistant/app" \
        --cov-report=term-missing \
        --cov-report=html:"$TOP_DIR/htmlcov" \
        --cov-report=xml:"$TOP_DIR/coverage.xml"
fi

echo "=== All Tests and Lints Passed Successfully ==="
