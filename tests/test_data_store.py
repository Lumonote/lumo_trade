import os
from pathlib import Path

import pytest

from data_store import connection as conn_mod
from data_store import schema as schema_mod


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "kronos_test.sqlite"
    monkeypatch.setenv("KRONOS_SQLITE_PATH", str(db))
    conn_mod.reset_for_testing()
    yield db
    conn_mod.reset_for_testing()


def test_get_conn_creates_db_and_applies_schema(tmp_db):
    c = conn_mod.get_conn()
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "schema_version",
        "ohlcv",
        "sentiment_cache",
        "daily_basic",
        "trade_calendar",
        "moneyflow_dc",
        "kv_cache",
        "market_daily",
        "market_flow_daily",
        "dragon_tiger_inst",
        "hsgt_individual",
        "top10_floatholders",
        "stk_holdernumber",
        "jgdy_detail",
        "fund_hold_detail",
        "sync_log",
    }.issubset(tables)
    version = c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert version == 6


def test_migrate_is_idempotent(tmp_db):
    c = conn_mod.get_conn()
    before = c.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    schema_mod.migrate(c)
    after = c.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert before == after


def test_pragmas_are_set(tmp_db):
    c = conn_mod.get_conn()
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_db_path_respects_env(tmp_path, monkeypatch):
    target = tmp_path / "alt.sqlite"
    monkeypatch.setenv("KRONOS_SQLITE_PATH", str(target))
    assert conn_mod.db_path() == target
