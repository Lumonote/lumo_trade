# 个股分析增强：行业/业务景气度 + 关联热点新闻 Tab — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给个股分析"业绩预期"Tab 加入行业景气度+个股业务景气度两块纯规则面板，并新增"关联热点"Tab 展示 5 层关联新闻（缓存优先+按需刷新）。

**Architecture:** 新增共享纯模块 `stock_context.resolve_relations` 解析个股→板块/同行/概念环；Part A 在 `stock_analysis_suite` 内加两个纯评分函数并扩展 performance section；Part B 新增聚合引擎 + schema v16 持久化 + suite 读缓存 section + service 后台 worker + API + 前端 Tab。

**Tech Stack:** Python 3.13（`.venv`）、pytest、SQLite（`data_store/schema.py` migrations）、Robyn（`webui/robyn_app.py`）、原生 JS（`webui/static/kronos_desktop_app.js`）。

## Global Constraints

- **绝不执行任何 git 操作**：本计划所有"检查点"均不含 git 命令。提交与否由用户自行决定（可用 `! git ...`）。实现者/子代理同样禁止 git 写操作。
- 测试命令一律用 venv：`.venv/bin/python -m pytest ...`。
- 设计依据：`docs/superpowers/specs/2026-06-20-stock-context-prosperity-related-news-design.md`。
- 降级约定：复用 `analysis/stock_analysis_suite.py` 的 `_unavailable_section()` 与 `data_status ∈ {fresh, stale, unavailable}`；单源失败只降级对应块，不影响整页。
- 数值清洗：基本面字段可能为 `'N/A'`/字符串，统一用 `_safe_float`/`_to_optional_float` 强制转换，禁止把字符串喂进比较运算。
- 本 spec 全在叙述管线 `stock_analysis_suite`，**不得改动** `analysis/opportunity_scorer.py` 或回测 S/A/B/C 分层逻辑。
- 关联新闻读路径**零联网**；联网仅发生在后台刷新 worker。
- schema 当前头部为 v15，新增迁移为 v16。
- 改桌面交互逻辑改 `webui/static/kronos_desktop_app.js`（非 `desktop.html` 内联脚本）。

---

## Task 1 (P0): 共享关联解析器 `stock_context.resolve_relations`

**Files:**
- Create: `analysis/stock_context.py`
- Test: `tests/test_stock_context.py`

**Interfaces:**
- Produces:
  - `resolve_relations(code: str, *, boards_fn=None, peers_fn=None, rings_fn=None, sector_fn=None) -> dict`
    返回 `{"boards": list[dict], "peers": list[dict], "concept_rings": list[dict], "sector_sentiment": dict, "degraded": list[str]}`
  - `_safe_float(v) -> float | None`（吸收 `'N/A'`/None/空串）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_stock_context.py
from analysis.stock_context import resolve_relations, _safe_float


def test_safe_float_coerces_na_and_strings():
    assert _safe_float("N/A") is None
    assert _safe_float(None) is None
    assert _safe_float("") is None
    assert _safe_float("12.5") == 12.5
    assert _safe_float(3) == 3.0


def test_resolve_relations_assembles_all_dimensions():
    rel = resolve_relations(
        "601702",
        boards_fn=lambda code: [{"name": "铜箔", "bk": "BK1"}, {"name": "PCB", "bk": "BK2"}],
        peers_fn=lambda code: [{"code": "002171", "name": "楚江新材", "reason": "同行"}],
        rings_fn=lambda boards: [{"ring": "AI产业链", "concepts": ["铜箔"]}],
        sector_fn=lambda code: {"sentiment_score": 61.0, "change_pct": 2.3},
    )
    assert [b["name"] for b in rel["boards"]] == ["铜箔", "PCB"]
    assert rel["peers"][0]["name"] == "楚江新材"
    assert rel["concept_rings"][0]["ring"] == "AI产业链"
    assert rel["sector_sentiment"]["sentiment_score"] == 61.0
    assert rel["degraded"] == []


