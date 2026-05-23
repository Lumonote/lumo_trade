"""Surface-level regression tests for the helpers/singletons that move
from webui.app to webui.core during the Flask removal migration.

These tests should pass with the original webui.app, then continue passing
after the helpers move to webui.core, and finally pass when both
webui.app and webui.core re-export them.
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
def webui_module(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    sys.modules.pop("webui.app", None)
    sys.modules.pop("webui.core", None)
    yield


def test_webui_app_exposes_required_surface(webui_module):
    module = importlib.import_module("webui.app")
    for name in EXPECTED_CONSTANTS | EXPECTED_SINGLETONS | EXPECTED_FUNCTIONS:
        assert hasattr(module, name), f"webui.app missing attribute: {name}"
