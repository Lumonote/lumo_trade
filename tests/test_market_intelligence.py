import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from webui.services import market_intelligence as market_intelligence_module
from webui.services.market_intelligence import MarketIntelligenceService


class StubMarketIntelligenceService(MarketIntelligenceService):
    def __init__(self):
        super().__init__(ttl_seconds=180)
        self.calls = 0

    def _request_json(self, url, headers=None, timeout=5, trust_env=True):
        self.calls += 1
        if "jin10" in url:
            return {
                "data": [
                    {
                        "id": 1,
                        "time": "10:00:00",
                        "important": True,
                        "data": {
                            "title": "<b>央行发布政策</b>",
                            "source": " 金十 ",
                            "link": "https://example.com/news",
                        },
                    }
                ]
            }
        if "getAllStockChanges" in url:
            # 盘口异动（push2ex）。i 为速度类格式 [幅, 价, 幅]，tm 为 HHMMSS。
            return {
                "data": {
                    "allstock": [
                        {"c": "300001", "n": "测试股", "t": 8201, "i": "0.0589,12.34,0.0589", "tm": 143000},
                    ]
                }
            }
        return {
            "data": {
                "diff": [
                    {
                        "f12": "BK0420",
                        "f14": "银行",
                        "f2": "10.5",
                        "f3": "1.23",
                        "f62": "123456789",
                    }
                ]
            }
        }


def test_load_fetches_and_caches_payload():
    service = StubMarketIntelligenceService()

    first = service.load()
    second = service.load()

    assert first is second
    # 1 金十快讯 + 5 东财 clist（行业 / 概念 / 资金 / 热门股 / 涨幅榜）+ 1 东财盘口异动 = 7 次上游抓取；
    # 第二次 load 命中缓存，不再抓取。
    assert service.calls == 7
    assert first["jinshi"][0]["title"] == "央行发布政策"
    assert first["eastmoney"]["industry_boards"][0]["main_net_inflow_text"] == "1.23亿"
    assert first["eastmoney"]["top_gainers"][0]["change_pct"] == 1.23
    # 盘口异动：类型码映射为中文标签，i 字段启发式解析出价格与涨跌幅，tm 解析为 HH:MM。
    change = first["eastmoney"]["changes"][0]
    assert change["type"] == "火箭发射"
    assert change["change_pct"] == 5.89
    assert change["price"] == 12.34
    assert change["time"] == "14:30"


def test_load_force_refresh_bypasses_cache():
    service = StubMarketIntelligenceService()

    first = service.load()
    second = service.load(force_refresh=True)

    assert first is not second
    assert service.calls == 14


def test_load_captures_source_errors():
    service = MarketIntelligenceService()
    service.fetch_jinshi_flash = lambda limit=12: (_ for _ in ()).throw(RuntimeError("offline"))
    service.fetch_eastmoney_clist = lambda *args, **kwargs: []
    # clist 为空会触发热点回退（人气榜+腾讯）；回退也失败时应捕获错误而非抛出/联网。
    service.fetch_hot_rank = lambda limit=12: (_ for _ in ()).throw(RuntimeError("rank offline"))
    # 板块的腾讯兜底同样不发网(联网机器上不桩会拿到真实板块,断言必挂)
    service.fetch_tencent_boards = lambda board_type, limit=8: []

    payload = service.load()

    assert payload["jinshi"] == []
    assert payload["errors"]["jinshi"] == "offline"
    assert payload["eastmoney"]["industry_boards"] == []
    assert payload["eastmoney"]["hot_stocks"] == []
    assert payload["errors"]["eastmoney_hot_stocks"] == "rank offline"


def test_hot_stocks_falls_back_to_rank_when_clist_empty():
    """clist 返回空（本机 push2 被掐）时，热点应回退到人气榜+腾讯行情。"""
    service = MarketIntelligenceService()
    service.fetch_jinshi_flash = lambda limit=12: []
    service.fetch_xueqiu_hot = lambda limit=12: []
    service.fetch_eastmoney_changes = lambda limit=15: []
    service.fetch_eastmoney_clist = lambda *args, **kwargs: []
    service.fetch_hot_rank = lambda limit=12: [
        {"code": "601991", "name": "大唐发电", "price": 9.18, "change_pct": 9.68,
         "main_net_inflow": None, "main_net_inflow_text": "—", "source": "eastmoney_rank"}
    ]

    payload = service.load()

    assert "eastmoney_hot_stocks" not in payload["errors"]
    hot = payload["eastmoney"]["hot_stocks"]
    assert len(hot) == 1
    assert hot[0]["code"] == "601991"
    assert hot[0]["source"] == "eastmoney_rank"


