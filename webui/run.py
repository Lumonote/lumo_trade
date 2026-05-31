#!/usr/bin/env python3
"""Kronos Web UI startup script — Robyn only."""

import os
import sys
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def check_dependencies():
    try:
        import robyn  # noqa: F401
        import httpx  # noqa: F401
        import pandas  # noqa: F401
        import numpy  # noqa: F401
        import plotly  # noqa: F401
        if os.environ.get("KRONOS_DISABLE_TORCH", "0").lower() not in {"1", "true", "yes"}:
            import modelscope  # noqa: F401
        print("✅ All dependencies installed")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        return False


def install_dependencies():
    print("Installing dependencies...")
    requirements = Path(__file__).resolve().parent / "requirements.txt"
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
        print("✅ Dependencies installation completed")
        return True
    except subprocess.CalledProcessError:
        print("❌ Dependencies installation failed")
        return False


def main():
    print("🚀 Starting Kronos Web UI (Robyn)...")
    print("=" * 50)

    if not check_dependencies():
        print("\nAuto-install dependencies? (y/n): ", end="")
        if input().lower() == "y":
            if not install_dependencies():
                return
        else:
            print("Please manually install dependencies and retry")
            return

    try:
        from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: F401
        print("✅ Kronos model library available")
    except ImportError:
        print("⚠️  Kronos model library not available, will use simulated prediction")

    try:
        from webui.robyn_app import webui_core, run_server

        _host, port, _debug = webui_core.get_server_config()
        print("✅ Robyn server starting")
        print(f"🌐 Access URL: http://localhost:{port}")
        print("💡 Tip: Press Ctrl+C to stop server")
        run_server()
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        print("Please check if the configured port is occupied")


if __name__ == "__main__":
    main()
