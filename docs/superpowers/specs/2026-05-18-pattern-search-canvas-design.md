# 形态画板搜股功能设计

**日期**: 2026-05-18
**位置**: 投资机会挖掘与批量分析首页 (`/`)
**状态**: 设计已确认，待生成实现计划

## 1. 背景与目标

Kronos 当前首页 (`stock_analysis_home.html`) 提供机会挖掘、批量分析、K线研判等功能。用户希望增加一种"以形找股"的新检索维度：

1. **手绘形态搜股**: 在画板上画一条价格走势曲线，从全 A 股市场找出近 30 日形态最相似的股票
2. **以股找股**: 输入一只股票的代码，找出近 30 日形态与之相似的其他股票

两条流程使用同一套匹配引擎与同一个 Modal 入口。

## 2. 用户决策摘要

| 维度 | 选择 |
|---|---|
| 匹配形态种类 | 收盘价曲线形态（MVP） + K线形态（后续扩展） |
| 股票池 | 全 A 股市场（4500+ 只） |
| 执行模式 | 后台定时预计算指纹库，检索秒级响应 |
| 形态窗口 | 近 30 个交易日 |
| UI 入口 | 首页顶部按钮 → 全屏 Modal |
| 以股找股入口 | Modal 内 Tab 切换 |
| 点击结果行为 | Modal 内部展开对比图（不跳转） |
| 匹配算法 | Pearson 相关 (0.7) + 趋势斜率匹配 (0.3) |
| 存储 | SQLite（替代文件存储） |

## 3. 总体架构

```
┌─────────────────────────────────────────────────────┐
│  前端: stock_analysis_home.html                    │
│    ├─ 顶部状态栏新增「形态搜股」按钮               │
│    └─ 全屏 Modal（左画板 / 右结果列表 + 对比图）   │
└──────────────────────┬──────────────────────────────┘
                       │ POST /api/pattern-search/match
                       ▼
┌─────────────────────────────────────────────────────┐
│  后端: analysis/pattern_matcher.py                  │
│    match(curve_30, top_n, filters)                  │
│    ├─ Pearson 相关  ×0.7                            │
│    └─ 趋势斜率匹配 ×0.3                             │
└──────────────────────┬──────────────────────────────┘
                       │ SQL
                       ▼
┌─────────────────────────────────────────────────────┐
│  存储: data/pattern_fingerprints.db (SQLite)       │
│    每只股票 = 30 点归一化曲线 + 元信息              │
└──────────────────────▲──────────────────────────────┘
                       │ 16:30 写入
                       │
┌──────────────────────┴──────────────────────────────┐
│  Cron/手动: scripts/build_pattern_fingerprints.py  │
│    拉取东财全A 4500 只 × 30 日 OHLCV                │
│    计算指纹 → 写库 (10-15 min)                      │
└─────────────────────────────────────────────────────┘
```

### 3.1 新增/修改文件清单

**新增文件**:
- `analysis/pattern_matcher.py` — 匹配核心引擎（Pearson + slope）
- `scripts/build_pattern_fingerprints.py` — 全市场指纹构建脚本
- `data/pattern_fingerprints.db` — SQLite 数据库（首次运行自动创建）
- `webui/static/pattern-search.js` — 前端 JS（可选，也可内联到模板）
- `tests/test_pattern_matcher.py` — 单元测试

**修改文件**:
- `webui/app.py` — 新增 4 个 API 路由 + 后台刷新任务
- `webui/templates/stock_analysis_home.html` — 顶部按钮 + Modal HTML/CSS/JS

## 4. SQLite Schema

数据库文件: `data/pattern_fingerprints.db`

