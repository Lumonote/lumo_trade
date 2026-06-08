# 风险·机遇统筹作战大屏 — 完整设计 Spec

> 状态:设计已定稿(brainstorming 完成,含 5 屏可视化共创),待按「分期实现计划」逐步落地
> 日期:2026-06-08
> 语言/口径:中文界面;A 股口径;单用户单进程桌面端
> 高保真视觉标尺:`docs/superpowers/specs/2026-06-08-risk-opportunity-command-center-mockup.html`(霓虹暗调 v3)

---

## 1. 目标 / 背景

在桌面端新增一块「**风险·机遇统筹作战大屏**」——一个**强大、全面的数据可视化大屏(command-center)**,把现有各路信号**统筹**到一个视图,对每只标的同时给出**机会评级 + 风险评级**,并**撮合**成「该不该出手 / 该规避」的行动建议。

核心价值:现有系统已有机会评分(v5.6 / 评分 v20)、资金榜单、市场环境、模拟盘、情绪等,但**散落在多个页面**,且没有一个地方把"机会"与"风险"放在一起做撮合决策。本大屏即这块"作战驾驶舱"。

### 非目标(本期不做)

- 不重写/不改动现有机会评分算法(v20),只**消费**其产物。
- 不做真实下单(动作"加入买入池"复用现有模拟盘)。
- 不做全市场逐股扫描(取数 = 统筹现有信号源,见 §2 / D2)。
- 不引入新前端图表依赖(复用 Plotly + CSS/SVG,见 D-Approach)。

---

## 2. 设计决策汇总(brainstorming 已确认)

| # | 决策点 | 选定 |
|---|---|---|
| D1 | 核心形态 | **新建统筹决策页**(独立侧栏页,非增强报告/模拟盘) |
| D2 | 股票范围 | **统筹现有信号源**:最新机会报告 S/A/B/C + 资金榜单 Top-N(主力买入/龙虎)+ 自选 + 模拟盘持仓,去重合并成「待决策股池」 |
| D3 | 大屏布局 | **方案 C:信息瀑布分层**(状态条 → KPI 仪表盘条 → 双 hero[矩阵+热力] → 三榜单 → 滚动日志) |
| D4 | 视觉风格 | **霓虹作战大屏 · 暗调 v3**(午夜暗底 + 收敛霓虹,无 bloom);scoped 到 `.cc-screen` 不污染其它浅色页 |
| D4b | 颜色语义 | **分语境**:价格涨跌用 A 股惯例(涨红跌绿);风险/行动用 绿=好 / 红=坏。靠面板标题区分 |
| D5 | 风险覆盖 | **四层全覆盖**:① 市场系统性 ② 板块拥挤 ③ 个股 ④ 组合(持仓) |
| D6 | 取数方式 | **即时读 + 实时叠加 + 按需重算**:打开读现成产物秒开;盘中 30s 叠加实时报价;顶部「重新统筹」复用机会挖掘 job |
| D7 | 呈现方式 | **侧栏页 + 一键全屏**(默认侧栏内嵌,`⛶` 进沉浸全屏 `position:fixed;inset:0` 隐藏侧栏,`Esc` 退出) |
| D-App | 实现策略 | **方案 A:薄编排服务 + 独立纯计算风险引擎 + 单聚合接口** |
| D-Chart | 图表库 | **复用 Plotly 2.32**(散点矩阵/可选热力)+ **CSS/SVG**(仪表盘环/滚动条/榜单条),零新依赖 |

---

## 3. 复用清单(已核对真实代码)

