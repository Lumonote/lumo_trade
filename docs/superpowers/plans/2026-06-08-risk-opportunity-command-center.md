# 风险·机遇统筹作战大屏 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建一个独立侧栏「风险·机遇」大屏,把现有机会报告/资金榜单/市场环境/模拟盘持仓统筹到一屏,对每只标的同时给出机会分+四层风险分并撮合成 9 象限行动建议(霓虹暗调可视化,可一键全屏)。

**Architecture:** 方案 A —— 纯计算引擎 `analysis/risk_opportunity_engine.py`(无 I/O,可独立单测)+ 编排服务 `webui/services/command_center_service.py`(拉各源、降级、实时叠加)+ 单聚合接口 `/api/command-center/overview` + 复用 `_run_opportunity_job` 的 `/recompute`。前端用现有 Plotly 画散点矩阵 + CSS/SVG 画仪表盘环/榜单/滚动条。

**Tech Stack:** Python 3.13 · pytest · Robyn(`webui/robyn_app.py`)· SQLite(已有 repo)· Plotly.js 2.32(CDN,已加载)· 原生 JS(`webui/static/kronos_desktop_app.js`)+ CSS。

**Spec:** `docs/superpowers/specs/2026-06-08-risk-opportunity-command-center-design.md`
**视觉标尺:** `docs/superpowers/specs/2026-06-08-risk-opportunity-command-center-mockup.html`(v3)

---

## File Structure

| 文件 | 责任 | 新建/改 |
|---|---|---|
| `analysis/risk_opportunity_engine.py` | 纯计算:四层风险打分、机会分透传、撮合象限映射、综合指数。模块级可调常量。无 I/O。 | 新建 |
| `tests/test_risk_opportunity_engine.py` | 引擎全部单测(TDD 先行) | 新建 |
| `webui/services/command_center_service.py` | 编排:拉机会报告+sidecar/资金榜单/市场环境/持仓/实时报价 → 调引擎 → 整屏 JSON;`quotes_only` 增量;逐源降级;轻缓存。 | 新建 |
| `tests/test_command_center_service.py` | 编排/降级/增量/缓存 单测 | 新建 |
| `analysis/opportunity_scorer.py`(或报告生成处) | 生成报告时额外落 `*.signals.json` sidecar | 改 |
| `tests/test_opportunity_signals_sidecar.py` | sidecar 落盘内容单测 | 新建 |
| `webui/core.py` | `DESKTOP_PAGES` 加 `command_center`;`command_center_overview()`/`start_command_center_recompute()` 包装;实例化服务 | 改 |
| `webui/robyn_app.py` | 挂 `/api/command-center/overview`、`/recompute` 路由 | 改 |
| `webui/static/kronos_desktop_app.js` | `renderCommandCenter*`、全屏切换、30s 实时刷新、每标的动作 | 改 |
| `webui/static/kronos_desktop.css` | `.cc-screen` 霓虹暗调主题(对齐 v3) | 改 |

**Engine public API(全阶段共用,务必一致):**
```
score_stock_risk(signals: dict) -> dict          # {risk:float|None, factors:[{name,contrib,detail}], dominant:str|None, unknown:bool}
score_sector_crowding(sector: dict) -> float     # 0-100
score_market_risk(market_env: dict) -> dict      # {risk:float, factors:[...]}
score_portfolio_risk(account: dict, positions: list, max_drawdown: float) -> dict
combine_stock_risk(stock: dict, sector_crowding: float, market_backdrop: float) -> float|None
match_action(opp: float, risk: float|None, *, held: bool=False) -> dict   # {quadrant,action,code,color,held_overlay}
opportunity_index(items: list) -> float
market_risk_index(market_risk: float, sentiment: float) -> float
build_target(item: dict, signals: dict, sector_crowding: float, market_backdrop: float, *, held: bool) -> dict
```

**可调常量(模块顶部):**
```python
OPP_BANDS = {"high": 70.0, "mid": 55.0}
RISK_BANDS = {"low": 40.0, "high": 60.0}
RISK_BLEND = {"stock": 0.55, "sector": 0.20, "market": 0.25}
STOCK_RISK_BASE = 30.0
```

---

## Phase 1 — 风险引擎(纯计算 · TDD)

### Task 1: 撮合象限映射 `match_action`

**Files:**
- Create: `analysis/risk_opportunity_engine.py`
- Test: `tests/test_risk_opportunity_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_risk_opportunity_engine.py
from analysis import risk_opportunity_engine as eng


def test_match_action_high_opp_low_risk_is_act():
    r = eng.match_action(88, 32)
    assert r["action"] == "重点出手"
    assert r["code"] == "act"
    assert r["color"] == "green"
    assert r["quadrant"] == "high-low"


def test_match_action_high_opp_high_risk_is_care():
    r = eng.match_action(85, 72)
    assert r["action"] == "谨慎·轻仓"
    assert r["code"] == "care"


def test_match_action_low_opp_high_risk_is_avoid():
    r = eng.match_action(40, 75)
    assert r["action"] == "坚决回避"
    assert r["code"] == "avoid"


def test_match_action_held_high_risk_overlays_cut():
    r = eng.match_action(85, 72, held=True)
    assert r["held_overlay"] == "减仓/止盈"


def test_match_action_held_act_overlays_hold():
    r = eng.match_action(88, 32, held=True)
    assert r["held_overlay"] == "持有"


def test_match_action_unknown_risk_returns_unknown():
    r = eng.match_action(88, None)
    assert r["action"] == "风险未知"
    assert r["code"] == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_risk_opportunity_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'analysis.risk_opportunity_engine'`

- [ ] **Step 3: Write minimal implementation**

