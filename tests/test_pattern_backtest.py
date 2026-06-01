"""同类图形回测引擎的离线单测（注入假 fetch，不联网）。"""

import math

import pytest

from analysis.pattern_backtest import (
    backtest_patterns,
    parse_close_series,
    scan_series,
)


def _klines(closes):
    """构造 Sina 风格的日 K 列表（按时间升序，仅 close 有效）。"""
    out = []
    for idx, close in enumerate(closes, start=1):
        out.append({
            "day": f"2026-01-{idx:02d}",
            "open": str(close),
            "high": str(close),
            "low": str(close),
            "close": str(close),
            "volume": "100",
        })
    return out


def _ramp(start, length, step=1.0):
    return [float(start) + step * i for i in range(length)]


# --------------------------------------------------------------------------- #
# parse_close_series
# --------------------------------------------------------------------------- #

def test_parse_close_series_handles_dict_list_and_csv():
    klines = [
        {"day": "2026-01-01", "close": "10.5"},
        ["2026-01-02", "10.0", "11.0", "11.5", "9.8", "100"],  # [date,open,close,high,low,vol]
        "2026-01-03,10,12,13,11",                               # csv: date,open,close,...
        {"day": "bad", "close": "0"},                            # 收盘 0 → 丢弃
    ]
    closes = parse_close_series(klines)
    assert closes == [10.5, 11.0, 12.0]


# --------------------------------------------------------------------------- #
# scan_series
# --------------------------------------------------------------------------- #

def test_scan_series_single_hit_has_exact_forward_return():
    closes = _ramp(10, 40)  # 10,11,...,49
    query = list(range(10))  # 上升形态
    # min_gap 取超大值，命中后直接跳出 → 只保留首个命中，结果确定。
    samples = scan_series(
        closes,
        query,
        window_days=10,
        horizons=(5,),
        similarity_threshold=0.85,
        min_gap_days=1000,
    )
    assert len(samples) == 1
    sample = samples[0]
    assert sample["end_index"] == 9
    # 窗口末日收盘=closes[9]=19, 后5日=closes[14]=24 → 5/19
    assert math.isclose(sample["returns"][5], 24.0 / 19.0 - 1.0, rel_tol=1e-9)
    assert sample["similarity"] >= 0.85


def test_scan_series_rejects_opposite_shape():
    closes = _ramp(50, 40, step=-1.0)  # 严格下跌
    query = list(range(10))            # 上升形态 → pearson 负 → 不命中
    samples = scan_series(closes, query, window_days=10, horizons=(5,), similarity_threshold=0.85)
    assert samples == []


def test_scan_series_skips_flat_windows():
    closes = [20.0] * 40  # 全平 → normalize_curve 返回 None
    query = list(range(10))
    samples = scan_series(closes, query, window_days=10, horizons=(5,), similarity_threshold=0.5)
    assert samples == []


# --------------------------------------------------------------------------- #
# backtest_patterns (注入 fetch，离线)
# --------------------------------------------------------------------------- #

def test_backtest_patterns_aggregates_across_candidates():
    series = {
        "sh600001": _ramp(10, 60),  # 长 → 10 个命中
        "sz000002": _ramp(10, 30),  # 短 → 4 个命中
    }

    def fake_fetch(symbol, limit):
        return "名称", _klines(series[symbol])

    candidates = [
        {"stock_code": "600001", "stock_name": "甲", "symbol": "sh600001"},
        {"stock_code": "000002", "stock_name": "乙", "symbol": "sz000002"},
    ]
    result = backtest_patterns(
        query_curve=list(range(10)),
        candidates=candidates,
        fetch_klines=fake_fetch,
        window_days=10,
        horizons=(5,),
        similarity_threshold=0.85,
        history_days=250,
        min_gap_days=5,
    )

    assert result["ok"] is True
    assert result["candidates_total"] == 2
    assert result["candidates_scanned"] == 2
    assert result["sample_count"] == 14
    assert result["errors"] == []

    assert len(result["horizons"]) == 1
    h5 = result["horizons"][0]
    assert h5["horizon"] == 5
    assert h5["count"] == 14
    assert h5["win_rate"] == 1.0      # 全程上升 → 全胜
    assert h5["avg_return"] > 0
    assert h5["best"] > 0 and h5["worst"] > 0

    # 命中最多的股票排在前面
    assert result["top_stocks"][0]["stock_code"] == "600001"
    assert result["top_stocks"][0]["count"] == 10
    assert result["top_stocks"][1]["stock_code"] == "000002"
    assert result["top_stocks"][1]["count"] == 4


