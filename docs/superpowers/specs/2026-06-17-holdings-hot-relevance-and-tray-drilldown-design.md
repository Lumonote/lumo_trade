# 持仓·热点关联面板 + 行情台(托盘弹窗)直达个股/板块 — 设计

日期：2026-06-17
分支：V2.1.1
状态：设计已与用户确认，待写实施计划

## 背景与问题

两个相关的可用性问题，集中在「风险·机遇 作战大屏」与「行情台(托盘弹窗)」：

1. **风险·机遇大屏的「持仓 · 组合风险」面板信息冗余、不够有效。**
   该面板当前显示 `组合风险分 / 敞口 / 集中度 / 回撤` 加每只持仓的 `动作·风险·机会`。但敞口/集中度/回撤/持仓数**已经在顶部 KPI 条 (`ccPills`) 重复出现**，面板本身缺乏「我的持仓和当下热点的关系」这一更可操作的视角。用户希望把这块腾出来，改成**持仓与热点板块、热点资讯的关联程度**，要有有效展示。

2. **行情台(托盘弹窗)点击进不去工作台个股；热点板块根本点不动。**
   托盘弹窗(`desktop/tray.html`，窗口标题即「Kronos 行情台」)里：
   - 点股票路由到 `/desktop/workbench?stock=<code>`，但主窗对 `?stock=` 的自动打开逻辑**埋在机会列表渲染函数里**(`kronos_desktop_app.js:3703`，`#opportunityList` 渲染器内部)。机会数据为空/慢/报错时 `openStockContext` 不触发，用户落在工作台却看不到个股弹窗。
   - 热点板块行是 `<div style="cursor:default">`，**完全没有路由**(`tray.html:304`)，点了没反应。

## 目标 / 非目标

**目标**
- 把「持仓 · 组合风险」面板改造为「持仓 · 热点关联」：逐只持仓展示与热点板块/热点资讯的关联度(0–100)、命中板块芯片、命中资讯芯片，按关联度降序，表头汇总「踩中 X / 脱离 Y」。
- 行情台点股票稳定直达工作台个股分析(`?stock=` 健壮化)。
- 行情台点热点板块 → 主窗打开该板块**成分股列表**，每只股票可再点进个股分析。
- 关联评分逻辑做成**可单测的纯函数**；各数据源**独立降级**，缺源只置灰不崩。

**非目标**
- 不改组合风险本身的计算(`score_portfolio_risk` 不动，数字仍供顶部 KPI 条)。
- 不改机会挖掘/评分算法、不改报告生成。
- 不做板块成分股的离线入库/历史化(成分股走实时拉取，缺源即降级)。
- 不重做托盘窗口架构(仅令板块行可点 + 绑定事件)。

## 关键既有设施(复用)

| 能力 | 位置 |
|---|---|
| 大屏 payload 编排(纯注入式、逐源降级) | `webui/services/command_center_service.py::CommandCenterService` |
| 大屏数据源装配 | `webui/core.py:222 COMMAND_CENTER_SERVICE` |
| 持仓(模拟盘账户+持仓+回撤) | `webui/core.py:131 _cc_holdings()` → `positions[]: {ts_code,name,market_value,float_pnl_rate,...}` |
| 个股→热门板块归属索引 | `webui/core.py:1809 _hot_sector_stock_membership_index(hot_sector)` → `{code6: [{board_name,board_rank,stock_rank,main_net_inflow,main_net_inflow_text,change_pct,lhb_hit,...}]}` |
| 按日期取热门板块快照 | `webui/core.py:1471 _hot_sector_snapshot_for_date(date)` |
| 市场情报(金十/东财热度/东财快讯/新浪快讯) | `webui/core.py:929 _load_market_intelligence()` |
| 个股分析弹窗(工作台个股) | `kronos_desktop_app.js:5096 openStockContext(target)` |
| 东财 clist 拉取(可传 `fs`) | `webui/services/market_intelligence.py fetch_eastmoney_clist(fs, fid, limit)` |
| 托盘→主窗导航 | `desktop/tray.html openMain(route)` → Rust `open_main`(`window.location.assign`) |
| 大屏纯评分函数集 | `analysis/risk_opportunity_engine.py` |

---

## 任务 1：「持仓 · 热点关联」面板

### 1.1 后端纯函数 — `analysis/risk_opportunity_engine.py`

新增 `score_holdings_relevance(positions, membership_index, news_index, *, sector_weight=0.6, news_weight=0.4)`。

**输入**
- `positions`：`[{ts_code, name, market_value, float_pnl_rate, ...}]`(来自 `_cc_holdings`)。
- `membership_index`：`{code6: [membership, ...]}`(来自 `_hot_sector_stock_membership_index`)。
- `news_index`：`{code6: [{platform, title}, ...]}`(来自新增 `_holdings_news_index`，见 1.3)。

