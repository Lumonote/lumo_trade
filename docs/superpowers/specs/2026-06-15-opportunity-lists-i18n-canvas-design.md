# 投资机会页:历史表格化 + 术语中文化 + 画布按日 — 设计 Spec

> 状态:设计已定稿(brainstorming 完成,用户已认可),待写实施计划
> 日期:2026-06-15
> 语言/口径:中文界面;A 股口径;单用户单进程桌面端
> 分支:V2.1.1(工作区已有大量未提交的「机会页重构」改动,本 spec 在其之上继续)

---

## 1. 目标 / 背景

投资机会挖掘页(`active_page == 'opportunities'`)有三处体验问题,本期一并解决:

1. **历史榜单 / 历史热门板块只是卡片堆叠**,不能像「资金榜单」那样按列排序、看全字段。用户要求改成**和资金榜单同款的可点列排序表格**。
2. **大量量化信息名称是英文**(评分维度 key、风险信号 key、来源枚举、量化模型名等)直接显示给用户。要求**全量中文化**。
3. **投资机会画布只显示"最后一次"挖掘**,无法看某一天的快照。要求**保留默认最新 + 增加按日选择查询**。

### 非目标(本期不做)

- 不改动机会评分算法 / 评分产物结构,只**消费并美化展示**。
- 不重构「资金榜单」表格本身(只抽取其纯排序核心为共享函数,资金榜单渲染保持不动,详见 D1)。
- 不做 Excel 导出表头 / 后端列名的中文化(`hot_sector_repo.export_*` / 画布导出)——列为后续单独项,避免本次扩散(详见 D2)。
- 不新增前端依赖。

---

## 2. 设计决策汇总(brainstorming 已确认)

| # | 决策点 | 选定 |
|---|---|---|
| Q1 | 列表呈现 | **可排序表格(全层)**:历史 run 列表 / run 内股票 / 板块快照列表 / 板块成分股 四层都用与资金榜单同款的可点列排序表格(中文表头、缺失沉底、三态排序) |
| Q2 | 画布按日 | **默认最近 + 选日**:默认仍显示最近一次 run(维持现状),画布头部加日期/run 选择器可切到任意历史日,不强制今天 |
| Q3 | 中文化范围 | **全量术语**:评分维度 key、信号 key、量化模型名、来源/策略等枚举,凡展示给用户的英文统一中文化,建一份共享 EN→CN 字典 |
| D1 | 排序核心复用方式 | **抽共享纯排序函数,资金榜单代码不动**(回归风险最低)——而非把资金榜单一起重构进新组件 |
| D2 | 中文化边界 | **本期只做 UI 展示层**(客户端渲染);Excel/后端列名中文化列为后续 |

---

## 3. 复用清单(已核对真实代码)

