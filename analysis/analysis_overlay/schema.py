"""overlay 结构/类型校验（手写，不引 jsonschema）。

只校验结构与类型；语义质量门（覆盖度/占位符/FACTCHECK/行业 sanity）属后续 P0-B 计划。
返回中文错误列表（空列表 = 通过），错误文案会被回喂给 LLM 触发重试。
"""
from __future__ import annotations

from typing import Any, List

TIERS = ("lite", "medium", "deep")

_BUY_ZONE_BUCKETS = ("value", "growth", "technical", "youzi")


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_overlay(obj: Any, tier: str) -> List[str]:
    """返回错误字符串列表；空列表表示通过。lite 档无结构要求。"""
    if tier == "lite":
        return []
    if not isinstance(obj, dict):
        return ["overlay 必须是 JSON 对象"]

    errors: List[str] = []

    # medium 及以上：金句 + 风险
    gd = obj.get("great_divide_override")
    if not isinstance(gd, dict) or not _nonempty_str(gd.get("punchline")):
        errors.append("缺少 great_divide_override.punchline（非空字符串）")
    risks = obj.get("risks")
    if not isinstance(risks, list) or not all(isinstance(r, str) for r in risks):
        errors.append("risks 必须是字符串数组")

    if tier == "deep":
        insights = obj.get("panel_insights")
        if not isinstance(insights, dict) or len(insights) == 0:
            errors.append("panel_insights 必须是非空对象 {persona_id: 点评}")
        elif not all(isinstance(k, str) and isinstance(v, str) for k, v in insights.items()):
            errors.append("panel_insights 的键与值都必须是字符串")
        buy_zones = obj.get("buy_zones")
        if not isinstance(buy_zones, dict):
            errors.append("缺少 buy_zones 对象（需含 value/growth/technical/youzi）")
        else:
            for bucket in _BUY_ZONE_BUCKETS:
                if not isinstance(buy_zones.get(bucket), list):
                    errors.append(f"buy_zones.{bucket} 必须是数组")
        # narrative_override 可选，但若出现必须是字符串
        nar = obj.get("narrative_override")
        if nar is not None and not isinstance(nar, str):
            errors.append("narrative_override 若提供必须是字符串")

    return errors
