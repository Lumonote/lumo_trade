"""全市场日线补齐(data_store.market_daily_fetch)的取数编排。

「入选后涨幅」的价格面靠这里补:每个交易日一次 Tushare ``daily(trade_date=...)``
(约 5500 行),而不是按股票逐只抓(3600 次请求)。这里锁住:已补齐的日期不重复
抓、抓取有预算上限、Tushare 不可用时安全降级、交易日历本地缓存。
"""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)

    _getter = lambda: c  # noqa: E731
    from data_store import calendar_repo, connection, market_daily_fetch, market_snapshot_repo
    monkeypatch.setattr(connection, "get_conn", _getter)
    monkeypatch.setattr(calendar_repo, "get_conn", _getter)
    monkeypatch.setattr(market_snapshot_repo, "get_conn", _getter)
    monkeypatch.setattr(market_daily_fetch, "get_conn", _getter)
    yield c
    c.close()


class _FakePro:
    """只实现 daily / trade_cal 的假 Tushare 客户端,记录调用参数。"""

    def __init__(self, rows: int = 1500, cal_days=()):
        self.rows = rows
        self.cal_days = list(cal_days)
        self.daily_calls: list[str] = []
        self.cal_calls: list[tuple] = []

    def daily(self, trade_date: str):
        self.daily_calls.append(trade_date)
        if self.rows <= 0:
            return pd.DataFrame()
        return pd.DataFrame({
            "ts_code": [f"{600000 + i:06d}.SH" for i in range(self.rows)],
            "trade_date": [trade_date] * self.rows,
            "open": [10.0] * self.rows,
            "high": [11.0] * self.rows,
            "low": [9.0] * self.rows,
            "close": [10.5] * self.rows,
        })

    def trade_cal(self, exchange, start_date, end_date, is_open):
        self.cal_calls.append((start_date, end_date))
        return pd.DataFrame({"cal_date": self.cal_days})


def _use_pro(monkeypatch, pro):
    from data_store import market_daily_fetch, tushare_client
    monkeypatch.setattr(market_daily_fetch.tushare_client, "get_pro", lambda: pro)
    monkeypatch.setattr(tushare_client, "get_pro", lambda: pro)


def test_ensure_dates_fetches_missing_and_skips_filled(conn, monkeypatch):
    from data_store import market_daily_fetch as mdf

    pro = _FakePro()
    _use_pro(monkeypatch, pro)

    first = mdf.ensure_dates(["20260810", "20260811"])
    assert first == {"requested": 2, "filled": 0, "fetched": 2, "remaining": 0}
    assert sorted(pro.daily_calls) == ["20260810", "20260811"]

    again = mdf.ensure_dates(["20260810", "20260811"])
    assert again["fetched"] == 0 and again["filled"] == 2
    assert len(pro.daily_calls) == 2  # 没有重复请求


def test_ensure_dates_respects_budget_newest_first(conn, monkeypatch):
    from data_store import market_daily_fetch as mdf

    pro = _FakePro()
    _use_pro(monkeypatch, pro)

    stats = mdf.ensure_dates(["20260810", "20260811", "20260812"], max_fetch=1)
    assert stats["fetched"] == 1 and stats["remaining"] == 2
    assert pro.daily_calls == ["20260812"]  # 最近的交易日(现价)优先


def test_sparse_day_is_not_treated_as_filled(conn, monkeypatch):
    """只有零星行(如 market_regime 写的 4 条指数)不能算这天有全市场行情。"""
    from data_store import market_daily_fetch as mdf

    conn.execute(
        "INSERT INTO market_daily(ts_code, trade_date, open, close) VALUES('000001.SH','20260810',3000,3010)"
    )
    assert mdf.filled_dates(["20260810"]) == set()

    pro = _FakePro()
    _use_pro(monkeypatch, pro)
    assert mdf.ensure_dates(["20260810"])["fetched"] == 1
    assert mdf.latest_filled_date() == "2026-08-10"


def test_ensure_dates_degrades_without_tushare(conn, monkeypatch):
    from data_store import market_daily_fetch as mdf

    _use_pro(monkeypatch, None)
    stats = mdf.ensure_dates(["20260810"])
    assert stats == {"requested": 1, "filled": 0, "fetched": 0, "remaining": 1}
    assert mdf.latest_filled_date() == ""


def test_open_days_caches_calendar_locally(conn, monkeypatch):
    from data_store import calendar_repo, market_daily_fetch as mdf

    pro = _FakePro(cal_days=["20260810", "20260811", "20260812", "20261231"])
    _use_pro(monkeypatch, pro)

    days = mdf.open_days("2026-08-10", "2026-08-11")
    assert days == ["20260810", "20260811"]      # 只返回区间内
    assert calendar_repo.count() == 4            # 但多存到年底,后续不再请求
    assert pro.cal_calls == [("20260810", "20261231")]

    assert mdf.open_days("2026-08-10", "2026-08-12") == ["20260810", "20260811", "20260812"]
    assert len(pro.cal_calls) == 1               # 命中本地缓存


def test_next_open_days_maps_selection_day_to_buy_day(conn):
    from data_store import market_daily_fetch as mdf

    cal = ["20260810", "20260811", "20260812", "20260813"]
    # 入选日 08-10 → 次日 08-11;周末/休市造成的空档自动跳到下一个交易日
    assert mdf.next_open_days(["2026-08-10", "20260811"], cal) == ["20260811", "20260812"]
    assert mdf.next_open_days(["20260813"], cal) == []  # 之后还没有交易日
