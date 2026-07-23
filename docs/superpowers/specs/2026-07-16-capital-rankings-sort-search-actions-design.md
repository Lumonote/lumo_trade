# 资金榜单全表排序 + 搜索 + 行内按钮 — 设计

日期: 2026-07-16

## 需求

资金榜单页所有列表都要支持：**排序**、**个股与板块搜索**，并在每行右侧新增**「加自选」+「个股分析」**按钮。用户反馈量化交易分析（量化雷达）tab 下的列表既不能排序也不能搜索。

覆盖范围（用户确认「全部」）：

- 主榜：主力净流入榜 / 龙虎榜
- 窗口榜：5日净流入榜 / 30日净流入榜
- 量化 tab：活跃股票榜 / 活跃板块 / 收割预警（卡片形态）/ 吸筹埋伏榜

## 现状盘点

| 榜单 | 排序 | 搜索 | 行内按钮 | 渲染函数 |
|---|---|---|---|---|
| 主力净流入榜 / 龙虎榜（主榜） | ✅ 表头排序（`sortedCapitalRows`/`capitalSortValue`/`capitalSort`） | ❌ | ✅ 明细 / 分析(机会挖掘) / 加自选 | `capitalTableHtml(t,false)` |
| 5日 / 30日窗口榜 | ❌（compact 分支 `n=!e` 关闭排序） | ❌ | ❌ | `capitalTableHtml(t,true)` → `renderCapitalWindow` |
| 量化·活跃股票榜 | ❌ | ⚠️ 仅服务端按日搜索 `quantSearchDay` | ❌ | `quantPaintStocks` |
| 量化·活跃板块 | ❌ | ❌ | ❌ | `quantPaintSectors` |
| 量化·收割预警（卡片） | ❌ | ❌ | ❌ | `quantPaintAlerts` |
| 量化·吸筹埋伏榜 | ❌ | ❌ | ❌ | `renderQuantAccum` |

关键前提：

- **后端零改动**。排序/搜索纯客户端；按钮复用现有端点。所有榜单数据已全量加载到前端 state。
- `kronos_desktop_app.js` 是 **esbuild 压缩单行产物**（变量改名 t/e/a，函数声明仍全局提升）。改 JS 必须先用 python 提取实际字节做锚点，不能用原文；末尾追加的格式化函数块仍可读。
- 主榜「个股分析」入口现状：点击**股票名单元格**已打开个股套件弹窗（见 `2026-07-16-capital-rankings-stock-detail-design.md` 的捕获阶段委托）。本设计新增的是**显式按钮**，二者可并存。

## 决策（已与用户确认）

1. **「个股分析」按钮** → 打开个股分析套件弹窗 `openStockContext({stock_code, stock_name})`（含快照/财务/量化行为等 tab），与「点股票名」行为一致。
2. **搜索** → 每表独立客户端过滤（大小写不敏感，跨 代码/名称/行业/板块 字段），过滤后重新分页。活跃股票榜的**服务端按日搜索保留为底座**，客户端过滤叠加其上。
3. **覆盖范围** → 全部，含 5日/30日窗口榜。
4. **主榜按钮** → 原「分析」（机会挖掘 `analyzeCapitalSelection`）与新「个股分析」（套件弹窗）**两个都保留**，职能不同。

## 方案

在 `kronos_desktop_app.js` **末尾追加**一组共享 helper + 一次性 document 委托，四处列表复用，避免重复实现排序/过滤/按钮逻辑。压缩文件的既有 paint 函数用「python 字节锚点整段替换」升级。

### 共享 helper（新增，文件尾）

- **`rowActionsHtml(code, name)`** → 统一右侧两按钮：
  `加自选`（`data-row-watch="<code>" data-row-name="<name>"`）+ `个股分析`（`data-row-context="<code>" data-row-name="<name>"`）。窄栏用 `.button.secondary.compact`。**仅用于原本无按钮的表**（窗口榜 / 量化四榜 / 收割预警卡片）。主榜已有自己的 actions 列（含 加自选），只追加单个「个股分析」按钮，不套用本 helper，避免 加自选 重复。
