"""analysis_overlay：schema 校验 / prompt / 引擎（含重试·回退·merge·分档）。LLM 全程 stub。"""
from __future__ import annotations

from analysis.analysis_overlay.schema import validate_overlay, TIERS


def _deep_ok():
    return {
        "great_divide_override": {"punchline": "放量突破压制估值担忧"},
        "risks": ["估值透支三年成长", "题材退潮", "解禁压力"],
        "panel_insights": {"buffett": "护城河深，回调即买", "zhao": "量化席位进场"},
        "buy_zones": {"value": ["12.4 以下分批"], "growth": [], "technical": ["站上 20 日线"], "youzi": []},
        "narrative_override": "多头占优但需防估值",
    }


def test_tiers_constant():
    assert TIERS == ("lite", "medium", "deep")


def test_lite_has_no_requirements():
    assert validate_overlay({}, "lite") == []


def test_medium_requires_punchline_and_risks():
    errs = validate_overlay({}, "medium")
    assert any("punchline" in e for e in errs)
    assert any("risks" in e for e in errs)
    ok = validate_overlay({"great_divide_override": {"punchline": "多头占优"}, "risks": ["风险一"]}, "medium")
    assert ok == []


def test_medium_punchline_must_be_nonempty_string():
    errs = validate_overlay({"great_divide_override": {"punchline": "   "}, "risks": []}, "medium")
    assert any("punchline" in e for e in errs)


def test_deep_requires_insights_and_buy_zones():
    errs = validate_overlay(
        {"great_divide_override": {"punchline": "多头占优"}, "risks": ["a"]}, "deep")
    assert any("panel_insights" in e for e in errs)
    assert any("buy_zones" in e for e in errs)


def test_deep_buy_zones_needs_four_buckets():
    bad = _deep_ok()
    bad["buy_zones"] = {"value": [], "growth": [], "technical": []}  # 缺 youzi
    errs = validate_overlay(bad, "deep")
    assert any("youzi" in e for e in errs)


def test_deep_valid_passes():
    assert validate_overlay(_deep_ok(), "deep") == []


def test_non_dict_is_error():
    assert validate_overlay(["not", "a", "dict"], "deep") == ["overlay 必须是 JSON 对象"]
