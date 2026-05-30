# 多空评审团 Tab — 设计 spec

- **作者**：Claude Code（OpenClawd 协助）
- **日期**：2026-05-30
- **状态**：Design（待用户复审 → 转 writing-plans）
- **来源**：[`2026-05-29-uzi-skill-deep-analysis-and-integration.md`](2026-05-29-uzi-skill-deep-analysis-and-integration.md) 的 P0-A / P0-B / P1-A 收口为一个垂直切片
- **关联代码**：`analysis/stock_analysis_suite.py` · `analysis/technical_analysis.py`（30 模型）· `analysis/institutional/` · `analysis/llm_service.py` · `data_store/kv_repo.py` · `config/scoring_runtime_config.json` · `webui/templates/desktop.html`（12-Tab 工作台）· `scripts/auto_backtest.py`
- **可视化决策**：经 brainstorm 浏览器伴侣确认 —— **C「Bloomberg 终端」风格 · 51 位按 7 流派可折叠 · 16 项量化指标 · 动画策略 ③（克制：顶部常动、成员行悬停/更新才动）**。配色 A 股习惯：**红 = 多/看涨，绿 = 空/看跌**。

---

## 0. 概要

在个股 12-Tab 工作台新增 **第 13 个 Tab「多空评审团」**：以终端风格,用 **51 位资深投资人 persona** 的多空裁决 + **16 项量化指标** + **多空温度计共识** + **多空大分歧（Great Divide）+ 可传播金句**,把"这只票现在多空怎么看"一屏说清。规则引擎出骨架分(可单测、可回测),LLM 只写"覆盖层"点评(结构化、可校验、可回退),机械质量门在出 AI 点评前 block 幻觉/占位符。**kronos 独有的 Kronos K线预测 + 回测胜率** 作为差异化指标,并最终用回测闭环验证"哪派大佬/哪类指标真有 alpha"。

## 1. 目标与范围

**做（本 spec）**
- 新增 `analysis/panel/`：persona 注册表（YAML）+ 规则引擎 + style 加权 + 共识/大分歧计算。
- 新增 payload 顶层 key `panel`（向后兼容,带 `data_status`/`last_updated`）。
- 16 项量化指标聚合（**复用** kronos 既有数据,不引新数据源）。
- LLM 覆盖层 `analysis/analysis_overlay`（P0-A）+ schema 校验 + `kv_repo` 持久化。
- 机械质量门 `analysis/report_quality.py`（P0-B）。
- 前端 Tab #13 渲染（终端风格 + 折叠 + 动画 ③）。

> 以上为**完整设计范围**；实现按 §11 分阶段交付，**首个实现计划只覆盖 Phase 1（纯规则、无 LLM）**，P0-A 覆盖层与 P0-B 质量门属 Phase 2、回测校准属 Phase 3。

**不做（另立 spec / 后续阶段）**
- 估值建模 `analysis/valuation/`（P1-B，独立 spec）。
- 分享卡 PNG 导出（P2-A）。
- **不一次性手写 51 套规则**：12 旗舰手写 + 39 规则衍生 stub（见 §4、§11）。
- 不移植 UZI 的数据采集层 / CLI / 插件运行时。

## 2. 总体架构与数据流

```
点击个股 → StockAnalysisSuite._collect_inputs()         （已有：12-Tab payload = raw_data 契约）
                         │
        ┌────────────────┼─────────────────────────────┐
        ▼                ▼                               ▼
 analysis/panel/   16 量化指标聚合器               analysis/analysis_overlay (P0-A)
 (新·纯计算/规则)  (新·复用既有 provider)          (重构自 llm_service)
 persona 规则引擎  资金/技术/筹码/机构/模型          stage1 = 已有 payload + panel 骨架分
 → 每人 signal/    → 16 格多空信号                  → build_overlay_prompt → LLM 返回 JSON
   score/headline                                   → schema 校验（失败重试/回退）
        │                │                          → merge_overlay（agent 字段 > 脚本 stub）
        └────────┬───────┴──────────────────────────┘  → 落 data_store/kv_repo
                 ▼
        共识温度计 + 多空大分歧（由 panel 分数算）
                 │
                 ▼
        analysis/report_quality.py（P0-B 机械质量门）
                 │  critical 不过 → 不渲染 AI 点评，回退规则文案 + 顶部红条
                 ▼
        payload 增 panel / analysis_overlay 顶层 key（带 data_status）
                 ▼
        webui Tab #13「多空评审团」渲染（终端风格 + 折叠 + 动画 ③）
                 ▼
        scripts/auto_backtest.py 验证：哪派共识 / 哪类指标有 alpha → 校准 style 权重（F4）
```

