# 多空评审团 Tab — Phase 1 实现计划（纯规则，无 LLM）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在个股工作台新增第 16 个 Tab「多空评审团」，用纯规则引擎产出 51 位投资人 persona 的多空裁决 + 7 流派折叠 + 16 项量化指标 + 多空共识温度计 + 大分歧，全部由既有 payload 派生，无 LLM。

**Architecture:** 后端新增 `analysis/panel/` 纯计算包：`extract_features()` 从既有 `inputs`+已装配 payload 段抽 26 个标准化特征 → `rules.py`（12 旗舰手写规则 + 7 流派默认规则）对每位 persona 裁决 → `engine.py` 聚合共识/大分歧/流派 → `indicators.py` 产出 16 格多空指标。`StockAnalysisSuite._compute_full_payload` 增 `panel` 顶层 key（沿用 M1 `_collect_*` 骨架范式，降级 `data_status`）。前端 `desktop.html` 新增 `data-suite-tab="panel"` 按钮 + pane + `renderSuitePanel()`，终端风格 + `<details>` 懒渲染 + 动画策略③ + `prefers-reduced-motion`。

**Tech Stack:** Python 3.13 / pandas / PyYAML（persona 注册表）/ pytest（TDD）；前端原生 JS + CSS/SVG（无新渲染依赖）；Robyn webui。

**关键约定（贯穿全部任务）：**
- 运行测试一律用项目 venv：`.venv/bin/python -m pytest`（**不要**用 Homebrew `python3`）。
- 所有特征 Optional：缺失 = `None`，规则与指标必须容忍 `None`（不抛异常，降级中性）。
- A 股配色：**红 = 多/看涨 `#d23f3f`，绿 = 空/看跌 `#2f9e5a`**（与既有 `renderSuiteQuantMatrix` 一致）。
- payload 向后兼容：只新增 `panel` 顶层 key，不改既有 15 个 key。
- **范围裁定（无静默截断）：** spec §5 的 16 指标中，★ Kronos K线预测 与 ★ 回测胜率 依赖模型运行时（Phase 2）与回测闭环（Phase 3），**Phase 1 这两格以 `data_status:"unavailable"` + `signal:"neutral"` 显式降级渲染**（标注「Phase 2/3 接入」），其余 14 格接真实数据。这与 M1 `quant_matrix` 的 preview 降级范式一致。
- **配置落点裁定：** spec §4 说 style 权重读 `config/scoring_runtime_config.json`，但该文件被 `analysis/opportunity_scorer.py` / `scripts/auto_backtest.py` 回测优化器整体重写（含 `generated_at`），静态加 key 会被覆盖。**Phase 1 改为独立 `config/panel_style_weights.json`**，Phase 3 回测器可单独联动此文件。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `requirements.txt` | 固定 PyYAML 版本 | Modify（加 `pyyaml>=6.0`） |
| `analysis/panel/__init__.py` | 包入口；导出 `build_panel()` 编排器 | Create |
| `analysis/panel/personas/*.yaml` | 51 persona 注册表（7 流派文件，每文件一组） | Create |
| `analysis/panel/registry.py` | YAML 加载 + 校验 + rule_key 解析 | Create |
| `analysis/panel/features.py` | `extract_features(inputs, sections) -> dict`（26 特征） | Create |
| `analysis/panel/rules.py` | 12 旗舰规则 + 7 流派默认规则 + `score_to_signal` | Create |
| `analysis/panel/style.py` | `classify_style()` + `load_style_weights()` + `school_style_weight()` | Create |
| `analysis/panel/engine.py` | `evaluate_all` / `compute_consensus` / `compute_great_divide` / `compute_schools` | Create |
| `analysis/panel/indicators.py` | `build_indicators(features) -> [16]` | Create |
| `config/panel_style_weights.json` | 流派 × 风格 权重矩阵（Phase 1 静态默认） | Create |
| `analysis/stock_analysis_suite.py` | 新增 `_collect_panel()` + payload `panel` key | Modify（`_compute_full_payload` ~L230-250） |
| `tests/test_panel_features.py` | 特征抽取测试 | Create |
| `tests/test_panel_rules.py` | 规则裁决测试 | Create |
| `tests/test_panel_engine.py` | 注册表/共识/大分歧/流派/style 测试 | Create |
| `tests/test_panel_indicators.py` | 16 指标归类边界测试 | Create |
| `tests/test_stock_analysis_suite.py` | 扩展：payload 含 `panel` + 向后兼容 | Modify（文件末尾追加） |
| `webui/templates/desktop.html` | Tab 按钮 + pane + dispatch + `renderSuitePanel` + CSS | Modify（多处，见 Task 8-10） |

**数据契约（`panel` 顶层 key，落地 spec §3）：**
```jsonc
"panel": {
  "data_status": "fresh",            // fresh / stale / unavailable
  "last_updated": "2026-05-30 14:00:00",
  "consensus": { "score": 61, "label": "偏多", "bull": 28, "neutral": 11, "bear": 12 },
  "great_divide": {
    "bull": { "id": "zhao", "name": "赵老哥", "school": "F", "score": 92 },
    "bear": { "id": "graham", "name": "格雷厄姆", "school": "A", "score": 25 },
    "punchline": "赵老哥 看到 量化席位活跃，格雷厄姆 担心 估值超出安全边际"
  },
  "schools": [ { "key": "A", "name": "价值派", "count": 9, "lean": "偏空", "lean_score": 46 } ],
  "analysts": [
    { "id": "buffett", "name": "巴菲特", "school": "A", "signal": "bull", "score": 78,
      "headline": "ROE 22% 优秀，护城河深厚", "source": "handwritten",
      "reasons": ["ROE 22% 优秀，护城河深厚", "行业估值分位低，有安全边际"] }
  ],
  "indicators": [
    { "group": "capital", "key": "main_capital", "label": "主力资金", "value_text": "净流入 1.2 亿",
      "signal": "up", "strength": 0.7, "data_status": "fresh" }
  ]
}
```

---

### Task 1: Panel 包骨架 + persona 注册表（YAML）+ 加载器

**Files:**
- Modify: `requirements.txt`
- Create: `analysis/panel/__init__.py`
- Create: `analysis/panel/personas/value.yaml`（A 价值派，9 人，示例完整给出）
- Create: `analysis/panel/personas/growth.yaml`、`macro.yaml`、`technical.yaml`、`china_value.yaml`、`youzi.yaml`、`quant.yaml`（按下方 roster 表填）
- Create: `analysis/panel/registry.py`
- Test: `tests/test_panel_engine.py`

**51-persona roster（id / 中文名 / school / tier / rule_key）— 全量，不得省略：**

| school 文件 | id | 名称 | tier | rule_key |
|---|---|---|---|---|
| value (A,9) | buffett | 巴菲特 | flagship | buffett |
| | munger | 芒格 | flagship | munger |
| | graham | 格雷厄姆 | flagship | graham |
| | templeton | 约翰·邓普顿 | stub | school_default |
| | klarman | 塞思·卡拉曼 | stub | school_default |
| | schloss | 沃尔特·施洛斯 | stub | school_default |
| | neff | 约翰·涅夫 | stub | school_default |
| | marks | 霍华德·马克斯 | stub | school_default |
| | ackman | 比尔·阿克曼 | stub | school_default |
| growth (B,8) | fisher | 费雪 | flagship | fisher |
| | lynch | 彼得·林奇 | flagship | lynch |
| | wood | 木头姐 | flagship | wood |
| | miller | 比尔·米勒 | stub | school_default |
| | price | 普莱斯 | stub | school_default |
| | robertson | 朱利安·罗伯逊 | stub | school_default |
| | zhanglei | 张磊 | stub | school_default |
| | gltt | 葛兰 | stub | school_default |
| macro (C,7) | soros | 索罗斯 | flagship | soros |
| | dalio | 达里奥 | flagship | dalio |
| | tudor | 都铎·琼斯 | stub | school_default |
| | druckenmiller | 德鲁肯米勒 | stub | school_default |
| | paulson | 约翰·保尔森 | stub | school_default |
| | icahn | 卡尔·伊坎 | stub | school_default |
| | rogers | 吉姆·罗杰斯 | stub | school_default |
| technical (D,7) | livermore | 利弗莫尔 | stub | school_default |
| | oneil | 威廉·欧奈尔 | stub | school_default |
| | minervini | 米勒维尼 | stub | school_default |
| | weinstein | 斯坦·温斯坦 | stub | school_default |
| | murphy | 约翰·墨菲 | stub | school_default |
| | sperandeo | 斯波朗迪 | stub | school_default |
| | williams | 拉瑞·威廉姆斯 | stub | school_default |
| china_value (E,7) | duan | 段永平 | flagship | duan |
| | zhangkun | 张坤 | flagship | zhangkun |
| | dengbin | 但斌 | stub | school_default |
| | linyuan | 林园 | stub | school_default |
| | lilu | 李录 | stub | school_default |
| | fengliu | 冯柳 | stub | school_default |
| | qiuguolu | 邱国鹭 | stub | school_default |
| youzi (F,7) | zhao | 赵老哥 | flagship | zhao |
| | zhang_mz | 章盟主 | flagship | zhang_mz |
| | xuxiang | 徐翔 | stub | school_default |
| | yangjia | 炒股养家 | stub | school_default |
| | tuixue | 退学炒股 | stub | school_default |
| | qiaobang | 乔帮主 | stub | school_default |
| | sunge | 孙哥 | stub | school_default |
| quant (G,6) | simons | 西蒙斯 | stub | school_default |
| | griffin | 肯·格里芬 | stub | school_default |
| | deshaw | 大卫·肖 | stub | school_default |
| | asness | 阿斯内斯 | stub | school_default |
| | thorp | 爱德华·索普 | stub | school_default |
| | zan | 格里高利·赞恩 | stub | school_default |

> 合计 9+8+7+7+7+7+6 = **51**；flagship 3+3+2+0+2+2+0 = **12**；stub = **39**。D 技术派/G 量化派无旗舰，全部走流派默认规则（这两类规则本就纯数据驱动，见 Task 3）。

- [ ] **Step 1: 写失败测试 `tests/test_panel_engine.py`（注册表部分）**

```python
import pytest

from analysis.panel.registry import load_personas, SCHOOLS


def test_registry_loads_51_personas():
    personas = load_personas()
    assert len(personas) == 51
    flagship = [p for p in personas if p["tier"] == "flagship"]
    stub = [p for p in personas if p["tier"] == "stub"]
    assert len(flagship) == 12
    assert len(stub) == 39


def test_registry_covers_seven_schools():
    personas = load_personas()
    schools = {p["school"] for p in personas}
    assert schools == set(SCHOOLS.keys())  # A..G
    assert SCHOOLS["A"] == "价值派" and SCHOOLS["F"] == "游资派"


def test_registry_entries_have_required_fields():
    personas = load_personas()
    for p in personas:
        assert {"id", "name", "school", "tier", "rule", "voice"} <= set(p.keys())
        assert p["school"] in SCHOOLS
        assert p["tier"] in ("flagship", "stub")


def test_registry_ids_unique():
    ids = [p["id"] for p in load_personas()]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_panel_engine.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'analysis.panel'`）

- [ ] **Step 3: 加 PyYAML 到 requirements.txt**

在 `requirements.txt` 末尾追加一行：
```
pyyaml>=6.0
```

- [ ] **Step 4: 创建 `analysis/panel/__init__.py`（先占空，Task 7 填 `build_panel`）**

```python
"""多空评审团 panel 引擎（纯规则，无 LLM）。Phase 1。"""
```

- [ ] **Step 5: 创建 `analysis/panel/personas/value.yaml`（完整示例，照此格式写其余 6 个文件）**

```yaml
# A 价值派（9 人：3 旗舰 + 6 stub）
- id: buffett
  name: 巴菲特
  school: A
  tier: flagship
  rule: buffett
  voice: 护城河与长期复利
  key_metrics: [roe, pe_industry_rank, net_profit_yoy]
- id: munger
  name: 芒格
  school: A
  tier: flagship
  rule: munger
  voice: 合理价格的好生意
  key_metrics: [roe, pe_industry_rank]
- id: graham
  name: 格雷厄姆
  school: A
  tier: flagship
  rule: graham
  voice: 深度低估与安全边际
  key_metrics: [pe_industry_rank, pb]
- id: templeton
  name: 约翰·邓普顿
  school: A
  tier: stub
  rule: school_default
  voice: 逆向价值
  key_metrics: [pe_industry_rank, roe]
- id: klarman
  name: 塞思·卡拉曼
  school: A
  tier: stub
  rule: school_default
  voice: 安全边际优先
  key_metrics: [pe_industry_rank, roe]
- id: schloss
  name: 沃尔特·施洛斯
  school: A
  tier: stub
  rule: school_default
  voice: 低估分散
  key_metrics: [pe_industry_rank, pb]
- id: neff
  name: 约翰·涅夫
  school: A
  tier: stub
  rule: school_default
  voice: 低市盈率投资
  key_metrics: [pe_industry_rank]
- id: marks
  name: 霍华德·马克斯
  school: A
  tier: stub
  rule: school_default
  voice: 周期与风险
  key_metrics: [pe_industry_rank, roe]
- id: ackman
  name: 比尔·阿克曼
  school: A
  tier: stub
  rule: school_default
  voice: 集中价值
  key_metrics: [roe, pe_industry_rank]
```

