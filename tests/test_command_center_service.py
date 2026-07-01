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
             "sector": "半导体", "sector_code": "BK1036"}], "market_env": "暖", "file": md.name,
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
    assert out["matrix"][0]["sector_code"] == "BK1036"
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


# ── 持仓 · 热点关联 payload + 逐源降级 ──────────────────────────

def _svc_with_positions(positions, *, hot_membership=None, news_index=None):
    return CommandCenterService(
        load_report=lambda: {"items": [], "report_path": None, "date": "2026-06-17"},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {"sentiment": 55},
        holdings=lambda: {"account": {"total_equity": 1_000_000},
                          "positions": positions, "max_drawdown": 0.0},
        quotes=lambda codes: {},
        hot_membership=hot_membership,
        news_index=news_index,
    )


def test_overview_holdings_relevance_panel():
    positions = [{"ts_code": "600519.SH", "name": "贵州茅台", "market_value": 100000}]
    svc = _svc_with_positions(
        positions,
        hot_membership=lambda date=None: {"600519": [
            {"board_name": "白酒", "board_code": "BK0001", "board_rank": 1,
             "stock_rank": 1, "lhb_hit": False, "snapshot_id": 7}]},
        news_index=lambda pos: {"600519": [{"platform": "金十快讯", "title": "茅台提价"}]},
    )
    out = svc.overview()
    rel = out["holdings_relevance"]
    assert rel and rel[0]["code"] == "600519"
    assert rel[0]["status"] == "踩中"
    assert rel[0]["boards"][0]["board_code"] == "BK0001"
    assert rel[0]["boards"][0]["snapshot_id"] == 7
    assert out["degraded"]["hot_sector"] is False
    assert out["degraded"]["news"] is False


def test_overview_holdings_relevance_degrades_per_source():
    positions = [{"ts_code": "600519", "name": "x", "market_value": 1}]

    def boom(*a, **k):
        raise RuntimeError("hot sector source down")

    svc = _svc_with_positions(
        positions, hot_membership=boom,                 # 板块源挂
        news_index=lambda pos: {"600519": [{"platform": "新浪快讯", "title": "t"}]})
    out = svc.overview()
    assert out["degraded"]["hot_sector"] is True        # 仅该面板降级
    assert out["degraded"]["news"] is False
    assert out["holdings_relevance"][0]["news_relevance"] == 35   # 资讯源仍生效
    assert "matrix" in out and "portfolio" in out       # 其余面板不受影响


def test_overview_holdings_relevance_default_sources_empty():
    # 未注入两源时不报错,持仓全「脱离」。
    svc = CommandCenterService(
        load_report=lambda: {"items": [], "report_path": None},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {},
        holdings=lambda: {"account": {}, "positions": [
            {"ts_code": "600000", "name": "浦发", "market_value": 5}], "max_drawdown": 0.0},
        quotes=lambda codes: {})
    out = svc.overview()
    assert out["holdings_relevance"][0]["status"] == "脱离"


# ── 东财热点新闻面板(撮合矩阵右栏) ──────────────────────────

def _svc_with_hot_news(hot_news):
    return CommandCenterService(
        load_report=lambda: {"items": [], "report_path": None, "date": "2026-06-19",
                             "file": "opportunity_top10_20260619_153102.md"},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {"sentiment": 55},
        holdings=lambda: {"account": {}, "positions": [], "max_drawdown": 0.0},
        quotes=lambda codes: {},
        hot_news=hot_news,
    )


def test_overview_includes_hot_news_payload():
    news = [
        {"rank": 1, "title": "热点A", "url": "http://x/1", "source": "东方财富",
         "publish_time": "2026-06-19 09:30", "heat": 95},
        {"rank": 2, "title": "热点B", "url": None, "source": "东方财富",
         "publish_time": "2026-06-19 10:00", "heat": 80},
    ]
    captured = {}

    def _hn(date=None, report_file=None):
        captured["date"] = date
        captured["report_file"] = report_file
        return news

    out = _svc_with_hot_news(_hn).overview()
    assert out["hot_news"] == news       # 原样、顺序不变
    assert out["degraded"]["hot_news"] is False
    assert captured["date"] == "2026-06-19"  # 按报告日期读取
    assert captured["report_file"] == "opportunity_top10_20260619_153102.md"


def test_overview_hot_news_degrades_independently():
    def boom(*a, **k):
        raise RuntimeError("hot news source down")

    out = _svc_with_hot_news(boom).overview()
    assert out["degraded"]["hot_news"] is True
    assert out["hot_news"] == []
    assert "matrix" in out and "portfolio" in out  # 其余面板不受影响


def test_overview_hot_news_default_empty():
    svc = CommandCenterService(
        load_report=lambda: {"items": [], "report_path": None},
        capital_rankings=lambda: {"rows": []},
        market_env=lambda: {},
        holdings=lambda: {"account": {}, "positions": [], "max_drawdown": 0.0},
        quotes=lambda codes: {})
    out = svc.overview()
    assert out["hot_news"] == []
    assert out["degraded"]["hot_news"] is False
