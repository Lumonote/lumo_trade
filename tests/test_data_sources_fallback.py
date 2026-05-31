"""E7（spec §6.8）：直连 HTTP 兜底（情绪/新闻/行情）。

`analysis/data_sources_fallback.DirectHTTPFallback`：0-key、可注入 `fetch`、
TTL 缓存、多源按可用性顺序回退。仅作 investor_sentiment /
news_sentiment_collector 主路径失败时的兜底，降低「数据不足」。

各端点响应样本结构：
- Tencent gtimg `qt.gtimg.cn/q=`：`~` 分隔，[1]名 [3]现价 [4]昨收 [30]时间 [31]涨跌额 [32]涨跌幅%。
- Sina sinajs `hq.sinajs.cn/list=`：`,` 分隔，[0]名 [1]开 [2]昨收 [3]现价。
- 金十 `flash-api.jin10.com/get_flash_list`：{status,data:[{id,time,important,data:{title,content,source,...}}]}。
- 东财快讯 `newsapi.eastmoney.com/kuaixun/v1/...`：JSONP `var ajaxResult={...LivesList:[{title,url_w,newsid}]}`。
"""
from __future__ import annotations

import pytest

from analysis.data_sources_fallback import DirectHTTPFallback


# ---- 各端点响应样本 --------------------------------------------------------
GTIMG_INDEX = (
    'v_sh000001="1~上证指数~000001~4068.57~4098.64~4110.52~731597710~0~0~0.00~0~'
    '0.00~0~0.00~0~0.00~0~0.00~0~0.00~0~0.00~0~0.00~0~0.00~0~0.00~0~~'
    '20260529161415~-30.07~-0.73~4112.96~4055.89~";'
)
GTIMG_STOCK = (
    'v_sz000001="51~平安银行~000001~10.93~10.66~10.65~1399368~844000~555368~10.92~'
    '1232~10.91~2827~10.90~3482~10.89~2171~10.88~1479~10.93~12481~10.94~6046~10.95~'
    '11971~10.96~9878~10.97~15224~~20260529161454~0.27~2.53~10.93~10.62~";'
)
SINA_INDEX = (
    'var hq_str_sh000001="上证指数,4110.5212,4098.6358,4068.5691,4112.9553,'
    '4055.8861,0,0,731597710,1532067352982,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
    '0,2026-05-29,15:30:39,00,";'
)
JIN10_FLASH = (
    '{"status":200,"message":"OK","data":['
    '{"id":"20260531172555462800","time":"2026-05-31 17:25:55","type":0,"important":0,'
    '"data":{"pic":"","title":"","source":"央视新闻",'
    '"content":"【伊朗议会议长：不会轻易批准任何协议】金十数据5月31日讯，伊朗议会议长表示……",'
    '"source_link":"https://www.jin10.com/example1"}},'
    '{"id":"20260531172000111111","time":"2026-05-31 17:20:00","type":0,"important":1,'
    '"data":{"pic":"","title":"美联储官员发表鹰派讲话","source":"金十数据",'
    '"content":"详情……","link":"https://www.jin10.com/example2"}},'
    '{"id":"20260531171000222222","time":"2026-05-31 17:10:00","type":0,"important":0,'
    '"data":{"pic":"","title":"","source":"","content":""}}'
    ']}'
)
JIN10_EMPTY = '{"status":200,"message":"OK","data":[]}'
EM_KUAIXUN = (
    'var ajaxResult={"rc":1,"me":"","LivesList":['
    '{"sort":"1780218762082388","id":"202605313755182388","newsid":"202605313755182388",'
    '"url_w":"http://finance.eastmoney.com/a/202605313755182388.html",'
    '"url_m":"https://wap.eastmoney.com/a/202605313755182388.html",'
    '"url_unique":"http://finance.eastmoney.com/a/202605313755182388.html",'
    '"title":"以色列称将在博福尔城堡部署部队 建立黎巴嫩南部安全区","simtitle":"以色列称……"}'
    ']}'
)


def _fake_fetch(mapping: dict, calls: list | None = None):
    """按 url 子串映射到预设响应；映射缺失或值为 None → 模拟该源失败。"""
    def fetch(url, *, headers=None, timeout=6, encoding=None):
        if calls is not None:
            calls.append(url)
        for key, val in mapping.items():
            if key in url:
                return val
        return None
    return fetch


# ---- 行情兜底：Tencent gtimg → Sina sinajs ---------------------------------
def test_fetch_index_quote_parses_tencent_gtimg():
    fb = DirectHTTPFallback(fetch=_fake_fetch({"gtimg": GTIMG_INDEX}))
    q = fb.fetch_index_quote("sh000001")
    assert q is not None
    assert q["current"] == pytest.approx(4068.57)
    assert q["prev_close"] == pytest.approx(4098.64)
    assert q["change_pct"] == pytest.approx(-0.73, abs=0.01)
    assert q["name"] == "上证指数"
    assert q["source"] == "tencent"