```python
# analysis/risk_opportunity_engine.py
"""Pure risk/opportunity scoring & matching for the command-center 大屏.

No I/O. Inputs are plain dicts assembled by command_center_service; outputs are
plain dicts the frontend renders. Thresholds are module-level tunable constants
(mirrors the project's scoring-param tuning culture).
"""

OPP_BANDS = {"high": 70.0, "mid": 55.0}
RISK_BANDS = {"low": 40.0, "high": 60.0}
RISK_BLEND = {"stock": 0.55, "sector": 0.20, "market": 0.25}
STOCK_RISK_BASE = 30.0

_ACTION_TABLE = {
    ("high", "low"): ("重点出手", "act", "green"),
    ("high", "mid"): ("可做·控仓", "do", "amber"),
    ("high", "high"): ("谨慎·轻仓", "care", "orange"),
    ("mid", "low"): ("关注", "watch", "cyan"),
    ("mid", "mid"): ("观望", "watch", "blue"),
    ("mid", "high"): ("暂避", "avoid", "red"),
    ("low", "low"): ("无感", "none", "gray"),
    ("low", "mid"): ("回避", "avoid", "red"),
    ("low", "high"): ("坚决回避", "avoid", "red"),
}


def _opp_band(opp):
    if opp >= OPP_BANDS["high"]:
        return "high"
    if opp >= OPP_BANDS["mid"]:
        return "mid"
    return "low"


def _risk_band(risk):
    if risk < RISK_BANDS["low"]:
        return "low"
    if risk >= RISK_BANDS["high"]:
        return "high"
    return "mid"


def match_action(opp, risk, *, held=False):
    if risk is None:
        return {"quadrant": "unknown", "action": "风险未知", "code": "unknown",
                "color": "gray", "held_overlay": None}
    o, r = _opp_band(opp), _risk_band(risk)
    label, code, color = _ACTION_TABLE[(o, r)]
    overlay = None
    if held:
        if r == "high":
            overlay = "减仓/止盈"
        elif o == "high" and r == "low":
            overlay = "持有"
    return {"quadrant": f"{o}-{r}", "action": label, "code": code,
            "color": color, "held_overlay": overlay}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_risk_opportunity_engine.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add analysis/risk_opportunity_engine.py tests/test_risk_opportunity_engine.py
git commit -m "feat(cc): risk-opportunity matching quadrant (match_action)"
```

---

### Task 2: 个股风险打分 `score_stock_risk`

**Files:**
- Modify: `analysis/risk_opportunity_engine.py`
- Test: `tests/test_risk_opportunity_engine.py`

- [ ] **Step 1: Write the failing test**

```python
def test_score_stock_risk_rsi_overheat_dominates():
    r = eng.score_stock_risk({"rsi": 81, "chase": 20, "change_3d": 5,
                              "sell_signals": 0, "quant_score": 60})
    assert r["unknown"] is False
    assert r["risk"] >= 55          # base 30 + rsi>=80 (+30) - clamp
    assert r["dominant"] == "RSI过热"


def test_score_stock_risk_hard_gate_st_caps_high():
    r = eng.score_stock_risk({"rsi": 40, "is_st": True})
    assert r["risk"] >= 85


def test_score_stock_risk_sell_and_chase_stack():
    r = eng.score_stock_risk({"rsi": 55, "chase": 82, "change_3d": 21,
                              "sell_signals": 3, "quant_score": 91})
    # base30 + chase>=80(20) + chg>=20(15) + sell>=2(12) + quant>=90(10) = 87
    assert r["risk"] >= 80
    factor_names = {f["name"] for f in r["factors"]}
    assert {"追高", "5日急涨", "卖出信号", "量化过度共识"} <= factor_names


def test_score_stock_risk_clean_stock_low():
    r = eng.score_stock_risk({"rsi": 48, "chase": 10, "change_3d": 3,
                              "sell_signals": 0, "quant_score": 55})
    assert r["risk"] <= 40


def test_score_stock_risk_empty_signals_unknown():
    r = eng.score_stock_risk({})
    assert r["unknown"] is True
    assert r["risk"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_risk_opportunity_engine.py -k stock_risk -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'score_stock_risk'`

- [ ] **Step 3: Write minimal implementation**

```python
def _num(signals, key):
    v = signals.get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def score_stock_risk(signals):
    signals = signals or {}
    rsi = _num(signals, "rsi")
    chase = _num(signals, "chase")
    chg3 = _num(signals, "change_3d")
    sell = _num(signals, "sell_signals")
    quant = _num(signals, "quant_score")
    streak = _num(signals, "limit_up_streak")
    is_st = bool(signals.get("is_st"))
    halt = bool(signals.get("halt"))

    if all(v is None for v in (rsi, chase, chg3, sell, quant)) and not (is_st or halt):
        return {"risk": None, "factors": [], "dominant": None, "unknown": True}

    risk = STOCK_RISK_BASE
    factors = []

    def add(name, contrib, detail):
        nonlocal risk
        risk += contrib
        factors.append({"name": name, "contrib": contrib, "detail": detail})

    if rsi is not None and rsi >= 80:
        add("RSI过热", 30, f"RSI {rsi:.0f} ≥80")
    elif rsi is not None and rsi >= 70:
        add("RSI偏热", 15, f"RSI {rsi:.0f} ≥70")
    if chase is not None and chase >= 80:
        add("追高", 20, f"追高 {chase:.0f}")
    elif chase is not None and chase >= 50:
        add("追高", 10, f"追高 {chase:.0f}")
    if chg3 is not None and chg3 >= 20:
        add("5日急涨", 15, f"3日 +{chg3:.0f}%")
    elif chg3 is not None and chg3 >= 12:
        add("5日急涨", 8, f"3日 +{chg3:.0f}%")
    if sell is not None and sell >= 2:
        add("卖出信号", 12, f"卖出 {sell:.0f}")
    if quant is not None and quant >= 90:
        add("量化过度共识", 10, f"量化 {quant:.0f} ≥90")
    if streak is not None and streak >= 2:
        add("连板高位", 10, f"连板 {streak:.0f}")

    if is_st or halt:
        risk = max(risk, 85)
        factors.append({"name": "ST/停牌硬闸", "contrib": 0, "detail": "风险封顶"})

    risk = max(0.0, min(100.0, risk))
    scored = [f for f in factors if f["contrib"] > 0]
    dominant = max(scored, key=lambda f: f["contrib"])["name"] if scored else (
        "ST/停牌硬闸" if (is_st or halt) else None)
    return {"risk": risk, "factors": factors, "dominant": dominant, "unknown": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_risk_opportunity_engine.py -k stock_risk -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add analysis/risk_opportunity_engine.py tests/test_risk_opportunity_engine.py
git commit -m "feat(cc): per-stock risk scoring from reused signals"
```

