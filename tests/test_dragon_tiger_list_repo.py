# tests/test_dragon_tiger_list_repo.py
"""dragon_tiger_list_repo 的 upsert / 单日榜 / 多日聚合 / 上榜次数 行为。"""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)

    _getter = lambda: c  # noqa: E731
    from data_store import connection
    monkeypatch.setattr(connection, "get_conn", _getter)
    from data_store import dragon_tiger_list_repo
    monkeypatch.setattr(dragon_tiger_list_repo, "get_conn", _getter)
    yield c
    c.close()


def _df(rows):
    return pd.DataFrame(rows)


def test_upsert_df_and_get_top_n_orders_by_net(conn):
    from data_store import dragon_tiger_list_repo as repo

    n = repo.upsert_df(_df([
        {"trade_date": "2026-06-04", "ts_code": "000001.SZ", "name": "甲",
         "close": 10.0, "pct_change": 5.0, "net_amount": 3.0e7,
         "l_buy": 4e7, "l_sell": 1e7, "amount": 2e8, "reason": "日涨幅7%"},
        {"trade_date": "2026-06-04", "ts_code": "000002.SZ", "name": "乙",
         "close": 20.0, "pct_change": 9.9, "net_amount": 9.0e7,
         "l_buy": 1e8, "l_sell": 1e7, "amount": 3e8, "reason": "日涨幅7%"},
    ]))
    assert n == 2

    df = repo.get_top_n("2026-06-04", 10)
    assert list(df["ts_code"]) == ["000002.SZ", "000001.SZ"]  # 按净买入额降序
    assert df.iloc[0]["net_amount"] == pytest.approx(9.0e7)
    assert df.iloc[0]["name"] == "乙"


def test_get_top_n_limit(conn):
    from data_store import dragon_tiger_list_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-04", "ts_code": f"00000{i}.SZ", "name": f"S{i}",
         "net_amount": float(i) * 1e7, "reason": "x"}
        for i in range(1, 6)
    ]))
    df = repo.get_top_n("2026-06-04", 3)
    assert len(df) == 3
    assert list(df["ts_code"]) == ["000005.SZ", "000004.SZ", "000003.SZ"]


def test_get_top_n_merges_multiple_reasons_same_day(conn):
    """同股同日多条上榜原因 → 合并为一行,net_amount 求和(总净买入额含游资)。"""
    from data_store import dragon_tiger_list_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-04", "ts_code": "300750.SZ", "name": "丙",
         "close": 50.0, "net_amount": 2.0e7, "l_buy": 3e7, "amount": 5e8, "reason": "日涨幅偏离7%"},
        {"trade_date": "2026-06-04", "ts_code": "300750.SZ", "name": "丙",
         "close": 50.0, "net_amount": 5.0e7, "l_buy": 6e7, "amount": 5e8, "reason": "换手率达20%"},
    ]))
    df = repo.get_top_n("2026-06-04", 10)
    assert len(df) == 1                                  # 合并为一行
    assert df.iloc[0]["net_amount"] == pytest.approx(7.0e7)   # 2e7 + 5e7 求和
    assert df.iloc[0]["amount"] == pytest.approx(5e8)        # 日级字段不重复计(取 MAX)


def test_upsert_df_idempotent(conn):
    from data_store import dragon_tiger_list_repo as repo

    rows = _df([
        {"trade_date": "2026-06-04", "ts_code": "000001.SZ", "net_amount": 3e7, "reason": "r1"},
    ])
    repo.upsert_df(rows)
    repo.upsert_df(rows)
    assert repo.count() == 1


def test_upsert_df_updates_on_conflict(conn):
    from data_store import dragon_tiger_list_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-04", "ts_code": "000001.SZ", "net_amount": 3e7, "reason": "r1"},
    ]))
    repo.upsert_df(_df([
        {"trade_date": "2026-06-04", "ts_code": "000001.SZ", "net_amount": 8e7, "reason": "r1"},
    ]))
    assert repo.count() == 1
    df = repo.get_top_n("2026-06-04", 10)
    assert df.iloc[0]["net_amount"] == pytest.approx(8e7)   # 同主键被覆盖


