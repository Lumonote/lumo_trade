# 形态画板搜股 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在首页加入"形态搜股"全屏 Modal，用户手绘曲线或选择股票代码，从 SQLite 指纹库中检索全 A 股近 30 日形态最相似的 Top-30 股票，匹配采用 Pearson 相关 (0.7) + 趋势斜率 (0.3) 加权。

**Architecture:** 后端定时拉取全市场 30 日 K 线，计算归一化指纹存入 SQLite (`data/pattern_fingerprints.db`)。前端 Modal 通过 Canvas 收集 30 点曲线，POST 到 Flask 路由 `/api/pattern-search/match`，后端 NumPy 向量化匹配后返回 Top-N。点击结果在 Modal 内 Plotly 绘制对比图。

**Tech Stack:** Python 3 + SQLite3 (stdlib) + NumPy + Flask + HTML5 Canvas + Plotly.js + Eastmoney push2 API（复用 `_fetch_eastmoney_kline` 模式）

---

## File Structure

**新增**:
- `analysis/pattern_matcher.py` — 匹配核心（curve 规范化、Pearson、slope、Top-N 排序）
- `analysis/pattern_store.py` — SQLite 仓储层（schema 初始化、读写指纹与快照元数据）
- `scripts/build_pattern_fingerprints.py` — 全市场指纹构建 CLI
- `tests/__init__.py`
- `tests/test_pattern_matcher.py` — 算法单元测试
- `tests/test_pattern_store.py` — 仓储层单元测试
- `tests/test_build_fingerprints.py` — 指纹构建集成测试（mock）

**修改**:
- `webui/app.py` — 新增 4 个 API 路由 + 1 个后台任务函数 + 列入 `_module_health`
- `webui/templates/stock_analysis_home.html` — 顶部按钮 + Modal HTML/CSS + JS 逻辑

**新建数据文件**（运行时自动）:
- `data/pattern_fingerprints.db` — SQLite 库

---

## Task 1: 准备测试基础设施

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 创建 tests 包**

写入 `tests/__init__.py`（空文件）：

```python
```

- [ ] **Step 2: 写入 conftest.py 提供 tmp_db fixture**

写入 `tests/conftest.py`:

```python
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """提供临时 SQLite 数据库路径，测试结束自动清理。"""
    return tmp_path / "test_fingerprints.db"
```

- [ ] **Step 3: 验证 pytest 可用**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/ -v --collect-only`
Expected: `collected 0 items` 且无错误

- [ ] **Step 4: 提交**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "test: 形态搜股 - 准备测试基础设施"
```

---

## Task 2: 实现曲线归一化 + 斜率计算

**Files:**
- Create: `analysis/pattern_matcher.py`
- Test: `tests/test_pattern_matcher.py`

- [ ] **Step 1: 写入失败测试 - normalize_curve**

写入 `tests/test_pattern_matcher.py`:

```python
import math
import numpy as np
import pytest

from analysis.pattern_matcher import (
    normalize_curve,
    linear_slope,
    pearson_similarity,
    score_pair,
    SLOPE_NORM,
)


def test_normalize_curve_basic():
    raw = [10.0, 11.0, 12.0, 13.0, 14.0]
    norm = normalize_curve(raw)
    assert norm[0] == pytest.approx(0.0)
    assert norm[-1] == pytest.approx(1.0)
    assert len(norm) == len(raw)


def test_normalize_curve_constant_returns_none():
    """停牌期间所有价格相同，归一化无意义，返回 None。"""
    assert normalize_curve([10.0, 10.0, 10.0]) is None


def test_normalize_curve_resamples_to_target_length():
    """输入任意长度，按 x 等分采样到目标长度。"""
    raw = list(range(60))  # 60 个递增点
    norm = normalize_curve(raw, target_length=30)
    assert len(norm) == 30
    assert norm[0] == pytest.approx(0.0, abs=0.05)
    assert norm[-1] == pytest.approx(1.0, abs=0.05)
```

- [ ] **Step 2: 验证测试失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py::test_normalize_curve_basic -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'analysis.pattern_matcher'"

- [ ] **Step 3: 写入 normalize_curve 最小实现**

写入 `analysis/pattern_matcher.py`:

```python
"""Pattern matching engine for the canvas-based stock search feature.

Algorithm: pearson correlation (0.7) + slope match (0.3) on
30-point normalized close-price curves.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

TARGET_LENGTH = 30
SLOPE_NORM = 0.05  # 归一化曲线上 30 日斜率经验上界
SHAPE_WEIGHT = 0.7
SLOPE_WEIGHT = 0.3


def normalize_curve(
    raw: Sequence[float],
    target_length: int = TARGET_LENGTH,
) -> Optional[List[float]]:
    """将任意长度的价格序列重采样到 target_length 点并归一化到 [0,1]。

    停牌或全平输入（max == min）返回 None。
    """
    if not raw or len(raw) < 2:
        return None

    arr = np.asarray(raw, dtype=float)
    if not np.isfinite(arr).all():
        return None

    if len(arr) != target_length:
        # 按 x 轴等分插值重采样
        x_src = np.linspace(0.0, 1.0, num=len(arr))
        x_dst = np.linspace(0.0, 1.0, num=target_length)
        arr = np.interp(x_dst, x_src, arr)

    span = float(arr.max() - arr.min())
    if span <= 1e-9:
        return None

    norm = (arr - arr.min()) / span
    return norm.tolist()
```

- [ ] **Step 4: 运行 normalize_curve 测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py -k normalize -v`
Expected: 3 passed

- [ ] **Step 5: 追加 linear_slope 失败测试**

追加到 `tests/test_pattern_matcher.py`:

```python
def test_linear_slope_increasing():
    """完全线性递增曲线，归一化后斜率约 1/(N-1)。"""
    norm = normalize_curve(list(range(30)))
    slope = linear_slope(norm)
    assert slope == pytest.approx(1.0 / 29, abs=0.005)


def test_linear_slope_flat_after_normalize_is_zero():
    norm = [0.5] * 30
    assert linear_slope(norm) == pytest.approx(0.0)


def test_linear_slope_decreasing():
    norm = normalize_curve(list(range(30, 0, -1)))
    slope = linear_slope(norm)
    assert slope < 0
```

- [ ] **Step 6: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py -k slope -v`
Expected: FAIL with "ImportError: cannot import name 'linear_slope'"

- [ ] **Step 7: 实现 linear_slope**

追加到 `analysis/pattern_matcher.py`:

```python
def linear_slope(curve: Sequence[float]) -> float:
    """归一化曲线的线性回归斜率（每点一个 x 单位）。"""
    arr = np.asarray(curve, dtype=float)
    n = len(arr)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    # slope = cov(x, y) / var(x)
    x_mean = x.mean()
    y_mean = arr.mean()
    denom = float(((x - x_mean) ** 2).sum())
    if denom <= 1e-12:
        return 0.0
    return float(((x - x_mean) * (arr - y_mean)).sum() / denom)
```

- [ ] **Step 8: 运行测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py -v`
Expected: 6 passed

- [ ] **Step 9: 提交**

```bash
git add analysis/pattern_matcher.py tests/test_pattern_matcher.py
git commit -m "feat: 形态搜股 - 添加曲线归一化与斜率计算"
```

---

## Task 3: 实现 Pearson 相似度与综合评分

**Files:**
- Modify: `analysis/pattern_matcher.py`
- Modify: `tests/test_pattern_matcher.py`

- [ ] **Step 1: 写入 Pearson 失败测试**

追加到 `tests/test_pattern_matcher.py`:

```python
def test_pearson_identical_curves():
    norm = normalize_curve(list(range(30)))
    assert pearson_similarity(norm, norm) == pytest.approx(1.0)


def test_pearson_opposite_curves():
    asc = normalize_curve(list(range(30)))
    desc = normalize_curve(list(range(30, 0, -1)))
    assert pearson_similarity(asc, desc) == pytest.approx(-1.0)


def test_pearson_zero_variance_returns_zero():
    flat = [0.5] * 30
    asc = normalize_curve(list(range(30)))
    assert pearson_similarity(asc, flat) == 0.0
```

- [ ] **Step 2: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py -k pearson -v`
Expected: FAIL with "ImportError: cannot import name 'pearson_similarity'"

- [ ] **Step 3: 实现 pearson_similarity**

追加到 `analysis/pattern_matcher.py`:

```python
def pearson_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Pearson 相关系数，输入长度不等返回 0。"""
    arr_a = np.asarray(a, dtype=float)
    arr_b = np.asarray(b, dtype=float)
    if arr_a.shape != arr_b.shape or arr_a.size < 2:
        return 0.0

    std_a = arr_a.std()
    std_b = arr_b.std()
    if std_a <= 1e-9 or std_b <= 1e-9:
        return 0.0

    return float(((arr_a - arr_a.mean()) * (arr_b - arr_b.mean())).mean() / (std_a * std_b))
```

- [ ] **Step 4: 运行 Pearson 测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py -k pearson -v`
Expected: 3 passed

- [ ] **Step 5: 写入 score_pair 测试**

追加到 `tests/test_pattern_matcher.py`:

```python
def test_score_pair_identical_yields_one():
    user_curve = normalize_curve(list(range(30)))
    fp_curve = list(user_curve)
    user_slope = linear_slope(user_curve)
    fp_slope = user_slope
    breakdown = score_pair(user_curve, user_slope, fp_curve, fp_slope)
    assert breakdown["score"] == pytest.approx(1.0)
    assert breakdown["shape_sim"] == pytest.approx(1.0)
    assert breakdown["slope_sim"] == pytest.approx(1.0)


