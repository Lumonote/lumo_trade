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


def save_run(meta: Dict[str, Any], items: List[Dict[str, Any]]) -> int:
    """落库一次挖掘 run。返回 run_id。

    items 形如 build_items() 的输出;按 total_score 降序写入并赋 item_rank,
    同 run 内重复 code 保留先到(高分)行。
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
            item.get("source"), _num(item.get("change_pct")),
            _json_or_none(item.get("scores")),
            _json_or_none(item.get("signals")),
        ))
    conn.executemany(
        """
        INSERT INTO opportunity_item(
          run_id, code, name, item_rank, total_score, rating,
          degraded, source, change_pct, scores_json, signals_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(run_id, code) DO NOTHING
        """,
        rows,
    )
    return run_id


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


def items_for_run(run_id: int) -> List[Dict[str, Any]]:
    rows = get_conn().execute(
        "SELECT * FROM opportunity_item WHERE run_id = ? ORDER BY item_rank",
        (int(run_id),),
    ).fetchall()
    return [dict(row) for row in rows]


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
