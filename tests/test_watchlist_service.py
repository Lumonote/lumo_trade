"""watchlist_service 代码校验 + 行情源市场前缀（含北交所新代码段 920xxx）。"""
from webui.services.watchlist_service import (
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
