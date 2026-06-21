# 涨停强势形态自动识别 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rule-based limit-up strong-pattern recognition to individual stock analysis, K-line payloads, and the desktop UI.

**Architecture:** Add `analysis/limit_up_patterns.py` as the single source of truth for bar normalization, limit-up classification, ten pattern detectors, and per-stock historical win-rate stats. `StockAnalysisSuite` consumes the detector once per payload and exposes `limit_up_screening` plus `overview.strong_patterns`; `StockKlineService` attaches compact `patterns` to K-line responses; JavaScript only renders annotations and cards.

**Tech Stack:** Python 3, pandas/numpy already present in the project, pytest, Plotly in `webui/static/kronos_desktop_app.js`.

---

日期: 2026-06-21
分支: V2.1.1
Spec: `docs/superpowers/specs/2026-06-20-limit-up-strong-pattern-recognition-design.md`

## Spec Review Notes

The spec is ready to implement with two small adjustments folded into this plan:

1. Pass stock `name` into pattern detection wherever available. The spec allows suite-side `name=None`, but K-line payloads already expose `name` after quote overlay; use it for ST/退 5% board threshold when present.
2. Add a private K-line payload helper in `webui/services/kline_service.py` so both success paths (`sina_records` and `local_records`) attach `patterns`. Do not duplicate detector calls in each return block.

Do not change `webui/templates/desktop.html`; the `limit_up_screening` tab and pane already exist.

## File Structure

- Create `analysis/limit_up_patterns.py`: pure module, no network or filesystem I/O. Owns normalized bars, limit-up rules, ten detectors, `detect_all`, and historical stats.
- Create `tests/test_limit_up_patterns.py`: synthetic K-line fixtures for helpers, all ten pattern detectors, `detect_all`, and backtests.
- Modify `analysis/stock_analysis_suite.py`: import detector helpers, collect matches in `_collect_inputs`, add `_collect_limit_up_patterns`, include real `limit_up_screening`, and add `overview.strong_patterns`.
- Create `tests/test_stock_suite_limit_up.py`: suite payload assembly and graceful degradation.
- Modify `webui/services/kline_service.py`: import detector helpers and attach compact `patterns` via helper.
- Create `tests/test_kline_patterns_payload.py`: K-line payload includes patterns and degrades to `[]` on detector failure.
- Modify `webui/static/kronos_desktop_app.js`: add pattern chart annotations, render strong-pattern overview chips, and replace the limit-up pane with real pattern cards plus the existing 4-factor environment block.

Run Python tests from repo root with:

```bash
.venv/bin/python -m pytest <test-file> -q
```

If `.venv` is unavailable in the execution environment, use `python -m pytest ...` after confirming the project imports resolve.

---

## Task 1: Detector Data Contract And Limit-Up Helpers

**Files:**
- Create: `analysis/limit_up_patterns.py`
- Create: `tests/test_limit_up_patterns.py`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_limit_up_patterns.py` with the helper section first:

```python
import math

import pandas as pd

from analysis.limit_up_patterns import (
    bars_from_dataframe,
    bars_from_records,
    board_limit_pct,
    detect_all,
    is_limit_up,
)


def bar(date, open_, close, high=None, low=None, volume=1000, pct_chg=None):
    high = max(open_, close) if high is None else high
    low = min(open_, close) if low is None else low
    out = {
        "date": date,
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
    }
    if pct_chg is not None:
        out["pct_chg"] = float(pct_chg)
    return out


def test_board_limit_pct_by_market_and_name():
    assert board_limit_pct("600000") == 10.0
    assert board_limit_pct("000001") == 10.0
    assert board_limit_pct("002001") == 10.0
    assert board_limit_pct("300001") == 20.0
    assert board_limit_pct("688001") == 20.0
    assert board_limit_pct("830000") == 30.0
    assert board_limit_pct("600000", "ST测试") == 5.0
    assert board_limit_pct("300001", "*ST测试") == 5.0
    assert board_limit_pct("", None) == 10.0


def test_is_limit_up_requires_sealed_close_near_high():
    assert is_limit_up(bar("2026-01-02", 10, 11, high=11, low=10, pct_chg=10.0), 10.0)
    assert is_limit_up(bar("2026-01-02", 10, 10.95, high=10.96, low=10, pct_chg=9.5), 10.0)
    assert not is_limit_up(bar("2026-01-02", 10, 10.7, high=11.0, low=10, pct_chg=10.0), 10.0)
    assert not is_limit_up(bar("2026-01-02", 10, 10.93, high=10.93, low=10, pct_chg=9.3), 10.0)


def test_bars_from_records_sorts_and_computes_pct_change():
    records = [
        bar("2026-01-03", 10, 11, high=11, pct_chg=None),
        bar("2026-01-01", 10, 10, high=10, pct_chg=None),
        bar("2026-01-02", 10, 10.5, high=10.5, pct_chg=None),
    ]
    bars = bars_from_records(records)
    assert [b["date"] for b in bars] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert bars[0]["pct_chg"] == 0.0
    assert round(bars[1]["pct_chg"], 2) == 5.0
    assert round(bars[2]["pct_chg"], 2) == 4.76


def test_bars_from_dataframe_accepts_timestamp_column_and_index():
    df = pd.DataFrame({
        "timestamps": pd.to_datetime(["2026-01-02", "2026-01-01"]),
        "open": [10, 9],
        "high": [11, 10],
        "low": [9, 8.8],
        "close": [10.5, 9.5],
        "volume": [2000, 1000],
    })
    bars = bars_from_dataframe(df)
    assert [b["date"] for b in bars] == ["2026-01-01", "2026-01-02"]
    assert all({"date", "open", "high", "low", "close", "volume", "pct_chg"} <= set(b) for b in bars)
```

- [ ] **Step 2: Run helper tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_limit_up_patterns.py -q
```

Expected: import failure for `analysis.limit_up_patterns`.

- [ ] **Step 3: Implement helper module skeleton**

Create `analysis/limit_up_patterns.py` with constants, data normalization, and limit-up helpers:

