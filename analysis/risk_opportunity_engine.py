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


def score_sector_crowding(sector):
    s = _num(sector or {}, "sector_score")
    if s is None:
        return 35.0
    if 65 <= s <= 75:        # memory: 死区 25.5%wr
        return 65.0
    if s > 75:               # 过热追高
        return 55.0
    if s < 45:
        return 30.0
    return 45.0


def score_market_risk(market_env):
    m = market_env or {}
    risk, factors = 35.0, []

    def add(name, contrib, detail):
        nonlocal risk
        risk += contrib
        factors.append({"name": name, "contrib": contrib, "detail": detail})

    r5 = _num(m, "hs300_ret_5d")
    r20 = _num(m, "hs300_ret_20d")
    if r5 is not None and r5 <= -3:
        add("近5日回撤", 15, f"沪深300 {r5:.1f}%")
    if r20 is not None and r20 <= -6:
        add("近20日回撤", 12, f"沪深300 {r20:.1f}%")
    adv, dec = _num(m, "advance"), _num(m, "decline")
    if adv is not None and dec is not None and (adv + dec) > 0:
        ratio = dec / (adv + dec)
        if ratio >= 0.6:
            add("涨跌家数", 15, f"跌{int(dec)}/涨{int(adv)}")
    sent = _num(m, "sentiment")
    if sent is not None and sent <= 35:
        add("情绪冰点", 8, f"情绪 {sent:.0f}")
    elif sent is not None and sent >= 80:
        add("情绪过热", 8, f"情绪 {sent:.0f}")
    risk = max(0.0, min(100.0, risk))
    return {"risk": risk, "factors": factors}


def score_portfolio_risk(account, positions, max_drawdown=0.0):
    account = account or {}
    positions = positions or []
    equity = _num(account, "total_equity") or 0.0
    pos_val = sum((_num(p, "market_value") or 0.0) for p in positions)
    weights = [((_num(p, "market_value") or 0.0) / equity) for p in positions] if equity else []
    concentration = round(max(weights), 4) if weights else 0.0
    exposure = round(pos_val / equity, 4) if equity else 0.0
    dd = float(max_drawdown or 0.0)
    risk = 20.0 + concentration * 60 + min(exposure, 1.0) * 20 + min(dd, 0.5) * 60
    risk = max(0.0, min(100.0, risk))
    return {"risk": risk, "concentration": concentration,
            "exposure": exposure, "max_drawdown": dd}


def combine_stock_risk(stock, sector_crowding, market_backdrop):
    if not stock or stock.get("unknown") or stock.get("risk") is None:
        return None
    v = (RISK_BLEND["stock"] * stock["risk"]
         + RISK_BLEND["sector"] * float(sector_crowding or 35.0)
         + RISK_BLEND["market"] * float(market_backdrop or 35.0))
    return max(0.0, min(100.0, v))


def opportunity_index(items):
    items = items or []
    if not items:
        return 0.0
    scores = sorted((float(i.get("score") or 0) for i in items), reverse=True)
    top = scores[: max(1, len(scores) // 3)]      # 取头部 1/3 的均分
    base = sum(top) / len(top)
    s_a = sum(1 for i in items if str(i.get("rating")) in ("S", "A"))
    boost = min(15.0, s_a * 1.5)
    return max(0.0, min(100.0, base + boost))


def market_risk_index(market_risk, sentiment):
    sent = float(sentiment if sentiment is not None else 50.0)
    # 情绪越低,系统性风险体感越高
    return max(0.0, min(100.0, 0.7 * float(market_risk) + 0.3 * (100 - sent)))


def _reason_line(item, risk_result, action_obj):
    opp_part = f"机会{item.get('score'):.0f}({item.get('rating', '—')})"
    if risk_result.get("unknown") or risk_result.get("risk") is None:
        risk_part = "风险未知(无结构化信号)"
    elif risk_result.get("dominant"):
        risk_part = f"{risk_result['dominant']}"
    else:
        risk_part = "风险可控"
    return f"{opp_part} · {risk_part} → {action_obj['action']}"


def build_target(item, signals, sector_crowding, market_backdrop, *, held):
    stock = score_stock_risk(signals)
    combined = combine_stock_risk(stock, sector_crowding, market_backdrop)
    action = match_action(float(item.get("score") or 0), combined, held=held)
    return {
        "code": item.get("code") or item.get("stock_code"),
        "name": item.get("name") or item.get("stock_name"),
        "sector": item.get("sector"),
        "opp": float(item.get("score") or 0),
        "rating": item.get("rating"),
        "risk": round(combined, 1) if combined is not None else None,
        "risk_unknown": stock["unknown"],
        "quadrant": action["quadrant"],
        "action": action["action"],
        "code_action": action["code"],
        "color": action["color"],
        "held": held,
        "held_overlay": action["held_overlay"],
        "reason": _reason_line(item, stock, action),
    }
