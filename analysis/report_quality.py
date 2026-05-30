"""多空评审团 LLM 覆盖层机械质量门（P0-B，spec §8 / §8.1）。

纯函数,无 I/O,不调 LLM、不落库。出 AI 点评前强制跑:
- 🔴 critical 命中 → passed=False（调用方降级 reviewed + 红条 + 回退规则文案）
- 🟡 warning 命中 → 软旗标,不影响 passed

不 import analysis.sector_api（其 import 触发 Tushare 行业缓存加载,重副作用）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

# 占位符标记（高精度集合,避免误拦合法中文点评）。
_PLACEHOLDER_MARKERS = (
    "[脚本占位]", "占位符", "占位", "todo", "tbd", "待补充", "待填写", "{{", "}}",
)

# 抽数字 token（千分位 / 小数 / 负号）。% 与 亿/万 单位后缀由匹配时多尺度容差处理。
_NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")
_FACTCHECK_MIN_ABS = 10.0   # |v|<10 的数（序号/小计数/常识）豁免,避免误报
_FACTCHECK_REL_TOL = 0.02   # 容差 |n-v| <= max(0.5, |v|*2%)


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

    # 🟡 风险 ≥ 3 条
    if sum(1 for r in (overlay.get("risks") or []) if isinstance(r, str) and r.strip()) < 3:
        warnings.append("风险条目少于 3 条")

    # 🟡 FACTCHECK（轻量）：overlay 引用数字须能在 payload 找到出处
    unverifiable = _factcheck_numbers(texts, panel, payload or {})
    if unverifiable:
        warnings.append("以下数字未能在数据中找到出处：" + "、".join(unverifiable[:5]))

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


def _norm_num(token: str) -> Optional[float]:
    try:
        return float(token.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _payload_number_set(panel: Dict[str, Any], payload: Dict[str, Any]) -> set:
    """递归收集 panel+payload 内所有数值（含字符串里的数字），归一化为浮点。"""
    found: set = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            found.add(round(float(obj), 2))
        elif isinstance(obj, str):
            for tok in _NUM_RE.findall(obj):
                v = _norm_num(tok)
                if v is not None:
                    found.add(round(v, 2))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    walk(panel)
    walk(payload)
    return found


def _close_to_any(v: float, number_set: set) -> bool:
    """v 在 原值/万/亿 三种尺度上任一接近 payload 数值即视作有出处（保守,少误报）。"""
    for scale in (1.0, 1e4, 1e8):
        scaled = v * scale
        tol = max(0.5, abs(scaled) * _FACTCHECK_REL_TOL)
        if any(abs(n - scaled) <= tol for n in number_set):
            return True
    return False


def _factcheck_numbers(texts: List[str], panel: Dict[str, Any], payload: Dict[str, Any]) -> List[str]:
    number_set = _payload_number_set(panel, payload)
    unverifiable: List[str] = []
    seen: set = set()
    for text in texts:
        for tok in _NUM_RE.findall(text):
            if tok in seen:
                continue
            seen.add(tok)
            v = _norm_num(tok)
            if v is None or abs(v) < _FACTCHECK_MIN_ABS:
                continue
            if not _close_to_any(v, number_set):
                unverifiable.append(tok)
    return unverifiable