| 复用对象 | 位置 | 用途 |
|---|---|---|
| `_run_opportunity_job(job_id, params)` | `webui/core.py`(`params` 支持 `stock_codes`/`source`) | 「重新统筹」按钮触发后台重算机会评分 |
| `_parse_opportunity_report(path)` | `webui/core.py:949` | 读最新报告 → 每股 `score`/`sector`/`rating`/技术·量化·关键加减分文本段 |
| `_latest_primary_opportunity_reports(limit)` | `webui/core.py` | 取最新机会报告路径 |
| `OpportunityScorer` 结构化 `result` | `analysis/opportunity_scorer.py`(`result['scores']`/`['details']` + chase/rsi/change_3d/quant buy-sell/tech/sector 等) | **个股风险层的精确因子源**(见 §8 前置) |
| `MarketEnvAnalyzer.analyze_market_environment()` | `analysis/market_env_analyzer.py:200` | 市场系统性风险(沪深300 5/20 日、涨跌家数、环境分级) |
| `capital_rankings_service` | `webui/services/capital_rankings_service.py` | 资金主线榜(主力买入 + 龙虎榜净买入)Top-N / 单日·多日聚合 |
| `paper_trading_service` | `webui/services/paper_trading_service.py` | 组合风险层:持仓、集中度、权益曲线/回撤 |
| `WatchlistService`(quotes / 自选增删) | `webui/services/watchlist_service.py` | 实时报价叠加 + 「加自选」动作 |
| `DESKTOP_PAGES` | `webui/core.py:2294` | 加 `command_center` 条目 → 自动路由 + 侧栏 |
| 桌面交互 JS | `webui/static/kronos_desktop_app.js` | 新页 `render*` 函数(改这个,不是 desktop.html 内联) |
| Plotly 加载 | `webui/templates/desktop.html:7`(CDN 2.32)+ `Plotly.newPlot/react` | 散点矩阵渲染;已有 `renderRadarSvgFallback` SVG 兜底范式 |
| 30s 自动刷新范式 | 现有盘中自动刷新逻辑 | 大屏实时叠加照此 |

### 现有缺口(需新建)

- **统筹编排**:把上述各源拉到一起、喂引擎、组装整屏 JSON —— 全新 `command_center_service`。
- **风险引擎**:四层风险打分 + 机会分 + 撮合决策 + 综合指数 —— 全新 `risk_opportunity_engine`。
- **结构化信号 sidecar**:机会报告生成时落一份每股结构化 JSON(见 §8)——对报告生成链路的小改动。
- **大屏前端 + 霓虹暗调主题** —— 全新 `render*` + `.cc-screen` CSS。

---

## 4. 架构总览

```
侧栏 [新] 风险·机遇 (command_center)   ——一键⛶全屏——
│
│  GET /api/command-center/overview ──► command_center_service (编排)
│        │  读最新机会报告(_parse + signals sidecar)
│        │  读资金榜单(capital_rankings_service)
│        │  读市场环境(MarketEnvAnalyzer)
│        │  读持仓(paper_trading_service)
│        │  叠加实时报价(WatchlistService.quotes)
│        ▼
│   risk_opportunity_engine (纯计算·无 I/O)
│        ① 市场系统性  ② 板块拥挤  ③ 个股  ④ 组合
│        + 机会分(复用 v20)+ 撮合决策(9 象限)+ 三综合指数
│        ▼
│   整屏 JSON ──► 前端 render*(KPI环/散点矩阵/热力/三榜/ticker)
│
└─ POST /api/command-center/recompute ──► 复用 _run_opportunity_job(后台)
```

**分层原则**:`risk_opportunity_engine` **无 I/O 纯函数**(输入信号 dict,输出评级 → 好测);`command_center_service` 负责脏活(取数/降级/缓存/实时叠加)。

---

## 5. 新建 / 改动模块清单

| 模块 | 类型 | 职责 |
|---|---|---|
| `analysis/risk_opportunity_engine.py` | 新增·纯计算 | 四层风险打分、机会分透传、撮合象限映射、三综合指数;阈值/权重为可调参数(模块级常量) |
| `webui/services/command_center_service.py` | 新增·编排 | 拉取各源 → 组装股池 → 调引擎 → 整屏 JSON;`quotes_only` 增量;轻量缓存;逐源降级 |
| `analysis/opportunity_scorer.py` 或报告生成链 | 改 | 生成报告时**额外落结构化 signals sidecar**(见 §8) |
| `webui/core.py` | 改 | `DESKTOP_PAGES` 加 `command_center`;注册新 API;复用 `_run_opportunity_job` |
| `webui/robyn_app.py` | 改 | 挂 `/api/command-center/*` 路由 |
| `webui/static/kronos_desktop_app.js` | 改 | 新页 `renderCommandCenter*`、全屏切换、30s 实时刷新、每标的动作 |
| `webui/static/kronos_desktop.css` | 改 | `.cc-screen` 霓虹暗调主题(v3 调色) |
| `tests/test_risk_opportunity_engine.py` | 新增 | 引擎评级/撮合/降级/参数 单测(TDD 先行) |
| `tests/test_command_center_service.py` | 新增 | 编排/单源缺失降级/quotes_only/缓存 单测 |

