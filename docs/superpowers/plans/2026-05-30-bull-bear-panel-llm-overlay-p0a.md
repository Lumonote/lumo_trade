# 多空评审团 — LLM 覆盖层 (P0-A) 实现计划（Phase 2 上半）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给「多空评审团」Tab 增加一层**结构化、可校验、可回退、可审计**的 LLM 覆盖层 —— 由规则引擎产出的 panel 骨架分基础上，LLM 只写"覆盖层"（金句 / 逐人点评 / 买点区间 / 风险），返回 JSON 经手写 schema 校验（失败重试 N 次，仍失败回退规则文案），物理隔离存入 `kv_repo` 可 diff/回滚，分 lite/medium/deep 三档控 token。

**Architecture:** 新增纯计算包 `analysis/analysis_overlay/`：`prompt.build_overlay_prompt(panel, payload, tier)` 把 Phase 1 的 `panel` 段 + payload 摘要拼成"只返回 JSON"的提示 → 注入的 `llm_caller`（默认薄封装 `LLMAnalyzer.interpret_stock_markdown`）→ `prompt.extract_overlay_json` 抽 JSON → `schema.validate_overlay(obj, tier)` 手写校验返回错误列表（把错误回喂给 LLM 重试）→ 成功 `reviewed=True`，全失败/未配置 `reviewed=False` 降级。`engine.merge_overlay(panel, overlay)` 把 agent 字段叠加到 panel 副本（punchline 覆盖、逐人 insight）。`StockAnalysisSuite` 增 `_collect_analysis_overlay`（读 `kv_repo`）+ `trigger_panel_overlay`（按需生成并落 kv），payload 增 `analysis_overlay` 顶层 key（默认 lite/未生成 → `reviewed=False`，前端回退 Phase 1 规则文案）。新增端点 `POST /api/stock-analysis-suite/:code/panel-overlay`。前端 `renderSuitePanel` 增"AI 深度点评"升档按钮 + overlay 渲染（覆盖金句 / 逐人点评 / 买点区间 / 风险）。

**Tech Stack:** Python 3.13 / `requests`（既有 LLM provider，不引 openai SDK）/ `data_store.kv_repo`（JSON 持久化）/ pytest（TDD，**LLM 全程 stub**）/ 原生 JS + CSS（前端，无新依赖）/ Robyn webui。

**关键约定（贯穿全部任务）：**
- 运行测试一律用项目 venv：`.venv/bin/python -m pytest`（**不要** Homebrew `python3`）。
- **不引 `jsonschema` 依赖**：手写 `validate_overlay(obj, tier) -> list[str]`，返回人类可读中文错误，便于回喂 LLM 重试。
- **LLM 通过依赖注入**：overlay 引擎收 `llm_caller: Callable[[str], tuple[bool, str]]`，默认薄封装既有 `LLMAnalyzer`。**所有测试注入 stub caller，绝不真连网络**（参考 Phase 1 `AkshareAdapter` 的 `client_factory` 范式）。
- **未配置 / 失败优雅降级**：无 API key 或全部重试失败 → overlay `reviewed=False` + `data_status="unavailable"` + `reason`，**前端回退 Phase 1 规则文案，绝不空白/报错**。
- **payload 向后兼容**：只新增 `analysis_overlay` 顶层 key，不改既有 16 个 key（含 Phase 1 的 `panel`）。
- **物理隔离 + 审计**：overlay 独立存 `kv_repo` 命名空间 `"analysis_overlay"`（key=股票代码），可 diff/回滚；不污染 `panel` 原始规则分。
- A 股配色沿用 Phase 1：红=多 `#d23f3f`，绿=空 `#2f9e5a`，黄=中性 `#c9a227`。
- **范围裁定（无静默截断）：** 本计划只做 spec §7 的 **P0-A 覆盖层**。spec §8 的 **P0-B 机械质量门**（覆盖度/占位符/FACTCHECK/行业 sanity）属**下一个独立计划**；★Kronos 预测格（模型运行时）按用户裁定**本期不纳入**，`kronos_pred` 指标继续 Phase 1 显式降级。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `analysis/analysis_overlay/__init__.py` | 包入口；导出 `build_overlay` / `merge_overlay` / `TIERS` | Create |
| `analysis/analysis_overlay/schema.py` | `validate_overlay(obj, tier) -> list[str]` 手写结构/类型校验 | Create |
| `analysis/analysis_overlay/prompt.py` | `build_overlay_prompt(panel, payload, tier)` + `extract_overlay_json(text)` | Create |
| `analysis/analysis_overlay/engine.py` | `build_overlay(...)`（重试/回退）+ `merge_overlay(...)` + 默认 `llm_caller` | Create |
| `analysis/stock_analysis_suite.py` | `_collect_analysis_overlay` + `trigger_panel_overlay` + payload `analysis_overlay` key | Modify（`_compute_full_payload` 返回 dict ~L237-258；新方法加在 `trigger_ai_interpretation` 附近 ~L202 后） |
| `webui/services/stock_suite_service.py` | `trigger_panel_overlay` 薄封装 | Modify（`trigger_ai_interpretation` ~L118-131 后） |
| `webui/robyn_app.py` | 新端点 `POST /api/stock-analysis-suite/:code/panel-overlay` | Modify（`post_stock_analysis_suite_ai` ~L483-501 后） |
| `webui/templates/desktop.html` | `renderSuitePanel` 增升档按钮 + overlay 渲染 + `triggerPanelOverlay` | Modify（`renderSuitePanel` ~L3358） |
| `webui/static/kronos_desktop.css` | overlay 区样式（`.bbp-overlay-*`） | Modify（文件末尾） |
| `tests/test_analysis_overlay.py` | schema/prompt/engine（含重试/回退/merge/分档）单测 | Create |
| `tests/test_stock_analysis_suite.py` | payload 含 `analysis_overlay` + `trigger_panel_overlay` 集成 + 向后兼容 | Modify（文件末尾追加） |
| `tests/test_robyn_app.py` | 新端点测试 | Modify（文件末尾追加） |
| `tests/test_webui_core_surface.py` | desktop.html overlay 接线表面断言 | Modify（文件末尾追加） |

**数据契约（`analysis_overlay` 顶层 key，落地 spec §3 / §7）：**
```jsonc
"analysis_overlay": {
  "data_status": "fresh",          // fresh(本次生成) / stale(读 kv 历史) / unavailable(未生成/失败/lite)
  "last_updated": "2026-05-30 14:00:00",
  "reviewed": true,                // schema 校验通过；false=回退规则文案
  "tier": "deep",                  // lite / medium / deep
  "panel_insights": { "buffett": "现金牛+护城河，回调即买" },   // deep
  "great_divide_override": { "punchline": "放量突破+量化席位进场，多头压制估值担忧" }, // medium+
  "buy_zones": { "value": ["12.4 以下分批"], "growth": [], "technical": ["站上 20 日线加仓"], "youzi": [] }, // deep
  "risks": ["估值透支三年成长", "..."],
  "narrative_override": "一句话总览…",  // deep，可为 null
  "reason": null                   // unavailable 时给原因（如"lite 档不调用 LLM"/"未配置 API Key"）
}
```

---

## Task 1: overlay schema 手写校验器 `schema.py`

**Files:**
- Create: `analysis/analysis_overlay/__init__.py`
- Create: `analysis/analysis_overlay/schema.py`
- Test: `tests/test_analysis_overlay.py`

