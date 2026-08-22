"""验证 migration 21:板块日序列 + 拐点信号两张新表。

板块序列预聚合落表,避免每次请求扫 moneyflow_dc 115 万行(见 spec §4.3)。
"""
import sqlite3

import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    yield c
    c.close()


def test_migrate_creates_sector_tables(conn):
    assert migrate(conn) == 21
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "sector_daily_metrics" in names
    assert "sector_turning_signal" in names


def test_sector_daily_metrics_columns(conn):
    migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sector_daily_metrics)")}
    assert cols == {
        "trade_date", "sector", "sector_type", "member_count", "net_amount",
        "net_rate_median", "pct_chg_mean", "breadth", "amount_median",
        "excess_vs_market", "seat_count", "provisional",
    }


def test_sector_daily_metrics_primary_key_is_date_sector_type(conn):
    migrate(conn)
    conn.execute(
        "INSERT INTO sector_daily_metrics(trade_date, sector, sector_type, member_count) "
        "VALUES('2026-08-20','半导体','行业',10)")
    # 同名板块不同类型可共存(行业「半导体」与概念「半导体」是两条线)
    conn.execute(
        "INSERT INTO sector_daily_metrics(trade_date, sector, sector_type, member_count) "
        "VALUES('2026-08-20','半导体','概念',12)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sector_daily_metrics(trade_date, sector, sector_type, member_count) "
            "VALUES('2026-08-20','半导体','行业',99)")
    assert conn.execute("SELECT COUNT(*) FROM sector_daily_metrics").fetchone()[0] == 2


def test_sector_turning_signal_roundtrip(conn):
    migrate(conn)
    conn.execute(
        "INSERT INTO sector_turning_signal"
        "(trade_date, sector, sector_type, rule, state, score, evidence_json, provisional) "
        "VALUES('2026-08-20','半导体','行业','T1','fired',72.5,'{\"cum20\":123}',1)")
    row = conn.execute("SELECT * FROM sector_turning_signal").fetchone()
    assert row["rule"] == "T1"
    assert row["state"] == "fired"
    assert row["provisional"] == 1


def test_migrate_is_idempotent(conn):
    assert migrate(conn) == 21
    assert migrate(conn) == 21
