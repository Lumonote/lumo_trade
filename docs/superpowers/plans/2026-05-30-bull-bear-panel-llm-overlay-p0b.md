# 多空评审团 — LLM 覆盖层机械质量门 (P0-B) 实现计划（Phase 2 下半）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 AI 覆盖层产出前强制跑机械质量门，🔴 critical 命中则拦截（`reviewed=False` + 前端红条 + 回退规则文案），🟡 warning 命中则软旗标。

**Architecture:** 新增纯函数模块 `analysis/report_quality.py`（`evaluate_overlay` 只读 overlay/panel/payload，不调 LLM、不落库）。在唯一收口点 `analysis/analysis_overlay/engine.py::build_overlay` 的 schema 合法分支挂 `quality` 字段并按 critical 降级 `reviewed`。前端 `renderPanelOverlay` 改三分支（AI 卡 +黄旗 / 红条 / 升档按钮）。生成与重生成路径共用同一收口，行为一致。

**Tech Stack:** Python 3.13（纯标准库 `re`）、pytest（`.venv/bin/python -m pytest`）、原生 JS/CSS（desktop.html + kronos_desktop.css，无新依赖）。

**范围裁定（spec §8.1，无静默截断）：** v1 做 4 条确定性 🔴（无占位符 / punchline 非空 / deep 逐人覆盖 / deep buy_zones 内容）+ 2 条 🟡（风险≥3 / 轻量 FACTCHECK）。**行业映射 sanity + 编造产业链红旗本期不做**（需 sector 交叉校验、启发式模糊，v1 后另议）。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `analysis/report_quality.py` | 质量门纯函数 `evaluate_overlay` + 私有 helper（占位符 / 覆盖 / FACTCHECK） | Create |
| `tests/test_report_quality.py` | 每条 🔴/🟡 一个单测（red→green） | Create |
| `analysis/analysis_overlay/engine.py` | `build_overlay` 收口：挂 `quality` + critical 降级 `reviewed` | Modify（L65-112 `build_overlay`） |
| `tests/test_analysis_overlay.py` | build_overlay 命中 critical → `reviewed=False`+`quality`；clean → 挂 `quality` | Modify（追加） |
| `webui/templates/desktop.html` | `renderPanelOverlay` 三分支 + `triggerPanelOverlay` 拦截分支 | Modify（L3471-3529） |
| `webui/static/kronos_desktop.css` | `.bbp-overlay-redbar` / `.bbp-overlay-flag` 样式 | Modify（L2183 后） |
| `tests/test_webui_core_surface.py` | 红条 / 黄旗接线表面断言 | Modify（追加） |

**关键约束：** 不 `import analysis.sector_api`（其 import 触发 Tushare 行业缓存加载，重副作用）。占位符标记集合在 `report_quality.py` 本地定义（`sector_api._is_placeholder_text` 只判空/横杠/N-A 哨兵，不判模板残留，不适用）。

---

## Task 1: `report_quality.py` 骨架 + 占位符 🔴 + punchline 🔴

**Files:**
- Create: `analysis/report_quality.py`
- Test: `tests/test_report_quality.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_quality.py
from analysis.report_quality import evaluate_overlay


def _medium_overlay(**over):
    base = {
        "reviewed": True, "tier": "medium",
        "great_divide_override": {"punchline": "放量突破压制估值担忧"},
        "risks": ["估值透支", "题材退潮", "解禁压力"],
        "panel_insights": {}, "buy_zones": None, "narrative_override": None,
    }
    base.update(over)
    return base


def test_passes_clean_minimal_overlay():
    rep = evaluate_overlay(_medium_overlay(), {}, {}, "medium")
    assert rep["passed"] is True
    assert rep["criticals"] == []


def test_blocks_on_placeholder_in_punchline():
    ov = _medium_overlay(great_divide_override={"punchline": "TODO 待补充金句"})
    rep = evaluate_overlay(ov, {}, {}, "medium")
    assert rep["passed"] is False
    assert any("占位符" in c for c in rep["criticals"])


def test_blocks_on_placeholder_in_risk():
    ov = _medium_overlay(risks=["估值透支", "[脚本占位]", "解禁压力"])
    rep = evaluate_overlay(ov, {}, {}, "medium")
    assert rep["passed"] is False
    assert any("占位符" in c for c in rep["criticals"])


def test_blocks_on_empty_punchline():
    ov = _medium_overlay(great_divide_override={"punchline": "   "})
    rep = evaluate_overlay(ov, {}, {}, "medium")
    assert rep["passed"] is False
    assert any("punchline" in c for c in rep["criticals"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_report_quality.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'analysis.report_quality'`

