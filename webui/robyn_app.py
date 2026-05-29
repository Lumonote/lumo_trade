"""Robyn entry point for the WebUI runtime.

Robyn owns the HTTP runtime. All routes are implemented as native Robyn
handlers backed by shared services in ``webui.core``.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, unquote_plus

from jinja2 import Environment, FileSystemLoader, select_autoescape
from robyn import ALLOW_CORS, Headers, Request, Response, Robyn
from robyn.argument_parser import Config

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui import core as webui_core
from webui.services.model_runtime import load_model_payload, loaded_model_info, run_prediction_payload


def _robyn_config() -> Config:
    config = Config()
    config.log_level = os.environ.get("ROBYN_LOG_LEVEL", "WARN")
    return config


app = Robyn(__file__, config=_robyn_config())
ALLOW_CORS(app, "*")

TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
    autoescape=select_autoescape(("html", "xml")),
)
NATIVE_ROUTE_KEYS: set[tuple[str, str]] = set()


def _native_route(method: str, route: str):
    def decorator(handler):
        normalized_method = method.upper()
        app.add_route(normalized_method, route, handler)
        NATIVE_ROUTE_KEYS.add((normalized_method, route))
        return handler

    return decorator


def _native_get(route: str):
    return _native_route("GET", route)


def _native_post(route: str):
    return _native_route("POST", route)


def _safe_unquote_plus(value: Any) -> str:
    text = "" if value is None else str(value)
    try:
        return unquote_plus(text)
    except Exception:
        return text


def _iter_query_pairs(query_params: Any) -> list[tuple[str, str]]:
    if query_params is None:
        return []
    try:
        query_dict = query_params.to_dict()
    except AttributeError:
        query_dict = {}

    pairs: list[tuple[str, str]] = []
    for key, value in query_dict.items():
        decoded_key = _safe_unquote_plus(key)
        if isinstance(value, list):
            pairs.extend((decoded_key, _safe_unquote_plus(item)) for item in value)
        else:
            pairs.append((decoded_key, _safe_unquote_plus(value)))
    return pairs


def _raw_request_path(request: Request) -> str:
    path = getattr(getattr(request, "url", None), "path", "") or "/"
    return path if path.startswith("/") else f"/{path}"


def _split_path_query(path: str) -> tuple[str, list[tuple[str, str]]]:
    clean_path, separator, query_string = str(path or "/").partition("?")
    if not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"
    query_pairs = parse_qsl(query_string, keep_blank_values=True) if separator else []
    return clean_path or "/", [(str(key), str(value)) for key, value in query_pairs]


def _request_query_pairs(request: Request) -> list[tuple[str, str]]:
    _path, path_pairs = _split_path_query(_raw_request_path(request))
    return path_pairs + _iter_query_pairs(request.query_params)


def _query_value(request: Request, name: str, default: Any = None) -> Any:
    for key, value in _request_query_pairs(request):
        if key == name:
            return value
    return default


def _path_param(request: Request, name: str, fallback: Any = None) -> str:
    value = fallback
    path_params = getattr(request, "path_params", None)
    if value is None and isinstance(path_params, dict):
        value = path_params.get(name)
    value = "" if value is None else str(value)
    raw = value.split("?", 1)[0]
    try:
        return unquote(raw)
    except Exception:
        return raw


def _request_json(request: Request) -> dict[str, Any]:
    body = _request_body(request)
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if not body:
        return {}
    try:
        payload = json.loads(str(body))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_response(payload: Any, status_code: int = 200) -> Response:
    safe_payload = webui_core._json_safe(payload)
    return Response(
        status_code=status_code,
        headers=Headers({"Content-Type": "application/json; charset=utf-8"}),
        description=json.dumps(safe_payload, ensure_ascii=False, default=str),
    )


def _text_response(text: str, status_code: int = 200, content_type: str = "text/plain; charset=utf-8") -> Response:
    return Response(
        status_code=status_code,
        headers=Headers({"Content-Type": content_type}),
        description=text,
    )


def _html_response(html: str, status_code: int = 200) -> Response:
    return _text_response(html, status_code=status_code, content_type="text/html; charset=utf-8")


def _render_template(template_name: str, **context: Any) -> Response:
    return _html_response(TEMPLATE_ENV.get_template(template_name).render(**context))


def _safe_child_path(root: Path, relative_path: str) -> Path | None:
    root_path = root.resolve()
    candidate = (root_path / str(relative_path).replace("\\", "/")).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _file_response(path: Path | None) -> Response:
    if path is None:
        return _text_response("Not Found", status_code=404)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return Response(
        status_code=200,
        headers=Headers({"Content-Type": content_type}),
        description=path.read_bytes(),
    )


def _request_body(request: Request) -> bytes | str:
    body = getattr(request, "body", b"")
    if body is None:
        return b""
    return body


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _model_status_payload() -> dict[str, Any]:
    disabled = os.environ.get("KRONOS_DISABLE_TORCH", "0").lower() in {"1", "true", "yes"}
    bundle_mode = os.environ.get("KRONOS_BACKEND_BUNDLE_MODE", "source")
    if not webui_core.MODEL_AVAILABLE:
        message = "Kronos model library not available, please install related dependencies"
        if disabled:
            message = "当前桌面 lite 包未内置 Kronos/PyTorch 推理依赖，请使用 full backend 构建或源码环境载入模型"
        return {
            "available": False,
            "loaded": False,
            "message": message,
            "bundle_mode": bundle_mode,
            "torch_disabled": disabled,
        }
    if webui_core.predictor is None:
        return {
            "available": True,
            "loaded": False,
            "message": "Kronos model available but not loaded",
            "bundle_mode": bundle_mode,
            "torch_disabled": disabled,
        }
    return {
        "available": True,
        "loaded": True,
        "message": "Kronos model loaded and available",
        "bundle_mode": bundle_mode,
        "torch_disabled": disabled,
        "current_model": loaded_model_info(webui_core.predictor),
    }


def _dataframe_info(df: Any) -> dict[str, Any]:
    def detect_timeframe() -> str:
        if len(df) < 2 or "timestamps" not in df.columns:
            return "Unknown"

        time_diffs = [
            df["timestamps"].iloc[index] - df["timestamps"].iloc[index - 1]
            for index in range(1, min(10, len(df)))
        ]
        if not time_diffs:
            return "Unknown"

        avg_diff = sum(time_diffs, webui_core.pd.Timedelta(0)) / len(time_diffs)
        if avg_diff < webui_core.pd.Timedelta(minutes=1):
            return f"{avg_diff.total_seconds():.0f} seconds"
        if avg_diff < webui_core.pd.Timedelta(hours=1):
            return f"{avg_diff.total_seconds() / 60:.0f} minutes"
        if avg_diff < webui_core.pd.Timedelta(days=1):
            return f"{avg_diff.total_seconds() / 3600:.0f} hours"
        return f"{avg_diff.days} days"

    return {
        "rows": len(df),
        "columns": list(df.columns),
        "start_date": df["timestamps"].min().isoformat() if "timestamps" in df.columns else "N/A",
        "end_date": df["timestamps"].max().isoformat() if "timestamps" in df.columns else "N/A",
        "price_range": {
            "min": float(df[["open", "high", "low", "close"]].min().min()),
            "max": float(df[["open", "high", "low", "close"]].max().max()),
        },
        "prediction_columns": ["open", "high", "low", "close"] + (["volume"] if "volume" in df.columns else []),
        "timeframe": detect_timeframe(),
    }


@_native_get("/")
def index(request: Request) -> Response:
    return _render_template("stock_analysis_home.html")


@_native_get("/prediction")
def prediction_console(request: Request) -> Response:
    return _render_template("index.html")


def _desktop_response(page: str = "features") -> Response:
    page = webui_core.resolve_desktop_page(page)
    if page not in webui_core.DESKTOP_PAGES:
        return _text_response("Not Found", status_code=404)
    return _render_template(
        "desktop.html",
        pages=webui_core.DESKTOP_PAGES,
        active_page=page,
        page_title=webui_core.DESKTOP_PAGES[page]["title"],
        page_subtitle=webui_core.DESKTOP_PAGES[page]["subtitle"],
    )


@_native_get("/desktop")
def desktop_home(request: Request) -> Response:
    return _desktop_response("features")


@_native_get("/desktop/:page")
def desktop_page(request: Request, page=None) -> Response:
    return _desktop_response(_path_param(request, "page", page))


@_native_get("/static/*filename")
def static_asset(request: Request, filename=None) -> Response:
    relative = _path_param(request, "filename", filename)
    return _file_response(_safe_child_path(webui_core.PROJECT_ROOT / "webui" / "static", relative))


@_native_get("/figures/*filename")
def figures(request: Request, filename=None) -> Response:
    relative = _path_param(request, "filename", filename)
    return _file_response(_safe_child_path(webui_core.PROJECT_ROOT / "figures", relative))


@_native_get("/assets/*filename")
def assets(request: Request, filename=None) -> Response:
    relative = _path_param(request, "filename", filename)
    return _file_response(_safe_child_path(webui_core.PROJECT_ROOT / "assets", relative))


@_native_get("/favicon.ico")
def favicon(request: Request) -> Response:
    return _file_response(_safe_child_path(webui_core.PROJECT_ROOT / "assets", "kronos_ai_stock.ico"))


@_native_get("/particles")
def particles(request: Request) -> Response:
    path = webui_core.PROJECT_ROOT / "webui" / "templates" / "market_particles.html"
    return _file_response(path if path.is_file() else None)


@_native_get("/analysis-reports/*subpath")
def analysis_report(request: Request, subpath=None) -> Response:
    safe_path = _path_param(request, "subpath", subpath).replace("\\", "/")
    root_key, _separator, filename = safe_path.partition("/")
    directory = webui_core.REPORT_DIRS.get(root_key)
    if not directory or not filename:
        return _text_response("Not Found", status_code=404)
    return _file_response(_safe_child_path(directory, filename))


@_native_get("/api/data-files")
def get_data_files(request: Request) -> Response:
    return _json_response(webui_core.load_data_files())


@_native_post("/api/load-data")
def load_data(request: Request) -> Response:
    try:
        data = _request_json(request)
        file_path = data.get("file_path")
        if not file_path:
            return _json_response({"error": "File path cannot be empty"}, status_code=400)

        df, error = webui_core.load_data_file(file_path)
        if error:
            return _json_response({"error": error}, status_code=400)

        return _json_response(
            {
                "success": True,
                "data_info": _dataframe_info(df),
                "message": f"Successfully loaded data, total {len(df)} rows",
            }
        )
    except Exception as exc:
        return _json_response({"error": f"Failed to load data: {exc}"}, status_code=500)


@_native_post("/api/predict")
def predict(request: Request) -> Response:
    payload, status_code = run_prediction_payload(
        _request_json(request),
        webui_core._model_runtime_context(),
    )
    return _json_response(payload, status_code=status_code)


@_native_post("/api/load-model")
def load_model(request: Request) -> Response:
    payload, status_code = load_model_payload(
        _request_json(request),
        webui_core._model_runtime_context(),
    )
    return _json_response(payload, status_code=status_code)


@_native_get("/api/available-models")
def get_available_models(request: Request) -> Response:
    return _json_response(
        {
            "models": webui_core.AVAILABLE_MODELS,
            "model_available": webui_core.MODEL_AVAILABLE,
        }
    )


@_native_get("/api/model-status")
def get_model_status(request: Request) -> Response:
    return _json_response(_model_status_payload())


@_native_get("/api/settings")
def get_settings(request: Request) -> Response:
    return _json_response(webui_core.CONFIGURATION_SERVICE.settings_payload())


@_native_post("/api/settings/llm")
def save_llm_settings(request: Request) -> Response:
    return _json_response(webui_core.CONFIGURATION_SERVICE.save_llm_settings(_request_json(request)))


@_native_post("/api/settings/tushare")
def save_tushare_settings(request: Request) -> Response:
    return _json_response(webui_core.CONFIGURATION_SERVICE.save_tushare_settings(_request_json(request)))


@_native_get("/api/stock-dashboard")
def get_stock_dashboard(request: Request) -> Response:
    dashboard = {
        "generated_at": webui_core.datetime.datetime.now().isoformat(),
        "market": webui_core._build_market_dashboard(),
        "opportunity": webui_core._load_latest_opportunities(),
        "batch": webui_core._load_batch_summary(),
        "reports": webui_core._load_report_history(),
        "modules": webui_core._module_health(),
        "model": {
            "library_available": webui_core.MODEL_AVAILABLE,
            "loaded": webui_core.predictor is not None,
            "available_models": webui_core.AVAILABLE_MODELS,
        },
        "settings": webui_core.CONFIGURATION_SERVICE.settings_payload(),
        "jobs": webui_core._get_job_snapshot(),
    }
    return _json_response(dashboard)


@_native_get("/api/stock-kline/:stock_code")
def get_stock_kline(request: Request, stock_code=None) -> Response:
    payload, error = webui_core._get_stock_kline_payload(
        _path_param(request, "stock_code", stock_code),
        period=_query_value(request, "period", "daily"),
        limit=_query_value(request, "limit", 120),
    )
    if error:
        return _json_response({"error": error}, status_code=400)
    return _json_response({"success": True, "data": payload})


@_native_get("/api/stock-context/:stock_code")
def get_stock_context(request: Request, stock_code=None) -> Response:
    payload, error = webui_core._stock_context_payload(
        _path_param(request, "stock_code", stock_code),
        stock_name=_query_value(request, "name", ""),
    )
    if error:
        return _json_response({"error": error}, status_code=400)
    return _json_response(payload)


@_native_get("/api/stock-analysis-suite/:stock_code")
def get_stock_analysis_suite(request: Request, stock_code=None) -> Response:
    code = _path_param(request, "stock_code", stock_code)
    name = _query_value(request, "name", "")
    force_refresh = str(_query_value(request, "refresh", "") or "").lower() in {"1", "true", "yes"}
    try:
        payload = webui_core.STOCK_SUITE_SERVICE.get_suite(code, name=name, force_refresh=force_refresh)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"success": False, "error": str(exc)}, status_code=500)
    return _json_response(payload)


@_native_get("/api/diagnostics/data-sources")
def get_diagnostics_data_sources(request: Request) -> Response:
    """最近 24h 各数据源同步摘要（从 sync_log 读取）。"""
    try:
        from data_store import sync_log_repo

        summary = sync_log_repo.summary_last_24h()
    except Exception as exc:  # noqa: BLE001
        return _json_response({"error": str(exc)}, status_code=500)
    return _json_response(summary)


@_native_post("/api/stock-analysis-suite/:stock_code/ai")
def post_stock_analysis_suite_ai(request: Request, stock_code=None) -> Response:
    code = _path_param(request, "stock_code", stock_code)
    body = _request_json(request) or {}
    name = str(body.get("name") or "")
    force_refresh = bool(body.get("force_refresh", False))
    model_full_key = body.get("model_full_key")
    try:
        payload = webui_core.STOCK_SUITE_SERVICE.trigger_ai_interpretation(
            code,
            name=name,
            model_full_key=model_full_key,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _json_response({"success": False, "error": str(exc)}, status_code=500)
    return _json_response(payload)


@_native_post("/api/opportunity-discovery/start")
def start_opportunity_discovery(request: Request) -> Response:
    params, error = webui_core.ANALYSIS_JOB_PARSER.opportunity_params(_request_json(request))
    if error:
        return _json_response({"error": error}, status_code=400)
    job = webui_core.JOB_SERVICE.start("opportunity_discovery", params, webui_core._run_opportunity_job)
    return _json_response({"success": True, "job": webui_core._get_job_snapshot(job["id"])})


@_native_post("/api/batch-analysis/start")
def start_batch_analysis(request: Request) -> Response:
    params, error = webui_core.ANALYSIS_JOB_PARSER.batch_params(_request_json(request))
    if error:
        return _json_response({"error": error}, status_code=400)
    job = webui_core.JOB_SERVICE.start("batch_analysis", params, webui_core._run_batch_analysis_job)
    return _json_response({"success": True, "job": webui_core._get_job_snapshot(job["id"])})


@_native_get("/api/jobs")
def list_jobs(request: Request) -> Response:
    return _json_response({"jobs": webui_core._get_job_snapshot()})


@_native_get("/api/jobs/:job_id")
def get_job(request: Request, job_id=None) -> Response:
    job = webui_core._get_job_snapshot(_path_param(request, "job_id", job_id))
    if not job:
        return _json_response({"error": "Job not found"}, status_code=404)
    return _json_response({"job": job})


@_native_get("/api/trading-clients")
def list_trading_clients(request: Request) -> Response:
    refresh = str(_query_value(request, "refresh", "") or "").lower() in {"1", "true", "yes"}
    return _json_response(webui_core.TRADING_CLIENT_SERVICE.discover_clients(refresh=refresh))


@_native_post("/api/trading-clients/open")
def open_trading_client(request: Request) -> Response:
    payload = _request_json(request)
    client_id = str(payload.get("client_id") or "").strip()
    target = payload.get("target") or {}
    if not client_id or not isinstance(target, dict):
        return _json_response({"success": False, "error": "参数不完整"}, status_code=400)
    result = webui_core.TRADING_CLIENT_SERVICE.open_target(client_id, target)
    return _json_response(result, status_code=200 if result.get("success") else 400)


@_native_get("/api/pattern-search/status")
def pattern_search_status(request: Request) -> Response:
    return _json_response(webui_core.PATTERN_SEARCH_SERVICE.status())


@_native_post("/api/pattern-search/match")
def pattern_search_match(request: Request) -> Response:
    result, status_code = webui_core.PATTERN_SEARCH_SERVICE.match(_request_json(request))
    return _json_response(result, status_code=status_code)


@_native_get("/api/pattern-search/stocks")
def pattern_search_stocks(request: Request) -> Response:
    payload = webui_core.PATTERN_SEARCH_SERVICE.search_stocks(
        _query_value(request, "q"),
        limit=_query_value(request, "limit"),
    )
    return _json_response(payload)


@_native_get("/api/pattern-search/stock-curve/:stock_code")
def pattern_search_stock_curve(request: Request, stock_code=None) -> Response:
    result, status_code = webui_core.PATTERN_SEARCH_SERVICE.stock_curve(
        _path_param(request, "stock_code", stock_code)
    )
    return _json_response(result, status_code=status_code)


@_native_post("/api/pattern-search/refresh")
def pattern_search_refresh(request: Request) -> Response:
    params = webui_core.PATTERN_SEARCH_SERVICE.refresh_params(_request_json(request))
    job = webui_core.JOB_SERVICE.start("pattern_refresh", params, webui_core._run_pattern_refresh_job)
    return _json_response({"job_id": job["id"], "status": "queued", "job": webui_core._get_job_snapshot(job["id"])})


@_native_get("/api/snapshot")
def get_snapshot(request: Request) -> Response:
    return _json_response(webui_core.market_state)


@app.startup_handler
def startup() -> None:
    webui_core.start_market_monitor()


def configure_server_from_env() -> None:
    app.config.processes = _env_int("ROBYN_PROCESSES", 1)
    app.config.workers = _env_int("ROBYN_WORKERS", 1)
    app.config.log_level = os.environ.get("ROBYN_LOG_LEVEL", app.config.log_level)


def get_route_manifest() -> list[dict[str, Any]]:
    """Return the registered Robyn route manifest for tests and diagnostics."""
    return [
        {"method": str(route.route_type).split(".")[-1], "route": route.route}
        for route in app.router.get_routes()
    ]


def get_native_route_manifest() -> list[dict[str, str]]:
    """Return routes implemented by native Robyn handlers."""
    return [
        {"method": method, "route": route}
        for method, route in sorted(NATIVE_ROUTE_KEYS)
    ]


def run_server() -> None:
    host, port, _debug = webui_core.get_server_config()
    configure_server_from_env()
    _ensure_port_available(host, port)
    app.start(host=host, port=port, _check_port=False)


def _ensure_port_available(host: str, port: int) -> None:
    """Fail fast with a clear message instead of Robyn's interactive port prompt.

    Robyn's default _check_port=True loops on input() when the port is busy,
    which hangs Tauri-spawned backends (no tty attached). We probe with a
    fresh socket (no SO_REUSEADDR) and exit non-zero so the host process
    can recover.
    """
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError as exc:
        msg = (
            f"❌ Port {port} on {host} is already in use ({exc}). "
            "Kill the stale Kronos backend or set ROBYN_PORT to a free port."
        )
        print(msg, file=sys.stderr, flush=True)
        sys.exit(1)
    finally:
        probe.close()


if __name__ == "__main__":
    print("Starting Kronos Web UI with Robyn...")
    print(json.dumps({"routes": get_route_manifest()[:5], "server": "robyn"}, ensure_ascii=False))
    run_server()
