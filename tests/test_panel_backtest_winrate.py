"""Phase 3 ★回测胜率指标测试：纯 OHLCV、无前视的历史形态胜率 + 指标渲染。"""
import pandas as pd

from analysis.panel.backtest_winrate import compute_backtest_winrate
from analysis.panel.indicators import build_indicators


def _df(closes):
    n = len(closes)
    return pd.DataFrame({
        "timestamps": pd.date_range("2025-01-01", periods=n, freq="D"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1e6] * n,
        "amount": [1e7] * n,
    })


def test_rising_series_full_winrate():
    """单调上行 → 任意 N 日后必涨，当前多头排列，条件胜率 100%。"""
    r = compute_backtest_winrate(_df([100 + i for i in range(120)]), horizon=5)
    assert r is not None
    assert r["winrate"] == 1.0
    assert r["state"] == "bull"
    assert r["confident"] is True


def test_falling_series_zero_winrate():
    """单调下行 → N 日后必跌，当前空头排列，胜率 0%。"""
    r = compute_backtest_winrate(_df([300 - i for i in range(120)]), horizon=5)
    assert r is not None
    assert r["winrate"] == 0.0
    assert r["state"] == "bear"


def test_short_series_returns_none():
    """不足 60 行 → 数据不足 → None。"""
    assert compute_backtest_winrate(_df([100 + i for i in range(40)])) is None


def test_none_df_returns_none():
    assert compute_backtest_winrate(None) is None


def test_indicator_renders_winrate_up():
    inds = build_indicators({"backtest_winrate": {
        "winrate": 0.62, "sample": 40, "horizon": 5, "state": "bull", "confident": True}})
    bw = next(i for i in inds if i["key"] == "backtest_winrate")
    assert bw["data_status"] == "fresh"
    assert bw["signal"] == "up"
    assert "62%" in bw["value_text"]
    assert "多头排列" in bw["value_text"]


def test_indicator_unavailable_without_winrate():
    bw = next(i for i in build_indicators({}) if i["key"] == "backtest_winrate")
    assert bw["data_status"] == "unavailable"
