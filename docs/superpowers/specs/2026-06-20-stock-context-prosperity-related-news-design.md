# 个股分析增强：行业/业务景气度 + 关联热点新闻 Tab

- **日期**: 2026-06-20
- **分支**: V2.1.1
- **状态**: 设计已批准，待写实施计划
- **关联记忆**: [[analysis-narrative-inversion-bugs]]、[[star-orbit-map-feature]]、[[sector-pool-empty-proxy]]、[[news-flash-sources-dedup]]

## 1. 背景与目标

个股分析（`StockAnalysisSuite`）现有 18 个 Tab，但存在两个缺口：

1. **缺行业/个股业务景气度的深度分析**：现有"业绩预期(performance)"Tab 仅有 `compute_performance_score`（PE分位/ROE/YoY 三因子合成一个分），既看不到所属**行业景气度**（板块资金/涨跌/PE分位/行业排名/龙头），也看不到**个股业务景气度**（营收/净利 YoY 多期趋势、毛利率/净利率、现金流）。
2. **缺关联热点新闻视图**：没有一个地方汇总"与该股直接/间接相关"的新闻，用户无法快速看到所属板块、产业链同行、题材政策、星轨概念环层面的消息面。

**目标**：
- A. 增强"业绩预期"Tab，加入**行业景气度**与**个股业务景气度**两块纯规则面板。
- B. 新增"关联热点"Tab，按 5 个关联层级展示直接与间接相关新闻，**缓存优先 + 按需刷新**。

**非目标（YAGNI）**：
- 不做 LLM 叙述生成（呈现为纯规则面板；既有"AI 解读"Tab 已覆盖 LLM 场景）。
- 不做实时推送/订阅；刷新为用户主动触发。
- 不改动回测调优的 `opportunity_scorer` / S/A/B/C 分层（本 spec 全在叙述管线 `stock_analysis_suite`，与回测系统是两套，互不影响）。

## 2. 总体架构

```
analysis/stock_context.py        ← 新增·共享: code → {boards, peers, concept_rings, sector_sentiment}
   ├─ Part A: 业绩预期Tab景气度    ← analysis/stock_analysis_suite.py 内纯函数 + performance section 扩展
   └─ Part B: 关联热点Tab
        ├─ analysis/stock_relation_news.py   ← 新增·聚合引擎(注入 collector，纯逻辑)
        ├─ data_store/stock_related_news_repo.py + schema v16   ← 新增·持久化缓存
        ├─ StockAnalysisSuite.related_news section               ← 读缓存
        └─ StockSuiteService.refresh_related_news (后台 worker)  ← 写缓存
```

**复用既有模式**：
- 降级：`_unavailable_section()` / `data_status ∈ {fresh, stale, unavailable}`。
- 后台 worker：与 `StockSuiteService.start_ai_interpretation` 同型（线程 + 状态轮询）。
- DB 缓存：与 `opportunity_hot_news`（schema v15）同型。
- 个股→板块：复用 `analysis/sector_api.py` 既有 `get_stock_boards` / `get_sector_sentiment` / `get_stock_sector_info`。

## 3. 共享地基：`analysis/stock_context.py`

纯逻辑模块，外部依赖通过参数/可注入函数传入，便于测试。

```python
def resolve_relations(code: str, *, boards_fn=None, peers_fn=None, rings_fn=None,
                      sector_fn=None) -> dict:
    """返回该股的多维关联，缺某源时该维度为空列表，不抛异常。
    {
      "boards":        [{"name": "铜箔", "bk": "BK..."} ...],   # 行业/概念板块
      "peers":         [{"code": "...", "name": "...", "reason": "同行|产业链"} ...],
      "concept_rings": [{"ring": "AI产业链", "concepts": [...]} ...],  # 星轨
      "sector_sentiment": {... 来自 get_sector_sentiment ...},
    }
    """
```

- `boards_fn` 默认 `sector_api.get_stock_boards`
- `peers_fn` 默认组合 `FundamentalDataCollector.get_industry_comparison()`（同行）+ `MergerAssociationAnalyzer`（产业链/关联方）
- `rings_fn` 默认 `star_orbit_repo` 查询包含该股板块的概念环
- `sector_fn` 默认 `sector_api.get_sector_sentiment`

任一源异常 → 该维度降级空列表 + 在返回里标注 `degraded` 来源，**绝不影响其它维度**。

## 4. Part A — 业绩预期 Tab 景气度（纯规则）

### 4.1 纯函数（与 `compute_performance_score` 并列，可单测）

