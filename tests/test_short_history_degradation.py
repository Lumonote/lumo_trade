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
    df = StockAnalysisSuite(auto_fetch=False)._load_ohlcv("000001")
    assert len(df) == 40


def test_load_ohlcv_prefers_sufficient_frequency(monkeypatch):
    """回归守护：1d 仅 40 行但 5m ≥60 → 仍优先返回 ≥60 的 5m。"""
    _patch_repo(monkeypatch, {"1d": _ohlcv(40), "5m": _ohlcv(100)})
    df = StockAnalysisSuite(auto_fetch=False)._load_ohlcv("000001")
    assert len(df) == 100


def test_load_ohlcv_raises_below_35_with_specific_reason(monkeypatch):
    """<35 行 → 抛错且 message 含当前行数与 ≥35 条件（非泛化「数据不足」）。"""
    _patch_repo(monkeypatch, {"1d": _ohlcv(20), "5m": pd.DataFrame()})
    with pytest.raises(FileNotFoundError) as ei:
        StockAnalysisSuite(auto_fetch=False)._load_ohlcv("000001")
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
    suite = StockAnalysisSuite(auto_fetch=False)
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


# ---- 按需补偿：本地不足时立即拉数据，实在没有才显示指引 ----

def test_load_ohlcv_auto_fetches_when_local_insufficient(monkeypatch):
    """本地 <60 行 → 调 ensure_daily 补偿 → 重扫命中 ≥60 并返回补偿后的序列。"""
    from data_store import ohlcv_fetch, ohlcv_repo

    state = {"fetched": False}

    def _load(code, frequency):
        # 补偿前空表；ensure_daily 跑过后 1d 重扫到足量历史（模拟 upsert 入库）。
        if frequency == "1d" and state["fetched"]:
            return _ohlcv(120)
        return pd.DataFrame()

    def _fake_ensure(code, start, end, throttle=0.0):
        state["fetched"] = True
        return _ohlcv(120)

    monkeypatch.setattr(ohlcv_repo, "load_dataframe", _load)
    monkeypatch.setattr(ohlcv_fetch, "ensure_daily", _fake_ensure)

    df = StockAnalysisSuite()._load_ohlcv("688111")  # auto_fetch 默认 True
    assert state["fetched"] is True
    assert len(df) == 120


def test_load_ohlcv_auto_fetch_cooldown_dedups(monkeypatch):
    """冷却去重：补偿失败后，冷却窗口内的再次调用不重复打网络（payload 内双调用同此）。"""
    from data_store import ohlcv_fetch, ohlcv_repo

    calls: list = []
    monkeypatch.setattr(ohlcv_repo, "load_dataframe", lambda code, freq: pd.DataFrame())

    def _fake_ensure(code, start, end, throttle=0.0):
        calls.append(code)
        return pd.DataFrame()  # 数据源无数据 → 补偿失败

    monkeypatch.setattr(ohlcv_fetch, "ensure_daily", _fake_ensure)

    suite = StockAnalysisSuite()
    for _ in range(2):
        with pytest.raises(FileNotFoundError):
            suite._load_ohlcv("688111")
    assert calls == ["688111"]  # 只补偿一次


def test_load_ohlcv_message_has_remediation_when_fetch_fails(monkeypatch):
    """实在补偿无果 → 抛错 message 含操作指引（代码/停牌核对 + fetch_data.py）。"""
    from data_store import ohlcv_fetch, ohlcv_repo

    monkeypatch.setattr(ohlcv_repo, "load_dataframe", lambda code, freq: pd.DataFrame())
    monkeypatch.setattr(ohlcv_fetch, "ensure_daily",
                        lambda code, start, end, throttle=0.0: pd.DataFrame())

    with pytest.raises(FileNotFoundError) as ei:
        StockAnalysisSuite()._load_ohlcv("688111")
    msg = str(ei.value)
    assert "688111" in msg
    assert "fetch_data.py" in msg


def test_load_ohlcv_no_fetch_when_auto_fetch_disabled(monkeypatch):
    """auto_fetch=False → 纯本地降级，绝不触网（单测离线/幂等保证）。"""
    from data_store import ohlcv_fetch, ohlcv_repo

    monkeypatch.setattr(ohlcv_repo, "load_dataframe", lambda code, freq: pd.DataFrame())

    def _boom(*a, **kw):
        raise AssertionError("ensure_daily must not be called when auto_fetch=False")

    monkeypatch.setattr(ohlcv_fetch, "ensure_daily", _boom)

    with pytest.raises(FileNotFoundError):
        StockAnalysisSuite(auto_fetch=False)._load_ohlcv("688111")


# ---- 新股/次新股：自动拉取成功但历史天然不足 → 放行给下游降级计算 ----

def test_load_ohlcv_returns_ipo_short_history_when_fetched(monkeypatch):
    """新股（上市 13 天，<35 行）自动拉取成功后 → 放行返回短历史，不抛错。

    这是「新股出现很多数据不足」的核心修复：数据源确实有该股（fetch 成功），
    只是上市时间短导致历史不足，应让量化模型基于短历史降级产出信号，
    而不是整页「M4: OHLCV 不足或加载失败」。
    """
    from data_store import ohlcv_repo

    _patch_repo(monkeypatch, {"1d": _ohlcv(13), "5m": pd.DataFrame()})
    suite = StockAnalysisSuite(auto_fetch=True)
    # 数据源确实返回了数据（ensure_daily 有结果）→ 触发新股放行分支
    monkeypatch.setattr(suite, "_ensure_ohlcv_daily", lambda code: True)
    df = suite._load_ohlcv("688825")
    assert len(df) == 13
    # 量化模型基于短历史仍能产出信号（非 0 总数）
    from analysis.stock_analysis_suite import count_quant_signals
    res = count_quant_signals(df)
    assert res["total"] == 30


def test_load_ohlcv_ipo_still_raises_when_source_has_no_data(monkeypatch):
    """新股但数据源确实无数据（补偿无果）→ 仍抛错（避免伪造行情）。"""
    from data_store import ohlcv_repo

    _patch_repo(monkeypatch, {"1d": pd.DataFrame(), "5m": pd.DataFrame()})
    suite = StockAnalysisSuite(auto_fetch=True)
    monkeypatch.setattr(suite, "_ensure_ohlcv_daily", lambda code: False)
    with pytest.raises(FileNotFoundError):
        suite._load_ohlcv("688825")


def test_fetch_daily_sina_filters_by_window():
    """新浪兜底：按 start/end 窗口过滤（YYYYMMDD 与 ISO 均兼容）。"""
    from data_store.ohlcv_fetch import fetch_daily_sina
    # 用真实新浪接口拉取新股（网络可用时）；不可用则跳过断言
    df = fetch_daily_sina("688825", "20260101", "20260812")
    if df.empty:
        pytest.skip("新浪接口不可达，跳过在线断言")
    assert len(df) > 0
    assert all("2026-01-01" <= str(ts)[:10] <= "2026-08-12" for ts in df["timestamps"])


def test_sina_symbol_mapping():
    """新浪 symbol 前缀：沪/深/北（含 92 新段）。"""
    from data_store.ohlcv_fetch import _sina_symbol
    assert _sina_symbol("688825") == "sh688825"
    assert _sina_symbol("000001") == "sz000001"
    assert _sina_symbol("920161") == "bj920161"
    assert _sina_symbol("830799") == "bj830799"
