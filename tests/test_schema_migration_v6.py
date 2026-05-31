# tests/test_schema_migration_v6.py
"""验证 migration v6 建出 7 张新表，schema_version 推进到 6。"""
from __future__ import annotations

import sqlite3
import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    yield c
    c.close()


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def test_v6_creates_seven_new_tables(conn):
    final = migrate(conn)
    assert final == 6
    for tbl in (
        "dragon_tiger_inst",
        "hsgt_individual",
        "top10_floatholders",
        "stk_holdernumber",
        "jgdy_detail",
        "fund_hold_detail",
        "sync_log",
    ):
        assert _table_exists(conn, tbl), f"{tbl} not created"


def test_v6_idempotent(conn):
    migrate(conn)
    assert migrate(conn) == 6  # 二次运行不报错也不重复 insert version


def test_dragon_tiger_inst_columns(conn):
    migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dragon_tiger_inst)")}
    expected = {
        "ts_code", "trade_date", "inst_name", "side",
        "net_amount", "buy_amount", "sell_amount",
        "is_quant", "quant_confidence", "reason",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_dragon_tiger_inst_indexes(conn):
    migrate(conn)
    idxs = {r[1] for r in conn.execute("PRAGMA index_list(dragon_tiger_inst)")}
    assert "idx_lhbi_code_date" in idxs
    assert "idx_lhbi_quant" in idxs
