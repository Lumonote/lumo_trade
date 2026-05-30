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
