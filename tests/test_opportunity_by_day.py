"""Part C 投资机会画布按日 + Part D 作战大屏按日 后端行为。

C: /api/opportunity-canvas 的核心 opportunity_canvas_payload + _hot_sector_snapshot_for_date。
D: command_center_overview 按日聚合(当日全部报告去重)+ available_dates + sidecar 合并。
纯逻辑用 monkeypatch 隔离 I/O;DB 相关走临时库。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from data_store.schema import migrate
from webui.services.command_center_service import CommandCenterService


# --------------------------- Part D: CommandCenterService 层 ---------------------------

def _write_report(tmp_path, name, signals):
    md = tmp_path / name
    md.write_text("# r", encoding="utf-8")
    side = tmp_path / name.replace(".md", ".signals.json")
    side.write_text(json.dumps(signals), encoding="utf-8")
    return md


def test_service_merges_multiple_sidecars_and_report_count(tmp_path):
    r_am = _write_report(tmp_path, "opportunity_top10_20260610_090000.md", [
        {"code": "600000", "risk_signals": {"rsi": 50, "chase": 20}, "sector_score": 40},
    ])
    r_pm = _write_report(tmp_path, "opportunity_top10_20260610_150000.md", [
        {"code": "300750", "risk_signals": {"rsi": 70, "chase": 60}, "sector_score": 66},
    ])
    report = {
        "items": [
            {"code": "600000", "name": "浦发银行", "score": 80, "rating": "A"},
            {"code": "300750", "name": "宁德时代", "score": 88, "rating": "S"},
        ],
        "report_paths": [str(r_pm), str(r_am)],
        "date": "2026-06-10",
        "report_count": 2,
        "file": r_pm.name,
    }
    svc = CommandCenterService(
        load_report=lambda: {"items": []},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {"sentiment": 55},
        holdings=lambda: {"account": {}, "positions": [], "max_drawdown": 0.0},
        quotes=lambda codes: {})
    out = svc.overview(report=report, available_dates=["2026-06-10", "2026-06-09"])
    assert out["as_of"]["date"] == "2026-06-10"
    assert out["as_of"]["report_count"] == 2
    assert out["as_of"]["sidecar"] is True
    assert out["available_dates"] == ["2026-06-10", "2026-06-09"]
    by_code = {m["code"]: m for m in out["matrix"]}
    assert set(by_code) == {"600000", "300750"}  # 两份报告各自的票都进了 matrix


def test_service_backward_compatible_single_report_path(tmp_path):
    r = _write_report(tmp_path, "opportunity_top10_20260610_150000.md", [
        {"code": "600000", "risk_signals": {"rsi": 50}, "sector_score": 40}])
    svc = CommandCenterService(
        load_report=lambda: {"items": [{"code": "600000", "name": "浦发银行", "score": 80}],
                             "report_path": str(r), "file": r.name},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {},
        holdings=lambda: {"account": {}, "positions": [], "max_drawdown": 0.0},
        quotes=lambda codes: {})
    out = svc.overview()  # 旧调用法:不注入 report,走 load_report + 单 report_path
    assert out["matrix"][0]["code"] == "600000"
    assert out["as_of"]["sidecar"] is True
    assert out["available_dates"] == []


# --------------------------- Part D: core 聚合层 ---------------------------

def test_command_center_report_aggregates_day(monkeypatch, tmp_path):
    import webui.core as core
    files = [
        tmp_path / "opportunity_top10_20260610_150000.md",
        tmp_path / "opportunity_top10_20260610_090000.md",
        tmp_path / "opportunity_top10_20260609_150000.md",
    ]
    monkeypatch.setattr(core, "_latest_primary_opportunity_reports", lambda limit=1: files[:limit])
    parsed_map = {
        "opportunity_top10_20260610_150000.md": {
            "file": "opportunity_top10_20260610_150000.md", "market_env": "下午暖",
            "items": [{"code": "600000", "score": 70}, {"code": "300750", "score": 88}]},
        "opportunity_top10_20260610_090000.md": {
            "file": "opportunity_top10_20260610_090000.md", "market_env": "上午",
            "items": [{"code": "600000", "score": 85}, {"code": "002594", "score": 60}]},
        "opportunity_top10_20260609_150000.md": {
            "file": "opportunity_top10_20260609_150000.md", "market_env": "昨天",
            "items": [{"code": "600000", "score": 99}]},
    }
    monkeypatch.setattr(core, "_parse_opportunity_report", lambda p: parsed_map[Path(p).name])

    rep = core._command_center_report()  # 默认最近一天 = 2026-06-10
    assert rep["date"] == "2026-06-10"
    assert rep["report_count"] == 2
    by_code = {i["code"]: i for i in rep["items"]}
    assert set(by_code) == {"600000", "300750", "002594"}
    assert by_code["600000"]["score"] == 85  # 同日去重取最高(09:00=85 > 15:00=70),不含昨日 99
    assert rep["market_env"] == "下午暖"  # 取当日最新一份报告的 env
    assert rep["items"][0]["code"] == "300750"  # 按分降序,88 居首
    assert len(rep["report_paths"]) == 2


def test_command_center_report_specific_date_and_fallback(monkeypatch, tmp_path):
    import webui.core as core
    files = [tmp_path / "opportunity_top10_20260610_150000.md",
             tmp_path / "opportunity_top10_20260609_150000.md"]
    monkeypatch.setattr(core, "_latest_primary_opportunity_reports", lambda limit=1: files[:limit])
    monkeypatch.setattr(core, "_parse_opportunity_report",
                        lambda p: {"file": Path(p).name, "market_env": "",
                                   "items": [{"code": "600000", "score": 50}]})
    rep = core._command_center_report("2026-06-09")
    assert rep["date"] == "2026-06-09"
    assert rep["report_count"] == 1
    rep2 = core._command_center_report("2025-01-01")  # 不存在的日 → 回退最近一天
    assert rep2["date"] == "2026-06-10"


def test_available_dates_distinct_newest_first(monkeypatch, tmp_path):
    import webui.core as core
    files = [tmp_path / "opportunity_top10_20260610_150000.md",
             tmp_path / "opportunity_top10_20260610_090000.md",
             tmp_path / "opportunity_top10_20260609_150000.md"]
    monkeypatch.setattr(core, "_latest_primary_opportunity_reports", lambda limit=1: files[:limit])
    assert core._command_center_available_dates() == ["2026-06-10", "2026-06-09"]


def test_primary_report_date_parsing():
    import webui.core as core
    assert core._primary_report_date("opportunity_top10_20260610_153102.md") == "2026-06-10"
    assert core._primary_report_date("opportunity_top10_xueqiu_20260610_153102.md") is None
    assert core._primary_report_date("foo.md") is None


# --------------------------- Part C: 画布按日 ---------------------------

def test_opportunity_canvas_payload_run_not_found(monkeypatch):
    import webui.core as core
    from data_store import opportunity_repo
    monkeypatch.setattr(opportunity_repo, "get_run", lambda rid: None)
    monkeypatch.setattr(opportunity_repo, "latest_run", lambda: None)
    monkeypatch.setattr(opportunity_repo, "list_runs", lambda **k: [])
    assert core.opportunity_canvas_payload(run_id=123) is None
    assert core.opportunity_canvas_payload(date="2099-01-01") is None
    assert core.opportunity_canvas_payload() is None


def test_opportunity_canvas_payload_by_run_id_shape(monkeypatch):
    import webui.core as core
    from data_store import opportunity_repo
    run = {"id": 7, "report_file": "", "run_at": "2026-06-10T15:00:00",
           "run_date": "2026-06-10", "source": "multi", "mode": "scan",
           "item_count": 2, "extra_json": None}
    monkeypatch.setattr(opportunity_repo, "get_run", lambda rid: run if int(rid) == 7 else None)
    monkeypatch.setattr(core, "_load_opportunity_run_payload",
                        lambda run_id=None, report_file=None: {
                            "run": run,
                            "items": [{"code": "600000", "degraded": False},
                                      {"code": "300750", "degraded": True}]})
    monkeypatch.setattr(core, "_hot_sector_snapshot_for_date", lambda d=None: None)
    monkeypatch.setattr(core, "_build_opportunity_canvas",
                        lambda items, lr=None, me="", hs=None: {"nodes": [], "n": len(items)})
    out = core.opportunity_canvas_payload(run_id=7)
    assert out is not None
    assert out["run"]["id"] == 7
    assert out["run"]["source"] == "multi"
    assert out["date"] == "2026-06-10"
    assert out["degraded_count"] == 1  # 300750 degraded
    assert out["canvas"]["n"] == 2
    assert out["hot_sector"] is None


def test_opportunity_canvas_payload_by_date_picks_latest_run(monkeypatch):
    import webui.core as core
    from data_store import opportunity_repo
    run = {"id": 9, "report_file": "", "run_at": "2026-06-10T15:00:00",
           "run_date": "2026-06-10", "source": "heat", "mode": "scan",
           "item_count": 1, "extra_json": None}
    captured = {}
    def _list_runs(run_date=None, limit=50):
        captured["run_date"] = run_date
        captured["limit"] = limit
        return [run]
    monkeypatch.setattr(opportunity_repo, "list_runs", _list_runs)
    monkeypatch.setattr(opportunity_repo, "get_run", lambda rid: run)
    monkeypatch.setattr(core, "_load_opportunity_run_payload",
                        lambda run_id=None, report_file=None: {"run": run, "items": [{"code": "600000"}]})
    monkeypatch.setattr(core, "_hot_sector_snapshot_for_date", lambda d=None: None)
    monkeypatch.setattr(core, "_build_opportunity_canvas",
                        lambda items, lr=None, me="", hs=None: {"n": len(items)})
    out = core.opportunity_canvas_payload(date="2026-06-10")
    assert out["run"]["id"] == 9
    assert captured["run_date"] == "2026-06-10"
    assert captured["limit"] == 1  # 当日最新一条


# --------------------------- Part C: 热门板块按日匹配 ---------------------------

@pytest.fixture
def hs_conn(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "k.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)
    getter = lambda: c  # noqa: E731
    from data_store import connection, hot_sector_repo
    monkeypatch.setattr(connection, "get_conn", getter)
    monkeypatch.setattr(hot_sector_repo, "get_conn", getter)
    yield c
    c.close()


def test_hot_sector_snapshot_for_date_exact_and_nearest(hs_conn):
    import webui.core as core
    from data_store import hot_sector_repo as repo
    s_old = repo.save_snapshot(boards=[{"code": "B1", "name": "半导体"}], stocks=[], relations=[],
                               meta={"created_at": "2026-06-08T10:00:00", "trade_date": "2026-06-08"})
    s_new = repo.save_snapshot(boards=[{"code": "B1", "name": "半导体"}], stocks=[], relations=[],
                               meta={"created_at": "2026-06-10T10:00:00", "trade_date": "2026-06-10"})

    assert core._hot_sector_snapshot_for_date("2026-06-08")["snapshot"]["id"] == s_old  # 精确
    assert core._hot_sector_snapshot_for_date("2026-06-09")["snapshot"]["id"] == s_old  # 回退最近 <=
    assert core._hot_sector_snapshot_for_date("2026-06-30")["snapshot"]["id"] == s_new  # 晚于全部→最近
    assert core._hot_sector_snapshot_for_date("2026-01-01") is None  # 早于全部→无
    assert core._hot_sector_snapshot_for_date(None)["snapshot"]["id"] == s_new  # 空→最新
