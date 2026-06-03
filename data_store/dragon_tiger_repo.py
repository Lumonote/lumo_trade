"""Dragon-tiger (龙虎榜) institutional detail repository.

Table: dragon_tiger_inst. PK: (ts_code, trade_date, inst_name, side).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from data_store.connection import get_conn


_FIELDS = (
    "ts_code", "trade_date", "inst_name", "side",
    "net_amount", "buy_amount", "sell_amount",
    "is_quant", "quant_confidence", "reason",
)

_PK = ("ts_code", "trade_date", "inst_name", "side")


def _code_match(ts_code: str) -> tuple[str, tuple[str, str]]:
    """同一只股票可能以 6 位裸码('000007')或带交易所后缀('000007.SZ')入库：
    akshare 路径(_fetch_and_save)存裸码，Tushare top_inst 回填存带后缀。二者指向同一股票。
    用「裸码精确 OR 后缀 LIKE」同时命中两种格式，修复 6 位查询(suite 统一传 6 位)
    查不到后缀数据导致龙虎榜席位恒「数据不足」的 bug。返回 (where 子句, 参数元组)。"""
    core = (ts_code or "").split(".")[0]
    return "(ts_code=? OR ts_code LIKE ?)", (core, f"{core}.%")


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
        INSERT INTO dragon_tiger_inst({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT({",".join(_PK)}) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount else len(values)


def get_by_code(ts_code: str, trade_date: Optional[str] = None) -> pd.DataFrame:
    """Get all dragon-tiger rows for a stock, optionally filtered by date.

    Matches both 6-digit ('000007') and suffixed ('000007.SZ') storage formats.
    """
    clause, code_params = _code_match(ts_code)
    if trade_date:
        return pd.read_sql_query(
            f"SELECT {','.join(_FIELDS)} FROM dragon_tiger_inst "
            f"WHERE {clause} AND trade_date=? ORDER BY trade_date DESC",
            get_conn(), params=(*code_params, trade_date),
        )
    return pd.read_sql_query(
        f"SELECT {','.join(_FIELDS)} FROM dragon_tiger_inst "
        f"WHERE {clause} ORDER BY trade_date DESC",
        get_conn(), params=code_params,
    )


def latest(ts_code: str) -> Optional[Dict]:
    """Return the most recent trade_date row(s) as a dict, or None."""
    clause, code_params = _code_match(ts_code)
    row = get_conn().execute(
        f"SELECT MAX(trade_date) FROM dragon_tiger_inst WHERE {clause}",
        code_params,
    ).fetchone()
    if not row or not row[0]:
        return None
    return {"trade_date": row[0]}


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
