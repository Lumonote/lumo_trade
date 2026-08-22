"""回测收益年化的唯一口径实现(报告「历史回测表现」与桌面「报告与健康」共用)。

规则:

1. **同一报告日**的多只推荐是同时建仓的等权组合 → 当日组合的 5 日持仓收益 =
   当日各样本 5 日收益的算术均值(算术均值正是等权组合收益,这一步没有偏差);
2. **跨报告日**是时间序列 → 必须几何链乘(复利),不能再取算术均值;
3. 年化 = 每周期等效增长因子 ^ (252/5)。

旧实现把跨日的 5 日收益直接取算术均值再一次性 ``(1+r)^50.4``,在 Jensen 不等式
下系统性高估复利结果(波动越大高估越多)。样本数不同的报告日按可评估样本数加权,
避免只有 1 只可评估的日子与 10 只的日子等权。

注意:报告每个交易日出一批,相邻两日的 5 日持仓重叠 4 天,年化按 50.4 次顺序独立
周期折算仍是**估算**;本模块只保证复利与加权这两步不出错,不消除重叠。
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

ANNUAL_TRADING_DAYS = 252.0
HOLDING_TRADE_DAYS = 5.0
ANNUAL_CYCLES = ANNUAL_TRADING_DAYS / HOLDING_TRADE_DAYS  # ≈50.4 次/年


def _growth_factor(value) -> float | None:
    """5 日收益(百分数)→ 增长因子 1+r;非数值/NaN/本金归零一律 None。"""
    if value is None:
        return None
    try:
        ret = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(ret) or math.isinf(ret):
        return None
    factor = 1.0 + ret / 100.0
    return factor if factor > 0 else None


def annualize_chained(returns_pct: Iterable, weights: Sequence | None = None) -> float | None:
    """一串按时间先后排列的 5 日持仓收益(百分数)→ 加权几何链乘年化(百分数)。

    Args:
        returns_pct: 每个报告日的组合 5 日收益;None/NaN 条目直接跳过(该日无可评估样本)。
        weights: 与 ``returns_pct`` 等长的权重(通常是当日可评估样本数);
            省略则等权。权重 <=0 的条目跳过。

    Returns:
        年化收益百分数(保留两位);无有效条目或期间本金归零时返回 None。
    """
    values = list(returns_pct)
    weight_list = list(weights) if weights is not None else [1.0] * len(values)

    log_sum = 0.0
    weight_sum = 0.0
    for index, value in enumerate(values):
        factor = _growth_factor(value)
        if factor is None:
            # 收益缺失 → 跳过;本金归零 → 几何均值无定义,整体不出数
            if value is not None and _is_wipeout(value):
                return None
            continue
        try:
            weight = float(weight_list[index]) if index < len(weight_list) else 1.0
        except (TypeError, ValueError):
            weight = 1.0
        if weight <= 0:
            continue
        log_sum += weight * math.log(factor)
        weight_sum += weight

    if weight_sum <= 0:
        return None
    per_cycle_growth = math.exp(log_sum / weight_sum)
    return round((per_cycle_growth ** ANNUAL_CYCLES - 1) * 100, 2)


def _is_wipeout(value) -> bool:
    """收益 <= -100%(本金归零/穿仓),几何链乘无定义。"""
    try:
        ret = float(value)
    except (TypeError, ValueError):
        return False
    return not math.isnan(ret) and ret <= -100.0


def annualize_cycle_return(value) -> float | None:
    """单个 5 日持仓收益(百分数)→ 年化(百分数)。等价于只有一个周期的链乘。"""
    return annualize_chained([value])
