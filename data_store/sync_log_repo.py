"""Sync log repository.

Table: sync_log. PK: (source, ts_code, ran_at).
Records each data-sync invocation for observability.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, Optional

import pandas as pd

from data_store.connection import get_conn


_FIELDS = ("source", "ts_code", "ran_at", "status", "rows", "error")


def append(
    source: str,
    ts_code: str,
    ran_at: Optional[str] = None,
    status: str = "ok",
    *,
    rows: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """Append a sync log entry."""
    if ran_at is None:
        ran_at = _dt.datetime.now().isoformat(timespec="seconds")
    get_conn().execute(
        f"""
        INSERT INTO sync_log({",".join(_FIELDS)}) VALUES(?,?,?,?,?,?)
        ON CONFLICT(source, ts_code, ran_at) DO UPDATE SET
          status=excluded.status, rows=excluded.rows, error=excluded.error
        """,
        (_to_native(source), _to_native(ts_code), _to_native(ran_at),
         _to_native(status), _to_native(rows), _to_native(error)),
    )


def summary_last_24h(now_iso: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    """Return {source: {ok: N, failed: N}} for the last 24 hours.

    If now_iso is not provided, uses current time.
    """
    if now_iso is None:
        now_iso = _dt.datetime.now().isoformat(timespec="seconds")
    # Compute 24h ago
    now_dt = _dt.datetime.fromisoformat(now_iso)
    since = (now_dt - _dt.timedelta(hours=24)).isoformat(timespec="seconds")

    rows = get_conn().execute(
        "SELECT source, status, COUNT(*) as cnt FROM sync_log "
        "WHERE ran_at >= ? GROUP BY source, status",
        (since,),
    ).fetchall()

    result: Dict[str, Dict[str, int]] = {}
    for row in rows:
        src, st, cnt = row[0], row[1], row[2]
        if src not in result:
            result[src] = {}
        result[src][st] = cnt
    return result


def _to_native(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, float, str)):
        return v
    return str(v)
