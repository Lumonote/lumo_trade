# 涨停强势形态自动识别 — 设计文档

- 日期：2026-06-20
- 分支：V2.1.1
- 状态：设计待评审

## 1. 背景与目标

用户希望系统能"持续挖掘到牛股 / 后续可能大涨"的强势模型，先落地经典的 **6 种涨停模型**，并在此基础上再深挖几种强势模型；把识别结果展示到**综合分析（个股分析 suite）**与 **K 线图**上，K 线图要能**自动识别多种强势指标（形态）**。

经探查，当前代码：

- 既有「形态搜股」(`analysis/pattern_matcher.py` / `pattern_store.py` / `pattern_backtest.py`) 是**曲线形状指纹匹配**（归一化收盘价 + 皮尔逊相关），**不是**规则化的命名 K 线/量价形态——本需求需要新的**规则检测器**。
- `StockAnalysisSuite._compute_full_payload`（`analysis/stock_analysis_suite.py:360`）已声明 `limit_up_screening` 的 **stub tab**（`stub_tabs`，行 373），但其前端面板 `renderSuiteLimitUpPane`（`webui/static/kronos_desktop_app.js:6456`）只是「量价/主力/筹码/周期」4 因子打分占位，**并非真实形态识别**——本需求正好填这个坑。
- K 线图为 **Plotly**，`renderKlineChart → buildKlineLayout → buildKlineAutoDrawings(records, mode)`（`kronos_desktop_app.js:292`）已经在用 Plotly `shapes/annotations` 自动画支撑/压力/趋势线——这是挂"形态自动标注"的天然钩子。
- 数据齐备：suite 侧 `_load_ohlcv`（df，自动补偿 Eastmoney 日线）、图表侧 `StockKlineService.get_payload`（Sina 日 K，含 `date/open/high/low/close/volume/amount/pct_chg`，最多 500 根）。

**目标范围（已与用户确认）：**

- 运行范围：**个股页为主**。在「个股分析」对当前股票自动识别形态：K 线标注 + 填充「涨停筛选」Tab + 综合总览摘要。检测器写成纯函数，日后可被全市场扫描复用。
- 历史验证：**自带 per-stock 回测胜率**（该股自身历史里该形态命中后的 5/10/20 日前向收益）。

**范围之外（YAGNI）：**

- 全市场扫描排名 → 沿用既有「机会挖掘」的 `limit_up` 任务。
- `webui/templates/stock_analysis_home.html` 旧独立页（`/` 路由，`robyn_app.py:306`）。
- 分钟级/盘中形态；本期只做日线。

## 2. 架构方案

**单一事实源：一个 Python 检测器，两处消费。**

```
analysis/limit_up_patterns.py   ← 纯模块：规则检测 + per-stock 自回测（无 I/O、无网络）
        ▲                                   ▲
        │ df→bars                           │ records→bars
StockAnalysisSuite                   StockKlineService.get_payload
  ._collect_limit_up_patterns()        （为 payload 追加 patterns 字段）
        │                                   │
        ▼                                   ▼
 suite payload:                       /api/stock-kline payload.patterns
   limit_up_screening (真实 section)        │
   overview.strong_patterns (摘要)          ▼
        │                            JS buildPatternAnnotations()
        ▼                            → 并入 buildKlineAutoDrawings 的 shapes/annotations
 JS renderSuiteLimitUpPane / renderSuiteOverview
```

- 规则逻辑只有一份（Python），综合分析与 K 线图都调它；JS 只负责把后端给的 `patterns` 画成箭头/标签，**不复刻规则逻辑**，杜绝 JS/Python 漂移。
- 胜率（前向收益统计）在 Python 计算。
- 备选方案 B（JS 重写检测）/ C（仅 suite 算、图表借 suite 状态）均因"规则双份易漂移 / 任意 K 线拿不到形态"被否决。

## 3. 检测器模块 `analysis/limit_up_patterns.py`

### 3.1 数据契约

输入：归一化日 K（按时间**升序**）的 list[dict]，每项至少含
`date, open, high, low, close, volume`（`amount/pct_chg` 可选，`pct_chg` 缺失时由 `close/prev_close-1` 现算）。

- `bars_from_records(records)`：校验/清洗 `StockKlineService` 记录（已是该结构）。
- `bars_from_dataframe(df)`：把 suite 的 OHLCV df（列 `open/high/low/close/volume`，索引或列含日期）转成上述结构。

**Match（检测输出项）：**