def test_score_pair_opposite_shape_yields_low():
    asc = normalize_curve(list(range(30)))
    desc = normalize_curve(list(range(30, 0, -1)))
    breakdown = score_pair(asc, linear_slope(asc), desc, linear_slope(desc))
    assert breakdown["score"] < 0.05  # 形态反向 + 斜率反向, 双零
    assert breakdown["shape_sim"] == 0.0  # 负相关被裁剪为 0


def test_score_pair_slope_diff_penalized():
    asc = normalize_curve(list(range(30)))
    # 同形态但人为构造差异较大的斜率
    breakdown = score_pair(
        asc, linear_slope(asc), asc, linear_slope(asc) + SLOPE_NORM * 2
    )
    assert breakdown["slope_sim"] == 0.0
    # 形态完全一致 → 0.7 * 1 + 0.3 * 0 = 0.7
    assert breakdown["score"] == pytest.approx(0.7)
```

- [ ] **Step 6: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py -k score_pair -v`
Expected: FAIL with "ImportError: cannot import name 'score_pair'"

- [ ] **Step 7: 实现 score_pair**

追加到 `analysis/pattern_matcher.py`:

```python
def score_pair(
    user_curve: Sequence[float],
    user_slope: float,
    fp_curve: Sequence[float],
    fp_slope: float,
) -> dict:
    """计算单对曲线的相似度，返回 {score, shape_sim, slope_sim}。"""
    pearson_r = pearson_similarity(user_curve, fp_curve)
    shape_sim = max(0.0, pearson_r)  # 仅保留正相关
    slope_diff = abs(user_slope - fp_slope)
    slope_sim = max(0.0, 1.0 - slope_diff / SLOPE_NORM)
    score = SHAPE_WEIGHT * shape_sim + SLOPE_WEIGHT * slope_sim
    return {
        "score": round(score, 4),
        "shape_sim": round(shape_sim, 4),
        "slope_sim": round(slope_sim, 4),
    }
```

- [ ] **Step 8: 运行所有测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py -v`
Expected: 9 passed

- [ ] **Step 9: 提交**

```bash
git add analysis/pattern_matcher.py tests/test_pattern_matcher.py
git commit -m "feat: 形态搜股 - 添加 Pearson 与综合评分函数"
```

---

## Task 4: 实现 SQLite 仓储层

**Files:**
- Create: `analysis/pattern_store.py`
- Create: `tests/test_pattern_store.py`

- [ ] **Step 1: 写入失败测试 - init_schema**

写入 `tests/test_pattern_store.py`:

```python
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
```

- [ ] **Step 2: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_store.py -k init_schema -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'analysis.pattern_store'"

- [ ] **Step 3: 实现 PatternStore 与 schema**

写入 `analysis/pattern_store.py`:

```python
"""SQLite repository for pattern fingerprints."""

from __future__ import annotations

import datetime
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional


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
"""


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
```

- [ ] **Step 4: 运行 init_schema 测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_store.py -k init_schema -v`
Expected: 2 passed

- [ ] **Step 5: 写入 upsert/read 失败测试**

追加到 `tests/test_pattern_store.py`:

```python
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
```

- [ ] **Step 6: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_store.py -k upsert -v`
Expected: FAIL with "AttributeError: 'PatternStore' object has no attribute 'upsert_fingerprints'"

- [ ] **Step 7: 实现 upsert/load**

追加到 `analysis/pattern_store.py`:

```python
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
```

- [ ] **Step 8: 运行测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_store.py -v`
Expected: 5 passed

- [ ] **Step 9: 写入 status / snapshot meta 测试**

追加到 `tests/test_pattern_store.py`:

```python
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
```

- [ ] **Step 10: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_store.py -k snapshot -v`
Expected: FAIL

- [ ] **Step 11: 实现 snapshot/status 函数**

追加到 `analysis/pattern_store.py`:

```python
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
        if total > 0 and last_snap:
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
```

- [ ] **Step 12: 运行全部仓储测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_store.py -v`
Expected: 7 passed

- [ ] **Step 13: 提交**

```bash
git add analysis/pattern_store.py tests/test_pattern_store.py
git commit -m "feat: 形态搜股 - 实现 SQLite 指纹仓储"
```

---

## Task 5: 实现匹配引擎 search()

**Files:**
- Modify: `analysis/pattern_matcher.py`
- Modify: `tests/test_pattern_matcher.py`

- [ ] **Step 1: 写入 search 失败测试**

追加到 `tests/test_pattern_matcher.py`:

```python
import datetime
import math

from analysis.pattern_matcher import search_similar
from analysis.pattern_store import Fingerprint, PatternStore


def _fp(code: str, name: str, market: str, curve: list, slope: float) -> Fingerprint:
    return Fingerprint(
        stock_code=code,
        stock_name=name,
        market=market,
        industry="测试行业",
        normalized_curve=curve,
        mean_slope=slope,
        latest_close=10.0,
        latest_change_pct=1.0,
        snapshot_date=datetime.date(2026, 5, 17),
    )


def test_search_returns_sorted_top_n(tmp_db):
    store = PatternStore(tmp_db)
    store.init_schema()
    asc = normalize_curve(list(range(30)))
    desc = normalize_curve(list(range(30, 0, -1)))
    asc_slope = linear_slope(asc)
    desc_slope = linear_slope(desc)
    store.upsert_fingerprints([
        _fp("AAA", "上涨股", "SH", asc, asc_slope),
        _fp("BBB", "下跌股", "SZ", desc, desc_slope),
    ])
    results = search_similar(store, user_curve=asc, top_n=10)
    assert len(results) >= 1
    assert results[0]["stock_code"] == "AAA"
    assert results[0]["score"] == pytest.approx(1.0)


def test_search_filters_st_stocks(tmp_db):
    store = PatternStore(tmp_db)
    store.init_schema()
    asc = normalize_curve(list(range(30)))
    slope = linear_slope(asc)
    store.upsert_fingerprints([
        _fp("AAA", "上涨股", "SH", asc, slope),
        _fp("BBB", "ST退市", "SH", asc, slope),
        _fp("CCC", "*ST警告", "SH", asc, slope),
        _fp("DDD", "中弘退", "SZ", asc, slope),
    ])
    results = search_similar(store, user_curve=asc, top_n=10, exclude_st=True)
    codes = {row["stock_code"] for row in results}
    assert "AAA" in codes
    assert "BBB" not in codes
    assert "CCC" not in codes
    assert "DDD" not in codes


def test_search_market_filter(tmp_db):
    store = PatternStore(tmp_db)
    store.init_schema()
    asc = normalize_curve(list(range(30)))
    slope = linear_slope(asc)
    store.upsert_fingerprints([
        _fp("600001", "沪市", "SH", asc, slope),
        _fp("000001", "深市", "SZ", asc, slope),
    ])
    results = search_similar(
        store, user_curve=asc, top_n=10, markets=["SZ"]
    )
    codes = {row["stock_code"] for row in results}
    assert codes == {"000001"}


def test_search_top_n_limit(tmp_db):
    store = PatternStore(tmp_db)
    store.init_schema()
    asc = normalize_curve(list(range(30)))
    slope = linear_slope(asc)
    fps = [_fp(f"{i:06d}", f"股{i}", "SH", asc, slope) for i in range(50)]
    store.upsert_fingerprints(fps)
    results = search_similar(store, user_curve=asc, top_n=10)
    assert len(results) == 10
```

- [ ] **Step 2: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py -k search -v`
Expected: FAIL with "ImportError: cannot import name 'search_similar'"

- [ ] **Step 3: 实现 search_similar**

追加到 `analysis/pattern_matcher.py`:

```python
from typing import Dict, List, Optional, Sequence

from analysis.pattern_store import Fingerprint, PatternStore


def _is_st_name(name: str) -> bool:
    if not name:
        return False
    n = name.upper().strip()
    return "ST" in n or "退" in name


def search_similar(
    store: "PatternStore",
    user_curve: Sequence[float],
    top_n: int = 30,
    markets: Optional[List[str]] = None,
    industry: Optional[str] = None,
    exclude_st: bool = True,
) -> List[Dict]:
    """从指纹库检索与 user_curve 最相似的 Top-N 股票。"""
    if user_curve is None or len(user_curve) < 2:
        return []

    user_slope = linear_slope(user_curve)
    market_set = set(markets) if markets else None

    candidates: List[Dict] = []
    for fp in store.load_all_fingerprints():
        if market_set and fp.market not in market_set:
            continue
        if industry and fp.industry != industry:
            continue
        if exclude_st and _is_st_name(fp.stock_name):
            continue
        breakdown = score_pair(user_curve, user_slope, fp.normalized_curve, fp.mean_slope)
        if breakdown["score"] <= 0.0:
            continue
        candidates.append({
            "stock_code": fp.stock_code,
            "stock_name": fp.stock_name,
            "market": fp.market,
            "industry": fp.industry,
            "score": breakdown["score"],
            "shape_sim": breakdown["shape_sim"],
            "slope_sim": breakdown["slope_sim"],
            "latest_close": fp.latest_close,
            "latest_change_pct": fp.latest_change_pct,
            "normalized_curve": fp.normalized_curve,
            "snapshot_date": fp.snapshot_date.isoformat(),
        })

    candidates.sort(key=lambda row: row["score"], reverse=True)
    return candidates[:top_n]
```

- [ ] **Step 4: 运行所有 matcher 测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_pattern_matcher.py -v`
Expected: 13 passed (9 算法 + 4 search)

- [ ] **Step 5: 提交**

```bash
git add analysis/pattern_matcher.py tests/test_pattern_matcher.py
git commit -m "feat: 形态搜股 - 实现 search_similar 匹配引擎"
```

---

## Task 6: 实现指纹构建 CLI - 单股拉取

**Files:**
- Create: `scripts/build_pattern_fingerprints.py`
- Create: `tests/test_build_fingerprints.py`

- [ ] **Step 1: 写入测试 - fetch_kline mocked**

写入 `tests/test_build_fingerprints.py`:

```python
import datetime
from unittest.mock import patch

import pytest

from scripts.build_pattern_fingerprints import (
    build_fingerprint_for_stock,
    parse_market_from_secid,
)


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
```

- [ ] **Step 2: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_build_fingerprints.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: 实现 build_fingerprint_for_stock 与辅助函数**

写入 `scripts/build_pattern_fingerprints.py`:

```python
"""Build pattern fingerprints for the full A-share market.