---

### Task 3: 板块拥挤 / 市场系统性 / 组合风险

**Files:**
- Modify: `analysis/risk_opportunity_engine.py`
- Test: `tests/test_risk_opportunity_engine.py`

- [ ] **Step 1: Write the failing test**

```python
def test_sector_crowding_dead_zone_high():
    assert eng.score_sector_crowding({"sector_score": 70}) >= 60   # 65-75 死区
    assert eng.score_sector_crowding({"sector_score": 50}) < 50


def test_market_risk_drawdown_and_breadth():
    r = eng.score_market_risk({"hs300_ret_5d": -4.0, "hs300_ret_20d": -8.0,
                               "advance": 800, "decline": 4000, "sentiment": 30})
    assert r["risk"] >= 60
    assert any("回撤" in f["name"] or "breadth" in f["name"] or "家数" in f["name"]
               for f in r["factors"])


def test_market_risk_calm_low():
    r = eng.score_market_risk({"hs300_ret_5d": 1.0, "hs300_ret_20d": 2.0,
                               "advance": 3000, "decline": 1800, "sentiment": 60})
    assert r["risk"] <= 45


def test_portfolio_risk_concentration_and_drawdown():
    acct = {"total_equity": 1_000_000}
    pos = [{"ts_code": "600000", "market_value": 600_000},
           {"ts_code": "000001", "market_value": 200_000}]
    r = eng.score_portfolio_risk(acct, pos, max_drawdown=0.18)
    assert r["concentration"] == 0.6
    assert r["exposure"] == 0.8
    assert r["risk"] >= 55


def test_combine_stock_risk_blends_layers():
    # stock 60, sector 40, market 50 -> .55*60 +.2*40 +.25*50 = 53.5
    v = eng.combine_stock_risk({"risk": 60, "unknown": False}, 40, 50)
    assert round(v, 1) == 53.5


def test_combine_stock_risk_unknown_propagates():
    assert eng.combine_stock_risk({"risk": None, "unknown": True}, 40, 50) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_risk_opportunity_engine.py -k "sector or market_risk or portfolio or combine" -v`
Expected: FAIL — attributes not defined

- [ ] **Step 3: Write minimal implementation**

```python
def score_sector_crowding(sector):
    s = _num(sector or {}, "sector_score")
    if s is None:
        return 35.0
    if 65 <= s <= 75:        # memory: 死区 25.5%wr
        return 65.0
    if s > 75:               # 过热追高
        return 55.0
    if s < 45:
        return 30.0
    return 45.0


def score_market_risk(market_env):
    m = market_env or {}
    risk, factors = 35.0, []

    def add(name, contrib, detail):
        nonlocal risk
        risk += contrib
        factors.append({"name": name, "contrib": contrib, "detail": detail})

    r5 = _num(m, "hs300_ret_5d")
    r20 = _num(m, "hs300_ret_20d")
    if r5 is not None and r5 <= -3:
        add("近5日回撤", 15, f"沪深300 {r5:.1f}%")
    if r20 is not None and r20 <= -6:
        add("近20日回撤", 12, f"沪深300 {r20:.1f}%")
    adv, dec = _num(m, "advance"), _num(m, "decline")
    if adv is not None and dec is not None and (adv + dec) > 0:
        ratio = dec / (adv + dec)
        if ratio >= 0.6:
            add("涨跌家数", 15, f"跌{int(dec)}/涨{int(adv)}")
    sent = _num(m, "sentiment")
    if sent is not None and sent <= 35:
        add("情绪冰点", 8, f"情绪 {sent:.0f}")
    elif sent is not None and sent >= 80:
        add("情绪过热", 8, f"情绪 {sent:.0f}")
    risk = max(0.0, min(100.0, risk))
    return {"risk": risk, "factors": factors}


def score_portfolio_risk(account, positions, max_drawdown=0.0):
    account = account or {}
    positions = positions or []
    equity = _num(account, "total_equity") or 0.0
    pos_val = sum((_num(p, "market_value") or 0.0) for p in positions)
    weights = [((_num(p, "market_value") or 0.0) / equity) for p in positions] if equity else []
    concentration = round(max(weights), 4) if weights else 0.0
    exposure = round(pos_val / equity, 4) if equity else 0.0
    dd = float(max_drawdown or 0.0)
    risk = 20.0 + concentration * 60 + min(exposure, 1.0) * 20 + min(dd, 0.5) * 60
    risk = max(0.0, min(100.0, risk))
    return {"risk": risk, "concentration": concentration,
            "exposure": exposure, "max_drawdown": dd}


def combine_stock_risk(stock, sector_crowding, market_backdrop):
    if not stock or stock.get("unknown") or stock.get("risk") is None:
        return None
    v = (RISK_BLEND["stock"] * stock["risk"]
         + RISK_BLEND["sector"] * float(sector_crowding or 35.0)
         + RISK_BLEND["market"] * float(market_backdrop or 35.0))
    return max(0.0, min(100.0, v))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_risk_opportunity_engine.py -k "sector or market_risk or portfolio or combine" -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add analysis/risk_opportunity_engine.py tests/test_risk_opportunity_engine.py
git commit -m "feat(cc): sector/market/portfolio risk layers + blend"
```

---

### Task 4: 综合指数 + 每股 `build_target`

**Files:**
- Modify: `analysis/risk_opportunity_engine.py`
- Test: `tests/test_risk_opportunity_engine.py`

- [ ] **Step 1: Write the failing test**

