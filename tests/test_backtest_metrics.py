# tests/test_backtest_metrics.py
"""analysis/backtest_metrics.py：回测年化口径(报告与健康页共用的唯一实现)。

核心断言:跨报告日必须几何链乘复利,不能先取算术均值再一次性 ^50.4
(Jensen 不等式下算术口径系统性高估)。
"""
from __future__ import annotations

import math

import pytest

from analysis.backtest_metrics import (
    ANNUAL_CYCLES,
    annualize_chained,
    annualize_cycle_return,
)


def test_annual_cycles_is_252_over_5():
    assert ANNUAL_CYCLES == pytest.approx(252 / 5)


def test_single_cycle_return_compounds_50_4_times():
    assert annualize_cycle_return(1.0) == pytest.approx(((1.01 ** ANNUAL_CYCLES) - 1) * 100, abs=1e-2)


def test_single_cycle_none_and_total_loss_return_none():
    assert annualize_cycle_return(None) is None
    assert annualize_cycle_return(float("nan")) is None
    assert annualize_cycle_return(-100.0) is None
    assert annualize_cycle_return("bad") is None


def test_chained_uses_geometric_not_arithmetic_mean():
    """+10% 与 -10% 交替:算术均值为 0(年化 0%),几何链乘为负。"""
    returns = [10.0, -10.0] * 5
    arithmetic = annualize_cycle_return(sum(returns) / len(returns))
    chained = annualize_chained(returns)

    assert arithmetic == pytest.approx(0.0, abs=1e-6)
    assert chained is not None and chained < -20.0

    growth = math.prod(1 + r / 100 for r in returns) ** (ANNUAL_CYCLES / len(returns))
    assert chained == pytest.approx((growth - 1) * 100, abs=1e-2)


def test_chained_single_value_matches_single_cycle_helper():
    assert annualize_chained([2.5]) == pytest.approx(annualize_cycle_return(2.5))


def test_chained_skips_none_entries_without_shifting_weights():
    assert annualize_chained([3.0, None, 3.0]) == pytest.approx(annualize_chained([3.0, 3.0]))


def test_chained_weights_by_sample_count():
    """1 只样本的天不应与 10 只样本的天等权。"""
    equal = annualize_chained([10.0, -10.0])
    weighted = annualize_chained([10.0, -10.0], [1, 10])

    assert equal is not None and weighted is not None
    assert weighted < equal  # -10% 那天样本多 → 拉低
    log_g = (1 * math.log(1.10) + 10 * math.log(0.90)) / 11
    assert weighted == pytest.approx((math.exp(log_g * ANNUAL_CYCLES) - 1) * 100, abs=1e-2)


def test_chained_ignores_zero_weight_days():
    assert annualize_chained([5.0, -8.0], [3, 0]) == pytest.approx(annualize_chained([5.0]))


def test_chained_empty_and_wipeout_return_none():
    assert annualize_chained([]) is None
    assert annualize_chained([None, None]) is None
    assert annualize_chained([5.0, -100.0]) is None
