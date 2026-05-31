# 个股深度挖掘 M1 (Foundation) Implementation Plan

> **实施状态（2026-05-29 复核）：代码与测试已全部落地并入库。**
> - ✅ Phase A–D（数据层 / 业务层 / 编排 payload / 诊断端点）：全部代码与单元测试已完成，相关 58 个用例全绿（`pytest tests/test_schema_migration_v6.py tests/test_institutional_repos.py tests/test_akshare_adapter.py tests/test_quant_seat_registry.py tests/test_institutional_providers.py tests/test_stock_analysis_suite.py tests/test_robyn_app.py`）。全量 156 用例通过。
> - ✅ Phase E（前端 12 Tab 重排 + 4 个 render 函数 + radar 2 轴）：代码已落地于 `webui/templates/desktop.html` / `webui/static/kronos_desktop.css`。
> - ⚠️ **遗留：Phase E/F 的「手动浏览器冒烟 + 截图归档」未执行** —— `docs/screenshots/2026-05-28-deep-mining/` 目前仅有 `README.md` 索引，缺实际 PNG。下个迭代补做手动 smoke 与截图后即可关闭 M1。
> - 🛠 修复：本次发现 SQLite 迁移期遗漏入库的 `data_store/connection.py`、各 repo、整个 `webui/services/` 包及多份测试（已被 HEAD 中已提交代码 import 却从未 `git add`），现已全部纳入版本控制，干净检出导入校验通过。
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地个股深度挖掘的全栈骨架 —— `AkshareAdapter` + 6 张 SQLite 表 + `analysis/institutional/` 包（含 6 个返回 `unavailable` 的 provider 骨架与量化席位注册表）+ payload schema 扩展 + 前端 Tab 11→12 重排 + 4 个新 render 函数。本期不实现真实数据抓取与业务规则，只搭骨架并让 4 个新 Tab 用 `data_status="unavailable"` 渲染降级 UI。

**Architecture:** 三层。**数据层**：`data_store/akshare_adapter.py` 单一对外取数入口（fallback + 限流 + 熔断），`data_store/schema.py` 增 migration v6（6 张业务表 + sync_log），各表配模块级 repo（参考 `moneyflow_repo.py` 风格）。**业务层**：`analysis/institutional/` 包，每个 provider 通过 `BaseProvider.get()` 返回统一 `ProviderResult[T]`，骨架阶段全部返回 `unavailable`；`QuantSeatRegistry` 从 `config/quant_seats.json` 热加载。**编排+前端层**：`StockAnalysisSuite._collect_inputs` 注入 6 个 provider，payload 顶层增 4 个 key（`main_force_deep / institutional_holdings / chip_control / quant_matrix`）+ overview.radar 增 2 轴；`webui/templates/desktop.html` 重排 Tab 并新增 4 个 render 函数。

**Tech Stack:** Python 3.13, sqlite3（项目自带 `data_store.connection`）, pandas, akshare（仅在 adapter 测试中 stub）, Robyn, Jinja2, ECharts（前端已加载）, pytest（已配置 `tests/conftest.py`）。

**Spec 参考:** `docs/superpowers/specs/2026-05-28-individual-stock-deep-mining-design.md`（commit `83e7233`）

**本计划范围（M1 only）:**

- ✅ `AkshareAdapter` + 限流/重试/熔断 + 单元测试（用 stub client_factory）
- ✅ Migration v6（6 张表 + sync_log）+ 6 个 repo
- ✅ `analysis/institutional/` 包：`base.py` / `quant_seat_registry.py` / 6 个 provider 骨架
- ✅ `config/quant_seats.json` 初版（含 5 高置信 + 2 中置信席位示例）
- ✅ `StockAnalysisSuite` payload 扩展（4 新顶层 key + 2 新 radar 轴，骨架阶段全 unavailable）
- ✅ 前端 Tab nav 重排 11→12 + 4 个新 render 函数（unavailable 分支）
- ✅ `GET /api/diagnostics/data-sources` 端点（从 `sync_log` 读取最近 24h 摘要）

**不在本计划范围（留给后续计划）:**

- ❌ 真实 akshare 数据抓取（M2）—— provider 骨架的 `_fetch_*` 方法只 raise NotImplementedError
- ❌ `scripts/sync_institutional_data.py` 隔夜批（M2）
- ❌ `stage_classifier` + `quant_signature_detector`（M3）
- ❌ 30 模型 → 信号矩阵 + 历史命中率（M4）
- ❌ 风控 `hidden_risks` 联动 + `scenario_probability` 融合（M5）
- ❌ Playwright 前端冒烟（spec §4.4 已明示暂不引入）

---

## 文件结构概览

### Create

**数据层**
- `data_store/akshare_adapter.py` — `AkshareAdapter` 类（fallback chain / 限流 / 熔断）
- `data_store/dragon_tiger_repo.py` — 龙虎榜机构席位 repo
- `data_store/hsgt_repo.py` — 陆股通个股持股 repo
- `data_store/holders_repo.py` — Top10 流通股东 + 股东户数（同一业务域，共一个模块）
- `data_store/survey_repo.py` — 机构调研 repo
- `data_store/fund_hold_repo.py` — 重仓基金 repo
- `data_store/sync_log_repo.py` — 同步日志 repo（供诊断端点使用）

**业务层**
- `analysis/institutional/__init__.py` — 导出 `BaseProvider`, `ProviderResult`, 6 provider 类
- `analysis/institutional/base.py` — `ProviderResult[T]` dataclass + `BaseProvider` ABC
- `analysis/institutional/quant_seat_registry.py` — JSON 热加载注册表
- `analysis/institutional/lhb_provider.py` — `LhbProvider` 骨架
- `analysis/institutional/hsgt_provider.py` — `HsgtProvider` 骨架
- `analysis/institutional/holders_provider.py` — `HoldersProvider` 骨架（含 Top10 + 户数）
- `analysis/institutional/survey_provider.py` — `SurveyProvider` 骨架
- `analysis/institutional/fund_holdings_provider.py` — `FundHoldingsProvider` 骨架
- `analysis/institutional/cyq_provider.py` — `CyqProvider` 骨架

**配置**
- `config/quant_seats.json` — 量化席位初版名单

**测试**
- `tests/test_akshare_adapter.py`
- `tests/test_institutional_repos.py`（合并 6 个 repo 的测试）
- `tests/test_institutional_providers.py`（合并 6 个 provider 骨架的测试）
- `tests/test_quant_seat_registry.py`
- `tests/test_schema_migration_v6.py`

### Modify

- `data_store/schema.py` — 在 `_MIGRATIONS` 列表追加 `(6, ...)`
- `data_store/__init__.py` — 暴露新 repo 模块
- `analysis/stock_analysis_suite.py` — 注入 6 provider + 在 `_collect_inputs` 与 payload 组装中产出 4 个新顶层 key + 2 个 radar 轴
- `webui/templates/desktop.html` — Tab nav 11→12 重排 + 4 个新 render 函数 + dispatch switch 扩展
- `webui/static/kronos_desktop.css` — `.quant-seat-pill` / `.suite-kpi-bar` / `.suite-stage-axis` / `.suite-unavailable-banner` 等样式
- `webui/robyn_app.py` — 注册 `GET /api/diagnostics/data-sources`
- `tests/test_stock_analysis_suite.py` — 追加 4 个新顶层 key 与 radar 轴的断言
- `tests/test_robyn_app.py` — 追加 `/api/diagnostics/data-sources` 测试

---

## Phase A — 数据层骨架（TDD）

### Task 1: Migration v6 — 6 张业务表 + sync_log

**Files:**
- Modify: `data_store/schema.py`
- Create: `tests/test_schema_migration_v6.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_schema_migration_v6.py
"""验证 migration v6 建出 7 张新表，schema_version 推进到 6。"""
from __future__ import annotations

import sqlite3
import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    yield c
    c.close()


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def test_v6_creates_seven_new_tables(conn):
    final = migrate(conn)
    assert final == 6
    for tbl in (
        "dragon_tiger_inst",
        "hsgt_individual",
        "top10_floatholders",
        "stk_holdernumber",
        "jgdy_detail",
        "fund_hold_detail",
        "sync_log",
    ):
        assert _table_exists(conn, tbl), f"{tbl} not created"


def test_v6_idempotent(conn):
    migrate(conn)
    assert migrate(conn) == 6  # 二次运行不报错也不重复 insert version


def test_dragon_tiger_inst_columns(conn):
    migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dragon_tiger_inst)")}
    expected = {
        "ts_code", "trade_date", "inst_name", "side",
        "net_amount", "buy_amount", "sell_amount",
        "is_quant", "quant_confidence", "reason",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_dragon_tiger_inst_indexes(conn):
    migrate(conn)
    idxs = {r[1] for r in conn.execute("PRAGMA index_list(dragon_tiger_inst)")}
    assert "idx_lhbi_code_date" in idxs
    assert "idx_lhbi_quant" in idxs
```

- [ ] **Step 2: Run test — 应失败**

Run: `pytest tests/test_schema_migration_v6.py -v`
Expected: 4 个 case FAIL（migrate 返回 5 而非 6，新表不存在）

- [ ] **Step 3: 实现 migration v6**

在 `data_store/schema.py` 的 `_MIGRATIONS` 列表末尾追加：

```python
    (
        6,
        # 个股深度挖掘：龙虎榜机构席位 / 陆股通持股 / Top10 流通股东 /
        # 股东户数 / 机构调研 / 重仓基金 / 同步日志
        """
        CREATE TABLE IF NOT EXISTS dragon_tiger_inst (
          ts_code          TEXT NOT NULL,
          trade_date       TEXT NOT NULL,
          inst_name        TEXT NOT NULL,
          side             TEXT NOT NULL,
          net_amount       REAL,
          buy_amount       REAL,
          sell_amount      REAL,
          is_quant         INTEGER DEFAULT 0,
          quant_confidence TEXT,
          reason           TEXT,
          PRIMARY KEY (ts_code, trade_date, inst_name, side)
        );
        CREATE INDEX IF NOT EXISTS idx_lhbi_code_date
          ON dragon_tiger_inst(ts_code, trade_date);
        CREATE INDEX IF NOT EXISTS idx_lhbi_quant
          ON dragon_tiger_inst(is_quant, trade_date);

        CREATE TABLE IF NOT EXISTS hsgt_individual (
          ts_code     TEXT NOT NULL,
          trade_date  TEXT NOT NULL,
          hold_vol    REAL,
          hold_ratio  REAL,
          market_cap  REAL,
          PRIMARY KEY (ts_code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS top10_floatholders (
          ts_code       TEXT NOT NULL,
          end_date      TEXT NOT NULL,
          holder_rank   INTEGER NOT NULL,
          holder_name   TEXT NOT NULL,
          hold_amount   REAL,
          hold_ratio    REAL,
          change_type   TEXT,
          change_amount REAL,
          PRIMARY KEY (ts_code, end_date, holder_rank)
        );

        CREATE TABLE IF NOT EXISTS stk_holdernumber (
          ts_code     TEXT NOT NULL,
          end_date    TEXT NOT NULL,
          holder_num  INTEGER,
          avg_hold    REAL,
          pct_change  REAL,
          PRIMARY KEY (ts_code, end_date)
        );

        CREATE TABLE IF NOT EXISTS jgdy_detail (
          ts_code      TEXT NOT NULL,
          survey_date  TEXT NOT NULL,
          inst_name    TEXT NOT NULL,
          reception    TEXT,
          topic        TEXT,
          PRIMARY KEY (ts_code, survey_date, inst_name)
        );

        CREATE TABLE IF NOT EXISTS fund_hold_detail (
          ts_code      TEXT NOT NULL,
          end_date     TEXT NOT NULL,
          fund_code    TEXT NOT NULL,
          fund_name    TEXT,
          hold_shares  REAL,
          market_value REAL,
          nv_ratio     REAL,
          PRIMARY KEY (ts_code, end_date, fund_code)
        );

        CREATE TABLE IF NOT EXISTS sync_log (
          source    TEXT NOT NULL,
          ts_code   TEXT NOT NULL DEFAULT '',
          ran_at    TEXT NOT NULL,
          status    TEXT NOT NULL,
          rows      INTEGER,
          error     TEXT,
          PRIMARY KEY (source, ts_code, ran_at)
        );
        CREATE INDEX IF NOT EXISTS idx_synclog_source_ran
          ON sync_log(source, ran_at DESC);
        """,
    ),
```

> 注：`sync_log.ts_code` 设为 `NOT NULL DEFAULT ''`，避免 SQLite 主键 NULL 语义引起去重失败。

