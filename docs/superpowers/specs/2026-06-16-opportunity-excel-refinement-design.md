# 投资机会挖掘 — 精细化 Excel 导出（与个股分析对齐）设计

- **日期**: 2026-06-16
- **分支**: V2.1.1
- **状态**: 已确认，待生成实现计划
- **关联记忆**: [[opportunity-canvas-excel-detail]] · [[opportunity-run-db-and-config-parity]] · [[opportunity-score-parity]] · [[stock-analysis-suite-design]]（2026-05-23）

## 1. 背景与目标

当前「投资机会画布」导出的 Excel（`webui/core.py::export_opportunity_canvas_excel`）有 8 张 sheet，每只股票的信息基本来自**机会挖掘报告的文本段**（约 12 段：概览/入选原因/涨幅/板块/量化/技术/基本面/情绪资金/消息/关键加减分/最新动态/高级/历史重复入选）+ 机会评分 10 维分项 + 风险信号 + 热门板块关联。

而「个股分析」页（`/api/stock-analysis-suite/:code` → `analysis/stock_analysis_suite.py::StockAnalysisSuite.get_full_payload`）拥有**更丰富的结构化数据**，这些是机会报告里没有的：
- `overview.radar`：5 维评分（主力阶段/市场周期/量价博弈/筹码结构/业绩预期）+ 控盘度（每项 `{score, label, reason}`）
- `overview.key_signals`：大盘周期/仓位上限/主力阶段/可信度/量能质量/筹码集中度/技术趋势
- `overview.scenario_probability`：看多/看空/震荡 %（30 量化模型多空票数归一）
- `risk_control`：止损（价/幅度/依据）、盈亏比、预期收益、分批建仓 5 档、分批止盈 4 档、回撤/年化波动率/夏普（`deep_signals` 文本）
- `quant_matrix`：30 模型逐模型信号矩阵 + 多空共振计数 + 当前态势
- `chip_control`：控盘度+标签、90%/70%/50% 集中度、cyq 分布
- `institutional_holdings`：十大流通股东、股东户数、机构调研、基金持仓
- `main_force_deep`：龙虎榜、陆股通

**目标**：让 Excel 在每只入选股票上达到与个股分析页一致的颗粒度，并**分层可读**——普通人看「投资速览 + 术语表」即可读懂机会，资深分析师可下钻「雷达/风控/量化矩阵/筹码机构」明细。

**非目标**：
- 不在挖掘 run 时持久化这些字段（不改 `opportunity_item` schema、不重跑历史报告）。
- 默认不纳入 LLM 7 段深度点评（耗时 ~100s/股、消耗 token；用户未选该项）。
- 不改动个股分析页本身与挖掘评分算法。

## 2. 取数策略：导出时按需复算

导出时报告/画布里的股票代码已知，对每只 `type=stock` 节点调用 **`STOCK_SUITE_SERVICE.get_suite(code)`**（个股分析页同款引擎，含 5 分钟 LRU 缓存）。

**为何导出时复算而非 run 时持久化**：
- 与页面**逐字一致**（同一引擎、同一缓存），杜绝 Excel 与页面分叉（参见 [[opportunity-score-parity]] 既往分叉教训）。
- 无需改库、无需重跑；**对历史老报告同样生效**。
- 5 分钟 LRU 缓存使重复导出与「刚看过个股页再导出」近乎零成本。

**报告文本仍作基线**：即使某股复算失败/超时，该股仍保留报告文本派生的列，不出现空行。

## 3. 架构（隔离 / 可测）

### 3.1 新模块 `webui/opportunity_excel.py`（纯装配 + 样式规格，不碰网络/Robyn）

```
build_opportunity_workbook(
    canvas: dict,
    latest_report: dict,
    opportunity: dict,
    suite_fetcher: Callable[[str], dict] | None,   # 注入 STOCK_SUITE_SERVICE.get_suite；测试可注入假实现
    *, suite_limit: int = 30,
    time_budget_sec: float = 150.0,
    clock: Callable[[], float] | None = None,        # 注入计时器，测试可控时间预算
) -> tuple[list[SheetSpec], dict]                    # (sheet 规格列表, 复算覆盖率元信息)
```

- `SheetSpec = {name, rows, columns, style}`；`style` 为下游写盘器消费的样式规格（见 §6）。
- 逐股 best-effort：`suite_fetcher` 抛错/超预算 → 该股 `suite=None`，落报告文本基线；累计 `coverage = {requested, succeeded, failed, skipped_over_budget}`。
- **纯函数**：不写文件、不直接 import 服务单例，便于单测（注入假 `suite_fetcher` 与假 `clock`）。

