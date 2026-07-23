#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analysis/factor_history 单测 —— v25 因子取数(主力资金/期指多空)与回看对齐。

sim(enrich_frame)/live(live_extra_factors) 共用同一实现,重点覆盖:
周末报告回看最近交易日、3日滚动、staleness 守卫、缺数据 → None。
"""
import datetime as dt

import pandas as pd
import pytest

from data_store import connection as conn_mod, kv_repo, moneyflow_repo

from analysis import factor_history as fh


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_SQLITE_PATH", str(tmp_path / "k.sqlite"))
    conn_mod.reset_for_testing()
    fh._live_cache.update(ts=0.0, as_of=None, fut_3d=None, mf_date=None)
    yield
    conn_mod.reset_for_testing()


def _seed_moneyflow(rows):
    moneyflow_repo.upsert_df(pd.DataFrame(rows), top_n=0)


def _seed_futures(day: str, net_chg_per_variety: int, net: int = -20000):
    for variety in fh.FUT_VARIETIES:
        kv_repo.set_("futures_rank", f"{variety}:{day.replace('-', '')}", {
            "aggregate": {"summary": {"net": net, "net_chg": net_chg_per_variety}},
        })


def test_nearest_on_or_before_with_lookback_cap():
    days = ["2026-07-01", "2026-07-03"]
    assert fh.nearest_on_or_before("2026-07-03", days) == "2026-07-03"
    assert fh.nearest_on_or_before("2026-07-05", days) == "2026-07-03"  # 周末回看
    assert fh.nearest_on_or_before("2026-07-08", days) is None          # 超过3天不回看
    assert fh.nearest_on_or_before("2026-06-30", days) is None


def test_load_moneyflow_factors_in_days3(tmp_db):
    _seed_moneyflow([
        {"trade_date": "2026-07-01", "ts_code": "000001.SZ", "net_amount": 100.0, "net_amount_rate": 3.0},
        {"trade_date": "2026-07-02", "ts_code": "000001.SZ", "net_amount": -50.0, "net_amount_rate": -6.0},
        {"trade_date": "2026-07-03", "ts_code": "000001.SZ", "net_amount": 80.0, "net_amount_rate": 2.5},
    ])
    out = fh.load_moneyflow_factors("2026-07-01", "2026-07-03", codes=["000001"])
    assert out[("2026-07-03", "000001")]["main_net_rate"] == 2.5
    assert out[("2026-07-03", "000001")]["main_in_days3"] == 2  # 3天中2天净流入为正
    assert out[("2026-07-01", "000001")]["main_in_days3"] == 1  # 不足3天按已有天数


def test_load_futures_regime_rolls_and_falls_back(tmp_db):
    _seed_futures("2026-07-01", -1000)
    _seed_futures("2026-07-02", -2000)
    _seed_futures("2026-07-03", -3000)  # 周五
    out = fh.load_futures_regime(["2026-07-03", "2026-07-05"])  # 07-05 周日
    assert out["2026-07-03"]["fut_net_chg"] == -3000 * 4
    assert out["2026-07-03"]["fut_net_chg_3d"] == (-1000 - 2000 - 3000) * 4
    assert out["2026-07-05"] == out["2026-07-03"]  # 周日报告回看周五


def test_enrich_frame_joins_both_factors(tmp_db):
    _seed_moneyflow([
        {"trade_date": "2026-07-03", "ts_code": "000001.SZ", "net_amount": -900.0, "net_amount_rate": -7.2},
    ])
    _seed_futures("2026-07-03", -2500)
    df = pd.DataFrame([
        {"report_date": "2026-07-05", "code6": "000001"},   # 周日 → 回看周五
        {"report_date": "2026-07-05", "code6": "999999"},   # 无资金数据
    ])
    out = fh.enrich_frame(df)
    assert out.iloc[0]["main_net_rate"] == -7.2
    assert out.iloc[0]["fut_net_chg_3d"] == -2500 * 4
    assert pd.isna(out.iloc[1]["main_net_rate"])  # 缺数据 → NaN, 规则侧 _num() 视为缺失
    assert out.iloc[1]["fut_net_chg_3d"] == -2500 * 4  # 市场因子全场同值


def test_live_extra_factors_fresh_data(tmp_db):
    today = dt.date.today().isoformat()
    prev = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    _seed_moneyflow([
        {"trade_date": today, "ts_code": "000001.SZ", "net_amount": 500.0, "net_amount_rate": 3.3},
    ])
    _seed_futures(prev, -1500)
    _seed_futures(today, -2000)
    out = fh.live_extra_factors("000001")
    assert out["main_net_rate"] == 3.3
    assert out["fut_net_chg_3d"] == (-1500 - 2000) * 4
    # 无该股资金行 → None, 市场因子仍在
    out2 = fh.live_extra_factors("999999")
    assert out2["main_net_rate"] is None
    assert out2["fut_net_chg_3d"] == (-1500 - 2000) * 4


def test_live_extra_factors_stale_or_sparse_guard(tmp_db):
    stale_day = (dt.date.today() - dt.timedelta(days=9)).isoformat()
    _seed_moneyflow([
        {"trade_date": stale_day, "ts_code": "000001.SZ", "net_amount": 500.0, "net_amount_rate": 3.3},
    ])
    _seed_futures(dt.date.today().isoformat(), -9000)  # 仅1个已发布日(<2)
    out = fh.live_extra_factors("000001")
    assert out["main_net_rate"] is None      # 快照过期
    assert out["fut_net_chg_3d"] is None     # 单日样本不足