`validate_overlay(obj, tier)` 只做**结构/类型**校验（语义质量门是后续 P0-B 计划）。返回中文错误字符串列表，空列表 = 通过。分档要求：`lite` 无要求（不调 LLM）；`medium` 需 `great_divide_override.punchline`（非空 str）+ `risks`（str 数组）；`deep` 在 medium 基础上再需 `panel_insights`（非空 `{str:str}`）+ `buy_zones`（含 value/growth/technical/youzi 四个数组键）。

- [ ] **Step 1: 写失败测试 `tests/test_analysis_overlay.py`（schema 部分）**

```python
"""analysis_overlay：schema 校验 / prompt / 引擎（含重试·回退·merge·分档）。LLM 全程 stub。"""
from __future__ import annotations

from analysis.analysis_overlay.schema import validate_overlay, TIERS


def _deep_ok():
    return {
        "great_divide_override": {"punchline": "放量突破压制估值担忧"},
        "risks": ["估值透支三年成长", "题材退潮", "解禁压力"],
        "panel_insights": {"buffett": "护城河深，回调即买", "zhao": "量化席位进场"},
        "buy_zones": {"value": ["12.4 以下分批"], "growth": [], "technical": ["站上 20 日线"], "youzi": []},
        "narrative_override": "多头占优但需防估值",
    }


def test_tiers_constant():
    assert TIERS == ("lite", "medium", "deep")


def test_lite_has_no_requirements():
    assert validate_overlay({}, "lite") == []


def test_medium_requires_punchline_and_risks():
    errs = validate_overlay({}, "medium")
    assert any("punchline" in e for e in errs)
    assert any("risks" in e for e in errs)
    ok = validate_overlay({"great_divide_override": {"punchline": "多头占优"}, "risks": ["风险一"]}, "medium")
    assert ok == []


def test_medium_punchline_must_be_nonempty_string():
    errs = validate_overlay({"great_divide_override": {"punchline": "   "}, "risks": []}, "medium")
    assert any("punchline" in e for e in errs)


def test_deep_requires_insights_and_buy_zones():
    errs = validate_overlay(
        {"great_divide_override": {"punchline": "多头占优"}, "risks": ["a"]}, "deep")
    assert any("panel_insights" in e for e in errs)
    assert any("buy_zones" in e for e in errs)


def test_deep_buy_zones_needs_four_buckets():
    bad = _deep_ok()
    bad["buy_zones"] = {"value": [], "growth": [], "technical": []}  # 缺 youzi
    errs = validate_overlay(bad, "deep")
    assert any("youzi" in e for e in errs)


def test_deep_valid_passes():
    assert validate_overlay(_deep_ok(), "deep") == []


def test_non_dict_is_error():
    assert validate_overlay(["not", "a", "dict"], "deep") == ["overlay 必须是 JSON 对象"]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_analysis_overlay.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'analysis.analysis_overlay'`）

- [ ] **Step 3: 创建 `analysis/analysis_overlay/__init__.py`（先占位，Task 3 补导出）**

```python
"""多空评审团 LLM 覆盖层（P0-A）：结构化 / 可校验 / 可回退 / 可审计。"""
```

- [ ] **Step 4: 实现 `analysis/analysis_overlay/schema.py`**

```python
"""overlay 结构/类型校验（手写，不引 jsonschema）。

只校验结构与类型；语义质量门（覆盖度/占位符/FACTCHECK/行业 sanity）属后续 P0-B 计划。
返回中文错误列表（空列表 = 通过），错误文案会被回喂给 LLM 触发重试。
"""
from __future__ import annotations

from typing import Any, List

TIERS = ("lite", "medium", "deep")

_BUY_ZONE_BUCKETS = ("value", "growth", "technical", "youzi")


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_overlay(obj: Any, tier: str) -> List[str]:
    """返回错误字符串列表；空列表表示通过。lite 档无结构要求。"""
    if tier == "lite":
        return []
    if not isinstance(obj, dict):
        return ["overlay 必须是 JSON 对象"]

    errors: List[str] = []

    # medium 及以上：金句 + 风险
    gd = obj.get("great_divide_override")
    if not isinstance(gd, dict) or not _nonempty_str(gd.get("punchline")):
        errors.append("缺少 great_divide_override.punchline（非空字符串）")
    risks = obj.get("risks")
    if not isinstance(risks, list) or not all(isinstance(r, str) for r in risks):
        errors.append("risks 必须是字符串数组")

    if tier == "deep":
        insights = obj.get("panel_insights")
        if not isinstance(insights, dict) or len(insights) == 0:
            errors.append("panel_insights 必须是非空对象 {persona_id: 点评}")
        elif not all(isinstance(k, str) and isinstance(v, str) for k, v in insights.items()):
            errors.append("panel_insights 的键与值都必须是字符串")
        buy_zones = obj.get("buy_zones")
        if not isinstance(buy_zones, dict):
            errors.append("缺少 buy_zones 对象（需含 value/growth/technical/youzi）")
        else:
            for bucket in _BUY_ZONE_BUCKETS:
                if not isinstance(buy_zones.get(bucket), list):
                    errors.append(f"buy_zones.{bucket} 必须是数组")
        # narrative_override 可选，但若出现必须是字符串
        nar = obj.get("narrative_override")
        if nar is not None and not isinstance(nar, str):
            errors.append("narrative_override 若提供必须是字符串")

    return errors
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_analysis_overlay.py -q`
Expected: PASS（8 passed）

- [ ] **Step 6: 提交**

```bash
git add analysis/analysis_overlay/__init__.py analysis/analysis_overlay/schema.py tests/test_analysis_overlay.py
git commit -m "feat(overlay): analysis_overlay schema 手写校验器（lite/medium/deep 分档，P0-A Task 1）"
```

> ⚠️ 仓库工作区有大量无关已暂存文件 —— **务必用上面的逐路径 `git add`**，不要 `git add -A`。下同。

---

## Task 2: prompt 构造 + JSON 抽取 `prompt.py`

**Files:**
- Create: `analysis/analysis_overlay/prompt.py`
- Test: `tests/test_analysis_overlay.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 `tests/test_analysis_overlay.py`）**

```python
# --- prompt / JSON 抽取 ---
from analysis.analysis_overlay.prompt import build_overlay_prompt, extract_overlay_json


def _panel():
    return {
        "data_status": "fresh",
        "consensus": {"score": 61, "label": "偏多", "bull": 28, "neutral": 11, "bear": 12},
        "great_divide": {
            "bull": {"id": "zhao", "name": "赵老哥", "school": "F", "score": 92},
            "bear": {"id": "graham", "name": "格雷厄姆", "school": "A", "score": 25},
            "punchline": "赵老哥 看到 量化席位活跃，格雷厄姆 担心 估值超出安全边际",
        },
        "schools": [{"key": "F", "name": "游资派", "count": 7, "lean": "偏多", "lean_score": 64}],
        "analysts": [
            {"id": "zhao", "name": "赵老哥", "school": "F", "signal": "bull", "score": 92,
             "headline": "量化席位活跃", "source": "handwritten", "reasons": ["量化席位 90 日 3 次活跃"]},
            {"id": "graham", "name": "格雷厄姆", "school": "A", "signal": "bear", "score": 25,
             "headline": "估值超出安全边际", "source": "handwritten", "reasons": ["估值超出安全边际，不碰"]},
        ],
        "indicators": [
            {"group": "capital", "key": "main_capital", "label": "主力资金",
             "value_text": "净流入 1.20 亿", "signal": "up", "strength": 0.6, "data_status": "fresh"},
        ],
    }


