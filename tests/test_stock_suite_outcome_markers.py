# -*- coding: utf-8 -*-
"""个股分析套件的「入选后表现标记」接入单测(TDD 先行)。

口径要求(2026-07-29):
- 优先复用该股**最近一次机会挖掘入选**时已入库的标记 —— 与报告完全一致, 不重算;
- 从未入选/旧版 run 无标记时, **标记分析照常执行**: 技术分/追高风险/RSI/5日涨幅
  由 ``OpportunityScorer.marker_factors_from_ohlcv`` 按机会挖掘同口径现场算,
  板块情绪/卖出信号沿用本链路结果; 只有真拿不到的因子才进 ``missing_factors``;
- 任何一步失败都不能让整个套件装配崩掉。
"""
import json
from unittest.mock import patch

import pandas as pd
import pytest

from analysis.stock_analysis_suite import StockAnalysisSuite


@pytest.fixture
def suite():
    return StockAnalysisSuite.__new__(StockAnalysisSuite)  # 免网络/缓存依赖


@pytest.fixture
def ohlcv():
    """一段足够长的日线，够评分器算技术分/追高风险。"""
    n = 260
    close = [10.0 + i * 0.05 for i in range(n)]
    return pd.DataFrame({
        "timestamps": pd.date_range("2025-01-02", periods=n, freq="D"),
        "open": close,
        "high": [c * 1.02 for c in close],
        "low": [c * 0.98 for c in close],
        "close": close,
        "volume": [1_000_000] * n,
        "amount": [c * 1_000_000 for c in close],
    })


def _stored_row(markers_payload, run_date="2026-07-28"):
    return {
        "code": "600000",
        "run_date": run_date,
        "run_at": f"{run_date}T15:30:00",
        "signals_json": json.dumps({
            "rsi": 62.0,
            "markers": markers_payload["markers"],
            "constitution": markers_payload["constitution"],
            "marker_description": markers_payload["description"],
            "markers_version": markers_payload["version"],
        }, ensure_ascii=False),
    }


class TestReuseStoredMarkers:
    def test_prefers_stored_markers_from_last_selection(self, suite):
        from analysis.outcome_markers import marker_payload
        payload = marker_payload({"tech_score": 70, "sector_score": 45, "sell_signals": 0})
        with patch("data_store.opportunity_repo.latest_item_for_code",
                   return_value=_stored_row(payload)):
            out = suite._collect_outcome_markers("600000", inputs={})
        assert out["available"] is True
        assert out["source"] == "opportunity_run"
        assert out["as_of"] == "2026-07-28"
        assert out["constitution"]["grade"] == "爆发体质"
        assert {m["key"] for m in out["markers"]} == {"breakout_gene", "clean_sell"}

    def test_falls_back_when_stored_run_predates_markers(self, suite):
        """旧版 run 的 signals_json 没有 markers 键 → 走本地兜底。"""
        old_row = {"code": "600000", "run_date": "2026-06-01",
                   "signals_json": json.dumps({"rsi": 62.0, "chase": 30.0})}
        with patch("data_store.opportunity_repo.latest_item_for_code",
                   return_value=old_row):
            out = suite._collect_outcome_markers(
                "600000", inputs={"sector": {"sentiment_score": 98.0}})
        assert out["source"] == "local"
        assert "sector_overheat" in {m["key"] for m in out["markers"]}


class TestLocalFallback:
    def test_local_factors_drive_markers(self, suite):
        inputs = {
            "sector": {"sentiment_score": 98.0},
            "models": {"sell_signal_count": 5, "total": 30},
        }
        with patch("data_store.opportunity_repo.latest_item_for_code", return_value=None):
            out = suite._collect_outcome_markers("600000", inputs=inputs)
        keys = {m["key"] for m in out["markers"]}
        assert out["source"] == "local"
        assert "sector_overheat" in keys and "sell_pressure" in keys

    def test_clean_sell_from_zero_sell_signals(self, suite):
        inputs = {"models": {"sell_signal_count": 0, "total": 30}}
        with patch("data_store.opportunity_repo.latest_item_for_code", return_value=None):
            out = suite._collect_outcome_markers("600000", inputs=inputs)
        assert "clean_sell" in {m["key"] for m in out["markers"]}

    def test_stored_source_is_not_partial(self, suite):
        from analysis.outcome_markers import marker_payload
        payload = marker_payload({"tech_score": 70, "sector_score": 45,
                                  "sell_signals": 0, "chase_risk": 20, "rsi": 60})
        with patch("data_store.opportunity_repo.latest_item_for_code",
                   return_value=_stored_row(payload)):
            out = suite._collect_outcome_markers("600000", inputs={})
        assert out["partial"] is False
        assert out["missing_factors"] == []


