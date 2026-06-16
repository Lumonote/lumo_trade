"""TDD specs for webui/opportunity_excel.py — the suite-enriched opportunity workbook builder.

These tests pin the pure assembly + derivation behaviour (no file IO, no network):
the builder takes a canvas + an injectable suite_fetcher and returns sheet specs +
a coverage summary. A fake fetcher stands in for STOCK_SUITE_SERVICE.get_suite so we
can exercise the success / raise / over-budget / over-limit paths deterministically.
"""

from __future__ import annotations

import pytest

from webui import opportunity_excel as ox


# --------------------------------------------------------------------------- fakes


def _full_suite(code: str = "688111") -> dict:
    """Mirror analysis.stock_analysis_suite.get_full_payload for a fully-populated stock."""
    return {
        "success": True,
        "overview": {
            "radar": {
                "main_force_phase": {"score": 72, "label": "强势主导", "reason": "主力近5日4日净流入"},
                "market_cycle": {"score": 55, "label": "震荡期", "reason": "大盘资金流入比 0.50"},
                "volume_price_game": {"score": 63, "label": "多头占优", "reason": "30 模型中 8 个买入信号"},
                "chip_structure": {"score": 58, "label": "结构健康", "reason": "90% 成本集中度 12.0%"},
                "performance": {"score": 66, "label": "基本面稳健", "reason": "PE 35，ROE 12%"},
                "control_degree": {"score": 68, "label": "中控"},
                "quant_activity": {"score": 0, "label": "未知"},
            },
            "key_signals": [
                {"label": "大盘周期", "value": "震荡期", "tone": "warn"},
                {"label": "仓位上限", "value": "60%", "tone": "warn"},
                {"label": "主力阶段", "value": "强势主导", "tone": "info"},
                {"label": "可信度", "value": "高", "tone": "neutral"},
                {"label": "量能质量", "value": "健康", "tone": "info"},
                {"label": "筹码集中度", "value": "集中", "tone": "neutral"},
                {"label": "技术趋势", "value": "多头排列", "tone": "info"},
            ],
            "deep_signals": [],
            "scenario_probability": {"bullish": 60, "bearish": 13, "sideways": 27,
                                     "source": "30 量化模型多空票数归一化"},
        },
        "risk_control": {
            "available": True,
            "execution_plan": {
                "stop_loss": {"price": 28.5, "drop_pct": 7.5, "basis": "ATR(20)×1.5 下沿"},
                "risk_reward": {"ratio": "1:2.6", "expected_return_pct": 19.5},
            },
            "scaled_entry": [
                {"label": "现价建仓", "price": 30.8, "position_pct": 10},
                {"label": "浅回调加仓", "price": 30.2, "position_pct": 20},
                {"label": "中度回调加仓", "price": 29.6, "position_pct": 30},
                {"label": "深度回调加仓", "price": 28.9, "position_pct": 25},
                {"label": "极限加仓", "price": 28.6, "position_pct": 15},
            ],
            "tiered_take_profit": [
                {"label": "第一止盈(前高)", "price": 36.8, "sell_pct": 30},
                {"label": "第二止盈(+15%)", "price": 35.4, "sell_pct": 30},
                {"label": "第三止盈(+30%)", "price": 40.0, "sell_pct": 25},
                {"label": "终极止盈(+50%)", "price": 46.2, "sell_pct": 15},
            ],
            "deep_signals": [
                {"text": "最大回撤：当前 -8.5%", "tone": "info"},
                {"text": "60日最大回撤 -18.2%", "tone": "warn"},
                {"text": "波动率(60日年化) 42.3%", "tone": "info"},
                {"text": "夏普比率(60日年化) 1.35", "tone": "info"},
            ],
            "hidden_risks": [],
        },
        "quant_matrix": {
            "data_status": "fresh",
            "signals_matrix": [
                {"model": "海龟交易", "period": "daily", "signal": 1, "confidence": None},
                {"model": "MACD金叉", "period": "daily", "signal": -1, "confidence": None},
                {"model": "RSI背离", "period": "daily", "signal": 0, "confidence": None},
            ],
            "multi_period_resonance": {"bull": 8, "bear": 2, "neutral": 20},
            "current_posture": "震荡偏多",
        },
        "chip_control": {
            "data_status": "fresh",
            "control_degree": 68,
            "control_label": "中控",
            "concentration_90": 12.0,
            "concentration_70": 8.5,
        },
        "main_force_deep": {
            "data_status": "stale",
            "last_updated": "2026-06-13",
            "dragon_tiger": {
                "history_90d": [],
                "quant_seat_appearances": 2,
                "net_inst_buy_30d": 5.0e7,
                "highlight_seats": [],
            },
            "hsgt": {
                "latest": {"hold_vol": 1.2e7, "hold_ratio": 3.5, "trade_date": "2026-06-13"},
                "trend_30d": [],
                "delta_30d_pct": 0.4,
            },
        },
        "institutional_holdings": {
            "data_status": "stale",
            "top10_floatholders": {"period": "2026-03-31", "rows": [], "concentration": 42.0},
            "holder_number": {"latest_num": 32000, "pct_change_qoq": -3.1, "history": []},
        },
    }


