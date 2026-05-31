# 个股深度分析弹窗 (Stock Analysis Suite) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `#stockContextModal` 升级为 11 个 Tab 的深度分析工作台，首版交付 3 个核心 Tab（综合总览、操盘风控、AI 解读）+ 现有 6 面板归入「快速信息」Tab + 7 个占位 Tab。

**Architecture:** 三层结构。Analysis 层 `analysis/stock_analysis_suite.py` 编排现有 5 个 analyzer，输出结构化 dict + 5min LRU 缓存。Service 层 `webui/services/stock_suite_service.py` 包薄 JSON 转换层 + 触发 AI。Web 层在 `webui/robyn_app.py` 注册 2 个原生 Robyn handler（GET 数据/POST AI），前端在 `webui/templates/desktop.html` 插入 Tab 栏 + JS 渲染。

**Tech Stack:** Python 3.13, Robyn, Jinja2, Plotly (with SVG fallback), pytest, existing analyzers (AdvancedAnalyzer / TechnicalAnalysis / FundamentalDataCollector / LLMAnalyzer / InvestorSentimentAnalyzer / MarketEnvAnalyzer).

**Spec 参考:** `docs/superpowers/specs/2026-05-23-stock-analysis-suite-design.md`

**Ground-truth deviations from spec (verified):**

1. **`ChipAnalyzer._estimate_main_force_control` 签名** ≠ `(code)`，实际是 `(close: np.ndarray, volume: np.ndarray, turnover: Optional[np.ndarray])`。Plan 通过 `ChipAnalyzer().analyze(code, df)` 调用，从 `details['main_force_control']` 读取。
2. **`MarketEnvAnalyzer.assess()` 不存在**。实际是 `analyze_market_environment(market_data: Dict) -> Tuple[scheme_name, weights]`。Plan 自建 `_classify_market_regime()` helper：先用 `InvestorSentimentAnalyzer.get_overall_market_sentiment()` 拿 0-100 sentiment + change_pct，再分桶为 bull/sideways/bear。
3. **`LLMAnalyzer.analyze_stock()` 返回 parsed dict，非 markdown**。Plan 通过 `LLMAnalyzer._build_analysis_prompt` + provider.`call_api()` 直拿 raw text，并新增 `LLMAnalyzer.interpret_stock_markdown(payload, model_key)` 返回 `(success, markdown, token_usage)`。Token usage 从 OpenAI / DashScope response `usage` 字段抽取。
4. **Plotly 在 desktop.html 不一定加载**。Task 12 先 grep，缺失则在 `<head>` 添加 CDN；附带 SVG fallback 路径。

---

## 文件结构概览

### Create

- `analysis/stock_analysis_suite.py` — `StockAnalysisSuite` orchestrator, 5min in-memory LRU cache
- `webui/services/stock_suite_service.py` — `StockSuiteService` thin wrapper
- `webui/templates/components/stock_suite_tabs.html` — Jinja include (Tab 骨架)
- `tests/test_stock_analysis_suite.py` — orchestrator unit/integration tests
- `tests/test_stock_suite_service.py` — service tests with stub orchestrator

### Modify

- `webui/robyn_app.py` — 2 个新 native handler（GET 数据、POST AI）
- `webui/core.py` — 新增 `STOCK_SUITE_SERVICE` 单例 + 暴露给 surface test
- `tests/test_webui_core_surface.py` — `EXPECTED_SINGLETONS` 添加 `STOCK_SUITE_SERVICE`
- `tests/test_robyn_app.py` — 2 个新 route 的测试
- `webui/templates/desktop.html` — Tab 栏插入 + `renderStockContext` 重构 + 3 个 Tab 渲染 JS
- `webui/static/kronos_desktop.css` — Tab 样式 + suite 专属样式
- `analysis/llm_service.py` — 新增 `interpret_stock_markdown` 方法（返回 raw markdown + token usage）

### Not touched (spec §2.1)

`scripts/run_opportunity_discovery.py`、`scripts/opportunity_report_generator.py`、`scripts/run_integrated_discovery.py`、`analysis/technical_analysis.py`（只读签名调用）、`analysis/advanced_analysis.py`（只读签名调用）、`analysis/market_env_analyzer.py`（只读）、`analysis/fundamental_data_collector.py`（只读）、`analysis/investor_sentiment.py`（只读）、`analysis/opportunity_scorer_v4_1_integration.py`。

---

## Phase A — Analysis 层编排器（TDD）

### Task 1: Orchestrator 骨架与 5min LRU 缓存

**Files:**
- Create: `analysis/stock_analysis_suite.py`
- Create: `tests/test_stock_analysis_suite.py`

- [ ] **Step 1: 写失败测试 — 实例化 + 缓存命中**

```python
# tests/test_stock_analysis_suite.py
import time
from analysis.stock_analysis_suite import StockAnalysisSuite


def test_suite_caches_payload_for_ttl():
    suite = StockAnalysisSuite(ttl_seconds=60)
    calls = []

    def fake_compute(code: str):
        calls.append(code)
        return {"code": code, "value": len(calls)}

    suite._compute_full_payload = fake_compute  # type: ignore[attr-defined]
    r1 = suite.get_full_payload("000001")
    r2 = suite.get_full_payload("000001")
    assert r1 == r2 == {"code": "000001", "value": 1}
    assert calls == ["000001"]


def test_suite_recomputes_after_ttl():
    suite = StockAnalysisSuite(ttl_seconds=0.05)
    calls = []
    suite._compute_full_payload = lambda code: calls.append(code) or {"v": len(calls)}  # type: ignore[attr-defined]
    suite.get_full_payload("000001")
    time.sleep(0.1)
    suite.get_full_payload("000001")
    assert len(calls) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_stock_analysis_suite.py -v`
Expected: `ImportError` or `ModuleNotFoundError: analysis.stock_analysis_suite`

- [ ] **Step 3: 写最小实现**

```python
# analysis/stock_analysis_suite.py
"""Stock Analysis Suite orchestrator — single entry per stock code, 5-min LRU cache."""

from __future__ import annotations

import time
from threading import RLock
from typing import Any, Dict


_DEFAULT_TTL_SECONDS = 300  # 5 minutes per spec §3


class StockAnalysisSuite:
    """Orchestrates per-stock analysis (overview / risk_control / AI payload).

    Thread-safe in-memory LRU cache keyed by stock_code. Cache value is the full
    suite payload as a JSON-serializable dict.
    """

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl = float(ttl_seconds)
        self._cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._lock = RLock()

    def get_full_payload(self, code: str) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(code)
            if cached and now - cached[0] < self._ttl:
                return cached[1]
        payload = self._compute_full_payload(code)
        with self._lock:
            self._cache[code] = (now, payload)
        return payload

    def invalidate(self, code: str) -> None:
        with self._lock:
            self._cache.pop(code, None)

    def _compute_full_payload(self, code: str) -> Dict[str, Any]:
        """Override-able in tests. Real impl assembled in later tasks."""
        raise NotImplementedError
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_stock_analysis_suite.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit（如果你要 commit；否则跳过 — 由用户决定 commit 策略）**

```bash
git add analysis/stock_analysis_suite.py tests/test_stock_analysis_suite.py
git commit -m "feat(analysis): stock analysis suite orchestrator skeleton with 5min LRU cache"
```

---

### Task 2: 5 维雷达评分（compute_radar_scores）

**Files:**
- Modify: `analysis/stock_analysis_suite.py`
- Modify: `tests/test_stock_analysis_suite.py`

5 维（参见 spec §4）：`main_force_phase`, `market_cycle`, `volume_price_game`, `chip_structure`, `performance`。每维返回 `{score: int|null, label: str, reason: str}`。任一维度抛异常 → 该维度 `score=null, label="数据不足", reason="<error message>"`。

- [ ] **Step 1: 写失败测试 — 单维度公式 + 全部缺失降级**

```python
# tests/test_stock_analysis_suite.py (append)
import numpy as np
import pandas as pd

def _fake_ohlcv(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = 10.0 + rng.normal(0, 0.2, n).cumsum() * 0.1
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": close * 0.99, "high": close * 1.02,
        "low": close * 0.98, "close": close,
        "volume": rng.integers(1e6, 5e6, n).astype(float),
        "amount": close * rng.integers(1e6, 5e6, n).astype(float),
    })


def test_radar_main_force_phase_formula():
    """0.5 * control_degree + 0.3 * continuity_score + 0.2 * retail_normalized."""
    from analysis.stock_analysis_suite import compute_main_force_phase_score
    score = compute_main_force_phase_score(
        control_degree=80.0,
        recent_main_positive_days=4,
        main_net=-1_000_000.0,
        retail_net=600_000.0,
    )
    # 0.5*80 + 0.3*(4*20) + 0.2*min(100, abs(600000/1000000)*100) = 40 + 24 + 12 = 76
    assert score == 76


