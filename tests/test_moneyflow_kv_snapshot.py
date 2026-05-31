import json

import pandas as pd
import pytest

from data_store import (
    connection as conn_mod,
    kv_repo,
    market_snapshot_repo,
    moneyflow_repo,
)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_SQLITE_PATH", str(tmp_path / "k.sqlite"))
    conn_mod.reset_for_testing()
    yield
    conn_mod.reset_for_testing()


def test_moneyflow_upsert_dedup_by_top_n(tmp_db):
    df = pd.DataFrame({
        "trade_date": ["20260520", "20260520"],
        "ts_code": ["000001.SZ", "688343.SH"],
        "name": ["平安", "联动"],
        "pct_change": [1.2, 5.5],
        "close": [11.5, 30.1],
        "net_amount": [100.0, 200.0],
    })
    n1 = moneyflow_repo.upsert_df(df, top_n=3)
    n2 = moneyflow_repo.upsert_df(df, top_n=100)
    assert n1 == 2 and n2 == 2
    assert moneyflow_repo.count() == 4
    out = moneyflow_repo.get_top_n("20260520", 3)
    assert len(out) == 2
    assert moneyflow_repo.latest_date() == "20260520"


def test_moneyflow_upsert_handles_bom_column(tmp_db):
    df = pd.DataFrame({
        "﻿trade_date": ["20260520"],
        "ts_code": ["000001.SZ"],
        "_amount_unit": ["万元"],
    })
    df.columns = [c.lstrip("﻿") for c in df.columns]
    n = moneyflow_repo.upsert_df(df, top_n=3)
    assert n == 1
    out = moneyflow_repo.get_top_n("20260520", 3)
    assert out["amount_unit"].iloc[0] == "万元"


def test_kv_repo_roundtrip(tmp_db):
    payload = {"stocks": [{"code": "000001", "score": 100}]}
    kv_repo.set_("hot_stocks", "latest", payload, ttl_seconds=3600)
    got = kv_repo.get("hot_stocks", "latest")
    assert got is not None
    data, _ = got
    assert data == payload
    assert kv_repo.delete("hot_stocks", "latest") == 1
    assert kv_repo.get("hot_stocks", "latest") is None


def test_market_daily_and_flow_upsert(tmp_db):
    daily_df = pd.DataFrame({
        "ts_code": ["000001.SZ", "688343.SH"],
        "trade_date": ["20260520", "20260520"],
        "open": [11.5, 30.0],
        "high": [11.7, 31.0],
        "low": [11.3, 29.5],
        "close": [11.6, 30.5],
        "pct_chg": [0.5, 1.7],
    })
    assert market_snapshot_repo.upsert_daily_df(daily_df) == 2

    flow_df = pd.DataFrame({
        "trade_date": ["20260520"],
        "ts_code": ["000001.SZ"],
        "name": ["平安"],
        "net_amount": [123.4],
    })
    assert market_snapshot_repo.upsert_flow_df(flow_df) == 1
    assert market_snapshot_repo.daily_count() == 2
    assert market_snapshot_repo.flow_count() == 1
    snap = market_snapshot_repo.get_daily("20260520")
    assert set(snap["ts_code"]) == {"000001.SZ", "688343.SH"}
