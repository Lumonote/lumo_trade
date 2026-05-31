# Flask 完整移除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `webui/app.py` 内的非 Flask 业务逻辑迁移到 `webui/core.py`，然后删除 Flask 相关代码与依赖，使 Robyn 成为唯一 HTTP runtime，所有路由对外契约零变更。

**Architecture:** 两阶段策略。阶段 A 是 pure refactor：抽离 94 个 helper + 7 个 service singleton + 模块级常量到新文件 `webui/core.py`，原 `webui/app.py` 改为薄包装（只保留 33 条 `@app.route` 装饰器 + `from webui.core import *`）。阶段 B 是删除：切换 `webui/robyn_app.py` 的 import 路径到 `webui/core`，删除 Flask 兼容层（5 个函数），删除 `webui/app.py` 整个文件，清理依赖、启动器、测试、文档。

**Tech Stack:** Python 3.13、Robyn（HTTP runtime）、Jinja2（模板）、httpx（HTTP client）、pytest（测试）。

**Spec 参考:** `docs/superpowers/specs/2026-05-23-flask-removal-design.md`

---

## 文件结构概览

### Phase A 改动

**Create:**
- `webui/core.py` — 非 Flask 通用层（helper、service 单例、常量）
- `tests/test_webui_core_surface.py` — 接口表面回归测试

**Modify:**
- `webui/app.py` — 删除非路由代码，改为 `from webui.core import *` + 33 路由
- `webui/__init__.py` — 如有需要导出 `core` 模块（通常不需）

### Phase B 改动

**Modify:**
- `webui/robyn_app.py` — 切换 import 到 `webui.core`，删除 Flask 兼容层 5 函数
- `webui/run.py` — 删除 `KRONOS_WEB_SERVER` 分支，只走 Robyn
- `requirements.txt` — 删除 flask 行
- `webui/requirements.txt` — 删除 flask、flask-cors 行
- `tests/test_robyn_app.py` — `flask_webui` → `webui_core`
- `scripts/check_environment.py` — 删除 flask/flask_cors 检查
- `scripts/check_runtime_upgrade.py` — 删除 PackageCheck("flask"/"flask-cors")
- `CLAUDE.md` — 删除 `python app.py` 路径，只留 Robyn 启动
- `docs/implementation/PY313_ROBYN_PROGRESS.md` — 标记 Flask 已完全移除
- `docs/implementation/DEPENDENCIES.md` — 同步依赖清单

**Delete:**
- `webui/app.py` — 整个文件

**Not touched:**
- `analysis/*`、`scripts/run_opportunity_discovery.py`、`scripts/opportunity_report_generator.py`
- `webui/services/*`（已抽出的 services 不动）
- `webui/templates/*`、`webui/static/*`
- `packaging/backend/kronos_webui_backend/_internal/*`（构建产物）

---

## Phase A — 抽离到 webui/core.py（Flask 仍在）

### Task A1: 创建接口表面快照测试

**Files:**
- Create: `tests/test_webui_core_surface.py`

- [ ] **Step 1: 写表面快照测试（先用 `webui.app` 跑通，证明清单准确）**

```python
# tests/test_webui_core_surface.py
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
```

- [ ] **Step 2: 运行测试确认当前 webui.app 满足清单**

Run: `pytest tests/test_webui_core_surface.py -v`
Expected: PASS（如有未列入的属性补充清单；如清单中的属性不存在于 app.py 则修正清单后再继续）

- [ ] **Step 3: Commit**

```bash
git add tests/test_webui_core_surface.py
git commit -m "test: 新增 webui.app 接口表面快照测试，准备 Flask 移除迁移"
```

---

### Task A2: 创建 webui/core.py 骨架并搬入模块常量

**Files:**
- Create: `webui/core.py`
- Modify: `webui/app.py`

- [ ] **Step 1: 创建 `webui/core.py`，把模块级 import 与常量从 app.py 搬过来**

