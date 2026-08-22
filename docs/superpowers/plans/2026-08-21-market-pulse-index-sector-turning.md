# 总览页「指数风向 + 板块机会与拐点」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在桌面「总览」页新增「指数风向」(四大指数状态分级 + 风格轴)与「板块机会与拐点」(已触发 / 临界观察双轨)两个分区,全部基于本地已有数据面,拐点判据须通过历史胜率校验才准上线。

**Architecture:** 纯函数分析模块(`analysis/index_pulse.py`、`analysis/sector_turning.py`)零 I/O、可离线测试;取数与聚合落在 `data_store/sector_map_repo.py`、`analysis/sector_series.py`;编排层 `webui/services/market_pulse_service.py` 全注入,逐源独立降级;`CommandCenterService` 只加一个注入槽,业务逻辑零改动。板块日序列预聚合落新表,避免每次请求扫 115 万行。

**Tech Stack:** Python 3.13 / SQLite(`data_store` schema 迁移体系)/ pandas / Robyn(`webui/robyn_app.py`)/ 原生 JS(esbuild 压缩后的 `kronos_desktop_app.js`)/ pytest

设计 spec: `docs/superpowers/specs/2026-08-21-market-pulse-index-sector-turning-design.md`

---

## Global Constraints

- **禁止执行任何 git 写操作**(commit / add / push / 分支)。每个任务最后的「交付」步骤只列出应提交的文件清单,由用户自行提交。只读 git 查询允许。
- **所有数据落 SQLite**,不用 CSV 落盘。新持久化走 `data_store` schema 表或 `kv_repo`。
- **数据库连接统一用 `from data_store.connection import get_conn`**,签名为 `get_conn() -> sqlite3.Connection`(注意:没有 `get_connection` / `connection` 这两个名字)。
- **金额单位**:`moneyflow_dc.net_amount` 单位由同行 `amount_unit` 决定,取值为 `'万元'` 或 `NULL`(NULL 按 `'万元'` 处理),历史上有 `'元'` 的行需乘 `1e-4` 归一到万元。归一口径照抄 `analysis/accumulation_detector.py:46`:`mult = 1e-4 if str(r.get("amount_unit") or "万元") == "元" else 1.0`。
- **`moneyflow_dc` 全市场快照的哨兵是 `top_n=0`**,其它 top_n 值是榜单快照,聚合时必须过滤 `top_n=0`。
- **`moneyflow_dc.trade_date` 是 ISO 格式 `YYYY-MM-DD`**;`market_daily.trade_date` 是紧凑格式 `YYYYMMDD`。两者不可混用。
- **`moneyflow_dc.ts_code` 带交易所后缀**(如 `000001.SZ`);`quant_radar_stock_daily.code` 与 `hot_sector_stock.code` 是裸 6 位码。跨表关联必须先归一到裸码。
- **收益口径强制复用 `analysis/backtest_metrics.py`**:`annualize_chained(returns_pct, weights=None)`。禁止手搓「算术均值再取幂」的年化。
- **前端 `webui/static/kronos_desktop_app.js` 是 esbuild 压缩产物**(504118 字节,顶层 classic script,非模块):只允许在**文件末尾追加** IIFE,**追加块必须以分号结尾**,块首也加分号保护(`;(function(){...})();`),改完必须跑 `node --check`。禁止用 `innerHTML +=`(会灭掉已绑监听)。
- **免责声明**:所有新增结论性文案沿用项目合规措辞,用「正向 / 风险」而非「暴涨 / 暴跌」,不出现具体回测数字承诺。
- **打包 App 需重打包才能生效**(dev 环境即时生效)。
- dev e2e 端口用 `KRONOS_PORT=7071`(7070 被打包 App 占用)。
- 测试命令统一 `python -m pytest`。

---

## File Structure

