#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E4：基本面采集器优先复用已入库 daily_basic（spec 2026-05-31 §6.5）。

纯逻辑（代码后缀归一）+ 命中库走库路径（注入 tmp sqlite + monkeypatch repo，不触网）。
"""
import sqlite3

import pandas as pd
import pytest

from data_store.schema import migrate
from data_store import connection, daily_basic_repo
from analysis.fundamental_data_collector import FundamentalDataCollector


# --------------------------------------------------------------------------- 纯逻辑
def test_to_ts_code_suffix():
    assert FundamentalDataCollector("600519")._to_ts_code() == "600519.SH"
    assert FundamentalDataCollector("000001")._to_ts_code() == "000001.SZ"
    assert FundamentalDataCollector("300750")._to_ts_code() == "300750.SZ"
    assert FundamentalDataCollector("830799")._to_ts_code() == "830799.BJ"
    assert FundamentalDataCollector("900901")._to_ts_code() == "900901.SH"  # 沪 B 股


# --------------------------------------------------------------------------- 走库路径
@pytest.fixture
def db(tmp_path, monkeypatch):
    c = sqlite3.connect(str(tmp_path / "t.sqlite"), isolation_level=None)
    migrate(c)
    getter = lambda: c  # noqa: E731
    monkeypatch.setattr(connection, "get_conn", getter)
    monkeypatch.setattr(daily_basic_repo, "get_conn", getter)
    yield c
    c.close()


def test_indicators_prefer_daily_basic(db, monkeypatch):
    daily_basic_repo.upsert_df(pd.DataFrame([{
        "ts_code": "000001.SZ", "trade_date": "20260529",
        "pe": 5.0, "pe_ttm": 4.8, "pb": 0.6, "ps": 1.3, "ps_ttm": 1.1,
        "total_mv": 21482351.0, "circ_mv": 21481999.92,  # 万元
    }]))
    collector = FundamentalDataCollector("000001")

    def _boom(*a, **k):
        raise AssertionError("daily_basic 命中时不应触网（不应调用腾讯接口）")
    monkeypatch.setattr(collector, "_get_financial_indicators_tencent", _boom)

    ind = collector.get_financial_indicators()

    assert ind["data_source"] == "daily_basic"
    assert ind["pe"] == 4.8           # PE 优先 pe_ttm
    assert ind["pe_ratio"] == 4.8     # 向后兼容键保留
    assert ind["pb"] == 0.6
    assert ind["ps_ratio"] == 1.1     # PS 优先 ps_ttm
    # 万元 → 元（×1e4），对齐腾讯/clist 的「元」单位契约
    assert ind["total_market_cap"] == 21482351.0 * 1e4
    assert ind["circulation_market_cap"] == 21481999.92 * 1e4


def test_indicators_fall_through_when_db_empty(db):
    # 库内无该股 → daily_basic 分支返回 None，交回原有实时抓取链
    collector = FundamentalDataCollector("000002")
    assert collector._get_indicators_from_daily_basic() is None


def test_indicators_negative_pe_marked_loss(db, monkeypatch):
    # 负 PE（亏损）应走 _format_indicators 的「亏损(x)」标注，不污染数值消费方
    daily_basic_repo.upsert_df(pd.DataFrame([{
        "ts_code": "300750.SZ", "trade_date": "20260529",
        "pe_ttm": -12.3, "pb": 2.0, "total_mv": 100.0, "circ_mv": 80.0,
    }]))
    collector = FundamentalDataCollector("300750")
    monkeypatch.setattr(collector, "_get_financial_indicators_tencent",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应触网")))
    ind = collector.get_financial_indicators()
    assert ind["data_source"] == "daily_basic"
    assert isinstance(ind["pe"], str) and "亏损" in ind["pe"]
    assert ind["pb"] == 2.0
