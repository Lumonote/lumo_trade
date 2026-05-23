# 个股深度分析弹窗（Stock Analysis Suite）设计文档

- **创建日期**：2026-05-23
- **作者**：OpenClawd（通过 brainstorming 与用户对齐）
- **状态**：待用户复核
- **下一步**：通过后调用 `superpowers:writing-plans` 生成实施计划

## 1. 背景与目标

当前点击个股弹出的 `#stockContextModal` 只有 6 个面板（机会、分析结果、本地报告、操作、交易软件、雪球），信息密度远低于参考设计：截图中弹窗以 10 个 Tab（综合总览、市场周期、主力阶段、量价博弈、筹码结构、业绩预期、概率推演、操盘风控、涨停筛选、AI 解读）呈现量化级深度分析。

**本次目标**：在不影响现有「投资机会挖掘」和「批量分析」流水线的前提下，把点击个股弹窗升级为带 Tab 的深度分析工作台，首版交付 **3 个核心 Tab**（综合总览、操盘风控、AI 解读），其余 7 个 Tab 留占位接口。

**核心新指标**（用户明确要求）：支撑位、主力控盘度、散户数据、主力买卖数据、量化数据 —— 这些指标的底层计算在 `analysis/advanced_analysis.py`、`analysis/technical_analysis.py`、`analysis/market_env_analyzer.py` 中已存在，本次只做编排和展示。

## 2. 范围与边界

### 2.1 严格不修改的现有文件（保护机会挖掘 / 批量分析）

- `scripts/run_opportunity_discovery.py`
- `scripts/opportunity_report_generator.py`
- `scripts/run_integrated_discovery.py`
- `analysis/technical_analysis.py`
- `analysis/advanced_analysis.py`
- `analysis/market_env_analyzer.py`
- `analysis/fundamental_data_collector.py`
- `analysis/investor_sentiment.py`
- `analysis/llm_service.py`
- `analysis/opportunity_scorer_v4_1_integration.py`

新代码以 `import` 方式调用这些模块的现有函数，**不修改任何签名、不内联拷贝逻辑**。

### 2.2 新增文件

```
analysis/stock_analysis_suite.py        # 编排器，单一入口
   ├─ class StockAnalysisSuite
   ├─ compute_overview(code)            # 综合总览 Tab 数据
   ├─ compute_risk_control(code)        # 操盘风控 Tab 数据
   ├─ compute_radar_scores(code)        # 5 维 0-100 评分
   ├─ collect_cached_reports(code)      # 读 reports/ 下既有产物
   └─ build_llm_payload(code)           # 给 AI 解读拼 prompt 上下文

webui/services/stock_suite_service.py   # Flask service 层
   ├─ get_suite(code, name)             # 调编排器，返回结构化 JSON
   └─ trigger_ai_interpretation(code)   # 异步包 LLMAnalyzer

webui/templates/components/
   └─ stock_suite_tabs.html             # Tab UI 片段（Jinja include）

tests/test_stock_analysis_suite.py      # 单元/集成测试
```

### 2.3 最小侵入式改动的现有文件

> **Web 框架现状**：项目正在执行 Flask → Robyn 迁移。30 条 HTTP 路由已全部注册成原生 Robyn handler（`webui/robyn_app.py`），Flask 路由（`webui/app.py`）作为兼容兜底保留。新路由必须**在两侧同时注册**，与现有 `stock-context` 等路由保持一致：
> - Flask 端：`@app.route('/api/stock-analysis-suite/<stock_code>')`
> - Robyn 端：`@_native_get("/api/stock-analysis-suite/:stock_code")`
>
> 业务逻辑放在 `webui/services/stock_suite_service.py`，被两侧 handler 共享调用（与 `model_runtime` 现有模式一致），避免双框架逻辑分叉。

- `webui/app.py`：新增 2 个 Flask 路由 `/api/stock-analysis-suite/<code>` (GET) 和 `/api/stock-analysis-suite/<code>/ai` (POST)，不改已有路由
- `webui/robyn_app.py`：新增对应 2 个原生 Robyn handler（`@_native_get` / `@_native_post`），逻辑全部委托给 `stock_suite_service`
- `webui/templates/desktop.html`：在 `#stockContextModal` → `#stockContextBody` 上方插一段 Tab 栏；现有 6 个面板原封不动塞进「快速信息」Tab
- `webui/static/kronos_desktop.css`：追加 Tab 样式，不改已有规则
- `webui/services/__init__.py`：如不存在则创建（仅一行空 import）

### 2.4 不在本次范围

- 7 个占位 Tab 的内容实现（市场周期、主力阶段、量价博弈、筹码结构、业绩预期、概率推演、涨停筛选）只放骨架与「即将上线」提示
- 离线/批量场景不变更
- 已有的桌面 K 线 modal 不动

