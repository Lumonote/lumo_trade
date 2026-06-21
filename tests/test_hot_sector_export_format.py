"""导出 Excel 可读化 + 去重 + 实时回填 + 逐股评分。

热门板块快照导出此前直接把 DB 行(英文列名 + ``raw_json``/``detail_json``/``extra_json``
整段 JSON)倒进 Excel,且出现重复列、空数据、缺评分。这里覆盖:
- JSON 平铺 + 表头中文化(``_dataframe_for_export``);
- 冗余列去重(代码/日期变体、主力净流入数值/文本孪生列);
- 实时报价回填空值 + 逐股评分关联(``_enrich_stock_frame``)。
"""

import json

import pandas as pd

from data_store import hot_sector_repo as repo


def test_stocks_sheet_chinese_headers_and_dedup():
    df = pd.DataFrame([{
        "snapshot_id": 4, "board_code": "BK0674", "code": "688478",
        "name": "晶升股份", "stock_rank": 1, "price": 0, "change_pct": 0,
        "main_net_inflow": None, "main_net_inflow_text": "—", "lhb_reason": "涨幅达15%",
        "raw_json": json.dumps(
            {"trade_date": "20260618", "ts_code": "BK0674.DC",
             "con_code": "688478.SH", "name": "晶升股份"},
            ensure_ascii=False),
    }])
    cols = list(repo._dataframe_for_export(df).columns)
    assert "股票代码" in cols and "名称" in cols and "上榜原因" in cols
    assert "raw_json" not in cols
    # 用户反馈的「重复」:代码/日期变体平铺列应被丢弃
    assert "TS代码" not in cols and "成分TS代码" not in cols and "交易日" not in cols
    # 主力净流入 文本孪生列丢弃,仅保留数值列
    assert "主力净流入" not in cols and "主力净流入(元)" in cols
    assert cols.count("名称") == 1


def test_boards_sheet_keeps_moneyflow_breakdown_drops_dups():
    df = pd.DataFrame([{
        "snapshot_id": 4, "board_code": "BK1625", "board_name": "钨",
        "board_type": "行业", "board_rank": 1, "change_pct": 8.17, "main_net_inflow": 9.8e8,
        "raw_json": json.dumps(
            {"trade_date": "20260618", "content_type": "行业", "ts_code": "BK1625.DC",
             "name": "钨", "pct_change": 8.17, "net_amount": 9.8e8, "close": 12598.21,
             "buy_elg_amount": 1.26e9, "buy_sm_amount_stock": "中钨高新", "_chg": 8.17},
            ensure_ascii=False),
    }])
    cols = list(repo._dataframe_for_export(df).columns)
    assert "超大单买入(元)" in cols and "板块点位" in cols and "小单买入代表股" in cols
    # 与既有列重复/内部派生键均不平铺
    for gone in ("TS代码", "内容类型", "板块涨跌幅(%)", "净额(元)", "交易日", "_chg"):
        assert gone not in cols, gone


def test_relations_detail_json_flattened_and_internal_keys_skipped():
    df = pd.DataFrame([{
        "id": 1, "snapshot_id": 4, "board_code": "BK1136", "code": "688662",
        "relation_type": "dragon_tiger", "trade_date": "2026-06-12", "amount": 3.5e8,
        "detail_json": json.dumps(
            {"code": "688662", "name": "富信科技", "l_buy": 1.0e9,
             "net_amount": 3.5e8, "reason": "涨幅偏离", "_chg": 8.1},
            ensure_ascii=False),
    }])
    out = repo._dataframe_for_export(df)
    cols = list(out.columns)
    assert "detail_json" not in cols
    assert "关联类型" in cols and "金额(元)" in cols
    assert "龙虎榜买入额(元)" in cols and "净额(元)" in cols and "上榜原因" in cols
    assert "名称" in cols and "_chg" not in cols
    assert cols.count("股票代码") == 1 and cols.count("交易日") == 1
    # 枚举值中文化:dragon_tiger → 龙虎榜
    assert out.iloc[0]["关联类型"] == "龙虎榜"


def test_enum_values_translated_to_chinese():
    df = pd.DataFrame([
        {"snapshot_id": 4, "source": "sector_hot_tushare",
         "relation_type": "dragon_tiger", "related_table": "dragon_tiger_list"},
        {"snapshot_id": 5, "source": "sector_hot",
         "relation_type": "dragon_tiger", "related_table": "dragon_tiger_list"},
        # 未在映射表中的值原样保留
        {"snapshot_id": 6, "source": "unknown_src",
         "relation_type": "dragon_tiger", "related_table": "dragon_tiger_list"},
    ])
    out = repo._dataframe_for_export(df)
    assert list(out["数据源"]) == ["热门板块 Tushare", "热门板块 东财", "unknown_src"]
    assert set(out["关联类型"]) == {"龙虎榜"}
    assert set(out["关联表"]) == {"龙虎榜单"}


def test_enrich_fills_quotes_only_when_blank():
    df = pd.DataFrame([
        {"code": "688478", "price": 0, "change_pct": 0, "main_net_inflow": None},
        {"code": "300861", "price": 12.3, "change_pct": 5.1, "main_net_inflow": 1.2e7},
    ])
    quotes = {
        "688478": {"price": 99.5, "change_pct": 14.98, "main_net_inflow": 1.77e8},
        "300861": {"price": 88.0, "change_pct": -1.0, "main_net_inflow": 2.0e7},
    }
    out = repo._enrich_stock_frame(df, scores=None, quotes=quotes)
    # 空值被回填
    assert out.iloc[0]["price"] == 99.5 and out.iloc[0]["change_pct"] == 14.98
    assert out.iloc[0]["main_net_inflow"] == 1.77e8
    # 已有非空值不被覆盖
    assert out.iloc[1]["price"] == 12.3 and out.iloc[1]["main_net_inflow"] == 1.2e7


def test_enrich_adds_scores_and_marks_unscored():
    df = pd.DataFrame([{"code": "688478", "name": "晶升股份"},
                       {"code": "300861", "name": "美畅股份"}])
    scores = {"688478": {
        "total_score": 87.17, "rating": "S", "sector_stock_rank": 1,
        "scores_json": json.dumps({"quantitative": 73.2, "technical": 58.0, "momentum": 76.0}),
        "signals_json": json.dumps({"chase": 0.0, "rsi": 45.8370, "day_change": 9.99}),
    }}
    out = repo._enrich_stock_frame(df, scores=scores, quotes=None)
    assert out.iloc[0]["综合评分"] == 87.17 and out.iloc[0]["评级"] == "S"
    assert out.iloc[0]["量化分"] == 73.2 and out.iloc[0]["RSI"] == 45.84
    assert out.iloc[0]["当日涨幅(%)"] == 9.99 and out.iloc[0]["板块内评分排名"] == 1
    # 未命中评分 → 评级标「未评分」,综合评分留空(NaN,Excel 中显示为空)
    assert out.iloc[1]["评级"] == "未评分" and pd.isna(out.iloc[1]["综合评分"])


def test_empty_inputs_are_safe_and_still_chinese():
    assert repo._dataframe_for_export(pd.DataFrame()).empty
    out = repo._dataframe_for_export(pd.DataFrame(columns=["snapshot_id", "raw_json"]))
    assert "raw_json" not in out.columns and "快照编号" in out.columns
    # enrich 对空/无 code 列安全
    assert repo._enrich_stock_frame(pd.DataFrame(), scores={}, quotes={}).empty