- [ ] **Step 3: 写最小实现**

```python
# analysis/report_quality.py
"""多空评审团 LLM 覆盖层机械质量门（P0-B，spec §8 / §8.1）。

纯函数,无 I/O,不调 LLM、不落库。出 AI 点评前强制跑:
- 🔴 critical 命中 → passed=False（调用方降级 reviewed + 红条 + 回退规则文案）
- 🟡 warning 命中 → 软旗标,不影响 passed

不 import analysis.sector_api（其 import 触发 Tushare 行业缓存加载,重副作用）。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

# 占位符标记（高精度集合,避免误拦合法中文点评）。
_PLACEHOLDER_MARKERS = (
    "[脚本占位]", "占位符", "占位", "todo", "tbd", "待补充", "待填写", "{{", "}}",
)


def evaluate_overlay(
    overlay: Optional[Dict[str, Any]],
    panel: Optional[Dict[str, Any]],
    payload: Optional[Dict[str, Any]],
    tier: str,
) -> Dict[str, Any]:
    """返回 {"passed": bool, "criticals": [str], "warnings": [str]}。

    passed=False 当且仅当任一 🔴 命中。仅应在结构合法（reviewed 将为 True）的
    overlay 上调用；lite/未配置/非法 JSON 的 overlay 走既有「未生成」路径,不在此判定。
    """
    overlay = overlay or {}
    panel = panel or {}
    criticals: List[str] = []
    warnings: List[str] = []

    texts = list(_iter_overlay_texts(overlay))

    # 🔴 无占位符残留
    flagged = next((t for t in texts if _has_placeholder(t)), None)
    if flagged is not None:
        criticals.append(f"检测到占位符残留：{flagged.strip()[:30]}")

    # 🔴 punchline 非空（medium 及以上）
    punchline = ((overlay.get("great_divide_override") or {}).get("punchline") or "").strip()
    if not punchline:
        criticals.append("great_divide_override.punchline 为空")

    return {"passed": not criticals, "criticals": criticals, "warnings": warnings}


def _iter_overlay_texts(overlay: Dict[str, Any]) -> Iterable[str]:
    """遍历 overlay 里所有自由文本（占位符检测 + FACTCHECK 共用）。"""
    gd = overlay.get("great_divide_override") or {}
    if isinstance(gd.get("punchline"), str):
        yield gd["punchline"]
    for r in overlay.get("risks") or []:
        if isinstance(r, str):
            yield r
    for v in (overlay.get("panel_insights") or {}).values():
        if isinstance(v, str):
            yield v
    if isinstance(overlay.get("narrative_override"), str):
        yield overlay["narrative_override"]
    bz = overlay.get("buy_zones") or {}
    if isinstance(bz, dict):
        for items in bz.values():
            for it in items or []:
                if isinstance(it, str):
                    yield it


def _has_placeholder(text: str) -> bool:
    low = (text or "").lower()
    return any(marker.lower() in low for marker in _PLACEHOLDER_MARKERS)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_report_quality.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add analysis/report_quality.py tests/test_report_quality.py
git commit -m "feat(quality): report_quality 骨架 + 占位符/punchline 🔴 critical（P0-B Task 1）"
```

---

## Task 2: deep 档覆盖 🔴 —— 逐人覆盖 + buy_zones 内容