## 3. 架构与数据流

```
点击个股
   ↓
desktop.html: openStockContext(target)
   ↓
GET /api/stock-analysis-suite/{code}?name={name}
   ↓
webui/services/stock_suite_service.get_suite()
   ↓
analysis/stock_analysis_suite.StockAnalysisSuite
   ├─ compute_radar_scores  → 5 维评分
   ├─ compute_overview      → 关键信号 + 深度信号 + 情景概率
   ├─ compute_risk_control  → 止损/分批/止盈/隐性风险
   └─ collect_cached_reports → 读 reports/
   ↓
JSON 响应（不含 AI 解读正文）
   ↓
前端渲染 4 个 Tab（快速信息/综合总览/操盘风控/AI 解读骨架）+ 7 个占位 Tab
   ↓
用户点击 AI Tab 的「生成深度解读」按钮
   ↓
POST /api/stock-analysis-suite/{code}/ai
   ↓
service.trigger_ai_interpretation
   ↓
analysis/llm_service.LLMAnalyzer (现有，不改)
   ↓
返回 markdown 报告并缓存
```

**缓存策略**：单股完整 suite 数据缓存 5 分钟（`analysis/stock_analysis_suite.py` 内存 LRU，key=stock_code）。LLM 解读结果单独持久化到 `reports/stock_suite/{code}_{timestamp}.md`。

## 4. 5 维雷达评分公式（综合总览核心）

每个维度 0–100，全部基于现有模块。任一维度数据缺失返回 `null`，前端对应顶点显示「--」，不影响其他维度。

### ① 主力阶段
- 源：`AdvancedAnalyzer.ChipAnalyzer._estimate_main_force_control` + `CapitalFlowAnalyzer`
- 公式：`0.5 × control_degree + 0.3 × main_force_continuity_score + 0.2 × retail_inflow_normalized`
  - `control_degree`：0-100 直接使用
  - `main_force_continuity_score`：近 5 日主力净流入为正的天数 × 20
  - `retail_inflow_normalized`：`max(0, -retail_net / |main_net|) × 100`，封顶 100

### ② 市场周期
- 源：`MarketEnvAnalyzer.assess()`
- 公式：`base_by_regime + 30 × capital_flow_ratio`
  - 牛市 base=50、震荡 base=35、熊市 base=15

### ③ 量价博弈
- 源：`TechnicalAnalysis` 30 个量化模型
- 公式：`(买入信号数 / 30) × 100`，取最近 N=5 日聚合

### ④ 筹码结构
- 源：`AdvancedAnalyzer.ChipAnalyzer`
- 公式：`clip(100 - concentration × 2, 0, 100) × 0.5 + (100 - |profit_ratio - 50|) × 0.5`

### ⑤ 业绩预期
- 源：`FundamentalDataCollector`
- 公式：`PE_score × 0.35 + ROE_score × 0.35 + GrowthRate_score × 0.30`
  - PE_score：行业百分位反向
  - ROE_score：≥15%→100，≤5%→0，线性
  - GrowthRate_score：YoY 利润 [0%, 50%] 线性映射 [50, 100]，负增长扣分

每个维度同时返回 `label`（中文档位）和 `reason`（一句话说明），用于前端 tooltip。

## 5. API 契约

### 5.1 `GET /api/stock-analysis-suite/<code>?name=<name>`