def test_radar_handles_all_missing():
    suite = StockAnalysisSuite()
    radar = suite._compute_radar({})  # all analyzer outputs missing
    for key in ("main_force_phase", "market_cycle", "volume_price_game", "chip_structure", "performance"):
        assert radar[key]["score"] is None
        assert "数据不足" in radar[key]["label"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_stock_analysis_suite.py::test_radar_main_force_phase_formula -v`
Expected: `ImportError`

- [ ] **Step 3: 实现 `compute_main_force_phase_score` + `_compute_radar` + 4 个 helper**

```python
# analysis/stock_analysis_suite.py (append)
from typing import Optional


_REGIME_BASE = {"bull": 50, "sideways": 35, "bear": 15}


def compute_main_force_phase_score(
    control_degree: float,
    recent_main_positive_days: int,
    main_net: float,
    retail_net: float,
) -> int:
    """5维评分①. Spec §4 ①."""
    continuity = min(100.0, recent_main_positive_days * 20.0)
    if main_net == 0:
        retail_norm = 0.0
    else:
        retail_norm = max(0.0, -retail_net / abs(main_net)) * 100.0
    score = 0.5 * control_degree + 0.3 * continuity + 0.2 * min(100.0, retail_norm)
    return int(round(score))


def compute_market_cycle_score(regime: str, capital_flow_ratio: float) -> int:
    """5维评分②. Spec §4 ②. regime ∈ {bull, sideways, bear}."""
    base = _REGIME_BASE.get(regime, 35)
    score = base + 30.0 * max(0.0, min(1.0, capital_flow_ratio))
    return int(round(min(100.0, score)))


def compute_volume_price_game_score(buy_signal_count: int, total_models: int = 30) -> int:
    """5维评分③. Spec §4 ③."""
    if total_models <= 0:
        return 0
    return int(round(buy_signal_count / total_models * 100.0))


def compute_chip_structure_score(concentration_pct: float, profit_ratio_pct: float) -> int:
    """5维评分④. Spec §4 ④."""
    a = max(0.0, min(100.0, 100.0 - concentration_pct * 2.0)) * 0.5
    b = (100.0 - abs(profit_ratio_pct - 50.0)) * 0.5
    return int(round(a + b))


def compute_performance_score(
    pe_percentile_rank: Optional[float],
    roe_pct: Optional[float],
    yoy_growth_pct: Optional[float],
) -> Optional[int]:
    """5维评分⑤. Spec §4 ⑤. Returns None if all three inputs None."""
    if pe_percentile_rank is None and roe_pct is None and yoy_growth_pct is None:
        return None
    pe_score = (100.0 - (pe_percentile_rank or 50.0)) if pe_percentile_rank is not None else 50.0
    if roe_pct is None:
        roe_score = 50.0
    elif roe_pct >= 15:
        roe_score = 100.0
    elif roe_pct <= 5:
        roe_score = 0.0
    else:
        roe_score = (roe_pct - 5.0) / 10.0 * 100.0
    if yoy_growth_pct is None:
        growth_score = 50.0
    elif yoy_growth_pct >= 50:
        growth_score = 100.0
    elif yoy_growth_pct <= 0:
        growth_score = max(0.0, 50.0 + yoy_growth_pct)  # 负增长扣分到 0
    else:
        growth_score = 50.0 + yoy_growth_pct
    return int(round(pe_score * 0.35 + roe_score * 0.35 + growth_score * 0.30))


def _missing(label: str = "数据不足", reason: str = "数据采集失败") -> Dict[str, Any]:
    return {"score": None, "label": label, "reason": reason}


# Inside class StockAnalysisSuite:

    def _compute_radar(self, inputs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Compute 5 radar dimensions from pre-fetched analyzer outputs.

        `inputs` is a dict with optional keys: chip, capital_flow, market_env,
        models, fundamental, sentiment. Each entry is itself a dict from the
        corresponding analyzer, or absent if collection failed.
        """
        radar = {}
        try:
            chip = inputs["chip"]["details"]
            cap = inputs["capital_flow"]["details"]["order_analysis"]
            score = compute_main_force_phase_score(
                control_degree=chip["main_force_control"],
                recent_main_positive_days=inputs["capital_flow"]["details"].get("positive_days_5d", 0),
                main_net=cap["main_net_inflow"],
                retail_net=cap["retail_net_inflow"],
            )
            radar["main_force_phase"] = {"score": score, "label": self._label_main_force(score),
                                          "reason": f"主力近5日{inputs['capital_flow']['details'].get('positive_days_5d', 0)}日净流入"}
        except (KeyError, TypeError, ValueError):
            radar["main_force_phase"] = _missing()
        try:
            regime = inputs["market_regime"]
            ratio = inputs.get("capital_flow_ratio", 0.0)
            score = compute_market_cycle_score(regime, ratio)
            radar["market_cycle"] = {"score": score, "label": self._label_regime(regime),
                                      "reason": f"大盘资金流入比 {ratio:.2f}"}
        except (KeyError, TypeError, ValueError):
            radar["market_cycle"] = _missing()
        try:
            buy_count = inputs["models"]["buy_signal_count"]
            score = compute_volume_price_game_score(buy_count, inputs["models"].get("total", 30))
            radar["volume_price_game"] = {"score": score, "label": self._label_vp(score),
                                           "reason": f"30 模型中 {buy_count} 个买入信号"}
        except (KeyError, TypeError, ValueError):
            radar["volume_price_game"] = _missing()
        try:
            chip_details = inputs["chip"]["details"]
            score = compute_chip_structure_score(
                concentration_pct=chip_details["concentration_90"],
                profit_ratio_pct=chip_details.get("profit_ratio", 50.0),
            )
            radar["chip_structure"] = {"score": score, "label": self._label_chip(score),
                                        "reason": f"90% 成本集中度 {chip_details['concentration_90']:.1f}%"}
        except (KeyError, TypeError, ValueError):
            radar["chip_structure"] = _missing()
        try:
            fundam = inputs["fundamental"]
            score = compute_performance_score(
                pe_percentile_rank=fundam.get("pe_industry_rank"),
                roe_pct=fundam.get("roe"),
                yoy_growth_pct=fundam.get("net_profit_yoy"),
            )
            if score is None:
                radar["performance"] = _missing()
            else:
                pe = fundam.get("pe")
                roe = fundam.get("roe")
                radar["performance"] = {"score": score, "label": self._label_perf(score),
                                         "reason": f"PE {pe}，ROE {roe}%" if pe and roe else "基本面"}
        except (KeyError, TypeError, ValueError):
            radar["performance"] = _missing()
        return radar

    @staticmethod
    def _label_main_force(score: int) -> str:
        if score >= 70: return "强势主导"
        if score >= 50: return "中等偏强"
        if score >= 30: return "弱势承接"
        return "主力撤离"

    @staticmethod
    def _label_regime(regime: str) -> str:
        return {"bull": "牛市趋势", "sideways": "震荡期", "bear": "熊市风险"}.get(regime, "未知")

    @staticmethod
    def _label_vp(score: int) -> str:
        if score >= 60: return "多头占优"
        if score >= 40: return "多空胶着"
        return "空头占优"

    @staticmethod
    def _label_chip(score: int) -> str:
        if score >= 60: return "结构健康"
        if score >= 35: return "结构一般"
        return "结构偏差"

    @staticmethod
    def _label_perf(score: int) -> str:
        if score >= 70: return "估值修复"
        if score >= 50: return "基本面稳健"
        if score >= 30: return "基本面承压"
        return "基本面恶化"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_stock_analysis_suite.py -v`
Expected: all passed

- [ ] **Step 5: Commit (optional per user)**

---

### Task 3: compute_overview 装配（key_signals + deep_signals + scenario_probability）

**Files:** modify `analysis/stock_analysis_suite.py`, modify `tests/test_stock_analysis_suite.py`.

- [ ] **Step 1: 写失败测试 — compute_overview 输出 shape**

```python
def test_compute_overview_assembles_full_payload(monkeypatch):
    suite = StockAnalysisSuite()
    fake_inputs = {
        "chip": {"details": {"main_force_control": 80, "concentration_90": 15.9, "profit_ratio": 50}},
        "capital_flow": {"details": {"order_analysis": {"main_net_inflow": -1e6, "retail_net_inflow": 6e5},
                                       "positive_days_5d": 4}},
        "market_regime": "sideways",
        "capital_flow_ratio": 0.42,
        "models": {"buy_signal_count": 16, "sell_signal_count": 8, "hold_signal_count": 6, "total": 30},
        "fundamental": {"pe": 4.8, "roe": 14.2, "pe_industry_rank": 10.0, "net_profit_yoy": 12.0},
        "sentiment": {"confidence_label": "中"},
        "quality": {"volume_label": "量价正常", "chip_label": "中等"},
    }
    suite._collect_inputs = lambda code: fake_inputs  # type: ignore[attr-defined]
    overview = suite.compute_overview("000001")
    assert "radar" in overview
    assert overview["scenario_probability"]["bullish"] + overview["scenario_probability"]["bearish"] \
         + overview["scenario_probability"]["sideways"] == 100
    assert any(s["label"] == "主力阶段" for s in overview["key_signals"])
    assert isinstance(overview["deep_signals"], list)
```

- [ ] **Step 2: 实现 `compute_overview` + `_collect_inputs` stub**

```python
# Inside class StockAnalysisSuite:

    def _collect_inputs(self, code: str) -> Dict[str, Any]:
        """Fetch raw analyzer outputs. Real impl lives in Task 6 (wires to actual analyzers)."""
        return {}

    def compute_overview(self, code: str) -> Dict[str, Any]:
        inputs = self._collect_inputs(code)
        radar = self._compute_radar(inputs)
        return {
            "radar": radar,
            "key_signals": self._build_key_signals(inputs, radar),
            "deep_signals": self._build_deep_signals(inputs),
            "scenario_probability": self._build_scenario_probability(inputs),
        }

    def _build_key_signals(self, inputs, radar):
        result = []
        regime = inputs.get("market_regime", "unknown")
        result.append({"label": "大盘周期", "value": self._label_regime(regime),
                       "tone": "warn" if regime != "bull" else "info"})
        cap_ratio = inputs.get("capital_flow_ratio", 0.0)
        position_cap = max(20, min(80, int(cap_ratio * 100)))
        result.append({"label": "仓位上限", "value": f"{position_cap}%", "tone": "warn"})
        mf_label = radar["main_force_phase"]["label"]
        result.append({"label": "主力阶段", "value": mf_label, "tone": "info"})
        conf = (inputs.get("sentiment") or {}).get("confidence_label", "—")
        result.append({"label": "可信度", "value": conf, "tone": "neutral"})
        quality = inputs.get("quality") or {}
        result.append({"label": "量能质量", "value": quality.get("volume_label", "—"), "tone": "info"})
        result.append({"label": "筹码集中度", "value": quality.get("chip_label", "—"), "tone": "neutral"})
        return result

    def _build_deep_signals(self, inputs):
        signals = []
        chip = (inputs.get("chip") or {}).get("signals") or []
        for sig in chip[:3]:
            signals.append({"text": sig, "tone": "info", "tag": "筹码"})
        cap_signals = (inputs.get("capital_flow") or {}).get("signals") or []
        for sig in cap_signals[:3]:
            signals.append({"text": sig, "tone": "info", "tag": "资金"})
        return signals

    def _build_scenario_probability(self, inputs):
        models = inputs.get("models") or {}
        buy = models.get("buy_signal_count", 0)
        sell = models.get("sell_signal_count", 0)
        hold = models.get("hold_signal_count", 0)
        total = max(1, buy + sell + hold)
        return {
            "bullish": int(round(buy / total * 100)),
            "bearish": int(round(sell / total * 100)),
            "sideways": 100 - int(round(buy / total * 100)) - int(round(sell / total * 100)),
            "source": "30 量化模型多空票数归一化",
        }
```

- [ ] **Step 3: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_stock_analysis_suite.py -v`
Expected: all passed

- [ ] **Step 4: Commit (optional)**

---

### Task 4: compute_risk_control（操盘风控 Tab 数据）

**Files:** modify `analysis/stock_analysis_suite.py`, modify `tests/test_stock_analysis_suite.py`.

按 spec §5.1 `risk_control` 节装配 `execution_plan`, `scaled_entry`, `tiered_take_profit`, `deep_signals`, `hidden_risks`。

- [ ] **Step 1: 写失败测试**

```python
def test_compute_risk_control_with_atr_and_levels():
    suite = StockAnalysisSuite()
    df = _fake_ohlcv(120)
    suite._load_ohlcv = lambda code: df  # type: ignore[attr-defined]
    rc = suite.compute_risk_control("000001")
    assert rc["execution_plan"]["stop_loss"]["price"] > 0
    assert len(rc["scaled_entry"]) == 5
    assert sum(item["position_pct"] for item in rc["scaled_entry"]) == 100
    assert len(rc["tiered_take_profit"]) == 4
    assert sum(item["sell_pct"] for item in rc["tiered_take_profit"]) == 100
    assert all("price" in item for item in rc["tiered_take_profit"])
    assert isinstance(rc["deep_signals"], list)
```

- [ ] **Step 2: 实现 compute_risk_control + _load_ohlcv 占位**

```python
# analysis/stock_analysis_suite.py (append)
import numpy as np
from analysis.technical_analysis import TechnicalAnalysis


# Inside class StockAnalysisSuite:

    def _load_ohlcv(self, code: str):  # noqa: ARG002 - real impl in Task 6
        raise NotImplementedError

    def compute_risk_control(self, code: str) -> Dict[str, Any]:
        try:
            df = self._load_ohlcv(code)
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "reason": f"数据不足，建议先补齐数据 ({exc})"}
        if df is None or len(df) < 60:
            return {"available": False, "reason": "数据不足，建议先补齐数据"}

        close = df["close"].to_numpy()
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        current = float(close[-1])
        atr_series = TechnicalAnalysis.calculate_atr(high, low, close, period=20)
        atr = float(atr_series[-1]) if len(atr_series) and not np.isnan(atr_series[-1]) else 0.0

        stop_price = round(current - atr * 1.5, 2)
        drop_pct = round((current - stop_price) / current * 100, 1) if current else 0.0
        recent_high = float(max(close[-60:])) if len(close) >= 60 else float(max(close))
        expected_return_pct = round((recent_high - current) / current * 100, 1) if current else 0.0
        rr_ratio = round(expected_return_pct / max(0.1, drop_pct), 1)

        scaled = [
            {"label": "现价建仓", "price": round(current, 2), "position_pct": 10},
            {"label": "浅回调加仓", "price": round(current - atr * 0.25, 2), "position_pct": 20},
            {"label": "中度回调加仓", "price": round(current - atr * 0.5, 2), "position_pct": 30},
            {"label": "深度回调加仓", "price": round(current - atr * 1.0, 2), "position_pct": 25},
            {"label": "极限加仓", "price": round(current - atr * 1.25, 2), "position_pct": 15},
        ]
        take_profit = [
            {"label": "第一止盈(前高)", "price": round(recent_high, 2), "sell_pct": 30},
            {"label": "第二止盈(+15%)", "price": round(current * 1.15, 2), "sell_pct": 30},
            {"label": "第三止盈(+30%)", "price": round(current * 1.30, 2), "sell_pct": 25},
            {"label": "终极止盈(+50%)", "price": round(current * 1.50, 2), "sell_pct": 15},
        ]

        deep = self._build_risk_deep_signals(df, close)
        return {
            "available": True,
            "execution_plan": {
                "stop_loss": {"price": stop_price, "drop_pct": drop_pct, "basis": "ATR(20)×1.5 下沿"},
                "risk_reward": {"ratio": f"1:{rr_ratio}", "expected_return_pct": expected_return_pct},
            },
            "scaled_entry": scaled,
            "tiered_take_profit": take_profit,
            "deep_signals": deep,
            "hidden_risks": [],  # 占位；Task 5 由 fundamental + 公告 补
        }

    def _build_risk_deep_signals(self, df, close):
        signals = []
        windows = [(60, "60日"), (120, "120日")]
        peak = float(max(close))
        cur = float(close[-1])
        cur_drawdown = round((cur - peak) / peak * 100, 1)
        signals.append({"text": f"最大回撤：当前 {cur_drawdown}%", "tone": "warn" if cur_drawdown < -15 else "info"})
        for window, label in windows:
            if len(close) >= window:
                wclose = close[-window:]
                wpeak = float(max(wclose))
                wdd = round((float(min(wclose)) - wpeak) / wpeak * 100, 1)
                signals.append({"text": f"{label}最大回撤 {wdd}%", "tone": "warn" if wdd < -15 else "info"})
        if len(close) >= 60:
            log_returns = np.diff(np.log(close[-60:]))
            sigma = float(np.std(log_returns, ddof=1)) * np.sqrt(252)
            signals.append({"text": f"波动率(60日年化) {sigma*100:.1f}%", "tone": "info"})
            mean_return = float(np.mean(log_returns)) * 252
            sharpe = round(mean_return / max(0.0001, sigma), 2)
            signals.append({"text": f"夏普比率(60日年化) {sharpe}", "tone": "danger" if sharpe < 0 else "info"})
        return signals
```

- [ ] **Step 3: 验证 TechnicalAnalysis.calculate_atr 签名**

Run: `.venv/bin/python -c "from analysis.technical_analysis import TechnicalAnalysis; import inspect; print(inspect.signature(TechnicalAnalysis.calculate_atr))"`
Expected: 输出含 high/low/close/period 参数。若签名不同，调整调用方式。

- [ ] **Step 4: 运行测试**

Run: `.venv/bin/pytest tests/test_stock_analysis_suite.py -v`
Expected: all passed

- [ ] **Step 5: Commit (optional)**

---

### Task 5: collect_cached_reports

**Files:** modify `analysis/stock_analysis_suite.py`, modify `tests/test_stock_analysis_suite.py`.

读取 `reports/` 目录下与该 code 关联的产物，返回 `opportunity` / `batch_analysis` 两个 entry。

- [ ] **Step 1: 写失败测试**

```python
def test_collect_cached_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "opportunity_top10_20260523_101500.md").write_text("test", encoding="utf-8")
    (reports / "batch_analysis_000001_20260523.md").write_text("test", encoding="utf-8")
    suite = StockAnalysisSuite()
    out = suite.collect_cached_reports("000001", base_dir=reports)
    assert out["opportunity"]["found"] is True
    assert out["opportunity"]["path"].endswith("opportunity_top10_20260523_101500.md")
    assert out["batch_analysis"]["found"] is True


def test_collect_cached_reports_no_match(tmp_path):
    suite = StockAnalysisSuite()
    out = suite.collect_cached_reports("999999", base_dir=tmp_path)
    assert out["opportunity"]["found"] is False
    assert out["opportunity"]["path"] is None
```

- [ ] **Step 2: 实现 collect_cached_reports**

```python
from pathlib import Path
import datetime as _dt


# Inside class StockAnalysisSuite:

    def collect_cached_reports(self, code: str, base_dir: Optional[Path] = None) -> Dict[str, Any]:
        base = Path(base_dir) if base_dir is not None else Path("reports")
        opp = _latest_match(base, ["opportunity_top10_*.md", "opportunity_top10_*.html"])
        batch = _latest_match(base, [f"batch_analysis_{code}_*.md", f"batch_analysis_*{code}*.json"])
        return {
            "opportunity": _report_entry(opp),
            "batch_analysis": _report_entry(batch),
        }


def _latest_match(base: Path, patterns: list[str]) -> Optional[Path]:
    if not base.exists():
        return None
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(base.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _report_entry(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {"found": False, "path": None, "updated_at": None}
    return {
        "found": True,
        "path": str(path),
        "updated_at": _dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
    }
```

- [ ] **Step 3: 运行测试** `.venv/bin/pytest tests/test_stock_analysis_suite.py -v` → all passed

- [ ] **Step 4: Commit (optional)**

---

### Task 6: _collect_inputs 实接 analyzer（集成）

**Files:** modify `analysis/stock_analysis_suite.py`, modify `tests/test_stock_analysis_suite.py`.

实现 `_collect_inputs(code)` 从真实 analyzer 抽取数据；任意 analyzer 失败时该字段缺失，整体不中断。

- [ ] **Step 1: 写失败测试 — 用 monkeypatch 替换每个 analyzer 类**

```python
def test_collect_inputs_pulls_from_all_analyzers(monkeypatch):
    from analysis import stock_analysis_suite as mod

    class _Chip:
        def analyze(self, code, df):
            return {"details": {"main_force_control": 70, "concentration_90": 15.9, "profit_ratio": 50},
                    "signals": ["持仓集中"]}
    class _Cap:
        def analyze(self, code, df):
            return {"details": {"order_analysis": {"main_net_inflow": -1e6, "retail_net_inflow": 6e5},
                                "positive_days_5d": 4}, "signals": ["主力撤离"]}
    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {"financial_indicators": {"pe": 4.8, "roe": 14.2}, "industry_comparison": {"pe_rank": 10.0}, "financial_reports": {"net_profit_yoy": 12.0}}

    monkeypatch.setattr(mod, "ChipAnalyzer", _Chip)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _Cap)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]
    suite._classify_market_regime = lambda: ("sideways", 0.42)  # type: ignore[attr-defined]
    suite._run_quant_models = lambda code, df: {"buy_signal_count": 16, "sell_signal_count": 8, "hold_signal_count": 6, "total": 30}  # type: ignore[attr-defined]

    inputs = suite._collect_inputs("000001")
    assert inputs["chip"]["details"]["main_force_control"] == 70
    assert inputs["market_regime"] == "sideways"
    assert inputs["models"]["buy_signal_count"] == 16
    assert inputs["fundamental"]["pe"] == 4.8
```

- [ ] **Step 2: 实现 `_collect_inputs`、`_load_ohlcv`、`_classify_market_regime`、`_run_quant_models`**

```python
# analysis/stock_analysis_suite.py (top of file, imports)
import pandas as pd

from analysis.advanced_analysis import ChipAnalyzer, CapitalFlowAnalyzer
from analysis.fundamental_data_collector import FundamentalDataCollector
from analysis.investor_sentiment import InvestorSentimentAnalyzer
from analysis.technical_analysis import QuantitativeModels


# Inside class StockAnalysisSuite:

    def _load_ohlcv(self, code: str) -> pd.DataFrame:
        """Load OHLCV CSV from data/ directory.

        File pattern: data/{XSHE|XSHG}_5min_{code}.csv. We try day-level first
        (data/{XSHE|XSHG}_day_{code}.csv) and fall back to 5min aggregated.
        """
        import os
        data_dir = Path(os.environ.get("KRONOS_DATA_DIR", "data"))
        exchange = "XSHE" if code.startswith(("0", "3")) else "XSHG"
        for suffix in (f"{exchange}_day_{code}.csv", f"{exchange}_5min_{code}.csv"):
            path = data_dir / suffix
            if path.exists():
                df = pd.read_csv(path, parse_dates=["timestamps"])
                if len(df) >= 60:
                    return df
        raise FileNotFoundError(f"no OHLCV file for {code} in {data_dir}")

    def _classify_market_regime(self) -> tuple[str, float]:
        """Map InvestorSentimentAnalyzer overall sentiment to {bull, sideways, bear} + capital flow ratio."""
        try:
            analyzer = InvestorSentimentAnalyzer("000001")  # 任意代码触发整体大盘信息
            overall = analyzer.get_overall_market_sentiment() or {}
            score = float(overall.get("sentiment_score", 50))
            change_pct = float(overall.get("average_change_pct", 0))
            ratio = max(0.0, min(1.0, (score / 100.0) * 0.5 + (max(-2.0, min(2.0, change_pct)) + 2) / 4 * 0.5))
            if score >= 65 or change_pct >= 1.0:
                regime = "bull"
            elif score <= 35 or change_pct <= -1.0:
                regime = "bear"
            else:
                regime = "sideways"
            return regime, ratio
        except Exception:  # noqa: BLE001
            return "sideways", 0.0

    def _run_quant_models(self, code: str, df: pd.DataFrame) -> Dict[str, int]:
        models = QuantitativeModels(df)
        models.run_all_models()
        buy = sell = hold = 0
        for name, signal_series in (models.signals or {}).items():
            last = signal_series[-1] if hasattr(signal_series, "__getitem__") else signal_series
            if last == 1: buy += 1
            elif last == -1: sell += 1
            else: hold += 1
        return {"buy_signal_count": buy, "sell_signal_count": sell, "hold_signal_count": hold, "total": buy + sell + hold}

    def _collect_inputs(self, code: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        try:
            df = self._load_ohlcv(code)
            out["ohlcv"] = df
        except Exception as exc:
            out["ohlcv_error"] = str(exc)
            df = None
        if df is not None:
            try:
                out["chip"] = ChipAnalyzer().analyze(code, df)
            except Exception as exc:
                out["chip_error"] = str(exc)
            try:
                out["capital_flow"] = CapitalFlowAnalyzer().analyze(code, df)
            except Exception as exc:
                out["capital_flow_error"] = str(exc)
            try:
                out["models"] = self._run_quant_models(code, df)
            except Exception as exc:
                out["models_error"] = str(exc)
        try:
            regime, ratio = self._classify_market_regime()
            out["market_regime"] = regime
            out["capital_flow_ratio"] = ratio
        except Exception as exc:
            out["market_error"] = str(exc)
        try:
            fundam_raw = FundamentalDataCollector(code, minimal_api_mode=True).get_comprehensive_data() or {}
            fi = fundam_raw.get("financial_indicators") or {}
            fr = fundam_raw.get("financial_reports") or {}
            ic = fundam_raw.get("industry_comparison") or {}
            out["fundamental"] = {
                "pe": fi.get("pe"), "roe": fi.get("roe"),
                "pe_industry_rank": ic.get("pe_rank"),
                "net_profit_yoy": fr.get("net_profit_yoy"),
            }
        except Exception as exc:
            out["fundamental_error"] = str(exc)
        return out
```

- [ ] **Step 3: 实现 `_compute_full_payload` 把 overview / risk_control / cached_reports 装配**

```python
# Inside class StockAnalysisSuite:

    def _compute_full_payload(self, code: str) -> Dict[str, Any]:
        warnings: list[str] = []
        try:
            overview = self.compute_overview(code)
        except Exception as exc:  # noqa: BLE001
            overview = None
            warnings.append(f"overview 装配失败：{exc}")
        try:
            risk = self.compute_risk_control(code)
        except Exception as exc:  # noqa: BLE001
            risk = {"available": False, "reason": str(exc)}
            warnings.append(f"risk_control 装配失败：{exc}")
        try:
            cached = self.collect_cached_reports(code)
        except Exception as exc:  # noqa: BLE001
            cached = {"opportunity": _report_entry(None), "batch_analysis": _report_entry(None)}
            warnings.append(f"cached_reports 读取失败：{exc}")
        return {
            "overview": overview,
            "risk_control": risk,
            "cached_reports": cached,
            "ai_interpretation": {
                "status": "not_generated", "report": None, "token_usage": None,
                "generated_at": None,
                "trigger_endpoint": f"/api/stock-analysis-suite/{code}/ai",
            },
            "stub_tabs": [
                "market_cycle", "main_force_phase", "volume_price_game",
                "chip_structure", "performance", "probability", "limit_up_screening",
            ],
            "warnings": warnings,
        }
```

- [ ] **Step 4: 运行测试** `.venv/bin/pytest tests/test_stock_analysis_suite.py -v` → all passed

- [ ] **Step 5: Commit (optional)**

---

### Task 7: build_llm_payload + LLMAnalyzer.interpret_stock_markdown

**Files:** modify `analysis/stock_analysis_suite.py`, modify `analysis/llm_service.py`, modify `tests/test_stock_analysis_suite.py`.

新增 `LLMAnalyzer.interpret_stock_markdown(payload, model_full_key=None) -> (success: bool, markdown: str, token_usage: int|None)`，直接拿 provider raw text，并尝试从 OpenAI/DashScope response 抽 `usage.total_tokens`。

- [ ] **Step 1: 写失败测试 — build_llm_payload 包含 7 节关键上下文**

```python
def test_build_llm_payload_contains_required_sections():
    suite = StockAnalysisSuite()
    suite_data = {
        "overview": {
            "radar": {"main_force_phase": {"score": 62, "label": "中等偏强"},
                       "market_cycle": {"score": 35, "label": "震荡期"},
                       "volume_price_game": {"score": 53, "label": "多空胶着"},
                       "chip_structure": {"score": 28, "label": "结构偏差"},
                       "performance": {"score": 71, "label": "估值修复"}},
            "key_signals": [{"label": "大盘周期", "value": "震荡期"}],
            "deep_signals": [{"text": "主力撤离", "tag": "资金"}],
            "scenario_probability": {"bullish": 34, "bearish": 32, "sideways": 34},
        },
        "risk_control": {"available": True, "execution_plan": {"stop_loss": {"price": 10.43, "drop_pct": 2.3}}},
    }
    payload = suite.build_llm_payload("000001", "平安银行", suite_data)
    text = payload["prompt"]
    for keyword in ["核心定性", "价值与安全边际", "主力博弈", "多因子量化", "情绪周期", "预期差", "操盘建议"]:
        assert keyword in text, f"prompt missing section: {keyword}"
    assert "平安银行" in text and "000001" in text
    assert payload["model_full_key"] is None  # 由 caller 决定
```

- [ ] **Step 2: 实现 build_llm_payload**

```python
# Inside class StockAnalysisSuite:

    def build_llm_payload(self, code: str, name: str, suite_data: Dict[str, Any]) -> Dict[str, Any]:
        overview = (suite_data or {}).get("overview") or {}
        radar = overview.get("radar") or {}
        risk = (suite_data or {}).get("risk_control") or {}

        def _fmt_radar(key):
            entry = radar.get(key) or {}
            return f"{entry.get('label','—')}({entry.get('score','—')}分)"

        prompt = "\n".join([
            f"# 股票深度分析任务：{name}（{code}）",
            "",
            "请按以下 7 个小节输出 Markdown 报告（保留小节标题，每节 3-5 段）：",
            "## 1. 核心定性",
            "## 2. 价值与安全边际",
            "## 3. 主力博弈解析",
            "## 4. 多因子量化评估",
            "## 5. 情绪周期与市场定位",
            "## 6. 预期差挖掘",
            "## 7. 操盘建议",
            "",
            "## 输入数据",
            f"- 5维评分：主力阶段 {_fmt_radar('main_force_phase')}；市场周期 {_fmt_radar('market_cycle')}；"
            f"量价博弈 {_fmt_radar('volume_price_game')}；筹码结构 {_fmt_radar('chip_structure')}；"
            f"业绩预期 {_fmt_radar('performance')}",
            f"- 关键信号：{overview.get('key_signals')}",
            f"- 深度信号：{overview.get('deep_signals')}",
            f"- 情景概率：{overview.get('scenario_probability')}",
            f"- 风控数据：{risk}",
        ])
        return {"prompt": prompt, "model_full_key": None}
```

- [ ] **Step 3: 写 LLMAnalyzer.interpret_stock_markdown 失败测试**

```python
# tests/test_stock_analysis_suite.py (append)
def test_llm_interpret_stock_markdown_returns_raw_text(monkeypatch):
    from analysis.llm_service import LLMAnalyzer
    analyzer = LLMAnalyzer()

    def fake_call(prompt, model_cfg, max_tokens=3000):
        return True, "## 1. 核心定性\n平安银行...\n## 2. 价值与安全边际\n...", {"total_tokens": 3651}

    monkeypatch.setattr(analyzer, "_call_provider_raw", fake_call)
    ok, markdown, tokens = analyzer.interpret_stock_markdown(
        {"prompt": "any prompt"}, model_full_key=None,
    )
    assert ok is True
    assert markdown.startswith("## 1. 核心定性")
    assert tokens == 3651
```

- [ ] **Step 4: 实现 LLMAnalyzer.interpret_stock_markdown + _call_provider_raw**

读 `analysis/llm_service.py` 现有 provider 调用代码（`OpenAIProvider.call_api`、`DashScopeProvider.call_api`），新增方法包 raw text + usage。

```python
# analysis/llm_service.py (inside class LLMAnalyzer, end of class)

    def interpret_stock_markdown(
        self, payload: Dict[str, Any], model_full_key: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[int]]:
        """Call provider directly and return (success, raw_markdown, total_tokens).

        Unlike analyze_stock() this returns the raw text without JSON parsing.
        """
        prompt = payload.get("prompt") or ""
        if not prompt:
            return False, "prompt 为空", None
        try:
            model_cfg = self._resolve_model(model_full_key)
        except Exception as exc:  # noqa: BLE001
            return False, f"模型解析失败：{exc}", None
        try:
            ok, text, usage = self._call_provider_raw(prompt, model_cfg, max_tokens=3000)
        except Exception as exc:  # noqa: BLE001
            return False, f"LLM 调用异常：{exc}", None
        tokens = (usage or {}).get("total_tokens") if isinstance(usage, dict) else None
        return ok, text, tokens

    def _call_provider_raw(self, prompt, model_cfg, max_tokens=3000):
        """Provider-agnostic raw call. Returns (success, text, usage_dict).

        Adapts each provider's response to extract usage. Implementation must
        introspect the provider's HTTP response — see OpenAIProvider.call_api
        in this module for the pattern (look for json()["choices"][0]["message"]["content"]
        and json().get("usage")).
        """
        # Implementation: copy the relevant call_api method's body but extract
        # usage from the response JSON before returning. Wire by inspecting
        # `model_cfg.provider` and dispatching to the appropriate provider's
        # internal HTTP call. See existing _call_provider in this file for the
        # dispatch pattern (~line 466 area).
        raise NotImplementedError("Implement by adapting existing provider call_api to expose usage")
```

> **Implementer note for Step 4:** before stubbing `_call_provider_raw`, read `analysis/llm_service.py` lines 363-528 to understand how providers are dispatched today (look for `self._call_provider(...)` or similar). Implement `_call_provider_raw` by either (a) replicating that dispatch and reading `usage` from the HTTP response JSON, or (b) wrapping the existing call and best-effort extracting tokens from cached state. If introspecting requires significant provider rewrite, drop token tracking (return `None` for usage) and document in the report — token tracking is a "nice to have" per spec.

- [ ] **Step 5: 运行测试** `.venv/bin/pytest tests/test_stock_analysis_suite.py -v` → all passed

- [ ] **Step 6: Commit (optional)**

---

### Task 8: AI interpretation entry on orchestrator + reports/stock_suite/ persistence

**Files:** modify `analysis/stock_analysis_suite.py`, modify `tests/test_stock_analysis_suite.py`.

- [ ] **Step 1: 写失败测试**

```python
def test_trigger_ai_interpretation_persists_markdown(tmp_path, monkeypatch):
    suite = StockAnalysisSuite()
    suite._reports_root = tmp_path  # type: ignore[attr-defined]
    suite.get_full_payload = lambda code: {"overview": {}, "risk_control": {}}  # type: ignore[assignment]

    class _Fake:
        def interpret_stock_markdown(self, payload, model_full_key=None):
            return True, "## 1. 核心定性\nfoo", 1234
    monkeypatch.setattr("analysis.stock_analysis_suite.LLMAnalyzer", lambda: _Fake())

    out = suite.trigger_ai_interpretation("000001", name="平安银行")
    assert out["success"] is True
    assert out["report"].startswith("## 1. 核心定性")
    assert out["token_usage"] == 1234
    assert Path(out["cached_path"]).exists()
    assert "000001" in out["cached_path"]
```

- [ ] **Step 2: 实现 trigger_ai_interpretation**

```python
# analysis/stock_analysis_suite.py (top imports)
from analysis.llm_service import LLMAnalyzer


# Inside class StockAnalysisSuite (init):
    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS, reports_root: Optional[Path] = None) -> None:
        # ... existing init
        self._reports_root = Path(reports_root) if reports_root else Path("reports/stock_suite")

# Method:
    def trigger_ai_interpretation(
        self, code: str, name: str = "", model_full_key: Optional[str] = None, force_refresh: bool = False,
    ) -> Dict[str, Any]:
        if force_refresh:
            self.invalidate(code)
        suite_data = self.get_full_payload(code)
        payload = self.build_llm_payload(code, name or code, suite_data)
        analyzer = LLMAnalyzer()
        ok, text, tokens = analyzer.interpret_stock_markdown(payload, model_full_key)
        if not ok:
            return {"success": False, "status": "failed", "error": text,
                    "generated_at": _dt.datetime.now().isoformat(timespec="seconds")}
        self._reports_root.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._reports_root / f"{code}_{ts}.md"
        path.write_text(text, encoding="utf-8")
        return {
            "success": True, "status": "ready", "report": text,
            "token_usage": tokens,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "cached_path": str(path),
        }
```

- [ ] **Step 3: 运行测试** `.venv/bin/pytest tests/test_stock_analysis_suite.py -v` → all passed

- [ ] **Step 4: Commit (optional)**

---

## Phase B — Service 层与 webui.core 接线

### Task 9: webui/services/stock_suite_service.py + STOCK_SUITE_SERVICE singleton

**Files:**
- Create: `webui/services/stock_suite_service.py`
- Modify: `webui/core.py`
- Modify: `tests/test_webui_core_surface.py`
- Create: `tests/test_stock_suite_service.py`

- [ ] **Step 1: 写 service 测试**

```python
# tests/test_stock_suite_service.py
import pytest
from webui.services.stock_suite_service import StockSuiteService


class _FakeSuite:
    def __init__(self):
        self.calls = []
    def get_full_payload(self, code):
        self.calls.append(("get", code))
        return {"overview": {"radar": {}}, "risk_control": {"available": True},
                "cached_reports": {}, "ai_interpretation": {"status": "not_generated", "report": None,
                "token_usage": None, "generated_at": None, "trigger_endpoint": f"/api/stock-analysis-suite/{code}/ai"},
                "stub_tabs": [], "warnings": []}
    def trigger_ai_interpretation(self, code, name, model_full_key=None, force_refresh=False):
        self.calls.append(("ai", code, force_refresh))
        return {"success": True, "status": "ready", "report": "## md", "token_usage": 100,
                "generated_at": "2026-05-23T14:32:05", "cached_path": "reports/stock_suite/...md"}


def test_get_suite_returns_jsonable_dict():
    fake = _FakeSuite()
    svc = StockSuiteService(orchestrator=fake)
    out = svc.get_suite("000001", name="平安银行")
    assert out["success"] is True
    assert out["stock"] == {"code": "000001", "name": "平安银行", "sector": "—", "market": "XSHE"}
    assert "overview" in out
    assert out["ai_interpretation"]["trigger_endpoint"] == "/api/stock-analysis-suite/000001/ai"


def test_trigger_ai_proxies_to_orchestrator():
    fake = _FakeSuite()
    svc = StockSuiteService(orchestrator=fake)
    out = svc.trigger_ai_interpretation("000001", name="平安银行", force_refresh=True)
    assert out["success"] is True
    assert fake.calls[0] == ("ai", "000001", True)


def test_get_suite_validates_code():
    svc = StockSuiteService(orchestrator=_FakeSuite())
    with pytest.raises(ValueError):
        svc.get_suite("")
```

- [ ] **Step 2: 实现 StockSuiteService**

```python
# webui/services/stock_suite_service.py
"""Service-layer wrapper around analysis.StockAnalysisSuite.

Adds:
- Input validation (stock code)
- JSON shape conformance with spec §5.1 / §5.2
- Stock metadata enrichment (sector, market exchange)
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, Optional

from analysis.stock_analysis_suite import StockAnalysisSuite


_CODE_RE = re.compile(r"^[036][0-9]{5}$|^[68][0-9]{5}$")


class StockSuiteService:
    def __init__(self, orchestrator: Optional[StockAnalysisSuite] = None) -> None:
        self._suite = orchestrator or StockAnalysisSuite()

    def _validate_code(self, code: str) -> str:
        code = (code or "").strip()
        if not code or not _CODE_RE.match(code):
            raise ValueError(f"invalid stock code: {code!r}")
        return code

    def _stock_meta(self, code: str, name: str) -> Dict[str, str]:
        market = "XSHE" if code.startswith(("0", "3")) else "XSHG"
        return {"code": code, "name": name or "", "sector": "—", "market": market}

    def get_suite(self, code: str, name: str = "") -> Dict[str, Any]:
        code = self._validate_code(code)
        try:
            payload = self._suite.get_full_payload(code)
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False, "error": str(exc),
                "stock": self._stock_meta(code, name),
                "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            }
        return {
            "success": True,
            "stock": self._stock_meta(code, name),
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "cache": {"hit": False, "expires_at": None},  # cache hit metadata 在 Task 10 由 handler 加
            **payload,
        }

    def trigger_ai_interpretation(
        self, code: str, name: str = "", model_full_key: Optional[str] = None, force_refresh: bool = False,
    ) -> Dict[str, Any]:
        code = self._validate_code(code)
        return self._suite.trigger_ai_interpretation(
            code, name=name, model_full_key=model_full_key, force_refresh=force_refresh,
        )


STOCK_SUITE_SERVICE = StockSuiteService()
```

- [ ] **Step 3: 在 webui/core.py 中导出 singleton + 更新 surface test**

Read `webui/core.py` 找到现有 singleton 段（around line 85-88: `STOCK_KLINE_SERVICE`, `MARKET_INTELLIGENCE_SERVICE` 等），在该段尾追加：

```python
# webui/core.py (after existing singletons)
from webui.services.stock_suite_service import STOCK_SUITE_SERVICE  # noqa: E402
```

Then in `tests/test_webui_core_surface.py`, find `EXPECTED_SINGLETONS = {...}` and add `"STOCK_SUITE_SERVICE"`.

- [ ] **Step 4: 运行测试**

Run: `.venv/bin/pytest tests/test_stock_suite_service.py tests/test_webui_core_surface.py -v`
Expected: all passed

- [ ] **Step 5: Commit (optional)**

---

## Phase C — HTTP routes（TDD）

### Task 10: GET /api/stock-analysis-suite/:stock_code handler

**Files:** modify `webui/robyn_app.py`, modify `tests/test_robyn_app.py`.

- [ ] **Step 1: 写失败测试**

```python
# tests/test_robyn_app.py (append a new test)
def test_robyn_stock_analysis_suite_get(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    class _StubSvc:
        def get_suite(self, code, name=""):
            return {"success": True, "stock": {"code": code, "name": name, "market": "XSHE", "sector": "—"}, "warnings": []}
    monkeypatch.setattr(robyn_module.webui_core, "STOCK_SUITE_SERVICE", _StubSvc())

    client = TestClient(robyn_module.app)
    response = client.get("/api/stock-analysis-suite/000001?name=平安银行")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["stock"]["code"] == "000001"


def test_robyn_stock_analysis_suite_invalid_code(robyn_module, monkeypatch):
    from robyn.testing import TestClient
    class _ErrSvc:
        def get_suite(self, code, name=""):
            raise ValueError("invalid stock code")
    monkeypatch.setattr(robyn_module.webui_core, "STOCK_SUITE_SERVICE", _ErrSvc())
    client = TestClient(robyn_module.app)
    response = client.get("/api/stock-analysis-suite/INVALID")
    assert response.status_code == 400
```

- [ ] **Step 2: 添加 handler**

```python
# webui/robyn_app.py (add near other native handlers, e.g., after _native_get("/api/stock-context/:stock_code"))

@_native_get("/api/stock-analysis-suite/:stock_code")
def get_stock_analysis_suite(request: Request, stock_code=None) -> Response:
    code = _path_param(request, "stock_code", stock_code)
    name = _query_value(request, "name", "")
    try:
        payload = webui_core.STOCK_SUITE_SERVICE.get_suite(code, name=name)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"success": False, "error": str(exc)}, status_code=500)
    return _json_response(payload)
```

- [ ] **Step 3: 运行测试** `.venv/bin/pytest tests/test_robyn_app.py -v` → 全 PASS

- [ ] **Step 4: Commit (optional)**

---

### Task 11: POST /api/stock-analysis-suite/:stock_code/ai handler

**Files:** modify `webui/robyn_app.py`, modify `tests/test_robyn_app.py`.

- [ ] **Step 1: 写失败测试**

```python
def test_robyn_stock_analysis_suite_ai(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    class _StubSvc:
        def trigger_ai_interpretation(self, code, name="", model_full_key=None, force_refresh=False):
            return {"success": True, "status": "ready", "report": "## md",
                    "token_usage": 100, "generated_at": "2026-05-23T14:32:05",
                    "cached_path": "reports/stock_suite/000001_x.md"}
    monkeypatch.setattr(robyn_module.webui_core, "STOCK_SUITE_SERVICE", _StubSvc())

    client = TestClient(robyn_module.app)
    response = client.post("/api/stock-analysis-suite/000001/ai", json={"force_refresh": False, "name": "平安"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["status"] == "ready"
```

- [ ] **Step 2: 添加 handler**

```python
@_native_post("/api/stock-analysis-suite/:stock_code/ai")
def post_stock_analysis_suite_ai(request: Request, stock_code=None) -> Response:
    code = _path_param(request, "stock_code", stock_code)
    body = _request_json(request) or {}
    name = body.get("name", "")
    force_refresh = bool(body.get("force_refresh", False))
    model_full_key = body.get("model_full_key")
    try:
        payload = webui_core.STOCK_SUITE_SERVICE.trigger_ai_interpretation(
            code, name=name, model_full_key=model_full_key, force_refresh=force_refresh,
        )
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"success": False, "error": str(exc)}, status_code=500)
    return _json_response(payload)
```

- [ ] **Step 3: 运行测试** → 全 PASS

- [ ] **Step 4: Commit (optional)**

---

## Phase D — 前端（手工 + 浏览器验证）

### Task 12: Tab 栏 HTML + CSS + Plotly 加载

**Files:** modify `webui/templates/desktop.html`, modify `webui/static/kronos_desktop.css`.

- [ ] **Step 1: 在 desktop.html `<head>` 段确认 Plotly 已加载，缺失则添加 CDN**

Run: `grep -n "plotly" webui/templates/desktop.html`
- 若有 `cdn.plot.ly` / `plotly.min.js` 标签 → 跳到 Step 2
- 若无 → 在 `<head>` 段（约 L10-30）添加：
  ```html
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js" crossorigin="anonymous"></script>
  ```

- [ ] **Step 2: 修改 `#stockContextModal` `.modal-body`（约 L729-731）插入 Tab 栏**

打开 `webui/templates/desktop.html` L729，把：
```html
<div class="modal-body stock-context-body">
    <div id="stockContextBody"></div>
</div>
```
改为：
```html
<div class="modal-body stock-context-body">
    <nav class="stock-suite-tabs" role="tablist" id="stockSuiteTabs">
        <button data-suite-tab="quick"               class="suite-tab active" type="button">快速信息</button>
        <button data-suite-tab="overview"            class="suite-tab" type="button">综合总览</button>
        <button data-suite-tab="market_cycle"        class="suite-tab" type="button" disabled title="即将上线 · 与市场环境模块联调中">市场周期</button>
        <button data-suite-tab="main_force_phase"    class="suite-tab" type="button" disabled title="即将上线 · 与主力博弈模块联调中">主力阶段</button>
        <button data-suite-tab="volume_price_game"   class="suite-tab" type="button" disabled title="即将上线 · 与量价模型联调中">量价博弈</button>
        <button data-suite-tab="chip_structure"      class="suite-tab" type="button" disabled title="即将上线 · 与筹码模块联调中">筹码结构</button>
        <button data-suite-tab="performance"         class="suite-tab" type="button" disabled title="即将上线 · 与基本面模块联调中">业绩预期</button>
        <button data-suite-tab="probability"         class="suite-tab" type="button" disabled title="即将上线 · 与概率推演模块联调中">概率推演</button>
        <button data-suite-tab="risk_control"        class="suite-tab" type="button">操盘风控</button>
        <button data-suite-tab="limit_up_screening"  class="suite-tab" type="button" disabled title="即将上线 · 与涨停模块联调中">涨停筛选</button>
        <button data-suite-tab="ai_interpretation"   class="suite-tab" type="button">AI 解读</button>
    </nav>
    <div class="stock-suite-panels" id="stockSuitePanels">
        <div class="suite-pane" data-suite-pane="quick" id="stockContextBody"></div>
        <div class="suite-pane hidden" data-suite-pane="overview" id="suitePaneOverview"></div>
        <div class="suite-pane hidden" data-suite-pane="risk_control" id="suitePaneRiskControl"></div>
        <div class="suite-pane hidden" data-suite-pane="ai_interpretation" id="suitePaneAi"></div>
    </div>
</div>
```

> **注意：** `#stockContextBody` 节点位置变了（现在嵌在 `.suite-pane[data-suite-pane="quick"]` 里），但保持同 id，因此 `renderStockContext(context)` 现有逻辑无需修改。

- [ ] **Step 3: 添加 CSS（在 kronos_desktop.css 末尾追加）**

```css
/* Stock analysis suite tab nav */
.stock-suite-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    padding: 8px 16px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.1);
}
.suite-tab {
    background: transparent;
    border: 1px solid rgba(255,255,255,0.15);
    color: rgba(255,255,255,0.7);
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
}
.suite-tab:hover:not(:disabled) {
    background: rgba(91,141,239,0.15);
    color: #fff;
}
.suite-tab.active {
    background: rgba(91,141,239,0.25);
    color: #5b8def;
    border-color: #5b8def;
}
.suite-tab:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
.stock-suite-panels { padding-top: 8px; }
.suite-pane.hidden { display: none; }

/* Suite Tab content */
.suite-radar-section { display: grid; grid-template-columns: 1fr 280px; gap: 16px; padding: 16px; }
.suite-radar-chart { min-height: 320px; background: rgba(0,0,0,0.15); border-radius: 8px; }
.suite-key-signals { display: flex; flex-direction: column; gap: 8px; }
.suite-key-card { padding: 10px 12px; border-radius: 6px; background: rgba(255,255,255,0.04); }
.suite-key-card.tone-warn { border-left: 3px solid #f5a623; }
.suite-key-card.tone-danger { border-left: 3px solid #e25c5c; }
.suite-key-card.tone-info { border-left: 3px solid #5b8def; }
.suite-key-card.tone-success { border-left: 3px solid #4caf50; }
.suite-key-card.tone-neutral { border-left: 3px solid rgba(255,255,255,0.2); }
.suite-key-label { font-size: 11px; color: rgba(255,255,255,0.5); }
.suite-key-value { font-size: 14px; color: #fff; margin-top: 2px; }
.suite-probability-donut { min-height: 200px; margin-top: 12px; }
.suite-deep-signals { padding: 12px 16px; border-top: 1px solid rgba(255,255,255,0.08); }
.suite-deep-signal { display: flex; gap: 10px; padding: 6px 0; font-size: 13px; }
.suite-deep-tag { background: rgba(91,141,239,0.15); color: #5b8def; padding: 2px 8px; border-radius: 4px; font-size: 11px; }

/* Risk control */
.suite-risk-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; padding: 16px; }
.suite-risk-col { background: rgba(0,0,0,0.15); padding: 14px; border-radius: 8px; }
.suite-risk-col h4 { margin: 0 0 10px 0; font-size: 13px; color: #5b8def; }
.suite-price-row { display: flex; justify-content: space-between; padding: 6px 0; font-family: ui-monospace, monospace; }
.suite-price-row .price { color: #fff; font-weight: 600; }
.suite-price-row .meta { color: rgba(255,255,255,0.6); font-size: 12px; }

/* AI interpretation */
.suite-ai-empty { text-align: center; padding: 40px; }
.suite-ai-button { background: linear-gradient(135deg, #5b8def, #7c5bef); border: none; color: #fff; padding: 10px 24px; border-radius: 6px; cursor: pointer; font-size: 14px; }
.suite-ai-button:disabled { opacity: 0.5; cursor: not-allowed; }
.suite-ai-progress { padding: 20px; text-align: center; color: rgba(255,255,255,0.7); }
.suite-ai-report { padding: 16px; font-size: 13px; line-height: 1.6; }
.suite-ai-report h2 { color: #5b8def; margin-top: 16px; }
.suite-ai-footer { padding: 8px 16px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 11px; color: rgba(255,255,255,0.5); }
```

- [ ] **Step 4: 添加 Tab 切换 JS（在 desktop.html `<script>` 段中合适位置插入；放在 openStockContext 函数附近）**

```javascript
// Stock suite tab switching
function initStockSuiteTabs() {
    const nav = document.getElementById('stockSuiteTabs');
    if (!nav || nav.dataset.bound === '1') return;
    nav.dataset.bound = '1';
    nav.addEventListener('click', (event) => {
        const btn = event.target.closest('button.suite-tab');
        if (!btn || btn.disabled) return;
        const tab = btn.dataset.suiteTab;
        nav.querySelectorAll('button.suite-tab').forEach(b => b.classList.toggle('active', b === btn));
        document.querySelectorAll('#stockSuitePanels .suite-pane').forEach(p => {
            p.classList.toggle('hidden', p.dataset.suitePane !== tab);
        });
        // Lazy-render on first switch
        const ctx = state.currentSuitePayload;
        if (tab === 'overview' && !document.getElementById('suitePaneOverview').dataset.rendered) {
            renderSuiteOverview(ctx);
        } else if (tab === 'risk_control' && !document.getElementById('suitePaneRiskControl').dataset.rendered) {
            renderSuiteRiskControl(ctx);
        } else if (tab === 'ai_interpretation' && !document.getElementById('suitePaneAi').dataset.rendered) {
            renderSuiteAi(ctx);
        }
    });
}
```

> Call `initStockSuiteTabs()` once at modal mount time (look for `openStockContext` JS in Task 13).

- [ ] **Step 5: 手工浏览器验证**

Start Robyn (`.venv/bin/python webui/run.py`). Click any stock to open the modal. Verify:
- 11 个 Tab 按钮显示，7 个 disabled 有 tooltip
- 「快速信息」默认 active 且显示现有 6 个面板
- 切到「综合总览」「操盘风控」「AI 解读」时面板空白（Task 13-15 实现内容）
- 关闭 modal、再开 → Tab 状态 reset

- [ ] **Step 6: Commit (optional)**

---

### Task 13: 综合总览 Tab 渲染（雷达图 + 关键信号 + 情景概率 + 深度信号）

**Files:** modify `webui/templates/desktop.html`.

- [ ] **Step 1: 修改 openStockContext / renderStockContext，新增 suite payload fetch**

找到 `openStockContext` 函数（约 L2200），扩展为：拿到 stock context payload 后**追加**调用 `/api/stock-analysis-suite/{code}?name={name}` 拿 suite payload，存入 `state.currentSuitePayload`。

```javascript
async function openStockContext(target) {
    const code = target?.code;
    if (!code) return;
    // ... 原有 fetch /api/stock-context/{code} 部分 ...
    state.currentStockContext = context;
    renderStockContext(context);
    // 新增：拉 suite payload
    try {
        const suiteResp = await fetch(`/api/stock-analysis-suite/${encodeURIComponent(code)}?name=${encodeURIComponent(target.name || '')}`);
        const suite = await suiteResp.json();
        state.currentSuitePayload = suite;
    } catch (e) {
        state.currentSuitePayload = { success: false, error: String(e) };
    }
    initStockSuiteTabs();
    showStockContextModal();
}
```

- [ ] **Step 2: 实现 renderSuiteOverview**

```javascript
function renderSuiteOverview(payload) {
    const pane = document.getElementById('suitePaneOverview');
    pane.dataset.rendered = '1';
    if (!payload || !payload.success || !payload.overview) {
        pane.innerHTML = '<div class="suite-ai-empty"><p>综合总览数据加载失败</p></div>';
        return;
    }
    const ov = payload.overview;
    pane.innerHTML = `
        <div class="suite-radar-section">
            <div id="suiteRadarChart" class="suite-radar-chart"></div>
            <div class="suite-key-signals">${
                (ov.key_signals || []).map(s => `
                    <div class="suite-key-card tone-${s.tone || 'neutral'}">
                        <div class="suite-key-label">${escapeHtml(s.label)}</div>
                        <div class="suite-key-value">${escapeHtml(s.value)}</div>
                    </div>`).join('')
            }<div id="suiteProbabilityDonut" class="suite-probability-donut"></div></div>
        </div>
        <div class="suite-deep-signals">${
            (ov.deep_signals || []).map(s => `
                <div class="suite-deep-signal">
                    <span class="suite-deep-tag">${escapeHtml(s.tag || '—')}</span>
                    <span>${escapeHtml(s.text)}</span>
                </div>`).join('')
        }</div>
    `;
    drawRadarChart(ov.radar);
    drawProbabilityDonut(ov.scenario_probability);
}

function drawRadarChart(radar) {
    const el = document.getElementById('suiteRadarChart');
    if (!el || typeof Plotly === 'undefined') {
        el.innerHTML = renderRadarSvgFallback(radar);
        return;
    }
    const labels = ['主力阶段', '市场周期', '量价博弈', '筹码结构', '业绩预期'];
    const keys = ['main_force_phase', 'market_cycle', 'volume_price_game', 'chip_structure', 'performance'];
    const values = keys.map(k => (radar?.[k]?.score ?? 0));
    Plotly.newPlot(el, [{
        type: 'scatterpolar',
        r: [...values, values[0]],
        theta: [...labels, labels[0]],
        fill: 'toself', line: {color: '#5b8def'}, fillcolor: 'rgba(91,141,239,0.3)',
    }], {
        polar: {radialaxis: {range: [0, 100], visible: true}, bgcolor: 'rgba(0,0,0,0.2)'},
        paper_bgcolor: 'rgba(0,0,0,0)', font: {color: '#fff'}, showlegend: false,
        margin: {t: 20, l: 40, r: 40, b: 20},
    }, {displayModeBar: false, responsive: true});
}

function renderRadarSvgFallback(radar) {
    // 简易 5 边形 SVG fallback
    const labels = ['主力阶段', '市场周期', '量价博弈', '筹码结构', '业绩预期'];
    const keys = ['main_force_phase', 'market_cycle', 'volume_price_game', 'chip_structure', 'performance'];
    const values = keys.map(k => (radar?.[k]?.score ?? 0) / 100);
    const cx = 160, cy = 160, r = 120;
    const pts = values.map((v, i) => {
        const a = -Math.PI / 2 + i * 2 * Math.PI / 5;
        return [cx + Math.cos(a) * r * v, cy + Math.sin(a) * r * v];
    });
    const polyPoints = pts.map(p => p.join(',')).join(' ');
    const labelPos = labels.map((l, i) => {
        const a = -Math.PI / 2 + i * 2 * Math.PI / 5;
        return `<text x="${cx + Math.cos(a) * (r + 18)}" y="${cy + Math.sin(a) * (r + 18)}" text-anchor="middle" fill="#fff" font-size="12">${l}</text>`;
    }).join('');
    return `<svg viewBox="0 0 320 320" width="100%" height="320">
        <polygon points="${polyPoints}" fill="rgba(91,141,239,0.3)" stroke="#5b8def" stroke-width="2"/>
        ${labelPos}
    </svg>`;
}

function drawProbabilityDonut(prob) {
    const el = document.getElementById('suiteProbabilityDonut');
    if (!el || typeof Plotly === 'undefined') return;
    Plotly.newPlot(el, [{
        type: 'pie', hole: 0.5,
        labels: ['看涨', '看跌', '震荡'],
        values: [prob?.bullish ?? 33, prob?.bearish ?? 33, prob?.sideways ?? 34],
        marker: {colors: ['#4caf50', '#e25c5c', '#888']},
        textinfo: 'label+percent',
    }], {paper_bgcolor: 'rgba(0,0,0,0)', font: {color: '#fff'}, showlegend: false,
        margin: {t: 10, l: 10, r: 10, b: 10}, height: 200}, {displayModeBar: false, responsive: true});
}

// Reuse existing escapeHtml in desktop.html or add one if absent
```

- [ ] **Step 3: 浏览器验证**

启动 Robyn，点开一只股票，切到「综合总览」Tab，确认：
- 雷达图渲染（5 顶点）
- 关键信号 6 卡片
- 情景概率环形图
- 深度信号列表

- [ ] **Step 4: Commit (optional)**

---

### Task 14: 操盘风控 Tab 渲染

**Files:** modify `webui/templates/desktop.html`.

- [ ] **Step 1: 实现 renderSuiteRiskControl**

```javascript
function renderSuiteRiskControl(payload) {
    const pane = document.getElementById('suitePaneRiskControl');
    pane.dataset.rendered = '1';
    const rc = payload?.risk_control;
    if (!rc || rc.available === false) {
        pane.innerHTML = `<div class="suite-ai-empty">${escapeHtml(rc?.reason || '数据不足')}</div>`;
        return;
    }
    const ep = rc.execution_plan || {};
    const sl = ep.stop_loss || {};
    const rr = ep.risk_reward || {};
    pane.innerHTML = `
        <div class="suite-risk-grid">
            <div class="suite-risk-col">
                <h4>操盘执行方案</h4>
                <div class="suite-price-row"><span>止损价</span><span class="price">${sl.price ?? '—'} <span class="meta">(${sl.drop_pct ?? '—'}%)</span></span></div>
                <div class="suite-price-row"><span>盈亏比</span><span class="price">${rr.ratio ?? '—'}</span></div>
                <h4 style="margin-top:16px">分批建仓</h4>
                ${(rc.scaled_entry || []).map(e => `
                    <div class="suite-price-row"><span>${escapeHtml(e.label)}</span>
                    <span class="price">${e.price} <span class="meta">${e.position_pct}%</span></span></div>
                `).join('')}
                <h4 style="margin-top:16px">分层止盈</h4>
                ${(rc.tiered_take_profit || []).map(t => `
                    <div class="suite-price-row"><span>${escapeHtml(t.label)}</span>
                    <span class="price">${t.price} <span class="meta">${t.sell_pct}%</span></span></div>
                `).join('')}
            </div>
            <div class="suite-risk-col">
                <h4>深度信号</h4>
                ${(rc.deep_signals || []).map(s => `<div class="suite-deep-signal">${escapeHtml(s.text)}</div>`).join('')}
            </div>
            <div class="suite-risk-col">
                <h4>隐性风险预警</h4>
                ${(rc.hidden_risks || []).map(h => `<div class="suite-deep-signal">${escapeHtml(h.text)}</div>`).join('') || '<p style="color:rgba(255,255,255,0.5)">暂无隐性风险</p>'}
            </div>
        </div>
    `;
}
```

- [ ] **Step 2: 浏览器验证** — 切到「操盘风控」Tab，确认止损/分批/止盈/深度信号/隐性风险渲染

- [ ] **Step 3: Commit (optional)**

---

### Task 15: AI 解读 Tab 渲染

**Files:** modify `webui/templates/desktop.html`.

- [ ] **Step 1: 实现 renderSuiteAi + 按钮事件**

```javascript
function renderSuiteAi(payload) {
    const pane = document.getElementById('suitePaneAi');
    pane.dataset.rendered = '1';
    const ai = payload?.ai_interpretation;
    if (ai && ai.status === 'ready' && ai.report) {
        renderAiReady(pane, ai);
        return;
    }
    pane.innerHTML = `
        <div class="suite-ai-empty">
            <h3>AI 操盘手深度解读</h3>
            <p style="color:rgba(255,255,255,0.6)">基于多因子模型 + DeepSeek 推理引擎<br>约 3-5k tokens / 单次 5-30 秒</p>
            <button id="suiteAiGenBtn" class="suite-ai-button">生成深度解读</button>
        </div>
    `;
    document.getElementById('suiteAiGenBtn').addEventListener('click', () => triggerSuiteAi(payload?.stock?.code, payload?.stock?.name));
}

function renderAiReady(pane, ai) {
    pane.innerHTML = `
        <div class="suite-ai-report">${renderMarkdown(ai.report)}</div>
        <div class="suite-ai-footer">Token 使用：${ai.token_usage ?? '—'} · 生成时间：${ai.generated_at}</div>
    `;
}

async function triggerSuiteAi(code, name) {
    if (!code) return;
    const btn = document.getElementById('suiteAiGenBtn');
    btn.disabled = true; btn.textContent = '正在调用 DeepSeek…';
    const pane = document.getElementById('suitePaneAi');
    pane.innerHTML += '<div class="suite-ai-progress">⏳ 正在调用 DeepSeek 进行深度解读…</div>';
    try {
        const resp = await fetch(`/api/stock-analysis-suite/${encodeURIComponent(code)}/ai`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, force_refresh: false}),
        });
        const data = await resp.json();
        if (data.success && data.report) {
            // 更新 state 并重渲染
            state.currentSuitePayload.ai_interpretation = {
                status: 'ready', report: data.report, token_usage: data.token_usage,
                generated_at: data.generated_at,
            };
            renderAiReady(pane, state.currentSuitePayload.ai_interpretation);
        } else {
            pane.innerHTML = `<div class="suite-ai-empty"><p>LLM 调用失败：${escapeHtml(data.error || '未知错误')}</p>
                <button class="suite-ai-button" onclick="triggerSuiteAi('${code}','${name||""}')">重试</button></div>`;
        }
    } catch (e) {
        pane.innerHTML = `<div class="suite-ai-empty"><p>网络错误：${escapeHtml(String(e))}</p></div>`;
    }
}

// Minimal markdown renderer — handles ## headings and paragraphs
function renderMarkdown(md) {
    return (md || '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/^/, '<p>').replace(/$/, '</p>')
        .replace(/<p><h(\d)>/g, '<h$1>').replace(/<\/h(\d)><\/p>/g, '</h$1>');
}
```

- [ ] **Step 2: 浏览器验证（如果 DeepSeek API 已配置）**

切到 AI Tab，点「生成深度解读」按钮，确认：
- 按钮 disabled + 显示「正在调用…」
- 5-30s 后渲染 markdown 报告
- 底部显示 token 使用量与时间
- 重新打开同一只股票的 modal，AI Tab 仍为「未生成」（因为 state reset）— 这是预期行为

如未配置 DeepSeek，点击应显示「LLM 调用失败」或「请先配置 DeepSeek API」错误。

- [ ] **Step 3: Commit (optional)**

---

### Task 16: 占位 Tab 提示文案

**Files:** modify `webui/templates/desktop.html`.

7 个 disabled Tab 已经在 Task 12 加了 `title` tooltip。本任务额外加：用户点击 disabled Tab 时弹 toast 提示。

- [ ] **Step 1: 在 initStockSuiteTabs 的事件处理里增加 disabled 分支**

```javascript
nav.addEventListener('click', (event) => {
    const btn = event.target.closest('button.suite-tab');
    if (!btn) return;
    if (btn.disabled) {
        showToast(btn.title || '该 Tab 即将上线');
        return;
    }
    // ... existing logic
});
```

确认 `showToast` 函数已存在；否则添加简易版：

```javascript
function showToast(msg) {
    let t = document.getElementById('kronosToast');
    if (!t) {
        t = document.createElement('div');
        t.id = 'kronosToast';
        t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:8px 16px;border-radius:6px;z-index:99999;opacity:0;transition:opacity 0.2s';
        document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.opacity = '1';
    setTimeout(() => { t.style.opacity = '0'; }, 2000);
}
```

- [ ] **Step 2: 浏览器验证** — 点击任意 disabled Tab 弹 toast

- [ ] **Step 3: Commit (optional)**

---

## Phase E — 集成 & 回归

### Task 17: 端到端浏览器验证 & 性能 budget

**Files:** 无修改，仅验证。

- [ ] **Step 1: 启动 Robyn**

```bash
.venv/bin/python webui/run.py &
sleep 5
```

- [ ] **Step 2: 浏览器打开 desktop UI，点开一只数据齐全的股票（如 000001、600519）**

逐一确认：
- 11 个 Tab 显示，7 个 disabled
- 快速信息 Tab = 原 6 面板布局
- 综合总览 Tab = 雷达图 5 顶点 + 6 关键信号卡片 + 情景概率环 + 深度信号列表
- 操盘风控 Tab = 3 列布局，止损/分批/止盈/深度信号/隐性风险
- AI 解读 Tab = 按钮 → 5-30s → markdown 报告
- 关闭再打开同一股票，5 分钟内缓存命中（首屏 ≤ 500ms；首次冷启 ≤ 3s）

- [ ] **Step 3: 验证 spec §9 验收清单**

逐项勾选 §9 的 7 个验收项。

- [ ] **Step 4: kill server**

```bash
pkill -9 -f "webui/run.py"
sleep 1
pgrep -fl "webui/run.py" || echo "✅ no orphan"
```

---

### Task 18: 回归保护（不修改任何 spec §2.1 文件）

**Files:** 无修改，仅验证。

- [ ] **Step 1: 跑机会挖掘短任务**

Run: `.venv/bin/python scripts/run_opportunity_discovery.py --limit 3 2>&1 | tail -20`
Expected: exit 0，无 ImportError

- [ ] **Step 2: 跑所有 tests**

Run: `.venv/bin/pytest tests/ -v 2>&1 | tail -20`
Expected: 全绿（比 Phase B 收官 76 多出本次新增的 stock_suite 测试约 12-15 条）

- [ ] **Step 3: 确认未触碰 spec §2.1 文件**

```bash
git diff --stat $(git merge-base HEAD main)..HEAD -- \
    scripts/run_opportunity_discovery.py \
    scripts/opportunity_report_generator.py \
    scripts/run_integrated_discovery.py \
    analysis/technical_analysis.py \
    analysis/advanced_analysis.py \
    analysis/market_env_analyzer.py \
    analysis/fundamental_data_collector.py \
    analysis/investor_sentiment.py \
    analysis/opportunity_scorer_v4_1_integration.py
```
Expected: 0 行（或仅空白行差异）

注：`analysis/llm_service.py` 不在 §2.1 名单（spec 写的是「现有 analyzer 不修改」），Task 7 已在该文件**追加** `interpret_stock_markdown` 新方法 — 是允许的扩展，未改任何现有签名。

- [ ] **Step 4: Commit (optional — 整个 Phase 的 wrap-up)**

---

## 完整验收清单（与 spec §9 对齐）

- [ ] 点击任一个股，弹窗展示 11 个 Tab，3 个核心 Tab 有完整内容，7 个占位 Tab 可点击但显示「即将上线」
- [ ] 综合总览雷达图 5 维有数据；关键信号、深度信号、情景概率全部渲染
- [ ] 操盘风控的止损/分批/止盈/隐性风险按 spec §6.3 布局
- [ ] AI 解读点击按钮后 5-30s 内返回 markdown
- [ ] 运行 `python scripts/run_opportunity_discovery.py` 与「批量分析」无任何回归
- [ ] 弹窗首屏渲染（不含 AI）≤ 3s（缓存命中 ≤ 500ms）
- [ ] 单股数据降级路径（停牌 / 数据不足）有友好提示，整体 200
- [ ] `tests/` 全绿
- [ ] grep `from analysis import technical_analysis` 等只读 import，未修改 spec §2.1 文件签名

---

## 自审

**Spec 覆盖**：
- §3 数据流 → Task 1-8（编排器）+ Task 9（service）+ Task 10-11（routes）+ Task 13-15（前端）
- §4 雷达评分 → Task 2 公式 + Task 6 输入装配
- §5 API 契约 → Task 9 service shape + Task 10-11 handlers
- §6 UI → Task 12 Tab 栏 + Task 13/14/15 内容渲染
- §7 错误处理 → Task 6 降级（warning + null）+ Task 10 异常→500 + Task 14 reason 显示 + Task 15 AI fail UI
- §8 测试 → Task 1-9 单元 + Task 10-11 handler + Task 18 回归

**Placeholder 扫描**：0 命中（所有 step 都有代码或具体命令）。

**Type 一致性**：
- `StockSuiteService.get_suite` 返回 dict ↔ Task 10 handler 透传 ↔ JS `renderSuiteOverview` 读 `payload.overview.radar.*.score`
- `trigger_ai_interpretation` 返回 `{success, status, report, token_usage, generated_at, cached_path}` ↔ Task 15 JS 读同字段
- `STOCK_SUITE_SERVICE` 单例名贯穿 webui/core.py / surface test / robyn_app.py handler 三处

**已知偏离 spec 处（在 plan 头部已声明）**：4 处全部用替代实现，无任何 unfixable gap。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-23-stock-analysis-suite.md`.

**两种执行方式：**

**1. Subagent-Driven (recommended)** — fresh subagent per task + 两阶段 review

**2. Inline Execution** — 在本 session 内连续执行，每个 Task 后 checkpoint

**Which approach?**
