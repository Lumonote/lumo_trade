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
    from data_store import dragon_tiger_repo, hsgt_repo, holders_repo, survey_repo, fund_hold_repo, sentiment_repo
    monkeypatch.setattr(dragon_tiger_repo, "get_conn", _getter)
    monkeypatch.setattr(hsgt_repo, "get_conn", _getter)
    monkeypatch.setattr(holders_repo, "get_conn", _getter)
    monkeypatch.setattr(survey_repo, "get_conn", _getter)
    monkeypatch.setattr(fund_hold_repo, "get_conn", _getter)
    monkeypatch.setattr(sentiment_repo, "get_conn", _getter)
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


# ---------------------------------------------------------------------------
# E1: 真实单股抓取（fund / cyq）+ E3 原因透出
# ---------------------------------------------------------------------------

class _FundAdapter:
    """模拟 ak.stock_fund_stock_holder 的真实返回（茅台同款列）。"""
    def fetch(self, key, *a, **kw):
        assert key == "fund_stock_holder"
        return pd.DataFrame({
            "基金名称": ["基金A", "基金B", "基金C"],
            "基金代码": ["001", "002", "003"],
            "持仓数量": [100, 200, 300],
            "占流通股比例": [0.1, 0.2, 0.3],
            "持股市值": [1e7, 3e7, 2e7],
            "占净值比例": [1.0, 2.0, 1.5],
            "截止日期": ["2026-03-31", "2026-03-31", "2025-12-31"],  # 含旧报告期
        })


def test_fund_provider_fetches_and_saves(conn):
    from analysis.institutional.fund_holdings_provider import FundHoldingsProvider
    p = FundHoldingsProvider(akshare_adapter=_FundAdapter())
    res = p.get("600519.SH")
    assert res.data_status == "stale"
    assert res.data["period"] == "2026-03-31"      # 只留最新报告期
    rows = res.data["rows"]
    assert len(rows) == 2                            # 旧报告期 基金C 被剔除
    # 按持股市值降序：基金B(3e7) 在前
    assert rows[0]["fund_name"] == "基金B"
    assert res.data["total_nv_pct"] == 3.0           # 1.0 + 2.0


class _BreakerAdapter:
    def __init__(self, msg):
        self._msg = msg
    def fetch(self, key, *a, **kw):
        from data_store.akshare_adapter import AkshareUnavailable
        raise AkshareUnavailable(self._msg)


def test_fund_provider_reason_surfaces_breaker(conn):
    from analysis.institutional.fund_holdings_provider import FundHoldingsProvider
    p = FundHoldingsProvider(
        akshare_adapter=_BreakerAdapter("circuit breaker open for fund_stock_holder"))
    res = p.get("600519.SH")
    assert res.data_status == "unavailable"
    assert "重仓基金" in res.reason
    assert "熔断" in res.reason                       # 英文异常被翻成中文条件


class _CyqAdapter:
    def fetch(self, key, *a, **kw):
        assert key == "cyq"
        return pd.DataFrame({
            "日期": ["2026-05-28", "2026-05-29"],
            "获利比例": [0.80, 0.83],
            "平均成本": [12.0, 12.3],
            "90成本-低": [10.0, 10.1], "90成本-高": [14.0, 14.2], "90集中度": [0.16, 0.17],
            "70成本-低": [11.0, 11.1], "70成本-高": [13.0, 13.1], "70集中度": [0.08, 0.085],
        })


def test_cyq_provider_fetches_and_summarizes(conn):
    from analysis.institutional.cyq_provider import CyqProvider
    p = CyqProvider(akshare_adapter=_CyqAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "fresh"
    d = res.data
    assert d["as_of"] == "2026-05-29"                # 取最新一行
    assert d["profit_ratio_pct"] == 83.0             # 0.83 -> 83%
    assert d["concentration_90_pct"] == 17.0         # 0.17 -> 17%
    assert d["concentration_70_pct"] == 8.5          # 0.085 -> 8.5%
    assert d["avg_cost"] == 12.3
    assert len(d["trend_30d"]) == 2


def test_cyq_provider_fresh_cache_skips_fetch(conn):
    """30min 内命中缓存：不再调 adapter（用会抛错的 adapter 验证未被调用）。"""
    from data_store import sentiment_repo
    sentiment_repo.set_("cyq_em", {"as_of": "2026-05-29", "concentration_90_pct": 15.0}, "000001.SZ")
    from analysis.institutional.cyq_provider import CyqProvider
    p = CyqProvider(akshare_adapter=_BreakerAdapter("should-not-be-called"))
    res = p.get("000001.SZ")
    assert res.data_status == "fresh"
    assert res.data["concentration_90_pct"] == 15.0


def test_cyq_provider_serves_stale_cache_on_fetch_failure(conn, monkeypatch):
    """缓存过期且取数失败时，降级返回旧缓存(stale)+原因，而非整体 unavailable。"""
    from data_store import sentiment_repo
    sentiment_repo.set_("cyq_em", {"as_of": "2026-05-20", "concentration_90_pct": 9.0}, "000001.SZ")
    from analysis.institutional import cyq_provider
    # 把时钟拨到 TTL 之外，迫使重新取数
    monkeypatch.setattr(cyq_provider.time, "time", lambda: 10 ** 12)
    p = cyq_provider.CyqProvider(
        akshare_adapter=_BreakerAdapter("all sources failed for cyq: timeout"))
    res = p.get("000001.SZ")
    assert res.data_status == "stale"
    assert res.data["concentration_90_pct"] == 9.0
    assert "筹码分布" in res.reason and "超时" in res.reason


def test_survey_provider_reason_explains_backfill(conn):
    from analysis.institutional.survey_provider import SurveyProvider
    res = SurveyProvider(akshare_adapter=_NullAdapter()).get("000001.SZ")
    assert res.data_status == "unavailable"
    assert "sync_institutional_data.py" in res.reason   # 告知如何回填


class _NullAdapter:
    """M1 阶段：所有 akshare 调用直接抛 AkshareUnavailable。"""
    def fetch(self, key, *a, **kw):
        from data_store.akshare_adapter import AkshareUnavailable
        raise AkshareUnavailable("M1: not implemented")


def _stub_registry():
    from analysis.institutional.quant_seat_registry import QuantSeatRegistry
    repo_root = Path(__file__).resolve().parents[1]
    return QuantSeatRegistry(repo_root / "config" / "quant_seats.json")