Fetches last 30 trading days of daily OHLCV from Eastmoney's push2 API
for all listed A-share stocks, computes normalized curves and slopes,
and stores results in SQLite.

Usage:
    python scripts/build_pattern_fingerprints.py
    python scripts/build_pattern_fingerprints.py --limit 50   # 调试
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analysis.pattern_matcher import (  # noqa: E402
    TARGET_LENGTH,
    linear_slope,
    normalize_curve,
)
from analysis.pattern_store import Fingerprint, PatternStore  # noqa: E402

DB_PATH = ROOT_DIR / "data" / "pattern_fingerprints.db"

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
USER_AGENT = "Mozilla/5.0"
DEFAULT_TIMEOUT = 10
DEFAULT_WORKERS = 16
WINDOW = 30  # 取最近 30 个交易日


def parse_market_from_secid(secid: str) -> str:
    """Eastmoney secid 形如 '1.600977' / '0.000001'。1=沪, 0=深/京。"""
    prefix = secid.split(".", 1)[0]
    if prefix == "1":
        return "SH"
    if prefix == "0":
        return "SZ"
    if prefix == "116":
        return "HK"
    return "BJ" if prefix == "0" else "SZ"


def build_fingerprint_for_stock(
    stock_code: str,
    stock_name: str,
    market: str,
    industry: str,
    klines_raw: List[str],
    snapshot_date: datetime.date,
) -> Optional[Fingerprint]:
    """从原始 Eastmoney K 线字符串数组构建指纹。

    klines 格式: 'date,open,close,high,low,volume,amount,amplitude,pct_chg,change,turnover'
    """
    if not klines_raw or len(klines_raw) < 10:
        return None
    closes: List[float] = []
    last_pct = 0.0
    for item in klines_raw[-WINDOW:]:
        parts = str(item).split(",")
        if len(parts) < 5:
            continue
        try:
            close = float(parts[2])
            closes.append(close)
            if len(parts) > 8:
                last_pct = float(parts[8])
        except (TypeError, ValueError):
            continue
    if len(closes) < 10:
        return None

    norm = normalize_curve(closes, target_length=TARGET_LENGTH)
    if norm is None:
        return None
    slope = linear_slope(norm)

    return Fingerprint(
        stock_code=stock_code,
        stock_name=stock_name,
        market=market,
        industry=industry,
        normalized_curve=norm,
        mean_slope=slope,
        latest_close=closes[-1],
        latest_change_pct=last_pct,
        snapshot_date=snapshot_date,
    )
```

- [ ] **Step 4: 运行测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_build_fingerprints.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/build_pattern_fingerprints.py tests/test_build_fingerprints.py
git commit -m "feat: 形态搜股 - 添加指纹构建工具与辅助函数"
```

---

## Task 7: 指纹构建 - 全市场抓取与并发

**Files:**
- Modify: `scripts/build_pattern_fingerprints.py`
- Modify: `tests/test_build_fingerprints.py`

- [ ] **Step 1: 写入 fetch_recent_klines 测试（mocked HTTP）**

追加到 `tests/test_build_fingerprints.py`:

```python
from unittest.mock import patch, MagicMock

from scripts.build_pattern_fingerprints import fetch_recent_klines


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
```

- [ ] **Step 2: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_build_fingerprints.py -k fetch_recent_klines -v`
Expected: FAIL with "ImportError: cannot import name 'fetch_recent_klines'"

- [ ] **Step 3: 实现 fetch_recent_klines + _http_get_json**

追加到 `scripts/build_pattern_fingerprints.py`:

```python
def _http_get_json(url: str, params: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_recent_klines(secid: str, limit: int = 30) -> Tuple[str, List[str]]:
    """拉取该 secid 最近 limit 个日 K。返回 (股票名, 原始 klines 字符串数组)。"""
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "klt": "101",  # 101 = 日 K
        "secid": secid,
        "fqt": "1",    # 前复权
        "lmt": str(limit + 5),  # 多取几个防止节假日
        "end": "20500101",
        "_": str(int(time.time() * 1000)),
    }
    payload = _http_get_json(KLINE_URL, params)
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    name = data.get("name") or ""
    return name, list(klines)
```

- [ ] **Step 4: 运行测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_build_fingerprints.py -k fetch_recent_klines -v`
Expected: 2 passed

- [ ] **Step 5: 写入 list_all_secids 测试（mocked）**

追加到 `tests/test_build_fingerprints.py`:

```python
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
```

- [ ] **Step 6: 验证失败**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_build_fingerprints.py -k list_all_secids -v`
Expected: FAIL

- [ ] **Step 7: 实现 list_all_secids**

追加到 `scripts/build_pattern_fingerprints.py`:

```python
def list_all_secids() -> List[dict]:
    """获取沪深京全 A 股代码列表。

    返回 [{stock_code, secid, stock_name, industry, market}, ...]
    """
    # fs=m:0+t:6: 深主板; m:0+t:80: 创业板;
    # m:1+t:2:  沪主板; m:1+t:23: 科创板;
    # m:0+t:81+s:2048: 北交所
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    page_size = 200
    page = 1
    out: List[dict] = []
    while True:
        params = {
            "pn": str(page),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f12",
            "fs": fs,
            "fields": "f12,f13,f14,f100",
            "_": str(int(time.time() * 1000)),
        }
        payload = _http_get_json(CLIST_URL, params)
        data = payload.get("data") or {}
        diff = data.get("diff") or []
        if not diff:
            break
        for row in diff:
            code = str(row.get("f12") or "").strip()
            market_id = int(row.get("f13") or 0)
            name = str(row.get("f14") or "").strip()
            industry = str(row.get("f100") or "").strip()
            if not code:
                continue
            secid = f"{market_id}.{code}"
            market = parse_market_from_secid(secid)
            out.append({
                "stock_code": code,
                "secid": secid,
                "stock_name": name,
                "industry": industry,
                "market": market,
            })
        if len(diff) < page_size:
            break
        page += 1
        if page > 50:  # 安全上限：~10000 只
            break
    return out
```

- [ ] **Step 8: 运行测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/test_build_fingerprints.py -v`
Expected: 8 passed

- [ ] **Step 9: 提交**

```bash
git add scripts/build_pattern_fingerprints.py tests/test_build_fingerprints.py
git commit -m "feat: 形态搜股 - 实现全市场代码列表与 K 线抓取"
```

---

## Task 8: 指纹构建 - 主流程 main()

**Files:**
- Modify: `scripts/build_pattern_fingerprints.py`

- [ ] **Step 1: 实现 build_all + main**

追加到 `scripts/build_pattern_fingerprints.py`:

