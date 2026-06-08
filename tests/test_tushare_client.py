"""tushare_client.to_ts_code 交易所后缀推导（含北交所新代码段 920xxx）。"""
from data_store.tushare_client import to_ts_code


def test_to_ts_code_beijing_920_segment():
    """北交所 920xxx 新代码段须映射到 .BJ（不可因 9 开头被误判为沪市 B 股）。"""
    assert to_ts_code("920161") == "920161.BJ"
    assert to_ts_code("920000") == "920000.BJ"


def test_to_ts_code_shanghai_b_share_900_segment():
    """沪市 B 股 900xxx 仍映射到 .SH（与 920 北交所区分开）。"""
    assert to_ts_code("900001") == "900001.SH"


def test_to_ts_code_other_segments_unchanged():
    assert to_ts_code("600519") == "600519.SH"
    assert to_ts_code("000001") == "000001.SZ"
    assert to_ts_code("300750") == "300750.SZ"
    assert to_ts_code("830799") == "830799.BJ"
    assert to_ts_code("430047") == "430047.BJ"


def test_to_ts_code_accepts_already_suffixed():
    assert to_ts_code("600519.SH") == "600519.SH"
    assert to_ts_code("920161.BJ") == "920161.BJ"


# ---------- verify_token:离线可验边界(空 / 占位符 直接判失败,不联网) ----------

def test_verify_token_rejects_empty():
    from data_store import tushare_client
    res = tushare_client.verify_token("")
    assert res["ok"] is False
    assert res["error"]


def test_verify_token_rejects_placeholder():
    from data_store import tushare_client
    res = tushare_client.verify_token("your_tushare_token_here")
    assert res["ok"] is False
    assert res["error"]
