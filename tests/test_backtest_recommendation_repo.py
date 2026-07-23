"""backtest_recommendation 表仓库测试 —— 回测推荐记录全量走 SQLite。

recommendations.csv 自 2026-07-09 起不再作为持久层；CSV 仅在表空时作为
一次性种子来源(传输格式)。
"""
from datetime import datetime

import pandas as pd
import pytest

from data_store import backtest_recommendation_repo as btr
from data_store import connection as conn_mod


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_SQLITE_PATH", str(tmp_path / "k.sqlite"))
    conn_mod.reset_for_testing()
    yield tmp_path
    conn_mod.reset_for_testing()


def _rec(**kw):
    base = {
        'report_date': '2026-07-01', 'rank': 1, 'code': '000001', 'name': 'X',
        'score': 80.0, 'chase_risk': 30, 'buy_signals': 5, 'sell_signals': 0,
        'rsi': 45.0, 'day_change': 1.0, 'change_3d': 2.0, 'change_5d': 3.0,
        'sector_score': 60, 'quant_score': 55, 'tech_score': 65,
        'momentum_pattern': '[]', 'buy_price': 0,
        'return_1d': None, 'return_3d': None, 'return_5d': None, 'return_10d': None,
    }
    base.update(kw)
    return base


def test_replace_day_roundtrip_and_dedup(tmp_db):
    btr.replace_day('2026-07-01', [_rec(rank=1, code='000001'),
                                   _rec(rank=2, code='600519', score=75)])
    # 同日重写 = 整日替换(与旧 save_recommendations 去同日重复语义一致)
    btr.replace_day('2026-07-01', [_rec(rank=1, code='300750', score=88)])
    df = btr.load_df()
    assert len(df) == 1
    assert df.loc[0, 'code'] == '300750'
    assert df.loc[0, 'rank'] == 1          # DataFrame 侧仍叫 rank
    assert abs(df.loc[0, 'score'] - 88) < 1e-9
    assert pd.isna(df.loc[0, 'return_5d'])


def test_load_df_normalizes_and_sorts(tmp_db):
    btr.replace_day('2026-07-02', [_rec(report_date='2026-07-02', code='1.SZ', rank=1)])
    btr.replace_day('2026-07-01', [_rec(report_date='2026-07-01T20:00:00', code='600519', rank=1)])
    df = btr.load_df()
    assert list(df['report_date']) == ['2026-07-01', '2026-07-02']  # 日期归一 + 升序
    assert list(df['code']) == ['600519', '000001']                 # code 零填充6位
    assert list(df.columns) == list(btr.DF_COLUMNS)


def test_upsert_update_vs_ignore(tmp_db):
    btr.replace_day('2026-07-01', [_rec()])
    # update: 回填收益
    btr.upsert_rows([_rec(buy_price=11.0, return_5d=4.5)])
    df = btr.load_df()
    assert abs(df.loc[0, 'return_5d'] - 4.5) < 1e-9
    # ignore: 已存在 (date,code) 原样保留(回填脚本语义)
    btr.upsert_rows([_rec(score=1.0, return_5d=-9.9)], on_conflict='ignore')
    df = btr.load_df()
    assert abs(df.loc[0, 'return_5d'] - 4.5) < 1e-9
    assert abs(df.loc[0, 'score'] - 80.0) < 1e-9


def test_save_df_writes_back_returns(tmp_db):
    btr.replace_day('2026-07-01', [_rec(code='000001'), _rec(rank=2, code='600519')])
    df = btr.load_df()
    df.loc[df['code'] == '000001', 'return_1d'] = 1.23
    btr.save_df(df)
    out = btr.load_df()
    row = out[out['code'] == '000001'].iloc[0]
    assert abs(row['return_1d'] - 1.23) < 1e-9
    assert pd.isna(out[out['code'] == '600519'].iloc[0]['return_1d'])


def test_seed_from_legacy_csv_if_empty(tmp_db):
    csv_path = tmp_db / "recommendations.csv"
    pd.DataFrame([_rec(code='000001', return_5d=2.0),
                  _rec(rank=2, code='600519')]).to_csv(
        csv_path, index=False, encoding='utf-8-sig')  # 带 BOM,模拟存量文件
    n = btr.seed_from_legacy_csv_if_empty(csv_path=str(csv_path))
    assert n == 2
    # 幂等:表非空 → 不再导入
    assert btr.seed_from_legacy_csv_if_empty(csv_path=str(csv_path)) == 0
    df = btr.load_df()
    assert len(df) == 2
    assert abs(df[df['code'] == '000001'].iloc[0]['return_5d'] - 2.0) < 1e-9


def test_delete_by_name(tmp_db):
    btr.replace_day('2026-07-01', [_rec(code='000001', name='冒烟测试'),
                                   _rec(rank=2, code='600519', name='真票')])
    assert btr.delete_by_name('冒烟测试') == 1
    df = btr.load_df()
    assert list(df['name']) == ['真票']


def test_load_df_empty_has_columns(tmp_db):
    df = btr.load_df()
    assert df.empty
    assert list(df.columns) == list(btr.DF_COLUMNS)


def test_prepare_backtest_history_reads_sqlite(tmp_db):
    """报告生成器的历史回测统计必须从 SQLite 读,不再依赖 results/ CSV。"""
    rows = [_rec(report_date=f'2026-06-{d:02d}', rank=i + 1, code=f'{600000 + i:06d}',
                 score=85 + (i % 5), return_5d=1.0 + i % 3, return_10d=2.0)
            for d in range(1, 11) for i in range(3)]
    by_day = {}
    for r in rows:
        by_day.setdefault(r['report_date'], []).append(r)
    for day, recs in by_day.items():
        btr.replace_day(day, recs)

    from scripts.opportunity_report_generator import OpportunityReportGenerator
    gen = OpportunityReportGenerator.__new__(OpportunityReportGenerator)
    bt, score_col, cutoff, wstart = gen._prepare_backtest_history(datetime(2026, 6, 25))
    assert bt is not None and len(bt) > 0
    assert bt[score_col].notna().all()
    assert bt['report_date'].min() >= '2026-06-01'
