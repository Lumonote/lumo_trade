"""Moneyflow ranking (top-N) repository.

Mirrors `data/moneyflow_dc_YYYYMMDD_topN.csv`. Each row keyed by
(trade_date, ts_code, top_n).
"""
from __future__ import annotations

import json
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
    "amount_unit", "raw_json",
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
    work["raw_json"] = work.apply(_row_raw_json, axis=1)
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


def get_ranking(trade_date: str, limit: int = 50, snapshot_top_n: int = 0) -> pd.DataFrame:
    """资金榜单日:在 snapshot_top_n 快照内按主力净流入降序取前 limit。

    snapshot_top_n=0 约定为「资金榜全市场快照」,与 opportunity discovery 写入的
    正 top_n 快照互不干扰。"""
    return pd.read_sql_query(
        f"""
        SELECT {','.join(_FIELDS)} FROM moneyflow_dc
        WHERE trade_date=? AND top_n=?
        ORDER BY net_amount DESC
        LIMIT ?
        """,
        get_conn(),
        params=(str(trade_date), int(snapshot_top_n), int(limit)),
    )


def get_aggregated(
    end_date: str,
    days: int = 5,
    limit: int = 50,
    snapshot_top_n: int = 0,
    sort_by: str = "net_amount",
) -> pd.DataFrame:
    """资金榜多日聚合:end_date 及之前最近 days 个有数据交易日,按累计主力净流入
    降序取前 limit;list_count = 窗口内上榜天数(去重日期)。"""
    order_expr = (
        "main_buy_amount DESC, net_amount DESC"
        if sort_by in {"buy_amount", "main_buy_amount"}
        else "net_amount DESC"
    )
    return pd.read_sql_query(
        """
        WITH recent_dates AS (
            SELECT DISTINCT trade_date FROM moneyflow_dc
            WHERE trade_date <= ? AND top_n = ?
            ORDER BY trade_date DESC
            LIMIT ?
        )
        SELECT ts_code,
               MAX(name)              AS name,
               MAX(close)             AS close,
               MAX(pct_change)        AS pct_change,
               SUM(net_amount)        AS net_amount,
               AVG(net_amount_rate)   AS net_amount_rate,
               SUM(buy_elg_amount)    AS buy_elg_amount,
               AVG(buy_elg_amount_rate) AS buy_elg_amount_rate,
               SUM(buy_lg_amount)     AS buy_lg_amount,
               AVG(buy_lg_amount_rate) AS buy_lg_amount_rate,
               SUM(buy_md_amount)     AS buy_md_amount,
               AVG(buy_md_amount_rate) AS buy_md_amount_rate,
               SUM(buy_sm_amount)     AS buy_sm_amount,
               AVG(buy_sm_amount_rate) AS buy_sm_amount_rate,
               SUM(COALESCE(buy_elg_amount, 0) + COALESCE(buy_lg_amount, 0)) AS main_buy_amount,
               SUM(COALESCE(buy_md_amount, 0) + COALESCE(buy_sm_amount, 0)) AS retail_buy_amount,
               MAX(amount_unit)       AS amount_unit,
               COUNT(DISTINCT trade_date) AS list_count,
               MIN(trade_date) AS first_date,
               MAX(trade_date) AS last_date,
               GROUP_CONCAT(raw_json, '\n') AS raw_json
        FROM moneyflow_dc
        WHERE top_n = ? AND trade_date IN (SELECT trade_date FROM recent_dates)
        GROUP BY ts_code
        ORDER BY {order_expr}
        LIMIT ?
        """.format(order_expr=order_expr),
        get_conn(),
        params=(str(end_date), int(snapshot_top_n), int(days), int(snapshot_top_n), int(limit)),
    )


def get_range_aggregated(
    start_date: str,
    end_date: str,
    limit: int = 50,
    snapshot_top_n: int = 0,
    sort_by: str = "net_amount",
) -> pd.DataFrame:
    """资金榜日期区间聚合:按 [start_date, end_date] 内累计主力净流入排序。"""
    order_expr = (
        "main_buy_amount DESC, net_amount DESC"
        if sort_by in {"buy_amount", "main_buy_amount"}
        else "net_amount DESC"
    )
    return pd.read_sql_query(
        """
        SELECT ts_code,
               MAX(name)              AS name,
               MAX(close)             AS close,
               MAX(pct_change)        AS pct_change,
               SUM(net_amount)        AS net_amount,
               AVG(net_amount_rate)   AS net_amount_rate,
               SUM(buy_elg_amount)    AS buy_elg_amount,
               AVG(buy_elg_amount_rate) AS buy_elg_amount_rate,
               SUM(buy_lg_amount)     AS buy_lg_amount,
               AVG(buy_lg_amount_rate) AS buy_lg_amount_rate,
               SUM(buy_md_amount)     AS buy_md_amount,
               AVG(buy_md_amount_rate) AS buy_md_amount_rate,
               SUM(buy_sm_amount)     AS buy_sm_amount,
               AVG(buy_sm_amount_rate) AS buy_sm_amount_rate,
               SUM(COALESCE(buy_elg_amount, 0) + COALESCE(buy_lg_amount, 0)) AS main_buy_amount,
               SUM(COALESCE(buy_md_amount, 0) + COALESCE(buy_sm_amount, 0)) AS retail_buy_amount,
               MAX(amount_unit)       AS amount_unit,
               COUNT(DISTINCT trade_date) AS list_count,
               MIN(trade_date) AS first_date,
               MAX(trade_date) AS last_date,
               GROUP_CONCAT(raw_json, '\n') AS raw_json
        FROM moneyflow_dc
        WHERE top_n = ? AND trade_date >= ? AND trade_date <= ?
        GROUP BY ts_code
        ORDER BY {order_expr}
        LIMIT ?
        """.format(order_expr=order_expr),
        get_conn(),
        params=(int(snapshot_top_n), str(start_date), str(end_date), int(limit)),
    )


def latest_date(top_n: int = None):
    if top_n is None:
        row = get_conn().execute("SELECT MAX(trade_date) FROM moneyflow_dc").fetchone()
    else:
        row = get_conn().execute(
            "SELECT MAX(trade_date) FROM moneyflow_dc WHERE top_n=?", (int(top_n),)
        ).fetchone()
    return row[0] if row and row[0] else None


def existing_dates(dates, snapshot_top_n: int = 0) -> set[str]:
    """Return ISO trade dates already stored for the given snapshot bucket."""
    normalized = [_date_key(d) for d in (dates or []) if _date_key(d)]
    if not normalized:
        return set()
    placeholders = ",".join("?" for _ in normalized)
    rows = get_conn().execute(
        f"""
        SELECT DISTINCT trade_date FROM moneyflow_dc
        WHERE top_n=? AND trade_date IN ({placeholders})
        """,
        (int(snapshot_top_n), *normalized),
    ).fetchall()
    return {str(row[0]) for row in rows}


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


def _date_key(value) -> str:
    s = str(value or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _row_raw_json(row) -> str:
    payload = {
        str(c): _to_native(row.get(c))
        for c in row.index
        if str(c) != "raw_json"
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
