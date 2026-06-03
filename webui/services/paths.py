"""Path helpers for source and packaged WebUI runtimes."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    configured = os.environ.get("KRONOS_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2]


def user_root(app_name: str = "com.kronos.app") -> Path:
    configured = os.environ.get("KRONOS_USER_DIR")
    if configured:
        root = Path(configured).expanduser()
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / app_name
    elif os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / app_name
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / app_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def results_dir() -> Path:
    """Single source of truth for the opportunity/report output directory.

    Honors KRONOS_RESULTS_DIR when set (packaging / power users), otherwise
    falls back to ``user_root()/results``. Both the WebUI reader
    (``webui/core.py``) and the CLI writer (``scripts/run_opportunity_discovery.py``)
    resolve through here so desktop / dev / command-line read & write the same place.
    """
    configured = os.environ.get("KRONOS_RESULTS_DIR")
    if configured:
        return Path(configured).expanduser()
    return user_root() / "results"


def ensure_user_subdirs(root: Path) -> None:
    for name in ("data", "logs", "models", "results", "reports", "integrated_results", "config"):
        (root / name).mkdir(parents=True, exist_ok=True)