def test_backtest_patterns_records_fetch_errors_but_keeps_going():
    def fake_fetch(symbol, limit):
        if symbol == "sh600003":
            raise RuntimeError("网络超时")
        return "名称", _klines(_ramp(10, 60))

    candidates = [
        {"stock_code": "600001", "stock_name": "甲", "symbol": "sh600001"},
        {"stock_code": "600003", "stock_name": "丙", "symbol": "sh600003"},
    ]
    result = backtest_patterns(
        query_curve=list(range(10)),
        candidates=candidates,
        fetch_klines=fake_fetch,
        window_days=10,
        horizons=(5,),
        similarity_threshold=0.85,
        min_gap_days=5,
    )

    assert result["ok"] is True
    assert result["candidates_scanned"] == 1
    assert any(e["stock_code"] == "600003" for e in result["errors"])
    assert result["sample_count"] > 0


def test_backtest_patterns_empty_candidates_is_not_ok():
    result = backtest_patterns(
        query_curve=list(range(10)),
        candidates=[],
        fetch_klines=lambda s, l: ("", []),
    )
    assert result["ok"] is False
    assert "error" in result


def test_backtest_patterns_rejects_short_query():
    result = backtest_patterns(
        query_curve=[1.0],
        candidates=[{"stock_code": "600001", "symbol": "sh600001"}],
        fetch_klines=lambda s, l: ("", []),
    )
    assert result["ok"] is False


# --------------------------------------------------------------------------- #
# PatternSearchService 接线（离线，注入 fetch）
# --------------------------------------------------------------------------- #

def test_service_backtest_params_validates_and_normalizes(tmp_path):
    from webui.services.pattern_search_service import PatternSearchService

    service = PatternSearchService(tmp_path / "patterns.sqlite")

    _params, error = service.backtest_params({"curve": [1, 2, 3]})
    assert error and "curve 必须" in error

    params, error = service.backtest_params({
        "curve": list(range(30)),
        "stock_codes": ["SH600001", "600001", "000002.SZ", "bad"],
        "top_n": 999,
        "similarity_threshold": 5.0,
    })
    assert error is None
    assert params["stock_codes"] == ["600001", "000002"]  # 去重 + 规范化 + 丢弃非法
    assert params["top_n"] == 50                            # 上限封顶
    assert params["similarity_threshold"] == 0.99           # 上限封顶


def test_service_backtest_with_explicit_codes_uses_injected_fetch(tmp_path):
    from webui.services.pattern_search_service import PatternSearchService

    service = PatternSearchService(tmp_path / "patterns.sqlite")
    params, error = service.backtest_params({
        "curve": list(range(30)),
        "stock_codes": ["600001", "000002"],
        "window_days": 10,
    })
    assert error is None

    def fake_fetch(symbol, limit):
        return "名称", _klines(_ramp(10, 60))

    result = service.backtest(params, fetch_klines=fake_fetch)
    assert result["ok"] is True
    assert result["candidates_scanned"] == 2
    assert result["sample_count"] > 0
    assert result["query_curve"]                       # 回传查询曲线供前端绘制
    assert {h["horizon"] for h in result["horizons"]} == {5, 10, 20}