```python
"""Rule-based strong limit-up pattern detection.

Pure functions only: no network, no filesystem, no app state.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Callable, Iterable

import math

try:
    import pandas as pd
except Exception:  # noqa: BLE001
    pd = None


PULLBACK_MAX_DAYS = 5
DOUBLE_VOL_RATIO = 1.8
SHRINK_VOL_RATIO = 0.8
HUGE_VOL_RATIO = 1.5
LEFT_PEAK_LOOKBACK = 60
HOLD_MAX_DAYS = 6
PLATFORM_MIN_DAYS = 4
PLATFORM_MAX_DAYS = 12
PLATFORM_RANGE = 0.09
SHOULDER_MAX_DAYS = 6
SHOULDER_MAX_DRAWDOWN = 0.08
RECENT_DAYS = 10

STRENGTH_RANK = {"强": 0, "中": 1}


@dataclass(frozen=True)
class PatternDef:
    key: str
    name: str
    detector: Callable[[dict[str, Any]], list[dict[str, Any]]]
    default_tone: str = "warn"


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, "", "—", "N/A"):
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def _date_text(value: Any) -> str:
    if pd is not None and isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def bars_from_records(records: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    for item in records or []:
        open_ = _safe_float(item.get("open"))
        high = _safe_float(item.get("high"))
        low = _safe_float(item.get("low"))
        close = _safe_float(item.get("close"))
        if open_ is None or high is None or low is None or close is None:
            continue
        if open_ <= 0 or high <= 0 or low <= 0 or close <= 0:
            continue
        bars.append({
            "date": _date_text(item.get("date") or item.get("datetime") or item.get("time")),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": _safe_float(item.get("volume"), 0.0) or 0.0,
            "amount": _safe_float(item.get("amount"), 0.0) or 0.0,
            "pct_chg": _safe_float(item.get("pct_chg")),
        })
    bars.sort(key=lambda b: b["date"])
    prev_close: float | None = None
    for b in bars:
        if b["pct_chg"] is None:
            b["pct_chg"] = (b["close"] / prev_close - 1.0) * 100.0 if prev_close else 0.0
        prev_close = b["close"]
    return bars


def bars_from_dataframe(df: Any) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    work = df.copy()
    timestamp_col = next((c for c in ("timestamps", "timestamp", "date", "datetime", "time") if c in work.columns), None)
    if timestamp_col is None:
        work = work.reset_index()
        timestamp_col = next((c for c in ("timestamps", "timestamp", "date", "datetime", "time", "index") if c in work.columns), None)
    records = []
    for _, row in work.iterrows():
        item = {k: row.get(k) for k in ("open", "high", "low", "close", "volume", "amount", "pct_chg") if k in work.columns}
        item["date"] = row.get(timestamp_col) if timestamp_col else ""
        records.append(item)
    return bars_from_records(records)


def board_limit_pct(code: str | None, name: str | None = None) -> float:
    name_text = str(name or "").upper()
    if "ST" in name_text or "退" in name_text:
        return 5.0
    code_text = str(code or "").strip().split(".")[0].zfill(6)
    if code_text.startswith(("688", "689", "300", "301")):
        return 20.0
    if code_text.startswith(("8", "43", "83", "87", "92")):
        return 30.0
    return 10.0


def is_limit_up(bar: dict[str, Any], limit_pct: float) -> bool:
    pct = _safe_float(bar.get("pct_chg"), 0.0) or 0.0
    high = _safe_float(bar.get("high"), 0.0) or 0.0
    close = _safe_float(bar.get("close"), 0.0) or 0.0
    return pct >= limit_pct - 0.5 and high > 0 and close >= high * 0.999
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_limit_up_patterns.py -q
```

Expected: helper tests pass; later detector tests do not exist yet.

---

## Task 2: Pattern Detection Core

**Files:**
- Modify: `analysis/limit_up_patterns.py`
- Modify: `tests/test_limit_up_patterns.py`

- [ ] **Step 1: Add detector tests**

Append synthetic detector tests. Keep data intentionally small and deterministic:

```python
def trend_prefix(n=80, start=10.0):
    bars = []
    close = start
    for i in range(n):
        close *= 1.002
        bars.append(bar(f"2026-01-{(i % 28) + 1:02d}-{i:03d}", close * 0.995, close, high=close * 1.01, low=close * 0.99, volume=1000 + i))
    for idx, b in enumerate(bars):
        b["date"] = f"2026-{1 + idx // 28:02d}-{1 + idx % 28:02d}"
    return bars


def append_zt(bars, date, prev_close, volume=5000):
    close = round(prev_close * 1.10, 2)
    bars.append(bar(date, prev_close * 1.02, close, high=close, low=prev_close * 1.01, volume=volume, pct_chg=10.0))
    return close


def patterns(bars, code="600000", recent_days=None):
    return {m["pattern"]: m for m in detect_all(bars, code=code, recent_days=recent_days)}


def test_detect_pullback_double_volume():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    bars.extend([
        bar("2026-04-02", zt_close * 0.99, zt_close * 0.98, high=zt_close, low=zt_close * 0.96, volume=2500),
        bar("2026-04-03", zt_close * 0.98, zt_close * 0.985, high=zt_close, low=zt_close * 0.96, volume=2600),
        bar("2026-04-04", zt_close * 0.99, zt_close * 1.01, high=zt_close * 1.02, low=zt_close * 0.98, volume=5200),
    ])
    got = patterns(bars)
    assert got["zt_pullback_double_volume"]["anchor_date"] == "2026-04-01"
    assert got["zt_pullback_double_volume"]["trigger_date"] == "2026-04-04"


def test_detect_beauty_shoulder():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    bars.extend([
        bar("2026-04-02", zt_close * 0.995, zt_close * 0.985, high=zt_close, low=zt_close * 0.98, volume=4200),
        bar("2026-04-03", zt_close * 0.986, zt_close * 0.980, high=zt_close * 0.99, low=zt_close * 0.975, volume=3600),
        bar("2026-04-04", zt_close * 0.981, zt_close * 0.990, high=zt_close * 0.995, low=zt_close * 0.98, volume=3100),
    ])
    got = patterns(bars)
    assert got["zt_beauty_shoulder"]["trigger_date"] == "2026-04-04"


def test_detect_high_volume_hold_and_volume_over_left_peak():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=9000)
    low = bars[-1]["low"]
    bars.extend([
        bar("2026-04-02", zt_close * 0.99, zt_close * 0.98, high=zt_close, low=low * 1.002, volume=3000),
        bar("2026-04-03", zt_close * 0.98, zt_close * 1.01, high=zt_close * 1.02, low=low * 1.005, volume=3200),
    ])
    got = patterns(bars)
    assert got["zt_high_volume_hold"]["strength"] == "强"
    assert got["zt_volume_over_left_peak"]["trigger_date"] == "2026-04-01"


def test_detect_huge_yin_rewrap():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    append_zt(bars, "2026-04-01", prev, volume=5000)
    y_open = bars[-1]["close"] * 1.02
    bars.append(bar("2026-04-02", y_open, y_open * 0.95, high=y_open * 1.01, low=y_open * 0.94, volume=9000))
    bars.append(bar("2026-04-03", y_open * 0.96, y_open * 1.02, high=y_open * 1.03, low=y_open * 0.95, volume=7000))
    got = patterns(bars)
    assert got["zt_huge_yin_rewrap"]["anchor_date"] == "2026-04-02"
    assert got["zt_huge_yin_rewrap"]["strength"] == "强"


def test_detect_board_then_bull_cannon():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    bars.extend([
        bar("2026-04-02", zt_close * 1.01, zt_close * 1.03, high=zt_close * 1.04, low=zt_close * 1.00, volume=4200),
        bar("2026-04-03", zt_close * 1.025, zt_close * 1.015, high=zt_close * 1.035, low=zt_close * 1.005, volume=3000),
        bar("2026-04-04", zt_close * 1.018, zt_close * 1.035, high=zt_close * 1.04, low=zt_close * 1.01, volume=4300),
    ])
    assert patterns(bars)["zt_board_then_bull_cannon"]["trigger_date"] == "2026-04-04"


def test_detect_n_shape_relay_and_ma_pullback_hold():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    bars.extend([
        bar("2026-04-02", zt_close * 0.99, zt_close * 0.985, high=zt_close, low=zt_close * 0.975, volume=2500),
        bar("2026-04-03", zt_close * 0.986, zt_close * 0.99, high=zt_close * 0.995, low=zt_close * 0.98, volume=2300),
        bar("2026-04-04", zt_close, zt_close * 1.02, high=zt_close * 1.03, low=zt_close * 0.99, volume=4200),
    ])
    got = patterns(bars)
    assert got["zt_n_shape_relay"]["trigger_date"] == "2026-04-04"
    assert got["zt_ma_pullback_hold"]["trigger_date"] in {"2026-04-03", "2026-04-04"}


def test_detect_consecutive_boards():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    first = append_zt(bars, "2026-04-01", prev, volume=5000)
    append_zt(bars, "2026-04-02", first, volume=8000)
    got = patterns(bars)
    assert got["zt_consecutive_boards"]["trigger_date"] == "2026-04-02"
    assert got["zt_consecutive_boards"]["strength"] == "中"


def test_detect_platform_breakout():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt_close = append_zt(bars, "2026-04-01", prev, volume=5000)
    for i in range(2, 8):
        bars.append(bar(f"2026-04-{i:02d}", zt_close * 0.99, zt_close * (0.99 + i * 0.001), high=zt_close * 1.01, low=zt_close * 0.97, volume=2500))
    bars.append(bar("2026-04-08", zt_close * 1.01, zt_close * 1.04, high=zt_close * 1.05, low=zt_close, volume=4200))
    assert patterns(bars)["zt_platform_breakout"]["trigger_date"] == "2026-04-08"


def test_detect_all_recent_filter_and_sorting():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    first = append_zt(bars, "2026-04-01", prev, volume=5000)
    second = append_zt(bars, "2026-04-02", first, volume=8000)
    append_zt(bars, "2026-04-03", second, volume=11000)
    matches = detect_all(bars, code="600000", recent_days=1)
    assert matches
    assert all(m["days_ago"] <= 1 for m in matches)
    assert matches == sorted(matches, key=lambda m: (m["days_ago"], 0 if m["strength"] == "强" else 1))
```

- [ ] **Step 2: Run detector tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_limit_up_patterns.py -q
```

Expected: failures for missing `detect_all` detector behavior.

- [ ] **Step 3: Implement enrichment, match builder, detectors, and registry**

Add these functions to `analysis/limit_up_patterns.py`. Use simple list math; avoid adding dependencies.

Implementation requirements:

- `_sma(values, window)` returns a same-length list with `None` until enough history exists.
- `_enrich(bars, code, name)` returns arrays and `is_zt`.
- `_make_match(...)` fills the exact Match contract in the spec.
- `detect_all(...)` runs every registered detector, dedupes `(pattern, trigger_date)`, applies `recent_days`, and sorts by `(days_ago, strength)`.
- Each detector returns all matches, not just the latest. The frontend and suite decide display density.

Use these detector boundaries:

```python
def _sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        out.append(total / window if i >= window - 1 else None)
    return out


def _enrich(bars: list[dict[str, Any]], code: str | None, name: str | None) -> dict[str, Any]:
    clean = bars_from_records(bars)
    closes = [b["close"] for b in clean]
    opens = [b["open"] for b in clean]
    highs = [b["high"] for b in clean]
    lows = [b["low"] for b in clean]
    vols = [b["volume"] for b in clean]
    limit_pct = board_limit_pct(code, name)
    return {
        "bars": clean,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "vols": vols,
        "pct": [b["pct_chg"] for b in clean],
        "ma5": _sma(closes, 5),
        "ma10": _sma(closes, 10),
        "ma20": _sma(closes, 20),
        "ma60": _sma(closes, 60),
        "vol_ma5": _sma(vols, 5),
        "is_zt": [is_limit_up(b, limit_pct) for b in clean],
        "limit_pct": limit_pct,
    }