```jsonc
{
  "success": true,
  "stock": { "code": "000001", "name": "平安银行", "sector": "银行", "market": "XSHE" },
  "generated_at": "2026-05-23T14:30:12+08:00",
  "cache": { "hit": true, "expires_at": "2026-05-23T14:35:12+08:00" },

  "overview": {
    "radar": {
      "main_force_phase":  { "score": 62, "label": "中等偏强", "reason": "主力近5日4日净流入" },
      "market_cycle":      { "score": 35, "label": "震荡期",   "reason": "大盘资金流入比 0.42" },
      "volume_price_game": { "score": 53, "label": "多空胶着", "reason": "30 模型中 16 个买入信号" },
      "chip_structure":    { "score": 28, "label": "结构偏差", "reason": "90% 成本集中度 15.9%" },
      "performance":       { "score": 71, "label": "估值修复", "reason": "PE 4.8 行业前 10%，ROE 14.2%" }
    },
    "key_signals": [
      { "label": "大盘周期", "value": "震荡期", "tone": "warn" },
      { "label": "仓位上限", "value": "30%",   "tone": "warn" },
      { "label": "主力阶段", "value": "洗盘期 → 拉升期", "tone": "info" },
      { "label": "可信度",   "value": "中",    "tone": "neutral" },
      { "label": "量能质量", "value": "量价正常", "tone": "info" },
      { "label": "筹码集中度", "value": "中等",  "tone": "neutral" }
    ],
    "deep_signals": [
      { "text": "...", "tone": "danger|warn|info|success", "tag": "形态|价位|量能|资金|基本面" }
    ],
    "scenario_probability": {
      "bullish": 34, "bearish": 32, "sideways": 34,
      "source": "30 量化模型多空票数归一化"
    }
  },

  "risk_control": {
    "execution_plan": {
      "stop_loss":   { "price": 10.43, "drop_pct": 2.3, "basis": "ATR(20)×1.5 下沿" },
      "risk_reward": { "ratio": "1:3.7", "expected_return_pct": 8.5 }
    },
    "scaled_entry": [
      { "label": "现价建仓",   "price": 10.68, "position_pct": 10 },
      { "label": "浅回调加仓", "price": 10.62, "position_pct": 20 },
      { "label": "中度回调加仓","price": 10.58, "position_pct": 30 },
      { "label": "深度回调加仓","price": 10.55, "position_pct": 25 },
      { "label": "极限加仓",   "price": 10.53, "position_pct": 15 }
    ],
    "tiered_take_profit": [
      { "label": "第一止盈(前高)", "price": 11.60, "sell_pct": 30 },
      { "label": "第二止盈(+15%)", "price": 11.74, "sell_pct": 30 },
      { "label": "第三止盈(+30%)", "price": 11.88, "sell_pct": 25 },
      { "label": "终极止盈(+50%)", "price": 12.06, "sell_pct": 15 }
    ],
    "deep_signals": [
      { "text": "最大回撤：60日 -19.2% / 120日 -19.2% / 当前 -17.5%", "tone": "warn" },
      { "text": "波动率锥(年化)：20日 16.0% / 60日 16.8% / 120日 14.3%", "tone": "info" },
      { "text": "夏普比率(60日年化)：-0.45", "tone": "danger" }
    ],
    "hidden_risks": [
      { "text": "近期有限售股解禁——解禁前10日注意减持压力", "severity": "warn" }
    ]
  },

  "ai_interpretation": {
    "status": "not_generated",
    "report": null,
    "token_usage": null,
    "generated_at": null,
    "trigger_endpoint": "/api/stock-analysis-suite/000001/ai"
  },

  "cached_reports": {
    "opportunity":    { "found": true,  "path": "...", "updated_at": "..." },
    "batch_analysis": { "found": false, "path": null,  "updated_at": null }
  },

  "stub_tabs": [
    "market_cycle", "main_force_phase", "volume_price_game",
    "chip_structure", "performance", "probability", "limit_up_screening"
  ],

  "warnings": []
}
```

**降级**：任何子模块抛异常 → 对应字段为 `null` 且 `warnings[]` 追加一条说明，整体请求仍返回 200。

### 5.2 `POST /api/stock-analysis-suite/<code>/ai`

请求体（可选）：`{ "force_refresh": false }`

响应：

```jsonc
{
  "success": true,
  "status": "ready",
  "report": "## 1. 核心定性\n...\n## 2. 价值与安全边际\n...",
  "token_usage": 3651,
  "generated_at": "2026-05-23T14:32:05+08:00",
  "cached_path": "reports/stock_suite/000001_20260523_143205.md"
}
```

失败：`{ "success": false, "status": "failed", "error": "DeepSeek API 超时" }`

**触发**：同步调用 `analysis/llm_service.LLMAnalyzer`（现有模块），单次调用阻塞 5–30s。前端按钮点击后立刻置为 disabled 并显示骨架进度条；返回后渲染 markdown。

**AI 解读 prompt 结构**（在 `stock_analysis_suite.build_llm_payload` 中拼装）：
1. 核心定性
2. 价值与安全边际
3. 主力博弈解析
4. 多因子量化评估
5. 情绪周期与市场定位
6. 预期差挖掘
7. 操盘建议

输入上下文包含 5 维评分、关键信号、深度信号、风控数据、基本面摘要。

## 6. 前端 UI 规范

### 6.1 Tab 栏插入位置

`#stockContextModal` 的 `.modal-body` 内最上方插入：

```html
<nav class="stock-suite-tabs" role="tablist">
  <button data-tab="quick"         class="active">快速信息</button>
  <button data-tab="overview">综合总览</button>
  <button data-tab="market_cycle"     disabled>市场周期</button>
  <button data-tab="main_force_phase" disabled>主力阶段</button>
  <button data-tab="volume_price_game" disabled>量价博弈</button>
  <button data-tab="chip_structure"   disabled>筹码结构</button>
  <button data-tab="performance"      disabled>业绩预期</button>
  <button data-tab="probability"      disabled>概率推演</button>
  <button data-tab="risk_control">操盘风控</button>
  <button data-tab="limit_up_screening" disabled>涨停筛选</button>
  <button data-tab="ai_interpretation">AI 解读</button>
</nav>
<div class="stock-suite-panels">
  <!-- 各 Tab 对应面板，display:none 切换 -->
</div>
```