**Files:**
- Modify: `analysis/report_quality.py`（`evaluate_overlay` 加 deep 分支 + 2 个 helper）
- Test: `tests/test_report_quality.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_quality.py —— 追加在文件末尾

def _deep_overlay(**over):
    base = {
        "reviewed": True, "tier": "deep",
        "great_divide_override": {"punchline": "放量突破压制估值担忧"},
        "risks": ["估值透支", "题材退潮", "解禁压力"],
        "panel_insights": {"zhao": "量化席位进场", "graham": "估值偏贵需谨慎"},
        "buy_zones": {"value": ["回调分批"], "growth": [], "technical": [], "youzi": []},
        "narrative_override": None,
    }
    base.update(over)
    return base


_DEEP_PANEL = {
    "great_divide": {
        "bull": {"id": "zhao", "name": "赵老哥"},
        "bear": {"id": "graham", "name": "格雷厄姆"},
    }
}


def test_deep_blocks_when_headline_insight_missing():
    ov = _deep_overlay(panel_insights={"zhao": "量化席位进场"})  # 缺 graham(bear 头牌)
    rep = evaluate_overlay(ov, _DEEP_PANEL, {}, "deep")
    assert rep["passed"] is False
    assert any("头牌" in c for c in rep["criticals"])


def test_deep_blocks_when_all_buy_zones_empty():
    ov = _deep_overlay(buy_zones={"value": [], "growth": [], "technical": [], "youzi": []})
    rep = evaluate_overlay(ov, _DEEP_PANEL, {}, "deep")
    assert rep["passed"] is False
    assert any("buy_zones" in c for c in rep["criticals"])


def test_deep_passes_with_both_insights_and_one_zone():
    rep = evaluate_overlay(_deep_overlay(), _DEEP_PANEL, {}, "deep")
    assert rep["passed"] is True
    assert rep["criticals"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_report_quality.py -q`
Expected: FAIL — `test_deep_blocks_when_headline_insight_missing` / `test_deep_blocks_when_all_buy_zones_empty` 失败（deep 分支未实现，criticals 为空）

- [ ] **Step 3: 写实现** —— 在 `evaluate_overlay` 的 `return` 行之前插入 deep 分支；并在 `_has_placeholder` 后追加两个 helper

把 `evaluate_overlay` 里这段：

```python
    if not punchline:
        criticals.append("great_divide_override.punchline 为空")

    return {"passed": not criticals, "criticals": criticals, "warnings": warnings}
```

替换为：

```python
    if not punchline:
        criticals.append("great_divide_override.punchline 为空")

    if tier == "deep":
        # 🔴 逐人覆盖：两位头牌（bull/bear）必须有非空 insight
        criticals.extend(_missing_headline_insights(overlay, panel))
        # 🔴 buy_zones ≥1 档非空（至少一个可操作区间）
        if not _has_actionable_zone(overlay.get("buy_zones")):
            criticals.append("buy_zones 四档均为空（无可操作区间）")

    return {"passed": not criticals, "criticals": criticals, "warnings": warnings}
```

并在 `_has_placeholder` 函数之后追加：

```python
def _missing_headline_insights(overlay: Dict[str, Any], panel: Dict[str, Any]) -> List[str]:
    """deep 档：great_divide 的 bull/bear 头牌必须在 panel_insights 里有非空点评。"""
    gd = (panel or {}).get("great_divide") or {}
    insights = overlay.get("panel_insights") or {}
    out: List[str] = []
    for role in ("bull", "bear"):
        person = gd.get(role) or {}
        pid = person.get("id")
        if not pid:
            continue
        val = insights.get(pid)
        if not (isinstance(val, str) and val.strip()):
            out.append(f"逐人点评缺失头牌：{person.get('name') or pid}（{role}）")
    return out


def _has_actionable_zone(buy_zones: Any) -> bool:
    if not isinstance(buy_zones, dict):
        return False
    return any(isinstance(v, list) and len(v) > 0 for v in buy_zones.values())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_report_quality.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add analysis/report_quality.py tests/test_report_quality.py
git commit -m "feat(quality): deep 逐人覆盖 + buy_zones 内容 🔴 critical（P0-B Task 2）"
```

---

## Task 3: 🟡 warning —— 风险≥3 + 轻量 FACTCHECK