- [ ] **Step 4: Run test 验证通过**

Run: `pytest tests/test_schema_migration_v6.py -v`
Expected: 4 个 case PASS

- [ ] **Step 5: 跑全量回归确保旧 migration 未被破坏**

Run: `pytest tests/test_data_store.py tests/test_calendar_daily_basic.py tests/test_moneyflow_kv_snapshot.py tests/test_sentiment_repo.py tests/test_ohlcv_repo.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add data_store/schema.py tests/test_schema_migration_v6.py
git commit -m "feat(data_store): migration v6 新增 6 张机构/龙虎榜/控盘表 + sync_log"
```

---

### Task 2: 6 张表的 Repo 层

**Files:**
- Create: `data_store/dragon_tiger_repo.py`
- Create: `data_store/hsgt_repo.py`
- Create: `data_store/holders_repo.py`（含 Top10 + 户数两组函数）
- Create: `data_store/survey_repo.py`
- Create: `data_store/fund_hold_repo.py`
- Create: `data_store/sync_log_repo.py`
- Modify: `data_store/__init__.py`
- Create: `tests/test_institutional_repos.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_institutional_repos.py
"""6 个 institutional repo 的 upsert / get / latest 行为。"""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    migrate(c)

    # 用 monkeypatch 替换全局 get_conn，让 repo 模块走该 conn
    from data_store import connection
    monkeypatch.setattr(connection, "get_conn", lambda: c)
    yield c
    c.close()


def test_dragon_tiger_repo_upsert_and_get(conn):
    from data_store import dragon_tiger_repo as dt

    rows = [
        {"ts_code": "000001.SZ", "trade_date": "2026-05-27", "inst_name": "X 营业部",
         "side": "buy", "net_amount": 1.2e8, "buy_amount": 1.5e8, "sell_amount": 3e7,
         "is_quant": 1, "quant_confidence": "high", "reason": "日涨幅 7%"},
        {"ts_code": "000001.SZ", "trade_date": "2026-05-27", "inst_name": "Y 营业部",
         "side": "sell", "net_amount": -5e7, "buy_amount": 1e7, "sell_amount": 6e7,
         "is_quant": 0, "quant_confidence": None, "reason": "日涨幅 7%"},
    ]
    n = dt.upsert_rows(rows)
    assert n == 2

    df = dt.get_by_code("000001.SZ")
    assert len(df) == 2
    assert set(df["inst_name"]) == {"X 营业部", "Y 营业部"}

    # 幂等：再 upsert 一次仍是 2 行
    dt.upsert_rows(rows)
    df2 = dt.get_by_code("000001.SZ")
    assert len(df2) == 2


def test_hsgt_repo_latest(conn):
    from data_store import hsgt_repo

    hsgt_repo.upsert_rows([
        {"ts_code": "000001.SZ", "trade_date": "2026-05-25",
         "hold_vol": 1.0e8, "hold_ratio": 5.1, "market_cap": 1.2e10},
        {"ts_code": "000001.SZ", "trade_date": "2026-05-27",
         "hold_vol": 1.1e8, "hold_ratio": 5.4, "market_cap": 1.3e10},
    ])
    latest = hsgt_repo.latest("000001.SZ")
    assert latest["trade_date"] == "2026-05-27"
    assert latest["hold_ratio"] == 5.4


def test_holders_repo_top10_and_holdernumber(conn):
    from data_store import holders_repo

    holders_repo.upsert_top10([
        {"ts_code": "000001.SZ", "end_date": "2026-03-31", "holder_rank": 1,
         "holder_name": "公募 A", "hold_amount": 1e8, "hold_ratio": 6.2,
         "change_type": "add", "change_amount": 2e7},
    ])
    df = holders_repo.get_top10("000001.SZ", "2026-03-31")
    assert len(df) == 1 and df.iloc[0]["holder_name"] == "公募 A"

    holders_repo.upsert_holdernumber([
        {"ts_code": "000001.SZ", "end_date": "2026-03-31",
         "holder_num": 50000, "avg_hold": 1234.5, "pct_change": -3.2},
    ])
    latest = holders_repo.latest_holdernumber("000001.SZ")
    assert latest["holder_num"] == 50000


def test_survey_repo_recent(conn):
    from data_store import survey_repo

    survey_repo.upsert_rows([
        {"ts_code": "000001.SZ", "survey_date": "2026-05-20",
         "inst_name": "公募 A", "reception": "董秘", "topic": "AI 业务"},
        {"ts_code": "000001.SZ", "survey_date": "2026-05-10",
         "inst_name": "私募 B", "reception": "证代", "topic": "Q1 业绩"},
    ])
    df = survey_repo.get_by_code("000001.SZ", since="2026-05-15")
    assert len(df) == 1
    assert df.iloc[0]["inst_name"] == "公募 A"


def test_fund_hold_repo_upsert(conn):
    from data_store import fund_hold_repo

    fund_hold_repo.upsert_rows([
        {"ts_code": "000001.SZ", "end_date": "2026-03-31",
         "fund_code": "001234", "fund_name": "易方达蓝筹",
         "hold_shares": 1e7, "market_value": 1.5e8, "nv_ratio": 3.4},
    ])
    df = fund_hold_repo.get_by_code("000001.SZ", "2026-03-31")
    assert len(df) == 1


def test_sync_log_repo_recent_summary(conn):
    from data_store import sync_log_repo

    sync_log_repo.append("lhb", "000001.SZ", "2026-05-27T17:31:00", "ok", rows=42)
    sync_log_repo.append("lhb", "", "2026-05-27T17:32:00", "failed", error="429")
    summary = sync_log_repo.summary_last_24h(now_iso="2026-05-28T09:00:00")
    assert summary["lhb"]["ok"] == 1
    assert summary["lhb"]["failed"] == 1
```

- [ ] **Step 2: Run test 验证全部失败**

Run: `pytest tests/test_institutional_repos.py -v`
Expected: 6 个 case FAIL（ImportError，模块不存在）

- [ ] **Step 3: 实现 6 个 repo 模块**

每个 repo 走模块级函数风格（参考 `data_store/moneyflow_repo.py`）。

```python
# data_store/dragon_tiger_repo.py
"""龙虎榜机构席位 repo（含量化席位标记）。"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from data_store.connection import get_conn


_FIELDS = (
    "ts_code", "trade_date", "inst_name", "side",
    "net_amount", "buy_amount", "sell_amount",
    "is_quant", "quant_confidence", "reason",
)


def upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _FIELDS
        if c not in ("ts_code", "trade_date", "inst_name", "side")
    )
    values = [tuple(_to_native(r.get(c)) for c in _FIELDS) for r in rows]
    cur = get_conn().executemany(
        f"""
        INSERT INTO dragon_tiger_inst({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT(ts_code, trade_date, inst_name, side) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount is not None else len(rows)


def get_by_code(ts_code: str, since: str | None = None,
                limit: int | None = None) -> pd.DataFrame:
    sql = f"SELECT {','.join(_FIELDS)} FROM dragon_tiger_inst WHERE ts_code=?"
    params: list = [str(ts_code)]
    if since:
        sql += " AND trade_date >= ?"
        params.append(str(since))
    sql += " ORDER BY trade_date DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return pd.read_sql_query(sql, get_conn(), params=tuple(params))


def latest(ts_code: str) -> dict | None:
    row = get_conn().execute(
        f"SELECT {','.join(_FIELDS)} FROM dragon_tiger_inst "
        "WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
        (str(ts_code),),
    ).fetchone()
    return dict(zip(_FIELDS, row)) if row else None


def _to_native(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, float, str)):
        return v
    return str(v)
```

```python
# data_store/hsgt_repo.py
"""陆股通个股持股 repo。"""
from __future__ import annotations

import pandas as pd

from data_store.connection import get_conn

_FIELDS = ("ts_code", "trade_date", "hold_vol", "hold_ratio", "market_cap")


def upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _FIELDS if c not in ("ts_code", "trade_date")
    )
    values = [tuple(_to_native(r.get(c)) for c in _FIELDS) for r in rows]
    cur = get_conn().executemany(
        f"""
        INSERT INTO hsgt_individual({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT(ts_code, trade_date) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount is not None else len(rows)


def get_by_code(ts_code: str, since: str | None = None) -> pd.DataFrame:
    sql = f"SELECT {','.join(_FIELDS)} FROM hsgt_individual WHERE ts_code=?"
    params: list = [str(ts_code)]
    if since:
        sql += " AND trade_date >= ?"
        params.append(str(since))
    sql += " ORDER BY trade_date DESC"
    return pd.read_sql_query(sql, get_conn(), params=tuple(params))


def latest(ts_code: str) -> dict | None:
    row = get_conn().execute(
        f"SELECT {','.join(_FIELDS)} FROM hsgt_individual "
        "WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
        (str(ts_code),),
    ).fetchone()
    return dict(zip(_FIELDS, row)) if row else None


def _to_native(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, float, str)):
        return v
    return str(v)
```

```python
# data_store/holders_repo.py
"""Top10 流通股东 + 股东户数 repo（同一业务域）。"""
from __future__ import annotations

import pandas as pd

from data_store.connection import get_conn

_TOP10_FIELDS = (
    "ts_code", "end_date", "holder_rank", "holder_name",
    "hold_amount", "hold_ratio", "change_type", "change_amount",
)
_HOLDERNUM_FIELDS = ("ts_code", "end_date", "holder_num", "avg_hold", "pct_change")


def upsert_top10(rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_TOP10_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _TOP10_FIELDS
        if c not in ("ts_code", "end_date", "holder_rank")
    )
    values = [tuple(_to_native(r.get(c)) for c in _TOP10_FIELDS) for r in rows]
    cur = get_conn().executemany(
        f"""
        INSERT INTO top10_floatholders({",".join(_TOP10_FIELDS)}) VALUES({placeholders})
        ON CONFLICT(ts_code, end_date, holder_rank) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount is not None else len(rows)


def get_top10(ts_code: str, end_date: str) -> pd.DataFrame:
    return pd.read_sql_query(
        f"SELECT {','.join(_TOP10_FIELDS)} FROM top10_floatholders "
        "WHERE ts_code=? AND end_date=? ORDER BY holder_rank ASC",
        get_conn(),
        params=(str(ts_code), str(end_date)),
    )


def latest_top10(ts_code: str) -> tuple[str | None, pd.DataFrame]:
    row = get_conn().execute(
        "SELECT MAX(end_date) FROM top10_floatholders WHERE ts_code=?",
        (str(ts_code),),
    ).fetchone()
    end_date = row[0] if row else None
    if not end_date:
        return None, pd.DataFrame(columns=_TOP10_FIELDS)
    return end_date, get_top10(ts_code, end_date)


def upsert_holdernumber(rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_HOLDERNUM_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _HOLDERNUM_FIELDS if c not in ("ts_code", "end_date")
    )
    values = [tuple(_to_native(r.get(c)) for c in _HOLDERNUM_FIELDS) for r in rows]
    cur = get_conn().executemany(
        f"""
        INSERT INTO stk_holdernumber({",".join(_HOLDERNUM_FIELDS)}) VALUES({placeholders})
        ON CONFLICT(ts_code, end_date) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount is not None else len(rows)


def get_holdernumber_history(ts_code: str) -> pd.DataFrame:
    return pd.read_sql_query(
        f"SELECT {','.join(_HOLDERNUM_FIELDS)} FROM stk_holdernumber "
        "WHERE ts_code=? ORDER BY end_date ASC",
        get_conn(),
        params=(str(ts_code),),
    )


def latest_holdernumber(ts_code: str) -> dict | None:
    row = get_conn().execute(
        f"SELECT {','.join(_HOLDERNUM_FIELDS)} FROM stk_holdernumber "
        "WHERE ts_code=? ORDER BY end_date DESC LIMIT 1",
        (str(ts_code),),
    ).fetchone()
    return dict(zip(_HOLDERNUM_FIELDS, row)) if row else None


def _to_native(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, float, str)):
        return v
    return str(v)
```

```python
# data_store/survey_repo.py
"""机构调研 repo。"""
from __future__ import annotations

import pandas as pd

from data_store.connection import get_conn

_FIELDS = ("ts_code", "survey_date", "inst_name", "reception", "topic")


def upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _FIELDS
        if c not in ("ts_code", "survey_date", "inst_name")
    )
    values = [tuple(_to_native(r.get(c)) for c in _FIELDS) for r in rows]
    cur = get_conn().executemany(
        f"""
        INSERT INTO jgdy_detail({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT(ts_code, survey_date, inst_name) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount is not None else len(rows)


def get_by_code(ts_code: str, since: str | None = None,
                limit: int | None = None) -> pd.DataFrame:
    sql = f"SELECT {','.join(_FIELDS)} FROM jgdy_detail WHERE ts_code=?"
    params: list = [str(ts_code)]
    if since:
        sql += " AND survey_date >= ?"
        params.append(str(since))
    sql += " ORDER BY survey_date DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return pd.read_sql_query(sql, get_conn(), params=tuple(params))


def _to_native(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, float, str)):
        return v
    return str(v)
```