def test_fetch_index_quote_falls_back_to_sina_when_tencent_unavailable():
    fb = DirectHTTPFallback(fetch=_fake_fetch({"gtimg": None, "sinajs": SINA_INDEX}))
    q = fb.fetch_index_quote("sh000001")
    assert q is not None
    assert q["current"] == pytest.approx(4068.5691)
    assert q["change_pct"] == pytest.approx(-0.73, abs=0.01)
    assert q["source"] == "sina"


def test_fetch_index_quote_returns_none_when_all_sources_fail():
    fb = DirectHTTPFallback(fetch=_fake_fetch({}))
    assert fb.fetch_index_quote("sh000001") is None


def test_fetch_stock_quote_parses_tencent_gtimg():
    fb = DirectHTTPFallback(fetch=_fake_fetch({"gtimg": GTIMG_STOCK}))
    q = fb.fetch_stock_quote("000001")
    assert q is not None
    assert q["current"] == pytest.approx(10.93)
    assert q["prev_close"] == pytest.approx(10.66)
    assert q["change_pct"] == pytest.approx(2.53, abs=0.01)
    assert q["name"] == "平安银行"
    assert q["source"] == "tencent"


def test_index_quote_cached_within_ttl():
    calls: list = []
    fb = DirectHTTPFallback(fetch=_fake_fetch({"gtimg": GTIMG_INDEX}, calls))
    a = fb.fetch_index_quote("sh000001")
    b = fb.fetch_index_quote("sh000001")
    assert a == b
    assert len(calls) == 1  # 第二次命中缓存，不再发起请求


# ---- 快讯兜底：金十 → 东财快讯 ----------------------------------------------
def test_fetch_flash_news_parses_jinshi():
    fb = DirectHTTPFallback(fetch=_fake_fetch({"jin10": JIN10_FLASH}))
    items = fb.fetch_flash_news(limit=10)
    assert len(items) == 2  # 第三条 title/content 均空 → 跳过
    titles = [it["title"] for it in items]
    assert any("伊朗议会议长" in t for t in titles)  # title 空时回落用 content
    assert any("美联储" in t for t in titles)
    assert all(it["title"] for it in items)         # 不留空标题
    assert items[0]["origin"] == "jin10"
    assert items[0]["source"]                        # 来源透出


def test_fetch_flash_news_falls_back_to_eastmoney():
    fb = DirectHTTPFallback(fetch=_fake_fetch({"jin10": JIN10_EMPTY, "eastmoney": EM_KUAIXUN}))
    items = fb.fetch_flash_news(limit=10)
    assert len(items) >= 1
    assert any("以色列" in it["title"] for it in items)
    assert items[0]["origin"] == "eastmoney"
    assert items[0]["url"].startswith("http")


def test_fetch_flash_news_empty_when_all_sources_fail():
    fb = DirectHTTPFallback(fetch=_fake_fetch({}))
    assert fb.fetch_flash_news() == []


# ---- 接入：investor_sentiment 大盘行情兜底 ----------------------------------
class _StubQuoteFallback:
    """指数兜底桩：记录调用并返回可用涨跌。"""

    def __init__(self):
        self.index_calls: list = []

    def fetch_index_quote(self, code):
        self.index_calls.append(code)
        return {"current": 3000.0, "change_pct": 1.23, "name": f"指数{code}", "source": "tencent"}


def test_overall_market_sentiment_uses_direct_http_when_primary_sources_fail(monkeypatch):
    """Eastmoney 与 Sina 备用都取不到指数涨跌时，get_overall_market_sentiment
    应调用 DirectHTTPFallback.fetch_index_quote 补齐，而非返回「数据不足」。"""
    import analysis.investor_sentiment as ism

    class _EmptyResp:
        status_code = 200

        def json(self):
            return {}

    monkeypatch.setattr(ism.requests, "get", lambda *a, **k: _EmptyResp())

    analyzer = ism.InvestorSentimentAnalyzer("000001")
    monkeypatch.setattr(analyzer.global_cache, "get_overall_market", lambda: None)
    monkeypatch.setattr(analyzer.global_cache, "set_overall_market", lambda *a, **k: None)
    monkeypatch.setattr(analyzer, "_get_index_from_sina", lambda code: None)
    stub = _StubQuoteFallback()
    analyzer._http_fallback = stub

    result = analyzer.get_overall_market_sentiment()

    assert stub.index_calls, "主源失败后应调用直连兜底补齐缺失指数"
    assert result["overall"] != "数据不足"
    assert isinstance(result["primary_change_pct"], (int, float))


