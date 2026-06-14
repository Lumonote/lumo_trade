import time

import numpy as np
import pandas as pd

from analysis.stock_analysis_suite import StockAnalysisSuite


def _fake_ohlcv(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = 10.0 + rng.normal(0, 0.2, n).cumsum() * 0.1
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": close * 0.99, "high": close * 1.02,
        "low": close * 0.98, "close": close,
        "volume": rng.integers(1e6, 5e6, n).astype(float),
        "amount": close * rng.integers(1e6, 5e6, n).astype(float),
    })


def test_radar_main_force_phase_formula():
    """0.5 * control_degree + 0.3 * continuity_score + 0.2 * retail_normalized."""
    from analysis.stock_analysis_suite import compute_main_force_phase_score
    score = compute_main_force_phase_score(
        control_degree=80.0,
        recent_main_positive_days=4,
        main_net=-1_000_000.0,
        retail_net=600_000.0,
    )
    # 0.5*80 + 0.3*(4*20) + 0.2*min(100, abs(600000/1000000)*100) = 40 + 24 + 12 = 76
    assert score == 76


def test_volume_price_game_uses_net_model_votes_not_missing_buys():
    """少量多空票 + 大量观望不应被判成强空/空头占优。"""
    from analysis.stock_analysis_suite import compute_volume_price_game_score

    suite = StockAnalysisSuite()
    score = compute_volume_price_game_score(4, 30, 5)
    assert score == 48
    assert suite._label_vp(score) == "多空胶着"

    radar = suite._compute_radar({
        "models": {
            "buy_signal_count": 4,
            "sell_signal_count": 5,
            "hold_signal_count": 21,
            "total": 30,
        },
    })
    assert radar["volume_price_game"]["score"] == 48
    assert radar["volume_price_game"]["label"] == "多空胶着"


def test_quant_matrix_posture_observation_dominant_is_not_strong_bear():
    suite = StockAnalysisSuite()
    section = suite._collect_quant_matrix("688322.SH", {
        "buy_signal_count": 4, "sell_signal_count": 5, "hold_signal_count": 21,
        "total": 30, "per_model": [],
    })
    assert section["current_posture"] == "观望主导"


def test_radar_handles_all_missing():
    suite = StockAnalysisSuite()
    radar = suite._compute_radar({})  # all analyzer outputs missing
    for key in ("main_force_phase", "market_cycle", "volume_price_game", "chip_structure", "performance"):
        assert radar[key]["score"] is None
        assert "数据不足" in radar[key]["label"]


def test_suite_caches_payload_for_ttl():
    suite = StockAnalysisSuite(ttl_seconds=60)
    calls = []

    def fake_compute(code: str):
        calls.append(code)
        return {"code": code, "value": len(calls)}

    suite._compute_full_payload = fake_compute  # type: ignore[attr-defined]
    r1 = suite.get_full_payload("000001")
    r2 = suite.get_full_payload("000001")
    assert r1 == r2 == {"code": "000001", "value": 1}
    assert calls == ["000001"]


def test_suite_recomputes_after_ttl():
    suite = StockAnalysisSuite(ttl_seconds=0.05)
    calls = []
    suite._compute_full_payload = lambda code: calls.append(code) or {"v": len(calls)}  # type: ignore[attr-defined]
    suite.get_full_payload("000001")
    time.sleep(0.1)
    suite.get_full_payload("000001")
    assert len(calls) == 2


def test_compute_overview_assembles_full_payload():
    suite = StockAnalysisSuite()
    fake_inputs = {
        "chip": {"details": {"main_force_control": 80, "concentration_90": 15.9, "profit_ratio": 50},
                  "signals": ["主力筹码集中"]},
        "capital_flow": {"details": {"order_analysis": {"main_net_inflow": -1e6, "retail_net_inflow": 6e5},
                                       "positive_days_5d": 4},
                          "signals": ["主力撤离"]},
        "market_regime": "sideways",
        "capital_flow_ratio": 0.42,
        "models": {"buy_signal_count": 16, "sell_signal_count": 8, "hold_signal_count": 6, "total": 30},
        "fundamental": {"pe": 4.8, "roe": 14.2, "pe_industry_rank": 10.0, "net_profit_yoy": 12.0},
        "sentiment": {"confidence_label": "中"},
        "quality": {"volume_label": "量价正常", "chip_label": "中等"},
    }
    suite._collect_inputs = lambda code: fake_inputs  # type: ignore[attr-defined]
    overview = suite.compute_overview("000001")
    assert "radar" in overview
    prob = overview["scenario_probability"]
    assert prob["bullish"] + prob["bearish"] + prob["sideways"] == 100
    assert any(s["label"] == "主力阶段" for s in overview["key_signals"])
    assert len(overview["key_signals"]) == 6
    assert isinstance(overview["deep_signals"], list)
    assert overview["radar"]["main_force_phase"]["score"] is not None