```python
# webui/core.py
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

# Project root on sys.path
PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.append(str(PROJECT_ROOT_PATH))

# Optional Kronos model import
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

# Service imports
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

# Module-level constants
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

# Service singletons
CONFIGURATION_SERVICE = RuntimeConfigurationService(PROJECT_ROOT, USER_ROOT)
JOB_STORE = JobStore(USER_ROOT / "data" / "webui_jobs.sqlite")
ANALYSIS_JOB_PARSER = AnalysisJobRequestParser()
STOCK_KLINE_SERVICE = StockKlineService(USER_ROOT / "data")
MARKET_INTELLIGENCE_SERVICE = MarketIntelligenceService()
PATTERN_SEARCH_SERVICE = PatternSearchService(USER_ROOT / "data" / "pattern_fingerprints.db")
TRADING_CLIENT_SERVICE = TradingClientService(PROJECT_ROOT / "config" / "trading_client_adapters.json")

# Globals for currently loaded Kronos model
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

# JOB_SERVICE depends on _json_safe; instantiated after helpers move (Task A3)
JOB_SERVICE: BackgroundJobService | None = None


def _set_loaded_model(new_tokenizer, new_model, new_predictor):
    global tokenizer, model, predictor
    tokenizer = new_tokenizer
    model = new_model
    predictor = new_predictor


def _model_runtime_context():
    return ModelRuntimeContext(
        model_available=lambda: MODEL_AVAILABLE,
        get_predictor=lambda: predictor,
        set_loaded_model=_set_loaded_model,
        available_models=AVAILABLE_MODELS,
        kronos_classes=(Kronos, KronosTokenizer, KronosPredictor),
    )
```

- [ ] **Step 2: 在 `webui/app.py` 头部把这些常量/单例换成从 core 导入**

打开 `webui/app.py`，删除第 1-114 行的全部 import、warnings、sys.path、Kronos 导入、`app = Flask(...)`、`CORS(app)` 之外的 service imports、模块级常量、service 单例实例化、`AVAILABLE_MODELS`、`_set_loaded_model`、`_model_runtime_context`。

仅保留 Flask 必需部分：

```python
# webui/app.py (顶部)
from flask import Flask, render_template, request, jsonify, send_from_directory, abort
from flask_cors import CORS

from webui.core import *  # noqa: F401,F403  - re-export helpers/singletons
from webui.core import (
    PROJECT_ROOT,
    USER_ROOT,
    RESULTS_DIR,
    REPORT_DIRS,
    AVAILABLE_MODELS,
    MODEL_AVAILABLE,
    CONFIGURATION_SERVICE,
    JOB_STORE,
    ANALYSIS_JOB_PARSER,
    STOCK_KLINE_SERVICE,
    MARKET_INTELLIGENCE_SERVICE,
    PATTERN_SEARCH_SERVICE,
    TRADING_CLIENT_SERVICE,
    _set_loaded_model,
    _model_runtime_context,
)

app = Flask(__name__)
CORS(app)
```

- [ ] **Step 3: 运行表面快照测试**

Run: `pytest tests/test_webui_core_surface.py -v`
Expected: PASS（常量与单例已通过 `from webui.core import *` 暴露，helper 还在 app.py 待 Task A3 搬迁）

- [ ] **Step 4: 运行 webui 现有测试做回归**

