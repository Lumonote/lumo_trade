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


def test_opportunity_index_aggregates_tiers():
    items = [{"score": 88, "rating": "S"}, {"score": 80, "rating": "A"},
             {"score": 60, "rating": "C"}]
    idx = eng.opportunity_index(items)
    assert 0 <= idx <= 100
    assert idx >= 60        # has S+A


def test_market_risk_index_blends_sentiment():
    assert 0 <= eng.market_risk_index(62, 55) <= 100


def test_build_target_assembles_action_and_reason():
    item = {"code": "603986", "name": "兆易创新", "score": 88, "rating": "S",
            "sector": "半导体", "sector_code": "BK1036"}
    signals = {"rsi": 58, "chase": 30, "change_3d": 6, "sell_signals": 0,
               "quant_score": 62, "sector_score": 50}
    t = eng.build_target(item, signals, sector_crowding=45, market_backdrop=50,
                         held=False)
    assert t["code"] == "603986"
    assert t["sector_code"] == "BK1036"
    assert t["opp"] == 88
    assert t["risk"] is not None
    assert t["action"] == "重点出手"
    assert "机会" in t["reason"] and "→" in t["reason"]


def test_build_target_unknown_risk_when_no_signals():
    item = {"code": "000001", "name": "X", "score": 75, "rating": "B"}
    t = eng.build_target(item, {}, sector_crowding=40, market_backdrop=40, held=False)
    assert t["risk"] is None
    assert t["code_action"] == "unknown"


# ── 持仓 · 热点关联 ─────────────────────────────────────────────

def _mk_board(board_rank=1, stock_rank=1, lhb_hit=False,
              board_name="半导体", board_code="BK1036", **kw):
    d = {"board_name": board_name, "board_code": board_code, "board_rank": board_rank,
         "stock_rank": stock_rank, "lhb_hit": lhb_hit, "main_net_inflow": 1.0e8,
         "main_net_inflow_text": "1.00亿", "change_pct": 3.2}
    d.update(kw)
    return d


def test_holdings_relevance_sector_only():
    pos = [{"ts_code": "600519.SH", "name": "贵州茅台", "market_value": 100000}]
    mem = {"600519": [_mk_board(board_rank=1, stock_rank=1, snapshot_id=42)]}
    rows = eng.score_holdings_relevance(pos, mem, {})
    r = rows[0]
    assert r["code"] == "600519"                 # ts_code 归一为 code6,对齐索引键
    assert r["status"] == "踩中"
    assert r["sector_relevance"] == 100          # rank1 base100 + stock1 +12 -> clamp100
    assert r["news_relevance"] == 0
    assert r["relevance"] == 60                  # round(0.6*100 + 0.4*0)
    assert r["boards"][0]["board_code"] == "BK1036"
    assert r["boards"][0]["snapshot_id"] == 42


def test_holdings_relevance_news_only_distinct_platform():
    pos = [{"ts_code": "000001", "name": "平安银行", "market_value": 1}]
    news = {"000001": [{"platform": "东财人气热度", "title": "x"},
                       {"platform": "金十快讯", "title": "y"},
                       {"platform": "金十快讯", "title": "z"}]}  # 同平台多条只计一次
    rows = eng.score_holdings_relevance(pos, {}, news)
    r = rows[0]
    assert r["sector_relevance"] == 0
    assert r["news_relevance"] == 85             # 东财45 + 金十40 (金十不重复)
    assert r["relevance"] == 34                  # round(0.4*85)
    assert r["status"] == "踩中"
    assert len(r["news"]) == 3                   # 展示封顶 3 条


def test_holdings_relevance_both_multiboard_lhb_picks_hottest():
    pos = [{"ts_code": "300750.SZ", "name": "宁德时代", "market_value": 5}]
    mem = {"300750": [_mk_board(board_rank=5, stock_rank=3, board_code="BK0002"),
                      _mk_board(board_rank=2, stock_rank=1, lhb_hit=True, board_code="BK0001")]}
    news = {"300750": [{"platform": "新浪快讯", "title": "n"}]}
    rows = eng.score_holdings_relevance(pos, mem, news)
    r = rows[0]
    # 最热=rank2: base 100-8=92; stock1 +12=104; lhb +8=112; 多板块 +5=117 -> clamp100
    assert r["sector_relevance"] == 100
    assert r["news_relevance"] == 35
    assert r["boards"][0]["board_rank"] == 2     # 即便输入乱序也取最热在前
    assert r["relevance"] == round(0.6 * 100 + 0.4 * 35)   # 74


def test_holdings_relevance_no_hit_is_detached():
    pos = [{"ts_code": "600000", "name": "浦发", "market_value": 9}]
    rows = eng.score_holdings_relevance(pos, {}, {})
    r = rows[0]
    assert r["relevance"] == 0
    assert r["status"] == "脱离"
    assert r["boards"] == [] and r["news"] == []


def test_holdings_relevance_sort_desc_then_market_value():
    pos = [{"ts_code": "111111", "name": "low", "market_value": 999},
           {"ts_code": "222222", "name": "mid", "market_value": 1},
           {"ts_code": "333333", "name": "tieA", "market_value": 50}]
    mem = {"222222": [_mk_board(board_rank=3, stock_rank=2)]}
    rows = eng.score_holdings_relevance(pos, mem, {})
    assert rows[0]["code"] == "222222"                       # 关联度最高在前
    assert [r["code"] for r in rows[1:]] == ["111111", "333333"]  # 同 rel0 按市值降序


def test_holdings_relevance_weight_params_apply():
    pos = [{"ts_code": "600519", "name": "x", "market_value": 1}]
    mem = {"600519": [_mk_board(board_rank=1, stock_rank=1)]}
    news = {"600519": [{"platform": "金十快讯", "title": "t"}]}
    full_sector = eng.score_holdings_relevance(pos, mem, news, sector_weight=1.0, news_weight=0.0)
    assert full_sector[0]["relevance"] == 100
    full_news = eng.score_holdings_relevance(pos, mem, news, sector_weight=0.0, news_weight=1.0)
    assert full_news[0]["relevance"] == 40                   # 金十 40


def test_holdings_relevance_degraded_indices_do_not_crash():
    pos = [{"ts_code": "600519", "name": "x", "market_value": 1}]
    rows = eng.score_holdings_relevance(pos, None, None)     # 两源都降级
    assert rows[0]["relevance"] == 0 and rows[0]["status"] == "脱离"


def test_holdings_relevance_empty_positions():
    assert eng.score_holdings_relevance([], {"x": [1]}, {"y": [2]}) == []
    assert eng.score_holdings_relevance(None, None, None) == []
