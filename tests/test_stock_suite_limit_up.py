import pandas as pd

from analysis.limit_up_patterns import bars_from_dataframe, detect_all
from analysis.stock_analysis_suite import StockAnalysisSuite


def _df_with_recent_limit_up_pattern():
    rows = []
    close = 10.0
    for i in range(80):
        close *= 1.002
        rows.append({
            "timestamps": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0 + i,
            "amount": close * (1000.0 + i),
        })
    prev = rows[-1]["close"]
    zt_close = prev * 1.10
    rows.append({
        "timestamps": pd.Timestamp("2026-04-01"),
        "open": prev * 1.02,
        "high": zt_close,
        "low": prev * 1.01,
        "close": zt_close,
        "volume": 6000.0,
        "amount": zt_close * 6000.0,
        "pct_chg": 10.0,
    })
    rows.append({
        "timestamps": pd.Timestamp("2026-04-02"),
        "open": zt_close * 0.99,
        "high": zt_close,
        "low": zt_close * 0.96,
        "close": zt_close * 0.98,
        "volume": 2500.0,
        "amount": zt_close * 2500.0,
    })
    rows.append({
        "timestamps": pd.Timestamp("2026-04-03"),
        "open": zt_close * 0.99,
        "high": zt_close * 1.02,
        "low": zt_close * 0.98,
        "close": zt_close * 1.01,
        "volume": 5200.0,
        "amount": zt_close * 5200.0,
    })
    return pd.DataFrame(rows)


def test_full_payload_has_real_limit_up_section_and_overview_summary():
    suite = StockAnalysisSuite(auto_fetch=False)
    df = _df_with_recent_limit_up_pattern()
    bars = bars_from_dataframe(df)
    fake_inputs = {"ohlcv": df, "lp_matches": detect_all(bars, code="600000", recent_days=10)}
    suite._collect_inputs = lambda code: fake_inputs  # type: ignore[method-assign]
    suite.compute_risk_control = lambda code: {"available": False, "reason": "stubbed"}  # type: ignore[method-assign]
    suite.collect_cached_reports = lambda code: {}  # type: ignore[method-assign]

    payload = suite._compute_full_payload("600000")

    assert "limit_up_screening" in payload
    assert "limit_up_screening" in payload["stub_tabs"]
    assert payload["limit_up_screening"]["data_status"] == "fresh"
    assert payload["limit_up_screening"]["matches"]
    assert payload["overview"]["strong_patterns"]["detected_count"] >= 1
    assert payload["overview"]["strong_patterns"]["items"][0]["name"]


def test_limit_up_section_degrades_when_ohlcv_missing():
    suite = StockAnalysisSuite(auto_fetch=False)
    section = suite._collect_limit_up_patterns("600000", {"ohlcv_error": "offline", "lp_matches": []})

    assert section["data_status"] == "unavailable"
    assert "offline" in section["reason"]
    assert section["matches"] == []
