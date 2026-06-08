# tests/test_dragon_tiger_list_provider.py
"""龙虎榜单回填编排:循环交易日 → fetcher → 归一化日期 → 落库 → sync_log。

用注入式 fetcher + 显式 dates,完全不触网、不依赖 tushare_client/交易日历。
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
    from data_store import connection, dragon_tiger_list_repo, sync_log_repo
    monkeypatch.setattr(connection, "get_conn", _getter)
    monkeypatch.setattr(dragon_tiger_list_repo, "get_conn", _getter)
    monkeypatch.setattr(sync_log_repo, "get_conn", _getter)
    yield c
    c.close()


def _toplist_df(trade_date_yyyymmdd, rows):
    """模拟 Tushare top_list 返回(trade_date 为 YYYYMMDD)。"""
    return pd.DataFrame([{"trade_date": trade_date_yyyymmdd, **r} for r in rows])


def test_backfill_loops_dates_and_persists(conn):
    from analysis.institutional import dragon_tiger_list_provider as prov
    from data_store import dragon_tiger_list_repo as repo

    calls = []

    def fake_fetcher(d):
        calls.append(d)
        return _toplist_df(d, [
            {"ts_code": "000001.SZ", "name": "甲", "net_amount": 3e7, "l_buy": 4e7, "reason": "r"},
        ])

    summary = prov.backfill_recent(dates=["20260603", "20260604"], fetcher=fake_fetcher)

    assert calls == ["20260603", "20260604"]      # 逐日调用
    assert repo.count() == 2                       # 两日各 1 行
    assert summary["rows"] == 2
    assert summary["ok_dates"] == 2


def test_backfill_normalizes_yyyymmdd_to_iso(conn):
    from analysis.institutional import dragon_tiger_list_provider as prov
    from data_store import dragon_tiger_list_repo as repo

    prov.backfill_recent(
        dates=["20260604"],
        fetcher=lambda d: _toplist_df(d, [
            {"ts_code": "000002.SZ", "name": "乙", "net_amount": 9e7, "reason": "r"},
        ]),
    )
    # 存的是 ISO 日期,可被 ISO 查询命中
    df = repo.get_top_n("2026-06-04", 10)
    assert len(df) == 1
    assert df.iloc[0]["ts_code"] == "000002.SZ"
    assert repo.latest_date() == "2026-06-04"


def test_backfill_skips_empty_and_none(conn):
    from analysis.institutional import dragon_tiger_list_provider as prov
    from data_store import dragon_tiger_list_repo as repo

    def fetcher(d):
        if d == "20260603":
            return None
        if d == "20260604":
            return pd.DataFrame()          # 空
        return _toplist_df(d, [{"ts_code": "000001.SZ", "net_amount": 1e7, "reason": "r"}])

    summary = prov.backfill_recent(dates=["20260603", "20260604", "20260605"], fetcher=fetcher)
    assert repo.count() == 1               # 仅 06-05 落库
    assert summary["rows"] == 1
    assert summary["ok_dates"] == 3        # 三日均成功调用(空也算成功,无错误)


def test_backfill_continues_on_fetch_error(conn):
    from analysis.institutional import dragon_tiger_list_provider as prov
    from data_store import dragon_tiger_list_repo as repo

    def fetcher(d):
        if d == "20260603":
            raise RuntimeError("429 too many requests")
        return _toplist_df(d, [{"ts_code": "000001.SZ", "net_amount": 1e7, "reason": "r"}])

    summary = prov.backfill_recent(dates=["20260603", "20260604"], fetcher=fetcher)
    assert repo.count() == 1               # 06-04 仍落库
    assert len(summary["errors"]) == 1
    assert "20260603" in summary["errors"][0][0]


def test_backfill_writes_sync_log(conn):
    from analysis.institutional import dragon_tiger_list_provider as prov

    prov.backfill_recent(
        dates=["20260604"],
        fetcher=lambda d: _toplist_df(d, [{"ts_code": "000001.SZ", "net_amount": 1e7, "reason": "r"}]),
    )
    row = conn.execute(
        "SELECT source, status, rows FROM sync_log WHERE source='dragon_tiger_list'"
    ).fetchone()
    assert row is not None
    assert row["status"] == "ok"


def test_backfill_idempotent(conn):
    from analysis.institutional import dragon_tiger_list_provider as prov
    from data_store import dragon_tiger_list_repo as repo

    f = lambda d: _toplist_df(d, [{"ts_code": "000001.SZ", "net_amount": 1e7, "reason": "r"}])  # noqa: E731
    prov.backfill_recent(dates=["20260604"], fetcher=f)
    prov.backfill_recent(dates=["20260604"], fetcher=f)
    assert repo.count() == 1               # 同主键覆盖,不重复


def test_backfill_skip_existing_avoids_refetch(conn):
    from analysis.institutional import dragon_tiger_list_provider as prov
    from data_store import dragon_tiger_list_repo as repo

    repo.upsert_df(_toplist_df("20260604", [
        {"ts_code": "000001.SZ", "net_amount": 1e7, "reason": "r"},
    ]))
    calls = []

    def fetcher(d):
        calls.append(d)
        return _toplist_df(d, [{"ts_code": "000002.SZ", "net_amount": 2e7, "reason": "r"}])

    summary = prov.backfill_recent(
        dates=["20260604", "20260605"],
        fetcher=fetcher,
        skip_existing=True,
    )
    assert calls == ["20260605"]
    assert summary["requested_dates"] == 2
    assert summary["skipped_dates"] == 1
    assert summary["rows"] == 1
