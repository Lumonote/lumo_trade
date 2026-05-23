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
    _json_safe,
    _load_report_history,
    _load_latest_opportunities,
    _load_batch_summary,
    _stock_context_payload,
    _module_health,
    _get_job_snapshot,
    _run_pattern_refresh_job,
    _run_opportunity_job,
    _run_batch_analysis_job,
    _build_market_dashboard,
    _get_stock_kline_payload,
)

app = Flask(__name__)
CORS(app)


@app.route('/')
def index():
    """Stock analysis home page"""
    return render_template('stock_analysis_home.html')


@app.route('/prediction')
def prediction_console():
    """Kronos prediction console"""
    return render_template('index.html')


@app.route('/desktop')
@app.route('/desktop/<page>')
def desktop_page(page='features'):
    """Tauri desktop multi-page shell."""
    page = resolve_desktop_page(page)
    if page not in DESKTOP_PAGES:
        abort(404)
    return render_template(
        'desktop.html',
        pages=DESKTOP_PAGES,
        active_page=page,
        page_title=DESKTOP_PAGES[page]['title'],
        page_subtitle=DESKTOP_PAGES[page]['subtitle'],
    )


@app.route('/api/data-files')
def get_data_files():
    """Get available data file list"""
    data_files = load_data_files()
    return jsonify(data_files)


@app.route('/api/load-data', methods=['POST'])
def load_data():
    """Load data file"""
    try:
        data = request.get_json()
        file_path = data.get('file_path')

        if not file_path:
            return jsonify({'error': 'File path cannot be empty'}), 400

        df, error = load_data_file(file_path)
        if error:
            return jsonify({'error': error}), 400

        # Detect data time frequency
        def detect_timeframe(df):
            if len(df) < 2:
                return "Unknown"

            time_diffs = []
            for i in range(1, min(10, len(df))):  # Check first 10 time differences
                diff = df['timestamps'].iloc[i] - df['timestamps'].iloc[i - 1]
                time_diffs.append(diff)

            if not time_diffs:
                return "Unknown"

            # Calculate average time difference
            avg_diff = sum(time_diffs, pd.Timedelta(0)) / len(time_diffs)

            # Convert to readable format
            if avg_diff < pd.Timedelta(minutes=1):
                return f"{avg_diff.total_seconds():.0f} seconds"
            elif avg_diff < pd.Timedelta(hours=1):
                return f"{avg_diff.total_seconds() / 60:.0f} minutes"
            elif avg_diff < pd.Timedelta(days=1):
                return f"{avg_diff.total_seconds() / 3600:.0f} hours"
            else:
                return f"{avg_diff.days} days"

        # Return data information
        data_info = {
            'rows': len(df),
            'columns': list(df.columns),
            'start_date': df['timestamps'].min().isoformat() if 'timestamps' in df.columns else 'N/A',
            'end_date': df['timestamps'].max().isoformat() if 'timestamps' in df.columns else 'N/A',
            'price_range': {
                'min': float(df[['open', 'high', 'low', 'close']].min().min()),
                'max': float(df[['open', 'high', 'low', 'close']].max().max())
            },
            'prediction_columns': ['open', 'high', 'low', 'close'] + (['volume'] if 'volume' in df.columns else []),
            'timeframe': detect_timeframe(df)
        }

        return jsonify({
            'success': True,
            'data_info': data_info,
            'message': f'Successfully loaded data, total {len(df)} rows'
        })

    except Exception as e:
        return jsonify({'error': f'Failed to load data: {str(e)}'}), 500


@app.route('/api/predict', methods=['POST'])
def predict():
    """Perform prediction"""
    payload, status_code = run_prediction_payload(request.get_json(silent=True) or {}, _model_runtime_context())
    return jsonify(_json_safe(payload)), status_code


@app.route('/api/load-model', methods=['POST'])
def load_model():
    """Load Kronos model"""
    payload, status_code = load_model_payload(request.get_json(silent=True) or {}, _model_runtime_context())
    return jsonify(_json_safe(payload)), status_code


@app.route('/api/available-models')
def get_available_models():
    """Get available model list"""
    return jsonify({
        'models': AVAILABLE_MODELS,
        'model_available': MODEL_AVAILABLE
    })


