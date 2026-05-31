# UZI-Skill 深度分析 × kronos_ultra 融合优化建议

- **作者**：Claude Code（OpenClawd 协助）
- **日期**：2026-05-29
- **状态**：Research + Advisory（待用户复审，未实施）
- **研究对象**：[`wbh604/UZI-Skill`](https://github.com/wbh604/UZI-Skill) · v3.5.0 · MIT · ⭐1,816 / 🍴278（截至 2026-05-29）
- **关联代码**：`analysis/` · `analysis/institutional/` · `analysis/llm_service.py` ·
  `analysis/technical_analysis.py` · `data_store/` · `webui/`
- **关联 spec**：[`2026-05-28-individual-stock-deep-mining-design.md`](2026-05-28-individual-stock-deep-mining-design.md)
  · [`2026-05-23-stock-analysis-suite-design.md`](2026-05-23-stock-analysis-suite-design.md)
  · [`2026-05-25-data-sqlite-migration-design.md`](2026-05-25-data-sqlite-migration-design.md)

> 置信度标注：🟢 高（基于 UZI 源码 / kronos 源码直读）· 🟡 中（基于设计文档与接口签名推断）· 🔴 低（需进一步验证）

---

## 0. 执行摘要（TL;DR）

UZI-Skill 与 kronos_ultra **处在同一赛道**（A 股 / 港股 / 美股个股深度分析），但走了
**互补的两条路**：

| | kronos_ultra | UZI-Skill |
|---|---|---|
| 强在 | **基础设施**：SQLite 数据仓 + 回测闭环 + Kronos K 线基座模型 + 30 量化模型 + Robyn WebUI + 多 LLM Provider | **分析方法论 + 表达层**：51 大佬评审团 + 17 种机构估值法 + Agent 主导叙事 + 机械化质量门 + Bloomberg 报告/分享战报 |
| 弱在 | LLM 仅"单次出文本"、无多视角评审、无估值建模、无机械质量门、报告偏工程化 | 无自有数据仓（每次 24h 文件缓存）、无回测验证、无趋势预测模型、无 Web 服务化 |

**核心判断**：UZI 最值得吸收的 **不是数据采集代码**（kronos 的 `data_store` + `institutional/`
provider 体系已更成熟、且已 SQLite 化），而是它的 **6 个"软件设计资产"**：

1. 🥇 **闭环数据契约 + Agent 覆盖层**（`agent_analysis.json` merge 模式）—— 让 LLM 从"出一段文本"升级为"结构化覆盖脚本结论"。
2. 🥇 **51 大佬评审团 / 多流派视角**（persona YAML + 规则引擎 + style 加权 + 单派锁定）。
3. 🥇 **机械化自检质量门**（`self_review.py` 13 条 BUG 派生规则，critical 即 `raise`，拒绝出报告）。
4. 🥈 **17 种机构估值法**（DCF / Comps / LBO / 三表 / IC Memo / Porter）—— kronos 完全缺失的估值维度。
5. 🥈 **多空大分歧叙事 + 分享战报**（punchline / Great Divide / share-card PNG）—— 直接提升用户可感知价值。
6. 🥉 **数据源 registry + 网络 preflight + Playwright 兜底**（kronos 已有 fallback 链，可借鉴其分层与健康度模型）。

**最高 ROI 的三件事**（详见 §6、§7）：
- **P0-A**：把 `analysis/llm_service.py` 升级为"两段式 + agent_analysis 闭环"，复用现有 12-Tab payload 作为 `raw_data` 契约。
- **P0-B**：移植 `self_review.py` 思想，给 `StockAnalysisSuite` payload 与 AI 解读加一道机械质量门。
- **P1-A**：在 12-Tab 工作台新增 **"大佬评审团" Tab**（51/精选流派），用 kronos 已有数据喂 persona 规则引擎。

> ⚠️ 许可证：UZI-Skill 为 **MIT**，与本项目兼容。**移植代码须保留版权声明**，并在
> `NOTICE` / 文件头标注来源。建议"借鉴设计 + 重写实现"为主，避免大段直接拷贝其
> `lib/` 业务代码（其耦合较深、且面向 CLI/插件环境）。

---

## 1. UZI-Skill 项目画像 🟢

### 1.1 它到底是什么

一句话：**一个"跨 AI 平台（Claude Code / Codex / Cursor / OpenCode / Gemini）的个股深度分析
Skill 插件"**，口号"冰冷的钱就这样流进我温暖的口袋——游资（UZI）Skills"。

- **形态**：不是 Web 应用，而是一个 **Agent Skill**——核心是 `skills/deep-analysis/SKILL.md`
  （54KB 的工作流编排说明书）+ 一堆 Python 计算脚本 + 多平台插件清单。
- **规模**：371 文件，Python 1.63MB / HTML 109KB；332 个 pytest；`RELEASE-NOTES.md` 168KB、
  `BUGS-LOG.md` 104KB（迭代极其频繁，6 周内从 v2.x 干到 v3.5）。
- **覆盖**：A 股 / 港股 / 美股；22 维数据 × 51 位投资大佬 × 17 种机构方法 × 杀猪盘检测。

### 1.2 关键指标与活跃度 🟢

| 指标 | 值 |
|---|---|
| Stars / Forks | 1,816 / 278 |
| 创建 / 最近 push | 2026-04-16 / 2026-05-28 |
| 最新版本 | v3.5.0（`--school` 单一流派锁定 + SaaS 集成） |
| 语言 | Python（94%）+ HTML（6%）+ Shell |
| License | MIT |
| 测试 | `scripts/tests/` 50+ 文件，按 feature 版本命名（`test_v3_5_0_school_lock.py` 等） |

### 1.3 目录结构骨架 🟢

```
UZI-Skill/
├── run.py                         # 用户 CLI 入口（python run.py <ticker>）
├── AGENTS.md / CLAUDE.md / GEMINI.md / CODEX.md   # 各平台 agent 指令
├── .claude-plugin/ .codex/ .cursor-plugin/ .opencode/ gemini-extension.json  # 多平台清单
├── commands/                      # 15 个 slash 命令（analyze-stock / dcf / comps / ic-memo / scan-trap ...）
├── agents/investor-panel.md       # 评审团 sub-agent 定义
└── skills/deep-analysis/
    ├── SKILL.md                   # 工作流编排（6 Task + 一堆 HARD-GATE）
    ├── personas/*.yaml            # 51 位大佬 persona（12 旗舰手写 + 39 stub）
    ├── assets/{report-template.html, data-contracts.md, quality-checklist.md, avatars/*.svg}
    ├── references/task1..task5.md # 每个 Task 的操作手册
    └── scripts/
        ├── run_real_test.py       # stage1/stage2 入口
        ├── fetch_*.py (22)        # 22 维数据采集
        ├── compute_*.py           # 机构建模
        └── lib/
            ├── pipeline/          # v3.0 管道式架构（collect/score/synthesize + score_fns.py 1228 行）
            ├── report/            # svg_primitives / dim_viz / institutional / panel_cards / special_cards
            ├── fin_models.py      # DCF/Comps/LBO/三表/并购
            ├── deep_analysis_methods.py  # IC Memo/Porter/BCG/DD/单位经济
            ├── investor_{criteria,evaluator,personas,knowledge}.py  # 51 人 180 规则评审
            ├── self_review.py     # 13 条机械质量门（critical raise）
            ├── data_source_registry.py / network_preflight.py / playwright_fallback.py
            └── stock_style.py / quant_signal.py / segmental_model.py
```

---

## 2. UZI-Skill 核心设计解剖（"值得偷的 7 个设计"）🟢

### 2.1 两段式执行："脚本算数，Agent 推理"

这是整个项目的 **灵魂设定**（SKILL.md 开篇）：

> "你不是脚本的搬运工——你是分析师。脚本负责算数，你负责推理和下结论。"

- **Stage 1（脚本）**：`stage1()` 跑完 Task 1（22 维采集）→ 1.5（机构建模）→ 2（打分）→ 3（规则引擎骨架分）。
- **中间（Agent 介入）**：读骨架分 → spawn 4 个并行 sub-agent role-play 投资者 → 写 `agent_analysis.json`。
- **Stage 2（脚本）**：`stage2()` 读 `agent_analysis.json` 合并 → 出 HTML 报告。

价值：**确定性计算与不确定性判断彻底解耦**。脚本可单测、可缓存、可回归；Agent 只负责"读
数据 + 写判断"，且判断被结构化约束（见 2.2）。kronos 当前的 `llm_service.analyze_stock`
是"喂 prompt → 拿一段 markdown"，没有这个分层。

### 2.2 闭环数据契约（最值得移植的工程模式）🥇

5 个 Task 通过 **JSON 文件**串联，字段契约写在 `assets/data-contracts.md`：

```
raw_data.json     (Task1/1.5 脚本写)    22 维原始数据 + dim20/21/22 机构建模
   ↓
dimensions.json   (Task2 脚本写)        每维 score/weight/reasons_pass/fail
   ↓
panel.json        (Task3 规则引擎写 → Agent 覆盖)  51 人 signal/score/headline/reasoning
   ↓
agent_analysis.json  (★ Agent 写)       dim_commentary + panel_insights + great_divide_override + narrative_override
   ↓
synthesis.json    (stage2 合并 agent_analysis)  最终研判
   ↓
full-report.html  (Task5 脚本)
```

**精髓在 `agent_analysis.json`**：Agent **不直接改 synthesis.json**（会被覆盖），而是写一个
**独立的"覆盖层"文件**，由 `stage2()` 的 `generate_synthesis()` 自动 merge，agent 字段
优先级 > 脚本 stub。好处：
- 脚本结论与 Agent 结论 **物理隔离**，可 diff、可审计、可回滚到纯脚本模式。
- 字段级 schema 校验（`agent_analysis_validator.py`）：缺字段 → 写 `_agent_analysis_errors.json`，
  agent 按提示修。例如 `buy_zones` 必须含 `value/growth/technical/youzi` 四个 key（缺 → error）。

> kronos 已有 12-Tab payload（`overview/main_force_deep/institutional_holdings/chip_control/quant_matrix`），
> **天然就是 `raw_data.json` 的等价物**。只差一个"agent 覆盖层"契约。

### 2.3 51 大佬评审团 / 多流派视角 🥇

- **personas/*.yaml**：51 位投资者，分 A-G 七大流派（A 价值 / B 成长 / C 宏观 / D 技术 /
  E 中国价投 / F 游资 / G 量化）。12 旗舰（巴菲特/芒格/格雷厄姆/费雪/林奇/木头姐/索罗斯/
  达里奥/段永平/张坤/赵老哥/章盟主）**手写** persona（含 `voice`/`key_metrics`），39 个
  **auto-generated stub**（仅身份提示，主要靠规则引擎）。
- **规则引擎**：`investor_criteria.INVESTOR_RULES`（51 人 × 180 条规则）给"骨架分"，
  `investor_evaluator.evaluate_all(features)` 批量裁决；`stock_features.extract_features` 出
  **108 个标准化特征**。
- **Agent role-play 覆盖**：规则引擎只是"参考分"，真正判断由 Agent 站在每个人视角重写
  （巴菲特实际持有苹果 → 100 分，比任何规则都重要；木头姐看白酒 → "不在我的平台里" → skip）。
- **style 动态加权**（v2.7）：自动识别股票风格（白马/高成长/周期/小盘投机/分红防御/困境反转/
  量化因子），按 `流派 × style` 矩阵调整组级权重 + 8 个个体 override。
- **`--school` 单派锁定**（v3.5）：只看某一派视角，其他派 skip，报告顶部渲染 SCHOOL LOCK banner。
- **戏剧化产物**："Great Divide 多空大分歧"——选最高分 bull + 最低分 bear，3 轮辩论 + 一句
  可传播的 punchline（进分享卡）。

### 2.4 17 种机构级估值方法 🥈

改编自 `anthropics/financial-services-plugins`，A 股参数本地化（rf 2.5% / ERP 6% / 税 25% /
终值 g 2.5% / Beta 1.0 / 债务比 30%）：

| 类别 | 方法 | 模块 |
|---|---|---|
| 估值 | DCF（含 WACC + 5×5 敏感性 + 自检中心格）、Comps、三表预测、LBO（PE 买方 IRR）、并购增厚摊薄 | `lib/fin_models.py` |
| 研究 | 首次覆盖、财报解读、催化剂日历、逻辑追踪、晨报、量化筛选、行业综述 | `lib/research_workflow.py` |
| 决策 | IC Memo（Bull/Base/Bear 三情景）、Porter 五力 + BCG、单位经济、价值创造、DD 清单、组合再平衡 | `lib/deep_analysis_methods.py` |

设计原则（很值得学）：**公式 over 硬编码**（改假设全链条联动）、**step-by-step `methodology_log`
可审计**、**敏感性内置**、**默认值显式标 `DEFAULT_*`**、**强制三情景**。

> kronos **完全没有估值建模维度**——它是"趋势预测 + 技术/资金/情绪打分"导向。这是一个
> 干净的能力补位，且是纯计算（无需新数据源）。

### 2.5 机械化自检质量门（`self_review.py`）🥇

UZI 把"每一次踩过的坑"固化成 **13 条机械检查**，`assemble_report()` 跑前强制执行，
**critical 即 `raise RuntimeError` 拒绝出 HTML**：

| 严重度 | 检查 | 背后的真实 BUG |
|---|---|---|
| 🔴 | 行业映射 sanity | 工业金属→农副食品加工 碰撞 |
| 🔴 | 所有维度存在 / 非空 | wave2 timeout 丢维度 |
| 🔴 | 覆盖度 ≥ 60% | `_integrity.coverage_pct` 过低 |
| 🔴 | 无占位符串 "[脚本占位]" | 脚本 stub 漏进报告 |
| 🔴 | `agent_reviewed == true` | agent 跳过分析 |
| 🟡 | DCF/Comps 非全 0、有色金属须有原材料、编造"苹果产业链"红旗 | 各类幻觉 |

精髓：**质量不靠 agent 自觉，靠代码 block**。"修一半 critical 就出报告 = 报告不 ship"。

> kronos 的 `StockAnalysisSuite` 已经有 `data_status: fresh/stale/unavailable` 的优雅降级，
> 但**没有"拒绝出 AI 解读"的硬门**。可移植"机械门"思想到 payload 校验 + AI 解读前置检查。

### 2.6 数据韧性三件套 🥈

- **`data_source_registry.py`**（40+ 源、3 tier）：每个 dim 声明"主源 → 备源 → 浏览器源"，
  按 health 排序，失败 fallthrough。
- **`network_preflight.py`**：探测国内/境外/搜索 9 个目标可达性，写 `network_profile.json`，
  每维声明所需网络能力，不可达自动跳过。
- **`playwright_fallback.py`**：HTTP 全失败时用浏览器抓（雪球/东财 F10/cninfo）。

> kronos 已有 `AkshareAdapter` 的 fallback 链 + 限流 + 熔断 + `sync_log`（见 deep-mining spec §2.1），
> **设计上更收敛**。可借鉴 UZI 的"按 dim 声明网络能力 + health 排序"，以及"浏览器兜底"作为
> 最后一层。

### 2.7 表达层与跨平台分发 🥈

- **Bloomberg 风格 HTML**（`report-template.html` 109KB）+ SVG 图元库（`svg_primitives.py`）+
  **分享战报 PNG**（朋友圈 `share-card.png` 1080×1920、微信群 `war-report.png` 1920×1080）+
  一句话 `one-liner.txt`。
- **多平台插件清单**：同一套 Skill 通过 `.claude-plugin/` `.codex/` `gemini-extension.json` 等
  分发到 5 个 AI 平台。
- **进度条 UX**：每个 Task 完成打一个 20 字符进度条。

---

## 3. kronos_ultra 现状映射 🟢

### 3.1 已具备、且比 UZI 更成熟的部分

| 能力 | kronos 位置 | 相对 UZI 的优势 |
|---|---|---|
| 持久化数据仓 | `data_store/*.sqlite`（ohlcv/daily_basic/dragon_tiger/hsgt/holders/fund_hold/moneyflow/sentiment/kv...） | UZI 仅 24h 文件缓存，无跨次复用 |
| 机构数据 provider | `analysis/institutional/`（lhb/hsgt/holders/survey/fund_holdings/cyq + `quant_seat_registry`） | 已 DTO 化 + `data_status` 降级 + 量化席位识别 |
| 趋势预测 | `model/`（Kronos K 线基座模型）+ `examples/prediction_*` | UZI 无任何预测模型 |
| 量化模型 | `analysis/technical_analysis.py:216 QuantitativeModels`（30 模型 `analyze_model_01..30`） | 与 UZI 180 规则互补 |
| 回测闭环 | `scripts/auto_backtest.py` / `backtest_scoring_optimizer.py` / `opportunity_scorer` | UZI 完全无回测验证 |
| Web 服务 | `webui/`（Robyn + 12-Tab 个股工作台 + 形态选股 + 任务队列） | UZI 仅 CLI + 静态 HTML |
| 多 LLM Provider | `analysis/llm_service.py`（OpenAI 兼容 + DashScope + 工厂） | 与 UZI 平级 |

### 3.2 kronos 缺失、而 UZI 已成熟的部分（融合机会）

| 缺口 | UZI 对应 | 优先级 |
|---|---|---|
| LLM 仅"单次出文本"，无闭环/可审计覆盖层 | 两段式 + `agent_analysis.json` merge | **P0** |
| 无机械化报告/解读质量门 | `self_review.py` 13 检查 | **P0** |
| 无多视角/多流派评审团 | 51 persona + 规则引擎 + style 加权 | **P1** |
| 无估值建模（DCF/Comps/LBO/IC Memo） | `fin_models.py` + `deep_analysis_methods.py` | **P1** |
| 报告偏工程化，缺"可传播金句 + 分享图" | Great Divide punchline + share-card PNG | **P2** |
| 无"按 dim 声明网络能力 + 浏览器兜底" | registry + preflight + playwright | **P2** |

### 3.3 与"个股深度挖掘 spec（2026-05-28）"的关系 🟢

kronos 正在做的 12-Tab 工作台与 UZI **高度同构**：

| kronos Tab | UZI 对应 dim/方法 |
|---|---|
| `main_force_deep`（龙虎榜/北向/阶段时间轴/量化签名） | dim16_lhb + dim12_capital_flow + `quant_signal` |
| `institutional_holdings`（Top10/户数/调研/重仓基金） | `fetch_fund_holders` + 股东维度 |
| `chip_control`（控盘度/cyq/集中度） | 筹码维度 |
| `quant_matrix`（30 模型 × 多周期信号矩阵） | 51 评委规则引擎 + `quant_signal` |
| `ai_interpretation`（LLM 解读） | **← 这正是该套用"两段式 + agent_analysis"的地方** |

**结论**：融合不是"另起炉灶"，而是 **沿着 deep-mining spec 的既定方向，把 UZI 的方法论
注入到 M2–M5 里**（见 §7 路线图）。

---

## 4. 能力对照矩阵 🟢

| 维度 | kronos_ultra | UZI-Skill | 融合后理想态 |
|---|---|---|---|
| 数据采集 | SQLite 仓 + provider + 夜间 cron | 22 fetcher + 24h 文件缓存 | **保留 kronos 仓**，借 UZI 浏览器兜底 |
| 趋势预测 | ✅ Kronos 基座模型 | ❌ | 保留并作为"data perspective"输入评审团 |
| 量化信号 | ✅ 30 模型 + 信号矩阵 | ✅ 180 规则 + 108 特征 | 30 模型喂 quant_matrix；借 UZI 特征工程思路 |
| 估值建模 | ❌ | ✅ DCF/Comps/LBO/三表/IC Memo | **新增 `analysis/valuation/` 模块** |
| 多视角评审 | ❌ | ✅ 51 persona + style 加权 | **新增"评审团"Tab + persona 引擎** |
| LLM 编排 | 单次 analyze_stock | 两段式 + 闭环覆盖 + 多 sub-agent | **重构 llm_service 为两段式** |
| 质量保障 | data_status 降级 | 机械 13 检查 raise | **payload + 解读双层质量门** |
| 回测验证 | ✅ 完整闭环 | ❌ | **用回测验证评审团/估值的预测力** |
| 报告表达 | Robyn 12-Tab + ECharts | Bloomberg HTML + 分享 PNG | Web Tab 为主 + 加"分享卡"导出 |
| 分发 | Web/桌面/Tauri | 5 平台 Skill 插件 | （可选）把 kronos 分析能力也封成 Skill |

---

## 5. 融合的总体架构建议 🟡

建议在 **不破坏现有 12-Tab payload 向后兼容** 的前提下，引入一个 **"分析编排层"**：

```
                          点击个股 / CLI / Skill
                                   │
                                   ▼
                  StockAnalysisSuite._collect_inputs()   ← 已有：12-Tab payload = raw_data 契约
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        ▼                          ▼                            ▼
  analysis/valuation/      analysis/panel/              analysis/llm_orchestrator.py
  (新增·纯计算)            (新增·persona 引擎)          (重构 llm_service)
  DCF/Comps/LBO/IC Memo    51/精选大佬骨架分             两段式：
        │                          │                     stage1=collect(已有)
        └─────────┬────────────────┘                     ├─ 读 payload+骨架分
                  ▼                                       ├─ (可选)spawn sub-agent role-play
        payload 增 valuation / panel 顶层 key             └─ 写 analysis_overlay.json (= agent_analysis)
                  │                                                  │
                  ▼                                                  ▼
        analysis/report_quality.py (新增·机械质量门)  ←──── merge overlay
                  │  critical → 拒绝出"AI 解读"，回退骨架文案
                  ▼
        webui 渲染：新增"估值"Tab + "评审团"Tab + "分享卡"导出
                  │
                  ▼
        回测闭环验证：评审团共识 / 估值 safety_margin 是否有 alpha
```

关键约束（沿用 deep-mining spec 风格）：
- **payload 向后兼容**：新增 `valuation` / `panel` / `analysis_overlay` 顶层 key，不动现有 7+ Tab。
- **每个新 key 带 `data_status` + `last_updated`**，复用现有降级文案体系。
- **纯计算优先**：估值模块不引入新数据源（用已有 financials/daily_basic）。
- **Agent 介入可选**：默认走"规则引擎骨架 + 机械文案"，用户点"深度分析"才 spawn sub-agent
  （对应 UZI 的 lite/medium/deep 分档），控制 token 成本。

---

## 6. 分项融合建议（按优先级，每条含 What/Why/How/工作量/风险）

### 🥇 P0-A · LLM 升级为"两段式 + 闭环覆盖" 🟢

- **What**：把 `analysis/llm_service.py` 的 `analyze_stock`（单次出 markdown）重构为：
  ① `build_overlay_prompt(payload)` 产出 **结构化 JSON 覆盖**（dim_commentary / 多空分歧 /
  核心结论 / 风险 / 买入区间）；② `merge_overlay(payload, overlay)` 合并；③ schema 校验器。
- **Why**：当前 AI 解读是"黑盒一段话"，不可 diff、不可审计、易幻觉。闭环模式让 LLM 输出
  **结构化、可校验、可回退**，且与 deep-mining spec 的 `ai_interpretation` Tab 无缝对接。
- **How in kronos**：
  - 新增 `analysis/analysis_overlay_schema.py`（移植 UZI `agent_analysis_validator` 思想，用
    jsonschema）；overlay 文件落 `data_store/kv_repo`（而非散文件，复用 SQLite）。
  - `llm_service._build_analysis_prompt` 改为要求模型 **返回 JSON**（kronos 已有
    `parse_llm_response`，扩展为带 schema 重试）。
  - `post_stock_analysis_suite_ai`（`robyn_app.py:484`）改为返回"合并后 payload + overlay 审计"。
- **工作量**：🟡 中（~2-3 天）。**风险**：低（向后兼容，失败回退现有文案）。

### 🥇 P0-B · 机械化报告质量门 🟢

- **What**：新增 `analysis/report_quality.py`，对 `StockAnalysisSuite` payload + LLM overlay 跑
  ~10 条机械检查；critical 不过 → **不渲染 AI 解读**，回退骨架文案 + 顶部红条。
- **Why**：UZI 的核心教训——"质量不靠 agent 自觉，靠代码 block"。kronos 已有 `data_status`，
  但缺"拒绝输出"的硬门，LLM 幻觉/占位符可能直接进报告。
- **How in kronos**：检查清单本地化（覆盖度阈值、占位符串、`overlay.reviewed==true`、买入区间
  四档齐全、风险 ≥3 条、引用数字必须能在 payload 找到出处）。复用现有
  `tests/test_stock_analysis_suite.py` 扩展。诊断走已有 `/api/diagnostics/data-sources`。
- **工作量**：🟢 小（~1-2 天）。**风险**：低。

### 🥇 P1-A · "大佬评审团" Tab + persona 引擎 🟡

- **What**：新增 `analysis/panel/`（persona 注册表 + 规则引擎 + style 加权），在 12-Tab 工作台
  新增 **"评审团"Tab**（Tab #13，放 `ai_interpretation` 前），展示 N 位大佬的 signal/score/
  headline + 多空分歧 + style 加权后的共识分。
- **Why**：这是 UZI 最具"用户可感知差异化"的功能，且与 kronos 已有数据天然契合（龙虎榜→游资派、
  ROE/护城河→价值派、30 模型→量化派）。回测闭环还能**验证哪一派的共识真有 alpha**（UZI 做不到）。
- **How in kronos**：
  - persona 定义用 YAML（可直接参考 UZI 的 schema：school/group/voice/key_metrics），
    **但规则重写**（绑定 kronos 的 `extract_features` 等价物，而非 UZI 的 108 特征）。
  - **起步先做精选 12 旗舰 + 7 流派代表**（不必一上来 51 人），降低规则工程量。
  - 复用 `config/quant_seats.json` + `quant_seat_registry`：游资派直接吃龙虎榜量化席位信号。
  - style 加权读 `config/scoring_runtime_config.json`（已有），与回测优化器联动调权重。
- **工作量**：🔴 大（~1-2 周，分档交付）。**风险**：中（规则质量需回测校准；先 12 人降风险）。

### 🥈 P1-B · 估值建模模块 `analysis/valuation/` 🟢

- **What**：新增纯计算的 DCF / Comps / LBO / 三表 / IC Memo（Bull/Base/Bear 三情景），
  payload 增 `valuation` 顶层 key，新增"估值"Tab（DCF 敏感性热力图 + 三角验证卡）。
- **Why**：kronos 完全缺估值视角；纯计算、无新数据源（用已有 financials/daily_basic）；
  与"价值派评审团"互为输入（DCF intrinsic → 买入区间 value 档）。
- **How in kronos**：A 股参数本地化照搬 UZI 的 `fin-methods`（rf 2.5%/ERP 6%/税 25%...，
  这些是公开金融常识，非 UZI 独创）；**实现重写**，每个函数返回带 `methodology_log` + 5×5
  敏感性（中心格自检）。ECharts `heatmap` 渲染敏感性表。
- **工作量**：🟡 中（~3-5 天）。**风险**：低（纯计算可单测）。

### 🥈 P2-A · 多空分歧叙事 + 分享卡导出 🟡

- **What**：评审团产出 Great Divide（最高 bull vs 最低 bear + punchline），LLM overlay 生成
  "可传播金句"；webui 加"导出分享卡 PNG"（个股结论 + 评分 + 金句 + 二维码）。
- **Why**：直接提升用户"想截图发群"的可感知价值；UZI 的 share-card 是其传播飞轮核心。
- **How in kronos**：punchline 走 P0-A 的 overlay 字段；分享卡可用前端 Canvas / 服务端
  Pillow 渲染（kronos 已有 `figures/` 与报告产物体系）。
- **工作量**：🟡 中。**风险**：低。

### 🥉 P2-B · 数据源 health 分层 + 浏览器兜底 🟡

- **What**：给 `AkshareAdapter` 的 fallback 链补"按 dim 声明网络能力 + health 排序"，
  并加一层 Playwright 兜底（仅对最常被反爬的 push2/cninfo）。
- **Why**：kronos 已有 fallback/熔断，UZI 的"health 模型 + 浏览器最后一层"是增量增强。
- **How**：扩展现有 `data_store/akshare_adapter.py` 的 `FALLBACK_CHAINS` 为带 health 的
  结构；Playwright 兜底设为可选依赖（不进默认安装）。
- **工作量**：🟡 中。**风险**：中（Playwright 增加运维复杂度，建议默认关闭）。

### 🥉 P3 · （可选）把 kronos 分析能力封成跨平台 Skill 🔴

- **What**：参考 UZI 的 `.claude-plugin/` + `SKILL.md` 模式，把 kronos 的个股分析封成一个
  Claude Code Skill / 插件，让 kronos 不止是 Web 应用，也能在 agent 环境一键调用。
- **Why**：扩大触达面（UZI 的 1816 star 很大程度来自"插件即用"）。
- **工作量**：🟡 中。**风险**：低（纯增量，不影响 Web）。**建议**：等 P0/P1 稳定后再做。

---

## 7. 分阶段路线图（对齐 deep-mining spec 的 M 里程碑）🟡

| 阶段 | 内容 | 对齐 | 验收 |
|---|---|---|---|
| **F1**（P0） | 两段式 LLM 闭环 + overlay schema + 机械质量门 | deep-mining **M3/M5 的 AI 解读** | AI 解读输出结构化 JSON；critical 不过则回退骨架文案；扩展 `test_stock_analysis_suite.py` 全绿 |
| **F2**（P1-B） | `analysis/valuation/` DCF/Comps/LBO/IC Memo + 估值 Tab | 新增 Tab，复用 ECharts | DCF 敏感性中心格自检通过；估值三角验证卡渲染 |
| **F3**（P1-A 起步） | 精选 12 旗舰 + 7 流派评审团 Tab + style 加权 | 新增 Tab #13 | 12 人 signal/score 渲染；共识分 + 多空分歧；游资派吃龙虎榜量化席位 |
| **F4** | 评审团/估值 **接入回测闭环**，验证 alpha；按结果扩到 51 人 | `scripts/auto_backtest.py` | 回测显示某派共识或 DCF safety_margin 与未来收益相关性 > 阈值 |
| **F5**（P2） | 多空金句 + 分享卡 PNG 导出 + 数据源 health 分层 | — | 一键导出分享卡；最常失败维度有浏览器兜底 |

> **关键差异化**：UZI 无法验证它的 51 评委到底准不准；kronos 有回测闭环，**F4 是 kronos
> 能甩开 UZI 的杀手锏**——用历史数据证明"哪派大佬/哪种估值法在 A 股真有效"，再据此调 style 权重。

---

## 8. 与当前两个 WebUI 待办的衔接 🟢

用户在本次会话中追加的两个 webui 诉求，与本融合方向 **天然契合**，建议一并纳入：

1. **报告库 / 任务队列收成弹窗按钮 + 腾出空间放热点（东财/板块/股票热点）**
   （`desktop.html` 206/217/320/443/464；`market_intelligence.py` 已有市场情报服务）
   → 可借鉴 UZI 的 `lib/hottrend.py`（热点榜单聚合）思路，把腾出的版面做成
   "东财热点 / 板块热点 / 个股异动"三栏热点流，点击直接进 12-Tab 工作台。
   （详见独立任务 #5，本融合 spec 不展开实现细节。）

2. **形态选股保存后，缺"查看历史图形 / 历史图形选股"入口**
   （`pattern_search_service.py` + `pattern_search_*` 路由缺 save/list 闭环）
   → 与 UZI 关系较弱，属 kronos 自身 `pattern_search` 闭环补全。
   （详见独立任务 #6。）

> 这两项我会在本 spec 复审后、作为 **独立小改动** 单独处理，不与大融合耦合。

---

## 9. 风险、边界与"不要做的事" 🟢

| 风险 | 说明 | 对策 |
|---|---|---|
| 许可证 | UZI = MIT，兼容；但大段拷贝其 `lib/` 业务代码会引入耦合 + 版权声明义务 | **借鉴设计、重写实现**；必要时拷贝的文件保留 MIT 头 + 记 `NOTICE` |
| 重复造轮子 | UZI 的数据采集 ≈ kronos `data_store`，但 kronos 已更成熟 | **不要移植 UZI 的 fetcher/数据层**，只取方法论与表达层 |
| Token 成本 | 51 人 role-play / 多 sub-agent 很贵 | 分档（lite/medium/deep）；默认规则引擎骨架，深度档才 spawn |
| 规则质量 | persona 规则若不校准会误导用户 | **先 12 人 + 回测校准**，再扩 51；UI 标"规则推断，仅供参考" |
| 幻觉 | LLM 编造"X 是 Y 产业链一环" | 移植 UZI 的 FACTCHECK 门：每条结论须能在 payload 找出处 |
| 维护面膨胀 | 12 Tab → 14 Tab + 估值 + 评审团 | 沿用 spec 的"懒渲染 + 顶层 key 独立可关闭"原则 |

**明确不做**：① 不移植 UZI 数据采集层；② 不引入 UZI 的 CLI/插件运行时；③ 不一次性上 51 人；
④ 不为分享卡引入重型渲染依赖。

---

## 10. 附录 A · UZI 关键文件 → kronos 对照速查

| UZI 文件 | 作用 | kronos 对应 / 建议落点 |
|---|---|---|
| `SKILL.md` 两段式编排 | 工作流 | `analysis/llm_orchestrator.py`（新） |
| `assets/data-contracts.md` | JSON 契约 | `analysis/analysis_overlay_schema.py`（新）+ 现有 payload |
| `lib/agent_analysis_validator.py` | 覆盖层校验 | overlay schema 校验器（新） |
| `lib/self_review.py` | 13 机械门 | `analysis/report_quality.py`（新） |
| `personas/*.yaml` + `investor_criteria.py` | 51 人规则 | `analysis/panel/`（新，先 12 人） |
| `lib/stock_style.py` | style 加权 | `config/scoring_runtime_config.json`（已有）+ 加权器 |
| `lib/fin_models.py` | DCF/Comps/LBO | `analysis/valuation/`（新） |
| `lib/deep_analysis_methods.py` | IC Memo/Porter | `analysis/valuation/`（新） |
| `lib/data_source_registry.py` | 源 health 分层 | 扩展 `data_store/akshare_adapter.py` |
| `lib/hottrend.py` | 热点榜单 | webui 热点流（衔接任务 #5） |
| `report-template.html` + `lib/report/` | Bloomberg 报告 | 保留 Robyn 12-Tab + 加分享卡导出 |

## 11. 附录 B · 研究方法与置信度

- **数据来源**：GitHub 公共 API（metadata/commits/tree）+ 通过 contents API 直读 14 个核心
  设计文档（SKILL.md / AGENTS.md / data-contracts.md / task1.5/2/3/4 / fin-methods / 命令 /
  插件清单）。kronos 侧直读源码与 3 份现有 spec。
- **未直读**（基于文件名/接口推断，🟡）：UZI 的 `score_fns.py`(65KB)、`investor_criteria.py`(38KB)、
  `self_review.py` 的逐条实现、`report/` 渲染细节。结论依据其 SKILL.md/references 的自述与
  schema，已足够支撑设计级建议；**若进入实施，建议对将要移植的具体模块再做一次源码精读**。
- **置信度**：项目画像与设计模式 🟢；kronos 落点与工作量估算 🟡（依赖实施时的代码细节）。