Run: `pytest tests/test_robyn_app.py tests/test_analysis_jobs.py -v 2>&1 | tail -30`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add webui/core.py webui/app.py
git commit -m "refactor(webui): 抽离常量与 service 单例到 webui/core，Flask 路由仍在"
```

---

### Task A3: 把 94 个 helper 函数从 app.py 迁移到 core.py

**Files:**
- Modify: `webui/core.py`
- Modify: `webui/app.py`

> 说明：Flask 路由（`@app.route`）保留在 app.py 不动；所有非路由的 `def` / `class` 整体迁移到 `webui/core.py`，再实例化依赖它们的 `JOB_SERVICE`。

- [ ] **Step 1: 在 `webui/core.py` 末尾粘贴所有 helper 函数**

将 `webui/app.py` 中以下所有内容**剪切**到 `webui/core.py`（保留函数签名和实现一字不改）：

- `_set_loaded_model`、`_model_runtime_context`（如 Task A2 已搬，跳过）
- `generate_market_news`、`init_market`、`_parse_tencent_quote_line`、`fetch_real_index_data`、`fetch_real_market_data`、`monitor_loop`、`start_market_monitor`
- `load_data_files`、`load_data_file`
- `save_prediction_results`
- `create_prediction_chart`
- `_safe_int`、`_safe_float`、`_format_datetime`、`_load_market_intelligence`、`_normalize_stock_codes`
- `_json_safe`
- `_latest_files`、`_latest_primary_opportunity_reports`、`_report_url`
- `_strip_markup`、`_truncate_text`、`_extract_detail_section`、`_parse_rating`、`_parse_recommendation`、`_parse_sector`、`_parse_quant_models`
- `_html_table_rows`、`_markdown_table_rows`
- `_parse_opportunity_report`、`_build_quant_model_summary`
- `_market_symbol_for_code`、`_xueqiu_symbol`、`_stock_external_links`、`_latest_stock_quote`、`_stock_kline_summary`、`_report_matches_stock`、`_load_stock_report_history`、`_stock_row_code`、`_stock_batch_fields`、`_load_stock_batch_results`、`_stock_social_sources`、`_stock_news_sources`
- `_stock_context_payload`
- `_load_latest_opportunities`、`_build_market_dashboard`
- `_get_stock_kline_payload`、`_load_batch_summary`、`_report_history_candidates`、`_load_report_history`
- `_module_health`
- `_update_job`、`_append_job_log`（如它们存在）
- `_run_pattern_refresh_job`、`_run_opportunity_job`、`_run_batch_analysis_job`、`_get_job_snapshot`
- `get_server_config`、`resolve_desktop_page`、`DESKTOP_PAGES`
- 其它非 Flask 路由的辅助类（如自定义 logging Handler）

具体源行号通过下面命令定位：

```bash
grep -n "^def \|^class " webui/app.py
```

然后把所有不带 `@app.route`、`@app.errorhandler`、`@app.before_request` 装饰器的顶层定义剪切粘贴。

- [ ] **Step 2: 在 `webui/core.py` 中把 JOB_SERVICE 移到 helper 之后实例化**

```python
# webui/core.py (helper 全部就位之后)
JOB_SERVICE = BackgroundJobService(JOB_STORE, sanitizer=lambda value: _json_safe(value))
```

并删除 Task A2 在末尾留下的 `JOB_SERVICE: BackgroundJobService | None = None` 占位声明。

- [ ] **Step 3: 在 `webui/app.py` 顶部追加 helper re-export**

```python
# webui/app.py 顶部，紧跟原有 import 之后
from webui.core import (
    JOB_SERVICE,
    _json_safe,
    _stock_context_payload,
    _module_health,
    _get_job_snapshot,
    _run_pattern_refresh_job,
    _run_opportunity_job,
    _run_batch_analysis_job,
    _load_report_history,
    _load_latest_opportunities,
    _load_batch_summary,
    get_server_config,
    start_market_monitor,
    resolve_desktop_page,
    load_data_files,
    load_data_file,
    # 其它路由内 body 使用到的 helper
)
```

> Pro tip：直接 `from webui.core import *` 已经 re-export 一切，但显式 import 更易维护。两种方式都可，选其一。本 plan 使用 `import *` + 显式 import 兜底。

- [ ] **Step 4: 运行表面快照测试**

Run: `pytest tests/test_webui_core_surface.py -v`
Expected: PASS

- [ ] **Step 5: 运行完整回归**

Run: `pytest tests/ -v 2>&1 | tail -40`
Expected: 与迁移前同等绿色

- [ ] **Step 6: Flask 启动手动验证**

```bash
KRONOS_WEB_SERVER=flask python webui/run.py &
sleep 3
curl -s http://localhost:5000/api/jobs
curl -s http://localhost:5000/api/snapshot | head -c 200
kill %1
```

Expected: 两个端点返回 200 JSON

- [ ] **Step 7: Robyn 启动手动验证**

```bash
KRONOS_WEB_SERVER=robyn python webui/run.py &
sleep 3
curl -s http://localhost:5000/api/jobs
curl -s http://localhost:5000/api/snapshot | head -c 200
curl -s http://localhost:5000/api/stock-context/000001?name=平安银行 | head -c 200
kill %1
```

Expected: 路由返回 200 JSON（即使仍走 Flask compat 兜底也算 OK）

- [ ] **Step 8: Commit**

```bash
git add webui/core.py webui/app.py
git commit -m "refactor(webui): 把 94 个 helper 从 app.py 迁移到 core.py，Flask 路由层保留"
```

---

## Phase B — 切换 Robyn 并删除 Flask

### Task B1: 切换 `webui/robyn_app.py` 的 import 路径

**Files:**
- Modify: `webui/robyn_app.py`

- [ ] **Step 1: 替换 module-level Flask app 引用**

打开 `webui/robyn_app.py`，把：

```python
from flask import Response as FlaskResponse
...
from webui import app as flask_webui
```

修改为：

```python
from webui import core as webui_core
```

> 注意：`FlaskResponse` 删除后，下面的 `_to_robyn_response(response: FlaskResponse)` 将在 Task B2 一并删除。

- [ ] **Step 2: 批量替换 `flask_webui.` → `webui_core.`**

整文件做不区分大小写的精确替换。约 64 处。执行后 grep 应为 0：

```bash
sed -i.bak 's/flask_webui\./webui_core./g' webui/robyn_app.py
rm webui/robyn_app.py.bak
grep -c "flask_webui" webui/robyn_app.py
```

Expected: 输出 `0`

- [ ] **Step 3: 处理 `flask_webui.app` 的特殊引用**

`flask_webui.app` 是 Flask 实例本身，`webui_core` 没有这个属性。检查并删除/重写引用点：

```bash
grep -n "webui_core\.app\b" webui/robyn_app.py
```

每个出现都在 Flask 兼容层内（`_dispatch_to_flask`、`_register_flask_routes`），Task B2 会删除整段，本步骤不修复，等 Task B2 一并清理。

- [ ] **Step 4: 运行 Robyn 测试看部分断言会失败但不会 ImportError**

Run: `pytest tests/test_robyn_app.py -v 2>&1 | tail -30`
Expected: collect 成功；部分 test_robyn_route_manifest 因 Flask 路由没注册而少几条 → 在 Task B2 之后恢复

- [ ] **Step 5: 暂不 commit，进入 Task B2 一起 commit**

---

### Task B2: 删除 `webui/robyn_app.py` 内 Flask 兼容层（5 函数）

**Files:**
- Modify: `webui/robyn_app.py`

- [ ] **Step 1: 删除 `_to_robyn_response` 函数（约第 211-224 行）**

完整删除：

```python
def _to_robyn_response(response: FlaskResponse) -> Response:
    if response.direct_passthrough:
        response.direct_passthrough = False
    body = response.get_data()
    headers = Headers({})
    for key, value in response.headers.items():
        if key.lower() in {"content-length"}:
            continue
        headers.append(key, value)
    return Response(
        status_code=response.status_code,
        headers=headers,
        description=body,
    )
