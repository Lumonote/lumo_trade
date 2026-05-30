from analysis.report_quality import evaluate_overlay


def _medium_overlay(**over):
    base = {
        "reviewed": True, "tier": "medium",
        "great_divide_override": {"punchline": "放量突破压制估值担忧"},
        "risks": ["估值透支", "题材退潮", "解禁压力"],
        "panel_insights": {}, "buy_zones": None, "narrative_override": None,
    }
    base.update(over)
    return base


def test_passes_clean_minimal_overlay():
    rep = evaluate_overlay(_medium_overlay(), {}, {}, "medium")
    assert rep["passed"] is True
    assert rep["criticals"] == []


def test_blocks_on_placeholder_in_punchline():
    ov = _medium_overlay(great_divide_override={"punchline": "TODO 待补充金句"})
    rep = evaluate_overlay(ov, {}, {}, "medium")
    assert rep["passed"] is False
    assert any("占位符" in c for c in rep["criticals"])


def test_blocks_on_placeholder_in_risk():
    ov = _medium_overlay(risks=["估值透支", "[脚本占位]", "解禁压力"])
    rep = evaluate_overlay(ov, {}, {}, "medium")
    assert rep["passed"] is False
    assert any("占位符" in c for c in rep["criticals"])


def test_blocks_on_empty_punchline():
    ov = _medium_overlay(great_divide_override={"punchline": "   "})
    rep = evaluate_overlay(ov, {}, {}, "medium")
    assert rep["passed"] is False
    assert any("punchline" in c for c in rep["criticals"])


def _deep_overlay(**over):
    base = {
        "reviewed": True, "tier": "deep",
        "great_divide_override": {"punchline": "放量突破压制估值担忧"},
        "risks": ["估值透支", "题材退潮", "解禁压力"],
        "panel_insights": {"zhao": "量化席位进场", "graham": "估值偏贵需谨慎"},
        "buy_zones": {"value": ["回调分批"], "growth": [], "technical": [], "youzi": []},
        "narrative_override": None,
    }
    base.update(over)
    return base


_DEEP_PANEL = {
    "great_divide": {
        "bull": {"id": "zhao", "name": "赵老哥"},
        "bear": {"id": "graham", "name": "格雷厄姆"},
    }
}


def test_deep_blocks_when_headline_insight_missing():
    ov = _deep_overlay(panel_insights={"zhao": "量化席位进场"})  # 缺 graham(bear 头牌)
    rep = evaluate_overlay(ov, _DEEP_PANEL, {}, "deep")
    assert rep["passed"] is False
    assert any("头牌" in c for c in rep["criticals"])


def test_deep_blocks_when_all_buy_zones_empty():
    ov = _deep_overlay(buy_zones={"value": [], "growth": [], "technical": [], "youzi": []})
    rep = evaluate_overlay(ov, _DEEP_PANEL, {}, "deep")
    assert rep["passed"] is False
    assert any("buy_zones" in c for c in rep["criticals"])


def test_deep_passes_with_both_insights_and_one_zone():
    rep = evaluate_overlay(_deep_overlay(), _DEEP_PANEL, {}, "deep")
    assert rep["passed"] is True
    assert rep["criticals"] == []
