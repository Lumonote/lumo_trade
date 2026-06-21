# tests/test_schema_migration_v15.py
"""验证 migration 15 建 opportunity_hot_news 表(机会挖掘前十热点新闻按天落盘)。"""
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


def test_migrate_reaches_v15(conn):
    assert migrate(conn) >= 15


def test_schema_version_max_is_15(conn):
    migrate(conn)
    versions = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    assert 15 in versions


def test_hot_news_table_created(conn):
    migrate(conn)
    assert _table_exists(conn, "opportunity_hot_news")


def test_hot_news_columns(conn):
    migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(opportunity_hot_news)")}
    assert {
        "run_id", "news_rank", "title", "url", "source", "publish_time", "heat",
    }.issubset(cols)


def test_hot_news_foreign_key_to_run_cascades(conn):
    migrate(conn)
    fks = conn.execute("PRAGMA foreign_key_list(opportunity_hot_news)").fetchall()
    assert any(fk[2] == "opportunity_run" and fk[6] == "CASCADE" for fk in fks), fks


def test_hot_news_index_present(conn):
    migrate(conn)
    idxs = {r[1] for r in conn.execute("PRAGMA index_list(opportunity_hot_news)")}
    assert "idx_opp_hotnews_run" in idxs


def test_migrate_idempotent(conn):
    final = migrate(conn)
    assert migrate(conn) == final
