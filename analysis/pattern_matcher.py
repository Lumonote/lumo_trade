"""Pattern matching engine for the canvas-based stock search feature.

Algorithm: pearson correlation (0.7) + slope match (0.3) on
30-point normalized close-price curves.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np

from analysis.pattern_store import Fingerprint, PatternStore

TARGET_LENGTH = 30
SLOPE_NORM = 0.05  # 归一化曲线上 30 日斜率经验上界
SHAPE_WEIGHT = 0.7
SLOPE_WEIGHT = 0.3


def normalize_curve(
    raw: Sequence[float],
    target_length: Optional[int] = None,
) -> Optional[List[float]]:
    """将任意长度的价格序列归一化到 [0,1]。

    - 当 ``target_length`` 显式传入时，按 x 轴等分采样到目标长度。
    - 不传 ``target_length`` 时保持输入原长度。
    - 停牌或全平输入（max == min）返回 None。
    """
    if not raw or len(raw) < 2:
        return None

    arr = np.asarray(raw, dtype=float)
    if not np.isfinite(arr).all():
        return None

    if target_length is not None and len(arr) != target_length:
        # 按 x 轴等分插值重采样
        x_src = np.linspace(0.0, 1.0, num=len(arr))
        x_dst = np.linspace(0.0, 1.0, num=target_length)
        arr = np.interp(x_dst, x_src, arr)

    span = float(arr.max() - arr.min())
    if span <= 1e-9:
        return None

    norm = (arr - arr.min()) / span
    return norm.tolist()


def linear_slope(curve: Sequence[float]) -> float:
    """归一化曲线的线性回归斜率（每点一个 x 单位）。"""
    arr = np.asarray(curve, dtype=float)
    n = len(arr)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    # slope = cov(x, y) / var(x)
    x_mean = x.mean()
    y_mean = arr.mean()
    denom = float(((x - x_mean) ** 2).sum())
    if denom <= 1e-12:
        return 0.0
    return float(((x - x_mean) * (arr - y_mean)).sum() / denom)


def comparison_window(
    curve: Sequence[float],
    max_days: int = TARGET_LENGTH,
    offset_days: int = 0,
) -> Optional[List[float]]:
    """截取用于相似度比较的窗口，并在窗口内重新归一化。

    ``max_days`` 表示最多比较多少个交易日；当 ``offset_days`` 为 1 时，
    参考曲线会向前回推一天，即排除最新一个点。
    """
    if not curve:
        return None

    values = []
    for item in curve:
        try:
            value = float(item)
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            values.append(value)
    if len(values) < 2:
        return None

    offset = max(0, int(offset_days or 0))
    if offset >= len(values) - 1:
        return None

    end = len(values) - offset
    window_len = max(2, min(int(max_days or TARGET_LENGTH), end))
    segment = values[end - window_len:end]
    return normalize_curve(segment)


def slope_norm_for_length(length: int) -> float:
    """短窗口的斜率天然更大，按窗口长度放宽斜率归一化尺度。"""
    if length <= 1:
        return SLOPE_NORM
    return max(SLOPE_NORM, 1.4 / float(length - 1))


def pearson_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Pearson 相关系数，输入长度不等返回 0。"""
    arr_a = np.asarray(a, dtype=float)
    arr_b = np.asarray(b, dtype=float)
    if arr_a.shape != arr_b.shape or arr_a.size < 2:
        return 0.0

    std_a = arr_a.std()
    std_b = arr_b.std()
    if std_a <= 1e-9 or std_b <= 1e-9:
        return 0.0

    return float(((arr_a - arr_a.mean()) * (arr_b - arr_b.mean())).mean() / (std_a * std_b))


def score_pair(
    user_curve: Sequence[float],
    user_slope: float,
    fp_curve: Sequence[float],
    fp_slope: float,
    slope_norm: float = SLOPE_NORM,
) -> dict:
    """计算单对曲线的相似度，返回 {score, shape_sim, slope_sim}。"""
    pearson_r = pearson_similarity(user_curve, fp_curve)
    shape_sim = max(0.0, pearson_r)  # 仅保留正相关
    slope_diff = abs(user_slope - fp_slope)
    slope_sim = max(0.0, 1.0 - slope_diff / max(slope_norm, 1e-9))
    score = SHAPE_WEIGHT * shape_sim + SLOPE_WEIGHT * slope_sim
    return {
        "score": round(score, 4),
        "shape_sim": round(shape_sim, 4),
        "slope_sim": round(slope_sim, 4),
    }


def _is_st_name(name: str) -> bool:
    if not name:
        return False
    n = name.upper().strip()
    return "ST" in n or "退" in name


def search_similar(
    store: "PatternStore",
    user_curve: Sequence[float],
    top_n: int = 30,
    markets: Optional[List[str]] = None,
    industry: Optional[str] = None,
    exclude_st: bool = True,
    window_days: int = TARGET_LENGTH,
    query_offset_days: int = 0,
) -> List[Dict]:
    """从指纹库检索与 user_curve 最相似的 Top-N 股票。"""
    query_curve = comparison_window(
        user_curve,
        max_days=window_days,
        offset_days=query_offset_days,
    )
    if query_curve is None or len(query_curve) < 2:
        return []

    actual_window_days = len(query_curve)
    user_slope = linear_slope(query_curve)
    slope_norm = slope_norm_for_length(actual_window_days)
    market_set = set(markets) if markets else None

    candidates: List[Dict] = []
    for fp in store.load_all_fingerprints():
        if market_set and fp.market not in market_set:
            continue
        if industry and fp.industry != industry:
            continue
        if exclude_st and _is_st_name(fp.stock_name):
            continue
        fp_window = comparison_window(
            fp.normalized_curve,
            max_days=actual_window_days,
            offset_days=0,
        )
        if fp_window is None:
            continue
        fp_slope = linear_slope(fp_window)
        breakdown = score_pair(
            query_curve,
            user_slope,
            fp_window,
            fp_slope,
            slope_norm=slope_norm,
        )
        if breakdown["score"] <= 0.0:
            continue
        candidates.append({
            "stock_code": fp.stock_code,
            "stock_name": fp.stock_name,
            "market": fp.market,
            "industry": fp.industry,
            "score": breakdown["score"],
            "shape_sim": breakdown["shape_sim"],
            "slope_sim": breakdown["slope_sim"],
            "latest_close": fp.latest_close,
            "latest_change_pct": fp.latest_change_pct,
            "mean_slope": fp_slope,
            "normalized_curve": fp.normalized_curve,
            "matched_curve": fp_window,
            "window_days": actual_window_days,
            "query_offset_days": max(0, int(query_offset_days or 0)),
            "snapshot_date": fp.snapshot_date.isoformat(),
        })

    candidates.sort(key=lambda row: row["score"], reverse=True)
    return candidates[:top_n]
