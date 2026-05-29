"""Unit tests for the forward-return calculator in scripts/auto_backtest.py.

Covers the next-open-buy / N-th-day-close-sell methodology and robustness
against intraday-polluted '1d' rows. Pure logic — no network, no sqlite.
"""
import pandas as pd

from scripts.auto_backtest import compute_forward_returns, _collapse_to_daily


def _series(rows):
    """rows: list of (date, open, high, low, close) -> canonical OHLCV df."""
    return pd.DataFrame(
        [{'timestamps': f'{d} 00:00:00', 'open': o, 'high': h, 'low': l, 'close': c}
         for d, o, h, l, c in rows]
    )


def test_next_open_buy_and_horizon_closes():
    df = _series([
        ('2026-03-02', 10, 10, 10, 10),   # report day — must NOT be the buy bar
        ('2026-03-03', 11, 12, 10, 12),   # D1: buy at OPEN=11
        ('2026-03-04', 12, 13, 11, 13),   # D2
        ('2026-03-05', 13, 14, 12, 14),   # D3: close 14
        ('2026-03-06', 14, 15, 13, 15),   # D4
        ('2026-03-09', 15, 16, 14, 16),   # D5: close 16
    ])
    res = compute_forward_returns(df, '2026-03-02')
    assert res['buy_price'] == 11
    assert round(res['return_1d'], 6) == round((12 / 11 - 1) * 100, 6)
    assert round(res['return_3d'], 6) == round((14 / 11 - 1) * 100, 6)
    assert round(res['return_5d'], 6) == round((16 / 11 - 1) * 100, 6)
    assert 'return_10d' not in res  # only 5 forward bars available


def test_no_forward_bar_returns_empty():
    df = _series([('2026-03-02', 10, 10, 10, 10)])
    assert compute_forward_returns(df, '2026-03-02') == {}


def test_report_date_on_non_trading_day_buys_next_bar():
    df = _series([('2026-03-02', 10, 10, 10, 10), ('2026-03-05', 20, 21, 19, 21)])
    res = compute_forward_returns(df, '2026-03-03')  # holiday gap; next bar = 03-05
    assert res['buy_price'] == 20
    assert round(res['return_1d'], 6) == round((21 / 20 - 1) * 100, 6)


def test_collapse_intraday_pollution():
    # D1 has two intraday bars; should fold into open=first, close=last.
    df = pd.DataFrame([
        {'timestamps': '2026-03-02 00:00:00', 'open': 10, 'high': 10, 'low': 10, 'close': 10},
        {'timestamps': '2026-03-03 09:35:00', 'open': 11.0, 'high': 12, 'low': 10, 'close': 11.5},
        {'timestamps': '2026-03-03 15:00:00', 'open': 11.6, 'high': 13, 'low': 11, 'close': 12.0},
    ])
    collapsed = _collapse_to_daily(df)
    assert len(collapsed) == 2  # two distinct calendar days
    res = compute_forward_returns(df, '2026-03-02')
    assert res['buy_price'] == 11.0                       # first intraday open of D1
    assert round(res['return_1d'], 6) == round((12.0 / 11.0 - 1) * 100, 6)  # last intraday close


def test_empty_input_safe():
    assert compute_forward_returns(pd.DataFrame(), '2026-03-02') == {}
    assert _collapse_to_daily(None).empty
