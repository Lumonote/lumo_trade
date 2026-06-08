from analysis import risk_opportunity_engine as eng


def test_match_action_high_opp_low_risk_is_act():
    r = eng.match_action(88, 32)
    assert r["action"] == "重点出手"
    assert r["code"] == "act"
    assert r["color"] == "green"
    assert r["quadrant"] == "high-low"


def test_match_action_high_opp_high_risk_is_care():
    r = eng.match_action(85, 72)
    assert r["action"] == "谨慎·轻仓"
    assert r["code"] == "care"


def test_match_action_low_opp_high_risk_is_avoid():
    r = eng.match_action(40, 75)
    assert r["action"] == "坚决回避"
    assert r["code"] == "avoid"


def test_match_action_held_high_risk_overlays_cut():
    r = eng.match_action(85, 72, held=True)
    assert r["held_overlay"] == "减仓/止盈"


def test_match_action_held_act_overlays_hold():
    r = eng.match_action(88, 32, held=True)
    assert r["held_overlay"] == "持有"


def test_match_action_unknown_risk_returns_unknown():
    r = eng.match_action(88, None)
    assert r["action"] == "风险未知"
    assert r["code"] == "unknown"


def test_score_stock_risk_rsi_overheat_dominates():
    r = eng.score_stock_risk({"rsi": 81, "chase": 20, "change_3d": 5,
                              "sell_signals": 0, "quant_score": 60})
    assert r["unknown"] is False
    assert r["risk"] >= 55          # base 30 + rsi>=80 (+30) - clamp
    assert r["dominant"] == "RSI过热"


def test_score_stock_risk_hard_gate_st_caps_high():
    r = eng.score_stock_risk({"rsi": 40, "is_st": True})
    assert r["risk"] >= 85


def test_score_stock_risk_sell_and_chase_stack():
    r = eng.score_stock_risk({"rsi": 55, "chase": 82, "change_3d": 21,
                              "sell_signals": 3, "quant_score": 91})
    # base30 + chase>=80(20) + chg>=20(15) + sell>=2(12) + quant>=90(10) = 87
    assert r["risk"] >= 80
    factor_names = {f["name"] for f in r["factors"]}
    assert {"追高", "5日急涨", "卖出信号", "量化过度共识"} <= factor_names


def test_score_stock_risk_clean_stock_low():
    r = eng.score_stock_risk({"rsi": 48, "chase": 10, "change_3d": 3,
                              "sell_signals": 0, "quant_score": 55})
    assert r["risk"] <= 40


def test_score_stock_risk_empty_signals_unknown():
    r = eng.score_stock_risk({})
    assert r["unknown"] is True
    assert r["risk"] is None


def test_sector_crowding_dead_zone_high():
    assert eng.score_sector_crowding({"sector_score": 70}) >= 60   # 65-75 死区
    assert eng.score_sector_crowding({"sector_score": 50}) < 50


def test_market_risk_drawdown_and_breadth():
    r = eng.score_market_risk({"hs300_ret_5d": -4.0, "hs300_ret_20d": -8.0,
                               "advance": 800, "decline": 4000, "sentiment": 30})
    assert r["risk"] >= 60
    assert any("回撤" in f["name"] or "breadth" in f["name"] or "家数" in f["name"]
               for f in r["factors"])


def test_market_risk_calm_low():
    r = eng.score_market_risk({"hs300_ret_5d": 1.0, "hs300_ret_20d": 2.0,
                               "advance": 3000, "decline": 1800, "sentiment": 60})
    assert r["risk"] <= 45


def test_portfolio_risk_concentration_and_drawdown():
    acct = {"total_equity": 1_000_000}
    pos = [{"ts_code": "600000", "market_value": 600_000},
           {"ts_code": "000001", "market_value": 200_000}]
    r = eng.score_portfolio_risk(acct, pos, max_drawdown=0.18)
    assert r["concentration"] == 0.6
    assert r["exposure"] == 0.8
    assert r["risk"] >= 55


def test_combine_stock_risk_blends_layers():
    # stock 60, sector 40, market 50 -> .55*60 +.2*40 +.25*50 = 53.5
    v = eng.combine_stock_risk({"risk": 60, "unknown": False}, 40, 50)
    assert round(v, 1) == 53.5


def test_combine_stock_risk_unknown_propagates():
    assert eng.combine_stock_risk({"risk": None, "unknown": True}, 40, 50) is None