**Files:**
- Modify: `analysis/report_quality.py`（`evaluate_overlay` 加 warning 段 + FACTCHECK helper）
- Test: `tests/test_report_quality.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_quality.py —— 追加在文件末尾

def test_warns_when_fewer_than_three_risks():
    ov = _deep_overlay(risks=["仅一条风险"])
    rep = evaluate_overlay(ov, _DEEP_PANEL, {}, "deep")
    assert rep["passed"] is True                       # 🟡 不拦截
    assert any("风险" in w for w in rep["warnings"])


def test_factcheck_flags_unverifiable_number():
    # 金句引用 888.88，payload/panel 里没有这个数 → 黄旗
    ov = _deep_overlay(great_divide_override={"punchline": "目标价直指 888.88 元"})
    rep = evaluate_overlay(ov, _DEEP_PANEL, {"overview": {"price": 12.40}}, "deep")
    assert rep["passed"] is True
    assert any("888.88" in w for w in rep["warnings"])


def test_factcheck_passes_number_present_in_payload():
    ov = _deep_overlay(great_divide_override={"punchline": "控盘度高达 72"})
    payload = {"chip_control": {"control_degree": 72}}
    rep = evaluate_overlay(ov, _DEEP_PANEL, payload, "deep")
    assert not any("72" in w for w in rep["warnings"])  # 能在 payload 找到出处


def test_small_numbers_exempt_from_factcheck():
    ov = _deep_overlay(great_divide_override={"punchline": "未来 3 个月看多 2 成仓位"})
    rep = evaluate_overlay(ov, _DEEP_PANEL, {}, "deep")
    assert not any(w.startswith("以下数字") for w in rep["warnings"])  # <10 豁免
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_report_quality.py -q`
Expected: FAIL — `test_warns_when_fewer_than_three_risks` / `test_factcheck_flags_unverifiable_number` 失败（warnings 为空）

- [ ] **Step 3: 写实现** —— `evaluate_overlay` 加 warning 段；补常量、`import re`、4 个 FACTCHECK helper

把模块顶部：

```python
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

# 占位符标记（高精度集合,避免误拦合法中文点评）。
_PLACEHOLDER_MARKERS = (
    "[脚本占位]", "占位符", "占位", "todo", "tbd", "待补充", "待填写", "{{", "}}",
)
```

替换为：

```python
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

# 占位符标记（高精度集合,避免误拦合法中文点评）。
_PLACEHOLDER_MARKERS = (
    "[脚本占位]", "占位符", "占位", "todo", "tbd", "待补充", "待填写", "{{", "}}",
)

# 抽数字 token（千分位 / 小数 / 负号）。% 与 亿/万 单位后缀由匹配时多尺度容差处理。
_NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")
_FACTCHECK_MIN_ABS = 10.0   # |v|<10 的数（序号/小计数/常识）豁免,避免误报
_FACTCHECK_REL_TOL = 0.02   # 容差 |n-v| <= max(0.5, |v|*2%)
```

把 `evaluate_overlay` 里这段：

```python
        if not _has_actionable_zone(overlay.get("buy_zones")):
            criticals.append("buy_zones 四档均为空（无可操作区间）")

    return {"passed": not criticals, "criticals": criticals, "warnings": warnings}
```

替换为：

```python
        if not _has_actionable_zone(overlay.get("buy_zones")):
            criticals.append("buy_zones 四档均为空（无可操作区间）")

    # 🟡 风险 ≥ 3 条
    if sum(1 for r in (overlay.get("risks") or []) if isinstance(r, str) and r.strip()) < 3:
        warnings.append("风险条目少于 3 条")

    # 🟡 FACTCHECK（轻量）：overlay 引用数字须能在 payload 找到出处
    unverifiable = _factcheck_numbers(texts, panel, payload or {})
    if unverifiable:
        warnings.append("以下数字未能在数据中找到出处：" + "、".join(unverifiable[:5]))

    return {"passed": not criticals, "criticals": criticals, "warnings": warnings}
```

在文件末尾追加 FACTCHECK helper：

