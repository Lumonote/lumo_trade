"""Integration tests for auto_backtest's sqlite-native update_returns and the
strengthened optimizer guard. No network: the fetcher is monkeypatched.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

import scripts.auto_backtest as ab
from data_store import ohlcv_fetch


_REC_COLUMNS = [
    'report_date', 'rank', 'code', 'name', 'score', 'chase_risk', 'buy_signals',
    'sell_signals', 'rsi', 'day_change', 'change_3d', 'change_5d', 'sector_score',
    'quant_score', 'tech_score', 'momentum_pattern', 'buy_price',
    'return_1d', 'return_3d', 'return_5d', 'return_10d',
]


def _row(**kw):
    base = {c: (None if c.startswith('return_') else 0) for c in _REC_COLUMNS}
    base.update(name='X', momentum_pattern='[]')
    base.update(kw)
    return base


def test_update_returns_recompute_all_next_open(tmp_path, monkeypatch):
    rec = tmp_path / "recommendations.csv"
    pd.DataFrame([_row(report_date='2026-03-02', rank=1, code='000001', score=80,
                       quant_score=70)], columns=_REC_COLUMNS).to_csv(
        rec, index=False, encoding='utf-8-sig')
    monkeypatch.setattr(ab, 'RECOMMENDATIONS_FILE', str(rec))

    def fake_ensure(code, beg, end, throttle=0.0):
        return pd.DataFrame([
            {'timestamps': '2026-03-02 00:00:00', 'open': 10, 'high': 10, 'low': 10, 'close': 10},
            {'timestamps': '2026-03-03 00:00:00', 'open': 11, 'high': 12, 'low': 10, 'close': 12},  # D1 buy=11
            {'timestamps': '2026-03-04 00:00:00', 'open': 12, 'high': 13, 'low': 11, 'close': 13},
            {'timestamps': '2026-03-05 00:00:00', 'open': 13, 'high': 14, 'low': 12, 'close': 14},  # D3
            {'timestamps': '2026-03-06 00:00:00', 'open': 14, 'high': 15, 'low': 13, 'close': 15},
            {'timestamps': '2026-03-09 00:00:00', 'open': 15, 'high': 16, 'low': 14, 'close': 16},  # D5
        ])
    monkeypatch.setattr(ohlcv_fetch, 'ensure_daily', fake_ensure)

    res = ab.update_returns(recompute_all=True, throttle=0)
    assert res['updated'] == 1
    out = pd.read_csv(rec)
    assert abs(out.loc[0, 'buy_price'] - 11) < 1e-6
    assert abs(out.loc[0, 'return_1d'] - (12 / 11 - 1) * 100) < 1e-3
    assert abs(out.loc[0, 'return_5d'] - (16 / 11 - 1) * 100) < 1e-3
    # destructive recompute must leave a backup
    assert list(tmp_path.glob("recommendations.backup_*.csv"))


def test_update_returns_partial_fill_when_window_incomplete(tmp_path, monkeypatch):
    """A recent rec with only 3 forward bars fills 1d/3d but leaves 5d/10d empty."""
    rec = tmp_path / "recommendations.csv"
    pd.DataFrame([_row(report_date='2026-03-02', rank=1, code='600197', score=75)],
                 columns=_REC_COLUMNS).to_csv(rec, index=False, encoding='utf-8-sig')
    monkeypatch.setattr(ab, 'RECOMMENDATIONS_FILE', str(rec))

    def fake_ensure(code, beg, end, throttle=0.0):
        return pd.DataFrame([
            {'timestamps': '2026-03-03 00:00:00', 'open': 11, 'high': 12, 'low': 10, 'close': 12},
            {'timestamps': '2026-03-04 00:00:00', 'open': 12, 'high': 13, 'low': 11, 'close': 13},
            {'timestamps': '2026-03-05 00:00:00', 'open': 13, 'high': 14, 'low': 12, 'close': 14},
        ])
    monkeypatch.setattr(ohlcv_fetch, 'ensure_daily', fake_ensure)

    ab.update_returns(recompute_all=True, throttle=0)
    out = pd.read_csv(rec)
    assert pd.notna(out.loc[0, 'return_1d']) and pd.notna(out.loc[0, 'return_3d'])
    assert pd.isna(out.loc[0, 'return_5d']) and pd.isna(out.loc[0, 'return_10d'])


def test_optimizer_refuses_on_stale_data(tmp_path, monkeypatch):
    """Enough total samples, but all old → must refuse instead of mis-tuning."""
    rec = tmp_path / "recommendations.csv"
    old = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    rows = [_row(report_date=old, rank=i, code=f'{i:06d}', score=80 + i % 10,
                 quant_score=90, chase_risk=30, rsi=50, return_5d=1.0 + i % 3)
            for i in range(40)]
    pd.DataFrame(rows, columns=_REC_COLUMNS).to_csv(rec, index=False, encoding='utf-8-sig')
    monkeypatch.setattr(ab, 'RECOMMENDATIONS_FILE', str(rec))
    monkeypatch.setattr(ab, 'SCORING_RUNTIME_CONFIG', str(tmp_path / "cfg.json"))

    res = ab.optimize_scoring_config(days_back=120, min_samples=30,
                                     recent_days=45, min_recent=12)
    assert res['applied'] is False
    assert res['reason'].startswith('stale_or_insufficient_recent_returns')


def test_update_returns_incremental_fills_missing_10d(tmp_path, monkeypatch):
    """Incremental (non-recompute) must re-touch a row missing only return_10d —
    the case the old `return_5d.isna()` gate skipped."""
    rec = tmp_path / "recommendations.csv"
    pd.DataFrame([_row(report_date='2026-03-02', rank=1, code='000001', score=80,
                       return_1d=1.0, return_3d=2.0, return_5d=3.0, return_10d=None)],
                 columns=_REC_COLUMNS).to_csv(rec, index=False, encoding='utf-8-sig')
    monkeypatch.setattr(ab, 'RECOMMENDATIONS_FILE', str(rec))

    def fake_ensure(code, beg, end, throttle=0.0):
        days = [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 16, 17]  # 12 trading days, enough for 10d
        return pd.DataFrame([
            {'timestamps': f'2026-03-{d:02d} 00:00:00', 'open': 10 + i, 'high': 10 + i,
             'low': 10 + i, 'close': 10 + i}
            for i, d in enumerate(days)
        ])
    monkeypatch.setattr(ohlcv_fetch, 'ensure_daily', fake_ensure)

    ab.update_returns(days_back=120, recompute_all=False, throttle=0)
    out = pd.read_csv(rec)
    assert pd.notna(out.loc[0, 'return_10d'])  # previously-missing horizon now filled


def test_optimizer_runs_and_deweights_inverted_quant(tmp_path, monkeypatch):
    """Fresh data where higher quant_score → lower return: quant weight must drop."""
    rec = tmp_path / "recommendations.csv"
    rows = []
    for i in range(40):
        d = (datetime.now() - timedelta(days=(i % 30))).strftime('%Y-%m-%d')  # all recent
        q = 50 + (i % 11) * 5           # 50..100
        ret = 8.0 - 0.12 * q + (i % 3)  # strong negative quant↔return relationship
        rows.append(_row(report_date=d, rank=i, code=f'{i:06d}', score=70 + i % 20,
                         quant_score=q, chase_risk=40, rsi=55, return_5d=ret))
    pd.DataFrame(rows, columns=_REC_COLUMNS).to_csv(rec, index=False, encoding='utf-8-sig')
    monkeypatch.setattr(ab, 'RECOMMENDATIONS_FILE', str(rec))
    cfg = tmp_path / "cfg.json"
    monkeypatch.setattr(ab, 'SCORING_RUNTIME_CONFIG', str(cfg))

    res = ab.optimize_scoring_config(days_back=120, min_samples=30,
                                     recent_days=45, min_recent=12)
    assert res['applied'] is True
    assert any('quant' in s for s in res['signals'])
    import json
    written = json.loads(cfg.read_text(encoding='utf-8'))
    assert written['dimension_weights']['quantitative'] < 0.30  # below class default
    assert 'factor_corr_5d' in written and 'newest_return_age_days' in written
