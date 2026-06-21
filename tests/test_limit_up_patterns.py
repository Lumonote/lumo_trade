import pandas as pd

from analysis.limit_up_patterns import (
    backtest_all,
    backtest_pattern_on_history,
    bars_from_dataframe,
    bars_from_records,
    board_limit_pct,
    detect_all,
    detect_kline_patterns,
    is_limit_up,
)


def bar(date, open_, close, high=None, low=None, volume=1000, pct_chg=None):
    high = max(open_, close) if high is None else high
    low = min(open_, close) if low is None else low
    out = {
        "date": date,
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
    }
    if pct_chg is not None:
        out["pct_chg"] = float(pct_chg)
    return out


def trend_prefix(n=80, start=10.0):
    bars = []
    close = start
    for i in range(n):
        close *= 1.002
        bars.append(bar(
            f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
            close * 0.995,
            close,
            high=close * 1.01,
            low=close * 0.99,
            volume=1000 + i,
        ))
    return bars


def append_zt(bars, date, prev_close, volume=5000):
    close = round(prev_close * 1.10, 2)
    bars.append(bar(date, prev_close * 1.02, close, high=close, low=prev_close * 1.01, volume=volume, pct_chg=10.0))
    return close


def patterns(bars, code="600000", recent_days=None):
    return {m["pattern"]: m for m in detect_all(bars, code=code, recent_days=recent_days)}


def test_board_limit_pct_by_market_and_name():
    assert board_limit_pct("600000") == 10.0
    assert board_limit_pct("000001") == 10.0
    assert board_limit_pct("300001") == 20.0
    assert board_limit_pct("688001") == 20.0
    assert board_limit_pct("830000") == 30.0
    assert board_limit_pct("600000", "ST测试") == 5.0
    assert board_limit_pct("300001", "*ST测试") == 5.0
    assert board_limit_pct("", None) == 10.0


def test_is_limit_up_requires_sealed_close_near_high():
    assert is_limit_up(bar("2026-01-02", 10, 11, high=11, low=10, pct_chg=10.0), 10.0)
    assert is_limit_up(bar("2026-01-02", 10, 10.95, high=10.96, low=10, pct_chg=9.5), 10.0)
    assert not is_limit_up(bar("2026-01-02", 10, 10.7, high=11.0, low=10, pct_chg=10.0), 10.0)
    assert not is_limit_up(bar("2026-01-02", 10, 10.93, high=10.93, low=10, pct_chg=9.3), 10.0)


def test_bars_from_records_sorts_and_computes_pct_change():
    records = [
        bar("2026-01-03", 10, 11),
        bar("2026-01-01", 10, 10),
        bar("2026-01-02", 10, 10.5),
    ]
    bars = bars_from_records(records)
    assert [b["date"] for b in bars] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert bars[0]["pct_chg"] == 0.0
    assert round(bars[1]["pct_chg"], 2) == 5.0
    assert round(bars[2]["pct_chg"], 2) == 4.76


def test_bars_from_dataframe_accepts_timestamp_column_and_index():
    df = pd.DataFrame({
        "timestamps": pd.to_datetime(["2026-01-02", "2026-01-01"]),
        "open": [10, 9],
        "high": [11, 10],
        "low": [9, 8.8],
        "close": [10.5, 9.5],
        "volume": [2000, 1000],
    })
    bars = bars_from_dataframe(df)
    assert [b["date"] for b in bars] == ["2026-01-01", "2026-01-02"]
    assert all({"date", "open", "high", "low", "close", "volume", "pct_chg"} <= set(b) for b in bars)


def test_detect_pullback_double_volume():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    bars.extend([
        bar("2026-04-02", zt_close * 0.99, zt_close * 0.98, high=zt_close, low=zt_close * 0.96, volume=2500),
        bar("2026-04-03", zt_close * 0.98, zt_close * 0.985, high=zt_close, low=zt_close * 0.96, volume=2600),
        bar("2026-04-04", zt_close * 0.99, zt_close * 1.01, high=zt_close * 1.02, low=zt_close * 0.98, volume=5200),
    ])
    got = patterns(bars)
    assert got["zt_pullback_double_volume"]["anchor_date"] == "2026-04-01"
    assert got["zt_pullback_double_volume"]["trigger_date"] == "2026-04-04"