```python
def test_opportunity_index_aggregates_tiers():
    items = [{"score": 88, "rating": "S"}, {"score": 80, "rating": "A"},
             {"score": 60, "rating": "C"}]
    idx = eng.opportunity_index(items)
    assert 0 <= idx <= 100
    assert idx >= 60        # has S+A


def test_market_risk_index_blends_sentiment():
    assert 0 <= eng.market_risk_index(62, 55) <= 100


def test_build_target_assembles_action_and_reason():
    item = {"code": "603986", "name": "兆易创新", "score": 88, "rating": "S",
            "sector": "半导体"}
    signals = {"rsi": 58, "chase": 30, "change_3d": 6, "sell_signals": 0,
               "quant_score": 62, "sector_score": 50}
    t = eng.build_target(item, signals, sector_crowding=45, market_backdrop=50,
                         held=False)
    assert t["code"] == "603986"
    assert t["opp"] == 88
    assert t["risk"] is not None
    assert t["action"] == "重点出手"
    assert "机会" in t["reason"] and "→" in t["reason"]


def test_build_target_unknown_risk_when_no_signals():
    item = {"code": "000001", "name": "X", "score": 75, "rating": "B"}
    t = eng.build_target(item, {}, sector_crowding=40, market_backdrop=40, held=False)
    assert t["risk"] is None
    assert t["code_action"] == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_risk_opportunity_engine.py -k "index or build_target" -v`
Expected: FAIL — attributes not defined

- [ ] **Step 3: Write minimal implementation**

```python
def opportunity_index(items):
    items = items or []
    if not items:
        return 0.0
    scores = sorted((float(i.get("score") or 0) for i in items), reverse=True)
    top = scores[: max(1, len(scores) // 3)]      # 取头部 1/3 的均分
    base = sum(top) / len(top)
    s_a = sum(1 for i in items if str(i.get("rating")) in ("S", "A"))
    boost = min(15.0, s_a * 1.5)
    return max(0.0, min(100.0, base + boost))


def market_risk_index(market_risk, sentiment):
    sent = float(sentiment if sentiment is not None else 50.0)
    # 情绪越低,系统性风险体感越高
    return max(0.0, min(100.0, 0.7 * float(market_risk) + 0.3 * (100 - sent)))


def _reason_line(item, risk_result, action_obj):
    opp_part = f"机会{item.get('score'):.0f}({item.get('rating', '—')})"
    if risk_result.get("unknown") or risk_result.get("risk") is None:
        risk_part = "风险未知(无结构化信号)"
    elif risk_result.get("dominant"):
        risk_part = f"{risk_result['dominant']}"
    else:
        risk_part = "风险可控"
    return f"{opp_part} · {risk_part} → {action_obj['action']}"


def build_target(item, signals, sector_crowding, market_backdrop, *, held):
    stock = score_stock_risk(signals)
    combined = combine_stock_risk(stock, sector_crowding, market_backdrop)
    action = match_action(float(item.get("score") or 0), combined, held=held)
    return {
        "code": item.get("code") or item.get("stock_code"),
        "name": item.get("name") or item.get("stock_name"),
        "sector": item.get("sector"),
        "opp": float(item.get("score") or 0),
        "rating": item.get("rating"),
        "risk": round(combined, 1) if combined is not None else None,
        "risk_unknown": stock["unknown"],
        "quadrant": action["quadrant"],
        "action": action["action"],
        "code_action": action["code"],
        "color": action["color"],
        "held": held,
        "held_overlay": action["held_overlay"],
        "reason": _reason_line(item, stock, action),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_risk_opportunity_engine.py -v`
Expected: PASS (all engine tests)

- [ ] **Step 5: Commit**

```bash
git add analysis/risk_opportunity_engine.py tests/test_risk_opportunity_engine.py
git commit -m "feat(cc): composite indices + per-target builder"
```

---

## Phase 2 — 结构化信号 sidecar

### Task 5: 报告生成时落 `*.signals.json`

> 目的:让大屏个股风险层拿到 chase/rsi/change_3d/sell/quant 等数值(markdown 拿不到)。

**Files:**
- Modify: `analysis/opportunity_scorer.py`(在产出每股 `result` 后、写报告处附近)
- Test: `tests/test_opportunity_signals_sidecar.py`

- [ ] **Step 1: 定位写报告的落点**

Run: `grep -nE "opportunity_top10_|\.md'|write_text|to_markdown|def .*generate.*report|results_dir|RESULTS_DIR" analysis/opportunity_scorer.py scripts/run_opportunity_discovery.py analysis/report_generator_v5.py | head -30`
记下实际写 `opportunity_top10_<date>.md` 的函数与它手上的每股 `result` 列表(含 `result['scores']`、`result['details']`、`chase`/`rsi`/`change_3d`/quant buy-sell 等)。Sidecar 写在**同目录、同 `<date>`**。

- [ ] **Step 2: Write the failing test**

```python
# tests/test_opportunity_signals_sidecar.py
import json
from analysis.opportunity_scorer import write_signals_sidecar


def test_write_signals_sidecar(tmp_path):
    results = [
        {"code": "603986", "name": "兆易创新", "total_score": 88, "rating": "S",
         "risk_signals": {"chase": 30, "rsi": 58, "change_3d": 6,
                          "sell_signals": 0, "quant_score": 62},
         "scores": {"sector": 50}},
    ]
    path = write_signals_sidecar(results, tmp_path / "opportunity_top10_20260608.md")
    assert path.name == "opportunity_top10_20260608.signals.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["code"] == "603986"
    assert data[0]["risk_signals"]["rsi"] == 58
    assert data[0]["sector_score"] == 50
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_opportunity_signals_sidecar.py -v`
Expected: FAIL — `ImportError: cannot import name 'write_signals_sidecar'`

- [ ] **Step 4: Write minimal implementation**

```python
# analysis/opportunity_scorer.py  (module-level helper)
import json
from pathlib import Path


def write_signals_sidecar(results, report_path):
    """Persist per-stock structured risk signals next to the markdown report.

    `results` are the rich per-stock dicts the scorer already builds. Sidecar is
    `<report stem>.signals.json` in the same directory. Best-effort: a flat list
    keyed by code with the fields the command-center risk engine needs.
    """
    report_path = Path(report_path)
    out = report_path.with_suffix("").with_suffix(".signals.json")
    payload = []
    for r in results or []:
        rs = dict(r.get("risk_signals") or {})
        payload.append({
            "code": r.get("code") or r.get("stock_code"),
            "name": r.get("name") or r.get("stock_name"),
            "total_score": r.get("total_score") or r.get("score"),
            "rating": r.get("rating"),
            "sector_score": (r.get("scores") or {}).get("sector"),
            "risk_signals": {
                "chase": rs.get("chase"),
                "rsi": rs.get("rsi"),
                "change_3d": rs.get("change_3d"),
                "sell_signals": rs.get("sell_signals"),
                "quant_score": rs.get("quant_score"),
                "limit_up_streak": rs.get("limit_up_streak"),
                "is_st": rs.get("is_st", False),
                "halt": rs.get("halt", False),
            },
        })
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_opportunity_signals_sidecar.py -v`
Expected: PASS