def test_key_signals_include_ma_alignment_when_ohlcv_available():
    suite = StockAnalysisSuite()
    signals = suite._build_key_signals({"ohlcv": _fake_ohlcv(80)}, {})
    tech = next(s for s in signals if s["label"] == "技术趋势")
    assert tech["value"] in ("多头排列", "空头排列", "均线交织")


def test_key_signals_detect_bullish_ma_alignment():
    suite = StockAnalysisSuite()
    close = np.arange(1.0, 81.0)
    df = pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=80, freq="D"),
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.ones(80), "amount": close,
    })
    signals = suite._build_key_signals({"ohlcv": df}, {})
    assert {"label": "技术趋势", "value": "多头排列", "tone": "info"} in signals


def test_compute_risk_control_with_atr_and_levels():
    suite = StockAnalysisSuite()
    df = _fake_ohlcv(120)
    suite._load_ohlcv = lambda code: df  # type: ignore[attr-defined]
    rc = suite.compute_risk_control("000001")
    assert rc["available"] is True
    assert rc["execution_plan"]["stop_loss"]["price"] > 0
    assert len(rc["scaled_entry"]) == 5
    assert sum(item["position_pct"] for item in rc["scaled_entry"]) == 100
    assert len(rc["tiered_take_profit"]) == 4
    assert sum(item["sell_pct"] for item in rc["tiered_take_profit"]) == 100
    assert all("price" in item for item in rc["tiered_take_profit"])
    assert isinstance(rc["deep_signals"], list)


def test_compute_risk_control_insufficient_data():
    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(30)  # < 60 bars
    rc = suite.compute_risk_control("000001")
    assert rc["available"] is False
    assert "数据不足" in rc["reason"]


from pathlib import Path

def test_collect_cached_reports_finds_latest(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "opportunity_top10_20260523_101500.md").write_text("test", encoding="utf-8")
    (reports / "batch_analysis_000001_20260523.md").write_text("test", encoding="utf-8")
    suite = StockAnalysisSuite()
    out = suite.collect_cached_reports("000001", base_dir=reports)
    assert out["opportunity"]["found"] is True
    assert out["opportunity"]["path"].endswith("opportunity_top10_20260523_101500.md")
    assert out["opportunity"]["updated_at"] is not None
    assert out["batch_analysis"]["found"] is True


def test_collect_cached_reports_no_match(tmp_path):
    suite = StockAnalysisSuite()
    out = suite.collect_cached_reports("999999", base_dir=tmp_path)
    assert out["opportunity"]["found"] is False
    assert out["opportunity"]["path"] is None
    assert out["opportunity"]["updated_at"] is None
    assert out["batch_analysis"]["found"] is False


def test_collect_cached_reports_returns_most_recent(tmp_path):
    """Multiple opportunity reports — pick the one with latest mtime."""
    import time
    reports = tmp_path / "reports"
    reports.mkdir()
    older = reports / "opportunity_top10_20260520_100000.md"
    newer = reports / "opportunity_top10_20260523_101500.md"
    older.write_text("old", encoding="utf-8")
    time.sleep(0.01)
    newer.write_text("new", encoding="utf-8")
    suite = StockAnalysisSuite()
    out = suite.collect_cached_reports("000001", base_dir=reports)
    assert out["opportunity"]["path"].endswith("opportunity_top10_20260523_101500.md")


def test_collect_inputs_pulls_from_all_analyzers(monkeypatch):
    from analysis import stock_analysis_suite as mod

    class _Chip:
        def analyze(self, code, df):
            return {"details": {"main_force_control": 70, "concentration_90": 15.9, "profit_ratio": 50},
                    "signals": ["持仓集中"]}

    class _Cap:
        def analyze(self, code, df):
            return {"details": {"order_analysis": {"main_net_inflow": -1e6, "retail_net_inflow": 6e5},
                                "positive_days_5d": 4},
                    "signals": ["主力撤离"]}

    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {
                "financial_indicators": {"pe": 4.8, "roe": 14.2},
                "industry_comparison": {"pe_rank": 10.0},
                "financial_reports": {"net_profit_yoy": 12.0},
            }

    monkeypatch.setattr(mod, "ChipAnalyzer", _Chip)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _Cap)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]
    suite._classify_market_regime = lambda: ("sideways", 0.42)  # type: ignore[attr-defined]
    suite._run_quant_models = lambda code, df: {"buy_signal_count": 16, "sell_signal_count": 8, "hold_signal_count": 6, "total": 30}  # type: ignore[attr-defined]

    inputs = suite._collect_inputs("000001")
    assert inputs["chip"]["details"]["main_force_control"] == 70
    assert inputs["market_regime"] == "sideways"
    assert inputs["models"]["buy_signal_count"] == 16
    assert inputs["fundamental"]["pe"] == 4.8
    assert inputs["capital_flow"]["details"]["order_analysis"]["main_net_inflow"] == -1e6


