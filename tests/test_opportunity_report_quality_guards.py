import importlib
import sys


def _stock(code, name, score, degraded=False):
    quant = {"buy_count": 0, "sell_count": 0, "total_count": 0, "top_buy_models": []}
    if degraded:
        quant.update({"degraded": True, "error": "无历史数据"})
    return {
        "stock_code": code,
        "name": name,
        "passed": True,
        "final_score": score,
        "rating": "C",
        "scoring_result": {
            "total_score": score,
            "rating": "C",
            "degraded": degraded,
            "scores": {
                "quantitative": 0 if degraded else 55,
                "technical": 0 if degraded else 60,
                "sentiment": 70,
                "sector": 50,
                "fundamental": 50,
                "events": 50,
            },
            "details": {
                "quantitative": quant,
                "technical": {},
                "sentiment": {},
                "sector": {},
                "fundamental": {},
                "events": {},
                "price_changes": {},
            },
        },
    }


def test_report_generator_demotes_degraded_top_rows(tmp_path, monkeypatch):
    from scripts import opportunity_report_generator as mod

    gen = mod.OpportunityReportGenerator(output_dir=str(tmp_path))
    monkeypatch.setattr(gen, "_filter_st_analysis_results", lambda rows, context: rows)
    monkeypatch.setattr(gen, "_fetch_top_list", lambda *args, **kwargs: None)
    monkeypatch.setattr(gen, "_build_yesterday_recap", lambda *args, **kwargs: [])
    monkeypatch.setattr(gen, "_build_market_regime_alert", lambda *args, **kwargs: [])
    monkeypatch.setitem(
        sys.modules,
        "scripts.generate_xueqiu_article",
        type("FakeXueqiu", (), {"generate": staticmethod(lambda path: str(path) + ".xueqiu.md")}),
    )

    gen.generate_report([
        _stock("600519", "贵州茅台", 90, degraded=True),
        _stock("688111", "金山办公", 40, degraded=False),
    ])

    content = open(gen.latest_top_report_path, encoding="utf-8").read()
    assert content.index("<td>金山办公</td>") < content.index("<td>贵州茅台</td>")
    assert "本次有 1/2 只候选缺少有效历史行情数据" in content


def test_latest_opportunities_hides_fully_degraded_report(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    monkeypatch.setenv("KRONOS_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("KRONOS_DISABLE_TORCH", "1")
    sys.modules.pop("webui.core", None)
    core = importlib.import_module("webui.core")

    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report = results_dir / "opportunity_top10_20260611_232713.md"
    report.write_text(
        "## 综合排名 TOP20\n"
        "<table><tbody>\n"
        "<tr><td>1</td><td>600519</td><td>贵州茅台</td><td>50.39</td>"
        "<td>【概览】评级C；【量化】买0/卖0/总0，0分，⚠️数据降级；【入选原因】测试</td></tr>\n"
        "</tbody></table>\n",
        encoding="utf-8",
    )

    parsed = core._parse_opportunity_report(report)
    assert parsed["all_degraded"] is True
    assert parsed["items"][0]["degraded"] is True

    payload = core._load_latest_opportunities()
    assert payload["latest_report"]["file"] == report.name
    assert payload["latest_report"]["all_degraded"] is True
    assert payload["items"] == []
    assert "已隐藏诊断性 Top 榜" in payload["empty_reason"]
