"""新浪指数实时报价解析。字段顺序:名称,当前点位,涨跌额,涨跌幅,成交量(手),成交额(万元)。"""
import pytest

from data_store import index_quote_fetch as q

SAMPLE = (
    'var hq_str_s_sh000001="上证指数,3905.2026,1.4816,0.04,4468958,88342348";\n'
    'var hq_str_s_sz399006="创业板指,3545.58,49.989,1.43,28710547,21464404";\n'
    'var hq_str_s_sh000688="";\n'
)


def test_parse_returns_symbol_keyed_dict():
    out = q.parse_sina_payload(SAMPLE)
    assert set(out) == {"sh000001", "sz399006"}


def test_parse_extracts_fields():
    out = q.parse_sina_payload(SAMPLE)["sz399006"]
    assert out["name"] == "创业板指"
    assert out["close"] == pytest.approx(3545.58)
    assert out["change"] == pytest.approx(49.989)
    assert out["pct_chg"] == pytest.approx(1.43)
    assert out["volume"] == pytest.approx(28710547)


def test_parse_skips_empty_quote():
    assert "sh000688" not in q.parse_sina_payload(SAMPLE)


def test_parse_tolerates_garbage():
    assert q.parse_sina_payload("not a quote") == {}
    assert q.parse_sina_payload("") == {}


def test_parse_skips_malformed_row():
    assert q.parse_sina_payload('var hq_str_s_sh000001="上证指数,abc";') == {}
