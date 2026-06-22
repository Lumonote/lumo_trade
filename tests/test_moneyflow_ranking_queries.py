# tests/test_moneyflow_ranking_queries.py
"""moneyflow_repo 的资金榜查询:单日 get_ranking / 多日 get_aggregated。

哨兵 snapshot_top_n=0 = 资金榜全市场快照,须与 opportunity discovery 的正
top_n 快照互不干扰。
"""
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
    from data_store import connection, moneyflow_repo
    monkeypatch.setattr(connection, "get_conn", _getter)
    monkeypatch.setattr(moneyflow_repo, "get_conn", _getter)
    yield c
    c.close()


def _df(rows):
    return pd.DataFrame(rows)


def test_get_ranking_orders_by_net_and_limits(conn):
    from data_store import moneyflow_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-04", "ts_code": f"00000{i}.SZ", "name": f"S{i}",
         "net_amount": float(i) * 1e7, "pct_change": 1.0, "close": 10.0}
        for i in range(1, 6)
    ]), top_n=0)

    df = repo.get_ranking("2026-06-04", limit=3, snapshot_top_n=0)
    assert list(df["ts_code"]) == ["000005.SZ", "000004.SZ", "000003.SZ"]
    assert df.iloc[0]["net_amount"] == pytest.approx(5e7)


def test_get_ranking_isolates_sentinel_snapshot(conn):
    """同股同日在 top_n=0 与 top_n=100 各存一行,哨兵查询只取 top_n=0,不双计。"""
    from data_store import moneyflow_repo as repo

    repo.upsert_df(_df([{"trade_date": "2026-06-04", "ts_code": "000001.SZ",
                         "name": "甲", "net_amount": 5e7}]), top_n=0)
    repo.upsert_df(_df([{"trade_date": "2026-06-04", "ts_code": "000001.SZ",
                         "name": "甲", "net_amount": 9e7}]), top_n=100)

    df = repo.get_ranking("2026-06-04", limit=10, snapshot_top_n=0)
    assert len(df) == 1
    assert df.iloc[0]["net_amount"] == pytest.approx(5e7)   # 取哨兵快照值,非 top_n=100 的 9e7


def test_get_aggregated_sums_window_and_counts(conn):
    from data_store import moneyflow_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-02", "ts_code": "000001.SZ", "name": "甲", "net_amount": 5e7},  # 窗口外
        {"trade_date": "2026-06-03", "ts_code": "000001.SZ", "name": "甲", "net_amount": 2e7},
        {"trade_date": "2026-06-03", "ts_code": "000002.SZ", "name": "乙", "net_amount": 1e7},
        {"trade_date": "2026-06-04", "ts_code": "000001.SZ", "name": "甲", "net_amount": 3e7},
    ]), top_n=0)

    df = repo.get_aggregated("2026-06-04", days=2, limit=10, snapshot_top_n=0)
    g = {r["ts_code"]: r for _, r in df.iterrows()}
    assert g["000001.SZ"]["net_amount"] == pytest.approx(5e7)   # 2e7+3e7,排除 06-02
    assert g["000001.SZ"]["list_count"] == 2
    assert g["000002.SZ"]["net_amount"] == pytest.approx(1e7)
    assert g["000002.SZ"]["list_count"] == 1
    assert list(df["ts_code"]) == ["000001.SZ", "000002.SZ"]    # 按累计净流入降序


def test_get_range_aggregated_uses_explicit_date_bounds(conn):
    from data_store import moneyflow_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-01", "ts_code": "000001.SZ", "name": "甲", "net_amount": 9e7},
        {"trade_date": "2026-06-02", "ts_code": "000001.SZ", "name": "甲", "net_amount": 2e7},
        {"trade_date": "2026-06-03", "ts_code": "000002.SZ", "name": "乙", "net_amount": 4e7},
        {"trade_date": "2026-06-04", "ts_code": "000001.SZ", "name": "甲", "net_amount": 3e7},
    ]), top_n=0)

    df = repo.get_range_aggregated("2026-06-02", "2026-06-04", limit=10, snapshot_top_n=0)
    g = {r["ts_code"]: r for _, r in df.iterrows()}
    assert "000001.SZ" in g
    assert g["000001.SZ"]["net_amount"] == pytest.approx(5e7)   # 排除 06-01
    assert g["000001.SZ"]["list_count"] == 2
    assert list(df["ts_code"]) == ["000001.SZ", "000002.SZ"]


def test_get_aggregated_isolates_sentinel_snapshot(conn):
    from data_store import moneyflow_repo as repo

    repo.upsert_df(_df([{"trade_date": "2026-06-04", "ts_code": "000001.SZ",
                         "name": "甲", "net_amount": 5e7}]), top_n=0)
    repo.upsert_df(_df([{"trade_date": "2026-06-04", "ts_code": "000001.SZ",
                         "name": "甲", "net_amount": 9e7}]), top_n=50)

    df = repo.get_aggregated("2026-06-04", days=5, limit=10, snapshot_top_n=0)
    assert len(df) == 1
    assert df.iloc[0]["net_amount"] == pytest.approx(5e7)


def test_get_stock_aggregated_keeps_market_rank(conn):
    from data_store import moneyflow_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-03", "ts_code": "000001.SZ", "name": "甲",
         "net_amount": 1e7, "buy_elg_amount": 2e7, "buy_lg_amount": 2e7},
        {"trade_date": "2026-06-04", "ts_code": "000001.SZ", "name": "甲",
         "net_amount": 1e7, "buy_elg_amount": 2e7, "buy_lg_amount": 2e7},
        {"trade_date": "2026-06-04", "ts_code": "000002.SZ", "name": "乙",
         "net_amount": 9e7, "buy_elg_amount": 6e7, "buy_lg_amount": 6e7},
    ]), top_n=0)

    df = repo.get_stock_aggregated("000001", end_date="2026-06-04", days=2, snapshot_top_n=0)
    assert len(df) == 1
    assert df.iloc[0]["ts_code"] == "000001.SZ"
    assert df.iloc[0]["main_buy_amount"] == pytest.approx(8e7)
    assert df.iloc[0]["market_rank"] == 2
    assert df.iloc[0]["list_count"] == 2


def test_get_stock_range_aggregated_uses_explicit_bounds(conn):
    from data_store import moneyflow_repo as repo

    repo.upsert_df(_df([
        {"trade_date": "2026-06-01", "ts_code": "000001.SZ", "name": "甲",
         "net_amount": 5e7, "buy_elg_amount": 5e7},
        {"trade_date": "2026-06-02", "ts_code": "000001.SZ", "name": "甲",
         "net_amount": 2e7, "buy_elg_amount": 2e7},
        {"trade_date": "2026-06-03", "ts_code": "000001.SZ", "name": "甲",
         "net_amount": 3e7, "buy_lg_amount": 3e7},
    ]), top_n=0)

    df = repo.get_stock_range_aggregated(
        "000001",
        "2026-06-02",
        "2026-06-03",
        snapshot_top_n=0,
    )
    assert len(df) == 1
    assert df.iloc[0]["net_amount"] == pytest.approx(5e7)
    assert df.iloc[0]["first_date"] == "2026-06-02"
    assert df.iloc[0]["last_date"] == "2026-06-03"