def _make_match(e: dict[str, Any], pattern: str, name: str, anchor: int, trigger: int, strength: str, tone: str, rationale: str, mark_indexes: list[int] | None = None) -> dict[str, Any]:
    bars = e["bars"]
    indexes = mark_indexes or [anchor, trigger]
    return {
        "pattern": pattern,
        "name": name,
        "anchor_date": bars[anchor]["date"],
        "trigger_date": bars[trigger]["date"],
        "anchor_index": anchor,
        "trigger_index": trigger,
        "mark_dates": [bars[i]["date"] for i in indexes if 0 <= i < len(bars)],
        "strength": strength,
        "tone": tone,
        "rationale": rationale,
        "days_ago": max(0, len(bars) - 1 - trigger),
    }
```

Implement ten `detect_<pattern_key>(e)` functions with the exact keys from the spec:

- `detect_zt_pullback_double_volume`
- `detect_zt_beauty_shoulder`
- `detect_zt_high_volume_hold`
- `detect_zt_volume_over_left_peak`
- `detect_zt_huge_yin_rewrap`
- `detect_zt_board_then_bull_cannon`
- `detect_zt_n_shape_relay`
- `detect_zt_consecutive_boards`
- `detect_zt_platform_breakout`
- `detect_zt_ma_pullback_hold`

Register them at module bottom:

```python
PATTERNS = [
    PatternDef("zt_pullback_double_volume", "涨停回调倍量冲锋", detect_zt_pullback_double_volume, "danger"),
    PatternDef("zt_beauty_shoulder", "涨停美人肩", detect_zt_beauty_shoulder, "warn"),
    PatternDef("zt_high_volume_hold", "涨停高量不破", detect_zt_high_volume_hold, "danger"),
    PatternDef("zt_volume_over_left_peak", "涨停量过左峰", detect_zt_volume_over_left_peak, "danger"),
    PatternDef("zt_huge_yin_rewrap", "涨停巨量阴反包", detect_zt_huge_yin_rewrap, "danger"),
    PatternDef("zt_board_then_bull_cannon", "先板后多方炮", detect_zt_board_then_bull_cannon, "warn"),
    PatternDef("zt_n_shape_relay", "涨停N字接力", detect_zt_n_shape_relay, "warn"),
    PatternDef("zt_consecutive_boards", "连板加速", detect_zt_consecutive_boards, "danger"),
    PatternDef("zt_platform_breakout", "涨停平台突破", detect_zt_platform_breakout, "warn"),
    PatternDef("zt_ma_pullback_hold", "缩量回踩均线企稳", detect_zt_ma_pullback_hold, "info"),
]
```

Keep each detector permissive enough for the synthetic fixtures but faithful to the spec thresholds. Do not make patterns mutually exclusive.

- [ ] **Step 4: Run detector tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_limit_up_patterns.py -q
```

Expected: all helper and detector tests pass. If one detector is too brittle, adjust only that detector or its synthetic fixture; do not relax shared limit-up sealing rules.

---

## Task 3: Historical Per-Stock Backtest Stats

**Files:**
- Modify: `analysis/limit_up_patterns.py`
- Modify: `tests/test_limit_up_patterns.py`

- [ ] **Step 1: Add failing backtest tests**

Append:

```python
from analysis.limit_up_patterns import backtest_all, backtest_pattern_on_history


def test_backtest_pattern_on_history_forward_returns_and_sample_note():
    bars = trend_prefix()
    prev = bars[-1]["close"]
    zt = append_zt(bars, "2026-04-01", prev, volume=6000)
    bars.append(bar("2026-04-02", zt * 0.99, zt * 1.01, high=zt * 1.02, low=zt * 0.98, volume=12000))
    trigger_close = bars[-1]["close"]
    for i, ratio in enumerate([1.02, 1.04, 0.98, 1.06, 1.08, 1.10, 1.12, 1.14, 1.16, 1.18, 1.20, 1.22, 1.24, 1.26, 1.28, 1.30, 1.32, 1.34, 1.36, 1.38], start=3):
        close = trigger_close * ratio
        bars.append(bar(f"2026-04-{i:02d}", close * 0.99, close, high=close * 1.01, low=close * 0.98, volume=3000))

    stats = backtest_pattern_on_history(bars, "zt_huge_yin_rewrap", code="600000", horizons=(5, 10, 20), min_gap_days=5)

    assert stats["name"] == "涨停巨量阴反包"
    assert stats["horizons"]["5"]["count"] == 1
    assert stats["horizons"]["5"]["win_rate"] == 100.0
    assert stats["horizons"]["5"]["avg_return"] > 0
    assert stats["sample_note"] == "样本少，仅供参考"


def test_backtest_all_returns_all_registered_patterns():
    stats = backtest_all(trend_prefix(), code="600000")
    assert len(stats) == 10
    assert "zt_pullback_double_volume" in stats
    assert set(stats["zt_pullback_double_volume"]["horizons"]) == {"5", "10", "20"}
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_limit_up_patterns.py -q
```

Expected: missing backtest functions.

- [ ] **Step 3: Implement backtest functions**

Add:

