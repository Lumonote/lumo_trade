import datetime
from unittest.mock import patch, MagicMock

import pytest

from scripts.build_pattern_fingerprints import (
    build_fingerprint_for_stock,
    parse_market_from_secid,
)
from scripts.build_pattern_fingerprints import fetch_recent_klines


def test_parse_market_sh():
    assert parse_market_from_secid("1.600977") == "SH"
    assert parse_market_from_secid("0.000001") == "SZ"
    assert parse_market_from_secid("1.688981") == "SH"
    assert parse_market_from_secid("0.300750") == "SZ"


def test_build_fingerprint_for_stock_basic():
    klines = [
        f"2026-04-{day:02d},10.0,{10.0 + day * 0.1},11.0,9.5,1000,10000,0.5,1.2,0.1,3.0"
        for day in range(1, 31)
    ]
    fp = build_fingerprint_for_stock(
        stock_code="600977",
        stock_name="中国电影",
        market="SH",
        industry="影视娱乐",
        klines_raw=klines,
        snapshot_date=datetime.date(2026, 5, 18),
    )
    assert fp is not None
    assert fp.stock_code == "600977"
    assert len(fp.normalized_curve) == 30
    assert fp.normalized_curve[0] == pytest.approx(0.0, abs=0.01)
    assert fp.normalized_curve[-1] == pytest.approx(1.0, abs=0.01)
    assert fp.mean_slope > 0
    assert fp.latest_close == pytest.approx(13.0, abs=0.01)


def test_build_fingerprint_returns_none_for_constant_price():
    klines = [
        f"2026-04-{day:02d},10.0,10.0,10.0,10.0,0,0,0,0,0,0"
        for day in range(1, 31)
    ]
    fp = build_fingerprint_for_stock(
        stock_code="STOP", stock_name="停牌", market="SH",
        industry="", klines_raw=klines,
        snapshot_date=datetime.date(2026, 5, 18),
    )
    assert fp is None


def test_build_fingerprint_returns_none_for_insufficient_data():
    klines = [
        f"2026-04-{day:02d},10.0,11.0,11.5,9.8,1000,10000,0.5,1.0,0.1,1.0"
        for day in range(1, 5)  # 仅 4 条
    ]
    fp = build_fingerprint_for_stock(
        stock_code="600977", stock_name="X", market="SH",
        industry="", klines_raw=klines,
        snapshot_date=datetime.date(2026, 5, 18),
    )
    assert fp is None


def test_fetch_recent_klines_parses_response():
    fake_payload = {
        "data": {
            "code": "600977",
            "name": "中国电影",
            "klines": [
                "2026-04-01,10.0,10.5,10.6,9.9,1000,10000,0.5,1.0,0.1,1.0",
                "2026-04-02,10.5,10.8,10.9,10.4,1100,11000,0.5,1.0,0.1,1.0",
            ],
        }
    }
    with patch("scripts.build_pattern_fingerprints._http_get_json", return_value=fake_payload):
        name, klines = fetch_recent_klines("1.600977", limit=30)
    assert name == "中国电影"
    assert len(klines) == 2
    assert klines[0].startswith("2026-04-01")


def test_fetch_recent_klines_returns_empty_on_missing_data():
    with patch("scripts.build_pattern_fingerprints._http_get_json", return_value={}):
        name, klines = fetch_recent_klines("1.600977", limit=30)
    assert name == ""
    assert klines == []


def test_list_all_secids_parses_clist():
    fake_payload = {
        "data": {
            "total": 3,
            "diff": [
                {"f12": "600977", "f13": 1, "f14": "中国电影", "f100": "影视娱乐"},
                {"f12": "000001", "f13": 0, "f14": "平安银行", "f100": "银行"},
                {"f12": "688981", "f13": 1, "f14": "中芯国际", "f100": "半导体"},
            ],
        }
    }
    with patch(
        "scripts.build_pattern_fingerprints._http_get_json",
        return_value=fake_payload,
    ):
        from scripts.build_pattern_fingerprints import list_all_secids
        stocks = list_all_secids()
    assert len(stocks) == 3
    codes = {s["stock_code"] for s in stocks}
    assert codes == {"600977", "000001", "688981"}
    sh_row = next(s for s in stocks if s["stock_code"] == "600977")
    assert sh_row["secid"] == "1.600977"
    assert sh_row["market"] == "SH"
    sz_row = next(s for s in stocks if s["stock_code"] == "000001")
    assert sz_row["secid"] == "0.000001"
    assert sz_row["market"] == "SZ"