```python
# data_store/fund_hold_repo.py
"""重仓基金 repo。"""
from __future__ import annotations

import pandas as pd

from data_store.connection import get_conn

_FIELDS = (
    "ts_code", "end_date", "fund_code", "fund_name",
    "hold_shares", "market_value", "nv_ratio",
)


def upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _FIELDS
        if c not in ("ts_code", "end_date", "fund_code")
    )
    values = [tuple(_to_native(r.get(c)) for c in _FIELDS) for r in rows]
    cur = get_conn().executemany(
        f"""
        INSERT INTO fund_hold_detail({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT(ts_code, end_date, fund_code) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount is not None else len(rows)


def get_by_code(ts_code: str, end_date: str) -> pd.DataFrame:
    return pd.read_sql_query(
        f"SELECT {','.join(_FIELDS)} FROM fund_hold_detail "
        "WHERE ts_code=? AND end_date=? ORDER BY market_value DESC",
        get_conn(),
        params=(str(ts_code), str(end_date)),
    )


def latest_period(ts_code: str) -> str | None:
    row = get_conn().execute(
        "SELECT MAX(end_date) FROM fund_hold_detail WHERE ts_code=?",
        (str(ts_code),),
    ).fetchone()
    return row[0] if row and row[0] else None


def _to_native(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, float, str)):
        return v
    return str(v)
```

```python
# data_store/sync_log_repo.py
"""同步任务日志 repo（供 /api/diagnostics/data-sources 使用）。"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from data_store.connection import get_conn

_FIELDS = ("source", "ts_code", "ran_at", "status", "rows", "error")


def append(source: str, ts_code: str, ran_at: str, status: str,
           rows: int | None = None, error: str | None = None) -> None:
    get_conn().execute(
        f"""
        INSERT INTO sync_log({",".join(_FIELDS)}) VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, ts_code, ran_at) DO UPDATE SET
          status=excluded.status, rows=excluded.rows, error=excluded.error
        """,
        (source, ts_code or "", ran_at, status, rows, error),
    )


def summary_last_24h(now_iso: Optional[str] = None) -> dict:
    """Return {source: {ok: n, partial: n, failed: n, last_ok: iso}}."""
    now = _dt.datetime.fromisoformat(now_iso) if now_iso else _dt.datetime.now()
    since = (now - _dt.timedelta(hours=24)).isoformat(timespec="seconds")
    rows = get_conn().execute(
        "SELECT source, status, ran_at FROM sync_log WHERE ran_at >= ?",
        (since,),
    ).fetchall()
    out: dict = {}
    for source, status, ran_at in rows:
        bucket = out.setdefault(source, {"ok": 0, "partial": 0, "failed": 0, "last_ok": None})
        bucket[status] = bucket.get(status, 0) + 1
        if status == "ok" and (bucket["last_ok"] is None or ran_at > bucket["last_ok"]):
            bucket["last_ok"] = ran_at
    return out
```

- [ ] **Step 4: 修改 `data_store/__init__.py` 暴露新 repo**

在 `__all__` 列表末尾扩展：

```python
"""SQLite-backed business data store.

Public surface:
- `data_store.connection.get_conn()` — process-wide thread-local connection
- repo singletons: OHLCV_REPO, SENTIMENT_REPO, DAILY_BASIC_REPO,
  CALENDAR_REPO, MONEYFLOW_REPO, KV_REPO (added by phases P1-P4)
- institutional repos (P6): dragon_tiger_repo, hsgt_repo, holders_repo,
  survey_repo, fund_hold_repo, sync_log_repo

DB path defaults to `data/kronos_data.sqlite`; override with `KRONOS_SQLITE_PATH`.
"""
from data_store.connection import get_conn, close_conn, db_path
from data_store.schema import migrate
from data_store import (
    dragon_tiger_repo,
    hsgt_repo,
    holders_repo,
    survey_repo,
    fund_hold_repo,
    sync_log_repo,
)

__all__ = [
    "get_conn", "close_conn", "db_path", "migrate",
    "dragon_tiger_repo", "hsgt_repo", "holders_repo",
    "survey_repo", "fund_hold_repo", "sync_log_repo",
]
```

- [ ] **Step 5: Run test 验证通过**

Run: `pytest tests/test_institutional_repos.py -v`
Expected: 6 个 case PASS

- [ ] **Step 6: Commit**

```bash
git add data_store/dragon_tiger_repo.py data_store/hsgt_repo.py \
        data_store/holders_repo.py data_store/survey_repo.py \
        data_store/fund_hold_repo.py data_store/sync_log_repo.py \
        data_store/__init__.py tests/test_institutional_repos.py
git commit -m "feat(data_store): 6 张机构表的 repo 层（upsert/get/latest + sync_log 摘要）"
```

---

### Task 3: AkshareAdapter — fallback + 限流 + 熔断

**Files:**
- Create: `data_store/akshare_adapter.py`
- Create: `tests/test_akshare_adapter.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_akshare_adapter.py
"""AkshareAdapter 的 fallback、限流、熔断行为。"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from data_store.akshare_adapter import (
    AkshareAdapter,
    AkshareUnavailable,
)


class _StubClient:
    """模拟 akshare 客户端：按函数名分发，每个函数可设置返回值或异常。"""

    def __init__(self, behaviors: dict):
        # behaviors[fn_name] = "ok" / "raise" / Exception 实例 / DataFrame
        self.behaviors = behaviors
        self.call_log: list[str] = []

    def __getattr__(self, name):
        def _call(*args, **kwargs):
            self.call_log.append(name)
            beh = self.behaviors.get(name, "ok")
            if isinstance(beh, BaseException):
                raise beh
            if beh == "raise":
                raise RuntimeError(f"stub raise from {name}")
            if isinstance(beh, pd.DataFrame):
                return beh
            return pd.DataFrame({"col": [1]})
        return _call


def test_primary_source_success_no_fallback():
    stub = _StubClient({"stock_lhb_detail_em": pd.DataFrame({"x": [1, 2]})})
    adapter = AkshareAdapter(client_factory=lambda: stub, rate_limit_per_min=999)
    df = adapter.fetch("lhb_detail", symbol="000001")
    assert len(df) == 2
    assert stub.call_log == ["stock_lhb_detail_em"]


def test_fallback_chain_triggered_on_primary_failure():
    stub = _StubClient({
        "stock_lhb_detail_em": "raise",
        "stock_lhb_detail_daily_sina": pd.DataFrame({"y": [9]}),
    })
    adapter = AkshareAdapter(client_factory=lambda: stub, rate_limit_per_min=999)
    df = adapter.fetch("lhb_detail")
    assert df.iloc[0]["y"] == 9
    assert stub.call_log == ["stock_lhb_detail_em", "stock_lhb_detail_daily_sina"]


def test_all_sources_fail_raises_unavailable():
    stub = _StubClient({
        "stock_lhb_detail_em": "raise",
        "stock_lhb_detail_daily_sina": "raise",
    })
    adapter = AkshareAdapter(client_factory=lambda: stub, rate_limit_per_min=999)
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("lhb_detail")


def test_unknown_key_raises_keyerror():
    adapter = AkshareAdapter(client_factory=lambda: _StubClient({}))
    with pytest.raises(KeyError):
        adapter.fetch("not_a_key")


def test_circuit_breaker_opens_after_failure_window(monkeypatch):
    """全链路失败后进入 5 分钟熔断，期间直接 raise AkshareUnavailable
    且不再调用 client。"""
    stub = _StubClient({
        "stock_lhb_detail_em": "raise",
        "stock_lhb_detail_daily_sina": "raise",
    })
    fake_now = {"t": 0.0}
    monkeypatch.setattr(
        "data_store.akshare_adapter._now",
        lambda: fake_now["t"],
    )
    adapter = AkshareAdapter(
        client_factory=lambda: stub,
        rate_limit_per_min=999,
        breaker_cooldown_sec=300,
    )
    # 第一次：触发熔断
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("lhb_detail")
    n1 = len(stub.call_log)
    # 第二次（熔断窗口内）：直接 raise，不调用 client
    fake_now["t"] = 30.0
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("lhb_detail")
    assert len(stub.call_log) == n1
    # 熔断过期后：重新尝试
    fake_now["t"] = 400.0
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("lhb_detail")
    assert len(stub.call_log) > n1


def test_rate_limit_blocks_excess_requests(monkeypatch):
    """rate_limit_per_min=2 时，第三次请求应触发 sleep。"""
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "data_store.akshare_adapter._sleep",
        lambda s: sleep_calls.append(s),
    )
    fake_now = {"t": 0.0}
    monkeypatch.setattr(
        "data_store.akshare_adapter._now",
        lambda: fake_now["t"],
    )

    stub = _StubClient({"stock_lhb_detail_em": pd.DataFrame({"a": [1]})})
    adapter = AkshareAdapter(client_factory=lambda: stub, rate_limit_per_min=2)

    adapter.fetch("lhb_detail")  # t=0
    adapter.fetch("lhb_detail")  # t=0
    assert sleep_calls == []
    adapter.fetch("lhb_detail")  # t=0，应该触发限流 sleep
    assert sleep_calls and sleep_calls[0] > 0
```

- [ ] **Step 2: Run test 验证全失败**

Run: `pytest tests/test_akshare_adapter.py -v`
Expected: 6 个 case 全部 FAIL（模块不存在）

- [ ] **Step 3: 实现 AkshareAdapter**

```python
# data_store/akshare_adapter.py
"""统一 akshare 取数适配器（fallback / 限流 / 熔断）。

provider 层不直接 import akshare —— 通过 AkshareAdapter.fetch(key, *args, **kwargs)。
失败时按 FALLBACK_CHAINS[key] 依次试，全失败抛 AkshareUnavailable，并对该 key
开启 5 分钟熔断窗口。
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

logger = logging.getLogger(__name__)


class AkshareUnavailable(RuntimeError):
    """所有 fallback 源均失败 / 熔断窗口内。"""


@dataclass
class _BreakerState:
    opened_at: float = 0.0


def _now() -> float:
    return time.time()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _default_client_factory():
    import akshare as ak
    return ak


class AkshareAdapter:
    """单一 akshare 取数入口。"""

    FALLBACK_CHAINS: dict[str, list[str]] = {
        "lhb_detail":   ["stock_lhb_detail_em", "stock_lhb_detail_daily_sina"],
        "lhb_jgmm":     ["stock_lhb_jgmmtj_em"],
        "hsgt_hold":    ["stock_hsgt_hold_stock_em", "stock_hsgt_individual_em"],
        "top10_float":  ["stock_circulate_stock_holder", "stock_main_stock_holder"],
        "gdhs":         ["stock_zh_a_gdhs_detail_em", "stock_zh_a_gdhs"],
        "jgdy":         ["stock_jgdy_detail_em"],
        "fund_hold":    ["stock_report_fund_hold_detail"],
        "cyq":          ["stock_cyq_em"],
        "minute":       ["stock_zh_a_minute", "stock_zh_a_hist_min_em"],
    }

    def __init__(
        self,
        client_factory: Callable[[], object] | None = None,
        rate_limit_per_min: int = 30,
        breaker_cooldown_sec: int = 300,
        retry_per_source: int = 2,
    ):
        self._client_factory = client_factory or _default_client_factory
        self._client = None
        self._rate_limit = rate_limit_per_min
        self._call_times: deque[float] = deque(maxlen=rate_limit_per_min)
        self._cooldown = breaker_cooldown_sec
        self._breakers: dict[str, _BreakerState] = {}
        self._retries = retry_per_source

    def fetch(self, key: str, *args, **kwargs) -> pd.DataFrame:
        if key not in self.FALLBACK_CHAINS:
            raise KeyError(f"AkshareAdapter: unknown key '{key}'")

        if self._is_breaker_open(key):
            raise AkshareUnavailable(f"circuit breaker open for {key}")

        self._throttle()

        if self._client is None:
            self._client = self._client_factory()

        last_err: Exception | None = None
        for fn_name in self.FALLBACK_CHAINS[key]:
            for attempt in range(self._retries):
                try:
                    fn = getattr(self._client, fn_name)
                    df = fn(*args, **kwargs)
                    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                        last_err = RuntimeError(f"{fn_name} returned empty")
                        # 空结果也算失败，继续下一个 attempt 或下一个 source
                        continue
                    return df
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    logger.warning(
                        "akshare %s attempt %d failed: %s",
                        fn_name, attempt + 1, exc,
                    )
                    _sleep(2 ** attempt)  # 指数退避 1s, 2s
            # 该 source 全部 attempt 失败，进入下一个 source

        self._open_breaker(key)
        raise AkshareUnavailable(
            f"all sources failed for {key}: {last_err}"
        ) from last_err

    def _throttle(self) -> None:
        now = _now()
        # 清掉 60s 之外的记录
        while self._call_times and now - self._call_times[0] > 60:
            self._call_times.popleft()
        if len(self._call_times) >= self._rate_limit:
            wait = 60 - (now - self._call_times[0]) + 0.01
            if wait > 0:
                logger.info("AkshareAdapter throttle sleep %.2fs", wait)
                _sleep(wait)
        self._call_times.append(_now())

    def _is_breaker_open(self, key: str) -> bool:
        state = self._breakers.get(key)
        if not state:
            return False
        if _now() - state.opened_at < self._cooldown:
            return True
        # 过期：清除状态，允许重试
        del self._breakers[key]
        return False

    def _open_breaker(self, key: str) -> None:
        self._breakers[key] = _BreakerState(opened_at=_now())
        logger.warning("AkshareAdapter breaker opened for %s", key)
```

