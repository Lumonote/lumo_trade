"""热门板块全量快照仓库。

记录前十大热门板块、板块下全部成分股排名/资金字段,以及命中的龙虎榜关系。
桌面无限画布和 Excel 导出都读这份结构化快照。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from data_store.connection import get_conn


def save_snapshot(
    boards: List[Dict[str, Any]],
    stocks: List[Dict[str, Any]],
    relations: List[Dict[str, Any]] | None = None,
    *,
    meta: Dict[str, Any] | None = None,
) -> int:
    meta = dict(meta or {})
    boards = list(boards or [])
    stocks = list(stocks or [])
    relations = list(relations or [])
    created_at = str(meta.get("created_at") or datetime.now().isoformat(timespec="seconds"))
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO hot_sector_snapshot(
          created_at, trade_date, source, board_limit, board_count,
          stock_count, relation_count, extra_json
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            created_at,
            meta.get("trade_date"),
            meta.get("source"),
            _num(meta.get("board_limit")),
            len(boards),
            len(stocks),
            len(relations),
            _json_or_none({k: v for k, v in meta.items() if k not in {"created_at", "trade_date", "source", "board_limit"}}),
        ),
    )
    snapshot_id = int(cur.lastrowid)

    board_rows = [
        (
            snapshot_id,
            b.get("code") or b.get("board_code"),
            b.get("name") or b.get("board_name"),
            b.get("type") or b.get("board_type"),
            _num(b.get("rank") or b.get("board_rank")),
            _num(b.get("change_pct")),
            _num(b.get("main_net_inflow")),
            _json_or_none(b.get("raw") or b),
        )
        for b in boards
        if b.get("code") or b.get("board_code")
    ]
    conn.executemany(
        """
        INSERT INTO hot_sector_board(
          snapshot_id, board_code, board_name, board_type, board_rank,
          change_pct, main_net_inflow, raw_json
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(snapshot_id, board_code) DO UPDATE SET
          board_name=excluded.board_name,
          board_type=excluded.board_type,
          board_rank=excluded.board_rank,
          change_pct=excluded.change_pct,
          main_net_inflow=excluded.main_net_inflow,
          raw_json=excluded.raw_json
        """,
        board_rows,
    )

    stock_rows = [
        (
            snapshot_id,
            s.get("sector_code") or s.get("board_code"),
            s.get("code"),
            s.get("name"),
            _num(s.get("sector_stock_rank") or s.get("stock_rank")),
            _num(s.get("candidate_rank") or s.get("rank")),
            _num(s.get("price")),
            _num(s.get("change_pct")),
            _num(s.get("main_net_inflow")),
            s.get("main_net_inflow_text"),
            s.get("lhb_trade_date"),
            _num(s.get("lhb_buy_amount")),
            _num(s.get("lhb_sell_amount")),
            _num(s.get("lhb_net_amount")),
            s.get("lhb_reason"),
            _json_or_none(s.get("raw") or s),
        )
        for s in stocks
        if (s.get("sector_code") or s.get("board_code")) and s.get("code")
    ]
    conn.executemany(
        """
        INSERT INTO hot_sector_stock(
          snapshot_id, board_code, code, name, stock_rank, candidate_rank,
          price, change_pct, main_net_inflow, main_net_inflow_text,
          lhb_trade_date, lhb_buy_amount, lhb_sell_amount, lhb_net_amount,
          lhb_reason, raw_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(snapshot_id, board_code, code) DO UPDATE SET
          name=excluded.name,
          stock_rank=excluded.stock_rank,
          candidate_rank=excluded.candidate_rank,
          price=excluded.price,
          change_pct=excluded.change_pct,
          main_net_inflow=excluded.main_net_inflow,
          main_net_inflow_text=excluded.main_net_inflow_text,
          lhb_trade_date=excluded.lhb_trade_date,
          lhb_buy_amount=excluded.lhb_buy_amount,
          lhb_sell_amount=excluded.lhb_sell_amount,
          lhb_net_amount=excluded.lhb_net_amount,
          lhb_reason=excluded.lhb_reason,
          raw_json=excluded.raw_json
        """,
        stock_rows,
    )

    relation_rows = [
        (
            snapshot_id,
            r.get("board_code") or r.get("sector_code"),
            r.get("code"),
            r.get("relation_type"),
            r.get("related_table"),
            r.get("related_key"),
            r.get("trade_date"),
            _num(r.get("amount")),
            _json_or_none(r.get("detail") or r),
        )
        for r in relations
        if r.get("code") and r.get("relation_type")
    ]
    conn.executemany(
        """
        INSERT INTO hot_sector_relation(
          snapshot_id, board_code, code, relation_type, related_table,
          related_key, trade_date, amount, detail_json
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        relation_rows,
    )
    return snapshot_id


def latest_snapshot() -> Optional[Dict[str, Any]]:
    row = get_conn().execute(
        """
        SELECT * FROM hot_sector_snapshot
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def list_snapshots(limit: int = 50) -> List[Dict[str, Any]]:
    """List historical hot-sector snapshots, newest first."""
    rows = get_conn().execute(
        """
        SELECT * FROM hot_sector_snapshot
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [dict(row) for row in rows]


def get_snapshot(snapshot_id: int | None = None) -> Optional[Dict[str, Any]]:
    if snapshot_id is None:
        return latest_snapshot()
    row = get_conn().execute(
        "SELECT * FROM hot_sector_snapshot WHERE id=?",
        (int(snapshot_id),),
    ).fetchone()
    return dict(row) if row else None


def boards_for_snapshot(snapshot_id: int) -> List[Dict[str, Any]]:
    rows = get_conn().execute(
        """
        SELECT b.*,
               (SELECT COUNT(*) FROM hot_sector_stock s
                WHERE s.snapshot_id=b.snapshot_id AND s.board_code=b.board_code) AS stock_count,
               (SELECT COUNT(*) FROM hot_sector_relation r
                WHERE r.snapshot_id=b.snapshot_id AND r.board_code=b.board_code) AS relation_count
        FROM hot_sector_board b
        WHERE b.snapshot_id=?
        ORDER BY b.board_rank, b.change_pct DESC
        """,
        (int(snapshot_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def stocks_for_snapshot(
    snapshot_id: int,
    *,
    board_code: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    where = "snapshot_id=?"
    params: list[Any] = [int(snapshot_id)]
    if board_code:
        where += " AND board_code=?"
        params.append(str(board_code))
    params.extend([int(limit), int(offset)])
    rows = get_conn().execute(
        f"""
        SELECT * FROM hot_sector_stock
        WHERE {where}
        ORDER BY board_code, stock_rank, candidate_rank
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def relations_for_snapshot(
    snapshot_id: int,
    *,
    board_code: str | None = None,
    code: str | None = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    where = "snapshot_id=?"
    params: list[Any] = [int(snapshot_id)]
    if board_code:
        where += " AND board_code=?"
        params.append(str(board_code))
    if code:
        where += " AND code=?"
        params.append(str(code))
    params.append(int(limit))
    rows = get_conn().execute(
        f"""
        SELECT * FROM hot_sector_relation
        WHERE {where}
        ORDER BY relation_type, trade_date DESC, amount DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def export_snapshot_excel(snapshot_id: int, output_path: Path | str) -> Path:
    """Export snapshot to a multi-sheet Excel workbook."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        raise ValueError(f"hot sector snapshot not found: {snapshot_id}")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    boards = pd.DataFrame(boards_for_snapshot(snapshot_id))
    stocks = pd.DataFrame(stocks_for_snapshot(snapshot_id, limit=100000))
    relations = pd.DataFrame(relations_for_snapshot(snapshot_id, limit=100000))
    summary = pd.DataFrame([snapshot])

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        used_sheets = {"快照", "热门板块", "成分股排名资金", "龙虎榜命中", "关联关系"}
        summary.to_excel(writer, sheet_name="快照", index=False)
        boards.to_excel(writer, sheet_name="热门板块", index=False)
        stocks.to_excel(writer, sheet_name="成分股排名资金", index=False)
        lhb = stocks[stocks.get("lhb_trade_date").notna()] if not stocks.empty and "lhb_trade_date" in stocks else pd.DataFrame()
        lhb.to_excel(writer, sheet_name="龙虎榜命中", index=False)
        relations.to_excel(writer, sheet_name="关联关系", index=False)

        if not stocks.empty and "board_code" in stocks:
            for board_code, group in stocks.groupby("board_code"):
                board_name = ""
                if not boards.empty and "board_code" in boards:
                    matched = boards.loc[boards["board_code"] == board_code]
                    if not matched.empty:
                        board_name = str(matched.iloc[0].get("board_name") or "")
                sheet = _unique_sheet_name(_sheet_name(f"{board_name or board_code}"), used_sheets)
                used_sheets.add(sheet)
                group.to_excel(writer, sheet_name=sheet, index=False)
    return output


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _json_or_none(v) -> Optional[str]:
    if v is None:
        return None
    try:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _sheet_name(value: str) -> str:
    text = str(value or "sheet").strip()[:28] or "sheet"
    for ch in r'[]:*?/\\':
        text = text.replace(ch, "_")
    return text


def _unique_sheet_name(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    for i in range(2, 100):
        suffix = f"_{i}"
        candidate = f"{base[:31 - len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
    return base[:28] + "_x"