def _stock_node(code="688111", name="金山办公", score=87.08, rating="S", **kw):
    node = {
        "id": f"stock-1-{code}",
        "type": "stock",
        "stock_code": code,
        "stock_name": name,
        "sector": kw.get("sector", "软件服务"),
        "score": score,
        "score_rank": kw.get("score_rank", 1),
        "report_rank": kw.get("report_rank", 1),
        "rating": rating,
        "source": kw.get("source", "multi"),
        "source_detail": kw.get("source_detail", ""),
        "sector_rank": kw.get("sector_rank"),
        "sector_peer_count": kw.get("sector_peer_count"),
        "degraded": kw.get("degraded", False),
        "analysis": kw.get("analysis", [
            {"label": "入选原因", "value": "半导体板块走强，量价配合良好"},
            {"label": "概览", "value": f"评级{rating}，建议：可关注"},
            {"label": "涨幅", "value": "当日:+3.10%，3日:+8.20%，5日:+4.40%"},
            {"label": "关键加减分", "value": "牛股动量识别:+5；追高风险偏高:-3"},
        ]),
        "score_breakdown": kw.get("score_breakdown", {"technical": 72, "quantitative": 80}),
        "signals": kw.get("signals", {
            "chase": 35, "rsi": 55, "sell_signals": 0, "quant_score": 75,
            "day_change": 3.1, "change_3d": 8.2, "change_5d": 4.4,
        }),
        "quant_models": kw.get("quant_models", ["海龟交易", "MACD金叉"]),
    }
    return node


def _canvas(*nodes):
    return {"nodes": list(nodes), "edges": [], "stats": {}}


def _sheet(sheets, name):
    for s in sheets:
        if s["name"] == name:
            return s
    raise AssertionError(f"sheet {name!r} not found in {[s['name'] for s in sheets]}")


def _row_for(sheet, code):
    for r in sheet["rows"]:
        if r.get("代码") == code:
            return r
    raise AssertionError(f"no row for {code} in sheet {sheet['name']}")


# ----------------------------------------------------------------- derive_action