- [ ] **Step 4: Run test 验证通过**

Run: `pytest tests/test_akshare_adapter.py -v`
Expected: 6 个 case PASS

- [ ] **Step 5: Commit**

```bash
git add data_store/akshare_adapter.py tests/test_akshare_adapter.py
git commit -m "feat(data_store): AkshareAdapter 统一取数（fallback/限流/熔断）"
```

---

## Phase B — `analysis/institutional/` 业务层骨架（TDD）

### Task 4: Provider base + DTO + QuantSeatRegistry

**Files:**
- Create: `analysis/institutional/__init__.py`
- Create: `analysis/institutional/base.py`
- Create: `analysis/institutional/quant_seat_registry.py`
- Create: `config/quant_seats.json`
- Create: `tests/test_quant_seat_registry.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_quant_seat_registry.py
"""量化席位注册表加载 + 分类 + 热加载。"""
from __future__ import annotations

import json

from analysis.institutional.quant_seat_registry import QuantSeatRegistry


def test_classify_high_confidence(tmp_path):
    cfg = tmp_path / "quant_seats.json"
    cfg.write_text(json.dumps({
        "high_confidence": ["华泰证券股份有限公司总部"],
        "medium_confidence": ["招商证券股份有限公司深圳蛇口工业八路证券营业部"],
        "notes": "test",
    }, ensure_ascii=False), encoding="utf-8")

    reg = QuantSeatRegistry(cfg)
    is_q, conf = reg.classify("华泰证券股份有限公司总部")
    assert is_q is True and conf == "high"

    is_q, conf = reg.classify("招商证券股份有限公司深圳蛇口工业八路证券营业部")
    assert is_q is True and conf == "medium"

    is_q, conf = reg.classify("某不知名小券商营业部")
    assert is_q is False and conf is None


def test_reload_picks_up_changes(tmp_path):
    cfg = tmp_path / "quant_seats.json"
    cfg.write_text(json.dumps({"high_confidence": [], "medium_confidence": []}), encoding="utf-8")
    reg = QuantSeatRegistry(cfg)
    assert reg.classify("新席位 A") == (False, None)

    cfg.write_text(json.dumps({
        "high_confidence": ["新席位 A"], "medium_confidence": [],
    }, ensure_ascii=False), encoding="utf-8")
    reg.reload()
    assert reg.classify("新席位 A") == (True, "high")


def test_default_config_path_loads_ship_seat_list():
    """ship 默认 config/quant_seats.json 至少包含 5 个 high + 2 个 medium。"""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    reg = QuantSeatRegistry(repo_root / "config" / "quant_seats.json")
    assert len(reg._high) >= 5  # noqa: SLF001
    assert len(reg._medium) >= 2  # noqa: SLF001
```

- [ ] **Step 2: Run test 验证全失败**

Run: `pytest tests/test_quant_seat_registry.py -v`
Expected: FAIL（模块不存在 / config 不存在）

- [ ] **Step 3: 实现 base.py + quant_seat_registry.py + config/quant_seats.json**

```python
# analysis/institutional/__init__.py
"""个股深度挖掘 — 龙虎榜 / 北向 / 股东 / 调研 / 基金 / 控盘度 providers。"""
from analysis.institutional.base import (
    BaseProvider,
    ProviderResult,
)
from analysis.institutional.quant_seat_registry import QuantSeatRegistry

__all__ = [
    "BaseProvider",
    "ProviderResult",
    "QuantSeatRegistry",
]
```

```python
# analysis/institutional/base.py
"""Provider 抽象 + 统一 DTO。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, Literal, Optional, TypeVar

T = TypeVar("T")

DataStatus = Literal["fresh", "stale", "unavailable"]


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    """所有 provider 的统一返回。

    data 为 None 时 data_status 必为 'unavailable'。
    """
    data: Optional[T]
    data_status: DataStatus
    last_updated: Optional[str] = None  # ISO8601
    reason: Optional[str] = None        # unavailable 时的失败原因

    @classmethod
    def unavailable(cls, reason: str = "not implemented") -> "ProviderResult[T]":
        return cls(data=None, data_status="unavailable", last_updated=None, reason=reason)


class BaseProvider(ABC):
    """所有 institutional provider 的抽象基类。"""

    @abstractmethod
    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        ...
```

```python
# analysis/institutional/quant_seat_registry.py
"""量化席位注册表（JSON 热加载）。"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Tuple


class QuantSeatRegistry:
    """从 config/quant_seats.json 加载 high/medium 置信度席位清单。

    构造或调用 reload() 时读 JSON；classify(name) 返回 (is_quant, confidence)。
    """

    def __init__(self, config_path: Path):
        self._path = Path(config_path)
        self._lock = Lock()
        self._high: set[str] = set()
        self._medium: set[str] = set()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._high, self._medium = set(), set()
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._high = set(data.get("high_confidence", []))
            self._medium = set(data.get("medium_confidence", []))

    def classify(self, inst_name: str) -> Tuple[bool, str | None]:
        if inst_name in self._high:
            return True, "high"
        if inst_name in self._medium:
            return True, "medium"
        return False, None
```

```json
# config/quant_seats.json
{
  "high_confidence": [
    "中信证券股份有限公司上海分公司",
    "华泰证券股份有限公司总部",
    "华鑫证券有限责任公司上海宛平南路证券营业部",
    "国金证券股份有限公司上海奉贤区福海路证券营业部",
    "财通证券股份有限公司杭州金城路证券营业部"
  ],
  "medium_confidence": [
    "华泰证券股份有限公司深圳益田路荣超商务中心证券营业部",
    "招商证券股份有限公司深圳蛇口工业八路证券营业部"
  ],
  "notes": "high_confidence = 经长期统计量化交易占比 > 60% 的席位；M2 上线前由 OpenClawd 复核"
}
```

- [ ] **Step 4: Run test 验证通过**

Run: `pytest tests/test_quant_seat_registry.py -v`
Expected: 3 个 case PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/institutional/__init__.py analysis/institutional/base.py \
        analysis/institutional/quant_seat_registry.py \
        config/quant_seats.json tests/test_quant_seat_registry.py
git commit -m "feat(institutional): Provider 抽象 + DTO + 量化席位注册表"
```

---

### Task 5: 6 个 Provider 骨架

**Files:**
- Create: `analysis/institutional/lhb_provider.py`
- Create: `analysis/institutional/hsgt_provider.py`
- Create: `analysis/institutional/holders_provider.py`
- Create: `analysis/institutional/survey_provider.py`
- Create: `analysis/institutional/fund_holdings_provider.py`
- Create: `analysis/institutional/cyq_provider.py`
- Modify: `analysis/institutional/__init__.py`
- Create: `tests/test_institutional_providers.py`

> 骨架阶段：每个 provider 的 `get()` 都从 SQLite 读已有数据（若有则返回 `data_status="stale"`），若库里无记录则返回 `unavailable`。不调用 akshare —— M2 才接入实数据。这样 frontend 在 M1 即可用「读 stale 历史」+「unavailable 降级」两条路径联调。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_institutional_providers.py
"""6 个 provider 骨架的接口与降级行为。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    migrate(c)
    from data_store import connection
    monkeypatch.setattr(connection, "get_conn", lambda: c)
    yield c
    c.close()


def test_lhb_provider_unavailable_when_db_empty(conn):
    from analysis.institutional.lhb_provider import LhbProvider
    p = LhbProvider(
        seat_registry=_stub_registry(),
        akshare_adapter=_NullAdapter(),
    )
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"
    assert res.data is None


def test_lhb_provider_returns_stale_from_db(conn):
    from data_store import dragon_tiger_repo
    dragon_tiger_repo.upsert_rows([{
        "ts_code": "000001.SZ", "trade_date": "2026-05-27",
        "inst_name": "华泰证券股份有限公司总部", "side": "buy",
        "net_amount": 1e8, "buy_amount": 1.2e8, "sell_amount": 2e7,
        "is_quant": 1, "quant_confidence": "high", "reason": "测试",
    }])

    from analysis.institutional.lhb_provider import LhbProvider
    p = LhbProvider(seat_registry=_stub_registry(), akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ", days=90)
    assert res.data_status == "stale"
    assert res.data is not None
    assert res.data["quant_seat_appearances"] == 1


def test_hsgt_provider_skeleton(conn):
    from analysis.institutional.hsgt_provider import HsgtProvider
    p = HsgtProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


def test_holders_provider_skeleton(conn):
    from analysis.institutional.holders_provider import HoldersProvider
    p = HoldersProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


def test_survey_provider_skeleton(conn):
    from analysis.institutional.survey_provider import SurveyProvider
    p = SurveyProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


def test_fund_holdings_provider_skeleton(conn):
    from analysis.institutional.fund_holdings_provider import FundHoldingsProvider
    p = FundHoldingsProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


def test_cyq_provider_skeleton(conn):
    from analysis.institutional.cyq_provider import CyqProvider
    p = CyqProvider(akshare_adapter=_NullAdapter())
    res = p.get("000001.SZ")
    assert res.data_status == "unavailable"


class _NullAdapter:
    """M1 阶段：所有 akshare 调用直接抛 AkshareUnavailable。"""
    def fetch(self, key, *a, **kw):
        from data_store.akshare_adapter import AkshareUnavailable
        raise AkshareUnavailable("M1: not implemented")


def _stub_registry():
    from analysis.institutional.quant_seat_registry import QuantSeatRegistry
    repo_root = Path(__file__).resolve().parents[1]
    return QuantSeatRegistry(repo_root / "config" / "quant_seats.json")
```

- [ ] **Step 2: Run test 验证全失败**

Run: `pytest tests/test_institutional_providers.py -v`
Expected: 7 个 case 全 FAIL

- [ ] **Step 3: 实现 6 个 provider 骨架**

```python
# analysis/institutional/lhb_provider.py
"""龙虎榜机构席位 provider（骨架：仅读 SQLite，未对接 akshare）。"""
from __future__ import annotations

import datetime as _dt

from analysis.institutional.base import BaseProvider, ProviderResult
from analysis.institutional.quant_seat_registry import QuantSeatRegistry
from data_store import dragon_tiger_repo


class LhbProvider(BaseProvider):
    def __init__(self, seat_registry: QuantSeatRegistry, akshare_adapter):
        self._registry = seat_registry
        self._adapter = akshare_adapter  # 留给 M2 用

    def get(self, ts_code: str, days: int = 90, **kwargs) -> ProviderResult:
        since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
        df = dragon_tiger_repo.get_by_code(ts_code, since=since)
        if df.empty:
            return ProviderResult.unavailable(
                reason="M1: dragon_tiger_inst empty for this code"
            )
        records = df.to_dict("records")
        latest_date = df["trade_date"].max()
        quant_count = int((df["is_quant"] == 1).sum())
        net_inst_buy = float(df["net_amount"].sum())
        highlights = (
            df.sort_values("net_amount", ascending=False)
              .head(5)[["trade_date", "inst_name", "side", "net_amount",
                         "is_quant", "quant_confidence"]]
              .to_dict("records")
        )
        return ProviderResult(
            data={
                "history_90d": records,
                "quant_seat_appearances": quant_count,
                "net_inst_buy_30d": net_inst_buy,
                "highlight_seats": highlights,
            },
            data_status="stale",
            last_updated=latest_date,
        )
```

