"""验证 migration 16 建 stock_related_news 表。"""
import sqlite3
import pytest
from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    migrate(c)
    yield c
    c.close()


def test_migrate_reaches_v16(conn):
    assert migrate(conn) == 16


def test_stock_related_news_table_exists(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(stock_related_news)")}
    assert {"code", "tier", "title", "content_hash", "fetched_at"} <= cols
