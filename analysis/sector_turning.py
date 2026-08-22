# -*- coding: utf-8 -*-
"""板块拐点判据 —— 纯函数,输入板块日序列,输出已触发 / 临界观察。

⚠️ 判据是否上线由 ``scripts/validate_turning_rules.py`` 的历史胜率校验决定
(spec §8):未过门槛的判据由调用方通过 ``enabled`` 关闭。本模块只负责
「判据实现符合定义」,不对有效性背书。

⚠️ 盘中(provisional)数据上算出的信号会随当日资金流变化跳变,不享有历史
胜率背书,展示层必须分开标注(spec §5)。

序列行由 ``analysis/sector_series.py`` 产出,键见该模块 ``_COLUMNS``。
"""
from __future__ import annotations

from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

RULE_IDS: Tuple[str, ...] = ("T1", "T2", "T3", "T4", "T5")

RULE_LABELS: Dict[str, str] = {
    "T1": "资金反转",
    "T2": "背离修复",
    "T3": "广度突破",
    "T4": "相对强度转正",
    "T5": "席位共振",
}

# --- 阈值(校验阶段可调,集中放置)
CUM_WINDOW = 20            # 累计窗口(交易日)
INFLOW_STREAK = 3          # T1 连续净流入天数
DIVERGENCE_WINDOW = 10     # T2 背离回看窗口
VOLUME_BREAKOUT = 1.5      # T2 放量倍数
BREADTH_HIGH = 0.6         # T3 广度上沿
BREADTH_LOW = 0.4          # T3 广度下沿
BREADTH_LOOKBACK = 5       # T3 前期窄幅回看
EXCESS_WATCH_BAND = 1.0    # T4 临界带(百分点)
SEAT_MIN_FIRED = 3         # T5 席位数下限
SEAT_MULT_FIRED = 2.0
SEAT_MIN_WATCH = 2
SEAT_MULT_WATCH = 1.5

MIN_SERIES_LEN = CUM_WINDOW + 2   # 判据所需的最短历史

# fired 记满分权重,watch 记 40%
WATCH_FACTOR = 0.4
DEFAULT_WEIGHTS: Dict[str, float] = {r: 1.0 for r in RULE_IDS}


def _num(value: Any) -> Optional[float]:
    try:
        if value in (None, "", "-"):
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result


def _col(series: Sequence[Mapping[str, Any]], field: str) -> List[Optional[float]]:
    return [_num(row.get(field)) for row in series]


def _cum(values: Sequence[Optional[float]], start: int, end: int) -> Optional[float]:
    """values[start:end] 求和;窗口内全为 None → None,部分 None 按 0 计。"""
    window = values[start:end]
    present = [v for v in window if v is not None]
    return sum(present) if present else None


