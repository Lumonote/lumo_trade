# -*- coding: utf-8 -*-
"""market_regime 纯函数单测(TDD 先行)。

背景(2026-07-27 回测调查): 6~7月小盘/题材崩盘(中证1000 单月-18%)时,
既有门控只盯沪深300 从未触发 → 门控必须纳入小盘风格指数;
Top10 样本 91% 都是 S 级 → 分级阈值改滚动分位数(带静态下限);
回测表须并排同期指数基准,"差"才可归因。
"""
import math

import pytest

from analysis.market_regime import (
    classify_index_level,
    classify_style_regime,
    compute_dynamic_tier_thresholds,
    forward_returns_for_dates,
    merge_regime_levels,
    position_advice,
    resolve_tier,
    trailing_changes,
)


# ---------------------------------------------------------------- 趋势指标
class TestTrailingChanges:
    def test_basic_5d_20d(self):
        closes = list(range(1, 31))  # 1..30
        m = trailing_changes(closes)
        assert m["chg_5d"] == pytest.approx((30 - 25) / 25 * 100)
        assert m["chg_20d"] == pytest.approx((30 - 10) / 10 * 100)

    def test_insufficient_history_gives_none(self):
        m = trailing_changes([10.0, 11.0, 12.0])
        assert m["chg_5d"] is None
        assert m["chg_20d"] is None

    def test_20d_missing_but_5d_present(self):
        m = trailing_changes([100.0] * 10)
        assert m["chg_5d"] == pytest.approx(0.0)
        assert m["chg_20d"] is None


# ---------------------------------------------------------------- 单指数分级
class TestClassifyIndexLevel:
    def test_crash_is_risk_off(self):
        assert classify_index_level({"chg_5d": -4.0, "chg_20d": -10.0}) == "risk_off"

    def test_slow_bleed_is_risk_off(self):
        assert classify_index_level({"chg_5d": -1.2, "chg_20d": -6.0}) == "risk_off"

    def test_mild_weakness_is_caution(self):
        assert classify_index_level({"chg_5d": -2.0, "chg_20d": 1.0}) == "caution"

    def test_strong_uptrend_is_risk_on(self):
        assert classify_index_level({"chg_5d": 3.5, "chg_20d": 5.0}) == "risk_on"

    def test_flat_is_neutral(self):
        assert classify_index_level({"chg_5d": 0.5, "chg_20d": 1.0}) == "neutral"

    def test_missing_data_is_unknown(self):
        assert classify_index_level({"chg_5d": None, "chg_20d": None}) == "unknown"
        assert classify_index_level({}) == "unknown"


# ---------------------------------------------------------------- 合并与风格
class TestMergeAndStyle:
    def test_merge_takes_worst(self):
        assert merge_regime_levels(["neutral", "risk_off"]) == "risk_off"
        assert merge_regime_levels(["risk_on", "caution"]) == "caution"

    def test_merge_ignores_unknown_when_any_known(self):
        assert merge_regime_levels(["unknown", "neutral"]) == "neutral"

    def test_merge_all_unknown(self):
        assert merge_regime_levels(["unknown", "unknown"]) == "unknown"
        assert merge_regime_levels([]) == "unknown"

    def test_smallcap_crash_with_flat_hs300_is_risk_off(self):
        """2026-06/07 实际场景: 沪深300走平、中证1000崩 → 必须 risk_off。"""
        result = classify_style_regime({
            "沪深300": {"chg_5d": 0.1, "chg_20d": 0.5},
            "中证1000": {"chg_5d": -4.5, "chg_20d": -12.0},
            "国证2000": {"chg_5d": -5.0, "chg_20d": -13.0},
        })
        assert result["style_regime"] == "risk_off"
        assert any("中证1000" in r or "国证2000" in r for r in result["reasons"])

    def test_all_healthy_is_risk_on(self):
        result = classify_style_regime({
            "沪深300": {"chg_5d": 3.2, "chg_20d": 4.0},
            "中证1000": {"chg_5d": 4.0, "chg_20d": 6.0},
        })
        assert result["style_regime"] == "risk_on"

    def test_empty_is_unknown(self):
        assert classify_style_regime({})["style_regime"] == "unknown"

    def test_position_advice_has_text_for_all_levels(self):
        for level in ("risk_off", "caution", "neutral", "risk_on", "unknown"):
            assert position_advice(level)


