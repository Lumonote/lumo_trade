"""Surface-level regression tests for the helpers/singletons exposed by
webui.core after the Flask removal migration.

These tests guard the public surface (constants, singletons, helper
functions) that Robyn routes import from webui.core.
"""

import importlib
import sys

import pytest


EXPECTED_CONSTANTS = {
    "PROJECT_ROOT",
    "USER_ROOT",
    "RESULTS_DIR",
    "REPORT_DIRS",
    "PRIMARY_OPPORTUNITY_REPORT_RE",
    "AVAILABLE_MODELS",
    "MODEL_AVAILABLE",
    "DESKTOP_PAGES",
}

EXPECTED_SINGLETONS = {
    "CONFIGURATION_SERVICE",
    "JOB_STORE",
    "JOB_SERVICE",
    "ANALYSIS_JOB_PARSER",
    "STOCK_KLINE_SERVICE",
    "MARKET_INTELLIGENCE_SERVICE",
    "PATTERN_SEARCH_SERVICE",
    "STOCK_SUITE_SERVICE",
    "TRADING_CLIENT_SERVICE",
}

EXPECTED_FUNCTIONS = {
    "_json_safe",
    "_load_report_history",
    "_load_latest_opportunities",
    "_load_batch_summary",
    "_stock_context_payload",
    "_module_health",
    "_get_job_snapshot",
    "_run_pattern_refresh_job",
    "_run_opportunity_job",
    "_run_batch_analysis_job",
    "_model_runtime_context",
    "_set_loaded_model",
    "get_server_config",
    "start_market_monitor",
    "resolve_desktop_page",
    "load_data_files",
    "load_data_file",
}


@pytest.fixture()
def clean_webui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    sys.modules.pop("webui.core", None)
    yield
    sys.modules.pop("webui.core", None)


def test_webui_core_exposes_required_surface(clean_webui_env):
    module = importlib.import_module("webui.core")
    for name in sorted(EXPECTED_CONSTANTS | EXPECTED_SINGLETONS | EXPECTED_FUNCTIONS):
        assert hasattr(module, name), f"webui.core missing attribute: {name}"


def test_desktop_html_has_panel_tab():
    """多空评审团 Tab 的按钮 / pane / 渲染函数都已接线。"""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    html = (repo_root / "webui" / "templates" / "desktop.html").read_text(encoding="utf-8")
    assert 'data-suite-tab="panel"' in html
    assert 'data-suite-pane="panel"' in html
    assert 'id="suitePanePanel"' in html
    assert "function renderSuitePanel" in html
    # 接入两处 dispatch + paneIdMap
    assert html.count('renderSuitePanel(payload)') >= 2
    assert 'panel: "suitePanePanel"' in html


def test_desktop_html_has_panel_overlay_wiring():
    """LLM 覆盖层的渲染函数 / 升档按钮 / 端点调用都已接线。"""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    html = (repo_root / "webui" / "templates" / "desktop.html").read_text(encoding="utf-8")
    assert "function renderPanelOverlay" in html
    assert "function triggerPanelOverlay" in html
    assert "/panel-overlay" in html
    assert "analysis_overlay" in html


def test_desktop_html_has_quality_gate_wiring():
    """P0-B：质量门红条 + 黄旗渲染分支已接线。"""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    html = (repo_root / "webui" / "templates" / "desktop.html").read_text(encoding="utf-8")
    assert "bbp-overlay-redbar" in html          # 红条
    assert "ov.quality" in html                  # 读 quality 字段
    assert "未通过质量门" in html                  # 红条文案
    assert "bbp-overlay-flag" in html            # 黄旗


def test_desktop_html_has_market_cloud_sidebar_menu():
    """桌面左侧栏提供大盘云图焦点入口。"""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    html = (repo_root / "webui" / "templates" / "desktop.html").read_text(encoding="utf-8")
    css = (repo_root / "webui" / "static" / "kronos_desktop.css").read_text(encoding="utf-8")
    js = (repo_root / "webui" / "static" / "kronos_market_cloud.js").read_text(encoding="utf-8")
    core_text = (repo_root / "webui" / "core.py").read_text(encoding="utf-8")

    assert 'class="market-cloud-menu' in html
    assert 'href="/desktop/market_cloud"' in html
    assert "{% if active_page == 'market_cloud' %}" in html
    assert "marketCloudRoot" in html
    assert "大盘云图" in html
    assert "market-cloud-points" in html
    assert "kronos_market_cloud.js" in html
    assert "'market_cloud':" in core_text
    assert "'title': '大盘云图'" in core_text
    assert "tushare_market_cloud" in js
    assert "TuShare全市场" in js
    assert 'sizeMode:"amount"' in js or 'sizeMode: "amount"' in js
    assert "面积按成交额" in js
    assert "mc-sector-panel" in js
    assert "panelPinned" in js
    assert "data-mc-close-panel" in js
    assert "data-sector-id" in js
    assert "mc-terminal-top" in js
    assert "mc-home-link" in js
    assert 'href="/desktop/features"' in js
    assert "返回主界面" in js
    assert "mcHeaderRefreshBtn" in js
    assert "刷新实时行情" in js
    assert "mcTradeDateInput" in js
    assert "mcDateSearchBtn" in js
    assert "mcLiveBtn" in js
    assert "date=" in js
    assert "mcBreadthBar" in js
    assert "上涨" in js
    assert "下跌" in js
    assert "平盘" in js
    assert "涨跌过滤" in js
    assert "data-filter" in js
    assert "data-range" in js
    assert "openMarketCloudStock" in js
    assert "openStockContext" in js
    assert "data-stock-code" in js
    assert "data-stock-name" in js
    assert "zoomSectorId" in js
    assert "mcZoomBackBtn" in js
    assert "返回全市场" in js
    assert "mc-zoom-back" in css
    assert "pointer-events: auto" in css
    assert "中证500" in js
    assert "sh000905" in core_text
    assert ".market-cloud-menu" in css
    assert ".app-shell.nav-collapsed .market-cloud-menu" in css
    assert 'body[data-page="market_cloud"] .sidebar' in css
    assert ".mc-terminal-bottom" in css
    assert ".mc-filter-bar" in css
    assert ".mc-date-bar" in css
    assert ".mc-breadth-bar" in css
    assert ".mc-home-link" in css
    assert ".mc-header-action" in css
    assert ".mc-sector-panel" in css
    assert ".mc-sector-panel.pinned" in css