```

- [ ] **Step 2: 删除 `_dispatch_to_flask` 函数（约第 227-248 行）**

完整删除：

```python
def _dispatch_to_flask(
    request: Request,
    job_id=None,
    page=None,
    stock_code=None,
    filename=None,
    subpath=None,
) -> Response:
    ...
```

- [ ] **Step 3: 删除 `_flask_rule_to_robyn` 函数（约第 251-273 行）**

完整删除该函数。

- [ ] **Step 4: 删除 `_register_flask_routes` 函数（约第 276-287 行）**

完整删除该函数。

- [ ] **Step 5: 删除对 `_register_flask_routes()` 的调用点**

```bash
grep -n "_register_flask_routes\b" webui/robyn_app.py
```

把所有非定义点的调用（通常在文件末尾 `if __name__ == "__main__":` 或 `run_server()` 内）删除。

- [ ] **Step 6: 删除 `FlaskResponse` import（应已在 Task B1 删除）确认清理**

```bash
grep -n "FlaskResponse\|from flask" webui/robyn_app.py
```

Expected: 输出 0 行（无任何 Flask import）

- [ ] **Step 7: 删除 `Headers` import（如果不再被其他 native handler 使用）**

```bash
grep -n "Headers" webui/robyn_app.py | grep -v "from robyn"
```

如果只有 `from robyn import ... Headers ...` 而无任何 `Headers({...})` 使用，从 import 行移除。

- [ ] **Step 8: 运行 Robyn 测试**

Run: `pytest tests/test_robyn_app.py -v 2>&1 | tail -30`
Expected: `test_robyn_route_manifest_contains_native_routes` 仍然 PASS（依赖 native_manifest，已不需 Flask）；其他 6 个测试 PASS（但 `test_robyn_native_json_routes` 与 `test_robyn_native_template_static_and_path_params` 因 monkeypatch 仍指向 `flask_webui` 会失败 → 在 Task B6 修复）

> 已知失败可接受，Task B6 会修。

- [ ] **Step 9: Commit Task B1+B2**

```bash
git add webui/robyn_app.py
git commit -m "refactor(webui): robyn_app 切换到 webui.core，删除 Flask 兼容层（_dispatch_to_flask 等 5 函数）"
```

---

### Task B3: 删除 `webui/app.py`

**Files:**
- Delete: `webui/app.py`

- [ ] **Step 1: 确认所有外部引用都已切走**

```bash
grep -rn "from webui import app\b\|from webui.app\b\|import webui.app\b" --include="*.py" . | grep -v __pycache__ | grep -v packaging/backend/
```

Expected: 输出 0 行（packaging/backend 是构建产物，下次 build 会重生成）

如果有遗漏，先修复。

- [ ] **Step 2: 删除文件**

```bash
git rm webui/app.py
```

- [ ] **Step 3: 表面快照测试要预期更新（webui.app 不再存在）**

修改 `tests/test_webui_core_surface.py`，把 `importlib.import_module("webui.app")` 改为 `"webui.core"`：

```python
def test_webui_core_exposes_required_surface(webui_module):
    module = importlib.import_module("webui.core")
    for name in EXPECTED_CONSTANTS | EXPECTED_SINGLETONS | EXPECTED_FUNCTIONS:
        assert hasattr(module, name), f"webui.core missing attribute: {name}"
