"""Pure risk/opportunity scoring & matching for the command-center 大屏.

No I/O. Inputs are plain dicts assembled by command_center_service; outputs are
plain dicts the frontend renders. Thresholds are module-level tunable constants
(mirrors the project's scoring-param tuning culture).
"""

OPP_BANDS = {"high": 70.0, "mid": 55.0}
RISK_BANDS = {"low": 40.0, "high": 60.0}
RISK_BLEND = {"stock": 0.55, "sector": 0.20, "market": 0.25}
STOCK_RISK_BASE = 30.0

_ACTION_TABLE = {
    ("high", "low"): ("重点出手", "act", "green"),
    ("high", "mid"): ("可做·控仓", "do", "amber"),
    ("high", "high"): ("谨慎·轻仓", "care", "orange"),
    ("mid", "low"): ("关注", "watch", "cyan"),
    ("mid", "mid"): ("观望", "watch", "blue"),
    ("mid", "high"): ("暂避", "avoid", "red"),
    ("low", "low"): ("无感", "none", "gray"),
    ("low", "mid"): ("回避", "avoid", "red"),
    ("low", "high"): ("坚决回避", "avoid", "red"),
}


def _opp_band(opp):
    if opp >= OPP_BANDS["high"]:
        return "high"
    if opp >= OPP_BANDS["mid"]:
        return "mid"
    return "low"


def _risk_band(risk):
    if risk < RISK_BANDS["low"]:
        return "low"
    if risk >= RISK_BANDS["high"]:
        return "high"
    return "mid"


def match_action(opp, risk, *, held=False):
    if risk is None:
        return {"quadrant": "unknown", "action": "风险未知", "code": "unknown",
                "color": "gray", "held_overlay": None}
    o, r = _opp_band(opp), _risk_band(risk)
    label, code, color = _ACTION_TABLE[(o, r)]
    overlay = None
    if held:
        if r == "high":
            overlay = "减仓/止盈"
        elif o == "high" and r == "low":
            overlay = "持有"
    return {"quadrant": f"{o}-{r}", "action": label, "code": code,
            "color": color, "held_overlay": overlay}


def _num(signals, key):
    v = signals.get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def score_stock_risk(signals):
    signals = signals or {}
    rsi = _num(signals, "rsi")
    chase = _num(signals, "chase")
    chg3 = _num(signals, "change_3d")
    sell = _num(signals, "sell_signals")
    quant = _num(signals, "quant_score")
    streak = _num(signals, "limit_up_streak")
    is_st = bool(signals.get("is_st"))
    halt = bool(signals.get("halt"))

    if all(v is None for v in (rsi, chase, chg3, sell, quant)) and not (is_st or halt):
        return {"risk": None, "factors": [], "dominant": None, "unknown": True}

    risk = STOCK_RISK_BASE
    factors = []

    def add(name, contrib, detail):
        nonlocal risk
        risk += contrib
        factors.append({"name": name, "contrib": contrib, "detail": detail})

    if rsi is not None and rsi >= 80:
        add("RSI过热", 30, f"RSI {rsi:.0f} ≥80")
    elif rsi is not None and rsi >= 70:
        add("RSI偏热", 15, f"RSI {rsi:.0f} ≥70")
    if chase is not None and chase >= 80:
        add("追高", 20, f"追高 {chase:.0f}")
    elif chase is not None and chase >= 50:
        add("追高", 10, f"追高 {chase:.0f}")
    if chg3 is not None and chg3 >= 20:
        add("5日急涨", 15, f"3日 +{chg3:.0f}%")
    elif chg3 is not None and chg3 >= 12:
        add("5日急涨", 8, f"3日 +{chg3:.0f}%")
    if sell is not None and sell >= 2:
        add("卖出信号", 12, f"卖出 {sell:.0f}")
    if quant is not None and quant >= 90:
        add("量化过度共识", 10, f"量化 {quant:.0f} ≥90")
    if streak is not None and streak >= 2:
        add("连板高位", 10, f"连板 {streak:.0f}")

    if is_st or halt:
        risk = max(risk, 85)
        factors.append({"name": "ST/停牌硬闸", "contrib": 0, "detail": "风险封顶"})

    risk = max(0.0, min(100.0, risk))
    scored = [f for f in factors if f["contrib"] > 0]
    dominant = max(scored, key=lambda f: f["contrib"])["name"] if scored else (
        "ST/停牌硬闸" if (is_st or halt) else None)
    return {"risk": risk, "factors": factors, "dominant": dominant, "unknown": False}
