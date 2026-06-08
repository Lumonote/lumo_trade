# 资金榜单 · 机会分析 · 模拟盘回测 · 整库备份 — 完整设计 Spec

> 状态:设计已定稿(brainstorming 完成),待按「分期实现计划」逐步落地
> 日期:2026-06-04
> 语言/口径:中文界面;A 股口径(100 股/手、T+1、涨跌停);单用户单进程桌面端

---

## 1. 目标 / 背景

在桌面端新增一条「**发现资金主线 → 用机会挖掘算法分析 → 进模拟盘下单 → 回测出胜率**」的完整闭环:

1. **资金榜单**:完整的「主力买入榜」+「龙虎榜」排行榜列表,带刷新/补偿按钮(默认 30 天、可填),支持按**某一天**或**多日聚合**统计,支持**全选/多选**股票。
2. **机会分析**:对选中的股票用**与投资机会挖掘完全相同的算法**(v5.6 / 评分 v20)分析,生成结果页,**样式参考 `opportunity_top10_*.md`**。
3. **买入池 + 模拟盘**:结果页支持「加入买入池」;支持开盘价买入/即时买入/指定价买入、即时卖出/收盘价卖出/指定价卖出;用这些操作记录给**回测结果 + 总体胜率**;**默认资金 100W** 扣减计算盈亏。
4. **EOD 自动复盘**:**当天收盘后,若有持仓或当日有买卖,自动撮合 + 盯市 + 生成「市场环境 + 个人操作日志」当日复盘回测**。
5. **整库备份**:支持**整个 SQLite 数据库全量导出 / 全量导入**(备份还原)。

### 非目标(本期不做)

- 真实下单/券商对接(纯模拟盘台账)。
- 分时级撮合(撮合用日 K 的 open/high/low/close 近似,见 §8)。
- 多账户、多策略组合归因。
- 复权价交易(模拟盘按未复权价,与实盘体验一致)。

---

## 2. 设计决策汇总(brainstorming 已确认)

| # | 决策点 | 选定 |
|---|---|---|
| D1 | 推进方式 | **一次完整设计,分阶段实现** |
| D2 | 买入池+回测本质 | **模拟交易台账**(记录真实下单/成交,据此算盈亏与胜率) |
| D3 | 仓位/资金 | **手动指定金额 或 股数**(起始 100W) |
| D4 | 手续费 | **含简化费用**(佣金 + 印花税 + 过户费,可配置) |
| D5 | 龙虎榜排序 | **总净买入额(含游资)**,多日 = N 日累计净买入 |
| D6 | 非即时单成交 | **真实挂单撮合**(开盘价/收盘价/指定价进委托区,触发条件成交) |
| D7 | 侧栏布局 | **两个新侧栏页**(资金榜单、模拟盘) |
| D8 | 结果页呈现 | **渲染同款 markdown 卡片 + 注入「加入买入池」按钮** |
| D9 | 撮合架构 | **方案 C:惰性补算 + 轻量定时**(关 App 不丢单 + 收盘自动复盘) |
| D10 | EOD 自动复盘 | 收盘后若有持仓/成交 → 自动撮合 + 收盘价盯市 + 市场环境 + 个人操作日志复盘 + 通知 |
| D11 | 落库 | **全部 SQLite**(模拟盘不用 JSON,统一进 `kronos_data.sqlite`) |
| D12 | 数据复用 | **尽量复用**现有 repo / service / job / 引擎(见 §3) |
| D13 | 整库导出/导入格式 | **原始 .db 快照**(SQLite backup API;导入=校验后整库替换,替换前自动备份当前库) |

### 待用户否决的默认决定(非阻塞)