```python
def _empty_horizon() -> dict[str, Any]:
    return {"count": 0, "win_rate": None, "avg_return": None, "median": None, "best": None, "worst": None}


def _summarize_returns(values: list[float]) -> dict[str, Any]:
    if not values:
        return _empty_horizon()
    wins = [v for v in values if v > 0]
    return {
        "count": len(values),
        "win_rate": round(len(wins) / len(values) * 100.0, 2),
        "avg_return": round(sum(values) / len(values) * 100.0, 2),
        "median": round(median(values) * 100.0, 2),
        "best": round(max(values) * 100.0, 2),
        "worst": round(min(values) * 100.0, 2),
    }


def backtest_pattern_on_history(
    bars: list[dict[str, Any]],
    pattern_key: str,
    code: str | None = None,
    horizons: tuple[int, ...] = (5, 10, 20),
    min_gap_days: int = 5,
) -> dict[str, Any]:
    pattern_def = next((p for p in PATTERNS if p.key == pattern_key), None)
    if pattern_def is None:
        raise ValueError(f"Unknown pattern: {pattern_key}")
    clean = bars_from_records(bars)
    matches = [m for m in pattern_def.detector(_enrich(clean, code, None))]
    matches.sort(key=lambda m: m["trigger_index"])
    selected = []
    last_trigger = -10_000
    for m in matches:
        idx = int(m["trigger_index"])
        if idx - last_trigger >= min_gap_days:
            selected.append(m)
            last_trigger = idx
    by_horizon: dict[str, list[float]] = {str(h): [] for h in horizons}
    closes = [b["close"] for b in clean]
    for m in selected:
        idx = int(m["trigger_index"])
        base = closes[idx] if 0 <= idx < len(closes) else 0
        if base <= 0:
            continue
        for h in horizons:
            if idx + h < len(closes):
                by_horizon[str(h)].append(closes[idx + h] / base - 1.0)
    horizon_stats = {key: _summarize_returns(values) for key, values in by_horizon.items()}
    max_count = max((item["count"] for item in horizon_stats.values()), default=0)
    return {
        "name": pattern_def.name,
        "horizons": horizon_stats,
        "sample_note": "样本少，仅供参考" if max_count < 5 else None,
    }


def backtest_all(
    bars: list[dict[str, Any]],
    code: str | None = None,
    horizons: tuple[int, ...] = (5, 10, 20),
    min_gap_days: int = 5,
) -> dict[str, Any]:
    return {
        p.key: backtest_pattern_on_history(bars, p.key, code=code, horizons=horizons, min_gap_days=min_gap_days)
        for p in PATTERNS
    }
```

If repeated `_enrich` calls are slow in practice, optimize later; for 500 bars and ten patterns this should remain cheap.

- [ ] **Step 4: Run detector suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_limit_up_patterns.py -q
```

Expected: pass.

---

## Task 4: Stock Analysis Suite Integration

**Files:**
- Modify: `analysis/stock_analysis_suite.py`
- Create: `tests/test_stock_suite_limit_up.py`

- [ ] **Step 1: Write failing suite integration tests**

Create `tests/test_stock_suite_limit_up.py`:

```python
import numpy as np
import pandas as pd

from analysis.stock_analysis_suite import StockAnalysisSuite


def _df_with_recent_limit_up_pattern():
    rows = []
    close = 10.0
    for i in range(80):
        close *= 1.002
        rows.append({
            "timestamps": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0 + i,
            "amount": close * (1000.0 + i),
        })
    prev = rows[-1]["close"]
    zt_close = prev * 1.10
    rows.append({"timestamps": pd.Timestamp("2026-04-01"), "open": prev * 1.02, "high": zt_close, "low": prev * 1.01, "close": zt_close, "volume": 6000.0, "amount": zt_close * 6000.0})
    rows.append({"timestamps": pd.Timestamp("2026-04-02"), "open": zt_close * 0.99, "high": zt_close, "low": zt_close * 0.96, "close": zt_close * 0.98, "volume": 2500.0, "amount": zt_close * 2500.0})
    rows.append({"timestamps": pd.Timestamp("2026-04-03"), "open": zt_close * 0.99, "high": zt_close * 1.02, "low": zt_close * 0.98, "close": zt_close * 1.01, "volume": 5200.0, "amount": zt_close * 5200.0})
    return pd.DataFrame(rows)


def test_full_payload_has_real_limit_up_section_and_overview_summary(monkeypatch):
    suite = StockAnalysisSuite(auto_fetch=False)
    df = _df_with_recent_limit_up_pattern()
    suite._load_ohlcv = lambda code: df  # type: ignore[method-assign]
    monkeypatch.setattr("analysis.stock_analysis_suite.FundamentalDataCollector", lambda *a, **k: type("F", (), {"get_comprehensive_data": lambda self: {}})())

    payload = suite._compute_full_payload("600000")

    assert "limit_up_screening" in payload
    assert "limit_up_screening" in payload["stub_tabs"]
    assert payload["limit_up_screening"]["data_status"] == "fresh"
    assert payload["limit_up_screening"]["matches"]
    assert payload["overview"]["strong_patterns"]["detected_count"] >= 1
    assert payload["overview"]["strong_patterns"]["items"][0]["name"]


def test_limit_up_section_degrades_when_ohlcv_missing():
    suite = StockAnalysisSuite(auto_fetch=False)
    payload = {
        "ohlcv_error": "offline",
        "lp_matches": [],
    }
    section = suite._collect_limit_up_patterns("600000", payload)
    assert section["data_status"] == "unavailable"
    assert "offline" in section["reason"]
```

- [ ] **Step 2: Run suite tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_stock_suite_limit_up.py -q
```

Expected: missing suite fields/method.

- [ ] **Step 3: Import detector helpers**

In `analysis/stock_analysis_suite.py`, add near the other analysis imports:

```python
from analysis.limit_up_patterns import (
    RECENT_DAYS,
    backtest_all,
    bars_from_dataframe,
    detect_all,
)
```

- [ ] **Step 4: Collect matches once in `_collect_inputs`**

At the end of the `if df is not None:` block in `_collect_inputs`, after quant models:

```python
            try:
                bars = bars_from_dataframe(df)
                out["lp_matches"] = detect_all(bars, code=code, recent_days=RECENT_DAYS)
            except Exception as exc:  # noqa: BLE001
                out["lp_matches"] = []
                out["lp_error"] = str(exc)
```

- [ ] **Step 5: Add overview summary**

In `compute_overview`, assign the dict to a variable and add `strong_patterns`:

```python
        overview = {
            "radar": radar,
            "key_signals": self._build_key_signals(inputs, radar),
            "deep_signals": self._build_deep_signals(inputs),
            "scenario_probability": self._build_scenario_probability(inputs),
        }
        overview["strong_patterns"] = self._build_strong_patterns_summary(inputs)
        return overview
```

Add the helper method near `_build_key_signals`:

```python
    def _build_strong_patterns_summary(self, inputs: Dict[str, Any]) -> dict:
        matches = inputs.get("lp_matches") or []
        items = []
        for m in matches[:5]:
            items.append({
                "name": m.get("name"),
                "strength": m.get("strength"),
                "tone": m.get("tone"),
                "days_ago": m.get("days_ago"),
                "best_win_rate": None,
            })
        return {"items": items, "detected_count": len(matches)}
```

