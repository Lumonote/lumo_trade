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


def test_fund_hold_falls_back_to_count_when_no_trend():
    """provider 仅返回单期基金持仓(无上一期→无增减持趋势)时，重仓基金卡应改用
    「重仓家数 + 持仓市值」反映机构关注度，而非恒显「数据不足」。"""
    inds = {it["key"]: it for it in build_indicators(
        _features(fund_hold_trend=None, fund_hold_count=12, fund_hold_mv=3.6e9))}
    fh = inds["fund_hold"]
    assert fh["data_status"] == "fresh"
    assert fh["signal"] == "up"          # ≥10 家重仓 = 机构认可度高（偏多）
    assert "12 只基金重仓" in fh["value_text"]
    assert "36.0 亿" in fh["value_text"]  # 市值 3.6e9 元 → 36.0 亿


def test_fund_hold_count_low_is_neutral():
    inds = {it["key"]: it for it in build_indicators(
        _features(fund_hold_trend=None, fund_hold_count=3, fund_hold_mv=None))}
    fh = inds["fund_hold"]
    assert fh["data_status"] == "fresh"
    assert fh["signal"] == "neutral"     # <10 家 = 信息中性
    assert "3 只基金重仓" in fh["value_text"]


def test_fund_hold_unavailable_when_no_trend_no_count():
    inds = {it["key"]: it for it in build_indicators(
        _features(fund_hold_trend=None, fund_hold_count=None))}
    assert inds["fund_hold"]["data_status"] == "unavailable"
