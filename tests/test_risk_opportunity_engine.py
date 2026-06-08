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
