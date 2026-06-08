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