def test_resolve_relations_degrades_failing_source_only():
    def boom(*a, **k):
        raise RuntimeError("net down")

    rel = resolve_relations(
        "601702",
        boards_fn=lambda code: [{"name": "铜箔", "bk": "BK1"}],
        peers_fn=boom,                      # 同行源失败
        rings_fn=lambda boards: [],
        sector_fn=lambda code: {"sentiment_score": 50.0},
    )
    assert rel["boards"][0]["name"] == "铜箔"   # 其它维度正常
    assert rel["peers"] == []                   # 失败维度降级空
    assert "peers" in rel["degraded"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_stock_context.py -v`
Expected: FAIL（`No module named 'analysis.stock_context'`）

- [ ] **Step 3: 写最小实现**

```python
# analysis/stock_context.py
"""个股关联解析器：code → 板块 / 同行 / 概念环 / 板块情绪。

纯逻辑：所有外部数据源通过可注入函数传入，默认实现在 service 层接线，
便于单测。任一源异常只降级该维度，绝不影响其它维度。
"""
from __future__ import annotations

from typing import Any, Callable, Optional


def _safe_float(v: Any) -> Optional[float]:
    """把 'N/A'/None/空串/非数字字符串安全转 float；失败返回 None。"""
    if v is None:
        return None
    try:
        s = str(v).strip()
        if not s or s.upper() == "N/A":
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def resolve_relations(
    code: str,
    *,
    boards_fn: Optional[Callable[[str], list]] = None,
    peers_fn: Optional[Callable[[str], list]] = None,
    rings_fn: Optional[Callable[[list], list]] = None,
    sector_fn: Optional[Callable[[str], dict]] = None,
) -> dict:
    degraded: list[str] = []

    def _try(name: str, fn, *args, default):
        if fn is None:
            return default
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001
            degraded.append(name)
            return default

    boards = _try("boards", boards_fn, code, default=[]) or []
    peers = _try("peers", peers_fn, code, default=[]) or []
    rings = _try("concept_rings", rings_fn, boards, default=[]) or []
    sector = _try("sector_sentiment", sector_fn, code, default={}) or {}

    return {
        "boards": boards,
        "peers": peers,
        "concept_rings": rings,
        "sector_sentiment": sector,
        "degraded": degraded,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_stock_context.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 检查点** — P0 完成。**不要执行 git**；提交由用户决定。

---

## Task 2 (P1): 景气度纯评分函数

**Files:**
- Modify: `analysis/stock_analysis_suite.py`（在 `compute_performance_score` 之后，约 117 行处新增两个函数）
- Test: `tests/test_prosperity_scores.py`

**Interfaces:**
- Consumes: 无（纯函数）
- Produces:
  - `compute_industry_prosperity_score(sector_chg_pct, sector_moneyflow_net, pe_industry_percentile, rank_in_industry_pct) -> int | None`
  - `compute_business_prosperity_score(revenue_yoy_pct, profit_yoy_pct, gross_margin_trend, roe_pct) -> int | None`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_prosperity_scores.py
from analysis.stock_analysis_suite import (
    compute_industry_prosperity_score,
    compute_business_prosperity_score,
)


def test_industry_prosperity_all_none_returns_none():
    assert compute_industry_prosperity_score(None, None, None, None) is None


def test_industry_prosperity_high_when_strong_sector():
    # 板块+3%、资金净流入、PE便宜(分位20)、行业排名靠前(80)
    s = compute_industry_prosperity_score(3.0, 5.0e8, 20.0, 80.0)
    assert s is not None and s >= 70


def test_industry_prosperity_low_when_weak_sector():
    s = compute_industry_prosperity_score(-4.0, -3.0e8, 90.0, 10.0)
    assert s is not None and s < 40


def test_business_prosperity_all_none_returns_none():
    assert compute_business_prosperity_score(None, None, None, None) is None


def test_business_prosperity_expansion_high():
    # 营收+40% 净利+60% 毛利率改善+2pct ROE 18
    s = compute_business_prosperity_score(40.0, 60.0, 2.0, 18.0)
    assert s is not None and s >= 75


def test_business_prosperity_deterioration_low():
    s = compute_business_prosperity_score(-20.0, -50.0, -3.0, 2.0)
    assert s is not None and s < 35
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_prosperity_scores.py -v`
Expected: FAIL（`ImportError: cannot import name 'compute_industry_prosperity_score'`）

- [ ] **Step 3: 写最小实现**（插入到 `analysis/stock_analysis_suite.py` 第 117 行 `compute_performance_score` 之后）

```python
def compute_industry_prosperity_score(
    sector_chg_pct: "float | None",
    sector_moneyflow_net: "float | None",
    pe_industry_percentile: "float | None",
    rank_in_industry_pct: "float | None",
) -> "int | None":
    """行业景气度 0-100；全 None 返回 None。
    板块涨跌 0.30 + 板块资金 0.30 + PE便宜度 0.20 + 行业排名 0.20。"""
    if all(v is None for v in (sector_chg_pct, sector_moneyflow_net,
                               pe_industry_percentile, rank_in_industry_pct)):
        return None
    chg_score = max(0.0, min(100.0, 50.0 + (sector_chg_pct or 0.0) * 5.0))
    # 资金：±3 亿映射到 ±50 分，封顶
    mf = (sector_moneyflow_net or 0.0) / 3.0e8
    mf_score = max(0.0, min(100.0, 50.0 + mf * 50.0))
    pe_score = (100.0 - pe_industry_percentile) if pe_industry_percentile is not None else 50.0
    rank_score = rank_in_industry_pct if rank_in_industry_pct is not None else 50.0
    score = chg_score * 0.30 + mf_score * 0.30 + pe_score * 0.20 + rank_score * 0.20
    return int(round(max(0.0, min(100.0, score))))


def compute_business_prosperity_score(
    revenue_yoy_pct: "float | None",
    profit_yoy_pct: "float | None",
    gross_margin_trend: "float | None",
    roe_pct: "float | None",
) -> "int | None":
    """个股业务景气度 0-100；全 None 返回 None。
    营收YoY 0.30 + 净利YoY 0.35 + 毛利率趋势 0.15 + ROE 0.20。"""
    if all(v is None for v in (revenue_yoy_pct, profit_yoy_pct,
                               gross_margin_trend, roe_pct)):
        return None

    def _yoy(v):  # -50%→0, 0%→50, +50%→100
        if v is None:
            return 50.0
        return max(0.0, min(100.0, 50.0 + v))

    rev_score = _yoy(revenue_yoy_pct)
    profit_score = _yoy(profit_yoy_pct)
    # 毛利率趋势：±5pct 映射 ±50
    gm = gross_margin_trend
    gm_score = 50.0 if gm is None else max(0.0, min(100.0, 50.0 + gm * 10.0))
    if roe_pct is None:
        roe_score = 50.0
    elif roe_pct >= 15:
        roe_score = 100.0
    elif roe_pct <= 0:
        roe_score = 0.0
    else:
        roe_score = roe_pct / 15.0 * 100.0
    score = rev_score * 0.30 + profit_score * 0.35 + gm_score * 0.15 + roe_score * 0.20
    return int(round(max(0.0, min(100.0, score))))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_prosperity_scores.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 检查点** — 纯函数完成。不要执行 git。

---

## Task 3 (P1): 接入数据 + 扩展 performance section 两子块

**Files:**
- Modify: `analysis/stock_analysis_suite.py`
  - `_collect_inputs`（约 649-663 行）：扩 `out["fundamental"]` 字段 + 新增 `out["sector"]`
  - `_compute_radar` 的 performance 块（约 585-606 行）：加 `industry_prosperity` / `business_prosperity` 子块
  - 新增静态标签方法 `_label_prosperity`
- Test: `tests/test_stock_analysis_suite.py`（追加用例）

**Interfaces:**
- Consumes: Task 2 的 `compute_industry_prosperity_score` / `compute_business_prosperity_score`；`stock_context._safe_float`
- Produces: `radar["performance"]["industry_prosperity"]` 与 `["business_prosperity"]`，结构
  `{"score": int|None, "label": str, "rows": list[{"label","value","tone"}], "data_status": str, "reason": str|None}`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_stock_analysis_suite.py` 末尾）

```python
def test_performance_section_has_prosperity_blocks():
    suite = StockAnalysisSuite()
    radar = suite._compute_radar({
        "fundamental": {
            "pe": 25.0, "roe": 16.0, "pe_industry_rank": 30.0,
            "net_profit_yoy": 40.0, "revenue_yoy": 30.0, "gross_margin": 22.0,
            "gross_margin_prev": 20.0, "industry_rank_pct": 75.0,
        },
        "sector": {"change_pct": 2.5, "moneyflow_net": 4.0e8},
    })
    perf = radar["performance"]
    assert "industry_prosperity" in perf and "business_prosperity" in perf
    assert perf["industry_prosperity"]["score"] is not None
    assert perf["business_prosperity"]["score"] is not None
    assert any(r["label"] == "营收YoY" for r in perf["business_prosperity"]["rows"])


def test_performance_prosperity_degrades_without_data():
    suite = StockAnalysisSuite()
    radar = suite._compute_radar({})   # 空 inputs
    perf = radar["performance"]
    # 既有 performance 仍降级 _missing，且不报错
    assert perf.get("data_status") in ("unavailable", None) or "score" in perf
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_stock_analysis_suite.py::test_performance_section_has_prosperity_blocks -v`
Expected: FAIL（`KeyError: 'industry_prosperity'`）

- [ ] **Step 3a: 扩展 `_collect_inputs`** — 把 `out["fundamental"]` 块（约 654-660 行）替换为：

```python
            out["fundamental"] = {
                "pe": fi.get("pe"),
                "pb": fi.get("pb"),
                "roe": fi.get("roe"),
                "pe_industry_rank": ic.get("pe_rank"),
                "net_profit_yoy": fr.get("net_profit_yoy"),
                "revenue_yoy": fr.get("revenue_yoy"),
                "gross_margin": fr.get("gross_margin"),
                "gross_margin_prev": fr.get("gross_margin_prev"),
                "industry_rank_pct": ic.get("industry_rank"),
            }
```

紧接 `self._augment_fundamental_from_local(code, out)` 之前，新增板块情绪采集（失败降级）：

```python
        try:
            from analysis.sector_api import get_sector_sentiment
            sec = get_sector_sentiment(code) or {}
            out["sector"] = {
                "change_pct": sec.get("change_pct") or sec.get("avg_change_pct"),
                "moneyflow_net": sec.get("moneyflow_net") or sec.get("main_net_inflow"),
                "sentiment_score": sec.get("sentiment_score"),
                "sector_name": sec.get("sector_name"),
            }
        except Exception as exc:  # noqa: BLE001
            out["sector_error"] = str(exc)
```

- [ ] **Step 3b: 扩展 performance 块** — 在 `_compute_radar` 中，把 `radar["performance"] = {...}`（约 600-604 行的成功分支）改为先构造 base，再附加两子块。将第 597-604 行替换为：

```python
            else:
                pe = _to_optional_float(fundam.get("pe"))
                reason = f"PE {pe}，ROE {roe}%" if pe is not None and roe is not None else "基本面"
                radar["performance"] = {
                    "score": score,
                    "label": self._label_perf(score),
                    "reason": reason,
                    "industry_prosperity": self._build_industry_prosperity(inputs),
                    "business_prosperity": self._build_business_prosperity(fundam),
                }
```

- [ ] **Step 3c: 新增三个 helper 方法**（加到类内，`_label_perf` 附近）：

```python
    @staticmethod
    def _label_prosperity(score: "int | None") -> str:
        if score is None:
            return "—"
        if score >= 70: return "高景气"
        if score >= 55: return "回暖"
        if score >= 40: return "平淡"
        return "退潮"

    def _build_industry_prosperity(self, inputs: dict) -> dict:
        from analysis.stock_context import _safe_float
        fundam = inputs.get("fundamental") or {}
        sector = inputs.get("sector") or {}
        chg = _safe_float(sector.get("change_pct"))
        mf = _safe_float(sector.get("moneyflow_net"))
        pe_pct = _safe_float(fundam.get("pe_industry_rank"))
        rank = _safe_float(fundam.get("industry_rank_pct"))
        score = compute_industry_prosperity_score(chg, mf, pe_pct, rank)
        if score is None:
            return _unavailable_section("行业景气度：无板块/行业数据")
        return {
            "score": score,
            "label": self._label_prosperity(score),
            "data_status": "fresh",
            "reason": None,
            "rows": [
                {"label": "板块涨跌", "value": f"{chg}%" if chg is not None else "—", "tone": "info"},
                {"label": "板块资金净流入", "value": f"{mf/1e8:.2f}亿" if mf is not None else "—",
                 "tone": "danger" if (mf is not None and mf < 0) else "info"},
                {"label": "PE行业分位", "value": f"{pe_pct:.0f}%" if pe_pct is not None else "—", "tone": "neutral"},
                {"label": "行业内排名分位", "value": f"{rank:.0f}%" if rank is not None else "—", "tone": "neutral"},
            ],
        }

    def _build_business_prosperity(self, fundam: dict) -> dict:
        from analysis.stock_context import _safe_float
        rev = _safe_float(fundam.get("revenue_yoy"))
        prof = _safe_float(fundam.get("net_profit_yoy"))
        gm = _safe_float(fundam.get("gross_margin"))
        gm_prev = _safe_float(fundam.get("gross_margin_prev"))
        gm_trend = (gm - gm_prev) if (gm is not None and gm_prev is not None) else None
        roe = _safe_float(fundam.get("roe"))
        score = compute_business_prosperity_score(rev, prof, gm_trend, roe)
        if score is None:
            return _unavailable_section("业务景气度：无财报数据")
        return {
            "score": score,
            "label": self._label_prosperity(score),
            "data_status": "fresh",
            "reason": None,
            "rows": [
                {"label": "营收YoY", "value": f"{rev}%" if rev is not None else "—",
                 "tone": "danger" if (rev is not None and rev < 0) else "info"},
                {"label": "净利YoY", "value": f"{prof}%" if prof is not None else "—",
                 "tone": "danger" if (prof is not None and prof < 0) else "info"},
                {"label": "毛利率", "value": f"{gm}%" if gm is not None else "—", "tone": "neutral"},
                {"label": "ROE", "value": f"{roe}%" if roe is not None else "—", "tone": "neutral"},
            ],
        }
```

- [ ] **Step 4: 运行测试确认通过 + 回归**

Run: `.venv/bin/python -m pytest tests/test_stock_analysis_suite.py tests/test_prosperity_scores.py -v`
Expected: PASS（含新增 2 例与既有全部）

- [ ] **Step 5: 检查点** — Part A 后端完成。不要执行 git。

---

## Task 4 (P1): 前端 — performance 面板渲染景气度两块

**Files:**
- Modify: `webui/static/kronos_desktop_app.js`（performance/业绩预期 面板渲染处）
- Verify: 手动（浏览器/桌面 App）

**Interfaces:**
- Consumes: `payload.overview.radar.performance.industry_prosperity` / `.business_prosperity`

- [ ] **Step 1: 定位渲染函数**

Run: `grep -n "performance\|业绩预期\|radar" webui/static/kronos_desktop_app.js | head`
找到渲染 performance 雷达卡的函数（记为 `renderPerformance` 或 suite 面板分发处）。

- [ ] **Step 2: 加入景气度两块渲染**（在 performance 面板既有内容后追加）

```javascript
function renderProsperityBlock(title, blk) {
  if (!blk || blk.data_status === "unavailable") {
    return `<div class="prosperity-block"><h4>${title}</h4>
            <p class="muted">${(blk && blk.reason) || "暂无数据"}</p></div>`;
  }
  const rows = (blk.rows || []).map(r =>
    `<tr><td>${r.label}</td><td class="tone-${r.tone || "info"}">${r.value}</td></tr>`
  ).join("");
  return `<div class="prosperity-block">
    <h4>${title} <span class="score-pill">${blk.score} · ${blk.label}</span></h4>
    <table class="prosperity-table"><tbody>${rows}</tbody></table></div>`;
}
// 在 performance 面板 HTML 拼接处追加：
//   const perf = payload.overview.radar.performance || {};
//   html += renderProsperityBlock("行业景气度", perf.industry_prosperity);
//   html += renderProsperityBlock("个股业务景气度", perf.business_prosperity);
```

- [ ] **Step 3: 加样式**（`webui/static/kronos_desktop.css` 追加）

```css
.prosperity-block { margin-top: 12px; }
.prosperity-block .score-pill { font-size: 12px; padding: 2px 8px; border-radius: 10px; background: rgba(120,160,255,.15); }
.prosperity-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.prosperity-table td { padding: 4px 8px; border-bottom: 1px solid rgba(255,255,255,.06); }
.prosperity-table .tone-danger { color: #ff6b6b; }
```

- [ ] **Step 4: 手动验证**

启动 webui（参考 CLAUDE.md），打开任一个股分析 → 业绩预期 Tab，确认出现"行业景气度""个股业务景气度"两块及评分。注意 WKWebView 缓存（必要时清缓存/改 `?v=`）。

- [ ] **Step 5: 检查点** — Part A 完成。不要执行 git。

---

## Task 5 (P2): schema v16 + `stock_related_news_repo`

**Files:**
- Modify: `data_store/schema.py`（`_MIGRATIONS` 追加 v16 元组）
- Create: `data_store/stock_related_news_repo.py`
- Test: `tests/test_schema_migration_v16.py`、`tests/test_stock_related_news_repo.py`

**Interfaces:**
- Produces:
  - `replace_for_code(code: str, items: list[dict], fetched_at: str) -> int`
  - `latest_for_code(code: str) -> dict`，返回 `{"items": list[dict], "fetched_at": str|None}`

- [ ] **Step 1: 写迁移测试**

```python
# tests/test_schema_migration_v16.py
"""验证 migration 16 建 stock_related_news 表。"""
import sqlite3
import pytest
from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    migrate(c)
    yield c
    c.close()


def test_migrate_reaches_v16(conn):
    assert migrate(conn) == 16


def test_stock_related_news_table_exists(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(stock_related_news)")}
    assert {"code", "tier", "title", "content_hash", "fetched_at"} <= cols
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_schema_migration_v16.py -v`
Expected: FAIL（`assert 15 == 16`）

- [ ] **Step 3: 追加 v16 迁移** — 在 `data_store/schema.py` 的 `_MIGRATIONS` 列表末尾（v15 元组之后）追加：

```python
    (
        16,
        """
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
        CREATE INDEX IF NOT EXISTS idx_srn_code_fetched
          ON stock_related_news(code, fetched_at);
        """,
    ),
```

- [ ] **Step 4: 运行迁移测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_schema_migration_v16.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 写 repo 测试**

```python
# tests/test_stock_related_news_repo.py
import sqlite3
import pytest
from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "t.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)
    from data_store import connection, stock_related_news_repo
    monkeypatch.setattr(connection, "get_conn", lambda: c)
    monkeypatch.setattr(stock_related_news_repo, "get_conn", lambda: c)
    yield c
    c.close()


def _item(h, tier="direct"):
    return {"tier": tier, "title": f"t{h}", "url": f"http://x/{h}", "source": "金十",
            "published_at": "2026-06-20T10:00:00", "relation_reason": "名称命中",
            "sentiment": "neutral", "content_hash": h}


def test_replace_is_idempotent_and_overwrites(conn):
    from data_store import stock_related_news_repo as repo
    assert repo.replace_for_code("601702", [_item("a"), _item("b")], "2026-06-20T10:00:00") == 2
    # 再次替换为单条 → 旧的被清掉
    assert repo.replace_for_code("601702", [_item("c")], "2026-06-20T11:00:00") == 1
    snap = repo.latest_for_code("601702")
    assert snap["fetched_at"] == "2026-06-20T11:00:00"
    assert [i["content_hash"] for i in snap["items"]] == ["c"]


def test_latest_for_unknown_code_returns_empty(conn):
    from data_store import stock_related_news_repo as repo
    snap = repo.latest_for_code("000000")
    assert snap == {"items": [], "fetched_at": None}
```

- [ ] **Step 6: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_stock_related_news_repo.py -v`
Expected: FAIL（`No module named 'data_store.stock_related_news_repo'`）

- [ ] **Step 7: 写 repo 实现**（参照 `data_store/opportunity_repo.py` 的 `get_conn` 用法）

```python
# data_store/stock_related_news_repo.py
"""个股关联新闻缓存：每次刷新整体替换该 code 的记录（缓存优先+按需刷新）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from data_store.connection import get_conn

_TIER_ORDER = {"direct": 0, "board": 1, "peer": 2, "theme": 3, "orbit": 4}


def replace_for_code(code: str, items: List[Dict[str, Any]], fetched_at: str) -> int:
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM stock_related_news WHERE code=?", (code,))
        n = 0
        for it in items:
            conn.execute(
                """INSERT OR IGNORE INTO stock_related_news
                   (code, tier, title, url, source, published_at,
                    relation_reason, sentiment, content_hash, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (code, it.get("tier"), it.get("title"), it.get("url"),
                 it.get("source"), it.get("published_at"), it.get("relation_reason"),
                 it.get("sentiment"), it.get("content_hash"), fetched_at),
            )
            n += 1
        conn.execute("COMMIT")
        return n
    except Exception:
        conn.execute("ROLLBACK")
        raise


def latest_for_code(code: str) -> Dict[str, Any]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM stock_related_news WHERE code=? ", (code,)
    ).fetchall()
    if not rows:
        return {"items": [], "fetched_at": None}
    items = [dict(r) for r in rows]
    items.sort(key=lambda r: _TIER_ORDER.get(r.get("tier"), 9))
    return {"items": items, "fetched_at": items[0].get("fetched_at")}
```

- [ ] **Step 8: 运行 repo 测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_stock_related_news_repo.py -v`
Expected: PASS（2 passed）

- [ ] **Step 9: 检查点** — 持久化层完成。不要执行 git。

---

## Task 6 (P2): 关联新闻聚合引擎 `stock_relation_news.py`

**Files:**
- Create: `analysis/stock_relation_news.py`
- Test: `tests/test_stock_relation_news.py`

**Interfaces:**
- Consumes: Task 1 的 `resolve_relations` 输出结构
- Produces:
  - `RELATION_TIERS = ("direct", "board", "peer", "theme", "orbit")`
  - `content_hash(title, url) -> str`
  - `collect_related_news(code, relations, *, stock_news_fn=None, sector_news_fn=None, hot_news_fn=None, orbit_news_fn=None, per_tier_limit=8) -> list[dict]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_stock_relation_news.py
from analysis.stock_relation_news import collect_related_news, content_hash, RELATION_TIERS


def test_content_hash_stable_and_host_based():
    h1 = content_hash("某股大涨", "http://a.com/1")
    h2 = content_hash("某股大涨 ", "http://a.com/2")  # 同标题同host → 同hash
    assert h1 == h2


def test_collect_classifies_and_dedups_by_priority():
    relations = {
        "boards": [{"name": "铜箔"}],
        "peers": [{"name": "楚江新材", "reason": "同行"}],
        "concept_rings": [{"ring": "AI产业链", "concepts": ["铜箔"]}],
    }
    dup = {"title": "铜箔涨价", "url": "http://x.com/1", "source": "东财",
           "published_at": "2026-06-20"}
    items = collect_related_news(
        "601702", relations,
        stock_news_fn=lambda code: [dict(dup)],                     # direct
        sector_news_fn=lambda names: [dict(dup)],                   # board（与 direct 重复）
        hot_news_fn=lambda boards: [{"title": "政策利好新能源", "url": "http://y/2",
                                      "source": "金十", "published_at": "2026-06-20"}],
        orbit_news_fn=lambda rings: [],
    )
    by_hash = {}
    for it in items:
        by_hash.setdefault(content_hash(it["title"], it["url"]), it)
    # 重复新闻只保留最高优先级 direct
    dup_item = by_hash[content_hash(dup["title"], dup["url"])]
    assert dup_item["tier"] == "direct"
    assert any(it["tier"] == "theme" for it in items)
    assert all(it["tier"] in RELATION_TIERS for it in items)


def test_collect_skips_failing_source():
    def boom(*a, **k):
        raise RuntimeError("net")
    items = collect_related_news(
        "601702", {"boards": [{"name": "铜箔"}], "peers": [], "concept_rings": []},
        stock_news_fn=boom,                                  # direct 源挂
        sector_news_fn=lambda names: [{"title": "板块新闻", "url": "http://z/9",
                                       "source": "同花顺", "published_at": "2026-06-20"}],
        hot_news_fn=lambda boards: [], orbit_news_fn=lambda rings: [],
    )
    assert [it["tier"] for it in items] == ["board"]   # direct 跳过，board 正常
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_stock_relation_news.py -v`
Expected: FAIL（`No module named 'analysis.stock_relation_news'`）

- [ ] **Step 3: 写实现**

```python
# analysis/stock_relation_news.py
"""关联新闻聚合：5 层(直接/板块/同行/题材/星轨)，去重保留最高优先级层。"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse
from typing import Any, Callable, Dict, List, Optional

RELATION_TIERS = ("direct", "board", "peer", "theme", "orbit")
_TIER_RANK = {t: i for i, t in enumerate(RELATION_TIERS)}


def content_hash(title: str, url: str) -> str:
    t = re.sub(r"\s+", "", (title or "")).lower()
    host = ""
    try:
        host = urlparse(url or "").netloc.lower()
    except Exception:  # noqa: BLE001
        host = ""
    return hashlib.sha1(f"{t}|{host}".encode("utf-8")).hexdigest()


def _norm(raw: dict, tier: str, reason: str) -> dict:
    return {
        "title": raw.get("title") or "",
        "url": raw.get("url"),
        "source": raw.get("source"),
        "published_at": raw.get("published_at"),
        "tier": tier,
        "relation_reason": reason,
        "sentiment": raw.get("sentiment"),
    }


def collect_related_news(
    code: str,
    relations: dict,
    *,
    stock_news_fn: Optional[Callable[[str], list]] = None,
    sector_news_fn: Optional[Callable[[list], list]] = None,
    hot_news_fn: Optional[Callable[[list], list]] = None,
    orbit_news_fn: Optional[Callable[[list], list]] = None,
    per_tier_limit: int = 8,
) -> List[Dict[str, Any]]:
    boards = relations.get("boards") or []
    peers = relations.get("peers") or []
    rings = relations.get("concept_rings") or []
    board_names = [b.get("name") for b in boards if b.get("name")]

    def _safe(fn, *args):
        if fn is None:
            return []
        try:
            return fn(*args) or []
        except Exception:  # noqa: BLE001
            return []

    staged: list[tuple[str, str, dict]] = []
    for raw in _safe(stock_news_fn, code)[:per_tier_limit]:
        staged.append(("direct", "名称/代码命中", raw))
    for raw in _safe(sector_news_fn, board_names)[:per_tier_limit]:
        staged.append(("board", f"所属板块：{'、'.join(board_names[:2])}", raw))
    peer_names = [p.get("name") for p in peers if p.get("name")]
    if peer_names:
        for raw in _safe(sector_news_fn, peer_names)[:per_tier_limit]:
            staged.append(("peer", f"同行/产业链：{peer_names[0]}", raw))
    for raw in _safe(hot_news_fn, board_names)[:per_tier_limit]:
        staged.append(("theme", "题材/政策", raw))
    for raw in _safe(orbit_news_fn, rings)[:per_tier_limit]:
        staged.append(("orbit", "星轨概念环", raw))

    best: Dict[str, Dict[str, Any]] = {}
    for tier, reason, raw in staged:
        item = _norm(raw, tier, reason)
        if not item["title"]:
            continue
        h = content_hash(item["title"], item["url"] or "")
        prev = best.get(h)
        if prev is None or _TIER_RANK[tier] < _TIER_RANK[prev["tier"]]:
            best[h] = item
    return sorted(best.values(), key=lambda it: _TIER_RANK[it["tier"]])
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_stock_relation_news.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 检查点** — 聚合引擎完成。不要执行 git。

---

## Task 7 (P2): suite `related_news` section（读缓存，零联网）

**Files:**
- Modify: `analysis/stock_analysis_suite.py`（新增 `_collect_related_news`；`_compute_full_payload` 返回加 `related_news`；`stub_tabs` 加 `"related_news"`）
- Test: `tests/test_stock_analysis_suite.py`（追加）

**Interfaces:**
- Consumes: Task 5 `stock_related_news_repo.latest_for_code`
- Produces: payload `["related_news"]= {"data_status","last_updated","tiers":{tier:[items]},"reason"}`

- [ ] **Step 1: 写失败测试**

```python
def test_related_news_section_empty_is_unavailable(monkeypatch):
    suite = StockAnalysisSuite()
    from data_store import stock_related_news_repo
    monkeypatch.setattr(stock_related_news_repo, "latest_for_code",
                        lambda code: {"items": [], "fetched_at": None})
    sec = suite._collect_related_news("601702")
    assert sec["data_status"] == "unavailable"
    assert sec["tiers"] == {}


def test_related_news_section_groups_by_tier(monkeypatch):
    suite = StockAnalysisSuite()
    from data_store import stock_related_news_repo
    monkeypatch.setattr(stock_related_news_repo, "latest_for_code", lambda code: {
        "items": [
            {"tier": "direct", "title": "A", "url": "u1", "source": "金十",
             "published_at": "2026-06-20", "relation_reason": "命中", "sentiment": "pos"},
            {"tier": "board", "title": "B", "url": "u2", "source": "东财",
             "published_at": "2026-06-20", "relation_reason": "板块", "sentiment": None},
        ],
        "fetched_at": "2026-06-20T11:00:00",
    })
    sec = suite._collect_related_news("601702")
    assert sec["data_status"] in ("fresh", "stale")
    assert [n["title"] for n in sec["tiers"]["direct"]] == ["A"]
    assert [n["title"] for n in sec["tiers"]["board"]] == ["B"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_stock_analysis_suite.py::test_related_news_section_empty_is_unavailable -v`
Expected: FAIL（`AttributeError: ... '_collect_related_news'`）

- [ ] **Step 3: 写实现** — 新增方法（用模块级 `_dt` 已 import 的 datetime）：

```python
    def _collect_related_news(self, code: str) -> dict:
        from analysis.stock_relation_news import RELATION_TIERS
        from data_store import stock_related_news_repo
        snap = stock_related_news_repo.latest_for_code(code)
        if not snap.get("fetched_at"):
            return {"data_status": "unavailable", "last_updated": None,
                    "reason": "未抓取，点击「刷新关联新闻」", "tiers": {}}
        try:
            age = (_dt.datetime.now()
                   - _dt.datetime.fromisoformat(snap["fetched_at"])).total_seconds()
        except Exception:  # noqa: BLE001
            age = 0
        status = "fresh" if age < 6 * 3600 else "stale"
        tiers: dict = {}
        for it in snap["items"]:
            tiers.setdefault(it.get("tier"), []).append(it)
        return {"data_status": status, "last_updated": snap["fetched_at"],
                "reason": None, "tiers": tiers,
                "tier_order": list(RELATION_TIERS)}
```

在 `_compute_full_payload` 的返回 dict 里加一行（与 `quant_matrix` 同级）：
```python
            "related_news": self._collect_related_news(code),
```
并在 `stub_tabs` 列表末尾追加 `"related_news"`。

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `.venv/bin/python -m pytest tests/test_stock_analysis_suite.py -v`
Expected: PASS（含新增 2 例）

- [ ] **Step 5: 检查点** — suite 读路径完成。不要执行 git。

---

## Task 8 (P2): service 后台刷新 worker + 默认 collector 接线 + API

**Files:**
- Modify: `webui/services/stock_suite_service.py`（新增 `refresh_related_news` / `get_related_news_status` + `_related_jobs`/`_related_lock`；接线默认 collector）
- Modify: `webui/robyn_app.py`（两条路由，仿 `.../ai`）
- Test: `tests/test_trading_client_service.py` 同目录新增 `tests/test_related_news_service.py`

**Interfaces:**
- Consumes: Task 1 `resolve_relations`、Task 6 `collect_related_news`、Task 5 `replace_for_code`
- Produces:
  - `StockSuiteService.refresh_related_news(code, force_refresh=False) -> {"status":"running"|...}`
  - `StockSuiteService.get_related_news_status(code) -> {"status": "idle|running|ready|failed", ...}`

- [ ] **Step 1: 写失败测试**（worker 用注入引擎，验证状态机；不联网）

```python
# tests/test_related_news_service.py
import time
from webui.services.stock_suite_service import StockSuiteService


def test_refresh_runs_and_persists(monkeypatch):
    svc = StockSuiteService()
    writes = {}
    monkeypatch.setattr(svc, "_run_related_news_job",
                        lambda code: writes.update({code: 3}) or 3)
    r = svc.refresh_related_news("601702")
    assert r["status"] == "running"
    for _ in range(50):
        if svc.get_related_news_status("601702").get("status") in ("ready", "failed"):
            break
        time.sleep(0.02)
    st = svc.get_related_news_status("601702")
    assert st["status"] == "ready"
    assert writes["601702"] == 3


def test_status_idle_when_never_run():
    svc = StockSuiteService()
    assert svc.get_related_news_status("000000")["status"] == "idle"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_related_news_service.py -v`
Expected: FAIL（`AttributeError: ... 'refresh_related_news'`）

- [ ] **Step 3: 写实现** — 在 `StockSuiteService.__init__` 加 `self._related_jobs = {}` 和 `self._related_lock = threading.Lock()`，并新增（仿 `start_ai_interpretation`）：

```python
    def _run_related_news_job(self, code: str) -> int:
        """同步执行一次抓取并落盘，返回写入条数。默认 collector 在此接线。"""
        import datetime as _dt
        from analysis.stock_context import resolve_relations
        from analysis.stock_relation_news import collect_related_news
        from analysis import sector_api
        from analysis.sector_hot_news_collector import SectorNewsCollector
        from analysis.news_sentiment_collector import NewsSentimentCollector
        from data_store import opportunity_repo, star_orbit_repo, stock_related_news_repo

        def _stock_news(c):
            col = NewsSentimentCollector(c)
            news = col.get_latest_news(limit=8) or []
            ann = col.get_latest_announcements(limit=4) or []
            return list(news) + list(ann)

        sector_col = SectorNewsCollector()

        def _sector_news(names):
            return sector_col.get_top_news_by_sectors(list(names), per_sector_limit=4, total_limit=8) or []

        def _hot_news(boards):
            rows = opportunity_repo.latest_hot_news() or []
            kw = [b for b in boards]
            return [r for r in rows
                    if not kw or any(k and k in (r.get("title") or "") for k in kw)] or rows[:6]

        def _orbit_news(rings):
            return []  # 星轨事件源暂返回空（环映射已在 relations 中体现，后续可接 star_orbit 事件）

        relations = resolve_relations(
            code,
            boards_fn=sector_api.get_stock_boards,
            peers_fn=lambda c: [],   # 同行/产业链：首版留空，后续接 industry_comparison/merger
            rings_fn=lambda boards: star_orbit_repo_rings_for(boards, star_orbit_repo),
            sector_fn=sector_api.get_sector_sentiment,
        )
        items = collect_related_news(
            code, relations,
            stock_news_fn=_stock_news, sector_news_fn=_sector_news,
            hot_news_fn=_hot_news, orbit_news_fn=_orbit_news,
        )
        fetched_at = _dt.datetime.now().isoformat(timespec="seconds")
        n = stock_related_news_repo.replace_for_code(code, items, fetched_at)
        self._suite.invalidate(code)
        return n

    def refresh_related_news(self, code: str, force_refresh: bool = False) -> dict:
        code = self._validate_code(code)
        with self._related_lock:
            ex = self._related_jobs.get(code)
            if ex and ex.get("status") == "running" and not force_refresh:
                return {"success": True, "status": "running", "started_at": ex.get("started_at")}
            started_at = _dt.datetime.now().isoformat(timespec="seconds")
            self._related_jobs[code] = {"status": "running", "started_at": started_at}

        def _worker():
            try:
                n = self._run_related_news_job(code)
                res = {"status": "ready", "written": n,
                       "generated_at": _dt.datetime.now().isoformat(timespec="seconds")}
            except Exception as exc:  # noqa: BLE001
                res = {"status": "failed", "error": str(exc),
                       "generated_at": _dt.datetime.now().isoformat(timespec="seconds")}
            with self._related_lock:
                prev = self._related_jobs.get(code) or {}
                res.setdefault("started_at", prev.get("started_at"))
                self._related_jobs[code] = res

        threading.Thread(target=_worker, name=f"related-news-{code}", daemon=True).start()
        return {"success": True, "status": "running", "started_at": started_at}

    def get_related_news_status(self, code: str) -> dict:
        code = self._validate_code(code)
        with self._related_lock:
            job = self._related_jobs.get(code)
            return dict(job) if job else {"success": True, "status": "idle"}
```

并在文件顶部模块级加一个小 helper（避免 worker 内长 lambda）：

```python
def star_orbit_repo_rings_for(boards, star_orbit_repo) -> list:
    """从星轨图谱里找出包含这些板块的概念环。失败返回 []。"""
    try:
        names = {b.get("name") for b in (boards or []) if b.get("name")}
        m = star_orbit_repo.get_map() or {}
        out = []
        for ring in m.get("rings", []):
            concepts = [b.get("board_name") for b in ring.get("boards", [])]
            if names & set(concepts):
                out.append({"ring": ring.get("name"), "concepts": concepts})
        return out
    except Exception:  # noqa: BLE001
        return []
```

> 注：确认 `_dt`/`threading` 已在 `stock_suite_service.py` 顶部 import（既有 `start_ai_interpretation` 已用，应已具备）。

- [ ] **Step 4: 运行 service 测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_related_news_service.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 加 API 路由** — 在 `webui/robyn_app.py` 仿 `.../ai`（524 行附近）新增：

```python
@_native_post("/api/stock-analysis-suite/:stock_code/related-news/refresh")
def _stock_related_news_refresh(request):
    code = request.path_params.get("stock_code")
    return _json(_stock_suite_service.refresh_related_news(code))


@_native_get("/api/stock-analysis-suite/:stock_code/related-news/status")
def _stock_related_news_status(request):
    code = request.path_params.get("stock_code")
    return _json(_stock_suite_service.get_related_news_status(code))
```
（`_native_get/_native_post/_json/_stock_suite_service` 沿用文件内既有命名；按相邻路由的真实写法对齐参数取值方式。）

- [ ] **Step 6: 回归**

Run: `.venv/bin/python -m pytest tests/test_related_news_service.py tests/test_stock_analysis_suite.py -v`
Expected: PASS

- [ ] **Step 7: 检查点** — Part B 后端+API 完成。不要执行 git。

---

## Task 9 (P2): 前端 — 关联热点 Tab

**Files:**
- Modify: `webui/templates/desktop.html`（`#stockSuiteTabs` 加按钮）
- Modify: `webui/static/kronos_desktop_app.js`（渲染 related_news 面板 + 刷新轮询）
- Modify: `webui/static/kronos_desktop.css`（新闻卡样式）
- Verify: 手动

- [ ] **Step 1: 加 Tab 按钮** — 在 `desktop.html` 第 1016 行 `pattern_backtest` 按钮后追加：

```html
            <button data-suite-tab="related_news"       class="suite-tab" type="button">关联热点</button>
```

- [ ] **Step 2: 渲染面板 + 刷新逻辑**（`kronos_desktop_app.js`）

```javascript
const RELATED_TIER_LABEL = {
  direct: "直接关联", board: "行业/概念板块", peer: "产业链/同行",
  theme: "题材/政策", orbit: "星轨概念环",
};

function renderRelatedNews(code, rn) {
  if (!rn || rn.data_status === "unavailable") {
    return `<div class="related-news">
      <button class="button" onclick="refreshRelatedNews('${code}')">刷新关联新闻</button>
      <p class="muted">${(rn && rn.reason) || "未抓取"}</p></div>`;
  }
  const order = rn.tier_order || ["direct","board","peer","theme","orbit"];
  const blocks = order.map(tier => {
    const list = (rn.tiers && rn.tiers[tier]) || [];
    const cards = list.map(n => `
      <div class="news-card sentiment-${n.sentiment || 'neutral'}">
        <a href="${n.url || '#'}" target="_blank">${n.title}</a>
        <div class="news-meta">${n.source || ''} · ${n.published_at || ''} · ${n.relation_reason || ''}</div>
      </div>`).join("");
    return `<section class="news-tier">
      <h4><span class="tier-badge tier-${tier}">${RELATED_TIER_LABEL[tier]||tier}</span></h4>
      ${cards || '<p class="muted">暂无</p>'}</section>`;
  }).join("");
  const stale = rn.data_status === "stale" ? ' <span class="muted">(已陈旧)</span>' : '';
  return `<div class="related-news">
    <div class="related-head">最后更新：${rn.last_updated || '—'}${stale}
      <button class="button" onclick="refreshRelatedNews('${code}')">刷新</button></div>
    ${blocks}</div>`;
}

async function refreshRelatedNews(code) {
  await fetch(`/api/stock-analysis-suite/${code}/related-news/refresh`, {method: "POST"});
  const poll = async () => {
    const r = await (await fetch(`/api/stock-analysis-suite/${code}/related-news/status`)).json();
    if (r.status === "ready" || r.status === "failed") {
      reloadStockSuite(code);            // 复用既有重载函数
    } else {
      setTimeout(poll, 1500);
    }
  };
  setTimeout(poll, 1500);
}
// 在 suite 面板分发处把 data-suite-tab="related_news" 映射到 renderRelatedNews(code, payload.related_news)
```
（`reloadStockSuite`/面板分发函数名以文件内既有实现为准，按其约定接线。）

- [ ] **Step 3: 加样式**（`kronos_desktop.css`）

```css
.related-head { display:flex; gap:12px; align-items:center; margin-bottom:10px; }
.news-tier { margin-bottom:14px; }
.tier-badge { font-size:11px; padding:2px 8px; border-radius:10px; background:rgba(120,160,255,.18); }
.news-card { padding:8px 10px; border-bottom:1px solid rgba(255,255,255,.06); }
.news-card .news-meta { font-size:12px; color:#9aa4b2; margin-top:2px; }
.news-card.sentiment-pos { border-left:3px solid #3ddc84; }
.news-card.sentiment-neg { border-left:3px solid #ff6b6b; }
```

- [ ] **Step 4: 手动验证**

启动 webui → 个股分析 → 关联热点 Tab：初次显示"未抓取/刷新"，点刷新 → 后台抓取 → 轮询完成 → 出现 5 层新闻。注意 WKWebView 缓存（清缓存或 `?v=`）。

- [ ] **Step 5: 检查点** — Part B 前端完成。全功能完成。不要执行 git。

---

## 全量回归

Run:
```bash
.venv/bin/python -m pytest tests/test_stock_context.py tests/test_prosperity_scores.py \
  tests/test_stock_analysis_suite.py tests/test_schema_migration_v16.py \
  tests/test_stock_related_news_repo.py tests/test_stock_relation_news.py \
  tests/test_related_news_service.py -v
```
Expected: 全 PASS。

---

## Self-Review 记录（计划自检）

- **Spec 覆盖**：Part A 行业景气度→Task 2/3/4；个股业务景气度→Task 2/3/4；Part B 5 层关联→Task 1/6；缓存优先→Task 5/7；按需刷新 worker→Task 8；前端两 Tab→Task 4/9。schema v16→Task 5。✓
- **占位符**：每个代码步骤均含完整代码，无 TBD/TODO。前端"分发函数名以既有为准"为接线说明，非占位（Step 1 已给 grep 定位法）。
- **类型一致**：`resolve_relations` 返回键（boards/peers/concept_rings/sector_sentiment/degraded）在 Task 6/8 一致消费；`collect_related_news` item 结构（tier/relation_reason/...）在 repo(Task5)/suite(Task7)/前端(Task9)一致；`replace_for_code`/`latest_for_code` 签名贯穿 Task5→7→8。✓
- **已知留白（非占位，明确标注首版范围）**：Task 8 中 `peers_fn` 首版返回空、`_orbit_news` 返回空 —— 关联结构与渲染已就位，同行/产业链与星轨事件源作为后续增量接入（避免首版引入 merger/akshare 的网络不稳定，符合 YAGNI + 缓存优先策略）。
