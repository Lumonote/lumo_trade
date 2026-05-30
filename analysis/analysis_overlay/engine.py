"""overlay 引擎：调用 LLM（依赖注入）→ 抽 JSON → 校验 → 重试/回退；merge 叠加到 panel。"""
from __future__ import annotations

import copy
import datetime as _dt
from typing import Any, Callable, Dict, List, Optional, Tuple

from analysis.analysis_overlay.prompt import build_overlay_prompt, extract_overlay_json
from analysis.analysis_overlay.schema import TIERS, validate_overlay

LlmCaller = Callable[[str], Tuple[bool, str]]

# overlay 产物里需要透传给前端/合并的字段
_PASS_FIELDS = ("great_divide_override", "risks", "panel_insights", "buy_zones", "narrative_override")


def _default_llm_caller(prompt: str) -> Tuple[bool, str]:
    """默认 caller：薄封装既有 LLMAnalyzer（用 requests 调 DeepSeek）。无 key 时返回 (False, 原因)。"""
    from analysis.llm_service import LLMAnalyzer
    ok, text, _tokens = LLMAnalyzer().interpret_stock_markdown({"prompt": prompt})
    return bool(ok), str(text)


def _now_iso(now_iso: Optional[str]) -> str:
    return now_iso if now_iso else _dt.datetime.now().isoformat(timespec="seconds")


def _unavailable(tier: str, reason: str, now_iso: Optional[str]) -> Dict[str, Any]:
    return {
        "data_status": "unavailable",
        "last_updated": _now_iso(now_iso),
        "reviewed": False,
        "tier": tier,
        "great_divide_override": None,
        "risks": [],
        "panel_insights": {},
        "buy_zones": None,
        "narrative_override": None,
        "reason": reason,
    }


def _looks_unconfigured(text: str) -> bool:
    t = text or ""
    return ("未配置" in t) or ("API Key" in t) or ("api key" in t.lower())


def _success(obj: Dict[str, Any], tier: str, now_iso: Optional[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "data_status": "fresh",
        "last_updated": _now_iso(now_iso),
        "reviewed": True,
        "tier": tier,
        "reason": None,
    }
    for f in _PASS_FIELDS:
        out[f] = obj.get(f)
    if out.get("risks") is None:
        out["risks"] = []
    if out.get("panel_insights") is None:
        out["panel_insights"] = {}
    return out


def build_overlay(
    panel: Dict[str, Any],
    payload: Dict[str, Any],
    tier: str,
    *,
    llm_caller: Optional[LlmCaller] = None,
    retries: int = 2,
    now_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """生成 overlay。lite 不调 LLM；medium/deep 调用 + 校验 + 至多 retries 次重试，全失败回退。"""
    if tier not in TIERS:
        tier = "medium"
    if tier == "lite":
        return _unavailable("lite", "lite 档不调用 LLM（默认走规则文案）", now_iso)

    caller = llm_caller or _default_llm_caller
    base_prompt = build_overlay_prompt(panel or {}, payload or {}, tier)
    last_reason = "LLM 覆盖层生成失败"
    last_errors: List[str] = []

    for attempt in range(max(1, retries)):
        prompt = base_prompt
        if attempt > 0 and last_errors:
            prompt = base_prompt + "\n【上一次返回的问题，请修正后重新只输出 JSON】\n- " + "\n- ".join(last_errors)
        try:
            ok, text = caller(prompt)
        except Exception as exc:  # noqa: BLE001
            last_reason = f"LLM 调用异常：{exc}"
            last_errors = [last_reason]
            continue
        if not ok:
            last_reason = text or "LLM 调用失败"
            if _looks_unconfigured(text):
                return _unavailable(tier, last_reason, now_iso)  # 未配置 → 不重试
            last_errors = [last_reason]
            continue
        obj = extract_overlay_json(text)
        if obj is None:
            last_errors = ["返回不是合法 JSON，请只输出 JSON 对象"]
            last_reason = last_errors[0]
            continue
        errors = validate_overlay(obj, tier)
        if not errors:
            return _success(obj, tier, now_iso)
        last_errors = errors
        last_reason = "；".join(errors)

    return _unavailable(tier, last_reason, now_iso)


def merge_overlay(panel: Dict[str, Any], overlay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """返回 panel 深拷贝，叠加已审阅 overlay 的 agent 字段（punchline 覆盖 + 逐人 insight）。"""
    merged = copy.deepcopy(panel or {})
    if not overlay or not overlay.get("reviewed"):
        return merged
    gd_override = overlay.get("great_divide_override") or {}
    punchline = gd_override.get("punchline")
    if punchline and isinstance(merged.get("great_divide"), dict):
        merged["great_divide"]["punchline"] = punchline
    insights = overlay.get("panel_insights") or {}
    for analyst in merged.get("analysts", []) or []:
        if analyst.get("id") in insights:
            analyst["insight"] = insights[analyst["id"]]
    return merged