| 复用对象 | 位置 | 用途 |
|---|---|---|
| `sortedCapitalRows(rows, key, dir)` | `kronos_desktop_app.js:7972` | 排序核心范式:数值/字符串混排、缺失值恒沉底、同值稳定。**据其算法新建**通用 `sortRows`(资金榜单本身不改,见 D1) |
| `capitalTableHtml(rows, compact)` | `kronos_desktop_app.js:8161` | 表头三态箭头 + `data-cap-sort` 点击排序 + 主行/明细行结构范式 |
| `CAPITAL_COLUMN_LABELS` | `kronos_desktop_app.js:7790` | 列 key→中文表头映射范式 |
| `CANVAS_SCORE_LABELS` / `CANVAS_SIGNAL_LABELS` | `kronos_desktop_app.js:2380` / `:2385` | 已有的评分/信号 EN→CN 局部字典(将被统一字典合并取代,并补齐缺口) |
| `opportunityRunRow` / `renderOpportunityHistoryData` | `kronos_desktop_app.js:520` / `:537` | 历史 run 列表(现为卡片,改表格) |
| `opportunityAnalysisCard` | `kronos_desktop_app.js:682` | run 内股票卡片(现直接打印英文 score key,改表格 + 中文化) |
| `hotSectorSnapshotRow` / `hotSectorBoardHistoryRow` / `hotSectorStockAnalysisCard` | `kronos_desktop_app.js:751` / `:765` / `:781` | 板块快照 / 板块 / 成分股(现为卡片,改表格) |
| `renderOpportunitySectorsData` | `kronos_desktop_app.js:584` | 热门板块三层钻取导航(保留导航,换渲染) |
| `renderOpportunityCanvas` / `renderOpportunityCanvasDetail` | `kronos_desktop_app.js:2916` / `:2455` | 画布渲染 + 详情面板(详情改用统一字典) |
| `_build_opportunity_canvas(items, latest_report, market_env, hot_sector)` | `webui/core.py`(组装于 `:1180`) | 复用同一函数为「指定日」重建画布 |
| `_load_opportunity_run_payload(report_file)` | `webui/core.py:1362` | 按报告文件取某 run 的结构化 items |
| `_load_hot_sector_snapshot_summary(snapshot_id)` | `webui/core.py:1280` | 取指定快照摘要(板块级) |
| `opportunity_repo.list_runs(run_date=, limit=)` / `items_for_run(rid)` / `runs_by_day(limit)` | `data_store/opportunity_repo.py` | 按日/按 run 取入库数据(已支持) |
| `hot_sector_repo.list_snapshots(limit)` | `data_store/hot_sector_repo.py:168` | 列历史快照,用于"按日期找快照" |
| `/api/opportunity-runs?date=&limit=&days=` | `webui/robyn_app.py:968` | 已支持按日过滤 + 按天聚合 |
| 表单来源选项中文 | `desktop.html:198-203` / `:361-366` | source 枚举的中文口径(multi→多源候选 等)直接对齐 |

### 现有缺口(需新建)

- **通用可排序表格组件**:`sortRows` / `sortableTableHtml` / `bindSortableHeaders`(三态 降→升→取消)+ 四层列规格。
- **统一术语字典**:`OPP_LABELS` + `zhLabel(kind, key)`,合并 `CANVAS_*_LABELS` 并补齐缺失维度键。
- **按日画布接口**:后端 `/api/opportunity-canvas`(按 `run_id` 或 `date`)+「按日期找热门板块快照」helper;前端画布日期/run 选择器 + 切换重渲染。

---

## 4. 架构总览

```
机会页 (opportunities)
│
├─ 历史与板块抽屉 (#opportunityDataBody)
│    ├─ 历史 run 列表        ─┐
│    ├─ run 内股票           │  共享组件:
│    ├─ 板块快照列表          ├─ sortRows(rows,key,dir,valueFor)   ← 抽自 sortedCapitalRows
│    └─ 板块成分股           ─┘   sortableTableHtml(rows, spec)
│                                 bindSortableHeaders(container, sortState, rerender)
│                                 ↑ 列头/单元格文案统一走 zhLabel()
│
├─ 统一术语字典 OPP_LABELS{score,signal,source,strategy,relation,model} + zhLabel(kind,key)
│    应用:四层表格列头/单元格、画布详情(score_breakdown/signals/quant_models)、run 来源
│
└─ 投资机会画布
     画布头部 [日期/run 选择器 ▼]  默认=最新
        └ change → GET /api/opportunity-canvas?run_id=N
                      └ core: items_for_run(N) + 按日找 hot_sector 快照 → _build_opportunity_canvas
                      ← {canvas, run, hot_sector, date}
                    → renderOpportunityCanvas(canvas)
```

---

## 5. 方案 A — 历史/板块四层表格化

### A.1 通用组件(新增,资金榜单不动)

> 放在 `kronos_desktop_app.js` 现有工具函数区(资金榜单段之外,供复用)。

