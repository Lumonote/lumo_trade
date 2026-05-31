"""SQLite connection management for kronos_data.sqlite.

Single thread-local connection per process. WAL mode + 5s busy timeout so
concurrent readers don't block on the importer.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional


_DEFAULT_REL_PATH = Path("data") / "kronos_data.sqlite"
_local = threading.local()
_schema_lock = threading.Lock()
_schema_applied: bool = False


def db_path() -> Path:
    """Resolve the kronos_data.sqlite path.

    Order:
    1. `KRONOS_SQLITE_PATH` — explicit file path override (tests, custom installs).
    2. `KRONOS_DATA_DIR/kronos_data.sqlite` — packaged app sets this to the user's
       app-data directory, so the DB lands in a writable, persistent location.
    3. Relative `data/kronos_data.sqlite` — dev mode default (cwd = project root).
    """
    explicit = os.environ.get("KRONOS_SQLITE_PATH")
    if explicit:
        return Path(explicit)
    data_dir = os.environ.get("KRONOS_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser() / "kronos_data.sqlite"
    return _DEFAULT_REL_PATH


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
