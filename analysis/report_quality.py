"""多空评审团 LLM 覆盖层机械质量门（P0-B，spec §8 / §8.1）。

纯函数,无 I/O,不调 LLM、不落库。出 AI 点评前强制跑:
- 🔴 critical 命中 → passed=False（调用方降级 reviewed + 红条 + 回退规则文案）
- 🟡 warning 命中 → 软旗标,不影响 passed

不 import analysis.sector_api（其 import 触发 Tushare 行业缓存加载,重副作用）。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

# 占位符标记（高精度集合,避免误拦合法中文点评）。
_PLACEHOLDER_MARKERS = (
    "[脚本占位]", "占位符", "占位", "todo", "tbd", "待补充", "待填写", "{{", "}}",
)


def evaluate_overlay(
    overlay: Optional[Dict[str, Any]],
    panel: Optional[Dict[str, Any]],
    payload: Optional[Dict[str, Any]],
    tier: str,
) -> Dict[str, Any]:
    """返回 {"passed": bool, "criticals": [str], "warnings": [str]}。

    passed=False 当且仅当任一 🔴 命中。仅应在结构合法（reviewed 将为 True）的
    overlay 上调用；lite/未配置/非法 JSON 的 overlay 走既有「未生成」路径,不在此判定。
    """
    overlay = overlay or {}
    panel = panel or {}
    criticals: List[str] = []
    warnings: List[str] = []

    texts = list(_iter_overlay_texts(overlay))

    # 🔴 无占位符残留
    flagged = next((t for t in texts if _has_placeholder(t)), None)
    if flagged is not None:
        criticals.append(f"检测到占位符残留：{flagged.strip()[:30]}")

    # 🔴 punchline 非空（medium 及以上）
    punchline = ((overlay.get("great_divide_override") or {}).get("punchline") or "").strip()
    if not punchline:
        criticals.append("great_divide_override.punchline 为空")

    if tier == "deep":
        # 🔴 逐人覆盖：两位头牌（bull/bear）必须有非空 insight
        criticals.extend(_missing_headline_insights(overlay, panel))
        # 🔴 buy_zones ≥1 档非空（至少一个可操作区间）
        if not _has_actionable_zone(overlay.get("buy_zones")):
            criticals.append("buy_zones 四档均为空（无可操作区间）")

    return {"passed": not criticals, "criticals": criticals, "warnings": warnings}


def _iter_overlay_texts(overlay: Dict[str, Any]) -> Iterable[str]:
    """遍历 overlay 里所有自由文本（占位符检测 + FACTCHECK 共用）。"""
    gd = overlay.get("great_divide_override") or {}
    if isinstance(gd.get("punchline"), str):
        yield gd["punchline"]
    for r in overlay.get("risks") or []:
        if isinstance(r, str):
            yield r
    for v in (overlay.get("panel_insights") or {}).values():
        if isinstance(v, str):
            yield v
    if isinstance(overlay.get("narrative_override"), str):
        yield overlay["narrative_override"]
    bz = overlay.get("buy_zones") or {}
    if isinstance(bz, dict):
        for items in bz.values():
            for it in items or []:
                if isinstance(it, str):
                    yield it


def _has_placeholder(text: str) -> bool:
    low = (text or "").lower()
    return any(marker.lower() in low for marker in _PLACEHOLDER_MARKERS)


def _missing_headline_insights(overlay: Dict[str, Any], panel: Dict[str, Any]) -> List[str]:
    """deep 档：great_divide 的 bull/bear 头牌必须在 panel_insights 里有非空点评。"""
    gd = (panel or {}).get("great_divide") or {}
    insights = overlay.get("panel_insights") or {}
    out: List[str] = []
    for role in ("bull", "bear"):
        person = gd.get(role) or {}
        pid = person.get("id")
        if not pid:
            continue
        val = insights.get(pid)
        if not (isinstance(val, str) and val.strip()):
            out.append(f"逐人点评缺失头牌：{person.get('name') or pid}（{role}）")
    return out


def _has_actionable_zone(buy_zones: Any) -> bool:
    if not isinstance(buy_zones, dict):
        return False
    return any(isinstance(v, list) and len(v) > 0 for v in buy_zones.values())