- **`sortRows(rows, key, dir, valueFor)`** — 据 `sortedCapitalRows`(`:7972`)的纯算法**新建**通用函数(`sortedCapitalRows` 不动):
  - `valueFor(row, key)` 返回该列排序原值;空值判定 `== null || '' || NaN`。
  - 规则:缺失值**恒沉底**(与方向无关);数值比数值,否则 `localeCompare('zh-Hans-CN',{numeric:true})`;同值按原序稳定。
- **`sortableTableHtml(rows, spec)`** — `spec = { columns, sortState, sortAttr, tableClass, rowAttrs?, emptyText? }`,`columns[i] = { key, label, sortable=true, cell(row), value(row)?, className? }`:
  - 表头:`label` 经 `zhLabel` 已是中文;可排序列渲染 `data-${sortAttr}="${key}"` + 三态箭头(▲/▼/无),范式照 `capitalTableHtml`(`:8169-8177`)。
  - 行:`rowAttrs(row)` 注入点击/选中所需 `data-*`(如 `data-stock-code`),保留现有个股点击绑定。
- **`bindSortableHeaders(container, sortState, rerender)`** — 点击表头三态循环:`key 不同→{key,'desc'}`;`同 key && 'desc'→'asc'`;`同 key && 'asc'→ 清空(恢复原序)`。更新 `sortState` 后调 `rerender()`。

### A.2 四层列规格 + 排序状态

每层独立 sort 状态(`state.opportunityData.sortRuns` / `sortRunItems` / `state.hotSectorHistory.sortSnapshots` / `sortBoardStocks`),钻取导航(返回上一层按钮)保留不变,仅把卡片 `map(...)` 换成 `sortableTableHtml(...)` + `bindSortableHeaders(...)`。

1. **历史 run 列表**(替换 `opportunityRunRow`):列 = `run_at` 时间 / `item_count` 条数 / `source`(中文) / `mode` / `report_file` / 操作(查看全部)。`run_at` 默认降序。
2. **run 内股票**(替换 `opportunityAnalysisCard` 在历史 tab 的卡片):列 = 名次 / 名称·代码 / 综合分 / 评级 / 涨跌幅 / 关键评分维度(动态列,key 经 `zhLabel('score',…)`) / 关键信号(chase/rsi/change_3d/sell 等,经 `zhLabel('signal',…)`) / 降级标记。点击行 → 个股分析(沿用 `bindOpportunityDataStockClicks`)。
3. **板块快照列表**(替换 `hotSectorSnapshotRow`):列 = `created_at` / `trade_date` / `board_count` / `stock_count` / `relation_count` / `source`。点击行进入该快照板块表。
4. **板块成分股**(替换 `hotSectorStockAnalysisCard`):列 = `stock_rank` 名次 / 名称·代码 / `change_pct` / 主力净流入 / `candidate_rank` / 最新价 / 龙虎榜命中(`lhb_*` 汇总)。点击行 → 个股(沿用 `bindHotStockClicks`)。
   - (板块层 `hotSectorBoardHistoryRow` 作为"快照→板块"的中间钻取层,同样表格化:名次/板块名/涨跌幅/类型/主力净流入/股票数/关联数。)

> 说明:run 内股票的"评分维度"列是动态的(不同 run 的 `scores_json` key 可能不同)——列集合取当前数据并集,缺失单元格显示 `--`,与资金榜单 `capitalColumns` 动态扩列(`:7883`)同思路。

> **范围边界**:本期表格化仅覆盖用户点名的「历史」与「板块」——即历史 run 列表、run 内股票、板块快照列表、板块/成分股四(五)层。抽屉的「全部数据」tab(当前 run,用 `opportunityDataItemRow` `:492`)与主页「最新机会 Top10」卡片**不在本期范围**,保持现状;如需一并表格化列为后续。

---

## 6. 方案 B — 全量术语中文化

### B.1 统一字典(新增,取代分散字典)