```python
def compute_industry_prosperity_score(
    sector_chg_pct: Optional[float],        # 板块当日涨跌%
    sector_moneyflow_net: Optional[float],  # 板块主力净流入(元)
    pe_industry_percentile: Optional[float],# 个股PE在行业内分位(0-100，越低越便宜)
    rank_in_industry_pct: Optional[float],  # 个股在行业内排名分位(0-100，越高越靠前)
) -> Optional[int]:
    """行业景气度 0-100；全 None 返回 None。"""
```
合成（初版权重，可在实现时按数据特性微调，但需在 docstring 注明）：
- 板块涨跌：`clamp(50 + chg*5, 0, 100)` × 0.30
- 板块资金：净流入为正加分、负流出减分（按相对规模归一）× 0.30
- PE 分位：`100 - pe_industry_percentile` × 0.20（越便宜越高）
- 行业排名：`rank_in_industry_pct` × 0.20
- 标签：≥70 高景气 / ≥55 回暖 / ≥40 平淡 / <40 退潮

```python
def compute_business_prosperity_score(
    revenue_yoy_pct: Optional[float],   # 最新营收 YoY%
    profit_yoy_pct: Optional[float],    # 最新净利 YoY%
    gross_margin_trend: Optional[float],# 毛利率环比变化(百分点，正=改善)
    roe_pct: Optional[float],
) -> Optional[int]:
    """个股业务景气度 0-100；全 None 返回 None。"""
```
合成：营收 YoY ×0.30、净利 YoY ×0.35、毛利率趋势 ×0.15、ROE ×0.20；标签：扩张/稳健/承压/恶化。

### 4.2 数据接入与 section 扩展

`_compute_full_payload` 收集 inputs 时新增（失败降级，不阻塞）：
- `get_sector_sentiment(code)` → 板块涨跌/资金/换手
- `FundamentalDataCollector(code).get_industry_comparison()` → 同行 PE/排名/龙头
- `get_financial_reports()` / `get_financial_indicators()` → 营收净利 YoY 多期、毛利率/净利率、ROE、现金流

`_compute_radar` 的 `performance` 维度**向后兼容**扩为：
```python
radar["performance"] = {
    "score": ..., "label": ...,            # 既有，不变
    "industry_prosperity": {
        "score": int|None, "label": str,
        "rows": [{"label":"板块资金净流入","value":...,"tone":...}, ...],
        "data_status": "fresh|unavailable", "reason": ...,
    },
    "business_prosperity": {
        "score": int|None, "label": str,
        "rows": [{"label":"营收YoY","value":...}, {"label":"净利YoY",...}, ...],
        "data_status": ..., "reason": ...,
    },
}
```
无数据时两子块各自 `unavailable`，既有 `score`/`label` 不受影响。

## 5. Part B — 关联热点 Tab

### 5.1 聚合引擎 `analysis/stock_relation_news.py`

```python
RELATION_TIERS = ("direct", "board", "peer", "theme", "orbit")

def collect_related_news(code: str, relations: dict, *,
                         stock_news_fn=None, sector_news_fn=None,
                         hot_news_fn=None, orbit_news_fn=None,
                         per_tier_limit: int = 8) -> list[dict]:
    """返回扁平去重的新闻列表，每条带 tier + relation_reason。"""
```

| tier | 关联理由 | 数据源（默认实现） |
|---|---|---|
| `direct` | 名称/代码命中 | `NewsSentimentCollector(code).get_latest_news()` + `get_latest_announcements()` |
| `board` | 所属板块 | `SectorNewsCollector().get_top_news_by_sectors([board names])` |
| `peer` | 同行/产业链命中 | `SectorNewsCollector` 以 peer 名为 keyword + merger 关联方 |
| `theme` | 板块 keyword 命中题材 | `opportunity_repo.latest_hot_news()` + `global_hot_news_collector` |
| `orbit` | 同概念环 | 星轨环内概念相关事件 |

**新闻 item 统一结构**：
```python
{"title","url","source","published_at","tier","relation_reason","sentiment"}
```
- `content_hash = sha1(normalize(title) | url_host)`
- **去重 + 优先级**：同 hash 只保留最高优先级（direct > board > peer > theme > orbit）。
- 每个数据源异常 → 该 tier 跳过并记 `degraded`，其余 tier 正常返回。

### 5.2 持久化：schema v16 + `stock_related_news_repo.py`

```sql
-- migration 16
CREATE TABLE IF NOT EXISTS stock_related_news (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT NOT NULL,
    tier         TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    source       TEXT,
    published_at TEXT,
    relation_reason TEXT,
    sentiment    TEXT,
    content_hash TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    UNIQUE(code, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_srn_code_fetched ON stock_related_news(code, fetched_at);
```