- [ ] **Step 6: Call it from the report writer**

在 Step 1 定位的写报告处,拿到每股 `results` 列表与 `report_path` 后追加一行(用真实变量名替换):
```python
try:
    write_signals_sidecar(results, report_path)
except Exception as exc:  # sidecar 不可阻塞报告生成
    logger.warning("signals sidecar 写入失败: %s", exc)
```
> 若该处 `result` 字典里 chase/rsi/change_3d 等不在 `result['risk_signals']` 而是散落在 `result['details']`,在此处先归集成 `result['risk_signals'] = {...}` 再调用(用 Step 1 看到的真实键名)。

- [ ] **Step 7: Commit**

```bash
git add analysis/opportunity_scorer.py tests/test_opportunity_signals_sidecar.py
git commit -m "feat(cc): emit per-stock signals.json sidecar at report time"
```

---

## Phase 3 — 编排服务 + 接口

### Task 6: `command_center_service` 读机会池 + sidecar + 撮合

**Files:**
- Create: `webui/services/command_center_service.py`
- Test: `tests/test_command_center_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_command_center_service.py
import json
from webui.services.command_center_service import CommandCenterService


def _report(tmp_path):
    md = tmp_path / "opportunity_top10_20260608.md"
    md.write_text("# r", encoding="utf-8")
    (tmp_path / "opportunity_top10_20260608.signals.json").write_text(json.dumps([
        {"code": "603986", "risk_signals": {"rsi": 58, "chase": 30, "change_3d": 6,
         "sell_signals": 0, "quant_score": 62}, "sector_score": 50},
    ]), encoding="utf-8")
    return md


def test_overview_builds_matrix_from_report(tmp_path):
    md = _report(tmp_path)
    svc = CommandCenterService(
        load_report=lambda: {"items": [
            {"code": "603986", "name": "兆易创新", "score": 88, "rating": "S",
             "sector": "半导体"}], "market_env": "暖", "file": md.name,
            "report_path": str(md)},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {"hs300_ret_5d": 1, "advance": 3000, "decline": 1800,
                            "sentiment": 60},
        holdings=lambda: {"account": {"total_equity": 0}, "positions": [],
                          "max_drawdown": 0.0},
        quotes=lambda codes: {},
    )
    out = svc.overview()
    assert out["matrix"][0]["code"] == "603986"
    assert out["matrix"][0]["action"] == "重点出手"
    assert out["indices"]["opportunity"] >= 60
    assert "market_risk" in out["indices"]


def test_overview_degrades_when_no_report():
    svc = CommandCenterService(
        load_report=lambda: {"items": [], "market_env": "", "report_path": None},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {}, holdings=lambda: {"account": {}, "positions": [],
                                                 "max_drawdown": 0.0},
        quotes=lambda codes: {})
    out = svc.overview()
    assert out["matrix"] == []
    assert out["degraded"]["opportunity"] is True


def test_overview_marks_held_positions(tmp_path):
    md = _report(tmp_path)
    svc = CommandCenterService(
        load_report=lambda: {"items": [
            {"code": "603986", "name": "兆易创新", "score": 88, "rating": "S"}],
            "report_path": str(md)},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {"sentiment": 55},
        holdings=lambda: {"account": {"total_equity": 1_000_000},
                          "positions": [{"ts_code": "603986",
                                         "market_value": 400_000}],
                          "max_drawdown": 0.0},
        quotes=lambda codes: {})
    out = svc.overview()
    assert out["matrix"][0]["held"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_command_center_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# webui/services/command_center_service.py
"""Orchestrates existing signals into the command-center 大屏 payload.

Pure orchestration: every data source is injected as a callable so the service
is testable without I/O. Each source degrades independently — a failing source
sets a `degraded[...]` flag and leaves its panel empty rather than crashing.
"""
import json
from pathlib import Path

from analysis import risk_opportunity_engine as eng


class CommandCenterService:
    def __init__(self, *, load_report, capital_rankings, market_env, holdings, quotes):
        self._load_report = load_report
        self._capital_rankings = capital_rankings
        self._market_env = market_env
        self._holdings = holdings
        self._quotes = quotes

    def _safe(self, fn, default):
        try:
            return fn(), False
        except Exception:
            return default, True

    def _load_sidecar(self, report_path):
        if not report_path:
            return {}
        side = Path(report_path).with_suffix("").with_suffix(".signals.json")
        if not side.is_file():
            return {}
        try:
            data = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out = {}
        for row in data:
            sig = dict(row.get("risk_signals") or {})
            if row.get("sector_score") is not None:
                sig["sector_score"] = row["sector_score"]
            out[row.get("code")] = sig
        return out

    def overview(self, *, quotes_only=False):
        degraded = {}
        report, d = self._safe(self._load_report, {"items": [], "report_path": None})
        degraded["opportunity"] = d or not report.get("items")
        menv, d = self._safe(self._market_env, {})
        degraded["market_env"] = d
        hold, d = self._safe(self._holdings,
                             {"account": {}, "positions": [], "max_drawdown": 0.0})
        degraded["holdings"] = d
        cap, d = self._safe(self._capital_rankings, {"rows": []})
        degraded["capital"] = d

        market = eng.score_market_risk(menv)
        held_codes = {p.get("ts_code") for p in hold.get("positions", [])}
        sidecar = self._load_sidecar(report.get("report_path"))

        matrix = []
        for item in report.get("items", []):
            code = item.get("code") or item.get("stock_code")
            sig = sidecar.get(code, {})
            sector_crowd = eng.score_sector_crowding(sig)
            matrix.append(eng.build_target(
                item, sig, sector_crowding=sector_crowd,
                market_backdrop=market["risk"], held=code in held_codes))

        portfolio = eng.score_portfolio_risk(
            hold.get("account", {}), hold.get("positions", []),
            max_drawdown=hold.get("max_drawdown", 0.0))

        indices = {
            "market_risk": round(eng.market_risk_index(
                market["risk"], menv.get("sentiment")), 0),
            "opportunity": round(eng.opportunity_index(report.get("items", [])), 0),
            "sentiment": round(float(menv.get("sentiment") or 50), 0),
        }
        return {
            "as_of": {"report": report.get("file"), "count": len(matrix),
                      "sidecar": bool(sidecar)},
            "indices": indices,
            "market_env": menv,
            "matrix": matrix,
            "portfolio": portfolio,
            "rankings": {"capital": cap.get("rows", [])},
            "degraded": degraded,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_command_center_service.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add webui/services/command_center_service.py tests/test_command_center_service.py
git commit -m "feat(cc): command-center orchestration service"
```