- [ ] **Step 6: Add `limit_up_screening` section**

Add a method on `StockAnalysisSuite`:

```python
    def _collect_limit_up_patterns(self, code: str, inputs: dict | None) -> dict:
        inputs = inputs or {}
        df = inputs.get("ohlcv")
        if df is None or getattr(df, "empty", True):
            return {
                **_unavailable_section(inputs.get("ohlcv_error") or "OHLCV 数据不足，无法识别涨停强势形态"),
                "matches": [],
                "pattern_stats": {},
                "summary": {"detected_count": 0, "best": None},
            }
        try:
            bars = bars_from_dataframe(df)
            matches = inputs.get("lp_matches")
            if matches is None:
                matches = detect_all(bars, code=code, recent_days=RECENT_DAYS)
            stats = backtest_all(bars, code=code)
            best = None
            for match in matches:
                horizons = (stats.get(match.get("pattern")) or {}).get("horizons") or {}
                for horizon, row in horizons.items():
                    win_rate = row.get("win_rate")
                    count = row.get("count") or 0
                    if win_rate is None or count <= 0:
                        continue
                    if best is None or win_rate > best["win_rate"]:
                        best = {"name": match.get("name"), "win_rate": win_rate, "horizon": horizon}
            return {
                "data_status": "fresh",
                "last_updated": _dt.datetime.now().isoformat(timespec="seconds"),
                "reason": None,
                "matches": matches,
                "pattern_stats": stats,
                "summary": {"detected_count": len(matches), "best": best},
            }
        except Exception as exc:  # noqa: BLE001
            return {
                **_unavailable_section(f"涨停强势形态识别失败：{exc}"),
                "matches": [],
                "pattern_stats": {},
                "summary": {"detected_count": 0, "best": None},
            }
```

- [ ] **Step 7: Wire `_compute_full_payload`**

After `quant_matrix = ...`, compute:

```python
        limit_up_screening = self._collect_limit_up_patterns(code, inputs)
```

Add to returned payload dict:

```python
            "limit_up_screening": limit_up_screening,
```

Keep `"limit_up_screening"` in `stub_tabs`; the frontend tab list already uses it.

- [ ] **Step 8: Run suite tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_stock_suite_limit_up.py tests/test_stock_analysis_suite.py -q
```

Expected: pass.

---

## Task 5: K-Line Payload Patterns

**Files:**
- Modify: `webui/services/kline_service.py`
- Create: `tests/test_kline_patterns_payload.py`

- [ ] **Step 1: Write failing K-line payload tests**

Create `tests/test_kline_patterns_payload.py`:

```python
from webui.services.kline_service import StockKlineService


class StubKlineService(StockKlineService):
    def __init__(self, records=None):
        super().__init__("unused")
        self.records = records or []

    def load_local_kline(self, stock_code, period, limit):
        return [], None

    def fetch_sina_kline(self, stock_code, period, limit):
        return self.records, ""


def _records_with_pattern():
    records = []
    close = 10.0
    for i in range(80):
        close *= 1.002
        records.append({"date": f"2026-01-{(i % 28) + 1:02d}", "open": close * 0.995, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1000 + i})
    for idx, row in enumerate(records):
        row["date"] = f"2026-{1 + idx // 28:02d}-{1 + idx % 28:02d}"
    prev = records[-1]["close"]
    zt = prev * 1.10
    records.append({"date": "2026-04-01", "open": prev * 1.02, "high": zt, "low": prev * 1.01, "close": zt, "volume": 6000, "pct_chg": 10.0})
    records.append({"date": "2026-04-02", "open": zt * 0.99, "high": zt, "low": zt * 0.96, "close": zt * 0.98, "volume": 2500})
    records.append({"date": "2026-04-03", "open": zt * 0.99, "high": zt * 1.02, "low": zt * 0.98, "close": zt * 1.01, "volume": 5200})
    return records


def test_get_payload_attaches_patterns():
    service = StubKlineService(_records_with_pattern())

    payload, error = service.get_payload("600000")

    assert error is None
    assert payload["available"] is True
    assert payload["patterns"]
    item = payload["patterns"][0]
    assert {"pattern", "name", "date", "anchor_date", "mark_dates", "strength", "tone", "rationale", "days_ago"} <= set(item)


def test_get_payload_patterns_degrade_to_empty(monkeypatch):
    service = StubKlineService(_records_with_pattern())

    def boom(*args, **kwargs):
        raise RuntimeError("detector offline")

    monkeypatch.setattr("webui.services.kline_service.detect_all", boom)
    payload, error = service.get_payload("600000")

    assert error is None
    assert payload["available"] is True
    assert payload["patterns"] == []
```

- [ ] **Step 2: Run K-line tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_kline_patterns_payload.py -q
```

Expected: no `patterns` key.

- [ ] **Step 3: Implement payload helper**

In `webui/services/kline_service.py`, add imports:

```python
from analysis.limit_up_patterns import bars_from_records, detect_all
```

Add private method on `StockKlineService`:

```python
    def _pattern_payload(self, records: list[dict[str, Any]], code: str, name: str = "") -> list[dict[str, Any]]:
        try:
            bars = bars_from_records(records)
            matches = detect_all(bars, code=code, name=name)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for m in matches[:12]:
            out.append({
                "pattern": m.get("pattern"),
                "name": m.get("name"),
                "date": m.get("trigger_date"),
                "anchor_date": m.get("anchor_date"),
                "mark_dates": m.get("mark_dates") or [],
                "strength": m.get("strength"),
                "tone": m.get("tone"),
                "rationale": m.get("rationale"),
                "days_ago": m.get("days_ago"),
            })
        return out
```

- [ ] **Step 4: Attach patterns in both success returns**

In the Sina success path:

```python
            name = (quote_block or {}).get('name') or ''
            return {
                'code': code,
                'name': name,
                ...
                'patterns': self._pattern_payload(sina_records, code, name),
            }, None
```