```python
# data_store/stock_related_news_repo.py
def replace_for_code(code: str, items: list[dict], fetched_at: str) -> int:
    """同事务: 删除该 code 旧记录 → 批量插入新记录。返回写入条数。"""

def latest_for_code(code: str) -> dict:
    """{"items":[...按tier排序...], "fetched_at": str|None}。无记录 fetched_at=None。"""
```
采用"整体替换"（每次刷新覆盖该 code），语义简单、避免陈旧条目堆积。

### 5.3 读路径（Tab 打开，绝不联网）

`StockAnalysisSuite` 新增 section：
```python
def _collect_related_news(self, code) -> dict:
    snap = stock_related_news_repo.latest_for_code(code)
    if not snap["fetched_at"]:
        return {"data_status":"unavailable","reason":"未抓取，点击「刷新关联新闻」","tiers":{},"last_updated":None}
    age = now - parse(snap["fetched_at"])
    status = "fresh" if age < 6h else "stale"
    return {"data_status":status,"last_updated":snap["fetched_at"],
            "tiers":{tier:[items...] for tier in RELATION_TIERS}}
```
并入 `_compute_full_payload` 返回的 `related_news` 字段；加入 `stub_tabs`。

### 5.4 写路径（按需刷新，后台 worker）

`StockSuiteService`（与 `start_ai_interpretation` 同型）：
```python
def refresh_related_news(self, code) -> dict:        # 启动后台线程，立即返回 {"status":"running"}
def get_related_news_status(self, code) -> dict:     # 轮询：running|ready|failed + last_updated
# worker: relations = stock_context.resolve_relations(code)
#         items = stock_relation_news.collect_related_news(code, relations)
#         stock_related_news_repo.replace_for_code(code, items, now); suite.invalidate(code)
```

### 5.5 API（`webui/robyn_app.py`）
- `POST /api/stock-analysis-suite/{code}/related-news/refresh` → `refresh_related_news`
- `GET  /api/stock-analysis-suite/{code}/related-news/status` → `get_related_news_status`
- 读取走既有 `GET /api/stock-analysis-suite/{code}`（payload 已含 `related_news`）。

## 6. 前端（`desktop.html` + `webui/static/kronos_desktop_app.js`）

- `#stockSuiteTabs` 增 `<button data-suite-tab="related_news">关联热点</button>`。
- 面板渲染（`kronos_desktop_app.js`，注意改的是 .js 不是内联）：
  - 顶部："最后更新 {last_updated}" + 「刷新关联新闻」按钮（点击 → refresh 接口 → 轮询 status → 完成重载 suite）。
  - 5 个层级分区，每区新闻卡片：层级徽章 + 标题(链接) + 来源 + 时间 + 关联理由 + 情绪配色；空区显示"暂无"。
  - `data_status=unavailable` 显示引导刷新；`stale` 显示陈旧提示。
- "业绩预期"面板：既有雷达卡下方追加"行业景气度""个股业务景气度"两张明细表（评分+标签+rows）。

## 7. 错误处理与降级

- 每个数据源独立 try/except，单源失败仅令对应 tier/子块降级，不影响整页。
- 刷新 worker 全失败 → status `failed` + reason；前端提示可重试，旧缓存仍可读。
- 代理/串行规避：读路径零联网；写路径在后台线程，沿用 `sector_api`/collector 既有的 `trust_env`/重试加固。

## 8. 测试计划（TDD）

| 测试 | 覆盖 |
|---|---|
| `test_industry_prosperity_score` | 边界、None 降级、标签分档 |
| `test_business_prosperity_score` | 同上 |
| `test_resolve_relations` | 注入 fn 组装 boards/peers/rings；单源异常降级空 |
| `test_collect_related_news` | 注入 collector → 5 层分类、去重、优先级保留最高 tier、单源失败跳过 |
| `test_stock_related_news_repo` | replace_for_code 幂等覆盖、latest_for_code 排序、无记录 fetched_at=None |
| `test_schema_migration_v16` | `migrate()==16`、表与索引存在 |
| `test_suite_related_news_section` | 空→unavailable；有缓存→fresh/stale 按 fetched_at |
| `test_performance_prosperity_blocks` | performance section 含两子块、无数据降级、既有 score 不变 |

## 9. 分阶段实施

- **P0**：`stock_context.resolve_relations` + 测试（共享地基）。
- **P1**：Part A — 两个纯函数 + performance section 扩展 + 前端明细表 + 测试。
- **P2**：Part B — `stock_relation_news` 引擎 + schema v16 + repo + suite section + service worker + API + 前端 Tab + 测试。

合为一个 spec，实施计划内按 P0→P1→P2 推进，每阶段独立可测、互不阻塞。
