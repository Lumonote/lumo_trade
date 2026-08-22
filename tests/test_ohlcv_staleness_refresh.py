# -*- coding: utf-8 -*-
"""个股分析日线的**新鲜度**门槛(2026-08-16)。

背景: `_load_ohlcv` 原本只看行数, 行数够就直接返回, 于是本地库里停在几个月前的
日线会被当成可用数据, 让整页分析(筹码/资金/量化/RSI/入选后表现标记)静默跑在过期
数据上 —— 表现标记的"当前状态"甚至比入选日期还早, 用户无从察觉。

口径:
- 行数够但最后一根 K 线早于「最近应有的交易日」→ 也要补偿, 补到了用新的;
- 补不动(停牌/退市/长假)→ 照常用旧的, 但不假装它新, 且按退避窗口限流不空打网络;
- auto_fetch 关闭时行为不变(离线/测试路径不许触网)。
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import pytest

from analysis.stock_analysis_suite import StockAnalysisSuite


def _frame(n: int, end: _dt.date) -> pd.DataFrame:
    close = [10.0 + i * 0.01 for i in range(n)]
    return pd.DataFrame({
        "timestamps": pd.date_range(end=pd.Timestamp(end), periods=n, freq="D"),
        "open": close, "high": [c * 1.02 for c in close], "low": [c * 0.98 for c in close],
        "close": close, "volume": [1e6] * n, "amount": [c * 1e6 for c in close],
    })


def _patch_repo(monkeypatch, frames: dict) -> None:
    from data_store import ohlcv_repo

    def _load(code, frequency):
        df = frames.get(frequency)
        return df if df is not None else pd.DataFrame()

    monkeypatch.setattr(ohlcv_repo, "load_dataframe", _load)


class TestExpectedLatestTradingDay:
    def test_weekend_falls_back_to_friday(self):
        sunday = _dt.datetime(2026, 8, 16, 10, 0)  # 周日
        assert StockAnalysisSuite._expected_latest_trading_day(sunday) == _dt.date(2026, 8, 14)

    def test_before_close_expects_previous_session(self):
        """周三 09:30 当天日线还没收出来 → 期望值是周二。"""
        wednesday_open = _dt.datetime(2026, 8, 12, 9, 30)
        assert StockAnalysisSuite._expected_latest_trading_day(wednesday_open) == _dt.date(2026, 8, 11)

    def test_after_close_expects_today(self):
        wednesday_close = _dt.datetime(2026, 8, 12, 15, 30)
        assert StockAnalysisSuite._expected_latest_trading_day(wednesday_close) == _dt.date(2026, 8, 12)

    def test_monday_before_close_skips_weekend_to_friday(self):
        monday_open = _dt.datetime(2026, 8, 17, 9, 30)
        assert StockAnalysisSuite._expected_latest_trading_day(monday_open) == _dt.date(2026, 8, 14)


class TestIsStale:
    def test_last_bar_months_old_is_stale(self):
        now = _dt.datetime(2026, 8, 14, 16, 0)
        assert StockAnalysisSuite._ohlcv_is_stale(_frame(120, _dt.date(2026, 6, 1)), now) is True

    def test_last_bar_at_expected_session_is_fresh(self):
        now = _dt.datetime(2026, 8, 14, 16, 0)
        assert StockAnalysisSuite._ohlcv_is_stale(_frame(120, _dt.date(2026, 8, 14)), now) is False

    def test_empty_or_malformed_never_claims_stale(self):
        assert StockAnalysisSuite._ohlcv_is_stale(None) is False
        assert StockAnalysisSuite._ohlcv_is_stale(pd.DataFrame()) is False
        assert StockAnalysisSuite._ohlcv_is_stale(pd.DataFrame({"close": [1.0]})) is False


class TestStaleTriggersRefresh:
    def test_sufficient_but_stale_frame_triggers_fetch(self, monkeypatch):
        stale, fresh = _frame(120, _dt.date(2026, 6, 1)), _frame(120, _dt.date.today())
        frames = {"1d": stale, "5m": pd.DataFrame()}
        _patch_repo(monkeypatch, frames)
        suite = StockAnalysisSuite(auto_fetch=True)
        calls = []

        def _fetch(code):
            calls.append(code)
            frames["1d"] = fresh  # 模拟补偿写库后重扫命中新数据
            return True

        suite._ensure_ohlcv_daily = _fetch  # type: ignore[attr-defined]
        out = suite._load_ohlcv("000001")
        assert calls == ["000001"]
        assert out["timestamps"].iloc[-1].date() == fresh["timestamps"].iloc[-1].date()

    def test_fresh_frame_never_touches_network(self, monkeypatch):
        _patch_repo(monkeypatch, {"1d": _frame(120, _dt.date.today()), "5m": pd.DataFrame()})
        suite = StockAnalysisSuite(auto_fetch=True)
        suite._ensure_ohlcv_daily = lambda code: pytest.fail("新鲜数据不该触发补偿")  # type: ignore[attr-defined]
        assert len(suite._load_ohlcv("000001")) == 120

    def test_failed_refresh_still_returns_stale_frame(self, monkeypatch):
        """停牌/退市补不动 → 用旧的，不抛错、不清空整页。"""
        stale = _frame(120, _dt.date(2026, 6, 1))
        _patch_repo(monkeypatch, {"1d": stale, "5m": pd.DataFrame()})
        suite = StockAnalysisSuite(auto_fetch=True)
        suite._ensure_ohlcv_daily = lambda code: False  # type: ignore[attr-defined]
        out = suite._load_ohlcv("000001")
        assert out["timestamps"].iloc[-1].date() == _dt.date(2026, 6, 1)

    def test_stale_refresh_is_rate_limited(self, monkeypatch):
        """补不动的票不能每次打开都空打一次网络。"""
        _patch_repo(monkeypatch, {"1d": _frame(120, _dt.date(2026, 6, 1)), "5m": pd.DataFrame()})
        suite = StockAnalysisSuite(auto_fetch=True)
        calls = []
        suite._ensure_ohlcv_daily = lambda code: (calls.append(code), False)[1]  # type: ignore[attr-defined]
        suite._load_ohlcv("000001")
        suite._load_ohlcv("000001")
        suite._load_ohlcv("000001")
        assert calls == ["000001"]

    def test_auto_fetch_off_keeps_offline_behaviour(self, monkeypatch):
        _patch_repo(monkeypatch, {"1d": _frame(120, _dt.date(2026, 6, 1)), "5m": pd.DataFrame()})
        suite = StockAnalysisSuite(auto_fetch=False)
        suite._ensure_ohlcv_daily = lambda code: pytest.fail("auto_fetch=False 不许触网")  # type: ignore[attr-defined]
        assert len(suite._load_ohlcv("000001")) == 120

    def test_short_history_path_unchanged(self, monkeypatch):
        """行数不足仍走原来的补偿 → 分级降级，不受新鲜度门槛影响。"""
        _patch_repo(monkeypatch, {"1d": _frame(40, _dt.date(2026, 6, 1)), "5m": pd.DataFrame()})
        suite = StockAnalysisSuite(auto_fetch=True)
        calls = []
        suite._ensure_ohlcv_daily = lambda code: (calls.append(code), False)[1]  # type: ignore[attr-defined]
        assert len(suite._load_ohlcv("000001")) == 40
        assert calls == ["000001"]
