import json

import pytest

from data_store import connection as conn_mod
from data_store import sentiment_repo


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_SQLITE_PATH", str(tmp_path / "k.sqlite"))
    conn_mod.reset_for_testing()
    yield
    conn_mod.reset_for_testing()


def test_set_get_roundtrip(tmp_db):
    sentiment_repo.set_("overall_market", {"score": 65, "label": "偏强"})
    got = sentiment_repo.get("overall_market")
    assert got is not None
    data, epoch = got
    assert data == {"score": 65, "label": "偏强"}
    assert epoch > 0


def test_identifier_isolation(tmp_db):
    sentiment_repo.set_("sector", {"x": 1}, "BK0001")
    sentiment_repo.set_("sector", {"x": 2}, "BK0002")
    assert sentiment_repo.get("sector", "BK0001")[0] == {"x": 1}
    assert sentiment_repo.get("sector", "BK0002")[0] == {"x": 2}


def test_set_is_upsert(tmp_db):
    sentiment_repo.set_("sector", {"x": 1}, "BK0001")
    sentiment_repo.set_("sector", {"x": 99}, "BK0001")
    assert sentiment_repo.get("sector", "BK0001")[0] == {"x": 99}
    assert sentiment_repo.count() == 1


def test_delete_and_clear(tmp_db):
    sentiment_repo.set_("overall_market", {"a": 1})
    sentiment_repo.set_("sector", {"b": 1}, "BK0001")
    assert sentiment_repo.delete("overall_market") == 1
    assert sentiment_repo.count() == 1
    assert sentiment_repo.clear_all() == 1
    assert sentiment_repo.count() == 0


def test_count_by_type(tmp_db):
    sentiment_repo.set_("sector", {"a": 1}, "BK0001")
    sentiment_repo.set_("sector", {"a": 1}, "BK0002")
    sentiment_repo.set_("overall_market", {"a": 1})
    stats = sentiment_repo.count_by_type()
    assert stats == {"sector": 2, "overall_market": 1}


def test_clear_expired_uses_ttl_map(tmp_db, monkeypatch):
    import datetime as dt
    from data_store import sentiment_repo as repo_mod

    fixed_now = dt.datetime(2026, 5, 25, 12, 0, 0)

    class _FakeDT:
        @staticmethod
        def now():
            return fixed_now
        @staticmethod
        def fromisoformat(s):
            return dt.datetime.fromisoformat(s)
        @staticmethod
        def fromtimestamp(t):
            return dt.datetime.fromtimestamp(t)
        timedelta = dt.timedelta

    repo_mod.set_("sector", {"recent": 1}, "BK0001")
    conn = conn_mod.get_conn()
    conn.execute(
        "UPDATE sentiment_cache SET updated_at=? WHERE cache_type='sector'",
        ((fixed_now - dt.timedelta(seconds=900)).isoformat(timespec="seconds"),),
    )
    monkeypatch.setattr(repo_mod._dt, "datetime", _FakeDT, raising=True)
    removed = repo_mod.clear_expired({"sector": 600})
    assert removed == 1
    assert repo_mod.count() == 0


def test_importer_parses_filenames():
    from data_store.importers.import_sentiment import parse_filename
    assert parse_filename("overall_market") == ("overall_market", "")
    assert parse_filename("sector_BK0447") == ("sector", "BK0447")
    assert parse_filename("sector_constituents_BK0447") == ("sector_constituents", "BK0447")
    assert parse_filename("capital_flow_000001") == ("capital_flow", "000001")
    assert parse_filename("dragon_tiger_000001") == ("dragon_tiger", "000001")
    assert parse_filename("moneyflow_ind_dc_20260524") == ("moneyflow_ind_dc", "20260524")
