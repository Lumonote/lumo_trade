from analysis.panel.rules import RULES, SCHOOL_DEFAULTS, score_to_signal


def test_score_to_signal_thresholds():
    assert score_to_signal(78) == "bull"
    assert score_to_signal(25) == "bear"
    assert score_to_signal(50) == "neutral"


def test_buffett_bull_on_high_roe_cheap():
    v = RULES["buffett"]({"roe": 22.0, "pe_industry_rank": 20.0, "net_profit_yoy": 18.0})
    assert v["score"] >= 70
    assert score_to_signal(v["score"]) == "bull"
    assert any("ROE" in r for r in v["reasons"])


def test_graham_bear_on_expensive():
    v = RULES["graham"]({"pe_industry_rank": 85.0, "pb": 6.0})
    assert score_to_signal(v["score"]) == "bear"


def test_zhao_bull_on_quant_seats_and_inflow():
    v = RULES["zhao"]({"quant_seat_appearances": 3, "main_net_inflow": 1e8,
                       "volume_ratio": 2.0})
    assert score_to_signal(v["score"]) == "bull"
    assert any("量化席位" in r for r in v["reasons"])


def test_technical_default_uses_indicators():
    bull = SCHOOL_DEFAULTS["D"]({"rsi": 28.0, "macd_hist": 0.3, "ma_alignment": "bull"})
    bear = SCHOOL_DEFAULTS["D"]({"rsi": 75.0, "macd_hist": -0.3, "ma_alignment": "bear"})
    assert score_to_signal(bull["score"]) == "bull"
    assert score_to_signal(bear["score"]) == "bear"


def test_quant_default_uses_model_ratio():
    v = SCHOOL_DEFAULTS["G"]({"model_bull_ratio": 0.7})
    assert score_to_signal(v["score"]) == "bull"


def test_all_rules_tolerate_empty_features():
    for fn in list(RULES.values()) + list(SCHOOL_DEFAULTS.values()):
        v = fn({})
        assert 0 <= v["score"] <= 100
        assert isinstance(v["reasons"], list)


def test_every_school_has_default():
    assert set(SCHOOL_DEFAULTS.keys()) == {"A", "B", "C", "D", "E", "F", "G"}


def test_twelve_flagship_rules_registered():
    expected = {"buffett", "munger", "graham", "fisher", "lynch", "wood",
                "soros", "dalio", "duan", "zhangkun", "zhao", "zhang_mz"}
    assert expected <= set(RULES.keys())