@pytest.mark.parametrize("rating,degraded,score,posture,bullish,bearish,chase,sell,expected", [
    ("S",  False, 87, "震荡偏多", 60, 13, 35, 0, "买入"),   # rule 3
    ("A",  False, 80, "强势多头", 55, 20, 30, 0, "买入"),
    ("C",  False, 42, "震荡偏多", 40, 10, 10, 0, "回避"),   # rule 1: rating C
    ("A",  True,  82, "强势多头", 60, 10, 10, 0, "回避"),   # rule 1: degraded
    ("B",  False, 55, "震荡偏多", 60, 10, 10, 0, "回避"),   # rule 1: score<60
    ("A",  False, 80, "强势空头", 40, 30, 10, 0, "观望"),   # rule 2: bearish posture
    ("A",  False, 80, "震荡偏多", 30, 50, 10, 0, "观望"),   # rule 2: bearish>bullish
    ("A",  False, 80, "强势多头", 60, 10, 85, 0, "观望"),   # rule 2: chase>=80
    ("A",  False, 80, "强势多头", 60, 10, 10, 3, "观望"),   # rule 2: sell>=3
    ("B",  False, 72, "震荡偏多", 60, 13, 10, 0, "观望"),   # rule 4: B not in {S,A+,A}
])
def test_derive_action_with_suite(rating, degraded, score, posture, bullish, bearish, chase, sell, expected):
    node = _stock_node(rating=rating, score=score, degraded=degraded,
                       signals={"chase": chase, "sell_signals": sell, "rsi": 50})
    suite = _full_suite()
    suite["quant_matrix"]["current_posture"] = posture
    suite["overview"]["scenario_probability"] = {"bullish": bullish, "bearish": bearish,
                                                  "sideways": max(0, 100 - bullish - bearish)}
    assert ox.derive_action(node, suite) == expected


@pytest.mark.parametrize("rating,degraded,chase,expected", [
    ("S", False, 30, "买入"),
    ("A", False, 30, "买入"),
    ("A", False, 85, "观望"),   # high chase blocks the fallback buy
    ("C", False, 10, "回避"),
    ("B", True,  10, "回避"),
])
def test_derive_action_without_suite_falls_back_to_rating_and_signals(rating, degraded, chase, expected):
    node = _stock_node(rating=rating, degraded=degraded,
                       score=80 if rating in ("S", "A") else 72,
                       signals={"chase": chase, "sell_signals": 0})
    assert ox.derive_action(node, None) == expected


# ----------------------------------------------------------- parse_risk_metrics


def test_parse_risk_metrics_extracts_drawdown_volatility_sharpe():
    metrics = ox.parse_risk_metrics(_full_suite()["risk_control"]["deep_signals"])
    assert metrics["max_drawdown_pct"] == -8.5      # the 当前 drawdown, not the 60日 one
    assert metrics["volatility_pct"] == 42.3
    assert metrics["sharpe"] == 1.35


def test_parse_risk_metrics_tolerates_missing_and_garbage():
    assert ox.parse_risk_metrics([]) == {"max_drawdown_pct": None, "volatility_pct": None, "sharpe": None}
    assert ox.parse_risk_metrics([{"text": "无关文本", "tone": "info"}])["sharpe"] is None


# ------------------------------------------------------------------ signal_label


@pytest.mark.parametrize("value,label", [(1, "买入"), (-1, "卖出"), (0, "观望"), (None, "观望"), ("x", "观望")])
def test_signal_label(value, label):
    assert ox.signal_label(value) == label


# --------------------------------------------------------------- derive_key_risks


def test_derive_key_risks_flags_numeric_thresholds():
    node = _stock_node(signals={"chase": 85, "rsi": 82, "sell_signals": 3, "change_5d": 22.0})
    suite = _full_suite()
    suite["risk_control"]["deep_signals"] = [{"text": "最大回撤：当前 -18.0%", "tone": "warn"}]
    risks = ox.derive_key_risks(node, suite)
    assert "追高" in risks
    assert "RSI" in risks
    assert "卖出" in risks
    assert "回撤" in risks


# --------------------------------------------------------- build_suite_sheets


def test_build_suite_sheets_emits_all_six_sheets():
    sheets, _ = ox.build_suite_sheets(_canvas(_stock_node()), suite_fetcher=lambda c: _full_suite(c))
    assert {s["name"] for s in sheets} == {
        "投资速览", "评分雷达", "风控执行计划", "量化模型矩阵", "筹码与机构", "术语表与图例",
    }


