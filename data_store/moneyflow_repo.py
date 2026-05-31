"""Moneyflow ranking (top-N) repository.

Mirrors `data/moneyflow_dc_YYYYMMDD_topN.csv`. Each row keyed by
(trade_date, ts_code, top_n).
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from data_store.connection import get_conn


_FIELDS = (
    "trade_date", "ts_code", "top_n",
    "name", "pct_change", "close",
    "net_amount", "net_amount_rate",
    "buy_elg_amount", "buy_elg_amount_rate",
    "buy_lg_amount",  "buy_lg_amount_rate",
    "buy_md_amount",  "buy_md_amount_rate",
    "buy_sm_amount",  "buy_sm_amount_rate",
    "amount_unit",
)


def upsert_df(df: pd.DataFrame, top_n: int) -> int:
    if df is None or df.empty:
        return 0
    work = df.copy()
    work["top_n"] = int(top_n)
    if "_amount_unit" in work.columns and "amount_unit" not in work.columns:
        work["amount_unit"] = work["_amount_unit"]
    work["trade_date"] = work["trade_date"].astype(str)
    work["ts_code"] = work["ts_code"].astype(str)
    for col in _FIELDS:
        if col not in work.columns:
            work[col] = None
    rows: Iterable = (tuple(_to_native(getattr(r, c)) for c in _FIELDS) for r in work.itertuples(index=False))
    placeholders = ",".join("?" * len(_FIELDS))
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in _FIELDS if c not in ("trade_date", "ts_code", "top_n"))
    cur = get_conn().executemany(
        f"""
        INSERT INTO moneyflow_dc({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT(trade_date, ts_code, top_n) DO UPDATE SET {set_clause}
        """,
        list(rows),
    )
    return cur.rowcount if cur.rowcount is not None else len(work)


def get_top_n(trade_date: str, top_n: int) -> pd.DataFrame:
    return pd.read_sql_query(
        f"SELECT {','.join(_FIELDS)} FROM moneyflow_dc WHERE trade_date=? AND top_n=?",
        get_conn(),
        params=(str(trade_date), int(top_n)),
    )


def latest_date(top_n: int = None):
    if top_n is None:
        row = get_conn().execute("SELECT MAX(trade_date) FROM moneyflow_dc").fetchone()
    else:
        row = get_conn().execute(
            "SELECT MAX(trade_date) FROM moneyflow_dc WHERE top_n=?", (int(top_n),)
        ).fetchone()
    return row[0] if row and row[0] else None


def count() -> int:
    row = get_conn().execute("SELECT COUNT(*) FROM moneyflow_dc").fetchone()
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