- **`tableFilterRows(rows, term, fields)`** → `term` 归一小写；对每行 `fields`（如 `['code','name','industry']`）任一命中即保留；空 term 返回原数组。
- **`quantSortRows(rows, key, dir)`** → 数值优先、退化到 `localeCompare('zh-Hans-CN',{numeric:true})`，空值沉底，稳定（同值保持原序）；逻辑对齐既有 `sortedCapitalRows`。
- **`quantSortHeaderHtml(cols, sortState)`** → 产出带 `data-quant-sort` + ▲▼ 箭头的 `<thead>`；`cols` 为 `{key,label,sortable}` 列表。

### 一次性 document 委托（新增，boot 时挂一次）

监听 `click`：

- `[data-row-watch]` → `addToWatchlist(code, name).catch(e=>showToast(e.message))`
- `[data-row-context]` → `openStockContext({stock_code:code, stock_name:name})`

好处：分页翻页 / 重渲染 / 搜索过滤后按钮**自动生效**，无需每次重新绑定。委托用冒泡阶段即可（不与主榜「股票名单元格」的捕获阶段拦截冲突，二者作用元素不同）。

### 分块改动

**A. 主榜（moneyflow / dragon_tiger）**
- 工具栏（`.capital-actions` 附近）加搜索框 `#capitalSearchInput`，写 `state.capital.search`；`renderCapitalRankings` 渲染前用 `tableFilterRows(state.capital.rows, search, ['code','name','ts_code'])` 过滤（不改 `state.capital.rows` 本体，过滤是渲染期派生），再交 `capitalTableHtml`。选中/全选逻辑仍基于完整 `rows`。
- `capitalCellHtml` 的 `actions` 分支追加「个股分析」按钮（`data-row-context`），与现有 明细/分析/加自选 并列。

**B. 5日 / 30日窗口榜**
- `capitalTableHtml` compact 分支（`e=true`）：
  - 开启表头排序：compact 时也生成 `data-cap-sort`；每窗口独立 sort state `state.capital.sortWindow[5|30]`（`capitalSort` 委托区分主表/窗口表）。
  - `capitalColumns` compact 列表尾部加 `actions` 列（`rowActionsHtml`）。
  - `renderCapitalWindow` 上方加搜索框 `#capitalWindow{5|30}Search`（过滤该窗口 rows）。
- 窄栏两按钮用 compact 尺寸；CSS 保证不换行。

**C. 量化·活跃股票榜 / 活跃板块 / 吸筹埋伏榜**
- `quantPaintStocks` / `quantPaintSectors` / `renderQuantAccum` 整段替换为增强版，统一管线：
  `客户端搜索过滤 → quantSortRows 排序 → quantPageSlice 分页 → quantSortHeaderHtml 可排序表头 + rowActionsHtml 行内按钮`。
- 每表加独立搜索框 + 独立 sort state（存 `quantState().sort.{stocks|sectors|accum}`，形如 `{key,dir}`）。
- 股票榜：客户端搜索叠加在服务端 `quantSearchDay` 结果之上（服务端拉全量→客户端再过滤/排序）。
- 板块表：按钮作用于「代表股」`top.code`；搜索字段 `['industry']` +（有代表股则 name/code）。
- 吸筹榜：搜索字段 `['code','name','industry']`；按钮作用于该行 code。
- 行点击进深评（`quantAnalyzeStock` / `data-accum-code`）保留；新按钮 `stopPropagation` 避免误触发行点击。

**D. 量化·收割预警（卡片形态）**
- 卡片非表格：加搜索框（过滤高危+疑似被砸名单，字段 `['code','name','industry']`）+ 一个排序下拉 `#quantAlertSortSelect`（按 综合活跃度 / 涨跌% / 名称）→ 排序后 paint。
- 每张卡片右侧加 `rowActionsHtml`（加自选 + 个股分析）；沿用 document 委托。