def test_overview_sheet_has_plainlanguage_columns_for_full_stock():
    sheets, cov = ox.build_suite_sheets(_canvas(_stock_node()), suite_fetcher=lambda c: _full_suite(c))
    row = _row_for(_sheet(sheets, "投资速览"), "688111")
    assert row["建议操作"] == "买入"
    assert row["当前态势"] == "震荡偏多"
    assert row["主力阶段"] == "强势主导"
    assert row["仓位上限"] == "60%"
    assert row["现价"] == 30.8
    assert row["止损价"] == 28.5
    assert row["第一目标价"] == 36.8
    assert row["盈亏比"] == "1:2.6"
    assert row["预期收益%"] == 19.5
    assert row["最大回撤%"] == -8.5
    assert row["年化波动率%"] == 42.3
    assert row["夏普"] == 1.35
    assert "半导体板块走强" in row["一句话逻辑"]
    assert cov["succeeded"] == 1 and cov["failed"] == 0 and cov["total_stocks"] == 1


def test_radar_sheet_maps_five_dimensions_and_scenario():
    sheets, _ = ox.build_suite_sheets(_canvas(_stock_node()), suite_fetcher=lambda c: _full_suite(c))
    row = _row_for(_sheet(sheets, "评分雷达"), "688111")
    assert row["主力阶段分"] == 72
    assert row["控盘度"] == 68
    assert row["看多%"] == 60
    assert row["看空%"] == 13
    assert row["震荡%"] == 27


def test_risk_plan_sheet_is_long_form_entries_takeprofits_and_stop():
    sheets, _ = ox.build_suite_sheets(_canvas(_stock_node()), suite_fetcher=lambda c: _full_suite(c))
    rows = [r for r in _sheet(sheets, "风控执行计划")["rows"] if r.get("代码") == "688111"]
    # 5 建仓 + 4 止盈 + 1 止损
    assert len(rows) == 10
    plans = {r["计划"] for r in rows}
    assert plans == {"分批建仓", "分批止盈", "止损"}
    entry0 = next(r for r in rows if r["计划"] == "分批建仓" and r["档位"] == "现价建仓")
    assert entry0["价格"] == 30.8 and entry0["仓位/卖出%"] == 10
    stop = next(r for r in rows if r["计划"] == "止损")
    assert stop["价格"] == 28.5 and "ATR" in str(stop["说明"])


def test_quant_matrix_sheet_maps_signal_codes():
    sheets, _ = ox.build_suite_sheets(_canvas(_stock_node()), suite_fetcher=lambda c: _full_suite(c))
    rows = [r for r in _sheet(sheets, "量化模型矩阵")["rows"] if r.get("代码") == "688111"]
    by_model = {r["模型"]: r["信号"] for r in rows}
    assert by_model["海龟交易"] == "买入"
    assert by_model["MACD金叉"] == "卖出"
    assert by_model["RSI背离"] == "观望"


def test_chip_inst_sheet_reads_real_provider_shapes():
    sheets, _ = ox.build_suite_sheets(_canvas(_stock_node()), suite_fetcher=lambda c: _full_suite(c))
    row = _row_for(_sheet(sheets, "筹码与机构"), "688111")
    assert row["控盘度"] == 68
    assert row["90%集中度"] == 12.0
    assert row["龙虎榜命中"] == "是"
    assert row["机构净买(30日)"] == 5.0e7
    assert row["陆股通持股占比%"] == 3.5
    assert row["十大流通股东合计%"] == 42.0
    assert row["股东户数"] == 32000


