"""整库备份服务(Phase 6)。

整个 SQLite 库的全量导出 / 导入,走 **SQLite backup API**(非磁盘换文件):
  - 导出:`live.backup(target_file)` 生成一致性 .db 快照(并发读也安全)。
  - 导入:校验合法 Kronos 库 → 自动备份当前库 → `uploaded.backup(live)` 灌进活连接 →
    `migrate(live)` 把旧版本升到当前 schema。规避「Robyn 多线程仍持旧文件句柄 +
    WAL 边车」的并发坑(spec §6.4 / §10)。

所有库访问经 get_conn()(线程局部);备份目标/上传库各自用独立的临时连接。
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from data_store.connection import get_conn


class DbBackupService:
    # 校验上传库时检查的表:必须有 schema_version,且至少一张关键数据表
    KEY_TABLES = ("ohlcv", "moneyflow_dc", "schema_version")

    def __init__(self, now_fn=None):
        self._now_fn = now_fn or datetime.now

    # ----------------------------- 工具 -----------------------------

    def _stamp(self) -> str:
        return self._now_fn().strftime("%Y%m%d_%H%M")

    def default_export_name(self) -> str:
        return f"kronos_backup_{self._stamp()}.db"

    # ----------------------------- 导出 -----------------------------

    def export_snapshot(self, dest_path: Optional[str] = None) -> str:
        """用 backup API 生成活库的一致性快照,返回快照文件路径。"""
        if not dest_path:
            dest_path = str(Path(tempfile.gettempdir()) / self.default_export_name())
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(dest_path))
        try:
            get_conn().backup(target)          # source=live → target=文件
        finally:
            target.close()
        return dest_path

    # ----------------------------- 校验 -----------------------------

    def validate_db(self, path) -> dict:
        """只读打开候选库,检查它是合法 Kronos 库。

        返回 {ok, version, tables:{name:bool}, error}。"""
        result = {"ok": False, "version": None, "tables": {}, "error": None}
        p = Path(path)
        if not p.exists():
            result["error"] = "文件不存在"
            return result
        try:
            conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            result["error"] = f"无法打开数据库:{exc}"
            return result
        try:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            for t in self.KEY_TABLES:
                result["tables"][t] = t in names
            if "schema_version" not in names:
                result["error"] = "缺少 schema_version 表,非 Kronos 数据库"
                return result
            if not (result["tables"].get("ohlcv") or result["tables"].get("moneyflow_dc")):
                result["error"] = "缺少关键数据表(ohlcv / moneyflow_dc),非 Kronos 数据库"
                return result
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            result["version"] = int(row[0]) if row and row[0] is not None else 0
            result["ok"] = True
            return result
        except sqlite3.DatabaseError as exc:
            result["error"] = f"非法 SQLite 文件:{exc}"
            return result
        finally:
            conn.close()

    # ----------------------------- 导入 -----------------------------

    def import_snapshot(self, uploaded_path, *, backup_dir: Optional[str] = None) -> dict:
        """校验 → 自动备份当前库 → backup-into-live 灌库 → migrate 升级。返回结果概览。"""
        validation = self.validate_db(uploaded_path)
        if not validation["ok"]:
            return {"ok": False, "error": validation.get("error") or "校验失败",
                    "validation": validation}

        # 导入前自动备份当前库(防导错丢数据)
        if not backup_dir:
            backup_dir = tempfile.gettempdir()
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        pre_backup = str(Path(backup_dir) / f"kronos_backup_before_import_{self._stamp()}.db")
        self.export_snapshot(pre_backup)

        # 灌库:把上传库内容通过 backup API 写进当前活连接(不换文件,WAL 安全)
        live = get_conn()
        uploaded = sqlite3.connect(f"file:{Path(uploaded_path).resolve()}?mode=ro", uri=True)
        try:
            uploaded.backup(live)              # source=上传库 → target=活连接
        finally:
            uploaded.close()

        # 把旧版本备份升级到当前 schema
        from data_store.schema import migrate
        final_version = migrate(live)

        return {
            "ok": True,
            "imported_version": validation.get("version"),
            "final_version": final_version,
            "pre_import_backup": pre_backup,
            "tables": self._table_counts(live),
        }

    def _table_counts(self, conn) -> dict:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        out = {}
        for n in names:
            try:
                out[n] = conn.execute(f"SELECT COUNT(*) FROM \"{n}\"").fetchone()[0]
            except sqlite3.Error:
                out[n] = None
        return out
