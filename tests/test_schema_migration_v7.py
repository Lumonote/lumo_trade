# tests/test_schema_migration_v7.py
"""验证资金榜 / 模拟盘相关迁移建表并推进到当前 schema 版本。"""
from __future__ import annotations

import sqlite3
import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    c.execute("PRAGMA foreign_keys=ON")
    yield c
    c.close()


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _cols(conn, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_migrate_reaches_latest_version(conn):
    assert migrate(conn) == 12  # v12: financial_statement 财务三大表缓存表


def test_v7_creates_all_tables(conn):
    migrate(conn)
    for tbl in (
        "dragon_tiger_list",
        "paper_account",
        "paper_order",
        "paper_position",
        "paper_trade",
        "paper_equity_curve",
        "paper_settings",
    ):
        assert _table_exists(conn, tbl), f"{tbl} not created"


def test_v7_idempotent(conn):
    migrate(conn)
    assert migrate(conn) == 12  # 二次运行不报错、不重复推进


def test_opportunity_item_sector_columns(conn):
    migrate(conn)
    assert {
        "source_detail",
        "sector",
        "sector_code",
        "sector_rank",
        "sector_stock_rank",
    }.issubset(_cols(conn, "opportunity_item"))


def test_dragon_tiger_list_columns(conn):
    migrate(conn)
    expected = {
        "trade_date", "ts_code", "name", "close", "pct_change",
        "turnover_rate", "amount", "l_buy", "l_sell", "l_amount",
        "net_amount", "net_rate", "amount_rate", "reason", "raw_json",
    }
    assert expected.issubset(_cols(conn, "dragon_tiger_list"))


def test_moneyflow_raw_json_column(conn):
    migrate(conn)
    assert "raw_json" in _cols(conn, "moneyflow_dc")


def test_dragon_tiger_list_indexes(conn):
    migrate(conn)
    idxs = {r[1] for r in conn.execute("PRAGMA index_list(dragon_tiger_list)")}
    assert "idx_dtl_date_net" in idxs
    assert "idx_dtl_code" in idxs


def test_paper_account_columns(conn):
    migrate(conn)
    assert {"id", "initial_cash", "cash", "created_at", "updated_at"}.issubset(
        _cols(conn, "paper_account")
    )


def test_paper_order_columns(conn):
    migrate(conn)
    assert {
        "id", "ts_code", "side", "price_type", "limit_price",
        "qty", "amount_budget", "status", "created_date",
        "filled_price", "filled_qty", "fee",
    }.issubset(_cols(conn, "paper_order"))


def test_paper_trade_columns(conn):
    migrate(conn)
    assert {
        "id", "order_id", "ts_code", "side", "price", "qty",
        "gross", "fee", "realized_pnl", "traded_at", "trade_date",
    }.issubset(_cols(conn, "paper_trade"))


def test_paper_position_columns(conn):
    migrate(conn)
    assert {"ts_code", "qty", "avg_cost"}.issubset(_cols(conn, "paper_position"))


def test_paper_equity_curve_columns(conn):
    migrate(conn)
    assert {"trade_date", "cash", "position_value", "total_equity", "daily_pnl"}.issubset(
        _cols(conn, "paper_equity_curve")
    )


def test_paper_order_price_type_check_rejects_invalid(conn):
    """price_type 的 CHECK 约束必须挡住非法值。"""
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO paper_order(ts_code, side, price_type, status, created_at, created_date) "
            "VALUES('000001.SZ','buy','telepathy','pending','2026-06-04T10:00:00','2026-06-04')"
        )


def test_paper_order_side_check_rejects_invalid(conn):
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO paper_order(ts_code, side, price_type, status, created_at, created_date) "
            "VALUES('000001.SZ','hodl','market','pending','2026-06-04T10:00:00','2026-06-04')"
        )
