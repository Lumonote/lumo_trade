"""HSGT (沪深港通) individual stock holding repository.

Table: hsgt_individual. PK: (ts_code, trade_date).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from data_store.connection import get_conn


_FIELDS = (
    "ts_code", "trade_date", "hold_vol", "hold_ratio", "market_cap",
)

_PK = ("ts_code", "trade_date")


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
        INSERT INTO hsgt_individual({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT({",".join(_PK)}) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount else len(values)


def get_by_code(ts_code: str) -> pd.DataFrame:
    """Get all HSGT rows for a stock ordered by date descending."""
    return pd.read_sql_query(
        f"SELECT {','.join(_FIELDS)} FROM hsgt_individual "
        "WHERE ts_code=? ORDER BY trade_date DESC",
        get_conn(), params=(ts_code,),
    )


def latest(ts_code: str) -> Optional[Dict]:
    """Return the most recent row as a dict, or None."""
    row = get_conn().execute(
        f"SELECT {','.join(_FIELDS)} FROM hsgt_individual "
        "WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
        (ts_code,),
    ).fetchone()
    if not row:
        return None
    return dict(zip(_FIELDS, row))


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
