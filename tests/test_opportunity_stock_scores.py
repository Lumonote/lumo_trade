"""投资机会挖掘·个股深度评分(懒加载):_opportunity_stock_scores 三块分值。

形态回测 + 多空评审团共用一次日K拉取(注入 fetch_klines 隔离网络);
资金榜单走 capital_summary 注入。三者任一失败互不影响,各自降级。
"""
from __future__ import annotations

import math

import pytest


def _ohlcv_klines(n=300):
    """造一段有重复形态的正弦+上行趋势日K(含 OHLCV 五列),
    保证 scan_series 命中并有前向收益,同时够 30 量化模型跑出信号。"""
    out = []
    for i in range(n):
        close = 100 + 0.05 * i + 5 * math.sin(i / 6.0)
        openp = close - 0.3 * math.cos(i / 6.0)
        high = max(openp, close) + 0.5
        low = min(openp, close) - 0.5
        out.append({
            "day": f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
            "open": round(openp, 3),
            "high": round(high, 3),
            "low": round(low, 3),
            "close": round(close, 3),
            "volume": 1_000_000 + (i % 50) * 10_000,
        })
    return out


def _capital_summary_hit(code):
    return {
        "kind": "stock_capital_rankings",
        "code": code,
        "days": 5,
        "data_status": "fresh",
        "moneyflow": {"data_status": "fresh", "row": {"rank": 12, "net_amount": 1.5e8, "list_count": 3}},
        "dragon_tiger": {"data_status": "fresh", "row": {"rank": 4, "net_amount": 8e7, "list_count": 2, "reason": "涨停板"}},
    }


@pytest.fixture
def core():
    import webui.core as core
    return core


def test_stock_scores_all_three_blocks(core):
    fake = lambda symbol, limit=250: ("测试股", _ohlcv_klines(300))
    out = core._opportunity_stock_scores(
        "600000", name="浦发银行", window_days=20,
        fetch_klines=fake, capital_summary=_capital_summary_hit,
    )
    assert out["ok"] is True
    assert out["code"] == "600000"

    # 形态回测
    pattern = out["pattern"]
    assert pattern["data_status"] in {"fresh", "thin"}
    assert "pattern_score" in pattern and "win_rate" in pattern
    assert "10" in pattern["horizons"]

    # 多空评审团(30 模型)
    jury = out["jury"]
    assert jury["data_status"] == "fresh"
    assert jury["total_models"] == 30
    assert 0 <= jury["game_score"] <= 100
    assert jury["bullish"] + jury["bearish"] + jury["sideways"] == 100
    assert jury["label"] in {"观望主导", "强势多头", "震荡偏多", "震荡", "震荡偏空", "强势空头"}

    # 资金榜单(注入命中)
    capital = out["capital"]
    assert capital["data_status"] == "fresh"
    assert capital["moneyflow"]["row"]["rank"] == 12


def test_stock_scores_insufficient_history_degrades_pattern_and_jury(core):
    fake = lambda symbol, limit=250: ("测试股", _ohlcv_klines(20))  # 太短
    out = core._opportunity_stock_scores(
        "000001", window_days=30,
        fetch_klines=fake, capital_summary=lambda c: {"data_status": "unavailable", "reason": "无记录"},
    )
    assert out["ok"] is True
    assert out["pattern"]["data_status"] == "unavailable"
    assert out["jury"]["data_status"] == "unavailable"
    # 资金榜单独立降级,不受日K不足影响
    assert out["capital"]["data_status"] == "unavailable"


def test_stock_scores_kline_fetch_failure_isolated_from_capital(core):
    def boom(symbol, limit=250):
        raise RuntimeError("网络超时")
    out = core._opportunity_stock_scores(
        "600000", fetch_klines=boom, capital_summary=_capital_summary_hit,
    )
    assert out["ok"] is True
    assert out["pattern"]["data_status"] == "unavailable"
    assert out["jury"]["data_status"] == "unavailable"
    # 日K挂了,资金榜单仍正常
    assert out["capital"]["data_status"] == "fresh"


def test_stock_scores_capital_failure_isolated(core):
    fake = lambda symbol, limit=250: ("测试股", _ohlcv_klines(300))

    def boom(code):
        raise RuntimeError("库读取失败")
    out = core._opportunity_stock_scores(
        "600000", window_days=20, fetch_klines=fake, capital_summary=boom,
    )
    assert out["ok"] is True
    assert out["pattern"]["data_status"] in {"fresh", "thin"}
    assert out["capital"]["data_status"] == "unavailable"


def test_stock_scores_missing_code(core):
    out = core._opportunity_stock_scores("", fetch_klines=lambda s, limit=250: ("", []))
    assert out["ok"] is False


def test_klines_to_ohlcv_df_filters_invalid(core):
    klines = [
        {"open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000},
        {"open": 0, "high": 0, "low": 0, "close": 0, "volume": 0},   # 非法,丢弃
        {"open": 10.5, "high": 11.5, "low": 10, "close": 11, "volume": 1200},
    ]
    df = core._klines_to_ohlcv_df(klines)
    assert df is not None
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert core._klines_to_ohlcv_df([]) is None
