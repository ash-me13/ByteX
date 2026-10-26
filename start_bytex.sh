#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "============================================================"
echo "  ByteX AI Launcher (macOS / Linux)"
echo "============================================================"

# Prefer .venv Python if available
if [ -f "$DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "Error: Python 3 not found."
    exit 1
fi

echo "Using Python: $PYTHON_BIN"
exec "$PYTHON_BIN" "$DIR/start_bytex.py" "$@"
