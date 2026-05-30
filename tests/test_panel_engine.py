import pytest

from analysis.panel.registry import load_personas, SCHOOLS


def test_registry_loads_51_personas():
    personas = load_personas()
    assert len(personas) == 51
    flagship = [p for p in personas if p["tier"] == "flagship"]
    stub = [p for p in personas if p["tier"] == "stub"]
    assert len(flagship) == 12
    assert len(stub) == 39


def test_registry_covers_seven_schools():
    personas = load_personas()
    schools = {p["school"] for p in personas}
    assert schools == set(SCHOOLS.keys())  # A..G
    assert SCHOOLS["A"] == "价值派" and SCHOOLS["F"] == "游资派"


def test_registry_entries_have_required_fields():
    personas = load_personas()
    for p in personas:
        assert {"id", "name", "school", "tier", "rule", "voice"} <= set(p.keys())
        assert p["school"] in SCHOOLS
        assert p["tier"] in ("flagship", "stub")


def test_registry_ids_unique():
    ids = [p["id"] for p in load_personas()]
    assert len(ids) == len(set(ids))


from analysis.panel.style import classify_style, load_style_weights, school_style_weight


def test_classify_style_small_spec():
    # 高控盘 + 放量 + 无基本面 → 小盘投机
    style = classify_style({"control_degree": 80, "volume_ratio": 2.2,
                            "roe": None, "quant_seat_appearances": 3})
    assert style == "small_spec"


def test_classify_style_baima_default():
    style = classify_style({"roe": 20, "net_profit_yoy": 12, "control_degree": 30})
    assert style in ("baima", "growth")


def test_load_style_weights_has_matrix():
    w = load_style_weights()
    assert "matrix" in w and "default" in w


def test_school_style_weight_lookup():
    w = load_style_weights()
    # 小盘投机时游资派(F)权重应 > 价值派(A)
    assert school_style_weight("F", "small_spec", w) > school_style_weight("A", "small_spec", w)


def test_school_style_weight_falls_back_to_default():
    w = {"default": 1.0, "matrix": {}}
    assert school_style_weight("A", "unknown_style", w) == 1.0


from analysis.panel.engine import (
    evaluate_all, compute_consensus, compute_great_divide, compute_schools,
    consensus_label, lean_label,
)


def _analysts_fixture():
    # 构造一组可控裁决（绕过真实规则）
    return [
        {"id": "a1", "name": "多1", "school": "F", "signal": "bull", "score": 92,
         "headline": "量化席位活跃", "source": "handwritten", "reasons": ["量化席位活跃"]},
        {"id": "a2", "name": "多2", "school": "B", "signal": "bull", "score": 70,
         "headline": "高成长", "source": "rule", "reasons": ["高成长"]},
        {"id": "a3", "name": "空1", "school": "A", "signal": "bear", "score": 25,
         "headline": "估值超出安全边际", "source": "handwritten", "reasons": ["估值超出安全边际"]},
        {"id": "a4", "name": "中1", "school": "C", "signal": "neutral", "score": 50,
         "headline": "震荡观望", "source": "rule", "reasons": ["震荡观望"]},
    ]


def test_evaluate_all_returns_one_verdict_per_persona():
    from analysis.panel.registry import load_personas
    features = {"roe": 22, "pe_industry_rank": 20, "net_profit_yoy": 35,
                "main_net_inflow": 1e8, "quant_seat_appearances": 3, "volume_ratio": 2.0,
                "rsi": 28, "macd_hist": 0.3, "ma_alignment": "bull", "model_bull_ratio": 0.7,
                "market_regime": "bull"}
    analysts = evaluate_all(load_personas(), features)
    assert len(analysts) == 51
    sample = analysts[0]
    assert {"id", "name", "school", "signal", "score", "headline", "source", "reasons"} <= set(sample.keys())
    assert sample["signal"] in ("bull", "bear", "neutral")
    # 旗舰 → source=handwritten；stub → source=rule
    sources = {a["id"]: a["source"] for a in analysts}
    assert sources["buffett"] == "handwritten"
    assert sources["templeton"] == "rule"


def test_compute_consensus_counts_and_weighted_score():
    c = compute_consensus(_analysts_fixture(), style="baima")
    assert c["bull"] == 2 and c["bear"] == 1 and c["neutral"] == 1
    assert 0 <= c["score"] <= 100
    assert isinstance(c["label"], str)


def test_compute_great_divide_picks_extremes():
    gd = compute_great_divide(_analysts_fixture())
    assert gd["bull"]["id"] == "a1" and gd["bull"]["score"] == 92
    assert gd["bear"]["id"] == "a3" and gd["bear"]["score"] == 25
    assert "量化席位活跃" in gd["punchline"]
    assert "估值超出安全边际" in gd["punchline"]


def test_compute_great_divide_handles_no_bear():
    only_bulls = [a for a in _analysts_fixture() if a["signal"] == "bull"]
    gd = compute_great_divide(only_bulls)
    assert gd["bull"] is not None
    assert gd["bear"] is None
    assert isinstance(gd["punchline"], str)


def test_compute_schools_aggregates_seven():
    from analysis.panel.registry import load_personas
    features = {"market_regime": "sideways"}
    analysts = evaluate_all(load_personas(), features)
    schools = compute_schools(analysts)
    assert len(schools) == 7
    keys = {s["key"] for s in schools}
    assert keys == {"A", "B", "C", "D", "E", "F", "G"}
    for s in schools:
        assert {"key", "name", "count", "lean", "lean_score"} <= set(s.keys())
    assert sum(s["count"] for s in schools) == 51


def test_consensus_and_lean_labels():
    assert consensus_label(70) == "强烈看多"
    assert consensus_label(57) == "偏多"
    assert consensus_label(50) == "中性"
    assert consensus_label(40) == "偏空"
    assert consensus_label(30) == "强烈看空"
    assert lean_label(58) == "偏多" and lean_label(42) == "偏空"