In the local success path, do the same:

```python
            name = (quote_block or {}).get('name') or ''
            return {
                'code': code,
                'name': name,
                ...
                'patterns': self._pattern_payload(local_records, code, name),
            }, None
```

Do not attach `patterns` to unavailable payloads unless a later test requires it.

- [ ] **Step 5: Run K-line tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_kline_patterns_payload.py tests/test_kline_service.py -q
```

Expected: pass.

---

## Task 6: Frontend K-Line Annotations

**Files:**
- Modify: `webui/static/kronos_desktop_app.js`

- [ ] **Step 1: Add pattern annotation helpers**

Near `buildKlineAutoDrawings`, add:

```javascript
      function patternToneColor(tone) {
        if (tone === "danger") return "rgba(196, 61, 54, 0.88)";
        if (tone === "warn") return "rgba(196, 126, 22, 0.88)";
        return "rgba(47, 111, 221, 0.82)";
      }

      function shortPatternName(name) {
        return String(name || "")
          .replace(/^涨停/, "")
          .replace("缩量回踩均线企稳", "回踩均线")
          .replace("回调倍量冲锋", "倍量冲锋")
          .slice(0, 6);
      }

      function buildPatternAnnotations(records, patterns, mode = "preview") {
        if (!records.length || !Array.isArray(patterns) || !patterns.length) return { shapes: [], annotations: [] };
        const byDate = new Map(records.map((r) => [String(r.date), r]));
        const visible = patterns
          .filter((p) => byDate.has(String(p.date || p.trigger_date || "")) || (p.mark_dates || []).some((d) => byDate.has(String(d))))
          .sort((a, b) => {
            const ar = a.tone === "danger" ? 0 : a.tone === "warn" ? 1 : 2;
            const br = b.tone === "danger" ? 0 : b.tone === "warn" ? 1 : 2;
            return (Number(a.days_ago ?? 999) - Number(b.days_ago ?? 999)) || (ar - br);
          })
          .slice(0, mode === "modal" ? 12 : 2);
        const shapes = [];
        const annotations = [];
        visible.forEach((p, idx) => {
          const date = String(p.date || p.trigger_date || "");
          const row = byDate.get(date);
          if (!row) return;
          const color = patternToneColor(p.tone);
          const high = Number(row.high);
          const y = Number.isFinite(high) ? high * (1.018 + idx * 0.012) : undefined;
          shapes.push({
            type: "rect",
            xref: "x",
            yref: "paper",
            x0: date,
            x1: date,
            y0: 0.28,
            y1: 1,
            fillcolor: color.replace("0.88", "0.10").replace("0.82", "0.10"),
            line: { width: 0 },
            layer: "below",
          });
          annotations.push({
            x: date,
            y,
            xref: "x",
            yref: "y",
            text: shortPatternName(p.name),
            showarrow: true,
            arrowhead: 2,
            arrowsize: 1,
            arrowwidth: 1.2,
            arrowcolor: color,
            ax: 0,
            ay: -26 - idx * 6,
            font: { size: mode === "modal" ? 11 : 10, color },
            bgcolor: "rgba(255,255,255,0.92)",
            bordercolor: color,
            borderwidth: 1,
          });
        });
        if (mode === "modal" && visible.length) {
          annotations.push({
            xref: "paper",
            yref: "paper",
            x: 1,
            y: 1.08,
            xanchor: "right",
            showarrow: false,
            text: `强势形态 ${visible.length} 个`,
            font: { size: 11, color: "#344256" },
            bgcolor: "rgba(255,255,255,0.86)",
            bordercolor: "rgba(47,111,221,0.25)",
            borderwidth: 1,
          });
        }
        return { shapes, annotations };
      }
```

- [ ] **Step 2: Merge pattern annotations into K-line layout**

In `buildKlineLayout`, after `autoDrawings`:

```javascript
        const patternDrawings = buildPatternAnnotations(records, data.patterns || [], mode);
```

Change:

```javascript
          shapes: autoDrawings.shapes,
```

to:

```javascript
          shapes: [...autoDrawings.shapes, ...patternDrawings.shapes],
```

Change annotations spread to:

```javascript
          }, ...autoDrawings.annotations, ...patternDrawings.annotations],
```

- [ ] **Step 3: Manual browser check**

Start the app/dev server using the project’s normal command. Open a stock with synthetic or real limit-up records and verify:

- Preview chart shows at most two pattern labels.
- Modal chart shows up to twelve pattern labels plus the legend note.
- Existing support/resistance lines still render.

No automated frontend test currently exists for Plotly layout generation.

---

## Task 7: Frontend Suite Panels

**Files:**
- Modify: `webui/static/kronos_desktop_app.js`

- [ ] **Step 1: Add stats formatting helpers**

Near `scoreTone`, add:

```javascript
      function formatPatternStat(row) {
        if (!row || row.count == null || row.count === 0) return "样本 0";
        const win = row.win_rate == null ? "—" : `${row.win_rate}%`;
        const avg = row.avg_return == null ? "—" : `${row.avg_return}%`;
        return `样本 ${row.count} · 胜率 ${win} · 均涨 ${avg}`;
      }

      function bestPatternWinRate(stats) {
        let best = null;
        Object.entries(stats?.horizons || {}).forEach(([horizon, row]) => {
          if (row?.win_rate == null || !row.count) return;
          if (!best || row.win_rate > best.win_rate) best = { horizon, win_rate: row.win_rate };
        });
        return best;
      }
```

- [ ] **Step 2: Render overview strong-pattern chips**

In `renderSuiteOverview`, before the radar section, build:

```javascript
        const strongPatterns = ov.strong_patterns || {};
        const strongHtml = (strongPatterns.items || []).length ? `
          <div class="suite-deep-signals" style="margin-bottom:14px;">
            ${(strongPatterns.items || []).map((p) => `
              <button type="button" class="suite-key-card tone-${html(p.tone || "neutral")}" data-jump-limit-up="1" style="text-align:left;cursor:pointer;">
                <div class="suite-key-label">${html(p.strength || "中")} · ${Number(p.days_ago || 0) === 0 ? "今日" : `${html(p.days_ago)}日前`}</div>
                <div class="suite-key-value" style="font-size:14px;">${html(p.name || "强势形态")}</div>
              </button>`).join("")}
          </div>` : "";
