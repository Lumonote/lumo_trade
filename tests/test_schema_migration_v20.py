"""验证 migration 20:回填历史 change_pct + 补两条查询索引。

背景:入库路径此前漏透传 change_pct(见 analysis/opportunity_filter),存量
opportunity_item 该列整列 NULL,股票池「平均涨跌」长期为空;同口径的当日涨跌幅
一直写在 signals_json.day_change 里,迁移直接回填。
"""
import sqlite3

import pytest

from data_store.schema import _MIGRATIONS, migrate

# 版本号写死会在每次 schema 升版时假报错(与 v7/v16 测试同款处理)
LATEST = max(v for v, _ in _MIGRATIONS)


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    yield c
    c.close()


def _seed_v19(conn):
    """建到 v19 为止的库,并塞一条 change_pct 为空、signals 里有 day_change 的旧数据。"""
    from data_store import schema

    original = schema._MIGRATIONS
    schema._MIGRATIONS = [m for m in original if m[0] <= 19]
    try:
        migrate(conn)
    finally:
        schema._MIGRATIONS = original
    conn.execute(
        "INSERT INTO opportunity_run(id, run_at, run_date) VALUES(1, '2026-06-10T15:00:00', '2026-06-10')"
    )
    conn.executemany(
        "INSERT INTO opportunity_item(run_id, code, name, change_pct, signals_json) VALUES(1,?,?,?,?)",
        [
            ("000001", "有信号", None, '{"day_change": 4.65}'),
            ("000002", "无信号", None, "{}"),
            ("000003", "坏 JSON", None, "not json"),
            ("000004", "已有值", 1.5, '{"day_change": 9.99}'),
        ],
    )


def test_migrate_backfills_change_pct_from_signals(conn):
    _seed_v19(conn)
    assert migrate(conn) == LATEST

    rows = {
        r["code"]: r["change_pct"]
        for r in conn.execute("SELECT code, change_pct FROM opportunity_item")
    }
    assert rows["000001"] == pytest.approx(4.65)   # 回填
    assert rows["000002"] is None                  # 没有 day_change → 保持空
    assert rows["000003"] is None                  # 坏 JSON 不炸、不写值
    assert rows["000004"] == pytest.approx(1.5)    # 已有值不被覆盖


def test_migrate_adds_lookup_indexes(conn):
    migrate(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_market_daily_date" in names
    assert "idx_mf_code_date" in names