def test_collect_inputs_passes_pb_to_fundamental(monkeypatch):
    """panel features 消费 fundamental.pb,_collect_inputs 必须透传(此前漏传)。"""
    from analysis import stock_analysis_suite as mod

    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {"financial_indicators": {"pe": 9.5, "pb": 1.3, "roe": 11.0},
                    "industry_comparison": {}, "financial_reports": {}}

    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: (_ for _ in ()).throw(RuntimeError("no ohlcv"))  # type: ignore[attr-defined]
    suite._classify_market_regime = lambda: ("sideways", 0.5)  # type: ignore[attr-defined]

    inputs = suite._collect_inputs("000001")
    assert inputs["fundamental"]["pb"] == 1.3


def test_fundamental_local_daily_basic_fallback(monkeypatch):
    """联网基本面整组失败时,PE/PB 从库内 daily_basic 最近一行兜底。"""
    import pandas as pd
    from analysis import stock_analysis_suite as mod
    from data_store import daily_basic_repo

    class _Boom:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            raise RuntimeError("network down")

    monkeypatch.setattr(mod, "FundamentalDataCollector", _Boom)
    monkeypatch.setattr(
        daily_basic_repo, "get_for_code",
        lambda ts_code, limit=None: pd.DataFrame([
            {"ts_code": ts_code, "trade_date": "2026-06-09",
             "pe": 12.0, "pe_ttm": 10.5, "pb": 1.8},
        ]),
    )

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: (_ for _ in ()).throw(RuntimeError("no ohlcv"))  # type: ignore[attr-defined]
    suite._classify_market_regime = lambda: ("sideways", 0.5)  # type: ignore[attr-defined]

    inputs = suite._collect_inputs("000001")
    assert inputs["fundamental_error"]  # 采集确实失败
    assert inputs["fundamental"]["pe"] == 10.5  # pe_ttm 优先
    assert inputs["fundamental"]["pb"] == 1.8


def test_compute_full_payload_assembles_overview_and_risk(monkeypatch, tmp_path):
    """Smoke test: _compute_full_payload returns the spec §5.1 shape."""
    from analysis import stock_analysis_suite as mod

    class _Chip:
        def analyze(self, code, df):
            return {"details": {"main_force_control": 70, "concentration_90": 15.9, "profit_ratio": 50}, "signals": []}

    class _Cap:
        def analyze(self, code, df):
            return {"details": {"order_analysis": {"main_net_inflow": -1e6, "retail_net_inflow": 6e5},
                                "positive_days_5d": 4}, "signals": []}

    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {"financial_indicators": {"pe": 4.8, "roe": 14.2}, "industry_comparison": {"pe_rank": 10.0}, "financial_reports": {"net_profit_yoy": 12.0}}

    monkeypatch.setattr(mod, "ChipAnalyzer", _Chip)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _Cap)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]
    suite._classify_market_regime = lambda: ("sideways", 0.42)  # type: ignore[attr-defined]
    suite._run_quant_models = lambda code, df: {"buy_signal_count": 16, "sell_signal_count": 8, "hold_signal_count": 6, "total": 30}  # type: ignore[attr-defined]

    payload = suite._compute_full_payload("000001")
    assert "overview" in payload
    assert "risk_control" in payload
    assert "cached_reports" in payload
    assert payload["ai_interpretation"]["status"] == "not_generated"
    assert payload["ai_interpretation"]["trigger_endpoint"] == "/api/stock-analysis-suite/000001/ai"
    assert payload["overview"]["radar"]["main_force_phase"]["score"] is not None
    assert payload["risk_control"]["available"] is True
    assert "stub_tabs" in payload
    assert "warnings" in payload


def test_build_llm_payload_contains_required_sections():
    suite = StockAnalysisSuite()
    suite_data = {
        "overview": {
            "radar": {
                "main_force_phase": {"score": 62, "label": "中等偏强"},
                "market_cycle":     {"score": 35, "label": "震荡期"},
                "volume_price_game":{"score": 53, "label": "多空胶着"},
                "chip_structure":   {"score": 28, "label": "结构偏差"},
                "performance":      {"score": 71, "label": "估值修复"},
            },
            "key_signals": [{"label": "大盘周期", "value": "震荡期"}],
            "deep_signals": [{"text": "主力撤离", "tag": "资金"}],
            "scenario_probability": {"bullish": 34, "bearish": 32, "sideways": 34},
        },
        "risk_control": {"available": True, "execution_plan": {"stop_loss": {"price": 10.43, "drop_pct": 2.3}}},
    }
    payload = suite.build_llm_payload("000001", "平安银行", suite_data)
    text = payload["prompt"]
    for keyword in ["核心定性", "价值与安全边际", "主力博弈", "多因子量化", "情绪周期", "预期差", "操盘建议"]:
        assert keyword in text, f"prompt missing section: {keyword}"
    assert "平安银行" in text and "000001" in text
    assert payload["model_full_key"] is None