```python
def _norm_num(token: str) -> Optional[float]:
    try:
        return float(token.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _payload_number_set(panel: Dict[str, Any], payload: Dict[str, Any]) -> set:
    """递归收集 panel+payload 内所有数值（含字符串里的数字），归一化为浮点。"""
    found: set = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            found.add(round(float(obj), 2))
        elif isinstance(obj, str):
            for tok in _NUM_RE.findall(obj):
                v = _norm_num(tok)
                if v is not None:
                    found.add(round(v, 2))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    walk(panel)
    walk(payload)
    return found


def _close_to_any(v: float, number_set: set) -> bool:
    """v 在 原值/万/亿 三种尺度上任一接近 payload 数值即视作有出处（保守,少误报）。"""
    for scale in (1.0, 1e4, 1e8):
        scaled = v * scale
        tol = max(0.5, abs(scaled) * _FACTCHECK_REL_TOL)
        if any(abs(n - scaled) <= tol for n in number_set):
            return True
    return False


def _factcheck_numbers(texts: List[str], panel: Dict[str, Any], payload: Dict[str, Any]) -> List[str]:
    number_set = _payload_number_set(panel, payload)
    unverifiable: List[str] = []
    seen: set = set()
    for text in texts:
        for tok in _NUM_RE.findall(text):
            if tok in seen:
                continue
            seen.add(tok)
            v = _norm_num(tok)
            if v is None or abs(v) < _FACTCHECK_MIN_ABS:
                continue
            if not _close_to_any(v, number_set):
                unverifiable.append(tok)
    return unverifiable
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_report_quality.py -q`
Expected: PASS（11 passed）

- [ ] **Step 5: 提交**

```bash
git add analysis/report_quality.py tests/test_report_quality.py
git commit -m "feat(quality): 风险≥3 + 轻量 FACTCHECK 🟡 warning（多尺度容差,P0-B Task 3）"
```

---

## Task 4: 收口接入 `build_overlay` + 扩展 overlay 引擎测试

**Files:**
- Modify: `analysis/analysis_overlay/engine.py`（import + `build_overlay` 成功分支）
- Test: `tests/test_analysis_overlay.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_analysis_overlay.py —— 追加在文件末尾（_panel / build_overlay 已在本文件 import）

def _placeholder_deep_json_text():
    import json as _json
    return "```json\n" + _json.dumps({
        "great_divide_override": {"punchline": "TODO 待补充金句"},
        "risks": ["估值透支", "题材退潮", "解禁压力"],
        "panel_insights": {"zhao": "量化席位进场", "graham": "估值偏贵"},
        "buy_zones": {"value": ["12.4 以下"], "growth": [], "technical": [], "youzi": []},
        "narrative_override": "多头占优",
    }, ensure_ascii=False) + "\n```"


def test_build_overlay_blocks_on_quality_critical():
    """schema 合法但含占位符 → 质量门拦截：reviewed 降级 + 挂 quality + reason。"""
    ov = build_overlay(_panel(), {}, "deep",
                       llm_caller=lambda p: (True, _placeholder_deep_json_text()),
                       now_iso=_FIXED_NOW)
    assert ov["reviewed"] is False
    assert ov["quality"]["passed"] is False
    assert any("占位符" in c for c in ov["quality"]["criticals"])
    assert ov["reason"].startswith("质量门拦截")