```python
{
  "pattern": "zt_pullback_double_volume",   # 英文键
  "name": "涨停回调倍量冲锋",                  # 中文显示名
  "anchor_date": "2026-06-12",              # 锚点(涨停/关键)bar 日期
  "trigger_date": "2026-06-18",             # 确认/买点 bar 日期（形态完成日）
  "anchor_index": 230,                      # 相对传入 bars 的下标
  "trigger_index": 236,
  "mark_dates": ["2026-06-12", "2026-06-18"],# 需要在图上打标的 bar 日期
  "strength": "强",                          # 强 / 中
  "tone": "danger",                          # danger=最强(红) / warn=中 / info
  "rationale": "涨停后缩量回调3日，今日量能放大1.9倍重新上攻",
  "days_ago": 0                              # trigger 距最新 bar 的交易日数（0=最新一根）
}
```

### 3.2 涨停判定

- `board_limit_pct(code, name=None) -> float`：
  - 科创板 `688/689`、创业板 `300/301` → **20**
  - 北交所 `8/43/83/87/92` → **30**
  - 名称含 `ST`/`*ST`/`退` → **5**
  - 其余主板（`60/000/001/002/003` 等）→ **10**
  - 无 code → 默认 10。
- `is_limit_up(bar, limit_pct) -> bool`：`pct_chg >= limit_pct - 0.5` **且** `close >= high*0.999`（收在最高=封板，覆盖一字板/T 字板，排除炸板）。

### 3.3 内部增强结构 `_enrich(bars, code, name)`

一次性预计算并缓存供各检测器复用（避免每个检测器重算）：
`closes/opens/highs/lows/vols/pct` 数组、`ma5/ma10/ma20/ma60`、`vol_ma5`、`is_zt[]`（逐 bar 涨停标记）、`limit_pct`。

### 3.4 形态注册表与顶层 API

```python
PATTERNS = [PatternDef(key, name, detector, default_tone), ...]   # 10 个

def detect_all(bars, code=None, name=None, *, recent_days=None) -> list[Match]
    # 跑全部检测器；recent_days 给定时只保留 trigger 在最近 recent_days 根内的 match。
    # 排序：先按 days_ago 升序（越新越靠前），再按 strength（强>中）。
    # 同一 trigger_date 同 pattern 去重。

def backtest_pattern_on_history(bars, pattern_key, code=None,
                                horizons=(5,10,20), min_gap_days=5) -> dict
def backtest_all(bars, code=None, horizons=(5,10,20), min_gap_days=5) -> dict
```

每个检测器签名：`detect_<key>(enriched) -> list[Match]`，是**独立、可单测**的小函数。

### 3.5 十种形态规则（常量集中在模块顶部，可调）

> 公共常量（初值，可调）：`PULLBACK_MAX_DAYS=5`、`DOUBLE_VOL_RATIO=1.8`、`SHRINK_VOL_RATIO=0.8`、`HUGE_VOL_RATIO=1.5`（相对 `vol_ma5`）、`LEFT_PEAK_LOOKBACK=60`、`HOLD_MAX_DAYS=6`、`PLATFORM_MIN_DAYS=4`/`PLATFORM_MAX_DAYS=12`/`PLATFORM_RANGE=0.09`、`SHOULDER_MAX_DAYS=6`/`SHOULDER_MAX_DRAWDOWN=0.08`、`RECENT_DAYS=10`（综合分析/总览只取最近触发的为"活跃"）。

**用户给的 6 种：**

1. **涨停回调倍量冲锋** `zt_pullback_double_volume`
   涨停 L(i) → 第 i+1..i+k 日（k∈1..5）缩量回调（`mean(回调量)<SHRINK_VOL_RATIO*vol(L)`、低点不破 L.low 与 MA5）→ 触发日 D：`vol(D) >= DOUBLE_VOL_RATIO*vol(D-1)` 且 `close(D)>open(D)` 且 `close(D)>close(D-1)`。trigger=D，anchor=L。

2. **涨停美人肩** `zt_beauty_shoulder`
   涨停 L → 圆弧回调 m 日（3..6）：累计回撤 ≤ `SHOULDER_MAX_DRAWDOWN`、全程 `close>=MA10`、量能递减、阴线 body 均 <3%（无大阴）、最后一根阳线拐头（`close>close[-1]`）。trigger=拐头日。

3. **涨停高量不破** `zt_high_volume_hold`
   涨停 L 为高量柱（`vol(L) >= HUGE_VOL_RATIO*vol_ma5(L 前)`）→ 之后 2..`HOLD_MAX_DAYS` 日**最低价均不破** `L.low*(1-0.005)`（高量柱守住），且最新仍站 L 开盘上方更强。trigger=最新守住日；强=兼站 L.close 上方。

4. **涨停量过左峰** `zt_volume_over_left_peak`
   涨停 L(i) → 回看 `[i-LEFT_PEAK_LOOKBACK, i-3]` 内最大量（左峰）。`vol(L) > 左峰量` → 命中。trigger=L。

