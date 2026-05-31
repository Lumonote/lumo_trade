"""Daily basic (valuation/turnover) market snapshot repository."""
from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

from data_store.connection import get_conn


_FIELDS = (
    "ts_code", "trade_date",
    "close", "turnover_rate", "turnover_rate_f", "volume_ratio",
    "pe", "pe_ttm", "pb", "ps", "ps_ttm",
    "dv_ratio", "dv_ttm",
    "total_share", "float_share", "free_share",
    "total_mv", "circ_mv",
)


def upsert_df(df: pd.DataFrame) -> int:
    """Upsert rows. df must contain ts_code + trade_date; other cols default to NULL."""
    if df is None or df.empty:
        return 0
    work = df.copy()
    for col in _FIELDS:
        if col not in work.columns:
            work[col] = None
    work["trade_date"] = work["trade_date"].astype(str)
    rows: Iterable = (tuple(_to_native(getattr(r, c)) for c in _FIELDS) for r in work.itertuples(index=False))
    placeholders = ",".join("?" * len(_FIELDS))
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in _FIELDS if c not in ("ts_code", "trade_date"))
    cur = get_conn().executemany(
        f"""
        INSERT INTO daily_basic({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT(ts_code, trade_date) DO UPDATE SET {set_clause}
        """,
        list(rows),
    )
    return cur.rowcount if cur.rowcount is not None else len(work)


def get_for_date(trade_date: str) -> pd.DataFrame:
    return pd.read_sql_query(
        f"SELECT {','.join(_FIELDS)} FROM daily_basic WHERE trade_date=?",
        get_conn(),
        params=(str(trade_date),),
    )


def get_for_code(ts_code: str, limit: Optional[int] = None) -> pd.DataFrame:
    sql = f"SELECT {','.join(_FIELDS)} FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC"
    params: tuple = (ts_code,)
    if limit:
        sql += " LIMIT ?"
        params = (ts_code, int(limit))
    return pd.read_sql_query(sql, get_conn(), params=params)


def count() -> int:
    row = get_conn().execute("SELECT COUNT(*) FROM daily_basic").fetchone()
    return int(row[0]) if row else 0


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