---

## 6. 数据流(三态)

1. **打开秒开** — `GET /api/command-center/overview`:service 读各路**现成产物**(最新报告 + sidecar、DB 资金榜单、市场环境快照、持仓),引擎算评级,返回整屏 JSON。
2. **盘中实时叠加** — 前端每 30s 调 `GET …/overview?quotes_only=1`:只刷实时价/涨跌幅及受其影响的 KPI 药丸与矩阵点位漂移,**不重算重活**;收盘后停。
3. **按需重算** — 顶部「重新统筹」→ `POST …/recompute` → 复用 `_run_opportunity_job`(后台 job),前端轮询 job 完成 → 重新拉 overview 读到新报告/新 sidecar。

---

## 7. 风险引擎(四层 + 综合指数 + 撮合决策)

**机会分**:直接复用 v20 评分(0–100)+ S/A/B/C 分层(S≥85 / A≥78 / B≥70 / C<70),**不重算**。

**四层风险**(各 0–100,越高越危;因子全部复用评分引擎已算信号):

| 层 | 取自 | 主要因子(memory 已验证负向) |
|---|---|---|
| ① 个股风险 | sidecar 每股结构化信号 | 追高 `chase`、RSI 过热(≥70 升 / **≥80 重罚**)、3 日涨幅 `change_3d`、**sell≥2**、连板高位、**量化过度共识 quant≥90**、ST/停牌/流动性硬闸(命中即风险封顶高) |
| ② 板块拥挤 | `result.scores.sector` / sector 详情 | **板块死区 65–75**、热门追高、换手过高;个股继承所属板块拥挤度 |
| ③ 市场系统性 | `MarketEnvAnalyzer` | 沪深300 近 5/20 日回撤、涨跌家数 breadth、情绪过热/冰点 →全市场一个 backdrop 值 |
| ④ 组合风险 | `paper_*` 持仓 | 集中度(单票/前 N 权重)、最大回撤(`paper_equity_curve`)、仓位暴露、持仓个股风险加权 |

- **每股综合风险** = ① 为主 + ② 叠加 + ③ 大盘 backdrop;④ 为**账户级**(单独面板 + 给持仓股打 ⚠️ 标)。
- **缺字段降级**:个股缺子信号 → 该股风险标「未知」而非强行 0。

**三个综合指数(顶部仪表盘环,0–100)**:
- **市场风险指数** = ③ + breadth + 情绪。
- **机会指数** = 池内 S/A 数量与分聚合。
- **市场情绪指数** = `investor_sentiment` / 市场环境。
- 另配原始 KPI 药丸:主力净流入 / 北向 / 涨跌家数 / 涨停跌停 / 成交额。

**撮合决策(9 象限,阈值=可调参数)**:
- 机会带:高 ≥70 / 中 55–70 / 低 <55
- 风险带:低 <40 / 中 40–60 / 高 ≥60

| | 风险低 <40 | 风险中 40–60 | 风险高 ≥60 |
|---|---|---|---|
| **机会高 ≥70** | 🟢 重点出手 | 🟡 可做·控仓 | 🟠 谨慎·轻仓 |
| **机会中 55–70** | 🔵 关注 | 🔵 观望 | 🔴 暂避 |
| **机会低 <55** | ⚪ 无感 | 🔴 回避 | 🔴 坚决回避 |

- **持仓叠加层**:持仓且风险转高 → ⚠️ **减仓/止盈**;持仓且仍高机会低风险 → ✅ **持有**。
- **每股最终输出**:机会分、风险分、所在象限 + **行动标签** + 一行**理由**(主导风险因子 + 主导机会因子,如「机会高(S级)但 RSI 81 过热 → 谨慎轻仓」)。