def test_fetch_eastmoney_clist_bypasses_http_cache():
    """东财热点榜请求要带防缓存参数/头，避免工作台热点模块拿到旧响应。"""
    service = MarketIntelligenceService()
    captured = {}

    def fake_request(url, headers=None, timeout=5, trust_env=True):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["trust_env"] = trust_env
        return {"data": {"diff": []}}

    service._request_json = fake_request
    service.fetch_eastmoney_clist("m:90+t:3", fid="f3", limit=10)

    assert "&_=" in captured["url"]
    assert captured["headers"].get("Cache-Control") == "no-cache"
    assert captured["headers"].get("Pragma") == "no-cache"
    assert captured["trust_env"] is False


def test_load_fetches_ten_concept_boards():
    """工作台「板块热点 / 东财概念」应拉东财概念 Top10。"""
    service = MarketIntelligenceService()
    service.fetch_jinshi_flash = lambda limit=12: []
    service.fetch_ths_flash = lambda limit=15: []
    service.fetch_sina_flash = lambda limit=12: []
    service.fetch_eastmoney_news = lambda limit=15: []
    service.fetch_tencent_boards = lambda board_type, limit=8: []
    service.fetch_hot_rank = lambda limit=12: []
    service.fetch_eastmoney_changes = lambda limit=15: []
    calls = []

    def fake_clist(fs, fid="f3", limit=10):
        calls.append((fs, fid, limit))
        return []

    service.fetch_eastmoney_clist = fake_clist
    service.load()

    assert ("m:90+t:3", "f3", 10) in calls


def test_market_cloud_prefers_tushare_and_converts_units(monkeypatch):
    """大盘云图优先使用 TuShare，并把 TuShare 的千元/万元字段统一成元口径。"""

    class FakePro:
        def trade_cal(self, **kwargs):  # noqa: D401 - 测试桩
            return pd.DataFrame([
                {"cal_date": "20260617", "is_open": 1},
                {"cal_date": "20260618", "is_open": 1},
            ])

        def stock_basic(self, **kwargs):  # noqa: D401 - 测试桩
            return pd.DataFrame([
                {"ts_code": "600519.SH", "symbol": "600519", "name": "贵州茅台", "industry": "白酒", "market": "主板"},
                {"ts_code": "300750.SZ", "symbol": "300750", "name": "宁德时代", "industry": "电池", "market": "创业板"},
                {"ts_code": "900901.SH", "symbol": "900901", "name": "B股样本", "industry": "其他", "market": "主板"},
            ])

        def daily(self, trade_date=None, fields=""):  # noqa: D401 - 测试桩
            assert trade_date == "20260618"
            return pd.DataFrame([
                {"ts_code": "600519.SH", "trade_date": trade_date, "close": 1688.8, "pct_chg": 2.345, "amount": 211619.6},
                {"ts_code": "300750.SZ", "trade_date": trade_date, "close": 388.1, "pct_chg": -1.2, "amount": 12345.0},
                {"ts_code": "900901.SH", "trade_date": trade_date, "close": 1.2, "pct_chg": 9.9, "amount": 999999.0},
            ])

        def daily_basic(self, trade_date=None, fields=""):  # noqa: D401 - 测试桩
            return pd.DataFrame([
                {"ts_code": "600519.SH", "trade_date": trade_date, "turnover_rate": 0.7, "total_mv": 200000000.0, "circ_mv": 190000000.0},
                {"ts_code": "300750.SZ", "trade_date": trade_date, "turnover_rate": 1.5, "total_mv": 80000000.0, "circ_mv": 75000000.0},
            ])

        def moneyflow_dc(self, trade_date=None):  # noqa: D401 - 测试桩
            return pd.DataFrame([
                {"ts_code": "600519.SH", "net_amount": 21161.96},
                {"ts_code": "300750.SZ", "net_amount": -444.4},
            ])

    fake_pro = FakePro()
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token")
    monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=lambda token: fake_pro))
    # 桩数据只有 2 行,压低"全市场覆盖"门槛以命中提前返回分支
    monkeypatch.setattr(market_intelligence_module, "MARKET_CLOUD_FULL_COVERAGE", 1)

    service = MarketIntelligenceService()
    service._request_json = lambda *args, **kwargs: pytest.fail("Eastmoney should not be called when TuShare has rows")
    service.fetch_sina_market_cloud_stocks = lambda *args, **kwargs: pytest.fail("Sina fallback should not be called")

    rows = service.fetch_market_cloud_stocks(limit=100, force_refresh=False)

    assert [row["code"] for row in rows] == ["600519", "300750"]
    first = rows[0]
    assert first["source"] == "tushare_market_cloud"
    assert first["industry"] == "白酒"
    assert first["trade_date"] == "20260618"
    assert first["amount"] == pytest.approx(211619600.0)          # 千元 → 元
    assert first["market_cap"] == pytest.approx(2000000000000.0)  # 万元 → 元
    assert first["main_net_inflow"] == pytest.approx(211619600.0) # 万元 → 元
    assert first["main_net_inflow_text"] == "2.12亿"