- [ ] **Step 6: 创建其余 6 个 YAML 文件**

按 Step 5 同样字段（`id/name/school/tier/rule/voice/key_metrics`）与上方 roster 表，逐个写出：
- `growth.yaml`（B，8 人，school 字段全为 `B`；旗舰 fisher/lynch/wood 的 rule 分别为 `fisher`/`lynch`/`wood`，其余 `school_default`，voice 用「高成长」「合理价格成长」「颠覆式创新」等）
- `macro.yaml`（C，7 人；旗舰 soros/dalio 的 rule 为 `soros`/`dalio`，其余 `school_default`）
- `technical.yaml`（D，7 人，全 stub，rule 全 `school_default`，voice 用「趋势跟随」「价量突破」等）
- `china_value.yaml`（E，7 人；旗舰 duan/zhangkun 的 rule 为 `duan`/`zhangkun`，其余 `school_default`）
- `youzi.yaml`（F，7 人；旗舰 zhao/zhang_mz 的 rule 为 `zhao`/`zhang_mz`，其余 `school_default`，voice 用「龙虎榜打板」「板块龙头」等）
- `quant.yaml`（G，6 人，全 stub，rule 全 `school_default`，voice 用「统计套利」「多因子」等）

- [ ] **Step 7: 创建 `analysis/panel/registry.py`**

```python
"""persona 注册表：从 personas/*.yaml 加载 + 校验。"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Dict, List

import yaml

SCHOOLS: Dict[str, str] = {
    "A": "价值派", "B": "成长派", "C": "宏观派", "D": "技术派",
    "E": "中国价投", "F": "游资派", "G": "量化派",
}

_REQUIRED = ("id", "name", "school", "tier", "rule", "voice")
_PERSONAS_DIR = Path(__file__).resolve().parent / "personas"


@functools.lru_cache(maxsize=1)
def load_personas() -> List[Dict[str, Any]]:
    """加载并校验全部 persona。结果进程内缓存（YAML 静态）。"""
    personas: List[Dict[str, Any]] = []
    for path in sorted(_PERSONAS_DIR.glob("*.yaml")):
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for entry in entries:
            missing = [k for k in _REQUIRED if k not in entry]
            if missing:
                raise ValueError(f"{path.name}: persona 缺字段 {missing}: {entry!r}")
            if entry["school"] not in SCHOOLS:
                raise ValueError(f"{path.name}: 未知流派 {entry['school']!r}")
            if entry["tier"] not in ("flagship", "stub"):
                raise ValueError(f"{path.name}: 未知 tier {entry['tier']!r}")
            personas.append(entry)
    return personas
```

- [ ] **Step 8: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_panel_engine.py -q`
Expected: PASS（4 passed）

- [ ] **Step 9: 提交**

```bash
git add requirements.txt analysis/panel/__init__.py analysis/panel/personas/ analysis/panel/registry.py tests/test_panel_engine.py
git commit -m "feat(panel): persona 注册表（51 人/7 流派 YAML）+ 加载器（Phase 1 Task 1）"
```

---

### Task 2: 特征抽取 `features.py`

**Files:**
- Create: `analysis/panel/features.py`
- Test: `tests/test_panel_features.py`

**特征 schema（`extract_features` 产出的全部 key，规则/指标共用，DRY）：**
`pe, pb, roe, pe_industry_rank, net_profit_yoy`（基本面）；`main_net_inflow, super_large_net, retail_net_inflow, main_positive_days_5d, north_delta_30d, quant_seat_appearances, lhb_net_inst_buy`（资金面）；`rsi, macd_hist, kdj_j, ma_alignment, boll_position, volume_ratio`（技术面）；`control_degree, holder_number_trend, fund_hold_trend`（筹码·机构）；`model_bull, model_bear, model_total, model_bull_ratio`（模型）；`market_regime`（宏观）；`kronos_direction, backtest_winrate`（★ 预测，Phase 1 恒为 `None`）。

- [ ] **Step 1: 写失败测试 `tests/test_panel_features.py`**

```python
import numpy as np
import pandas as pd

from analysis.panel.features import extract_features


def _ohlcv(n=80):
    rng = np.random.default_rng(1)
    close = pd.Series(10 + rng.normal(0, 0.2, n).cumsum() * 0.1)
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": pd.Series(rng.integers(1e6, 5e6, n).astype(float)),
        "amount": close * 1e6,
    })


def _inputs():
    return {
        "ohlcv": _ohlcv(80),
        "capital_flow": {"details": {
            "order_analysis": {"main_net_inflow": 1.2e8, "super_large_net": 8e7,
                               "retail_net_inflow": -3e7},
            "positive_days_5d": 3}},
        "fundamental": {"pe": 18.0, "pb": 2.1, "roe": 22.0,
                        "pe_industry_rank": 28.0, "net_profit_yoy": 35.0},
        "market_regime": "bull",
    }


def _sections():
    return {
        "main_force_deep": {"data_status": "fresh",
            "dragon_tiger": {"quant_seat_appearances": 2, "net_inst_buy": 5e7},
            "hsgt": {"latest": {"hold_ratio": 4.1}, "delta": 0.6}},
        "chip_control": {"data_status": "fresh", "control_degree": 72},
        "institutional_holdings": {"data_status": "stale",
            "holder_number": {"latest": 50000, "previous": 56000},
            "fund_holds": {"latest_funds": 30, "previous_funds": 24}},
        "quant_matrix": {"data_status": "fresh",
            "multi_period_resonance": {"bull": 18, "bear": 6, "neutral": 6}},
    }


def test_extract_features_fundamental_and_capital():
    f = extract_features(_inputs(), _sections())
    assert f["roe"] == 22.0
    assert f["pe_industry_rank"] == 28.0
    assert f["main_net_inflow"] == 1.2e8
    assert f["super_large_net"] == 8e7


def test_extract_features_sections_and_model_ratio():
    f = extract_features(_inputs(), _sections())
    assert f["quant_seat_appearances"] == 2
    assert f["north_delta_30d"] == 0.6
    assert f["control_degree"] == 72
    assert f["model_total"] == 30
    assert abs(f["model_bull_ratio"] - 0.6) < 1e-6
    assert f["holder_number_trend"] == "down"   # 户数减少 = 筹码集中
    assert f["fund_hold_trend"] == "up"          # 基金增持


def test_extract_features_technical_computed():
    f = extract_features(_inputs(), _sections())
    assert f["rsi"] is not None and 0 <= f["rsi"] <= 100
    assert f["macd_hist"] is not None
    assert f["ma_alignment"] in ("bull", "bear", "mixed")
    assert f["volume_ratio"] is not None and f["volume_ratio"] > 0


def test_extract_features_predictions_none_in_phase1():
    f = extract_features(_inputs(), _sections())
    assert f["kronos_direction"] is None
    assert f["backtest_winrate"] is None


def test_extract_features_tolerates_empty():
    f = extract_features({}, {})
    assert f["roe"] is None and f["rsi"] is None and f["model_bull_ratio"] is None
    assert f["market_regime"] is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_panel_features.py -q`
Expected: FAIL（`ModuleNotFoundError: analysis.panel.features`）

- [ ] **Step 3: 实现 `analysis/panel/features.py`**

```python
"""从既有 inputs + 已装配 payload 段抽标准化特征。所有特征 Optional。"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from analysis.technical_analysis import TechnicalAnalysis as TA


def _num(v: Any) -> Optional[float]:
    """转 float；None/NaN/不可转 → None。"""
    if v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    if isinstance(out, float) and (np.isnan(out) or np.isinf(out)):
        return None
    return out


def _last(series: Any) -> Optional[float]:
    """pandas Series 最后一个非 NaN 值 → float，否则 None。"""
    if series is None:
        return None
    try:
        s = series.dropna() if hasattr(series, "dropna") else pd.Series(series).dropna()
        if len(s) == 0:
            return None
        return float(s.iloc[-1])
    except Exception:  # noqa: BLE001
        return None


def _technical_features(df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "rsi": None, "macd_hist": None, "kdj_j": None,
        "ma_alignment": None, "boll_position": None, "volume_ratio": None,
    }
    if df is None or len(df) < 35:
        return out
    close = df["close"]
    out["rsi"] = _last(TA.calculate_rsi(close, 14))
    try:
        _, _, hist = TA.calculate_macd(close)
        out["macd_hist"] = _last(hist)
    except Exception:  # noqa: BLE001
        pass
    try:
        _, _, j = TA.calculate_kdj(df["high"], df["low"], close)
        out["kdj_j"] = _last(j)
    except Exception:  # noqa: BLE001
        pass
    ma5, ma10, ma20 = (_last(TA.calculate_ma(close, p)) for p in (5, 10, 20))
    if None not in (ma5, ma10, ma20):
        if ma5 > ma10 > ma20:
            out["ma_alignment"] = "bull"
        elif ma5 < ma10 < ma20:
            out["ma_alignment"] = "bear"
        else:
            out["ma_alignment"] = "mixed"
    try:
        upper, _, lower = TA.calculate_bollinger_bands(close)
        u, lo, c = _last(upper), _last(lower), _last(close)
        if None not in (u, lo, c) and u > lo:
            out["boll_position"] = max(0.0, min(1.0, (c - lo) / (u - lo)))
    except Exception:  # noqa: BLE001
        pass
    vma = _last(TA.calculate_ma(df["volume"], 20))
    cur_vol = _last(df["volume"])
    if vma and vma > 0 and cur_vol is not None:
        out["volume_ratio"] = cur_vol / vma
    return out


def _trend(latest: Any, previous: Any, *, down_label: str, up_label: str) -> Optional[str]:
    a, b = _num(latest), _num(previous)
    if a is None or b is None:
        return None
    if a < b:
        return down_label
    if a > b:
        return up_label
    return "flat"


def extract_features(inputs: Dict[str, Any], sections: Dict[str, Any]) -> Dict[str, Any]:
    inputs = inputs or {}
    sections = sections or {}
    f: Dict[str, Any] = {}

    fundam = inputs.get("fundamental") or {}
    f["pe"] = _num(fundam.get("pe"))
    f["pb"] = _num(fundam.get("pb"))
    f["roe"] = _num(fundam.get("roe"))
    f["pe_industry_rank"] = _num(fundam.get("pe_industry_rank"))
    f["net_profit_yoy"] = _num(fundam.get("net_profit_yoy"))

    cf_details = (inputs.get("capital_flow") or {}).get("details") or {}
    order = cf_details.get("order_analysis") or {}
    f["main_net_inflow"] = _num(order.get("main_net_inflow"))
    f["super_large_net"] = _num(order.get("super_large_net"))
    f["retail_net_inflow"] = _num(order.get("retail_net_inflow"))
    f["main_positive_days_5d"] = _num(cf_details.get("positive_days_5d"))

    mfd = sections.get("main_force_deep") or {}
    hsgt = mfd.get("hsgt") or {}
    f["north_delta_30d"] = _num(hsgt.get("delta"))
    dt = mfd.get("dragon_tiger") or {}
    f["quant_seat_appearances"] = _num(dt.get("quant_seat_appearances"))
    f["lhb_net_inst_buy"] = _num(dt.get("net_inst_buy"))

    f.update(_technical_features(inputs.get("ohlcv")))

    cc = sections.get("chip_control") or {}
    f["control_degree"] = _num(cc.get("control_degree"))
    ih = sections.get("institutional_holdings") or {}
    hn = ih.get("holder_number") or {}
    f["holder_number_trend"] = _trend(hn.get("latest"), hn.get("previous"),
                                      down_label="down", up_label="up")
    fh = ih.get("fund_holds") or {}
    f["fund_hold_trend"] = _trend(fh.get("latest_funds"), fh.get("previous_funds"),
                                  down_label="down", up_label="up")

    qm = sections.get("quant_matrix") or {}
    reso = qm.get("multi_period_resonance") or {}
    bull, bear, neu = (_num(reso.get(k)) for k in ("bull", "bear", "neutral"))
    f["model_bull"] = bull
    f["model_bear"] = bear
    total = (bull or 0) + (bear or 0) + (neu or 0)
    f["model_total"] = total if total else None
    f["model_bull_ratio"] = (bull / total) if (total and bull is not None) else None

    f["market_regime"] = inputs.get("market_regime")

    # ★ 差异化两项：Phase 1 不接（模型运行时 Phase 2 / 回测 Phase 3）
    f["kronos_direction"] = None
    f["backtest_winrate"] = None
    return f
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_panel_features.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add analysis/panel/features.py tests/test_panel_features.py
git commit -m "feat(panel): extract_features 抽 26 标准化特征（Phase 1 Task 2）"
```

---

### Task 3: 规则引擎 `rules.py`（12 旗舰 + 7 流派默认）

**Files:**
- Create: `analysis/panel/rules.py`
- Test: `tests/test_panel_rules.py`

每条规则签名 `rule_xxx(f: dict) -> {"score": int(0-100), "reasons": list[str]}`，`score` 为多头度（100 = 极多）。`score_to_signal(score)`：≥60 `bull`，≤40 `bear`，否则 `neutral`。

- [ ] **Step 1: 写失败测试 `tests/test_panel_rules.py`**

```python
from analysis.panel.rules import RULES, SCHOOL_DEFAULTS, score_to_signal


def test_score_to_signal_thresholds():
    assert score_to_signal(78) == "bull"
    assert score_to_signal(25) == "bear"
    assert score_to_signal(50) == "neutral"


def test_buffett_bull_on_high_roe_cheap():
    v = RULES["buffett"]({"roe": 22.0, "pe_industry_rank": 20.0, "net_profit_yoy": 18.0})
    assert v["score"] >= 70
    assert score_to_signal(v["score"]) == "bull"
    assert any("ROE" in r for r in v["reasons"])


def test_graham_bear_on_expensive():
    v = RULES["graham"]({"pe_industry_rank": 85.0, "pb": 6.0})
    assert score_to_signal(v["score"]) == "bear"


def test_zhao_bull_on_quant_seats_and_inflow():
    v = RULES["zhao"]({"quant_seat_appearances": 3, "main_net_inflow": 1e8,
                       "volume_ratio": 2.0})
    assert score_to_signal(v["score"]) == "bull"
    assert any("量化席位" in r for r in v["reasons"])


def test_technical_default_uses_indicators():
    bull = SCHOOL_DEFAULTS["D"]({"rsi": 28.0, "macd_hist": 0.3, "ma_alignment": "bull"})
    bear = SCHOOL_DEFAULTS["D"]({"rsi": 75.0, "macd_hist": -0.3, "ma_alignment": "bear"})
    assert score_to_signal(bull["score"]) == "bull"
    assert score_to_signal(bear["score"]) == "bear"


def test_quant_default_uses_model_ratio():
    v = SCHOOL_DEFAULTS["G"]({"model_bull_ratio": 0.7})
    assert score_to_signal(v["score"]) == "bull"


def test_all_rules_tolerate_empty_features():
    for fn in list(RULES.values()) + list(SCHOOL_DEFAULTS.values()):
        v = fn({})
        assert 0 <= v["score"] <= 100
        assert isinstance(v["reasons"], list)


def test_every_school_has_default():
    assert set(SCHOOL_DEFAULTS.keys()) == {"A", "B", "C", "D", "E", "F", "G"}


def test_twelve_flagship_rules_registered():
    expected = {"buffett", "munger", "graham", "fisher", "lynch", "wood",
                "soros", "dalio", "duan", "zhangkun", "zhao", "zhang_mz"}
    assert expected <= set(RULES.keys())
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_panel_rules.py -q`
Expected: FAIL（`ModuleNotFoundError: analysis.panel.rules`）

- [ ] **Step 3: 实现 `analysis/panel/rules.py`**

```python
"""12 旗舰手写规则 + 7 流派默认规则。规则纯函数，容忍 None 特征。"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