```python
def _process_one(stock: dict, snapshot_date: datetime.date) -> Optional[Fingerprint]:
    """单股拉取并构建指纹。失败返回 None。"""
    try:
        name, klines = fetch_recent_klines(stock["secid"], limit=WINDOW)
    except Exception as exc:
        print(f"[warn] {stock['stock_code']}: kline fetch failed: {exc}")
        return None
    final_name = name or stock["stock_name"]
    return build_fingerprint_for_stock(
        stock_code=stock["stock_code"],
        stock_name=final_name,
        market=stock["market"],
        industry=stock["industry"],
        klines_raw=klines,
        snapshot_date=snapshot_date,
    )


def build_all(
    store: PatternStore,
    limit: Optional[int] = None,
    max_workers: int = DEFAULT_WORKERS,
    snapshot_date: Optional[datetime.date] = None,
    progress_callback=None,
) -> dict:
    snapshot_date = snapshot_date or datetime.date.today()
    store.init_schema()
    snapshot_id = store.start_snapshot(snapshot_date)
    started_at = time.time()

    try:
        stocks = list_all_secids()
    except Exception as exc:
        store.finish_snapshot(
            snapshot_id, status="failed", total=0, succeeded=0,
            failed=0, error_log=f"list_all_secids: {exc}",
        )
        raise

    if limit:
        stocks = stocks[:limit]
    total = len(stocks)
    if progress_callback:
        progress_callback(f"开始抓取 {total} 只股票的 30 日 K 线")

    succeeded = 0
    failed = 0
    errors: List[str] = []
    buffer: List[Fingerprint] = []
    BATCH = 200

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_process_one, stock, snapshot_date): stock
            for stock in stocks
        }
        for idx, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            stock = futures[future]
            try:
                fp = future.result()
            except Exception as exc:
                fp = None
                errors.append(f"{stock['stock_code']}: {exc}")
            if fp is None:
                failed += 1
            else:
                buffer.append(fp)
                succeeded += 1
            if len(buffer) >= BATCH:
                store.upsert_fingerprints(buffer)
                buffer.clear()
            if progress_callback and idx % 200 == 0:
                progress_callback(
                    f"进度 {idx}/{total}  成功 {succeeded}  失败 {failed}"
                )
    if buffer:
        store.upsert_fingerprints(buffer)

    elapsed = time.time() - started_at
    fail_rate = failed / total if total else 1.0
    status = "failed" if fail_rate > 0.30 else "success"
    store.finish_snapshot(
        snapshot_id,
        status=status,
        total=total,
        succeeded=succeeded,
        failed=failed,
        error_log=("; ".join(errors[:30]) if errors else None),
    )
    return {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date.isoformat(),
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "elapsed_seconds": round(elapsed, 1),
        "status": status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="构建全市场形态指纹库")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 只（调试用）")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--db", type=str, default=str(DB_PATH))
    args = parser.parse_args()
    store = PatternStore(Path(args.db))

    def log(msg: str) -> None:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

    result = build_all(
        store, limit=args.limit, max_workers=args.workers, progress_callback=log
    )
    log(f"完成: {result}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 烟测 — 处理 3 只股票**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python scripts/build_pattern_fingerprints.py --limit 3`
Expected: 输出形如 `完成: {'snapshot_id': 1, 'snapshot_date': '2026-05-18', 'total': 3, 'succeeded': 3, 'failed': 0, ...}` 且 `data/pattern_fingerprints.db` 创建成功

- [ ] **Step 3: 验证库内容**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -c "from analysis.pattern_store import PatternStore; s = PatternStore('data/pattern_fingerprints.db'); print(s.current_status()); print([r.stock_code for r in s.load_all_fingerprints()])"`
Expected: status `available=True total_stocks=3`, 列出 3 个 stock_code

- [ ] **Step 4: 提交**

```bash
git add scripts/build_pattern_fingerprints.py
git commit -m "feat: 形态搜股 - 实现全市场指纹构建主流程"
```

---

## Task 9: 后端 Flask API - status / match / stock-curve

**Files:**
- Modify: `webui/app.py`

- [ ] **Step 1: 添加模块顶层 import 与单例**

定位 `webui/app.py` 第 1-50 行的 import 区，在现有 import 之后添加：

```python
# === Pattern Search ===
from analysis.pattern_matcher import (
    TARGET_LENGTH as PATTERN_TARGET_LENGTH,
    normalize_curve as pattern_normalize_curve,
    search_similar as pattern_search_similar,
)
from analysis.pattern_store import PatternStore

PATTERN_DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'pattern_fingerprints.db'
_pattern_store_instance = None


def _get_pattern_store():
    global _pattern_store_instance
    if _pattern_store_instance is None:
        _pattern_store_instance = PatternStore(PATTERN_DB_PATH)
        _pattern_store_instance.init_schema()
    return _pattern_store_instance
```

注：若 `Path` 已在文件顶部导入则无需重复 import。

- [ ] **Step 2: 添加 /api/pattern-search/status 路由**

在 `webui/app.py` 中找到 `@app.route('/api/jobs/<job_id>')` 上方（约第 2076 行附近），插入：

```python
@app.route('/api/pattern-search/status')
def pattern_search_status():
    store = _get_pattern_store()
    status = store.current_status()

    staleness_days = None
    warning = None
    if status.get('last_snapshot_date'):
        try:
            d = datetime.date.fromisoformat(status['last_snapshot_date'])
            staleness_days = (datetime.date.today() - d).days
            if staleness_days >= 3:
                warning = f"指纹数据已陈旧 {staleness_days} 天，建议刷新"
        except ValueError:
            staleness_days = None
    if not status.get('available'):
        warning = warning or "指纹库尚未生成，请先点击刷新"

    return jsonify({
        'available': status.get('available', False),
        'snapshot_date': status.get('last_snapshot_date'),
        'total_stocks': status.get('total_stocks', 0),
        'updated_at': status.get('last_finished_at'),
        'last_status': status.get('last_status'),
        'staleness_days': staleness_days,
        'warning': warning,
    })
```

- [ ] **Step 3: 添加 /api/pattern-search/match 路由**

紧接 status 路由之后插入：

```python
@app.route('/api/pattern-search/match', methods=['POST'])
def pattern_search_match():
    payload = request.get_json(silent=True) or {}
    curve = payload.get('curve')
    if not isinstance(curve, list) or len(curve) != PATTERN_TARGET_LENGTH:
        return jsonify({
            'error': f'curve 必须为长度 {PATTERN_TARGET_LENGTH} 的数组'
        }), 400
    try:
        curve = [float(x) for x in curve]
    except (TypeError, ValueError):
        return jsonify({'error': 'curve 元素必须为数字'}), 400

    top_n = _safe_int(payload.get('top_n'), default=30, minimum=1, maximum=200)
    filters = payload.get('filters') or {}
    markets = filters.get('market') or None
    if markets and not isinstance(markets, list):
        markets = [markets]
    industry = filters.get('industry') or None
    exclude_st = bool(filters.get('exclude_st', True))

    store = _get_pattern_store()
    started = time.time()
    results = pattern_search_similar(
        store, curve, top_n=top_n,
        markets=markets, industry=industry, exclude_st=exclude_st,
    )
    elapsed_ms = int((time.time() - started) * 1000)

    status = store.current_status()
    return jsonify({
        'matches': results,
        'snapshot_date': status.get('last_snapshot_date'),
        'compute_ms': elapsed_ms,
        'count': len(results),
    })
```

- [ ] **Step 4: 添加 /api/pattern-search/stock-curve/\<code\> 路由**

紧接 match 路由之后插入：

```python
@app.route('/api/pattern-search/stock-curve/<stock_code>')
def pattern_search_stock_curve(stock_code):
    code = (stock_code or '').strip()
    if not code:
        return jsonify({'error': '股票代码不能为空'}), 400
    store = _get_pattern_store()
    fp = store.load_fingerprint(code)
    if fp is None:
        return jsonify({
            'available': False,
            'message': '该股不在指纹库中（可能停牌、未上市或库尚未刷新）',
        }), 404
    return jsonify({
        'available': True,
        'stock_code': fp.stock_code,
        'stock_name': fp.stock_name,
        'market': fp.market,
        'industry': fp.industry,
        'normalized_curve': fp.normalized_curve,
        'mean_slope': fp.mean_slope,
        'latest_close': fp.latest_close,
        'latest_change_pct': fp.latest_change_pct,
        'snapshot_date': fp.snapshot_date.isoformat(),
    })
```

- [ ] **Step 5: 启动 webui 烟测 status**

Run（后台）: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui && python app.py &`
Wait 3 秒后:
Run: `curl -s http://localhost:7070/api/pattern-search/status | python -m json.tool`
Expected: 返回 JSON，`available: true` 或带 warning（取决于 Task 8 是否运行过）

- [ ] **Step 6: 烟测 match**

Run: `curl -s -X POST http://localhost:7070/api/pattern-search/match -H 'Content-Type: application/json' -d '{"curve": [0.0, 0.03, 0.06, 0.10, 0.13, 0.16, 0.20, 0.23, 0.26, 0.30, 0.33, 0.36, 0.40, 0.43, 0.46, 0.50, 0.53, 0.56, 0.60, 0.63, 0.66, 0.70, 0.73, 0.76, 0.80, 0.83, 0.86, 0.90, 0.93, 1.00], "top_n": 5}' | python -m json.tool`
Expected: 返回包含 `matches` 数组（指纹库非空时）或 `count: 0`

- [ ] **Step 7: 杀掉测试服务**

Run: `pkill -f 'webui/app.py' || true`

- [ ] **Step 8: 提交**

```bash
git add webui/app.py
git commit -m "feat: 形态搜股 - 添加 status/match/stock-curve API"
```

---

## Task 10: 后端 Flask API - refresh 后台任务

**Files:**
- Modify: `webui/app.py`

- [ ] **Step 1: 添加 _run_pattern_refresh_job 函数**

在 `webui/app.py` 中 `_run_batch_analysis_job` 函数（约 1540 行）之后添加：

