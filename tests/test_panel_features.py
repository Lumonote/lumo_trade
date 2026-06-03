import numpy as np
import pandas as pd

from analysis.panel.features import extract_features


def _ohlcv(n=80):
    rng = np.random.default_rng(1)
    close = pd.Series(10 + rng.normal(0, 0.2, n).cumsum() * 0.1)
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": pd.Series(rng.integers(1e6, 5e6, n).astype(float)),
        "amount": close * 1e6,
    })


def _inputs():
    return {
        "ohlcv": _ohlcv(80),
        "capital_flow": {"details": {
            "order_analysis": {"main_net_inflow": 1.2e8, "super_large_net": 8e7,
                               "retail_net_inflow": -3e7},
            "positive_days_5d": 3}},
        "fundamental": {"pe": 18.0, "pb": 2.1, "roe": 22.0,
                        "pe_industry_rank": 28.0, "net_profit_yoy": 35.0},
        "market_regime": "bull",
    }


def _sections():
    return {
        "main_force_deep": {"data_status": "fresh",
            "dragon_tiger": {"quant_seat_appearances": 2, "net_inst_buy_30d": 5e7},
            "hsgt": {"latest": {"hold_ratio": 4.1}, "delta_30d_pct": 0.6}},
        "chip_control": {"data_status": "fresh", "control_degree": 72},
        "institutional_holdings": {"data_status": "stale",
            "holder_number": {"latest_num": 50000, "pct_change_qoq": -3.2,
                "history": [{"end_date": "2025-12-31", "holder_num": 56000, "pct_change": 0.0},
                            {"end_date": "2026-03-31", "holder_num": 50000, "pct_change": -3.2}]},
            "fund_holds": {"period": "2026-03-31",
                "rows": [{"fund_name": "易方达蓝筹", "nv_ratio": 3.4}], "total_nv_pct": 3.4}},
        "quant_matrix": {"data_status": "fresh",
            "multi_period_resonance": {"bull": 18, "bear": 6, "neutral": 6}},
    }


def test_extract_features_fundamental_and_capital():
    f = extract_features(_inputs(), _sections())
    assert f["roe"] == 22.0
    assert f["pe_industry_rank"] == 28.0
    assert f["main_net_inflow"] == 1.2e8
    assert f["super_large_net"] == 8e7


def test_extract_features_sections_and_model_ratio():
    f = extract_features(_inputs(), _sections())
    assert f["quant_seat_appearances"] == 2
    assert f["north_delta_30d"] == 0.6
    assert f["control_degree"] == 72
    assert f["model_total"] == 30
    assert abs(f["model_bull_ratio"] - 0.6) < 1e-6
    assert f["lhb_net_inst_buy"] == 5e7
    assert f["holder_number_trend"] == "down"   # 户数减少 = 筹码集中
    assert f["fund_hold_trend"] is None          # Phase 1: fund provider exposes no prior period
    assert f["fund_hold_count"] == 1             # 单期重仓家数（来自 fund_holds.rows）
    assert f["fund_hold_mv"] is None             # 该 fixture 行无 market_value → None


def test_extract_features_technical_computed():
    f = extract_features(_inputs(), _sections())
    assert f["rsi"] is not None and 0 <= f["rsi"] <= 100
    assert f["macd_hist"] is not None
    assert f["ma_alignment"] in ("bull", "bear", "mixed")
    assert f["volume_ratio"] is not None and f["volume_ratio"] > 0


def test_extract_features_kronos_none_but_backtest_live():
    f = extract_features(_inputs(), _sections())
    assert f["kronos_direction"] is None          # Phase 2: Kronos 运行时尚未接入
    bw = f["backtest_winrate"]                     # Phase 3: 纯 OHLCV 历史形态胜率已接入
    assert isinstance(bw, dict)
    assert 0.0 <= bw["winrate"] <= 1.0
    assert bw["horizon"] == 5
    assert bw["sample"] > 0
    assert bw["state"] in ("bull", "bear", "mixed")


def test_extract_features_tolerates_empty():
    f = extract_features({}, {})
    assert f["roe"] is None and f["rsi"] is None and f["model_bull_ratio"] is None
    assert f["market_regime"] is None


def test_extract_features_fund_hold_count_and_mv_sum():
    """重仓基金家数 = fund_holds.rows 长度；持仓市值 = 各行 market_value(元) 求和。
    锁定『单期持仓→重仓家数+市值』派生，支撑 indicators 重仓基金卡。"""
    sections = {
        "institutional_holdings": {"data_status": "fresh",
            "fund_holds": {"period": "2026-03-31", "rows": [
                {"fund_name": "易方达蓝筹", "market_value": 1.5e9, "nv_ratio": 3.4},
                {"fund_name": "兴全合润", "market_value": 2.1e9, "nv_ratio": 2.8},
                {"fund_name": "中欧时代先锋", "market_value": None},  # 缺市值不应计入求和
            ], "total_nv_pct": 6.2}},
    }
    f = extract_features({}, sections)
    assert f["fund_hold_count"] == 3
    assert abs(f["fund_hold_mv"] - 3.6e9) < 1.0   # 1.5e9 + 2.1e9，第三行 None 跳过


def test_extract_features_no_fund_rows_gives_none():
    sections = {"institutional_holdings": {"fund_holds": {"rows": []}}}
    f = extract_features({}, sections)
    assert f["fund_hold_count"] is None
    assert f["fund_hold_mv"] is None


def test_extract_features_reads_real_provider_keys():
    """Guard against features.py drifting from the actual institutional provider output keys."""
    sections = {
        "main_force_deep": {"data_status": "fresh",
            "dragon_tiger": {"quant_seat_appearances": 2, "net_inst_buy_30d": 5e7},
            "hsgt": {"delta_30d_pct": 0.6}},
        "institutional_holdings": {"data_status": "stale",
            "holder_number": {"latest_num": 50000, "pct_change_qoq": -3.2},
            "fund_holds": {"period": "2026-03-31", "rows": [], "total_nv_pct": 3.4}},
    }
    f = extract_features({}, sections)
    assert f["north_delta_30d"] == 0.6
    assert f["lhb_net_inst_buy"] == 5e7
    assert f["holder_number_trend"] == "down"
    assert f["fund_hold_trend"] is None