---

## 8. 关键前置:结构化信号 sidecar

**问题**:`_parse_opportunity_report` 只暴露 `score` + 文本段(技术/量化/关键加减分),**无干净数值子信号**;而个股风险层需要 chase/rsi/change_3d/sell/quant_score/sector_score 等数值。

**方案**:评分引擎**内部**已有完整结构化 `result`(`result['scores']` + `result['details']` + 上述变量)。在报告生成时(`OpportunityDiscovery.run` / `report_generator_v5` 写 markdown 的同一处)**额外落一份 sidecar**:

```
results/opportunity_top10_<date>.signals.json
[
  { "code":"603986","name":"兆易创新","total_score":88,"rating":"S",
    "scores":{"technical":..,"quantitative":..,"sector":..},
    "risk_signals":{"chase":32,"rsi":58,"change_3d":6.2,"sell_signals":0,
                    "quant_score":62,"limit_up_streak":0,"is_st":false,"halt":false} },
  ...
]
```

- `command_center_service` 优先读 sidecar(与 markdown 同 `<date>` 配对)驱动精确个股风险。
- **降级**:sidecar 缺失(旧报告)→ 退化用 `_parse_opportunity_report` 的 `score` + 文本段做粗估风险,并在面板标注「精度降级:无结构化信号」。

> 该 sidecar 是 §7 个股风险层落地的**主要前置**,放在分期实现 Phase 1。

---

## 9. 大屏分区详述(Layout C · 霓虹暗调,全部 scoped 到 `.cc-screen`)

> 视觉以 `…-mockup.html`(v3)为施工标尺。

1. **状态条**:标题「风险·机遇统筹作战大屏」· 交易日 / 报告时间 / 实时时钟 / 池数量 · `[↻ 重新统筹]` · `[⛶ 全屏大屏]`。
2. **KPI 仪表盘条**:3 个综合指数环(市场风险 / 机会 / 情绪,**CSS conic-gradient** 画,免 Plotly)+ 原始药丸(主力净流入 / 北向 / 涨跌家数 / 涨停跌停 / 成交额)。
3. **双 hero**:
   - 左(宽)**风险–机遇撮合散点矩阵**(Plotly scatter):x=机会分、y=风险(上=低风险)、点大小=主力净流入、色=行动象限、象限背景着色;hover 出理由;**点某点→该股动作菜单**。
   - 右(窄)**行业热力 treemap**:板块按涨跌着色(A 股涨红跌绿)+ 拥挤死区描红框;**点板块→矩阵过滤到该板块**。
4. **三榜单**(每行带动作钮 `析 / 自 / 池`):
   - **资金主线榜**(`capital_rankings_service`,龙虎净买入/多日聚合)
   - **机会 Top 榜**(机会分 / 风险分**双标** + S/A/B 徽章 + 象限)
   - **持仓 · 自选风险榜**(集中度 / 浮盈 / 回撤 + ⚠️减仓 / 持有 标)
5. **底部滚动条**:异动 / 事件 / 当日复盘 横向 ticker(CSS 动画)。

**每标的动作**(全复用):`个股深度分析`(跳 stock suite)· `加自选`(WatchlistService)· `加入买入池`(paper_trading 下单框)· `矩阵高亮`。
**全屏**:`.cc-screen` 全屏时 `position:fixed; inset:0` 铺满 + 隐藏侧栏;`Esc` / 按钮退出(CSS 铺满窗口,不强依赖系统全屏 API)。
**实时刷新**:盘中每 30s `?quotes_only=1`,收盘停。

---

## 10. API 端点

- `GET  /api/command-center/overview?quotes_only=0|1` → 整屏 JSON(或仅报价增量)
- `POST /api/command-center/recompute` → 复用 `_run_opportunity_job`,返回 `job_id`;前端轮询完成后刷 overview

