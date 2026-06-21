"""watchlist_service 代码校验 + 行情源市场前缀（含北交所新代码段 920xxx）。"""
from webui.services.watchlist_service import (
    WatchlistService,
    _VALID_CODE,
    _eastmoney_secid,
    _tencent_symbol,
)


def test_valid_code_accepts_beijing_920():
    """北交所 920xxx 应通过自选代码校验。"""
    assert _VALID_CODE.match("920161")


def test_valid_code_still_accepts_known_segments():
    for code in ("600519", "000001", "300750", "830799", "430047"):
        assert _VALID_CODE.match(code), code


def test_eastmoney_secid_beijing_is_market_0():
    """北交所 920xxx 在东财 secid 中归市场 0（不可因 9 开头被当沪市 1）。"""
    assert _eastmoney_secid("920161") == "0.920161"


def test_eastmoney_secid_shanghai_b_share_is_market_1():
    assert _eastmoney_secid("900001") == "1.900001"
    assert _eastmoney_secid("600519") == "1.600519"


def test_tencent_symbol_beijing_is_bj():
    """北交所 920xxx 腾讯行情前缀须为 bj（不可因 9 开头被当 sh）。"""
    assert _tencent_symbol("920161") == "bj920161"


def test_tencent_symbol_shanghai_b_share_is_sh():
    assert _tencent_symbol("900001") == "sh900001"
    assert _tencent_symbol("600519") == "sh600519"


def test_list_with_quotes_includes_sector_and_return_summary(tmp_path, monkeypatch):
    svc = WatchlistService(tmp_path / "watchlist.json")
    svc.add("600519", "贵州茅台")
    svc.add("000001", "平安银行")
    monkeypatch.setattr(svc, "quotes", lambda codes: {
        "600519": {"name": "贵州茅台", "price": 1800.0, "change_pct": 2.5, "main_net_inflow": 100000000.0},
        "000001": {"name": "平安银行", "price": 12.0, "change_pct": -1.0, "main_net_inflow": -20000000.0},
    })
    monkeypatch.setattr(svc, "_sector_info", lambda code: {
        "600519": {"sector": "白酒", "boards": ["白酒概念"]},
        "000001": {"sector": "银行", "boards": ["银行"]},
    }[code])

    out = svc.list_with_quotes()

    assert out["items"][0]["sector"] == "银行"
    assert out["items"][1]["sector"] == "白酒"
    ret = out["summary"]["return_summary"]
    assert ret["avg_change_pct"] == 0.75
    assert ret["up_count"] == 1
    assert ret["down_count"] == 1
    assert ret["main_net_inflow"] == 80000000.0
    sectors = out["summary"]["sector_summary"]["top_sectors"]
    assert {s["name"] for s in sectors} == {"白酒", "银行"}