```python
def _run_pattern_refresh_job(job_id, params):
    _update_job(job_id, status='running', started_at=datetime.datetime.now().isoformat())
    _append_job_log(job_id, '开始刷新形态指纹库')
    try:
        from scripts.build_pattern_fingerprints import build_all

        store = _get_pattern_store()

        def log_cb(message):
            _append_job_log(job_id, message)

        result = build_all(
            store,
            limit=params.get('limit'),
            max_workers=params.get('workers', 16),
            progress_callback=log_cb,
        )
        _append_job_log(
            job_id,
            f"刷新完成: 总数 {result['total']} 成功 {result['succeeded']} 失败 {result['failed']}"
        )
        _update_job(
            job_id,
            status='finished',
            finished_at=datetime.datetime.now().isoformat(),
            result=result,
        )
    except Exception as exc:
        _append_job_log(job_id, f'指纹刷新失败: {exc}')
        _update_job(
            job_id,
            status='failed',
            finished_at=datetime.datetime.now().isoformat(),
            error=str(exc),
        )
```

- [ ] **Step 2: 添加 /api/pattern-search/refresh 路由**

紧接 Task 9 stock-curve 路由之后插入：

```python
@app.route('/api/pattern-search/refresh', methods=['POST'])
def pattern_search_refresh():
    payload = request.get_json(silent=True) or {}
    params = {
        'limit': _safe_int(payload.get('limit'), default=None, minimum=1, maximum=10000) if payload.get('limit') else None,
        'workers': _safe_int(payload.get('workers'), default=16, minimum=1, maximum=64),
    }
    job = _create_job('pattern_refresh', params)
    thread = threading.Thread(
        target=_run_pattern_refresh_job, args=(job['id'], params), daemon=True
    )
    thread.start()
    return jsonify({'job_id': job['id'], 'status': 'queued'})
```

注：`threading` 已在 app.py 顶部导入，无需重复。

- [ ] **Step 3: 启动服务并烟测 refresh（limit=2 快速）**

Run（后台）: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui && python app.py &`
Wait 3 秒后:
Run: `curl -s -X POST http://localhost:7070/api/pattern-search/refresh -H 'Content-Type: application/json' -d '{"limit": 2}' | python -m json.tool`
Expected: 返回 `{"job_id": "...", "status": "queued"}`

抽出 job_id：
Run: `JOB=$(curl -s http://localhost:7070/api/jobs | python -c 'import json,sys; jobs=json.load(sys.stdin); print(next(j["id"] for j in jobs if j["type"]=="pattern_refresh"))') && sleep 5 && curl -s http://localhost:7070/api/jobs/$JOB | python -m json.tool`
Expected: status 已变为 `finished`，result 含 `succeeded`, `failed`

- [ ] **Step 4: 杀掉测试服务**

Run: `pkill -f 'webui/app.py' || true`

- [ ] **Step 5: 提交**

```bash
git add webui/app.py
git commit -m "feat: 形态搜股 - 添加后台指纹刷新任务"
```

---

## Task 11: 前端 - 顶部按钮与 Modal 骨架

**Files:**
- Modify: `webui/templates/stock_analysis_home.html`

- [ ] **Step 1: 在 status-row 右侧添加按钮**

找到 `<section class="status-row" ...>` 块内的 `<div class="status-right">`（约第 887 行附近），将 `<button id="refreshBtn" ...>` 之前插入：

```html
<button id="patternSearchBtn" class="button" type="button" title="画一条曲线/选一只股票，搜索全 A 股相似形态">
    形态搜股
</button>
```

- [ ] **Step 2: 在 `</body>` 之前添加 Modal HTML 与 CSS**

在 `</body>` 标签前面（约文件末尾）插入：

```html
<div id="patternModal" class="pattern-modal" hidden>
    <div class="pattern-modal-shell">
        <header class="pattern-modal-header">
            <h2>形态搜股</h2>
            <div class="pattern-modal-meta">
                <span id="patternDataStatus" class="pill">指纹库状态</span>
                <button id="patternRefreshBtn" class="soft-button" type="button">刷新指纹库</button>
            </div>
            <button id="patternCloseBtn" class="soft-button" type="button" aria-label="关闭">✕</button>
        </header>

        <div class="pattern-tabs">
            <button class="pattern-tab active" data-mode="draw" type="button">手绘形态</button>
            <button class="pattern-tab" data-mode="stock" type="button">选股票形态</button>
        </div>

        <div class="pattern-body">
            <section class="pattern-canvas-pane">
                <div id="patternDrawPanel" class="pattern-input-panel">
                    <canvas id="patternCanvas" width="640" height="320"></canvas>
                    <div class="pattern-canvas-footer">
                        <span id="patternSampleHint" class="muted">在画布中按住鼠标拖动绘制曲线</span>
                        <div class="pattern-canvas-actions">
                            <button id="patternUndoBtn" class="soft-button" type="button">撤销</button>
                            <button id="patternClearBtn" class="soft-button" type="button">清空</button>
                            <button id="patternSubmitBtn" class="button" type="button" disabled>检索</button>
                        </div>
                    </div>
                </div>

                <div id="patternStockPanel" class="pattern-input-panel" hidden>
                    <div class="pattern-stock-form">
                        <input id="patternStockInput" type="text" placeholder="股票代码（如 600977）" maxlength="10">
                        <button id="patternStockLoadBtn" class="button secondary" type="button">载入预览</button>
                    </div>
                    <div id="patternStockPreview" class="pattern-stock-preview empty">
                        输入股票代码后点击"载入预览"
                    </div>
                    <button id="patternStockSubmitBtn" class="button" type="button" disabled>用该形态检索</button>
                </div>

                <div id="patternCompare" class="pattern-compare" hidden>
                    <h3 id="patternCompareTitle">对比图</h3>
                    <div id="patternComparePlot" style="height: 220px;"></div>
                </div>
            </section>

            <aside class="pattern-result-pane">
                <header class="pattern-result-header">
                    <h3>相似股票</h3>
                    <span id="patternResultCount" class="muted">--</span>
                </header>
                <div id="patternResults" class="pattern-results"></div>
                <div id="patternEmpty" class="empty" hidden>暂无匹配结果</div>
                <div id="patternLoading" class="empty" hidden>正在检索…</div>
            </aside>
        </div>
    </div>
</div>
```

- [ ] **Step 3: 在 `<style>` 末尾添加 Modal CSS**

找到 `</style>`（约第 856 行附近），在它之前插入：

```css
.pattern-modal {
    position: fixed; inset: 0; z-index: 1000;
    background: rgba(20, 35, 50, 0.55);
    display: flex; align-items: center; justify-content: center;
    padding: 24px;
}
.pattern-modal[hidden] { display: none; }

.pattern-modal-shell {
    width: 100%; max-width: 1280px; height: 92vh;
    background: var(--surface); border-radius: 12px;
    box-shadow: 0 20px 50px rgba(20, 35, 50, 0.2);
    display: flex; flex-direction: column; overflow: hidden;
}
.pattern-modal-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 20px; border-bottom: 1px solid var(--line); gap: 12px;
}
.pattern-modal-header h2 { margin: 0; font-size: 16px; color: var(--ink); }
.pattern-modal-meta { display: flex; gap: 8px; align-items: center; }

.pattern-tabs {
    display: flex; gap: 4px; padding: 8px 20px;
    border-bottom: 1px solid var(--line); background: var(--surface-soft);
}
.pattern-tab {
    padding: 6px 14px; border: 1px solid transparent;
    border-radius: 6px; background: transparent; cursor: pointer;
    color: var(--muted); font-weight: 600;
}
.pattern-tab.active { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }

.pattern-body {
    flex: 1; display: grid;
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
    gap: 16px; padding: 16px 20px; overflow: hidden;
}
.pattern-canvas-pane { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.pattern-input-panel {
    border: 1px solid var(--line); border-radius: 8px;
    padding: 12px; background: var(--surface-soft);
}
#patternCanvas {
    width: 100%; height: 320px; background: #ffffff;
    border: 1px dashed #cbd5e1; border-radius: 6px;
    cursor: crosshair; display: block;
}
.pattern-canvas-footer {
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 8px; flex-wrap: wrap; gap: 8px;
}
.pattern-canvas-actions { display: flex; gap: 6px; }
.muted { color: var(--muted); font-size: 12px; }

.pattern-stock-form {
    display: flex; gap: 8px; margin-bottom: 10px;
}
.pattern-stock-form input {
    flex: 1; padding: 8px 10px; border: 1px solid var(--line);
    border-radius: 6px; font-size: 14px;
}
.pattern-stock-preview {
    padding: 12px; border: 1px solid var(--line);
    border-radius: 6px; background: #fff; margin-bottom: 10px;
    min-height: 48px;
}
.pattern-stock-preview.empty {
    color: var(--muted); display: flex; align-items: center;
    justify-content: center; min-height: 80px; font-size: 12px;
}

.pattern-compare {
    border: 1px solid var(--line); border-radius: 8px;
    padding: 12px; background: var(--surface);
}
.pattern-compare h3 { margin: 0 0 8px; font-size: 13px; color: var(--ink); }

.pattern-result-pane {
    display: flex; flex-direction: column; min-height: 0;
    border: 1px solid var(--line); border-radius: 8px;
    background: var(--surface); overflow: hidden;
}
.pattern-result-header {
    padding: 10px 14px; border-bottom: 1px solid var(--line);
    display: flex; justify-content: space-between; align-items: center;
}
.pattern-result-header h3 { margin: 0; font-size: 14px; color: var(--ink); }
.pattern-results {
    flex: 1; overflow-y: auto; padding: 8px;
    display: flex; flex-direction: column; gap: 6px;
}
.pattern-result-item {
    padding: 10px; border: 1px solid var(--line);
    border-radius: 6px; background: #fff; cursor: pointer;
    transition: background 0.15s;
}
.pattern-result-item:hover { background: #eff6ff; border-color: #bfdbfe; }
.pattern-result-item.active { background: #dbeafe; border-color: #93c5fd; }
.pattern-result-row1 {
    display: flex; justify-content: space-between; align-items: center;
    font-weight: 700; color: var(--ink); font-size: 14px;
}
.pattern-result-score {
    background: #ecfeff; color: #0c4a6e;
    padding: 1px 6px; border-radius: 999px; font-size: 12px; font-weight: 700;
}
.pattern-result-row2 { color: var(--muted); font-size: 12px; margin-top: 4px; }
.pattern-result-spark {
    margin-top: 6px; height: 32px; width: 100%;
    background: #f8fafc; border-radius: 4px;
}

@media (max-width: 1100px) {
    .pattern-body { grid-template-columns: 1fr; }
}
```