### 3.2 `webui/core.py` 编排瘦身

`export_opportunity_canvas_excel` 改为：装载机会 → 建画布 → 懒加载 `STOCK_SUITE_SERVICE.get_suite` 作为 `suite_fetcher` → 调 `build_opportunity_workbook` → 用写盘器落盘。把 Excel 行装配逻辑从 core.py 迁出到新模块（core.py 已过大），core 仅保留薄编排 + 写盘。

`suite_fetcher` 包一层防御：`get_suite` 返回 `{success: False, ...}` 或抛异常都视为该股复算失败。

### 3.3 写盘器升级（openpyxl 样式层）

在现有 `_write_excel_sheet`（pandas `.map`、空表写表头、`columns` 稳定 schema）基础上，新增 `_style_worksheet(ws, style_spec)`：
- 冻结首行表头 + 冻结「代码/名称」两列（`freeze_panes`）。
- 列宽按内容估算并设上限。
- 数字格式：百分比列 `0.0%`/`0.0"%"`（视存的是比例还是已乘100的数）、金额/价格列 `#,##0.00`。
- 分桶着色（`PatternFill`）：按列语义把单元格按阈值上色（见 §6）。

`build_opportunity_workbook` 产出 `style` 规格（声明式：哪些列是百分比/价格、哪些列按什么阈值着色、表头与冻结策略），写盘器执行之。保持装配与渲染解耦、便于测试装配结果。

## 4. 工作簿结构（顺序即阅读动线）

新增 6 张（⭐），强化 2 张，保留其余以向后兼容。写入顺序：

| # | Sheet | 受众 | 形态 |
|---|---|---|---|
| 1 | 投资速览(导读) ⭐ | 普通人 | 每股一行宽表 |
| 2 | 报告信息 | 两者 | 单行（强化：+复算覆盖率） |
| 3 | 评分雷达 ⭐ | 分析师 | 每股一行宽表 |
| 4 | 风控执行计划 ⭐ | 两者 | 整洁长表（股票×档位） |
| 5 | 量化模型矩阵 ⭐ | 分析师 | 整洁长表（股票×模型） |
| 6 | 筹码与机构 ⭐ | 分析师 | 每股一行宽表 |
| 7 | 股票排名 | 分析师 | 原有，保留 |
| 8 | 股票全量明细 | 分析师 | 原有，保留 |
| 9 | 分析内容 | — | 原有，保留 |
| 10 | 板块汇总 | — | 原有，保留 |
| 11 | 热门板块关联 | — | 原有，保留 |
| 12 | 画布节点 | — | 原有，保留 |
| 13 | 画布关系 | — | 原有，保留 |
| 14 | 术语表与图例 ⭐ | 普通人 | 静态字典 |

> 用户确认：原有 8 张 sheet 全部保留（不破坏现有 `tests/test_opportunity_report_parser.py` 断言）。

### 4.1 投资速览(导读) — 每股一行
列顺序与取数（缺失留空，不报错）：

| 列 | 取数 |
|---|---|
| 排名 | `node.score_rank or report_rank` |
| 代码 / 名称 / 所属板块 | `node.stock_code / stock_name / sector` |
| 综合评分 / 评级 | `node.score / node.rating` |
| **建议操作** | 派生规则见 §5.1（买入/观望/回避） |
| 一句话逻辑 | 报告「入选原因」首句，缺失退「概览」首句 |
| 当前态势 | `suite.quant_matrix.current_posture` |
| 主力阶段 | `suite.overview.radar.main_force_phase.label` |
| 大盘周期 | `suite.overview.key_signals[label=大盘周期].value` |
| 仓位上限 | `suite.overview.key_signals[label=仓位上限].value` |
| 现价 | `suite.risk_control.scaled_entry[0].price`（label=现价建仓）|
| 止损价 / 止损幅度% | `risk_control.execution_plan.stop_loss.price / drop_pct` |
| 第一目标价 | `risk_control.tiered_take_profit[0].price`（前高）|
| 盈亏比 | `risk_control.execution_plan.risk_reward.ratio` |
| 预期收益% | `risk_control.execution_plan.risk_reward.expected_return_pct` |
| 最大回撤% / 年化波动率% / 夏普 | 解析 `risk_control.deep_signals[].text`（见 §5.2）|
| 关键风险 | 报告「关键加减分」中的扣分项 + 高追高/高 RSI/卖出信号 文本（见 §5.3）|
| 当日 / 3日 / 5日涨幅 | `_stock_change_columns`（已存在，run-store 数值优先，退文本解析）|
| 数据完整度 | `完整 / 部分(缺X) / 仅报告基线`（按 suite 各 section data_status 汇总）|

