"""自选股智能提醒 —— 在既有数据面上派生「有意义」的盘口/资金/技术信号。

纯函数,数据全部由调用方注入(日K + 资金流窗口 + 量化雷达当日 + 吸筹 + 量化席位),
不发网络、不读库,便于离线单测。信号口径对齐项目既有语义:
- 超卖/超买: RSI(14) <=30 / >=70(与 technical_analysis.calculate_rsi 同源)。
- 超跌反弹: 近5日 RSI 探入超卖后回升 + 当日放量收阳。
- 主力出逃: 连续净流出 或 当日主力净流出率极端为负(moneyflow_dc 净流入率)。
- 主力进场: 连续净流入 或 净流入率显著为正。
- 量化介入: 量化雷达高活跃 / 龙虎榜量化席位 / 吸筹判定达标(任一即触发,合并成一条)。
- 收割预警: 量化雷达当日盘口方向为「砸盘」。
- 放量异动: 当日量能 >= 2× 近5日均量。

每条 alert = {type, level(danger/warn/info), title, text}; 返回按 level 严重度降序。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_LEVEL_RANK = {"danger": 3, "warn": 2, "info": 1}


def _num(v: Any) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def tech_snapshot(bars: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """日K(≥15根升序) → RSI 现值/近5日最小值/是否回升 + 当日涨跌与放量。不足 → None。"""
    rows = sorted((b for b in bars or [] if _num(b.get("close")) is not None),
                  key=lambda b: str(b.get("date")))
    if len(rows) < 15:
        return None
    closes = [float(b["close"]) for b in rows]
    vols = [float(b.get("volume") or 0.0) for b in rows]
    rsi_last = rsi_min5 = None
    rsi_rising = False
    try:
        import pandas as pd

        from analysis.technical_analysis import TechnicalAnalysis as TA

        rsi_s = TA.calculate_rsi(pd.Series(closes, dtype=float)).dropna()
        if len(rsi_s):
            rsi_last = round(float(rsi_s.iloc[-1]), 1)
            tail = rsi_s.iloc[-5:]
            rsi_min5 = round(float(tail.min()), 1)
            rsi_rising = bool(len(rsi_s) >= 2 and rsi_s.iloc[-1] > rsi_s.iloc[-2])
    except Exception:
        pass
    today_pct = None
    o, c = float(rows[-1].get("open") or closes[-1]), closes[-1]
    if rows[-1].get("pct_chg") is not None:
        today_pct = _num(rows[-1].get("pct_chg"))
    elif o > 0:
        today_pct = round((c - o) / o * 100, 2)
    vol_ratio = None
    if len(vols) >= 6 and vols[-1] > 0:
        base = sum(vols[-6:-1]) / 5
        vol_ratio = round(vols[-1] / base, 2) if base > 0 else None
    return {"rsi": rsi_last, "rsi_min5": rsi_min5, "rsi_rising": rsi_rising,
            "today_pct": today_pct, "vol_ratio": vol_ratio}


def detect(bars: Optional[List[Dict[str, Any]]] = None,
           flow: Optional[Dict[str, Any]] = None,
           radar: Optional[Dict[str, Any]] = None,
           accum: Optional[Dict[str, Any]] = None,
           quant_seat: bool = False) -> List[Dict[str, Any]]:
    """按注入数据派生自选股提醒列表(按严重度降序)。任一数据缺失只跳过对应规则。"""
    alerts: List[Dict[str, Any]] = []
    snap = tech_snapshot(bars or [])
    if snap:
        rsi, rmin, pct = snap["rsi"], snap["rsi_min5"], snap["today_pct"]
        if rsi is not None and rsi <= 30:
            alerts.append({"type": "oversold", "level": "warn", "title": "超卖",
                           "text": f"RSI {rsi} 进入超卖区(≤30),短线或有反抽,勿追空"})
        elif rsi is not None and rsi >= 70:
            alerts.append({"type": "overbought", "level": "warn", "title": "超买",
                           "text": f"RSI {rsi} 进入超买区(≥70),涨幅透支,注意回调风险"})
        # 超跌反弹:近5日 RSI 曾探入超卖(≤32)且当前回升 + 当日放量收阳(>1.5%)
        if (rmin is not None and rmin <= 32 and snap["rsi_rising"]
                and pct is not None and pct >= 1.5):
            extra = "并放量" if (snap["vol_ratio"] or 0) >= 1.5 else ""
            alerts.append({"type": "oversold_rebound", "level": "info", "title": "超跌反弹",
                           "text": f"RSI 自超卖区({rmin})回升,当日{extra}上涨 {pct:.2f}%,疑似超跌反弹启动"})
        if (snap["vol_ratio"] or 0) >= 2.0 and pct is not None:
            alerts.append({"type": "volume_surge", "level": "info", "title": "放量异动",
                           "text": f"当日量能达近5日均量 {snap['vol_ratio']}×,{'放量上攻' if pct >= 0 else '放量下杀'}"})

    if flow:
        net_rate = _num(flow.get("net_rate"))
        streak_out = int(flow.get("streak_out") or 0)
        streak_in = int(flow.get("streak") or 0)
        net_wan = _num(flow.get("main_net_wan"))
        if streak_out >= 3 or (net_rate is not None and net_rate <= -5):
            reason = (f"主力连续净流出 {streak_out} 日" if streak_out >= 3
                      else f"当日主力净流出率 {net_rate:.1f}%")
            alerts.append({"type": "main_fleeing", "level": "danger", "title": "主力出逃",
                           "text": f"{reason}" + (f",净额 {net_wan:.0f} 万" if net_wan is not None else "")
                                   + ",资金持续撤离,警惕破位"})
        elif streak_in >= 3 or (net_rate is not None and net_rate >= 5):
            reason = (f"主力连续净流入 {streak_in} 日" if streak_in >= 3
                      else f"当日主力净流入率 {net_rate:.1f}%")
            alerts.append({"type": "main_inflow", "level": "info", "title": "主力进场",
                           "text": f"{reason}" + (f",净额 {net_wan:.0f} 万" if net_wan is not None else "")
                                   + ",资金持续流入"})

    # 量化介入:高活跃 / 量化席位 / 吸筹达标 任一触发,合并成一条
    reasons: List[str] = []
    activity = _num((radar or {}).get("activity"))
    if activity is not None and activity >= 50:
        reasons.append(f"量化雷达活跃度 {activity:.0f}")
    if quant_seat:
        reasons.append("龙虎榜现量化席位")
    if accum and accum.get("qualified"):
        ad = int(accum.get("accum_days") or 0)
        reasons.append(f"吸筹判定达标(近{ad}日主力潜伏)")
    if reasons:
        alerts.append({"type": "quant_involved", "level": "info", "title": "量化介入",
                       "text": "、".join(reasons) + ",量化资金迹象明显"})

    if radar and str(radar.get("direction") or "") == "砸盘":
        ct = int(radar.get("changes_total") or 0)
        alerts.append({"type": "smash_warning", "level": "danger", "title": "收割预警",
                       "text": f"量化雷达判定当日盘口为「砸盘」" + (f"(异动 {ct} 笔)" if ct else "")
                               + ",疑似程序化出货,接飞刀风险高"})

    alerts.sort(key=lambda a: -_LEVEL_RANK.get(a["level"], 0))
    return alerts