```
const OPP_LABELS = {
  score:  { sector:'板块', technical:'技术', quantitative:'量化', fundamental:'基本面',
            sentiment:'情绪', news:'消息', event:'事件', events:'事件', moneyflow:'资金',
            momentum:'动量', volume_health:'量能', liquidity:'流动性', dragon_tiger:'龙虎榜',
            position_timing:'仓位择时', capital_flow:'资金流', /* ←补齐实际评分维度 */ },
  signal: { chase:'追高风险', rsi:'RSI', day_change:'当日涨幅', change_3d:'3日涨幅',
            change_5d:'5日涨幅', sell_signals:'卖出信号', buy_signals:'买入信号', quant_score:'量化总分' },
  source: { multi:'多源候选', sector_hot:'热门板块成分股', heat:'热度候选', moneyflow_dc:'东方财富资金' },
  strategy:{ balanced:'均衡', strict:'严格', loose:'宽松' },
  relation:{ dragon_tiger:'龙虎榜', sector:'板块', concept:'概念' },
  model:  { /* 已知英文模型 key 兜底,如 turtle_trading_system:'海龟交易', macd_golden_cross:'MACD金叉' … */ },
};
function zhLabel(kind, key){ return (OPP_LABELS[kind] || {})[key] || key; }  // 未命中回退原文
```

- **实际维度键以代码为准**:实现时核对 `opportunity_scorer` 产出的 `scores`/`signals` key,确保 `OPP_LABELS.score/signal` 全覆盖(已知现 `CANVAS_SCORE_LABELS` 缺 `position_timing`/`capital_flow`)。
- `CANVAS_SCORE_LABELS` / `CANVAS_SIGNAL_LABELS` 由 `OPP_LABELS.score/signal` 取代(画布详情 `:2401`/`:2424` 改调 `zhLabel`),避免两份字典漂移。

### B.2 应用点

- 四层表格列头与单元格(§5)。
- `opportunityAnalysisCard` 的 `scoreBits`(`:690-693`,现 `${html(key)}`)、`signalBits` → `zhLabel`。
- run 列表/表格的 `source` → `zhLabel('source',…)`。
- 量化模型名:报告解析多为中文,英文键经 `OPP_LABELS.model` 兜底;`opportunityCanvasQuantModels`(`:2443`)沿用。
- 回退策略:`zhLabel` 未命中**返回原 key**(绝不显示空),保证新维度键加入前不至于空白。

---

## 7. 方案 C — 投资机会画布按日

### C.1 后端

- **新增路由** `GET /api/opportunity-canvas`(`webui/robyn_app.py`),参数 `run_id`(优先)或 `date=YYYY-MM-DD`:
  1. 解析目标 run:`run_id` → 取该 run(若 `opportunity_repo` 无 `get_run(rid)`,在 `list_runs` 结果按 id 匹配,或补一个仓库函数);或 `date` → 该日最新 run(`opportunity_repo.list_runs(run_date=…, limit=1)`)。
  2. `items = opportunity_repo.items_for_run(rid)`,经现有 item→canvas 映射整形(复用 `_load_opportunity_run_payload` 的整形逻辑;必要时让其支持按 `run_id` 入参)。
  3. **热门板块快照按日匹配**:新增 `_hot_sector_snapshot_for_date(date)`——遍历 `hot_sector_repo.list_snapshots()`,取 `trade_date`(无则 `created_at` 日期)`== date`、否则 `<= date` 最近一条;再走 `_load_hot_sector_snapshot_summary(snapshot_id)`。
  4. `market_env`:目标 run 报告文件若在则 `_parse_opportunity_report` 取;否则传 `{}`(画布对空 env 已能容忍)。
  5. `canvas = _build_opportunity_canvas(items, report_meta, market_env, hot_sector)`。
  6. 返回 `{ canvas, run, hot_sector, date, degraded_count }`;run 不存在 → 404 + 友好信息。
- 默认(首屏)仍由 dashboard 内置的"最新" canvas 提供,本路由只服务"切日"。

