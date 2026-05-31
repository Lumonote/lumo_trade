"""E6（spec §6.7）：OHLCV/技术/风控硬门槛 → 分级降级。

验收：40–59 日历史股不再整页「数据不足」。
- `_load_ohlcv`：`<35` 抛错（带「当前行数 + 需 ≥N 日」明确条件）；`35–59` 返回该序列
  （短历史降级，可算指标交由下游）；`≥60` 优先（保留旧频率偏好）。
- `_collect_inputs`：短历史命中后 `ohlcv` 被装载，不再级联 `ohlcv_error` → 多面板空白。
- `compute_risk_control`：`<60` 仍 unavailable，但 reason 给「需 ≥60 交易日」明确条件。
- `panel/features._technical_features`：`35–59` 计算指标并标注低置信；`<35` 给具体原因。
- `build_panel`：把低置信标注冒泡到 `panel.note`，供前端展示。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.panel.features import _technical_features
from analysis.stock_analysis_suite import StockAnalysisSuite


def _ohlcv(n: int) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 10.0 + rng.normal(0, 0.2, n).cumsum() * 0.1
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": rng.integers(1e6, 5e6, n).astype(float),
        "amount": close * 1e6,
    })


def _patch_repo(monkeypatch, frames: dict) -> None:
    """替换 ohlcv_repo.load_dataframe，按频率返回预设 df（缺省空表）。"""
    from data_store import ohlcv_repo

    def _load(code, frequency):
        df = frames.get(frequency)
        return df if df is not None else pd.DataFrame()

    monkeypatch.setattr(ohlcv_repo, "load_dataframe", _load)


# ---- Gate 1: _load_ohlcv 分级降级 ----

def test_load_ohlcv_returns_short_history_35_to_59(monkeypatch):
    """40 日历史（35–59）→ 返回该 df，不再抛 FileNotFoundError。"""
    _patch_repo(monkeypatch, {"1d": _ohlcv(40), "5m": pd.DataFrame()})
    df = StockAnalysisSuite()._load_ohlcv("000001")
    assert len(df) == 40


def test_load_ohlcv_prefers_sufficient_frequency(monkeypatch):
    """回归守护：1d 仅 40 行但 5m ≥60 → 仍优先返回 ≥60 的 5m。"""
    _patch_repo(monkeypatch, {"1d": _ohlcv(40), "5m": _ohlcv(100)})
    df = StockAnalysisSuite()._load_ohlcv("000001")
    assert len(df) == 100


def test_load_ohlcv_raises_below_35_with_specific_reason(monkeypatch):
    """<35 行 → 抛错且 message 含当前行数与 ≥35 条件（非泛化「数据不足」）。"""
    _patch_repo(monkeypatch, {"1d": _ohlcv(20), "5m": pd.DataFrame()})
    with pytest.raises(FileNotFoundError) as ei:
        StockAnalysisSuite()._load_ohlcv("000001")
    msg = str(ei.value)
    assert "20" in msg and "35" in msg


# ---- Gate 1 级联：_collect_inputs 不再整页 unavailable ----

class _StubAnalyzer:
    def __init__(self, *a, **kw):
        pass

    def analyze(self, code, df):
        return {"details": {}, "signals": []}


class _StubFundam:
    def __init__(self, code, minimal_api_mode=True):
        pass

    def get_comprehensive_data(self):
        return {}


def test_collect_inputs_short_history_loads_ohlcv_no_cascade(monkeypatch):
    """40 日历史经真实 _load_ohlcv → out['ohlcv'] 装载、无 ohlcv_error。"""
    _patch_repo(monkeypatch, {"1d": _ohlcv(40), "5m": pd.DataFrame()})
    from analysis import stock_analysis_suite as mod
    monkeypatch.setattr(mod, "ChipAnalyzer", _StubAnalyzer)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _StubAnalyzer)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _StubFundam)
    suite = StockAnalysisSuite()
    suite._classify_market_regime = lambda: ("sideways", 0.4)  # type: ignore[attr-defined]
    suite._run_quant_models = lambda code, df: {"total": 0, "buy_signal_count": 0,
                                                "sell_signal_count": 0, "hold_signal_count": 0}  # type: ignore[attr-defined]
    out = suite._collect_inputs("000001")
    assert "ohlcv_error" not in out
    assert out.get("ohlcv") is not None and len(out["ohlcv"]) == 40


# ---- Gate 3: 风控 <60 明确条件 ----

def test_risk_control_below_60_reason_states_60_day_condition():
    """40 日历史 → 风控 unavailable，reason 含「60」「交易日」与当前行数。"""
    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _ohlcv(40)  # type: ignore[attr-defined]
    rc = suite.compute_risk_control("000001")
    assert rc["available"] is False
    assert "60" in rc["reason"]
    assert "交易日" in rc["reason"]
    assert "40" in rc["reason"]


# ---- Gate 2: panel/features 技术指标分级 + 标注 ----

def test_technical_features_short_history_computes_with_low_confidence():
    """35–59 行 → 指标可算（rsi 非 None）且标注低置信。"""
    out = _technical_features(_ohlcv(45))
    assert out.get("rsi") is not None
    assert out.get("low_confidence") is True
    assert out.get("history_days") == 45
    assert out.get("confidence_note") and "45" in out["confidence_note"]


def test_technical_features_full_history_no_low_confidence():
    """≥60 行 → 指标可算且不标低置信。"""
    out = _technical_features(_ohlcv(80))
    assert out.get("rsi") is not None
    assert out.get("low_confidence") is False
    assert out.get("confidence_note") is None


def test_technical_features_below_35_unavailable_with_reason():
    """<35 行 → 指标 None，带具体原因（含 35），而非低置信。"""
    out = _technical_features(_ohlcv(20))
    assert out.get("rsi") is None
    assert out.get("low_confidence") is None
    assert out.get("confidence_note") and "35" in out["confidence_note"]


# ---- 标注冒泡到 build_panel ----

def test_build_panel_surfaces_low_confidence_note():
    from analysis.panel import build_panel
    panel = build_panel({"ohlcv": _ohlcv(45)}, {})
    assert panel.get("note") and "45" in panel["note"]


def test_build_panel_no_note_for_full_history():
    """回归守护：≥60 行无低置信标注。"""
    from analysis.panel import build_panel
    panel = build_panel({"ohlcv": _ohlcv(80)}, {})
    assert panel.get("note") is None