关键约束（沿用 deep-mining spec 风格）：
- **payload 向后兼容**：只新增顶层 key,不改既有 7+ Tab。
- 每个新 key 带 `data_status: fresh/stale/unavailable` + `last_updated`,复用既有降级文案。
- **纯计算/规则优先**：默认走规则引擎骨架 + 模板文案;LLM 覆盖为可选档(lite/medium/deep),控 token。
- **懒渲染**：折叠态不渲染成员,展开才渲染。

## 3. 数据契约：payload 增量

```jsonc
"panel": {
  "data_status": "fresh",
  "last_updated": "2026-05-30 14:00:00",
  "consensus": { "score": 61, "label": "偏多", "bull": 28, "neutral": 11, "bear": 12 },
  "great_divide": {
    "bull": { "id": "zhao", "name": "赵老哥", "school": "F", "score": 92 },
    "bear": { "id": "soros", "name": "索罗斯", "school": "C", "score": 31 },
    "punchline": null            // 规则阶段为模板；P0-A 由 LLM 覆盖
  },
  "schools": [ { "key": "A", "name": "价值派", "count": 9, "lean": "偏空", "lean_score": 46 } /* …7 派 */ ],
  "analysts": [
    { "id":"buffett","name":"巴菲特","school":"A","signal":"bull","score":78,
      "headline":"护城河强，长期持有","source":"handwritten","reasons":["ROE>20%","品牌护城河"] }
    /* …51 人 */
  ]
},
"analysis_overlay": {           // P0-A 产物；规则阶段可为 null（前端回退模板）
  "data_status": "fresh", "reviewed": true,
  "panel_insights": { "buffett": "持有 Apple 思路套用：现金牛+护城河，回调即买" },
  "great_divide_override": { "punchline": "放量突破+量化席位进场，多头压制估值担忧" },
  "buy_zones": { "value": [...], "growth": [...], "technical": [...], "youzi": [...] },
  "risks": ["估值透支三年成长", "..."], "narrative_override": "..."
}
```

## 4. persona 引擎 `analysis/panel/`

- **`personas/*.yaml`**：`id / name / school(A-G) / voice / key_metrics / rules`。7 流派：A 价值 / B 成长 / C 宏观 / D 技术 / E 中国价投 / F 游资 / G 量化。
- **12 旗舰手写**（巴菲特/芒格/格雷厄姆/费雪/林奇/木头姐/索罗斯/达里奥/段永平/张坤/赵老哥/章盟主）：规则**绑定 kronos 既有特征**(而非 UZI 的 108 特征)。
- **39 规则衍生 stub**：仅身份提示 + 流派级默认规则(继承所属 school 的裁决逻辑),UI 标注"规则推断,仅供参考"。
- **`features.py`**：`extract_features(payload) -> dict` —— 从既有 payload 抽标准化特征(ROE/PE/PB、龙虎榜量化席位、30 模型共振、主力/北向、控盘度、Kronos 预测方向…),供规则消费。
- **裁决**：`evaluate_all(features) -> [{id,signal,score,headline,reasons}]`。signal ∈ {bull,bear,neutral}。映射示例：龙虎榜量化席位 → 游资派;ROE/护城河 → 价值派;30 模型 → 量化派。
- **style 加权**：识别股票风格(白马/高成长/周期/小盘投机/分红/困境反转/量化),按 `流派 × style` 矩阵调权;权重读 `config/scoring_runtime_config.json`(已有,可被 §10 回测优化器联动调整)。