> **代码归一**：持仓 `ts_code`(如 `600519.SH`)在函数内取前 6 位数字归一为 `code6`，再查 `membership_index`/`news_index`；两个索引均以 `code6` 为键。输出行的 `code` 为归一后的 `code6`。

**输出**(按 `relevance` 降序，次级按 `market_value` 降序)
```
[{
  code, name, market_value, float_pnl_rate,
  relevance,            # 0–100 总关联度
  sector_relevance,     # 0–100
  news_relevance,       # 0–100
  boards: [{name, board_rank, stock_rank, main_net_inflow, main_net_inflow_text, change_pct, lhb_hit}],  # 最热(board_rank 最小)在前，封顶 3 条
  news:   [{platform, title}],   # 封顶 3 条
  status: '踩中' | '脱离',
}]
```

**评分(常量为模块级、可调；用户已知会调权重)**

板块关联 `sector_relevance`(取 board_rank 最小的「最热命中板块」为基准)：
- `base = clamp(100 - (board_rank - 1) * RANK_DECAY, RANK_FLOOR, 100)`；`board_rank` 缺失取 `RANK_UNKNOWN`。
  默认 `RANK_DECAY=8, RANK_FLOOR=20, RANK_UNKNOWN=55`(板块#1→100，#10→28)。
- `+ stock_rank_bonus = clamp(STOCK_TOP_BONUS - (stock_rank-1)*STOCK_DECAY, 0, STOCK_TOP_BONUS)`(默认 12/2：板块内 #1 +12)。
- `+ LHB_BONUS`(默认 +8)若任一命中板块 `lhb_hit`。
- `+ MULTI_BOARD_BONUS`(默认 +5)若命中 ≥2 个热门板块。
- `clamp(…, 0, 100)`；无命中 → 0。

资讯关联 `news_relevance = clamp(Σ platform_weight, 0, 100)`：
- 平台权重 `NEWS_WEIGHTS = {'东财人气热度':45, '金十快讯':40, '东财快讯':35, '新浪快讯':35}`，未知平台默认 20。
- 无命中 → 0。

总分与状态：
- `relevance = round(sector_weight * sector_relevance + news_weight * news_relevance)`。
- `status = '踩中'` 当 `boards` 或 `news` 非空，否则 `'脱离'`。

> 纯函数：不做任何 I/O、不做名称模糊匹配(匹配在 `_holdings_news_index` 完成)。仅消费 dict，便于单测。

### 1.2 服务编排 — `webui/services/command_center_service.py`

- `__init__` 新增两个注入源：
  - `hot_membership`：`callable(date) -> {code6: [membership]}`。
  - `news_index`：`callable(positions) -> {code6: [{platform,title}]}`。
- `overview(...)` 内(在已取得 `report`、`hold` 之后)：
  ```python
  membership, dms = self._safe(lambda: self._hot_membership(report.get("date")), {})
  degraded["hot_sector"] = dms
  news_idx, dnw = self._safe(lambda: self._news_index(hold.get("positions", [])), {})
  degraded["news"] = dnw
  holdings_relevance = eng.score_holdings_relevance(
      hold.get("positions", []), membership, news_idx)
  ```
- payload 增加 `"holdings_relevance": holdings_relevance`(`portfolio` 仍保留供顶部 KPI 条)。

### 1.3 数据装配 — `webui/core.py`

- 新增 `_holdings_news_index(positions, intelligence)`：对每只持仓(code6 + 中文名)扫描一次情报，命中即收。
  - `intelligence['jinshi']`(`{title,source,time,url}`)：`code` 或 `name` 出现在 `title+source` → `{platform:'金十快讯', title}`。
  - `intelligence['eastmoney']['hot_stocks']`：`code` 等于行 code，或 `name` 等于行 name → `{platform:'东财人气热度', title: f'{name} 资金热度'}`。
  - `intelligence['eastmoney_news']`、`intelligence['sina_news']`：`code`/`name` 出现在 `title` → `{platform:'东财快讯'/'新浪快讯', title}`。
  - 每只封顶 ~5 条；去重(platform+title)。
- 装配 `COMMAND_CENTER_SERVICE`(core.py:222)新增：
  ```python
  hot_membership=lambda date=None: _hot_sector_stock_membership_index(_hot_sector_snapshot_for_date(date)),
  news_index=lambda positions: _holdings_news_index(positions, _load_market_intelligence()),
  ```

### 1.4 前端 — `webui/static/kronos_desktop_app.js`

- `ccRankings(d)`：第三个面板由「持仓·组合风险」改为「持仓·热点关联」：
  - 表头：`<b>持仓 · 热点关联</b><span class="tag">板块/资讯 命中</span>`，右侧汇总 `踩中 X / 脱离 Y`(由 `holdings_relevance` 的 status 统计)。
  - 数据取 `d.holdings_relevance`(已降序)。无持仓 → `无模拟盘持仓`；有持仓但 `degraded.hot_sector && degraded.news` → 置灰提示「热点/资讯源暂不可用」。
- 新增 `ccHoldingRelevanceRow(h)`：
  - 主行：股票名(可点→个股) + 关联度进度条(按 status 着色：踩中=绿、脱离=灰) + 数值。
  - 副行芯片：`🔥<板块名> #<board_rank>(<净流入text>)`(每个板块芯片可点→板块成分股，见任务2b) · `📰<平台>×<count>`；`脱离` 则灰字「脱离热点 · 无板块/资讯」。
  - 主行带 `data-cc-code/name`(复用既有 `.acts`→analyze 模式)；板块芯片带 `data-cc-board-code/name`。
- `ccBindActions(host, data)`：新增绑定 `[data-cc-board-code]` → `openBoardDrill(code, name)`(任务2b，同窗直接打开，不走 open_main)。
- 顶部 KPI 条不动(敞口/集中/回撤/持仓数已在此)。

### 1.5 样式 — `webui/static/kronos_desktop.css`
- `.cc-rel-bar`(进度条，踩中/脱离两色)、`.cc-chip`(板块/资讯芯片，板块芯片 hover 可点态)。尽量复用既有 `.rk-row/.rnm/.rsub/.tag`。

### 1.6 测试
- `tests/test_risk_opportunity_engine.py` 扩展 `score_holdings_relevance`：仅板块命中 / 仅资讯命中 / 两者 / 都无 / 多板块取最热 + 多板块加成 / LHB 加成 / 降序与 market_value 次级排序 / 空持仓 / 空索引(降级) / 权重参数生效。
- `tests/test_command_center_service.py` 扩展：注入假 `hot_membership`/`news_index`，断言 payload 含 `holdings_relevance` 且 `degraded.hot_sector/news` 正确;某源抛异常时该面板降级而其余不受影响。

---

## 任务 2：行情台(托盘弹窗)直达

### 2a 股票稳定直达个股(`?stock=` 健壮化)

- 新增 `maybeOpenFromQuery()`(`kronos_desktop_app.js`)：读 `location.search`：
  - 有 `?stock=<code>` → `openStockContext({stock_code, stock_name:''})`(自带取数，不依赖机会列表)。
  - 否则有 `?board=<code>`/`?board_name=<name>` → `openBoardDrill(code, name)`(见 2b)。
  - 用一次性 guard 防重复触发。
- 在主程序引导处(页面 init 派发，约 `kronos_desktop_app.js:1625` 之后)调用一次 `maybeOpenFromQuery()`。
- 移除 `kronos_desktop_app.js:3703` 块内的 `openStockContext` 调用(避免双开)，保留 `loadKline(firstCode)` 让画布默认显示请求股票的 K 线。`?stock=` 的个股弹窗统一由 `maybeOpenFromQuery` 负责。

### 2b 热点板块可点 → 展开成分股

**托盘 `desktop/tray.html`**
- 板块行从 `<div class="row" style="cursor:default">` 改为可点：
  `<button class="row" data-route="/desktop/workbench?board=<code>&board_name=<name>">`(有 `code` 用 `?board=&board_name=`；无 `code` 仅 `?board_name=<name>`)。
- 渲染后补 `bindRows($("#boards"))`(当前未绑定)。

**后端成分股接口**
- `webui/core.py` 新增 `board_stocks_payload(code, name='', limit=60)`：
  - `code` 存在 → `stocks = MARKET_INTELLIGENCE_SERVICE.fetch_eastmoney_clist(fs=f'b:{code}', fid='f3', limit=limit)`(东财板块成分：`fs=b:BKxxxx`)。
  - 返回 `{board:{code,name}, stocks:[{code,name,price,change_pct,main_net_inflow,main_net_inflow_text}], count, degraded, note}`；拉取失败/空 → `degraded:True` + `note`，`stocks:[]`。
  - 实施时需实测 `fs=b:<BKcode>` 返回成分股(复用现有 `fields=f12,f14,f2,f3,f62,f100`)。
- `webui/robyn_app.py` 新增 `@_native_get("/api/market/board-stocks")` → `webui_core.board_stocks_payload(code, name)`。

**主窗板块成分股弹窗**
- `webui/templates/desktop.html` 新增 `#boardDrillModal`(结构仿 `#stockContextModal`：标题=板块名、meta、body 列表)。
- `kronos_desktop_app.js` 新增 `openBoardDrill(code, name)`：开弹窗 → `fetchJson('/api/market/board-stocks?code=&name=')` → 渲染成分股行(名/代码/价/涨跌幅/净流入)，每行可点 → `openStockContext`(从板块弹窗进入个股，弹窗可叠加或先关板块弹窗)。降级时显示 `note` + 东财板块外链兜底。
- 入口三处复用 `openBoardDrill`：托盘路由 `?board=`(经 `maybeOpenFromQuery`)、任务1 面板板块芯片、(可选)大屏「行业热力」块。

### 2c 测试
- `tests/test_market_intelligence.py` 或新增 `tests/test_board_stocks_payload.py`：mock `fetch_eastmoney_clist`，断言 `board_stocks_payload` 正常返回 / 空与异常降级。
- `?stock=`/`?board=` 前端逻辑 + 托盘点击：JS 无单测框架，列入**手动验证**(见下)。

---

## 数据流(任务1)

```
command_center_overview(date)
  └─ CommandCenterService.overview(report, available_dates)
       ├─ holdings = _cc_holdings()                         # positions[]
       ├─ membership = hot_membership(report.date)          # _hot_sector_stock_membership_index(_hot_sector_snapshot_for_date)
       ├─ news_idx   = news_index(positions)                # _holdings_news_index(positions, _load_market_intelligence())
       ├─ holdings_relevance = eng.score_holdings_relevance(positions, membership, news_idx)
       └─ payload += { holdings_relevance, degraded: {hot_sector, news, ...} }
                                   │
   前端 ccRankings → 持仓·热点关联面板(逐只行 + 芯片 + 踩中/脱离汇总)
```

## 降级策略
- `hot_membership` 抛错/无快照 → `membership={}` → 各持仓 `sector_relevance=0`、`boards=[]`，`degraded.hot_sector=True`。
- `news_index` 抛错 → `news_idx={}` → `news_relevance=0`，`degraded.news=True`。
- 两源皆降级且有持仓 → 面板置灰提示，但行仍列出(关联度=0、全脱离)。
- `board_stocks_payload` 拉取失败 → 弹窗显示 `note` + 外链，不报错。
- 既有 `portfolio/matrix/capital` 降级行为不变。

## 测试与验证计划
- **单测**：`pytest tests/test_risk_opportunity_engine.py tests/test_command_center_service.py tests/test_market_intelligence.py`(含新增用例)必须全绿。
- **手动验证**(需本地后端 7070 / 打包 App)：
  1. 风险·机遇大屏：有模拟盘持仓时，「持仓·热点关联」逐只显示关联度与板块/资讯芯片，按关联度降序，表头「踩中/脱离」数对。
  2. 点持仓名 → 个股弹窗；点板块芯片 → 板块成分股弹窗。
  3. 行情台点自选/热点股票/异动 → 主窗稳定打开该股个股弹窗(机会列表为空也能开)。
  4. 行情台点热点板块 → 主窗打开该板块成分股弹窗；点其中个股 → 个股弹窗。
  5. 断网/缺快照下各面板置灰不崩。
- **注意**：改了 `desktop/tray.html` 与前端静态资源，**打包 App 需重新打包**生效(参见记忆 Desktop Packaging / Inline JS Extracted)。

## 文件改动清单
**后端**
1. `analysis/risk_opportunity_engine.py` — `+ score_holdings_relevance` + 评分常量。
2. `webui/services/command_center_service.py` — 注入 `hot_membership`/`news_index`；`overview` 计算并加 `holdings_relevance` + 降级位。
3. `webui/core.py` — `+ _holdings_news_index`；装配两个新源；`+ board_stocks_payload`。
4. `webui/robyn_app.py` — `+ GET /api/market/board-stocks`。

**前端**
5. `webui/static/kronos_desktop_app.js` — `ccRankings` 面板重做 + `ccHoldingRelevanceRow` + `ccBindActions` 板块芯片绑定 + `openBoardDrill` + `maybeOpenFromQuery` + 移除 3703 处 openStockContext 双开。
6. `webui/static/kronos_desktop.css` — 关联度条 / 芯片 / 板块弹窗样式。
7. `webui/templates/desktop.html` — `#boardDrillModal` 结构。
8. `desktop/tray.html` — 板块行可点 + `bindRows`。

**测试**
9. `tests/test_risk_opportunity_engine.py` — `score_holdings_relevance` 用例。
10. `tests/test_command_center_service.py` — payload `holdings_relevance` + 降级。
11. `tests/test_market_intelligence.py`(或新建)— `board_stocks_payload`。
