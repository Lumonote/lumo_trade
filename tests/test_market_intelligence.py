from webui.services.market_intelligence import MarketIntelligenceService


class StubMarketIntelligenceService(MarketIntelligenceService):
    def __init__(self):
        super().__init__(ttl_seconds=180)
        self.calls = 0

    def _request_json(self, url, headers=None, timeout=5):
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


def test_load_captures_source_errors():
    service = MarketIntelligenceService()
    service.fetch_jinshi_flash = lambda limit=12: (_ for _ in ()).throw(RuntimeError("offline"))
    service.fetch_eastmoney_clist = lambda *args, **kwargs: []
    # clist 为空会触发热点回退（人气榜+腾讯）；回退也失败时应捕获错误而非抛出/联网。
    service.fetch_hot_rank = lambda limit=12: (_ for _ in ()).throw(RuntimeError("rank offline"))

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

