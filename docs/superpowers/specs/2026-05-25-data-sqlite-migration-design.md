# 数据存储 SQLite 迁移设计

- 日期：2026-05-25
- 范围：把项目中以 CSV/JSON 形式散落的结构化业务数据集中到 SQLite。`.md`、`.html`、模型权重二进制、图片、日志保持文件形态不变。
- 策略：**一步到位**，不双写。每个迁移阶段先跑 importer 把历史文件导入，再同 commit 切换读写代码到仓储层；历史文件保留在磁盘做回滚兜底。

## 1. 背景与动机

现状盘点（命中 A 方案的结构化数据）：

| 来源 | 形态 | 规模 |
|---|---|---|
| `data/1d_*.csv`、`data/5m_*.csv` | OHLCV 时序 | 24 文件 |
| `data/cache/ohlcv/*.csv` | OHLCV 日线缓存（带 ts_code 列） | ~10k+ 行 |
| `cache/sentiment/*.json` | 多类型情绪/资金缓存 | 6542 文件 |
| `data/cache/market/basic_*.csv` | 每日全市场基础数据 | 数百日 |
| `data/cache/calendar/trade_cal.csv` | 交易日历 | 单文件 |
| `data/moneyflow_dc_*_top*.csv` | 当日资金流榜 | 数十文件 |
| `data/cache/hot_stocks_cache.json` | 热门股 | 单文件 |

问题：
1. 文件命名约定漂移（如 `1d_*` vs `XSHE_day_*`）容易导致读不到数据，最近修过一次。
2. 6542 个 JSON 小文件目录扫描成本高，跨平台备份/同步麻烦。
3. 没有版本号、没有 schema 校验，重构时容易破坏调用方。
4. 缺乏并发安全写入，多进程跑 batch 时容易踩到部分写入。

迁移收益：单文件 + WAL 模式可并发读 + 强类型 schema + 一次性版本演进。

## 2. 不在范围

- LLM 报告 `reports/*.md`、`reports/*.html`：保留文件形态，由 `analysis.stock_analysis_suite.trigger_ai_interpretation` 写盘。
- 模型权重：`model/`、`models/`、HF 缓存 — 不动。
- 日志：`logs/` 不动。
- 中间产物：`integrated_results/`、`results/`、`figures/` 不动（一次性产物，价值低）。
- `data/webui_jobs.sqlite`：已是 SQLite，独立保留，不合并。

## 3. 架构

### 3.1 包结构

```
data_store/
  __init__.py          # 导出 repo 实例
  connection.py        # sqlite3 连接管理 + PRAGMA + 单例
  schema.py            # DDL + 版本表 + migrate() 入口
  ohlcv_repo.py
  sentiment_repo.py
  calendar_repo.py
  daily_basic_repo.py
  moneyflow_repo.py
  kv_repo.py
  importers/
    __init__.py
    import_ohlcv.py
    import_sentiment.py
    import_market_basic.py
    import_calendar.py
    import_moneyflow.py
    import_kv.py
    run_all.py         # 一键全量导入
```

### 3.2 数据库布局

| 文件 | 用途 |
|---|---|
| `data/kronos_data.sqlite` | 业务数据（OHLCV/sentiment/daily_basic/calendar/moneyflow/kv） |
| `data/webui_jobs.sqlite` | webui 作业状态（已存在，不动） |

分库原因：`webui_jobs` 是高频读写的运维状态（作业进度、日志），`kronos_data` 是读多写少的引用数据；分开避免锁争用，备份/重建独立。

### 3.3 连接层契约

`data_store.connection.get_conn()`:
- 进程级单例 (`threading.local` per-thread connection)
- PRAGMA: `journal_mode=WAL`、`synchronous=NORMAL`、`foreign_keys=ON`、`busy_timeout=5000`
- 启动时自动 `schema.migrate()` 到最新版本
- 路径可由 `KRONOS_SQLITE_PATH` 环境变量覆盖（用于测试隔离）

### 3.4 仓储层契约

每个 repo 文件暴露：
- 模块级单例（如 `OHLCV_REPO`），简化调用方。
- 显式方法签名（`get_*` / `upsert_*` / `query_*`），不暴露 raw SQL。
- 所有写操作使用 `INSERT ... ON CONFLICT DO UPDATE`（UPSERT）。