def test_market_cloud_force_refresh_prefers_eastmoney_realtime(monkeypatch):
    """手动刷新大盘云图时优先使用东财实时行情，避免继续展示 TuShare 日线收盘数据。"""

    # 东财桩只有 1 行,压低覆盖门槛使其视为"全市场达标"
    monkeypatch.setattr(market_intelligence_module, "MARKET_CLOUD_FULL_COVERAGE", 1)
    service = MarketIntelligenceService()
    service.fetch_tushare_market_cloud_stocks = lambda *args, **kwargs: pytest.fail(
        "manual refresh should prefer realtime Eastmoney rows"
    )
    service.fetch_sina_market_cloud_stocks = lambda *args, **kwargs: pytest.fail(
        "Sina fallback should not be called when Eastmoney has rows"
    )

    def fake_request_json(url, headers=None, timeout=5, trust_env=True):
        assert "push2.eastmoney.com/api/qt/clist/get" in url
        assert trust_env is False
        return {
            "data": {
                "diff": [
                    {
                        "f12": "600519",
                        "f14": "贵州茅台",
                        "f2": 1689.01,
                        "f3": 1.23,
                        "f6": 211619600.0,
                        "f8": 0.72,
                        "f20": 2000000000000.0,
                        "f62": 123456789.0,
                        "f100": "白酒",
                    }
                ]
            }
        }

    service._request_json = fake_request_json

    rows = service.fetch_market_cloud_stocks(limit=100, force_refresh=True)

    assert len(rows) == 1
    assert rows[0]["source"] == "eastmoney_market_cloud"
    assert rows[0]["code"] == "600519"
    assert rows[0]["price"] == 1689.01
    assert rows[0]["change_pct"] == 1.23
    assert rows[0]["industry"] == "白酒"


def test_market_cloud_refresh_falls_through_when_realtime_partial(monkeypatch):
    """东财不可达/部分覆盖时(如仅新浪 ~2400 只老股),继续尝试 TuShare 全市场并采用更全的结果。"""

    monkeypatch.setattr(market_intelligence_module, "MARKET_CLOUD_FULL_COVERAGE", 3)
    service = MarketIntelligenceService()
    partial = [{"code": "600519", "name": "贵州茅台", "source": "eastmoney_market_cloud"}]
    full = [{"code": f"60000{i}", "name": f"股{i}", "source": "tushare_market_cloud"}
            for i in range(3)]
    service.fetch_eastmoney_market_cloud_stocks = lambda *args, **kwargs: list(partial)
    service.fetch_tushare_market_cloud_stocks = lambda *args, **kwargs: list(full)
    service.fetch_sina_market_cloud_stocks = lambda *args, **kwargs: pytest.fail(
        "TuShare 覆盖已达标,不应再落到新浪部分覆盖")

    rows = service.fetch_market_cloud_stocks(limit=100, force_refresh=True)

    assert len(rows) == 3
    assert rows[0]["source"] == "tushare_market_cloud"


