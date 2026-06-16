"""Suite-enriched opportunity workbook builder.

Pure assembly + declarative style specs for the「投资机会画布」Excel export. This
module never touches the network or the filesystem: it takes a canvas dict plus an
injectable ``suite_fetcher`` (in production ``STOCK_SUITE_SERVICE.get_suite``) and
returns a list of ``SheetSpec`` dicts together with a coverage summary. Keeping it
pure makes every derivation (建议操作 / 风险指标解析 / 关键风险) and every degradation
path (fetch raises / over-budget / over-limit) directly unit-testable with a fake
fetcher and a fake clock.

Design: docs/superpowers/specs/2026-06-16-opportunity-excel-refinement-design.md
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

# --------------------------------------------------------------------------- helpers


def _num(value: Any) -> float | None:
    """Coerce to float, returning None for bools/None/garbage (never raises)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _g(value: float) -> str:
    """Compact numeric formatting: 85.0 -> '85', 22.5 -> '22.5'."""
    return f"{value:g}"


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Safe nested dict access: _get(suite, 'overview', 'radar') -> value or default."""
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def _analysis_value(node: dict, label: str) -> Any:
    """Return the value of a report analysis section by its label, or None."""
    for item in node.get("analysis") or []:
        if isinstance(item, dict) and item.get("label") == label:
            return item.get("value")
    return None


def _key_signal_value(suite: dict | None, label: str) -> Any:
    """Return overview.key_signals[label==label].value, or None."""
    for ks in _get(suite, "overview", "key_signals") or []:
        if isinstance(ks, dict) and ks.get("label") == label:
            return ks.get("value")
    return None


def _change_value(node: dict, signal_key: str, cn_label: str) -> float | None:
    """涨幅取数：run-store 数值信号优先，缺失时回退解析「涨幅」文本段（spec §4.1）。"""
    sig = node.get("signals") or {}
    v = _num(sig.get(signal_key))
    if v is not None:
        return v
    text = str(_analysis_value(node, "涨幅") or "")
    m = re.search(rf"{cn_label}\s*[:：]\s*([+-]?\d+(?:\.\d+)?)%?", text)
    return float(m.group(1)) if m else None


def _one_line_logic(node: dict) -> str:
    """First sentence of「入选原因」, falling back to「概览」."""
    raw = _analysis_value(node, "入选原因") or _analysis_value(node, "概览") or ""
    text = str(raw).strip()
    if not text:
        return ""
    first = re.split(r"[。\n]", text)[0].strip()
    return first or text


# --------------------------------------------------------------------- derivations


# rating buckets that are eligible for a 买入 recommendation
_BUY_RATINGS = {"S", "A+", "A"}
_HIGH_CHASE = 80.0


def derive_action(node: dict, suite: dict | None) -> str:
    """Derive 买入 / 观望 / 回避 (spec §5.1). Degrades gracefully when suite is None."""
    rating = (node.get("rating") or "").strip()
    degraded = bool(node.get("degraded"))
    score = _num(node.get("score"))
    sig = node.get("signals") or {}
    chase = _num(sig.get("chase"))
    sell = _num(sig.get("sell_signals"))

    # rule 1 — hard avoid
    if rating == "C" or degraded or (score is not None and score < 60):
        return "回避"

    # suite-less fallback: rating + chase only
    if not isinstance(suite, dict):
        if rating in _BUY_RATINGS and not (chase is not None and chase >= _HIGH_CHASE):
            return "买入"
        return "观望"

    posture = _get(suite, "quant_matrix", "current_posture") or ""
    bullish = _num(_get(suite, "overview", "scenario_probability", "bullish")) or 0.0
    bearish = _num(_get(suite, "overview", "scenario_probability", "bearish")) or 0.0

    # rule 2 — watch
    if (
        bearish > bullish
        or posture in ("强势空头", "震荡偏空")
        or (chase is not None and chase >= _HIGH_CHASE)
        or (sell is not None and sell >= 3)
    ):
        return "观望"

    # rule 3 — buy
    if (
        rating in _BUY_RATINGS
        and posture in ("强势多头", "震荡偏多")
        and bullish >= bearish
    ):
        return "买入"

    # rule 4 — default watch
    return "观望"


# regex for the three risk metrics carried as free text in risk_control.deep_signals
_NUM_PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_NUM_ANY = re.compile(r"-?\d+(?:\.\d+)?")


def parse_risk_metrics(deep_signals: list | None) -> dict:
    """Extract 最大回撤(当前)/年化波动率/夏普 from risk_control.deep_signals text.

    Tolerant of missing / garbage entries (returns None per field) — never raises.
    """
    out: dict[str, float | None] = {
        "max_drawdown_pct": None,
        "volatility_pct": None,
        "sharpe": None,
    }
    for item in deep_signals or []:
        text = item.get("text") if isinstance(item, dict) else item
        text = str(text or "")
        if out["max_drawdown_pct"] is None and "当前" in text and "回撤" in text:
            m = _NUM_PCT.search(text)
            if m:
                out["max_drawdown_pct"] = float(m.group(1))
        if out["volatility_pct"] is None and "波动率" in text:
            m = _NUM_PCT.search(text)
            if m:
                out["volatility_pct"] = float(m.group(1))
        if out["sharpe"] is None and "夏普" in text:
            nums = _NUM_ANY.findall(text)
            if nums:
                # the value trails the "(60日年化)" qualifier — take the last number
                out["sharpe"] = float(nums[-1])
    return out


def signal_label(value: Any) -> str:
    """Map a quant model signal code to a label: 1->买入, -1->卖出, else 观望."""
    if value == 1:
        return "买入"
    if value == -1:
        return "卖出"
    return "观望"


def derive_key_risks(node: dict, suite: dict | None) -> str:
    """Compose a 顿号-joined risk string (spec §5.3): signal thresholds + report penalties.

    Dedup, max 5 entries. Signal-derived risks come first so they survive truncation.
    """
    risks: list[str] = []
    sig = node.get("signals") or {}
    chase = _num(sig.get("chase"))
    rsi = _num(sig.get("rsi"))
    sell = _num(sig.get("sell_signals"))
    chg5 = _num(sig.get("change_5d"))

    if chase is not None and chase >= 60:
        risks.append(f"追高风险偏高({_g(chase)})")
    if rsi is not None and rsi >= 80:
        risks.append(f"RSI超买({_g(rsi)})")
    if sell is not None and sell >= 2:
        risks.append(f"卖出信号{int(sell)}个")
    if chg5 is not None and chg5 >= 20:
        risks.append(f"5日涨幅偏高({_g(chg5)}%)")

    if isinstance(suite, dict):
        dd = parse_risk_metrics(_get(suite, "risk_control", "deep_signals") or []).get(
            "max_drawdown_pct"
        )
        if dd is not None and dd <= -15:
            risks.append(f"最大回撤{_g(dd)}%")

    # report 关键加减分 penalty clauses
    kdj = _analysis_value(node, "关键加减分")
    if kdj:
        for clause in re.split(r"[；;\n]", str(kdj)):
            clause = clause.strip()
            if clause and any(k in clause for k in ("罚", "扣", "风险", "回调", "过热")):
                # keep the descriptive head, drop the trailing :±N score
                head = re.split(r"[:：]", clause)[0].strip()
                if head:
                    risks.append(head)

    seen: list[str] = []
    for r in risks:
        if r not in seen:
            seen.append(r)
    return "、".join(seen[:5])


def _data_completeness(suite: dict | None) -> str:
    """Summarise how much of the suite was recomputed (spec §4.1 数据完整度)."""
    if not isinstance(suite, dict):
        return "仅报告基线"
    sections = {
        "量化": _get(suite, "quant_matrix", "data_status"),
        "筹码": _get(suite, "chip_control", "data_status"),
        "主力": _get(suite, "main_force_deep", "data_status"),
        "机构": _get(suite, "institutional_holdings", "data_status"),
    }
    missing = [name for name, status in sections.items() if status in ("stale", "unavailable", None)]
    if not missing:
        return "完整"
    return f"部分(缺{''.join(missing)})"


def _dragon_hit(dragon: dict | None) -> str:
    """是 if there is any meaningful 龙虎榜 footprint, else 否."""
    if not isinstance(dragon, dict):
        return "否"
    if (
        _num(dragon.get("quant_seat_appearances"))
        or _num(dragon.get("net_inst_buy_30d"))
        or (dragon.get("history_90d") or [])
        or (dragon.get("highlight_seats") or [])
    ):
        return "是"
    return "否"


# ------------------------------------------------------------------ sheet builders

OVERVIEW_COLUMNS = [
    "排名", "代码", "名称", "所属板块", "综合评分", "评级", "建议操作", "一句话逻辑",
    "当前态势", "主力阶段", "大盘周期", "仓位上限", "现价", "止损价", "止损幅度%",
    "第一目标价", "盈亏比", "预期收益%", "最大回撤%", "年化波动率%", "夏普",
    "关键风险", "当日涨幅", "3日涨幅", "5日涨幅", "数据完整度",
]

RADAR_COLUMNS = [
    "代码", "名称", "主力阶段分", "主力阶段标签", "市场周期分", "量价博弈分",
    "筹码结构分", "业绩预期分", "控盘度", "量化活跃度", "看多%", "看空%", "震荡%",
    "可信度", "量能质量", "筹码集中度", "技术趋势",
]

RISK_PLAN_COLUMNS = ["代码", "名称", "计划", "档位", "价格", "仓位/卖出%", "说明"]

QUANT_MATRIX_COLUMNS = ["代码", "名称", "模型", "周期", "信号"]

CHIP_INST_COLUMNS = [
    "代码", "名称", "控盘度", "控盘标签", "90%集中度", "70%集中度", "龙虎榜命中",
    "龙虎榜最近日期", "机构净买(30日)", "陆股通持股", "陆股通持股占比%",
    "十大流通股东合计%", "股东户数",
]

GLOSSARY_COLUMNS = ["指标", "白话含义", "怎么读", "数据来源"]


def _overview_row(node: dict, suite: dict | None) -> dict:
    metrics = parse_risk_metrics(_get(suite, "risk_control", "deep_signals") or [])
    scaled = _get(suite, "risk_control", "scaled_entry") or []
    tp = _get(suite, "risk_control", "tiered_take_profit") or []
    stop = _get(suite, "risk_control", "execution_plan", "stop_loss") or {}
    rr = _get(suite, "risk_control", "execution_plan", "risk_reward") or {}
    return {
        "排名": node.get("score_rank") or node.get("report_rank"),
        "代码": node.get("stock_code"),
        "名称": node.get("stock_name"),
        "所属板块": node.get("sector"),
        "综合评分": _num(node.get("score")),
        "评级": node.get("rating"),
        "建议操作": derive_action(node, suite),
        "一句话逻辑": _one_line_logic(node),
        "当前态势": _get(suite, "quant_matrix", "current_posture"),
        "主力阶段": _get(suite, "overview", "radar", "main_force_phase", "label"),
        "大盘周期": _key_signal_value(suite, "大盘周期"),
        "仓位上限": _key_signal_value(suite, "仓位上限"),
        "现价": (scaled[0].get("price") if scaled else None),
        "止损价": stop.get("price"),
        "止损幅度%": stop.get("drop_pct"),
        "第一目标价": (tp[0].get("price") if tp else None),
        "盈亏比": rr.get("ratio"),
        "预期收益%": rr.get("expected_return_pct"),
        "最大回撤%": metrics["max_drawdown_pct"],
        "年化波动率%": metrics["volatility_pct"],
        "夏普": metrics["sharpe"],
        "关键风险": derive_key_risks(node, suite),
        "当日涨幅": _change_value(node, "day_change", "当日"),
        "3日涨幅": _change_value(node, "change_3d", "3日"),
        "5日涨幅": _change_value(node, "change_5d", "5日"),
        "数据完整度": _data_completeness(suite),
    }


def _radar_row(node: dict, suite: dict | None) -> dict:
    radar = _get(suite, "overview", "radar") or {}
    scen = _get(suite, "overview", "scenario_probability") or {}

    def _score(key: str) -> Any:
        return _get(radar, key, "score")

    return {
        "代码": node.get("stock_code"),
        "名称": node.get("stock_name"),
        "主力阶段分": _score("main_force_phase"),
        "主力阶段标签": _get(radar, "main_force_phase", "label"),
        "市场周期分": _score("market_cycle"),
        "量价博弈分": _score("volume_price_game"),
        "筹码结构分": _score("chip_structure"),
        "业绩预期分": _score("performance"),
        "控盘度": _score("control_degree"),
        "量化活跃度": _score("quant_activity"),
        "看多%": scen.get("bullish"),
        "看空%": scen.get("bearish"),
        "震荡%": scen.get("sideways"),
        "可信度": _key_signal_value(suite, "可信度"),
        "量能质量": _key_signal_value(suite, "量能质量"),
        "筹码集中度": _key_signal_value(suite, "筹码集中度"),
        "技术趋势": _key_signal_value(suite, "技术趋势"),
    }


def _risk_plan_rows(node: dict, suite: dict | None) -> list[dict]:
    code = node.get("stock_code")
    name = node.get("stock_name")
    rc = _get(suite, "risk_control") if isinstance(suite, dict) else None

    def _base(plan: str, tier: Any, price: Any, pct: Any, note: Any) -> dict:
        return {"代码": code, "名称": name, "计划": plan, "档位": tier,
                "价格": price, "仓位/卖出%": pct, "说明": note}

    if not isinstance(rc, dict) or rc.get("available") is False:
        return [_base("数据不足", "—", None, None, "复算失败或风控数据不足")]

    rows: list[dict] = []
    for e in rc.get("scaled_entry") or []:
        rows.append(_base("分批建仓", e.get("label"), e.get("price"), e.get("position_pct"), ""))
    for t in rc.get("tiered_take_profit") or []:
        rows.append(_base("分批止盈", t.get("label"), t.get("price"), t.get("sell_pct"), ""))
    stop = _get(rc, "execution_plan", "stop_loss") or {}
    if stop:
        drop = stop.get("drop_pct")
        note = stop.get("basis") or ""
        if drop is not None:
            note = f"{note}（止损幅度 {_g(_num(drop) or 0)}%）" if note else f"止损幅度 {_g(_num(drop) or 0)}%"
        rows.append(_base("止损", "止损", stop.get("price"), None, note))
    if not rows:
        return [_base("数据不足", "—", None, None, "风控数据不足")]
    return rows


def _quant_matrix_rows(node: dict, suite: dict | None) -> list[dict]:
    code = node.get("stock_code")
    name = node.get("stock_name")
    qm = _get(suite, "quant_matrix") if isinstance(suite, dict) else None
    matrix = qm.get("signals_matrix") if isinstance(qm, dict) else None
    status = qm.get("data_status") if isinstance(qm, dict) else None

    if not matrix or status == "unavailable":
        return [{"代码": code, "名称": name, "模型": "—", "周期": "",
                 "信号": "数据不足(M4: OHLCV 不足或加载失败)"}]

    rows: list[dict] = []
    for m in matrix:
        rows.append({
            "代码": code, "名称": name,
            "模型": m.get("model"),
            "周期": m.get("period"),
            "信号": signal_label(m.get("signal")),
        })
    return rows


def _chip_inst_row(node: dict, suite: dict | None) -> dict:
    chip = _get(suite, "chip_control") or {}
    dragon = _get(suite, "main_force_deep", "dragon_tiger") or {}
    hsgt = _get(suite, "main_force_deep", "hsgt") or {}
    hsgt_latest = hsgt.get("latest") or {}
    top10 = _get(suite, "institutional_holdings", "top10_floatholders") or {}
    holder = _get(suite, "institutional_holdings", "holder_number") or {}
    return {
        "代码": node.get("stock_code"),
        "名称": node.get("stock_name"),
        "控盘度": chip.get("control_degree"),
        "控盘标签": chip.get("control_label"),
        "90%集中度": chip.get("concentration_90"),
        "70%集中度": chip.get("concentration_70"),
        "龙虎榜命中": _dragon_hit(dragon) if isinstance(suite, dict) else None,
        "龙虎榜最近日期": hsgt_latest.get("trade_date"),
        "机构净买(30日)": dragon.get("net_inst_buy_30d"),
        "陆股通持股": hsgt_latest.get("hold_vol"),
        "陆股通持股占比%": hsgt_latest.get("hold_ratio"),
        "十大流通股东合计%": top10.get("concentration"),
        "股东户数": holder.get("latest_num"),
    }


def _glossary_rows() -> list[dict]:
    g = [
        ("综合评分", "0-100 的机会综合得分", "越高越好；≥85 顶级", "机会挖掘评分引擎"),
        ("评级", "S/A/B/C 四档", "S≥85 A≥78 B≥70 C<70", "评分阈值"),
        ("建议操作", "买入/观望/回避（自动派生）",
         "回避=评级C或降级或评分<60；观望=偏空/追高≥80/卖出≥3；买入=评级≥A且偏多且看多≥看空", "派生规则 §5.1"),
        ("主力阶段", "主力资金所处阶段", "强势主导>中性>派发", "个股分析雷达"),
        ("市场周期", "大盘所处周期", "上行>震荡>下行", "个股分析雷达"),
        ("量价博弈", "多空力量对比", "多头占优更好", "个股分析雷达"),
        ("筹码结构", "筹码分布健康度", "集中且低位更好", "个股分析雷达"),
        ("业绩预期", "基本面预期分", "越高越好", "个股分析雷达"),
        ("控盘度", "主力控盘程度(0-100)", "适度控盘(50-70)较健康，过高有风险", "筹码分布"),
        ("情景概率", "看多/看空/震荡 %", "看多>看空更积极", "30 量化模型多空票数归一"),
        ("当前态势", "量化矩阵综合态势", "强势多头>震荡偏多>震荡>偏空", "量化模型矩阵"),
        ("RSI", "相对强弱指标(0-100)", "≥80 超买偏热，40-50 黄金区", "技术指标"),
        ("追高风险", "追高程度评分", "≥80 高危红线，≥60 偏高", "评分引擎"),
        ("卖出信号", "看空模型计数", "≥3 偏空，0 最佳", "量化模型"),
        ("量化总分", "30 模型综合分", "<50 分歧或>90 过度共识均需留意", "量化模型"),
        ("盈亏比", "潜在收益:潜在亏损", "≥1:2 较优", "风控执行计划"),
        ("预期收益%", "至第一目标的预期涨幅", "越高越好", "风控执行计划"),
        ("最大回撤", "区间内最大跌幅%", "≤-20% 红线，≤-15% 警示", "风控 deep_signals"),
        ("年化波动率%", "60 日年化波动", "越低越稳", "风控 deep_signals"),
        ("夏普比率", "风险调整后收益", "越高越好；>1 较优", "风控 deep_signals"),
        ("仓位上限", "建议最大持仓比例", "据大盘周期与个股风险给出", "个股分析关键信号"),
        ("龙虎榜", "是否上榜及机构席位", "机构净买为正偏积极", "龙虎榜数据"),
        ("陆股通", "北向资金持股", "占比上升偏积极", "陆股通数据"),
        ("集中度(90/70%)", "90%/70% 筹码成本集中度", "越低越集中，换手风险小", "筹码分布"),
        ("降级标记", "该股复算所用数据是否降级", "降级时分数封顶，仅供参考", "评分引擎"),
        ("数据不足", "该项数据离线/限流未取到", "非报错，与个股分析页一致", "—"),
        ("颜色图例", "红涨绿跌(涨幅)；评分蓝深→灰浅；风险越危险越橙红；建议买入红/观望黄/回避灰",
         "见各列底色", "样式规则 §6"),
    ]
    return [{"指标": k, "白话含义": v, "怎么读": r, "数据来源": s} for k, v, r, s in g]


# ------------------------------------------------------------------- style specs


def _overview_style() -> dict:
    return {
        # freeze header row + 排名/代码/名称 (cols A,B,C)
        "freeze_panes": "D2",
        "header_bold": True,
        "percent_columns": ["止损幅度%", "预期收益%", "最大回撤%", "年化波动率%",
                            "当日涨幅", "3日涨幅", "5日涨幅"],
        "price_columns": ["现价", "止损价", "第一目标价"],
        "color_rules": [
            {"column": "当日涨幅", "kind": "updown"},
            {"column": "3日涨幅", "kind": "updown"},
            {"column": "5日涨幅", "kind": "updown"},
            {"column": "综合评分", "kind": "score"},
            {"column": "建议操作", "kind": "action"},
            {"column": "最大回撤%", "kind": "risk", "metric": "drawdown"},
        ],
    }


def _radar_style() -> dict:
    return {
        "freeze_panes": "C2",
        "header_bold": True,
        "percent_columns": ["看多%", "看空%", "震荡%"],
        "color_rules": [
            {"column": "主力阶段分", "kind": "score"},
            {"column": "控盘度", "kind": "score"},
            {"column": "看多%", "kind": "score"},
        ],
    }


def _risk_plan_style() -> dict:
    return {
        "freeze_panes": "C2",
        "header_bold": True,
        "price_columns": ["价格"],
        "color_rules": [{"column": "计划", "kind": "action"}],
    }


def _quant_matrix_style() -> dict:
    return {
        "freeze_panes": "C2",
        "header_bold": True,
        "color_rules": [{"column": "信号", "kind": "action"}],
    }


def _chip_inst_style() -> dict:
    return {
        "freeze_panes": "C2",
        "header_bold": True,
        "percent_columns": ["90%集中度", "70%集中度", "陆股通持股占比%", "十大流通股东合计%"],
        "color_rules": [{"column": "控盘度", "kind": "score"}],
    }


def _glossary_style() -> dict:
    return {"freeze_panes": "A2", "header_bold": True, "color_rules": []}


# ----------------------------------------------------------------- public surface


def build_suite_sheets(
    canvas: dict,
    *,
    suite_fetcher: Callable[[str], dict] | None,
    suite_limit: int = 30,
    time_budget_sec: float = 150.0,
    clock: Callable[[], float] | None = None,
) -> tuple[list[dict], dict]:
    """Build the 6 suite-enriched sheets + a coverage summary.

    Per-stock best-effort: ``suite_fetcher`` raising / returning ``{success: False}``,
    exceeding ``suite_limit`` (by index), or exceeding ``time_budget_sec`` all degrade
    that stock to the report-text baseline (suite=None) instead of crashing the export.

    Returns ``(sheets, coverage)`` where each sheet is
    ``{name, columns, rows, style}`` and coverage carries the per-stock outcome counts.
    """
    clock_fn = clock or time.monotonic
    nodes = [n for n in (canvas.get("nodes") or []) if n.get("type") == "stock"]

    coverage = {
        "total_stocks": len(nodes),
        "succeeded": 0,
        "failed": 0,
        "skipped_over_budget": 0,
        "skipped_over_limit": 0,
    }

    start = clock_fn()
    enriched: list[tuple[dict, dict | None]] = []
    for idx, node in enumerate(nodes):
        suite: dict | None = None
        if suite_fetcher is None:
            pass  # pure baseline path
        elif idx >= suite_limit:
            coverage["skipped_over_limit"] += 1
        elif (clock_fn() - start) > time_budget_sec:
            coverage["skipped_over_budget"] += 1
        else:
            try:
                result = suite_fetcher(node.get("stock_code"))
                if isinstance(result, dict) and result.get("success") is not False:
                    suite = result
                    coverage["succeeded"] += 1
                else:
                    coverage["failed"] += 1
            except Exception:
                coverage["failed"] += 1
        enriched.append((node, suite))

    overview_rows = [_overview_row(n, s) for n, s in enriched]
    radar_rows = [_radar_row(n, s) for n, s in enriched]
    risk_rows: list[dict] = []
    quant_rows: list[dict] = []
    chip_rows = [_chip_inst_row(n, s) for n, s in enriched]
    for n, s in enriched:
        risk_rows.extend(_risk_plan_rows(n, s))
        quant_rows.extend(_quant_matrix_rows(n, s))

    sheets = [
        {"name": "投资速览", "columns": OVERVIEW_COLUMNS, "rows": overview_rows,
         "style": _overview_style()},
        {"name": "评分雷达", "columns": RADAR_COLUMNS, "rows": radar_rows,
         "style": _radar_style()},
        {"name": "风控执行计划", "columns": RISK_PLAN_COLUMNS, "rows": risk_rows,
         "style": _risk_plan_style()},
        {"name": "量化模型矩阵", "columns": QUANT_MATRIX_COLUMNS, "rows": quant_rows,
         "style": _quant_matrix_style()},
        {"name": "筹码与机构", "columns": CHIP_INST_COLUMNS, "rows": chip_rows,
         "style": _chip_inst_style()},
        {"name": "术语表与图例", "columns": GLOSSARY_COLUMNS, "rows": _glossary_rows(),
         "style": _glossary_style()},
    ]
    return sheets, coverage