- **D14(默认)**:整库导出/导入入口放在**现有「后台配置」(settings) 页的「数据备份与恢复」卡片**,而非新增第 3 个侧栏页(低频管理操作,避免侧栏臃肿)。如需独立页,DESKTOP_PAGES 加一条即可。
- **D15(默认)**:**胜率口径 = 每笔卖出 vs 持仓均价**(盈利卖出笔数 / 总卖出笔数);均价为含费摊薄成本。另存「完整回合(建仓→清仓)」统计为次要指标。
- **D16(默认)**:盘中盯市价用 `watchlist_service.quotes`(东财→腾讯回退);收盘结算价用 `ohlcv_repo` 当日 `close`。

---

## 3. 复用清单(已核对真实代码)

> 「数据尽量复用」(D12)的落点。引用均已 grep/read 确认存在。

| 复用对象 | 位置 | 用途 |
|---|---|---|
| `moneyflow_repo.get_top_n(trade_date, top_n)` | `data_store/moneyflow_repo.py` | **主力买入榜单日数据已现成**;多日聚合 = 窗口内逐日累加 |
| Tushare `pro.moneyflow_dc(trade_date=...)` 同步 | `scripts/run_opportunity_discovery.py:143` | 主力买入榜回填(已在用,5000 积分) |
| `OpportunityDiscovery.run(limit, test_codes, source)` | `scripts/run_opportunity_discovery.py:721` | **选中股票分析直接传 `test_codes=选中`**,完全同款算法 |
| `_run_opportunity_job(job_id, params)` | `webui/core.py:1747` | 已是桌面后台任务;`params` 已支持 `stock_codes` / `source` |
| `_parse_opportunity_report(path)` | `webui/core.py:913` | **结果页复用它解析机会报告 → 渲染卡片**,绕开从零写 md 解析 |
| `_latest_primary_opportunity_reports(limit)` | `webui/core.py:806` | 取最新报告路径 |
| `MarketEnvAnalyzer.analyze_market_environment(market_data)` | `analysis/market_env_analyzer.py:200` | **EOD 复盘的市场环境段**(沪深 300 近 5/20 日、涨跌家数) |
| `WatchlistService.quotes(...)` | `webui/services/watchlist_service.py` | 模拟盘盘中盯市实时价(东财→腾讯回退) |
| `ohlcv_repo`(日 K) | `data_store/ohlcv_repo.py` | 撮合补算 open/high/low/close + 收盘结算价 |
| SQLite 基础设施 | `data_store/connection.py` + `data_store/schema.py` | `get_conn()` 自动迁移;`db_path()` 已 user-root 感知(`KRONOS_DATA_DIR`),命令行/打包 App 同库 |
| 迁移机制 | `data_store/schema.py::migrate()` | 新表 = 追加 `(7, "CREATE TABLE …")`,幂等 |
| 页面注册 | `webui/core.py:2032 DESKTOP_PAGES` | 数据驱动,加条目即自动路由 + 侧栏 |
| 桌面交互 JS | `webui/static/kronos_desktop_app.js` | **改桌面逻辑改这个 .js**(非 desktop.html 内联) |
| 应用内通知栏分类 | `kronos_desktop_app.js:4847 kronos_notify_cats2` | EOD 复盘通知挂这套分类机制 |
| 定时守护范式 | `start_pattern_autorefresh`(形态自动刷新) | EOD 轻量定时器**照此范式**实现 |
| `results_dir()` | `webui/paths.py`(机会分数 parity 修复时引入) | 复盘 markdown / 报告统一读写目录 |

### 现有缺口(需新建)

- **龙虎榜单(含游资净额)**:现有 `dragon_tiger_inst`(schema v6)是**机构席位级、仅机构**,无游资、无「按日全市场榜单」。D5 口径(总净买入额含游资)= Tushare `top_list`,**需新表 + 新回填**。
- **markdown → HTML 渲染器**:webui 现无任何 md 渲染。结果页优先走 `_parse_opportunity_report` 结构化渲染;若要保真 md,再引入轻量渲染(见 §6.2)。
- **模拟盘台账 / 撮合 / EOD / 整库备份**:全新。

---

## 4. 架构总览

