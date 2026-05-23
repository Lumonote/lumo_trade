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