```sql
-- 指纹主表
CREATE TABLE IF NOT EXISTS pattern_fingerprints (
    stock_code        TEXT PRIMARY KEY,         -- '600977'
    stock_name        TEXT,                     -- '中国电影'
    market            TEXT,                     -- 'SH' | 'SZ' | 'BJ'
    industry          TEXT,                     -- 行业（用于过滤）
    normalized_curve  TEXT NOT NULL,            -- JSON: [0.12, 0.18, ..., 0.95] 30 floats
    mean_slope        REAL NOT NULL,            -- 30 日归一化曲线的线性回归斜率
    latest_close      REAL,                     -- 最新收盘价
    latest_change_pct REAL,                     -- 最新涨跌幅(%)
    snapshot_date     DATE NOT NULL,            -- 指纹基准日
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fp_market   ON pattern_fingerprints(market);
CREATE INDEX IF NOT EXISTS idx_fp_industry ON pattern_fingerprints(industry);
CREATE INDEX IF NOT EXISTS idx_fp_date     ON pattern_fingerprints(snapshot_date);

-- 注：ST/退市股识别依赖 stock_name 是否含 'ST' / '*ST' / '退' 前缀，由查询时 WHERE 过滤，无需独立字段

-- 快照元数据（用于显示"上次刷新时间"、追踪失败）
CREATE TABLE IF NOT EXISTS pattern_snapshot_meta (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   DATE NOT NULL,
    status          TEXT NOT NULL,              -- 'running' | 'success' | 'failed'
    total_stocks    INTEGER,
    succeeded       INTEGER,
    failed          INTEGER,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    error_log       TEXT
);
```

库体积估算: 4500 行 × ~400 字节 ≈ **2 MB**；全表扫描 < 50ms。

## 5. 匹配算法

### 5.1 指纹生成

对每只股票最近 30 个交易日的**收盘价数组** `close[0..29]`:

```
min_p   = min(close)
max_p   = max(close)
norm[i] = (close[i] - min_p) / (max_p - min_p)   # 归一化到 [0, 1]
slope   = linear_regression_slope(x=range(30), y=norm)
```

存储 `norm[]`（JSON）和 `slope`。

**特殊情况**: 若 30 日内 `max_p == min_p`（停牌），跳过该股，不入库。

### 5.2 匹配计算

输入: 用户曲线 `user_curve[30]`（已归一化）

```
user_slope = linear_regression_slope(range(30), user_curve)

for each fingerprint fp in DB:
    pearson_r  = pearson_correlation(user_curve, fp.normalized_curve)
    shape_sim  = max(0, pearson_r)                          # 仅取正相关
    slope_diff = abs(user_slope - fp.mean_slope)
    slope_sim  = max(0, 1 - slope_diff / SLOPE_NORM)        # SLOPE_NORM = 0.05
    score      = 0.7 * shape_sim + 0.3 * slope_sim

return top_n_by(score)
```

`SLOPE_NORM = 0.05` 是经验常数：在 [0,1] 归一化的 30 日曲线上，斜率范围一般在 [-0.05, +0.05]；超过此差异认为方向不同，相似度归零。

**性能**: 4500 只 × (30 维 Pearson + 1 个 slope) ≈ 30 ms（NumPy 向量化）。

### 5.3 用户曲线采样

前端 Canvas 收集鼠标轨迹后，按 x 轴等分 30 区段，每段取该区段内点的 y 均值。若某段无点，按相邻段插值。结果归一化到 [0, 1] 后发给后端。

## 6. API 设计

### 6.1 `GET /api/pattern-search/status`
返回指纹库当前状态。

**响应**:
```json
{
  "available": true,
  "snapshot_date": "2026-05-17",
  "total_stocks": 4502,
  "updated_at": "2026-05-17T16:42:13",
  "staleness_days": 1,
  "warning": null
}
```

### 6.2 `POST /api/pattern-search/match`
执行匹配。

**请求**:
```json
{
  "curve": [0.12, 0.18, 0.22, ..., 0.95],   // 必须 30 个 float, 范围 [0, 1]
  "top_n": 30,
  "filters": {
    "market": ["SH", "SZ"],         // 可选, 默认全市场
    "industry": null,                // 可选行业过滤
    "exclude_st": true               // 默认排除 ST 股
  }
}
```

**响应**:
```json
{
  "matches": [
    {
      "stock_code": "600977",
      "stock_name": "中国电影",
      "industry": "影视娱乐",
      "score": 0.94,
      "shape_sim": 0.96,
      "slope_sim": 0.89,
      "latest_close": 10.85,
      "latest_change_pct": 2.13,
      "normalized_curve": [0.14, 0.19, ..., 0.93]
    }
    // ... up to top_n
  ],
  "snapshot_date": "2026-05-17",
  "compute_ms": 38
}
```

### 6.3 `GET /api/pattern-search/stock-curve/<stock_code>`
用于「选股票形态」Tab 的预填。

**响应**:
```json
{
  "stock_code": "600977",
  "stock_name": "中国电影",
  "normalized_curve": [0.14, 0.19, ..., 0.93],
  "mean_slope": 0.018,
  "snapshot_date": "2026-05-17"
}
```