def test_build_llm_payload_includes_fresh_deep_sections():
    """spec §4.3.4: 控盘度 / 量化矩阵等 fresh 字段应进入 prompt。"""
    suite = StockAnalysisSuite()
    suite_data = {
        "overview": {"radar": {}, "key_signals": [], "deep_signals": [],
                     "scenario_probability": {}},
        "risk_control": {},
        "chip_control": {"data_status": "fresh", "control_degree": 78,
                         "control_label": "高控", "concentration_90": 11.5},
        "quant_matrix": {"data_status": "fresh", "current_posture": "震荡偏多",
                         "multi_period_resonance": {"bull": 18, "bear": 6, "neutral": 6}},
    }
    text = suite.build_llm_payload("000001", "平安银行", suite_data)["prompt"]
    assert "高控" in text and "78" in text
    assert "震荡偏多" in text


def test_build_llm_payload_skips_unavailable_sections():
    """spec §4.3.4: unavailable 字段不得进入 prompt（避免 LLM 编造）。"""
    suite = StockAnalysisSuite()
    suite_data = {
        "overview": {"radar": {}, "key_signals": [], "deep_signals": [],
                     "scenario_probability": {}},
        "risk_control": {},
        "chip_control": {"data_status": "unavailable", "reason": "no data"},
        "quant_matrix": {"data_status": "unavailable", "reason": "no data"},
    }
    text = suite.build_llm_payload("000001", "平安银行", suite_data)["prompt"]
    # 降级数据不应把占位/原因塞进 prompt
    assert "no data" not in text
    assert "震荡偏多" not in text


def test_llm_interpret_stock_markdown_returns_raw_text(monkeypatch):
    from analysis.llm_service import LLMAnalyzer
    analyzer = LLMAnalyzer()

    captured = {}

    def fake_call(prompt, model_cfg, max_tokens=3000):
        captured["prompt"] = prompt
        return True, "## 1. 核心定性\n平安银行...\n## 2. 价值与安全边际\n...", {"total_tokens": 3651}

    monkeypatch.setattr(analyzer, "_call_provider_raw", fake_call)
    ok, markdown, tokens = analyzer.interpret_stock_markdown(
        {"prompt": "TEST_PROMPT"}, model_full_key=None,
    )
    assert ok is True
    assert markdown.startswith("## 1. 核心定性")
    assert tokens == 3651
    assert captured["prompt"] == "TEST_PROMPT"


def test_llm_interpret_stock_markdown_empty_prompt():
    from analysis.llm_service import LLMAnalyzer
    analyzer = LLMAnalyzer()
    ok, msg, tokens = analyzer.interpret_stock_markdown({"prompt": ""}, model_full_key=None)
    assert ok is False
    assert tokens is None
    assert "prompt" in msg.lower() or msg


def test_trigger_ai_interpretation_persists_markdown(tmp_path, monkeypatch):
    suite = StockAnalysisSuite(reports_root=tmp_path)
    suite.get_full_payload = lambda code: {"overview": {"radar": {}}, "risk_control": {}}  # type: ignore[assignment]

    class _Fake:
        def interpret_stock_markdown(self, payload, model_full_key=None):
            return True, "## 1. 核心定性\nfoo", 1234

    monkeypatch.setattr("analysis.stock_analysis_suite.LLMAnalyzer", lambda: _Fake())

    out = suite.trigger_ai_interpretation("000001", name="平安银行")
    assert out["success"] is True
    assert out["status"] == "ready"
    assert out["report"].startswith("## 1. 核心定性")
    assert out["token_usage"] == 1234
    assert "cached_path" in out
    assert Path(out["cached_path"]).exists()
    assert "000001" in out["cached_path"]
    assert out["cached_path"].endswith(".md")


def test_trigger_ai_interpretation_failure(tmp_path, monkeypatch):
    suite = StockAnalysisSuite(reports_root=tmp_path)
    suite.get_full_payload = lambda code: {"overview": {}, "risk_control": {}}  # type: ignore[assignment]

    class _Fake:
        def interpret_stock_markdown(self, payload, model_full_key=None):
            return False, "DeepSeek API 超时", None

    monkeypatch.setattr("analysis.stock_analysis_suite.LLMAnalyzer", lambda: _Fake())

    out = suite.trigger_ai_interpretation("000001", name="平安银行")
    assert out["success"] is False
    assert out["status"] == "failed"
    assert "DeepSeek" in out["error"]


