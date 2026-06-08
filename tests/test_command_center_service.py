import json
from webui.services.command_center_service import CommandCenterService


def _report(tmp_path):
    md = tmp_path / "opportunity_top10_20260608.md"
    md.write_text("# r", encoding="utf-8")
    (tmp_path / "opportunity_top10_20260608.signals.json").write_text(json.dumps([
        {"code": "603986", "risk_signals": {"rsi": 58, "chase": 30, "change_3d": 6,
         "sell_signals": 0, "quant_score": 62}, "sector_score": 50},
    ]), encoding="utf-8")
    return md


def test_overview_builds_matrix_from_report(tmp_path):
    md = _report(tmp_path)
    svc = CommandCenterService(
        load_report=lambda: {"items": [
            {"code": "603986", "name": "兆易创新", "score": 88, "rating": "S",
             "sector": "半导体"}], "market_env": "暖", "file": md.name,
            "report_path": str(md)},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {"hs300_ret_5d": 1, "advance": 3000, "decline": 1800,
                            "sentiment": 60},
        holdings=lambda: {"account": {"total_equity": 0}, "positions": [],
                          "max_drawdown": 0.0},
        quotes=lambda codes: {},
    )
    out = svc.overview()
    assert out["matrix"][0]["code"] == "603986"
    assert out["matrix"][0]["action"] == "重点出手"
    assert out["indices"]["opportunity"] >= 60
    assert "market_risk" in out["indices"]


def test_overview_degrades_when_no_report():
    svc = CommandCenterService(
        load_report=lambda: {"items": [], "market_env": "", "report_path": None},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {}, holdings=lambda: {"account": {}, "positions": [],
                                                 "max_drawdown": 0.0},
        quotes=lambda codes: {})
    out = svc.overview()
    assert out["matrix"] == []
    assert out["degraded"]["opportunity"] is True


def test_overview_marks_held_positions(tmp_path):
    md = _report(tmp_path)
    svc = CommandCenterService(
        load_report=lambda: {"items": [
            {"code": "603986", "name": "兆易创新", "score": 88, "rating": "S"}],
            "report_path": str(md)},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {"sentiment": 55},
        holdings=lambda: {"account": {"total_equity": 1_000_000},
                          "positions": [{"ts_code": "603986",
                                         "market_value": 400_000}],
                          "max_drawdown": 0.0},
        quotes=lambda codes: {})
    out = svc.overview()
    assert out["matrix"][0]["held"] is True
