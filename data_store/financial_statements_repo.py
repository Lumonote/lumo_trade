"""财务三大表(资产负债表/利润表/现金流量表)按期缓存仓库。

财报低频更新:默认读缓存,缺失/强制刷新才联网取数(provider 免费优先付费兜底)。
每个 (code, statement_type, report_date) 一行,行项目以 JSON 存 items_json。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from data_store.connection import get_conn

STATEMENT_TYPES = ("balance", "income", "cashflow")


def save_statements(
    code: str,
    statement_type: str,
    rows: List[Dict[str, Any]],
    *,
    source: Optional[str] = None,
    ts_code: Optional[str] = None,
) -> int:
    """落库某只股票某类报表的多期数据。rows[i] = {report_date, period?, currency?, items:{}}。

    返回写入行数。同 (code, statement_type, report_date) 覆盖更新。
    """
    code = str(code or "").strip()
    statement_type = str(statement_type or "").strip()
    if not code or statement_type not in STATEMENT_TYPES:
        return 0
    created_at = datetime.now().isoformat(timespec="seconds")
    conn = get_conn()
    payload = []
    for row in rows or []:
        report_date = str(row.get("report_date") or "").strip()
        if not report_date:
            continue
        payload.append((
            code, ts_code, statement_type, report_date,
            row.get("period"), source, row.get("currency"),
            _json_or_none(row.get("items")), created_at,
        ))
    if not payload:
        return 0
    conn.executemany(
        """
        INSERT INTO financial_statement(
          code, ts_code, statement_type, report_date, period, source, currency, items_json, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(code, statement_type, report_date) DO UPDATE SET
          ts_code=excluded.ts_code,
          period=excluded.period,
          source=excluded.source,
          currency=excluded.currency,
          items_json=excluded.items_json,
          created_at=excluded.created_at
        """,
        payload,
    )
    return len(payload)


def statements_for(code: str, statement_type: Optional[str] = None, limit: int = 8) -> List[Dict[str, Any]]:
    """取某股票报表(按报告期倒序)。statement_type 为空则取三表全部。"""
    code = str(code or "").strip()
    if not code:
        return []
    where = "code = ?"
    params: list = [code]
    if statement_type:
        where += " AND statement_type = ?"
        params.append(str(statement_type))
    params.append(int(limit) * (1 if statement_type else len(STATEMENT_TYPES)))
    rows = get_conn().execute(
        f"""
        SELECT * FROM financial_statement
        WHERE {where}
        ORDER BY statement_type, report_date DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["items"] = _json_obj(d.pop("items_json", None))
        out.append(d)
    return out


def latest_report_date(code: str, statement_type: str) -> Optional[str]:
    code = str(code or "").strip()
    if not code:
        return None
    row = get_conn().execute(
        """
        SELECT report_date FROM financial_statement
        WHERE code = ? AND statement_type = ?
        ORDER BY report_date DESC LIMIT 1
        """,
        (code, str(statement_type)),
    ).fetchone()
    return row[0] if row else None


def has_cached(code: str) -> bool:
    code = str(code or "").strip()
    if not code:
        return False
    row = get_conn().execute(
        "SELECT 1 FROM financial_statement WHERE code = ? LIMIT 1",
        (code,),
    ).fetchone()
    return bool(row)


def _json_or_none(v) -> Optional[str]:
    if v is None:
        return None
    try:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _json_obj(v):
    if not v:
        return {}
    try:
        out = json.loads(v)
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}