## 5. 量化指标栏（16 项 → kronos 数据源映射）

| 组 | 指标 | 多空判据 | kronos 数据来源 |
|---|---|---|---|
| 资金面 | 主力资金 / 北向 / 超大单 / 龙虎榜席位 | 净流入符号、量化席位进出 | `moneyflow_repo` · `hsgt_provider` · `lhb_provider`+`quant_seat_registry` |
| 技术面 | RSI / MACD / KDJ / 均线排列 / 布林带 / 量能 | 既有阈值规则 | `analysis/technical_analysis.py`（TechnicalAnalysis） |
| 筹码·机构 | 控盘度 / 股东户数 / 重仓基金 | 控盘阈值、户数减少=集中、基金增减持 | `cyq`/筹码 · `holders_provider` · `fund_holdings_provider` |
| 模型·预测 | 30模型共振 / ★Kronos K线预测 / ★回测胜率 | 多空模型占比、预测方向、该形态历史胜率 | `QuantitativeModels`(30 模型) · `model/`(Kronos) · `scripts/auto_backtest.py` |

- 每格归一为 `{label, value_text, signal: up/down/neutral, strength: 0..1}`,前端按红/绿/黄 + 动条渲染。
- ★ 两项为差异化核心(UZI 无预测/无回测)。

## 6. 多空共识 / 大分歧

- **共识温度计**：`consensus.score = Σ(analyst.score × school_weight × style_weight) / Σweights`,映射到 0(极空)–100(极多);标记滑块位置。
- **大分歧 Great Divide**：取最高分 bull 与最低分 bear;`punchline` 规则阶段用模板(`{bull_name} 看到 {top_reason}，{bear_name} 担心 {top_risk}`),P0-A 由 LLM 覆盖为可传播金句。

## 7. LLM 覆盖层（P0-A）`analysis/analysis_overlay`

- 重构 `llm_service`：`build_overlay_prompt(payload, panel)` 要求模型**返回 JSON**(扩展既有 `parse_llm_response` 为带 schema 重试)。
- `analysis_overlay_schema.py`：jsonschema 校验(移植 UZI `agent_analysis_validator` 思想);缺字段 → 回写错误提示重试 N 次,仍失败 → `reviewed=false` 回退规则文案。
- `merge_overlay(payload, overlay)`：agent 字段优先级 > 规则 stub;**物理隔离**(overlay 独立存 `kv_repo`,可 diff/审计/回滚)。
- **分档**：lite=不调 LLM(纯规则)、medium=只写 punchline+大分歧、deep=逐 persona 点评。默认 lite,用户点"深度分析"才升档。
- 接入点：`post_stock_analysis_suite_ai`(`robyn_app.py`)返回"合并后 payload + overlay 审计"。

## 8. 机械质量门（P0-B）`analysis/report_quality.py`

出 AI 点评前强制跑,**critical 不过 → 不渲染 AI 点评,回退规则文案 + 顶部红条**：

| 严重度 | 检查 |
|---|---|
| 🔴 | 覆盖度 ≥ 阈值(关键维度非空) |
| 🔴 | 无占位符串("[脚本占位]"/"TODO"等) |
| 🔴 | `analysis_overlay.reviewed == true` |
| 🔴 | `buy_zones` 四档(value/growth/technical/youzi)齐全 |
| 🟡 | 风险 ≥ 3 条;引用数字必须能在 payload 找到出处(FACTCHECK) |
| 🟡 | 行业映射 sanity(防"工业金属→农副食品"碰撞)、防编造产业链红旗 |

诊断走既有 `/api/diagnostics/data-sources`;扩展 `tests/test_stock_analysis_suite.py`。

### 8.1 实现设计（P0-B v1，范围裁定）

**模块接口** —— 纯函数,无 I/O,可单测:

```
analysis/report_quality.py
def evaluate_overlay(overlay, panel, payload, tier) -> QualityReport
# QualityReport = {"passed": bool, "criticals": [str], "warnings": [str]}
```

仅在「结构合法」的 overlay 上运行(即已过 `schema.validate_overlay`、`build_overlay` 即将返回 `reviewed=True` 时);LLM 未配置/返回非法的 overlay 走既有「未生成」路径,不算质量拦截。

**分档检查(tier-aware):**

🔴 Critical(拦截 → `reviewed=False` + 红条 + 回退规则文案):

- **无占位符** —— overlay 任一字符串(punchline / risks[] / panel_insights 值 / narrative_override / buy_zones 项)不得含 `[脚本占位]`/`TODO`/`占位`/`待补充`/`XXX`/未填充 `{...}`。复用 `analysis/sector_api.py` 的 `_is_placeholder_text` 范式。
- **punchline 非空**(medium 及以上)。
- **逐人覆盖**(仅 deep) —— `panel_insights` 必须同时点评 `great_divide.bull.id` 与 `great_divide.bear.id`(两位头牌不得空白)。
- **buy_zones 内容**(仅 deep) —— 四档键齐全(schema 已保证)且 ≥1 档非空(至少一个可操作区间)。

🟡 Warning(软旗标,不拦截):

- **风险 ≥ 3 条** —— 不足则黄旗。
- **FACTCHECK(轻量)** —— 从 overlay 文本抽数字 token,任一无法在 payload 数值集合内按取整容差(支持 `亿/万`、`%`、1–2 位小数)匹配 → 黄旗列出。刻意保守以免误报。

**本期不做(显式裁定,非静默截断):** 行业映射 sanity + 编造产业链红旗(需 sector 交叉校验、启发式模糊,v1 后另议)。

**接入点 / 控制流** —— `build_overlay`(`analysis/analysis_overlay/engine.py`)在 schema 合法的 `_success(...)` 之后:

```
overlay = _success(obj, tier, now_iso)        # reviewed=True
report  = evaluate_overlay(overlay, panel, payload, tier)
overlay["quality"] = report                   # 新增契约字段,恒存在
if not report["passed"]:
    overlay["reviewed"] = False               # 复用既有回退链
    overlay["reason"]   = "质量门拦截：" + "；".join(report["criticals"])
return overlay
```

单一收口点,生成与重生成路径都被门控。`quality` 成为 overlay 上恒存在的新字段。

**前端(`renderPanelOverlay`,`desktop.html`)** —— 用新 `quality` 字段三分支:

- `reviewed===true` → 照常渲染 AI 卡;若 `quality.warnings.length` → 卡内黄旗条。
- `reviewed===false` 且 `quality.criticals.length` → 顶部红条(`bbp-overlay-redbar`)+ 原因 + 重试按钮;下方仍渲染规则版 panel。
- `reviewed===false` 且无 criticals → 既有「AI 深度点评」升档按钮(未生成)。

**持久化 / 重载** —— `trigger_panel_overlay` 落 kv 时**含被拦截的 overlay**(审计 / diff / 回滚);重载时红条 + 重试复现,重试走 `force_refresh`。

**向后兼容** —— `quality` 为增量字段;P0-A 旧持久化 overlay 无此字段,前端将「缺 quality」视作「无警告」。

**测试(TDD,见 §12):** 新增 `tests/test_report_quality.py`(每条 🔴/🟡 一个 red→green:占位符被拦、逐人覆盖缺失被拦、buy_zones 空被拦、风险<3 黄旗、FACTCHECK 抓编造数字 / 放行真实数字、passed happy path);扩展 `tests/test_analysis_overlay.py`(build_overlay 命中 critical 时 `reviewed→False` 且挂 `quality`);webui 表面断言红条分支。

## 9. 前端：Tab #13「多空评审团」