def test_trigger_ai_interpretation_force_refresh_invalidates_cache(tmp_path, monkeypatch):
    suite = StockAnalysisSuite(reports_root=tmp_path)
    calls = []

    def fake_compute(code):
        calls.append(code)
        return {"overview": {}, "risk_control": {}}

    suite._compute_full_payload = fake_compute  # type: ignore[attr-defined]

    class _Fake:
        def interpret_stock_markdown(self, payload, model_full_key=None):
            return True, "## md", 100

    monkeypatch.setattr("analysis.stock_analysis_suite.LLMAnalyzer", lambda: _Fake())

    # Prime cache
    suite.get_full_payload("000001")
    assert len(calls) == 1
    # force_refresh should re-compute
    suite.trigger_ai_interpretation("000001", name="x", force_refresh=True)
    assert len(calls) == 2


# --- M1 扩展测试 ---


def test_payload_has_four_new_top_level_keys():
    """payload 必含 main_force_deep / institutional_holdings / chip_control / quant_matrix，
    且骨架阶段 data_status 均为 unavailable。"""
    from analysis.institutional.base import ProviderResult

    class _Stub:
        def get(self, ts_code, **kw):
            return ProviderResult.unavailable(reason="stub")

    suite = StockAnalysisSuite(
        institutional_providers={
            "lhb": _Stub(), "hsgt": _Stub(), "holders": _Stub(),
            "survey": _Stub(), "fund": _Stub(), "cyq": _Stub(),
        },
    )
    # Bypass real data loading
    suite._compute_full_payload_inner = suite._compute_full_payload
    def _mock_compute(code):
        # Call the real method but stub _collect_inputs
        return suite._build_payload_with_institutional(code)
    suite._compute_full_payload = _mock_compute

    payload = suite._build_payload_with_institutional("000001")

    for key in ("main_force_deep", "institutional_holdings",
                "chip_control", "quant_matrix"):
        assert key in payload, f"missing top-level key: {key}"
        assert payload[key]["data_status"] == "unavailable"
        assert "last_updated" in payload[key]
        assert "reason" in payload[key]


def test_overview_radar_has_two_new_axes():
    from analysis.institutional.base import ProviderResult

    class _Stub:
        def get(self, ts_code, **kw):
            return ProviderResult.unavailable(reason="stub")

    suite = StockAnalysisSuite(
        institutional_providers={
            "lhb": _Stub(), "hsgt": _Stub(), "holders": _Stub(),
            "survey": _Stub(), "fund": _Stub(), "cyq": _Stub(),
        },
    )
    radar = suite._compute_radar({})
    assert "control_degree" in radar
    assert "quant_activity" in radar
    assert radar["control_degree"]["score"] == 0
    assert radar["quant_activity"]["score"] == 0


def test_radar_control_degree_uses_chip_main_force_control():
    """有 chip 数据时，radar.control_degree.score = ChipAnalyzer 的 main_force_control
    （spec §0.1: 控盘度已计算但此前被硬编码为 0，本次接线）。"""
    suite = StockAnalysisSuite()
    inputs = {
        "chip": {"details": {"main_force_control": 78, "concentration_90": 12.0,
                              "profit_ratio": 50}, "signals": []},
    }
    radar = suite._compute_radar(inputs)
    assert radar["control_degree"]["score"] == 78
    assert radar["control_degree"]["label"] != "未知"


def test_collect_chip_control_passes_through_chip_metrics():
    """传入 chip details 时，chip_control 应透传控盘度与集中度，data_status=fresh，
    并给出 control_label（低控/中控/高控）。"""
    suite = StockAnalysisSuite()
    chip = {"details": {"main_force_control": 75, "concentration_90": 11.5,
                        "profit_ratio": 50}, "signals": []}
    section = suite._collect_chip_control("000001", chip=chip)
    assert section["data_status"] == "fresh"
    assert section["control_degree"] == 75
    assert section["concentration_90"] == 11.5
    assert section["control_label"] == "高控"


def test_collect_chip_control_unavailable_without_chip():
    """无 chip 数据（如 cyq provider 也无）时仍降级为 unavailable，向后兼容。"""
    suite = StockAnalysisSuite()
    section = suite._collect_chip_control("000001", chip=None)
    assert section["data_status"] == "unavailable"
    assert section["control_degree"] is None