def test_build_prompt_contains_tier_fields_and_json_directive():
    p = build_overlay_prompt(_panel(), {"stock": {"code": "000001", "name": "平安银行"}}, "deep")
    assert "只返回 JSON" in p or "只输出 JSON" in p
    # deep 档要求的字段名应在提示中出现
    for token in ("panel_insights", "great_divide_override", "buy_zones", "risks"):
        assert token in p
    # panel 摘要信息进了提示
    assert "61" in p and "偏多" in p
    assert "赵老哥" in p and "格雷厄姆" in p


def test_build_prompt_medium_omits_deep_only_fields():
    p = build_overlay_prompt(_panel(), {}, "medium")
    assert "great_divide_override" in p and "risks" in p
    assert "buy_zones" not in p and "panel_insights" not in p


def test_extract_json_from_fenced_block():
    text = '点评如下：\n```json\n{"risks": ["a", "b"]}\n```\n谢谢'
    assert extract_overlay_json(text) == {"risks": ["a", "b"]}


def test_extract_json_from_bare_object():
    text = '{"great_divide_override": {"punchline": "多头占优"}}'
    assert extract_overlay_json(text)["great_divide_override"]["punchline"] == "多头占优"


def test_extract_json_returns_none_on_garbage():
    assert extract_overlay_json("这不是 JSON") is None
    assert extract_overlay_json("") is None
    assert extract_overlay_json("```json\n{坏的 JSON}\n```") is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_analysis_overlay.py -q -k "prompt or extract"`
Expected: FAIL（`ModuleNotFoundError: analysis.analysis_overlay.prompt`）

- [ ] **Step 3: 实现 `analysis/analysis_overlay/prompt.py`**

```python
"""overlay 提示构造 + LLM 返回的 JSON 抽取。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

# 各档要求 LLM 产出的字段说明（提示里展示，也与 schema.validate_overlay 对齐）
_TIER_FIELDS = {
    "medium": (
        '  "great_divide_override": {"punchline": "<一句可传播的多空金句，<=40 字>"},\n'
        '  "risks": ["<风险点1>", "<风险点2>", "<风险点3>"]'
    ),
    "deep": (
        '  "great_divide_override": {"punchline": "<一句可传播的多空金句，<=40 字>"},\n'
        '  "risks": ["<风险点1>", "<风险点2>", "<风险点3>"],\n'
        '  "panel_insights": {"<persona_id>": "<该投资人视角的一句点评>"},\n'
        '  "buy_zones": {"value": ["<价值派买点>"], "growth": [], "technical": [], "youzi": []},\n'
        '  "narrative_override": "<一句话总览，可省略>"'
    ),
}


def _panel_digest(panel: Dict[str, Any]) -> str:
    """把 panel 关键信息压成提示用的紧凑摘要。"""
    c = panel.get("consensus") or {}
    gd = panel.get("great_divide") or {}
    bull = gd.get("bull") or {}
    bear = gd.get("bear") or {}
    lines = [
        f"- 共识温度：{c.get('score', '—')} / 100（{c.get('label', '—')}）；"
        f"多 {c.get('bull', 0)} · 观望 {c.get('neutral', 0)} · 空 {c.get('bear', 0)}",
        f"- 最强多头：{bull.get('name', '—')}（{bull.get('score', '—')}）；"
        f"最强空头：{bear.get('name', '—')}（{bear.get('score', '—')}）",
    ]
    analysts = panel.get("analysts") or []
    top = sorted(analysts, key=lambda a: a.get("score", 0), reverse=True)[:6]
    bot = sorted(analysts, key=lambda a: a.get("score", 0))[:4]
    lines.append("- 旗舰多头观点：" + "；".join(
        f"{a.get('name')}({a.get('id')})：{a.get('headline', '')}" for a in top) or "- 旗舰多头观点：无")
    lines.append("- 旗舰空头/谨慎观点：" + "；".join(
        f"{a.get('name')}({a.get('id')})：{a.get('headline', '')}" for a in bot) or "- 旗舰空头观点：无")
    inds = panel.get("indicators") or []
    fresh = [i for i in inds if i.get("data_status") != "unavailable"]
    if fresh:
        lines.append("- 量化指标：" + "；".join(
            f"{i.get('label')} {i.get('value_text')}({i.get('signal')})" for i in fresh))
    return "\n".join(lines)


def build_overlay_prompt(panel: Dict[str, Any], payload: Dict[str, Any], tier: str) -> str:
    """构造"只返回 JSON"的覆盖层提示。tier ∈ {medium, deep}（lite 不调 LLM，不会进这里）。"""
    stock = (payload or {}).get("stock") or {}
    fields = _TIER_FIELDS.get(tier, _TIER_FIELDS["medium"])
    digest = _panel_digest(panel or {})
    return (
        f"你是一位资深 A 股操盘手。下面是「{stock.get('name', '')}（{stock.get('code', '')}）」"
        "的多空评审团规则引擎结论，请基于这些数据写一层点评覆盖。\n\n"
        f"【规则引擎结论】\n{digest}\n\n"
        "【要求】\n"
        "1. 只能依据上面给出的数据，不得编造未提供的数字或产业链信息。\n"
        "2. punchline 要短、有传播力，体现最强多头与最强空头的核心分歧。\n"
        "3. panel_insights 的键必须用上面出现过的 persona_id（如 zhao / graham / buffett）。\n"
        "4. **只返回 JSON，不要任何额外文字、不要 markdown 说明**。JSON 结构如下：\n"
        "{\n"
        f"{fields}\n"
        "}\n"
    )


def extract_overlay_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 文本抽 JSON：优先 ```json 围栏，其次裸 {…}。失败返回 None。"""
    if not text or not isinstance(text, str):
        return None
    fenced = re.findall(r"```json\s*(.*?)\s*```", text, re.S)
    candidates = fenced if fenced else re.findall(r"(\{[\s\S]*\})", text)
    if not candidates:
        return None
    try:
        result = json.loads(candidates[0])
    except (json.JSONDecodeError, ValueError):
        return None
    return result if isinstance(result, dict) else None
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_analysis_overlay.py -q -k "prompt or extract"`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add analysis/analysis_overlay/prompt.py tests/test_analysis_overlay.py
git commit -m "feat(overlay): build_overlay_prompt（分档字段）+ extract_overlay_json（围栏/裸对象）（P0-A Task 2）"
```

---

## Task 3: overlay 引擎 `engine.py`（重试 / 回退 / merge / 默认 caller）

**Files:**
- Create: `analysis/analysis_overlay/engine.py`
- Modify: `analysis/analysis_overlay/__init__.py`
- Test: `tests/test_analysis_overlay.py`（追加）