```
桌面侧栏
├── [新] 资金榜单 (capital_rankings)
│     ├ tab 主力买入榜  ──┐
│     └ tab 龙虎榜       ──┤ 多选/全选 → [分析选中 N 只]
│                          ↓
│                      复用 _run_opportunity_job(test_codes)  ← 同款 v20 算法
│                          ↓
│                  机会分析结果页(同款卡片 + [加入买入池])
│                          ↓
├── [新] 模拟盘 (paper_trading)
│     ├ 账户头(100W 起)/ 下单框 / 委托区 / 持仓 / 成交日志
│     └ 回测区(胜率/盈亏比/回撤/收益率/逐笔)
│            ↑ 撮合引擎(惰性补算 + EOD 定时器 + 当日复盘)
│
└── 后台配置 (settings) → [新] 数据备份与恢复卡片(整库 .db 导出/导入)
```

### 新建模块清单

| 模块 | 类型 | 职责 |
|---|---|---|
| `data_store/schema.py` (改) | 迁移 | 追加 `(7, …)`:`dragon_tiger_list` + `paper_*` 表 |
| `data_store/dragon_tiger_list_repo.py` | repo | 龙虎榜单(含游资净额)`upsert_df` / `get_top_n(date)` / `get_aggregated(end_date, days)` / 上榜次数 |
| `webui/services/capital_rankings_service.py` | service | 主力买入榜 + 龙虎榜:查询 / 回填 N 天 / 单日·多日聚合 / Top-N |
| `webui/services/paper_trading_service.py` | service | 模拟盘台账:账户 / 下单 / 撤单 / 持仓 / 成交流水 / 费用 / 统计(胜率等) |
| `webui/services/paper_trading_engine.py` | engine | 挂单撮合(惰性补算)+ EOD 结算 + 收盘盯市 + 当日复盘生成 + 定时守护 |
| `webui/services/report_markdown.py` | service | 机会报告 → HTML 卡片(优先复用 `_parse_opportunity_report`)+ 注入「加入买入池」 |
| `webui/services/db_backup_service.py` | service | 整库导出(backup API 快照)/ 导入(校验 → 自动备份 → 灌库 → migrate) |
| `webui/core.py` (改) | 路由 | DESKTOP_PAGES 加 `capital_rankings` / `paper_trading`;注册新 API |
| `webui/static/kronos_desktop_app.js` (改) | 前端 | 两新页 UI、下单交互、加池按钮、通知接入 |

---

## 5. 数据模型(SQLite schema v7)

> 全部进 `kronos_data.sqlite`,经 `migrate()` 幂等创建。列名为拟定,实现时按 Tushare `top_list` 实际字段微调。

### 5.1 龙虎榜单 `dragon_tiger_list`(Tushare top_list,含游资净额)

```sql
CREATE TABLE IF NOT EXISTS dragon_tiger_list (
  trade_date    TEXT NOT NULL,
  ts_code       TEXT NOT NULL,
  name          TEXT,
  close         REAL,
  pct_change    REAL,
  turnover_rate REAL,
  amount        REAL,   -- 当日总成交额
  l_buy         REAL,   -- 龙虎榜买入额
  l_sell        REAL,   -- 龙虎榜卖出额
  l_amount      REAL,   -- 龙虎榜成交额
  net_amount    REAL,   -- 龙虎榜净买入额(含游资) ← 排序键
  net_rate      REAL,
  amount_rate   REAL,
  reason        TEXT,   -- 上榜原因(同一股可多条)
  PRIMARY KEY (trade_date, ts_code, reason)
);
CREATE INDEX IF NOT EXISTS idx_dtl_date_net ON dragon_tiger_list(trade_date, net_amount DESC);
CREATE INDEX IF NOT EXISTS idx_dtl_code     ON dragon_tiger_list(ts_code, trade_date);
```

