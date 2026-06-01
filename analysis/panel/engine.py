"""panel 聚合：裁决全部 persona → 共识 / 大分歧 / 流派。纯规则。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from analysis.panel.registry import SCHOOLS
from analysis.panel.rules import resolve_rule, score_to_signal
from analysis.panel.style import (
    classify_style, load_style_weights, school_style_weight,
)


def consensus_label(score: float) -> str:
    if score >= 65:
        return "强烈看多"
    if score >= 55:
        return "偏多"
    if score >= 45:
        return "中性"
    if score >= 35:
        return "偏空"
    return "强烈看空"


def lean_label(score: float) -> str:
    if score >= 55:
        return "偏多"
    if score >= 45:
        return "中性"
    return "偏空"


def evaluate_all(personas: List[Dict[str, Any]], features: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in personas:
        rule_fn = resolve_rule(p["rule"], p["school"])
        verdict = rule_fn(features)
        score = int(verdict["score"])
        reasons = verdict.get("reasons") or []
        headline = reasons[0] if reasons else p.get("voice", "—")
        out.append({
            "id": p["id"],
            "name": p["name"],
            "school": p["school"],
            "signal": score_to_signal(score),
            "score": score,
            "headline": headline,
            "voice": p.get("voice", ""),  # 投资风格一句话（前端悬停展示）
            "key_metrics": p.get("key_metrics", []),  # 该 persona 关注的核心指标（前端悬停展示）
            "source": "handwritten" if p["tier"] == "flagship" else "rule",
            "reasons": reasons,
        })
    return out


def compute_consensus(analysts: List[Dict[str, Any]], style: str) -> Dict[str, Any]:
    weights = load_style_weights()
    num = den = 0.0
    bull = bear = neutral = 0
    for a in analysts:
        w = school_style_weight(a["school"], style, weights)
        num += a["score"] * w
        den += w
        if a["signal"] == "bull":
            bull += 1
        elif a["signal"] == "bear":
            bear += 1
        else:
            neutral += 1
    score = int(round(num / den)) if den else 50
    return {"score": score, "label": consensus_label(score),
            "bull": bull, "neutral": neutral, "bear": bear}


def _slim(a: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if a is None:
        return None
    return {"id": a["id"], "name": a["name"], "school": a["school"], "score": a["score"]}


def compute_great_divide(analysts: List[Dict[str, Any]]) -> Dict[str, Any]:
    bulls = [a for a in analysts if a["signal"] == "bull"]
    bears = [a for a in analysts if a["signal"] == "bear"]
    top_bull = max(bulls, key=lambda a: a["score"]) if bulls else None
    top_bear = min(bears, key=lambda a: a["score"]) if bears else None
    if top_bull and top_bear:
        bull_reason = (top_bull["reasons"] or ["看多"])[0]
        bear_reason = (top_bear["reasons"] or ["看空"])[0]
        punchline = f"{top_bull['name']} 看到 {bull_reason}，{top_bear['name']} 担心 {bear_reason}"
    elif top_bull:
        punchline = f"{top_bull['name']} 领衔看多，暂无明确看空声音"
    elif top_bear:
        punchline = f"{top_bear['name']} 领衔看空，暂无明确看多声音"
    else:
        punchline = "多空分歧不明显，全员观望"
    return {"bull": _slim(top_bull), "bear": _slim(top_bear), "punchline": punchline}


def compute_schools(analysts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, name in SCHOOLS.items():
        members = [a for a in analysts if a["school"] == key]
        if members:
            lean_score = int(round(sum(a["score"] for a in members) / len(members)))
        else:
            lean_score = 50
        out.append({
            "key": key, "name": name, "count": len(members),
            "lean": lean_label(lean_score), "lean_score": lean_score,
        })
    return out


def classify_panel_style(features: Dict[str, Any]) -> str:
    return classify_style(features)
