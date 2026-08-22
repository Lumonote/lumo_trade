import importlib
import sys

import pytest


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


def test_backtest_score_bins_match_health_tiers():
    """报告「历史回测表现」分档必须与桌面「报告与健康」置信度档位一致
    (S≥85 / A 78-85 / B 70-78 / C<70),否则两处胜率/收益无法对数。"""
    from scripts import opportunity_report_generator as mod
    from webui.services import scoring_health_service as health

    bins = [(low, high) for low, high, _label, _color in mod.BACKTEST_SCORE_BINS]
    assert bins == [(85, 999), (78, 85), (70, 78), (0, 70)]
    assert health.TIER_THRESHOLDS == ((85.0, "S"), (78.0, "A"), (70.0, "B"))


def test_backtest_annualized_chains_report_days_geometrically():
    """报告「年化估算」与健康页「滚动年化」同口径:
    同一报告日的多只推荐取算术均值(等权组合),跨报告日几何链乘复利。
    旧实现把跨日样本混在一起取算术均值再 ^50.4,会系统性高估。
    """
    import math

    import pandas as pd

    from analysis.backtest_metrics import ANNUAL_CYCLES, annualize_cycle_return
    from scripts import opportunity_report_generator as mod

    subset = pd.DataFrame([
        {"report_date": "2026-05-06", "return_5d": 12.0},
        {"report_date": "2026-05-06", "return_5d": 8.0},   # 当日组合 = +10%
        {"report_date": "2026-05-07", "return_5d": -10.0},  # 当日组合 = -10%
    ])

    got = mod.backtest_annualized_return(subset)

    log_g = (2 * math.log(1.10) + 1 * math.log(0.90)) / 3
    assert got == pytest.approx((math.exp(log_g * ANNUAL_CYCLES) - 1) * 100, abs=1e-2)
    # 旧算术口径:mean(12,8,-10)=3.33% → 年化 +420%,必须已被淘汰
    assert got < annualize_cycle_return(10.0 / 3)


def test_backtest_annualized_handles_empty_and_missing_returns():
    import pandas as pd

    from scripts import opportunity_report_generator as mod

    assert mod.backtest_annualized_return(pd.DataFrame(columns=["report_date", "return_5d"])) is None
    frame = pd.DataFrame([{"report_date": "2026-05-06", "return_5d": None}])
    assert mod.backtest_annualized_return(frame) is None
