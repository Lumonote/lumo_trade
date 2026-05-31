"""★回测胜率指标（Phase 3）：个股「当前形态」的历史 N 日前向胜率。

纯 OHLCV、无前视：遍历历史交易日，按其均线排列（多头/空头/交织）分桶，统计该桶 N 日后
收盘价上涨的比例；取「当前形态」对应桶的胜率作为指标。条件样本不足时回退全样本基准率并
标注低置信。统计的是「过去出现该形态后、N 日内上涨的频率」——所有用到的 K 线都早于或等于
当下，对当下决策无未来信息泄漏（look-ahead-free）。

复用 `analysis.technical_analysis.TechnicalAnalysis` 的均线，与 panel features 同源（DRY）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from analysis.technical_analysis import TechnicalAnalysis as TA


def _f(series: Any, i: int) -> Optional[float]:
    """series.iloc[i] → float；越界/NaN/不可转 → None。"""
    try:
        v = float(series.iloc[i])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return None if v != v else v  # NaN 过滤


def _ma_state(ma5: Optional[float], ma10: Optional[float], ma20: Optional[float]) -> Optional[str]:
    """均线排列形态：多头(bull)/空头(bear)/交织(mixed)；任一均线缺失 → None。"""
    if None in (ma5, ma10, ma20):
        return None
    if ma5 > ma10 > ma20:
        return "bull"
    if ma5 < ma10 < ma20:
        return "bear"
    return "mixed"


def compute_backtest_winrate(
    df: Optional[pd.DataFrame],
    *,
    horizon: int = 5,
    lookback: int = 250,
    min_sample: int = 20,
) -> Optional[Dict[str, Any]]:
    """计算当前均线形态的历史 N 日前向胜率。

    Args:
        df: 个股 OHLCV（含 ``close`` 列），按时间升序。
        horizon: 前向持有交易日数（默认 5）。
        lookback: 回溯统计的最大历史交易日数（默认 250 ≈ 一年）。
        min_sample: 「当前形态」桶达到该样本量才用条件胜率，否则回退基准率。

    Returns:
        ``{winrate, sample, horizon, state, base_rate, base_sample, confident}``；
        数据不足（<60 行或无有效前向样本）→ None。``winrate`` ∈ [0,1]。
    """
    if df is None or "close" not in getattr(df, "columns", []) or len(df) < 60:
        return None
    close = df["close"].reset_index(drop=True)
    n = len(close)
    ma5 = TA.calculate_ma(close, 5)
    ma10 = TA.calculate_ma(close, 10)
    ma20 = TA.calculate_ma(close, 20)

    cur_state = _ma_state(_f(ma5, n - 1), _f(ma10, n - 1), _f(ma20, n - 1))

    start = max(0, n - horizon - lookback)
    end = n - horizon  # 需 i+horizon <= n-1
    wins = total = 0
    state_wins = state_total = 0
    for i in range(start, end):
        c0 = _f(close, i)
        cN = _f(close, i + horizon)
        if c0 is None or cN is None or c0 <= 0:
            continue
        up = cN > c0
        total += 1
        wins += 1 if up else 0
        if cur_state is not None and _ma_state(_f(ma5, i), _f(ma10, i), _f(ma20, i)) == cur_state:
            state_total += 1
            state_wins += 1 if up else 0

    if total == 0:
        return None
    base_rate = wins / total
    if cur_state is not None and state_total >= min_sample:
        return {
            "winrate": state_wins / state_total, "sample": state_total,
            "horizon": horizon, "state": cur_state,
            "base_rate": base_rate, "base_sample": total, "confident": True,
        }
    return {
        "winrate": base_rate, "sample": total, "horizon": horizon,
        "state": cur_state, "base_rate": base_rate, "base_sample": total,
        "confident": False,
    }