- **单日榜**:`SELECT … GROUP BY ts_code SUM(net_amount) ORDER BY SUM DESC`(合并多条上榜原因)。
- **多日聚合**:窗口内 `GROUP BY ts_code SUM(net_amount), COUNT(DISTINCT trade_date) AS 上榜次数 ORDER BY SUM DESC`。

### 5.2 模拟盘表组 `paper_*`

```sql
-- 单账户(id 恒为 1)
CREATE TABLE IF NOT EXISTS paper_account (
  id           INTEGER PRIMARY KEY CHECK(id=1),
  initial_cash REAL NOT NULL,   -- 默认 1000000
  cash         REAL NOT NULL,   -- 可用资金
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

-- 委托(即时单直接 filled;open/close/limit 进 pending 等撮合)
CREATE TABLE IF NOT EXISTS paper_order (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_code       TEXT NOT NULL,
  name          TEXT,
  side          TEXT NOT NULL CHECK(side IN ('buy','sell')),
  price_type    TEXT NOT NULL CHECK(price_type IN ('market','open','close','limit')),
  limit_price   REAL,            -- 指定价(limit)
  qty           INTEGER,         -- 股数(下单按股数时;100 整数倍)
  amount_budget REAL,            -- 金额(下单按金额时,撮合价确定后折算股数)
  status        TEXT NOT NULL CHECK(status IN ('pending','filled','cancelled','rejected')),
  created_at    TEXT NOT NULL,
  created_date  TEXT NOT NULL,   -- 下单交易日(撮合判定起点)
  filled_at     TEXT,
  filled_price  REAL,
  filled_qty    INTEGER,
  fee           REAL,
  note          TEXT             -- 拒单/撤单原因
);
CREATE INDEX IF NOT EXISTS idx_porder_status ON paper_order(status, ts_code);

-- 持仓(含费摊薄均价)
CREATE TABLE IF NOT EXISTS paper_position (
  ts_code    TEXT PRIMARY KEY,
  name       TEXT,
  qty        INTEGER NOT NULL,
  avg_cost   REAL NOT NULL,      -- (累计买入含费) / 累计股数
  opened_at  TEXT,
  updated_at TEXT
);

-- 成交流水(每笔 fill;卖出结算 realized_pnl)
CREATE TABLE IF NOT EXISTS paper_trade (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id     INTEGER,
  ts_code      TEXT NOT NULL,
  name         TEXT,
  side         TEXT NOT NULL,
  price        REAL NOT NULL,
  qty          INTEGER NOT NULL,
  gross        REAL NOT NULL,    -- price*qty
  fee          REAL NOT NULL,    -- 佣金+印花税+过户费
  realized_pnl REAL,             -- 仅卖出:(卖净) - avg_cost*qty
  traded_at    TEXT NOT NULL,
  trade_date   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ptrade_code ON paper_trade(ts_code, traded_at);

-- 每日权益曲线(回撤/收益率)
CREATE TABLE IF NOT EXISTS paper_equity_curve (
  trade_date     TEXT PRIMARY KEY,
  cash           REAL,
  position_value REAL,           -- 按当日 close 盯市
  total_equity   REAL,
  daily_pnl      REAL
);

-- 费用等配置(键值)
CREATE TABLE IF NOT EXISTS paper_settings (
  key   TEXT PRIMARY KEY,
  value TEXT
);
```

- `paper_settings` 默认项:`commission_rate=0.00025`、`commission_min=5`、`stamp_tax=0.0005`(仅卖)、`transfer_fee=0.00001`、`initial_cash=1000000`。
- 胜率等统计**实时由 `paper_trade` 聚合**,不落冗余表(D15)。

---

## 6. 功能详述

### 6.1 资金榜单页(`capital_rankings`)

**控件区**
- Tab:`主力买入榜` / `龙虎榜`。
- `[刷新/补偿 __ 天]`(默认 30,可填)→ 触发后台回填那 N 个交易日(见 §7 回填)。
- 模式:`单日 ▾日期` / `多日聚合 ▾天数`。
- `Top __`(默认 50)。

