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
    rows = _merge_duplicate_pk_rows(rows)
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


def _merge_duplicate_pk_rows(rows: List[Dict]) -> List[Dict]:
    """Merge same-seat rows from multiple reasons before upsert.

    Tushare top_inst can return the same institution/side for one stock-day under
    different reasons. The table primary key intentionally stores one row per
    seat, so merge the fetched batch first instead of letting later reasons
    overwrite earlier amounts.
    """
    merged: dict[tuple, Dict] = {}
    reasons: dict[tuple, list[str]] = {}
    for row in rows:
        key = tuple(_to_native(row.get(c)) for c in _PK)
        if key not in merged:
            merged[key] = dict(row)
            reason = str(row.get("reason") or "").strip()
            reasons[key] = [reason] if reason else []
            continue
        item = merged[key]
        for col in ("net_amount", "buy_amount", "sell_amount"):
            item[col] = _sum_values(item.get(col), row.get(col))
        item["is_quant"] = max(_num(item.get("is_quant")) or 0, _num(row.get("is_quant")) or 0)
        q_existing = _num(item.get("quant_confidence"))
        q_new = _num(row.get("quant_confidence"))
        if q_new is not None and (q_existing is None or q_new > q_existing):
            item["quant_confidence"] = row.get("quant_confidence")
        reason = str(row.get("reason") or "").strip()
        if reason and reason not in reasons[key]:
            reasons[key].append(reason)
    for key, item in merged.items():
        if reasons.get(key):
            item["reason"] = " / ".join(reasons[key])
    return list(merged.values())


def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sum_values(a, b):
    nums = [v for v in (_num(a), _num(b)) if v is not None]
    return sum(nums) if nums else None


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


def get_quant_by_date(start_date: str, end_date: str) -> pd.DataFrame:
    """日期窗口内 is_quant=1 的量化席位行(量化雷达按日扫描;命中 idx_lhbi_quant)。"""
    if not start_date or not end_date:
        return pd.DataFrame()
    return pd.read_sql_query(
        f"SELECT {','.join(_FIELDS)} FROM dragon_tiger_inst "
        "WHERE is_quant=1 AND trade_date>=? AND trade_date<=? "
        "ORDER BY trade_date DESC, ABS(COALESCE(net_amount,0)) DESC",
        get_conn(), params=(start_date, end_date),
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