5. **涨停巨量阴反包** `zt_huge_yin_rewrap`
   涨停/强阳 L → 巨量阴线 Y（`close<open`、`vol(Y) >= HUGE_VOL_RATIO*vol_ma5`）→ 1..2 日内阳线 R 反包（`close(R) > open(Y)`，强=`close(R)>high(Y)`，`close(R)>open(R)`）。trigger=R，anchor=Y。

6. **先板后多方炮** `zt_board_then_bull_cannon`
   最近 ~10 日内有涨停板 B → 多方炮三连 [阳, 小阴, 阳]：day1 阳；day2 阴且 body 小、未破 day1 区间（洗盘）；day3 阳且 `close >= day1.close`（收复）。"先板"=B 为 day1 或紧邻其前。trigger=day3。

**再深挖的 4 种（已确认全留）：**

7. **涨停 N 字接力** `zt_n_shape_relay`
   涨停 L → 1..3 日缩量回踩守 MA5 → 突破日：`close > 回调段最高 high` 或再现涨停。N 字（涨-缩量回踩-再涨）。trigger=突破日。（与 P1 区别：P1 看"倍量"，P7 看"破回调高点/再涨停"。）

8. **连板加速** `zt_consecutive_boards`
   连续 ≥2 日涨停（`is_zt[t] and is_zt[t-1]`）。trigger=最新板；strength 随连板数升级（二连=中，三连及以上=强）。

9. **涨停平台突破** `zt_platform_breakout`
   涨停 L → 平台 p 日（4..12）窄幅横盘（`(max-min)/mean(close) <= PLATFORM_RANGE`、守 MA20）→ 突破日 `close>平台最高` 且 `vol >= 1.3*平台均量`。trigger=突破日。

10. **缩量回踩均线企稳** `zt_ma_pullback_hold`
    涨停 L → 缩量回踩至 MA5/MA10 附近（`low <= MA5*1.01` 且量缩）→ 企稳日阳线收回站上该均线（回踩不破）。trigger=企稳日。

> 形态间可能在同一 bar 同时命中（如 P1 与 P7、P3 与 P8）；这是预期行为，全部列出，前端按 tone/strength 去重展示密度，不在检测层强行互斥。

### 3.6 per-stock 自回测

`backtest_pattern_on_history`：在传入的全历史 bars 上滑动，复跑该 pattern 的检测器，对每个历史 trigger 取其后 `h∈horizons` 日的 `close[t+h]/close[t]-1` 前向收益；`min_gap_days` 去重高度重叠命中。汇总：

```python
{ "name": "...",
  "horizons": { "5": {"count","win_rate","avg_return","median","best","worst"},
                "10": {...}, "20": {...} },
  "sample_note": "样本少，仅供参考" | None }   # count<5 → 提示样本少
```

`backtest_all` 对 10 个形态各跑一次（纯本地、~250–500 根、numpy/python，毫秒级，不触网）。

## 4. 接入综合分析（Python，`analysis/stock_analysis_suite.py`）

**detect_all 只算一次**：在 `_collect_inputs` 里基于已加载的 `inputs["ohlcv"]` 补一步
`inputs["lp_matches"] = detect_all(bars_from_dataframe(df), code, recent_days=RECENT_DAYS)`
（try/except 守护，失败置 `[]`），供 overview 摘要与 section 共用，避免重复检测。
（suite 侧通常无股票名 → `board_limit_pct(code, name=None)`，ST 退化为按 code 阈值；可接受。）

- 新增 `_collect_limit_up_patterns(self, code, df, matches) -> dict`：
  - `bars = bars_from_dataframe(df)`；`matches` 取自 `inputs["lp_matches"]`。
  - `stats = backtest_all(bars, code)`。
  - 返回真实 section（取代纯 stub）：

```python
{
  "data_status": "fresh"|"stale"|"unavailable",
  "last_updated": iso, "reason": None,
  "matches": [<match>...],
  "pattern_stats": {pattern_key: <stats>...},
  "summary": {"detected_count": n,
              "best": {"name","win_rate","horizon"} | None }
}
```

> 旧的「量价/主力/筹码/周期」4 因子环境打分**不进 Python section**——它本就派生自 `overview.radar`，由前端 `renderSuiteLimitUpPane` 继续从 `payload.overview.radar` 现算为副块（避免把 radar 线进采集器、避免数据重复）。

- `_compute_full_payload` 把 `limit_up_screening` 从 `stub_tabs` 升级为**真实顶层 key**（仍保留在 tab 列表）；df 缺失/异常 → `_unavailable_section(...)` 降级，**不拖垮其它 Tab**（沿用现有 try/except 模式）。
- `compute_overview` 增加 `overview["strong_patterns"]`（由 `inputs["lp_matches"]` 派生）：

