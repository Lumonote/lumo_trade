import pandas as pd
import pytest

from data_store import calendar_repo, connection as conn_mod, daily_basic_repo


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_SQLITE_PATH", str(tmp_path / "k.sqlite"))
    conn_mod.reset_for_testing()
    yield
    conn_mod.reset_for_testing()


def test_calendar_upsert_dedup(tmp_db):
    calendar_repo.upsert(["20260524", "20260525"])
    calendar_repo.upsert(["20260525", "20260526"])
    assert calendar_repo.count() == 3
    days = calendar_repo.open_days()
    assert days == ["20260524", "20260525", "20260526"]


def test_calendar_is_open_flag(tmp_db):
    calendar_repo.upsert(["20260524"], is_open=1)
    calendar_repo.upsert(["20260525"], is_open=0)
    assert calendar_repo.open_days() == ["20260524"]


def test_daily_basic_upsert_and_query(tmp_db):
    df = pd.DataFrame({
        "ts_code": ["000001.SZ", "688343.SH"],
        "trade_date": ["20260520", "20260520"],
        "close": [11.5, 30.1],
        "pe": [5.4, 35.2],
        "circ_mv": [1.2e6, 8e4],
    })
    n = daily_basic_repo.upsert_df(df)
    assert n == 2
    out = daily_basic_repo.get_for_date("20260520")
    assert set(out["ts_code"].tolist()) == {"000001.SZ", "688343.SH"}
    assert out["close"].sum() == pytest.approx(41.6)


def test_daily_basic_upsert_is_idempotent(tmp_db):
    df = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260520"], "close": [11.5]})
    daily_basic_repo.upsert_df(df)
    df.loc[0, "close"] = 99.9
    daily_basic_repo.upsert_df(df)
    out = daily_basic_repo.get_for_code("000001.SZ")
    assert out["close"].iloc[0] == pytest.approx(99.9)
    assert daily_basic_repo.count() == 1
