"""机会挖掘形态回测(item H):_opportunity_pattern_backtest 自回测打分逻辑。

用合成日K + 注入 fetch_klines 隔离网络;用 monkeypatch 的 opportunity_repo 提供 run/items。
"""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def core(monkeypatch):
    import webui.core as core

    run = {"id": 5, "run_at": "2026-06-10T15:00:00", "run_date": "2026-06-10"}
    items = [
        {"code": "600000", "name": "浦发银行", "rating": "A", "total_score": 80},
        {"code": "000001", "name": "平安银行", "rating": "B", "total_score": 72},
    ]
    from data_store import opportunity_repo
    monkeypatch.setattr(opportunity_repo, "get_run", lambda rid: run if int(rid) == 5 else None)
    monkeypatch.setattr(opportunity_repo, "latest_run", lambda: run)
    monkeypatch.setattr(opportunity_repo, "list_runs", lambda **k: [run])
    monkeypatch.setattr(opportunity_repo, "items_for_run", lambda rid: items)
    return core


def _wave_klines(n=300):
    # 造一段有重复形态的正弦+上行趋势收盘序列,保证 scan_series 能命中并有前向收益
    return [{"close": round(100 + 0.05 * i + 5 * math.sin(i / 6.0), 3)} for i in range(n)]


def test_opportunity_pattern_backtest_scores(core):
    fake = lambda symbol, limit=250: ("名称", _wave_klines(300))
    out = core._opportunity_pattern_backtest({"run_id": 5, "top_n": 2, "window_days": 20},
                                             fetch_klines=fake)
    assert out["ok"] is True
    assert out["total"] == 2
    assert out["scanned"] == 2
    assert len(out["rows"]) == 2
    r = out["rows"][0]
    assert r["code"] in {"600000", "000001"}
    assert "pattern_score" in r and "win_rate" in r and "avg_return" in r
    assert "horizons" in r and "10" in r["horizons"]
    # rows 按 pattern_score 降序(None 沉底)
    scores = [(x.get("pattern_score") if x.get("pattern_score") is not None else -1) for x in out["rows"]]
    assert scores == sorted(scores, reverse=True)


def test_opportunity_pattern_backtest_insufficient_history(core):
    fake = lambda symbol, limit=250: ("名称", _wave_klines(20))  # 太短
    out = core._opportunity_pattern_backtest({"run_id": 5, "top_n": 2, "window_days": 30},
                                             fetch_klines=fake)
    assert out["ok"] is True
    assert all(r["pattern_score"] is None for r in out["rows"])
    assert all(r.get("note") == "历史数据不足" for r in out["rows"])
    assert out["scanned"] == 0


def test_opportunity_pattern_backtest_no_run(core, monkeypatch):
    from data_store import opportunity_repo
    monkeypatch.setattr(opportunity_repo, "get_run", lambda rid: None)
    monkeypatch.setattr(opportunity_repo, "latest_run", lambda: None)
    out = core._opportunity_pattern_backtest({"top_n": 2}, fetch_klines=lambda s, limit=250: ("", []))
    assert out["ok"] is False