```

并重命名测试函数：`test_webui_app_exposes_required_surface` → `test_webui_core_exposes_required_surface`

- [ ] **Step 4: 运行表面快照测试**

Run: `pytest tests/test_webui_core_surface.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add webui/app.py tests/test_webui_core_surface.py
git commit -m "refactor(webui): 删除 webui/app.py，所有 Robyn 路由直接使用 webui.core"
```

---

### Task B4: 更新 `webui/run.py` 为 Robyn-only

**Files:**
- Modify: `webui/run.py`

- [ ] **Step 1: 重写 webui/run.py**

完整替换文件内容为：

```python
#!/usr/bin/env python3
"""Kronos Web UI startup script — Robyn only."""

import os
import sys
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def check_dependencies():
    try:
        import robyn  # noqa: F401
        import httpx  # noqa: F401
        import pandas  # noqa: F401
        import numpy  # noqa: F401
        import plotly  # noqa: F401
        if os.environ.get("KRONOS_DISABLE_TORCH", "0").lower() not in {"1", "true", "yes"}:
            import modelscope  # noqa: F401
        print("✅ All dependencies installed")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        return False


def install_dependencies():
    print("Installing dependencies...")
    requirements = Path(__file__).resolve().parent / "requirements.txt"
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
        print("✅ Dependencies installation completed")
        return True
    except subprocess.CalledProcessError:
        print("❌ Dependencies installation failed")
        return False


def main():
    print("🚀 Starting Kronos Web UI (Robyn)...")
    print("=" * 50)

    if not check_dependencies():
        print("\nAuto-install dependencies? (y/n): ", end="")
        if input().lower() == "y":
            if not install_dependencies():
                return
        else:
            print("Please manually install dependencies and retry")
            return

    try:
        from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: F401
        print("✅ Kronos model library available")
    except ImportError:
        print("⚠️  Kronos model library not available, will use simulated prediction")

    try:
        from webui.robyn_app import webui_core, run_server

        _host, port, _debug = webui_core.get_server_config()
        print("✅ Robyn server starting")
        print(f"🌐 Access URL: http://localhost:{port}")
        print("💡 Tip: Press Ctrl+C to stop server")
        run_server()
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        print("Please check if the configured port is occupied")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 手动启动确认**

