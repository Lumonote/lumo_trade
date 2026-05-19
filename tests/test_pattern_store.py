import datetime
import json
import sqlite3
from pathlib import Path

import pytest

from analysis.pattern_store import (
    PatternStore,
    Fingerprint,
)


def test_init_schema_creates_tables(tmp_db: Path):
    store = PatternStore(tmp_db)
    store.init_schema()
    with sqlite3.connect(tmp_db) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "pattern_fingerprints" in names
    assert "pattern_snapshot_meta" in names


def test_init_schema_is_idempotent(tmp_db: Path):
    store = PatternStore(tmp_db)
    store.init_schema()
    store.init_schema()  # 第二次不应报错


def _make_fp(code: str = "600977", slope: float = 0.02) -> Fingerprint:
    return Fingerprint(
        stock_code=code,
        stock_name="中国电影",
        market="SH",
        industry="影视娱乐",
        normalized_curve=[i / 29 for i in range(30)],
        mean_slope=slope,
        latest_close=10.85,
        latest_change_pct=2.13,
        snapshot_date=datetime.date(2026, 5, 17),
    )


def test_upsert_then_load_all(tmp_db: Path):
    store = PatternStore(tmp_db)
    store.init_schema()
    store.upsert_fingerprints([_make_fp("600977"), _make_fp("000001")])
    rows = store.load_all_fingerprints()
    assert len(rows) == 2
    codes = {row.stock_code for row in rows}
    assert codes == {"600977", "000001"}
    sample = next(row for row in rows if row.stock_code == "600977")
    assert sample.stock_name == "中国电影"
    assert len(sample.normalized_curve) == 30
    assert sample.mean_slope == pytest.approx(0.02)


def test_upsert_replaces_existing(tmp_db: Path):
    store = PatternStore(tmp_db)
    store.init_schema()
    store.upsert_fingerprints([_make_fp("600977", slope=0.01)])
    store.upsert_fingerprints([_make_fp("600977", slope=0.05)])
    rows = store.load_all_fingerprints()
    assert len(rows) == 1
    assert rows[0].mean_slope == pytest.approx(0.05)


def test_load_one_by_code(tmp_db: Path):
    store = PatternStore(tmp_db)
    store.init_schema()
    store.upsert_fingerprints([_make_fp("600977"), _make_fp("000001")])
    fp = store.load_fingerprint("600977")
    assert fp is not None
    assert fp.stock_name == "中国电影"
    assert store.load_fingerprint("999999") is None


def test_start_and_finish_snapshot(tmp_db: Path):
    store = PatternStore(tmp_db)
    store.init_schema()
    snap_id = store.start_snapshot(datetime.date(2026, 5, 18))
    assert snap_id > 0
    store.finish_snapshot(
        snap_id, status="success", total=4500, succeeded=4480, failed=20
    )
    status = store.current_status()
    assert status["available"] is True
    assert status["total_stocks"] >= 0  # 指纹表行数
    assert status["last_snapshot_date"] == "2026-05-18"
    assert status["last_status"] == "success"


def test_status_when_empty(tmp_db: Path):
    store = PatternStore(tmp_db)
    store.init_schema()
    status = store.current_status()
    assert status["available"] is False
    assert status["total_stocks"] == 0
