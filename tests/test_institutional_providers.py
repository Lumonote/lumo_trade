"""6 个 provider 骨架的接口与降级行为。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(str(path), isolation_level=None)
    migrate(c)
    _getter = lambda: c  # noqa: E731
    from data_store import connection
    monkeypatch.setattr(connection, "get_conn", _getter)
    # Patch the already-imported get_conn in each repo module
    from data_store import dragon_tiger_repo, hsgt_repo, holders_repo, survey_repo, fund_hold_repo
    monkeypatch.setattr(dragon_tiger_repo, "get_conn", _getter)
    monkeypatch.setattr(hsgt_repo, "get_conn", _getter)
    monkeypatch.setattr(holders_repo, "get_conn", _getter)
    monkeypatch.setattr(survey_repo, "get_conn", _getter)
    monkeypatch.setattr(fund_hold_repo, "get_conn", _getter)
    yield c
    c.close()


def test_lhb_provider_unavailable_when_db_empty(conn):
    from analysis.institutional.lhb_provider import LhbProvider
    p = LhbProvider(
        seat_registry=_stub_registry(),
        akshare_adapter=_NullAdapter(),
    )
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"
    assert res.data is None


def test_lhb_provider_returns_stale_from_db(conn):
    from data_store import dragon_tiger_repo
    dragon_tiger_repo.upsert_rows([{
        "ts_code": "000001.SZ", "trade_date": "2026-05-27",
        "inst_name": "华泰证券股份有限公司总部", "side": "buy",
        "net_amount": 1e8, "buy_amount": 1.2e8, "sell_amount": 2e7,
        "is_quant": 1, "quant_confidence": "high", "reason": "测试",
    }])

    from analysis.institutional.lhb_provider import LhbProvider
    p = LhbProvider(seat_registry=_stub_registry(), akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ", days=90)
    assert res.data_status == "stale"
    assert res.data is not None
    assert res.data["quant_seat_appearances"] == 1


def test_hsgt_provider_skeleton(conn):
    from analysis.institutional.hsgt_provider import HsgtProvider
    p = HsgtProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


def test_holders_provider_skeleton(conn):
    from analysis.institutional.holders_provider import HoldersProvider
    p = HoldersProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


def test_survey_provider_skeleton(conn):
    from analysis.institutional.survey_provider import SurveyProvider
    p = SurveyProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


def test_fund_holdings_provider_skeleton(conn):
    from analysis.institutional.fund_holdings_provider import FundHoldingsProvider
    p = FundHoldingsProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


def test_cyq_provider_skeleton(conn):
    from analysis.institutional.cyq_provider import CyqProvider
    p = CyqProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


class _NullAdapter:
    """M1 阶段：所有 akshare 调用直接抛 AkshareUnavailable。"""
    def fetch(self, key, *a, **kw):
        from data_store.akshare_adapter import AkshareUnavailable
        raise AkshareUnavailable("M1: not implemented")


def _stub_registry():
    from analysis.institutional.quant_seat_registry import QuantSeatRegistry
    repo_root = Path(__file__).resolve().parents[1]
    return QuantSeatRegistry(repo_root / "config" / "quant_seats.json")