@app.route('/api/model-status')
def get_model_status():
    """Get model status"""
    disabled = os.environ.get("KRONOS_DISABLE_TORCH", "0").lower() in {"1", "true", "yes"}
    bundle_mode = os.environ.get("KRONOS_BACKEND_BUNDLE_MODE", "source")
    if MODEL_AVAILABLE:
        if predictor is not None:
            return jsonify({
                'available': True,
                'loaded': True,
                'message': 'Kronos model loaded and available',
                'bundle_mode': bundle_mode,
                'torch_disabled': disabled,
                'current_model': loaded_model_info(predictor)
            })
        else:
            return jsonify({
                'available': True,
                'loaded': False,
                'message': 'Kronos model available but not loaded',
                'bundle_mode': bundle_mode,
                'torch_disabled': disabled,
            })
    else:
        message = 'Kronos model library not available, please install related dependencies'
        if disabled:
            message = '当前桌面 lite 包未内置 Kronos/PyTorch 推理依赖，请使用 full backend 构建或源码环境载入模型'
        return jsonify({
            'available': False,
            'loaded': False,
            'message': message,
            'bundle_mode': bundle_mode,
            'torch_disabled': disabled,
        })


@app.route('/api/settings')
def get_settings():
    """Return user-editable runtime settings for the desktop configuration page."""
    return jsonify(_json_safe(CONFIGURATION_SERVICE.settings_payload()))


@app.route('/api/settings/llm', methods=['POST'])
def save_llm_settings():
    payload = request.get_json(silent=True) or {}
    result = CONFIGURATION_SERVICE.save_llm_settings(payload)
    return jsonify(_json_safe(result))


@app.route('/api/settings/tushare', methods=['POST'])
def save_tushare_settings():
    payload = request.get_json(silent=True) or {}
    result = CONFIGURATION_SERVICE.save_tushare_settings(payload)
    return jsonify(_json_safe(result))


@app.route('/api/stock-dashboard')
def get_stock_dashboard():
    """Aggregate data for the stock analysis home page."""
    opportunity = _load_latest_opportunities()
    batch = _load_batch_summary()
    dashboard = {
        'generated_at': datetime.datetime.now().isoformat(),
        'market': _build_market_dashboard(),
        'opportunity': opportunity,
        'batch': batch,
        'reports': _load_report_history(),
        'modules': _module_health(),
        'model': {
            'library_available': MODEL_AVAILABLE,
            'loaded': predictor is not None,
            'available_models': AVAILABLE_MODELS,
        },
        'settings': CONFIGURATION_SERVICE.settings_payload(),
        'jobs': _get_job_snapshot(),
    }
    return jsonify(_json_safe(dashboard))


@app.route('/api/stock-kline/<stock_code>')
def get_stock_kline(stock_code):
    """Get K-line data for a stock from local data first, then Sina Finance."""
    period = request.args.get('period', 'daily')
    limit = request.args.get('limit', 120)
    payload, error = _get_stock_kline_payload(stock_code, period=period, limit=limit)
    if error:
        return jsonify({'error': error}), 400
    return jsonify({'success': True, 'data': _json_safe(payload)})


@app.route('/api/stock-context/<stock_code>')
def get_stock_context(stock_code):
    """Return the unified stock context used by the desktop stock workbench."""
    payload, error = _stock_context_payload(
        stock_code,
        stock_name=request.args.get('name', ''),
    )
    if error:
        return jsonify({'error': error}), 400
    return jsonify(_json_safe(payload))


@app.route('/api/opportunity-discovery/start', methods=['POST'])
def start_opportunity_discovery():
    """Start the existing investment opportunity discovery flow in the background."""
    data = request.get_json(silent=True) or {}
    params, error = ANALYSIS_JOB_PARSER.opportunity_params(data)
    if error:
        return jsonify({'error': error}), 400
    job = JOB_SERVICE.start('opportunity_discovery', params, _run_opportunity_job)
    return jsonify({'success': True, 'job': _get_job_snapshot(job['id'])})


@app.route('/api/batch-analysis/start', methods=['POST'])
def start_batch_analysis():
    """Start the existing batch analysis flow in the background."""
    data = request.get_json(silent=True) or {}
    params, error = ANALYSIS_JOB_PARSER.batch_params(data)
    if error:
        return jsonify({'error': error}), 400
    job = JOB_SERVICE.start('batch_analysis', params, _run_batch_analysis_job)
    return jsonify({'success': True, 'job': _get_job_snapshot(job['id'])})


