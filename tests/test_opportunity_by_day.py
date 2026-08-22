"""Part C 投资机会画布按日 + Part D 作战大屏按日 后端行为。

C: /api/opportunity-canvas 的核心 opportunity_canvas_payload + _hot_sector_snapshot_for_date。
D: command_center_overview 按日聚合 + available_dates。**数据源 = SQLite
   opportunity_run/opportunity_item**(不再解析 markdown 报告与 .signals.json 旁挂文件)。
纯逻辑用 monkeypatch 隔离 I/O;DB 相关走临时库。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from data_store.schema import migrate
from webui.services.command_center_service import CommandCenterService


# --------------------------- Part D: CommandCenterService 层 ---------------------------

def test_service_builds_matrix_from_item_signals():
    """风险信号随 item 从 SQLite 带下来,服务层不再读任何旁挂文件。"""
    report = {
        "items": [
            {"code": "600000", "name": "浦发银行", "score": 80, "rating": "A",
             "signals": {"rsi": 50, "chase": 20, "sector_score": 40}},
            {"code": "300750", "name": "宁德时代", "score": 88, "rating": "S",
             "signals": {"rsi": 70, "chase": 60, "sector_score": 66}},
        ],
        "date": "2026-06-10",
        "report_count": 2,
        "file": "opportunity_top10_20260610_150000.md",
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
    assert out["as_of"]["sidecar"] is True          # 结构化信号已加载
    assert out["available_dates"] == ["2026-06-10", "2026-06-09"]
    by_code = {m["code"]: m for m in out["matrix"]}
    assert set(by_code) == {"600000", "300750"}
    # 信号真正参与打分:追高60+RSI70 的票风险必须高于 RSI50/追高20 的票
    assert by_code["300750"]["risk"] > by_code["600000"]["risk"]
    assert by_code["600000"]["risk_unknown"] is False


def test_service_marks_risk_unknown_without_signals():
    """items 没带 signals(旧 run 未入库信号)→ 风险未知,不崩、不臆造。"""
    svc = CommandCenterService(
        load_report=lambda: {"items": [{"code": "600000", "name": "浦发银行", "score": 80}],
                             "file": "x.md", "date": "2026-06-10"},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {},
        holdings=lambda: {"account": {}, "positions": [], "max_drawdown": 0.0},
        quotes=lambda codes: {})
    out = svc.overview()
    assert out["matrix"][0]["risk_unknown"] is True
    assert out["as_of"]["sidecar"] is False


# --------------------------- Part D: core 聚合层(SQLite) ---------------------------

@pytest.fixture
def opp_conn(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "opp.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)
    getter = lambda: c  # noqa: E731
    from data_store import connection, opportunity_repo
    monkeypatch.setattr(connection, "get_conn", getter)
    monkeypatch.setattr(opportunity_repo, "get_conn", getter)
    yield c
    c.close()


def _no_markdown(monkeypatch):
    """守卫:大屏链路一旦回去解析 markdown 报告就让测试失败。"""
    import webui.core as core
    monkeypatch.setattr(core, "_parse_opportunity_report",
                        lambda p: pytest.fail("大屏不应解析 markdown 报告,数据源是 SQLite"))
    monkeypatch.setattr(core, "_latest_primary_opportunity_reports",
                        lambda limit=1: pytest.fail("大屏不应扫描报告目录"))


def _save_run(run_at, items, report_file=None):
    from data_store import opportunity_repo
    return opportunity_repo.save_run(
        {"run_at": run_at, "run_date": run_at[:10], "source": "multi",
         "report_file": report_file}, items)


def _item(code, score, *, sector="半导体", sector_score=50.0, rsi=55.0, rating="A"):
    return {"code": code, "name": f"股{code}", "total_score": score, "rating": rating,
            "sector": sector, "sector_code": "BK1036",
            "scores": {"sector": sector_score},
            "signals": {"rsi": rsi, "chase": 20.0, "change_3d": 3.0,
                        "sell_signals": 0.0, "quant_score": 60.0}}


def test_command_center_report_aggregates_day_from_sqlite(opp_conn, monkeypatch):
    import webui.core as core
    _no_markdown(monkeypatch)
    _save_run("2026-06-10T09:00:00", [_item("600000", 85), _item("002594", 60)],
              report_file="opportunity_top10_20260610_090000.md")
    _save_run("2026-06-10T15:00:00", [_item("600000", 70), _item("300750", 88)],
              report_file="opportunity_top10_20260610_150000.md")
    _save_run("2026-06-09T15:00:00", [_item("600000", 99)],
              report_file="opportunity_top10_20260609_150000.md")

    rep = core._command_center_report()  # 默认最近一天 = 2026-06-10

    assert rep["date"] == "2026-06-10"
    assert rep["report_count"] == 2                       # 当日两次 run
    by_code = {i["code"]: i for i in rep["items"]}
    assert set(by_code) == {"600000", "300750", "002594"}
    assert by_code["600000"]["score"] == 85               # 同日去重取最高,不含昨日 99
    assert rep["items"][0]["code"] == "300750"            # 按分降序
    assert rep["file"] == "opportunity_top10_20260610_150000.md"  # 当日最新一次 run
    # 风险信号 + 板块拥挤度分随 item 下发(供 CommandCenterService 直接消费)
    sig = by_code["300750"]["signals"]
    assert sig["rsi"] == 55.0 and sig["sector_score"] == 50.0


def test_command_center_report_caps_at_top_n(opp_conn, monkeypatch):
    """一次 run 存的是全量候选(数百只);大屏只取前 COMMAND_CENTER_TOP_N 名。"""
    import webui.core as core
    _no_markdown(monkeypatch)
    _save_run("2026-06-10T15:00:00",
              [_item(f"60{i:04d}", 90 - i) for i in range(core.COMMAND_CENTER_TOP_N + 15)])

    rep = core._command_center_report()

    assert len(rep["items"]) == core.COMMAND_CENTER_TOP_N
    assert rep["items"][0]["score"] == 90                  # 头部保留
    assert rep["items"][-1]["score"] == 90 - (core.COMMAND_CENTER_TOP_N - 1)


def test_command_center_report_specific_date_and_fallback(opp_conn, monkeypatch):
    import webui.core as core
    _no_markdown(monkeypatch)
    _save_run("2026-06-09T15:00:00", [_item("600000", 50)])
    _save_run("2026-06-10T15:00:00", [_item("300750", 80)])

    rep = core._command_center_report("2026-06-09")
    assert rep["date"] == "2026-06-09"
    assert [i["code"] for i in rep["items"]] == ["600000"]

    rep2 = core._command_center_report("2025-01-01")   # 无 run 的日 → 回退最近一天
    assert rep2["date"] == "2026-06-10"


def test_command_center_report_empty_store(opp_conn, monkeypatch):
    import webui.core as core
    _no_markdown(monkeypatch)
    rep = core._command_center_report()
    assert rep["items"] == [] and rep["date"] is None and rep["report_count"] == 0


def test_available_dates_from_sqlite_runs(opp_conn, monkeypatch):
    import webui.core as core
    _no_markdown(monkeypatch)
    _save_run("2026-06-09T15:00:00", [_item("600000", 50)])
    _save_run("2026-06-10T09:00:00", [_item("600000", 50)])
    _save_run("2026-06-10T15:00:00", [_item("300750", 80)])

    assert core._command_center_available_dates() == ["2026-06-10", "2026-06-09"]


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
