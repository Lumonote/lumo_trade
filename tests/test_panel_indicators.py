from analysis.panel.indicators import build_indicators, GROUPS


def _features(**over):
    base = {
        "main_net_inflow": 1.2e8, "north_delta_30d": 0.6, "super_large_net": 8e7,
        "quant_seat_appearances": 2, "lhb_net_inst_buy": 5e7,
        "rsi": 28.0, "macd_hist": 0.3, "kdj_j": 90.0, "ma_alignment": "bull",
        "boll_position": 0.85, "volume_ratio": 1.9,
        "control_degree": 72.0, "holder_number_trend": "down", "fund_hold_trend": "up",
        "model_bull_ratio": 0.6, "model_bull": 18, "model_bear": 6,
        "kronos_direction": None, "backtest_winrate": None,
    }
    base.update(over)
    return base


def test_build_indicators_has_16_items():
    inds = build_indicators(_features())
    assert len(inds) == 16
    for it in inds:
        assert {"group", "key", "label", "value_text", "signal", "strength", "data_status"} <= set(it.keys())
        assert it["group"] in GROUPS
        assert it["signal"] in ("up", "down", "neutral")
        assert 0.0 <= it["strength"] <= 1.0


def test_group_counts_match_spec():
    inds = build_indicators(_features())
    counts = {g: 0 for g in GROUPS}
    for it in inds:
        counts[it["group"]] += 1
    assert counts == {"capital": 4, "technical": 6, "chip": 3, "model": 3}


def test_main_capital_up_on_inflow():
    inds = {it["key"]: it for it in build_indicators(_features(main_net_inflow=2e8))}
    assert inds["main_capital"]["signal"] == "up"
    inds_out = {it["key"]: it for it in build_indicators(_features(main_net_inflow=-2e8))}
    assert inds_out["main_capital"]["signal"] == "down"


def test_rsi_oversold_is_up_overbought_is_down():
    up = {it["key"]: it for it in build_indicators(_features(rsi=25.0))}
    down = {it["key"]: it for it in build_indicators(_features(rsi=78.0))}
    assert up["rsi"]["signal"] == "up"
    assert down["rsi"]["signal"] == "down"


def test_star_indicators_unavailable_in_phase1():
    inds = {it["key"]: it for it in build_indicators(_features())}
    assert inds["kronos_pred"]["data_status"] == "unavailable"
    assert inds["kronos_pred"]["signal"] == "neutral"
    assert inds["backtest_winrate"]["data_status"] == "unavailable"


def test_missing_feature_degrades_to_unavailable_neutral():
    inds = {it["key"]: it for it in build_indicators(_features(main_net_inflow=None))}
    assert inds["main_capital"]["data_status"] == "unavailable"
    assert inds["main_capital"]["signal"] == "neutral"
