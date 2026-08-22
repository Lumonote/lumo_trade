"""盘中增量重算 + 收盘定稿(spec §5 第 2、3 层)。

两个函数都可注入 now,不依赖真实时钟。
"""
import sqlite3
from datetime import datetime

import pytest

from analysis import sector_series
from data_store.schema import migrate


@pytest.fixture
def db(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    monkeypatch.setattr(sector_series, "get_conn", lambda: conn)
    monkeypatch.setattr(sector_series, "_finalize_mapping",
                        lambda date: {"000001": [("银行", "行业")]})
    yield conn
    conn.close()


def _seed_flow(conn, date="2026-08-21"):
    conn.execute(
        "INSERT INTO moneyflow_dc(trade_date, ts_code, top_n, pct_change, "
        "net_amount, net_amount_rate, amount_unit) VALUES(?,?,0,?,?,?,'万元')",
        (date, "000001.SZ", 2.0, 100.0, 5.0))


def _seed_provisional_row(conn, date="2026-08-21"):
    conn.execute(
        "INSERT INTO sector_daily_metrics(trade_date, sector, sector_type, "
        "member_count, pct_chg_mean, provisional) VALUES(?,?,?,?,?,1)",
        (date, "银行", "行业", 20, 1.0))


# ---------------------------------------------------------------- 盘中
def test_intraday_writes_provisional_rows(db):
    _seed_flow(db)
    out = sector_series.refresh_intraday(now=datetime(2026, 8, 21, 10, 30))
    assert out["ran"] is True and out["written"] >= 1
    row = db.execute("SELECT provisional, pct_chg_mean FROM sector_daily_metrics "
                     "WHERE trade_date='2026-08-21'").fetchone()
    assert row["provisional"] == 1
    assert row["pct_chg_mean"] == pytest.approx(2.0)


def test_intraday_noop_without_todays_flow(db):
    out = sector_series.refresh_intraday(now=datetime(2026, 8, 21, 10, 30))
    assert out["ran"] is False


def test_intraday_does_not_overwrite_finalized_day(db):
    """已定稿的当日数据不该被盘中重算改回 provisional。"""
    _seed_flow(db)
    _seed_provisional_row(db)
    db.execute("UPDATE sector_daily_metrics SET provisional=0")
    out = sector_series.refresh_intraday(now=datetime(2026, 8, 21, 10, 30))
    assert out["ran"] is False
    assert db.execute("SELECT provisional FROM sector_daily_metrics").fetchone()[0] == 0


# ---------------------------------------------------------------- 收盘
def test_finalize_skips_before_cutoff(db):
    _seed_flow(db)
    _seed_provisional_row(db)
    out = sector_series.finalize_once(now=datetime(2026, 8, 21, 14, 0))
    assert out["ran"] is False
    assert "收盘" in out["reason"]


def test_finalize_runs_after_cutoff(db):
    _seed_flow(db)
    _seed_provisional_row(db)
    out = sector_series.finalize_once(now=datetime(2026, 8, 21, 18, 0))
    assert out["ran"] is True
    assert out["date"] == "2026-08-21"
    row = db.execute("SELECT provisional FROM sector_daily_metrics "
                     "WHERE trade_date='2026-08-21'").fetchone()
    assert row["provisional"] == 0


def test_finalize_noop_when_already_final(db):
    _seed_flow(db)
    _seed_provisional_row(db)
    db.execute("UPDATE sector_daily_metrics SET provisional=0")
    out = sector_series.finalize_once(now=datetime(2026, 8, 21, 18, 0))
    assert out["ran"] is False
    assert "已定稿" in out["reason"]


def test_finalize_noop_without_moneyflow_for_today(db):
    out = sector_series.finalize_once(now=datetime(2026, 8, 21, 18, 0))
    assert out["ran"] is False


def test_finalize_force_ignores_cutoff(db):
    _seed_flow(db)
    _seed_provisional_row(db)
    out = sector_series.finalize_once(now=datetime(2026, 8, 21, 10, 0), force=True)
    assert out["ran"] is True


def test_daemon_disabled_by_env(db, monkeypatch):
    monkeypatch.setenv("KRONOS_DISABLE_SECTOR_FINALIZE", "1")
    assert sector_series.start_finalize_daemon() is None