def test_collect_quant_matrix_from_local_models():
    """30 模型投票本地已算，quant_matrix 应据此产出 signals_matrix（日线列）+
    多周期共振计数 + 当前态势，data_status=fresh。多周期热力/30日命中率留 M4。"""
    suite = StockAnalysisSuite()
    models = {
        "buy_signal_count": 18, "sell_signal_count": 6, "hold_signal_count": 6,
        "total": 30,
        "per_model": [
            {"model": "macd_axis_golden_cross", "signal": 1},
            {"model": "atr_momentum", "signal": -1},
            {"model": "turtle_trading_system", "signal": 0},
        ],
    }
    section = suite._collect_quant_matrix("000001.SZ", models=models)
    assert section["data_status"] == "fresh"
    # 信号矩阵：逐模型条目（日线周期）
    assert isinstance(section["signals_matrix"], list)
    assert len(section["signals_matrix"]) == 3
    assert {"model", "period", "signal"} <= set(section["signals_matrix"][0].keys())
    # 多周期共振计数
    assert section["multi_period_resonance"] == {"bull": 18, "bear": 6, "neutral": 6}
    # 当前态势：18/30 买入 → 偏多
    assert section["current_posture"] in (
        "强势多头", "震荡偏多", "震荡", "震荡偏空", "强势空头")
    # M4 留空但 key 存在
    assert "hit_rate_30d" in section


def test_collect_quant_matrix_unavailable_without_models():
    """无本地模型结果（如 OHLCV 加载失败）时降级 unavailable。"""
    suite = StockAnalysisSuite()
    section = suite._collect_quant_matrix("000001.SZ", models=None)
    assert section["data_status"] == "unavailable"


def test_quant_matrix_posture_strong_bull():
    """买入占比高 → 强势多头。"""
    suite = StockAnalysisSuite()
    models = {"buy_signal_count": 26, "sell_signal_count": 2,
              "hold_signal_count": 2, "total": 30, "per_model": []}
    section = suite._collect_quant_matrix("000001.SZ", models=models)
    assert section["current_posture"] == "强势多头"



# --- Phase 1 panel 集成测试 ---


def test_compute_full_payload_includes_panel(monkeypatch):
    """payload 必含 panel 顶层 key，且 51 人 / 16 指标 / 7 流派齐全；既有 key 不丢。"""
    from analysis import stock_analysis_suite as mod

    class _Chip:
        def analyze(self, code, df):
            return {"details": {"main_force_control": 72, "concentration_90": 15.9,
                                "profit_ratio": 50}, "signals": []}

    class _Cap:
        def analyze(self, code, df):
            return {"details": {"order_analysis": {"main_net_inflow": 1.2e8,
                    "super_large_net": 8e7, "retail_net_inflow": -3e7},
                    "positive_days_5d": 3}, "signals": []}

    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {"financial_indicators": {"pe": 18.0, "roe": 22.0},
                    "industry_comparison": {"pe_rank": 28.0},
                    "financial_reports": {"net_profit_yoy": 35.0}}

    monkeypatch.setattr(mod, "ChipAnalyzer", _Chip)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _Cap)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]
    suite._classify_market_regime = lambda: ("bull", 0.6)  # type: ignore[attr-defined]
    suite._run_quant_models = lambda code, df: {"buy_signal_count": 18, "sell_signal_count": 6, "hold_signal_count": 6, "total": 30, "per_model": []}  # type: ignore[attr-defined]

    payload = suite._compute_full_payload("000001")
    # 既有 key 不丢（向后兼容）
    for key in ("overview", "risk_control", "main_force_deep", "quant_matrix"):
        assert key in payload
    # 新 panel key
    assert "panel" in payload
    panel = payload["panel"]
    assert len(panel["analysts"]) == 60
    assert len(panel["indicators"]) == 16
    assert len(panel["schools"]) == 7
    assert panel["consensus"]["bull"] + panel["consensus"]["neutral"] + panel["consensus"]["bear"] == 60


def test_collect_panel_degrades_on_failure(monkeypatch):
    """build_panel 抛异常时，panel 降级 unavailable 且不影响 payload 其它部分。"""
    suite = StockAnalysisSuite()
    import analysis.panel as panel_mod
    monkeypatch.setattr(panel_mod, "build_panel",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    section = suite._collect_panel("000001", {}, {})
    assert section["data_status"] == "unavailable"
    assert section["analysts"] == []


# --- P0-A: analysis_overlay 集成 ---


def test_payload_includes_analysis_overlay_key_backward_compatible(monkeypatch):
    """payload 必含 analysis_overlay 顶层 key（默认未生成→unavailable/reviewed=False），既有 key 不丢。"""
    from analysis import stock_analysis_suite as mod
    from data_store import kv_repo

    monkeypatch.setattr(kv_repo, "get", lambda ns, key: None)  # kv 空

    class _Chip:
        def analyze(self, code, df):
            return {"details": {"main_force_control": 70, "concentration_90": 15.9, "profit_ratio": 50}, "signals": []}

    class _Cap:
        def analyze(self, code, df):
            return {"details": {"order_analysis": {"main_net_inflow": -1e6, "retail_net_inflow": 6e5},
                                "positive_days_5d": 4}, "signals": []}

    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {"financial_indicators": {"pe": 4.8, "roe": 14.2}, "industry_comparison": {"pe_rank": 10.0}, "financial_reports": {"net_profit_yoy": 12.0}}

    monkeypatch.setattr(mod, "ChipAnalyzer", _Chip)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _Cap)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]
    payload = suite._compute_full_payload("000001")

    for key in ("overview", "risk_control", "panel", "ai_interpretation"):
        assert key in payload  # 向后兼容
    ov = payload["analysis_overlay"]
    assert ov["data_status"] == "unavailable"
    assert ov["reviewed"] is False