### 4.2 评分雷达 — 每股一行
代码 / 名称 / 主力阶段(分·标签·理由) / 市场周期 / 量价博弈 / 筹码结构 / 业绩预期 / 控盘度(分·标签) / 量化活跃度 / 情景概率-看多% / 看空% / 震荡% / 可信度 / 量能质量 / 筹码集中度 / 技术趋势。
取数：`suite.overview.radar.{main_force_phase, market_cycle, volume_price_game, chip_structure, performance, control_degree, quant_activity}`、`suite.overview.scenario_probability.{bullish,bearish,sideways}`、`suite.overview.key_signals`。

### 4.3 风控执行计划 — 整洁长表（每行=股票×档位）
列：代码 / 名称 / 计划(分批建仓·分批止盈·止损) / 档位 / 价格 / 仓位%或卖出% / 说明。
- 建仓 5 行：`risk_control.scaled_entry[]`（label, price, position_pct）。
- 止盈 4 行：`risk_control.tiered_take_profit[]`（label, price, sell_pct）。
- 止损 1 行：`execution_plan.stop_loss`（price, drop_pct, basis 入说明）。
- 该股 `risk_control.available=False` → 写 1 行「数据不足」附 reason。

### 4.4 量化模型矩阵 — 整洁长表（每行=股票×模型）
列：代码 / 名称 / 模型 / 信号。信号映射 `1→买入, -1→卖出, 0→观望`。
取数：`suite.quant_matrix.signals_matrix[]`（含 model、signal）。
表尾或「评分雷达」已含每股多空观望计数（`multi_period_resonance`）；矩阵 sheet 不重复计数，保持整洁。
`quant_matrix.data_status=unavailable` → 该股写 1 行「数据不足(M4: OHLCV 不足或加载失败)」。

### 4.5 筹码与机构 — 每股一行
代码 / 名称 / 控盘度 / 控盘标签 / 90%集中度 / 70%集中度 / 龙虎榜命中 / 龙虎榜最近日期 / 龙虎榜净额 / 龙虎榜原因 / 陆股通持股 / 陆股通占比 / 十大流通股东合计占比 / 股东户数。
取数：`suite.chip_control.{control_degree,control_label,concentration_90,concentration_70}`、`suite.main_force_deep.{dragon_tiger,hsgt}`、`suite.institutional_holdings.{top10_floatholders,holder_number}`。
机构数据离线/限流时多为 `数据不足`（与页面同步，符合预期，参见 [[stock-suite-empty-panels]]）。

### 4.6 报告信息（强化）
原有字段 + `复算成功数 / 复算失败数 / 超预算跳过数 / 复算覆盖率`、`规则版本 ruleset_version`、`配置哈希 config_hash`（若 `latest_report` 含 run-meta）。

### 4.7 术语表与图例（静态）
列：指标 / 白话含义 / 怎么读（好坏方向）/ 数据来源。覆盖：综合评分、评级(S/A/B/C 阈值)、建议操作(派生规则)、雷达 5 维各项、控盘度、情景概率、当前态势、RSI、追高风险、卖出信号、量化总分、盈亏比、预期收益、最大回撤、年化波动率、夏普比率、仓位上限、龙虎榜、陆股通、集中度(90/70%)、降级标记、「数据不足」含义、颜色图例（§6）。

## 5. 派生规则（透明、写入术语表）

### 5.1 建议操作（买入/观望/回避）
按可得数据降级判定，规则全文进术语表：
1. 评级 C 或 `node.degraded` 或综合评分 < 60 → **回避**。
2. 否则若 `scenario_probability.bearish > bullish` 或 当前态势 ∈ {强势空头, 震荡偏空} 或 追高风险 ≥ 80 或 卖出信号 ≥ 3 → **观望**。
3. 否则若 评级 ∈ {S, A+, A} 且 当前态势 ∈ {强势多头, 震荡偏多} 且 看多% ≥ 看空% → **买入**。
4. 其余 → **观望**。
> suite 缺失时仅用评级 + 涨幅信号判定（≥A 且非高追高→买入，C/降级→回避，余观望）。

### 5.2 风险指标解析（来自 `risk_control.deep_signals[].text`）
正则提取数值：`最大回撤：当前 X%`、`波动率(60日年化) X%`、`夏普比率(60日年化) X`。解析失败留空，不抛错（沿用 `_parse_change_breakdown` 风格）。

