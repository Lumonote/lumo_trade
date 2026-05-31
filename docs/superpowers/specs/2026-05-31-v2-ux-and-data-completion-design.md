# V2.0.1 桌面端总览整合 + 数据补齐 + Intel 打包 设计稿

- **作者**: OpenClawd（Claude Code 协助）
- **日期**: 2026-05-31
- **状态**: Draft（待用户复审）
- **关联代码**: `webui/templates/desktop.html` / `webui/core.py` /
  `webui/services/market_intelligence.py` / `webui/services/stock_suite_service.py` /
  `analysis/stock_analysis_suite.py` / `analysis/institutional/` / `analysis/sector_api.py` /
  `analysis/fundamental_data_collector.py` / `analysis/advanced_analysis.py` /
  `data_store/` / `packaging/scripts/`
- **关联 spec**: [`2026-05-28-individual-stock-deep-mining-design.md`](2026-05-28-individual-stock-deep-mining-design.md)
  （本期模块 E 是其 M2「真实数据 + 隔夜批」的落地与扩展）
- **外部参考**: [`wbh604/UZI-Skill`](https://github.com/wbh604/UZI-Skill) `skills/deep-analysis/scripts/`
  （A 股多源取数 / 直连 HTTP fallback / 热榜聚合 的可复用范式）

---

## 0. 背景与目标

### 0.1 背景（用户本期 6 项诉求）

1. **Intel 打包**：当前打包脚本名为 `build_universal.sh`，实则**无任何架构标志**，只产出
   宿主机原生架构（Apple Silicon → arm64，产物 `Kronos Ultra_*_aarch64.dmg` 可证）。
   需新增 Mac Intel（x86_64）打包能力。
2. **总览页冗余**：桌面端「功能总览」(`features`) 与「总览」(`overview`) 两页重复，且其中的
   「报告库」「批量结果」面板价值低。需**合并为一页**，去掉报告库/批量结果，改为
   **东方财富热榜 / 雪球热榜 / 金十数据热榜** 三个面板，并新增**个股快速搜索**入口（现无）。
3. **批量分析无直达**：批量分析跑完后，结果面板每行只挂 `data-preview-url`（打开 CSV/JSON
   文件预览），**无法点开某只股票的个股分析结果页**。
4. **板块动量非中文**：「板块动量」面板的板块名显示为英文（`AGI` / `Humanoid Robots`…），
   因其取自 `webui/core.py` 中 5 个**合成板块**的英文 `name`。需改为**真实板块 + 中文名**。
5. **综合分析偶发崩溃**：点「综合分析」时偶发 `NOT NULL constraint failed:
   top10_floatholders.holder_rank`。
6. **个股分析大面积「数据不足」**：机构持仓 / 调研 / 重仓基金 / 官方筹码 / 基本面 / 资金流 /
   情绪 等多处显示「数据不足」。需**尽可能补齐数据**，补不到的**给出具体原因/条件**。

### 0.2 本期目标

按「快速修复 → UX 整合 → 数据后端补齐 → 假阴性修复 → 打包」分阶段交付（详见 §1）：

- **模块 A**：桌面端「总览」单页化 + 三热榜 + 个股快搜。
- **模块 B**：批量分析结果行直达个股分析弹窗。
- **模块 C**：板块动量改用真实东财行业板块 + 中文名 + 真实涨跌幅。
- **模块 D**：修复 `top10_floatholders.holder_rank` NOT NULL 崩溃。
- **模块 E**：个股分析数据全面补齐 —— 机构 provider 真实落地 + 市场级批量回填 +
  复用已入库 `daily_basic`/`moneyflow_dc` + 阈值放宽 + 「数据不足」原因透出 +
  UZI 式多源直连 fallback。
- **模块 F**：Mac Intel（x86_64）独立 dmg 打包。

### 0.3 非目标

- 不做 Universal2 单包（torch 等重型 wheel 缺 universal2，本期产出**独立** x86_64 dmg）。
- 不重构 `StockAnalysisSuite` / `MarketIntelligenceService` 为新架构（沿用现有）。
- 不引入新前端框架 / 图表库（继续 Robyn + Jinja + 原生 JS + ECharts）。
- 不实现龙虎榜席位级量化识别的名单运营（沿用现有 `quant_seats.json`）。
- 不新增 Playwright 前端自动化冒烟（沿用 manual + screenshot，与上一 spec 一致）。

---

## 1. 工作分解与里程碑总览

| 阶段 | 模块 | 内容 | 体量 | 依赖 | 主要验收 |
|---|---|---|---|---|---|
| **P1 快速修复** | D | `holder_rank` NaN 兜底 | XS | 无 | 注入含 NaN 编号的样本 upsert 不再抛 NOT NULL |
| | C | 板块动量 → 真实东财行业板块 + 中文名 | S | 无 | `/api/stock-dashboard` 的 `market.sectors[].name` 为中文板块名 |
| | B | 批量结果行 → 个股弹窗直达 | S | 无 | 批量完成后点某股票打开 `openStockContext` |
| **P2 总览整合** | A | features+overview 合并、去报告库/批量结果、加三热榜、加快搜 | M | C（板块）、雪球热榜新源 | 单页呈现三热榜 + 搜索框可定位个股 |
| **P3 数据后端补齐** | E1 | survey/fund/cyq provider 真实抓取 | M | 无 | 单股 `stock_fund_stock_holder` 等可回 `fresh` |
| | E2 | `scripts/sync_institutional_data.py` 市场级回填 | M | E1、adapter key 扩展 | 跑全市场后机构表覆盖码数 ≫ 现状（2 码） |
| | E3 | 「数据不足」原因透出（AkshareUnavailable 传播 + `*_error` 暴露） | S | 无 | unavailable 文案区分「网络/熔断/限流」vs「确无数据」 |
| **P4 假阴性修复** | E4 | 基本面复用 `daily_basic`（5482 码已入库） | M | 无 | 基本面雷达维度在 `daily_basic` 命中时不再「数据不足」 |
| | E5 | 资金流复用 `moneyflow_dc`/`market_flow_daily` | S | 无 | 资金流面板优先读库，缺时再爬 |
| | E6 | OHLCV `≥60` / 技术 `≥35` 阈值放宽 + 短历史降级 | S | 无 | 40–59 日历史股票不再整页「数据不足」 |
| | E7 | UZI 式直连 HTTP fallback（Tencent/Sina 行情 + Jin10/东财快讯/同花顺新闻） | M | 无 | 情绪/新闻在 akshare 失败时仍有数据 |
| **P5 打包** | F | Mac Intel x86_64 独立 dmg | M | 可与 P1–P4 并行 | 产出 `Kronos Ultra_*_x86_64.dmg` 并在 Intel 机/Rosetta 启动 |

> 排期建议：P1 三项相互独立、当天可完成并快速验证；P5 与 P1–P4 解耦，可并行。
> P3 → P4 有先后（先把后端真实数据打通，再消化假阴性与 fallback）。
> 每个模块独立提交，遵循 [[clean-commit-on-shared-dirty-branch]]：只 `git add` 本模块改动文件。

---

## 2. 模块 A：桌面端「总览」单页整合

### 2.1 现状

- 页面注册表 `webui/core.py` `DESKTOP_PAGES`：`features`=「功能总览」、`overview`=「总览」，
  二者 90% 重叠。`desktop/index.html` 启动跳 `/desktop/features`（硬编码）。
- 模板 `webui/templates/desktop.html` 用 `{% if active_page == 'xxx' %}` 分块渲染；
  `overview` 块与 `features` 块各含一份指数/异动/快讯/板块动量，`features` 还多出
  「报告库」`#reportList`、「批量结果」`#batchRuns`、机会/模型/任务等。
- 热榜数据**已存在**：`MarketIntelligenceService.load()` 已产出 `jinshi`（金十 flash）、
  `eastmoney.hot_stocks`（东财个股热度）、`eastmoney.top_gainers`，且经 `/api/stock-dashboard`
  的 `market.intelligence` 下发；`renderHotTopics()` 已在 workbench 页渲染三块热榜。
  **缺口**：雪球热榜无数据源。
- 个股搜索**仅存在于 patterns 页**：`#patternStockInput` + `GET /api/pattern-search/stocks`
  + `openStockContext()` 钻取，可整体复用。

### 2.2 方案

1. **合并页**：保留 `features` 作为合并后的单页路由（避免改 `desktop/index.html` 硬编码跳转），
   `overview` 在 `DESKTOP_PAGES` 中移除（或别名指向 `features`）。标题定为「总览」。
   把 `overview` 块有用部分并入 `features` 块，删除重复 DOM。
2. **删面板**：移除「报告库」（topbar 按钮 `#openReportDrawerBtn`、抽屉 `#reportDrawer`、
   内联 `#reportList`）与「批量结果」`#batchRuns`/`#batchMeta` 的 DOM；JS `renderReports`/
   `renderReportsDrawer` 调用从合并页摘除（函数可保留以免影响 workbench）。后端
   `_load_report_history` / `_load_batch_summary` 保留（B 模块仍用 batch 数据）。
3. **三热榜**：把 workbench 的 `renderHotTopics` 三面板（涨幅榜/个股热度/金十快讯）迁/复用到
   合并页，并按用户语义重命名为 **东方财富热榜**（`eastmoney.hot_stocks`）、**金十数据热榜**
   （`jinshi`）、**雪球热榜**（新源，见 §2.3）。
4. **个股快搜**：在合并页顶部加 `#overviewStockSearch` 输入框 + 按钮，复用
   `GET /api/pattern-search/stocks?q=&limit=8` 做联想，选中调 `openStockContext({stock_code})`。

### 2.3 雪球热榜新数据源

`webui/services/market_intelligence.py` 新增 `fetch_xueqiu_hot()`：

- 首选 akshare `ak.stock_hot_follow_xq(symbol="最热门")`（雪球关注热度榜）。
- 兜底：UZI `lib/data_sources.py` 范式 —— 直连雪球需先 `GET https://xueqiu.com/` 取 cookie
  再请求，鉴于其 2026 年登录限制（见 UZI #51），**首选 akshare**，失败则该面板降级为
  「雪球热榜暂不可用」而非整页报错。
- 注入 `load()` 返回的 `payload` 内（约现有 `eastmoney`/`jinshi` 同级），新增 `xueqiu_hot`。

### 2.4 涉及文件

- 改：`webui/core.py`（`DESKTOP_PAGES`、可选 `_build_market_dashboard` 透传 `xueqiu_hot`）
- 改：`webui/templates/desktop.html`（合并块、删面板、三热榜、搜索框 + 绑定）
- 改：`webui/services/market_intelligence.py`（`fetch_xueqiu_hot` + `load()` 装配）
- 改：`webui/static/kronos_desktop.css`（热榜/搜索框样式，若复用现成则免）

### 2.5 验收

- 访问 `/desktop/features` 仅见一页总览；无「报告库/批量结果」入口。
- 三热榜面板均有数据或各自独立的降级文案（雪球失败不拖垮其余两个）。
- 搜索框输入「600519/贵州」可联想并点开个股分析弹窗。

---

## 3. 模块 B：批量分析 → 个股结果直达

### 3.1 现状

- 批量结果来自 `batch_results_{ts}.csv`（`analysis/batch_processor.py:make_row`，每行一只股票，
  含 `股票代码` 列）。`_load_batch_summary`（`webui/core.py`）只产出**文件级** `analysis_runs`
  （file/url/rows/top_score），不含每股明细。
- 前端批量结果行（`desktop.html` `renderReports` 段）与任务完成卡 `jobResultLinks` 仅挂
  `data-preview-url`（打开文件预览），**无 `data-stock-code`**。
- 个股结果是弹窗：`openStockContext({stock_code})` → `GET /api/stock-analysis-suite/:code`
  （仅需股票代码，无独立路由/报告 id）。

### 3.2 方案

1. **后端**：扩展 `_load_batch_summary`，对最新 `batch_results_*.csv` 额外产出
   `stocks: [{code: 股票代码, name, score: 综合评分, rating: 评级}]`（pandas 已在读该 CSV）。
2. **前端**：批量任务完成后（`job.type==="batch_analysis"`），在 `jobResultLinks` 区按通过股票
   渲染「查看分析」按钮，元素挂 `data-stock-code`/`data-stock-name`，统一绑定
   `openStockContext(stockTargetFromDataset(el.dataset))`（复用 `desktop.html` 既有 helper）。
   合并页虽删「批量结果」面板，但**任务队列/完成卡仍在**，直达入口落在完成卡上，与模块 A 不冲突。
3. 不新增后端路由（`/api/stock-analysis-suite/:code` 已足够）。

### 3.3 涉及文件

- 改：`webui/core.py`（`_load_batch_summary` 增 `stocks`）
- 改：`webui/templates/desktop.html`（`jobResultLinks` / 完成卡渲染每股直达按钮）

### 3.4 验收

- 跑一次批量分析，完成卡出现「通过 N 只」+ 每只「查看分析」按钮，点击打开对应个股弹窗。

---

## 4. 模块 C：板块动量真实板块 + 中文名

### 4.1 现状与根因

- 面板 `#sectorList` 取 `market.sectors[].name`；后端 `_build_market_dashboard`
  （`webui/core.py:1417+`）遍历 `SECTORS` 常量（`core.py:134-140`），其 `name` 为英文
  （`AGI` / `Humanoid Robots` / `Quantum Computing` / `Nuclear Fusion` / `Deep Space`），
  且为 5 个**合成**板块（绑定 `REAL_CODES_MAP` 监控股池），非真实东财板块、动量为合成值。

### 4.2 方案（用户选定「真实板块 + 中文名」）

- 复用 `analysis/sector_api.py:288-313` 已验证的东财行业板块拉取：
  `push2.eastmoney.com/api/qt/clist/get`，`fs='m:90 t:2'`，`fields` 扩为
  `f12,f14,f3`（代码 / **中文名** / 涨跌幅），按 |涨跌幅| 排序取 Top N（如 8）作为「板块动量」。
- 在 `webui/core.py` 新增 `_load_sector_momentum()`（带缓存，复用 `MarketIntelligenceService`
  已有的 industry/concept board 拉取更佳——优先复用，避免重复请求），改 `_build_market_dashboard`
  的 `sectors` 来源为真实板块行：`{name: f14, code: f12, avg_change: f3, is_hot, leader?}`。
- 领涨股（leader）可选：东财板块成分接口成本高，**本期 leader 留空或用板块涨跌幅替代**，
  保证中文名 + 真实动量先落地（leader 列为开放问题，见 §10）。
- 保留 `SECTORS` 合成常量供「粒子模拟」等其它视图使用，仅改总览面板的数据来源。

### 4.3 涉及文件

- 改：`webui/core.py`（`_build_market_dashboard` 的 `sectors` 来源；新增 `_load_sector_momentum`）
- 可能改：`webui/services/market_intelligence.py`（若复用其 board 拉取，暴露一个 getter）
- 改：`webui/templates/desktop.html`（`#sectorList` 渲染兼容真实板块字段；leader 缺省处理）

### 4.4 验收

- `/api/stock-dashboard` 的 `market.sectors[].name` 均为中文真实板块名（如「半导体」「证券」）；
  `avg_change` 为真实涨跌幅；面板按动量排序。

---

## 5. 模块 D：top10_floatholders.holder_rank 崩溃修复

### 5.1 根因（已核实）

`analysis/institutional/holders_provider.py:34-35`：
```python
if "holder_rank" not in df.columns:
    df["holder_rank"] = range(1, len(df) + 1)
```
仅在 `holder_rank` 列**完全缺失**时兜底。当上游 `top10_float` fallback 源
（`stock_circulate_stock_holder` / `stock_main_stock_holder`）返回的 `编号` 列**存在但部分行为
NaN** 时，NaN 经 `holders_repo._to_native` 变成 SQL NULL，命中 `holder_rank INTEGER NOT NULL`
（`data_store/schema.py`，且为主键），偶发抛错。

### 5.2 方案

把兜底条件扩为「缺列 **或** 含空值」，并强制整型重排（数据本就按持股排序）：
```python
if "holder_rank" not in df.columns or df["holder_rank"].isna().any():
    df["holder_rank"] = range(1, len(df) + 1)
df["holder_rank"] = df["holder_rank"].astype(int)
```
- 防御纵深（可选）：`holders_repo.upsert_top10` 内对 `holder_rank` 为 None 的行按出现序补号，
  作为第二道保险。
- **不**放宽 schema 的 NOT NULL（它是主键组成，放宽会破坏去重语义）。

### 5.3 涉及文件 / 验收

- 改：`analysis/institutional/holders_provider.py`（必）；可选 `data_store/holders_repo.py`。
- 测试：`tests/test_institutional_repos.py` / `tests/test_institutional_providers.py` 增一条
  「`编号` 列含 NaN」用例，断言 upsert 不抛、`holder_rank` 全非空且 1..N。

---

## 6. 模块 E：个股分析「数据不足」全面补齐

### 6.1 三类问题分层（来自现状盘点）

| 类型 | 表现 | 处理阶段 |
|---|---|---|
| **结构性缺口**（无单股取数路径） | survey/fund/cyq provider 的 `_fetch_and_save` 为 no-op/stub；机构表仅 ~2 码 | E1 + E2 |
| **假阴性**（数据已入库却不读 / 阈值过严） | 基本面爬实时却忽略 `daily_basic`(5482 码)；资金流忽略 `moneyflow_dc`；OHLCV `≥60` 门槛 | E4 + E5 + E6 |
| **原因被吞**（统一「数据不足」掩盖真因） | provider 把 `AkshareUnavailable`（熔断/限流/网络）压成「no data」；`*_error` 不外显 | E3 + E7 |

### 6.2 E1：机构 provider 真实抓取

- **fund（重仓基金）—— 改为单股真实抓取**：现注释称无法按股反查，但 UZI 已验证
  `ak.stock_fund_stock_holder(symbol=code)` 返回**持有该股的基金列表**（持仓量/占流通比/市值/截止日）。
  在 `data_store/akshare_adapter.py` 的 `FALLBACK_CHAINS` 增 key
  `fund_stock_holder: ["stock_fund_stock_holder"]`，`FundHoldingsProvider._fetch_and_save`
  调它、归一化入 `fund_hold_detail`。
- **cyq（官方筹码分布）—— 落地**：adapter 已有 `cyq: ["stock_cyq_em"]`。`CyqProvider.get` 改为
  读/取 `stock_cyq_em`（写 `sentiment_cache` 类型 `cyq_em` TTL 30min，见上一 spec §2.3），
  产出 90/70/50 集中度与成本分布，喂 `chip_control`。
- **survey（机构调研）—— 市场级回填为主**：`stock_jgdy_detail_em` 按交易日返回全市场，
  单股无直拉，主要靠 E2 批量回填；provider 仅读库。
- **holders（top10/gdhs）**：已是单股真实抓取，叠加模块 D 的健壮性修复即可。

### 6.3 E2：市场级批量回填脚本

落地上一 spec §2.4 规划但未实现的 `scripts/sync_institutional_data.py`：

- CLI：`--codes a,b | --watchlist | --all`、`--since YYYY-MM-DD`、
  `--tables lhb,hsgt,top10,gdhs,jgdy,fund`。
- 全市场友好的源优先用「按日/按期返回全市场」的接口（LHB `stock_lhb_jgmmtj_em`、
  调研 `stock_jgdy_detail_em`、基金持仓季度 `stock_report_fund_hold_detail`），
  逐表跑、单表失败写 `sync_log.status='failed'` 不阻塞其余表。
- 写 `sync_log`（已有表），供 `/api/diagnostics/data-sources` 与前端降级文案使用。
- 运维：退出码 0/1/2（全成/部分/全败）；建议 cron 收盘后跑。
- **UZI 复用要点**（写进实现注记）：LHB 用 `stock_lhb_stock_detail_date_em` 枚举真实上榜日再
  逐日 `stock_lhb_stock_detail_em(date=YYYYMMDD)`（规避 akshare「近一月」快捷参数失效）；
  市场级接口务必模块级缓存 + 按股过滤（UZI 实测未缓存「3+ 分钟/股」）。

### 6.4 E3：「数据不足」原因透出

前端 `suiteUnavailableBanner` 已把 `reason` 插值进「数据源暂不可用：{reason}」，故**只需改后端
reason 串**即可见效，无前端改动：

- `AkshareAdapter` 抛 `AkshareUnavailable` 时区分「熔断窗口内 / 全链路失败 / 空结果」并带具体信息；
  provider（lhb/hsgt/holders）捕获后**把该信息拼进 reason**，而非统一「no data for this code」。
- `StockAnalysisSuite._collect_inputs` 已捕获各 `*_error`（ohlcv_error/fundamental_error…）但未外显；
  在 radar/risk 的 `_missing(...)` reason 中带上对应 `*_error`，让用户看到「网络超时」「token 缺失」
  「历史不足 N 日」等具体条件，而非「数据采集失败」。

### 6.5 E4：基本面复用 `daily_basic`

- `analysis/fundamental_data_collector.py` 当前实时爬东财，忽略已入库的 `daily_basic`(5482 码)。
- 方案：新增 `daily_basic_repo` 读取路径，作为 PE/PB/市值等指标的**首选来源**，爬虫降为 fallback。
  直接抬升 radar「业绩/估值」维度命中率，减少该维度「数据不足」。

### 6.6 E5：资金流复用已入库表

- `CapitalFlowAnalyzer`（`analysis/advanced_analysis.py:842+`）优先 tushare→东财→synthetic，
  忽略已入库 `moneyflow_dc`(3674) / `market_flow_daily`(177k)。
- 方案：在 tushare 之前/并列加「读 `moneyflow_repo`」分支，命中即用，缺时再走现有链路。

### 6.7 E6：阈值放宽 + 短历史降级

- `stock_analysis_suite._load_ohlcv` 要求 `≥60` 行，否则 FileNotFoundError 级联多面板「数据不足」；
  `panel/features.py` 技术指标要求 `≥35`。
- 方案：把硬门槛改为**分级降级**——`<35` 才整体 unavailable；`35–59` 计算可算指标并标注
  「历史 N 日（<60），部分指标置信度低」，而非一刀切。风控 `<60` 同理给出「需≥60 交易日」明确条件。

### 6.8 E7：UZI 式直连 HTTP fallback（情绪/新闻/行情）

- 新增轻量直连模块（参考 UZI `lib/news_providers.py` / `direct_http_provider.py`，0 key、独立 try/except
  + 5–10min 缓存）：
  - 金十 `https://www.jin10.com/flash_newest.js`、东财快讯
    `newsapi.eastmoney.com/kuaixun/...`、同花顺 `news.10jqka.com.cn/today_list/` → 新闻/快讯 fallback。
  - 行情 Tencent `qt.gtimg.cn` / Sina `hq.sinajs.cn` → `investor_sentiment` 指数/个股取数 fallback。
- 仅作为现有 `investor_sentiment` / `news_sentiment_collector` 爬取失败时的兜底，降低其「数据不足」。

### 6.9 涉及文件

- 改：`data_store/akshare_adapter.py`（新增 `fund_stock_holder` key；可选 reason 细化）
- 改：`analysis/institutional/fund_holdings_provider.py` / `cyq_provider.py` /
  `holders_provider.py`（reason 透出）/ `lhb_provider.py` / `hsgt_provider.py`（reason 透出）
- 新：`scripts/sync_institutional_data.py`
- 改：`analysis/stock_analysis_suite.py`（`*_error` 外显 + 阈值分级降级）
- 改：`analysis/fundamental_data_collector.py`（接 `daily_basic_repo`）
- 改：`analysis/advanced_analysis.py`（接 `moneyflow_repo`）
- 新：`analysis/data_sources_fallback.py`（直连 HTTP 兜底，UZI 范式）+ 接入 `investor_sentiment` /
  `news_sentiment_collector`
- 改：`analysis/panel/features.py`（技术指标阈值分级）

### 6.10 验收

- survey/fund/cyq：单股（fund/cyq）或批量回填后（survey）`data_status` 可达 `fresh/stale`。
- `python scripts/sync_institutional_data.py --codes 000001,600519` 后机构表行数 > 0。
- 基本面/资金流面板在库内有数据时不再「数据不足」。
- 每个仍 unavailable 的面板，文案给出**具体原因/条件**（网络/熔断/token/历史不足）。

---

## 7. 模块 F：Mac Intel（x86_64）打包

### 7.1 现状

- `build_universal.sh` 无架构标志，PyInstaller 后端（`build_backend.py` +
  `kronos_webui_backend.spec`）与 `tauri build` 均产出宿主原生 arm64。
- 后端以 Tauri **resource** 形式打入（`tauri.conf.json:58`），非 sidecar。

### 7.2 方案（用户选定「独立 x86_64 包」）

1. **Rust/Tauri**：`rustup target add x86_64-apple-darwin`；`build_universal.sh` 把目标三元组
   透传到 `npm run desktop:build -- --target x86_64-apple-darwin`（Tauri 自动产出
   `..._x86_64.dmg`）。新增平台参数（如 `macos-intel`）或环境变量驱动。
2. **PyInstaller 后端（真正难点）**：PyInstaller 不能跨编译。需在 **Rosetta x86_64 Python venv**
   （含 x86_64 的 torch/numpy/pandas/akshare/robyn… wheel）下跑 `build_backend.py`：
   - `build_universal.sh` `check_python` 增「选择 x86_64 解释器」分支（`arch -x86_64 <python>`）。
   - 产物落到 `tauri.conf.json:58` 指向的 resource 路径，再 `tauri build`。
   - 复用现有 `_adhoc_codesign_macos` 对 x86_64 产物重签。
3. **文档**：新增「Intel 构建环境搭建」指南（Rosetta venv + x86_64 wheel 安装步骤）。

### 7.3 风险

- 某些 wheel 可能无 x86_64 版（需逐一确认 torch/onnx 等）；若个别缺失需记录降级方案。
- 真实产出/验证依赖能跑 x86_64 venv 的环境；**本模块先交付脚本能力 + 文档**，二进制产出与
  Intel 机实测作为验收的独立步骤（可能需用户侧 Intel 机或 CI runner 配合）。

### 7.4 涉及文件 / 验收

- 改：`packaging/scripts/build_universal.sh`、`packaging/scripts/build_backend.py`
  （`--target-arch` / 解释器选择）、可能 `kronos_webui_backend.spec`。
- 新：`docs/guides/` 下 Intel 构建指南。
- 验收：脚本可触发 x86_64 构建；产物 `file` 显示 `Mach-O ... x86_64`；在 Intel/Rosetta 启动可用。

---

## 8. 测试与验收策略

| 模块 | 测试方式 |
|---|---|
| D | pytest：`编号` 含 NaN 的 upsert/provider 用例（红→绿） |
| E1/E2 | pytest：stub adapter 验 fund/cyq 抓取归一化 + 回填脚本入库计数/断点续传/退出码 |
| E3/E6 | pytest：unavailable reason 含具体原因；35–59 行降级不抛 |
| E4/E5 | pytest：命中 `daily_basic`/`moneyflow_dc` 时走库路径（monkeypatch repo） |
| A/B/C | 后端 `/api/stock-dashboard` schema 断言（pytest）+ 手动浏览器冒烟（[[webui-desktop-verification-recipe]]：import robyn_app + jinja parse + node --check 内联 JS + 截图） |
| E7 | pytest：直连 fallback 在主源失败时返回非空（stub requests） |
| F | 构建脚本 dry-run + `file` 校验 + Intel/Rosetta 手动启动 |

- 运行环境遵循 [[venv-project-interpreter]]：一律 `.venv/bin/python -m pytest ...`。
- 全量回归：`.venv/bin/python -m pytest -x --tb=short`，新失败计入 PR 描述。

---

## 9. 风险与回滚

| 风险 | 缓解 |
|---|---|
| akshare/雪球/东财反爬或接口变动 | adapter fallback 链 + 直连 HTTP 兜底 + sentiment_cache TTL + sync_log 告警 + 面板独立降级 |
| 市场级回填耗时/被限流 | 市场级接口模块级缓存 + 断点续传 + 限流（adapter 30/min）+ 分表容错 |
| 总览合并误删 workbench 仍用的 DOM/JS | 删除前确认 `#reportList`/`#batchRuns` 的 JS 仅在合并页移除调用，函数保留；workbench 不受影响 |
| 真实板块拉取失败 | 失败回退到「板块动量暂不可用」文案，不崩总览 |
| x86_64 wheel 缺失 | 逐一确认；缺失项记录并评估降级（如纯 CPU torch / 跳过该依赖） |

回滚：各模块独立提交，可单独 revert；机构 provider 真实抓取可经环境变量禁用（沿用上一 spec
`KRONOS_DISABLE_PROVIDER_*` 机制）；总览合并保留旧块于 git 历史，必要时恢复 `overview` 路由。

---

## 10. 待办与开放问题

- [ ] 模块 C 的板块「领涨股」是否本期实现？（成分股接口成本高，倾向后置）
- [ ] 雪球热榜以 `stock_hot_follow_xq` 为准是否满足预期「热榜」语义（关注热度 vs 讨论热度）？
- [ ] E2 市场级回填默认跑 `--all` 还是 `--watchlist`？全市场首跑耗时与限流需实测定档。
- [ ] 模块 F 是否需要在本仓 CI 增加 x86_64 构建任务，还是仅本地脚本 + 文档？
- [ ] E4 基本面以 `daily_basic` 为首选后，TTM 同比等爬虫专属字段如何与库内字段拼合（保留爬虫补充）？
- [ ] 合并后单页信息密度较高，是否需要折叠/分区（与现有 workbench 职责划分）？
```