### 6.4 `POST /api/pattern-search/refresh`
触发后台刷新任务（与现有 opportunity_discovery 任务队列复用）。

**请求**: 空 body
**响应**:
```json
{ "job_id": "fp-refresh-abc123", "status": "queued" }
```

通过现有 `/api/jobs/<job_id>` 端点轮询进度。

## 7. 前端 UI 详细设计

### 7.1 顶部按钮位置

在 `status-row` 的右侧按钮组添加：
```html
<button id="patternSearchBtn" class="button" type="button">
  <span>形态搜股</span>
</button>
```

### 7.2 Modal 布局

```
╔══════════════════════════════════════════════════════════════════╗
║  形态搜股                                          [─] [X 关闭]  ║
║──────────────────────────────────────────────────────────────────║
║  [手绘形态 ▣]  [选股票形态 ▢]      数据基准: 2026-05-17 [刷新]  ║
║──────────────────────────────────────────────────────────────────║
║  ┌─────────────────────────────┐ │ Top 30 相似股票    [筛选 ▼]  ║
║  │                             │ │ ┌──────────────────────────┐ ║
║  │      ╱╲                     │ │ │ 600977 中国电影     0.94│ ║
║  │     ╱  ╲    ___╱╲           │ │ │ 制片业 · ¥10.85 ·+2.13% │ ║
║  │   ╱    ╲__╱   ╱  ╲          │ │ │ ▁▂▃▄▆▇▆▄▃▂▂▃▅▇         │ ║
║  │  ╱             ╲             │ │ ├──────────────────────────┤ ║
║  │                              │ │ │ 000001 平安银行     0.91│ ║
║  │  （HTML5 Canvas 画板）        │ │ │ 银行 · ¥12.30 · -0.8%  │ ║
║  └─────────────────────────────┘ │ │ ▁▃▅▆▇▇▆▅▃▂▂▃▅▆▇         │ ║
║                                  │ ├──────────────────────────┤ ║
║  采样: 30/30 ●●●●●●●●●●●●●●●●● │ │ ...                       │ ║
║  [清空] [撤销] [检索]             │ └──────────────────────────┘ ║
║                                  │                              ║
║  ── 对比图 (点击列表项展开) ──   │                              ║
║  ┌──────────────────────────────┐│                              ║
║  │ 画板  ───  600977 ─ ─  0.94 ││                              ║
║  │     ╱╲ ____                  ││                              ║
║  │  ──╯  ╲╱   ──                ││                              ║
║  └──────────────────────────────┘│  [在首页 K 线查看完整详情 ↗] ║
╚══════════════════════════════════════════════════════════════════╝
```

### 7.3 「选股票形态」Tab

```
股票代码: [600977     ] [载入预览]
预览 30 日走势:
  ▁▂▃▄▆▇▆▄▃▂▂▃▅▇▇▆▄▃▂▁▁▂▃▄▅▆▇▇▆▅
[使用该形态检索]
```

载入后，预览区显示该股 30 点归一化曲线 sparkline。点击「使用该形态检索」即用该曲线作为 query。

### 7.4 Canvas 交互

- 工具栏: 画笔（默认）、橡皮、清空、撤销
- 鼠标按下 → 拖动 → 松开 = 一笔
- 支持多笔续画，自动按 x 排序去重
- 实时显示「采样进度」: 30 个圆点的指示器，已覆盖区段亮起
- 笔迹叠加: 原始笔迹 (浅灰) + 30 点采样折线 (蓝色)

### 7.5 对比图

使用 Plotly.js (已在项目中) 渲染：
- X 轴: 0-29 索引
- Y 轴: 归一化值 [0, 1]
- 两条线: 用户曲线 (实线) + 匹配股票曲线 (虚线)
- 标题: 相似度分数 + 股票名

## 8. 后台刷新任务

### 8.1 触发方式
- **定时**: 每日 16:30 系统 cron 调用 `python scripts/build_pattern_fingerprints.py`
- **手动**: Modal 内的「刷新」按钮调用 `/api/pattern-search/refresh`，复用 `_create_job` / `_run_*_job` 模式

### 8.2 数据源
使用东方财富全市场快照 API（与现有 `_fetch_eastmoney_kline` 同源）：
1. 获取全 A 股代码列表（沪深京）
2. 对每只股票拉取最近 30 个交易日日 K
3. 计算指纹，UPSERT 到 SQLite