### 5.3 关键风险
拼接：报告「关键加减分」里的扣分句（含「罚/扣/风险/回调/过热」等）+ 信号阈值告警（追高风险≥60、RSI≥80、卖出信号≥2、5日涨幅≥20%、最大回撤≤-15%）。去重、最多 5 条、顿号连接。

## 6. 颜色与格式（CN 习惯，全在图例说明）

- **涨跌幅**：红涨绿跌（正→红、负→绿；A 股习惯）。适用「当日/3日/5日涨幅」。
- **评分/评级**：强→弱用蓝(强)→灰(弱)分桶（评分 ≥85 深蓝/≥78 蓝/≥70 浅蓝/<70 灰），避免与红涨语义冲突。
- **风险类（追高风险/卖出信号/最大回撤）**：越危险越橙红（追高≥80 红/≥60 橙；卖出≥3 红/≥2 橙；回撤≤-20% 红/≤-15% 橙）。
- **建议操作**：买入=红底、观望=黄底、回避=灰底。
- 表头：加粗 + 浅灰底；冻结首行 + 代码/名称两列；百分比/价格数字格式；列宽自适应（上限 ~40 字符）。
- 颜色与阈值在「术语表与图例」用文字 + 色块说明。

## 7. 降级 / 性能 / 配置

- **逐股 best-effort**：单股复算 try/except，失败回退报告文本基线，其余照常；任何字段缺失显示「数据不足」，**绝不让整个导出崩溃**。
- **上限**：`suite_limit` 默认 30，可由环境变量 `KRONOS_OPP_EXCEL_SUITE_LIMIT` 覆盖；只对 `type=stock` 节点深挖。超过上限的股票回退基线。
- **时间预算**：`time_budget_sec` 默认 150（前端 fetch 超时 180s）。每股复算前检查已耗时，超预算则剩余股票回退基线并计入 `skipped_over_budget`。
- **覆盖率**写入「报告信息」，让用户知道哪些是完整复算、哪些仅基线。
- pandas 3.0：继续用 `.map`（已 pin `pandas>=2.2.3`）；空表写表头；`columns` 稳定 schema。

## 8. 测试（扩展 `tests/test_opportunity_report_parser.py`）

注入假 `suite_fetcher` + 假 `clock`，构造 3 类股票：
1. **完整复算股**：返回完整 suite 假数据 → 断言投资速览/评分雷达/风控/量化矩阵/筹码机构 列与值正确；建议操作派生正确；风险指标解析正确。
2. **复算抛错股**：`suite_fetcher` 抛异常 → 断言不崩、该股落报告文本基线、`coverage.failed` +1、风控/量化矩阵写「数据不足」行。
3. **超预算股**：假 `clock` 使其超 `time_budget_sec` → 断言回退基线、`coverage.skipped_over_budget` +1。

另：
- 原有 8 张 sheet 与既有断言保持通过（向后兼容）。
- 6 张新 sheet 一定存在（空数据也写表头）。
- 术语表非空且含「建议操作」「夏普比率」等关键词。
- 样式规格断言：涨幅列标记为红涨绿跌、评分列标记分桶、冻结 panes 存在。
- `suite_limit=0` 时全部走基线（纯重构路径仍可用）。

## 9. 风险与已知约束

- **dev 本机直连 DB 常为空**（数据在打包 App 目录）；经 `webui.core` paths 解析后能读到 run-store。复算依赖 OHLCV/akshare，离线/限流时机构与筹码多降级——与页面表现一致，可接受。参见 [[opportunity-run-db-and-config-parity]]、[[stock-suite-empty-panels]]。
- **首次复算可能较慢**（冷缓存逐股 OHLCV 补偿 + 30 模型 + akshare）；靠 `suite_limit` + 时间预算兜底，5 分钟 LRU 让二次导出快。
- 桌面 App 若改了 JS 需注意 WKWebView 缓存（本任务不改 JS，仅后端 + 模板无关）。
- 改桌面交互逻辑走 `/static/kronos_desktop_app.js`（本任务不涉及）。

## 10. 交付清单

- 新增 `webui/opportunity_excel.py`（装配 + 样式规格）。
- 改 `webui/core.py::export_opportunity_canvas_excel`（编排 + 注入 fetcher）+ 写盘器加 `_style_worksheet`。
- 扩展 `tests/test_opportunity_report_parser.py`。
- 必要时小幅扩展 `webui/services/stock_suite_service.py` 仅用于防御性包装（如复算超时控制，若决定在 fetcher 侧加超时）。
- 文档：本 spec。