# ---- 接入：news_sentiment_collector 个股新闻全空 → 市场快讯兜底 --------------
class _StubFlashFallback:
    """快讯兜底桩：记录调用并返回可用市场快讯。"""

    def __init__(self):
        self.flash_calls: list = []

    def fetch_flash_news(self, limit=20):
        self.flash_calls.append(limit)
        return [
            {"title": "央行开展6000亿元逆回购操作", "time": "2026-05-31 10:00:00",
             "source": "金十数据", "url": "https://www.jin10.com/example", "origin": "jin10"},
            {"title": "三大指数集体高开 半导体板块领涨", "time": "2026-05-31 09:31:00",
             "source": "东方财富", "url": "https://finance.eastmoney.com/a/x.html", "origin": "eastmoney"},
        ]


def test_get_latest_news_uses_flash_fallback_when_stock_sources_empty(monkeypatch):
    """个股新闻三级降级（Playwright/爬虫/同花顺）全空时，get_latest_news 应调用
    DirectHTTPFallback.fetch_flash_news 兜底市场快讯（标注 scope='market'），
    而非返回空列表。"""
    from analysis.news_sentiment_collector import NewsSentimentCollector

    collector = NewsSentimentCollector("000001")
    collector.disable_playwright_news = True
    monkeypatch.setattr(collector, "_scrape_news", lambda limit=20: [])
    monkeypatch.setattr(collector, "_fallback_news_tonghuashun", lambda limit=20: [])
    stub = _StubFlashFallback()
    collector._http_fallback = stub

    news = collector.get_latest_news(limit=10)

    assert stub.flash_calls, "个股三源全空后应调用直连快讯兜底"
    assert news, "应以市场快讯兜底，而非返回空列表"
    assert all(it.get("scope") == "market" for it in news), "兜底项需标注 scope='market' 以区分个股新闻"
    assert all(it.get("title") and it.get("sentiment") for it in news), "需补齐标题与情感字段"
    assert all(it.get("date") for it in news), "需归一化快讯时间为日期"


def test_get_latest_news_skips_flash_when_stock_news_present(monkeypatch):
    """个股新闻可得时，不应触发市场快讯兜底，避免无谓直连请求。"""
    from analysis.news_sentiment_collector import NewsSentimentCollector

    collector = NewsSentimentCollector("000001")
    collector.disable_playwright_news = True
    monkeypatch.setattr(
        collector, "_scrape_news",
        lambda limit=20: [{"title": "平安银行发布季报", "date": "2026-05-30",
                           "source": "新浪财经", "url": "http://x", "summary": "季报",
                           "sentiment": "中性"}],
    )
    stub = _StubFlashFallback()
    collector._http_fallback = stub

    news = collector.get_latest_news(limit=10)

    assert not stub.flash_calls, "个股新闻可得时不应调用快讯兜底"
    assert all(it.get("scope") != "market" for it in news), "个股新闻不应被标注为市场快讯"


# ---- 接入：板块情绪回退用直连个股行情取真实涨跌 ------------------------------
class _StubStockQuoteFallback:
    """个股行情兜底桩：记录调用并返回真实涨跌。"""

    def __init__(self):
        self.stock_calls: list = []

    def fetch_stock_quote(self, code):
        self.stock_calls.append(code)
        return {"current": 12.34, "prev_close": 12.0, "change_pct": 2.83,
                "name": "测试股份", "source": "tencent"}


def test_sector_fallback_uses_direct_http_stock_quote_for_real_change(monkeypatch):
    """板块主源失败回退时，_get_sector_info_fallback 应调用 fetch_stock_quote
    取真实个股涨跌幅并据此算情绪分，替代硬编码 change_pct='N/A' / sentiment_score=50。"""
    import analysis.investor_sentiment as ism

    class _EmptyResp:
        status_code = 200
        text = ""

        def json(self):
            return {}

    monkeypatch.setattr(ism.requests, "get", lambda *a, **k: _EmptyResp())

    analyzer = ism.InvestorSentimentAnalyzer("000001")
    monkeypatch.setattr(
        analyzer, "get_overall_market_sentiment",
        lambda: {"avg_change_pct": 0, "sentiment_score": 50, "overall": "中性", "emotion": "neutral"},
    )
    stub = _StubStockQuoteFallback()
    analyzer._http_fallback = stub

    result = analyzer._get_sector_info_fallback()

    assert stub.stock_calls, "板块回退时应调用直连个股行情兜底"
    ss = result["sector_sentiment"]
    assert ss["change_pct"] == "2.83", "应透出真实个股涨跌幅，而非 N/A"
    expected = analyzer._calculate_sentiment_from_change("2.83")
    assert ss["sentiment_score"] == expected, "情绪分应据真实涨跌计算，而非硬编码 50"