def test_detect_beauty_shoulder():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    bars.extend([
        bar("2026-04-02", zt_close * 0.995, zt_close * 0.985, high=zt_close, low=zt_close * 0.98, volume=4200),
        bar("2026-04-03", zt_close * 0.986, zt_close * 0.980, high=zt_close * 0.99, low=zt_close * 0.975, volume=3600),
        bar("2026-04-04", zt_close * 0.981, zt_close * 0.990, high=zt_close * 0.995, low=zt_close * 0.98, volume=3100),
    ])
    assert patterns(bars)["zt_beauty_shoulder"]["trigger_date"] == "2026-04-04"


def test_detect_high_volume_hold_and_volume_over_left_peak():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=9000)
    low = bars[-1]["low"]
    bars.extend([
        bar("2026-04-02", zt_close * 0.99, zt_close * 0.98, high=zt_close, low=low * 1.002, volume=3000),
        bar("2026-04-03", zt_close * 0.98, zt_close * 1.01, high=zt_close * 1.02, low=low * 1.005, volume=3200),
    ])
    got = patterns(bars)
    assert got["zt_high_volume_hold"]["strength"] == "强"
    assert got["zt_volume_over_left_peak"]["trigger_date"] == "2026-04-01"


def test_detect_huge_yin_rewrap():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    y_open = zt_close * 1.02
    bars.append(bar("2026-04-02", y_open, y_open * 0.95, high=y_open * 1.01, low=y_open * 0.94, volume=9000))
    bars.append(bar("2026-04-03", y_open * 0.96, y_open * 1.02, high=y_open * 1.03, low=y_open * 0.95, volume=7000))
    got = patterns(bars)
    assert got["zt_huge_yin_rewrap"]["anchor_date"] == "2026-04-02"
    assert got["zt_huge_yin_rewrap"]["strength"] == "强"


def test_detect_board_then_bull_cannon():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    bars.extend([
        bar("2026-04-02", zt_close * 1.01, zt_close * 1.03, high=zt_close * 1.04, low=zt_close * 1.00, volume=4200),
        bar("2026-04-03", zt_close * 1.025, zt_close * 1.015, high=zt_close * 1.035, low=zt_close * 1.005, volume=3000),
        bar("2026-04-04", zt_close * 1.018, zt_close * 1.035, high=zt_close * 1.04, low=zt_close * 1.01, volume=4300),
    ])
    assert patterns(bars)["zt_board_then_bull_cannon"]["trigger_date"] == "2026-04-04"


def test_detect_n_shape_relay_and_ma_pullback_hold():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    bars.extend([
        bar("2026-04-02", zt_close * 0.99, zt_close * 0.985, high=zt_close, low=zt_close * 0.975, volume=2500),
        bar("2026-04-03", zt_close * 0.986, zt_close * 0.99, high=zt_close * 0.995, low=zt_close * 0.963, volume=2300),
        bar("2026-04-04", zt_close, zt_close * 1.02, high=zt_close * 1.03, low=zt_close * 0.99, volume=4200),
    ])
    got = patterns(bars)
    assert got["zt_n_shape_relay"]["trigger_date"] == "2026-04-04"
    assert got["zt_ma_pullback_hold"]["trigger_date"] in {"2026-04-03", "2026-04-04"}


def test_detect_consecutive_boards():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    first = append_zt(bars, "2026-04-01", prev, volume=5000)
    append_zt(bars, "2026-04-02", first, volume=8000)
    got = patterns(bars)
    assert got["zt_consecutive_boards"]["trigger_date"] == "2026-04-02"
    assert got["zt_consecutive_boards"]["strength"] == "中"