**榜单表**

| 列 | 主力买入榜 | 龙虎榜 |
|---|---|---|
| 排名 / 代码 / 名称 / 最新价 / 涨跌幅 | ✓ | ✓ |
| 主力净流入 | `net_amount`(moneyflow) | — |
| 总净买入额(含游资) | — | `SUM(net_amount)` |
| 上榜次数 | — | 多日聚合时显示 |
| ☑ 选择 / 个股分析 / 加自选 | ✓ | ✓ |

**底部**:`☑全选` + `[分析选中 N 只]`。

- **单日** = `get_top_n(date)`;**多日聚合** = 窗口内累加排序 + 上榜次数。
- 「加自选」复用 `WatchlistService`;「最新价/涨跌幅」复用 `WatchlistService.quotes`。

### 6.2 机会分析结果页

- `[分析选中]` → `POST /api/capital-rankings/analyze {codes}` → 复用 **`_run_opportunity_job`**(内部 `OpportunityDiscovery.run(test_codes=codes, source='multi')`),返回 `job_id`。
- 完全同款 v5.6 / 评分 v20 算法 + S/A/B/C 分层。
- 任务完成 → 生成 `opportunity_top10_*.md`(写入 `results_dir()`)。
- 结果页渲染:`report_markdown.py`
  - **首选**:复用 `_parse_opportunity_report(path)` 得结构化数据 → 渲染**同款卡片**(涨幅/板块/量化/技术/基本面/情绪资金/消息/亮点加分/高级/复盘),与 `opportunity_top10_*.md` 视觉一致。
  - **备选**:若结构化覆盖不全,补一个轻量 md→HTML(优先 `markdown` 库;若不愿加依赖则最小自渲染)。
- **每张股票卡注入 `[加入买入池]`** → 弹出下单框(§6.3),预填代码/名称/现价。

### 6.3 模拟盘页(`paper_trading`)

**账户头**:起始 100W · 可用资金 · 持仓市值 · 总资产 · 总收益率 · 已实现盈亏 · 浮动盈亏。

**下单框**
- 标的 + 方向(买/卖)+ 价格类型 `[即时 / 开盘价 / 收盘价 / 指定价 __]` + `金额 __` 或 `股数 __`(按 100 股取整,资金不足拒单)。
- **即时单立即成交**(用 `quotes` 实时价);`开盘价/收盘价/指定价` → 进**委托区**(`pending`),可撤单。

**委托区**:pending 单列表 + 撤单。
**持仓表**:代码/名称/股数/成本价/现价/浮动盈亏率/`[卖出]`(盯市价走 `quotes`)。
**成交/操作日志**:每笔买卖(时间/方向/价/股数/费用/已实现盈亏)。

**回测 / 胜率区**
- 总体胜率(D15:盈利卖出笔 / 总卖出笔)· 盈亏比 · 平均盈/亏 · 最大单笔盈/亏 · **最大回撤**(`paper_equity_curve`)· 总收益率 + **逐笔明细表**。

### 6.4 整库导出 / 导入(数据备份与恢复)

入口:后台配置(settings)页「数据备份与恢复」卡片(D14)。

- **导出** `GET /api/data/export`:用 **SQLite backup API**(`live_conn.backup(tmp_conn)`)生成一致性快照 `kronos_backup_YYYYMMDD_HHMM.db` 回传下载(即便有并发读也安全)。
- **导入** `POST /api/data/import`(上传 .db):
  1. **校验**上传文件是合法 Kronos 库(只读打开 → 查 `schema_version` 及关键表如 `ohlcv`/`moneyflow_dc` 存在),非法直接拒绝。
  2. **自动备份当前库**为 `kronos_backup_before_import_YYYYMMDD_HHMM.db`(防导错丢数据)。
  3. **灌库(关键техника)**:`uploaded_conn.backup(live_conn)` —— **把上传库内容通过 backup API 写进当前活连接的库**,而非在磁盘上换文件。规避「Robyn 多线程仍持旧文件句柄 + WAL `-wal/-shm` 边车」的并发坑(见 §10 风险)。
  4. 灌库后对 `live_conn` 跑 `migrate()`,把旧版本备份升到当前 schema。
  5. 返回导入结果(版本、表行数概览)。