## 4. Schema

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS ohlcv (
  code       TEXT NOT NULL,
  frequency  TEXT NOT NULL CHECK(frequency IN ('1d','5m','15m','30m','60m')),
  ts         TEXT NOT NULL,
  open       REAL,
  high       REAL,
  low        REAL,
  close      REAL,
  volume     REAL,
  amount     REAL,
  PRIMARY KEY (code, frequency, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_ohlcv_code_freq_ts ON ohlcv(code, frequency, ts DESC);

CREATE TABLE IF NOT EXISTS sentiment_cache (
  cache_type   TEXT NOT NULL,
  identifier   TEXT NOT NULL DEFAULT '',
  payload      TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  ttl_seconds  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (cache_type, identifier)
);

CREATE TABLE IF NOT EXISTS daily_basic (
  ts_code         TEXT NOT NULL,
  trade_date      TEXT NOT NULL,
  close           REAL,
  turnover_rate   REAL,
  turnover_rate_f REAL,
  volume_ratio    REAL,
  pe              REAL,
  pe_ttm          REAL,
  pb              REAL,
  ps              REAL,
  ps_ttm          REAL,
  dv_ratio        REAL,
  dv_ttm          REAL,
  total_share     REAL,
  float_share     REAL,
  free_share      REAL,
  total_mv        REAL,
  circ_mv         REAL,
  PRIMARY KEY (ts_code, trade_date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS trade_calendar (
  cal_date TEXT PRIMARY KEY,
  is_open  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS moneyflow_dc (
  trade_date         TEXT NOT NULL,
  ts_code            TEXT NOT NULL,
  top_n              INTEGER NOT NULL,
  name               TEXT,
  pct_change         REAL,
  close              REAL,
  net_amount         REAL,
  net_amount_rate    REAL,
  buy_elg_amount     REAL,
  buy_elg_amount_rate REAL,
  buy_lg_amount      REAL,
  buy_lg_amount_rate REAL,
  buy_md_amount      REAL,
  buy_md_amount_rate REAL,
  buy_sm_amount      REAL,
  buy_sm_amount_rate REAL,
  amount_unit        TEXT,
  PRIMARY KEY (trade_date, ts_code, top_n)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS kv_cache (
  namespace   TEXT NOT NULL,
  key         TEXT NOT NULL,
  payload     TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  ttl_seconds INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (namespace, key)
);
```

## 5. 切换点（调用方改造）

| 调用方 | 当前实现 | 迁移后 |
|---|---|---|
| `analysis/stock_analysis_suite.py:_load_ohlcv` | 读 `data/1d_*.csv`/`5m_*.csv` | `OHLCV_REPO.load_dataframe(code, freq)` |
| `scripts/fetch_data.py:save_data` | 写 `data/{freq}_{code}.csv` | `OHLCV_REPO.upsert_df(code, freq, df)` |
| `analysis/sentiment_cache_manager.py` | 读写 `cache/sentiment/*.json` | 内部改 `SENTIMENT_REPO`，对外接口不变 |
| `analysis/fundamental_data_collector.py`（市场基础） | 读 `data/cache/market/basic_*.csv` | `DAILY_BASIC_REPO.get_for_date(date)` |
| 各种 calendar / hot_stocks 读取 | 读 CSV/JSON | 对应 repo |

`sentiment_cache_manager` 单例保留 — 内部存储改 SQLite，对外 `get / set / clear_*` 签名不变，调用方无需改动。

## 6. 阶段拆分

| 阶段 | 内容 | 工作量 |
|---|---|---|
| **P0** | `data_store/connection.py`、`schema.py`、`schema_version` 表、`tests/test_data_store_connection.py` | 0.5d |
| **P1** | `ohlcv_repo` + `importers/import_ohlcv.py` + 切 `_load_ohlcv` + 切 `fetch_data.save_data` + 单测 + 跑 importer | 1d |
| **P2** | `sentiment_repo` + `importers/import_sentiment.py` + 改造 `sentiment_cache_manager` 内部 + 单测 + 跑 importer | 1d |
| **P3** | `daily_basic_repo` + `calendar_repo` + 各自 importer + 切读者 | 1d |
| **P4** | `moneyflow_repo` + `kv_repo` + `hot_stocks` 切换 + importer | 0.5d |
| **P5** | 把不再写的 CSV/JSON 路径整理（保留旧文件供回滚，新代码不写不读）；CLAUDE.md 同步文档；删除孤儿代码 | 0.5d |

每阶段独立 commit，可单独回滚。

## 7. 测试策略

- 每个 repo 独立 pytest（`tests/test_<x>_repo.py`），使用 `tmp_path` 隔离 SQLite 文件。
- 每个 importer：测样本 CSV/JSON → 导入 → 断言行数、字段、UPSERT 幂等。
- 集成测：`tests/test_stock_analysis_suite.py` 维持现有断言，重点验证 `_load_ohlcv` 切换后 radar 5 维仍跑出分数。
- 不写 E2E webui 测试（cost 太高）；后端 service 调用链覆盖足够。

## 8. 回滚策略

- 历史 CSV/JSON 不删除，新代码不读它们；如发现 bug，`git revert` 恢复读 CSV 的版本即可立即生效。
- importer 不删除源文件，只是把内容塞进 SQLite。
- 每阶段单 commit 单 PR（本地实践），最小化回滚面。

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| SQLite 单文件并发写阻塞 | WAL 模式 + 短事务；只在 importer 期间出现大批量写 |
| Schema 迁移失败 | `schema_version` 表 + 显式 migrate() 函数，可重跑 |
| importer 数据脏（如 5m_688110.csv 列名是 `timestamp`） | importer 跳过格式异常的文件并 log warn；不阻塞整体导入 |
| 现有 6542 JSON 一次性导入慢 | importer 用 `executemany` + 事务批量提交 |

## 10. 文档更新

- `CLAUDE.md` 改"数据保存"段：默认存 SQLite，文件形式仅为 importer 输入。
- `webui/README.md` 增加"数据存储"小节。
- 本设计文档归档 `docs/superpowers/specs/`。