```bash
python webui/run.py &
sleep 3
curl -s http://localhost:5000/api/jobs
kill %1
```

Expected: `{"jobs":[]}` 或同等 JSON

- [ ] **Step 3: Commit**

```bash
git add webui/run.py
git commit -m "refactor(webui): run.py 切换为 Robyn-only，删除 KRONOS_WEB_SERVER 分支"
```

---

### Task B5: 删除 Flask 依赖声明

**Files:**
- Modify: `requirements.txt`
- Modify: `webui/requirements.txt`

- [ ] **Step 1: 从 `requirements.txt` 删除 flask 相关行**

```bash
grep -n "^flask" requirements.txt
```

如有 `flask` / `flask-cors` 行，用 Edit 工具移除（保留其余依赖原序）。

- [ ] **Step 2: 从 `webui/requirements.txt` 删除 flask 相关行**

打开 `webui/requirements.txt`，删除：

```
flask>=3.0.0,<4.0
flask-cors>=4.0.0,<7.0
```

保留 `robyn>=0.84.0,<1.0` 与其他行。

- [ ] **Step 3: 在干净虚拟环境验证 pip 不再安装 flask**

```bash
python -m venv /tmp/kronos-flask-removal-check
/tmp/kronos-flask-removal-check/bin/pip install -r webui/requirements.txt > /tmp/pip-install.log
/tmp/kronos-flask-removal-check/bin/python -c "import flask" 2>&1
rm -rf /tmp/kronos-flask-removal-check
```

