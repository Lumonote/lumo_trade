# tests/test_opportunity_hot_news_repo.py
"""opportunity_repo 的 save_run(hot_news=) 落盘 + latest_hot_news 读取行为。"""
from __future__ import annotations

import sqlite3

import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    migrate(c)

    _getter = lambda: c  # noqa: E731
    from data_store import connection
    monkeypatch.setattr(connection, "get_conn", _getter)
    from data_store import opportunity_repo
    monkeypatch.setattr(opportunity_repo, "get_conn", _getter)
    yield c
    c.close()


def _meta(**overrides):
    base = {
        "run_at": "2026-06-19T15:31:02",
        "source": "multi",
        "candidate_limit": 100,
        "mode": "market_scan",
        "ruleset_version": "v24",
        "config_hash": "abc123",
        "report_file": "opportunity_top10_20260619_153102.md",
        "candidates": 120,
        "analyzed": 118,
        "duration_sec": 321.5,
    }
    base.update(overrides)
    return base


def _news(n=12):
    # 乱序 heat,验证落库时按 heat 降序、限 10。
    heats = [30, 95, 60, 88, 12, 77, 50, 99, 5, 41, 70, 22][:n]
    return [
        {"title": f"news-{i}", "url": f"http://x/{i}", "source": "东方财富",
         "publish_time": "2026-06-19 09:30", "heat": h, "rank": i}
        for i, h in enumerate(heats, start=1)
    ]


def test_save_run_writes_hot_news_desc_and_limit10(conn):
    from data_store import opportunity_repo as repo

    run_id = repo.save_run(_meta(), [], hot_news=_news(12))
    out = repo.latest_hot_news()
    assert len(out) == 10  # 限 10
    heats = [r["heat"] for r in out]
    assert heats == sorted(heats, reverse=True)  # 严格降序
    assert heats[0] == 99
    # 投影字段齐全,rank 来自 news_rank(1 = heat 最高)
    top = out[0]
    assert set(top) >= {"rank", "title", "url", "source", "publish_time", "heat"}
    assert top["rank"] == 1
    assert top["title"] == "news-8"  # heat=99 的那条
    assert run_id > 0


def test_latest_hot_news_by_date_takes_latest_run_of_day(conn):
    from data_store import opportunity_repo as repo

    # 6-19 两次 run(不同 run_at)+ 6-18 一次
    repo.save_run(_meta(run_at="2026-06-19T09:00:00"), [],
                  hot_news=[{"title": "morning", "heat": 50}])
    repo.save_run(_meta(run_at="2026-06-19T15:00:00"), [],
                  hot_news=[{"title": "afternoon", "heat": 60}])
    repo.save_run(_meta(run_at="2026-06-18T15:00:00"), [],
                  hot_news=[{"title": "yesterday", "heat": 70}])

    day = repo.latest_hot_news("2026-06-19")
    assert [r["title"] for r in day] == ["afternoon"]  # 当日最近一次 run

    glob = repo.latest_hot_news()  # 全局最近一次有热点的 run = 6-19 15:00
    assert [r["title"] for r in glob] == ["afternoon"]


def test_latest_hot_news_empty_when_no_data(conn):
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(), [])  # 无 hot_news
    assert repo.latest_hot_news() == []
    assert repo.latest_hot_news("2026-06-19") == []


def test_save_run_hot_news_none_or_empty_no_write(conn):
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-19T09:00:00"), [], hot_news=None)
    repo.save_run(_meta(run_at="2026-06-19T10:00:00"), [], hot_news=[])
    n = conn.execute("SELECT COUNT(*) FROM opportunity_hot_news").fetchone()[0]
    assert n == 0


def test_save_run_hot_news_dedup_by_title_keep_higher_heat(conn):
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(), [], hot_news=[
        {"title": "dup", "heat": 40},
        {"title": "dup", "heat": 90},
        {"title": "other", "heat": 50},
    ])
    out = repo.latest_hot_news()
    titles = [r["title"] for r in out]
    assert titles.count("dup") == 1
    dup = next(r for r in out if r["title"] == "dup")
    assert dup["heat"] == 90  # 保留 heat 高者


def test_delete_run_cascades_hot_news(conn):
    from data_store import opportunity_repo as repo

    run_id = repo.save_run(_meta(), [], hot_news=_news(3))
    assert conn.execute("SELECT COUNT(*) FROM opportunity_hot_news").fetchone()[0] == 3
    conn.execute("DELETE FROM opportunity_run WHERE id=?", (run_id,))
    assert conn.execute("SELECT COUNT(*) FROM opportunity_hot_news").fetchone()[0] == 0