```

Insert `${strongHtml}` after `${buildComprehensiveSummary(payload)}`.

After `pane.innerHTML = ...`, bind jumps:

```javascript
        pane.querySelectorAll("[data-jump-limit-up]").forEach((btn) => {
          btn.addEventListener("click", () => {
            const tab = document.querySelector('#stockSuiteTabs button.suite-tab[data-suite-tab="limit_up_screening"]');
            if (tab) tab.click();
          });
        });
```

- [ ] **Step 3: Replace `renderSuiteLimitUpPane` body**

Keep the existing 4-factor calculation, but source the primary section from `payload.limit_up_screening`:

```javascript
        const section = payload.limit_up_screening || {};
        const matches = section.matches || [];
        const stats = section.pattern_stats || {};
        const summary = section.summary || {};
        const best = summary.best;
        const patternCards = matches.map((m) => {
          const stat = stats[m.pattern] || {};
          const horizons = stat.horizons || {};
          const horizonRows = ["5", "10", "20"].map((h) => `
            <div class="suite-price-row"><span>${h}日</span><span class="price">${html(formatPatternStat(horizons[h]))}</span></div>
          `).join("");
          return `
            <div class="suite-risk-col">
              <h4>${html(m.name || "强势形态")} <span class="score-pill">${html(m.strength || "中")}</span></h4>
              <div class="suite-price-row"><span>锚点</span><span class="price">${html(m.anchor_date || "—")}</span></div>
              <div class="suite-price-row"><span>触发</span><span class="price">${html(m.trigger_date || "—")}</span></div>
              <p class="suite-empty-note" style="margin:8px 0 10px;">${html(m.rationale || "")}</p>
              ${horizonRows}
              ${stat.sample_note ? `<p class="suite-empty-note" style="margin-top:8px;">${html(stat.sample_note)}</p>` : ""}
            </div>`;
        }).join("");
```

Render layout:

```javascript
        pane.innerHTML = `
          <div class="suite-radar-section">
            <div class="suite-dimension-summary">
              <h3 style="margin:0 0 8px;font-size:16px;color:var(--ink);">涨停强势形态识别</h3>
              <div class="suite-key-card tone-${matches.length ? "info" : "neutral"}" style="margin-bottom:12px;">
                <div class="suite-key-label">综合判定</div>
                <div class="suite-key-value" style="font-size:22px;">
                  ${matches.length ? `命中 ${matches.length} 个形态` : "近10日未识别到强势形态"}
                </div>
              </div>
              <div class="suite-key-card tone-${best ? "info" : "neutral"}" style="margin-bottom:12px;">
                <div class="suite-key-label">最佳历史胜率</div>
                <div class="suite-key-value" style="font-size:15px;">
                  ${best ? `${html(best.name)} · ${html(best.horizon)}日 ${html(best.win_rate)}%` : "样本不足"}
                </div>
              </div>
              ${section.reason ? `<p class="suite-empty-note">${html(section.reason)}</p>` : ""}
            </div>
            <div class="suite-key-signals">${factorHtml}</div>
          </div>
          <div class="suite-risk-grid" style="margin-top:14px;">
            ${patternCards || `<div class="suite-ai-empty"><p>近10日未识别到强势形态</p></div>`}
          </div>
        `;
```

Preserve the existing `factors`, `passCount`, `verdict`, and `factorHtml` code as the environment sub-block.

- [ ] **Step 4: Manual suite check**

Open an individual stock analysis suite payload that includes `limit_up_screening` and verify:

- Overview shows strong-pattern chips only when `overview.strong_patterns.items` is non-empty.
- Clicking a chip activates the `涨停筛选` tab.
- `涨停筛选` shows match cards and 5/10/20-day stats.
- Empty state is readable when no matches exist.

---

## Task 8: Final Verification

**Files:** all changed files.

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_limit_up_patterns.py tests/test_stock_suite_limit_up.py tests/test_kline_patterns_payload.py tests/test_stock_analysis_suite.py tests/test_kline_service.py -q
```

Expected: pass.

- [ ] **Step 2: Run syntax checks**

Run:

```bash
.venv/bin/python -m py_compile analysis/limit_up_patterns.py analysis/stock_analysis_suite.py webui/services/kline_service.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Start local app and verify UI**

Run the project’s normal WebUI command. If no command is already in use for this repo, use the existing Robyn entrypoint with local temp dirs:

```bash
KRONOS_USER_DIR=/private/tmp/kronos-webui-user KRONOS_RESULTS_DIR=/private/tmp/kronos-webui-user/results KRONOS_DATA_DIR=/private/tmp/kronos-webui-user/data KRONOS_DISABLE_TORCH=1 KRONOS_HOST=127.0.0.1 KRONOS_PORT=7088 ROBYN_PORT=7088 python webui/run_robyn.py
```

Verify in the app:

- K-line preview/modal still loads.
- Pattern annotations appear when payload `patterns` is non-empty.
- Individual stock suite overview and `涨停筛选` tab render without JS console errors.

- [ ] **Step 4: Check diff scope**

Run:

```bash
git diff -- analysis/limit_up_patterns.py analysis/stock_analysis_suite.py webui/services/kline_service.py webui/static/kronos_desktop_app.js tests/test_limit_up_patterns.py tests/test_stock_suite_limit_up.py tests/test_kline_patterns_payload.py
```

Expected: only the planned files changed; no template or route changes.

---

## Execution Notes

- The detector tests intentionally use synthetic OHLCV because real market data makes threshold tests brittle.
- Keep `limit_up_patterns.py` pure and deterministic. If any future whole-market scan uses it, it should not inherit WebUI state or network behavior.
- If suite payload performance becomes a concern, cache `backtest_all` within `_collect_limit_up_patterns` for the current bars; do not add global cache in this task.
- Do not make pattern detection mutually exclusive. Same bar, multiple pattern matches is expected.
