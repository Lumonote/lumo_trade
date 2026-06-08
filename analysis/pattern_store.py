"""SQLite repository for pattern fingerprints."""

from __future__ import annotations

import datetime
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pattern_fingerprints (
    stock_code        TEXT PRIMARY KEY,
    stock_name        TEXT,
    market            TEXT,
    industry          TEXT,
    normalized_curve  TEXT NOT NULL,
    mean_slope        REAL NOT NULL,
    latest_close      REAL,
    latest_change_pct REAL,
    snapshot_date     DATE NOT NULL,
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fp_market   ON pattern_fingerprints(market);
CREATE INDEX IF NOT EXISTS idx_fp_industry ON pattern_fingerprints(industry);
CREATE INDEX IF NOT EXISTS idx_fp_date     ON pattern_fingerprints(snapshot_date);

CREATE TABLE IF NOT EXISTS pattern_snapshot_meta (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   DATE NOT NULL,
    status          TEXT NOT NULL,
    total_stocks    INTEGER,
    succeeded       INTEGER,
    failed          INTEGER,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    error_log       TEXT
);

-- 用户手绘 / 个股保存下来的形态，供"历史图形 + 历史图形选股"复用
CREATE TABLE IF NOT EXISTS saved_patterns (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT,
    normalized_curve TEXT NOT NULL,          -- JSON: 归一化后的曲线点
    points           TEXT,                   -- JSON: 原始手绘点（可选，用于重绘画布）
    window_days      INTEGER,
    source           TEXT,                   -- 'draw' / 'stock:<code>'
    tags             TEXT,                   -- JSON: 标签数组（可选）
    query_params     TEXT,                   -- JSON: 保存时的检索条件（top_n/窗口/筛选/阈值…），可一键重跑
    result_snapshot  TEXT,                   -- JSON: 保存时命中的股票快照（可选）
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_saved_created ON saved_patterns(created_at);
"""

# 旧库（无 tags/query_params/result_snapshot 列）升级用：列名 → 类型
_SAVED_PATTERN_COLUMNS = (
    ("tags", "TEXT"),
    ("query_params", "TEXT"),
    ("result_snapshot", "TEXT"),
)


@dataclass
class Fingerprint:
    stock_code: str
    stock_name: str
    market: str
    industry: str
    normalized_curve: List[float]
    mean_slope: float
    latest_close: float
    latest_change_pct: float
    snapshot_date: datetime.date


class PatternStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._migrate_saved_patterns(conn)

    @staticmethod
    def _migrate_saved_patterns(conn: sqlite3.Connection) -> None:
        """给旧版 saved_patterns 补齐新增列（SQLite 无 ADD COLUMN IF NOT EXISTS）。"""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(saved_patterns)")}
        for column, decl in _SAVED_PATTERN_COLUMNS:
            if column not in existing:
                conn.execute(f"ALTER TABLE saved_patterns ADD COLUMN {column} {decl}")

    def upsert_fingerprints(self, fingerprints: Iterable[Fingerprint]) -> int:
        """批量写入指纹，按主键 stock_code 替换。返回写入条数。"""
        records = list(fingerprints)
        if not records:
            return 0
        rows = [
            (
                fp.stock_code,
                fp.stock_name,
                fp.market,
                fp.industry,
                json.dumps(fp.normalized_curve, separators=(",", ":")),
                float(fp.mean_slope),
                float(fp.latest_close),
                float(fp.latest_change_pct),
                fp.snapshot_date.isoformat(),
                datetime.datetime.now().isoformat(timespec="seconds"),
            )
            for fp in records
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO pattern_fingerprints (
                    stock_code, stock_name, market, industry,
                    normalized_curve, mean_slope,
                    latest_close, latest_change_pct,
                    snapshot_date, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def _row_to_fp(self, row: sqlite3.Row) -> Fingerprint:
        return Fingerprint(
            stock_code=row["stock_code"],
            stock_name=row["stock_name"] or "",
            market=row["market"] or "",
            industry=row["industry"] or "",
            normalized_curve=json.loads(row["normalized_curve"]),
            mean_slope=float(row["mean_slope"]),
            latest_close=float(row["latest_close"] or 0.0),
            latest_change_pct=float(row["latest_change_pct"] or 0.0),
            snapshot_date=datetime.date.fromisoformat(row["snapshot_date"]),
        )

    def load_all_fingerprints(self) -> List[Fingerprint]:
        with self._connect() as conn:
            cursor = conn.execute("SELECT * FROM pattern_fingerprints")
            return [self._row_to_fp(row) for row in cursor]

    def load_fingerprint(self, stock_code: str) -> Optional[Fingerprint]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM pattern_fingerprints WHERE stock_code = ?",
                (stock_code,),
            )
            row = cursor.fetchone()
            return self._row_to_fp(row) if row else None

    def search_stocks(self, query: str, limit: int = 10) -> List[dict]:
        """按股票代码、名称、市场或行业搜索指纹库中的股票。"""
        keyword = str(query or "").strip()
        if not keyword:
            return []

        normalized = keyword.upper()
        if normalized.startswith(("SH", "SZ", "BJ")) and len(normalized) >= 8:
            normalized = normalized[2:]
        if normalized.endswith((".SH", ".SZ", ".BJ")):
            normalized = normalized.split(".")[0]

        like_any = f"%{keyword}%"
        code_like_any = f"%{normalized}%"
        code_prefix = f"{normalized}%"
        name_prefix = f"{keyword}%"
        capped_limit = max(1, min(int(limit or 10), 30))

        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT
                    stock_code, stock_name, market, industry,
                    mean_slope, latest_close, latest_change_pct, snapshot_date
                FROM pattern_fingerprints
                WHERE stock_code LIKE ?
                   OR stock_name LIKE ?
                   OR market LIKE ?
                   OR industry LIKE ?
                ORDER BY
                    CASE
                        WHEN stock_code = ? THEN 0
                        WHEN stock_code LIKE ? THEN 1
                        WHEN stock_name = ? THEN 2
                        WHEN stock_name LIKE ? THEN 3
                        WHEN industry LIKE ? THEN 4
                        ELSE 5
                    END,
                    snapshot_date DESC,
                    latest_change_pct DESC
                LIMIT ?
                """,
                (
                    code_like_any,
                    like_any,
                    like_any,
                    like_any,
                    normalized,
                    code_prefix,
                    keyword,
                    name_prefix,
                    like_any,
                    capped_limit,
                ),
            )
            rows = cursor.fetchall()

        return [
            {
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"] or "",
                "market": row["market"] or "",
                "industry": row["industry"] or "",
                "mean_slope": float(row["mean_slope"] or 0.0),
                "latest_close": float(row["latest_close"] or 0.0),
                "latest_change_pct": float(row["latest_change_pct"] or 0.0),
                "snapshot_date": row["snapshot_date"],
            }
            for row in rows
        ]

    def start_snapshot(self, snapshot_date: datetime.date) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pattern_snapshot_meta (
                    snapshot_date, status, started_at
                ) VALUES (?, 'running', ?)
                """,
                (snapshot_date.isoformat(), datetime.datetime.now().isoformat()),
            )
            return int(cursor.lastrowid)

    def finish_snapshot(
        self,
        snapshot_id: int,
        status: str,
        total: int,
        succeeded: int,
        failed: int,
        error_log: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pattern_snapshot_meta SET
                    status = ?, total_stocks = ?, succeeded = ?,
                    failed = ?, finished_at = ?, error_log = ?
                WHERE id = ?
                """,
                (
                    status,
                    total,
                    succeeded,
                    failed,
                    datetime.datetime.now().isoformat(),
                    error_log,
                    snapshot_id,
                ),
            )

    def current_status(self) -> dict:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM pattern_fingerprints"
            ).fetchone()[0]
            last_snap = conn.execute(
                """
                SELECT snapshot_date, status, finished_at
                FROM pattern_snapshot_meta
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        if last_snap and last_snap["status"] == "success":
            return {
                "available": True,
                "total_stocks": int(total),
                "last_snapshot_date": last_snap["snapshot_date"],
                "last_status": last_snap["status"],
                "last_finished_at": last_snap["finished_at"],
            }
        return {
            "available": False,
            "total_stocks": int(total),
            "last_snapshot_date": last_snap["snapshot_date"] if last_snap else None,
            "last_status": last_snap["status"] if last_snap else None,
            "last_finished_at": last_snap["finished_at"] if last_snap else None,
        }

    def successful_snapshot_exists(self, snapshot_date: datetime.date) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM pattern_snapshot_meta
                WHERE snapshot_date = ? AND status = 'success'
                LIMIT 1
                """,
                (snapshot_date.isoformat(),),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # 已保存形态（历史图形）
    # ------------------------------------------------------------------

    @staticmethod
    def _json_or(value: Any, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _row_to_saved(row: sqlite3.Row) -> dict:
        keys = row.keys()
        tags = PatternStore._json_or(row["tags"] if "tags" in keys else None, [])
        query_params = PatternStore._json_or(row["query_params"] if "query_params" in keys else None, None)
        result_snapshot = PatternStore._json_or(row["result_snapshot"] if "result_snapshot" in keys else None, None)
        return {
            "id": int(row["id"]),
            "name": row["name"] or "",
            "normalized_curve": json.loads(row["normalized_curve"]),
            "points": json.loads(row["points"]) if row["points"] else None,
            "window_days": int(row["window_days"]) if row["window_days"] is not None else None,
            "source": row["source"] or "draw",
            "tags": tags if isinstance(tags, list) else [],
            "query_params": query_params if isinstance(query_params, dict) else None,
            "result_snapshot": result_snapshot if isinstance(result_snapshot, list) else None,
            "result_count": len(result_snapshot) if isinstance(result_snapshot, list) else 0,
            "created_at": row["created_at"],
        }

    def save_pattern(
        self,
        name: str,
        normalized_curve: Iterable[float],
        points: Optional[list] = None,
        window_days: Optional[int] = None,
        source: str = "draw",
        tags: Optional[list] = None,
        query_params: Optional[dict] = None,
        result_snapshot: Optional[list] = None,
    ) -> dict:
        """保存一条用户形态，返回落库后的完整记录（含自增 id）。"""
        curve = [float(x) for x in normalized_curve]
        if len(curve) < 2:
            raise ValueError("normalized_curve 至少需要 2 个点")
        curve_json = json.dumps(curve, separators=(",", ":"))
        points_json = json.dumps(points, separators=(",", ":")) if points else None
        tags_json = json.dumps(tags, separators=(",", ":"), ensure_ascii=False) if tags else None
        qp_json = json.dumps(query_params, separators=(",", ":"), ensure_ascii=False) if query_params else None
        snap_json = json.dumps(result_snapshot, separators=(",", ":"), ensure_ascii=False) if result_snapshot else None
        created = datetime.datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO saved_patterns (
                    name, normalized_curve, points, window_days, source,
                    tags, query_params, result_snapshot, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (name or "").strip() or None,
                    curve_json,
                    points_json,
                    int(window_days) if window_days else None,
                    (source or "draw").strip() or "draw",
                    tags_json,
                    qp_json,
                    snap_json,
                    created,
                ),
            )
            pattern_id = int(cursor.lastrowid)
            row = conn.execute(
                "SELECT * FROM saved_patterns WHERE id = ?", (pattern_id,)
            ).fetchone()
        return self._row_to_saved(row)

    def list_saved_patterns(self, limit: int = 50) -> List[dict]:
        capped = max(1, min(int(limit or 50), 200))
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM saved_patterns ORDER BY id DESC LIMIT ?", (capped,)
            )
            return [self._row_to_saved(row) for row in cursor]

    def get_saved_pattern(self, pattern_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM saved_patterns WHERE id = ?", (int(pattern_id),)
            ).fetchone()
            return self._row_to_saved(row) if row else None

    def delete_saved_pattern(self, pattern_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM saved_patterns WHERE id = ?", (int(pattern_id),)
            )
            return cursor.rowcount > 0