def _sorted_series(series: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows = [dict(r) for r in series or [] if r.get("trade_date")]
    return sorted(rows, key=lambda r: str(r["trade_date"]))


# ============================================================ 各条判据
def _rule_t1(series: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    net = _col(series, "net_amount")
    cum_now = _cum(net, -CUM_WINDOW, len(net))
    cum_prev = _cum(net, -CUM_WINDOW - 1, len(net) - 1)
    if cum_now is None or cum_prev is None:
        return None
    streak = 0
    for value in reversed(net):
        if value is not None and value > 0:
            streak += 1
        else:
            break
    evidence = {"cum20": round(cum_now, 2), "cum20_prev": round(cum_prev, 2),
                "streak": streak}
    if cum_now > 0 and cum_prev <= 0 and streak >= INFLOW_STREAK:
        return {"rule": "T1", "state": "fired", "evidence": evidence,
                "gap": ""}
    if streak >= INFLOW_STREAK and cum_now <= 0:
        return {"rule": "T1", "state": "watch", "evidence": evidence,
                "gap": f"已连续 {streak} 日主力净流入,20 日累计仍为负,需继续流入转正"}
    if cum_now > 0 and cum_prev <= 0 and streak > 0:
        return {"rule": "T1", "state": "watch", "evidence": evidence,
                "gap": f"20 日累计刚转正,连续净流入 {streak} 日,还差 {INFLOW_STREAK - streak} 日"}
    return None


def _rule_t2(series: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    pct = _col(series, "pct_chg_mean")
    net = _col(series, "net_amount")
    amount = _col(series, "amount_median")
    win_start = -DIVERGENCE_WINDOW - 1
    cum_pct = _cum(pct, win_start, -1)
    cum_net = _cum(net, win_start, -1)
    if cum_pct is None or cum_net is None:
        return None
    if not (cum_pct < 0 and cum_net > 0):
        return None
    today_pct = pct[-1]
    hist_amount = [v for v in amount[win_start:-1] if v is not None]
    today_amount = amount[-1]
    base = median(hist_amount) if hist_amount else None
    evidence = {"window_pct": round(cum_pct, 2), "window_net": round(cum_net, 2),
                "today_pct": None if today_pct is None else round(today_pct, 2),
                "volume_ratio": (None if not base or today_amount is None
                                 else round(today_amount / base, 2))}
    breakout = (today_pct is not None and today_pct > 0 and base
                and today_amount is not None and today_amount >= base * VOLUME_BREAKOUT)
    if breakout:
        return {"rule": "T2", "state": "fired", "evidence": evidence, "gap": ""}
    return {"rule": "T2", "state": "watch", "evidence": evidence,
            "gap": f"前 {DIVERGENCE_WINDOW} 日价跌资金进(疑似吸筹),尚未出现放量上涨确认"}


def _rule_t3(series: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    breadth = _col(series, "breadth")
    if len(breadth) < BREADTH_LOOKBACK + 2:
        return None
    today, prev = breadth[-1], breadth[-2]
    earlier = [v for v in breadth[-BREADTH_LOOKBACK - 2:-2] if v is not None]
    if today is None or not earlier:
        return None
    was_narrow = min(earlier) < BREADTH_LOW
    evidence = {"breadth": round(today, 3),
                "breadth_prev": None if prev is None else round(prev, 3),
                "prior_min": round(min(earlier), 3)}
    if not (was_narrow and today > BREADTH_HIGH):
        return None
    if prev is not None and prev > BREADTH_HIGH:
        return {"rule": "T3", "state": "fired", "evidence": evidence, "gap": ""}
    return {"rule": "T3", "state": "watch", "evidence": evidence,
            "gap": f"上涨家数占比首日突破 {BREADTH_HIGH:.0%},还需再维持 1 日确认"}


def _rule_t4(series: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    excess = _col(series, "excess_vs_market")
    cum_now = _cum(excess, -CUM_WINDOW, len(excess))
    cum_prev = _cum(excess, -CUM_WINDOW - 1, len(excess) - 1)
    if cum_now is None or cum_prev is None:
        return None
    evidence = {"excess20": round(cum_now, 2), "excess20_prev": round(cum_prev, 2)}
    if cum_now > 0 and cum_prev <= 0:
        return {"rule": "T4", "state": "fired", "evidence": evidence, "gap": ""}
    if -EXCESS_WATCH_BAND < cum_now <= 0:
        return {"rule": "T4", "state": "watch", "evidence": evidence,
                "gap": f"20 日相对全市场累计 {cum_now:+.2f} 个百分点,接近转正"}
    return None


def _rule_t5(series: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    seats = _col(series, "seat_count")
    today = seats[-1]
    hist = [v for v in seats[-CUM_WINDOW - 1:-1] if v is not None]
    if today is None or not hist:
        return None
    base = median(hist)
    evidence = {"seat_count": int(today), "baseline": round(base, 2)}
    if today >= SEAT_MIN_FIRED and today >= max(base * SEAT_MULT_FIRED, SEAT_MIN_FIRED):
        return {"rule": "T5", "state": "fired", "evidence": evidence, "gap": ""}
    if today >= SEAT_MIN_WATCH and today >= base * SEAT_MULT_WATCH:
        return {"rule": "T5", "state": "watch", "evidence": evidence,
                "gap": f"异动/上榜席位 {int(today)} 个,较基线抬升但未达共振阈值"}
    return None


_RULE_FUNCS = {"T1": _rule_t1, "T2": _rule_t2, "T3": _rule_t3,
               "T4": _rule_t4, "T5": _rule_t5}


# ============================================================ 对外接口
def evaluate_rules(series: Iterable[Mapping[str, Any]],
                   *, enabled: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """板块日序列 → 命中的判据列表(不成立的判据不出现)。"""
    rows = _sorted_series(series)
    if len(rows) < MIN_SERIES_LEN:
        return []
    allow = tuple(enabled) if enabled is not None else RULE_IDS
    results: List[Dict[str, Any]] = []
    for rule_id in RULE_IDS:
        if rule_id not in allow:
            continue
        try:
            hit = _RULE_FUNCS[rule_id](rows)
        except Exception:  # noqa: BLE001 — 单条判据异常不影响其余
            hit = None
        if hit:
            hit["label"] = RULE_LABELS[rule_id]
            results.append(hit)
    return results


def turning_score(results: Iterable[Mapping[str, Any]],
                  weights: Optional[Mapping[str, float]] = None) -> float:
    """命中判据 → 0~100 拐点分。fired 计满权重,watch 计 40%。

    ``weights`` 给定时视为**完整权重表**(即当前上线的判据集合),分母只算这些判据;
    不给则按全部 RULE_IDS 等权。否则只上线 1 条判据时满命中也只能拿 1/5 分,
    分数失去意义(2026-08-21 仅 T5 上线时实测为 20 分)。
    """
    w = dict(weights) if weights else dict(DEFAULT_WEIGHTS)
    total = sum(abs(v) for v in w.values()) or 1.0
    got = 0.0
    for item in results or []:
        rule_id = item.get("rule")
        if rule_id not in w:
            continue
        factor = 1.0 if item.get("state") == "fired" else WATCH_FACTOR
        got += w[rule_id] * factor
    return round(min(100.0, max(0.0, got / total * 100.0)), 1)


def evaluate_universe(
    series_by_sector: Mapping[Tuple[str, str], Sequence[Mapping[str, Any]]],
    *,
    weights: Optional[Mapping[str, float]] = None,
    enabled: Optional[Sequence[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """全部板块 → {"fired": [...], "watch": [...]},各自按拐点分降序。"""
    fired: List[Dict[str, Any]] = []
    watch: List[Dict[str, Any]] = []
    for (sector, sector_type), series in (series_by_sector or {}).items():
        results = evaluate_rules(series, enabled=enabled)
        if not results:
            continue
        rows = _sorted_series(series)
        entry = {
            "sector": sector,
            "sector_type": sector_type,
            "trade_date": rows[-1]["trade_date"] if rows else "",
            "provisional": bool(rows[-1].get("provisional")) if rows else False,
            "member_count": rows[-1].get("member_count") if rows else None,
            "pct_chg_mean": rows[-1].get("pct_chg_mean") if rows else None,
            "net_amount": rows[-1].get("net_amount") if rows else None,
            "rules": results,
            "score": turning_score(results, weights),
        }
        (fired if any(r["state"] == "fired" for r in results) else watch).append(entry)
    fired.sort(key=lambda e: e["score"], reverse=True)
    watch.sort(key=lambda e: e["score"], reverse=True)
    return {"fired": fired, "watch": watch}
