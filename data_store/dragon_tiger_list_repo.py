"""龙虎榜单(个股/日)仓库 —— Tushare `top_list` 口径。

`net_amount` = 含游资的龙虎榜净买入额(D5 排序键)。同股同日可有多条
「上榜原因」(reason),故主键 (trade_date, ts_code, reason)。

排行查询按 ts_code 合并同日多原因:LHB 净/买/卖额求和,日级描述字段
(name/close/pct_change/turnover_rate/amount)取 MAX(同日各原因行相同,
取 MAX 即原值,避免重复计)。

数据语义假设:多原因行的 net_amount 视为可加(对应「总净买入额」)。
若实测 top_list 多原因行的 net 为重复披露而非可加,应改为按 ts_code 取
MAX(net_amount)——届时仅需改两处聚合 SQL。
"""
from __future__ import annotations

import json
from typing import Iterable, Optional

import pandas as pd

from data_store.connection import get_conn


_FIELDS = (
    "trade_date", "ts_code", "name", "close", "pct_change",
    "turnover_rate", "amount", "l_buy", "l_sell", "l_amount",
    "net_amount", "net_rate", "amount_rate", "reason", "raw_json",
)


def upsert_df(df: pd.DataFrame) -> int:
    """落库龙虎榜单。键 (trade_date, ts_code, reason),冲突即覆盖。返回写入行数。"""
    if df is None or df.empty:
        return 0
    work = df.copy()
    work["trade_date"] = work["trade_date"].map(_date_key)
    work["ts_code"] = work["ts_code"].astype(str)
    if "reason" not in work.columns:
        work["reason"] = ""
    work["reason"] = work["reason"].fillna("").astype(str)
    work["raw_json"] = work.apply(_row_raw_json, axis=1)
    for col in _FIELDS:
        if col not in work.columns:
            work[col] = None
    rows: Iterable = (
        tuple(_to_native(getattr(r, c)) for c in _FIELDS)
        for r in work.itertuples(index=False)
    )
    placeholders = ",".join("?" * len(_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _FIELDS
        if c not in ("trade_date", "ts_code", "reason")
    )
    cur = get_conn().executemany(
        f"""
        INSERT INTO dragon_tiger_list({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT(trade_date, ts_code, reason) DO UPDATE SET {set_clause}
        """,
        list(rows),
    )
    return cur.rowcount if cur.rowcount is not None else len(work)


def get_top_n(trade_date: str, top_n: int) -> pd.DataFrame:
    """单日榜:按 ts_code 合并多原因,按净买入额(含游资)降序取前 top_n。"""
    return pd.read_sql_query(
        """
        SELECT trade_date, ts_code,
               MAX(name)          AS name,
               MAX(close)         AS close,
               MAX(pct_change)    AS pct_change,
               MAX(turnover_rate) AS turnover_rate,
               MAX(amount)        AS amount,
               SUM(l_buy)         AS l_buy,
               SUM(l_sell)        AS l_sell,
               SUM(l_amount)      AS l_amount,
               SUM(net_amount)    AS net_amount,
               MAX(net_rate)      AS net_rate,
               MAX(amount_rate)   AS amount_rate,
               COUNT(*)           AS reason_count,
               GROUP_CONCAT(reason, ' / ') AS reason,
               GROUP_CONCAT(raw_json, '\n') AS raw_json
        FROM dragon_tiger_list
        WHERE trade_date = ?
        GROUP BY ts_code
        ORDER BY net_amount DESC
        LIMIT ?
        """,
        get_conn(),
        params=(str(trade_date), int(top_n)),
    )


def get_aggregated(end_date: str, days: int, top_n: int, sort_by: str = "net_amount") -> pd.DataFrame:
    """多日聚合:取 end_date 及之前最近 days 个有数据的交易日,按累计净买入额
    降序取前 top_n;list_count = 窗口内上榜天数(去重日期)。"""
    order_expr = "l_buy DESC, net_amount DESC" if sort_by in {"buy_amount", "l_buy"} else "net_amount DESC"
    return pd.read_sql_query(
        """
        WITH recent_dates AS (
            SELECT DISTINCT trade_date FROM dragon_tiger_list
            WHERE trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT ?
        )
        SELECT ts_code,
               MAX(name)          AS name,
               MAX(close)         AS close,
               MAX(pct_change)    AS pct_change,
               MAX(turnover_rate) AS turnover_rate,
               SUM(amount)        AS amount,
               SUM(l_buy)         AS l_buy,
               SUM(l_sell)        AS l_sell,
               SUM(l_amount)      AS l_amount,
               SUM(net_amount)    AS net_amount,
               AVG(net_rate)      AS net_rate,
               AVG(amount_rate)   AS amount_rate,
               COUNT(DISTINCT trade_date) AS list_count,
               COUNT(*) AS reason_count,
               MIN(trade_date) AS first_date,
               MAX(trade_date) AS last_date,
               GROUP_CONCAT(reason, ' / ') AS reason,
               GROUP_CONCAT(raw_json, '\n') AS raw_json
        FROM dragon_tiger_list
        WHERE trade_date IN (SELECT trade_date FROM recent_dates)
        GROUP BY ts_code
        ORDER BY {order_expr}
        LIMIT ?
        """.format(order_expr=order_expr),
        get_conn(),
        params=(str(end_date), int(days), int(top_n)),
    )


def get_range_aggregated(start_date: str, end_date: str, top_n: int, sort_by: str = "net_amount") -> pd.DataFrame:
    """日期区间聚合:按 [start_date, end_date] 内累计龙虎榜净买入额排序。"""
    order_expr = "l_buy DESC, net_amount DESC" if sort_by in {"buy_amount", "l_buy"} else "net_amount DESC"
    return pd.read_sql_query(
        """
        SELECT ts_code,
               MAX(name)          AS name,
               MAX(close)         AS close,
               MAX(pct_change)    AS pct_change,
               MAX(turnover_rate) AS turnover_rate,
               SUM(amount)        AS amount,
               SUM(l_buy)         AS l_buy,
               SUM(l_sell)        AS l_sell,
               SUM(l_amount)      AS l_amount,
               SUM(net_amount)    AS net_amount,
               AVG(net_rate)      AS net_rate,
               AVG(amount_rate)   AS amount_rate,
               COUNT(DISTINCT trade_date) AS list_count,
               COUNT(*) AS reason_count,
               MIN(trade_date) AS first_date,
               MAX(trade_date) AS last_date,
               GROUP_CONCAT(reason, ' / ') AS reason,
               GROUP_CONCAT(raw_json, '\n') AS raw_json
        FROM dragon_tiger_list
        WHERE trade_date >= ? AND trade_date <= ?
        GROUP BY ts_code
        ORDER BY {order_expr}
        LIMIT ?
        """.format(order_expr=order_expr),
        get_conn(),
        params=(str(start_date), str(end_date), int(top_n)),
    )


def latest_date() -> Optional[str]:
    row = get_conn().execute("SELECT MAX(trade_date) FROM dragon_tiger_list").fetchone()
    return row[0] if row and row[0] else None


def existing_dates(dates) -> set[str]:
    """Return ISO trade dates already stored in dragon_tiger_list."""
    normalized = [_date_key(d) for d in (dates or []) if _date_key(d)]
    if not normalized:
        return set()
    placeholders = ",".join("?" for _ in normalized)
    rows = get_conn().execute(
        f"""
        SELECT DISTINCT trade_date FROM dragon_tiger_list
        WHERE trade_date IN ({placeholders})
        """,
        tuple(normalized),
    ).fetchall()
    return {str(row[0]) for row in rows}


def count() -> int:
    row = get_conn().execute("SELECT COUNT(*) FROM dragon_tiger_list").fetchone()
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