**overview JSON 顶层结构(拟定)**:
```
{ "as_of": {...时间/池数量/精度降级标记},
  "indices": { "market_risk":62, "opportunity":71, "sentiment":55, ...原始药丸 },
  "market_env": {...沪深300/涨跌家数/环境分级},
  "matrix": [ {code,name,opp,risk,quadrant,action,reason,net_inflow,held} ... ],
  "sectors": [ {name,change,crowding,is_dead_zone} ... ],
  "rankings": { "capital":[...], "opportunity":[...], "holdings_risk":[...] },
  "ticker": [ {time,text,kind} ... ] }
```

---

## 11. 视觉规范(霓虹暗调 v3)

- 作用域:全部样式 scoped 到 `.cc-screen`,**不污染**其它浅色页。
- 调色(v3,见 mockup `:root`):底 `#04060e`;面板 `rgba(11,20,38,.95)`;线 `#143052`;青 `#25c2b4`、绿(好)`#25b88a`、琥珀(风险)`#cf922a`、红(坏/涨)`#cc5878`、蓝 `#4a82cf`;文字 `#aebfda` / 标题 `#d6e2f3`。
- 无 bloom:散点光晕 ≤6px,仪表盘环只 inset 阴影不外发光。
- 颜色语义分语境(D4b):价格涨红跌绿;风险/行动绿好红坏。

---

## 12. 降级策略(逐面板独立,不拖垮整屏)

| 缺失 | 表现 |
|---|---|
| 无最新机会报告 | 矩阵/机会榜「暂无机会数据,请先跑机会挖掘」;其它面板照常 |
| sidecar 缺失 | 个股风险走粗估 + 标注「精度降级」 |
| 资金榜单未回填 | 资金主线榜「数据待回填」 |
| 市场环境取数失败 | 市场风险指数 + 系统性层标「不可用」,个股风险去掉 backdrop 项 |
| 无模拟盘持仓 | 组合风险面板「空仓」;持仓风险榜空 |
| 实时报价失败 | 用报告/收盘价,挂「实时不可用」徽章 |

---

## 13. 测试(TDD)

- `tests/test_risk_opportunity_engine.py`:四层评分边界、9 象限撮合映射、持仓叠加(减仓/持有)、阈值参数生效、缺字段降级(风险=未知)。
- `tests/test_command_center_service.py`:全源编排、单源缺失逐项降级、`quotes_only` 增量只动报价、sidecar 命中/缺失两路、缓存。
- 前端:手测 + verifier 跑通 `overview` / `recompute` / 全屏 / 30s 刷新。

---

## 14. 分期实现计划

> 每期通过验证(verifier / 手测)才进下一期。

1. **结构化信号 sidecar + 风险引擎**:报告生成落 `*.signals.json`;`risk_opportunity_engine`(四层 + 机会 + 撮合 + 指数)+ 单测(TDD)。
2. **编排服务 + 聚合接口**:`command_center_service` + `GET /overview` + `POST /recompute` + 逐源降级 + 单测。
3. **大屏前端骨架**:`DESKTOP_PAGES` 注册 + `render*`(状态条 / KPI 环 / 三榜 / ticker)+ `.cc-screen` 霓虹暗调主题(对齐 v3 mockup)。
4. **双 hero 可视化**:Plotly 散点撮合矩阵(象限/点大小/hover 理由/点击动作)+ 行业热力 treemap(点击过滤)。
5. **交互闭环**:每标的动作(析/自/池)+ 实时 30s 叠加 + 一键全屏 + 重新统筹轮询刷新。

---

## 15. 验收标准(关键)

- 打开秒开,整屏五区(状态/KPI/双hero/三榜/ticker)按 v3 视觉呈现,霓虹暗调不刺眼且不污染其它页。
- 每只标的同时有机会分 + 风险分 + 行动标签 + 理由,且**落点与 9 象限撮合表一致**。
- 四层风险均生效:个股(基于 sidecar)、板块拥挤、市场系统性 backdrop、组合(持仓集中度/回撤);各源缺失独立降级不崩屏。
- 盘中 30s 实时叠加只动报价相关;「重新统筹」跑完后整屏读到新评分。
- 一键全屏铺满窗口 / 隐藏侧栏 / `Esc` 退出;每标的「析/自/池」动作正确跳转或下单。
- 与命令行机会挖掘**同算法同分**(大屏不二次改分,只消费 + 叠加风险)。