`build_overlay(panel, payload, tier, *, llm_caller=None, retries=2, now_iso=None)`：lite 直接回 `unavailable`+`reviewed=False`（不调 LLM）；medium/deep 调 `llm_caller(prompt) -> (ok, text)`，抽 JSON → 校验；通过则 `reviewed=True`；校验失败把错误回喂重试至多 `retries` 次；`ok=False` 且含"未配置"/"API Key"则短路（不浪费重试）；全失败回 `unavailable`+`reviewed=False`+`reason`。`merge_overlay(panel, overlay)` 返回 panel 深拷贝并叠加 agent 字段（punchline 覆盖、逐人 `insight`）。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_analysis_overlay.py`）**

```python
# --- 引擎：build_overlay / merge_overlay ---
from analysis.analysis_overlay.engine import build_overlay, merge_overlay


_FIXED_NOW = "2026-05-30T14:00:00"


def _good_deep_json_text():
    import json as _json
    return "```json\n" + _json.dumps({
        "great_divide_override": {"punchline": "放量突破压制估值担忧"},
        "risks": ["估值透支", "题材退潮", "解禁压力"],
        "panel_insights": {"zhao": "量化席位进场，打板情绪高", "graham": "估值偏贵需谨慎"},
        "buy_zones": {"value": ["12.4 以下分批"], "growth": [], "technical": ["站上 20 日线"], "youzi": []},
        "narrative_override": "多头占优但防估值",
    }, ensure_ascii=False) + "\n```"


def test_lite_does_not_call_llm():
    calls = []
    def caller(prompt):
        calls.append(prompt)
        return True, "{}"
    ov = build_overlay(_panel(), {}, "lite", llm_caller=caller, now_iso=_FIXED_NOW)
    assert calls == []
    assert ov["reviewed"] is False
    assert ov["data_status"] == "unavailable"
    assert ov["tier"] == "lite"
    assert ov["reason"]


def test_deep_success_first_try():
    def caller(prompt):
        return True, _good_deep_json_text()
    ov = build_overlay(_panel(), {}, "deep", llm_caller=caller, now_iso=_FIXED_NOW)
    assert ov["reviewed"] is True
    assert ov["data_status"] == "fresh"
    assert ov["last_updated"] == _FIXED_NOW
    assert ov["great_divide_override"]["punchline"] == "放量突破压制估值担忧"
    assert "zhao" in ov["panel_insights"]
    assert set(ov["buy_zones"].keys()) == {"value", "growth", "technical", "youzi"}


def test_retries_then_succeeds():
    seq = ["这不是 JSON", _good_deep_json_text()]
    attempts = {"n": 0}
    def caller(prompt):
        i = attempts["n"]; attempts["n"] += 1
        return True, seq[i]
    ov = build_overlay(_panel(), {}, "deep", llm_caller=caller, retries=2, now_iso=_FIXED_NOW)
    assert attempts["n"] == 2          # 重试了一次
    assert ov["reviewed"] is True


def test_all_attempts_fail_falls_back():
    def caller(prompt):
        return True, "始终不是 JSON"
    ov = build_overlay(_panel(), {}, "medium", llm_caller=caller, retries=2, now_iso=_FIXED_NOW)
    assert ov["reviewed"] is False
    assert ov["data_status"] == "unavailable"
    assert ov["reason"]


def test_not_configured_short_circuits_without_retry():
    attempts = {"n": 0}
    def caller(prompt):
        attempts["n"] += 1
        return False, "模型 DeepSeek官方/DeepSeek-V4 未配置 API Key"
    ov = build_overlay(_panel(), {}, "deep", llm_caller=caller, retries=3, now_iso=_FIXED_NOW)
    assert attempts["n"] == 1           # 未配置 → 不重试
    assert ov["reviewed"] is False
    assert "API Key" in ov["reason"] or "未配置" in ov["reason"]


def test_merge_overlay_overrides_punchline_and_attaches_insight():
    ov = build_overlay(_panel(), {}, "deep", llm_caller=lambda p: (True, _good_deep_json_text()),
                       now_iso=_FIXED_NOW)
    merged = merge_overlay(_panel(), ov)
    assert merged["great_divide"]["punchline"] == "放量突破压制估值担忧"
    zhao = next(a for a in merged["analysts"] if a["id"] == "zhao")
    assert zhao["insight"] == "量化席位进场，打板情绪高"
    # 原 panel 不被修改（深拷贝）
    assert _panel()["great_divide"]["punchline"] != merged["great_divide"]["punchline"]


def test_merge_overlay_noop_when_not_reviewed():
    ov = build_overlay(_panel(), {}, "lite", llm_caller=lambda p: (True, "{}"), now_iso=_FIXED_NOW)
    merged = merge_overlay(_panel(), ov)
    assert merged["great_divide"]["punchline"] == _panel()["great_divide"]["punchline"]
    assert all("insight" not in a for a in merged["analysts"])
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_analysis_overlay.py -q -k "lite or deep or retries or fail or configured or merge"`
Expected: FAIL（`ModuleNotFoundError: analysis.analysis_overlay.engine`）

- [ ] **Step 3: 实现 `analysis/analysis_overlay/engine.py`**

```python
"""overlay 引擎：调用 LLM（依赖注入）→ 抽 JSON → 校验 → 重试/回退；merge 叠加到 panel。"""
from __future__ import annotations

import copy
import datetime as _dt
from typing import Any, Callable, Dict, List, Optional, Tuple

from analysis.analysis_overlay.prompt import build_overlay_prompt, extract_overlay_json
from analysis.analysis_overlay.schema import TIERS, validate_overlay

LlmCaller = Callable[[str], Tuple[bool, str]]

# overlay 产物里需要透传给前端/合并的字段
_PASS_FIELDS = ("great_divide_override", "risks", "panel_insights", "buy_zones", "narrative_override")


def _default_llm_caller(prompt: str) -> Tuple[bool, str]:
    """默认 caller：薄封装既有 LLMAnalyzer（用 requests 调 DeepSeek）。无 key 时返回 (False, 原因)。"""
    from analysis.llm_service import LLMAnalyzer
    ok, text, _tokens = LLMAnalyzer().interpret_stock_markdown({"prompt": prompt})
    return bool(ok), str(text)


def _now_iso(now_iso: Optional[str]) -> str:
    return now_iso if now_iso else _dt.datetime.now().isoformat(timespec="seconds")


def _unavailable(tier: str, reason: str, now_iso: Optional[str]) -> Dict[str, Any]:
    return {
        "data_status": "unavailable",
        "last_updated": _now_iso(now_iso),
        "reviewed": False,
        "tier": tier,
        "great_divide_override": None,
        "risks": [],
        "panel_insights": {},
        "buy_zones": None,
        "narrative_override": None,
        "reason": reason,
    }


def _looks_unconfigured(text: str) -> bool:
    t = text or ""
    return ("未配置" in t) or ("API Key" in t) or ("api key" in t.lower())