```python
{"items": [{"name","strength","tone","days_ago","best_win_rate"}...],
 "detected_count": n}
```

供「综合总览」顶部摘要展示。

## 5. K 线自动识别标注

### 5.1 后端（`webui/services/kline_service.py`）

`get_payload` 返回前追加 `payload["patterns"]`：
`detect_all(bars_from_records(records), code, name)`（**不**限 recent，覆盖整段返回窗口，按 trigger 排序，**上限 ~12 条**防爆量），每项裁剪为前端所需：
`{pattern, name, date(=trigger_date), anchor_date, mark_dates, strength, tone, rationale, days_ago}`。
全程 try/except → 失败给 `[]`，绝不阻断 K 线本身。计算在 ≤500 根上为本地毫秒级。

### 5.2 前端（`webui/static/kronos_desktop_app.js`）

- 新增 `buildPatternAnnotations(records, patterns, mode)`：对每个 pattern 在其 `mark_dates` 命中的 bar 上：
  - `annotations`：箭头 + 形态短名（如「倍量冲锋」），`tone` 决定颜色（danger 红 / warn 橙 / info 蓝），锚在该 bar 高点上方。
  - 可选 `shapes`：trigger bar 处淡色竖向高亮带。
  - **预览图**(`mode==="preview"`) 仅显示最近最强 **1–2** 个，防拥挤；**弹窗**(`mode==="modal"`) 显示窗口内全部 + 一条图例注记。
- `buildKlineLayout` 把 `buildPatternAnnotations(records, data.patterns, mode)` 的 `shapes/annotations` 与现有 `buildKlineAutoDrawings` 结果**合并**后传给 Plotly。
- `renderSuiteLimitUpPane` 重做：
  - 顶部「综合判定」chip（命中形态数 + 最佳胜率）。
  - **命中形态卡片列表**：形态名、强度、anchor/trigger 日期、rationale、该形态 per-stock 5/10/20 日胜率/均涨 + 样本数（`sample_note` 标注）。
  - 副块保留旧 4 因子环境打分（继续从 `payload.overview.radar` 现算，逻辑不变）。
  - 空态：「近 N 日未识别到强势形态」。
- `renderSuiteOverview` 在总览顶部加「强势形态识别」块：渲染 `overview.strong_patterns.items` 为 chips（强度色 + 最佳胜率），点击跳「涨停筛选」Tab；空态隐藏或「暂无」。

## 6. 测试（TDD）

- `tests/test_limit_up_patterns.py`：
  - 每个检测器一组合成 K 线夹具（正例命中 + 负例不命中），断言 `pattern/anchor/trigger/strength`。
  - 涨停判定按板块阈值（主板/创业板/科创/北交/ST）+ 封板（close≈high）/ 炸板（close<high 不计）。
  - `detect_all` 排序/去重/`recent_days` 过滤。
  - `backtest_pattern_on_history`：构造已知前向收益的序列，断言 `count/win_rate/avg_return` 与 `min_gap` 去重；`count<5` → `sample_note`。
- `tests/test_stock_suite_limit_up.py`：suite section 装配（含真实 key、overview.strong_patterns）、df 缺失降级 `unavailable`、不影响其它 Tab。
- `tests/test_kline_patterns_payload.py`：`get_payload` 含 `patterns`，结构正确，检测失败时为 `[]` 且 K 线仍可用。
- 前端：人工在桌面 App 验证 K 线标注 + 两个面板（与既有「前端需人工验证」约定一致）。

## 7. 文件清单

- 新增：`analysis/limit_up_patterns.py`、`tests/test_limit_up_patterns.py`、`tests/test_stock_suite_limit_up.py`、`tests/test_kline_patterns_payload.py`
- 修改：`analysis/stock_analysis_suite.py`（`_collect_limit_up_patterns` + payload 接线 + overview）、`webui/services/kline_service.py`（payload.patterns）、`webui/static/kronos_desktop_app.js`（`buildPatternAnnotations` + 两个 render 函数）
- 不改：`desktop.html`（tab 与 pane 容器已存在）、路由（接口已存在）。

## 8. 风险与缓解

- **单票样本稀疏**：per-stock 自回测样本天然少 → 显式 `count` + `sample_note`；后续可选离线脚本建"全市场基准胜率"（本期不做）。
- **形态阈值经验性强**：常量集中模块顶部、单测覆盖边界，便于按实盘回测迭代（与既有 scoring 参数迭代风格一致）。
- **K 线标注拥挤**：预览限 1–2 个、弹窗全量 + 上限 12。
- **打包 App 缓存**：改 JS 后桌面 App 可能 WKWebView 缓存旧值（见既有备忘）；`?v=asset_v` 已按 mtime 强缓存，必要时清缓存重开。