```python
# analysis/institutional/hsgt_provider.py
"""陆股通个股持股 provider（骨架）。"""
from __future__ import annotations

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import hsgt_repo


class HsgtProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        df = hsgt_repo.get_by_code(ts_code)
        if df.empty:
            return ProviderResult.unavailable(
                reason="M1: hsgt_individual empty for this code"
            )
        df = df.sort_values("trade_date")
        latest = df.iloc[-1]
        trend = df.tail(30)[["trade_date", "hold_ratio"]].to_dict("records")
        delta = float(latest["hold_ratio"] - df.iloc[max(0, len(df) - 30)]["hold_ratio"])
        return ProviderResult(
            data={
                "latest": {
                    "hold_vol": float(latest["hold_vol"]),
                    "hold_ratio": float(latest["hold_ratio"]),
                    "trade_date": str(latest["trade_date"]),
                },
                "trend_30d": trend,
                "delta_30d_pct": delta,
            },
            data_status="stale",
            last_updated=str(latest["trade_date"]),
        )
```

```python
# analysis/institutional/holders_provider.py
"""Top10 流通股东 + 股东户数 provider（骨架）。"""
from __future__ import annotations

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import holders_repo


class HoldersProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        latest_period, top10 = holders_repo.latest_top10(ts_code)
        history = holders_repo.get_holdernumber_history(ts_code)
        if latest_period is None and history.empty:
            return ProviderResult.unavailable(
                reason="M1: top10_floatholders / stk_holdernumber empty"
            )
        data = {
            "top10_floatholders": {
                "period": latest_period,
                "rows": top10.to_dict("records") if not top10.empty else [],
                "concentration": float(top10["hold_ratio"].sum()) if not top10.empty else 0.0,
            },
            "holder_number": {
                "latest_num": int(history.iloc[-1]["holder_num"]) if not history.empty else None,
                "pct_change_qoq": float(history.iloc[-1]["pct_change"]) if not history.empty else None,
                "history": history.to_dict("records") if not history.empty else [],
            },
        }
        last_updated = latest_period or (
            str(history.iloc[-1]["end_date"]) if not history.empty else None
        )
        return ProviderResult(data=data, data_status="stale", last_updated=last_updated)
```

```python
# analysis/institutional/survey_provider.py
"""机构调研 provider（骨架）。"""
from __future__ import annotations

import datetime as _dt

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import survey_repo


class SurveyProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, days: int = 90, **kwargs) -> ProviderResult:
        since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
        df = survey_repo.get_by_code(ts_code, since=since)
        if df.empty:
            return ProviderResult.unavailable(reason="M1: jgdy_detail empty")
        return ProviderResult(
            data={"recent_90d": df.to_dict("records")},
            data_status="stale",
            last_updated=str(df["survey_date"].max()),
        )
```

```python
# analysis/institutional/fund_holdings_provider.py
"""重仓基金 provider（骨架）。"""
from __future__ import annotations

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import fund_hold_repo


class FundHoldingsProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        period = fund_hold_repo.latest_period(ts_code)
        if period is None:
            return ProviderResult.unavailable(reason="M1: fund_hold_detail empty")
        df = fund_hold_repo.get_by_code(ts_code, period)
        total_nv = float(df["nv_ratio"].sum()) if not df.empty else 0.0
        return ProviderResult(
            data={
                "period": period,
                "rows": df.to_dict("records"),
                "total_nv_pct": total_nv,
            },
            data_status="stale",
            last_updated=period,
        )
```

```python
# analysis/institutional/cyq_provider.py
"""官方筹码分布 provider（骨架：M1 不调 akshare）。"""
from __future__ import annotations

from analysis.institutional.base import BaseProvider, ProviderResult


class CyqProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        # M1 阶段不调用 akshare，也不读 sentiment_cache（M2 再接入）
        return ProviderResult.unavailable(reason="M1: cyq_em not yet integrated")
```

更新 `__init__.py` 导出：

```python
# analysis/institutional/__init__.py
"""个股深度挖掘 — 龙虎榜 / 北向 / 股东 / 调研 / 基金 / 控盘度 providers。"""
from analysis.institutional.base import BaseProvider, ProviderResult
from analysis.institutional.quant_seat_registry import QuantSeatRegistry
from analysis.institutional.lhb_provider import LhbProvider
from analysis.institutional.hsgt_provider import HsgtProvider
from analysis.institutional.holders_provider import HoldersProvider
from analysis.institutional.survey_provider import SurveyProvider
from analysis.institutional.fund_holdings_provider import FundHoldingsProvider
from analysis.institutional.cyq_provider import CyqProvider

__all__ = [
    "BaseProvider", "ProviderResult", "QuantSeatRegistry",
    "LhbProvider", "HsgtProvider", "HoldersProvider",
    "SurveyProvider", "FundHoldingsProvider", "CyqProvider",
]
```

- [ ] **Step 4: Run test 验证全通过**

Run: `pytest tests/test_institutional_providers.py -v`
Expected: 7 个 case PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/institutional/lhb_provider.py analysis/institutional/hsgt_provider.py \
        analysis/institutional/holders_provider.py analysis/institutional/survey_provider.py \
        analysis/institutional/fund_holdings_provider.py analysis/institutional/cyq_provider.py \
        analysis/institutional/__init__.py tests/test_institutional_providers.py
git commit -m "feat(institutional): 6 个 provider 骨架（读库回 stale，无库回 unavailable）"
```

---

## Phase C — 编排层 payload 扩展（TDD）

### Task 6: `StockAnalysisSuite` 注入 providers + 扩展 payload

**Files:**
- Modify: `analysis/stock_analysis_suite.py`
- Modify: `tests/test_stock_analysis_suite.py`

- [ ] **Step 1: 写失败测试 — 追加到现有文件末尾**

```python
# tests/test_stock_analysis_suite.py — 追加
"""M1 扩展：payload 顶层新增 4 个 key + overview.radar 增 2 轴。"""


def test_payload_has_four_new_top_level_keys(monkeypatch, sample_df):
    """payload 必含 main_force_deep / institutional_holdings / chip_control / quant_matrix，
    且骨架阶段 data_status 均为 unavailable。"""
    from analysis.stock_analysis_suite import StockAnalysisSuite

    suite = _build_suite_with_stub_providers(monkeypatch, sample_df)
    payload = suite.analyze("000001.SZ")

    for key in ("main_force_deep", "institutional_holdings",
                "chip_control", "quant_matrix"):
        assert key in payload, f"missing top-level key: {key}"
        assert payload[key]["data_status"] == "unavailable"
        assert "last_updated" in payload[key]
        assert "reason" in payload[key]


def test_overview_radar_has_two_new_axes(monkeypatch, sample_df):
    from analysis.stock_analysis_suite import StockAnalysisSuite

    suite = _build_suite_with_stub_providers(monkeypatch, sample_df)
    payload = suite.analyze("000001.SZ")
    radar = payload["overview"]["radar"]
    assert "control_degree" in radar
    assert "quant_activity" in radar
    # M1：unavailable 时两轴默认 0
    assert radar["control_degree"]["score"] == 0
    assert radar["quant_activity"]["score"] == 0


def _build_suite_with_stub_providers(monkeypatch, sample_df):
    """注入 6 个 stub provider，全部返回 unavailable。"""
    from analysis.institutional.base import ProviderResult
    from analysis.stock_analysis_suite import StockAnalysisSuite

    class _Stub:
        def get(self, ts_code, **kw):
            return ProviderResult.unavailable(reason="stub")

    suite = StockAnalysisSuite(
        # 假设 StockAnalysisSuite 构造接受 institutional_providers dict（见 Step 3）
        institutional_providers={
            "lhb": _Stub(), "hsgt": _Stub(), "holders": _Stub(),
            "survey": _Stub(), "fund": _Stub(), "cyq": _Stub(),
        },
    )
    # 复用现有 stub data path 的 fixture
    monkeypatch.setattr(
        "analysis.stock_analysis_suite.StockAnalysisSuite._load_kline",
        lambda self, code, period="1d": sample_df,
    )
    return suite
```

> 假设 `sample_df` fixture 已存在于 `tests/test_stock_analysis_suite.py`，引用现有
> 模式即可；若不存在，复用 `tests/conftest.py` 中通用 fixture（先 `grep` 确认）。

- [ ] **Step 2: Run test 验证失败**

Run: `pytest tests/test_stock_analysis_suite.py::test_payload_has_four_new_top_level_keys tests/test_stock_analysis_suite.py::test_overview_radar_has_two_new_axes -v`
Expected: 2 个 case FAIL（payload 不含新 key）

- [ ] **Step 3: 修改 `StockAnalysisSuite`**

**3.1 在 `__init__` 接受 `institutional_providers` dict：**

```python
# analysis/stock_analysis_suite.py — 修改 __init__
def __init__(
    self,
    # ... 现有参数 ...
    institutional_providers: dict | None = None,
):
    # ... 现有初始化 ...
    self._inst_providers = institutional_providers or {}
```

**3.2 在 `_collect_inputs` 或 payload 组装函数中加 4 个新 key：**

定位现有 payload 构造位置（grep `"overview"`），在返回的 dict 中追加：

```python
# 4 个新顶层 key
main_force_deep = self._collect_main_force_deep(stock_code)
institutional_holdings = self._collect_institutional_holdings(stock_code)
chip_control = self._collect_chip_control(stock_code)
quant_matrix = self._collect_quant_matrix(stock_code)

payload = {
    "overview": overview,
    "risk_control": risk_control,
    "cached_reports": cached_reports,
    "ai_interpretation": ai_interpretation,
    # M1 新增：
    "main_force_deep": main_force_deep,
    "institutional_holdings": institutional_holdings,
    "chip_control": chip_control,
    "quant_matrix": quant_matrix,
}
```

**3.3 实现 4 个 `_collect_*` 方法（骨架）：**

```python
def _collect_main_force_deep(self, ts_code: str) -> dict:
    lhb = self._inst_providers.get("lhb")
    hsgt = self._inst_providers.get("hsgt")
    lhb_res = lhb.get(ts_code) if lhb else None
    hsgt_res = hsgt.get(ts_code) if hsgt else None
    if not lhb_res and not hsgt_res:
        return _unavailable("no provider configured")
    # 任一 fresh/stale 都算 stale；全 unavailable 才算 unavailable
    statuses = [r.data_status for r in (lhb_res, hsgt_res) if r is not None]
    overall = "unavailable" if all(s == "unavailable" for s in statuses) else "stale"
    return {
        "data_status": overall,
        "last_updated": max((r.last_updated or "" for r in (lhb_res, hsgt_res) if r), default=None) or None,
        "reason": "; ".join(filter(None, (r.reason for r in (lhb_res, hsgt_res) if r))) or None,
        "dragon_tiger": lhb_res.data if (lhb_res and lhb_res.data) else None,
        "hsgt": hsgt_res.data if (hsgt_res and hsgt_res.data) else None,
        "stage_timeline": None,        # M3 填充
        "quant_signature": None,       # M3 填充
    }


def _collect_institutional_holdings(self, ts_code: str) -> dict:
    holders = self._inst_providers.get("holders")
    survey = self._inst_providers.get("survey")
    fund = self._inst_providers.get("fund")
    res = [(name, p.get(ts_code)) for name, p in
           (("holders", holders), ("survey", survey), ("fund", fund)) if p]
    if not res:
        return _unavailable("no provider configured")
    statuses = [r.data_status for _, r in res]
    overall = "unavailable" if all(s == "unavailable" for s in statuses) else "stale"
    out = {
        "data_status": overall,
        "last_updated": max((r.last_updated or "" for _, r in res), default=None) or None,
        "reason": "; ".join(filter(None, (r.reason for _, r in res))) or None,
        "top10_floatholders": None,
        "holder_number": None,
        "surveys": None,
        "fund_holds": None,
    }
    for name, r in res:
        if r.data:
            if name == "holders":
                out["top10_floatholders"] = r.data.get("top10_floatholders")
                out["holder_number"] = r.data.get("holder_number")
            elif name == "survey":
                out["surveys"] = r.data
            elif name == "fund":
                out["fund_holds"] = r.data
    return out


