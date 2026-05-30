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


# --- prompt / JSON 抽取 ---
from analysis.analysis_overlay.prompt import build_overlay_prompt, extract_overlay_json


def _panel():
    return {
        "data_status": "fresh",
        "consensus": {"score": 61, "label": "偏多", "bull": 28, "neutral": 11, "bear": 12},
        "great_divide": {
            "bull": {"id": "zhao", "name": "赵老哥", "school": "F", "score": 92},
            "bear": {"id": "graham", "name": "格雷厄姆", "school": "A", "score": 25},
            "punchline": "赵老哥 看到 量化席位活跃，格雷厄姆 担心 估值超出安全边际",
        },
        "schools": [{"key": "F", "name": "游资派", "count": 7, "lean": "偏多", "lean_score": 64}],
        "analysts": [
            {"id": "zhao", "name": "赵老哥", "school": "F", "signal": "bull", "score": 92,
             "headline": "量化席位活跃", "source": "handwritten", "reasons": ["量化席位 90 日 3 次活跃"]},
            {"id": "graham", "name": "格雷厄姆", "school": "A", "signal": "bear", "score": 25,
             "headline": "估值超出安全边际", "source": "handwritten", "reasons": ["估值超出安全边际，不碰"]},
        ],
        "indicators": [
            {"group": "capital", "key": "main_capital", "label": "主力资金",
             "value_text": "净流入 1.20 亿", "signal": "up", "strength": 0.6, "data_status": "fresh"},
        ],
    }


def test_build_prompt_contains_tier_fields_and_json_directive():
    p = build_overlay_prompt(_panel(), {"stock": {"code": "000001", "name": "平安银行"}}, "deep")
    assert "只返回 JSON" in p or "只输出 JSON" in p
    # deep 档要求的字段名应在提示中出现
    for token in ("panel_insights", "great_divide_override", "buy_zones", "risks"):
        assert token in p
    # panel 摘要信息进了提示
    assert "61" in p and "偏多" in p
    assert "赵老哥" in p and "格雷厄姆" in p


def test_build_prompt_medium_omits_deep_only_fields():
    p = build_overlay_prompt(_panel(), {}, "medium")
    assert "great_divide_override" in p and "risks" in p
    assert "buy_zones" not in p and "panel_insights" not in p


def test_extract_json_from_fenced_block():
    text = '点评如下：\n```json\n{"risks": ["a", "b"]}\n```\n谢谢'
    assert extract_overlay_json(text) == {"risks": ["a", "b"]}


def test_extract_json_from_bare_object():
    text = '{"great_divide_override": {"punchline": "多头占优"}}'
    assert extract_overlay_json(text)["great_divide_override"]["punchline"] == "多头占优"


def test_extract_json_returns_none_on_garbage():
    assert extract_overlay_json("这不是 JSON") is None
    assert extract_overlay_json("") is None
    assert extract_overlay_json("```json\n{坏的 JSON}\n```") is None