- 位置：12-Tab 工作台新增第 13 Tab,放 `ai_interpretation` 之前。
- 结构(对应 brainstorm 终稿 `panel-51.html` + `quant-board.html`)：
  1. 顶部固定：多空温度计(刻度+滑块) + 多/观望/空 计数 + 大分歧(bull VS bear)+ 金句。
  2. 7 流派 `<details>` 可折叠;summary = `▶ 流派 · 人数 · mini多空条 · 偏向`;展开懒渲染成员(紧凑双列:头像+名+sparkline+评分+信号灯)。
  3. 16 指标栏(4 组,红/绿/黄格+动条),含 ★ Kronos 预测/回测胜率。
- **动画策略 ③**：顶部温度计/大分歧常动;成员行/指标格**平时静止,悬停或数据更新才动**;进场逐行错峰点亮。纯 CSS/SVG(无需 ECharts),`prefers-reduced-motion` 关闭动效。
- 复用既有 desktop.html 渲染范式(懒渲染 + 顶层 key 独立可关闭)。

## 10. 回测验证（F4，后续阶段）

把 `panel.consensus` / 各流派信号 / 16 指标信号喂 `scripts/auto_backtest.py`,统计"某派共识 / 某指标"与未来收益相关性 → 校准 `scoring_runtime_config.json` 的 style 权重。**这是 kronos 甩开 UZI 的杀手锏**(UZI 无法验证 51 评委准不准)。

## 11. 分阶段交付

| 阶段 | 内容 | 验收 |
|---|---|---|
| **Phase 1**（首个实现计划） | Tab #13 UI（终端+折叠+③动画）+ `analysis/panel/`（12 手写 + 39 stub）+ 16 指标接既有数据 + 共识/大分歧（**纯规则,无 LLM**,headline/punchline 用模板） | Tab 渲染 51 人分 7 折叠;16 指标有真实数据;共识温度计+大分歧;`test_panel_*` 全绿 |
| **Phase 2** | LLM 覆盖层（P0-A）+ schema 校验 + `kv_repo` 持久化 + 机械质量门（P0-B） | AI 点评输出结构化 JSON;critical 不过则回退规则文案 + 红条（P0-A 覆盖层 ✅；P0-B 质量门 ✅ 完成于 2026-05-30） |
| **Phase 3** | 回测校准（F4）+ 升级 stub 规则 | 回测显示某派/某指标 alpha 显著性 > 阈值 |

## 12. 测试策略

- `tests/test_panel_engine.py`：特征抽取、12 旗舰规则裁决、style 加权、共识/大分歧计算。
- `tests/test_quant_indicators.py`：16 指标的多空归类边界。
- `tests/test_analysis_overlay.py`：schema 校验(缺字段重试/回退)、merge 优先级。
- `tests/test_report_quality.py`：每条 critical 触发 → block(红/绿 TDD)。
- 扩展 `tests/test_stock_analysis_suite.py`：payload 含 `panel`/`analysis_overlay` 且向后兼容。

## 13. 风险与不做的事

| 风险 | 对策 |
|---|---|
| 规则质量误导 | 先 12 手写 + 回测校准;UI 标"规则推断,仅供参考" |
| Token 成本 | LLM 分档,默认纯规则,深度档才调 |
| LLM 幻觉 | P0-B FACTCHECK:每条结论须能在 payload 找出处 |
| 51 行动效过载 | 动画策略 ③ + `prefers-reduced-motion` |
| 维护面膨胀 | 顶层 key 独立可关闭 + 懒渲染 |
| 许可证(UZI=MIT) | 借鉴设计、重写实现;不拷其 `lib/` 业务代码 |

**明确不做**：① 不移植 UZI 数据层/CLI;② 不一次性手写 51;③ 估值/分享卡另立 spec;④ 不引重型渲染依赖。

## 14. 附：可视化决策记录

brainstorm 浏览器伴侣产物(`.superpowers/brainstorm/.../content/`,已 gitignore)：`panel-direction.html`(3 方向→选 C)、`panel-c-detail.html`(单页结构)、`panel-51.html`(51 折叠终稿)、`quant-board.html`(16 指标终稿)。决策:C 终端风格 / 全 51 折叠 / 16 指标 / 动画 ③ / 红多绿空。
