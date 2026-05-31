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
    # 1 金十快讯 + 5 东财 clist（行业 / 概念 / 资金 / 热门股 / 涨幅榜）= 6 次上游抓取；
    # 第二次 load 命中缓存，不再抓取。
    assert service.calls == 6
    assert first["jinshi"][0]["title"] == "央行发布政策"
    assert first["eastmoney"]["industry_boards"][0]["main_net_inflow_text"] == "1.23亿"
    assert first["eastmoney"]["top_gainers"][0]["change_pct"] == 1.23


def test_load_captures_source_errors():
    service = MarketIntelligenceService()
    service.fetch_jinshi_flash = lambda limit=12: (_ for _ in ()).throw(RuntimeError("offline"))
    service.fetch_eastmoney_clist = lambda *args, **kwargs: []

    payload = service.load()

    assert payload["jinshi"] == []
    assert payload["errors"]["jinshi"] == "offline"
    assert payload["eastmoney"]["industry_boards"] == []