**并发**: 30 并发 + 限速（与现有爬虫配置一致），预计 10-15 分钟。

### 8.3 故障保护
- 单股失败不中断整体
- 失败的股票记录到 `pattern_snapshot_meta.error_log`
- 若失败率 > 30%，整体标记 `failed`，保留前一次成功快照
- 库写入采用事务: 全部成功才提交，否则回滚

## 9. 边界条件

| 场景 | 行为 |
|---|---|
| 指纹库不存在/为空 | Modal 顶部红条："首次使用，请等待数据初始化" + 「立即生成」按钮 |
| 指纹库陈旧（>2 天） | 顶部黄条："数据为 X 月 X 日，建议刷新" + 「刷新」按钮 |
| 用户绘制 < 5 个 x 不同点 | 「检索」按钮 disabled + 提示 "请画一条完整曲线" |
| 选股票 Tab，代码不存在 | "未找到该股的指纹数据" |
| 选股票 Tab，代码在指纹库但无法预览 | 走 `/api/pattern-search/stock-curve` 失败兜底 |
| 全表匹配耗时 > 2s | 显示加载动画 |
| 后台刷新失败 | 保留上次有效数据 + 在 Modal 顶部显示警告 |
| ST/退市股票 | 默认 `exclude_st: true`：SQL 中 `stock_name NOT LIKE '%ST%' AND stock_name NOT LIKE '%退%'` |
| 停牌股（30日 close 无波动） | 不入指纹库 |

## 10. 测试策略

### 10.1 单元测试 (`tests/test_pattern_matcher.py`)
- `test_normalize_curve`: 30 点归一化正确性
- `test_pearson_basic`: 已知曲线对 Pearson 计算
- `test_slope_basic`: 已知曲线对斜率计算
- `test_match_top_n`: 给定 fixture DB 与 query，断言 Top-N 顺序
- `test_match_exclude_zero_variance`: 停牌股不返回
- `test_match_filter_market`: market 过滤生效

### 10.2 指纹构建测试
- `test_build_with_mock_data`: 用 5 只股票的 mock OHLCV 数据，断言写库正确
- `test_build_partial_failure`: 模拟 1 只股票拉取失败，断言其他股票正常入库

### 10.3 接口烟测
- `GET /api/pattern-search/status` 返回正确状态
- `POST /api/pattern-search/match` 输入合法/非法 curve 的响应
- `GET /api/pattern-search/stock-curve/<code>` 存在/不存在两种情况
- `POST /api/pattern-search/refresh` 启动后台任务

### 10.4 前端手动烟测
- 顶部按钮打开 Modal
- 手绘曲线 → 看到采样指示器更新 → 点击检索 → 收到 Top-30
- 切换到「选股票形态」Tab → 输入代码 → 看到预览 → 检索
- 点击结果项 → 看到对比图展开
- 「在首页 K 线查看完整详情」跳转正确

## 11. 性能预算

| 操作 | 目标 |
|---|---|
| Modal 打开 | < 100ms |
| 用户绘制 → 采样更新 | 60fps (流畅) |
| 点击检索 → 响应 | < 500ms |
| 选股票预览加载 | < 200ms |
| 后台全量刷新 | 10-15 分钟 |

## 12. MVP 范围与后续扩展

### 12.1 MVP（本次实现）
- 手绘 + 以股找股两种输入
- Pearson + slope 加权匹配
- 30 日窗口
- 顶部 Modal UI
- 每日 16:30 定时刷新 + 手动触发
- SQLite 存储

### 12.2 后续扩展（不在本次范围）
- K 线/技术形态匹配（双底、头肩等模式识别）
- 多窗口选择（30 / 60 / 120 日切换）
- DTW 匹配算法（时间弹性对齐）
- 形态模板库（保存常用画板形态）
- 检索历史记录
- 行业内匹配 / 市值过滤的高级过滤器

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 东财 API 限流导致刷新失败 | 复用现有限速器；支持断点续传 |
| 用户首次访问时指纹库为空 | UI 引导手动触发首次构建；明确提示 |
| Pearson 单一指标过度匹配 | 加入 slope 维度；后续可加波动率 |
| Modal 在小屏幕下挤压 | 媒体查询：< 1280px 时左右栏改为上下堆叠 |
| SQLite 并发写入冲突（刷新 + 查询同时） | 写入使用 WAL 模式；查询无锁 |
