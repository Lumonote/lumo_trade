"""雪球热榜数据源（market_intelligence.fetch_xueqiu_hot）+ load() 装配与降级。"""
from __future__ import annotations

import sys
import types

import pandas as pd

from webui.services.market_intelligence import MarketIntelligenceService


def test_fetch_xueqiu_hot_parses(monkeypatch):
    fake = types.ModuleType("akshare")
    fake.stock_hot_follow_xq = lambda symbol="最热门": pd.DataFrame({
        "股票代码": ["SH600519", "SZ000001"],
        "股票简称": ["贵州茅台", "平安银行"],
        "关注": [123456, 7890],
        "最新价": [1680.0, 11.2],
    })
    monkeypatch.setitem(sys.modules, "akshare", fake)

    rows = MarketIntelligenceService().fetch_xueqiu_hot(limit=5)
    assert rows[0]["code"] == "600519"      # SH/SZ 前缀去除，留 6 位
    assert rows[0]["name"] == "贵州茅台"
    assert rows[0]["follow"] == 123456
    assert rows[0]["follow_text"]            # 万/亿格式化非空
    assert rows[0]["price"] == 1680.0
    assert rows[0]["source"] == "xueqiu"


def test_load_includes_xueqiu_hot_and_degrades(monkeypatch):
    svc = MarketIntelligenceService()
    # 全程无网络：所有 fetch_* 打桩；雪球抛错验证降级
    monkeypatch.setattr(svc, "fetch_jinshi_flash", lambda limit=12: [])
    monkeypatch.setattr(svc, "fetch_eastmoney_clist", lambda *a, **k: [])

    def boom(limit=12):
        raise RuntimeError("xueqiu blocked")

    monkeypatch.setattr(svc, "fetch_xueqiu_hot", boom)

    payload = svc.load()
    assert "xueqiu_hot" in payload
    assert payload["xueqiu_hot"] == []               # 失败降级为空面板
    assert "xueqiu_hot" in payload.get("errors", {})  # 真实原因被记录
