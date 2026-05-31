"""批量分析完成后抽取「通过」个股，供前端完成卡直达个股分析（spec 模块 B）。"""
from __future__ import annotations

import pandas as pd

from webui.core import _passed_stocks_from_result_df


def _df(rows):
    return pd.DataFrame(rows)


def test_extracts_passed_stocks_with_code_score_rating():
    df = _df([
        {"股票代码": "600519", "综合评分": 88.5, "评级": "A", "过滤状态": "通过"},
        {"股票代码": "000001", "综合评分": 72.0, "评级": "B", "过滤状态": "通过"},
        {"股票代码": "300750", "综合评分": 40.0, "评级": "C", "过滤状态": "未通过"},
    ])
    stocks, passed_count = _passed_stocks_from_result_df(df)
    assert passed_count == 2
    assert [s["code"] for s in stocks] == ["600519", "000001"]
    assert stocks[0]["score"] == 88.5
    assert stocks[0]["rating"] == "A"
    assert "300750" not in {s["code"] for s in stocks}  # 未通过不进入直达列表


def test_limit_caps_list_but_count_is_total():
    rows = [
        {"股票代码": str(600000 + i), "综合评分": float(i), "评级": "A", "过滤状态": "通过"}
        for i in range(60)
    ]
    stocks, passed_count = _passed_stocks_from_result_df(_df(rows), limit=50)
    assert passed_count == 60
    assert len(stocks) == 50


def test_empty_or_missing_columns_returns_empty():
    assert _passed_stocks_from_result_df(None) == ([], 0)
    assert _passed_stocks_from_result_df(pd.DataFrame()) == ([], 0)
    # 无「过滤状态」列时，全部按 code 抽取
    df = _df([{"股票代码": "600519", "综合评分": 88.5, "评级": "A"}])
    stocks, passed_count = _passed_stocks_from_result_df(df)
    assert passed_count == 1 and stocks[0]["code"] == "600519"


def test_nan_rating_becomes_none():
    df = _df([{"股票代码": "600519", "综合评分": 88.5, "评级": float("nan"), "过滤状态": "通过"}])
    stocks, _ = _passed_stocks_from_result_df(df)
    assert stocks[0]["rating"] is None