def test_collect_analysis_overlay_reads_persisted_as_stale(monkeypatch):
    from data_store import kv_repo

    stored = {"data_status": "fresh", "reviewed": True, "tier": "deep",
              "great_divide_override": {"punchline": "多头占优"}, "risks": ["x"],
              "panel_insights": {"zhao": "进场"}, "buy_zones": {"value": [], "growth": [],
              "technical": [], "youzi": []}, "narrative_override": None,
              "last_updated": "2026-05-29T10:00:00", "reason": None}
    monkeypatch.setattr(kv_repo, "get", lambda ns, key: (stored, 0.0))

    suite = StockAnalysisSuite()
    ov = suite._collect_analysis_overlay("000001")
    assert ov["reviewed"] is True
    assert ov["data_status"] == "stale"          # 读历史 → stale
    assert ov["great_divide_override"]["punchline"] == "多头占优"


def test_trigger_panel_overlay_generates_and_persists(monkeypatch):
    from analysis import stock_analysis_suite as mod
    from data_store import kv_repo

    saved = {}
    monkeypatch.setattr(kv_repo, "set_", lambda ns, key, payload, ttl_seconds=0: saved.update({(ns, key): payload}))
    monkeypatch.setattr(kv_repo, "get", lambda ns, key: None)

    class _Chip:
        def analyze(self, code, df):
            return {"details": {"main_force_control": 70, "concentration_90": 15.9, "profit_ratio": 50}, "signals": []}

    class _Cap:
        def analyze(self, code, df):
            return {"details": {"order_analysis": {"main_net_inflow": -1e6, "retail_net_inflow": 6e5},
                                "positive_days_5d": 4}, "signals": []}

    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {"financial_indicators": {"pe": 4.8, "roe": 14.2}, "industry_comparison": {"pe_rank": 10.0}, "financial_reports": {"net_profit_yoy": 12.0}}

    monkeypatch.setattr(mod, "ChipAnalyzer", _Chip)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _Cap)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]

    # deep 质量门（P0-B）要求逐人覆盖大分歧两位头牌 —— 先取规则面板拿到其 id 再据此造 insight。
    gd = suite.get_full_payload("000001")["panel"]["great_divide"]
    bull_id, bear_id = gd["bull"]["id"], gd["bear"]["id"]

    import json as _json
    good = "```json\n" + _json.dumps({
        "great_divide_override": {"punchline": "放量突破压制估值"},
        "risks": ["估值", "解禁", "题材退潮"],
        "panel_insights": {bull_id: "回调即买", bear_id: "估值偏贵需警惕"},
        "buy_zones": {"value": ["12 以下"], "growth": [], "technical": [], "youzi": []},
    }, ensure_ascii=False) + "\n```"

    result = suite.trigger_panel_overlay("000001", tier="deep", llm_caller=lambda p: (True, good))
    assert result["success"] is True
    assert result["overlay"]["reviewed"] is True
    assert result["overlay"]["quality"]["passed"] is True   # P0-B：完整 deep 覆盖过质量门
    assert ("analysis_overlay", "000001") in saved          # 已落 kv
    assert result["merged_panel"]["great_divide"]["punchline"] == "放量突破压制估值"