def test_market_cloud_keeps_largest_result_when_all_sources_partial(monkeypatch):
    """所有源都低于覆盖门槛时,返回行数最多的一组而非首个非空结果。"""

    monkeypatch.setattr(market_intelligence_module, "MARKET_CLOUD_FULL_COVERAGE", 100)
    service = MarketIntelligenceService()
    service.fetch_eastmoney_market_cloud_stocks = lambda *args, **kwargs: [
        {"code": "600519", "source": "eastmoney_market_cloud"}]
    service.fetch_tushare_market_cloud_stocks = lambda *args, **kwargs: []
    service.fetch_sina_market_cloud_stocks = lambda *args, **kwargs: [
        {"code": "600519", "source": "sina_market_cloud"},
        {"code": "000001", "source": "sina_market_cloud"}]

    rows = service.fetch_market_cloud_stocks(limit=100, force_refresh=True)

    assert len(rows) == 2
    assert rows[0]["source"] == "sina_market_cloud"


def test_market_cloud_trade_date_uses_tushare_history_only(monkeypatch):
    """指定交易日查询应精确读取该日 TuShare 日线，且不混入实时行情回退。"""

    calls = {"daily": [], "trade_cal": 0}

    class FakePro:
        def trade_cal(self, **kwargs):  # noqa: D401 - 测试桩
            calls["trade_cal"] += 1
            pytest.fail("explicit trade_date should not scan recent trade calendar")

        def stock_basic(self, **kwargs):  # noqa: D401 - 测试桩
            return pd.DataFrame([
                {"ts_code": "600519.SH", "symbol": "600519", "name": "贵州茅台", "industry": "白酒", "market": "主板"},
                {"ts_code": "300750.SZ", "symbol": "300750", "name": "宁德时代", "industry": "电池", "market": "创业板"},
            ])

        def daily(self, trade_date=None, fields=""):  # noqa: D401 - 测试桩
            calls["daily"].append(trade_date)
            assert trade_date == "20260617"
            return pd.DataFrame([
                {"ts_code": "600519.SH", "trade_date": trade_date, "close": 1680.0, "pct_chg": -0.56, "amount": 1000.0},
                {"ts_code": "300750.SZ", "trade_date": trade_date, "close": 390.0, "pct_chg": 2.15, "amount": 800.0},
            ])

        def daily_basic(self, trade_date=None, fields=""):  # noqa: D401 - 测试桩
            assert trade_date == "20260617"
            return pd.DataFrame([
                {"ts_code": "600519.SH", "trade_date": trade_date, "turnover_rate": 0.6, "total_mv": 200000000.0},
                {"ts_code": "300750.SZ", "trade_date": trade_date, "turnover_rate": 1.3, "total_mv": 80000000.0},
            ])

        def moneyflow_dc(self, trade_date=None):  # noqa: D401 - 测试桩
            assert trade_date == "20260617"
            return pd.DataFrame([
                {"ts_code": "600519.SH", "net_amount": -1200.0},
                {"ts_code": "300750.SZ", "net_amount": 900.0},
            ])

    fake_pro = FakePro()
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token")
    monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=lambda token: fake_pro))

    service = MarketIntelligenceService()
    service.fetch_eastmoney_market_cloud_stocks = lambda *args, **kwargs: pytest.fail(
        "date query should not call realtime Eastmoney rows"
    )
    service.fetch_sina_market_cloud_stocks = lambda *args, **kwargs: pytest.fail(
        "date query should not call realtime Sina fallback"
    )

    rows = service.fetch_market_cloud_stocks(limit=100, force_refresh=True, trade_date="2026-06-17")

    assert calls["daily"] == ["20260617"]
    assert calls["trade_cal"] == 0
    assert [row["trade_date"] for row in rows] == ["20260617", "20260617"]
    assert {row["source"] for row in rows} == {"tushare_market_cloud"}
    assert {row["code"] for row in rows} == {"600519", "300750"}