def build_overlay(
    panel: Dict[str, Any],
    payload: Dict[str, Any],
    tier: str,
    *,
    llm_caller: Optional[LlmCaller] = None,
    retries: int = 2,
    now_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """生成 overlay。lite 不调 LLM；medium/deep 调用 + 校验 + 至多 retries 次重试，全失败回退。"""
    if tier not in TIERS:
        tier = "medium"
    if tier == "lite":
        return _unavailable("lite", "lite 档不调用 LLM（默认走规则文案）", now_iso)

    caller = llm_caller or _default_llm_caller
    base_prompt = build_overlay_prompt(panel or {}, payload or {}, tier)
    last_reason = "LLM 覆盖层生成失败"

    for attempt in range(max(1, retries)):
        prompt = base_prompt
        if attempt > 0 and last_errors:
            prompt = base_prompt + "\n【上一次返回的问题，请修正后重新只输出 JSON】\n- " + "\n- ".join(last_errors)
        try:
            ok, text = caller(prompt)
        except Exception as exc:  # noqa: BLE001
            last_reason = f"LLM 调用异常：{exc}"
            last_errors = [last_reason]
            continue
        if not ok:
            last_reason = text or "LLM 调用失败"
            if _looks_unconfigured(text):
                return _unavailable(tier, last_reason, now_iso)  # 未配置 → 不重试
            last_errors = [last_reason]
            continue
        obj = extract_overlay_json(text)
        if obj is None:
            last_errors = ["返回不是合法 JSON，请只输出 JSON 对象"]
            last_reason = last_errors[0]
            continue
        errors = validate_overlay(obj, tier)
        if not errors:
            return _success(obj, tier, now_iso)
        last_errors = errors
        last_reason = "；".join(errors)

    return _unavailable(tier, last_reason, now_iso)


# 在循环外预声明，供 attempt>0 引用（首轮不会用到）
last_errors: List[str] = []


def _success(obj: Dict[str, Any], tier: str, now_iso: Optional[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "data_status": "fresh",
        "last_updated": _now_iso(now_iso),
        "reviewed": True,
        "tier": tier,
        "reason": None,
    }
    for f in _PASS_FIELDS:
        out[f] = obj.get(f)
    if out.get("risks") is None:
        out["risks"] = []
    if out.get("panel_insights") is None:
        out["panel_insights"] = {}
    return out


def merge_overlay(panel: Dict[str, Any], overlay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """返回 panel 深拷贝，叠加已审阅 overlay 的 agent 字段（punchline 覆盖 + 逐人 insight）。"""
    merged = copy.deepcopy(panel or {})
    if not overlay or not overlay.get("reviewed"):
        return merged
    gd_override = overlay.get("great_divide_override") or {}
    punchline = gd_override.get("punchline")
    if punchline and isinstance(merged.get("great_divide"), dict):
        merged["great_divide"]["punchline"] = punchline
    insights = overlay.get("panel_insights") or {}
    for analyst in merged.get("analysts", []) or []:
        if analyst.get("id") in insights:
            analyst["insight"] = insights[analyst["id"]]
    return merged
```

> 注：`last_errors` 在模块级预声明仅为让 `attempt>0` 的引用在静态层面安全；运行期每轮都会被重新赋值。实现者若偏好把 `last_errors` 收进函数局部（首轮初始化 `last_errors: List[str] = []`）亦可，行为等价 —— **请采用函数局部写法**（更干净，避免模块级可变状态），module-level 声明删除。

- [ ] **Step 4: 实现注意（采用函数局部 `last_errors`）**

把 Step 3 中 `build_overlay` 改为在函数体首行初始化 `last_errors: List[str] = []`，并删除模块级 `last_errors` 声明。最终 `build_overlay` 顶部：

```python
    if tier == "lite":
        return _unavailable("lite", "lite 档不调用 LLM（默认走规则文案）", now_iso)

    caller = llm_caller or _default_llm_caller
    base_prompt = build_overlay_prompt(panel or {}, payload or {}, tier)
    last_reason = "LLM 覆盖层生成失败"
    last_errors: List[str] = []
    for attempt in range(max(1, retries)):
        ...
```

- [ ] **Step 5: 更新 `analysis/analysis_overlay/__init__.py` 导出**

```python
"""多空评审团 LLM 覆盖层（P0-A）：结构化 / 可校验 / 可回退 / 可审计。"""
from analysis.analysis_overlay.engine import build_overlay, merge_overlay
from analysis.analysis_overlay.schema import TIERS, validate_overlay

__all__ = ["build_overlay", "merge_overlay", "validate_overlay", "TIERS"]
```

- [ ] **Step 6: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_analysis_overlay.py -q`
Expected: PASS（全部，约 20 passed）

- [ ] **Step 7: 提交**

```bash
git add analysis/analysis_overlay/engine.py analysis/analysis_overlay/__init__.py tests/test_analysis_overlay.py
git commit -m "feat(overlay): build_overlay 重试/回退/未配置短路 + merge_overlay 叠加（P0-A Task 3）"
```

---

## Task 4: suite 接入 —— `_collect_analysis_overlay` + `trigger_panel_overlay` + payload key

**Files:**
- Modify: `analysis/stock_analysis_suite.py`
- Test: `tests/test_stock_analysis_suite.py`（文件末尾追加）

`_collect_analysis_overlay(code)` 从 `kv_repo` 读历史 overlay（有则原样返回、`data_status` 置 `stale`；无则 `unavailable`+`reviewed=False`）；`_compute_full_payload` 增 `analysis_overlay` key。`trigger_panel_overlay(code, tier="deep", *, llm_caller=None, force_refresh=False)` 取 payload→panel→`build_overlay`→落 kv→回 `{success, overlay, merged_panel}`。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_stock_analysis_suite.py` 末尾）**

```python
# --- P0-A: analysis_overlay 集成 ---


def test_payload_includes_analysis_overlay_key_backward_compatible(monkeypatch):
    """payload 必含 analysis_overlay 顶层 key（默认未生成→unavailable/reviewed=False），既有 key 不丢。"""
    from analysis import stock_analysis_suite as mod
    from data_store import kv_repo

    monkeypatch.setattr(kv_repo, "get", lambda ns, key: None)  # kv 空

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]
    payload = suite._compute_full_payload("000001")

    for key in ("overview", "risk_control", "panel", "ai_interpretation"):
        assert key in payload  # 向后兼容
    ov = payload["analysis_overlay"]
    assert ov["data_status"] == "unavailable"
    assert ov["reviewed"] is False


def test_collect_analysis_overlay_reads_persisted_as_stale(monkeypatch):
    from data_store import kv_repo

    stored = {"data_status": "fresh", "reviewed": True, "tier": "deep",
              "great_divide_override": {"punchline": "多头占优"}, "risks": ["x"],
              "panel_insights": {"zhao": "进场"}, "buy_zones": {"value": [], "growth": [],
              "technical": [], "youzi": []}, "narrative_override": None,
              "last_updated": "2026-05-29T10:00:00", "reason": None}
    monkeypatch.setattr(kv_repo, "get", lambda ns, key: (stored, 0.0))

    suite = StockAnalysisSuite()
    ov = suite._collect_analysis_overlay("000001")
    assert ov["reviewed"] is True
    assert ov["data_status"] == "stale"          # 读历史 → stale
    assert ov["great_divide_override"]["punchline"] == "多头占优"


def test_trigger_panel_overlay_generates_and_persists(monkeypatch):
    from analysis import stock_analysis_suite as mod
    from data_store import kv_repo

    saved = {}
    monkeypatch.setattr(kv_repo, "set_", lambda ns, key, payload, ttl_seconds=0: saved.update({(ns, key): payload}))
    monkeypatch.setattr(kv_repo, "get", lambda ns, key: None)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]

    import json as _json
    good = "```json\n" + _json.dumps({
        "great_divide_override": {"punchline": "放量突破压制估值"},
        "risks": ["估值", "解禁", "题材退潮"],
        "panel_insights": {"buffett": "回调即买"},
        "buy_zones": {"value": ["12 以下"], "growth": [], "technical": [], "youzi": []},
    }, ensure_ascii=False) + "\n```"

    result = suite.trigger_panel_overlay("000001", tier="deep", llm_caller=lambda p: (True, good))
    assert result["success"] is True
    assert result["overlay"]["reviewed"] is True
    assert ("analysis_overlay", "000001") in saved          # 已落 kv
    assert result["merged_panel"]["great_divide"]["punchline"] == "放量突破压制估值"


def test_trigger_panel_overlay_lite_returns_unavailable(monkeypatch):
    from data_store import kv_repo
    monkeypatch.setattr(kv_repo, "set_", lambda *a, **k: None)
    monkeypatch.setattr(kv_repo, "get", lambda ns, key: None)
    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]
    called = []
    result = suite.trigger_panel_overlay("000001", tier="lite",
                                         llm_caller=lambda p: called.append(p) or (True, "{}"))
    assert called == []                                     # lite 不调 LLM
    assert result["success"] is False
    assert result["overlay"]["reviewed"] is False