def _collect_chip_control(self, ts_code: str) -> dict:
    cyq = self._inst_providers.get("cyq")
    cyq_res = cyq.get(ts_code) if cyq else None
    if not cyq_res:
        return _unavailable("no provider configured")
    return {
        "data_status": cyq_res.data_status,
        "last_updated": cyq_res.last_updated,
        "reason": cyq_res.reason,
        "control_degree": None,        # M2/M3 透传 ChipAnalyzer.main_force_control
        "control_label": None,
        "concentration_90": None,
        "concentration_70": None,
        "concentration_50": None,
        "top10_concentration": None,
        "cyq_distribution": cyq_res.data,  # M1: None
    }


def _collect_quant_matrix(self, ts_code: str) -> dict:
    # M1：完全骨架，M4 才填充
    return _unavailable("M1: quant_matrix not yet implemented (planned for M4)")
```

**3.4 工具函数 `_unavailable`（加在文件顶部或同模块）：**

```python
def _unavailable(reason: str) -> dict:
    return {
        "data_status": "unavailable",
        "last_updated": None,
        "reason": reason,
    }
```

**3.5 `overview.radar` 增 2 轴：**

定位 `overview["radar"]` 构造处（grep `"radar"`），追加：

```python
overview["radar"]["control_degree"] = {
    "score": 0,  # M2/M3 才有真实值
    "label": "未知",
}
overview["radar"]["quant_activity"] = {
    "score": 0,
    "label": "未知",
}
```

- [ ] **Step 4: Run test 验证通过**

Run: `pytest tests/test_stock_analysis_suite.py -v`
Expected: 全部 PASS（含新加的 2 个 case + 原有 case）

- [ ] **Step 5: 同步更新 `StockSuiteService` 构造**

定位 `webui/services/stock_suite_service.py`，在 `_build_suite()` 或同等单例工厂处
注入 providers：

```python
# webui/services/stock_suite_service.py — 仅展示新增部分
from pathlib import Path

from analysis.institutional import (
    LhbProvider, HsgtProvider, HoldersProvider,
    SurveyProvider, FundHoldingsProvider, CyqProvider,
    QuantSeatRegistry,
)
from data_store.akshare_adapter import AkshareAdapter


def _build_institutional_providers():
    repo_root = Path(__file__).resolve().parents[2]
    registry = QuantSeatRegistry(repo_root / "config" / "quant_seats.json")
    adapter = AkshareAdapter()  # M1: 用，但 providers 不会真的调用
    return {
        "lhb":     LhbProvider(seat_registry=registry, akshare_adapter=adapter),
        "hsgt":    HsgtProvider(akshare_adapter=adapter),
        "holders": HoldersProvider(akshare_adapter=adapter),
        "survey":  SurveyProvider(akshare_adapter=adapter),
        "fund":    FundHoldingsProvider(akshare_adapter=adapter),
        "cyq":     CyqProvider(akshare_adapter=adapter),
    }


# 在 StockSuiteService.__init__ 或 _build_suite 内：
# self._suite = StockAnalysisSuite(..., institutional_providers=_build_institutional_providers())
```

- [ ] **Step 6: 跑 service & robyn 测试确认未破坏**

Run: `pytest tests/test_stock_suite_service.py tests/test_robyn_app.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add analysis/stock_analysis_suite.py webui/services/stock_suite_service.py \
        tests/test_stock_analysis_suite.py
git commit -m "feat(suite): payload 增 4 顶层 key + radar 增 2 轴（M1 骨架，全 unavailable）"
```

---

## Phase D — API 诊断端点（TDD）

### Task 7: `GET /api/diagnostics/data-sources`

**Files:**
- Modify: `webui/robyn_app.py`
- Modify: `tests/test_robyn_app.py`

- [ ] **Step 1: 写失败测试 — 追加**

```python
# tests/test_robyn_app.py — 追加
def test_diagnostics_data_sources_returns_summary(robyn_test_client, isolated_db):
    """/api/diagnostics/data-sources 返回最近 24h sync_log 摘要。"""
    from data_store import sync_log_repo
    sync_log_repo.append("lhb", "000001.SZ", "2026-05-28T08:00:00", "ok", rows=42)
    sync_log_repo.append("hsgt", "", "2026-05-28T08:01:00", "failed", error="429")

    resp = robyn_test_client.get("/api/diagnostics/data-sources")
    assert resp.status_code == 200
    body = resp.json()
    assert "lhb" in body
    assert body["lhb"]["ok"] == 1
    assert "hsgt" in body
    assert body["hsgt"]["failed"] == 1
```

> `robyn_test_client` 与 `isolated_db` fixture 在 `tests/conftest.py` 中应已就绪；
> 若没有 `isolated_db`，可复用现有迁移 fixture 模式（见
> `tests/test_data_store.py` / `tests/test_moneyflow_kv_snapshot.py`）。

- [ ] **Step 2: Run test 验证失败**

Run: `pytest tests/test_robyn_app.py::test_diagnostics_data_sources_returns_summary -v`
Expected: FAIL（路由 404）

- [ ] **Step 3: 注册 handler**

在 `webui/robyn_app.py` 中找已有 `/api/...` 注册段，追加：

```python
@app.get("/api/diagnostics/data-sources")
async def diagnostics_data_sources(request):
    from data_store import sync_log_repo
    import json
    try:
        summary = sync_log_repo.summary_last_24h()
        return {"status_code": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(summary, ensure_ascii=False)}
    except Exception as exc:  # noqa: BLE001
        return {"status_code": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(exc)})}
```

> 实际函数签名以 `webui/robyn_app.py` 现有路由风格为准（同步 vs. async、返回
> 形式）。grep 文件内现有 `@app.get` 模式照搬。

- [ ] **Step 4: Run test 验证通过**

Run: `pytest tests/test_robyn_app.py -v`
Expected: 新 case + 原有 case 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add webui/robyn_app.py tests/test_robyn_app.py
git commit -m "feat(api): GET /api/diagnostics/data-sources 返回最近 24h 同步摘要"
```

---

## Phase E — 前端 Tab nav 重排 + 4 个 render 函数

> 本 Phase 不写自动化测试（spec §4.4 明示前端冒烟走 manual + screenshot）。
> 每个 Task 末尾要求**手动**在浏览器打开个股弹窗 → 切到目标 Tab → 截图归档到
> `docs/screenshots/2026-05-28-deep-mining/`。

### Task 8: Tab nav 11→12 重排 + 新 section 容器

**Files:**
- Modify: `webui/templates/desktop.html`
- Modify: `webui/static/kronos_desktop.css`

- [ ] **Step 1: 修改 nav#stockSuiteTabs**

打开 `webui/templates/desktop.html`，定位 `nav id="stockSuiteTabs"`（约 line 732）。

- 把 `data-suite-tab="main_force_phase"` 按钮 label 由 `主力阶段` 改为 `主力深度`
  （`data-suite-tab` 属性同步改为 `main_force_deep`）。
- 把 `data-suite-tab="volume_price_game"` label `量价博弈` 改为 `量化矩阵`
  （属性改为 `quant_matrix`）。
- 把 `data-suite-tab="chip_structure"` label `筹码结构` 改为 `筹码·控盘雷达`
  （属性改为 `chip_radar`）。
- 在 `data-suite-tab="limit_up_screening"` 与 `data-suite-tab="ai_interpretation"`
  之间插入：

```html
<button class="suite-tab" data-suite-tab="institutional_holdings">机构持仓</button>
```

- [ ] **Step 2: 在 div#stockSuitePanels 内对应改 / 增 section**

- 把 `data-suite-pane="main_force_phase"` 改为 `data-suite-pane="main_force_deep"`，
  pane 标题（如有）由 `主力阶段` 改为 `主力深度`。
- 同样改 `volume_price_game` → `quant_matrix`，标题 `量价博弈` → `量化矩阵`。
- 同样改 `chip_structure` → `chip_radar`，标题 `筹码结构` → `筹码·控盘雷达`。
- 在 `limit_up_screening` pane 后插入：

```html
<section class="suite-pane" data-suite-pane="institutional_holdings" hidden>
  <header class="suite-pane-header">
    <h3>机构持仓</h3>
    <small class="suite-pane-status" data-status-target></small>
  </header>
  <div class="suite-pane-body" data-render-target>
    <div class="suite-skeleton">加载中…</div>
  </div>
</section>
```

> 模板中其他 3 个改名 pane 也加 `data-status-target` 与 `data-render-target` 钩子
> （若已存在则跳过），后续 render 函数据此找元素。

- [ ] **Step 3: 在 kronos_desktop.css 加新样式**

定位 `webui/static/kronos_desktop.css` 末尾，追加：

```css
/* === Deep mining M1 === */
.suite-unavailable-banner {
  background: linear-gradient(90deg, #fef2f2, #fee2e2);
  color: #991b1b;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 13px;
  margin: 12px 0;
  border-left: 4px solid #dc2626;
}
.suite-stale-banner {
  background: linear-gradient(90deg, #fffbeb, #fef3c7);
  color: #92400e;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 13px;
  margin: 12px 0;
  border-left: 4px solid #d97706;
}
.suite-kpi-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 12px 0;
}
.suite-kpi-card {
  background: var(--surface-elevated, #fafbfc);
  border-radius: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border-subtle, #e5e7eb);
}
.suite-kpi-label { font-size: 12px; color: var(--text-muted, #6b7280); }
.suite-kpi-value { font-size: 20px; font-weight: 600; margin-top: 4px; }
.quant-seat-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  margin-left: 6px;
}
.quant-seat-pill[data-confidence="high"]   { background: #fee2e2; color: #991b1b; }
.quant-seat-pill[data-confidence="medium"] { background: #fef3c7; color: #92400e; }
.suite-stage-axis {
  display: grid;
  grid-template-columns: repeat(60, 1fr);
  gap: 2px;
  margin: 12px 0;
}
.suite-stage-cell {
  height: 16px; border-radius: 2px; background: #e5e7eb;
}
.suite-stage-cell[data-stage="建仓"] { background: #93c5fd; }
.suite-stage-cell[data-stage="洗盘"] { background: #fcd34d; }
.suite-stage-cell[data-stage="拉升"] { background: #f87171; }
.suite-stage-cell[data-stage="出货"] { background: #6b7280; }
.suite-stage-cell[data-stage="中性"] { background: #e5e7eb; }
```

- [ ] **Step 4: 修改 dispatch — applyStockSuitePayload**

定位 `webui/templates/desktop.html` 内 `applyStockSuitePayload` 函数（约 line 2419）。

把现有 switch 中 `case "main_force_phase":` 改为 `case "main_force_deep":`，
`case "volume_price_game":` 改为 `case "quant_matrix":`，
`case "chip_structure":` 改为 `case "chip_radar":`，并新增：

```js
case "institutional_holdings":
  renderSuiteHoldings(payload);
  break;
```

确保 4 个新 case 的 render 函数名与后续 Task 9~12 一致：
`renderSuiteMainForceDeep` / `renderSuiteQuantMatrix` /
`renderSuiteChipRadar` / `renderSuiteHoldings`。

- [ ] **Step 5: 手动冒烟**

1. 启动 `python webui/run.py`
2. 打开个股弹窗（任意股票）
3. 切换 12 个 Tab，确认：
   - Tab 文案：`主力深度 / 量化矩阵 / 筹码·控盘雷达 / 机构持仓` 已生效
   - 4 个改名/新增 Tab pane 显示 `加载中…` 骨架（render 函数 Task 9~12 才实现）
4. 浏览器 console 无报错
5. 截图 12 个 Tab 各一张到 `docs/screenshots/2026-05-28-deep-mining/m1-tab-nav-*.png`

- [ ] **Step 6: Commit**

```bash
git add webui/templates/desktop.html webui/static/kronos_desktop.css \
        docs/screenshots/2026-05-28-deep-mining/
git commit -m "feat(webui): 12 Tab 工作台重排（主力深度/量化矩阵/筹码控盘雷达/机构持仓）"
```

---

### Task 9: `renderSuiteMainForceDeep` 函数

**Files:**
- Modify: `webui/templates/desktop.html`

- [ ] **Step 1: 实现函数（unavailable + stale 分支）**

在 `desktop.html` 内 `<script>` 标签中（约 `renderSuiteRiskControl` 附近）添加：

