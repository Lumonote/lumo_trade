"""Rule-based strong limit-up pattern detection.

This module is intentionally pure: no network, no filesystem, no app state.
It is shared by the stock analysis suite and the K-line payload service.
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

_STRENGTH_RANK = {"强": 0, "中": 1}
_DIRECTION_RANK = {"bearish": 0, "bullish": 1}


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
        return out if math.isfinite(out) else default
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
    for bar in bars:
        if bar["pct_chg"] is None:
            bar["pct_chg"] = (bar["close"] / prev_close - 1.0) * 100.0 if prev_close else 0.0
        prev_close = bar["close"]
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


def _sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        out.append(total / window if i >= window - 1 else None)
    return out


def _prev_avg(values: list[float], index: int, window: int = 5) -> float | None:
    start = max(0, index - window)
    chunk = values[start:index]
    if not chunk:
        return None
    return sum(chunk) / len(chunk)


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


def _make_match(
    e: dict[str, Any],
    pattern: str,
    name: str,
    anchor: int,
    trigger: int,
    strength: str,
    tone: str,
    rationale: str,
    mark_indexes: list[int] | None = None,
) -> dict[str, Any]:
    bars = e["bars"]
    indexes = mark_indexes or [anchor, trigger]
    mark_dates = []
    for idx in indexes:
        if 0 <= idx < len(bars):
            date = bars[idx]["date"]
            if date not in mark_dates:
                mark_dates.append(date)
    return {
        "pattern": pattern,
        "name": name,
        "anchor_date": bars[anchor]["date"],
        "trigger_date": bars[trigger]["date"],
        "anchor_index": anchor,
        "trigger_index": trigger,
        "mark_dates": mark_dates,
        "strength": strength,
        "tone": tone,
        "rationale": rationale,
        "days_ago": max(0, len(bars) - 1 - trigger),
        "direction": "bearish" if pattern.startswith("bear_") else "bullish",
    }


def _body_pct(e: dict[str, Any], index: int) -> float:
    close = e["closes"][index]
    return abs(close - e["opens"][index]) / close if close else 0.0


def detect_zt_pullback_double_volume(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    n = len(e["bars"])
    for i in range(n - 2):
        if not e["is_zt"][i]:
            continue
        for j in range(i + 2, min(n, i + PULLBACK_MAX_DAYS + 2)):
            pull = list(range(i + 1, j))
            if not pull:
                continue
            mean_pull_vol = sum(e["vols"][p] for p in pull) / len(pull)
            low_ok = min(e["lows"][p] for p in pull) >= e["lows"][i] * 0.995
            ma_ok = all(e["ma5"][p] is None or e["lows"][p] >= e["ma5"][p] * 0.985 for p in pull)
            trigger_ok = (
                e["vols"][j] >= DOUBLE_VOL_RATIO * max(e["vols"][j - 1], 1.0)
                and e["closes"][j] > e["opens"][j]
                and e["closes"][j] > e["closes"][j - 1]
            )
            if mean_pull_vol < SHRINK_VOL_RATIO * e["vols"][i] and low_ok and ma_ok and trigger_ok:
                out.append(_make_match(
                    e, "zt_pullback_double_volume", "涨停回调倍量冲锋", i, j, "强", "danger",
                    f"涨停后缩量回调{len(pull)}日，今日量能放大重新上攻",
                ))
    return out


def detect_zt_beauty_shoulder(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    n = len(e["bars"])
    for i in range(n - 3):
        if not e["is_zt"][i]:
            continue
        for j in range(i + 3, min(n, i + SHOULDER_MAX_DAYS + 1)):
            seg = list(range(i + 1, j + 1))
            drawdown = 1.0 - min(e["lows"][p] for p in seg) / max(e["closes"][i], 1.0)
            ma_ok = all(e["ma10"][p] is None or e["closes"][p] >= e["ma10"][p] * 0.99 for p in seg)
            vol_down = all(e["vols"][seg[k]] <= e["vols"][seg[k - 1]] * 1.05 for k in range(1, len(seg)))
            no_big_yin = all(not (e["closes"][p] < e["opens"][p] and _body_pct(e, p) >= 0.03) for p in seg)
            turn = e["closes"][j] > e["closes"][j - 1] and e["closes"][j] > e["opens"][j]
            if drawdown <= SHOULDER_MAX_DRAWDOWN and ma_ok and vol_down and no_big_yin and turn:
                out.append(_make_match(e, "zt_beauty_shoulder", "涨停美人肩", i, j, "中", "warn", "涨停后温和缩量回调，阳线拐头企稳"))
    return out


def detect_zt_high_volume_hold(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    n = len(e["bars"])
    for i in range(n - 2):
        prev_avg = _prev_avg(e["vols"], i)
        if not e["is_zt"][i] or not prev_avg or e["vols"][i] < HUGE_VOL_RATIO * prev_avg:
            continue
        for j in range(i + 2, min(n, i + HOLD_MAX_DAYS + 1)):
            held = min(e["lows"][p] for p in range(i + 1, j + 1)) >= e["lows"][i] * 0.995
            if not held:
                break
            strength = "强" if e["closes"][j] >= e["closes"][i] else "中"
            out.append(_make_match(e, "zt_high_volume_hold", "涨停高量不破", i, j, strength, "danger", "涨停高量柱后回踩未破关键低点"))
    return out


def detect_zt_volume_over_left_peak(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i in range(len(e["bars"])):
        if not e["is_zt"][i] or i < 4:
            continue
        start = max(0, i - LEFT_PEAK_LOOKBACK)
        left = e["vols"][start:max(start, i - 2)]
        if left and e["vols"][i] > max(left):
            out.append(_make_match(e, "zt_volume_over_left_peak", "涨停量过左峰", i, i, "强", "danger", "涨停量能超过左侧峰值量"))
    return out


def detect_zt_huge_yin_rewrap(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    n = len(e["bars"])
    for y in range(1, n - 1):
        prev_strong = e["is_zt"][y - 1] or (e["closes"][y - 1] > e["opens"][y - 1] and (e["pct"][y - 1] or 0) >= 6.0)
        vol_avg = _prev_avg(e["vols"], y)
        huge_yin = e["closes"][y] < e["opens"][y] and vol_avg and e["vols"][y] >= HUGE_VOL_RATIO * vol_avg
        if not prev_strong or not huge_yin:
            continue
        for r in range(y + 1, min(n, y + 3)):
            if e["closes"][r] > e["opens"][y] and e["closes"][r] > e["opens"][r]:
                strength = "强" if e["closes"][r] > e["highs"][y] else "中"
                out.append(_make_match(e, "zt_huge_yin_rewrap", "涨停巨量阴反包", y, r, strength, "danger", "巨量阴线后快速阳线反包"))
    return out


def detect_zt_board_then_bull_cannon(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    n = len(e["bars"])
    for d3 in range(2, n):
        d1, d2 = d3 - 2, d3 - 1
        has_board = any(e["is_zt"][p] for p in range(max(0, d1 - 1), d1 + 1))
        if not has_board:
            continue
        day1_yang = e["closes"][d1] > e["opens"][d1]
        day2_small_yin = e["closes"][d2] < e["opens"][d2] and _body_pct(e, d2) <= 0.035
        day2_in_range = e["lows"][d2] >= e["lows"][d1] * 0.99 and e["highs"][d2] <= e["highs"][d1] * 1.02
        day3_yang = e["closes"][d3] > e["opens"][d3] and e["closes"][d3] >= e["closes"][d1]
        if day1_yang and day2_small_yin and day2_in_range and day3_yang:
            anchor = d1 if e["is_zt"][d1] else d1 - 1
            out.append(_make_match(e, "zt_board_then_bull_cannon", "先板后多方炮", anchor, d3, "中", "warn", "涨停后出现阳-小阴-阳多方炮结构", [anchor, d1, d2, d3]))
    return out


def detect_zt_n_shape_relay(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    n = len(e["bars"])
    for i in range(n - 3):
        if not e["is_zt"][i]:
            continue
        for j in range(i + 2, min(n, i + 5)):
            pull = list(range(i + 1, j))
            if not pull:
                continue
            vol_shrink = all(e["vols"][p] <= e["vols"][i] * SHRINK_VOL_RATIO for p in pull)
            ma_hold = all(e["ma5"][p] is None or e["lows"][p] >= e["ma5"][p] * 0.985 for p in pull)
            breaks = e["closes"][j] > max(e["highs"][p] for p in pull) or e["is_zt"][j]
            if vol_shrink and ma_hold and breaks:
                out.append(_make_match(e, "zt_n_shape_relay", "涨停N字接力", i, j, "中", "warn", "涨停后缩量回踩并突破回调高点"))
    return out


def detect_zt_consecutive_boards(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    run = 0
    start = 0
    for i, flag in enumerate(e["is_zt"]):
        if flag:
            if run == 0:
                start = i
            run += 1
            if run >= 2:
                strength = "强" if run >= 3 else "中"
                out.append(_make_match(e, "zt_consecutive_boards", "连板加速", start, i, strength, "danger", f"连续{run}日涨停加速"))
        else:
            run = 0
    return out


def detect_zt_platform_breakout(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    n = len(e["bars"])
    for i in range(n - PLATFORM_MIN_DAYS - 1):
        if not e["is_zt"][i]:
            continue
        for j in range(i + PLATFORM_MIN_DAYS + 1, min(n, i + PLATFORM_MAX_DAYS + 2)):
            platform = list(range(i + 1, j))
            mean_close = sum(e["closes"][p] for p in platform) / len(platform)
            range_ok = (max(e["highs"][p] for p in platform) - min(e["lows"][p] for p in platform)) / mean_close <= PLATFORM_RANGE
            ma_ok = all(e["ma20"][p] is None or e["lows"][p] >= e["ma20"][p] * 0.985 for p in platform)
            avg_vol = sum(e["vols"][p] for p in platform) / len(platform)
            breakout = e["closes"][j] > max(e["highs"][p] for p in platform) and e["vols"][j] >= 1.3 * avg_vol
            if range_ok and ma_ok and breakout:
                out.append(_make_match(e, "zt_platform_breakout", "涨停平台突破", i, j, "中", "warn", "涨停后窄幅平台整理并放量突破"))
    return out


def detect_zt_ma_pullback_hold(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    n = len(e["bars"])
    for i in range(n - 2):
        if not e["is_zt"][i]:
            continue
        for j in range(i + 1, min(n, i + PULLBACK_MAX_DAYS + 2)):
            candidates = [ma for ma in (e["ma5"][j], e["ma10"][j]) if ma is not None]
            if not candidates:
                continue
            touched = any(e["lows"][j] <= ma * 1.015 and e["lows"][j] >= ma * 0.985 for ma in candidates)
            shrunk = e["vols"][j] <= e["vols"][i] * SHRINK_VOL_RATIO
            held = any(e["closes"][j] >= ma for ma in candidates) and e["closes"][j] > e["opens"][j]
            if touched and shrunk and held:
                out.append(_make_match(e, "zt_ma_pullback_hold", "缩量回踩均线企稳", i, j, "中", "info", "涨停后缩量回踩均线并阳线企稳"))
    return out


def detect_bear_ma_breakdown(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i in range(21, len(e["bars"])):
        ma20 = e["ma20"][i]
        prev_ma20 = e["ma20"][i - 1]
        vol_avg = _prev_avg(e["vols"], i)
        if ma20 is None or prev_ma20 is None or not vol_avg:
            continue
        prev_above = e["closes"][i - 1] >= prev_ma20
        breaks = e["closes"][i] < ma20 * 0.99 and e["closes"][i] < e["opens"][i]
        vol_heavy = e["vols"][i] >= 1.4 * vol_avg
        pct_drop = (e["pct"][i] or 0) <= -3.0
        if prev_above and breaks and (vol_heavy or pct_drop):
            out.append(_make_match(
                e, "bear_ma_breakdown", "放量跌破均线", i - 1, i, "强", "bear",
                "放量阴线跌破MA20，短线趋势转弱",
            ))
    return out


def detect_bear_long_upper_shadow(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i in range(5, len(e["bars"])):
        high = e["highs"][i]
        close = e["closes"][i]
        open_ = e["opens"][i]
        low = e["lows"][i]
        if close <= 0:
            continue
        upper = high - max(open_, close)
        whole = max(high - low, close * 0.001)
        vol_avg = _prev_avg(e["vols"], i)
        near_high_area = high >= max(e["highs"][max(0, i - 40):i]) * 0.98
        long_upper = upper / whole >= 0.45 and upper / close >= 0.045
        weak_close = close <= open_ * 1.005
        vol_heavy = bool(vol_avg and e["vols"][i] >= 1.5 * vol_avg)
        if near_high_area and long_upper and weak_close and vol_heavy:
            out.append(_make_match(
                e, "bear_long_upper_shadow", "放量长上影", i, i, "中", "bear",
                "高位放量长上影，冲高回落抛压增强",
            ))
    return out


def detect_bear_large_yin_break(e: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i in range(10, len(e["bars"])):
        vol_avg = _prev_avg(e["vols"], i)
        ma5 = e["ma5"][i]
        ma10 = e["ma10"][i]
        if not vol_avg or ma5 is None or ma10 is None:
            continue
        large_yin = e["closes"][i] < e["opens"][i] and (e["pct"][i] or 0) <= -4.0
        breaks_short_ma = e["closes"][i] < ma5 * 0.99 and e["closes"][i] < ma10 * 0.995
        vol_heavy = e["vols"][i] >= 1.6 * vol_avg
        if large_yin and breaks_short_ma and vol_heavy:
            out.append(_make_match(
                e, "bear_large_yin_break", "放量大阴破位", i, i, "强", "bear",
                "放量大阴线跌破短期均线，破位风险升高",
            ))
    return out


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

BEARISH_PATTERNS = [
    PatternDef("bear_ma_breakdown", "放量跌破均线", detect_bear_ma_breakdown, "bear"),
    PatternDef("bear_long_upper_shadow", "放量长上影", detect_bear_long_upper_shadow, "bear"),
    PatternDef("bear_large_yin_break", "放量大阴破位", detect_bear_large_yin_break, "bear"),
]


def detect_all(
    bars: list[dict[str, Any]],
    code: str | None = None,
    name: str | None = None,
    *,
    recent_days: int | None = None,
) -> list[dict[str, Any]]:
    enriched = _enrich(bars, code, name)
    seen: set[tuple[str, str]] = set()
    matches: list[dict[str, Any]] = []
    for pattern_def in PATTERNS:
        for match in pattern_def.detector(enriched):
            key = (str(match.get("pattern")), str(match.get("trigger_date")))
            if key in seen:
                continue
            seen.add(key)
            if recent_days is not None and int(match.get("days_ago", 0)) > recent_days:
                continue
            matches.append(match)
    matches.sort(key=lambda m: (int(m.get("days_ago", 0)), _STRENGTH_RANK.get(str(m.get("strength")), 9)))
    return matches


def detect_kline_patterns(
    bars: list[dict[str, Any]],
    code: str | None = None,
    name: str | None = None,
    *,
    recent_days: int | None = None,
) -> list[dict[str, Any]]:
    enriched = _enrich(bars, code, name)
    seen: set[tuple[str, str]] = set()
    matches: list[dict[str, Any]] = []
    for pattern_def in [*PATTERNS, *BEARISH_PATTERNS]:
        for match in pattern_def.detector(enriched):
            key = (str(match.get("pattern")), str(match.get("trigger_date")))
            if key in seen:
                continue
            seen.add(key)
            if recent_days is not None and int(match.get("days_ago", 0)) > recent_days:
                continue
            matches.append(match)
    matches.sort(key=lambda m: (
        int(m.get("days_ago", 0)),
        _DIRECTION_RANK.get(str(m.get("direction")), 9),
        _STRENGTH_RANK.get(str(m.get("strength")), 9),
    ))
    return matches


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
    enriched = _enrich(clean, code, None)
    matches = pattern_def.detector(enriched)
    matches.sort(key=lambda m: int(m["trigger_index"]))
    selected = []
    last_trigger = -10_000
    for match in matches:
        idx = int(match["trigger_index"])
        if idx - last_trigger >= min_gap_days:
            selected.append(match)
            last_trigger = idx

    closes = [b["close"] for b in clean]
    returns_by_horizon: dict[str, list[float]] = {str(h): [] for h in horizons}
    for match in selected:
        idx = int(match["trigger_index"])
        if idx >= len(closes) or closes[idx] <= 0:
            continue
        for horizon in horizons:
            if idx + horizon < len(closes):
                returns_by_horizon[str(horizon)].append(closes[idx + horizon] / closes[idx] - 1.0)

    horizon_stats = {key: _summarize_returns(values) for key, values in returns_by_horizon.items()}
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
        pattern_def.key: backtest_pattern_on_history(
            bars,
            pattern_def.key,
            code=code,
            horizons=horizons,
            min_gap_days=min_gap_days,
        )
        for pattern_def in PATTERNS
    }
