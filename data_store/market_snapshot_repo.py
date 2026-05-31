"""Full-market daily price (market_daily) + flow (market_flow_daily) repos."""
from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

from data_store.connection import get_conn


_DAILY_FIELDS = (
    "ts_code", "trade_date",
    "open", "high", "low", "close", "pre_close",
    "change", "pct_chg",
    "vol", "amount",
)

_FLOW_FIELDS = (
    "trade_date", "ts_code", "name", "pct_change", "close",
    "net_amount", "net_amount_rate",
    "buy_elg_amount", "buy_elg_amount_rate",
    "buy_lg_amount",  "buy_lg_amount_rate",
    "buy_md_amount",  "buy_md_amount_rate",
    "buy_sm_amount",  "buy_sm_amount_rate",
)


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


def _upsert_generic(table: str, fields: tuple, key_cols: tuple, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    work = df.copy()
    for col in fields:
        if col not in work.columns:
            work[col] = None
    for col in key_cols:
        work[col] = work[col].astype(str)
    rows: Iterable = (tuple(_to_native(getattr(r, c)) for c in fields) for r in work.itertuples(index=False))
    placeholders = ",".join("?" * len(fields))
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in fields if c not in key_cols)
    conflict_cols = ",".join(key_cols)
    cur = get_conn().executemany(
        f"""
        INSERT INTO {table}({",".join(fields)}) VALUES({placeholders})
        ON CONFLICT({conflict_cols}) DO UPDATE SET {set_clause}
        """,
        list(rows),
    )
    return cur.rowcount if cur.rowcount is not None else len(work)


def upsert_daily_df(df: pd.DataFrame) -> int:
    return _upsert_generic("market_daily", _DAILY_FIELDS, ("ts_code", "trade_date"), df)


def upsert_flow_df(df: pd.DataFrame) -> int:
    return _upsert_generic("market_flow_daily", _FLOW_FIELDS, ("trade_date", "ts_code"), df)


def get_daily(date: str) -> pd.DataFrame:
    return pd.read_sql_query(
        f"SELECT {','.join(_DAILY_FIELDS)} FROM market_daily WHERE trade_date=?",
        get_conn(),
        params=(str(date),),
    )


def get_flow(date: str) -> pd.DataFrame:
    return pd.read_sql_query(
        f"SELECT {','.join(_FLOW_FIELDS)} FROM market_flow_daily WHERE trade_date=?",
        get_conn(),
        params=(str(date),),
    )


def get_flow_by_code(ts_code: str, limit: Optional[int] = None) -> pd.DataFrame:
    """单只个股的资金流历史，按 trade_date 降序（最新在前）。供 CapitalFlowAnalyzer 复用（E5）。"""
    sql = f"SELECT {','.join(_FLOW_FIELDS)} FROM market_flow_daily WHERE ts_code=? ORDER BY trade_date DESC"
    params: tuple = (str(ts_code),)
    if limit:
        sql += " LIMIT ?"
        params = (str(ts_code), int(limit))
    return pd.read_sql_query(sql, get_conn(), params=params)


def daily_count() -> int:
    row = get_conn().execute("SELECT COUNT(*) FROM market_daily").fetchone()
    return int(row[0]) if row else 0


def flow_count() -> int:
    row = get_conn().execute("SELECT COUNT(*) FROM market_flow_daily").fetchone()
    return int(row[0]) if row else 0