> 备注:若实测 backup-into-live 受限,退化方案 = `close_conn()` 全线程释放 + 换文件 + 重置 `_schema_applied`;但首选 backup-into-live。

---

## 7. API 端点清单

**资金榜单**
- `GET  /api/capital-rankings/moneyflow?date=&days=&top=&mode=single|aggregate`
- `GET  /api/capital-rankings/dragon-tiger?date=&days=&top=&mode=single|aggregate`
- `POST /api/capital-rankings/backfill {type: moneyflow|dragon_tiger|both, days:30}` → 后台 job
- `POST /api/capital-rankings/analyze {codes:[…]}` → 复用 `_run_opportunity_job`,返回 `job_id`

**机会结果**(复用现有 job 状态查询)
- `GET  /api/opportunity/result/{job_id}` → `report_markdown` 渲染的 HTML(或结构化 JSON 供前端渲染)

**模拟盘**
- `GET  /api/paper/account` · `GET /api/paper/positions` · `GET /api/paper/orders?status=` · `GET /api/paper/trades` · `GET /api/paper/stats`
- `POST /api/paper/order {ts_code,side,price_type,limit_price?,qty?|amount?}`
- `POST /api/paper/order/{id}/cancel`
- `POST /api/paper/settle`(手动触发撮合补算/EOD,也供定时器调用)
- `POST /api/paper/reset {initial_cash}`
- `GET  /api/paper/reviews` · `GET /api/paper/review/{date}`

**数据备份**
- `GET  /api/data/export` · `POST /api/data/import`(multipart)

---

## 8. 撮合 + EOD 引擎(方案 C 细节)

### 8.1 惰性补算(关 App 也不丢单)

打开模拟盘 / 刷新行情 / 调 `/api/paper/settle` 时,对每张 `pending` 单回放其 `created_date` 之后已有日 K 的交易日:
- **开盘价单** → 当日 `open` 成交。
- **收盘价单** → 当日 `close` 成交。
- **指定价(limit)买** → 当日 `low <= limit` 则成交;成交价 = `min(open, limit)`(开盘已低于限价则按开盘)。
- **指定价(limit)卖** → 当日 `high >= limit` 则成交;成交价 = `max(open, limit)`。
- 数据源:`ohlcv_repo` 日 K(缺数据则该日跳过,留 pending 待补)。

### 8.2 轻量定时(收盘自动)

照 `start_pattern_autorefresh` 范式起守护线程:
- 开关:`KRONOS_DISABLE_PAPER_EOD`(禁用)、`KRONOS_PAPER_EOD_AFTER`(默认 15:30)、`KRONOS_PAPER_EOD_INTERVAL`。
- 交易日 15:30 后触发一次当日 EOD(幂等:已结算当日则跳过)。

### 8.3 EOD 结算 + 当日复盘(D10)

**触发条件**:当日有持仓 **或** 当日有成交,才生成复盘。

1. **撮合**当日 open/close/触价 limit 单(走 §8.1)。
2. **盯市**:按当日 `close` 更新 `paper_position` 浮动盈亏,写 `paper_equity_curve`(cash / position_value / total_equity / daily_pnl)。
3. **生成当日复盘 markdown**(写 `results_dir()/paper_review_YYYY-MM-DD.md`):
   - **市场环境**:复用 `MarketEnvAnalyzer.analyze_market_environment()`(沪深 300 近 5/20 日、涨跌家数、环境分级)。
   - **个人操作日志结算**:当日成交明细、当日已实现盈亏、累计胜率变化、当日权益与回撤。
