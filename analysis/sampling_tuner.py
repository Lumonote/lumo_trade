from typing import Dict, Any, Optional


def tune_sampling_params(sentiment: Dict[str, Any], events_summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    根据多维情绪(股吧/大盘/板块)动态调优采样参数。

    输入结构参考 InvestorSentimentAnalyzer.get_comprehensive_sentiment()：
    - guba_sentiment: {overall, sentiment_score, bullish_ratio, bearish_ratio}
    - overall_market_sentiment: {emotion, sentiment_score, avg_change_pct}
    - sector_sentiment: {emotion, sentiment_score, change_pct, turnover_rate}

    返回示例：{"T": 0.68, "top_p": 0.88, "sample_count": 4, "reason": "...", "weights": {...}}
    """

    # 基线参数：兼顾稳定与质量
    T = 0.70
    top_p = 0.90
    sample_count = 3

    # 读取各维度情绪
    guba = sentiment.get("guba_sentiment", {})
    market = sentiment.get("overall_market_sentiment", {})
    sector = sentiment.get("sector_sentiment", {})

    # 安全读取数值
    guba_score = _to_num(guba.get("sentiment_score"), default=50)
    guba_bull = _to_num(guba.get("bullish_ratio"), default=0)
    guba_bear = _to_num(guba.get("bearish_ratio"), default=0)

    market_score = _to_num(market.get("sentiment_score"), default=50)
    # 使用所属大盘涨跌作为市场变化，若不可用则回退平均值
    market_change = _to_num(market.get("primary_change_pct"), default=None)
    if market_change is None:
        market_change = _to_num(market.get("avg_change_pct"), default=0)
    market_emotion = market.get("emotion", "neutral")

    sector_score = _to_num(sector.get("sentiment_score"), default=50)
    sector_change = _to_num(sector.get("change_pct"), default=0)
    sector_turnover = _to_num(sector.get("turnover_rate"), default=0)
    sector_emotion = sector.get("emotion", "neutral")

    # 权重设置：股民评论(0.35) + 大盘(0.30) + 板块(0.25) + 事件(0.15)
    weights = {"guba": 0.35, "market": 0.30, "sector": 0.25, "events": 0.15}

    # 风险/不确定性评估
    # - 看空占比高、市场/板块偏弱、涨跌幅绝对值大、板块换手率高 -> 增加样本数、降低温度和top_p
    risk_score = 0.0

    # 看空强度
    if guba_bear >= 20:
        risk_score += 0.20
    elif guba_bear >= 10:
        risk_score += 0.10

    # 市场波动
    risk_score += min(abs(market_change) / 3.0, 1.0) * 0.25  # |±3%|对风险的上限影响

    # 板块波动与活跃度
    risk_score += min(abs(sector_change) / 5.0, 1.0) * 0.25  # |±5%|上限
    if sector_turnover >= 5:
        risk_score += 0.10
    if sector_turnover >= 10:
        risk_score += 0.20

    # 事件面影响（可选）
    ev_rating = None
    ev_risk_level = None
    ev_opp_level = None
    ev_pos = 0
    ev_neg = 0
    ev_score = 0.0

    if isinstance(events_summary, dict) and events_summary:
        ev_rating = events_summary.get("rating")
        ev_risk_level = events_summary.get("risk_level")
        ev_opp_level = events_summary.get("opportunity_level")
        ev_pos = int(events_summary.get("total_positive_events", 0) or 0)
        ev_neg = int(events_summary.get("total_negative_events", 0) or 0)
        ev_score = _to_num(events_summary.get("comprehensive_score"), default=0)

        # 事件风险调节
        if ev_risk_level == "高风险":
            risk_score += 0.15
        elif ev_risk_level == "中等风险":
            risk_score += 0.08
        else:  # 低风险
            risk_score += 0.02

        # 机会等级对风险的缓释
        if ev_opp_level == "高机会":
            risk_score = max(0.0, risk_score - 0.06)
        elif ev_opp_level == "中等机会":
            risk_score = max(0.0, risk_score - 0.03)

    # 方向性评估：整体偏多/偏空影响温度与top_p
    bullish_bias = 0.0
    bearish_bias = 0.0

    bullish_bias += weights["guba"] * (guba_score - 50) / 50.0
    bullish_bias += weights["market"] * (market_score - 50) / 50.0
    bullish_bias += weights["sector"] * (sector_score - 50) / 50.0

    if market_emotion in ("bearish", "slightly_bearish"):
        bearish_bias += 0.15 if market_emotion == "bearish" else 0.08
    if sector_emotion in ("bearish", "slightly_bearish"):
        bearish_bias += 0.15 if sector_emotion == "bearish" else 0.08
    if guba_bear > guba_bull:
        bearish_bias += 0.08

    # 事件评级带来的方向性偏置（增强强利好影响）
    if ev_rating in ("强烈利好", "偏利好"):
        bullish_bias += weights["events"] * (0.40 if ev_rating == "强烈利好" else 0.20)
    elif ev_rating in ("强烈利空", "偏利空"):
        bearish_bias += weights["events"] * (0.40 if ev_rating == "强烈利空" else 0.20)

    # 事件分数的细化影响
    if ev_score:
        # ev_score通常在[-20, +20]范围，线性缩放到[-0.2, +0.2]
        scaled = max(-0.2, min(0.2, ev_score / 100.0 * 10))
        if scaled > 0:
            bullish_bias += weights["events"] * scaled
        else:
            bearish_bias += weights["events"] * abs(scaled)

    # 参数调整逻辑
    # 温度：偏空/高风险 -> 降低；偏多/低风险 -> 略提高但限制范围
    T_adj = -0.15 * min(bearish_bias, 0.25) + 0.12 * max(bullish_bias, 0.0)
    T += T_adj  # 偏空(负值)降低温度，偏多(正值)提高温度
    T = _clip(T, 0.50, 0.85)

    # top_p：高风险/偏空 -> 降低；偏多/低风险 -> 小幅提高
    top_p_adj = -0.10 * min(risk_score + bearish_bias, 0.40) + 0.05 * max(bullish_bias, 0.0)
    top_p += top_p_adj
    top_p = _clip(top_p, 0.80, 0.95)

    # sample_count：风险越高越增大；若强一致偏多且风险低可保持或减至2以提升速度
    if risk_score >= 0.35:
        sample_count = 5
    elif risk_score >= 0.20:
        sample_count = 4
    else:
        sample_count = 3
    if bullish_bias > 0.25 and risk_score < 0.15:
        sample_count = max(2, sample_count - 1)

    reason = _build_reason(
        guba_score, guba_bull, guba_bear,
        market_score, market_change, market_emotion,
        sector_score, sector_change, sector_turnover, sector_emotion,
        risk_score, bullish_bias, bearish_bias,
        ev_rating, ev_risk_level, ev_opp_level, ev_pos, ev_neg, ev_score
    )

    return {
        "T": round(T, 2),
        "top_p": round(top_p, 2),
        "sample_count": int(sample_count),
        "reason": reason,
        "weights": weights,
    }


def _to_num(x, default=0.0):
    try:
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            return float(x)
    except Exception:
        pass
    return float(default)


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def _build_reason(gs, gb, ge, ms, mc, me, ss, sc, st, se, rsk, bb, beb,
                  ev_rating, ev_risk, ev_opp, ev_pos, ev_neg, ev_score):
    ev_part = ""
    if ev_rating is not None:
        ev_part = (
            f" | 事件:评级{ev_rating} 风险{ev_risk} 机会{ev_opp} "
            f"利好{ev_pos} 利空{ev_neg} 分:{ev_score:+.0f}"
        )
    return (
        f"股吧分:{gs} 看多{gb}% 看空{ge}% | "
        f"大盘:{me} 所属涨跌{mc:+.2f}% 分:{ms} | "
        f"板块:{se} 涨跌{sc:+.2f}% 换手{st:.2f}% 分:{ss} | "
        f"风险:{rsk:.2f} 偏多:{bb:.2f} 偏空:{beb:.2f}" + ev_part
    )