### 状态与 DOM 约定

- `state.capital`：加 `search`（主榜）、`sortWindow{5,30}`（窗口榜）。
- `quantState()`：加 `sort.{stocks,sectors,accum}`、`search.{stocks,sectors,accum,alerts}`、`alertSort`。
- 搜索输入用 `input` 事件去抖（~120ms）→ 重置该表页码到 1 → 重 paint。
- 新增 DOM 元素（搜索框/下拉）加在 `desktop.html` 对应 panel-header 内；量化四榜与窗口榜各自的 header。

## CSS（`kronos_desktop.css` 追加）

- `.row-cell-actions`：`display:flex; gap:6px; flex-wrap:nowrap`（窄栏两按钮不换行）。
- `.table-search`：搜索框统一样式，窄屏 max-width。
- 复用既有 `.cap-sortable`/`.cap-sort-arrow`/`.quant-type-tag`，量化表头排序补 `.quant-sortable`/`.quant-sort-arrow`（镜像 cap 样式）。

## 复用入口（已核对）

- `openStockContext({stock_code, stock_name})` — 个股套件弹窗（`normalizeStockCode` 内部归一）。
- `addToWatchlist(code, name="")` — `/api/watchlist/add`，返回 toast。
- `analyzeCapitalSelection([code])` — 机会挖掘评分（主榜「分析」，不改）。
- `quantAnalyzeStock(code)` — 量化深评行点击（不改）。
- `sortedCapitalRows`/`capitalSortValue`/`capitalSort` — 主榜排序（窗口榜复用）。
- `quantPageSlice`/`quantPagerHtml`/`quantBindPager` — 量化分页（保留）。
- `showToast` / `html` / `num` / `changeClass` / `quantNum` — 既有工具。

## 备选方案（未采用）

- **一个全局搜索框统一过滤所有榜**：交互简单但跨表语义混乱（个股 vs 板块字段不同、各表分页独立），用户已选「每表独立过滤」。
- **服务端排序/搜索**：数据已全量在前端，客户端足够且零后端改动、零网络往返。
- **窗口榜每行加「详情」链接替代按钮**：入口太深，与主榜按钮不一致。

## 验证

- `node --check webui/static/kronos_desktop_app.js` 语法校验（追加后）。
- e2e（起 dev 服务，`KRONOS_PORT=` 指定端口）：
  - 主榜：搜索框实时过滤 + 重新分页；表头排序变向；「个股分析」弹出 `#stockContextModal`；「加自选」toast；原「分析」机会挖掘仍工作。
  - 窗口榜：表头可排序、搜索、两按钮生效。
  - 量化四榜：各自搜索 + 排序 + 按钮；股票榜服务端按日搜索与客户端过滤叠加正确；收割预警卡片搜索+排序下拉+按钮。
  - 行点击深评未被按钮误触发（`stopPropagation` 生效）。
- Playwright 无头截图确认各榜排序箭头/搜索/按钮渲染。
- 打包 App 需重打包（或清 WKWebView 缓存）后生效。

## 测试

- JS 无单测框架 → 以 `node --check` + e2e 冒烟为准。
- 若抽取纯函数（`tableFilterRows`/`quantSortRows`）到可测位置成本高（压缩产物），本次以 e2e 覆盖，不新增 JS 单测。
- 后端零改动 → 无新增 python 测试；跑一遍现有 `tests/test_quant_radar_service.py` 确认未回归（预期既存失败清单不变）。

## 已知既存失败清单（非本功能引入，勿误判）

- `test_schema_migration_v7`/`v16`（断言硬编码 schema 版本，工作区已到 v19）
- `test_robyn_app` 两例（品牌 Lumo Trade / 本机 tushare 配置）
- `test_webui_core_surface` 三例（断言已抽离的内联 JS）
- `test_market_intelligence_xueqiu`、`test_opportunity_*` 系列
