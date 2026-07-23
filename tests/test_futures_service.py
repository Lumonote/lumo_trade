"""股指期货服务纯函数测试（离线,不联网）。

覆盖 :mod:`webui.services.futures_service` 的排名表标准化(999 官方合计行)、
多合约聚合重排名、会员净持仓轧差、多空信号规则与整日 payload 组装。
"""

import pandas as pd
import pytest

from webui.services import futures_service as fs


def _rank_df(with_total: bool = True) -> pd.DataFrame:
    rows = [
        {
            "rank": 1,
            "vol_party_name": "甲期货", "vol": 300, "vol_chg": 30,
            "long_party_name": "甲期货", "long_open_interest": 1000, "long_open_interest_chg": 100,
            "short_party_name": "乙期货", "short_open_interest": 1500, "short_open_interest_chg": -50,
        },
        {
            "rank": 2,
            "vol_party_name": "乙期货", "vol": 200, "vol_chg": -20,
            "long_party_name": "丙期货", "long_open_interest": 800, "long_open_interest_chg": -40,
            "short_party_name": "甲期货", "short_open_interest": 600, "short_open_interest_chg": 60,
        },
    ]
    if with_total:
        rows.append({
            "rank": 999,
            "vol_party_name": "", "vol": 500, "vol_chg": 10,
            "long_party_name": "", "long_open_interest": 1800, "long_open_interest_chg": 60,
            "short_party_name": "", "short_open_interest": 2100, "short_open_interest_chg": 10,
        })
    return pd.DataFrame(rows)


def test_normalize_uses_official_total_row():
    table = fs._normalize_rank_df(_rank_df(with_total=True))
    assert [r["party"] for r in table["long_rows"]] == ["甲期货", "丙期货"]
    assert [r["party"] for r in table["short_rows"]] == ["乙期货", "甲期货"]
    assert table["totals"] == {
        "long": 1800, "long_chg": 60,
        "short": 2100, "short_chg": 10,
        "vol": 500, "vol_chg": 10,
    }


def test_normalize_sums_when_total_row_missing():
    table = fs._normalize_rank_df(_rank_df(with_total=False))
    assert table["totals"]["long"] == 1800
    assert table["totals"]["short"] == 2100
    assert table["totals"]["vol"] == 500
    assert table["totals"]["long_chg"] == 60


def test_normalize_emits_plain_python_ints():
    table = fs._normalize_rank_df(_rank_df())
    oi = table["long_rows"][0]["oi"]
    assert type(oi) is int  # numpy int 会被 _json_response default=str 变成字符串


def test_member_net_rows_offsets_long_short():
    net = fs._member_net_rows(
        [{"party": "甲期货", "oi": 1000, "chg": 100}],
        [{"party": "甲期货", "oi": 600, "chg": 60}, {"party": "乙期货", "oi": 1500, "chg": -50}],
    )
    by_party = {r["party"]: r for r in net}
    assert by_party["甲期货"]["net"] == 400
    assert by_party["甲期货"]["net_chg"] == 40
    assert by_party["乙期货"]["net"] == -1500
    assert net[0]["party"] == "甲期货"  # 净多头在前
    assert net[-1]["party"] == "乙期货"


def test_merge_rows_sums_and_reranks():
    merged = fs._merge_rows([
        [{"party": "甲期货", "oi": 100, "chg": 10}, {"party": "乙期货", "oi": 900, "chg": -5}],
        [{"party": "甲期货", "oi": 850, "chg": 15}],
    ])
    assert merged[0] == {"party": "甲期货", "oi": 950, "chg": 25, "rank": 1}
    assert merged[1]["party"] == "乙期货"
    assert merged[1]["rank"] == 2


@pytest.mark.parametrize(
    "long_chg,short_chg,tag",
    [
        (100, -50, "偏多"),
        (-100, 50, "偏空"),
        (100, 50, "分歧"),
        (-100, -50, "降温"),
        (0, 0, "中性"),
    ],
)
def test_summarize_signal_rules(long_chg, short_chg, tag):
    summary = fs._summarize({
        "long": 2000, "long_chg": long_chg,
        "short": 1000, "short_chg": short_chg,
        "vol": 500, "vol_chg": 0,
    })
    assert summary["signal"] == tag
    assert summary["net"] == 1000
    assert summary["ls_ratio"] == 2.0
    assert "净多头" in summary["signal_reason"]


def test_summarize_handles_zero_short():
    summary = fs._summarize({"long": 100, "long_chg": 0, "short": 0, "short_chg": 0})
    assert summary["ls_ratio"] is None


def test_build_day_payload_aggregates_contracts():
    tables = {
        "IF2609": fs._normalize_rank_df(_rank_df()),
        "IF2612": fs._normalize_rank_df(_rank_df()),
    }
    payload = fs._build_day_payload(tables)
    assert payload["contract_list"] == ["IF2609", "IF2612"]
    agg = payload["aggregate"]
    assert agg["totals"]["long"] == 3600  # 两合约官方合计相加
    assert agg["summary"]["long_total"] == 3600
    assert agg["long_rows"][0]["oi"] == 2000  # 同名会员跨合约求和
    assert {r["party"] for r in agg["net_rows"]} == {"甲期货", "乙期货", "丙期货"}
    single = payload["by_contract"]["IF2609"]
    assert single["summary"]["long_total"] == 1800
    assert single["net_rows"]


def test_position_rank_rejects_unknown_variety():
    result = fs.position_rank("XX")
    assert result["ok"] is False
    assert "XX" in result["error"]


def test_holding_tables_rebuilds_rankings_from_tushare_rows():
    """Tushare fut_holding 兜底:无名次列,按各指标降序重建前20;NaN 列不进对应榜。"""
    records = [
        {"symbol": "IF2609", "broker": "甲期货", "vol": 300, "vol_chg": 30,
         "long_hld": 500, "long_chg": 50, "short_hld": None, "short_chg": None},
        {"symbol": "IF2609", "broker": "乙期货", "vol": 400, "vol_chg": -10,
         "long_hld": 900, "long_chg": -20, "short_hld": 700, "short_chg": 70},
        {"symbol": "IF2612", "broker": "丙期货", "vol": 100, "vol_chg": 5,
         "long_hld": 200, "long_chg": 2, "short_hld": 300, "short_chg": -3},
    ]
    tables = fs._holding_tables(records)
    assert set(tables) == {"IF2609", "IF2612"}
    t9 = tables["IF2609"]
    assert [r["party"] for r in t9["long_rows"]] == ["乙期货", "甲期货"]  # 按持仓降序重排名
    assert t9["long_rows"][0]["rank"] == 1
    assert [r["party"] for r in t9["short_rows"]] == ["乙期货"]  # 甲期货 short NaN 不进空单榜
    assert t9["totals"] == {"long": 1400, "long_chg": 30, "short": 700, "short_chg": 70,
                            "vol": 700, "vol_chg": 20}
    payload = fs._build_day_payload(tables)
    assert payload["aggregate"]["totals"]["long"] == 1600


def test_recent_trade_dates_fallback_shape():
    dates = fs._recent_trade_dates(5)
    assert len(dates) == 5
    assert all(len(d) == 8 and d.isdigit() for d in dates)
