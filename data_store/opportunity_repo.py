"""投资机会挖掘结果仓库 —— 按天存每次 run 的元信息 + 全量评分明细。

桌面端 job(webui/core._run_opportunity_job) 与 quick_start CLI 都经
``OpportunityDiscovery.run`` 落库,故两侧产出同表可比对。
``ruleset_version``/``config_hash`` 记录该次 run 实际生效的评分规则版本与
运行时参数配置,用于解释「不同时间/不同端分数不一致」。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from analysis import outcome_markers
from data_store import opportunity_prices
from data_store.connection import get_conn


_RUN_FIELDS = (
    "run_at", "run_date", "source", "candidate_limit", "mode",
    "ruleset_version", "config_hash", "report_file",
    "candidates", "analyzed", "duration_sec", "extra_json",
)


def save_run(meta: Dict[str, Any], items: List[Dict[str, Any]],
             hot_news: Optional[List[Dict[str, Any]]] = None) -> int:
    """落库一次挖掘 run。返回 run_id。

    items 形如 build_items() 的输出;按 total_score 降序写入并赋 item_rank,
    同 run 内重复 code 保留先到(高分)行。
    hot_news 形如 run_opportunity_discovery.global_hot_news 的
    ``{title, url, source, publish_time, heat}``;非空则按 title 去重(保留 heat
    高者)、heat 降序、截前 10 条写入 opportunity_hot_news,与 items 同事务。
    """
    meta = dict(meta or {})
    run_at = str(meta.get("run_at") or "")
    meta.setdefault("run_date", run_at[:10])
    extra = meta.get("extra")
    meta["extra_json"] = (
        json.dumps(extra, ensure_ascii=False, separators=(",", ":"))
        if isinstance(extra, (dict, list)) else meta.get("extra_json")
    )

    conn = get_conn()
    cur = conn.execute(
        f"""
        INSERT INTO opportunity_run({",".join(_RUN_FIELDS)})
        VALUES({",".join("?" * len(_RUN_FIELDS))})
        """,
        tuple(meta.get(f) for f in _RUN_FIELDS),
    )
    run_id = int(cur.lastrowid)

    ordered = sorted(
        list(items or []),
        key=lambda i: float(i.get("total_score") or 0),
        reverse=True,
    )
    rows = []
    for rank, item in enumerate(ordered, start=1):
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        rows.append((
            run_id, code, item.get("name"), rank,
            _num(item.get("total_score")), item.get("rating"),
            1 if item.get("degraded") else 0,
            item.get("source"), item.get("source_detail"),
            item.get("sector") or item.get("industry") or item.get("sector_name"),
            item.get("sector_code"),
            _num(item.get("sector_rank")),
            _num(item.get("sector_stock_rank")),
            _num(item.get("change_pct")),
            _json_or_none(item.get("scores")),
            _json_or_none(item.get("signals")),
        ))
    conn.executemany(
        """
        INSERT INTO opportunity_item(
          run_id, code, name, item_rank, total_score, rating,
          degraded, source, source_detail, sector, sector_code,
          sector_rank, sector_stock_rank, change_pct, scores_json, signals_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(run_id, code) DO NOTHING
        """,
        rows,
    )
    _save_hot_news(conn, run_id, hot_news)
    return run_id


def _save_hot_news(conn, run_id: int, hot_news: Optional[List[Dict[str, Any]]],
                   limit: int = 10) -> None:
    """写入一次 run 的热点新闻:按 title 去重(保留 heat 高者)、heat 降序、限 limit。"""
    if not hot_news:
        return
    by_title: Dict[str, Dict[str, Any]] = {}
    for n in hot_news:
        if not isinstance(n, dict):
            continue
        title = str(n.get("title") or "").strip()
        if not title:
            continue
        heat = _num(n.get("heat"))
        prev = by_title.get(title)
        if prev is None or (heat or -1) > (_num(prev.get("heat")) or -1):
            by_title[title] = n
    ordered = sorted(by_title.values(),
                     key=lambda n: (_num(n.get("heat")) if _num(n.get("heat")) is not None else -1),
                     reverse=True)[:limit]
    rows = [
        (run_id, rank, str(n.get("title") or "").strip(), n.get("url"),
         n.get("source"), n.get("publish_time"), _num(n.get("heat")))
        for rank, n in enumerate(ordered, start=1)
    ]
    if rows:
        conn.executemany(
            """
            INSERT INTO opportunity_hot_news(
              run_id, news_rank, title, url, source, publish_time, heat)
            VALUES(?,?,?,?,?,?,?)
            """,
            rows,
        )


def latest_hot_news(run_date: Optional[str] = None,
                    limit: int = 10, *,
                    report_file: Optional[str] = None,
                    latest_run_only: bool = False) -> List[Dict[str, Any]]:
    """读取热点新闻。

    ``report_file`` 非空时精确读取该报告对应的 run；若该 run 没有热点则返回 []
    而不是回退旧数据。``latest_run_only`` 为 True 时读取指定日期(或全局)最新 run,
    同样不要求该 run 有热点。默认保持历史行为:读取最近一次有热点的 run。
    """
    conn = get_conn()
    if report_file:
        name = _basename(report_file)
        run_row = conn.execute(
            """
            SELECT id FROM opportunity_run
            WHERE report_file = ?
            ORDER BY run_at DESC, id DESC
            LIMIT 1
            """,
            (name,),
        ).fetchone()
        if not run_row:
            return []
        return _hot_news_for_run(conn, run_row[0], limit)

    if latest_run_only:
        where = "WHERE r.run_date = ?" if run_date else ""
        params: tuple = (str(run_date),) if run_date else ()
        sql = f"""
        SELECT r.id FROM opportunity_run r
        {where}
        ORDER BY r.run_at DESC, r.id DESC
        LIMIT 1
        """
    else:
        where = "AND r.run_date = ?" if run_date else ""
        params = (str(run_date),) if run_date else ()
        sql = f"""
        SELECT r.id FROM opportunity_run r
        WHERE EXISTS(SELECT 1 FROM opportunity_hot_news h WHERE h.run_id = r.id)
        {where}
        ORDER BY r.run_at DESC, r.id DESC
        LIMIT 1
        """
    run_row = conn.execute(
        sql,
        params,
    ).fetchone()
    if not run_row:
        return []
    return _hot_news_for_run(conn, run_row[0], limit)


def _basename(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]


def _hot_news_for_run(conn, run_id: int, limit: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT news_rank AS rank, title, url, source, publish_time, heat
        FROM opportunity_hot_news
        WHERE run_id = ?
        ORDER BY heat DESC, news_rank ASC
        LIMIT ?
        """,
        (run_id, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def build_items(filter_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从 OpportunityDiscovery 的 filter_results 投影出可入库 items。

    字段口径与报告 signals sidecar 保持一致(chase 回退动量明细等),
    分析失败/降级股票也入库并带 degraded 标记。
    """
    out: List[Dict[str, Any]] = []
    for stock in filter_results or []:
        if not isinstance(stock, dict):
            continue
        sr = stock.get("scoring_result") or {}
        det = sr.get("details") or {}
        scores = sr.get("scores") or {}
        quant = det.get("quantitative") or {}
        tech = det.get("technical") or {}
        sector = det.get("sector") or {}
        pc = det.get("price_changes") or {}
        mom = det.get("momentum") or {}
        chase = (((sr.get("advanced_analysis") or {}).get("overall_score") or {})
                 .get("risk_metrics") or {}).get("chase_risk_score")
        if not chase:  # 0/None -> 回退动量明细(与评分逻辑一致)
            chase = mom.get("chase_risk_score")
        degraded = bool(
            sr.get("degraded") or quant.get("degraded")
            or quant.get("error") == "无历史数据"
        )
        # 标记因子/走势上下文统一走 outcome_markers 的提取器: 那里带降级守卫
        # (技术明细 error 时 tech_score 按缺失处理, 不会把"取数失败"读成"技术0分")。
        markers = outcome_markers.marker_payload(
            outcome_markers.extract_factors(stock),
            outcome_markers.extract_context(stock),
        )
        out.append({
            "code": str(stock.get("stock_code") or stock.get("code") or "").strip(),
            "name": stock.get("name") or stock.get("stock_name"),
            "total_score": _num(stock.get("final_score") or sr.get("total_score")),
            "rating": stock.get("rating") or sr.get("rating"),
            "degraded": degraded,
            "source": stock.get("source"),
            "source_detail": stock.get("source_detail"),
            "sector": (
                stock.get("sector")
                or stock.get("sector_name")
                or sector.get("sector_name")
                or sector.get("name")
            ),
            "sector_code": stock.get("sector_code") or sector.get("sector_code"),
            "sector_rank": _num(stock.get("sector_rank")),
            "sector_stock_rank": _num(stock.get("sector_stock_rank")),
            # 当日涨跌幅: 优先候选源的实时涨跌幅, 缺失时回退评分明细的 change_1d
            # (同一口径也写进 signals.day_change), 避免上游漏透传时整列为空。
            "change_pct": _first_num(stock.get("change_pct"), pc.get("change_1d")),
            "scores": scores,
            "signals": {
                "chase": _num(chase),
                "rsi": _num(tech.get("RSI")),
                "day_change": _num(pc.get("change_1d")),
                "change_3d": _num(pc.get("change_3d")),
                "change_5d": _num(pc.get("change_5d")),
                "sell_signals": _num(quant.get("sell_count")),
                "quant_score": _num(scores.get("quantitative")),
                "exclusions": sr.get("exclusion_flags") or [],
                # 入选后表现标记(2026-07-29 回溯): 只提示不改分, 见 analysis/outcome_markers.py
                "markers": markers.get("markers") or [],
                "constitution": markers.get("constitution") or {},
                "marker_description": markers.get("description") or "",
                "marker_narrative": markers.get("narrative") or "",
                "markers_version": markers.get("version"),
            },
        })
    return out


def list_runs(run_date: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """run 列表(含 item_count),整体按时间倒序;可按 YYYY-MM-DD 过滤单日。"""
    where = "WHERE r.run_date = ?" if run_date else ""
    params: tuple = (str(run_date), int(limit)) if run_date else (int(limit),)
    rows = get_conn().execute(
        f"""
        SELECT r.*, (SELECT COUNT(*) FROM opportunity_item i WHERE i.run_id = r.id) AS item_count
        FROM opportunity_run r
        {where}
        ORDER BY r.run_at DESC, r.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def latest_run() -> Optional[Dict[str, Any]]:
    runs = list_runs(limit=1)
    return runs[0] if runs else None


def run_for_report_file(report_file: str) -> Optional[Dict[str, Any]]:
    """Return the newest run that produced a specific dashboard report file."""
    name = str(report_file or "").strip()
    if not name:
        return None
    row = get_conn().execute(
        """
        SELECT r.*, (SELECT COUNT(*) FROM opportunity_item i WHERE i.run_id = r.id) AS item_count
        FROM opportunity_run r
        WHERE r.report_file = ?
        ORDER BY r.run_at DESC, r.id DESC
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    return dict(row) if row else None


def get_run(run_id: int) -> Optional[Dict[str, Any]]:
    """Return a single run by id (含 item_count),不存在返回 None。"""
    if run_id is None:
        return None
    try:
        rid = int(run_id)
    except (TypeError, ValueError):
        return None
    row = get_conn().execute(
        """
        SELECT r.*, (SELECT COUNT(*) FROM opportunity_item i WHERE i.run_id = r.id) AS item_count
        FROM opportunity_run r
        WHERE r.id = ?
        LIMIT 1
        """,
        (rid,),
    ).fetchone()
    return dict(row) if row else None


def items_for_run(run_id: int) -> List[Dict[str, Any]]:
    rows = get_conn().execute(
        "SELECT * FROM opportunity_item WHERE run_id = ? ORDER BY item_rank",
        (int(run_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def run_for_hot_sector_snapshot(snapshot_id) -> Optional[Dict[str, Any]]:
    """关联到某热门板块快照的最近一次挖掘 run(extra_json.hot_sector_snapshot_id 命中)。

    供导出时把逐股评分关联回快照成分股(见 webui.core.export_hot_sector_snapshot)。
    """
    if snapshot_id is None:
        return None
    try:
        sid = int(snapshot_id)
    except (TypeError, ValueError):
        return None
    row = get_conn().execute(
        """
        SELECT r.*, (SELECT COUNT(*) FROM opportunity_item i WHERE i.run_id = r.id) AS item_count
        FROM opportunity_run r
        WHERE CAST(json_extract(r.extra_json, '$.hot_sector_snapshot_id') AS INTEGER) = ?
        ORDER BY r.run_at DESC, r.id DESC
        LIMIT 1
        """,
        (sid,),
    ).fetchone()
    return dict(row) if row else None


def latest_item_for_code(code: str,
                         before_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """某只个股最近一次入选的 item 行(含 run_date/run_at)。从未入选 → None。

    供个股分析复用「入选后表现标记」: 直接读该股上次入选时已入库的标记,
    与机会挖掘报告口径完全一致, 不重算因子。

    ``before_date`` 形如 ``YYYY-MM-DD``, 给定时只回看**严格早于**该日的入选行。
    个股分析要的是「上一次入选 vs 当前」, 而挖掘几乎每个交易日都跑, 不排除掉
    当天那行就会拿今天跟今天比(见 StockAnalysisSuite._collect_outcome_markers)。
    """
    key = str(code or "").strip()
    if not key:
        return None
    where = "WHERE i.code = ?"
    params: List[Any] = [key]
    if before_date:
        where += " AND r.run_date < ?"
        params.append(str(before_date))
    row = get_conn().execute(
        f"""
        SELECT i.*, r.run_date, r.run_at, r.ruleset_version
        FROM opportunity_item i
        JOIN opportunity_run r ON r.id = i.run_id
        {where}
        ORDER BY r.run_at DESC, r.id DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return dict(row) if row else None


def stock_pool(
    limit: int = 300,
    since_date: Optional[str] = None,
    until_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """跨所有 run 聚合的「股票池」:每只曾入选股票一行,含入选次数、首次/最近入选
    时间、重复入选的日期列表、最佳/平均评分等。

    - ``selections``:该股出现过的 run 次数(PK 为 (run_id, code),每 run 至多一行)。
    - ``distinct_days``:去重后的入选天数(衡量「重复入选」跨越多少个交易日)。
    - ``days_csv``:去重后的入选日期(逗号分隔,升序),前端展开为重复入选时间线。
    - 名称/评级/板块/分数等「最新值」取该股最近一次 run 的行(window rn=1)。
    - 资金流向取自 moneyflow_dc 最近一个交易日:主力净流入/散户流入/总流入/资金日期。
    - ``avg_change_pct``/``last_change_pct``:入选当日涨跌幅的均值/最新值。
    - ``post_select_return_pct``:入选后涨幅,连带 ``entry_date``/``entry_open``/
      ``price_date``/``price_source``(价格口径见 data_store.opportunity_prices)。
    ``since_date``/``until_date`` 形如 ``YYYY-MM-DD``,闭区间过滤 run:只统计
    ``since_date``(含)之后、``until_date``(含)之前的 run;二者均可单独使用。
    区间外的入选记录完全不参与聚合(次数/日期/最新值/首次入选均按区间内口径)。
    """
    conds = []
    cond_params: List[str] = []
    if since_date:
        conds.append("r.run_date >= ?")
        cond_params.append(str(since_date))
    if until_date:
        conds.append("r.run_date <= ?")
        cond_params.append(str(until_date))
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    params: tuple = (*cond_params, int(limit))
    rows = get_conn().execute(
        f"""
        WITH joined AS (
          SELECT i.code, i.name, i.rating, i.sector, i.sector_code,
                 i.total_score, i.change_pct, i.degraded,
                 r.run_at, r.run_date,
                 ROW_NUMBER() OVER (
                   PARTITION BY i.code ORDER BY r.run_at DESC, r.id DESC
                 ) AS rn
          FROM opportunity_item i
          JOIN opportunity_run r ON r.id = i.run_id
          {where}
        ),
        first_select AS (
          -- 每只股票的首次入选交易日(用于「入选后涨幅」的买入基准日)
          SELECT code, MIN(run_date) AS first_date FROM joined GROUP BY code
        )
        SELECT
          j.code,
          COUNT(*)                       AS selections,
          COUNT(DISTINCT j.run_date)       AS distinct_days,
          MIN(j.run_at)                    AS first_seen,
          MAX(j.run_at)                    AS last_seen,
          MAX(j.total_score)               AS best_score,
          AVG(j.total_score)               AS avg_score,
          AVG(j.change_pct)                AS avg_change_pct,
          SUM(j.degraded)                  AS degraded_count,
          GROUP_CONCAT(DISTINCT j.run_date) AS days_csv,
          MAX(CASE WHEN j.rn=1 THEN j.name END)        AS name,
          MAX(CASE WHEN j.rn=1 THEN j.rating END)      AS last_rating,
          MAX(CASE WHEN j.rn=1 THEN j.sector END)      AS last_sector,
          MAX(CASE WHEN j.rn=1 THEN j.sector_code END) AS last_sector_code,
          MAX(CASE WHEN j.rn=1 THEN j.total_score END) AS last_score,
          MAX(CASE WHEN j.rn=1 THEN j.change_pct END)  AS last_change_pct,
          fs.first_date
        FROM joined j
        LEFT JOIN first_select fs ON fs.code = j.code
        GROUP BY j.code
        ORDER BY distinct_days DESC, last_seen DESC, best_score DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        days = [s for s in str(d.pop("days_csv", "") or "").split(",") if s]
        d["days"] = sorted(days)
        out.append(d)
    # 资金流向 / 价格都按「先聚合再补维度」的方式在 Python 里合并:两者都是
    # 每只股票一行的旁挂数据,放进 SQL 做 LEFT JOIN 会让 SQLite 对上面这个
    # 分组结果做嵌套循环(实测整条查询 5.8s,拆出来后 0.4s)。
    flows = _latest_moneyflow({d["code"] for d in out})
    for d in out:
        d.update(flows.get(d["code"]) or _EMPTY_FLOW)
    # 入选后涨幅: (最新收盘 - 首次入选次日开盘) / 次日开盘 * 100,价格面见
    # data_store.opportunity_prices(全市场日线优先,本地 ohlcv 兜底,同股同源)。
    prices = opportunity_prices.post_selection_returns(
        {d["code"]: d.get("first_date") for d in out if d.get("first_date")}
    )
    for d in out:
        px = prices.get(d.get("code")) or {}
        d["post_select_return_pct"] = px.get("post_select_return_pct")
        d["entry_date"] = px.get("entry_date")
        d["entry_open"] = px.get("entry_open")
        d["price_date"] = px.get("price_date")
        d["price_source"] = px.get("price_source")
    return out


_EMPTY_FLOW: Dict[str, Any] = {
    "flow_date": None, "flow_unit": None,
    "main_net_inflow": None, "retail_flow": None, "total_inflow": None,
    "main_net_inflow_text": None, "retail_flow_text": None, "total_inflow_text": None,
}


def _latest_moneyflow(codes: Any) -> Dict[str, Dict[str, Any]]:
    """``{code: 该股最近一个交易日的资金流向}``(只返回 ``codes`` 里的股票)。

    取数走 (ts_code, MAX(trade_date)) 自连接 + idx_mf_code_date 索引;此前的
    ROW_NUMBER() 窗口要把 110 万行全排一遍(实测 4.6s),换法后 0.2s。
    """
    wanted = {str(c) for c in (codes or set())}
    if not wanted:
        return {}
    rows = get_conn().execute(
        """
        SELECT SUBSTR(mf.ts_code, 1, 6) AS code,
               mf.trade_date    AS flow_date,
               mf.net_amount    AS main_net_inflow,
               mf.buy_sm_amount AS retail_flow,
               COALESCE(mf.buy_elg_amount,0) + COALESCE(mf.buy_lg_amount,0)
                 + COALESCE(mf.buy_md_amount,0) + COALESCE(mf.buy_sm_amount,0) AS total_inflow,
               mf.amount_unit   AS flow_unit
        FROM moneyflow_dc mf
        JOIN (
          SELECT ts_code, MAX(trade_date) AS d FROM moneyflow_dc
          WHERE top_n = 0        -- 资金榜全市场快照哨兵(SNAPSHOT_TOP_N);
                                 -- top_n=1 是历史误用、几乎无行,会让资金流向列恒为空
          GROUP BY ts_code
        ) m ON m.ts_code = mf.ts_code AND m.d = mf.trade_date
        WHERE mf.top_n = 0
        """
    ).fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        d = dict(row)
        code = str(d.pop("code"))
        if code not in wanted:
            continue
        # Tushare moneyflow_dc 原始单位为万元,统一格式化为 +N.MM万
        scale = 1.0 if "万" in str(d.get("flow_unit") or "") else 0.0001
        for key in ("main_net_inflow", "retail_flow", "total_inflow"):
            val = _num(d.get(key))
            d[f"{key}_text"] = f"{val * scale:+.2f}万" if val is not None else None
        out[code] = d
    return out


def runs_by_day(limit: int = 30) -> List[Dict[str, Any]]:
    """按天聚合:每日 run 次数与最近一次 run 时间,日期倒序。"""
    rows = get_conn().execute(
        """
        SELECT run_date, COUNT(*) AS run_count, MAX(run_at) AS last_run_at
        FROM opportunity_run
        GROUP BY run_date
        ORDER BY run_date DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [dict(row) for row in rows]


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _first_num(*values) -> Optional[float]:
    """返回第一个可转成 float 的值(跳过 None/空串/不可转)。"""
    for v in values:
        num = _num(v)
        if num is not None:
            return num
    return None


def _json_or_none(v) -> Optional[str]:
    if v is None:
        return None
    try:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
