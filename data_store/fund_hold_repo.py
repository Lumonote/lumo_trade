"""Fund holding detail repository.

Table: fund_hold_detail. PK: (ts_code, end_date, fund_code).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from data_store.connection import get_conn


_FIELDS = (
    "ts_code", "end_date", "fund_code", "fund_name",
    "hold_shares", "market_value", "nv_ratio",
)

_PK = ("ts_code", "end_date", "fund_code")


def upsert_rows(rows: List[Dict]) -> int:
    """Insert or update rows. Returns number of rows affected."""
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _FIELDS if c not in _PK
    )
    values = [
        tuple(_to_native(r.get(c)) for c in _FIELDS) for r in rows
    ]
    cur = get_conn().executemany(
        f"""
        INSERT INTO fund_hold_detail({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT({",".join(_PK)}) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount else len(values)


def get_by_code(ts_code: str, end_date: Optional[str] = None) -> pd.DataFrame:
    """Get fund holdings for a stock, optionally filtered by end_date."""
    if end_date:
        return pd.read_sql_query(
            f"SELECT {','.join(_FIELDS)} FROM fund_hold_detail "
            "WHERE ts_code=? AND end_date=? ORDER BY market_value DESC",
            get_conn(), params=(ts_code, end_date),
        )
    return pd.read_sql_query(
        f"SELECT {','.join(_FIELDS)} FROM fund_hold_detail "
        "WHERE ts_code=? ORDER BY end_date DESC, market_value DESC",
        get_conn(), params=(ts_code,),
    )


def latest_period(ts_code: str) -> Optional[str]:
    """Return the most recent end_date for a stock, or None."""
    row = get_conn().execute(
        "SELECT MAX(end_date) FROM fund_hold_detail WHERE ts_code=?",
        (ts_code,),
    ).fetchone()
    return row[0] if row and row[0] else None


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
