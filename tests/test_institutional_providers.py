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


def test_holders_provider_fills_nan_holder_rank(conn):
    """回归：上游 top10_float 源的 `编号` 列存在但含 NaN 时，
    不应触发 `NOT NULL constraint failed: top10_floatholders.holder_rank`。

    复现路径：stock_main_stock_holder 等 fallback 源会返回带 `编号` 列但部分行为空，
    旧逻辑只在整列缺失时补号，NaN 行直落 upsert → NULL → 崩 综合分析。
    """
    from analysis.institutional.holders_provider import HoldersProvider

    class _Top10NaNRankAdapter:
        def fetch(self, key, *a, **kw):
            if key == "top10_float":
                return pd.DataFrame({
                    "截止日期": ["2026-03-31", "2026-03-31", "2026-03-31"],
                    "编号": [1, None, 3],          # 第二行缺编号
                    "股东名称": ["股东甲", "股东乙", "股东丙"],
                    "持股数量": [1e8, 8e7, 5e7],
                    "占流通股比例": [6.2, 5.0, 3.1],
                    "股本性质": ["流通A股", "流通A股", "流通A股"],
                })
            from data_store.akshare_adapter import AkshareUnavailable
            raise AkshareUnavailable("no gdhs in this test")

    p = HoldersProvider(akshare_adapter=_Top10NaNRankAdapter())
    res = p.get("000001.SZ")  # 旧逻辑在此抛 sqlite3.IntegrityError

    assert res.data_status == "stale"
    rows = res.data["top10_floatholders"]["rows"]
    assert len(rows) == 3
    assert all(r["holder_rank"] is not None for r in rows)
    assert sorted(r["holder_rank"] for r in rows) == [1, 2, 3]


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