def test_glossary_sheet_is_nonempty_and_explains_key_terms():
    sheets, _ = ox.build_suite_sheets(_canvas(_stock_node()), suite_fetcher=lambda c: _full_suite(c))
    terms = {r["指标"] for r in _sheet(sheets, "术语表与图例")["rows"]}
    assert {"建议操作", "夏普比率", "盈亏比", "追高风险", "控盘度"} <= terms


# ----------------------------------------------------- degradation / budget / limit


def test_failed_fetch_degrades_to_baseline_without_crashing():
    def fetcher(code):
        if code == "000002":
            raise RuntimeError("boom")
        return _full_suite(code)

    canvas = _canvas(_stock_node("688111"), _stock_node("000002", name="坏数据", rating="A"))
    sheets, cov = ox.build_suite_sheets(canvas, suite_fetcher=fetcher)

    assert cov["succeeded"] == 1 and cov["failed"] == 1 and cov["total_stocks"] == 2
    # baseline 速览 row still present for the failed stock (no suite columns)
    bad = _row_for(_sheet(sheets, "投资速览"), "000002")
    assert bad["名称"] == "坏数据"
    assert bad["止损价"] in (None, "")
    assert bad["建议操作"] in ("买入", "观望", "回避")  # derived from rating fallback
    # long-form sheets carry a single 数据不足 row for the failed stock
    risk_bad = [r for r in _sheet(sheets, "风控执行计划")["rows"] if r.get("代码") == "000002"]
    assert len(risk_bad) == 1 and "数据不足" in str(risk_bad[0].get("说明") or risk_bad[0].get("计划"))
    quant_bad = [r for r in _sheet(sheets, "量化模型矩阵")["rows"] if r.get("代码") == "000002"]
    assert len(quant_bad) == 1 and "数据不足" in str(quant_bad[0].get("信号") or quant_bad[0].get("模型"))


def test_time_budget_skips_remaining_stocks():
    ticks = iter([0.0, 0.0, 500.0, 500.0, 500.0, 500.0])
    calls = []

    def fetcher(code):
        calls.append(code)
        return _full_suite(code)

    canvas = _canvas(_stock_node("688111"), _stock_node("000002"))
    sheets, cov = ox.build_suite_sheets(
        canvas, suite_fetcher=fetcher, time_budget_sec=150.0, clock=lambda: next(ticks),
    )
    assert calls == ["688111"]              # second stock skipped before fetch
    assert cov["succeeded"] == 1
    assert cov["skipped_over_budget"] == 1


def test_suite_limit_zero_runs_pure_baseline():
    calls = []
    canvas = _canvas(_stock_node("688111"), _stock_node("000002"))
    sheets, cov = ox.build_suite_sheets(
        canvas, suite_fetcher=lambda c: (calls.append(c) or _full_suite(c)), suite_limit=0,
    )
    assert calls == []                       # no enrichment attempted
    assert cov["skipped_over_limit"] == 2
    assert cov["succeeded"] == 0
    # 速览 still lists both stocks from baseline
    assert {r["代码"] for r in _sheet(sheets, "投资速览")["rows"]} == {"688111", "000002"}


def test_none_fetcher_runs_pure_baseline():
    sheets, cov = ox.build_suite_sheets(_canvas(_stock_node()), suite_fetcher=None)
    assert cov["succeeded"] == 0
    assert _row_for(_sheet(sheets, "投资速览"), "688111")["名称"] == "金山办公"


# --------------------------------------------------------------- style spec


def test_overview_style_spec_declares_updown_score_and_freeze():
    sheets, _ = ox.build_suite_sheets(_canvas(_stock_node()), suite_fetcher=lambda c: _full_suite(c))
    style = _sheet(sheets, "投资速览")["style"]
    assert style.get("freeze_panes")            # header + identity columns frozen
    rules = {(r["column"], r["kind"]) for r in style.get("color_rules", [])}
    assert ("当日涨幅", "updown") in rules        # 红涨绿跌
    assert ("综合评分", "score") in rules
    assert ("建议操作", "action") in rules
