#!/usr/bin/env bash
#
# Scheduled backtest-loop wrapper.
#
# Why this exists: the feedback loop silently died in production because the
# scheduler invoked Python without the project venv (system python3 lacks
# pandas/akshare/etc.), and because the macOS system HTTP proxy (a local Clash
# port) intercepts requests and dies when it's down. This wrapper pins both:
#   - runs under .venv/bin/python (the only interpreter with deps installed)
#   - exports no_proxy=* so the Eastmoney daily fetch connects directly
#     (see data_store/ohlcv_fetch.py; the data hosts are reachable without proxy)
#
# Usage (from anywhere):
#   scripts/run_backtest.sh                 # incremental update + report
#   scripts/run_backtest.sh --optimize      # + auto-tune scoring config (guarded)
#   scripts/run_backtest.sh --recompute-all # full recompute (backs up first)
#
# Cron example (daily 18:30, after market close + discovery):
#   30 18 * * 1-5  /path/to/kronos_ultra/scripts/run_backtest.sh --optimize >> \
#                  /path/to/kronos_ultra/results/backtest/cron.log 2>&1
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Direct connection for the A-share data hosts; do not route through the
# (often-down) local system proxy. Harmless if no proxy is configured.
export no_proxy="*"
export NO_PROXY="*"

PY="$PROJECT_ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "ERROR: project venv not found at $PY" >&2
    echo "       create it first (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)" >&2
    exit 1
fi

echo "[run_backtest] $($PY --version) @ $PY  args: $*"
exec "$PY" scripts/auto_backtest.py "$@"
