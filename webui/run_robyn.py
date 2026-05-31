#!/usr/bin/env python3
"""Start the Kronos WebUI through the Robyn migration entry."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from webui.robyn_app import run_server


if __name__ == "__main__":
    run_server()
