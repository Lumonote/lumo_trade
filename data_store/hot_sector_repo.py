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


def sector_pool(limit: int = 200) -> List[Dict[str, Any]]:
    """跨所有快照聚合的「板块池」:每个曾上榜的热门板块一行,含上榜次数、首次/最近
    上榜时间、重复上榜的日期列表、最佳名次、平均涨幅等。

    - ``appearances``:该板块出现过的快照次数。
    - ``distinct_days``:去重交易日数(衡量「重复入选」跨越多少天)。
    - ``days_csv``→``days``:去重的上榜交易日(升序),前端展开为重复上榜时间线。
    - 名称/类型/名次/涨幅等「最新值」取该板块最近一次快照的行(window rn=1)。
    """
    rows = get_conn().execute(
        """
        WITH joined AS (
          SELECT b.board_code, b.board_name, b.board_type, b.board_rank,
                 b.change_pct, b.main_net_inflow, b.snapshot_id,
                 s.created_at, COALESCE(s.trade_date, substr(s.created_at,1,10)) AS day,
                 ROW_NUMBER() OVER (
                   PARTITION BY b.board_code ORDER BY s.created_at DESC, s.id DESC
                 ) AS rn
          FROM hot_sector_board b
          JOIN hot_sector_snapshot s ON s.id = b.snapshot_id
        )
        SELECT
          board_code,
          COUNT(*)                    AS appearances,
          COUNT(DISTINCT day)         AS distinct_days,
          MIN(created_at)             AS first_seen,
          MAX(created_at)             AS last_seen,
          MIN(board_rank)             AS best_rank,
          AVG(board_rank)             AS avg_rank,
          AVG(change_pct)             AS avg_change_pct,
          AVG(main_net_inflow)        AS avg_main_net_inflow,
          GROUP_CONCAT(DISTINCT day)  AS days_csv,
          MAX(CASE WHEN rn=1 THEN board_name END)      AS board_name,
          MAX(CASE WHEN rn=1 THEN board_type END)      AS board_type,
          MAX(CASE WHEN rn=1 THEN board_rank END)      AS last_rank,
          MAX(CASE WHEN rn=1 THEN change_pct END)      AS last_change_pct,
          MAX(CASE WHEN rn=1 THEN main_net_inflow END) AS last_main_net_inflow,
          MAX(CASE WHEN rn=1 THEN snapshot_id END)     AS last_snapshot_id
        FROM joined
        GROUP BY board_code
        ORDER BY appearances DESC, last_seen DESC, best_rank ASC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        days = [s for s in str(d.pop("days_csv", "") or "").split(",") if s]
        d["days"] = sorted(days)
        out.append(d)
    return out


_COLUMN_LABELS = {
    # 快照
    "id": "编号", "snapshot_id": "快照编号", "created_at": "生成时间",
    "trade_date": "交易日", "source": "数据源", "board_limit": "板块数上限",
    "board_count": "板块数", "stock_count": "成分股数", "relation_count": "关联数",
    # 热门板块
    "board_code": "板块代码", "board_name": "板块名称", "board_type": "板块类型",
    "board_rank": "板块排名", "change_pct": "涨跌幅(%)",
    "main_net_inflow": "主力净流入(元)", "main_net_inflow_text": "主力净流入",
    # 成分股
    "code": "股票代码", "name": "名称", "stock_rank": "板块内排名",
    "candidate_rank": "候选排名", "price": "现价",
    "lhb_trade_date": "龙虎榜日期", "lhb_buy_amount": "龙虎榜买入额(元)",
    "lhb_sell_amount": "龙虎榜卖出额(元)", "lhb_net_amount": "龙虎榜净额(元)",
    "lhb_reason": "上榜原因",
    # 关联关系
    "relation_type": "关联类型", "related_table": "关联表",
    "related_key": "关联键", "amount": "金额(元)",
    # ── JSON 平铺后的键(extra_json/raw_json/detail_json)──
    "candidate_limit": "候选数上限", "constituent_limit": "成分数上限",
    "content_type": "内容类型", "ts_code": "TS代码", "con_code": "成分TS代码",
    "pct_change": "板块涨跌幅(%)", "close": "板块点位",
    "net_amount": "净额(元)", "net_amount_rate": "净占比(%)",
    "buy_elg_amount": "超大单买入(元)", "buy_elg_amount_rate": "超大单买入占比(%)",
    "buy_lg_amount": "大单买入(元)", "buy_lg_amount_rate": "大单买入占比(%)",
    "buy_md_amount": "中单买入(元)", "buy_md_amount_rate": "中单买入占比(%)",
    "buy_sm_amount": "小单买入(元)", "buy_sm_amount_rate": "小单买入占比(%)",
    "buy_sm_amount_stock": "小单买入代表股", "rank": "资金排名",
    "l_buy": "龙虎榜买入额(元)", "l_sell": "龙虎榜卖出额(元)", "reason": "上榜原因",
}

# 整段塞进单元格的 JSON 列;导出时平铺成多列而不是留一段 JSON 文本。
_JSON_BLOB_COLUMNS = ("raw_json", "detail_json", "extra_json")

# 平铺时按来源列跳过的冗余键:代码/日期变体、与既有列重复的派生值。
# (raw_json 的 ts_code/con_code 只是 board_code/code 加交易所后缀;name/content_type/
#  pct_change/net_amount 与既有列重复;trade_date 恒为快照日,已在「快照」表。)
_JSON_DROP_KEYS = {
    "raw_json": frozenset({"ts_code", "con_code", "trade_date", "content_type",
                           "pct_change", "name", "net_amount"}),
    "detail_json": frozenset({"trade_date"}),
    "extra_json": frozenset(),
}

# 逐股评分列(来自 opportunity_item,见 _enrich_stock_frame)。
_SCORE_PART_LABELS = {
    "quantitative": "量化分", "technical": "技术分", "momentum": "动量分",
    "volume_health": "量能分", "liquidity": "流动性分",
}
_SCORE_SIGNAL_LABELS = {"chase": "追高风险", "rsi": "RSI", "day_change": "当日涨幅(%)"}

# 枚举型数据值的中文化(按英文列名分组,未命中的值原样保留)。
_VALUE_LABELS = {
    "source": {
        "sector_hot": "热门板块 东财",
        "sector_hot_eastmoney": "热门板块 东财",
        "sector_hot_tushare": "热门板块 Tushare",
        "multi": "多源融合",
        "heat": "热度榜",
        "moneyflow_dc": "资金流向",
    },
    "relation_type": {"dragon_tiger": "龙虎榜"},
    "related_table": {"dragon_tiger_list": "龙虎榜单"},
}


def _parse_json_cell(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _scalarize_cell(value):
    # 平铺出的值若仍是容器,转回紧凑 JSON 文本,避免 openpyxl 无法写入 dict/list。
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _label_for(key: str) -> str:
    return _COLUMN_LABELS.get(key, key)


def _dataframe_for_export(df: "pd.DataFrame") -> "pd.DataFrame":
    """把原始 DataFrame 转成可读导出形态:JSON 列平铺为多列 + 表头中文化。

    - ``raw_json``/``detail_json``/``extra_json`` 内每个键平铺成独立列(避免「整列就是
      一段 JSON」);下划线开头的内部派生键(``_chg``/``_net``)及与已有列/标签重复的键
      自动去重,不重复平铺;
    - 全部英文列名按 :data:`_COLUMN_LABELS` 映射成中文,未覆盖的列名原样保留。
    """
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    # 已有数值列 主力净流入(元),去掉冗余的格式化文本孪生列,避免「重复」观感。
    if "main_net_inflow_text" in out.columns:
        out = out.drop(columns=["main_net_inflow_text"])
    # 枚举型数据值中文化(dragon_tiger→龙虎榜、sector_hot_tushare→热门板块 Tushare 等)。
    for value_col, mapping in _VALUE_LABELS.items():
        if value_col in out.columns:
            out[value_col] = [mapping.get(v, v) for v in out[value_col].tolist()]
    for col in _JSON_BLOB_COLUMNS:
        if col not in out.columns:
            continue
        drop_keys = _JSON_DROP_KEYS.get(col, frozenset())
        parsed = [_parse_json_cell(v) for v in out[col].tolist()]
        out = out.drop(columns=[col])
        present_keys = set(out.columns)
        present_labels = {_label_for(c) for c in out.columns}
        ordered_keys = []
        for record in parsed:
            for key in record:
                if key not in ordered_keys:
                    ordered_keys.append(key)
        for key in ordered_keys:
            if key.startswith("_") or key in drop_keys:
                continue  # 内部派生键 / 冗余键不导出
            label = _label_for(key)
            if key in present_keys or label in present_labels:
                continue  # 与既有列(或已平铺列)去重
            present_labels.add(label)
            out[label] = [_scalarize_cell(record.get(key)) for record in parsed]
    return out.rename(columns=_COLUMN_LABELS)


def _is_blank_cell(value) -> bool:
    """快照里「无数据」的判定:None/NaN/空串/占位符 — / 0 都视为可被实时报价回填。"""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() in ("", "—", "-"):
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    return False


def _enrich_stock_frame(df: "pd.DataFrame", scores=None, quotes=None) -> "pd.DataFrame":
    """给成分股 DataFrame 回填实时报价 + 关联逐股评分。

    - ``quotes``:``{6位代码: {price, change_pct, main_net_inflow}}``,仅回填快照里为空
      的 现价/涨跌幅/主力净流入(不覆盖快照已有的非空值);
    - ``scores``:``{代码: opportunity_item 行}``,展开成 综合评分/评级/各分项/关键信号/
      板块内评分排名 等列;未命中的成分股「评级」标记为「未评分」,其余留空。
    """
    if df is None or df.empty or "code" not in df.columns:
        return df
    out = df.copy()
    codes = [_norm_code(c) for c in out["code"].tolist()]

    if quotes:
        for field in ("price", "change_pct", "main_net_inflow"):
            if field not in out.columns:
                out[field] = None
            filled = []
            for current, code in zip(out[field].tolist(), codes):
                q = quotes.get(code) or {}
                replacement = q.get(field)
                filled.append(replacement if (_is_blank_cell(current) and replacement is not None) else current)
            out[field] = filled

    if scores is not None:
        items = [scores.get(code) for code in codes]
        parts = [_parse_json_cell((it or {}).get("scores_json")) for it in items]
        signals = [_parse_json_cell((it or {}).get("signals_json")) for it in items]
        out["综合评分"] = [(it or {}).get("total_score") for it in items]
        out["评级"] = [((it or {}).get("rating") if it else "未评分") for it in items]
        for key, label in _SCORE_PART_LABELS.items():
            out[label] = [_round_num(p.get(key)) for p in parts]
        for key, label in _SCORE_SIGNAL_LABELS.items():
            out[label] = [_round_num(s.get(key)) for s in signals]
        out["板块内评分排名"] = [(it or {}).get("sector_stock_rank") for it in items]
    return out


def _round_num(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _norm_code(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit()).zfill(6)[-6:]


def export_snapshot_excel(snapshot_id: int, output_path: Path | str, *, scores=None, quotes=None) -> Path:
    """Export snapshot to a multi-sheet Excel workbook.

    ``scores`` / ``quotes`` 由上层(core.export_hot_sector_snapshot)按需注入,用于给成分股
    表回填实时报价并附上逐股评分;为空时退化为纯快照导出。
    """
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        raise ValueError(f"hot sector snapshot not found: {snapshot_id}")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    boards = pd.DataFrame(boards_for_snapshot(snapshot_id))
    stocks = pd.DataFrame(stocks_for_snapshot(snapshot_id, limit=100000))
    relations = pd.DataFrame(relations_for_snapshot(snapshot_id, limit=100000))
    summary = pd.DataFrame([snapshot])

    # 先在英文原始列上回填报价 + 附评分(过滤/分组仍走英文列),写表前再平铺+中文化。
    stocks = _enrich_stock_frame(stocks, scores=scores, quotes=quotes)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        used_sheets = {"快照", "热门板块", "成分股排名资金", "龙虎榜命中", "关联关系"}
        _dataframe_for_export(summary).to_excel(writer, sheet_name="快照", index=False)
        _dataframe_for_export(boards).to_excel(writer, sheet_name="热门板块", index=False)
        _dataframe_for_export(stocks).to_excel(writer, sheet_name="成分股排名资金", index=False)
        lhb = stocks[stocks.get("lhb_trade_date").notna()] if not stocks.empty and "lhb_trade_date" in stocks else pd.DataFrame()
        _dataframe_for_export(lhb).to_excel(writer, sheet_name="龙虎榜命中", index=False)
        _dataframe_for_export(relations).to_excel(writer, sheet_name="关联关系", index=False)

        if not stocks.empty and "board_code" in stocks:
            for board_code, group in stocks.groupby("board_code"):
                board_name = ""
                if not boards.empty and "board_code" in boards:
                    matched = boards.loc[boards["board_code"] == board_code]
                    if not matched.empty:
                        board_name = str(matched.iloc[0].get("board_name") or "")
                sheet = _unique_sheet_name(_sheet_name(f"{board_name or board_code}"), used_sheets)
                used_sheets.add(sheet)
                _dataframe_for_export(group).to_excel(writer, sheet_name=sheet, index=False)
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