def test_detect_platform_breakout():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    for i in range(2, 8):
        bars.append(bar(f"2026-04-{i:02d}", zt_close * 0.99, zt_close * (0.99 + i * 0.001), high=zt_close * 1.01, low=zt_close * 0.97, volume=2500))
    bars.append(bar("2026-04-08", zt_close * 1.01, zt_close * 1.04, high=zt_close * 1.05, low=zt_close, volume=4200))
    assert patterns(bars)["zt_platform_breakout"]["trigger_date"] == "2026-04-08"


def test_detect_all_recent_filter_and_sorting():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    first = append_zt(bars, "2026-04-01", prev, volume=5000)
    second = append_zt(bars, "2026-04-02", first, volume=8000)
    append_zt(bars, "2026-04-03", second, volume=11000)
    matches = detect_all(bars, code="600000", recent_days=1)
    assert matches
    assert all(m["days_ago"] <= 1 for m in matches)
    assert matches == sorted(matches, key=lambda m: (m["days_ago"], 0 if m["strength"] == "强" else 1))


def test_detect_kline_patterns_includes_bearish_ma_breakdown():
    bars = trend_prefix()
    last = bars[-1]["close"]
    bars.extend([
        bar("2026-04-01", last * 1.01, last * 1.015, high=last * 1.03, low=last * 1.00, volume=1800),
        bar("2026-04-02", last * 1.01, last * 0.965, high=last * 1.015, low=last * 0.955, volume=4200),
    ])

    got = {m["pattern"]: m for m in detect_kline_patterns(bars, code="600000", recent_days=3)}

    assert got["bear_ma_breakdown"]["direction"] == "bearish"
    assert got["bear_ma_breakdown"]["tone"] == "bear"
    assert got["bear_ma_breakdown"]["trigger_date"] == "2026-04-02"


def test_detect_kline_patterns_includes_long_upper_shadow():
    bars = trend_prefix()
    last = bars[-1]["close"]
    bars.append(bar(
        "2026-04-01",
        last * 1.01,
        last * 0.995,
        high=last * 1.09,
        low=last * 0.99,
        volume=4200,
    ))

    got = {m["pattern"]: m for m in detect_kline_patterns(bars, code="600000", recent_days=3)}

    assert got["bear_long_upper_shadow"]["direction"] == "bearish"
    assert got["bear_long_upper_shadow"]["trigger_date"] == "2026-04-01"


def test_detect_kline_patterns_keeps_bullish_detector_scope_separate():
    bars = trend_prefix()
    last = bars[-1]["close"]
    bars.append(bar("2026-04-01", last * 1.01, last * 0.95, high=last * 1.015, low=last * 0.94, volume=5000))

    assert all(not m["pattern"].startswith("bear_") for m in detect_all(bars, code="600000"))
    assert any(m["pattern"].startswith("bear_") for m in detect_kline_patterns(bars, code="600000"))


def test_backtest_pattern_on_history_forward_returns_and_sample_note():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    y_open = zt_close * 1.02
    bars.append(bar("2026-04-02", y_open, y_open * 0.95, high=y_open * 1.01, low=y_open * 0.94, volume=9000))
    bars.append(bar("2026-04-03", y_open * 0.96, y_open * 1.02, high=y_open * 1.03, low=y_open * 0.95, volume=7000))
    trigger_close = bars[-1]["close"]
    for i in range(4, 25):
        close = trigger_close * (1 + i * 0.01)
        bars.append(bar(f"2026-04-{i:02d}", close * 0.99, close, high=close * 1.01, low=close * 0.98, volume=3000))

    stats = backtest_pattern_on_history(bars, "zt_huge_yin_rewrap", code="600000", horizons=(5, 10, 20), min_gap_days=5)

    assert stats["name"] == "涨停巨量阴反包"
    assert stats["horizons"]["5"]["count"] == 1
    assert stats["horizons"]["5"]["win_rate"] == 100.0
    assert stats["horizons"]["5"]["avg_return"] > 0
    assert stats["sample_note"] == "样本少，仅供参考"


def test_backtest_all_returns_all_registered_patterns():
    stats = backtest_all(trend_prefix(), code="600000")
    assert len(stats) == 10
    assert "zt_pullback_double_volume" in stats
    assert set(stats["zt_pullback_double_volume"]["horizons"]) == {"5", "10", "20"}
