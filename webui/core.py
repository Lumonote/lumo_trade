"""Framework-agnostic WebUI core layer.

Holds helpers, service singletons, and module-level constants that
were originally defined in webui/app.py. Both webui/app.py (Flask
fallback during migration) and webui/robyn_app.py (Robyn runtime)
import from here.
"""

from __future__ import annotations

import os
import sys
import json
import math
import random
import re
import threading
import time
import urllib.parse
import warnings
import datetime
import logging
from html import unescape
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.utils

warnings.filterwarnings("ignore")

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.append(str(PROJECT_ROOT_PATH))

if os.environ.get("KRONOS_DISABLE_TORCH", "0").lower() in {"1", "true", "yes"}:
    MODEL_AVAILABLE = False
    Kronos = KronosTokenizer = KronosPredictor = None
    print("Kronos model import disabled by KRONOS_DISABLE_TORCH")
else:
    try:
        from model import Kronos, KronosTokenizer, KronosPredictor

        MODEL_AVAILABLE = True
    except ImportError:
        MODEL_AVAILABLE = False
        Kronos = KronosTokenizer = KronosPredictor = None
        print("Warning: Kronos model cannot be imported, will use simulated data for demonstration")
        print(f"Model import error: {sys.exc_info()[1]}")

from webui.services.background_jobs import BackgroundJobService
from webui.services.analysis_jobs import AnalysisJobRequestParser, normalize_stock_codes, safe_int
from webui.services.configuration_service import RuntimeConfigurationService
from webui.services.http_client import request_text
from webui.services.job_store import JobStore
from webui.services.kline_service import StockKlineService
from webui.services.market_intelligence import MarketIntelligenceService
from webui.services.model_runtime import (
    ModelRuntimeContext,
    load_model_payload,
    loaded_model_info,
    run_prediction_payload,
)
from webui.services.paths import ensure_user_subdirs, project_root, user_root
from webui.services.pattern_search_service import PatternSearchService
from webui.services.trading_client_service import TradingClientService

logger = logging.getLogger(__name__)

PROJECT_ROOT = project_root()
USER_ROOT = user_root()
ensure_user_subdirs(USER_ROOT)
RESULTS_DIR = USER_ROOT / "results"
REPORT_DIRS = {
    "results": RESULTS_DIR,
    "reports": USER_ROOT / "reports",
    "integrated_results": USER_ROOT / "integrated_results",
}
PRIMARY_OPPORTUNITY_REPORT_RE = re.compile(r"^opportunity_top10_\d{8}_\d{6}\.md$")

CONFIGURATION_SERVICE = RuntimeConfigurationService(PROJECT_ROOT, USER_ROOT)
JOB_STORE = JobStore(USER_ROOT / "data" / "webui_jobs.sqlite")
ANALYSIS_JOB_PARSER = AnalysisJobRequestParser()
STOCK_KLINE_SERVICE = StockKlineService(USER_ROOT / "data")
MARKET_INTELLIGENCE_SERVICE = MarketIntelligenceService()
PATTERN_SEARCH_SERVICE = PatternSearchService(USER_ROOT / "data" / "pattern_fingerprints.db")
TRADING_CLIENT_SERVICE = TradingClientService(PROJECT_ROOT / "config" / "trading_client_adapters.json")

tokenizer = None
model = None
predictor = None

AVAILABLE_MODELS = {
    "kronos-mini": {
        "name": "Kronos-mini",
        "model_id": "northwind9898/Kronos-mini",
        "tokenizer_id": "northwind9898/Kronos-Tokenizer-2k",
        "context_length": 2048,
        "params": "4.1M",
        "description": "Lightweight model, suitable for fast prediction",
    },
    "kronos-small": {
        "name": "Kronos-small",
        "model_id": "northwind9898/Kronos-small",
        "tokenizer_id": "northwind9898/Kronos-Tokenizer-base",
        "context_length": 512,
        "params": "24.7M",
        "description": "Small model, balanced performance and speed",
    },
    "kronos-base": {
        "name": "Kronos-base",
        "model_id": "northwind9898/Kronos-base",
        "tokenizer_id": "northwind9898/Kronos-Tokenizer-base",
        "context_length": 512,
        "params": "102.3M",
        "description": "Base model, provides better prediction quality",
    },
}

# JOB_SERVICE is instantiated after _json_safe moves over in Task A3.
JOB_SERVICE: BackgroundJobService | None = None


def _set_loaded_model(new_tokenizer, new_model, new_predictor):
    global tokenizer, model, predictor
    tokenizer = new_tokenizer
    model = new_model
    predictor = new_predictor


def _model_runtime_context():
    # Helpers load_data_file / create_prediction_chart / save_prediction_results
    # still live in webui.app during Task A2; they move to this module in Task A3.
    # Resolve them lazily via webui.app to avoid forward-reference NameError.
    from webui import app as _app

    return ModelRuntimeContext(
        model_available=lambda: MODEL_AVAILABLE,
        get_predictor=lambda: predictor,
        set_loaded_model=_set_loaded_model,
        available_models=AVAILABLE_MODELS,
        user_root=USER_ROOT,
        kronos_cls=Kronos if MODEL_AVAILABLE else None,
        tokenizer_cls=KronosTokenizer if MODEL_AVAILABLE else None,
        predictor_cls=KronosPredictor if MODEL_AVAILABLE else None,
        pandas=pd,
        load_data_file=_app.load_data_file,
        create_prediction_chart=_app.create_prediction_chart,
        save_prediction_results=_app.save_prediction_results,
    )