def test_get_aggregated_sums_window_and_counts_appearances(conn):
    from data_store import dragon_tiger_list_repo as repo

    repo.upsert_df(_df([
        # day1 (应被 days=2 窗口排除)
        {"trade_date": "2026-06-02", "ts_code": "000001.SZ", "name": "甲", "net_amount": 5e7, "reason": "r"},
        # day2
        {"trade_date": "2026-06-03", "ts_code": "000001.SZ", "name": "甲", "net_amount": 2e7, "reason": "r"},
        {"trade_date": "2026-06-03", "ts_code": "000002.SZ", "name": "乙", "net_amount": 1e7, "reason": "r"},
        # day3
        {"trade_date": "2026-06-04", "ts_code": "000001.SZ", "name": "甲", "net_amount": 3e7, "reason": "r"},
    ]))
    df = repo.get_aggregated("2026-06-04", days=2, top_n=10)  # 仅 06-03 + 06-04

    g = {r["ts_code"]: r for _, r in df.iterrows()}
    assert g["000001.SZ"]["net_amount"] == pytest.approx(5e7)   # 2e7 + 3e7,不含 06-02 的 5e7
    assert g["000001.SZ"]["list_count"] == 2                    # 上榜 2 天
    assert g["000002.SZ"]["net_amount"] == pytest.approx(1e7)
    assert g["000002.SZ"]["list_count"] == 1
    assert list(df["ts_code"]) == ["000001.SZ", "000002.SZ"]    # 按累计净买入降序


def test_latest_date_and_count(conn):
    from data_store import dragon_tiger_list_repo as repo

    assert repo.latest_date() is None
    assert repo.count() == 0
    repo.upsert_df(_df([
        {"trade_date": "2026-06-02", "ts_code": "000001.SZ", "net_amount": 1e7, "reason": "r"},
        {"trade_date": "2026-06-04", "ts_code": "000002.SZ", "net_amount": 1e7, "reason": "r"},
    ]))
    assert repo.latest_date() == "2026-06-04"
    assert repo.count() == 2


def test_get_stock_aggregated_keeps_market_rank(conn):
    from data_store import dragon_tiger_list_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-03", "ts_code": "000001.SZ", "name": "甲",
         "l_buy": 2e7, "l_sell": 1e7, "net_amount": 1e7, "reason": "r1"},
        {"trade_date": "2026-06-04", "ts_code": "000001.SZ", "name": "甲",
         "l_buy": 2e7, "l_sell": 1e7, "net_amount": 1e7, "reason": "r2"},
        {"trade_date": "2026-06-04", "ts_code": "000002.SZ", "name": "乙",
         "l_buy": 8e7, "l_sell": 1e7, "net_amount": 7e7, "reason": "r"},
    ]))

    df = repo.get_stock_aggregated("000001", end_date="2026-06-04", days=2)
    assert len(df) == 1
    assert df.iloc[0]["l_buy"] == pytest.approx(4e7)
    assert df.iloc[0]["net_amount"] == pytest.approx(2e7)
    assert df.iloc[0]["market_rank"] == 2
    assert df.iloc[0]["list_count"] == 2


def test_get_stock_range_aggregated_merges_reasons_in_bounds(conn):
    from data_store import dragon_tiger_list_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-01", "ts_code": "000001.SZ", "name": "甲",
         "l_buy": 9e7, "net_amount": 9e7, "reason": "outside"},
        {"trade_date": "2026-06-02", "ts_code": "000001.SZ", "name": "甲",
         "l_buy": 2e7, "net_amount": 1e7, "reason": "r1"},
        {"trade_date": "2026-06-02", "ts_code": "000001.SZ", "name": "甲",
         "l_buy": 3e7, "net_amount": 2e7, "reason": "r2"},
    ]))

    df = repo.get_stock_range_aggregated("000001", "2026-06-02", "2026-06-03")
    assert len(df) == 1
    assert df.iloc[0]["l_buy"] == pytest.approx(5e7)
    assert df.iloc[0]["net_amount"] == pytest.approx(3e7)
    assert df.iloc[0]["reason_count"] == 2
    assert df.iloc[0]["first_date"] == "2026-06-02"