```

> 假设 `_fake_ohlcv` 与 `StockAnalysisSuite` 已在该测试文件顶部导入/定义（Phase 1 集成测试已用过 `_fake_ohlcv`）。若签名不同，沿用文件既有 fixture 写法。

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_stock_analysis_suite.py -q -k "analysis_overlay or panel_overlay"`
Expected: FAIL（payload 无 `analysis_overlay` key / 无 `_collect_analysis_overlay` / 无 `trigger_panel_overlay`）

- [ ] **Step 3: 在 `analysis/stock_analysis_suite.py` 顶部加 import + kv 命名空间常量**

在文件已有 import 区（`from analysis.llm_service import LLMAnalyzer` 附近）追加：

```python
from analysis.analysis_overlay import build_overlay, merge_overlay
from data_store import kv_repo

_OVERLAY_NS = "analysis_overlay"
```

- [ ] **Step 4: 实现 `_collect_analysis_overlay`（加在 `_collect_panel` 附近）**

```python
    def _collect_analysis_overlay(self, code: str) -> dict:
        """读取已持久化的 LLM 覆盖层（spec §7 P0-A）。
        有历史 → 原样返回但 data_status 置 stale；无 → unavailable/reviewed=False（前端回退规则文案）。
        任何异常都降级，不影响其它 Tab。"""
        try:
            hit = kv_repo.get(_OVERLAY_NS, str(code))
        except Exception:  # noqa: BLE001
            hit = None
        if not hit:
            return {
                "data_status": "unavailable", "last_updated": None, "reviewed": False,
                "tier": "lite", "great_divide_override": None, "risks": [],
                "panel_insights": {}, "buy_zones": None, "narrative_override": None,
                "reason": "尚未生成 AI 覆盖层（点击「AI 深度点评」生成）",
            }
        overlay, _epoch = hit
        if isinstance(overlay, dict):
            overlay = {**overlay, "data_status": "stale"}  # 读历史 → stale
        return overlay
```

- [ ] **Step 5: 在 `_compute_full_payload` 返回 dict 追加 `analysis_overlay` key**

定位 `_compute_full_payload` 的返回 dict（含 `"panel": panel,` 那段，~L237-258），在 `"panel": panel,` 之后追加一行：

```python
            "panel": panel,
            "analysis_overlay": self._collect_analysis_overlay(code),
```

- [ ] **Step 6: 实现 `trigger_panel_overlay`（加在 `trigger_ai_interpretation` 之后，~L202 后）**

```python
    def trigger_panel_overlay(
        self,
        code: str,
        tier: str = "deep",
        *,
        llm_caller=None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """按需生成多空评审团 LLM 覆盖层（spec §7 P0-A）。
        lite 不调 LLM；medium/deep 生成 + 校验 + 持久化到 kv_repo（可审计/回滚）。
        返回 {success, overlay, merged_panel}；失败也返回结构化 overlay（reviewed=False）。"""
        if force_refresh:
            self.invalidate(code)
        suite_data = self.get_full_payload(code)
        panel = suite_data.get("panel") or {}
        overlay = build_overlay(panel, suite_data, tier, llm_caller=llm_caller)
        try:
            kv_repo.set_(_OVERLAY_NS, str(code), overlay)
        except Exception:  # noqa: BLE001
            pass
        return {
            "success": bool(overlay.get("reviewed")),
            "overlay": overlay,
            "merged_panel": merge_overlay(panel, overlay),
        }
```

- [ ] **Step 7: 运行测试，确认通过 + 全量回归（向后兼容）**

Run: `.venv/bin/python -m pytest tests/test_stock_analysis_suite.py tests/test_analysis_overlay.py -q`
Expected: PASS（含 Phase 1 既有用例不回归）

- [ ] **Step 8: 提交**

```bash
git add analysis/stock_analysis_suite.py tests/test_stock_analysis_suite.py
git commit -m "feat(suite): analysis_overlay payload key + _collect_analysis_overlay(读 kv) + trigger_panel_overlay(生成+落 kv)（P0-A Task 4）"
```

---

## Task 5: service 薄封装 + 新端点 `POST /…/panel-overlay`

**Files:**
- Modify: `webui/services/stock_suite_service.py`
- Modify: `webui/robyn_app.py`
- Test: `tests/test_robyn_app.py`（文件末尾追加）