Expected: 最后一条 `import flask` 报 `ModuleNotFoundError: No module named 'flask'`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt webui/requirements.txt
git commit -m "chore: 删除 flask 与 flask-cors 依赖"
```

---

### Task B6: 修复 `tests/test_robyn_app.py`

**Files:**
- Modify: `tests/test_robyn_app.py`

- [ ] **Step 1: 把 `flask_webui` 替换为 `webui_core`**

整文件批量替换：

```bash
sed -i.bak 's/flask_webui/webui_core/g' tests/test_robyn_app.py
rm tests/test_robyn_app.py.bak
grep -c "flask_webui" tests/test_robyn_app.py
```

Expected: 输出 `0`

- [ ] **Step 2: 同步删除测试 fixture 中的 `webui.app` 引用**

打开 `tests/test_robyn_app.py`，把 fixture：

```python
@pytest.fixture()
def robyn_module(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.app", None)
    module = importlib.import_module("webui.robyn_app")
    yield module
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.app", None)
```

改为：

```python
@pytest.fixture()
def robyn_module(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.core", None)
    module = importlib.import_module("webui.robyn_app")
    yield module
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.core", None)
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_robyn_app.py -v`
Expected: 全部 7 个测试 PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_robyn_app.py
git commit -m "test(webui): robyn 测试 flask_webui → webui_core"
```

---

### Task B7: 更新依赖检查脚本

**Files:**
- Modify: `scripts/check_runtime_upgrade.py`
- Modify: `scripts/check_environment.py`

- [ ] **Step 1: `check_runtime_upgrade.py` 删除 Flask 两条**

在 `WEBUI_PACKAGES` 列表（约第 44-50 行）中删除：

```python
    PackageCheck("flask", "flask", "flask", "3.0.0"),
    PackageCheck("flask-cors", "flask-cors", "flask_cors", "4.0.0"),
```

保留 `plotly`、`httpx`、`robyn` 三行。

- [ ] **Step 2: `check_environment.py` 删除 Flask 检查**

```bash
grep -n "'flask'\|'flask-cors'\|'flask_cors'" scripts/check_environment.py
```

打开文件，删除这两个键值对（在 PACKAGE_NAMES 之类的字典中）。

- [ ] **Step 3: 运行脚本验证**

Run: `python scripts/check_runtime_upgrade.py`
Expected: 输出不再提到 flask；其他依赖检查正常

- [ ] **Step 4: Commit**

```bash
git add scripts/check_runtime_upgrade.py scripts/check_environment.py
git commit -m "chore(scripts): 依赖检查脚本删除 flask/flask-cors"
```

---

### Task B8: 全量回归

**Files:**
- 无修改（仅验证）

- [ ] **Step 1: 全套 pytest**

Run: `pytest tests/ -v 2>&1 | tail -50`
Expected: 全绿；如有失败立即修复后再继续

- [ ] **Step 2: 启动 Robyn，curl 关键路由**

```bash
python webui/run.py &
SERVER_PID=$!
sleep 4

curl -s -o /dev/null -w "%{http_code} /api/jobs\n"               http://localhost:5000/api/jobs
curl -s -o /dev/null -w "%{http_code} /api/snapshot\n"           http://localhost:5000/api/snapshot
curl -s -o /dev/null -w "%{http_code} /api/model-status\n"       http://localhost:5000/api/model-status
curl -s -o /dev/null -w "%{http_code} /api/available-models\n"   http://localhost:5000/api/available-models
curl -s -o /dev/null -w "%{http_code} /api/settings\n"           http://localhost:5000/api/settings
curl -s -o /dev/null -w "%{http_code} /api/trading-clients\n"    http://localhost:5000/api/trading-clients
curl -s -o /dev/null -w "%{http_code} /\n"                       http://localhost:5000/
curl -s -o /dev/null -w "%{http_code} /desktop\n"                http://localhost:5000/desktop
curl -s -o /dev/null -w "%{http_code} /static/kronos_desktop.css\n"  http://localhost:5000/static/kronos_desktop.css

kill $SERVER_PID
```

Expected: 全部 `200` 或路由本身预期的状态码（如 `/desktop` 200、`/api/jobs` 200）

- [ ] **Step 3: 跑机会挖掘短任务，确认下游不受影响**

```bash
python scripts/run_opportunity_discovery.py --limit 3 2>&1 | tail -20
```

Expected: 完成；不报 ImportError

- [ ] **Step 4: 验证 Flask 完全消失**

```bash
grep -rln "from flask\b\|import flask\b\|@app\.route" --include="*.py" webui/ scripts/ tests/ 2>/dev/null | grep -v __pycache__ | grep -v packaging/backend/
```

Expected: 输出 0 行

- [ ] **Step 5: Commit（如有上述验证发现需修的小问题）**

如修无修，跳过 commit；如有修复，commit：

```bash
git add <files>
git commit -m "fix: Flask 移除回归发现的遗留问题"
```

---

### Task B9: 文档同步

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/implementation/PY313_ROBYN_PROGRESS.md`
- Modify: `docs/implementation/DEPENDENCIES.md`

- [ ] **Step 1: `CLAUDE.md` 删除 Flask 启动相关说明**

打开 `CLAUDE.md`，找到 `### Web Interface` 段（约第 87-100 行）：

```markdown
### Web Interface

```bash
# Start Flask web UI
cd webui
python app.py
# OR
python run.py

# Start with shell script
./start.sh
```
```

替换为：

```markdown
### Web Interface

```bash
# Start Robyn-powered Web UI
python webui/run.py

# Or with the shell script
./webui/start.sh
```

`webui/app.py` and Flask were removed in the 2026-05-23 migration. Robyn (Python 3.13) is the sole HTTP runtime.
```

- [ ] **Step 2: `docs/implementation/PY313_ROBYN_PROGRESS.md` 标记 Flask 完全移除**

在「已完成」段落末尾追加：

```markdown
- **2026-05-23 — Flask 完整移除**：
  - `webui/app.py` 已删除；所有 helper / service singleton 落地 `webui/core.py`
  - `webui/robyn_app.py` 不再 import Flask；5 个兼容函数（`_dispatch_to_flask`、`_register_flask_routes`、`_flask_rule_to_robyn`、`_to_robyn_response`、`flask_webui` 引用）已清除
  - `requirements.txt` / `webui/requirements.txt` 不再声明 flask / flask-cors
  - `webui/run.py` 移除 `KRONOS_WEB_SERVER` 分支，固定走 Robyn
  - 测试 `tests/test_robyn_app.py` 与依赖检查脚本同步更新
  - 桌面 backend 下次 build 自动使用新源码
```

- [ ] **Step 3: `docs/implementation/DEPENDENCIES.md` 同步**

打开文件，删除 flask、flask-cors 行项；如有 web framework 相关章节，更新为 "Robyn (sole HTTP runtime, 2026-05-23 起)"。

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/implementation/PY313_ROBYN_PROGRESS.md docs/implementation/DEPENDENCIES.md
git commit -m "docs: 同步 Flask 完整移除后的运行与依赖说明"
```

---

### Task B10: 收尾 — 修订排队中的 analysis-suite spec

**Files:**
- Modify: `docs/superpowers/specs/2026-05-23-stock-analysis-suite-design.md`

- [ ] **Step 1: 更新 §2.3 把"双框架同时注册"改为"仅 Robyn 注册"**

打开 spec 文件，定位 §2.3 节，把双框架注册段落替换为：

```markdown
### 2.3 最小侵入式改动的现有文件

> **Web 框架现状**：Flask 已于 2026-05-23 完整移除，Robyn 是唯一 HTTP runtime。新路由仅在 `webui/robyn_app.py` 注册，业务逻辑放在 `webui/services/stock_suite_service.py`，由 Robyn handler 调用。

- `webui/robyn_app.py`：新增 2 个原生 Robyn handler（`@_native_get` / `@_native_post`），逻辑全部委托给 `stock_suite_service`
- `webui/templates/desktop.html`：在 `#stockContextModal` → `#stockContextBody` 上方插一段 Tab 栏；现有 6 个面板原封不动塞进「快速信息」Tab
- `webui/static/kronos_desktop.css`：追加 Tab 样式，不改已有规则
- `webui/services/__init__.py`：如不存在则创建（仅一行空 import）
```

- [ ] **Step 2: 同时清理 §10 中关于 "双框架注册" 的修订条目**

定位 §10：

```markdown
- 该 spec 第 2.3 节关于"新路由必须双框架注册"的描述应同步更新为"仅 Robyn 注册"（在 stock-analysis-suite 进入 writing-plans 前修订）
```

替换为：

```markdown
- 第 2.3 节"双框架注册"的描述已在 Flask 移除完成后修订为"仅 Robyn 注册"
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-23-stock-analysis-suite-design.md
git commit -m "docs(spec): analysis-suite 修订为仅 Robyn 注册（Flask 已移除）"
```

---

## 完整验收清单（Phase A + B 全部完成时）

- [ ] `webui/app.py` 文件已删除
- [ ] `webui/core.py` 包含 94 个 helper + 7 个 singleton + 模块常量
- [ ] `webui/robyn_app.py` 不再 `from flask import` 或引用 `flask_webui`
- [ ] `webui/robyn_app.py` 内 5 个 Flask 兼容函数已删除
- [ ] `webui/run.py` 内 `KRONOS_WEB_SERVER` 分支已删除
- [ ] `requirements.txt` 与 `webui/requirements.txt` 不再声明 flask / flask-cors
- [ ] 干净 venv 安装后 `python -c "import flask"` 报 `ModuleNotFoundError`
- [ ] `pytest tests/` 全绿
- [ ] Robyn 启动后 9 个核心路由 curl 通过
- [ ] `python scripts/run_opportunity_discovery.py --limit 3` 跑通
- [ ] grep `from flask\|import flask\|@app\.route` 在 `webui/ scripts/ tests/` 全部 0 命中
- [ ] CLAUDE.md / PY313_ROBYN_PROGRESS.md / DEPENDENCIES.md 已同步
- [ ] analysis-suite spec §2.3 已修订
- [ ] 每个 Task 一个 commit，方便独立回滚

## 自审结果

**Spec 覆盖**：spec §2.1 In Scope 全 10 项 → 分别对应 Task A1-A3、B1-B7、B9；spec §2.2 Out of Scope 全部规避（analysis/* 等未触碰）。
**占位符扫描**：0 命中。
**类型一致性**：`webui_core` 命名贯穿 robyn_app.py + tests + run.py；`flask_webui` 在 B1+B6 完成后 0 残留。