def test_trigger_panel_overlay_blocked_still_persists(monkeypatch):
    """P0-B：deep 覆盖缺大分歧头牌逐人点评 → 质量门拦截（reviewed=False），但拦截 overlay 仍落 kv 供审计/重载红条复现（spec §8.1）。"""
    from analysis import stock_analysis_suite as mod
    from data_store import kv_repo

    saved = {}
    monkeypatch.setattr(kv_repo, "set_", lambda ns, key, payload, ttl_seconds=0: saved.update({(ns, key): payload}))
    monkeypatch.setattr(kv_repo, "get", lambda ns, key: None)

    class _Chip:
        def analyze(self, code, df):
            return {"details": {"main_force_control": 70, "concentration_90": 15.9, "profit_ratio": 50}, "signals": []}

    class _Cap:
        def analyze(self, code, df):
            return {"details": {"order_analysis": {"main_net_inflow": -1e6, "retail_net_inflow": 6e5},
                                "positive_days_5d": 4}, "signals": []}

    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {"financial_indicators": {"pe": 4.8, "roe": 14.2}, "industry_comparison": {"pe_rank": 10.0}, "financial_reports": {"net_profit_yoy": 12.0}}

    monkeypatch.setattr(mod, "ChipAnalyzer", _Chip)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _Cap)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]

    import json as _json
    # panel_insights 仅含一个绝非大分歧头牌的 id → 缺两位头牌逐人点评 → deep 逐人覆盖 critical
    incomplete = "```json\n" + _json.dumps({
        "great_divide_override": {"punchline": "放量突破压制估值"},
        "risks": ["估值", "解禁", "题材退潮"],
        "panel_insights": {"__nobody__": "市场情绪偏暖"},
        "buy_zones": {"value": ["12 以下"], "growth": [], "technical": [], "youzi": []},
    }, ensure_ascii=False) + "\n```"

    result = suite.trigger_panel_overlay("000001", tier="deep", llm_caller=lambda p: (True, incomplete))
    assert result["success"] is False                       # 被质量门拦截
    assert result["overlay"]["reviewed"] is False
    assert result["overlay"]["quality"]["passed"] is False
    assert any("头牌" in c for c in result["overlay"]["quality"]["criticals"])
    assert ("analysis_overlay", "000001") in saved          # 拦截 overlay 仍落 kv（审计/重载红条）


def test_trigger_panel_overlay_lite_returns_unavailable(monkeypatch):
    from data_store import kv_repo
    monkeypatch.setattr(kv_repo, "set_", lambda *a, **k: None)
    monkeypatch.setattr(kv_repo, "get", lambda ns, key: None)

    from analysis import stock_analysis_suite as mod

    class _Chip:
        def analyze(self, code, df):
            return {"details": {"main_force_control": 70, "concentration_90": 15.9, "profit_ratio": 50}, "signals": []}

    class _Cap:
        def analyze(self, code, df):
            return {"details": {"order_analysis": {"main_net_inflow": -1e6, "retail_net_inflow": 6e5},
                                "positive_days_5d": 4}, "signals": []}

    class _Fundam:
        def __init__(self, code, minimal_api_mode=True): pass
        def get_comprehensive_data(self):
            return {"financial_indicators": {"pe": 4.8, "roe": 14.2}, "industry_comparison": {"pe_rank": 10.0}, "financial_reports": {"net_profit_yoy": 12.0}}

    monkeypatch.setattr(mod, "ChipAnalyzer", _Chip)
    monkeypatch.setattr(mod, "CapitalFlowAnalyzer", _Cap)
    monkeypatch.setattr(mod, "FundamentalDataCollector", _Fundam)

    suite = StockAnalysisSuite()
    suite._load_ohlcv = lambda code: _fake_ohlcv(120)  # type: ignore[attr-defined]
    called = []
    result = suite.trigger_panel_overlay("000001", tier="lite",
                                         llm_caller=lambda p: called.append(p) or (True, "{}"))
    assert called == []                                     # lite 不调 LLM
    assert result["success"] is False
    assert result["overlay"]["reviewed"] is False


# --- E4: 基本面假阴性修复（'N/A' 字符串毒丸 → 业绩维度被吞成「数据不足」）---


def test_performance_survives_na_roe_string():
    """真实采集器对 roe 返回 'N/A' 字符串；旧逻辑在 compute_performance_score
    里 `'N/A' >= 15` 抛 TypeError 被 except 吞成 _missing「数据不足」（E4 假阴性）。
    修复：消费侧把 'N/A'/非数值强制为 None，有真实净利同比时业绩维度应正常评分。"""
    suite = StockAnalysisSuite()
    inputs = {
        "fundamental": {
            "pe": 4.8,
            "roe": "N/A",            # 字符串毒丸（采集器历史默认值）
            "pe_industry_rank": None,
            "net_profit_yoy": 12.0,  # 真实净利同比 → 应可评分
        }
    }
    radar = suite._compute_radar(inputs)
    perf = radar["performance"]
    assert perf["score"] is not None
    assert "数据不足" not in perf["label"]


def test_performance_still_missing_when_all_na():
    """三项全为 'N/A'/None（确无基本面）时仍须「数据不足」，不得凭空造分（防过度纠正）。"""
    suite = StockAnalysisSuite()
    inputs = {"fundamental": {"pe": "N/A", "roe": "N/A",
                              "pe_industry_rank": "N/A", "net_profit_yoy": "N/A"}}
    radar = suite._compute_radar(inputs)
    assert radar["performance"]["score"] is None
    assert "数据不足" in radar["performance"]["label"]