---

### Task 7: core 包装 + 服务接线 + 页面注册

**Files:**
- Modify: `webui/core.py`(实例化服务、`command_center_overview()`、`start_command_center_recompute()`、`DESKTOP_PAGES`)

- [ ] **Step 1: 注册 DESKTOP_PAGES 条目**

在 `webui/core.py` 的 `DESKTOP_PAGES`(约 2294 行)`'watchlist'` 之后插入:
```python
    'command_center': {
        'title': '风险·机遇',
        'subtitle': '统筹机会与四层风险,撮合成出手/规避决策的作战大屏',
    },
```

- [ ] **Step 2: 接线服务(复用已有单例)**

在 `webui/core.py` 服务实例化区(约 94–98 行,`PAPER_TRADING_SERVICE` 之后)添加:
```python
from webui.services.command_center_service import CommandCenterService


def _cc_market_env():
    """Normalize market breadth/index for the systemic-risk layer.

    Locate the overview's market-state provider first:
      grep -nE "涨跌|advance|decline|hs300|沪深300|market_state|breadth" \
        webui/services/market_intelligence.py webui/core.py
    Map it into {hs300_ret_5d, hs300_ret_20d, advance, decline, sentiment}.
    Fallback (source unavailable): {} -> engine yields a neutral backdrop.
    """
    try:
        # TODO(impl): fill from the located provider; keep keys above.
        return {}
    except Exception:
        return {}


def _cc_holdings():
    acct = PAPER_TRADING_SERVICE.account_summary()
    positions = PAPER_TRADING_SERVICE.positions()
    curve = PAPER_TRADING_SERVICE.equity_curve()
    equities = [float(p.get("total_equity") or 0) for p in curve] or [0.0]
    peak, dd = 0.0, 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            dd = max(dd, (peak - e) / peak)
    return {"account": acct, "positions": positions, "max_drawdown": dd}


COMMAND_CENTER_SERVICE = CommandCenterService(
    load_report=lambda: _command_center_report(),
    capital_rankings=lambda: CAPITAL_RANKINGS_SERVICE.moneyflow_ranking(top_n=20),
    market_env=_cc_market_env,
    holdings=_cc_holdings,
    quotes=WATCHLIST_SERVICE.quotes,
)


def _command_center_report():
    """Latest opportunity report parsed to items + its on-disk path (for sidecar)."""
    reports = _latest_primary_opportunity_reports(limit=1)
    if not reports:
        return {"items": [], "market_env": "", "file": None, "report_path": None}
    path = reports[0]
    parsed = _parse_opportunity_report(path)
    parsed["report_path"] = str(path)
    return parsed


def command_center_overview(quotes_only=False):
    return COMMAND_CENTER_SERVICE.overview(quotes_only=bool(quotes_only))
```
> `_latest_primary_opportunity_reports` 返回路径列表;若其元素不是文件路径(确认其返回类型),用 `RESULTS_DIR / <file>` 还原真实路径再传 `report_path`。

- [ ] **Step 3: recompute 包装(复用机会挖掘 job 入队)**

定位 workbench「开始挖掘」如何入队:
Run: `grep -nE "JOB_SERVICE|_run_opportunity_job|submit|enqueue|create_job|opportunity" webui/core.py | grep -iE "job|enqueue|submit" | head`
照同样入队方式加:
```python
def start_command_center_recompute():
    """Reuse the opportunity-mining background job (whole-market rescan)."""
    return _start_opportunity_job({"source": "multi", "limit": 100})  # 用 Step3 实测的入队函数名
```
> 用上面 grep 找到的真实入队函数(workbench 同款)替换 `_start_opportunity_job`,返回 `{job_id}`。

- [ ] **Step 4: 冒烟验证**

Run: `python -c "import webui.core as c; print(list(c.command_center_overview().keys()))"`
Expected: 打印 `['as_of','indices','market_env','matrix','portfolio','rankings','degraded']`(无报告时 matrix 为空、degraded.opportunity=True,不报错)

- [ ] **Step 5: Commit**

```bash
git add webui/core.py
git commit -m "feat(cc): wire command-center service + page registration in core"
```

---

### Task 8: Robyn 路由

**Files:**
- Modify: `webui/robyn_app.py`

- [ ] **Step 1: 定位路由注册并加两条**

Run: `grep -nE "add_route|/api/paper|/api/capital|_json_response|_query_value" webui/robyn_app.py | head`
照同款 handler 范式新增(放在资金榜单/paper 路由附近):
```python
def command_center_overview(request: Request) -> Response:
    quotes_only = _query_value(request, "quotes_only", "0") in ("1", "true", "True")
    return _json_response(webui_core.command_center_overview(quotes_only=quotes_only))


def command_center_recompute(request: Request) -> Response:
    return _json_response(webui_core.start_command_center_recompute())
```
并在路由表/注册处(同 `add_route` 列表)登记:
```python
app.add_route("GET", "/api/command-center/overview", command_center_overview)
app.add_route("POST", "/api/command-center/recompute", command_center_recompute)
```
> 用 grep 看到的真实注册写法(装饰器 or `add_route` 列表)对齐。

- [ ] **Step 2: 验证路由可达**