- [ ] **Step 4: 启动 webui 验证 Modal 显示**

Run（后台）: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui && python app.py &`
Wait 3 秒后:
Run: `curl -s http://localhost:7070/ | grep -o 'patternSearchBtn\|patternModal'`
Expected: 输出包含 `patternSearchBtn` 和 `patternModal`

- [ ] **Step 5: 杀掉测试服务**

Run: `pkill -f 'webui/app.py' || true`

- [ ] **Step 6: 提交**

```bash
git add webui/templates/stock_analysis_home.html
git commit -m "feat: 形态搜股 - 添加首页按钮与 Modal 骨架"
```

---

## Task 12: 前端 - Modal 控制脚本（打开/关闭/Tab/状态）

**Files:**
- Modify: `webui/templates/stock_analysis_home.html`

- [ ] **Step 1: 在 `</body>` 前的 script 块中（找到现有 `</script>` 之前的位置）添加 Modal 控制代码**

找到文件末尾最后一段 `<script>` 块的结尾 `</script>` 标签，在其之前插入：

```javascript
// ===== 形态搜股 Modal =====
const patternModal = {
    el: document.getElementById('patternModal'),
    openBtn: document.getElementById('patternSearchBtn'),
    closeBtn: document.getElementById('patternCloseBtn'),
    refreshBtn: document.getElementById('patternRefreshBtn'),
    statusEl: document.getElementById('patternDataStatus'),
    tabs: document.querySelectorAll('.pattern-tab'),
    drawPanel: document.getElementById('patternDrawPanel'),
    stockPanel: document.getElementById('patternStockPanel'),
    resultsEl: document.getElementById('patternResults'),
    emptyEl: document.getElementById('patternEmpty'),
    loadingEl: document.getElementById('patternLoading'),
    countEl: document.getElementById('patternResultCount'),
    compareEl: document.getElementById('patternCompare'),
    refreshJobId: null,

    open() {
        this.el.hidden = false;
        this.loadStatus();
    },
    close() { this.el.hidden = true; },

    async loadStatus() {
        try {
            const res = await fetch('/api/pattern-search/status');
            const data = await res.json();
            const cls = data.available ? 'pill ok' : 'pill warn';
            const text = data.available
                ? `指纹库 ${data.total_stocks} 只 · 基准 ${data.snapshot_date}${data.staleness_days != null ? ` · ${data.staleness_days} 天前` : ''}`
                : '指纹库尚未生成';
            this.statusEl.className = cls;
            this.statusEl.textContent = text;
            this.statusEl.title = data.warning || '';
        } catch (err) {
            this.statusEl.className = 'pill warn';
            this.statusEl.textContent = '指纹库状态获取失败';
        }
    },

    switchTab(mode) {
        this.tabs.forEach(t => t.classList.toggle('active', t.dataset.mode === mode));
        this.drawPanel.hidden = mode !== 'draw';
        this.stockPanel.hidden = mode !== 'stock';
    },

    async triggerRefresh() {
        if (!confirm('开始刷新全市场形态指纹？预计需要 10-15 分钟。')) return;
        this.refreshBtn.disabled = true;
        this.refreshBtn.textContent = '刷新中...';
        try {
            const res = await fetch('/api/pattern-search/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
            });
            const data = await res.json();
            this.refreshJobId = data.job_id;
            this._pollRefreshStatus();
        } catch (err) {
            alert('启动刷新失败：' + err);
            this.refreshBtn.disabled = false;
            this.refreshBtn.textContent = '刷新指纹库';
        }
    },

    _pollRefreshStatus() {
        if (!this.refreshJobId) return;
        fetch('/api/jobs/' + this.refreshJobId)
            .then(r => r.json())
            .then(job => {
                if (job.status === 'finished' || job.status === 'failed') {
                    this.refreshBtn.disabled = false;
                    this.refreshBtn.textContent = '刷新指纹库';
                    this.loadStatus();
                    if (job.status === 'failed') {
                        alert('指纹刷新失败：' + (job.error || '未知错误'));
                    }
                    this.refreshJobId = null;
                } else {
                    const tail = (job.logs || []).slice(-1)[0] || '';
                    this.refreshBtn.textContent = '刷新中: ' + tail.slice(-40);
                    setTimeout(() => this._pollRefreshStatus(), 3000);
                }
            })
            .catch(() => setTimeout(() => this._pollRefreshStatus(), 5000));
    },

    init() {
        this.openBtn.addEventListener('click', () => this.open());
        this.closeBtn.addEventListener('click', () => this.close());
        this.el.addEventListener('click', (e) => { if (e.target === this.el) this.close(); });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !this.el.hidden) this.close();
        });
        this.refreshBtn.addEventListener('click', () => this.triggerRefresh());
        this.tabs.forEach(t => t.addEventListener('click', () => this.switchTab(t.dataset.mode)));
    },
};
patternModal.init();
```

- [ ] **Step 2: 启动 webui 手动烟测**

Run（后台）: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui && python app.py &`

打开浏览器访问 `http://localhost:7070`，验证：
1. 顶部状态栏有「形态搜股」按钮
2. 点击按钮，Modal 弹出
3. 点击右上角 ✕ 或按 Esc 或点击 Modal 外部 → Modal 关闭
4. 切换 Tab 「手绘形态」/「选股票形态」
5. 「指纹库状态」pill 显示当前状态

- [ ] **Step 3: 杀掉测试服务**

Run: `pkill -f 'webui/app.py' || true`

- [ ] **Step 4: 提交**

```bash
git add webui/templates/stock_analysis_home.html
git commit -m "feat: 形态搜股 - 添加 Modal 控制脚本与 Tab 切换"
```

---

## Task 13: 前端 - Canvas 画板交互与 30 点采样

**Files:**
- Modify: `webui/templates/stock_analysis_home.html`

- [ ] **Step 1: 在 `patternModal.init();` 之后，`</script>` 之前添加 Canvas 模块**

