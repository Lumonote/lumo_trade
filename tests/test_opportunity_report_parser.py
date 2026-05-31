import importlib
import sys


def _load_webui_core(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    monkeypatch.setenv("KRONOS_DISABLE_TORCH", "1")
    sys.modules.pop("webui.core", None)
    module = importlib.import_module("webui.core")
    return module


def test_latest_opportunity_report_parser_handles_generated_html_table(tmp_path, monkeypatch):
    module = _load_webui_core(tmp_path, monkeypatch)
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report = results_dir / "opportunity_top10_20260521_101500.md"
    report.write_text(
        """
## 风险提示
<p>⚠️ <strong>今日候选质量偏低</strong></p>

## 综合排名 TOP20
<table>
<thead><tr><th>排名</th><th>代码</th><th>股票名称</th><th>综合得分</th><th>详细分析</th></tr></thead>
<tbody>
<tr><td>1</td><td>603005</td><td>晶方科技</td><td>83.25</td><td>【概览】评级A，建议：可关注；【板块】半导体(+3.2%, 强势领涨, 82分)；【量化】买2/卖0/总2(—)，75分，模型[RSI,MACD]；【技术】RSI:55，MACD:金叉；【情绪资金】情绪:中性；【关键加减分】量价改善；【入选原因】半导体板块走强</td></tr>
</tbody></table>
""",
        encoding="utf-8",
    )

    payload = module._load_latest_opportunities()

    assert payload["latest_report"]["file"] == report.name
    assert payload["market_env"] == "今日候选质量偏低"
    assert payload["stats"]["total"] == 1
    assert payload["stats"]["strong_count"] == 1
    assert payload["items"][0]["code"] == "603005"
    assert payload["items"][0]["sector"] == "半导体"
    assert payload["items"][0]["quant_models"] == ["RSI", "MACD"]
    assert [item["name"] for item in payload["quant_models"]] == ["RSI", "MACD"]


def test_stock_dashboard_route_survives_existing_report(tmp_path, monkeypatch):
    _load_webui_core(tmp_path, monkeypatch)
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "opportunity_top10_20260521_101600.md").write_text(
        "| 排名 | 代码 | 股票名称 | 综合得分 | 详细分析 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 1 | 600519 | 贵州茅台 | 42.5 | 【概览】评级C，建议：观望；【入选原因】测试 |\n",
        encoding="utf-8",
    )

    from robyn.testing import TestClient

    sys.modules.pop("webui.robyn_app", None)
    robyn_module = importlib.import_module("webui.robyn_app")

    with TestClient(robyn_module.app) as client:
        response = client.get("/api/stock-dashboard")

    assert response.status_code == 200
    assert response.json()["opportunity"]["items"][0]["code"] == "600519"