def test_build_overlay_attaches_quality_on_success():
    """clean 成功 → reviewed 保持 True 且挂 quality.passed=True。"""
    ov = build_overlay(_panel(), {}, "deep",
                       llm_caller=lambda p: (True, _good_deep_json_text()),
                       now_iso=_FIXED_NOW)
    assert ov["reviewed"] is True
    assert ov["quality"]["passed"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_analysis_overlay.py -q`
Expected: FAIL — `KeyError: 'quality'`（build_overlay 尚未挂 quality）

- [ ] **Step 3: 写实现** —— 改 `analysis/analysis_overlay/engine.py`

在 import 区（`from analysis.analysis_overlay.schema import TIERS, validate_overlay` 之后）追加：

```python
from analysis.report_quality import evaluate_overlay
```

把 `build_overlay` 里这段（约 L106-108）：

```python
        errors = validate_overlay(obj, tier)
        if not errors:
            return _success(obj, tier, now_iso)
```

替换为：

```python
        errors = validate_overlay(obj, tier)
        if not errors:
            overlay = _success(obj, tier, now_iso)
            report = evaluate_overlay(overlay, panel, payload, tier)
            overlay["quality"] = report
            if not report["passed"]:
                # 🔴 critical → 降级 reviewed,复用既有回退链；前端按 quality.criticals 显红条
                overlay["reviewed"] = False
                overlay["reason"] = "质量门拦截：" + "；".join(report["criticals"])
            return overlay
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_analysis_overlay.py tests/test_report_quality.py -q`
Expected: PASS（既有 overlay 用例 + 2 新用例全绿；既有 `test_deep_success_first_try` 等不回归——clean 成功仍 reviewed=True）

- [ ] **Step 5: 提交**

```bash
git add analysis/analysis_overlay/engine.py tests/test_analysis_overlay.py
git commit -m "feat(overlay): build_overlay 收口跑质量门——挂 quality + critical 降级 reviewed（P0-B Task 4）"
```

---

## Task 5: 前端 —— `renderPanelOverlay` 三分支 + 拦截一致性 + CSS + 表面测试

**Files:**
- Modify: `webui/templates/desktop.html`（`renderPanelOverlay` L3471-3501、`triggerPanelOverlay` L3512-3522）
- Modify: `webui/static/kronos_desktop.css`（L2183 `.bbp-overlay-zones` 规则后追加）
- Test: `tests/test_webui_core_surface.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_webui_core_surface.py —— 追加在文件末尾

def test_desktop_html_has_quality_gate_wiring():
    """P0-B：质量门红条 + 黄旗渲染分支已接线。"""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    html = (repo_root / "webui" / "templates" / "desktop.html").read_text(encoding="utf-8")
    assert "bbp-overlay-redbar" in html          # 红条
    assert "ov.quality" in html                  # 读 quality 字段
    assert "未通过质量门" in html                  # 红条文案
    assert "bbp-overlay-flag" in html            # 黄旗
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_webui_core_surface.py::test_desktop_html_has_quality_gate_wiring -q`
Expected: FAIL — `assert 'bbp-overlay-redbar' in html`（尚未实现）

- [ ] **Step 3a: 改 `renderPanelOverlay`（desktop.html）** —— 把整个函数（L3471-3501）替换为：

```javascript
      // P0-A/P0-B：reviewed=true 显 AI 点评(+黄旗警告)；质量拦截显红条+回退规则文案；未生成显升档按钮
      function renderPanelOverlay(payload) {
        const ov = (payload && payload.analysis_overlay) || {};
        const stock = (payload && payload.stock) || {};
        const q = ov.quality || {};
        const criticals = q.criticals || [];
        if (!ov.reviewed) {
          if (criticals.length) {
            // P0-B：AI 已生成但被机械质量门拦截 —— 红条 + 重新生成；下方仍渲染规则版 panel
            return `
              <div class="bbp-overlay-redbar">
                <span class="bbp-overlay-redbar-title">⚠ AI 点评未通过质量门</span>
                <span class="bbp-overlay-redbar-reason">${html(criticals.join("；"))}</span>
                <button class="bbp-overlay-btn" type="button"
                  onclick="triggerPanelOverlay('${html(stock.code || "")}')">重新生成</button>
              </div>`;
          }
          const reason = ov.reason ? `<span class="bbp-overlay-reason">${html(ov.reason)}</span>` : "";
          return `
            <div class="bbp-overlay-empty">
              <button class="bbp-overlay-btn" type="button"
                onclick="triggerPanelOverlay('${html(stock.code || "")}')">AI 深度点评</button>
              ${reason}
            </div>`;
        }
        const risks = (ov.risks || []).map((r) => `<li>${html(r)}</li>`).join("");
        const zones = ov.buy_zones || {};
        const zoneRow = (k, label) => {
          const items = (zones[k] || []).map((z) => `<span class="bbp-zone-pill">${html(z)}</span>`).join("");
          return items ? `<div class="bbp-zone"><span class="bbp-zone-label">${label}</span>${items}</div>` : "";
        };
        const nar = ov.narrative_override ? `<div class="bbp-overlay-nar">${html(ov.narrative_override)}</div>` : "";
        const warnings = (q.warnings || []).map((w) => `<div class="bbp-overlay-flag">⚠ ${html(w)}</div>`).join("");
        const flags = warnings ? `<div class="bbp-overlay-flags">${warnings}</div>` : "";
        return `
          <div class="bbp-overlay-card" data-status="${html(ov.data_status || "")}">
            <div class="bbp-overlay-tag">AI 点评 · ${html(ov.tier || "")}${ov.data_status === "stale" ? " · 历史" : ""}</div>
            ${nar}
            ${risks ? `<div class="bbp-overlay-risks"><b>风险</b><ul>${risks}</ul></div>` : ""}
            <div class="bbp-overlay-zones">
              ${zoneRow("value", "价值")}${zoneRow("growth", "成长")}
              ${zoneRow("technical", "技术")}${zoneRow("youzi", "游资")}
            </div>
            ${flags}
          </div>`;
      }
```

- [ ] **Step 3b: 改 `triggerPanelOverlay` 拦截一致性（desktop.html）** —— 把这段（L3513-3522）：

```javascript
          if (data.success && state.currentSuitePayload) {
            state.currentSuitePayload.analysis_overlay = data.overlay;
            if (data.merged_panel) state.currentSuitePayload.panel = data.merged_panel;
            renderSuitePanel(state.currentSuitePayload);   // 整面重渲（含覆盖后的金句/逐人 insight）
          } else if (box) {
            box.innerHTML = `<div class="bbp-overlay-empty">
              <span class="bbp-overlay-reason">生成失败：${html((data.overlay && data.overlay.reason) || data.error || "未知错误")}</span>
              <button class="bbp-overlay-btn" type="button" onclick="triggerPanelOverlay('${html(code)}')">重试</button>
            </div>`;
          }
```

替换为：

```javascript
          const blocked = data.overlay && (data.overlay.quality || {}).criticals
            && data.overlay.quality.criticals.length;
          if (data.success && state.currentSuitePayload) {
            state.currentSuitePayload.analysis_overlay = data.overlay;
            if (data.merged_panel) state.currentSuitePayload.panel = data.merged_panel;
            renderSuitePanel(state.currentSuitePayload);   // 整面重渲（含覆盖后的金句/逐人 insight）
          } else if (blocked && state.currentSuitePayload) {
            // P0-B：被质量门拦截 —— 落 state 整面重渲（红条 + 规则版 panel），与重载表现一致
            state.currentSuitePayload.analysis_overlay = data.overlay;
            if (data.merged_panel) state.currentSuitePayload.panel = data.merged_panel;
            renderSuitePanel(state.currentSuitePayload);
          } else if (box) {
            box.innerHTML = `<div class="bbp-overlay-empty">
              <span class="bbp-overlay-reason">生成失败：${html((data.overlay && data.overlay.reason) || data.error || "未知错误")}</span>
              <button class="bbp-overlay-btn" type="button" onclick="triggerPanelOverlay('${html(code)}')">重试</button>
            </div>`;
          }
```

- [ ] **Step 3c: 加 CSS（kronos_desktop.css）** —— 在 `.bbp-overlay-zones { ... }`（L2183）规则之后追加：

```css
.bbp-overlay-redbar { border: 1px solid #fecaca; border-left: 3px solid #dc2626;
  background: #fef2f2; border-radius: 8px; padding: 8px 12px; margin: 10px 0;
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.bbp-overlay-redbar-title { font-size: 12px; font-weight: 700; color: #b91c1c; }
.bbp-overlay-redbar-reason { font-size: 12px; color: #991b1b; flex: 1 1 auto; }
.bbp-overlay-flags { margin-top: 8px; display: flex; flex-direction: column; gap: 3px; }
.bbp-overlay-flag { font-size: 11px; color: #92400e; background: #fffbeb;
  border: 1px solid #fde68a; border-radius: 6px; padding: 2px 8px; }
```

- [ ] **Step 4: 验证（模板解析 + 表面测试）**

Run（按 [[webui-desktop-verification-recipe]]）：
```bash
.venv/bin/python -c "import jinja2, pathlib; jinja2.Environment().parse(pathlib.Path('webui/templates/desktop.html').read_text(encoding='utf-8')); print('jinja OK')"
.venv/bin/python -m pytest tests/test_webui_core_surface.py -q
```
Expected: `jinja OK`；表面测试全绿（含新 `test_desktop_html_has_quality_gate_wiring`）

- [ ] **Step 5: 提交**

```bash
git add webui/templates/desktop.html webui/static/kronos_desktop.css tests/test_webui_core_surface.py
git commit -m "feat(webui): 质量门红条 + 黄旗渲染三分支 + 拦截重渲一致性（P0-B Task 5）"
```

---

## Task 6: 全量回归终检 + spec §11 Phase 2 验收对照

**Files:**
- Modify: `docs/superpowers/specs/2026-05-30-bull-bear-investor-panel-tab-design.md`（§11 Phase 2 行标注 P0-B 完成）

- [ ] **Step 1: 全量回归**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS（P0-A 基线 248 + P0-B 新增 ≈ 11(report_quality) + 2(overlay) + 1(surface) = 262 上下；**0 fail / 0 skip**）。若有 fail 先修，不得标完成。

- [ ] **Step 2: spec §11 Phase 2 验收对照（人工核对）**

确认 spec §8 / §8.1 验收点满足：
- [ ] 🔴 占位符 / punchline / deep 逐人覆盖 / deep buy_zones → critical 命中即 `reviewed=False` + 红条 + 回退规则文案。
- [ ] 🟡 风险<3 / FACTCHECK 未中 → 黄旗但 `passed=True`，不拦截。
- [ ] 行业 sanity 显式未做（§8.1 已记录,非静默缺失）。
- [ ] 向后兼容：P0-A 旧持久化 overlay（无 `quality`）前端按「无警告/无 critical」降级。

- [ ] **Step 3: 标注 spec 并提交**

在 spec §11 表格 Phase 2 行末追加 `（P0-A 覆盖层 ✅；P0-B 质量门 ✅ 完成于 2026-05-30）`。

```bash
git add docs/superpowers/specs/2026-05-30-bull-bear-investor-panel-tab-design.md
git commit -m "docs(spec): §11 Phase 2 标注 P0-B 质量门完成（P0-B Task 6）"
```

---

## 自检（writing-plans skill 要求，作者自查）

**1. Spec 覆盖（spec §8 / §8.1）：**
- §8 🔴 覆盖度(关键维度非空) → Task 1（punchline）+ Task 2（deep 逐人/ buy_zones）✓
- §8 🔴 无占位符串 → Task 1 ✓
- §8 🔴 `reviewed == true` → Task 4（仅在结构合法 overlay 上跑门；critical 命中降级 reviewed，等价「只有过门才 reviewed」）✓
- §8 🔴 buy_zones 四档齐全 → Task 2（四档键由 schema 保证 + 门要求 ≥1 非空）✓
- §8 🟡 风险≥3 + FACTCHECK → Task 3 ✓
- §8 🟡 行业 sanity → §8.1 显式本期不做（Task 6 Step 2 核对记录）✓ 非静默截断
- §8 「critical 不过→回退规则文案+红条」 → Task 4（reviewed 降级触发既有回退）+ Task 5（红条）✓
- §8.1 前端三分支 / 持久化含拦截 overlay / 向后兼容 → Task 5 + Task 4（落 kv 由既有 `trigger_panel_overlay` 透传，含 quality）✓
- §12 `tests/test_report_quality.py` 每条 critical→block → Task 1-3 ✓

**2. 占位符扫描：** 计划内无 TBD/TODO/"implement later"（正文出现的 `TODO`/`占位` 均为「被检测的标记字面量」与测试输入，非计划占位）✓

**3. 类型一致性：**
- `evaluate_overlay(overlay, panel, payload, tier) -> {"passed","criticals","warnings"}` —— Task 1 定义，Task 4 调用签名一致 ✓
- helper 名跨任务一致：`_iter_overlay_texts`/`_has_placeholder`(T1)、`_missing_headline_insights`/`_has_actionable_zone`(T2)、`_norm_num`/`_payload_number_set`/`_close_to_any`/`_factcheck_numbers`(T3) ✓
- overlay 新增字段 `quality`（恒存在于成功路径）—— Task 4 写入，Task 5 前端读 `ov.quality`/`q.criticals`/`q.warnings` 一致 ✓
- `trigger_panel_overlay` 返回 `{success, overlay, merged_panel}`（既有），前端 Task 5 读 `data.overlay.quality.criticals` 一致 ✓

**4. 超范围未做（正确）：** 行业映射 sanity / 产业链红旗（spec §8 🟡 第二条）= P0-B v2 或后续；回测校准 = Phase 3。

---

## Execution Handoff

计划已存 `docs/superpowers/plans/2026-05-30-bull-bear-panel-llm-overlay-p0b.md`。