```js
function renderSuiteMainForceDeep(payload) {
  const pane = document.querySelector('[data-suite-pane="main_force_deep"]');
  if (!pane) return;
  const body = pane.querySelector('[data-render-target]');
  const status = pane.querySelector('[data-status-target]');
  if (!body) return;

  const section = payload.main_force_deep || {};
  if (section.data_status === "unavailable") {
    body.innerHTML = `
      <div class="suite-unavailable-banner">
        数据源暂不可用：${section.reason || '未知原因'}
        <a href="/api/diagnostics/data-sources" target="_blank">查看诊断</a>
      </div>
    `;
    if (status) status.textContent = '数据源不可用';
    return;
  }

  const isStale = section.data_status === "stale";
  const banner = isStale ? `
    <div class="suite-stale-banner">
      最近一次入库：${section.last_updated || '未知'}（本期 M1 仅展示历史数据）
    </div>` : '';

  const dt = section.dragon_tiger || {};
  const hsgt = section.hsgt || {};
  const stageTl = section.stage_timeline; // M1: null
  const qs = section.quant_signature;     // M1: null

  body.innerHTML = `
    ${banner}
    <div class="suite-kpi-bar">
      <div class="suite-kpi-card">
        <div class="suite-kpi-label">阶段</div>
        <div class="suite-kpi-value">${stageTl?.current_label || '—'}</div>
      </div>
      <div class="suite-kpi-card">
        <div class="suite-kpi-label">控盘度</div>
        <div class="suite-kpi-value">${(payload.overview?.radar?.control_degree?.score ?? '—')}</div>
      </div>
      <div class="suite-kpi-card">
        <div class="suite-kpi-label">量化席位 90 日</div>
        <div class="suite-kpi-value">${dt.quant_seat_appearances ?? '—'}</div>
      </div>
      <div class="suite-kpi-card">
        <div class="suite-kpi-label">北向占流通股 (%)</div>
        <div class="suite-kpi-value">${hsgt.latest?.hold_ratio?.toFixed?.(2) ?? '—'}</div>
      </div>
    </div>

    <h4>主力四阶段时间轴（近 60 交易日）</h4>
    <div class="suite-stage-axis" id="suite-stage-axis-main-force">
      ${(stageTl?.rows || []).slice(-60).map(r =>
        `<div class="suite-stage-cell" data-stage="${r.label}" title="${r.date}: ${r.label}"></div>`
      ).join('') || '<div class="suite-skeleton">阶段判定 M3 上线后可用</div>'}
    </div>

    <h4>龙虎榜机构席位（近 90 日）</h4>
    <table class="suite-table">
      <thead><tr><th>日期</th><th>席位</th><th>方向</th><th>净额</th><th>标记</th></tr></thead>
      <tbody>
        ${(dt.highlight_seats || []).map(s => `
          <tr>
            <td>${s.trade_date}</td>
            <td>${s.inst_name}${s.is_quant ? `<span class="quant-seat-pill" data-confidence="${s.quant_confidence}">量化</span>` : ''}</td>
            <td>${s.side}</td>
            <td>${formatAmount(s.net_amount)}</td>
            <td>${s.is_quant ? s.quant_confidence : ''}</td>
          </tr>`).join('') || '<tr><td colspan="5">暂无龙虎榜数据</td></tr>'}
      </tbody>
    </table>

    <h4>北向资金 30 日趋势</h4>
    <div id="suite-hsgt-trend-chart" style="height:180px"></div>

    <h4>量化行为签名</h4>
    <div>${qs ? `活跃度 ${qs.score}，事件 ${qs.events?.length || 0} 个`
                : 'M3 上线后可用'}</div>
  `;

  if (status) status.textContent = isStale ? '历史快照' : '实时';

  // 北向趋势图（如有数据）
  if (hsgt.trend_30d && hsgt.trend_30d.length) {
    const el = document.getElementById('suite-hsgt-trend-chart');
    const inst = echarts.init(el);
    inst.setOption({
      xAxis: { type: 'category', data: hsgt.trend_30d.map(r => r.trade_date) },
      yAxis: { type: 'value', name: '持股比 (%)' },
      series: [{ type: 'line', smooth: true,
                 data: hsgt.trend_30d.map(r => r.hold_ratio) }],
      grid: { left: 40, right: 20, top: 20, bottom: 28 },
    });
    window.__suite_charts__ = window.__suite_charts__ || {};
    window.__suite_charts__.main_force_deep_hsgt = inst;
  }
}
```

> `formatAmount` 若 `desktop.html` 内未定义，加一个简单版本：
> ```js
> function formatAmount(v) {
>   if (v == null) return '—';
>   const abs = Math.abs(v);
>   if (abs >= 1e8) return (v / 1e8).toFixed(2) + ' 亿';
>   if (abs >= 1e4) return (v / 1e4).toFixed(2) + ' 万';
>   return v.toFixed(0);
> }
> ```

- [ ] **Step 2: 手动冒烟**

1. 重启 `python webui/run.py`，硬刷浏览器（Cmd+Shift+R）
2. 打开任意个股，切到「主力深度」Tab
3. 应看到 `数据源暂不可用` 红条（因 SQLite 中无数据），样式正确无报错
4. 在 SQLite 中插一条龙虎榜测试数据：
   ```bash
   python -c "
   from data_store import dragon_tiger_repo
   from data_store.schema import migrate
   from data_store.connection import get_conn
   migrate(get_conn())
   dragon_tiger_repo.upsert_rows([{
     'ts_code': '000001.SZ', 'trade_date': '2026-05-27',
     'inst_name': '华泰证券股份有限公司总部', 'side': 'buy',
     'net_amount': 12000000, 'buy_amount': 15000000, 'sell_amount': 3000000,
     'is_quant': 1, 'quant_confidence': 'high', 'reason': '日涨幅 7%',
   }])
   "
   ```
5. 再次刷新「主力深度」Tab，应看到黄色 stale 提示 + KPI 条 + 表格中带「量化」高亮标签
6. 截图归档 `docs/screenshots/2026-05-28-deep-mining/m1-main-force-deep-{unavailable,stale}.png`

- [ ] **Step 3: Commit**

```bash
git add webui/templates/desktop.html docs/screenshots/
git commit -m "feat(webui): renderSuiteMainForceDeep（unavailable/stale 双路径 + KPI/表格/北向趋势）"
```

---

### Task 10: `renderSuiteQuantMatrix` 函数

**Files:**
- Modify: `webui/templates/desktop.html`

> M1 阶段 `quant_matrix.data_status` 永远是 `unavailable`（M4 才会填充）。
> 本 Task 只保证 Tab 不空白、Console 不报错、降级文案到位。

- [ ] **Step 1: 实现函数**

```js
function renderSuiteQuantMatrix(payload) {
  const pane = document.querySelector('[data-suite-pane="quant_matrix"]');
  if (!pane) return;
  const body = pane.querySelector('[data-render-target]');
  if (!body) return;

  const section = payload.quant_matrix || {};
  // M1: 永远走 unavailable 分支
  if (section.data_status === "unavailable") {
    body.innerHTML = `
      <div class="suite-unavailable-banner">
        量化矩阵将在 M4 里程碑（30 模型信号矩阵 + 多周期共振 + 历史命中率）上线。
        ${section.reason ? `<br>当前原因：${section.reason}` : ''}
      </div>
      <div class="suite-skeleton" style="margin-top:12px">
        <h4>预览结构（占位）</h4>
        <ul>
          <li>30 × 4 信号热力矩阵（日内/3 日/10 日/30 日）</li>
          <li>当前态势卡片（强势多头 / 震荡偏多 / 震荡 / 震荡偏空 / 强势空头）</li>
          <li>多周期共振环形图</li>
          <li>30 日历史命中率柱状图</li>
        </ul>
      </div>
    `;
    return;
  }
  // M4 上线后落到这里（暂留 TODO 行：以后实现 fresh/stale 分支）
}
```

- [ ] **Step 2: 手动冒烟**

1. 刷新弹窗 → 量化矩阵 Tab
2. 应看到红条 + 4 项预览列表
3. Console 无报错
4. 截图 `docs/screenshots/2026-05-28-deep-mining/m1-quant-matrix.png`

- [ ] **Step 3: Commit**

```bash
git add webui/templates/desktop.html docs/screenshots/
git commit -m "feat(webui): renderSuiteQuantMatrix（M1 仅占位说明 M4 计划）"
```

---

### Task 11: `renderSuiteChipRadar` 函数

**Files:**
- Modify: `webui/templates/desktop.html`

- [ ] **Step 1: 实现函数**

```js
function renderSuiteChipRadar(payload) {
  const pane = document.querySelector('[data-suite-pane="chip_radar"]');
  if (!pane) return;
  const body = pane.querySelector('[data-render-target]');
  if (!body) return;

  const s = payload.chip_control || {};
  if (s.data_status === "unavailable") {
    body.innerHTML = `
      <div class="suite-unavailable-banner">
        筹码 / 控盘数据暂不可用：${s.reason || '未知原因'}
      </div>
      <div class="suite-skeleton" style="margin-top:12px">
        <h4>预览结构（M2/M3 接入后可用）</h4>
        <ul>
          <li>控盘度仪表盘（0–100）</li>
          <li>筹码集中度雷达（90 / 70 / 50 / Top10）</li>
          <li>官方筹码分布直方图（stock_cyq_em）</li>
        </ul>
      </div>
    `;
    return;
  }

  body.innerHTML = `
    <div class="suite-kpi-bar">
      <div class="suite-kpi-card">
        <div class="suite-kpi-label">控盘度</div>
        <div class="suite-kpi-value">${s.control_degree ?? '—'}</div>
      </div>
      <div class="suite-kpi-card">
        <div class="suite-kpi-label">控盘标签</div>
        <div class="suite-kpi-value">${s.control_label ?? '—'}</div>
      </div>
      <div class="suite-kpi-card">
        <div class="suite-kpi-label">筹码集中度 90%</div>
        <div class="suite-kpi-value">${(s.concentration_90 ?? '—')}</div>
      </div>
      <div class="suite-kpi-card">
        <div class="suite-kpi-label">Top10 持股集中度</div>
        <div class="suite-kpi-value">${(s.top10_concentration ?? '—')}</div>
      </div>
    </div>
    <div id="suite-chip-radar-gauge" style="height:200px"></div>
    <div id="suite-chip-radar-chart" style="height:240px"></div>
    <div id="suite-cyq-histogram" style="height:240px"></div>
  `;

  // 仪表盘
  const gaugeEl = document.getElementById('suite-chip-radar-gauge');
  if (gaugeEl && s.control_degree != null) {
    const inst = echarts.init(gaugeEl);
    inst.setOption({
      series: [{
        type: 'gauge', min: 0, max: 100,
        detail: { formatter: '{value}', fontSize: 18 },
        data: [{ value: s.control_degree, name: '控盘度' }],
      }],
    });
    window.__suite_charts__ = window.__suite_charts__ || {};
    window.__suite_charts__.chip_radar_gauge = inst;
  }

  // 雷达
  const radarEl = document.getElementById('suite-chip-radar-chart');
  if (radarEl) {
    const inst = echarts.init(radarEl);
    inst.setOption({
      radar: {
        indicator: [
          { name: '90% 集中', max: 100 },
          { name: '70% 集中', max: 100 },
          { name: '50% 集中', max: 100 },
          { name: 'Top10 持股', max: 100 },
        ],
      },
      series: [{
        type: 'radar',
        data: [{
          value: [
            s.concentration_90 ?? 0,
            s.concentration_70 ?? 0,
            s.concentration_50 ?? 0,
            s.top10_concentration ?? 0,
          ],
          name: '筹码集中度',
        }],
      }],
    });
    window.__suite_charts__.chip_radar_radar = inst;
  }

  // 筹码分布直方图
  const histoEl = document.getElementById('suite-cyq-histogram');
  if (histoEl && s.cyq_distribution?.prices?.length) {
    const inst = echarts.init(histoEl);
    inst.setOption({
      xAxis: { type: 'category', data: s.cyq_distribution.prices,
               name: '价位' },
      yAxis: { type: 'value', name: '持仓比 (%)' },
      series: [{ type: 'bar',
                  data: s.cyq_distribution.ratios }],
      grid: { left: 40, right: 20, top: 20, bottom: 28 },
    });
    window.__suite_charts__.chip_radar_cyq = inst;
  }
}
```

- [ ] **Step 2: 手动冒烟**

1. 刷新弹窗 → 筹码·控盘雷达 Tab
2. M1 阶段应看到红条 + 预览列表（cyq provider 永远 unavailable）
3. Console 无报错
4. 截图 `docs/screenshots/2026-05-28-deep-mining/m1-chip-radar.png`

- [ ] **Step 3: Commit**

```bash
git add webui/templates/desktop.html docs/screenshots/
git commit -m "feat(webui): renderSuiteChipRadar（unavailable + fresh 双路径骨架）"
```

---

### Task 12: `renderSuiteHoldings` 函数

**Files:**
- Modify: `webui/templates/desktop.html`

- [ ] **Step 1: 实现函数**