| 文件 | 职责 | 状态 |
|---|---|---|
| `data_store/schema.py` | 追加 migration 21(两张新表) | 修改 |
| `tests/test_schema_migration_v21.py` | 迁移测试 | 新建 |
| `data_store/sector_map_repo.py` | 个股 → 板块映射 + 覆盖度 | 新建 |
| `tests/test_sector_map_repo.py` | 映射测试 | 新建 |
| `analysis/sector_series.py` | 板块×日序列聚合(纯函数)+ 读写 | 新建 |
| `tests/test_sector_series.py` | 聚合测试 | 新建 |
| `scripts/backfill_sector_series.py` | 历史 194 日回填 | 新建 |
| `analysis/sector_turning.py` | 拐点判据(纯函数) | 新建 |
| `tests/test_sector_turning.py` | 判据测试 | 新建 |
| `scripts/validate_turning_rules.py` | 判据历史校验(上线卡点) | 新建 |
| `analysis/index_pulse.py` | 指数指标 + 状态分级(纯函数) | 新建 |
| `tests/test_index_pulse.py` | 指数测试 | 新建 |
| `data_store/index_quote_fetch.py` | 指数实时报价(新浪) | 新建 |
| `tests/test_index_quote_fetch.py` | 报价解析测试 | 新建 |
| `analysis/market_regime.py` | `INDEX_SYMBOLS` 补三条指数 | 修改 |
| `webui/services/market_pulse_service.py` | 编排层(全注入) | 新建 |
| `tests/test_market_pulse_service.py` | 编排 + 降级测试 | 新建 |
| `webui/core.py` | 装配服务 + `market_pulse_payload()` | 修改 |
| `webui/services/command_center_service.py` | 加 `market_pulse` 注入槽 | 修改 |
| `webui/robyn_app.py` | `/api/market-pulse` 路由 | 修改 |
| `webui/static/kronos_desktop_app.js` | 末尾追加渲染 IIFE | 修改(追加) |
| `webui/static/kronos_desktop.css` | 末尾追加样式 | 修改(追加) |

**与 spec 的四处细化**(实施中确认的必要调整):

1. spec §4.3 表结构补 `sector_type` 列(行业 / 概念)与 `seat_count` 列。个股天然属于 1 个行业 + N 个概念,单列 `sector` 无法表达;T5 判据需要席位数进序列。
2. spec §4.3 的 `turnover_median` 改名 `amount_median`(成交额中位数,万元)。`moneyflow_dc` 没有换手率列,但成交额可由 `net_amount / (net_amount_rate/100)` 精确反推(已在真库验证:000002.SZ 2026-08-20 反推 44551 万元,量级合理)。
3. spec §4.1 模块表补 `data_store/index_quote_fetch.py`。指数实时报价走新浪 `hq.sinajs.cn`(已实测 6 条指数全部可取),`WatchlistService.quotes` 只吃个股代码,不能复用。
4. 任务顺序与 spec §12 不同:判据纯函数(Task 4)必须先于校验脚本(Task 5),否则没有可校验的对象。校验仍是硬卡点,位置不变。

---

## ✅ Task 1 已完成:schema v21(迁移测试 5/5 + 全量迁移回归 23 passed)

---

## ✅ Task 2 已完成:个股→板块映射(8/8 测试绿;App 库覆盖度 87.3%,板块 157 个)

---

## ✅ Task 3 已完成:板块日序列聚合(16/16 测试绿;App 库回填 194 天 / 30458 条 / 157 板块)

---

## ✅ Task 4 已完成:拐点判据 T1-T5(26/26 测试绿)

---

## ✅ Task 5 已完成:判据校验(卡点通过) — 用户决定放宽胜率至≥50%,仅 T5 席位共振上线(568样本/+0.66%超额/50.2%胜率/+30.9%年化);T1-T4 否决并记入 spec §13;kv rule_stats=enabled:[T5]

---

## ✅ Task 6 已完成:指数层(21+5 测试绿;六指数真数据冒烟:上证range/深成pullback/创业板pullback/科创50 risk/风格轴小盘占优;INDEX_SYMBOLS 已扩三条)

---

## ✅ Task 7 已完成:编排层+接线(14/14 测试绿;e2e 实证:/api/market-pulse 4指数+风格轴+T5触发5板块/临界7;command-center 总览 payload 已含 market_pulse)

---

## ✅ Task 8 已完成:前端两分区(node --check 通过;Playwright 实证:4 指数卡片+5 已触发+7 临界观察,零控制台错误,刷新无重复插入)

---

## ✅ Task 9 已完成:守护线程(9/9 测试绿;startup 钩子已接 start_sector_refresh;今日无资金流时正确降级不写)

---

## ✅ 全部任务完成

- [x] 8 个新增测试文件全绿(v21 迁移 5 + 映射 8 + 序列 16 + 判据 26 + 指数 21 + 报价 5 + 编排 14 + 守护 9 = **104 测试**)
- [x] `node --check webui/static/kronos_desktop_app.js` 通过
- [x] `/api/market-pulse` 返回四条指数 + 风格轴 + 板块双列表(已触发 5 / 临界观察 7)
- [x] spec §13「已否决判据」已填入实测数据,T5 经用户决策上线
- [x] 全量回归 1335 passed / 10 failed(全部为既有失败,与本次零交集)
- [x] 已告知用户:打包 App 需重打包才能生效
- [x] 已告知用户:压缩 JS 尾部追加块需尽快 commit,否则下次 bundle 重建会丢失
