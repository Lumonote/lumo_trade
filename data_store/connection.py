"""SQLite connection management for lumo_data.sqlite.

Single thread-local connection per process. WAL mode + 5s busy timeout so
concurrent readers don't block on the importer.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Optional


_DEFAULT_REL_PATH = Path("data") / "lumo_data.sqlite"
# 旧版库名：首次启动时若检测到，自动拷贝一份为 lumo_data.sqlite，实现平滑迁移。
_LEGACY_DB_NAME = "kronos_data.sqlite"
_local = threading.local()
_schema_lock = threading.Lock()
_schema_applied: bool = False


def _migrate_legacy_db(target: Path) -> None:
    """If the target DB doesn't exist but a legacy kronos_data.sqlite does,
    copy it to the new lumo_data.sqlite name (the legacy file is left intact so
    any older entry point that still references it keeps working)."""
    if target.exists():
        return
    legacy = target.parent / _LEGACY_DB_NAME
    if not legacy.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
        print(f"[migrate] copied {_LEGACY_DB_NAME} -> {target.name}", flush=True)
    except OSError as exc:
        print(f"[migrate] failed to copy {_LEGACY_DB_NAME}: {exc}", flush=True)


def db_path() -> Path:
    """Resolve the lumo_data.sqlite path.

    Order:
    1. `KRONOS_SQLITE_PATH` — explicit file path override (tests, custom installs).
    2. `KRONOS_DATA_DIR/lumo_data.sqlite` — packaged app sets this to the user's
       app-data directory, so the DB lands in a writable, persistent location.
    3. Relative `data/lumo_data.sqlite` — dev mode default (cwd = project root).

    On first resolution, if the target does not exist but a legacy
    `kronos_data.sqlite` does, it is copied across so existing users keep their
    data after the rename.
    """
    explicit = os.environ.get("KRONOS_SQLITE_PATH")
    if explicit:
        return Path(explicit)
    data_dir = os.environ.get("KRONOS_DATA_DIR")
    if data_dir:
        target = Path(data_dir).expanduser() / "lumo_data.sqlite"
    else:
        target = _DEFAULT_REL_PATH
    _migrate_legacy_db(target)
    return target


def get_conn() -> sqlite3.Connection:
    """Return the calling thread's connection, opening + migrating on first call."""
    conn: Optional[sqlite3.Connection] = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    _local.conn = conn

    # Lazy one-shot schema migration. Re-entrant safe.
    global _schema_applied
    if not _schema_applied:
        with _schema_lock:
            if not _schema_applied:
                from data_store.schema import migrate
                migrate(conn)
                _schema_applied = True
    return conn


def close_conn() -> None:
    conn: Optional[sqlite3.Connection] = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def reset_for_testing() -> None:
    """Drop the cached connection and schema flag. Tests only."""
    global _schema_applied
    close_conn()
    _schema_applied = False
