"""overlay 提示构造 + LLM 返回的 JSON 抽取。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

# 各档要求 LLM 产出的字段说明（提示里展示，也与 schema.validate_overlay 对齐）
_TIER_FIELDS = {
    "medium": (
        '  "great_divide_override": {"punchline": "<一句可传播的多空金句，<=40 字>"},\n'
        '  "risks": ["<风险点1>", "<风险点2>", "<风险点3>"]'
    ),
    "deep": (
        '  "great_divide_override": {"punchline": "<一句可传播的多空金句，<=40 字>"},\n'
        '  "risks": ["<风险点1>", "<风险点2>", "<风险点3>"],\n'
        '  "panel_insights": {"<persona_id>": "<该投资人视角的一句点评>"},\n'
        '  "buy_zones": {"value": ["<价值派买点>"], "growth": [], "technical": [], "youzi": []},\n'
        '  "narrative_override": "<一句话总览，可省略>"'
    ),
}


def _panel_digest(panel: Dict[str, Any]) -> str:
    """把 panel 关键信息压成提示用的紧凑摘要。"""
    c = panel.get("consensus") or {}
    gd = panel.get("great_divide") or {}
    bull = gd.get("bull") or {}
    bear = gd.get("bear") or {}
    lines = [
        f"- 共识温度：{c.get('score', '—')} / 100（{c.get('label', '—')}）；"
        f"多 {c.get('bull', 0)} · 观望 {c.get('neutral', 0)} · 空 {c.get('bear', 0)}",
        f"- 最强多头：{bull.get('name', '—')}（{bull.get('score', '—')}）；"
        f"最强空头：{bear.get('name', '—')}（{bear.get('score', '—')}）",
    ]
    analysts = panel.get("analysts") or []
    top = sorted(analysts, key=lambda a: a.get("score", 0), reverse=True)[:6]
    bot = sorted(analysts, key=lambda a: a.get("score", 0))[:4]
    lines.append("- 旗舰多头观点：" + "；".join(
        f"{a.get('name')}({a.get('id')})：{a.get('headline', '')}" for a in top) or "- 旗舰多头观点：无")
    lines.append("- 旗舰空头/谨慎观点：" + "；".join(
        f"{a.get('name')}({a.get('id')})：{a.get('headline', '')}" for a in bot) or "- 旗舰空头观点：无")
    inds = panel.get("indicators") or []
    fresh = [i for i in inds if i.get("data_status") != "unavailable"]
    if fresh:
        lines.append("- 量化指标：" + "；".join(
            f"{i.get('label')} {i.get('value_text')}({i.get('signal')})" for i in fresh))
    return "\n".join(lines)


def build_overlay_prompt(panel: Dict[str, Any], payload: Dict[str, Any], tier: str) -> str:
    """构造"只返回 JSON"的覆盖层提示。tier ∈ {medium, deep}（lite 不调 LLM，不会进这里）。"""
    stock = (payload or {}).get("stock") or {}
    fields = _TIER_FIELDS.get(tier, _TIER_FIELDS["medium"])
    digest = _panel_digest(panel or {})
    reqs = [
        "只能依据上面给出的数据，不得编造未提供的数字或产业链信息。",
        "punchline 要短、有传播力，体现最强多头与最强空头的核心分歧。",
    ]
    if tier == "deep":
        reqs.append("panel_insights 的键必须用上面出现过的 persona_id（如 zhao / graham / buffett）。")
    reqs.append("**只返回 JSON，不要任何额外文字、不要 markdown 说明**。JSON 结构如下：")
    req_block = "\n".join(f"{i}. {r}" for i, r in enumerate(reqs, 1))
    return (
        f"你是一位资深 A 股操盘手。下面是「{stock.get('name', '')}（{stock.get('code', '')}）」"
        "的多空评审团规则引擎结论，请基于这些数据写一层点评覆盖。\n\n"
        f"【规则引擎结论】\n{digest}\n\n"
        "【要求】\n"
        f"{req_block}\n"
        "{\n"
        f"{fields}\n"
        "}\n"
    )


def extract_overlay_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 文本抽 JSON：优先 ```json 围栏，其次裸 {…}。失败返回 None。"""
    if not text or not isinstance(text, str):
        return None
    fenced = re.findall(r"```json\s*(.*?)\s*```", text, re.S)
    candidates = fenced if fenced else re.findall(r"(\{[\s\S]*\})", text)
    if not candidates:
        return None
    try:
        result = json.loads(candidates[0])
    except (json.JSONDecodeError, ValueError):
        return None
    return result if isinstance(result, dict) else None
