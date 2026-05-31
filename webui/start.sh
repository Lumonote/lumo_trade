#!/bin/bash

# Kronos Web UI startup script

echo "🚀 Starting Kronos Web UI..."
echo "================================"

find_python() {
    for cmd in "${PYTHON_CMD:-}" "${PYTHON:-}" python3.13 python3.12 python3.11 python3 python; do
        if [ -z "$cmd" ]; then
            continue
        fi
        if command -v "$cmd" &> /dev/null && "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then
            echo "$cmd"
            return 0
        fi
    done
    return 1
}

PYTHON_BIN=$(find_python)
if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python 3.11+ not installed, please install Python 3.11 or later"
    exit 1
fi

# Check if in correct directory
if [ ! -f "run.py" ]; then
    echo "❌ Please run this script in the webui directory"
    exit 1
fi

# Check dependencies
echo "📦 Checking dependencies..."
DEPENDENCY_CHECK="import robyn, httpx, pandas, numpy, plotly"
if [ "${KRONOS_DISABLE_TORCH:-0}" != "1" ]; then
    DEPENDENCY_CHECK="${DEPENDENCY_CHECK}, modelscope"
fi
if ! "$PYTHON_BIN" -c "$DEPENDENCY_CHECK" &> /dev/null; then
    echo "⚠️  Missing dependencies, installing..."
    "$PYTHON_BIN" -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ Dependencies installation failed"
        exit 1
    fi
    echo "✅ Dependencies installation completed"
else
    echo "✅ All dependencies installed"
fi

# Start application
HOST="${KRONOS_HOST:-0.0.0.0}"
PORT="${KRONOS_PORT:-7070}"
echo "🌐 Starting Web server..."
echo "Access URL: http://localhost:${PORT}"
echo "Press Ctrl+C to stop server"
echo ""

"$PYTHON_BIN" run.py
