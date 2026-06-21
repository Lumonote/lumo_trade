"""投资机会挖掘结果仓库 —— 按天存每次 run 的元信息 + 全量评分明细。

桌面端 job(webui/core._run_opportunity_job) 与 quick_start CLI 都经
``OpportunityDiscovery.run`` 落库,故两侧产出同表可比对。
``ruleset_version``/``config_hash`` 记录该次 run 实际生效的评分规则版本与
运行时参数配置,用于解释「不同时间/不同端分数不一致」。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

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
                    limit: int = 10) -> List[Dict[str, Any]]:
    """读取某天(或全局)最近一次有热点的 run 的前 limit 条热点新闻。

    run_date 非空 → 该日期 run_at DESC 最近一次有热点的 run;为空 → 全局最近一次。
    返回 ``{rank, title, url, source, publish_time, heat}``,按 heat 降序;无数据 → []。
    """
    conn = get_conn()
    where = "AND r.run_date = ?" if run_date else ""
    params: tuple = (str(run_date),) if run_date else ()
    run_row = conn.execute(
        f"""
        SELECT r.id FROM opportunity_run r
        WHERE EXISTS(SELECT 1 FROM opportunity_hot_news h WHERE h.run_id = r.id)
        {where}
        ORDER BY r.run_at DESC, r.id DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if not run_row:
        return []
    run_id = run_row[0]
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
            "change_pct": _num(stock.get("change_pct")),
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


def stock_pool(limit: int = 300, since_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """跨所有 run 聚合的「股票池」:每只曾入选股票一行,含入选次数、首次/最近入选
    时间、重复入选的日期列表、最佳/平均评分等。

    - ``selections``:该股出现过的 run 次数(PK 为 (run_id, code),每 run 至多一行)。
    - ``distinct_days``:去重后的入选天数(衡量「重复入选」跨越多少个交易日)。
    - ``days_csv``:去重后的入选日期(逗号分隔,升序),前端展开为重复入选时间线。
    - 名称/评级/板块/分数等「最新值」取该股最近一次 run 的行(window rn=1)。
    ``since_date`` 形如 ``YYYY-MM-DD``,只统计该日期(含)之后的 run。
    """
    where = "WHERE r.run_date >= ?" if since_date else ""
    params: tuple = (str(since_date), int(limit)) if since_date else (int(limit),)
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
        )
        SELECT
          code,
          COUNT(*)                       AS selections,
          COUNT(DISTINCT run_date)       AS distinct_days,
          MIN(run_at)                    AS first_seen,
          MAX(run_at)                    AS last_seen,
          MAX(total_score)               AS best_score,
          AVG(total_score)               AS avg_score,
          AVG(change_pct)                AS avg_change_pct,
          SUM(degraded)                  AS degraded_count,
          GROUP_CONCAT(DISTINCT run_date) AS days_csv,
          MAX(CASE WHEN rn=1 THEN name END)        AS name,
          MAX(CASE WHEN rn=1 THEN rating END)      AS last_rating,
          MAX(CASE WHEN rn=1 THEN sector END)      AS last_sector,
          MAX(CASE WHEN rn=1 THEN sector_code END) AS last_sector_code,
          MAX(CASE WHEN rn=1 THEN total_score END) AS last_score,
          MAX(CASE WHEN rn=1 THEN change_pct END)  AS last_change_pct
        FROM joined
        GROUP BY code
        ORDER BY selections DESC, last_seen DESC, best_score DESC
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


def _json_or_none(v) -> Optional[str]:
    if v is None:
        return None
    try:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
