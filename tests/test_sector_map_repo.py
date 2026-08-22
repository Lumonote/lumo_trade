"""个股→板块映射:行业取 quant_radar_stock_daily,概念取 hot_sector_* 快照。

覆盖度必须显式返回(spec §4.4):映射不到的股票归「未分类」,绝不静默丢弃。
"""
import sqlite3

import pytest

from data_store import sector_map_repo
from data_store.schema import migrate


@pytest.fixture
def db(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    monkeypatch.setattr(sector_map_repo, "get_conn", lambda: conn)
    yield conn
    conn.close()


def _seed(conn):
    conn.executemany(
        "INSERT INTO quant_radar_stock_daily(trade_date, code, name, industry) VALUES(?,?,?,?)",
        [
            ("2026-08-20", "000001", "平安银行", "银行"),
            ("2026-08-20", "000002", "万科A", "房地产"),
            ("2026-08-19", "000003", "旧数据", "商业连锁"),
            ("2026-08-20", "000004", "无行业", ""),
        ],
    )
    conn.execute(
        "INSERT INTO hot_sector_snapshot(id, created_at, trade_date) "
        "VALUES(1, '2026-08-20T19:00:00', '2026-08-20')")
    conn.executemany(
        "INSERT INTO hot_sector_board(snapshot_id, board_code, board_name, board_type) VALUES(?,?,?,?)",
        [(1, "BK0877", "PCB", "概念"), (1, "BK0475", "银行", "行业")],
    )
    conn.executemany(
        "INSERT INTO hot_sector_stock(snapshot_id, board_code, code, name) VALUES(?,?,?,?)",
        [(1, "BK0877", "000001", "平安银行"), (1, "BK0475", "000001", "平安银行")],
    )


def test_bare_code_strips_suffix_and_prefix():
    assert sector_map_repo.bare_code("000001.SZ") == "000001"
    assert sector_map_repo.bare_code("sz000001") == "000001"
    assert sector_map_repo.bare_code("600000") == "600000"
    assert sector_map_repo.bare_code(None) == ""


def test_build_map_uses_latest_industry(db):
    _seed(db)
    mapping = sector_map_repo.build_map(as_of="2026-08-20")
    assert ("银行", "行业") in mapping["000001"]
    assert ("房地产", "行业") in mapping["000002"]


def test_build_map_falls_back_to_earlier_industry(db):
    """as_of 当天没有该股的行情行时,回看更早的行业分类(行业不会天天变)。"""
    _seed(db)
    mapping = sector_map_repo.build_map(as_of="2026-08-20")
    assert ("商业连锁", "行业") in mapping["000003"]


def test_build_map_adds_concept_boards(db):
    _seed(db)
    mapping = sector_map_repo.build_map(as_of="2026-08-20")
    assert ("PCB", "概念") in mapping["000001"]


def test_build_map_skips_blank_industry(db):
    _seed(db)
    mapping = sector_map_repo.build_map(as_of="2026-08-20")
    assert "000004" not in mapping


def test_build_map_does_not_duplicate_industry_from_both_sources(db):
    """东财「银行」行业板块与 quant_radar「银行」行业重名,只应留一条。"""
    _seed(db)
    industries = [s for s in mapping_of(db) if s[1] == "行业"]
    assert industries.count(("银行", "行业")) == 1


def mapping_of(conn):
    return sector_map_repo.build_map(as_of="2026-08-20")["000001"]


def test_coverage_reports_ratio_and_unmapped(db):
    _seed(db)
    mapping = sector_map_repo.build_map(as_of="2026-08-20")
    cov = sector_map_repo.coverage(mapping, ["000001", "000002", "000004", "999999"])
    assert cov["mapped"] == 2
    assert cov["unmapped"] == 2
    assert cov["ratio"] == pytest.approx(0.5)


def test_coverage_empty_universe_is_zero_not_crash(db):
    assert sector_map_repo.coverage({}, [])["ratio"] == 0.0