### C.2 前端

- 画布面板头部(`desktop.html` 画布 `panel-header`,现有 `opportunityCanvasViewSwitch`/`opportunityCanvasMeta` 一带)加一个 **日期/run 选择器**(`<select>` 或 `<input type=date>`):
  - 选项数据来自已存在的 `/api/opportunity-runs?limit=…`(每条 = 一天一次 run,`run_at`/`created_at` 作 label,`id` 作 value);默认选中最新(= 现状)。
- `onchange` → `fetchJson('/api/opportunity-canvas?run_id='+id)` → `renderOpportunityCanvas(payload.canvas)` + 更新 `opportunityCanvasMeta` 为所选日期;失败 `alert`/占位。
- 状态:`state.opportunityCanvas.activeRunId`;切回最新时可清空走默认。

---

## 8. 数据流

```
[A 表格] 列表数据 (已有 API)
  /api/opportunity-runs[/items] · /api/hot-sector-snapshots · /api/hot-sector-snapshot/:id/stocks
   → loadOpportunityRuns/Items · loadHotSector* → sortableTableHtml(spec{columns→zhLabel, cell})
   → bindSortableHeaders(三态) → 点击行复用现有个股钻取

[B 字典] OPP_LABELS 一份,zhLabel(kind,key) 贯穿:表格列头/单元格、画布详情、来源

[C 画布] 选择器(/api/opportunity-runs 填充) → /api/opportunity-canvas?run_id=N
   → items_for_run + _hot_sector_snapshot_for_date → _build_opportunity_canvas → renderOpportunityCanvas
```

---

## 9. 错误处理与边界

- **空/缺失**:四层任一无数据 → 现有 `empty(...)` 占位文案保留;表格单元格缺失 → `--`(经 `sortRows` 恒沉底)。
- **排序稳定性**:同值保持服务端原序(名次/分数已是默认序),清空排序即恢复原序。
- **画布切日**:目标日无 run → 404,前端提示"该日无挖掘记录"并保留当前画布;无对应板块快照 → canvas 照常(`hot_sector` 视图为空)。
- **字典未命中**:`zhLabel` 回退原 key,不空白;新维度键加入字典前也能正常显示(只是英文)。
- **回归隔离**(D1 落地):资金榜单渲染链(`capital*`)与 `sortedCapitalRows` **完全不改**;`sortRows` 是据其算法新建的独立函数,仅供四层新表格使用。零资金榜单回归面。(把 `sortedCapitalRows` 改为委托 `sortRows` 的清理列为后续,本期不做。)

---

## 10. 测试

- **后端(pytest)**:`/api/opportunity-canvas` 新增用例——按 `run_id` 返回 canvas、按 `date` 取当日最新 run、run 不存在 404、无板块快照时 canvas 仍成立;`_hot_sector_snapshot_for_date` 精确日/回退最近日两分支。复用现有 `tests/test_opportunity_repo.py` / `test_hot_sector_repo.py` 夹具。
- **前端**:无单测框架,走人工 GUI 验证清单(见下),`sortRows` 若可纯函数化可加轻量 node 断言(可选)。
- **人工验证清单**:四层表格点列三态排序 + 缺失沉底;英文术语全部中文(评分维度/信号/来源/模型);画布选日切换正确、默认仍最新、无记录日提示。

---

## 11. 分期实现顺序(对应用户"完成以上任务之后…")

1. **Part B 字典先行**(被 A 复用):建 `OPP_LABELS` + `zhLabel`,合并/补齐 `CANVAS_*`。
2. **Part A 表格组件 + 四层接入**:`sortRows`/`sortableTableHtml`/`bindSortableHeaders` → 四层列规格(列头即用 `zhLabel`)。
3. **Part C 画布按日**:后端路由 + helper + 测试 → 前端选择器。

> 用户明确 Part C 在 A/B 之后做;A 依赖 B 的字典,故 B→A→C。
