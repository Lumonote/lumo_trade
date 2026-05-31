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
        "history_days": None, "low_confidence": None, "confidence_note": None,
    }
    n = len(df) if df is not None else 0
    if df is not None:
        out["history_days"] = n
    if df is None or n < 35:  # 整体不可用：<35 给具体原因（E6/§6.7）
        if df is not None:
            out["confidence_note"] = f"历史仅 {n} 日（需 ≥35 日），技术指标暂不可用"
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
    if n < 60:  # 35–59：短历史降级，指标已算但标注低置信（E6/§6.7）
        out["low_confidence"] = True
        out["confidence_note"] = f"历史 {n} 日（<60），部分指标置信度低"
    else:
        out["low_confidence"] = False
    return out


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
    f["north_delta_30d"] = _num(hsgt.get("delta_30d_pct"))
    dt = mfd.get("dragon_tiger") or {}
    f["quant_seat_appearances"] = _num(dt.get("quant_seat_appearances"))
    f["lhb_net_inst_buy"] = _num(dt.get("net_inst_buy_30d"))

    f.update(_technical_features(inputs.get("ohlcv")))

    cc = sections.get("chip_control") or {}
    f["control_degree"] = _num(cc.get("control_degree"))
    ih = sections.get("institutional_holdings") or {}
    hn = ih.get("holder_number") or {}
    # 户数 QoQ 变化：<0 = 户数减少（筹码集中, 多）→ "down"，>0 → "up"，0 → "flat"
    qoq = _num(hn.get("pct_change_qoq"))
    if qoq is None:
        f["holder_number_trend"] = None
    elif qoq < 0:
        f["holder_number_trend"] = "down"
    elif qoq > 0:
        f["holder_number_trend"] = "up"
    else:
        f["holder_number_trend"] = "flat"
    # Phase 1: 基金持仓 provider 仅返回单期（latest period），无上一期数据，
    # 无法计算趋势——延后到后续阶段补齐上一期再派生 trend。
    f["fund_hold_trend"] = None

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