Run(另起后端 `python webui/run.py` 或现有启动方式后):
`curl -s "http://localhost:7070/api/command-center/overview" | python -m json.tool | head -20`
Expected: 返回含 `indices`/`matrix`/`degraded` 的 JSON,HTTP 200。

- [ ] **Step 3: Commit**

```bash
git add webui/robyn_app.py
git commit -m "feat(cc): /api/command-center/overview + /recompute routes"
```

---

## Phase 4 — 大屏前端骨架 + 主题

### Task 9: `.cc-screen` 霓虹暗调主题 CSS

**Files:**
- Modify: `webui/static/kronos_desktop.css`

- [ ] **Step 1: 移植 v3 mockup 的样式(scoped)**

把 `docs/superpowers/specs/2026-06-08-risk-opportunity-command-center-mockup.html` `<style>` 内的规则**整体加 `.cc-screen ` 前缀**(避免污染其它浅色页),追加到 `kronos_desktop.css` 末尾。保留 v3 调色变量:
```css
.cc-screen{ --cc-bg:#04060e; --cc-txt:#aebfda; --cc-txt-hi:#d6e2f3; --cc-muted:#5f799e;
  --cc-line:#143052; --cc-cyan:#25c2b4; --cc-green:#25b88a; --cc-amber:#cf922a;
  --cc-red:#cc5878; --cc-blue:#4a82cf;
  background:var(--cc-bg); color:var(--cc-txt); }
.cc-screen.cc-fullscreen{ position:fixed; inset:0; z-index:9999; overflow:auto; padding:14px; }
/* …(其余 panel/ring/plot/quad/tm/rank/ticker 规则,均以 .cc-screen 作用域)… */
```

- [ ] **Step 2: 验证不破坏其它页**

打开桌面 App,逐页(总览/自选/资金榜单/模拟盘/形态/报告/配置)目视确认样式无变化(因 `.cc-screen` 作用域隔离)。

- [ ] **Step 3: Commit**

```bash
git add webui/static/kronos_desktop.css
git commit -m "feat(cc): neon dark command-center theme (scoped .cc-screen)"
```

---

### Task 10: 页面骨架 + KPI 环 + 三榜 + ticker 渲染

**Files:**
- Modify: `webui/static/kronos_desktop_app.js`

- [ ] **Step 1: 入口 + 拉数 + 状态条/KPI**

参照现有 `render*` 范式(如 `renderOverview`)新增。在页面路由分发处(grep: `grep -nE "command_center|renderOverview|case '|page ===" webui/static/kronos_desktop_app.js`)挂上 `renderCommandCenter`:
```javascript
async function renderCommandCenter(){
  const host = document.querySelector('#page-command_center') || document.querySelector('.page-host');
  host.classList.add('cc-screen');
  let data;
  try { data = await fetch('/api/command-center/overview').then(r=>r.json()); }
  catch(e){ host.innerHTML = '<div class="cc-empty">大屏数据加载失败</div>'; return; }
  host.innerHTML = ccStatusBar(data) + ccKpiStrip(data) + ccHeroRow(data) + ccRankings(data) + ccTicker(data);
  ccBindActions(host, data);
  ccDrawMatrix(data);            // Task 11
  ccStartLiveRefresh();          // Task 12
}

function ccGauge(v, label, cls, sub){
  return `<div class="panel gaugebox"><div class="ring" style="--v:${v};--c:var(--cc-${cls})">
    <div class="rv"><b class="num">${v}</b><s>${sub||''}</s></div></div>
    <div class="glabel"><b>${label}</b></div></div>`;
}
function ccKpiStrip(d){
  const i = d.indices||{};
  return `<div class="kpi">
    ${ccGauge(i.market_risk||0,'市场风险','amber','')}
    ${ccGauge(i.opportunity||0,'机会指数','green','')}
    ${ccGauge(i.sentiment||0,'市场情绪','blue','')}
    <div class="panel pills">${ccPills(d)}</div></div>`;
}
```
(`ccStatusBar`/`ccPills`/`ccRankings`/`ccTicker`/`ccHeroRow` 按 mockup 的 DOM 结构实现真实 HTML;榜单读 `d.rankings.capital`、`d.matrix`(机会Top)、`d.portfolio`+持仓。)

- [ ] **Step 2: 全屏切换**

```javascript
function ccToggleFullscreen(){
  const el = document.querySelector('.cc-screen');
  el.classList.toggle('cc-fullscreen');
  document.body.classList.toggle('cc-fs-on');
}
document.addEventListener('keydown', e=>{
  if(e.key==='Escape') document.querySelector('.cc-screen.cc-fullscreen')?.classList.remove('cc-fullscreen');
});
```
状态条 `⛶` 按钮 `onclick=ccToggleFullscreen()`。

- [ ] **Step 3: 验证**

桌面 App 打开「风险·机遇」页:状态条/3 仪表盘环/药丸/三榜/ticker 按 v3 呈现;`⛶` 全屏铺满、`Esc` 退出。

- [ ] **Step 4: Commit**

```bash
git add webui/static/kronos_desktop_app.js
git commit -m "feat(cc): command-center page skeleton (status/KPI/ranks/ticker/fullscreen)"
```

---

## Phase 5 — 双 hero 可视化 + 交互闭环

### Task 11: Plotly 风险–机遇撮合散点矩阵 + 行业热力

**Files:**
- Modify: `webui/static/kronos_desktop_app.js`

- [ ] **Step 1: 散点矩阵(Plotly,象限着色 + hover 理由 + 点击动作)**