- 占位 Tab 鼠标悬停 tooltip：「即将上线 · 与 X 模块联调中」
- 「快速信息」Tab 内容 = 现有 6 个面板的当前布局，无任何回归

### 6.2 综合总览 Tab 布局

```
┌──────────────────────────────────────────────────────┬───────────────┐
│  多维度得分雷达 (5维)                                │ 关键信号 卡片 │
│  Plotly polar chart                                   │  6 行         │
│                                                       ├───────────────┤
│                                                       │ 情景概率推演 │
│                                                       │ 环形图       │
├──────────────────────────────────────────────────────┴───────────────┤
│  深度信号列表（按 tone 色彩 + tag 分组）                              │
└──────────────────────────────────────────────────────────────────────┘
```

- 雷达图：Plotly `scatterpolar`，5 顶点对应 5 维度，深色背景配 `#5b8def` 折线和半透明填充
- 关键信号：6 张窄卡片，`tone` → 颜色：`warn=橙、danger=红、info=蓝、success=绿、neutral=灰`
- 情景概率：Plotly donut，3 段（看涨/看跌/震荡）
- 深度信号：列表项 `[tag][tone-dot] text`，按 tag 折叠分组

### 6.3 操盘风控 Tab 布局

```
┌──────────────────────────┬──────────────────────────┬──────────────┐
│ 操盘执行方案             │ 深度信号                 │ 隐性风险预警 │
│  止损位 / 盈亏比         │  最大回撤/波动率锥/夏普   │  解禁/减持等 │
├──────────────────────────┤  /涨跌不对称              │              │
│ 分批建仓 (5 档)           │                          │              │
├──────────────────────────┤                          │              │
│ 分层止盈 (4 档)           │                          │              │
└──────────────────────────┴──────────────────────────┴──────────────┘
```

- 价格用大字号显示，伴随 `(2.3%)` 等次要信息
- 仓位百分比和价格用等宽字体对齐

### 6.4 AI 解读 Tab

未生成态：

```
[图标] AI 操盘手深度解读
       基于多因子模型 + DeepSeek 推理引擎
       约 3-5k tokens / 单次 5-30 秒
       [ 生成深度解读 ] 按钮
```

生成中：替换按钮为骨架进度条 + 「正在调用 DeepSeek 进行深度解读…」

生成完成：渲染 markdown，按编号小节展示（6-7 节），底部显示 token 使用量与生成时间。

## 7. 错误处理与降级

| 失败场景 | 行为 |
|----------|------|
| Tushare / Eastmoney 抓取超时 | 该指标返回 `null`，`warnings[]` 追加，UI 显示「--」 |
| K 线数据不足 60 日 | 风控 Tab 显示「数据不足，建议先补齐数据」 |
| LLM 未配置 / 超时 | AI Tab 按钮文案改「请先配置 DeepSeek API」/「LLM 调用失败：详情…」 |
| 缓存读取失败 | 降级为 live 计算，不影响主流程 |
| 编排器整体异常 | 端点返回 200 + `success: false` + error 文案，前端显示错误卡片，保留「快速信息」Tab 可用 |

## 8. 测试策略

`tests/test_stock_analysis_suite.py`：

- 单元测试：5 维评分函数的边界（全部缺失、单维缺失、极值）
- 集成测试：mock 现有 analyzer 输出 → `compute_overview` / `compute_risk_control` 装配正确
- API 测试：`GET /api/stock-analysis-suite/<code>` 路径覆盖（正常、不存在的股票、降级场景）
- 回归保护：跑 `tests/test_analysis_jobs.py` 等现有测试，确认机会挖掘 / 批量分析未受影响

## 9. 验收清单

- [ ] 点击任一个股，弹窗展示 11 个 Tab，3 个核心 Tab 有完整内容，7 个占位 Tab 可点击但显示「即将上线」
- [ ] 综合总览雷达图 5 维有数据；关键信号、深度信号、情景概率全部渲染
- [ ] 操盘风控的止损/分批/止盈/隐性风险按截图布局
- [ ] AI 解读点击按钮后 5-30s 内返回 markdown
- [ ] 运行 `python scripts/run_opportunity_discovery.py` 与 `批量分析` 无任何回归
- [ ] 弹窗首屏渲染（不含 AI）≤ 3s（缓存命中 ≤ 500ms）
- [ ] 单股数据降级路径（停牌 / 数据不足）有友好提示，整体 200

## 10. 未在本次范围内的后续工作

- 7 个占位 Tab 的内容实现（市场周期、主力阶段、量价博弈、筹码结构、业绩预期、概率推演、涨停筛选）
- 历史多次 AI 解读结果的对比视图
- 弹窗内可编辑止损/止盈参数并回写策略
- 多股票一键导出对比报告