Features = Dict[str, Any]
Verdict = Dict[str, Any]


def _clamp(x: float, lo: int = 0, hi: int = 100) -> int:
    return int(round(max(lo, min(hi, x))))


def score_to_signal(score: int) -> str:
    if score >= 60:
        return "bull"
    if score <= 40:
        return "bear"
    return "neutral"


# ---------- A 价值派旗舰 ----------
def rule_buffett(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 20:
            score += 25; reasons.append(f"ROE {roe:.0f}% 优秀，护城河深厚")
        elif roe >= 15:
            score += 12; reasons.append(f"ROE {roe:.0f}% 稳健")
        elif roe < 8:
            score -= 20; reasons.append(f"ROE {roe:.0f}% 偏低，缺乏护城河")
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank <= 30:
            score += 15; reasons.append("行业估值分位低，有安全边际")
        elif rank >= 80:
            score -= 15; reasons.append("估值偏贵，安全边际不足")
    yoy = f.get("net_profit_yoy")
    if yoy is not None and yoy < 0:
        score -= 10; reasons.append("利润负增长，长期价值受损")
    return {"score": _clamp(score), "reasons": reasons}


def rule_munger(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 18:
            score += 28; reasons.append(f"高质量生意 ROE {roe:.0f}%")
        elif roe < 10:
            score -= 22; reasons.append("生意质量平庸")
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank >= 85:
            score -= 18; reasons.append("好公司但出价过高")
        elif rank <= 40:
            score += 10; reasons.append("合理价格的好公司")
    return {"score": _clamp(score), "reasons": reasons}


def rule_graham(f: Features) -> Verdict:
    score, reasons = 50.0, []
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank <= 20:
            score += 30; reasons.append("深度低估，烟蒂级安全边际")
        elif rank <= 40:
            score += 12; reasons.append("估值偏低")
        elif rank >= 60:
            score -= 25; reasons.append("估值超出安全边际，不碰")
    pb = f.get("pb")
    if pb is not None:
        if pb < 1.0:
            score += 12; reasons.append(f"破净 PB {pb:.2f}")
        elif pb > 5.0:
            score -= 10; reasons.append(f"PB {pb:.1f} 过高")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- B 成长派旗舰 ----------
def rule_fisher(f: Features) -> Verdict:
    score, reasons = 50.0, []
    yoy = f.get("net_profit_yoy")
    if yoy is not None:
        if yoy >= 30:
            score += 28; reasons.append(f"利润高增长 {yoy:.0f}%")
        elif yoy >= 15:
            score += 14; reasons.append(f"利润增长 {yoy:.0f}%")
        elif yoy < 0:
            score -= 22; reasons.append("成长性恶化")
    roe = f.get("roe")
    if roe is not None and roe >= 15:
        score += 8; reasons.append("高质量成长")
    return {"score": _clamp(score), "reasons": reasons}


def rule_lynch(f: Features) -> Verdict:
    score, reasons = 50.0, []
    yoy, pe = f.get("net_profit_yoy"), f.get("pe")
    if yoy is not None and pe is not None and pe > 0 and yoy > 0:
        peg = pe / yoy
        if peg < 1.0:
            score += 26; reasons.append(f"PEG {peg:.2f}<1，成长价廉")
        elif peg <= 1.5:
            score += 10; reasons.append(f"PEG {peg:.2f} 合理")
        elif peg > 2.0:
            score -= 20; reasons.append("成长配不上估值")
    elif yoy is not None and yoy >= 20:
        score += 12; reasons.append(f"高成长 {yoy:.0f}%")
    elif yoy is not None and yoy < 0:
        score -= 18; reasons.append("成长熄火")
    return {"score": _clamp(score), "reasons": reasons}


def rule_wood(f: Features) -> Verdict:
    score, reasons = 50.0, []
    yoy = f.get("net_profit_yoy")
    if yoy is not None and yoy >= 25:
        score += 22; reasons.append("高增长赛道")
    ratio = f.get("model_bull_ratio")
    if ratio is not None:
        if ratio >= 0.6:
            score += 18; reasons.append("趋势动能强劲")
        elif ratio <= 0.3:
            score -= 16; reasons.append("动能转弱")
    vol = f.get("volume_ratio")
    if vol is not None and vol >= 1.5:
        score += 8; reasons.append("放量关注度高")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- C 宏观派旗舰 ----------
def rule_soros(f: Features) -> Verdict:
    score, reasons = 50.0, []
    regime = f.get("market_regime")
    if regime == "bull":
        score += 16; reasons.append("顺大势：牛市趋势可加杠杆")
    elif regime == "bear":
        score -= 18; reasons.append("逆大势：熊市风险高")
    mh = f.get("macd_hist")
    if mh is not None:
        if mh > 0:
            score += 12; reasons.append("MACD 动能向上，反身性正反馈")
        else:
            score -= 12; reasons.append("MACD 动能向下")
    return {"score": _clamp(score), "reasons": reasons}


def rule_dalio(f: Features) -> Verdict:
    score, reasons = 50.0, []
    regime = f.get("market_regime")
    if regime == "bull":
        score += 10; reasons.append("经济机器扩张期")
    elif regime == "bear":
        score -= 14; reasons.append("去杠杆周期，防御为主")
    rsi = f.get("rsi")
    if rsi is not None and (rsi >= 80 or rsi <= 20):
        score -= 10; reasons.append("情绪极端，风险平价减仓")
    yoy = f.get("net_profit_yoy")
    if yoy is not None and yoy > 0:
        score += 6; reasons.append("基本面稳健")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- E 中国价投旗舰 ----------
def rule_duan(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 18:
            score += 24; reasons.append(f"好生意 ROE {roe:.0f}%，本分经营")
        elif roe < 8:
            score -= 18; reasons.append("商业模式一般")
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank <= 35:
            score += 14; reasons.append("价格合理，看长期")
        elif rank >= 85:
            score -= 12; reasons.append("贵了，宁可错过")
    return {"score": _clamp(score), "reasons": reasons}


def rule_zhangkun(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 20:
            score += 26; reasons.append(f"高 ROE {roe:.0f}% 优质龙头，长期持有")
        elif roe < 10:
            score -= 20; reasons.append("非优质资产")
    yoy = f.get("net_profit_yoy")
    if yoy is not None and yoy >= 10:
        score += 10; reasons.append("业绩稳定增长")
    rank = f.get("pe_industry_rank")
    if rank is not None and rank >= 90:
        score -= 10; reasons.append("估值偏高需耐心")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- F 游资派旗舰 ----------
def rule_zhao(f: Features) -> Verdict:
    score, reasons = 50.0, []
    seats = f.get("quant_seat_appearances")
    if seats is not None:
        if seats >= 3:
            score += 26; reasons.append(f"量化席位 90 日 {int(seats)} 次活跃")
        elif seats >= 1:
            score += 12; reasons.append("龙虎榜量化席位进场")
    main = f.get("main_net_inflow")
    if main is not None:
        if main > 0:
            score += 12; reasons.append("主力净流入承接")
        else:
            score -= 12; reasons.append("主力净流出")
    vol = f.get("volume_ratio")
    if vol is not None and vol >= 1.8:
        score += 10; reasons.append("放量打板情绪高")
    return {"score": _clamp(score), "reasons": reasons}


def rule_zhang_mz(f: Features) -> Verdict:
    score, reasons = 50.0, []
    net = f.get("lhb_net_inst_buy")
    if net is not None:
        if net > 0:
            score += 22; reasons.append("龙虎榜机构净买，龙头属性")
        else:
            score -= 16; reasons.append("龙虎榜净卖出，分歧加大")
    vol = f.get("volume_ratio")
    if vol is not None and vol >= 1.5:
        score += 14; reasons.append("放量做龙头")
    main = f.get("main_net_inflow")
    if main is not None and main > 0:
        score += 8; reasons.append("主力流入助攻")
    return {"score": _clamp(score), "reasons": reasons}


# ---------- 7 流派默认规则（39 stub 用）----------
def rule_value_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    roe = f.get("roe")
    if roe is not None:
        if roe >= 15:
            score += 16; reasons.append(f"ROE {roe:.0f}% 良好")
        elif roe < 8:
            score -= 16; reasons.append("盈利能力偏弱")
    rank = f.get("pe_industry_rank")
    if rank is not None:
        if rank <= 35:
            score += 12; reasons.append("估值偏低")
        elif rank >= 80:
            score -= 12; reasons.append("估值偏高")
    return {"score": _clamp(score), "reasons": reasons}


def rule_growth_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    yoy = f.get("net_profit_yoy")
    if yoy is not None:
        if yoy >= 25:
            score += 20; reasons.append(f"利润增长 {yoy:.0f}%")
        elif yoy >= 10:
            score += 8; reasons.append("稳健增长")
        elif yoy < 0:
            score -= 18; reasons.append("成长性走弱")
    return {"score": _clamp(score), "reasons": reasons}


def rule_macro_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    regime = f.get("market_regime")
    if regime == "bull":
        score += 14; reasons.append("大盘趋势向上")
    elif regime == "bear":
        score -= 16; reasons.append("大盘风险偏高")
    else:
        reasons.append("大盘震荡，中性观望")
    return {"score": _clamp(score), "reasons": reasons}


def rule_technical_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    rsi = f.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            score -= 12; reasons.append(f"RSI {rsi:.0f} 超买")
        elif rsi <= 30:
            score += 12; reasons.append(f"RSI {rsi:.0f} 超卖待反弹")
    mh = f.get("macd_hist")
    if mh is not None:
        if mh > 0:
            score += 10; reasons.append("MACD 红柱")
        else:
            score -= 10; reasons.append("MACD 绿柱")
    ma = f.get("ma_alignment")
    if ma == "bull":
        score += 12; reasons.append("均线多头排列")
    elif ma == "bear":
        score -= 12; reasons.append("均线空头排列")
    return {"score": _clamp(score), "reasons": reasons}


def rule_youzi_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    seats = f.get("quant_seat_appearances")
    if seats is not None and seats >= 1:
        score += 14; reasons.append("龙虎榜活跃")
    main = f.get("main_net_inflow")
    if main is not None:
        if main > 0:
            score += 12; reasons.append("主力净流入")
        else:
            score -= 12; reasons.append("主力净流出")
    vol = f.get("volume_ratio")
    if vol is not None and vol >= 1.5:
        score += 8; reasons.append("放量")
    return {"score": _clamp(score), "reasons": reasons}


def rule_quant_default(f: Features) -> Verdict:
    score, reasons = 50.0, []
    ratio = f.get("model_bull_ratio")
    if ratio is not None:
        if ratio >= 0.6:
            score += 22; reasons.append(f"30 模型 {int(ratio * 100)}% 看多共振")
        elif ratio <= 0.35:
            score -= 20; reasons.append(f"30 模型仅 {int(ratio * 100)}% 看多")
        else:
            reasons.append("模型多空胶着")
    return {"score": _clamp(score), "reasons": reasons}


RULES: Dict[str, Callable[[Features], Verdict]] = {
    "buffett": rule_buffett, "munger": rule_munger, "graham": rule_graham,
    "fisher": rule_fisher, "lynch": rule_lynch, "wood": rule_wood,
    "soros": rule_soros, "dalio": rule_dalio,
    "duan": rule_duan, "zhangkun": rule_zhangkun,
    "zhao": rule_zhao, "zhang_mz": rule_zhang_mz,
}

SCHOOL_DEFAULTS: Dict[str, Callable[[Features], Verdict]] = {
    "A": rule_value_default, "B": rule_growth_default, "C": rule_macro_default,
    "D": rule_technical_default, "E": rule_value_default,
    "F": rule_youzi_default, "G": rule_quant_default,
}


def resolve_rule(rule_key: str, school: str) -> Callable[[Features], Verdict]:
    """旗舰用 rule_key；stub 的 'school_default' 解析到流派默认规则。"""
    if rule_key == "school_default":
        return SCHOOL_DEFAULTS[school]
    return RULES[rule_key]
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_panel_rules.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add analysis/panel/rules.py tests/test_panel_rules.py
git commit -m "feat(panel): 12 旗舰规则 + 7 流派默认规则 + score_to_signal（Phase 1 Task 3）"
```

---

### Task 4: 风格分类 + 权重 `style.py` + `config/panel_style_weights.json`

**Files:**
- Create: `config/panel_style_weights.json`
- Create: `analysis/panel/style.py`
- Test: `tests/test_panel_engine.py`（追加 style 用例）

`classify_style(features)` 把股票分到 7 风格之一：`baima`(白马)/`growth`(高成长)/`cyclic`(周期)/`small_spec`(小盘投机)/`dividend`(分红)/`turnaround`(困境反转)/`quant`(量化活跃)，默认 `baima`。权重矩阵 `流派(A-G) × 风格`，缺省 1.0。

- [ ] **Step 1: 创建 `config/panel_style_weights.json`**

```json
{
  "_comment": "流派(A-G) × 股票风格 权重矩阵。Phase 1 静态默认；Phase 3 回测器联动调整。缺省 1.0。",
  "default": 1.0,
  "matrix": {
    "baima":      { "A": 1.3, "E": 1.3, "B": 1.0, "D": 0.8, "F": 0.6, "G": 0.9, "C": 1.0 },
    "growth":     { "B": 1.4, "A": 0.8, "E": 0.9, "D": 1.0, "F": 1.0, "G": 1.0, "C": 1.0 },
    "cyclic":     { "C": 1.3, "A": 1.0, "B": 0.9, "D": 1.1, "E": 0.9, "F": 0.9, "G": 1.0 },
    "small_spec": { "F": 1.5, "D": 1.2, "G": 1.1, "A": 0.5, "E": 0.5, "B": 0.8, "C": 0.8 },
    "dividend":   { "A": 1.3, "E": 1.2, "C": 1.1, "B": 0.7, "D": 0.8, "F": 0.5, "G": 0.9 },
    "turnaround": { "C": 1.2, "A": 1.1, "F": 1.1, "B": 1.0, "D": 1.0, "E": 1.0, "G": 1.0 },
    "quant":      { "G": 1.5, "D": 1.3, "F": 1.1, "A": 0.8, "B": 0.9, "C": 1.0, "E": 0.8 }
  }
}
```

- [ ] **Step 2: 写失败测试（追加到 `tests/test_panel_engine.py`）**

```python
from analysis.panel.style import classify_style, load_style_weights, school_style_weight


def test_classify_style_small_spec():
    # 高控盘 + 放量 + 无基本面 → 小盘投机
    style = classify_style({"control_degree": 80, "volume_ratio": 2.2,
                            "roe": None, "quant_seat_appearances": 3})
    assert style == "small_spec"


def test_classify_style_baima_default():
    style = classify_style({"roe": 20, "net_profit_yoy": 12, "control_degree": 30})
    assert style in ("baima", "growth")


def test_load_style_weights_has_matrix():
    w = load_style_weights()
    assert "matrix" in w and "default" in w


def test_school_style_weight_lookup():
    w = load_style_weights()
    # 小盘投机时游资派(F)权重应 > 价值派(A)
    assert school_style_weight("F", "small_spec", w) > school_style_weight("A", "small_spec", w)


def test_school_style_weight_falls_back_to_default():
    w = {"default": 1.0, "matrix": {}}
    assert school_style_weight("A", "unknown_style", w) == 1.0
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_panel_engine.py -q -k style`
Expected: FAIL（`ModuleNotFoundError: analysis.panel.style`）

- [ ] **Step 4: 实现 `analysis/panel/style.py`**

```python
"""股票风格分类 + 流派×风格 权重矩阵加载。"""
from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Dict

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "panel_style_weights.json"

STYLES = ("baima", "growth", "cyclic", "small_spec", "dividend", "turnaround", "quant")


def classify_style(f: Dict[str, Any]) -> str:
    """按特征启发式分到 7 风格之一。优先级：小盘投机 > 量化活跃 > 高成长 > 白马。"""
    control = f.get("control_degree")
    vol = f.get("volume_ratio")
    seats = f.get("quant_seat_appearances")
    roe = f.get("roe")
    yoy = f.get("net_profit_yoy")
    model_ratio = f.get("model_bull_ratio")

    # 小盘投机：高控盘 + 放量 + 龙虎榜活跃 + 基本面缺位
    if (control is not None and control >= 70) and (vol is not None and vol >= 1.8) \
            and (seats is not None and seats >= 1):
        return "small_spec"
    # 量化活跃：模型共振极端 + 放量
    if model_ratio is not None and (model_ratio >= 0.7 or model_ratio <= 0.2) \
            and (vol is not None and vol >= 1.5):
        return "quant"
    # 高成长
    if yoy is not None and yoy >= 30:
        return "growth"
    # 白马：高 ROE
    if roe is not None and roe >= 15:
        return "baima"
    return "baima"


@functools.lru_cache(maxsize=1)
def load_style_weights() -> Dict[str, Any]:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"default": 1.0, "matrix": {}}


def school_style_weight(school: str, style: str, weights: Dict[str, Any]) -> float:
    default = float(weights.get("default", 1.0))
    row = (weights.get("matrix") or {}).get(style) or {}
    try:
        return float(row.get(school, default))
    except (TypeError, ValueError):
        return default
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_panel_engine.py -q -k style`
Expected: PASS（5 passed）

- [ ] **Step 6: 提交**

```bash
git add config/panel_style_weights.json analysis/panel/style.py tests/test_panel_engine.py
git commit -m "feat(panel): 风格分类 + 流派×风格 权重矩阵（独立 config，Phase 1 Task 4）"
```

---

### Task 5: 引擎 `engine.py`（evaluate_all / consensus / great_divide / schools）

**Files:**
- Create: `analysis/panel/engine.py`
- Test: `tests/test_panel_engine.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 `tests/test_panel_engine.py`）**

```python
from analysis.panel.engine import (
    evaluate_all, compute_consensus, compute_great_divide, compute_schools,
    consensus_label, lean_label,
)


def _analysts_fixture():
    # 构造一组可控裁决（绕过真实规则）
    return [
        {"id": "a1", "name": "多1", "school": "F", "signal": "bull", "score": 92,
         "headline": "量化席位活跃", "source": "handwritten", "reasons": ["量化席位活跃"]},
        {"id": "a2", "name": "多2", "school": "B", "signal": "bull", "score": 70,
         "headline": "高成长", "source": "rule", "reasons": ["高成长"]},
        {"id": "a3", "name": "空1", "school": "A", "signal": "bear", "score": 25,
         "headline": "估值超出安全边际", "source": "handwritten", "reasons": ["估值超出安全边际"]},
        {"id": "a4", "name": "中1", "school": "C", "signal": "neutral", "score": 50,
         "headline": "震荡观望", "source": "rule", "reasons": ["震荡观望"]},
    ]


def test_evaluate_all_returns_one_verdict_per_persona():
    from analysis.panel.registry import load_personas
    features = {"roe": 22, "pe_industry_rank": 20, "net_profit_yoy": 35,
                "main_net_inflow": 1e8, "quant_seat_appearances": 3, "volume_ratio": 2.0,
                "rsi": 28, "macd_hist": 0.3, "ma_alignment": "bull", "model_bull_ratio": 0.7,
                "market_regime": "bull"}
    analysts = evaluate_all(load_personas(), features)
    assert len(analysts) == 51
    sample = analysts[0]
    assert {"id", "name", "school", "signal", "score", "headline", "source", "reasons"} <= set(sample.keys())
    assert sample["signal"] in ("bull", "bear", "neutral")
    # 旗舰 → source=handwritten；stub → source=rule
    sources = {a["id"]: a["source"] for a in analysts}
    assert sources["buffett"] == "handwritten"
    assert sources["templeton"] == "rule"


def test_compute_consensus_counts_and_weighted_score():
    c = compute_consensus(_analysts_fixture(), style="baima")
    assert c["bull"] == 2 and c["bear"] == 1 and c["neutral"] == 1
    assert 0 <= c["score"] <= 100
    assert isinstance(c["label"], str)


def test_compute_great_divide_picks_extremes():
    gd = compute_great_divide(_analysts_fixture())
    assert gd["bull"]["id"] == "a1" and gd["bull"]["score"] == 92
    assert gd["bear"]["id"] == "a3" and gd["bear"]["score"] == 25
    assert "量化席位活跃" in gd["punchline"]
    assert "估值超出安全边际" in gd["punchline"]


def test_compute_great_divide_handles_no_bear():
    only_bulls = [a for a in _analysts_fixture() if a["signal"] == "bull"]
    gd = compute_great_divide(only_bulls)
    assert gd["bull"] is not None
    assert gd["bear"] is None
    assert isinstance(gd["punchline"], str)


def test_compute_schools_aggregates_seven():
    from analysis.panel.registry import load_personas
    features = {"market_regime": "sideways"}
    analysts = evaluate_all(load_personas(), features)
    schools = compute_schools(analysts)
    assert len(schools) == 7
    keys = {s["key"] for s in schools}
    assert keys == {"A", "B", "C", "D", "E", "F", "G"}
    for s in schools:
        assert {"key", "name", "count", "lean", "lean_score"} <= set(s.keys())
    assert sum(s["count"] for s in schools) == 51


def test_consensus_and_lean_labels():
    assert consensus_label(70) == "强烈看多"
    assert consensus_label(57) == "偏多"
    assert consensus_label(50) == "中性"
    assert consensus_label(40) == "偏空"
    assert consensus_label(30) == "强烈看空"
    assert lean_label(58) == "偏多" and lean_label(42) == "偏空"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_panel_engine.py -q -k "evaluate or consensus or great_divide or schools or label"`
Expected: FAIL（`ModuleNotFoundError: analysis.panel.engine`）

- [ ] **Step 3: 实现 `analysis/panel/engine.py`**

```python
"""panel 聚合：裁决全部 persona → 共识 / 大分歧 / 流派。纯规则。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from analysis.panel.registry import SCHOOLS
from analysis.panel.rules import resolve_rule, score_to_signal
from analysis.panel.style import (
    classify_style, load_style_weights, school_style_weight,
)


def consensus_label(score: float) -> str:
    if score >= 65:
        return "强烈看多"
    if score >= 55:
        return "偏多"
    if score >= 45:
        return "中性"
    if score >= 35:
        return "偏空"
    return "强烈看空"


def lean_label(score: float) -> str:
    if score >= 55:
        return "偏多"
    if score >= 45:
        return "中性"
    return "偏空"


def evaluate_all(personas: List[Dict[str, Any]], features: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in personas:
        rule_fn = resolve_rule(p["rule"], p["school"])
        verdict = rule_fn(features)
        score = int(verdict["score"])
        reasons = verdict.get("reasons") or []
        headline = reasons[0] if reasons else p.get("voice", "—")
        out.append({
            "id": p["id"],
            "name": p["name"],
            "school": p["school"],
            "signal": score_to_signal(score),
            "score": score,
            "headline": headline,
            "source": "handwritten" if p["tier"] == "flagship" else "rule",
            "reasons": reasons,
        })
    return out


def compute_consensus(analysts: List[Dict[str, Any]], style: str) -> Dict[str, Any]:
    weights = load_style_weights()
    num = den = 0.0
    bull = bear = neutral = 0
    for a in analysts:
        w = school_style_weight(a["school"], style, weights)
        num += a["score"] * w
        den += w
        if a["signal"] == "bull":
            bull += 1
        elif a["signal"] == "bear":
            bear += 1
        else:
            neutral += 1
    score = int(round(num / den)) if den else 50
    return {"score": score, "label": consensus_label(score),
            "bull": bull, "neutral": neutral, "bear": bear}


def _slim(a: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if a is None:
        return None
    return {"id": a["id"], "name": a["name"], "school": a["school"], "score": a["score"]}


def compute_great_divide(analysts: List[Dict[str, Any]]) -> Dict[str, Any]:
    bulls = [a for a in analysts if a["signal"] == "bull"]
    bears = [a for a in analysts if a["signal"] == "bear"]
    top_bull = max(bulls, key=lambda a: a["score"]) if bulls else None
    top_bear = min(bears, key=lambda a: a["score"]) if bears else None
    if top_bull and top_bear:
        bull_reason = (top_bull["reasons"] or ["看多"])[0]
        bear_reason = (top_bear["reasons"] or ["看空"])[0]
        punchline = f"{top_bull['name']} 看到 {bull_reason}，{top_bear['name']} 担心 {bear_reason}"
    elif top_bull:
        punchline = f"{top_bull['name']} 领衔看多，暂无明确看空声音"
    elif top_bear:
        punchline = f"{top_bear['name']} 领衔看空，暂无明确看多声音"
    else:
        punchline = "多空分歧不明显，全员观望"
    return {"bull": _slim(top_bull), "bear": _slim(top_bear), "punchline": punchline}


def compute_schools(analysts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, name in SCHOOLS.items():
        members = [a for a in analysts if a["school"] == key]
        if members:
            lean_score = int(round(sum(a["score"] for a in members) / len(members)))
        else:
            lean_score = 50
        out.append({
            "key": key, "name": name, "count": len(members),
            "lean": lean_label(lean_score), "lean_score": lean_score,
        })
    return out


def classify_panel_style(features: Dict[str, Any]) -> str:
    return classify_style(features)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_panel_engine.py -q`
Expected: PASS（全部 panel_engine 用例）

- [ ] **Step 5: 提交**

```bash
git add analysis/panel/engine.py tests/test_panel_engine.py
git commit -m "feat(panel): 引擎——裁决/共识/大分歧/流派聚合（Phase 1 Task 5）"
```

---

### Task 6: 16 指标聚合器 `indicators.py`

**Files:**
- Create: `analysis/panel/indicators.py`
- Test: `tests/test_panel_indicators.py`

每格：`{group, key, label, value_text, signal: "up"/"down"/"neutral", strength: 0..1, data_status}`。`group ∈ capital/technical/chip/model`。★ kronos_pred / backtest_winrate 恒 `unavailable` + `neutral`。

- [ ] **Step 1: 写失败测试 `tests/test_panel_indicators.py`**

```python
from analysis.panel.indicators import build_indicators, GROUPS


def _features(**over):
    base = {
        "main_net_inflow": 1.2e8, "north_delta_30d": 0.6, "super_large_net": 8e7,
        "quant_seat_appearances": 2, "lhb_net_inst_buy": 5e7,
        "rsi": 28.0, "macd_hist": 0.3, "kdj_j": 90.0, "ma_alignment": "bull",
        "boll_position": 0.85, "volume_ratio": 1.9,
        "control_degree": 72.0, "holder_number_trend": "down", "fund_hold_trend": "up",
        "model_bull_ratio": 0.6, "model_bull": 18, "model_bear": 6,
        "kronos_direction": None, "backtest_winrate": None,
    }
    base.update(over)
    return base


def test_build_indicators_has_16_items():
    inds = build_indicators(_features())
    assert len(inds) == 16
    for it in inds:
        assert {"group", "key", "label", "value_text", "signal", "strength", "data_status"} <= set(it.keys())
        assert it["group"] in GROUPS
        assert it["signal"] in ("up", "down", "neutral")
        assert 0.0 <= it["strength"] <= 1.0


def test_group_counts_match_spec():
    inds = build_indicators(_features())
    counts = {g: 0 for g in GROUPS}
    for it in inds:
        counts[it["group"]] += 1
    assert counts == {"capital": 4, "technical": 6, "chip": 3, "model": 3}


def test_main_capital_up_on_inflow():
    inds = {it["key"]: it for it in build_indicators(_features(main_net_inflow=2e8))}
    assert inds["main_capital"]["signal"] == "up"
    inds_out = {it["key"]: it for it in build_indicators(_features(main_net_inflow=-2e8))}
    assert inds_out["main_capital"]["signal"] == "down"


def test_rsi_oversold_is_up_overbought_is_down():
    up = {it["key"]: it for it in build_indicators(_features(rsi=25.0))}
    down = {it["key"]: it for it in build_indicators(_features(rsi=78.0))}
    assert up["rsi"]["signal"] == "up"
    assert down["rsi"]["signal"] == "down"


def test_star_indicators_unavailable_in_phase1():
    inds = {it["key"]: it for it in build_indicators(_features())}
    assert inds["kronos_pred"]["data_status"] == "unavailable"
    assert inds["kronos_pred"]["signal"] == "neutral"
    assert inds["backtest_winrate"]["data_status"] == "unavailable"


def test_missing_feature_degrades_to_unavailable_neutral():
    inds = {it["key"]: it for it in build_indicators(_features(main_net_inflow=None))}
    assert inds["main_capital"]["data_status"] == "unavailable"
    assert inds["main_capital"]["signal"] == "neutral"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_panel_indicators.py -q`
Expected: FAIL（`ModuleNotFoundError: analysis.panel.indicators`）

- [ ] **Step 3: 实现 `analysis/panel/indicators.py`**

```python
"""16 项量化指标聚合（4 组）。从 features 派生多空信号，复用 Task 2 特征（DRY）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

GROUPS = ("capital", "technical", "chip", "model")


def _amount_text(v: float) -> str:
    a = abs(v)
    sign = "净流入" if v >= 0 else "净流出"
    if a >= 1e8:
        return f"{sign} {v / 1e8:.2f} 亿"
    if a >= 1e4:
        return f"{sign} {v / 1e4:.2f} 万"
    return f"{sign} {v:.0f}"


def _ind(group: str, key: str, label: str, *, value_text: str, signal: str,
         strength: float, data_status: str = "fresh") -> Dict[str, Any]:
    return {"group": group, "key": key, "label": label, "value_text": value_text,
            "signal": signal, "strength": max(0.0, min(1.0, strength)),
            "data_status": data_status}


def _unavailable(group: str, key: str, label: str, note: str = "数据不足") -> Dict[str, Any]:
    return _ind(group, key, label, value_text=note, signal="neutral",
                strength=0.0, data_status="unavailable")


def _signed(group: str, key: str, label: str, value: Optional[float], *,
            value_text: str, scale: float) -> Dict[str, Any]:
    """正 → up(红/多)，负 → down(绿/空)。strength 按 |value|/scale 归一。"""
    if value is None:
        return _unavailable(group, key, label)
    signal = "up" if value > 0 else ("down" if value < 0 else "neutral")
    return _ind(group, key, label, value_text=value_text, signal=signal,
                strength=min(1.0, abs(value) / scale) if scale else 0.0)


def build_indicators(f: Dict[str, Any]) -> List[Dict[str, Any]]:
    inds: List[Dict[str, Any]] = []

    # ---- 资金面 (4) ----
    main = f.get("main_net_inflow")
    inds.append(_unavailable("capital", "main_capital", "主力资金") if main is None
                else _signed("capital", "main_capital", "主力资金", main,
                             value_text=_amount_text(main), scale=2e8))
    north = f.get("north_delta_30d")
    inds.append(_unavailable("capital", "north_capital", "北向资金") if north is None
                else _signed("capital", "north_capital", "北向资金", north,
                             value_text=f"30 日持股比 {'+' if north >= 0 else ''}{north:.2f}%",
                             scale=1.0))
    elg = f.get("super_large_net")
    inds.append(_unavailable("capital", "super_large", "超大单") if elg is None
                else _signed("capital", "super_large", "超大单", elg,
                             value_text=_amount_text(elg), scale=1.5e8))
    seats = f.get("quant_seat_appearances")
    lhb_net = f.get("lhb_net_inst_buy")
    if seats is None and lhb_net is None:
        inds.append(_unavailable("capital", "lhb_seat", "龙虎榜席位"))
    else:
        s = seats or 0
        net = lhb_net or 0
        if s >= 1 and net > 0:
            sig, strg = "up", min(1.0, 0.4 + s * 0.2)
        elif net < 0:
            sig, strg = "down", min(1.0, abs(net) / 1e8)
        else:
            sig, strg = "neutral", 0.2
        inds.append(_ind("capital", "lhb_seat", "龙虎榜席位",
                         value_text=f"量化席位 {int(s)} 次 / {_amount_text(net)}",
                         signal=sig, strength=strg))

    # ---- 技术面 (6) ----
    rsi = f.get("rsi")
    if rsi is None:
        inds.append(_unavailable("technical", "rsi", "RSI"))
    else:
        sig = "up" if rsi <= 30 else ("down" if rsi >= 70 else "neutral")
        inds.append(_ind("technical", "rsi", "RSI", value_text=f"{rsi:.0f}",
                         signal=sig, strength=abs(rsi - 50) / 50))
    mh = f.get("macd_hist")
    inds.append(_unavailable("technical", "macd", "MACD") if mh is None
                else _signed("technical", "macd", "MACD", mh,
                             value_text=f"柱 {mh:+.3f}", scale=0.5))
    kdj = f.get("kdj_j")
    if kdj is None:
        inds.append(_unavailable("technical", "kdj", "KDJ"))
    else:
        sig = "up" if kdj <= 0 else ("down" if kdj >= 100 else
                                     ("up" if kdj >= 50 else "down"))
        inds.append(_ind("technical", "kdj", "KDJ", value_text=f"J {kdj:.0f}",
                         signal=sig, strength=min(1.0, abs(kdj - 50) / 50)))
    ma = f.get("ma_alignment")
    if ma is None:
        inds.append(_unavailable("technical", "ma_align", "均线排列"))
    else:
        sig = {"bull": "up", "bear": "down", "mixed": "neutral"}[ma]
        text = {"bull": "多头排列", "bear": "空头排列", "mixed": "交织"}[ma]
        inds.append(_ind("technical", "ma_align", "均线排列", value_text=text,
                         signal=sig, strength=0.7 if ma != "mixed" else 0.2))
    boll = f.get("boll_position")
    if boll is None:
        inds.append(_unavailable("technical", "boll", "布林带"))
    else:
        sig = "up" if boll >= 0.8 else ("down" if boll <= 0.2 else "neutral")
        inds.append(_ind("technical", "boll", "布林带",
                         value_text=f"带内位置 {boll * 100:.0f}%",
                         signal=sig, strength=abs(boll - 0.5) * 2))
    vol = f.get("volume_ratio")
    if vol is None:
        inds.append(_unavailable("technical", "volume", "量能"))
    else:
        sig = "up" if vol >= 1.5 else ("down" if vol <= 0.7 else "neutral")
        inds.append(_ind("technical", "volume", "量能", value_text=f"量比 {vol:.2f}",
                         signal=sig, strength=min(1.0, abs(vol - 1.0))))

    # ---- 筹码·机构 (3) ----
    ctrl = f.get("control_degree")
    if ctrl is None:
        inds.append(_unavailable("chip", "control", "控盘度"))
    else:
        sig = "up" if ctrl >= 60 else ("down" if ctrl <= 30 else "neutral")
        inds.append(_ind("chip", "control", "控盘度", value_text=f"{ctrl:.0f}",
                         signal=sig, strength=ctrl / 100))
    hn = f.get("holder_number_trend")
    if hn is None:
        inds.append(_unavailable("chip", "holder_number", "股东户数"))
    else:
        sig = {"down": "up", "up": "down", "flat": "neutral"}[hn]  # 户数减少=筹码集中=多
        text = {"down": "户数减少（筹码集中）", "up": "户数增加（筹码分散）", "flat": "持平"}[hn]
        inds.append(_ind("chip", "holder_number", "股东户数", value_text=text,
                         signal=sig, strength=0.6 if hn != "flat" else 0.1))
    fh = f.get("fund_hold_trend")
    if fh is None:
        inds.append(_unavailable("chip", "fund_hold", "重仓基金"))
    else:
        sig = {"up": "up", "down": "down", "flat": "neutral"}[fh]
        text = {"up": "基金增持", "down": "基金减持", "flat": "持平"}[fh]
        inds.append(_ind("chip", "fund_hold", "重仓基金", value_text=text,
                         signal=sig, strength=0.6 if fh != "flat" else 0.1))

    # ---- 模型·预测 (3) ----
    ratio = f.get("model_bull_ratio")
    if ratio is None:
        inds.append(_unavailable("model", "model_resonance", "30模型共振"))
    else:
        sig = "up" if ratio >= 0.55 else ("down" if ratio <= 0.4 else "neutral")
        bull = int(f.get("model_bull") or 0)
        bear = int(f.get("model_bear") or 0)
        inds.append(_ind("model", "model_resonance", "30模型共振",
                         value_text=f"多 {bull} / 空 {bear}",
                         signal=sig, strength=abs(ratio - 0.5) * 2))
    # ★ 差异化两项：Phase 1 显式降级（模型运行时 Phase 2 / 回测 Phase 3）
    inds.append(_unavailable("model", "kronos_pred", "★Kronos预测", "Phase 2 接入"))
    inds.append(_unavailable("model", "backtest_winrate", "★回测胜率", "Phase 3 接入"))

    return inds
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_panel_indicators.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add analysis/panel/indicators.py tests/test_panel_indicators.py
git commit -m "feat(panel): 16 指标聚合器（4 组，★ 两项 Phase 1 降级）（Phase 1 Task 6）"
```

---

### Task 7: 编排器 `build_panel` + 接入 suite `_collect_panel` + payload `panel` key

**Files:**
- Modify: `analysis/panel/__init__.py`
- Modify: `analysis/stock_analysis_suite.py`（`_compute_full_payload` ~L226-250，`_build_payload_with_institutional` ~L391-398）
- Test: `tests/test_panel_engine.py`（追加 build_panel）、`tests/test_stock_analysis_suite.py`（追加 payload 集成）

- [ ] **Step 1: 写失败测试（追加到 `tests/test_panel_engine.py`）**

```python
from analysis.panel import build_panel


def _full_inputs():
    import numpy as np, pandas as pd
    rng = np.random.default_rng(2)
    close = pd.Series(10 + rng.normal(0, 0.2, 80).cumsum() * 0.1)
    df = pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=80, freq="D"),
        "open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": pd.Series(rng.integers(1e6, 5e6, 80).astype(float)),
        "amount": close * 1e6})
    return {
        "ohlcv": df,
        "capital_flow": {"details": {"order_analysis": {"main_net_inflow": 1.2e8,
                         "super_large_net": 8e7, "retail_net_inflow": -3e7},
                         "positive_days_5d": 3}},
        "fundamental": {"pe": 18.0, "pb": 2.1, "roe": 22.0,
                        "pe_industry_rank": 28.0, "net_profit_yoy": 35.0},
        "market_regime": "bull"}


def _full_sections():
    return {
        "main_force_deep": {"data_status": "fresh",
            "dragon_tiger": {"quant_seat_appearances": 2, "net_inst_buy": 5e7},
            "hsgt": {"latest": {"hold_ratio": 4.1}, "delta": 0.6}},
        "chip_control": {"data_status": "fresh", "control_degree": 72},
        "institutional_holdings": {"data_status": "stale",
            "holder_number": {"latest": 50000, "previous": 56000},
            "fund_holds": {"latest_funds": 30, "previous_funds": 24}},
        "quant_matrix": {"data_status": "fresh",
            "multi_period_resonance": {"bull": 18, "bear": 6, "neutral": 6}}}


def test_build_panel_full_shape():
    panel = build_panel(_full_inputs(), _full_sections())
    assert panel["data_status"] in ("fresh", "stale")
    assert len(panel["analysts"]) == 51
    assert len(panel["schools"]) == 7
    assert len(panel["indicators"]) == 16
    assert {"score", "label", "bull", "neutral", "bear"} <= set(panel["consensus"].keys())
    assert {"bull", "bear", "punchline"} <= set(panel["great_divide"].keys())
    assert panel["last_updated"] is not None


def test_build_panel_degrades_when_all_empty():
    panel = build_panel({}, {})
    # 无任何数据源 → unavailable，但结构仍完整（51 人走中性默认）
    assert panel["data_status"] == "unavailable"
    assert len(panel["analysts"]) == 51
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_panel_engine.py -q -k build_panel`
Expected: FAIL（`ImportError: cannot import name 'build_panel'`）

- [ ] **Step 3: 实现 `analysis/panel/__init__.py`**

```python
"""多空评审团 panel 引擎（纯规则，无 LLM）。Phase 1。"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict

from analysis.panel.engine import (
    classify_panel_style, compute_consensus, compute_great_divide,
    compute_schools, evaluate_all,
)
from analysis.panel.features import extract_features
from analysis.panel.indicators import build_indicators
from analysis.panel.registry import load_personas

# 决定 panel 整体 data_status 的关键数据源段
_KEY_SECTIONS = ("main_force_deep", "chip_control", "quant_matrix")


def _overall_status(inputs: Dict[str, Any], sections: Dict[str, Any]) -> str:
    has_ohlcv = inputs.get("ohlcv") is not None and len(inputs.get("ohlcv")) >= 35
    has_fundamental = bool(inputs.get("fundamental"))
    statuses = [(sections.get(k) or {}).get("data_status") for k in _KEY_SECTIONS]
    any_fresh = has_ohlcv or has_fundamental or any(s == "fresh" for s in statuses)
    any_stale = any(s == "stale" for s in statuses)
    if any_fresh:
        return "fresh"
    if any_stale:
        return "stale"
    return "unavailable"


def build_panel(inputs: Dict[str, Any], sections: Dict[str, Any]) -> Dict[str, Any]:
    """从既有 inputs + 已装配 payload 段构建多空评审团 panel。"""
    inputs = inputs or {}
    sections = sections or {}
    features = extract_features(inputs, sections)
    personas = load_personas()
    analysts = evaluate_all(personas, features)
    style = classify_panel_style(features)
    return {
        "data_status": _overall_status(inputs, sections),
        "last_updated": _dt.datetime.now().isoformat(timespec="seconds"),
        "style": style,
        "consensus": compute_consensus(analysts, style),
        "great_divide": compute_great_divide(analysts),
        "schools": compute_schools(analysts),
        "analysts": analysts,
        "indicators": build_indicators(features),
    }
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_panel_engine.py -q -k build_panel`
Expected: PASS（2 passed）

- [ ] **Step 5: 接入 suite — 在 `analysis/stock_analysis_suite.py` 加 `_collect_panel` 方法**

在 `_collect_quant_matrix` 方法之后（约 L378 之后）插入：

```python
    def _collect_panel(self, code: str, inputs: dict | None, sections: dict) -> dict:
        """多空评审团：51 persona 规则裁决 + 16 指标 + 共识/大分歧（spec §0/§11 Phase 1）。
        纯规则，无 LLM。任何异常降级 unavailable，不影响其它 Tab。"""
        try:
            from analysis.panel import build_panel
            return build_panel(inputs or {}, sections)
        except Exception as exc:  # noqa: BLE001
            return {
                **_unavailable_section(f"panel 计算失败：{exc}"),
                "consensus": None, "great_divide": None,
                "schools": [], "analysts": [], "indicators": [],
            }
```

- [ ] **Step 6: 在 `_compute_full_payload` 装配 `panel`（修改 `analysis/stock_analysis_suite.py` L226-250）**

把现有：
```python
        main_force_deep = self._collect_main_force_deep(code)
        institutional_holdings = self._collect_institutional_holdings(code)
        chip_control = self._collect_chip_control(code, chip=inputs.get("chip"))
        quant_matrix = self._collect_quant_matrix(code, models=inputs.get("models"))
        return {
            "overview": overview,
            "risk_control": risk,
            "cached_reports": cached,
            "ai_interpretation": {
                "status": "not_generated",
                "report": None,
                "token_usage": None,
                "generated_at": None,
                "trigger_endpoint": f"/api/stock-analysis-suite/{code}/ai",
            },
            "stub_tabs": [
                "market_cycle", "main_force_phase", "volume_price_game",
                "chip_structure", "performance", "probability", "limit_up_screening",
            ],
            "warnings": warnings_,
            "main_force_deep": main_force_deep,
            "institutional_holdings": institutional_holdings,
            "chip_control": chip_control,
            "quant_matrix": quant_matrix,
        }
```
改为（仅新增 `panel` 计算 + key，其它不动）：
```python
        main_force_deep = self._collect_main_force_deep(code)
        institutional_holdings = self._collect_institutional_holdings(code)
        chip_control = self._collect_chip_control(code, chip=inputs.get("chip"))
        quant_matrix = self._collect_quant_matrix(code, models=inputs.get("models"))
        panel = self._collect_panel(code, inputs, {
            "main_force_deep": main_force_deep,
            "institutional_holdings": institutional_holdings,
            "chip_control": chip_control,
            "quant_matrix": quant_matrix,
            "overview": overview,
        })
        return {
            "overview": overview,
            "risk_control": risk,
            "cached_reports": cached,
            "ai_interpretation": {
                "status": "not_generated",
                "report": None,
                "token_usage": None,
                "generated_at": None,
                "trigger_endpoint": f"/api/stock-analysis-suite/{code}/ai",
            },
            "stub_tabs": [
                "market_cycle", "main_force_phase", "volume_price_game",
                "chip_structure", "performance", "probability", "limit_up_screening",
            ],
            "warnings": warnings_,
            "main_force_deep": main_force_deep,
            "institutional_holdings": institutional_holdings,
            "chip_control": chip_control,
            "quant_matrix": quant_matrix,
            "panel": panel,
        }
```

- [ ] **Step 7: 也在 `_build_payload_with_institutional` 加 panel（保持测试辅助一致，L391-398）**

把：
```python
    def _build_payload_with_institutional(self, code: str) -> dict:
        """Build only the institutional portion of the payload (for testing)."""
        return {
            "main_force_deep": self._collect_main_force_deep(code),
            "institutional_holdings": self._collect_institutional_holdings(code),
            "chip_control": self._collect_chip_control(code),
            "quant_matrix": self._collect_quant_matrix(code),
        }
```
改为：
```python
    def _build_payload_with_institutional(self, code: str) -> dict:
        """Build only the institutional portion of the payload (for testing)."""
        mfd = self._collect_main_force_deep(code)
        ih = self._collect_institutional_holdings(code)
        cc = self._collect_chip_control(code)
        qm = self._collect_quant_matrix(code)
        return {
            "main_force_deep": mfd,
            "institutional_holdings": ih,
            "chip_control": cc,
            "quant_matrix": qm,
            "panel": self._collect_panel(code, {}, {
                "main_force_deep": mfd, "institutional_holdings": ih,
                "chip_control": cc, "quant_matrix": qm, "overview": None,
            }),
        }
```

- [ ] **Step 8: 写集成测试（追加到 `tests/test_stock_analysis_suite.py` 文件末尾）**

```python
# --- Phase 1 panel 集成测试 ---


def test_compute_full_payload_includes_panel(monkeypatch):
    """payload 必含 panel 顶层 key，且 51 人 / 16 指标 / 7 流派齐全；既有 key 不丢。"""
    from analysis import stock_analysis_suite as mod

    class _Chip:
        def analyze(self, code, df):
            return {"details": {"main_force_control": 72, "concentration_90": 15.9,
                                "profit_ratio": 50}, "signals": []}

    class _Cap:
        def analyze(self, code, df):
            return {"details": {"order_analysis": {"main_net_inflow": 1.2e8,
                    "super_large_net": 8e7, "retail_net_inflow": -3e7},
                    "positive_days_5d": 3}, "signals": []}

    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {"financial_indicators": {"pe": 18.0, "roe": 22.0},
                    "industry_comparison": {"pe_rank": 28.0},
                    "financial_reports": {"net_profit_yoy": 35.0}}

    monkeypatch.setattr(mod, "ChipAnalyzer", _Chip)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _Cap)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]
    suite._classify_market_regime = lambda: ("bull", 0.6)  # type: ignore[attr-defined]
    suite._run_quant_models = lambda code, df: {"buy_signal_count": 18, "sell_signal_count": 6, "hold_signal_count": 6, "total": 30, "per_model": []}  # type: ignore[attr-defined]

    payload = suite._compute_full_payload("000001")
    # 既有 key 不丢（向后兼容）
    for key in ("overview", "risk_control", "main_force_deep", "quant_matrix"):
        assert key in payload
    # 新 panel key
    assert "panel" in payload
    panel = payload["panel"]
    assert len(panel["analysts"]) == 51
    assert len(panel["indicators"]) == 16
    assert len(panel["schools"]) == 7
    assert panel["consensus"]["bull"] + panel["consensus"]["neutral"] + panel["consensus"]["bear"] == 51


def test_collect_panel_degrades_on_failure(monkeypatch):
    """build_panel 抛异常时，panel 降级 unavailable 且不影响 payload 其它部分。"""
    suite = StockAnalysisSuite()
    import analysis.panel as panel_mod
    monkeypatch.setattr(panel_mod, "build_panel",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    section = suite._collect_panel("000001", {}, {})
    assert section["data_status"] == "unavailable"
    assert section["analysts"] == []
```

- [ ] **Step 9: 运行测试，确认通过 + 全量回归（确认向后兼容）**

Run: `.venv/bin/python -m pytest tests/test_stock_analysis_suite.py tests/test_panel_engine.py -q`
Expected: PASS（全部，含既有 M1 用例不回归）

- [ ] **Step 10: 提交**

```bash
git add analysis/panel/__init__.py analysis/stock_analysis_suite.py tests/test_panel_engine.py tests/test_stock_analysis_suite.py
git commit -m "feat(panel): build_panel 编排器 + suite 接入 panel 顶层 key（Phase 1 Task 7）"
```

---

### Task 8: 前端骨架 — Tab #16 按钮 + pane + dispatch 接线

**Files:**
- Modify: `webui/templates/desktop.html`（nav L759 前、pane L778 前、dispatch L2581/L2684 前、paneIdMap L2665 前/L2857 区）

> **验证配方（来自项目记忆 [[webui-desktop-verification-recipe]]）：** 改完 desktop.html 后跑：① `import webui.robyn_app`；② Jinja `parse()`；③ 抽 `<script>` 块 `node --check`；④ pytest webui 用例。macOS 无 `timeout` 命令。

- [ ] **Step 1: 加 Tab 按钮（在 `ai_interpretation` 按钮 L759 之前插入）**

定位：
```html
            <button data-suite-tab="institutional_holdings" class="suite-tab" type="button">机构持仓</button>
            <button data-suite-tab="ai_interpretation"   class="suite-tab" type="button">AI 解读</button>
```
在两行之间插入：
```html
            <button data-suite-tab="panel"               class="suite-tab" type="button">多空评审团</button>
```

- [ ] **Step 2: 加 pane 容器（在 `suitePaneAi` L778 之前插入）**

定位：
```html
            <div class="suite-pane hidden" data-suite-pane="institutional_holdings" id="suitePaneHoldings"></div>
            <div class="suite-pane hidden" data-suite-pane="ai_interpretation" id="suitePaneAi"></div>
```
在两行之间插入：
```html
            <div class="suite-pane hidden" data-suite-pane="panel" id="suitePanePanel"></div>
```

- [ ] **Step 3: dispatch 块 1 接线（`renderActiveSuiteTab`，在 L2581 `ai_interpretation` 分支之前）**

定位：
```javascript
        else if (tab === "institutional_holdings") renderSuiteHoldings(payload);
        else if (tab === "ai_interpretation") renderSuiteAi(payload);
```
改为：
```javascript
        else if (tab === "institutional_holdings") renderSuiteHoldings(payload);
        else if (tab === "panel") renderSuitePanel(payload);
        else if (tab === "ai_interpretation") renderSuiteAi(payload);
```

- [ ] **Step 4: dispatch 块 2 接线（tab 点击加载，在 L2684 `ai_interpretation` 分支之前）**

定位（第二处，约 L2683-2684）：
```javascript
          else if (tab === "institutional_holdings") renderSuiteHoldings(payload);
          else if (tab === "ai_interpretation") renderSuiteAi(payload);
```
改为：
```javascript
          else if (tab === "institutional_holdings") renderSuiteHoldings(payload);
          else if (tab === "panel") renderSuitePanel(payload);
          else if (tab === "ai_interpretation") renderSuiteAi(payload);
```

- [ ] **Step 5: paneIdMap 接线（L2651-2666 的映射，`ai_interpretation` 行之前加）**

定位：
```javascript
              institutional_holdings: "suitePaneHoldings",
              ai_interpretation: "suitePaneAi",
```
改为：
```javascript
              institutional_holdings: "suitePaneHoldings",
              panel: "suitePanePanel",
              ai_interpretation: "suitePaneAi",
```

- [ ] **Step 6: 加占位 `renderSuitePanel`（在 `renderSuiteAi` 函数定义之前，约 L3342 之前插入，Task 9 替换为完整实现）**

```javascript
      function renderSuitePanel(payload) {
        const pane = document.getElementById("suitePanePanel");
        if (!pane) return;
        pane.dataset.rendered = "1";
        const p = (payload && payload.panel) || {};
        if (!payload || payload.success === false || p.data_status === "unavailable") {
          pane.innerHTML = suiteUnavailableBanner(p.reason || payload?.error, false);
          return;
        }
        pane.innerHTML = `<div class="bbp-placeholder">多空评审团（共识 ${html(String(p.consensus?.score ?? "—"))}）渲染占位 — Task 9 填充</div>`;
      }
```

- [ ] **Step 7: 验证 desktop.html 结构无破坏**

Run:
```bash
cd /Users/palmer/IdeaProjects/projectSync/AI/project/kronos_ultra
.venv/bin/python - <<'PY'
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader("webui/templates"))
env.parse(open("webui/templates/desktop.html", encoding="utf-8").read())
print("jinja parse OK")
import webui.robyn_app  # noqa: F401
print("import robyn_app OK")
PY
```
Expected: 打印 `jinja parse OK` 和 `import robyn_app OK`，无异常。

- [ ] **Step 8: 抽取内联 JS 做语法检查**

Run:
```bash
cd /Users/palmer/IdeaProjects/projectSync/AI/project/kronos_ultra
.venv/bin/python - <<'PY'
import re
html = open("webui/templates/desktop.html", encoding="utf-8").read()
blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
open("/tmp/desktop_inline.js", "w", encoding="utf-8").write("\n".join(blocks))
print(f"extracted {len(blocks)} script blocks")
PY
node --check /tmp/desktop_inline.js && echo "node --check OK"
```
Expected: `node --check OK`（若内联 JS 含 Jinja `{{ }}`/`{% %}` 导致误报，记录并改用浏览器手测；本次新增代码不含 Jinja 占位，应通过）

- [ ] **Step 9: 提交**

```bash
git add webui/templates/desktop.html
git commit -m "feat(webui): 多空评审团 Tab #16 骨架——按钮/pane/dispatch 接线（Phase 1 Task 8）"
```

---

### Task 9: 前端 — `renderSuitePanel` 终端风格完整渲染（温度计 + 7 流派折叠懒渲染 + 16 指标栏）

**Files:**
- Modify: `webui/templates/desktop.html`（替换 Task 8 的占位 `renderSuitePanel` + 在 `<style>` 末尾加 CSS）

- [ ] **Step 1: 用完整实现替换 Task 8 的占位 `renderSuitePanel`**

把 Task 8 Step 6 插入的占位函数整体替换为：

```javascript
      // 多空评审团：终端风格。红=多 #d23f3f，绿=空 #2f9e5a，黄=中性 #c9a227。
      const BBP_SCHOOL_ORDER = ["A", "B", "C", "D", "E", "F", "G"];
      function bbpSignalColor(sig) {
        return sig === "bull" || sig === "up" ? "#d23f3f"
             : sig === "bear" || sig === "down" ? "#2f9e5a" : "#c9a227";
      }
      function bbpSignalText(sig) {
        return sig === "bull" ? "多" : sig === "bear" ? "空"
             : sig === "up" ? "↑" : sig === "down" ? "↓" : "—";
      }

      function renderSuitePanel(payload) {
        const pane = document.getElementById("suitePanePanel");
        if (!pane) return;
        pane.dataset.rendered = "1";
        const p = (payload && payload.panel) || {};
        if (!payload || payload.success === false || p.data_status === "unavailable") {
          pane.innerHTML = suiteUnavailableBanner(p.reason || payload?.error, false);
          return;
        }
        const c = p.consensus || { score: 50, label: "—", bull: 0, neutral: 0, bear: 0 };
        const gd = p.great_divide || {};
        const banner = p.data_status === "stale" ? suiteStaleBanner(p.last_updated) : "";
        const sliderPct = Math.max(0, Math.min(100, c.score));

        // 顶部：温度计 + 计数 + 大分歧（常动区）
        const head = `
          <div class="bbp-head">
            <div class="bbp-thermo">
              <div class="bbp-thermo-label"><span>极空</span><span>多空温度计</span><span>极多</span></div>
              <div class="bbp-thermo-track">
                <div class="bbp-thermo-slider" style="left:${sliderPct}%"></div>
              </div>
              <div class="bbp-thermo-score" style="color:${bbpSignalColor(c.score >= 55 ? "bull" : c.score <= 45 ? "bear" : "neutral")}">
                ${html(String(c.score))} · ${html(c.label)}
              </div>
            </div>
            <div class="bbp-counts">
              <span class="bbp-count bull">多 ${c.bull}</span>
              <span class="bbp-count neutral">观望 ${c.neutral}</span>
              <span class="bbp-count bear">空 ${c.bear}</span>
            </div>
          </div>
          <div class="bbp-divide">
            <div class="bbp-divide-side bull">
              <div class="bbp-divide-tag">最强多头</div>
              <div class="bbp-divide-name">${html(gd.bull?.name || "—")} <small>${html(gd.bull?.score != null ? String(gd.bull.score) : "")}</small></div>
            </div>
            <div class="bbp-divide-vs">VS</div>
            <div class="bbp-divide-side bear">
              <div class="bbp-divide-tag">最强空头</div>
              <div class="bbp-divide-name">${html(gd.bear?.name || "—")} <small>${html(gd.bear?.score != null ? String(gd.bear.score) : "")}</small></div>
            </div>
          </div>
          <div class="bbp-punchline">${html(gd.punchline || "")}</div>`;

        // 16 指标栏（4 组）
        const groupTitles = { capital: "资金面", technical: "技术面", chip: "筹码·机构", model: "模型·预测" };
        const inds = p.indicators || [];
        const groupHtml = Object.keys(groupTitles).map((g) => {
          const cells = inds.filter((it) => it.group === g).map((it) => {
            const off = it.data_status === "unavailable";
            const col = off ? "#6b778a" : bbpSignalColor(it.signal);
            const w = Math.round((it.strength || 0) * 100);
            return `<div class="bbp-ind ${off ? "off" : ""}">
              <div class="bbp-ind-top"><span class="bbp-ind-label">${html(it.label)}</span>
                <span class="bbp-ind-sig" style="color:${col}">${bbpSignalText(it.signal)}</span></div>
              <div class="bbp-ind-val">${html(it.value_text)}</div>
              <div class="bbp-ind-bar"><i style="width:${w}%;background:${col}"></i></div>
            </div>`;
          }).join("");
          return `<div class="bbp-ind-group"><h5>${groupTitles[g]}</h5><div class="bbp-ind-grid">${cells}</div></div>`;
        }).join("");

        // 7 流派折叠（懒渲染：展开时才填成员，避免一次渲 51 行）
        const analysts = p.analysts || [];
        const schools = (p.schools || []).slice().sort(
          (a, b) => BBP_SCHOOL_ORDER.indexOf(a.key) - BBP_SCHOOL_ORDER.indexOf(b.key));
        const schoolHtml = schools.map((s) => {
          const lean = s.lean_score >= 55 ? "bull" : s.lean_score <= 45 ? "bear" : "neutral";
          return `<details class="bbp-school" data-school="${html(s.key)}">
            <summary>
              <span class="bbp-school-name">▶ ${html(s.name)}</span>
              <span class="bbp-school-meta">${s.count} 人</span>
              <span class="bbp-minibar"><i style="width:${Math.max(0, Math.min(100, s.lean_score))}%;background:${bbpSignalColor(lean)}"></i></span>
              <span class="bbp-school-lean" style="color:${bbpSignalColor(lean)}">${html(s.lean)} ${s.lean_score}</span>
            </summary>
            <div class="bbp-members" data-rendered="0"></div>
          </details>`;
        }).join("");

        pane.innerHTML = `${banner}
          <div class="bbp-root">
            ${head}
            <div class="bbp-section-title">量化指标（16）</div>
            ${groupHtml}
            <div class="bbp-section-title">投资人评审团（51 · 按流派折叠）</div>
            <div class="bbp-schools">${schoolHtml}</div>
          </div>`;

        // 懒渲染：首次展开某流派时才生成成员行
        pane.querySelectorAll("details.bbp-school").forEach((det) => {
          det.addEventListener("toggle", () => {
            if (!det.open) return;
            const box = det.querySelector(".bbp-members");
            if (box.dataset.rendered === "1") return;
            const key = det.dataset.school;
            const members = analysts.filter((a) => a.school === key)
              .sort((a, b) => b.score - a.score);
            box.innerHTML = members.map((a, i) => `
              <div class="bbp-member" style="animation-delay:${i * 30}ms">
                <span class="bbp-dot" style="background:${bbpSignalColor(a.signal)}"></span>
                <span class="bbp-member-name">${html(a.name)}${a.source === "rule" ? '<em class="bbp-rule-tag">规则推断</em>' : ""}</span>
                <span class="bbp-member-head">${html(a.headline)}</span>
                <span class="bbp-member-score" style="color:${bbpSignalColor(a.signal)}">${a.score}</span>
              </div>`).join("");
            box.dataset.rendered = "1";
          });
        });
      }
```

- [ ] **Step 2: 加 CSS（在 desktop.html 的 `<style>` 块末尾、`</style>` 之前插入）**

```html
    /* ===== 多空评审团（终端风格）===== */
    .bbp-root { font-family: "SF Mono", "JetBrains Mono", Consolas, monospace; color:#172033; }
    .bbp-head { display:flex; align-items:center; gap:24px; padding:14px 16px; background:#0e1726; border-radius:10px; color:#e6edf6; }
    .bbp-thermo { flex:1; }
    .bbp-thermo-label { display:flex; justify-content:space-between; font-size:11px; color:#8b98ac; margin-bottom:6px; }
    .bbp-thermo-track { position:relative; height:8px; border-radius:6px; background:linear-gradient(90deg,#2f9e5a,#c9a227,#d23f3f); }
    .bbp-thermo-slider { position:absolute; top:-4px; width:4px; height:16px; border-radius:2px; background:#fff; box-shadow:0 0 6px #fff; transition:left .6s ease; }
    .bbp-thermo-score { margin-top:8px; font-size:18px; font-weight:700; }
    .bbp-counts { display:flex; flex-direction:column; gap:4px; }
    .bbp-count { font-size:12px; padding:2px 8px; border-radius:4px; }
    .bbp-count.bull { color:#ff6b6b; } .bbp-count.bear { color:#52c98a; } .bbp-count.neutral { color:#c9a227; }
    .bbp-divide { display:flex; align-items:center; gap:16px; margin-top:12px; }
    .bbp-divide-side { flex:1; padding:10px 14px; border-radius:8px; border:1px solid #e1e6ee; }
    .bbp-divide-side.bull { border-left:3px solid #d23f3f; } .bbp-divide-side.bear { border-left:3px solid #2f9e5a; }
    .bbp-divide-tag { font-size:11px; color:#6b778a; } .bbp-divide-name { font-size:16px; font-weight:700; }
    .bbp-divide-vs { font-weight:700; color:#6b778a; }
    .bbp-punchline { margin-top:10px; padding:8px 12px; background:#f4f6fa; border-radius:6px; font-size:13px; }
    .bbp-section-title { margin:18px 0 8px; font-weight:700; font-size:13px; border-left:3px solid #2f6fdd; padding-left:8px; }
    .bbp-ind-group h5 { margin:8px 0 4px; font-size:12px; color:#6b778a; }
    .bbp-ind-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:8px; }
    .bbp-ind { padding:8px 10px; border:1px solid #e1e6ee; border-radius:8px; background:#fff; }
    .bbp-ind.off { opacity:.5; }
    .bbp-ind-top { display:flex; justify-content:space-between; }
    .bbp-ind-label { font-size:12px; } .bbp-ind-sig { font-weight:700; }
    .bbp-ind-val { font-size:11px; color:#6b778a; margin:2px 0 4px; }
    .bbp-ind-bar { height:4px; background:#eef1f6; border-radius:3px; overflow:hidden; }
    .bbp-ind-bar i { display:block; height:100%; transition:width .5s ease; }
    .bbp-schools { display:flex; flex-direction:column; gap:6px; }
    .bbp-school > summary { display:flex; align-items:center; gap:12px; cursor:pointer; padding:8px 12px; background:#f4f6fa; border-radius:8px; list-style:none; }
    .bbp-school > summary::-webkit-details-marker { display:none; }
    .bbp-school[open] > summary .bbp-school-name { color:#2f6fdd; }
    .bbp-school-name { font-weight:700; min-width:96px; } .bbp-school-meta { font-size:12px; color:#6b778a; }
    .bbp-minibar { flex:1; height:6px; background:#e6e9f0; border-radius:4px; overflow:hidden; }
    .bbp-minibar i { display:block; height:100%; }
    .bbp-school-lean { font-size:12px; font-weight:700; min-width:64px; text-align:right; }
    .bbp-members { display:grid; grid-template-columns:repeat(2,1fr); gap:4px; padding:8px 4px; }
    .bbp-member { display:flex; align-items:center; gap:8px; padding:4px 8px; border-radius:6px; }
    .bbp-member:hover { background:#f4f6fa; }
    .bbp-dot { width:8px; height:8px; border-radius:50%; flex:none; }
    .bbp-member-name { font-size:12px; min-width:120px; } .bbp-rule-tag { font-style:normal; font-size:10px; color:#a0a8b5; margin-left:4px; }
    .bbp-member-head { flex:1; font-size:11px; color:#6b778a; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .bbp-member-score { font-weight:700; font-size:12px; }
    /* 动画策略③：成员行进场逐行错峰点亮（仅展开时触发） */
    .bbp-school[open] .bbp-member { animation:bbpFadeIn .35s ease both; }
    @keyframes bbpFadeIn { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:none; } }
    @media (prefers-reduced-motion: reduce) {
      .bbp-thermo-slider, .bbp-ind-bar i { transition:none; }
      .bbp-school[open] .bbp-member { animation:none; }
    }
```

- [ ] **Step 3: 验证 desktop.html 结构 + 内联 JS 语法**

Run:
```bash
cd /Users/palmer/IdeaProjects/projectSync/AI/project/kronos_ultra
.venv/bin/python - <<'PY'
import re
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader("webui/templates"))
env.parse(open("webui/templates/desktop.html", encoding="utf-8").read())
print("jinja parse OK")
html = open("webui/templates/desktop.html", encoding="utf-8").read()
blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
open("/tmp/desktop_inline.js", "w", encoding="utf-8").write("\n".join(blocks))
print(f"extracted {len(blocks)} script blocks")
PY
node --check /tmp/desktop_inline.js && echo "node --check OK"
```
Expected: `jinja parse OK` + `node --check OK`

- [ ] **Step 4: 浏览器手测（人工确认渲染）— 启动 webui 并截图核对**

Run（后台启动，人工打开浏览器看「多空评审团」Tab）：
```bash
cd /Users/palmer/IdeaProjects/projectSync/AI/project/kronos_ultra
.venv/bin/python webui/run.py
```
人工核对清单：① 温度计滑块位置与共识分一致；② 多/观望/空 计数和=51；③ 16 指标格红/绿/黄 + 动条；④ 点开某流派才出成员（懒渲染）；⑤ stub 成员显示「规则推断」。确认后 Ctrl-C 停服。

- [ ] **Step 5: 提交**

```bash
git add webui/templates/desktop.html
git commit -m "feat(webui): renderSuitePanel 终端风格——温度计/大分歧/16 指标/7 流派懒渲染（Phase 1 Task 9）"
```

---

### Task 10: webui 表面测试 + 全量回归 + 终检

**Files:**
- Modify: `tests/test_webui_core_surface.py`（追加 panel Tab 存在性断言）

- [ ] **Step 1: 写失败测试（追加到 `tests/test_webui_core_surface.py`）**

```python
def test_desktop_html_has_panel_tab():
    """多空评审团 Tab 的按钮 / pane / 渲染函数都已接线。"""
    from pathlib import Path
    html = Path("webui/templates/desktop.html").read_text(encoding="utf-8")
    assert 'data-suite-tab="panel"' in html
    assert 'data-suite-pane="panel"' in html
    assert 'id="suitePanePanel"' in html
    assert "function renderSuitePanel" in html
    # 接入两处 dispatch + paneIdMap
    assert html.count('renderSuitePanel(payload)') >= 2
    assert 'panel: "suitePanePanel"' in html
```

> 若该测试文件的既有用例用别的方式读取 html（如 fixture），沿用其既有范式；上面是自包含写法。

- [ ] **Step 2: 运行该测试，确认通过（Task 8/9 已实现，应直接绿）**

Run: `.venv/bin/python -m pytest tests/test_webui_core_surface.py::test_desktop_html_has_panel_tab -q`
Expected: PASS

- [ ] **Step 3: 全量回归（确认无任何既有用例破坏）**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -40`
Expected: 全绿（新增 `test_panel_*` + 既有用例全部 PASS，无 fail/error）

- [ ] **Step 4: 验收对照 spec §11 Phase 1（人工核对）**

确认以下 spec §11 Phase 1 验收点全部满足：
- [ ] Tab #16「多空评审团」渲染 51 人，分 7 流派折叠
- [ ] 16 指标有真实数据（★ 两项显式标注 Phase 2/3 接入，非静默缺失）
- [ ] 共识温度计 + 大分歧正常显示
- [ ] `test_panel_*` 全绿

- [ ] **Step 5: 最终提交**

```bash
git add tests/test_webui_core_surface.py
git commit -m "test(webui): 多空评审团 Tab 表面存在性断言 + Phase 1 全量回归（Phase 1 Task 10）"
```

---

## 自检（writing-plans skill 要求，作者自查）

**1. Spec 覆盖：**
- §1 `analysis/panel/`（persona/规则/style/共识/大分歧）→ Task 1/3/4/5 ✓
- §1 payload 顶层 `panel` + `data_status`/`last_updated` → Task 7 ✓
- §1 16 指标复用既有数据，不引新数据源 → Task 6（全部派生自 features，无新 provider）✓
- §3 payload 契约（consensus/great_divide/schools/analysts）→ Task 7 build_panel 形状 ✓
- §4 persona 引擎（YAML/12 旗舰/39 stub/features/裁决/style 加权）→ Task 1/2/3/5 ✓
- §5 16 指标 4 组 + ★ 两项 → Task 6（★ 显式降级，已在范围裁定说明）✓
- §6 共识温度计公式 + 大分歧模板 punchline → Task 5 `compute_consensus`/`compute_great_divide` ✓
- §9 前端终端风格 + 7 流派折叠懒渲染 + 动画③ + prefers-reduced-motion + 红多绿空 → Task 8/9 ✓
- §11 Phase 1 验收 → Task 10 ✓
- §12 测试策略（panel 引擎/指标归类/suite 兼容）→ Task 1-7、10 测试 ✓（`test_analysis_overlay`/`test_report_quality` 属 Phase 2，本计划不含，正确）
- **超范围未做（正确）：** LLM 覆盖层（P0-A）、质量门（P0-B）、回测校准（F4）= Phase 2/3。

**2. 占位符扫描：** 无 TBD/TODO/"add error handling"/"similar to Task N"。所有代码步骤含完整代码；所有引用的函数（`build_panel`/`extract_features`/`resolve_rule`/`score_to_signal`/`load_personas`/`compute_*`/`build_indicators`/`renderSuitePanel`/`bbpSignalColor`）均在某任务中定义。

**3. 类型一致性核对：**
- `RULES`/`SCHOOL_DEFAULTS`/`resolve_rule`：Task 3 定义，Task 5 `evaluate_all` 使用 ✓
- `score_to_signal`：Task 3 定义，Task 5/测试使用 ✓
- 特征 key（`main_net_inflow`/`pe_industry_rank`/`model_bull_ratio`/`ma_alignment`/`holder_number_trend` 等）：Task 2 产出，Task 3 规则 + Task 6 指标消费，键名一致 ✓
- `build_panel(inputs, sections)` 签名：Task 7 `__init__.py` 定义，suite `_collect_panel` 调用一致 ✓
- panel dict key（`consensus`/`great_divide`/`schools`/`analysts`/`indicators`/`data_status`/`last_updated`）：Task 7 产出，Task 9 `renderSuitePanel` 消费一致 ✓
- 指标 dict key（`group`/`key`/`label`/`value_text`/`signal`/`strength`/`data_status`）：Task 6 产出，Task 9 渲染消费一致 ✓
- 前端 tab key `"panel"` + pane id `"suitePanePanel"` + 函数 `renderSuitePanel`：Task 8/9/10 三处一致 ✓
