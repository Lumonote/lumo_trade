"""吸筹识别与统计 —— 主力资金持续净流入 + 量价背离(纯函数,离线可测)。

数据源:``moneyflow_dc`` top_n=0 全市场快照行(取数在 repo/service 层,本模块零 IO)。
判定口径(spec §2.3,三条同时满足):流入持续性(净流入天数占比≥55%)、
流入力度(累计净流入>0 且日均净流入率≥0.2%)、量价背离(窗口涨跌幅在 ±15% 内)。
「疑似」口径:主力净流入为公开数据代理指标,不构成吸筹行为认定与投资建议。
设计 spec: docs/superpowers/specs/2026-07-16-accumulation-ambush-design.md
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

WINDOWS = (20, 40, 60)

# 判定与评分阈值(集中放置便于调参)
RATIO_MIN = 0.55                 # 净流入天数占比下限
DAILY_RATE_MIN = 0.2             # 日均净流入率下限(%)
PRICE_BAND = 15.0                # 量价背离:窗口区间涨跌幅绝对值上限(%)
KICK_3D_PCT = 5.0                # 疑似启动:近3日累计涨幅(%)
RATE_CAP = 1.0                   # 评分用日均净流入率封顶(%)
ELG_SHARE_INSTITUTIONAL = 0.7    # 超大+大单占比 ≥ 该值记机构型加成


def _num(v: Any) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _normalize(rows: List[Dict[str, Any]], window: int) -> List[Dict[str, Any]]:
    """原始行 → 升序、单位归一(万元)、剔除无净额行,截取窗口末端。"""
    srt = sorted((r for r in rows or [] if r.get("trade_date")),
                 key=lambda r: str(r["trade_date"]))
    days: List[Dict[str, Any]] = []
    for r in srt:
        net = _num(r.get("net_amount"))
        if net is None:
            continue
        mult = 1e-4 if str(r.get("amount_unit") or "万元") == "元" else 1.0
        days.append({
            "date": str(r["trade_date"]),
            "net": net * mult,
            "rate": _num(r.get("net_amount_rate")),
            "elg_lg": ((_num(r.get("buy_elg_amount")) or 0.0)
                       + (_num(r.get("buy_lg_amount")) or 0.0)) * mult,
            "close": _num(r.get("close")),
            "pct": _num(r.get("pct_change")),
        })
    return days[-window:]


def detect(rows: Optional[List[Dict[str, Any]]], window: int = 40) -> Optional[Dict[str, Any]]:
    """单只股票吸筹检测:``moneyflow_dc`` 行序列 → 判定 + 时间/量统计 + 埋伏评分。

    覆盖天数 < max(12, window//2) → None(新股/长停牌自然排除)。
    ``qualified`` 与否都返回统计,未通过时 ``reasons`` 为未通过原因。
    """
    window = int(window) if window in WINDOWS else 40
    days = _normalize(rows or [], window)
    coverage = len(days)
    if coverage < max(12, window // 2):
        return None

    inflow = [d["net"] > 0 for d in days]
    accum_days = sum(inflow)
    accum_ratio = round(accum_days / coverage, 3)
    max_streak = cur = 0
    for flag in inflow:
        cur = cur + 1 if flag else 0
        max_streak = max(max_streak, cur)
    idx = [i for i, flag in enumerate(inflow) if flag]
    span_days = (idx[-1] - idx[0] + 1) if idx else 0
    total_net_wan = round(sum(d["net"] for d in days), 2)
    rates = [d["rate"] for d in days if d["rate"] is not None]
    avg_rate = round(sum(rates) / coverage, 3) if rates else 0.0
    elg_lg_net = sum(d["elg_lg"] for d in days)
    elg_share = round(elg_lg_net / total_net_wan, 3) if total_net_wan > 0 else None

    closes = [d["close"] for d in days if d["close"]]
    if len(closes) >= 2 and closes[0] > 0:
        window_pct_chg = (closes[-1] / closes[0] - 1) * 100
    else:  # close 缺失时用逐日涨跌幅合计近似
        window_pct_chg = sum(d["pct"] or 0.0 for d in days)
    window_pct_chg = round(window_pct_chg, 2)

    fails: List[str] = []
    if accum_ratio < RATIO_MIN:
        fails.append(f"净流入天数占比 {accum_ratio:.0%} 不足 {RATIO_MIN:.0%}")
    if not (total_net_wan > 0 and avg_rate >= DAILY_RATE_MIN):
        fails.append(f"流入力度不足(日均净流入率 {avg_rate:.2f}%,"
                     f"累计 {total_net_wan:.0f} 万元)")
    if abs(window_pct_chg) > PRICE_BAND:
        fails.append(f"窗口涨跌幅 {window_pct_chg:+.1f}% 超出 ±{PRICE_BAND:.0f}%,"
                     "量价背离不成立(或已拉升)")
    qualified = not fails

    score = (30 * _clip01((accum_ratio - RATIO_MIN) / (1 - RATIO_MIN))
             + 2 * min(max_streak, 10)
             + 25 * _clip01((avg_rate - DAILY_RATE_MIN) / (RATE_CAP - DAILY_RATE_MIN))
             + 15 * _clip01((PRICE_BAND - abs(window_pct_chg)) / PRICE_BAND))
    institutional = elg_share is not None and elg_share >= ELG_SHARE_INSTITUTIONAL
    if institutional:
        score += 10
    score = int(round(max(0.0, min(100.0, score))))

    kick = sum(d["pct"] or 0.0 for d in days[-3:])
    status = ("疑似启动" if kick >= KICK_3D_PCT else "吸筹中") if qualified else ""

    if qualified:
        reasons = [
            f"近{coverage}个交易日 {accum_days} 天主力净流入"
            f"(占比 {accum_ratio:.0%}),最长连续 {max_streak} 天",
            f"累计净流入 {total_net_wan / 1e4:.2f} 亿元,日均净流入率 {avg_rate:.2f}%",
            f"期间股价仅 {window_pct_chg:+.1f}%,资金持续进而价未动,疑似吸筹",
        ]
        if institutional:
            reasons.append(f"超大+大单贡献 {elg_share:.0%},机构型吸筹特征")
        if status == "疑似启动":
            reasons.append(f"近3日累计上涨 {kick:+.1f}%,吸筹后疑似启动")
    else:
        reasons = fails

    return {
        "qualified": qualified,
        "window": window,
        "coverage_days": coverage,
        "accum_days": accum_days,
        "accum_ratio": accum_ratio,
        "max_streak": max_streak,
        "span_days": span_days,
        "total_net_wan": total_net_wan,
        "avg_rate": avg_rate,
        "elg_share": elg_share,
        "window_pct_chg": window_pct_chg,
        "score": score,
        "status": status,
        "reasons": reasons,
        "daily": [{"date": d["date"], "net_wan": round(d["net"], 2), "pct": d["pct"]}
                  for d in days],
    }
