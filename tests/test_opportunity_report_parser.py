import importlib
import sys


def _load_webui_core(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    # configuration_service does os.environ.setdefault("KRONOS_RESULTS_DIR", ...)
    # on first import, which pins results_dir() to the first tmp dir and breaks
    # re-import isolation across tests. Align it explicitly with this tmp dir.
    monkeypatch.setenv("KRONOS_RESULTS_DIR", str(tmp_path / "results"))
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


_RICH_DETAIL = (
    "【概览】评级S，建议：🌟 强烈推荐；"
    "【涨幅】当日:+7.38%，3日:+8.28%，5日:+4.39%；"
    "【板块】软件服务(—, 市场震荡, 50分)；"
    "【量化】买6/卖1/总30(20%)，97分，模型[机器学习RF, 资金趋势]；"
    "【技术】RSI:45.79，MACD:死叉，布林:中轨上方，54分；"
    "【基本面】营收:+23.9%，利润:+445.0%，35分；"
    "【情绪资金】情绪:中性，60分；"
    "【消息】评级:中性，利好0/利空0，50分；"
    "【关键加减分】牛股动量识别: 放量上涨2日:+5 (总+5分)；"
    "【入选原因】综合评级S级(强烈推荐)；"
    "【最新动态】金山办公软件激励计划自查报告；"
    "【高级】追高风险: 🟢 低(0分) 高级评分: 56.9分"
)


def _write_rich_report(results_dir, name="opportunity_top10_20260604_212907.md"):
    report = results_dir / name
    report.write_text(
        "## 综合排名 TOP20\n"
        "<table>\n"
        "<thead><tr><th>排名</th><th>代码</th><th>股票名称</th><th>综合得分</th><th>详细分析</th></tr></thead>\n"
        "<tbody>\n"
        f"<tr><td>3</td><td>688111</td><td>金山办公</td><td>87.08</td><td>{_RICH_DETAIL}</td></tr>\n"
        "</tbody></table>\n",
        encoding="utf-8",
    )
    return report


def test_extract_all_detail_sections_returns_ordered_label_value(tmp_path, monkeypatch):
    module = _load_webui_core(tmp_path, monkeypatch)

    sections = module._extract_all_detail_sections(_RICH_DETAIL)

    labels = [section["label"] for section in sections]
    assert labels == [
        "概览", "涨幅", "板块", "量化", "技术", "基本面",
        "情绪资金", "消息", "关键加减分", "入选原因", "最新动态", "高级",
    ]
    by_label = {section["label"]: section["value"] for section in sections}
    assert by_label["涨幅"] == "当日:+7.38%，3日:+8.28%，5日:+4.39%"
    assert by_label["概览"].startswith("评级S")
    # value must be trimmed of the trailing section separator
    assert not by_label["板块"].endswith("；")


def test_parse_opportunity_report_items_include_full_fields(tmp_path, monkeypatch):
    module = _load_webui_core(tmp_path, monkeypatch)
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report = _write_rich_report(results_dir)

    parsed = module._parse_opportunity_report(report)

    item = parsed["items"][0]
    assert item["code"] == "688111"
    labels = [field["label"] for field in item["fields"]]
    assert "涨幅" in labels and "板块" in labels and "高级" in labels
    # existing keys must remain intact (no regression for current callers)
    assert item["sector"] == "软件服务"
    assert item["quant_models"] == ["机器学习RF", "资金趋势"]


def test_load_opportunity_report_cards_by_file(tmp_path, monkeypatch):
    module = _load_webui_core(tmp_path, monkeypatch)
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report = _write_rich_report(results_dir)

    payload = module.load_opportunity_report_cards(report.name)

    assert payload is not None
    assert payload["file"] == report.name
    assert payload["count"] == 1
    card = payload["cards"][0]
    assert card["code"] == "688111"
    assert card["score"] == 87.08
    assert card["rating"] == "S"
    assert any(field["label"] == "板块" for field in card["fields"])


def test_load_opportunity_report_cards_rejects_traversal_and_missing(tmp_path, monkeypatch):
    module = _load_webui_core(tmp_path, monkeypatch)
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    _write_rich_report(results_dir)

    assert module.load_opportunity_report_cards("../../etc/passwd") is None
    assert module.load_opportunity_report_cards("does_not_exist.md") is None
    assert module.load_opportunity_report_cards("") is None
    # non-opportunity markdown in the results dir is not served by this endpoint
    (results_dir / "random_notes.md").write_text("hello", encoding="utf-8")
    assert module.load_opportunity_report_cards("random_notes.md") is None


def test_parse_opportunity_report_excludes_review_and_confidence_tables(tmp_path, monkeypatch):
    """Real reports start with a 昨日复盘 table (8 cols, detail = buy price, no 【】).

    Those rows must NOT be treated as opportunity items — only the TOP20 ranking
    rows (whose detail cell carries 【概览】…) are real candidates.
    """
    module = _load_webui_core(tmp_path, monkeypatch)
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report = results_dir / "opportunity_top10_20260602_095017.md"
    report.write_text(
        "## 昨日选股复盘\n"
        "<table>\n"
        "<thead><tr><th>原排名</th><th>代码</th><th>股票</th><th>原评分</th><th>买入价</th>"
        "<th>最新价</th><th>持有N日</th><th>累计涨跌</th></tr></thead>\n"
        "<tbody>\n"
        "<tr><td>#6</td><td>600027</td><td>华电国际</td><td>86.08</td><td>5.62</td>"
        "<td>5.92</td><td>1</td><td>+5.34%</td></tr>\n"
        "</tbody></table>\n"
        "## 综合排名 TOP20\n"
        "<table>\n"
        "<thead><tr><th>排名</th><th>代码</th><th>股票名称</th><th>综合得分</th><th>详细分析</th></tr></thead>\n"
        "<tbody>\n"
        f"<tr><td>3</td><td>688111</td><td>金山办公</td><td>87.08</td><td>{_RICH_DETAIL}</td></tr>\n"
        "</tbody></table>\n",
        encoding="utf-8",
    )

    parsed = module._parse_opportunity_report(report)

    codes = [item["code"] for item in parsed["items"]]
    assert codes == ["688111"]  # 复盘行 600027 必须被排除
    item = parsed["items"][0]
    assert item["rating"] == "S"
    assert [field["label"] for field in item["fields"]][:2] == ["概览", "涨幅"]


def test_parse_opportunity_report_prefers_market_env_line_over_review_heading(tmp_path, monkeypatch):
    """market_env should surface the 市场环境 blockquote, not the first 复盘 heading."""
    module = _load_webui_core(tmp_path, monkeypatch)
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report = results_dir / "opportunity_top10_20260602_095018.md"
    report.write_text(
        "## 📅 昨日选股复盘\n"
        "> **上一份报告**: (2026-05-31)\n"
        "## 综合排名 TOP20\n"
        "> **市场环境**: 🟡 中性 | 沪深300 近5日 -1.57% / 近20日 +0.70% | 今日 S 级 5 只\n"
        "<table>\n"
        "<tbody>\n"
        f"<tr><td>1</td><td>688111</td><td>金山办公</td><td>87.08</td><td>{_RICH_DETAIL}</td></tr>\n"
        "</tbody></table>\n",
        encoding="utf-8",
    )

    parsed = module._parse_opportunity_report(report)

    assert "市场环境" in parsed["market_env"]
    assert "中性" in parsed["market_env"]
    assert "昨日选股复盘" not in parsed["market_env"]


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


def test_opportunity_report_route_is_wired_and_maps_missing_to_404(tmp_path, monkeypatch):
    # NOTE: robyn's TestClient does not strip the query string before route
    # matching, so `?file=` cannot be exercised here (it returns robyn's default
    # "Not Found"). The parsing/validation is covered by the unit tests above; the
    # `?file=` happy-path is smoke-tested over live HTTP. This test proves the route
    # is registered and that a missing report maps to our JSON 404 envelope.
    _load_webui_core(tmp_path, monkeypatch)

    from robyn.testing import TestClient

    sys.modules.pop("webui.robyn_app", None)
    robyn_module = importlib.import_module("webui.robyn_app")

    with TestClient(robyn_module.app) as client:
        response = client.get("/api/opportunity-report")

    assert response.status_code == 404
    assert response.json()["error"] == "Report not found"
