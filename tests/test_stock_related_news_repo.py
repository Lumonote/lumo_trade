import sqlite3
import pytest
from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)
    from data_store import connection, stock_related_news_repo
    monkeypatch.setattr(connection, "get_conn", lambda: c)
    monkeypatch.setattr(stock_related_news_repo, "get_conn", lambda: c)
    yield c
    c.close()


def _item(h, tier="direct"):
    return {"tier": tier, "title": f"t{h}", "url": f"http://x/{h}", "source": "金十",
            "published_at": "2026-06-20T10:00:00", "relation_reason": "名称命中",
            "sentiment": "neutral", "content_hash": h}


def test_replace_is_idempotent_and_overwrites(conn):
    from data_store import stock_related_news_repo as repo
    assert repo.replace_for_code("601702", [_item("a"), _item("b")], "2026-06-20T10:00:00") == 2
    # 再次替换为单条 → 旧的被清掉
    assert repo.replace_for_code("601702", [_item("c")], "2026-06-20T11:00:00") == 1
    snap = repo.latest_for_code("601702")
    assert snap["fetched_at"] == "2026-06-20T11:00:00"
    assert [i["content_hash"] for i in snap["items"]] == ["c"]


def test_latest_for_unknown_code_returns_empty(conn):
    from data_store import stock_related_news_repo as repo
    snap = repo.latest_for_code("000000")
    assert snap == {"items": [], "fetched_at": None}