新增独立端点（不动既有 markdown `/ai` 端点）：`POST /api/stock-analysis-suite/:stock_code/panel-overlay`，body `{tier}`（默认 deep）。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_robyn_app.py` 末尾）**

```python
def test_panel_overlay_endpoint_returns_overlay(robyn_test_client, monkeypatch):
    """POST /…/panel-overlay 返回 {success, overlay, merged_panel}。service 层 stub。"""
    import webui.core as webui_core

    fake = {
        "success": True,
        "overlay": {"reviewed": True, "tier": "deep", "data_status": "fresh",
                    "great_divide_override": {"punchline": "多头占优"}, "risks": ["x"],
                    "panel_insights": {}, "buy_zones": {"value": [], "growth": [],
                    "technical": [], "youzi": []}, "narrative_override": None,
                    "last_updated": "2026-05-30T14:00:00", "reason": None},
        "merged_panel": {"great_divide": {"punchline": "多头占优"}},
    }
    monkeypatch.setattr(webui_core.STOCK_SUITE_SERVICE, "trigger_panel_overlay",
                        lambda code, tier="deep", force_refresh=False: fake)

    resp = robyn_test_client.post("/api/stock-analysis-suite/000001/panel-overlay",
                                  json={"tier": "deep"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["overlay"]["reviewed"] is True
    assert body["merged_panel"]["great_divide"]["punchline"] == "多头占优"


def test_panel_overlay_endpoint_bad_code_returns_400(robyn_test_client, monkeypatch):
    import webui.core as webui_core
    def _raise(code, tier="deep", force_refresh=False):
        raise ValueError("bad code")
    monkeypatch.setattr(webui_core.STOCK_SUITE_SERVICE, "trigger_panel_overlay", _raise)
    resp = robyn_test_client.post("/api/stock-analysis-suite/zzz/panel-overlay", json={"tier": "deep"})
    assert resp.status_code == 400
```

> `robyn_test_client` fixture 沿用 `tests/test_robyn_app.py` 既有范式；POST/json 调用方式照搬该文件已有的 POST 用例（若既有用例用别的 client 调用法，沿用之）。

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_robyn_app.py -q -k panel_overlay`
Expected: FAIL（路由 404 / service 无 `trigger_panel_overlay`）

- [ ] **Step 3: 在 `webui/services/stock_suite_service.py` 加薄封装（`trigger_ai_interpretation` 之后）**

```python
    def trigger_panel_overlay(
        self,
        code: str,
        tier: str = "deep",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        code = self._validate_code(code)
        return self._suite.trigger_panel_overlay(code, tier=tier, force_refresh=force_refresh)
```

- [ ] **Step 4: 在 `webui/robyn_app.py` 注册新端点（`post_stock_analysis_suite_ai` 之后）**

```python
@_native_post("/api/stock-analysis-suite/:stock_code/panel-overlay")
def post_stock_analysis_suite_panel_overlay(request: Request, stock_code=None) -> Response:
    code = _path_param(request, "stock_code", stock_code)
    body = _request_json(request) or {}
    tier = str(body.get("tier") or "deep")
    force_refresh = bool(body.get("force_refresh", False))
    try:
        payload = webui_core.STOCK_SUITE_SERVICE.trigger_panel_overlay(
            code, tier=tier, force_refresh=force_refresh,
        )
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"success": False, "error": str(exc)}, status_code=500)
    return _json_response(payload)
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_robyn_app.py -q`
Expected: PASS（新 2 例 + 既有全绿）

- [ ] **Step 6: 提交**

```bash
git add webui/services/stock_suite_service.py webui/robyn_app.py tests/test_robyn_app.py
git commit -m "feat(api): POST /…/panel-overlay 端点 + service 封装（tier 分档，P0-A Task 5）"
```

---

## Task 6: 前端 —— `renderSuitePanel` 升档按钮 + overlay 渲染

**Files:**
- Modify: `webui/templates/desktop.html`（`renderSuitePanel` ~L3358 区，新增 `triggerPanelOverlay`）
- Modify: `webui/static/kronos_desktop.css`（文件末尾加 `.bbp-overlay-*`）

> **验证配方（项目记忆 [[webui-desktop-verification-recipe]]）：** jinja `parse()` + `import webui.robyn_app` + 抽 `<script>` 块 `node --check`。macOS 无 `timeout`。

- [ ] **Step 1: 在 `renderSuitePanel` 顶部（温度计 head 之后）插入 overlay 区 + 升档按钮**

在 `renderSuitePanel`（Phase 1 实现）里，`pane.innerHTML = ...` 的模板字符串中，把 `<div class="bbp-punchline">...</div>` 之后、`<div class="bbp-section-title">量化指标（16）</div>` 之前，插入 overlay 容器：

```javascript
          <div class="bbp-overlay" id="bbpOverlay">
            ${renderPanelOverlay(payload)}
          </div>
```

- [ ] **Step 2: 在 `renderSuitePanel` 函数之后新增 `renderPanelOverlay` 与 `triggerPanelOverlay`**

```javascript
      // P0-A：LLM 覆盖层渲染（reviewed=true 显示 AI 点评；否则显示升档按钮，回退规则文案）
      function renderPanelOverlay(payload) {
        const ov = (payload && payload.analysis_overlay) || {};
        const stock = (payload && payload.stock) || {};
        if (!ov.reviewed) {
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
        return `
          <div class="bbp-overlay-card" data-status="${html(ov.data_status || "")}">
            <div class="bbp-overlay-tag">AI 点评 · ${html(ov.tier || "")}${ov.data_status === "stale" ? " · 历史" : ""}</div>
            ${nar}
            ${risks ? `<div class="bbp-overlay-risks"><b>风险</b><ul>${risks}</ul></div>` : ""}
            <div class="bbp-overlay-zones">
              ${zoneRow("value", "价值")}${zoneRow("growth", "成长")}
              ${zoneRow("technical", "技术")}${zoneRow("youzi", "游资")}
            </div>
          </div>`;
      }

      async function triggerPanelOverlay(code) {
        if (!code) { showToast("缺少股票代码"); return; }
        const box = document.getElementById("bbpOverlay");
        if (box) box.innerHTML = `<div class="bbp-overlay-empty">⏳ 正在调用 DeepSeek 生成深度点评…</div>`;
        try {
          const resp = await fetch(`/api/stock-analysis-suite/${encodeURIComponent(code)}/panel-overlay`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tier: "deep" }),
          });
          const data = await resp.json();
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
        } catch (err) {
          if (box) box.innerHTML = `<div class="bbp-overlay-empty">
            <span class="bbp-overlay-reason">网络错误：${html(String(err && err.message || err))}</span>
            <button class="bbp-overlay-btn" type="button" onclick="triggerPanelOverlay('${html(code)}')">重试</button>
          </div>`;
        }
      }
```

- [ ] **Step 3: 在成员行渲染处展示逐人 insight（懒渲染段，Phase 1 `bbp-member` 模板里追加）**

定位 Phase 1 `renderSuitePanel` 内懒渲染成员行的模板（`box.innerHTML = members.map(...)`），在 `bbp-member-head` 那一行后追加 insight（若有）：

```javascript
              <span class="bbp-member-name">${html(a.name)}${a.source === "rule" ? '<em class="bbp-rule-tag">规则推断</em>' : ""}</span>
              <span class="bbp-member-head">${html(a.insight || a.headline)}</span>
              <span class="bbp-member-score" style="color:${bbpSignalColor(a.signal)}">${a.score}</span>
```

> 即：成员行优先显示 `a.insight`（LLM 覆盖），无则回退 `a.headline`（规则）。

- [ ] **Step 4: 在 `webui/static/kronos_desktop.css` 末尾加 overlay 样式**

```css
/* ===== 多空评审团 — LLM 覆盖层（P0-A）===== */
.bbp-overlay { margin: 10px 0; }
.bbp-overlay-empty { display: flex; align-items: center; gap: 12px; padding: 8px 0; }
.bbp-overlay-btn { padding: 6px 14px; border-radius: 8px; border: none; cursor: pointer;
  background: linear-gradient(90deg, #2f6fdd, #4f8bff); color: #fff; font-weight: 600; }
.bbp-overlay-reason { font-size: 12px; color: #6b778a; }
.bbp-overlay-card { border: 1px solid #e1e6ee; border-left: 3px solid #2f6fdd;
  border-radius: 8px; padding: 10px 14px; background: #f7f9fc; }
.bbp-overlay-card[data-status="stale"] { border-left-color: #d97706; }
.bbp-overlay-tag { font-size: 11px; color: #2f6fdd; font-weight: 700; margin-bottom: 6px; }
.bbp-overlay-nar { font-size: 13px; margin-bottom: 6px; }
.bbp-overlay-risks ul { margin: 4px 0 0; padding-left: 18px; }
.bbp-overlay-risks li { font-size: 12px; color: #92400e; }
.bbp-overlay-zones { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.bbp-zone { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.bbp-zone-label { font-size: 11px; color: #6b778a; min-width: 32px; }
.bbp-zone-pill { font-size: 11px; padding: 1px 8px; border-radius: 999px; background: #e7effd; color: #2f6fdd; }
```

- [ ] **Step 5: 验证 desktop.html 结构 + 内联 JS 语法**

Run:
```bash
cd /Users/palmer/IdeaProjects/projectSync/AI/project/kronos_ultra
.venv/bin/python - <<'PY'
import re
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader("webui/templates"))
env.parse(open("webui/templates/desktop.html", encoding="utf-8").read())
print("jinja parse OK")
import webui.robyn_app  # noqa: F401
print("import robyn_app OK")
html = open("webui/templates/desktop.html", encoding="utf-8").read()
blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
open("/tmp/desktop_inline_p0a.js", "w", encoding="utf-8").write("\n".join(blocks))
print("renderPanelOverlay defs:", html.count("function renderPanelOverlay"))
print("triggerPanelOverlay defs:", html.count("function triggerPanelOverlay"))
PY
node --check /tmp/desktop_inline_p0a.js && echo "node --check OK"
```
Expected: `jinja parse OK` + `import robyn_app OK` + `renderPanelOverlay defs: 1` + `triggerPanelOverlay defs: 1` + `node --check OK`

- [ ] **Step 6: 手动冒烟（人工）**

启动 `.venv/bin/python webui/run.py` → 个股弹窗 → 多空评审团 Tab：① 默认显示「AI 深度点评」按钮 + 「尚未生成」提示（kv 空、未配置 key 时点按钮应显示降级原因，规则金句/headline 不受影响）；② Console 无报错。确认后 Ctrl-C。

- [ ] **Step 7: 提交**

```bash
git add webui/templates/desktop.html webui/static/kronos_desktop.css
git commit -m "feat(webui): 多空评审团 AI 深度点评升档按钮 + overlay 渲染（金句覆盖/逐人 insight/买点/风险）（P0-A Task 6）"
```

---

## Task 7: 表面测试 + 全量回归终检

**Files:**
- Modify: `tests/test_webui_core_surface.py`（追加 overlay 接线断言）

- [ ] **Step 1: 写测试（追加到 `tests/test_webui_core_surface.py` 末尾）**

```python
def test_desktop_html_has_panel_overlay_wiring():
    """LLM 覆盖层的渲染函数 / 升档按钮 / 端点调用都已接线。"""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    html = (repo_root / "webui" / "templates" / "desktop.html").read_text(encoding="utf-8")
    assert "function renderPanelOverlay" in html
    assert "function triggerPanelOverlay" in html
    assert "/panel-overlay" in html
    assert "analysis_overlay" in html
```

- [ ] **Step 2: 运行该测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_webui_core_surface.py::test_desktop_html_has_panel_overlay_wiring -q`
Expected: PASS

- [ ] **Step 3: 全量回归**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -30`
Expected: 全绿（新增 `test_analysis_overlay` + overlay 集成/端点/表面 + Phase 1 既有用例全部 PASS）。若有 unrelated（工作区在途 provider 等）失败，记入 PR 描述，不在本计划范围。

- [ ] **Step 4: 验收对照 spec §7 / §11 Phase 2（P0-A 部分，人工核对）**

- [ ] LLM 覆盖层输出结构化 JSON（medium=金句+风险 / deep=+逐人点评+买点）
- [ ] schema 校验失败 → 重试 → 仍失败回退 `reviewed=false` + 前端规则文案（不空白/不报错）
- [ ] 未配置 API Key → 短路降级，不浪费重试
- [ ] overlay 独立存 `kv_repo`（物理隔离，可 diff/回滚）
- [ ] payload 含 `analysis_overlay` 且向后兼容（既有 16 key 不丢）
- [ ] lite 默认不调 LLM

- [ ] **Step 5: 更新 spec 状态 + 提交**

在 `docs/superpowers/specs/2026-05-30-bull-bear-investor-panel-tab-design.md` §11 Phase 2 行末标注 `（P0-A 覆盖层 ✅ 完成于 2026-05-XX；P0-B 质量门待下一计划）`。

```bash
git add tests/test_webui_core_surface.py docs/superpowers/specs/2026-05-30-bull-bear-investor-panel-tab-design.md
git commit -m "test(overlay): panel-overlay 表面接线断言 + P0-A 全量回归终检（P0-A Task 7）"
```

---

## 自检（writing-plans skill 要求，作者自查）

**1. Spec 覆盖（spec §7 P0-A）：**
- 重构 `llm_service` 出结构化 JSON（带 schema 重试）→ Task 2 `extract_overlay_json` + Task 3 `build_overlay` 重试循环 ✓（**复用** `LLMAnalyzer.interpret_stock_markdown`，不破坏既有 markdown 路径）
- `analysis_overlay_schema`（jsonschema 思想，缺字段回写重试 N 次，仍失败 `reviewed=false`）→ Task 1 手写 `validate_overlay` + Task 3 重试/回退 ✓
- `merge_overlay`（agent 字段 > 规则 stub）→ Task 3 ✓
- 物理隔离独立存 `kv_repo`（可 diff/审计/回滚）→ Task 4 命名空间 `analysis_overlay` ✓
- 分档 lite/medium/deep，默认 lite → Task 3（lite 不调 LLM）+ Task 5（端点 tier 参数）✓
- 接入点（按需触发）→ Task 5 新端点 `POST /…/panel-overlay`（不动既有 `/ai`）✓
- payload 增 `analysis_overlay`（规则阶段可空，前端回退）→ Task 4 + Task 6 ✓
- 前端展示覆盖（金句/逐人点评/买点/风险）→ Task 6 ✓

**2. 占位符扫描：** 无 TBD/TODO/"add error handling"/"similar to Task N"。每个代码步骤含完整代码；所有引用函数（`build_overlay`/`merge_overlay`/`validate_overlay`/`build_overlay_prompt`/`extract_overlay_json`/`_collect_analysis_overlay`/`trigger_panel_overlay`/`renderPanelOverlay`/`triggerPanelOverlay`）均在某任务中定义。Task 3 模块级 `last_errors` 已在 Step 4 明确改为函数局部（消除 placeholder/坏味）。

**3. 类型一致性核对：**
- `validate_overlay(obj, tier) -> list[str]`：Task 1 定义，Task 3 消费 ✓
- `build_overlay(panel, payload, tier, *, llm_caller, retries, now_iso) -> dict`：Task 3 定义，Task 4 `trigger_panel_overlay` 调用一致 ✓
- `merge_overlay(panel, overlay) -> dict`：Task 3 定义，Task 4 调用 ✓
- LLM caller 协议 `(str) -> (bool, str)`：Task 3 默认封装 `interpret_stock_markdown`（返回 `(ok, text, tokens)` → 丢弃 tokens 取前两个）与勘察的真实签名一致 ✓
- overlay dict key（`data_status`/`reviewed`/`tier`/`great_divide_override`/`risks`/`panel_insights`/`buy_zones`/`narrative_override`/`reason`/`last_updated`）：Task 3 产出，Task 4 持久化、Task 6 `renderPanelOverlay` 消费一致 ✓
- `kv_repo.get(ns,key) -> (payload,epoch)|None` / `set_(ns,key,payload,ttl=0)`：与勘察的真实签名一致（Task 4 解包 `overlay, _epoch = hit`）✓
- 前端 tab key `"panel"`：复用 Phase 1，`renderSuitePanel` 整面重渲注入 overlay ✓

**4. 超范围未做（正确，转后续计划）：**
- P0-B 机械质量门（覆盖度/占位符/FACTCHECK/行业 sanity）→ 下一独立计划（spec §8）
- ★Kronos 预测格（模型运行时）→ 用户裁定本期不纳入
- 回测校准 F4 → Phase 3（spec §10）
