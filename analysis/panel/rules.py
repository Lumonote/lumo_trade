"""12 旗舰手写规则 + 7 流派默认规则。规则纯函数，容忍 None 特征。"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

Features = Dict[str, Any]
Verdict = Dict[str, Any]


def _clamp(x: float, lo: int = 0, hi: int = 100) -> int:
    return int(round(max(lo, min(hi, x))))


def score_to_signal(score: int) -> str:
    if score >= 60:
        return "bull"
    if score <= 40:
        return "bear"
    return "neutral"


# ---------- A 价值派旗舰 ----------
def rule_buffett(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 20:
            score += 25; reasons.append(f"ROE {roe:.0f}% 优秀，护城河深厚")
        elif roe >= 15:
            score += 12; reasons.append(f"ROE {roe:.0f}% 稳健")
        elif roe < 8:
            score -= 20; reasons.append(f"ROE {roe:.0f}% 偏低，缺乏护城河")
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank <= 30:
            score += 15; reasons.append("行业估值分位低，有安全边际")
        elif rank >= 80:
            score -= 15; reasons.append("估值偏贵，安全边际不足")
    yoy = f.get("net_profit_yoy")
    if yoy is not None and yoy < 0:
        score -= 10; reasons.append("利润负增长，长期价值受损")
    return {"score": _clamp(score), "reasons": reasons}


def rule_munger(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 18:
            score += 28; reasons.append(f"高质量生意 ROE {roe:.0f}%")
        elif roe < 10:
            score -= 22; reasons.append("生意质量平庸")
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank >= 85:
            score -= 18; reasons.append("好公司但出价过高")
        elif rank <= 40:
            score += 10; reasons.append("合理价格的好公司")
    return {"score": _clamp(score), "reasons": reasons}


def rule_graham(f: Features) -> Verdict:
    score, reasons = 50.0, []
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank <= 20:
            score += 30; reasons.append("深度低估，烟蒂级安全边际")
        elif rank <= 40:
            score += 12; reasons.append("估值偏低")
        elif rank >= 60:
            score -= 25; reasons.append("估值超出安全边际，不碰")
    pb = f.get("pb")
    if pb is not None:
        if pb < 1.0:
            score += 12; reasons.append(f"破净 PB {pb:.2f}")
        elif pb > 5.0:
            score -= 10; reasons.append(f"PB {pb:.1f} 过高")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- B 成长派旗舰 ----------
def rule_fisher(f: Features) -> Verdict:
    score, reasons = 50.0, []
    yoy = f.get("net_profit_yoy")
    if yoy is not None:
        if yoy >= 30:
            score += 28; reasons.append(f"利润高增长 {yoy:.0f}%")
        elif yoy >= 15:
            score += 14; reasons.append(f"利润增长 {yoy:.0f}%")
        elif yoy < 0:
            score -= 22; reasons.append("成长性恶化")
    roe = f.get("roe")
    if roe is not None and roe >= 15:
        score += 8; reasons.append("高质量成长")
    return {"score": _clamp(score), "reasons": reasons}


def rule_lynch(f: Features) -> Verdict:
    score, reasons = 50.0, []
    yoy, pe = f.get("net_profit_yoy"), f.get("pe")
    if yoy is not None and pe is not None and pe > 0 and yoy > 0:
        peg = pe / yoy
        if peg < 1.0:
            score += 26; reasons.append(f"PEG {peg:.2f}<1，成长价廉")
        elif peg <= 1.5:
            score += 10; reasons.append(f"PEG {peg:.2f} 合理")
        elif peg > 2.0:
            score -= 20; reasons.append("成长配不上估值")
    elif yoy is not None and yoy >= 20:
        score += 12; reasons.append(f"高成长 {yoy:.0f}%")
    elif yoy is not None and yoy < 0:
        score -= 18; reasons.append("成长熄火")
    return {"score": _clamp(score), "reasons": reasons}


def rule_wood(f: Features) -> Verdict:
    score, reasons = 50.0, []
    yoy = f.get("net_profit_yoy")
    if yoy is not None and yoy >= 25:
        score += 22; reasons.append("高增长赛道")
    ratio = f.get("model_bull_ratio")
    if ratio is not None:
        if ratio >= 0.6:
            score += 18; reasons.append("趋势动能强劲")
        elif ratio <= 0.3:
            score -= 16; reasons.append("动能转弱")
    vol = f.get("volume_ratio")
    if vol is not None and vol >= 1.5:
        score += 8; reasons.append("放量关注度高")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- C 宏观派旗舰 ----------
def rule_soros(f: Features) -> Verdict:
    score, reasons = 50.0, []
    regime = f.get("market_regime")
    if regime == "bull":
        score += 16; reasons.append("顺大势：牛市趋势可加杠杆")
    elif regime == "bear":
        score -= 18; reasons.append("逆大势：熊市风险高")
    mh = f.get("macd_hist")
    if mh is not None:
        if mh > 0:
            score += 12; reasons.append("MACD 动能向上，反身性正反馈")
        else:
            score -= 12; reasons.append("MACD 动能向下")
    return {"score": _clamp(score), "reasons": reasons}


def rule_dalio(f: Features) -> Verdict:
    score, reasons = 50.0, []
    regime = f.get("market_regime")
    if regime == "bull":
        score += 10; reasons.append("经济机器扩张期")
    elif regime == "bear":
        score -= 14; reasons.append("去杠杆周期，防御为主")
    rsi = f.get("rsi")
    if rsi is not None and (rsi >= 80 or rsi <= 20):
        score -= 10; reasons.append("情绪极端，风险平价减仓")
    yoy = f.get("net_profit_yoy")
    if yoy is not None and yoy > 0:
        score += 6; reasons.append("基本面稳健")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- E 中国价投旗舰 ----------
def rule_duan(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 18:
            score += 24; reasons.append(f"好生意 ROE {roe:.0f}%，本分经营")
        elif roe < 8:
            score -= 18; reasons.append("商业模式一般")
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank <= 35:
            score += 14; reasons.append("价格合理，看长期")
        elif rank >= 85:
            score -= 12; reasons.append("贵了，宁可错过")
    return {"score": _clamp(score), "reasons": reasons}


def rule_zhangkun(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 20:
            score += 26; reasons.append(f"高 ROE {roe:.0f}% 优质龙头，长期持有")
        elif roe < 10:
            score -= 20; reasons.append("非优质资产")
    yoy = f.get("net_profit_yoy")
    if yoy is not None and yoy >= 10:
        score += 10; reasons.append("业绩稳定增长")
    rank = f.get("pe_industry_rank")
    if rank is not None and rank >= 90:
        score -= 10; reasons.append("估值偏高需耐心")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- F 游资派旗舰 ----------
def rule_zhao(f: Features) -> Verdict:
    score, reasons = 50.0, []
    seats = f.get("quant_seat_appearances")
    if seats is not None:
        if seats >= 3:
            score += 26; reasons.append(f"量化席位 90 日 {int(seats)} 次活跃")
        elif seats >= 1:
            score += 12; reasons.append("龙虎榜量化席位进场")
    main = f.get("main_net_inflow")
    if main is not None:
        if main > 0:
            score += 12; reasons.append("主力净流入承接")
        else:
            score -= 12; reasons.append("主力净流出")
    vol = f.get("volume_ratio")
    if vol is not None and vol >= 1.8:
        score += 10; reasons.append("放量打板情绪高")
    return {"score": _clamp(score), "reasons": reasons}


def rule_zhang_mz(f: Features) -> Verdict:
    score, reasons = 50.0, []
    net = f.get("lhb_net_inst_buy")
    if net is not None:
        if net > 0:
            score += 22; reasons.append("龙虎榜机构净买，龙头属性")
        else:
            score -= 16; reasons.append("龙虎榜净卖出，分歧加大")
    vol = f.get("volume_ratio")
    if vol is not None and vol >= 1.5:
        score += 14; reasons.append("放量做龙头")
    main = f.get("main_net_inflow")
    if main is not None and main > 0:
        score += 8; reasons.append("主力流入助攻")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- 7 流派默认规则（48 stub 用）----------
def rule_value_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 15:
            score += 16; reasons.append(f"ROE {roe:.0f}% 良好")
        elif roe < 8:
            score -= 16; reasons.append("盈利能力偏弱")
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank <= 35:
            score += 12; reasons.append("估值偏低")
        elif rank >= 80:
            score -= 12; reasons.append("估值偏高")
    return {"score": _clamp(score), "reasons": reasons}


def rule_growth_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    yoy = f.get("net_profit_yoy")
    if yoy is not None:
        if yoy >= 25:
            score += 20; reasons.append(f"利润增长 {yoy:.0f}%")
        elif yoy >= 10:
            score += 8; reasons.append("稳健增长")
        elif yoy < 0:
            score -= 18; reasons.append("成长性走弱")
    return {"score": _clamp(score), "reasons": reasons}


def rule_macro_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    regime = f.get("market_regime")
    if regime == "bull":
        score += 14; reasons.append("大盘趋势向上")
    elif regime == "bear":
        score -= 16; reasons.append("大盘风险偏高")
    else:
        reasons.append("大盘震荡，中性观望")
    return {"score": _clamp(score), "reasons": reasons}


def rule_technical_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    rsi = f.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            score -= 12; reasons.append(f"RSI {rsi:.0f} 超买")
        elif rsi <= 30:
            score += 12; reasons.append(f"RSI {rsi:.0f} 超卖待反弹")
    mh = f.get("macd_hist")
    if mh is not None:
        if mh > 0:
            score += 10; reasons.append("MACD 红柱")
        else:
            score -= 10; reasons.append("MACD 绿柱")
    ma = f.get("ma_alignment")
    if ma == "bull":
        score += 12; reasons.append("均线多头排列")
    elif ma == "bear":
        score -= 12; reasons.append("均线空头排列")
    return {"score": _clamp(score), "reasons": reasons}


def rule_youzi_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    seats = f.get("quant_seat_appearances")
    if seats is not None and seats >= 1:
        score += 14; reasons.append("龙虎榜活跃")
    main = f.get("main_net_inflow")
    if main is not None:
        if main > 0:
            score += 12; reasons.append("主力净流入")
        else:
            score -= 12; reasons.append("主力净流出")
    vol = f.get("volume_ratio")
    if vol is not None and vol >= 1.5:
        score += 8; reasons.append("放量")
    return {"score": _clamp(score), "reasons": reasons}


def rule_quant_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    ratio = f.get("model_bull_ratio")
    if ratio is not None:
        if ratio >= 0.6:
            score += 22; reasons.append(f"30 模型 {int(ratio * 100)}% 看多共振")
        elif ratio <= 0.35:
            score -= 20; reasons.append(f"30 模型仅 {int(ratio * 100)}% 看多")
        else:
            reasons.append("模型多空胶着")
    return {"score": _clamp(score), "reasons": reasons}


RULES: Dict[str, Callable[[Features], Verdict]] = {
    "buffett": rule_buffett, "munger": rule_munger, "graham": rule_graham,
    "fisher": rule_fisher, "lynch": rule_lynch, "wood": rule_wood,
    "soros": rule_soros, "dalio": rule_dalio,
    "duan": rule_duan, "zhangkun": rule_zhangkun,
    "zhao": rule_zhao, "zhang_mz": rule_zhang_mz,
}

SCHOOL_DEFAULTS: Dict[str, Callable[[Features], Verdict]] = {
    "A": rule_value_default, "B": rule_growth_default, "C": rule_macro_default,
    "D": rule_technical_default, "E": rule_value_default,
    "F": rule_youzi_default, "G": rule_quant_default,
}


def resolve_rule(rule_key: str, school: str) -> Callable[[Features], Verdict]:
    """旗舰用 rule_key；stub 的 'school_default' 解析到流派默认规则。"""
    if rule_key == "school_default":
        return SCHOOL_DEFAULTS[school]
    return RULES[rule_key]


# ---------- stub 差异化：persona 的 key_metrics → 特征微调 ----------
# 48 个 stub 原本共用 7 个默认规则，导致同流派打分完全一致。这里让每个 stub
# 在流派默认裁决之上，按自己声明的 key_metrics 叠加“偏好微调”，使同流派成员
# 因关注指标不同而分化；同时只有当 key_metrics 对应的特征确有数据时才打分，
# 否则该 persona 标记为“数据不足”（reasons 为空 → 上游 data_insufficient）。

# key_metrics 语义 token → 实际特征键（None = 暂无对应特征，跳过不计分）
METRIC_FEATURE: Dict[str, Any] = {
    "roe": "roe",
    "pe_industry_rank": "pe_industry_rank",
    "pb": "pb",
    "net_profit_yoy": "net_profit_yoy",
    "revenue_yoy": None,          # 营收同比暂无特征，不参与计分
    "trend": "ma_alignment",
    "momentum": "macd_hist",
    "volatility": "boll_position",
    "volume": "volume_ratio",
}

# 各流派默认规则已读取的特征：避免 key_metrics 微调与默认规则重复计分
BASE_FEATURES: Dict[str, set] = {
    "A": {"roe", "pe_industry_rank"},
    "B": {"net_profit_yoy"},
    "C": {"market_regime"},
    "D": {"rsi", "macd_hist", "ma_alignment"},
    "E": {"roe", "pe_industry_rank"},
    "F": {"quant_seat_appearances", "main_net_inflow", "volume_ratio"},
    "G": {"model_bull_ratio"},
}


def _nudge_metric(token: str, f: Features):
    """返回 (delta, reason)。reason=None 表示该指标无数据（不计分、不计入“有据”）。
    有数据时即便方向中性也返回一句 reason，确保 data_insufficient 仅代表真无数据。"""
    feat = METRIC_FEATURE.get(token)
    if feat is None:
        return 0.0, None
    v = f.get(feat)
    if v is None:
        return 0.0, None
    if token == "roe":
        if v >= 15:
            return 10.0, f"ROE {v:.0f}% 良好"
        if v < 8:
            return -10.0, f"ROE {v:.0f}% 偏弱"
        return 3.0, f"ROE {v:.0f}% 中等"
    if token == "pe_industry_rank":
        if v <= 35:
            return 9.0, "行业估值分位偏低"
        if v >= 80:
            return -9.0, "行业估值分位偏高"
        return 2.0, "行业估值分位中性"
    if token == "pb":
        if v < 1.5:
            return 8.0, f"PB {v:.2f} 安全垫厚"
        if v > 8:
            return -8.0, f"PB {v:.1f} 偏高"
        return 2.0, f"PB {v:.1f} 适中"
    if token == "net_profit_yoy":
        if v >= 25:
            return 12.0, f"净利同比 +{v:.0f}%"
        if v >= 10:
            return 6.0, f"净利同比 +{v:.0f}%"
        if v < 0:
            return -12.0, f"净利同比 {v:.0f}%"
        return 2.0, f"净利同比 +{v:.0f}%"
    if token == "trend":
        if v == "bull":
            return 9.0, "均线多头排列"
        if v == "bear":
            return -9.0, "均线空头排列"
        return 0.0, "均线缠绕，方向不明"
    if token == "momentum":
        if v > 0:
            return 7.0, "MACD 动能向上"
        if v < 0:
            return -7.0, "MACD 动能向下"
        return 0.0, "动能持平"
    if token == "volatility":
        if v >= 0.85:
            return -6.0, "布林上轨，波动加剧"
        if v <= 0.15:
            return 6.0, "布林下轨，超跌企稳"
        return 0.0, "布林中轨，波动可控"
    if token == "volume":
        if v >= 1.8:
            return 8.0, f"放量 量比 {v:.1f}"
        if v >= 1.2:
            return 4.0, f"温和放量 量比 {v:.1f}"
        if v < 0.7:
            return -5.0, f"缩量 量比 {v:.1f}"
        return 1.0, f"量能正常 量比 {v:.1f}"
    return 0.0, None


def eval_school_default(features: Features, persona: Dict[str, Any]) -> Verdict:
    """stub 专用：流派默认裁决 + 该 persona key_metrics 的偏好微调。
    首位 key_metric 视为主视角(权重 1.0)，其余为辅(0.7)，使同对指标但顺序不同的
    persona 也能轻微分化。reasons 为空 ⟺ 该 persona 关注的指标全无数据。"""
    school = persona["school"]
    base = SCHOOL_DEFAULTS[school](features)
    score = float(base["score"])
    reasons: List[str] = list(base.get("reasons") or [])
    used = set(BASE_FEATURES.get(school, ()))
    for idx, token in enumerate(persona.get("key_metrics") or []):
        feat = METRIC_FEATURE.get(token)
        if feat is None or feat in used:
            continue
        delta, reason = _nudge_metric(token, features)
        if reason is None:          # 该指标无数据
            continue
        used.add(feat)
        score += delta * (1.0 if idx == 0 else 0.7)
        if reason not in reasons:
            reasons.append(reason)
    return {"score": _clamp(score), "reasons": reasons}
