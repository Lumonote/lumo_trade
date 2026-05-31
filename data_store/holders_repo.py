"""Holders repository: top10 float holders + holder number.

Tables: top10_floatholders, stk_holdernumber.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from data_store.connection import get_conn


# --- top10_floatholders ---

_TOP10_FIELDS = (
    "ts_code", "end_date", "holder_rank", "holder_name",
    "hold_amount", "hold_ratio", "change_type", "change_amount",
)
_TOP10_PK = ("ts_code", "end_date", "holder_rank")


def upsert_top10(rows: List[Dict]) -> int:
    """Insert or update top10 float holder rows."""
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_TOP10_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _TOP10_FIELDS if c not in _TOP10_PK
    )
    values = [
        tuple(_to_native(r.get(c)) for c in _TOP10_FIELDS) for r in rows
    ]
    cur = get_conn().executemany(
        f"""
        INSERT INTO top10_floatholders({",".join(_TOP10_FIELDS)}) VALUES({placeholders})
        ON CONFLICT({",".join(_TOP10_PK)}) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount else len(values)


def get_top10(ts_code: str, end_date: Optional[str] = None) -> pd.DataFrame:
    """Get top10 holders for a stock, optionally filtered by end_date."""
    if end_date:
        return pd.read_sql_query(
            f"SELECT {','.join(_TOP10_FIELDS)} FROM top10_floatholders "
            "WHERE ts_code=? AND end_date=? ORDER BY holder_rank",
            get_conn(), params=(ts_code, end_date),
        )
    return pd.read_sql_query(
        f"SELECT {','.join(_TOP10_FIELDS)} FROM top10_floatholders "
        "WHERE ts_code=? ORDER BY end_date DESC, holder_rank",
        get_conn(), params=(ts_code,),
    )


def latest_top10(ts_code: str) -> pd.DataFrame:
    """Return the most recent period's top10 holders."""
    row = get_conn().execute(
        "SELECT MAX(end_date) FROM top10_floatholders WHERE ts_code=?",
        (ts_code,),
    ).fetchone()
    if not row or not row[0]:
        return pd.DataFrame(columns=list(_TOP10_FIELDS))
    return get_top10(ts_code, row[0])


# --- stk_holdernumber ---

_HN_FIELDS = ("ts_code", "end_date", "holder_num", "avg_hold", "pct_change")
_HN_PK = ("ts_code", "end_date")


def upsert_holdernumber(rows: List[Dict]) -> int:
    """Insert or update holder number rows."""
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_HN_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _HN_FIELDS if c not in _HN_PK
    )
    values = [
        tuple(_to_native(r.get(c)) for c in _HN_FIELDS) for r in rows
    ]
    cur = get_conn().executemany(
        f"""
        INSERT INTO stk_holdernumber({",".join(_HN_FIELDS)}) VALUES({placeholders})
        ON CONFLICT({",".join(_HN_PK)}) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount else len(values)


def get_holdernumber_history(ts_code: str) -> pd.DataFrame:
    """Get all holder number records for a stock ordered by date descending."""
    return pd.read_sql_query(
        f"SELECT {','.join(_HN_FIELDS)} FROM stk_holdernumber "
        "WHERE ts_code=? ORDER BY end_date DESC",
        get_conn(), params=(ts_code,),
    )


def latest_holdernumber(ts_code: str) -> Optional[Dict]:
    """Return the most recent holder number row as a dict, or None."""
    row = get_conn().execute(
        f"SELECT {','.join(_HN_FIELDS)} FROM stk_holdernumber "
        "WHERE ts_code=? ORDER BY end_date DESC LIMIT 1",
        (ts_code,),
    ).fetchone()
    if not row:
        return None
    return dict(zip(_HN_FIELDS, row))


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