# ---------------------------------------------------------------- 动态分级阈值
class TestDynamicTierThresholds:
    FLOORS = {"S": 85.0, "A": 78.0, "B": 70.0}

    def test_saturated_scores_lift_thresholds_above_floor(self):
        scores = [float(x) for x in range(60, 100)]  # 60..99, n=40... 需>=min_samples
        result = compute_dynamic_tier_thresholds(scores, floors=self.FLOORS, min_samples=30)
        assert result["dynamic"] is True
        # P85 of 60..99 = 93.15 > 85 → S 阈值抬升
        assert result["S"] == pytest.approx(93.15, abs=0.1)
        assert result["S"] > self.FLOORS["S"]
        assert result["A"] < result["S"]
        assert result["B"] < result["A"]

    def test_thresholds_never_below_floor(self):
        scores = [50.0] * 100  # 全体低分 → 分位数低于下限 → 用下限
        result = compute_dynamic_tier_thresholds(scores, floors=self.FLOORS, min_samples=30)
        assert result["S"] == self.FLOORS["S"]
        assert result["A"] == self.FLOORS["A"]
        assert result["B"] == self.FLOORS["B"]

    def test_small_sample_falls_back_to_floors(self):
        result = compute_dynamic_tier_thresholds([90.0] * 10, floors=self.FLOORS, min_samples=30)
        assert result["dynamic"] is False
        assert result["S"] == self.FLOORS["S"]

    def test_cap_pileup_bounded_by_ceiling(self):
        """v24时代52%样本顶格100分: 纯分位数会得 S=100 → 新评分版本上线后
        当日全判C。阈值须封顶在 floor+10 带宽内,避免退化。"""
        scores = [100.0] * 60 + [95.0] * 40  # P85=P60=100
        result = compute_dynamic_tier_thresholds(scores, floors=self.FLOORS, min_samples=30)
        assert result["dynamic"] is True
        assert result["S"] == pytest.approx(self.FLOORS["S"] + 10)   # 95, not 100
        assert result["A"] <= self.FLOORS["A"] + 10                  # ≤88
        assert result["B"] <= self.FLOORS["B"] + 10                  # ≤80
        assert result["S"] > result["A"] > result["B"]

    def test_empty_scores_falls_back(self):
        result = compute_dynamic_tier_thresholds([], floors=self.FLOORS)
        assert result["dynamic"] is False

    def test_resolve_tier_boundaries(self):
        thr = {"S": 92.0, "A": 80.0, "B": 70.0}
        assert resolve_tier(92.0, thr) == "S"
        assert resolve_tier(91.9, thr) == "A"
        assert resolve_tier(80.0, thr) == "A"
        assert resolve_tier(79.9, thr) == "B"
        assert resolve_tier(69.9, thr) == "C"
        assert resolve_tier(None, thr) == "C"


# ---------------------------------------------------------------- 指数前瞻收益
def _mk_bars(days_prices):
    """[(day, open, close)] → sina 风格 bars。"""
    return [{"day": d, "open": str(o), "close": str(c), "high": str(max(o, c)),
             "low": str(min(o, c)), "volume": "1"} for d, o, c in days_prices]


class TestForwardReturns:
    def test_next_open_to_5th_close(self):
        # 报告日 07-01;次日(07-02)开盘100买入,第5个交易日(07-08)收盘110卖出 → +10%
        bars = _mk_bars([
            ("2026-07-01", 99, 99),
            ("2026-07-02", 100, 101),
            ("2026-07-03", 101, 102),
            ("2026-07-06", 102, 103),
            ("2026-07-07", 103, 104),
            ("2026-07-08", 105, 110),
        ])
        result = forward_returns_for_dates(bars, ["2026-07-01"], horizon=5)
        assert result["2026-07-01"] == pytest.approx(10.0)

    def test_report_date_between_trade_days_uses_next_trade_day(self):
        bars = _mk_bars([
            ("2026-07-03", 99, 99),
            ("2026-07-06", 200, 200),
            ("2026-07-07", 200, 200),
            ("2026-07-08", 200, 200),
            ("2026-07-09", 200, 200),
            ("2026-07-10", 200, 210),
        ])
        # 周六 07-04 出报告 → 07-06 开盘买
        result = forward_returns_for_dates(bars, ["2026-07-04"], horizon=5)
        assert result["2026-07-04"] == pytest.approx(5.0)

    def test_insufficient_forward_bars_excluded(self):
        bars = _mk_bars([("2026-07-01", 100, 100), ("2026-07-02", 100, 101)])
        result = forward_returns_for_dates(bars, ["2026-07-01"], horizon=5)
        assert "2026-07-01" not in result

    def test_zero_open_guarded(self):
        bars = _mk_bars([
            ("2026-07-01", 99, 99),
            ("2026-07-02", 0, 0),
            ("2026-07-03", 1, 1),
            ("2026-07-06", 1, 1),
            ("2026-07-07", 1, 1),
            ("2026-07-08", 1, 1),
        ])
        result = forward_returns_for_dates(bars, ["2026-07-01"], horizon=5)
        assert "2026-07-01" not in result