@app.route('/api/jobs')
def list_jobs():
    """List recent analysis jobs."""
    return jsonify({'jobs': _get_job_snapshot()})


@app.route('/api/trading-clients')
def list_trading_clients():
    """Discover installed desktop trading clients for context-menu jumps."""
    refresh = str(request.args.get('refresh') or '').lower() in {'1', 'true', 'yes'}
    return jsonify(_json_safe(TRADING_CLIENT_SERVICE.discover_clients(refresh=refresh)))


@app.route('/api/trading-clients/open', methods=['POST'])
def open_trading_client():
    """Jump to stock/board targets in an installed desktop trading client."""
    payload = request.get_json(silent=True) or {}
    client_id = str(payload.get('client_id') or '').strip()
    target = payload.get('target') or {}
    if not client_id or not isinstance(target, dict):
        return jsonify({'success': False, 'error': '参数不完整'}), 400
    result = TRADING_CLIENT_SERVICE.open_target(client_id, target)
    status = 200 if result.get('success') else 400
    return jsonify(_json_safe(result)), status


@app.route('/api/pattern-search/status')
def pattern_search_status():
    return jsonify(_json_safe(PATTERN_SEARCH_SERVICE.status()))


@app.route('/api/pattern-search/match', methods=['POST'])
def pattern_search_match():
    payload = request.get_json(silent=True) or {}
    result, status_code = PATTERN_SEARCH_SERVICE.match(payload)
    return jsonify(_json_safe(result)), status_code


@app.route('/api/pattern-search/stocks')
def pattern_search_stocks():
    payload = PATTERN_SEARCH_SERVICE.search_stocks(
        request.args.get('q'),
        limit=request.args.get('limit'),
    )
    return jsonify(_json_safe(payload))


@app.route('/api/pattern-search/stock-curve/<stock_code>')
def pattern_search_stock_curve(stock_code):
    result, status_code = PATTERN_SEARCH_SERVICE.stock_curve(stock_code)
    return jsonify(_json_safe(result)), status_code


@app.route('/api/pattern-search/refresh', methods=['POST'])
def pattern_search_refresh():
    payload = request.get_json(silent=True) or {}
    params = PATTERN_SEARCH_SERVICE.refresh_params(payload)
    job = JOB_SERVICE.start('pattern_refresh', params, _run_pattern_refresh_job)
    return jsonify({'job_id': job['id'], 'status': 'queued', 'job': _get_job_snapshot(job['id'])})


@app.route('/api/jobs/<job_id>')
def get_job(job_id):
    """Get a single analysis job."""
    job = _get_job_snapshot(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify({'job': job})


@app.route('/analysis-reports/<path:subpath>')
def analysis_report(subpath):
    """Serve generated local reports from approved report directories."""
    safe_path = str(subpath).replace('\\', '/')
    root_key, _, filename = safe_path.partition('/')
    directory = REPORT_DIRS.get(root_key)
    if not directory or not filename:
        abort(404)
    return send_from_directory(str(directory), filename)


@app.route('/figures/<path:filename>')
def figures(filename):
    """Serve project figures used by the web UI."""
    return send_from_directory(str(PROJECT_ROOT / 'figures'), filename)


@app.route('/assets/<path:filename>')
def assets(filename):
    """Serve project assets used by the web UI."""
    return send_from_directory(str(PROJECT_ROOT / 'assets'), filename)


@app.route('/favicon.ico')
def favicon():
    """Serve application favicon."""
    return send_from_directory(str(PROJECT_ROOT / 'assets'), 'kronos_ai_stock.ico')


@app.route('/particles')
def particles():
    """Render market particles visualization"""
    return send_from_directory(str(PROJECT_ROOT / 'webui' / 'templates'), 'market_particles.html')


@app.route('/api/snapshot')
def get_snapshot():
    """Get real-time market snapshot"""
    return jsonify(market_state)


def run_server():
    """Run the Flask development server using shared WebUI config."""
    host, port, debug = get_server_config()
    start_market_monitor()
    app.run(debug=debug, host=host, port=port, use_reloader=debug)


if __name__ == '__main__':
    print("Starting Kronos Web UI...")

    print(f"Model availability: {MODEL_AVAILABLE}")
    if MODEL_AVAILABLE:
        print("Tip: You can load Kronos model through /api/load-model endpoint")
    else:
        print("Tip: Will use simulated data for demonstration")

    run_server()
