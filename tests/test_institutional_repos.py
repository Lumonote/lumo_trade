# tests/test_institutional_repos.py
"""6 个 institutional repo 的 upsert / get / latest 行为。"""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    migrate(c)

    # 用 monkeypatch 替换全局 get_conn，让 repo 模块走该 conn
    _getter = lambda: c  # noqa: E731
    from data_store import connection
    monkeypatch.setattr(connection, "get_conn", _getter)
    # Patch the already-imported get_conn in each repo module
    from data_store import (
        dragon_tiger_repo, hsgt_repo, holders_repo,
        survey_repo, fund_hold_repo, sync_log_repo,
    )
    monkeypatch.setattr(dragon_tiger_repo, "get_conn", _getter)
    monkeypatch.setattr(hsgt_repo, "get_conn", _getter)
    monkeypatch.setattr(holders_repo, "get_conn", _getter)
    monkeypatch.setattr(survey_repo, "get_conn", _getter)
    monkeypatch.setattr(fund_hold_repo, "get_conn", _getter)
    monkeypatch.setattr(sync_log_repo, "get_conn", _getter)
    yield c
    c.close()


def test_dragon_tiger_repo_upsert_and_get(conn):
    from data_store import dragon_tiger_repo as dt

    rows = [
        {"ts_code": "000001.SZ", "trade_date": "2026-05-27", "inst_name": "X 营业部",
         "side": "buy", "net_amount": 1.2e8, "buy_amount": 1.5e8, "sell_amount": 3e7,
         "is_quant": 1, "quant_confidence": "high", "reason": "日涨幅 7%"},
        {"ts_code": "000001.SZ", "trade_date": "2026-05-27", "inst_name": "Y 营业部",
         "side": "sell", "net_amount": -5e7, "buy_amount": 1e7, "sell_amount": 6e7,
         "is_quant": 0, "quant_confidence": None, "reason": "日涨幅 7%"},
    ]
    n = dt.upsert_rows(rows)
    assert n == 2

    df = dt.get_by_code("000001.SZ")
    assert len(df) == 2
    assert set(df["inst_name"]) == {"X 营业部", "Y 营业部"}

    # 幂等：再 upsert 一次仍是 2 行
    dt.upsert_rows(rows)
    df2 = dt.get_by_code("000001.SZ")
    assert len(df2) == 2


def test_dragon_tiger_get_by_code_matches_bare_and_suffixed(conn):
    """6 位裸码查询必须命中带后缀入库的行：Tushare top_inst 回填存 '000007.SZ'，
    但 suite 统一传 6 位 '000007' —— 修复龙虎榜席位恒「数据不足」的格式错配 bug。"""
    from data_store import dragon_tiger_repo as dt

    dt.upsert_rows([
        {"ts_code": "000007.SZ", "trade_date": "2026-05-27", "inst_name": "量化 A",
         "side": "buy", "net_amount": 9e7, "buy_amount": 1e8, "sell_amount": 1e7,
         "is_quant": 1, "quant_confidence": 0.9, "reason": "上榜"},
    ])
    assert len(dt.get_by_code("000007")) == 1        # 核心修复：裸码命中后缀行
    assert len(dt.get_by_code("000007.SZ")) == 1     # 向后兼容：后缀查询仍命中
    assert dt.latest("000007")["trade_date"] == "2026-05-27"
    assert len(dt.get_by_code("000007", "2026-05-27")) == 1  # 带日期过滤同样归一


def test_hsgt_repo_latest(conn):
    from data_store import hsgt_repo

    hsgt_repo.upsert_rows([
        {"ts_code": "000001.SZ", "trade_date": "2026-05-25",
         "hold_vol": 1.0e8, "hold_ratio": 5.1, "market_cap": 1.2e10},
        {"ts_code": "000001.SZ", "trade_date": "2026-05-27",
         "hold_vol": 1.1e8, "hold_ratio": 5.4, "market_cap": 1.3e10},
    ])
    latest = hsgt_repo.latest("000001.SZ")
    assert latest["trade_date"] == "2026-05-27"
    assert latest["hold_ratio"] == 5.4


def test_holders_repo_top10_and_holdernumber(conn):
    from data_store import holders_repo

    holders_repo.upsert_top10([
        {"ts_code": "000001.SZ", "end_date": "2026-03-31", "holder_rank": 1,
         "holder_name": "公募 A", "hold_amount": 1e8, "hold_ratio": 6.2,
         "change_type": "add", "change_amount": 2e7},
    ])
    df = holders_repo.get_top10("000001.SZ", "2026-03-31")
    assert len(df) == 1 and df.iloc[0]["holder_name"] == "公募 A"

    holders_repo.upsert_holdernumber([
        {"ts_code": "000001.SZ", "end_date": "2026-03-31",
         "holder_num": 50000, "avg_hold": 1234.5, "pct_change": -3.2},
    ])
    latest = holders_repo.latest_holdernumber("000001.SZ")
    assert latest["holder_num"] == 50000


def test_survey_repo_recent(conn):
    from data_store import survey_repo

    survey_repo.upsert_rows([
        {"ts_code": "000001.SZ", "survey_date": "2026-05-20",
         "inst_name": "公募 A", "reception": "董秘", "topic": "AI 业务"},
        {"ts_code": "000001.SZ", "survey_date": "2026-05-10",
         "inst_name": "私募 B", "reception": "证代", "topic": "Q1 业绩"},
    ])
    df = survey_repo.get_by_code("000001.SZ", since="2026-05-15")
    assert len(df) == 1
    assert df.iloc[0]["inst_name"] == "公募 A"


def test_fund_hold_repo_upsert(conn):
    from data_store import fund_hold_repo

    fund_hold_repo.upsert_rows([
        {"ts_code": "000001.SZ", "end_date": "2026-03-31",
         "fund_code": "001234", "fund_name": "易方达蓝筹",
         "hold_shares": 1e7, "market_value": 1.5e8, "nv_ratio": 3.4},
    ])
    df = fund_hold_repo.get_by_code("000001.SZ", "2026-03-31")
    assert len(df) == 1


def test_sync_log_repo_recent_summary(conn):
    from data_store import sync_log_repo

    sync_log_repo.append("lhb", "000001.SZ", "2026-05-27T17:31:00", "ok", rows=42)
    sync_log_repo.append("lhb", "", "2026-05-27T17:32:00", "failed", error="429")
    summary = sync_log_repo.summary_last_24h(now_iso="2026-05-28T09:00:00")
    assert summary["lhb"]["ok"] == 1
    assert summary["lhb"]["failed"] == 1