class TestScorerDerivedFactors:
    """没有机会挖掘记录时, 技术分/追高风险也要照常算出来(不能挂着"缺失")。"""

    def test_tech_and_chase_derived_from_ohlcv(self, suite, ohlcv):
        inputs = {"ohlcv": ohlcv, "sector": {"sentiment_score": 50.0},
                  "models": {"sell_signal_count": 1, "total": 30}}
        factors = suite._local_marker_factors("600000", inputs)
        assert factors["tech_score"] is not None
        assert factors["chase_risk"] is not None
        assert factors["rsi"] is not None
        assert factors["change_5d"] is not None

    def test_no_missing_factors_when_ohlcv_present(self, suite, ohlcv):
        inputs = {"ohlcv": ohlcv, "sector": {"sentiment_score": 50.0},
                  "models": {"sell_signal_count": 1, "total": 30}}
        with patch("data_store.opportunity_repo.latest_item_for_code", return_value=None):
            out = suite._collect_outcome_markers("600000", inputs=inputs)
        assert out["missing_factors"] == []
        assert out["partial"] is False
        assert "缺失因子" not in out["note"]

    def test_factors_match_scorer_caliber_exactly(self, suite, ohlcv):
        """本地推导必须与机会挖掘同口径 —— 逐值比对, 不允许另写近似公式。"""
        from analysis.stock_analysis_suite import _marker_scorer
        expected = _marker_scorer().marker_factors_from_ohlcv("600000", ohlcv)
        factors = suite._local_marker_factors("600000", {"ohlcv": ohlcv})
        for key, value in expected.items():
            assert factors[key] == value

    def test_missing_factors_declared_when_no_ohlcv(self, suite):
        """真拿不到时仍要显式告知, 而不是静默漏判。"""
        with patch("data_store.opportunity_repo.latest_item_for_code", return_value=None):
            out = suite._collect_outcome_markers("600000", inputs={})
        assert out["partial"] is True
        assert "技术分" in out["missing_factors"]
        assert "追高风险" in out["missing_factors"]

    def test_empty_ohlcv_never_fakes_zero_tech_score(self, suite):
        """评分器无数据时返回 tech=0.0, 直接用会误触发「技术乏力」—— 必须按缺失处理。"""
        empty = pd.DataFrame(columns=["timestamps", "open", "high", "low", "close", "volume"])
        factors = suite._local_marker_factors("600000", {"ohlcv": empty})
        assert factors["tech_score"] is None
        with patch("data_store.opportunity_repo.latest_item_for_code", return_value=None):
            out = suite._collect_outcome_markers("600000", inputs={"ohlcv": empty})
        assert "tech_weak" not in {m["key"] for m in out["markers"]}

    def test_scorer_failure_degrades_to_local_price_factors(self, suite, ohlcv):
        """评分器炸了也要把 RSI/5日涨幅补上, 不能整块因子清零。"""
        with patch("analysis.stock_analysis_suite._marker_scorer", return_value=None):
            factors = suite._local_marker_factors("600000", {"ohlcv": ohlcv})
        assert factors["tech_score"] is None
        assert factors["rsi"] is not None
        assert factors["change_5d"] is not None


class TestResilience:
    def test_repo_failure_degrades_to_local(self, suite):
        with patch("data_store.opportunity_repo.latest_item_for_code",
                   side_effect=RuntimeError("db down")):
            out = suite._collect_outcome_markers(
                "600000", inputs={"sector": {"sentiment_score": 99.0}})
        assert out["source"] == "local"
        assert "sector_overheat" in {m["key"] for m in out["markers"]}

    def test_corrupt_signals_json_does_not_raise(self, suite):
        bad = {"code": "600000", "run_date": "2026-07-28", "signals_json": "{not json"}
        with patch("data_store.opportunity_repo.latest_item_for_code", return_value=bad):
            out = suite._collect_outcome_markers("600000", inputs={})
        assert out["source"] == "local"

    def test_no_data_at_all_is_still_well_formed(self, suite):
        with patch("data_store.opportunity_repo.latest_item_for_code", return_value=None):
            out = suite._collect_outcome_markers("600000", inputs=None)
        assert out["available"] is False
        assert out["markers"] == []
        assert out["constitution"]["grade"] == "中性体质"
        assert isinstance(out["description"], str)

    def test_result_is_json_serializable(self, suite, ohlcv):
        with patch("data_store.opportunity_repo.latest_item_for_code", return_value=None):
            out = suite._collect_outcome_markers(
                "600000", inputs={"ohlcv": ohlcv, "sector": {"sentiment_score": 99.0}})
        json.dumps(out, ensure_ascii=False)


class TestPayloadWiring:
    def test_full_payload_exposes_outcome_markers_key(self):
        """_compute_full_payload 必须把标记挂到顶层, 前端才能渲染。"""
        import inspect
        src = inspect.getsource(StockAnalysisSuite._compute_full_payload)
        assert "outcome_markers" in src
