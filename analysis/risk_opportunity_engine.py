"""Pure risk/opportunity scoring & matching for the command-center 大屏.

No I/O. Inputs are plain dicts assembled by command_center_service; outputs are
plain dicts the frontend renders. Thresholds are module-level tunable constants
(mirrors the project's scoring-param tuning culture).
"""
import re

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
        "sector_code": item.get("sector_code") or item.get("board_code"),
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


# ── 持仓 · 热点关联(holdings ⇄ 热门板块 / 热点资讯)──────────────────────
# 模块级可调常量(沿用本项目评分参数可调文化)。权重默认偏向板块:结构化的板块
# 归属比资讯子串匹配更可靠。用户已知会调权重。
HOLD_REL_WEIGHTS = {"sector": 0.6, "news": 0.4}
HOLD_REL_RANK_DECAY = 8.0          # 命中板块每降 1 名,基准分衰减
HOLD_REL_RANK_FLOOR = 20.0         # 命中板块的基准分下限
HOLD_REL_RANK_UNKNOWN = 55.0       # board_rank 缺失时的基准分
HOLD_REL_STOCK_TOP_BONUS = 12.0    # 板块内成分股 #1 的加分
HOLD_REL_STOCK_DECAY = 2.0         # 成分股每降 1 名,加分衰减
HOLD_REL_LHB_BONUS = 8.0           # 任一命中板块上榜龙虎
HOLD_REL_MULTI_BOARD_BONUS = 5.0   # 命中 ≥2 个热门板块
HOLD_REL_BOARDS_CAP = 3            # 每只持仓展示的命中板块上限
HOLD_REL_NEWS_CAP = 3              # 每只持仓展示的命中资讯上限
# 资讯平台权重:按「去重后的不同平台」计权,避免单平台多条例行快讯把分刷满。
# 平台名须与 webui.core._holdings_news_index 产出的 platform 一致。
NEWS_PLATFORM_WEIGHTS = {
    "东财人气热度": 45.0,
    "金十快讯": 40.0,
    "东财快讯": 35.0,
    "新浪快讯": 35.0,
    "同花顺快讯": 35.0,
}
NEWS_PLATFORM_DEFAULT_WEIGHT = 20.0


def _hold_rel_code6(value):
    """Leading 6-digit run of a ts_code — matches webui._stock_code_key, which the
    membership/news indices are keyed by, so the join lines up (no reinvented key)."""
    m = re.search(r"\d{6}", str(value or ""))
    return m.group(0) if m else str(value or "").strip()


def _hold_sector_relevance(boards):
    """0–100 板块关联,以 board_rank 最小(最热)的命中板块为基准。"""
    if not boards:
        return 0.0
    hottest = boards[0]                       # 调用方已按 board_rank 升序
    rank = hottest.get("board_rank")
    if rank is None:
        base = HOLD_REL_RANK_UNKNOWN
    else:
        base = max(HOLD_REL_RANK_FLOOR,
                   min(100.0, 100.0 - (float(rank) - 1.0) * HOLD_REL_RANK_DECAY))
    srank = hottest.get("stock_rank")
    if srank is not None:
        base += max(0.0, min(HOLD_REL_STOCK_TOP_BONUS,
                             HOLD_REL_STOCK_TOP_BONUS - (float(srank) - 1.0) * HOLD_REL_STOCK_DECAY))
    if any(b.get("lhb_hit") for b in boards):
        base += HOLD_REL_LHB_BONUS
    if len(boards) >= 2:
        base += HOLD_REL_MULTI_BOARD_BONUS
    return max(0.0, min(100.0, base))


def _hold_news_relevance(news):
    """0–100 资讯关联,按去重后的不同平台权重求和(同平台多条不重复计权)。"""
    platforms = {str(n.get("platform") or "") for n in (news or [])}
    total = sum(NEWS_PLATFORM_WEIGHTS.get(p, NEWS_PLATFORM_DEFAULT_WEIGHT)
                for p in platforms if p)
    return max(0.0, min(100.0, total))


def score_holdings_relevance(positions, membership_index, news_index, *,
                             sector_weight=None, news_weight=None):
    """Score each holding's relevance to current 热门板块 / 热点资讯.

    Pure: consumes plain dicts only — no I/O, no fuzzy name matching (matching is
    done upstream in webui.core._holdings_news_index). Rows are returned sorted by
    ``relevance`` desc, then ``market_value`` desc.

    - ``positions``        : ``[{ts_code, name, market_value, float_pnl_rate, ...}]``
    - ``membership_index`` : ``{code6: [membership, ...]}`` (见 ``_hot_sector_stock_membership_index``)
    - ``news_index``       : ``{code6: [{platform, title}, ...]}``
    """
    sw = HOLD_REL_WEIGHTS["sector"] if sector_weight is None else float(sector_weight)
    nw = HOLD_REL_WEIGHTS["news"] if news_weight is None else float(news_weight)
    membership_index = membership_index or {}
    news_index = news_index or {}
    rows = []
    for pos in positions or []:
        code = _hold_rel_code6(pos.get("ts_code") or pos.get("code"))
        # 防御性按 board_rank/stock_rank 升序,确保 boards[0] 为最热(即便上游未排序)。
        boards_all = sorted(
            (b for b in (membership_index.get(code) or []) if isinstance(b, dict)),
            key=lambda b: (b.get("board_rank") or 9999, b.get("stock_rank") or 9999))
        news_all = [n for n in (news_index.get(code) or []) if isinstance(n, dict)]
        sector_rel = _hold_sector_relevance(boards_all)
        news_rel = _hold_news_relevance(news_all)
        boards = [{
            "snapshot_id": b.get("snapshot_id"),
            "name": b.get("board_name") or b.get("board_code"),
            "board_code": b.get("board_code"),
            "board_rank": b.get("board_rank"),
            "stock_rank": b.get("stock_rank"),
            "main_net_inflow": b.get("main_net_inflow"),
            "main_net_inflow_text": b.get("main_net_inflow_text") or "",
            "change_pct": b.get("change_pct"),
            "lhb_hit": bool(b.get("lhb_hit")),
        } for b in boards_all[:HOLD_REL_BOARDS_CAP]]
        news = [{"platform": n.get("platform"), "title": n.get("title")}
                for n in news_all[:HOLD_REL_NEWS_CAP]]
        rows.append({
            "code": code,
            "name": pos.get("name") or pos.get("stock_name") or "",
            "market_value": _num(pos, "market_value") or 0.0,
            "float_pnl_rate": _num(pos, "float_pnl_rate"),
            "relevance": round(sw * sector_rel + nw * news_rel),
            "sector_relevance": round(sector_rel),
            "news_relevance": round(news_rel),
            "boards": boards,
            "news": news,
            "status": "踩中" if (boards or news) else "脱离",
        })
    rows.sort(key=lambda r: (r["relevance"], r["market_value"]), reverse=True)
    return rows