4. **推应用内通知栏**:挂现有 `kronos_notify_cats2` 分类机制(新增「复盘」类目或归入「自选」);后端生成复盘 → 前端通知栏可见。**精确接入点(后端复盘数据如何到前端通知流)在实现期对齐现有通知数据流**。

---

## 9. 费用模型(D4,可配置 `paper_settings`)

| 费项 | 默认 | 方向 |
|---|---|---|
| 佣金 | 万 2.5(0.00025),最低 5 元 | 买 + 卖 |
| 印花税 | 0.05%(0.0005) | 仅卖出 |
| 过户费 | 万 0.1(0.00001) | 买 + 卖 |

- 买入总成本 = `price*qty + 佣金 + 过户费` → 计入 `avg_cost`(摊薄)。
- 卖出净额 = `price*qty - 佣金 - 印花税 - 过户费`。
- 卖出 `realized_pnl = 卖出净额 - avg_cost*qty`。

---

## 10. 风险与降级

| 风险 | 缓解 |
|---|---|
| 龙虎榜 `top_list` 积分/限频 | akshare 回退(`ak.stock_lhb_detail_em` 等);失败写 `sync_log` |
| `moneyflow_dc` 需 5000 积分 | 项目已在用;不可达时榜单显示「数据待回填」 |
| **导入换库并发安全** | **首选 backup-into-live-conn**(不换文件,WAL 安全);退化才换文件+全线程 `close_conn` |
| 导入了非 Kronos / 旧版库 | 导入前校验 + 导入后 `migrate()` 升级;导入前自动备份当前库 |
| 撮合用日 K 近似 | 明确为「触价/开收盘」近似,非分时;UI 注明「模拟撮合」 |
| EOD 定时器仅 App 运行时触发 | 惰性补算兜底关机期间漏单;下次打开自动补 |
| 复权 | 模拟盘用未复权价(与实盘一致),复盘注明 |
| 通知接入点未完全确定 | §8.3 标为实现期对齐,不阻塞前 5 期 |

---

## 11. 分期实现计划

> 每期结束需通过验证(verifier/手测)才进下一期。

1. **数据层**:schema v7(`dragon_tiger_list` + `paper_*`)+ `dragon_tiger_list_repo` + `top_list` 回填 + moneyflow 回填 loop。
2. **资金榜单**:`capital_rankings_service` + 页面(双 tab / 单日·多日 / Top-N / 多选全选)+ `[分析选中]` 接 `_run_opportunity_job`。
3. **机会结果页**:`report_markdown`(复用 `_parse_opportunity_report`)+ 同款卡片 + `[加入买入池]`。
4. **模拟盘台账**:`paper_trading_service`(账户/下单/即时成交/持仓/费用/统计)+ 页面 + 回测胜率区。
5. **撮合 + EOD**:`paper_trading_engine`(惰性补算 + open/close/limit)+ EOD 定时器 + 当日复盘 + 通知。
6. **整库备份**:`db_backup_service`(backup API 导出 + 校验 + 自动备份 + 灌库 migrate)+ settings 页卡片。

---

## 12. 验收标准(关键)

- 资金榜单两榜可刷新补偿任意 N 天、单日与多日聚合切换、Top-N、全选/多选生效。
- 「分析选中」产出与命令行机会挖掘**同分同结论**(同款算法),结果页视觉≈ `opportunity_top10_*.md`。
- 加入买入池 → 即时/开盘/收盘/指定价买卖全链路成交正确;100W 资金按含费规则扣减;胜率/回撤/收益率与逐笔明细自洽。
- 收盘后自动撮合 + 盯市 + 生成「市场环境 + 操作日志」复盘 + 通知(满足触发条件时)。
- 关 App 期间到期的挂单,下次打开惰性补算成交,不丢单。
- 整库导出得到可用 .db 快照;导入校验 + 自动备份 + 灌库 + migrate 后数据完整、并发无损。
