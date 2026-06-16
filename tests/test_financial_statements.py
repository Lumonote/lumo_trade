"""财务三大表(item G):repo 落库/查询 + core 缓存优先取数逻辑。

provider 与 schema 版本以 monkeypatch 隔离,不联网。
"""
from __future__ import annotations

import sqlite3

import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "k.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)
    getter = lambda: c  # noqa: E731
    from data_store import connection, financial_statements_repo
    monkeypatch.setattr(connection, "get_conn", getter)
    monkeypatch.setattr(financial_statements_repo, "get_conn", getter)
    yield c
    c.close()


def _rows():
    return [
        {"report_date": "2025-03-31", "period": "2025一季报", "currency": "CNY",
         "items": {"资产总计": 1000.0, "负债合计": 400.0}},
        {"report_date": "2024-12-31", "period": "2024年报", "currency": "CNY",
         "items": {"资产总计": 900.0, "负债合计": 380.0}},
    ]


def test_migrate_creates_financial_statement_table(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "financial_statement" in names


def test_repo_roundtrip_and_queries(conn):
    from data_store import financial_statements_repo as repo
    n = repo.save_statements("600519", "balance", _rows(), source="akshare", ts_code="600519.SH")
    assert n == 2
    assert repo.has_cached("600519") is True
    assert repo.has_cached("000001") is False
    assert repo.latest_report_date("600519", "balance") == "2025-03-31"
    rows = repo.statements_for("600519", "balance")
    assert [r["report_date"] for r in rows] == ["2025-03-31", "2024-12-31"]  # 倒序
    assert rows[0]["items"]["资产总计"] == 1000.0
    assert rows[0]["source"] == "akshare"


def test_repo_upsert_overwrites_same_period(conn):
    from data_store import financial_statements_repo as repo
    repo.save_statements("600519", "balance", [{"report_date": "2025-03-31", "items": {"资产总计": 1.0}}], source="akshare")
    repo.save_statements("600519", "balance", [{"report_date": "2025-03-31", "items": {"资产总计": 2.0}}], source="tushare")
    rows = repo.statements_for("600519", "balance")
    assert len(rows) == 1
    assert rows[0]["items"]["资产总计"] == 2.0
    assert rows[0]["source"] == "tushare"


def test_core_cache_first_and_force(conn, monkeypatch):
    import webui.core as core
    calls = {"n": 0}
    def fake_fetch(code):
        calls["n"] += 1
        return {"balance": _rows(), "income": [], "cashflow": [], "source": "akshare", "partial": True}
    from analysis import financial_statements_provider as provider
    monkeypatch.setattr(provider, "fetch_three_statements", fake_fetch)

    # 1) 缓存缺失 → 取数一次并落库,标记 cached=False
    out = core.stock_financial_statements("600519")
    assert calls["n"] == 1
    assert out["cached"] is False
    assert out["statements"]["balance"][0]["items"]["资产总计"] == 1000.0
    assert out["source"] == "akshare"

    # 2) 再次调用 → 命中缓存,provider 不再被调用
    out2 = core.stock_financial_statements("600519")
    assert calls["n"] == 1
    assert out2["cached"] is True

    # 3) force=True → 即使有缓存也重新取数
    out3 = core.stock_financial_statements("600519", force_refresh=True)
    assert calls["n"] == 2
    assert out3["cached"] is False


def test_core_missing_code(conn):
    import webui.core as core
    out = core.stock_financial_statements("")
    assert out["error"]
    assert out["statements"]["balance"] == []


def test_provider_em_symbol_and_normalize():
    from analysis import financial_statements_provider as prov
    assert prov._em_symbol("600519") == "SH600519"
    assert prov._em_symbol("000001") == "SZ000001"
    assert prov._em_symbol("300750") == "SZ300750"
    assert prov._em_symbol("830799") == "BJ830799"