```javascript
// ===== Canvas 画板 =====
const patternCanvas = {
    canvas: document.getElementById('patternCanvas'),
    ctx: null,
    strokes: [],      // [[{x,y},...], ...]
    currentStroke: null,
    drawing: false,
    sampleHint: document.getElementById('patternSampleHint'),
    submitBtn: document.getElementById('patternSubmitBtn'),
    undoBtn: document.getElementById('patternUndoBtn'),
    clearBtn: document.getElementById('patternClearBtn'),

    TARGET: 30,

    init() {
        this.ctx = this.canvas.getContext('2d');
        this._resizeForDpr();

        this.canvas.addEventListener('mousedown', (e) => this._start(e));
        this.canvas.addEventListener('mousemove', (e) => this._move(e));
        window.addEventListener('mouseup', () => this._end());
        this.canvas.addEventListener('touchstart', (e) => this._start(e.touches[0]));
        this.canvas.addEventListener('touchmove', (e) => { e.preventDefault(); this._move(e.touches[0]); }, { passive: false });
        this.canvas.addEventListener('touchend', () => this._end());

        this.undoBtn.addEventListener('click', () => this.undo());
        this.clearBtn.addEventListener('click', () => this.clear());
    },

    _resizeForDpr() {
        const rect = this.canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.ctx.scale(dpr, dpr);
        this._cssWidth = rect.width;
        this._cssHeight = rect.height;
        this._render();
    },

    _pos(evt) {
        const rect = this.canvas.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(rect.width, evt.clientX - rect.left)),
            y: Math.max(0, Math.min(rect.height, evt.clientY - rect.top)),
        };
    },

    _start(evt) {
        this.drawing = true;
        this.currentStroke = [this._pos(evt)];
        this.strokes.push(this.currentStroke);
        this._render();
    },
    _move(evt) {
        if (!this.drawing) return;
        this.currentStroke.push(this._pos(evt));
        this._render();
    },
    _end() {
        if (!this.drawing) return;
        this.drawing = false;
        this.currentStroke = null;
        this._render();
        this._updateState();
    },

    undo() {
        this.strokes.pop();
        this._render();
        this._updateState();
    },
    clear() {
        this.strokes = [];
        this._render();
        this._updateState();
    },

    _render() {
        const w = this._cssWidth, h = this._cssHeight;
        this.ctx.clearRect(0, 0, w, h);
        // 网格背景
        this.ctx.strokeStyle = '#e2e8f0';
        this.ctx.lineWidth = 1;
        for (let i = 1; i < 6; i++) {
            const y = (h / 6) * i;
            this.ctx.beginPath();
            this.ctx.moveTo(0, y); this.ctx.lineTo(w, y);
            this.ctx.stroke();
        }
        // 笔迹（浅灰）
        this.ctx.strokeStyle = '#94a3b8';
        this.ctx.lineWidth = 2;
        this.strokes.forEach(stroke => {
            if (stroke.length < 2) return;
            this.ctx.beginPath();
            this.ctx.moveTo(stroke[0].x, stroke[0].y);
            for (let i = 1; i < stroke.length; i++) {
                this.ctx.lineTo(stroke[i].x, stroke[i].y);
            }
            this.ctx.stroke();
        });
        // 30 点采样曲线（蓝色）
        const sampled = this.sample();
        if (sampled) {
            this.ctx.strokeStyle = '#2563eb';
            this.ctx.lineWidth = 2.5;
            this.ctx.beginPath();
            sampled.forEach((y, i) => {
                const px = (i / (this.TARGET - 1)) * w;
                const py = h - y * h;   // y 翻转：上=高
                if (i === 0) this.ctx.moveTo(px, py);
                else this.ctx.lineTo(px, py);
            });
            this.ctx.stroke();
            this.ctx.fillStyle = '#2563eb';
            sampled.forEach((y, i) => {
                const px = (i / (this.TARGET - 1)) * w;
                const py = h - y * h;
                this.ctx.beginPath();
                this.ctx.arc(px, py, 2.5, 0, Math.PI * 2);
                this.ctx.fill();
            });
        }
    },

    sample() {
        // 收集所有点，按 x 排序
        const pts = [];
        this.strokes.forEach(s => s.forEach(p => pts.push(p)));
        if (pts.length < 5) return null;
        pts.sort((a, b) => a.x - b.x);

        // 去重 x（同一 x 取均值）
        const xs = pts.map(p => p.x);
        const xMin = xs[0], xMax = xs[xs.length - 1];
        if (xMax - xMin < this._cssWidth * 0.4) return null;

        // 按 x 等距采样 30 点
        const yVals = new Array(this.TARGET);
        const segWidth = (xMax - xMin) / (this.TARGET - 1);
        for (let i = 0; i < this.TARGET; i++) {
            const target = xMin + i * segWidth;
            // 线性插值
            let lo = 0, hi = pts.length - 1;
            for (let k = 0; k < pts.length - 1; k++) {
                if (pts[k].x <= target && pts[k + 1].x >= target) {
                    lo = k; hi = k + 1; break;
                }
            }
            const p0 = pts[lo], p1 = pts[hi];
            const t = p1.x === p0.x ? 0 : (target - p0.x) / (p1.x - p0.x);
            yVals[i] = p0.y + (p1.y - p0.y) * t;
        }

        // 归一化到 [0,1] (y=0 顶, y=h 底；映射后高=1)
        const yMin = Math.min(...yVals);
        const yMax = Math.max(...yVals);
        if (yMax - yMin < 1) return null;
        return yVals.map(y => 1 - (y - yMin) / (yMax - yMin));
    },

    getNormalizedCurve() { return this.sample(); },

    _updateState() {
        const sampled = this.sample();
        if (sampled) {
            this.sampleHint.textContent = `采样完成，30 个点已就绪`;
            this.submitBtn.disabled = false;
        } else {
            this.sampleHint.textContent = `继续绘制曲线（已绘 ${this.strokes.length} 笔）`;
            this.submitBtn.disabled = true;
        }
    },
};
patternCanvas.init();
```

- [ ] **Step 2: 启动 webui 手动烟测**

Run（后台）: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui && python app.py &`

打开浏览器访问 `http://localhost:7070`，点击「形态搜股」打开 Modal，验证：
1. 在 Canvas 上按住鼠标拖动绘制 → 笔迹显示
2. 30 点蓝色采样曲线叠加显示
3. 「采样完成」提示出现，「检索」按钮启用
4. 点击「撤销」/「清空」生效

- [ ] **Step 3: 杀掉测试服务**

Run: `pkill -f 'webui/app.py' || true`

- [ ] **Step 4: 提交**

```bash
git add webui/templates/stock_analysis_home.html
git commit -m "feat: 形态搜股 - 实现 Canvas 画板与 30 点采样"
```

---

## Task 14: 前端 - 检索调用与结果列表渲染

**Files:**
- Modify: `webui/templates/stock_analysis_home.html`

- [ ] **Step 1: 在 `patternCanvas.init();` 之后添加检索器**

```javascript
// ===== 检索逻辑 =====
const patternSearch = {
    async submit(curve) {
        if (!curve || curve.length !== 30) {
            alert('曲线数据不完整，请重新绘制');
            return;
        }
        patternModal.resultsEl.innerHTML = '';
        patternModal.emptyEl.hidden = true;
        patternModal.loadingEl.hidden = false;
        patternModal.compareEl.hidden = true;
        try {
            const res = await fetch('/api/pattern-search/match', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ curve, top_n: 30 }),
            });
            const data = await res.json();
            patternModal.loadingEl.hidden = true;
            patternState.lastQueryCurve = curve;
            patternState.lastResults = data.matches || [];
            this.render(data);
        } catch (err) {
            patternModal.loadingEl.hidden = true;
            alert('检索失败：' + err);
        }
    },

    render(data) {
        const matches = data.matches || [];
        patternModal.countEl.textContent = `${matches.length} 只 · ${data.compute_ms || 0}ms`;
        if (!matches.length) {
            patternModal.emptyEl.hidden = false;
            return;
        }
        patternModal.emptyEl.hidden = true;
        patternModal.resultsEl.innerHTML = matches.map((m, idx) => `
            <div class="pattern-result-item" data-idx="${idx}" data-code="${m.stock_code}">
                <div class="pattern-result-row1">
                    <span>${m.stock_code} ${escapeHtml(m.stock_name || '')}</span>
                    <span class="pattern-result-score">${m.score.toFixed(3)}</span>
                </div>
                <div class="pattern-result-row2">
                    ${escapeHtml(m.industry || '--')} ·
                    ¥${(m.latest_close || 0).toFixed(2)} ·
                    <span style="color:${(m.latest_change_pct || 0) >= 0 ? 'var(--red)' : 'var(--green)'}">
                        ${(m.latest_change_pct || 0).toFixed(2)}%
                    </span>
                </div>
                <canvas class="pattern-result-spark" data-curve='${JSON.stringify(m.normalized_curve)}'></canvas>
            </div>
        `).join('');

        // 渲染 spark
        patternModal.resultsEl.querySelectorAll('.pattern-result-spark').forEach(c => {
            this._drawSpark(c, JSON.parse(c.dataset.curve));
        });
        // 点击行为
        patternModal.resultsEl.querySelectorAll('.pattern-result-item').forEach(el => {
            el.addEventListener('click', () => {
                const idx = parseInt(el.dataset.idx, 10);
                patternModal.resultsEl.querySelectorAll('.pattern-result-item').forEach(x =>
                    x.classList.remove('active'));
                el.classList.add('active');
                patternCompare.show(patternState.lastQueryCurve, patternState.lastResults[idx]);
            });
        });
    },

    _drawSpark(canvas, curve) {
        const ctx = canvas.getContext('2d');
        const rect = canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, rect.width, rect.height);
        ctx.strokeStyle = '#2563eb';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        curve.forEach((v, i) => {
            const x = (i / (curve.length - 1)) * rect.width;
            const y = rect.height - v * rect.height;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
    },
};

const patternState = { lastQueryCurve: null, lastResults: [] };

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
}

document.getElementById('patternSubmitBtn').addEventListener('click', () => {
    const curve = patternCanvas.getNormalizedCurve();
    patternSearch.submit(curve);
});
```

- [ ] **Step 2: 烟测**

Run（后台）: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui && python app.py &`

打开 `http://localhost:7070`，点击形态搜股 → 在画板画一条曲线 → 点击检索

确认：
1. 「正在检索...」短暂显示后被结果替换
2. 右侧出现股票列表，每项有代码、名称、分数、行业、价格、涨跌幅、迷你曲线
3. 点击列表项变成 active 状态（蓝底）

注：若指纹库为空，会显示「暂无匹配结果」。需先在 Task 8/10 跑过 build_all。

- [ ] **Step 3: 杀掉测试服务**

Run: `pkill -f 'webui/app.py' || true`

- [ ] **Step 4: 提交**

```bash
git add webui/templates/stock_analysis_home.html
git commit -m "feat: 形态搜股 - 实现检索调用与结果列表"
```

---

## Task 15: 前端 - 「选股票形态」Tab 输入与预览

**Files:**
- Modify: `webui/templates/stock_analysis_home.html`

- [ ] **Step 1: 在 patternSearch 模块之后追加 patternStockMode**

