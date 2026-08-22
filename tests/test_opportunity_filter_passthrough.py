"""OpportunityFilter.apply_all_filters 的字段透传。

背景(2026-08-17):apply_all_filters 返回的是**新建的 result dict**,候选阶段拿到的
行情/板块字段(change_pct、sector_code、sector_rank…)不在里面就彻底丢失。
opportunity_repo.build_items 正是消费这个 dict 入库,于是 opportunity_item 的
change_pct / sector_code / sector_rank 整列 NULL,桌面「机会数据·股票池」的
「平均涨跌」列长期为空。这里锁住透传行为。
"""
from __future__ import annotations

import pytest

from analysis.opportunity_filter import OpportunityFilter


def _stock_data(**overrides):
    base = {
        "stock_code": "688343",
        "name": "云天励飞",
        "change_pct": 5.2,
        "popularity_score": 91.0,
        "source": "heat",
        "source_detail": "热门行业 软件服务 第2 · 成分第5",
        "sector_name": "软件服务",
        "sector_code": "BK2002",
        "sector_rank": 2,
        "sector_stock_rank": 5,
        "scoring_result": {
            "total_score": 79.3,
            "rating": "B",
            "scores": {"quantitative": 62, "technical": 70},
            "details": {"price_changes": {"change_1d": 1.2}},
        },
    }
    base.update(overrides)
    return base


def test_apply_all_filters_passes_through_quote_and_sector_fields():
    result = OpportunityFilter().apply_all_filters(_stock_data())

    assert result["change_pct"] == pytest.approx(5.2)
    assert result["sector_name"] == "软件服务"
    assert result["sector_code"] == "BK2002"
    assert result["sector_rank"] == 2
    assert result["sector_stock_rank"] == 5
    assert result["popularity_score"] == pytest.approx(91.0)


def test_passed_through_fields_reach_db_items():
    """透传字段一路走到 build_items 的入库投影(股票池「平均涨跌」的数据源)。"""
    from data_store import opportunity_repo

    result = OpportunityFilter().apply_all_filters(_stock_data())
    item = opportunity_repo.build_items([result])[0]

    assert item["code"] == "688343"
    assert item["change_pct"] == pytest.approx(5.2)
    assert item["sector"] == "软件服务"
    assert item["sector_code"] == "BK2002"
    assert item["sector_rank"] == 2


def test_missing_quote_fields_stay_none():
    """候选源本身没有行情字段时不伪造 0(0 会把「无数据」算进平均涨跌)。"""
    data = _stock_data()
    for key in ("change_pct", "sector_rank", "sector_stock_rank", "popularity_score"):
        data.pop(key)
    result = OpportunityFilter().apply_all_filters(data)

    assert result["change_pct"] is None
    assert result["sector_rank"] is None
    assert result["sector_stock_rank"] is None
