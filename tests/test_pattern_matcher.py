import datetime
import math
import numpy as np
import pytest

from analysis.pattern_matcher import (
    normalize_curve,
    linear_slope,
    pearson_similarity,
    score_pair,
    search_similar,
    SLOPE_NORM,
)
from analysis.pattern_store import Fingerprint, PatternStore


def test_normalize_curve_basic():
    raw = [10.0, 11.0, 12.0, 13.0, 14.0]
    norm = normalize_curve(raw)
    assert norm[0] == pytest.approx(0.0)
    assert norm[-1] == pytest.approx(1.0)
    assert len(norm) == len(raw)


def test_normalize_curve_constant_returns_none():
    """停牌期间所有价格相同，归一化无意义，返回 None。"""
    assert normalize_curve([10.0, 10.0, 10.0]) is None


def test_normalize_curve_resamples_to_target_length():
    """输入任意长度，按 x 等分采样到目标长度。"""
    raw = list(range(60))  # 60 个递增点
    norm = normalize_curve(raw, target_length=30)
    assert len(norm) == 30
    assert norm[0] == pytest.approx(0.0, abs=0.05)
    assert norm[-1] == pytest.approx(1.0, abs=0.05)


def test_linear_slope_increasing():
    """完全线性递增曲线，归一化后斜率约 1/(N-1)。"""
    norm = normalize_curve(list(range(30)))
    slope = linear_slope(norm)
    assert slope == pytest.approx(1.0 / 29, abs=0.005)


def test_linear_slope_flat_after_normalize_is_zero():
    norm = [0.5] * 30
    assert linear_slope(norm) == pytest.approx(0.0)


def test_linear_slope_decreasing():
    norm = normalize_curve(list(range(30, 0, -1)))
    slope = linear_slope(norm)
    assert slope < 0


def test_pearson_identical_curves():
    norm = normalize_curve(list(range(30)), target_length=30)
    assert pearson_similarity(norm, norm) == pytest.approx(1.0)


def test_pearson_opposite_curves():
    asc = normalize_curve(list(range(30)), target_length=30)
    desc = normalize_curve(list(range(30, 0, -1)), target_length=30)
    assert pearson_similarity(asc, desc) == pytest.approx(-1.0)


def test_pearson_zero_variance_returns_zero():
    flat = [0.5] * 30
    asc = normalize_curve(list(range(30)), target_length=30)
    assert pearson_similarity(asc, flat) == 0.0


def test_score_pair_identical_yields_one():
    user_curve = normalize_curve(list(range(30)), target_length=30)
    fp_curve = list(user_curve)
    user_slope = linear_slope(user_curve)
    fp_slope = user_slope
    breakdown = score_pair(user_curve, user_slope, fp_curve, fp_slope)
    assert breakdown["score"] == pytest.approx(1.0)
    assert breakdown["shape_sim"] == pytest.approx(1.0)
    assert breakdown["slope_sim"] == pytest.approx(1.0)


def test_score_pair_opposite_shape_yields_low():
    asc = normalize_curve(list(range(30)), target_length=30)
    desc = normalize_curve(list(range(30, 0, -1)), target_length=30)
    breakdown = score_pair(asc, linear_slope(asc), desc, linear_slope(desc))
    assert breakdown["score"] < 0.05  # 形态反向 + 斜率反向, 双零
    assert breakdown["shape_sim"] == 0.0  # 负相关被裁剪为 0


def test_score_pair_slope_diff_penalized():
    asc = normalize_curve(list(range(30)), target_length=30)
    # 同形态但人为构造差异较大的斜率
    breakdown = score_pair(
        asc, linear_slope(asc), asc, linear_slope(asc) + SLOPE_NORM * 2
    )
    assert breakdown["slope_sim"] == 0.0
    # 形态完全一致 → 0.7 * 1 + 0.3 * 0 = 0.7
    assert breakdown["score"] == pytest.approx(0.7)


def _fp(code: str, name: str, market: str, curve: list, slope: float) -> Fingerprint:
    return Fingerprint(
        stock_code=code,
        stock_name=name,
        market=market,
        industry="测试行业",
        normalized_curve=curve,
        mean_slope=slope,
        latest_close=10.0,
        latest_change_pct=1.0,
        snapshot_date=datetime.date(2026, 5, 17),
    )


def test_search_returns_sorted_top_n(tmp_db):
    store = PatternStore(tmp_db)
    store.init_schema()
    asc = normalize_curve(list(range(30)), target_length=30)
    desc = normalize_curve(list(range(30, 0, -1)), target_length=30)
    asc_slope = linear_slope(asc)
    desc_slope = linear_slope(desc)
    store.upsert_fingerprints([
        _fp("AAA", "上涨股", "SH", asc, asc_slope),
        _fp("BBB", "下跌股", "SZ", desc, desc_slope),
    ])
    results = search_similar(store, user_curve=asc, top_n=10)
    assert len(results) >= 1
    assert results[0]["stock_code"] == "AAA"
    assert results[0]["score"] == pytest.approx(1.0)


def test_search_filters_st_stocks(tmp_db):
    store = PatternStore(tmp_db)
    store.init_schema()
    asc = normalize_curve(list(range(30)), target_length=30)
    slope = linear_slope(asc)
    store.upsert_fingerprints([
        _fp("AAA", "上涨股", "SH", asc, slope),
        _fp("BBB", "ST退市", "SH", asc, slope),
        _fp("CCC", "*ST警告", "SH", asc, slope),
        _fp("DDD", "中弘退", "SZ", asc, slope),
    ])
    results = search_similar(store, user_curve=asc, top_n=10, exclude_st=True)
    codes = {row["stock_code"] for row in results}
    assert "AAA" in codes
    assert "BBB" not in codes
    assert "CCC" not in codes
    assert "DDD" not in codes


def test_search_market_filter(tmp_db):
    store = PatternStore(tmp_db)
    store.init_schema()
    asc = normalize_curve(list(range(30)), target_length=30)
    slope = linear_slope(asc)
    store.upsert_fingerprints([
        _fp("600001", "沪市", "SH", asc, slope),
        _fp("000001", "深市", "SZ", asc, slope),
    ])
    results = search_similar(
        store, user_curve=asc, top_n=10, markets=["SZ"]
    )
    codes = {row["stock_code"] for row in results}
    assert codes == {"000001"}


def test_search_top_n_limit(tmp_db):
    store = PatternStore(tmp_db)
    store.init_schema()
    asc = normalize_curve(list(range(30)), target_length=30)
    slope = linear_slope(asc)
    fps = [_fp(f"{i:06d}", f"股{i}", "SH", asc, slope) for i in range(50)]
    store.upsert_fingerprints(fps)
    results = search_similar(store, user_curve=asc, top_n=10)
    assert len(results) == 10
