"""板块×日序列聚合。aggregate_day 是纯函数,离线可测。

金额单位归一(万元)、top_n=0 过滤、相对全市场超额三件事最容易出错,重点覆盖。
"""
import sqlite3

import pytest

from analysis import sector_series
from data_store.schema import migrate

MAPPING = {
    "000001": [("银行", "行业")],
    "000002": [("房地产", "行业"), ("PCB", "概念")],
    "000003": [("银行", "行业")],
}


def _row(code, pct, net, rate, unit="万元"):
    return {
        "trade_date": "2026-08-20", "ts_code": f"{code}.SZ", "top_n": 0,
        "pct_change": pct, "net_amount": net, "net_amount_rate": rate,
        "amount_unit": unit,
    }


def test_aggregate_day_groups_by_sector_and_type():
    out = sector_series.aggregate_day(
        [_row("000001", 1.0, 100, 5.0), _row("000002", 2.0, 200, 4.0)], MAPPING)
    keys = {(r["sector"], r["sector_type"]) for r in out}
    assert keys == {("银行", "行业"), ("房地产", "行业"), ("PCB", "概念")}


def test_aggregate_day_computes_member_count_and_mean():
    out = {r["sector"]: r for r in sector_series.aggregate_day(
        [_row("000001", 1.0, 100, 5.0), _row("000003", 3.0, 300, 5.0)], MAPPING)}
    assert out["银行"]["member_count"] == 2
    assert out["银行"]["pct_chg_mean"] == pytest.approx(2.0)
    assert out["银行"]["net_amount"] == pytest.approx(400.0)


def test_aggregate_day_normalizes_yuan_to_wan():
    """amount_unit='元' 的行必须乘 1e-4 归一,否则单个板块净流入会虚高一万倍。"""
    out = {r["sector"]: r for r in sector_series.aggregate_day(
        [_row("000001", 1.0, 1_000_000, 5.0, unit="元")], MAPPING)}
    assert out["银行"]["net_amount"] == pytest.approx(100.0)


def test_aggregate_day_treats_missing_unit_as_wan():
    out = {r["sector"]: r for r in sector_series.aggregate_day(
        [_row("000001", 1.0, 100, 5.0, unit=None)], MAPPING)}
    assert out["银行"]["net_amount"] == pytest.approx(100.0)


def test_aggregate_day_skips_non_zero_top_n():
    rows = [_row("000001", 1.0, 100, 5.0)]
    rows[0]["top_n"] = 50
    assert sector_series.aggregate_day(rows, MAPPING) == []


def test_aggregate_day_breadth_is_up_ratio():
    out = {r["sector"]: r for r in sector_series.aggregate_day(
        [_row("000001", 1.0, 10, 1.0), _row("000003", -2.0, -10, -1.0)], MAPPING)}
    assert out["银行"]["breadth"] == pytest.approx(0.5)


def test_aggregate_day_excess_is_vs_whole_market_mean():
    """全市场等权 = (1+9)/2 = 5;银行板块 1.0 → 超额 -4.0 个百分点。"""
    out = {r["sector"]: r for r in sector_series.aggregate_day(
        [_row("000001", 1.0, 10, 1.0), _row("000002", 9.0, 10, 1.0)], MAPPING)}
    assert out["银行"]["excess_vs_market"] == pytest.approx(-4.0)


def test_aggregate_day_amount_median_derived_from_rate():
    """成交额 = 净流入 / (净流入率/100)。100 / 0.05 = 2000 万元。"""
    out = {r["sector"]: r for r in sector_series.aggregate_day(
        [_row("000001", 1.0, 100, 5.0)], MAPPING)}
    assert out["银行"]["amount_median"] == pytest.approx(2000.0)


def test_aggregate_day_amount_median_none_when_rate_near_zero():
    out = {r["sector"]: r for r in sector_series.aggregate_day(
        [_row("000001", 1.0, 100, 0.0)], MAPPING)}
    assert out["银行"]["amount_median"] is None


