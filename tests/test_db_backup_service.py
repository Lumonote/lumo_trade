"""Phase 6 整库备份:导出一致性快照、校验上传库、导入(自动备份 → backup-into-live → migrate)。

撮合不涉及;核心是 SQLite backup API:
  - 导出:live_conn.backup(target_file_conn) → 一致性 .db 快照
  - 导入:校验合法 Kronos 库 → 自动备份当前库 → uploaded.backup(live_conn) 灌库 → migrate(live)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from data_store.schema import migrate


@pytest.fixture
def backup_mod(tmp_path, monkeypatch):
    path = tmp_path / "kronos_live.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)
    getter = lambda: c  # noqa: E731
    from data_store import connection
    monkeypatch.setattr(connection, "get_conn", getter)
    import webui.services.db_backup_service as mod
    monkeypatch.setattr(mod, "get_conn", getter)
    yield mod, c, tmp_path
    c.close()


def _svc(mod, now=datetime(2026, 6, 5, 14, 30, 0)):
    return mod.DbBackupService(now_fn=lambda: now)


def _add_ohlcv(conn, code):
    conn.execute(
        "INSERT INTO ohlcv(code,frequency,ts,open,high,low,close,volume,amount) VALUES(?,?,?,?,?,?,?,?,?)",
        (code, "1d", "2026-06-05", 1, 1, 1, 1, 0, 0),
    )


def _make_kronos_db(path, codes=()):
    d = sqlite3.connect(path, isolation_level=None)
    migrate(d)
    for code in codes:
        _add_ohlcv(d, code)
    d.close()
    return str(path)


def _make_old_db(path):
    """只到 schema v1(仅 ohlcv + schema_version)的旧库,用于验证导入后 migrate 升级。"""
    d = sqlite3.connect(path, isolation_level=None)
    d.executescript(
        """
        CREATE TABLE ohlcv (code TEXT, frequency TEXT, ts TEXT, open REAL, high REAL,
          low REAL, close REAL, volume REAL, amount REAL, PRIMARY KEY(code,frequency,ts));
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT);
        INSERT INTO schema_version(version, applied_at) VALUES(1, '2025-01-01');
        """
    )
    _add_ohlcv(d, "600519")
    d.close()
    return str(path)


# ----------------------------- 导出 -----------------------------

def test_export_creates_consistent_snapshot(backup_mod):
    mod, c, tmp = backup_mod
    _add_ohlcv(c, "600000")
    _add_ohlcv(c, "000001")
    svc = _svc(mod)
    dest = str(tmp / "snap.db")
    out = svc.export_snapshot(dest)
    assert out == dest and Path(dest).exists()
    # 快照内容与活库一致
    snap = sqlite3.connect(dest)
    codes = {r[0] for r in snap.execute("SELECT code FROM ohlcv").fetchall()}
    ver = snap.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    snap.close()
    assert codes == {"600000", "000001"}
    assert ver == migrate(c)  # 与活库同版本


def test_default_export_name_has_timestamp(backup_mod):
    mod, _c, _tmp = backup_mod
    svc = _svc(mod, now=datetime(2026, 6, 5, 14, 30, 0))
    assert svc.default_export_name() == "kronos_backup_20260605_1430.db"


# ----------------------------- 校验 -----------------------------

def test_validate_accepts_kronos_db(backup_mod):
    mod, _c, tmp = backup_mod
    path = _make_kronos_db(tmp / "good.db", codes=["600000"])
    svc = _svc(mod)
    res = svc.validate_db(path)
    assert res["ok"] is True
    assert res["version"] == migrate(_c)
    assert res["tables"]["ohlcv"] is True


def test_validate_rejects_non_sqlite(backup_mod):
    mod, _c, tmp = backup_mod
    bad = tmp / "junk.db"
    bad.write_bytes(b"this is not a sqlite database at all\x00\x01")
    svc = _svc(mod)
    res = svc.validate_db(str(bad))
    assert res["ok"] is False
    assert res["error"]


def test_validate_rejects_db_without_schema_version(backup_mod):
    mod, _c, tmp = backup_mod
    other = tmp / "other.db"
    d = sqlite3.connect(other, isolation_level=None)
    d.execute("CREATE TABLE foo(x INTEGER)")
    d.close()
    svc = _svc(mod)
    res = svc.validate_db(str(other))
    assert res["ok"] is False
    assert "schema_version" in (res["error"] or "")


# ----------------------------- 导入 -----------------------------

def test_import_replaces_live_data_and_autobackups(backup_mod):
    mod, c, tmp = backup_mod
    _add_ohlcv(c, "AAA000")  # 活库原有数据
    uploaded = _make_kronos_db(tmp / "upload.db", codes=["BBB000", "CCC000"])
    svc = _svc(mod)
    res = svc.import_snapshot(uploaded, backup_dir=str(tmp / "backups"))
    assert res["ok"] is True
    # 活库已被替换为上传库内容
    live_codes = {r[0] for r in c.execute("SELECT code FROM ohlcv").fetchall()}
    assert live_codes == {"BBB000", "CCC000"}
    # 导入前自动备份了当前库
    pre = Path(res["pre_import_backup"])
    assert pre.exists()
    pre_conn = sqlite3.connect(pre)
    pre_codes = {r[0] for r in pre_conn.execute("SELECT code FROM ohlcv").fetchall()}
    pre_conn.close()
    assert pre_codes == {"AAA000"}  # 备份保留了被覆盖前的数据
    assert res["final_version"] == migrate(c)


def test_import_rejects_invalid_and_keeps_live_intact(backup_mod):
    mod, c, tmp = backup_mod
    _add_ohlcv(c, "KEEP00")
    bad = tmp / "bad.db"
    bad.write_bytes(b"garbage-not-sqlite")
    svc = _svc(mod)
    res = svc.import_snapshot(str(bad), backup_dir=str(tmp / "backups"))
    assert res["ok"] is False and res["error"]
    # 活库未受影响
    live_codes = {r[0] for r in c.execute("SELECT code FROM ohlcv").fetchall()}
    assert live_codes == {"KEEP00"}


def test_import_migrates_old_backup_to_current_schema(backup_mod):
    mod, c, tmp = backup_mod
    old = _make_old_db(tmp / "old_v1.db")
    svc = _svc(mod)
    res = svc.import_snapshot(old, backup_dir=str(tmp / "backups"))
    assert res["ok"] is True
    assert res["imported_version"] == 1
    assert res["final_version"] == migrate(c)  # 升级到当前 schema
    # 旧库数据保留 + 新版表已建出
    live_codes = {r[0] for r in c.execute("SELECT code FROM ohlcv").fetchall()}
    assert "600519" in live_codes
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "paper_account" in names  # v7 表在 migrate 后建出