```js
function renderSuiteHoldings(payload) {
  const pane = document.querySelector('[data-suite-pane="institutional_holdings"]');
  if (!pane) return;
  const body = pane.querySelector('[data-render-target]');
  if (!body) return;

  const s = payload.institutional_holdings || {};
  if (s.data_status === "unavailable") {
    body.innerHTML = `
      <div class="suite-unavailable-banner">
        机构持仓数据暂不可用：${s.reason || '未知原因'}
        <a href="/api/diagnostics/data-sources" target="_blank">查看诊断</a>
      </div>
    `;
    return;
  }

  const isStale = s.data_status === "stale";
  const banner = isStale ? `<div class="suite-stale-banner">
    最近一次入库：${s.last_updated || '未知'}
  </div>` : '';

  const t10 = s.top10_floatholders || {};
  const hn = s.holder_number || {};
  const surveys = s.surveys?.recent_90d || [];
  const funds = s.fund_holds?.rows || [];

  body.innerHTML = `
    ${banner}

    <h4>Top10 流通股东（${t10.period || '—'}）</h4>
    <table class="suite-table">
      <thead><tr><th>#</th><th>股东</th><th>持仓 (万股)</th><th>占流通比 (%)</th><th>变动</th></tr></thead>
      <tbody>
        ${(t10.rows || []).map(r => `
          <tr>
            <td>${r.holder_rank}</td>
            <td>${r.holder_name}</td>
            <td>${(r.hold_amount / 1e4).toFixed(2)}</td>
            <td>${(r.hold_ratio).toFixed(2)}</td>
            <td>${_changeBadge(r.change_type, r.change_amount)}</td>
          </tr>`).join('') || '<tr><td colspan="5">无数据</td></tr>'}
      </tbody>
    </table>

    <h4>股东户数变化</h4>
    <div>最新户数：<b>${hn.latest_num ?? '—'}</b>　环比：<b>${hn.pct_change_qoq != null ? hn.pct_change_qoq.toFixed(2) + '%' : '—'}</b></div>
    <div id="suite-holdernum-spark" style="height:120px"></div>

    <h4>机构调研（近 90 日）</h4>
    <ul>
      ${surveys.slice(0, 10).map(r => `<li>${r.survey_date} — ${r.inst_name}：${r.topic || ''}</li>`).join('') || '<li>无调研记录</li>'}
    </ul>

    <h4>重仓基金（${s.fund_holds?.period || '—'}）</h4>
    <div id="suite-fund-hold-bar" style="height:240px"></div>
  `;

  // 户数走势 sparkline
  const sparkEl = document.getElementById('suite-holdernum-spark');
  if (sparkEl && hn.history?.length) {
    const inst = echarts.init(sparkEl);
    inst.setOption({
      xAxis: { type: 'category', data: hn.history.map(r => r.end_date), show: false },
      yAxis: { type: 'value', show: false },
      series: [{ type: 'line', smooth: true,
                  data: hn.history.map(r => r.holder_num) }],
      grid: { left: 8, right: 8, top: 8, bottom: 8 },
    });
    window.__suite_charts__ = window.__suite_charts__ || {};
    window.__suite_charts__.holdings_spark = inst;
  }

  // 重仓基金条形图
  const barEl = document.getElementById('suite-fund-hold-bar');
  if (barEl && funds.length) {
    const inst = echarts.init(barEl);
    inst.setOption({
      yAxis: { type: 'category', data: funds.map(f => f.fund_name) },
      xAxis: { type: 'value', name: '占基金净值 (%)' },
      series: [{ type: 'bar', data: funds.map(f => f.nv_ratio) }],
      grid: { left: 120, right: 20, top: 20, bottom: 28 },
    });
    window.__suite_charts__.holdings_fund_bar = inst;
  }
}

function _changeBadge(type, amount) {
  if (!type || type === 'unchanged') return '—';
  const colorMap = { new: '#16a34a', add: '#16a34a', cut: '#dc2626', exit: '#6b7280' };
  const labelMap = { new: '新进', add: '增持', cut: '减持', exit: '退出' };
  return `<span style="color:${colorMap[type]}">${labelMap[type] || type}${amount ? ` ${(amount/1e4).toFixed(0)} 万` : ''}</span>`;
}
```

- [ ] **Step 2: 手动冒烟**

1. 刷新 → 机构持仓 Tab
2. 因 SQLite 无数据，应看到红条 + 诊断链接
3. 插测试数据后再刷：
   ```bash
   python -c "
   from data_store.schema import migrate; from data_store.connection import get_conn
   migrate(get_conn())
   from data_store import holders_repo, survey_repo, fund_hold_repo
   holders_repo.upsert_top10([{'ts_code':'000001.SZ','end_date':'2026-03-31','holder_rank':1,'holder_name':'易方达蓝筹精选','hold_amount':1e8,'hold_ratio':6.2,'change_type':'add','change_amount':2e7}])
   holders_repo.upsert_holdernumber([{'ts_code':'000001.SZ','end_date':'2026-03-31','holder_num':50000,'avg_hold':1234.5,'pct_change':-3.2}])
   survey_repo.upsert_rows([{'ts_code':'000001.SZ','survey_date':'2026-05-20','inst_name':'公募 A','reception':'董秘','topic':'AI 业务'}])
   fund_hold_repo.upsert_rows([{'ts_code':'000001.SZ','end_date':'2026-03-31','fund_code':'001234','fund_name':'易方达蓝筹','hold_shares':1e7,'market_value':1.5e8,'nv_ratio':3.4}])
   "
   ```
4. 刷新应看到 Top10 表 + 户数 + 调研 + 基金条形图
5. 截图 `docs/screenshots/2026-05-28-deep-mining/m1-holdings-{unavailable,stale}.png`

- [ ] **Step 3: Commit**

```bash
git add webui/templates/desktop.html docs/screenshots/
git commit -m "feat(webui): renderSuiteHoldings（机构持仓 Tab：Top10/户数/调研/基金）"
```

---

### Task 13: `renderSuiteOverview` 增 2 个 radar 轴

**Files:**
- Modify: `webui/templates/desktop.html`

- [ ] **Step 1: 定位现有 `renderSuiteOverview`**

约 `desktop.html` line 2449。找到 ECharts radar `indicator: [...]` 数组。

- [ ] **Step 2: 在数组末尾追加两轴**

```js
{ name: '控盘度', max: 100 },
{ name: '量化活跃度', max: 100 },
```

并同步把 `series[0].data[0].value` 数组追加两个值：

```js
payload.overview?.radar?.control_degree?.score ?? 0,
payload.overview?.radar?.quant_activity?.score ?? 0,
```

- [ ] **Step 3: 手动冒烟**

1. 刷新 → 综合总览 Tab
2. 雷达应显示 7 维（原 5 维 + 控盘度 + 量化活跃度），两个新轴值为 0
3. 截图 `docs/screenshots/2026-05-28-deep-mining/m1-overview-radar.png`

- [ ] **Step 4: Commit**

```bash
git add webui/templates/desktop.html docs/screenshots/
git commit -m "feat(webui): renderSuiteOverview radar 增控盘度 + 量化活跃度两轴"
```

---

## Phase F — 验收与归档

### Task 14: 全量回归 + 文档同步

**Files:**
- Modify: `docs/superpowers/specs/2026-05-28-individual-stock-deep-mining-design.md`（更新里程碑状态）
- Create: `docs/screenshots/2026-05-28-deep-mining/README.md`（截图索引）

- [ ] **Step 1: 跑全量 pytest**

Run: `pytest -x --tb=short`
Expected: 全部 PASS。若有 unrelated test 失败，记入 PR 描述，不在本计划范围。

- [ ] **Step 2: 手动 smoke 全 12 Tab**

打开 `python webui/run.py` → 个股弹窗 → 依次点 12 个 Tab，确认：
1. 12 个 Tab 标签名正确
2. 4 个新/改 Tab 都能正常渲染（unavailable 或 stale 两种状态）
3. Console 无 JS 报错
4. `/api/diagnostics/data-sources` 接口返回最近 24h 摘要

- [ ] **Step 3: 更新 spec M1 状态**

在 `docs/superpowers/specs/2026-05-28-individual-stock-deep-mining-design.md`
`### 4.5 渐进交付里程碑` 的 M1 行末追加 `✅ 完成于 2026-05-XX (PR #yyy)`。

- [ ] **Step 4: 写截图索引**

```markdown
# M1 (Foundation) 截图归档

- `m1-tab-nav-*.png` — 12 Tab 重排后导航
- `m1-main-force-deep-{unavailable,stale}.png` — 主力深度 Tab 两态
- `m1-quant-matrix.png` — 量化矩阵 Tab（M4 占位）
- `m1-chip-radar.png` — 筹码·控盘雷达 Tab（M2/M3 占位）
- `m1-holdings-{unavailable,stale}.png` — 机构持仓 Tab 两态
- `m1-overview-radar.png` — 综合总览 7 维雷达
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-28-individual-stock-deep-mining-design.md \
        docs/screenshots/2026-05-28-deep-mining/README.md
git commit -m "docs: M1 完成验收，更新 spec 里程碑状态 + 截图索引"
```

- [ ] **Step 6: 准备 PR**

PR 标题建议：`feat(stock-suite): 个股深度挖掘 M1 — 数据骨架 + 12 Tab 重排`

PR body 摘要要点：
- 落地 6 张 SQLite 表 + AkshareAdapter + 6 provider 骨架 + payload 4 顶层 key
- Tab 11→12 重排（主力深度 / 量化矩阵 / 筹码·控盘雷达 / 机构持仓）
- 提供 `/api/diagnostics/data-sources` 诊断端点
- M2 (真实数据) / M3 (业务规则) / M4 (量化矩阵) / M5 (集成) 见 spec

---

## 自审与遗留

**Spec 覆盖 vs 本计划任务：**

| Spec 节 | 本计划覆盖 | 后续计划 |
|---|---|---|
| §1 12 Tab 信息架构 | Task 8 (nav 重排) | — |
| §2.1 AkshareAdapter | Task 3 | — |
| §2.2 Migration v6 | Task 1 | — |
| §2.3 sentiment_cache TTL 扩展 | — | M2 |
| §2.4 隔夜批处理脚本 | — | M2 |
| §2.5 quant_seats.json / institutional_thresholds.json | Task 4（quant_seats）/ — | M3 (thresholds) |
| §3.1 包结构 | Task 4-5 | — |
| §3.2 ProviderResult / BaseProvider | Task 4 | — |
| §3.3 量化席位识别 | Task 4-5 | — |
| §3.4 stage_classifier | — | M3 |
| §3.5 quant_signature_detector | — | M3 |
| §3.6 payload 契约 | Task 6 (骨架 unavailable) | M2-M4 真实填充 |
| §3.7 风控联动 | — | M5 |
| §3.8 概率推演融合 | — | M5 |
| §4.1 4 个新 render 函数 | Task 9-12 | — |
| §4.2 API 路由 / 诊断端点 | Task 7 | M2 (bust_ttl) |
| §4.3 错误处理（unavailable/stale） | Task 9-12 内 | — |
| §4.4 测试矩阵 | Task 1-7 单元 / Task 8-13 手动冒烟 | M2+ |

**已知遗留（明确转移到后续计划）：**

- M2：`scripts/sync_institutional_data.py` 隔夜批 + 真实 akshare 拉取 + sentiment_cache TTL 扩展（cyq_em / minute_anomaly / hsgt_today / quant_signature）+ 各 provider `_fetch_from_akshare()` 实现 + `?bust_ttl=` 参数 + `config/institutional_thresholds.json`
- M3：`stage_classifier` + `quant_signature_detector` + 控盘度（`main_force_control`）从 `ChipAnalyzer` 透传到 `chip_control` 顶层 key + AI 解读 prompt 接入新字段
- M4：30 模型 → 信号矩阵 / 多周期共振 / 历史命中率 / 当前态势板
- M5：`risk_control.hidden_risks` 接入量化席位异动 + 户数骤升 + 净减持 / `scenario_probability` 融合公式 / CHANGELOG

**自审已修正：**

- 第一版伪代码中 `tests/data_store/test_*.py` 路径不符项目惯例（tests 目录平铺）—— 已统一为 `tests/test_*.py`。
- 第一版 `sync_log.ts_code` 设为 NULL 可空 —— SQLite 主键 NULL 语义不稳，改为 `NOT NULL DEFAULT ''`。
- Task 6 `_collect_*` 方法的「全 unavailable 折叠」逻辑与 spec §4.3 一致：任一子 provider 非 unavailable → 顶层 stale；全部 unavailable → 顶层 unavailable。
