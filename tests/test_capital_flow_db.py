#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E5：资金流复用已入库 market_flow_daily（spec 2026-05-31 §6.6）。

注入 tmp sqlite + monkeypatch repo，验证 CapitalFlowAnalyzer 命中库即走库路径
（订单分档 / 连续性 / 元级阈值），不触网。
"""
import sqlite3

import numpy as np
import pandas as pd
import pytest

from data_store.schema import migrate
from data_store import connection, market_snapshot_repo
from analysis.advanced_analysis import CapitalFlowAnalyzer


@pytest.fixture
def db(tmp_path, monkeypatch):
    c = sqlite3.connect(str(tmp_path / "t.sqlite"), isolation_level=None)
    migrate(c)
    getter = lambda: c  # noqa: E731
    monkeypatch.setattr(connection, "get_conn", getter)
    monkeypatch.setattr(market_snapshot_repo, "get_conn", getter)
    yield c
    c.close()


def _flow_rows(rows):
    """rows: list of (trade_date, net, elg, lg, md, sm)（单位：万元，东财各档净额）。"""
    return pd.DataFrame([{
        "trade_date": td, "ts_code": "000001.SZ", "name": "平安银行",
        "pct_change": 0.0, "close": 12.0,
        "net_amount": net, "buy_elg_amount": elg, "buy_lg_amount": lg,
        "buy_md_amount": md, "buy_sm_amount": sm,
    } for (td, net, elg, lg, md, sm) in rows])


def _fake_ohlcv(n=20):
    close = np.linspace(10, 11, n)
    return pd.DataFrame({"close": close, "volume": np.full(n, 1e6),
                         "amount": np.full(n, 1e7)})


def _no_net(analyzer, monkeypatch):
    monkeypatch.setattr(analyzer, "_fetch_tushare_moneyflow",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("命中库时不应触网")))


def test_get_flow_by_code_desc(db):
    market_snapshot_repo.upsert_flow_df(_flow_rows([
        ("20260204", 5708.16, 4981.17, 726.98, -4567.57, -1140.59),
        ("20260205", 15228.21, 17116.47, -1888.26, -9064.02, -6164.18),
    ]))
    out = market_snapshot_repo.get_flow_by_code("000001.SZ", limit=20)
    assert list(out["trade_date"]) == ["20260205", "20260204"]  # 降序，最新在前


def test_order_sizes_prefer_db(db, monkeypatch):
    market_snapshot_repo.upsert_flow_df(_flow_rows([
        ("20260205", 15228.21, 17116.47, -1888.26, -9064.02, -6164.18),
    ]))
    analyzer = CapitalFlowAnalyzer()
    _no_net(analyzer, monkeypatch)
    oa = analyzer._analyze_order_sizes("000001", _fake_ohlcv())
    assert oa["data_source"] == "market_flow_daily"
    # 万元 ×1e4 → 元
    assert oa["super_large_net"] == pytest.approx(17116.47 * 1e4)
    assert oa["main_net_inflow"] == pytest.approx(15228.21 * 1e4)            # =(elg+lg)×1e4=net×1e4
    assert oa["retail_net_inflow"] == pytest.approx((-9064.02 - 6164.18) * 1e4)


def test_continuity_prefer_db(db, monkeypatch):
    # 最新 3 日主力净额连续为正 → 连续流入 3 日（再往前转负，应断开）
    market_snapshot_repo.upsert_flow_df(_flow_rows([
        ("20260203", -100.0, -60.0, -40.0, 50.0, 50.0),
        ("20260204", 5708.16, 4981.17, 726.98, -4567.57, -1140.59),
        ("20260205", 15228.21, 17116.47, -1888.26, -9064.02, -6164.18),
        ("20260206", 300.0, 200.0, 100.0, -150.0, -150.0),
    ]))
    analyzer = CapitalFlowAnalyzer()
    _no_net(analyzer, monkeypatch)
    cont = analyzer._analyze_main_force_continuity("000001", _fake_ohlcv())
    assert cont["consecutive_inflow_days"] == 3
    assert cont["trend"] == "inflow"


def test_db_miss_returns_none(db):
    analyzer = CapitalFlowAnalyzer()
    assert analyzer._fetch_db_moneyflow("000002") is None


def test_analyze_uses_db_real_thresholds(db, monkeypatch):
    """端到端：命中库 → data_source != synthetic → 元级阈值 → 大额净流入加分 + 亿元文案。

    插 3 日（连续性需 ≥3 日），最新一日带 1.52 亿主力净额触发元级阈值。
    """
    market_snapshot_repo.upsert_flow_df(_flow_rows([
        ("20260203", 5000.0, 3000.0, 2000.0, -2500.0, -2500.0),
        ("20260204", 6000.0, 4000.0, 2000.0, -3000.0, -3000.0),
        ("20260205", 15228.21, 17116.47, -1888.26, -9064.02, -6164.18),
    ]))
    analyzer = CapitalFlowAnalyzer()
    _no_net(analyzer, monkeypatch)
    res = analyzer.analyze("000001", _fake_ohlcv())
    assert res["details"]["data_source"] == "market_flow_daily"
    assert res["score"] > 50
    assert any("亿" in s for s in res["signals"])  # 1.52亿 → 元级文案