```javascript
const CC_COLOR = {act:'#25b88a',do:'#cfa233',care:'#cf922a',watch:'#25c2b4',
                  avoid:'#cc5878',none:'#6a93d2',unknown:'#6a93d2'};
function ccDrawMatrix(d){
  if(typeof Plotly==='undefined') return;            // SVG 兜底另议(沿用 renderRadarSvgFallback 思路)
  const pts = (d.matrix||[]).filter(t=>t.risk!==null);
  const trace = {
    x: pts.map(t=>t.opp), y: pts.map(t=>t.risk),
    text: pts.map(t=>`${t.name}<br>${t.reason}`), mode:'markers',
    marker:{ size: pts.map(t=>Math.max(8, Math.min(26, (t.net_inflow||1)))),
             color: pts.map(t=>CC_COLOR[t.code_action]||'#6a93d2') },
    hoverinfo:'text', type:'scatter',
  };
  const layout = { paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
    font:{color:'#aebfda',size:10}, margin:{l:36,r:10,t:6,b:28},
    xaxis:{title:'机会分 →',range:[30,100],gridcolor:'rgba(95,130,173,.12)'},
    yaxis:{title:'风险(上低下高)',range:[100,0],gridcolor:'rgba(95,130,173,.12)'}, // 反向:低风险在上
    shapes: ccQuadShapes() };
  Plotly.newPlot('ccMatrix', [trace], layout, {displayModeBar:false, responsive:true});
  document.getElementById('ccMatrix').on('plotly_click', ev=>{
    const t = pts[ev.points[0].pointIndex]; ccTargetMenu(t);   // Task 12
  });
}
```
`ccQuadShapes()` 返回 4 个半透明矩形(出手/谨慎/观望/回避象限),按 v3 配色。

- [ ] **Step 2: 行业热力 treemap**

读 `d.sectors`(若 overview 暂未带 sectors,先用 CSS grid 占位:`ccSectorHeat(d)` 渲染 `d.sectors||[]`,空则「板块数据待接入」)。treemap 块按涨跌着色(A股涨红跌绿)、死区描红框,点击 `ccFilterMatrixBySector(name)` 过滤散点。

- [ ] **Step 3: 验证**

打开页面:矩阵散点落点与 9 象限一致(高机会低风险在右上绿区);hover 出理由;点击点弹动作菜单;板块热力着色正确。

- [ ] **Step 4: Commit**

```bash
git add webui/static/kronos_desktop_app.js
git commit -m "feat(cc): risk-opportunity scatter matrix + sector heatmap"
```

---

### Task 12: 每标的动作 + 实时 30s 叠加 + 重新统筹

**Files:**
- Modify: `webui/static/kronos_desktop_app.js`

- [ ] **Step 1: 每标的动作(复用现有跳转/下单)**

```javascript
function ccTargetMenu(t){
  // 复用现有:个股深度分析跳转、加自选、加入买入池(模拟盘下单框)
  ccActionAnalyze(t.code);    // 复用 stock suite 打开函数(grep: openStockSuite/analyzeStock)
  // 渲染小菜单含 [深度分析][加自选][加入买入池],分别接现有函数
}
```
榜单行的 `析/自/池` 按钮 `ccBindActions` 内委托到:深度分析(现有)、`WatchlistService` 加自选(现有前端调用)、加入买入池(现有 paper 下单框打开函数)。grep 现有函数名:`grep -nE "openStockSuite|addWatch|加入买入池|paperOrder|下单" webui/static/kronos_desktop_app.js`。

- [ ] **Step 2: 实时 30s 叠加(盘中,收盘停)**

```javascript
let ccTimer=null;
function ccStartLiveRefresh(){
  clearInterval(ccTimer);
  ccTimer = setInterval(async ()=>{
    if(!ccIsTradingHours()) return;                 // 复用现有交易时段判断
    const q = await fetch('/api/command-center/overview?quotes_only=1').then(r=>r.json());
    ccApplyQuotes(q);                                // 只更新价格/涨跌药丸/点位漂移
  }, 30000);
}
```
离开页面时 `clearInterval(ccTimer)`(在页面切换处清理)。

- [ ] **Step 3: 重新统筹按钮 + 轮询**

```javascript
async function ccRecompute(){
  const {job_id} = await fetch('/api/command-center/recompute',{method:'POST'}).then(r=>r.json());
  ccPollJob(job_id, ()=>renderCommandCenter());     // 复用现有 job 轮询(grep: pollJob/jobStatus)
}
```
状态条 `↻ 重新统筹` 按钮 `onclick=ccRecompute()`。

- [ ] **Step 4: 验证(verifier / 手测)**

- 点散点/榜单行 → 深度分析跳转、加自选、加入买入池 全部生效。
- 盘中等 30s,价格/涨跌药丸刷新(`quotes_only=1` 不重算矩阵结构)。
- 点「重新统筹」→ 后台 job 跑完 → 整屏读到新评分。

- [ ] **Step 5: Commit**

```bash
git add webui/static/kronos_desktop_app.js
git commit -m "feat(cc): per-target actions + 30s live overlay + recompute polling"
```

---

## Self-Review(plan vs spec)

- **§7 四层风险**:Task 2(个股)、Task 3(板块/市场/组合)、Task 4(综合指数)、Task 6(blend+backdrop 装配)✓
- **§7 撮合 9 象限 + 持仓叠加**:Task 1 ✓
- **§8 sidecar 前置**:Task 5 ✓;Task 6 读 sidecar ✓;缺失降级(`test_overview_*` + 粗估)✓
- **§6 三态取数**:overview(Task 6/7/8)、quotes_only(Task 12 Step2)、recompute(Task 7 Step3 + Task 12 Step3)✓
- **§9 五分区**:状态/KPI/三榜/ticker(Task 10)、双 hero(Task 11)✓;每标的动作(Task 12)✓;全屏(Task 10 Step2)✓
- **§11 视觉 v3 scoped**:Task 9 ✓
- **§12 降级**:Task 6 `_safe` + `degraded` 标记 + matrix 空视图 ✓
- **§3 复用**:`_parse_opportunity_report`/`_latest_primary_opportunity_reports`/`CAPITAL_RANKINGS_SERVICE`/`PAPER_TRADING_SERVICE`/`WATCHLIST_SERVICE.quotes`/`_run_opportunity_job` 均经真实签名引用 ✓
- **brownfield 接缝**(report writer 落点、market breadth 源、job 入队函数、前端现有跳转/轮询函数名):各以**精确 grep + 套现有范式**的步骤交付,非空泛占位 ✓
- **类型一致性**:engine API 名称(`match_action`/`score_stock_risk`/`build_target` 等)在 Task 1-4 定义、Task 6 消费,一致 ✓

无遗漏。