def test_aggregate_day_seat_counts_summed_per_sector():
    out = {r["sector"]: r for r in sector_series.aggregate_day(
        [_row("000001", 1.0, 10, 1.0), _row("000003", 1.0, 10, 1.0)], MAPPING,
        seat_counts={"000001": 2, "000003": 1})}
    assert out["银行"]["seat_count"] == 3


def test_aggregate_day_ignores_unmapped_codes():
    out = sector_series.aggregate_day([_row("999999", 1.0, 10, 1.0)], MAPPING)
    assert out == []


def test_aggregate_day_empty_rows():
    assert sector_series.aggregate_day([], MAPPING) == []


@pytest.fixture
def db(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    monkeypatch.setattr(sector_series, "get_conn", lambda: conn)
    yield conn
    conn.close()


def test_upsert_and_load_series_roundtrip(db):
    records = [
        {"trade_date": "2026-08-19", "sector": "银行", "sector_type": "行业",
         "member_count": 2, "net_amount": 100.0, "net_rate_median": 1.0,
         "pct_chg_mean": 1.0, "breadth": 0.5, "amount_median": 500.0,
         "excess_vs_market": 0.2, "seat_count": 0},
        {"trade_date": "2026-08-20", "sector": "银行", "sector_type": "行业",
         "member_count": 2, "net_amount": 200.0, "net_rate_median": 2.0,
         "pct_chg_mean": 2.0, "breadth": 1.0, "amount_median": 600.0,
         "excess_vs_market": 0.4, "seat_count": 1},
    ]
    assert sector_series.upsert_days(records) == 2
    series = sector_series.load_series("银行", "行业", end_date="2026-08-20")
    assert [r["trade_date"] for r in series] == ["2026-08-19", "2026-08-20"]
    assert series[-1]["net_amount"] == pytest.approx(200.0)


def test_upsert_overwrites_same_key(db):
    rec = {"trade_date": "2026-08-20", "sector": "银行", "sector_type": "行业",
           "member_count": 2, "net_amount": 100.0, "net_rate_median": 1.0,
           "pct_chg_mean": 1.0, "breadth": 0.5, "amount_median": 500.0,
           "excess_vs_market": 0.2, "seat_count": 0}
    sector_series.upsert_days([rec])
    sector_series.upsert_days([{**rec, "net_amount": 999.0}])
    series = sector_series.load_series("银行", "行业")
    assert len(series) == 1
    assert series[0]["net_amount"] == pytest.approx(999.0)


def test_load_all_series_filters_small_sectors(db):
    sector_series.upsert_days([
        {"trade_date": "2026-08-20", "sector": "大板块", "sector_type": "行业",
         "member_count": 30, "net_amount": 1.0, "net_rate_median": 0.0,
         "pct_chg_mean": 0.0, "breadth": 0.5, "amount_median": 1.0,
         "excess_vs_market": 0.0, "seat_count": 0},
        {"trade_date": "2026-08-20", "sector": "小板块", "sector_type": "概念",
         "member_count": 2, "net_amount": 1.0, "net_rate_median": 0.0,
         "pct_chg_mean": 0.0, "breadth": 0.5, "amount_median": 1.0,
         "excess_vs_market": 0.0, "seat_count": 0},
    ])
    out = sector_series.load_all_series(end_date="2026-08-20", min_members=5)
    assert ("大板块", "行业") in out
    assert ("小板块", "概念") not in out


def test_provisional_flag_persisted(db):
    rec = {"trade_date": "2026-08-20", "sector": "银行", "sector_type": "行业",
           "member_count": 2, "net_amount": 100.0, "net_rate_median": 1.0,
           "pct_chg_mean": 1.0, "breadth": 0.5, "amount_median": 500.0,
           "excess_vs_market": 0.2, "seat_count": 0}
    sector_series.upsert_days([rec], provisional=True)
    assert sector_series.load_series("银行", "行业")[0]["provisional"] == 1
    sector_series.upsert_days([rec], provisional=False)
    assert sector_series.load_series("银行", "行业")[0]["provisional"] == 0