```javascript
// ===== 选股票形态 Tab =====
const patternStockMode = {
    input: document.getElementById('patternStockInput'),
    loadBtn: document.getElementById('patternStockLoadBtn'),
    submitBtn: document.getElementById('patternStockSubmitBtn'),
    previewEl: document.getElementById('patternStockPreview'),
    currentCurve: null,

    init() {
        this.loadBtn.addEventListener('click', () => this.loadPreview());
        this.submitBtn.addEventListener('click', () => {
            if (this.currentCurve) patternSearch.submit(this.currentCurve);
        });
        this.input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.loadPreview();
        });
    },

    async loadPreview() {
        const code = this.input.value.trim();
        if (!/^\d{6}$/.test(code)) {
            this.previewEl.className = 'pattern-stock-preview empty';
            this.previewEl.textContent = '请输入 6 位股票代码';
            this.submitBtn.disabled = true;
            return;
        }
        this.previewEl.className = 'pattern-stock-preview empty';
        this.previewEl.textContent = '加载中...';
        this.submitBtn.disabled = true;
        try {
            const res = await fetch('/api/pattern-search/stock-curve/' + code);
            if (!res.ok) {
                const data = await res.json();
                this.previewEl.textContent = data.message || '未找到该股的指纹数据';
                this.currentCurve = null;
                return;
            }
            const data = await res.json();
            this.currentCurve = data.normalized_curve;
            this._renderPreview(data);
            this.submitBtn.disabled = false;
        } catch (err) {
            this.previewEl.textContent = '加载失败：' + err;
            this.currentCurve = null;
        }
    },

    _renderPreview(data) {
        this.previewEl.className = 'pattern-stock-preview';
        this.previewEl.innerHTML = `
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                <strong>${data.stock_code} ${escapeHtml(data.stock_name || '')}</strong>
                <span class="muted">${escapeHtml(data.industry || '')} · ¥${(data.latest_close||0).toFixed(2)}</span>
            </div>
            <canvas id="patternStockPreviewSpark" style="width:100%; height:64px;"></canvas>
            <div class="muted" style="margin-top:4px;">基准日 ${data.snapshot_date}</div>
        `;
        const spark = document.getElementById('patternStockPreviewSpark');
        patternSearch._drawSpark(spark, data.normalized_curve);
    },
};
patternStockMode.init();
```

- [ ] **Step 2: 烟测**

Run（后台）: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui && python app.py &`

打开 Modal → 切换到「选股票形态」Tab → 输入指纹库中存在的代码 → 「载入预览」

确认：
1. 预览区显示股票名 + 行业 + 价格 + 30 点曲线
2. 「用该形态检索」按钮启用
3. 点击它 → 右侧出现 Top-30 结果

无效代码 → 提示 "未找到该股的指纹数据"

- [ ] **Step 3: 杀掉测试服务**

Run: `pkill -f 'webui/app.py' || true`

- [ ] **Step 4: 提交**

```bash
git add webui/templates/stock_analysis_home.html
git commit -m "feat: 形态搜股 - 实现以股找股 Tab"
```

---

## Task 16: 前端 - Plotly 对比图

**Files:**
- Modify: `webui/templates/stock_analysis_home.html`

- [ ] **Step 1: 确认 Plotly 已加载**

查找 `webui/templates/stock_analysis_home.html` 中是否引入 Plotly：

Run: `grep -n 'plotly' /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui/templates/stock_analysis_home.html`

若没找到，找到 `</head>` 之前添加（应该已有，仅在缺失时执行此步骤）：

```html
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js" charset="utf-8"></script>
```

- [ ] **Step 2: 实现 patternCompare 模块**

在 patternStockMode 之后追加：

```javascript
// ===== 对比图 =====
const patternCompare = {
    el: document.getElementById('patternCompare'),
    plotEl: document.getElementById('patternComparePlot'),
    titleEl: document.getElementById('patternCompareTitle'),

    show(userCurve, match) {
        if (!userCurve || !match) return;
        this.el.hidden = false;
        this.titleEl.textContent = `画板  vs  ${match.stock_code} ${match.stock_name || ''} · 相似度 ${match.score.toFixed(3)}`;
        const x = Array.from({ length: 30 }, (_, i) => i + 1);
        const data = [
            {
                x, y: userCurve,
                mode: 'lines+markers', name: '画板曲线',
                line: { color: '#2563eb', width: 2.5 },
                marker: { size: 4 },
            },
            {
                x, y: match.normalized_curve,
                mode: 'lines+markers', name: `${match.stock_code}`,
                line: { color: '#c2410c', width: 2.5, dash: 'dot' },
                marker: { size: 4 },
            },
        ];
        const layout = {
            margin: { t: 16, r: 12, b: 32, l: 36 },
            xaxis: { title: '采样点', gridcolor: '#e2e8f0' },
            yaxis: { title: '归一化值', range: [-0.05, 1.05], gridcolor: '#e2e8f0' },
            legend: { orientation: 'h', y: -0.25 },
            plot_bgcolor: '#fff', paper_bgcolor: '#fff',
            height: 220,
        };
        Plotly.newPlot(this.plotEl, data, layout, { displayModeBar: false, responsive: true });
    },
};
```

- [ ] **Step 3: 烟测对比图**

Run（后台）: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui && python app.py &`

打开 Modal → 画曲线 → 检索 → 点击列表中的某只股票

确认：
1. 左侧底部出现对比图区块
2. 蓝实线（画板曲线）+ 橙虚线（匹配股票）
3. 标题显示 "画板 vs 600977 中国电影 · 相似度 0.940"

- [ ] **Step 4: 杀掉测试服务**

Run: `pkill -f 'webui/app.py' || true`

- [ ] **Step 5: 提交**

```bash
git add webui/templates/stock_analysis_home.html
git commit -m "feat: 形态搜股 - 实现 Plotly 对比图"
```

---

## Task 17: 端到端烟测与文档收尾

**Files:**
- Modify: `webui/README.md`

- [ ] **Step 1: 在 webui/README.md 「✨ Features」中追加形态搜股说明**

找到 `webui/README.md` 第 5-21 行的 Features 列表，在适当位置追加：

```markdown
- **Pattern search canvas**: Top-bar button opens a full-screen modal — draw any close-price shape or pick a stock code to find the top-30 A-share stocks whose 30-day normalized close curves match best. Backed by a SQLite fingerprint cache (`data/pattern_fingerprints.db`).
```

- [ ] **Step 2: 在 README「📍 Web Routes」之后新增 "形态搜股" 操作说明**

在 `## 📋 Usage Steps` 中 `### Stock Analysis Home` 列表追加：

```markdown
6. 使用顶部 **形态搜股** 按钮打开 Modal，「手绘形态」画一条曲线或「选股票形态」输入代码 → 点击检索 → 右侧列出近 30 日形态最相似的 Top-30 股票；点击列表项可在下方查看曲线对比图。首次使用需点击 Modal 顶部「刷新指纹库」（约 10-15 分钟），之后每日 16:30 后台自动刷新。
```

- [ ] **Step 3: 跑一次完整后端测试**

Run: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python -m pytest tests/ -v`
Expected: 全部测试通过（约 20 项）

- [ ] **Step 4: 端到端手动烟测清单**

启动: `cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos/webui && python app.py &`

打开 `http://localhost:7070`，按顺序验证：

1. ✅ 顶部「形态搜股」按钮可见
2. ✅ 点击按钮，Modal 全屏弹出
3. ✅ Modal 顶部显示指纹库状态（数量、基准日）
4. ✅ 切换 Tab「手绘形态」可见画布
5. ✅ 画布上拖动鼠标可绘制笔迹
6. ✅ 30 点采样曲线（蓝色）实时叠加
7. ✅ 撤销/清空生效
8. ✅ 点击检索，右侧 Top-30 列表出现
9. ✅ 列表项含代码、名称、分数、行业、价格、迷你 spark
10. ✅ 点击列表项 → 左侧底部 Plotly 对比图展开
11. ✅ 切换到「选股票形态」Tab
12. ✅ 输入 6 位代码（库中存在）→ 载入预览 → 看到 sparkline
13. ✅ 「用该形态检索」按钮启用，点击后右侧出更新结果
14. ✅ Esc / 点击 Modal 外部 / 点 ✕ → 关闭 Modal
15. ✅ 点击「刷新指纹库」→ 弹出确认 → 取消 / 接受后看到「刷新中」状态

杀掉: `pkill -f 'webui/app.py' || true`

- [ ] **Step 5: 提交**

```bash
git add webui/README.md
git commit -m "docs: 形态搜股 - 更新 webui README"
```

---

## 部署提示（不在本计划任务范围内）

若要每日 16:30 自动刷新指纹库，添加 cron：

```bash
# crontab -e
30 16 * * 1-5 cd /Users/palmer/IdeaProjects/projectSync/AI/project/Kronos && python scripts/build_pattern_fingerprints.py >> logs/pattern_refresh.log 2>&1
```

或在项目已有的调度器中加入。

---

## 计划自审 Checklist

✅ Spec §3 架构 → Task 4-10 覆盖
✅ Spec §4 SQLite Schema → Task 4 完整实现
✅ Spec §5 算法 → Task 2-3 (TDD)
✅ Spec §6 4 个 API → Task 9-10
✅ Spec §7 Modal UI → Task 11-16
✅ Spec §8 后台刷新 → Task 8 + Task 10
✅ Spec §9 边界条件（ST 过滤、停牌跳过、空库提示）→ Task 5/8/12
✅ Spec §10 测试 → 每个 Task 都有 TDD 步骤
✅ 无 TBD / TODO / 占位符
✅ 函数命名一致（pattern_normalize_curve / search_similar / etc.）
✅ 每个步骤都有完整代码或具体命令
