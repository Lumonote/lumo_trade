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
from webui.services.paths import ensure_user_subdirs, project_root, results_dir, user_root
from webui.services.pattern_search_service import PatternSearchService
from webui.services.stock_suite_service import STOCK_SUITE_SERVICE
from webui.services.trading_client_service import TradingClientService
from webui.services.watchlist_service import WatchlistService

logger = logging.getLogger(__name__)

PROJECT_ROOT = project_root()
USER_ROOT = user_root()
ensure_user_subdirs(USER_ROOT)
RESULTS_DIR = results_dir()
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
WATCHLIST_SERVICE = WatchlistService(USER_ROOT / "config" / "watchlist.json")
# 形态指纹是隔日快照；给命中结果叠加自选同款实时报价（东财 ulist.np→腾讯回退），形态页可见当日最新价。
PATTERN_SEARCH_SERVICE.set_quote_provider(WATCHLIST_SERVICE.quotes)
# K线默认是新浪日K（隔日/盘中按天一根）；叠加自选同款实时报价，让当日那根bar与「实时价」徽章跟随盘中最新价。
STOCK_KLINE_SERVICE.set_quote_provider(WATCHLIST_SERVICE.quotes)

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


# --- Market Data Configuration & Logic ---

# Real Stock Mapping (A-Share Codes)
REAL_CODES_MAP = {
    'ai': ['sz002230', 'sh688256', 'sh601360', 'sz000977', 'sh603019', 'sh601138', 'sh688111', 'sz300418'],
    'robot': ['sz300124', 'sz002747', 'sh603728', 'sh688017', 'sz002050', 'sh601689'],
    'quantum': ['sh688027', 'sz000555', 'sz300520', 'sh600120'],
    'fusion': ['sz000969', 'sh600105', 'sh688122', 'sh600363'],
    'space': ['sh600118', 'sh600879', 'sh601698', 'sh688568']
}

SECTORS = [
    { "id": 0, "key": 'ai', "name": '人工智能', "color": '#ff0055', "angle": 0, "count": 800, "hot": True },
    { "id": 1, "key": 'robot', "name": '人形机器人', "color": '#00ff88', "angle": 1.2, "count": 600, "hot": True },
    { "id": 2, "key": 'quantum', "name": '量子计算', "color": '#00ccff', "angle": 2.4, "count": 500, "hot": False },
    { "id": 3, "key": 'fusion', "name": '可控核聚变', "color": '#ffff00', "angle": 3.6, "count": 400, "hot": True },
    { "id": 4, "key": 'space', "name": '深空探测', "color": '#ff8800', "angle": 4.8, "count": 450, "hot": False },
]

# Flatten codes for API fetching
ALL_REAL_CODES = []
for k, v in REAL_CODES_MAP.items():
    ALL_REAL_CODES.extend(v)

REAL_INDEX_CODES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sh000300": "沪深300",
    "sz399006": "创业板指",
}

# Market Global State
market_state = {
    "stocks": [],
    "indices": {},
    "trades": [],
    "news": [],
    "sectors": SECTORS,
    "last_update": time.time(),
    "index_last_update": None,
    "real_data_cache": {} # code -> {price, change, name}
}
market_monitor_thread = None
market_monitor_lock = threading.Lock()

# Initial News Data
INITIAL_NEWS = [
    { "tag": "Breaking", "title": "Dec 7, 2025: A-Share stands at 3800, AI sector explodes" },
    { "tag": "Policy", "title": "AGI Development Plan (2025-2030) released, trillion-dollar market opens" },
    { "tag": "Flash", "title": "First consumer humanoid robot 'Optimus-C' sold out in seconds" },
    { "tag": "Tech", "title": "CAS announces major breakthrough in quantum computer 'Jiuzhang 4'" },
    { "tag": "Market", "title": "Northbound capital net inflow exceeds 15B, focusing on hard tech" },
    { "tag": "Company", "title": "Huawei releases 6G prototype, communication industry sees new revolution" },
    { "tag": "Warning", "title": "Abnormal capital inflow detected in 'Nuclear Fusion' sector, beware of chasing highs" }
]

def generate_market_news():
    """Generate dynamic market news based on current market state"""
    try:
        # Find top performing sector
        top_sector = None
        max_change = -100

        for stock in market_state["stocks"]:
            if stock.get("real_api_code") and stock["change"] > max_change:
                max_change = stock["change"]
                # Find sector name
                for s in SECTORS:
                    if s["id"] == stock["sectorId"]:
                        top_sector = s["name"]
                        break

        if top_sector and max_change > 3.0:
            return {
                "tag": "Market",
                "title": f"Sector Alert: {top_sector} leads the rally with top gainers up {max_change:.1f}%"
            }

        # Random generic news
        templates = [
            ("Tech", "Global AI computing power demand surges, semiconductor sector benefits"),
            ("Policy", "Central Bank: Maintain reasonable and sufficient liquidity"),
            ("Market", "Main board turnover exceeds 1 trillion in morning session"),
            ("Flash", "New battery technology achieves energy density breakthrough")
        ]
        t = random.choice(templates)
        return { "tag": t[0], "title": t[1] }

    except Exception:
        return None

def init_market():
    global_index = 0
    # Clear existing stocks to prevent duplication on re-init
    market_state["stocks"] = []
    market_state["news"] = list(INITIAL_NEWS)
    market_state["sectors"] = SECTORS
    market_state["indices"] = {}
    market_state["index_last_update"] = None

    for sector in SECTORS:
        real_codes = REAL_CODES_MAP.get(sector["key"], [])

        for i in range(sector["count"]):
            # Position (Spiral Galaxy Logic)
            arm_offset = sector["angle"]
            distance = random.random() * 40 + 10
            angle = distance * 0.1 + arm_offset
            x = math.cos(angle) * distance + (random.random() - 0.5) * 5
            y = (random.random() - 0.5) * (distance * 0.2)
            z = math.sin(angle) * distance + (random.random() - 0.5) * 5

            # Determine if this is a "Real" monitored stock or a "Background" particle
            is_real_monitored = i < len(real_codes)

            stock_code = "UNKNOWN"
            stock_name = "Unknown"

            if is_real_monitored:
                # Map to a real stock code
                full_code = real_codes[i] # e.g. sz002230
                stock_code = full_code[2:] # 002230
                stock_name = "Loading..."
            else:
                # Background particle
                stock_code = ('60' if random.random() > 0.5 else '00') + str(random.randint(0, 9999)).zfill(4)
                stock_name = sector["name"] + " Stock"

            stock = {
                "index": global_index,
                "id": f"{sector['key']}-{i}",
                "sectorId": sector["id"],
                "real_api_code": real_codes[i] if is_real_monitored else None,
                "name": stock_name,
                "code": stock_code,
                "price": 0.0,
                "change": 0.0,
                "volume": 0,
                "isLimitUp": False,
                "position": [x, y, z],
                "tags": [sector["name"]]
            }
            market_state["stocks"].append(stock)
            global_index += 1

    print(f"Market initialized with {len(market_state['stocks'])} stocks.")


def _parse_tencent_quote_line(line):
    if '="' not in line:
        return None, None
    parts = line.split('="', 1)
    api_code = parts[0].strip().replace('v_', '')
    fields = parts[1].strip().strip('"').split('~')
    if len(fields) <= 4:
        return api_code, None

    name = fields[1] or api_code
    price = _safe_float(fields[3], None)
    prev_close = _safe_float(fields[4], None)
    change = _safe_float(fields[31], None) if len(fields) > 31 else None
    change_pct = _safe_float(fields[32], None) if len(fields) > 32 else None

    if change_pct is None and price is not None and prev_close:
        change_pct = (price - prev_close) / prev_close * 100
    if change is None and price is not None and prev_close is not None:
        change = price - prev_close

    return api_code, {
        "code": api_code,
        "name": name,
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "available": price is not None,
        "source": "tencent",
        "updated_at": _format_datetime(),
    }


def fetch_real_index_data():
    """Fetch real index quotes. Never derive index values from monitored stocks."""
    try:
        url = f"http://qt.gtimg.cn/q={','.join(REAL_INDEX_CODES.keys())}"
        content = request_text(
            url,
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=5,
            encoding='gbk',
            errors='ignore',
        )

        indices = {}
        for line in content.strip().split(';'):
            api_code, quote = _parse_tencent_quote_line(line)
            if api_code and quote and quote.get("available"):
                quote["display_name"] = REAL_INDEX_CODES.get(api_code, quote["name"])
                indices[api_code] = quote

        if indices:
            market_state["indices"] = indices
            market_state["index_last_update"] = time.time()
            return True
    except Exception as e:
        print(f"Error fetching real index data: {e}")
    return False


def fetch_real_market_data():
    try:
        url = f"http://qt.gtimg.cn/q={','.join(ALL_REAL_CODES)}"
        content = request_text(
            url,
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=5,
            encoding='gbk',
        )

        lines = content.strip().split(';')
        for line in lines:
            if '="' in line:
                parts = line.split('="')
                if len(parts) < 2: continue

                api_code = parts[0].strip().replace('v_', '')
                data_str = parts[1].strip('"')
                fields = data_str.split('~')

                if len(fields) > 30:
                    name = fields[1]
                    current_price = float(fields[3])
                    prev_close = float(fields[4])

                    change_pct = 0.0
                    if prev_close > 0:
                        change_pct = (current_price - prev_close) / prev_close * 100

                    volume = float(fields[6]) # Hand/Lot

                    market_state["real_data_cache"][api_code] = {
                        "name": name,
                        "price": current_price,
                        "change": change_pct,
                        "volume": volume
                    }
                    market_state["last_update"] = time.time()

    except Exception as e:
        print(f"Error fetching real data: {e}")

def monitor_loop():
    print("Market data monitor started...")
    while True:
        try:
            # 1. Fetch Real Data
            fetch_real_index_data()
            fetch_real_market_data()

            # 2. Update Stocks
            for stock in market_state["stocks"]:
                if stock["real_api_code"]:
                    # Update Real Stocks
                    data = market_state["real_data_cache"].get(stock["real_api_code"])
                    if data:
                        stock["name"] = data["name"]
                        stock["price"] = data["price"]
                        stock["change"] = data["change"]
                        stock["volume"] = data["volume"]
                        stock["isLimitUp"] = data["change"] > 9.5

                        # Update tags
                        stock["tags"] = [SECTORS[stock["sectorId"]]["name"]]
                        if data["change"] > 5: stock["tags"].append("Inflow")
                else:
                    # Update Background Particles
                    sector_key = SECTORS[stock["sectorId"]]["key"]
                    leaders = REAL_CODES_MAP.get(sector_key, [])

                    base_change = 0
                    if leaders:
                        leader_code = leaders[0]
                        leader_data = market_state["real_data_cache"].get(leader_code)
                        if leader_data:
                            base_change = leader_data["change"]

                    noise = (random.random() - 0.5) * 2
                    stock["change"] = base_change + noise
                    stock["price"] = max(2.0, stock["price"] * (1 + stock["change"]/1000))

            # 3. Generate "Real" Trades
            current_time = time.time()
            if len(market_state["trades"]) < 15:
                for stock in market_state["stocks"]:
                    if stock["real_api_code"] and abs(stock["change"]) > 2.0:
                        if random.random() < 0.1:
                            amount = round(random.random() * 10 + 1, 1)
                            trade = {
                                "targetId": stock["id"],
                                "targetName": stock["name"],
                                "targetPos": stock["position"],
                                "amount": amount,
                                "timestamp": current_time
                            }
                            if not any(t["targetId"] == stock["id"] for t in market_state["trades"]):
                                market_state["trades"].append(trade)

            # Cleanup trades
            market_state["trades"] = [t for t in market_state["trades"] if current_time - t["timestamp"] < 5]

            # 4. Update Dynamic News
            if random.random() < 0.1: # 10% chance per loop (approx every 20s)
                new_news = generate_market_news()
                if new_news:
                    # Check duplication
                    if not market_state["news"] or market_state["news"][0]["title"] != new_news["title"]:
                        market_state["news"].insert(0, new_news)
                        if len(market_state["news"]) > 20:
                            market_state["news"] = market_state["news"][:20]

        except Exception as e:
            print(f"Error in monitor loop: {e}")

        time.sleep(2.0)


def start_market_monitor():
    """Initialize market state and start the monitor thread once."""
    global market_monitor_thread
    with market_monitor_lock:
        if market_monitor_thread and market_monitor_thread.is_alive():
            return market_monitor_thread

        print("Initializing market data...")
        init_market()
        market_monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        market_monitor_thread.start()
        return market_monitor_thread


def load_data_files():
    """Scan data directory and return available data files"""
    data_dir = USER_ROOT / 'data'
    data_files = []

    if data_dir.exists():
        for path in data_dir.iterdir():
            if path.suffix.lower() in ('.csv', '.feather'):
                file_size = path.stat().st_size
                data_files.append({
                    'name': path.name,
                    'path': str(path),
                    'size': f"{file_size / 1024:.1f} KB" if file_size < 1024 * 1024 else f"{file_size / (1024 * 1024):.1f} MB"
                })

    return data_files


def load_data_file(file_path):
    """Load data file"""
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.endswith('.feather'):
            df = pd.read_feather(file_path)
        else:
            return None, "Unsupported file format"

        # Check required columns
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            return None, f"Missing required columns: {required_cols}"

        # Process timestamp column
        if 'timestamps' in df.columns:
            df['timestamps'] = pd.to_datetime(df['timestamps'])
        elif 'timestamp' in df.columns:
            df['timestamps'] = pd.to_datetime(df['timestamp'])
        elif 'date' in df.columns:
            # If column name is 'date', rename it to 'timestamps'
            df['timestamps'] = pd.to_datetime(df['date'])
        else:
            # If no timestamp column exists, create one
            df['timestamps'] = pd.date_range(start='2024-01-01', periods=len(df), freq='1H')

        # Ensure numeric columns are numeric type
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Process volume column (optional)
        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

        # Process amount column (optional, but not used for prediction)
        if 'amount' in df.columns:
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

        # Remove rows containing NaN values
        df = df.dropna()

        return df, None

    except Exception as e:
        return None, f"Failed to load file: {str(e)}"


def save_prediction_results(file_path, prediction_type, prediction_results, actual_data, input_data, prediction_params):
    """Save prediction results to file"""
    try:
        # Runtime prediction output must stay outside packaged read-only resources.
        results_dir = USER_ROOT / 'prediction_results'
        results_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'prediction_{timestamp}.json'
        filepath = results_dir / filename

        # Prepare data for saving
        save_data = {
            'timestamp': datetime.datetime.now().isoformat(),
            'file_path': file_path,
            'prediction_type': prediction_type,
            'prediction_params': prediction_params,
            'input_data_summary': {
                'rows': len(input_data),
                'columns': list(input_data.columns),
                'price_range': {
                    'open': {'min': float(input_data['open'].min()), 'max': float(input_data['open'].max())},
                    'high': {'min': float(input_data['high'].min()), 'max': float(input_data['high'].max())},
                    'low': {'min': float(input_data['low'].min()), 'max': float(input_data['low'].max())},
                    'close': {'min': float(input_data['close'].min()), 'max': float(input_data['close'].max())}
                },
                'last_values': {
                    'open': float(input_data['open'].iloc[-1]),
                    'high': float(input_data['high'].iloc[-1]),
                    'low': float(input_data['low'].iloc[-1]),
                    'close': float(input_data['close'].iloc[-1])
                }
            },
            'prediction_results': prediction_results,
            'actual_data': actual_data,
            'analysis': {}
        }

        # If actual data exists, perform comparison analysis
        if actual_data and len(actual_data) > 0:
            # Calculate continuity analysis
            if len(prediction_results) > 0 and len(actual_data) > 0:
                last_pred = prediction_results[0]  # First prediction point
            first_actual = actual_data[0]  # First actual point

            save_data['analysis']['continuity'] = {
                'last_prediction': {
                    'open': last_pred['open'],
                    'high': last_pred['high'],
                    'low': last_pred['low'],
                    'close': last_pred['close']
                },
                'first_actual': {
                    'open': first_actual['open'],
                    'high': first_actual['high'],
                    'low': first_actual['low'],
                    'close': first_actual['close']
                },
                'gaps': {
                    'open_gap': abs(last_pred['open'] - first_actual['open']),
                    'high_gap': abs(last_pred['high'] - first_actual['high']),
                    'low_gap': abs(last_pred['low'] - first_actual['low']),
                    'close_gap': abs(last_pred['close'] - first_actual['close'])
                },
                'gap_percentages': {
                    'open_gap_pct': (abs(last_pred['open'] - first_actual['open']) / first_actual['open']) * 100,
                    'high_gap_pct': (abs(last_pred['high'] - first_actual['high']) / first_actual['high']) * 100,
                    'low_gap_pct': (abs(last_pred['low'] - first_actual['low']) / first_actual['low']) * 100,
                    'close_gap_pct': (abs(last_pred['close'] - first_actual['close']) / first_actual['close']) * 100
                }
            }

        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)

        print(f"Prediction results saved to: {filepath}")
        return str(filepath)

    except Exception as e:
        print(f"Failed to save prediction results: {e}")
        return None


def create_prediction_chart(df, pred_df, lookback, pred_len, actual_df=None, historical_start_idx=0):
    """Create prediction chart"""
    # Use specified historical data start position, not always from the beginning of df
    if historical_start_idx + lookback + pred_len <= len(df):
        # Display lookback historical points + pred_len prediction points starting from specified position
        historical_df = df.iloc[historical_start_idx:historical_start_idx + lookback]
        prediction_range = range(historical_start_idx + lookback, historical_start_idx + lookback + pred_len)
    else:
        # If data is insufficient, adjust to maximum available range
        available_lookback = min(lookback, len(df) - historical_start_idx)
        available_pred_len = min(pred_len, max(0, len(df) - historical_start_idx - available_lookback))
        historical_df = df.iloc[historical_start_idx:historical_start_idx + available_lookback]
        prediction_range = range(historical_start_idx + available_lookback,
                                 historical_start_idx + available_lookback + available_pred_len)

    # Create chart
    fig = go.Figure()

    # Add historical data (candlestick chart)
    fig.add_trace(go.Candlestick(
        x=historical_df['timestamps'] if 'timestamps' in historical_df.columns else historical_df.index,
        open=historical_df['open'],
        high=historical_df['high'],
        low=historical_df['low'],
        close=historical_df['close'],
        name='历史数据 (400个数据点)',
        increasing_line_color='#26A69A',
        decreasing_line_color='#EF5350'
    ))

    # Add prediction data (candlestick chart)
    if pred_df is not None and len(pred_df) > 0:
        # Calculate prediction data timestamps - ensure continuity with historical data
        if 'timestamps' in df.columns and len(historical_df) > 0:
            # Start from the last timestamp of historical data, create prediction timestamps with the same time interval
            last_timestamp = historical_df['timestamps'].iloc[-1]
            time_diff = df['timestamps'].iloc[1] - df['timestamps'].iloc[0] if len(df) > 1 else pd.Timedelta(hours=1)

            pred_timestamps = pd.date_range(
                start=last_timestamp + time_diff,
                periods=len(pred_df),
                freq=time_diff
            )
        else:
            # If no timestamps, use index
            pred_timestamps = range(len(historical_df), len(historical_df) + len(pred_df))

        fig.add_trace(go.Candlestick(
            x=pred_timestamps,
            open=pred_df['open'],
            high=pred_df['high'],
            low=pred_df['low'],
            close=pred_df['close'],
            name='预测数据 (120个数据点)',
            increasing_line_color='#66BB6A',
            decreasing_line_color='#FF7043'
        ))

    # Add actual data for comparison (if exists)
    if actual_df is not None and len(actual_df) > 0:
        # Actual data should be in the same time period as prediction data
        if 'timestamps' in df.columns:
            # Actual data should use the same timestamps as prediction data to ensure time alignment
            if 'pred_timestamps' in locals():
                actual_timestamps = pred_timestamps
            else:
                # If no prediction timestamps, calculate from the last timestamp of historical data
                if len(historical_df) > 0:
                    last_timestamp = historical_df['timestamps'].iloc[-1]
                    time_diff = df['timestamps'].iloc[1] - df['timestamps'].iloc[0] if len(df) > 1 else pd.Timedelta(
                        hours=1)
                    actual_timestamps = pd.date_range(
                        start=last_timestamp + time_diff,
                        periods=len(actual_df),
                        freq=time_diff
                    )
                else:
                    actual_timestamps = range(len(historical_df), len(historical_df) + len(actual_df))
        else:
            actual_timestamps = range(len(historical_df), len(historical_df) + len(actual_df))

        fig.add_trace(go.Candlestick(
            x=actual_timestamps,
            open=actual_df['open'],
            high=actual_df['high'],
            low=actual_df['low'],
            close=actual_df['close'],
            name='实际数据 (120个数据点)',
            increasing_line_color='#FF9800',
            decreasing_line_color='#F44336'
        ))

    # Update layout
    fig.update_layout(
        title='Kronos金融预测结果 - 400个历史数据点 + 120个预测数据点 vs 120个实际数据点',
        xaxis_title='时间',
        yaxis_title='价格',
        template='plotly_white',
        height=600,
        showlegend=True
    )

    # Ensure x-axis time continuity
    if 'timestamps' in historical_df.columns:
        # Get all timestamps and sort them
        all_timestamps = []
        if len(historical_df) > 0:
            all_timestamps.extend(historical_df['timestamps'])
        if 'pred_timestamps' in locals():
            all_timestamps.extend(pred_timestamps)
        if 'actual_timestamps' in locals():
            all_timestamps.extend(actual_timestamps)

        if all_timestamps:
            all_timestamps = sorted(all_timestamps)
            fig.update_xaxes(
                range=[all_timestamps[0], all_timestamps[-1]],
                rangeslider_visible=False,
                type='date'
            )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def _safe_int(value, default, minimum=None, maximum=None):
    """Parse an integer with optional bounds."""
    return safe_int(value, default, minimum=minimum, maximum=maximum)


def _safe_float(value, default=0.0):
    try:
        if value in (None, '', '—', 'N/A'):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_datetime(ts=None):
    if ts is None:
        dt = datetime.datetime.now()
    elif isinstance(ts, (int, float)):
        dt = datetime.datetime.fromtimestamp(ts)
    elif isinstance(ts, datetime.datetime):
        dt = ts
    else:
        return str(ts)
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def _load_market_intelligence():
    return MARKET_INTELLIGENCE_SERVICE.load()


def _normalize_stock_codes(raw_codes):
    return normalize_stock_codes(raw_codes)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if pd.isna(value) if not isinstance(value, (dict, list, tuple, set, str, bytes)) else False:
        return None
    return value


JOB_SERVICE = BackgroundJobService(JOB_STORE, sanitizer=lambda value: _json_safe(value))
JOB_SERVICE.mark_interrupted_jobs()


def _latest_files(directory, pattern, limit=10):
    if not directory.exists():
        return []
    files = [path for path in directory.glob(pattern) if path.is_file()]
    return sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)[:limit]


def _latest_primary_opportunity_reports(limit=1):
    """Return dashboard-ready Top榜 reports, excluding source-specific long-form files."""
    candidates = _latest_files(RESULTS_DIR, 'opportunity_top10_*.md', limit=80)
    reports = [
        path for path in candidates
        if PRIMARY_OPPORTUNITY_REPORT_RE.match(path.name)
    ]
    return reports[:limit]


def _report_url(path):
    if not path:
        return None
    report_path = Path(path)
    if not report_path.is_absolute():
        report_path = PROJECT_ROOT / report_path
    try:
        resolved = report_path.resolve()
    except OSError:
        return None

    for key, directory in REPORT_DIRS.items():
        try:
            relative = resolved.relative_to(directory.resolve())
            return f"/analysis-reports/{key}/{relative.as_posix()}"
        except ValueError:
            continue
    return None


def _strip_markup(value):
    text = unescape(str(value or ''))
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('**', '').replace('&nbsp;', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _truncate_text(value, limit=180):
    text = _strip_markup(value)
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + '…'


def _extract_detail_section(detail, title):
    pattern = rf'【{re.escape(title)}】([^【]+)'
    match = re.search(pattern, detail or '')
    return _strip_markup(match.group(1)).strip('；; ') if match else ''


def _parse_rating(detail):
    overview = _extract_detail_section(detail, '概览')
    match = re.search(r'评级\s*([A-Z]\+?|S|C)', overview)
    return match.group(1) if match else ''


def _parse_recommendation(detail):
    overview = _extract_detail_section(detail, '概览')
    match = re.search(r'建议[:：]\s*([^；;，,]+)', overview)
    return _strip_markup(match.group(1)) if match else ''


def _parse_sector(detail):
    sector = _extract_detail_section(detail, '板块')
    return re.split(r'[（(]', sector, maxsplit=1)[0].strip() if sector else ''


def _parse_quant_models(detail):
    quant = _extract_detail_section(detail, '量化')
    match = re.search(r'模型\[([^\]]+)\]', quant)
    if not match:
        return []
    models = [
        _strip_markup(item)
        for item in re.split(r'[,，/、\s]+', match.group(1))
        if _strip_markup(item) and _strip_markup(item) not in {'无', '-', '—'}
    ]
    return models[:8]


def _html_table_rows(markdown):
    rows = []
    for row_html in re.findall(r'<tr[^>]*>(.*?)</tr>', markdown or '', flags=re.I | re.S):
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, flags=re.I | re.S)
        if len(cells) < 5:
            continue
        cleaned = [_strip_markup(cell) for cell in cells[:5]]
        if cleaned[0] in {'排名', '#'} or cleaned[1] in {'代码', '股票代码'}:
            continue
        rows.append(cleaned)
    return rows


def _markdown_table_rows(markdown):
    rows = []
    for raw_line in str(markdown or '').splitlines():
        line = raw_line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        cells = [_strip_markup(cell) for cell in line.strip('|').split('|')]
        if len(cells) < 5 or cells[0] in {'排名', '#'} or cells[1] in {'代码', '股票代码'}:
            continue
        rows.append(cells[:5])
    return rows


def _parse_opportunity_report(path):
    report_path = Path(path)
    try:
        content = report_path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        content = ''

    rows = _html_table_rows(content) or _markdown_table_rows(content)
    items = []
    for cells in rows:
        rank_raw, code, name, score_raw, detail = cells
        code_match = re.search(r'\d{6}', code)
        if not code_match:
            continue
        score_match = re.search(r'-?\d+(?:\.\d+)?', score_raw)
        score = float(score_match.group(0)) if score_match else 0.0
        reason = _extract_detail_section(detail, '入选原因') or _truncate_text(detail, 180)
        quant = _extract_detail_section(detail, '量化')
        item = {
            'rank': _safe_int(rank_raw, len(items) + 1, minimum=1),
            'code': code_match.group(0),
            'stock_code': code_match.group(0),
            'name': _strip_markup(name),
            'stock_name': _strip_markup(name),
            'score': score,
            'rating': _parse_rating(detail),
            'recommendation': _parse_recommendation(detail),
            'sector': _parse_sector(detail),
            'industry': _parse_sector(detail),
            'technical': _extract_detail_section(detail, '技术'),
            'quant': quant,
            'sentiment': _extract_detail_section(detail, '情绪资金'),
            'risk': _extract_detail_section(detail, '关键加减分'),
            'reason': reason,
            'summary': reason,
            'quant_models': _parse_quant_models(detail),
            'has_local_kline': False,
        }
        items.append(item)

    market_env = ''
    risk_match = re.search(r'<p[^>]*>\s*⚠️\s*<strong>(.*?)</strong>', content, flags=re.S)
    if risk_match:
        market_env = _strip_markup(risk_match.group(1))
    if not market_env:
        heading_match = re.search(r'##\s*([^\n]+)', content)
        market_env = _strip_markup(heading_match.group(1)) if heading_match else '已解析最新机会挖掘报告'

    return {
        'file': report_path.name,
        'url': _report_url(report_path),
        'updated_at': _format_datetime(report_path.stat().st_mtime) if report_path.exists() else '--',
        'market_env': market_env,
        'items': items,
    }


def _build_quant_model_summary(items):
    model_meta = {
        'RSI': ('量化', '超买超卖', '相对强弱指标触发的拐点或风险信号'),
        'MACD': ('量化', '趋势动能', 'MACD 金叉、背离或趋势确认信号'),
        'KDJ': ('量化', '短线拐点', 'KDJ 低位/高位拐点和短线动能信号'),
        '布林': ('量化', '波动突破', '布林带突破、收敛或回归信号'),
        '均线': ('技术', '趋势结构', '多周期均线趋势与支撑压力结构'),
    }
    summary = {}
    for item in items or []:
        for name in item.get('quant_models') or []:
            entry = summary.setdefault(name, {
                'name': name,
                'count': 0,
                'category': model_meta.get(name, ('量化', '信号确认', '来自机会挖掘报告的量化模型触发'))[0],
                'focus': model_meta.get(name, ('量化', '信号确认', '来自机会挖掘报告的量化模型触发'))[1],
                'description': model_meta.get(name, ('量化', '信号确认', '来自机会挖掘报告的量化模型触发'))[2],
                'examples': [],
            })
            entry['count'] += 1
            if len(entry['examples']) < 4:
                entry['examples'].append({
                    'code': item.get('code') or item.get('stock_code') or '',
                    'name': item.get('name') or item.get('stock_name') or '',
                })
    return sorted(summary.values(), key=lambda item: item['count'], reverse=True)


def _market_symbol_for_code(stock_code):
    code = str(stock_code or '').strip().zfill(6)
    if code.startswith(('43', '83', '87', '92')):
        return {'lower': 'bj', 'upper': 'BJ', 'code': code}
    if code.startswith(('6', '9')):
        return {'lower': 'sh', 'upper': 'SH', 'code': code}
    return {'lower': 'sz', 'upper': 'SZ', 'code': code}


def _xueqiu_symbol(stock_code):
    market = _market_symbol_for_code(stock_code)
    return f"{market['upper']}{market['code']}"


def _stock_external_links(stock_code, stock_name=''):
    market = _market_symbol_for_code(stock_code)
    code = market['code']
    symbol = _xueqiu_symbol(code)
    keyword = (stock_name or code).strip() or code
    encoded_keyword = urllib.parse.quote(keyword)
    encoded_code = urllib.parse.quote(code)
    return {
        'xueqiu_stock': f'https://xueqiu.com/S/{symbol}',
        'xueqiu_search': f'https://xueqiu.com/k?q={encoded_keyword}',
        'jiuyangongshe_home': 'https://www.jiuyangongshe.com/',
        'jiuyangongshe_search': f'https://www.jiuyangongshe.com/search?keyword={encoded_keyword}',
        'eastmoney_quote': f'https://quote.eastmoney.com/{market["lower"]}{code}.html',
        'eastmoney_guba': f'https://guba.eastmoney.com/list,{encoded_code}.html',
        'eastmoney_news_search': f'https://so.eastmoney.com/news/s?keyword={encoded_keyword}',
        'eastmoney_report_search': f'https://so.eastmoney.com/report/s?keyword={encoded_keyword}',
        'ths_news_search': f'https://news.10jqka.com.cn/tapp/search/index/?keyword={encoded_keyword}',
        'sina_quote': f'https://finance.sina.com.cn/realstock/company/{market["lower"]}{code}/nc.shtml',
    }


def _latest_stock_quote(stock_code):
    code = str(stock_code or '').strip().zfill(6)
    api_code = f'{_market_symbol_for_code(code)["lower"]}{code}'
    quote = market_state.get('real_data_cache', {}).get(api_code) or {}
    if not quote:
        stock = next(
            (
                item for item in market_state.get('stocks', [])
                if str(item.get('code') or '').zfill(6) == code
            ),
            None,
        )
        if stock:
            quote = {
                'name': stock.get('name'),
                'price': stock.get('price'),
                'change': stock.get('change'),
                'volume': stock.get('volume'),
                'source': 'market_monitor',
            }
    if not quote:
        return None
    return {
        'code': code,
        'name': quote.get('name') or '',
        'price': round(_safe_float(quote.get('price'), 0.0), 2),
        'change_pct': round(_safe_float(quote.get('change'), 0.0), 2),
        'volume': _safe_float(quote.get('volume'), 0.0),
        'source': quote.get('source') or 'tencent',
        'updated_at': quote.get('updated_at') or _format_datetime(market_state.get('last_update')),
    }


def _stock_kline_summary(kline_payload):
    records = (kline_payload or {}).get('records') or []
    if not records:
        return {
            'available': False,
            'message': (kline_payload or {}).get('message') or '暂无K线数据',
        }
    first = records[0]
    last = records[-1]
    highs = [_safe_float(row.get('high'), None) for row in records]
    lows = [_safe_float(row.get('low'), None) for row in records]
    volumes = [_safe_float(row.get('volume'), 0.0) or 0.0 for row in records]
    highs = [value for value in highs if value is not None]
    lows = [value for value in lows if value is not None]
    first_close = _safe_float(first.get('close'), None)
    last_close = _safe_float(last.get('close'), None)
    change_pct = None
    if first_close and last_close is not None:
        change_pct = round((last_close / first_close - 1) * 100, 2)
    return {
        'available': True,
        'records': len(records),
        'source': (kline_payload or {}).get('source') or '--',
        'latest_date': last.get('date'),
        'latest_close': last_close,
        'latest_change_pct': _safe_float(last.get('pct_chg'), 0.0),
        'range_change_pct': change_pct,
        'range_high': max(highs) if highs else None,
        'range_low': min(lows) if lows else None,
        'avg_volume': round(sum(volumes) / len(volumes), 2) if volumes else None,
    }


def _report_matches_stock(report, stock_code, stock_name=''):
    code = str(stock_code or '').strip().zfill(6)
    name = _strip_markup(stock_name or '')
    text = ' '.join([
        str(report.get('file') or ''),
        str(report.get('type') or ''),
        str(report.get('url') or ''),
    ])
    if code in text or (name and name in text):
        return True
    path = report.get('_path')
    if not path:
        return False
    try:
        report_path = Path(path)
        if not report_path.is_file() or report_path.stat().st_size > 3 * 1024 * 1024:
            return False
        content = report_path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return False
    return code in content or (name and name in content)


def _load_stock_report_history(stock_code, stock_name='', limit=8):
    reports = []
    for report in _report_history_candidates(limit=40):
        if _report_matches_stock(report, stock_code, stock_name):
            reports.append({key: value for key, value in report.items() if key != '_path'})
        if len(reports) >= limit:
            break
    return reports


def _stock_row_code(row):
    for column in ['股票代码', 'stock_code', 'code', '代码', 'symbol', 'ts_code']:
        if column in row and row[column] not in (None, ''):
            codes = normalize_stock_codes([row[column]])
            if codes:
                return codes[0]
    for value in row.values():
        codes = normalize_stock_codes([value])
        if codes:
            return codes[0]
    return ''


def _stock_batch_fields(row):
    preferred = [
        '综合评分', '评级', '建议', '量化', '技术', '位置',
        '量价', '情绪', '板块', 'total_score', 'rating',
        'recommendation', 'score',
    ]
    fields = []
    seen = set()
    for column in preferred + list(row.keys()):
        if column in seen or column not in row:
            continue
        seen.add(column)
        value = row.get(column)
        if value is None or value == '':
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        fields.append({'label': str(column), 'value': str(value)})
        if len(fields) >= 12:
            break
    return fields


def _load_stock_batch_results(stock_code, limit=5):
    code = str(stock_code or '').strip().zfill(6)
    results = []
    for csv_path in _latest_files(RESULTS_DIR, 'batch_results_*.csv', limit=20):
        try:
            df = pd.read_csv(csv_path, dtype=str).fillna('')
        except Exception:
            continue
        for _, series in df.iterrows():
            row = series.to_dict()
            if _stock_row_code(row) != code:
                continue
            results.append({
                'file': csv_path.name,
                'updated_at': _format_datetime(csv_path.stat().st_mtime),
                'url': _report_url(csv_path),
                'fields': _stock_batch_fields(row),
            })
            break
        if len(results) >= limit:
            break
    return results


def _stock_social_sources(stock_code, stock_name=''):
    code = str(stock_code or '').strip().zfill(6)
    name = _strip_markup(stock_name or '')
    links = _stock_external_links(code, name)
    return [
        {
            'platform': '雪球',
            'title': f'{name or code} 雪球个股页',
            'summary': '社区讨论、组合关注、公告和行情聚合入口',
            'url': links['xueqiu_stock'],
            'status': 'external_link',
        },
        {
            'platform': '雪球',
            'title': f'{name or code} 雪球搜索',
            'summary': '按名称检索近期讨论和长文',
            'url': links['xueqiu_search'],
            'status': 'external_link',
        },
        {
            'platform': '韭研公社',
            'title': f'{name or code} 韭研公社检索',
            'summary': '主题投研、事件线索和热帖入口',
            'url': links['jiuyangongshe_search'],
            'status': 'external_link',
        },
        {
            'platform': '东方财富股吧',
            'title': f'{name or code} 股吧讨论',
            'summary': '散户讨论、异动解读和消息反馈',
            'url': links['eastmoney_guba'],
            'status': 'external_link',
        },
    ]


def _stock_news_sources(stock_code, stock_name='', limit=8):
    code = str(stock_code or '').strip().zfill(6)
    name = _strip_markup(stock_name or '')
    keywords = {code}
    if name:
        keywords.add(name)
    items = []

    def add_item(platform, title, summary='', url='', status='cached'):
        clean_title = _truncate_text(title, 120)
        if not clean_title:
            return
        key = (platform, clean_title, url)
        if any((row['platform'], row['title'], row.get('url', '')) == key for row in items):
            return
        items.append({
            'platform': platform,
            'title': clean_title,
            'summary': _truncate_text(summary, 160),
            'url': url,
            'status': status,
        })

    intelligence = _load_market_intelligence()
    for item in intelligence.get('jinshi') or []:
        text = ' '.join([str(item.get('title') or ''), str(item.get('source') or '')])
        if any(keyword and keyword in text for keyword in keywords):
            add_item(
                item.get('source') or '金十数据',
                item.get('title') or '',
                item.get('time') or '',
                item.get('url') or '',
            )

    for item in (intelligence.get('eastmoney') or {}).get('hot_stocks') or []:
        row_code = str(item.get('code') or '').zfill(6)
        if row_code == code or (name and name == str(item.get('name') or '')):
            add_item(
                '东方财富',
                f"{item.get('name') or code} 资金热度",
                f"涨跌幅 {item.get('change_pct', '--')}% · 主力净流入 {item.get('main_net_inflow_text', '--')}",
                _stock_external_links(code, name)['eastmoney_quote'],
            )

    opportunity = _load_latest_opportunities()
    match = next(
        (
            item for item in opportunity.get('items', [])
            if str(item.get('stock_code') or item.get('code') or '').zfill(6) == code
        ),
        None,
    )
    if match:
        add_item(
            '本地机会报告',
            match.get('reason') or match.get('summary') or f'{name or code} 入选机会榜',
            f"{match.get('rating') or '--'} · 评分 {match.get('score', '--')} · {match.get('recommendation') or ''}",
            (opportunity.get('latest_report') or {}).get('url') or '',
        )

    links = _stock_external_links(code, name)
    fallback_links = [
        ('东方财富新闻', f'{name or code} 新闻搜索', '个股新闻、公告和异动解读检索入口', links['eastmoney_news_search']),
        ('东方财富研报', f'{name or code} 研报搜索', '券商研报、评级变化和深度研究检索入口', links['eastmoney_report_search']),
        ('同花顺资讯', f'{name or code} 同花顺资讯', '同花顺新闻、公告和互动信息检索入口', links['ths_news_search']),
    ]
    for platform, title, summary, url in fallback_links:
        if len(items) >= limit:
            break
        add_item(platform, title, summary, url, status='external_link')

    return items[:limit]


def _stock_context_payload(stock_code, stock_name=''):
    codes = normalize_stock_codes([stock_code])
    if not codes:
        return None, 'Invalid stock code'
    code = codes[0]
    opportunity = _load_latest_opportunities()
    opportunity_match = next(
        (
            item for item in opportunity.get('items', [])
            if str(item.get('stock_code') or item.get('code') or '').zfill(6) == code
        ),
        None,
    )
    resolved_name = (
        stock_name
        or (opportunity_match or {}).get('stock_name')
        or (opportunity_match or {}).get('name')
        or (_latest_stock_quote(code) or {}).get('name')
        or ''
    )
    sector = (
        (opportunity_match or {}).get('sector')
        or (opportunity_match or {}).get('industry')
        or ''
    )
    kline_payload, kline_error = _get_stock_kline_payload(code, limit=240)
    if kline_error:
        kline_payload = {
            'code': code,
            'available': False,
            'records': [],
            'message': kline_error,
        }
    trading_clients = TRADING_CLIENT_SERVICE.discover_clients(refresh=False)
    clients = [
        client for client in trading_clients.get('clients', [])
        if (client.get('capabilities') or {}).get('stock')
    ]
    return {
        'success': True,
        'stock': {
            'code': code,
            'name': resolved_name,
            'sector': sector,
            'symbol': _xueqiu_symbol(code),
            'market': _market_symbol_for_code(code),
        },
        'quote': _latest_stock_quote(code),
        'opportunity': opportunity_match,
        'opportunity_report': opportunity.get('latest_report'),
        'analysis_results': _load_stock_batch_results(code),
        'kline_summary': _stock_kline_summary(kline_payload),
        'reports': _load_stock_report_history(code, resolved_name),
        'news': _stock_news_sources(code, resolved_name),
        'social': _stock_social_sources(code, resolved_name),
        'external_links': _stock_external_links(code, resolved_name),
        'trading_clients': {
            'platform': trading_clients.get('platform'),
            'generated_at': trading_clients.get('generated_at'),
            'clients': clients,
        },
    }, None


def _load_latest_opportunities():
    reports = _latest_primary_opportunity_reports(limit=1)
    if not reports:
        return {
            'latest_report': None,
            'market_env': '暂无机会挖掘报告',
            'items': [],
            'quant_models': [],
            'stats': {
                'total': 0,
                'strong_count': 0,
                'average_score': 0,
                'top_score': 0,
            },
        }

    try:
        parsed = _parse_opportunity_report(reports[0])
    except Exception as exc:
        logger.warning(f"解析机会报告失败: {exc}")
        return {
            'latest_report': {
                'file': reports[0].name,
                'url': _report_url(reports[0]),
                'updated_at': _format_datetime(reports[0].stat().st_mtime),
            },
            'market_env': '机会报告解析失败，已降级为空视图',
            'items': [],
            'quant_models': [],
            'stats': {
                'total': 0,
                'strong_count': 0,
                'average_score': 0,
                'top_score': 0,
            },
        }
    items = parsed['items']
    scores = [item['score'] for item in items]
    strong_count = len([item for item in items if item['score'] >= 80])
    return {
        'latest_report': {
            'file': parsed['file'],
            'url': parsed['url'],
            'updated_at': parsed['updated_at'],
        },
        'market_env': parsed['market_env'],
        'items': items,
        'quant_models': _build_quant_model_summary(items),
        'stats': {
            'total': len(items),
            'strong_count': strong_count,
            'average_score': round(sum(scores) / len(scores), 2) if scores else 0,
            'top_score': round(max(scores), 2) if scores else 0,
        },
    }


def _real_sector_rows(intelligence):
    """板块动量：从东财真实行业板块构造（中文名 + 真实涨跌幅 + 主力净流入）。"""
    boards = ((intelligence or {}).get('eastmoney') or {}).get('industry_boards') or []
    rows = []
    for board in boards:
        name = board.get('name')
        if not name:
            continue
        change = round(_safe_float(board.get('change_pct'), 0.0) or 0.0, 2)
        rows.append({
            'name': name,                       # 中文板块名，如「半导体」
            'key': board.get('code'),           # 东财板块代码 BK....
            'avg_change': change,
            'monitored_count': 0,
            'main_net_inflow_text': board.get('main_net_inflow_text'),
            'is_hot': change >= 2.0,
            'leader': None,                      # 领涨股本期后置（spec §10）
        })
    return rows


def _build_market_dashboard():
    stocks = market_state.get('stocks', [])
    real_stocks = [stock for stock in stocks if stock.get('real_api_code')]
    top_movers = sorted(
        real_stocks,
        key=lambda stock: _safe_float(stock.get('change'), 0.0),
        reverse=True,
    )[:8]

    intelligence = _load_market_intelligence()
    # 板块动量：完全由东财真实行业板块驱动（按当日涨跌幅热度降序，含主力净流入）。
    # 不写死板块——拉取失败时返回空（前端显示「暂无数据」），不回退合成板块。
    sector_rows = _real_sector_rows(intelligence)

    index_last_update = market_state.get("index_last_update")
    index_is_fresh = bool(index_last_update and (time.time() - index_last_update <= 600))
    raw_indices = market_state.get("indices", {}) if index_is_fresh else {}
    indices = []
    for code, fallback_name in REAL_INDEX_CODES.items():
        quote = raw_indices.get(code)
        if quote:
            indices.append({
                "code": code,
                "name": quote.get("display_name") or fallback_name,
                "price": round(_safe_float(quote.get("price"), 0.0), 2),
                "change": round(_safe_float(quote.get("change"), 0.0), 2),
                "change_pct": round(_safe_float(quote.get("change_pct"), 0.0), 2),
                "available": True,
                "source": quote.get("source", "tencent"),
                "updated_at": quote.get("updated_at"),
            })
        else:
            indices.append({
                "code": code,
                "name": fallback_name,
                "price": None,
                "change": None,
                "change_pct": None,
                "available": False,
                "source": "tencent",
                "updated_at": None,
            })

    primary_index = next((item for item in indices if item["code"] == "sh000001"), indices[0] if indices else None)

    return {
        'index': primary_index.get("price") if primary_index else None,
        'index_change': primary_index.get("change_pct") if primary_index else None,
        'primary_index': primary_index,
        'indices': indices,
        'index_available': bool(primary_index and primary_index.get("available")),
        'index_last_update': _format_datetime(index_last_update) if index_last_update else None,
        'total_particles': len(stocks),
        'monitored_count': len(real_stocks),
        'limit_up_count': len([stock for stock in real_stocks if stock.get('isLimitUp')]),
        'last_update': _format_datetime(market_state.get('last_update', time.time())),
        'top_movers': [
            {
                'code': stock.get('code'),
                'name': stock.get('name'),
                'price': round(_safe_float(stock.get('price'), 0.0), 2),
                'change': round(_safe_float(stock.get('change'), 0.0), 2),
                'sector': SECTORS[stock.get('sectorId', 0)]['name'] if stock.get('sectorId') is not None else '',
            }
            for stock in top_movers
        ],
        'sectors': sector_rows,
        'news': market_state.get('news', [])[:8],
        'intelligence': intelligence,
    }


def _get_stock_kline_payload(stock_code, period='daily', limit=120):
    return STOCK_KLINE_SERVICE.get_payload(stock_code, period=period, limit=limit)


def _load_batch_summary():
    batch_results = _latest_files(RESULTS_DIR, 'batch_results_*.csv', limit=5)
    batch_details = _latest_files(RESULTS_DIR, 'batch_details_*.json', limit=5)
    batch_predictions = _latest_files(RESULTS_DIR, 'batch_prediction_*.csv', limit=8)

    analysis_runs = []
    for csv_path in batch_results:
        rows = 0
        top_score = 0
        try:
            df = pd.read_csv(csv_path)
            rows = int(len(df))
            if not df.empty:
                score_col = next((col for col in ['综合评分', 'score', 'total_score'] if col in df.columns), None)
                if score_col:
                    top_score = round(float(pd.to_numeric(df[score_col], errors='coerce').max()), 2)
        except Exception:
            pass
        analysis_runs.append({
            'file': csv_path.name,
            'updated_at': _format_datetime(csv_path.stat().st_mtime),
            'rows': rows,
            'top_score': top_score,
            'url': _report_url(csv_path),
        })

    detail_runs = []
    for json_path in batch_details:
        summary = {}
        try:
            summary = json.loads(json_path.read_text(encoding='utf-8'))
        except Exception:
            summary = {}
        detail_runs.append({
            'file': json_path.name,
            'updated_at': _format_datetime(json_path.stat().st_mtime),
            'summary': summary,
            'url': _report_url(json_path),
        })

    prediction_runs = []
    for csv_path in batch_predictions:
        rows = 0
        try:
            rows = int(len(pd.read_csv(csv_path)))
        except Exception:
            rows = 0
        prediction_runs.append({
            'file': csv_path.name,
            'updated_at': _format_datetime(csv_path.stat().st_mtime),
            'rows': rows,
            'url': _report_url(csv_path),
        })

    return {
        'analysis_runs': analysis_runs,
        'detail_runs': detail_runs,
        'prediction_runs': prediction_runs,
        'analysis_count': len(batch_results),
        'prediction_count': len(batch_predictions),
    }


def _report_history_candidates(limit=12):
    patterns = [
        ('机会挖掘HTML', RESULTS_DIR, 'opportunity_discovery_*.html'),
        ('机会Top榜', RESULTS_DIR, 'opportunity_top10_*.md'),
        ('个股分析报告', RESULTS_DIR, 'kronos_analysis_*.html'),
        ('重大利好挖掘', PROJECT_ROOT / 'integrated_results', 'major_positive_news_*.html'),
    ]
    reports = []
    for label, directory, pattern in patterns:
        for path in _latest_files(directory, pattern, limit=limit):
            reports.append({
                'type': label,
                'file': path.name,
                'updated_at': _format_datetime(path.stat().st_mtime),
                'url': _report_url(path),
                'size_kb': round(path.stat().st_size / 1024, 1),
                '_path': str(path),
            })

    reports.sort(key=lambda item: item['updated_at'], reverse=True)
    return reports[:limit]


def _load_report_history(limit=12):
    return [
        {key: value for key, value in item.items() if key != '_path'}
        for item in _report_history_candidates(limit=limit)
    ]


def _module_health():
    modules = [
        ('投资机会挖掘', 'scripts.run_opportunity_discovery', '热门股、多源候选、漏斗过滤、报告生成'),
        ('异步批量分析', 'analysis.batch_processor', '批量采集、并发评分、结果汇总'),
        ('机会评分器', 'analysis.opportunity_scorer', '量化、技术、情绪、板块、事件综合打分'),
        ('专业个股分析', 'analysis.professional_stock_analyzer', '基本面、行业对比、风险过滤'),
        ('资金情绪分析', 'analysis.investor_sentiment', '主力资金、龙虎榜、市场情绪、股吧情绪'),
        ('Kronos预测模型', 'model', 'K线预测与多模型推理'),
    ]
    health = []
    for name, module_name, scope in modules:
        try:
            __import__(module_name)
            status = 'ready'
        except Exception:
            status = 'degraded'
        health.append({
            'name': name,
            'module': module_name,
            'scope': scope,
            'status': status,
        })
    return health


def _update_job(job_id, **updates):
    JOB_SERVICE.update(job_id, **updates)


def _append_job_log(job_id, message):
    JOB_SERVICE.append_log(job_id, message)


class _JobLogHandler(logging.Handler):
    """Forward selected Python logger messages into the WebUI job log."""

    def __init__(self, job_id):
        super().__init__(level=logging.INFO)
        self.job_id = job_id
        self._last_message = None

    def emit(self, record):
        try:
            message = record.getMessage()
            message = " / ".join(line.strip() for line in str(message).splitlines() if line.strip())
            if not message or message == self._last_message:
                return
            self._last_message = message
            if len(message) > 700:
                message = f"{message[:697]}..."
            _append_job_log(self.job_id, message)
        except Exception:
            pass


class _JobLogCapture:
    def __init__(self, job_id, logger_names):
        self.handler = _JobLogHandler(job_id)
        self.logger_names = logger_names
        self.loggers = []

    def __enter__(self):
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        for name in self.logger_names:
            logger = logging.getLogger(name)
            logger.addHandler(self.handler)
            self.loggers.append(logger)
        return self

    def __exit__(self, exc_type, exc, traceback):
        for logger in self.loggers:
            logger.removeHandler(self.handler)
        self.loggers.clear()


def _get_job_snapshot(job_id=None):
    return JOB_SERVICE.snapshot(job_id, limit=20)


def _run_opportunity_job(job_id, params):
    _update_job(job_id, status='running', started_at=datetime.datetime.now().isoformat())
    _append_job_log(job_id, '开始执行投资机会挖掘')
    try:
        from scripts.run_opportunity_discovery import OpportunityDiscovery

        with _JobLogCapture(job_id, ['scripts.run_opportunity_discovery']):
            discovery = OpportunityDiscovery(max_workers=params['workers'])
            report_path = discovery.run(
                limit=params['limit'],
                test_codes=params.get('stock_codes') or None,
                source=params['source'],
            )
        result = {
            'report_path': str(report_path) if report_path else '',
            'report_url': _report_url(report_path) if report_path else None,
        }
        _append_job_log(job_id, f"机会挖掘完成: {result['report_path'] or '未生成报告'}")
        _update_job(
            job_id,
            status='finished',
            finished_at=datetime.datetime.now().isoformat(),
            result=result,
        )
    except Exception as exc:
        _append_job_log(job_id, f'机会挖掘失败: {exc}')
        _update_job(
            job_id,
            status='failed',
            finished_at=datetime.datetime.now().isoformat(),
            error=str(exc),
        )


def _passed_stocks_from_result_df(result_df, limit=50):
    """从批量结果 DataFrame 抽取「通过」个股(code/score/rating)，供前端直达个股分析。

    返回 (stocks, passed_count)。passed_count 为通过总数，stocks 最多 limit 条。
    """
    if result_df is None or getattr(result_df, 'empty', True) or '股票代码' not in result_df.columns:
        return [], 0
    df_pass = result_df
    if '过滤状态' in result_df.columns:
        df_pass = result_df[result_df['过滤状态'] == '通过']
    passed_count = int(len(df_pass))
    stocks = []
    for _, srow in df_pass.head(limit).iterrows():
        code = str(srow.get('股票代码') or '').strip()
        if not code:
            continue
        rating = srow.get('评级')
        rating = str(rating).strip() if rating is not None else ''
        if rating in ('nan', 'None'):
            rating = ''
        stocks.append({
            'code': code,
            'score': _safe_float(srow.get('综合评分'), None),
            'rating': rating or None,
        })
    return stocks, passed_count


def _run_batch_analysis_job(job_id, params):
    _update_job(job_id, status='running', started_at=datetime.datetime.now().isoformat())
    _append_job_log(job_id, '开始执行批量分析')
    try:
        import asyncio
        from analysis.batch_processor import BatchProcessor

        processor = BatchProcessor(
            max_concurrent=params['max_concurrent'],
            collection_timeout=params['collection_timeout'],
            scoring_timeout=params['scoring_timeout'],
            enable_progress_bar=False,
        )
        processor.set_progress_callback(lambda message: _append_job_log(job_id, message))

        result_df, details, stats = asyncio.run(processor.process_batch(
            params['stock_codes'],
            data_types=params['data_types'],
            filter_strategy=params['filter_strategy'],
            skip_scoring=params['skip_scoring'],
        ))

        csv_path = None
        json_path = None
        if result_df is not None:
            csv_path, json_path = processor.save_results(
                result_df,
                details,
                output_dir=str(RESULTS_DIR),
            )

        # 批量完成后抽取「通过」的个股，供前端完成卡直达个股分析（spec 模块 B）。
        passed_rows, passed_count = _passed_stocks_from_result_df(result_df)

        result = {
            'rows': int(len(result_df)) if result_df is not None else 0,
            'statistics': stats.to_dict() if stats else {},
            'csv_path': str(csv_path) if csv_path else '',
            'json_path': str(json_path) if json_path else '',
            'csv_url': _report_url(csv_path) if csv_path else None,
            'json_url': _report_url(json_path) if json_path else None,
            'stocks': passed_rows,
            'passed_count': passed_count,
            'stocks_truncated': passed_count > len(passed_rows),
        }
        _append_job_log(job_id, f"批量分析完成，通过股票 {result['rows']} 只")
        _update_job(
            job_id,
            status='finished',
            finished_at=datetime.datetime.now().isoformat(),
            result=_json_safe(result),
        )
    except Exception as exc:
        _append_job_log(job_id, f'批量分析失败: {exc}')
        _update_job(
            job_id,
            status='failed',
            finished_at=datetime.datetime.now().isoformat(),
            error=str(exc),
        )


def _run_pattern_refresh_job(job_id, params):
    _update_job(job_id, status='running', started_at=datetime.datetime.now().isoformat())
    _append_job_log(job_id, '开始刷新形态指纹库')
    try:
        def log_cb(message):
            _append_job_log(job_id, message)

        result = PATTERN_SEARCH_SERVICE.refresh_fingerprints(params, progress_callback=log_cb)
        _append_job_log(
            job_id,
            f"刷新完成: 总数 {result['total']} 成功 {result['succeeded']} 失败 {result['failed']}"
        )
        _update_job(
            job_id,
            status='finished',
            finished_at=datetime.datetime.now().isoformat(),
            result=result,
        )
    except Exception as exc:
        _append_job_log(job_id, f'指纹刷新失败: {exc}')
        _update_job(
            job_id,
            status='failed',
            finished_at=datetime.datetime.now().isoformat(),
            error=str(exc),
        )


# ----------------------------------------------------------------------------
# 形态指纹库：收盘后自动重建（A 股「隔日快照」问题的服务端兜底）
#   指纹库是隔日冻结的 SQLite 快照，过去只能手动点「刷新」。这里加一个守护线程：
#   工作日收盘整理后若发现快照仍是旧交易日，且无刷新任务在跑，则自动触发重建。
# ----------------------------------------------------------------------------
pattern_autorefresh_thread = None
pattern_autorefresh_lock = threading.Lock()


def _parse_after_close(raw):
    """'15:30' → datetime.time(15,30)；非法值回退 15:30（给收盘后数据整理留足时间）。"""
    try:
        hh, mm = str(raw or '').strip().split(':', 1)
        return datetime.time(hour=int(hh), minute=int(mm))
    except (ValueError, AttributeError, TypeError):
        return datetime.time(hour=15, minute=30)


def _expected_pattern_snapshot_date(now, after_close):
    """最近一个『应已生成指纹』的交易日（粗口径：仅按工作日，不查节假日历）。

    - 工作日且已过收盘整理时刻 → 今天
    - 否则回退到最近的上一个工作日（跨过周末）
    偶发法定节假日会多触发一次重建（无害：拿到的就是最近交易日数据，快照日期随之对齐）。
    """
    today = now.date()
    if today.weekday() < 5 and now.time() >= after_close:
        return today
    probe = today - datetime.timedelta(days=1)
    while probe.weekday() >= 5:  # 5=周六 6=周日
        probe -= datetime.timedelta(days=1)
    return probe


def _pattern_refresh_in_flight():
    """是否已有形态指纹刷新任务在队列/运行中（避免自动调度与手动刷新重复触发）。"""
    try:
        for job in JOB_STORE.list_by_status(('queued', 'running'), limit=50):
            if job.get('type') == 'pattern_refresh':
                return True
    except Exception:  # noqa: BLE001 — 查询失败时按『无在跑任务』处理，最坏多跑一次
        return False
    return False


def _pattern_autorefresh_loop(after_close, interval):
    time.sleep(20)  # 冷启动让位：后端刚拉起时别和首屏请求抢指纹库读
    while True:
        try:
            now = datetime.datetime.now()
            expected = _expected_pattern_snapshot_date(now, after_close)
            current = None
            snapshot_raw = PATTERN_SEARCH_SERVICE.status().get('snapshot_date')
            if snapshot_raw:
                try:
                    current = datetime.date.fromisoformat(snapshot_raw)
                except (ValueError, TypeError):
                    current = None
            if (current is None or current < expected) and not _pattern_refresh_in_flight():
                print(f"[pattern-autorefresh] 指纹库快照={current} < 期望={expected}，自动触发重建")
                JOB_SERVICE.start(
                    "pattern_refresh",
                    PATTERN_SEARCH_SERVICE.refresh_params({}),
                    _run_pattern_refresh_job,
                )
        except Exception as exc:  # noqa: BLE001 — 守护线程绝不能因偶发错误退出
            print(f"[pattern-autorefresh] 调度循环异常: {exc}")
        time.sleep(interval)


def start_pattern_autorefresh():
    """启动『收盘后自动重建形态指纹库』守护线程（进程内只启一次）。

    环境变量：
    - KRONOS_DISABLE_PATTERN_AUTOREFRESH=1   关闭自动重建
    - KRONOS_PATTERN_REFRESH_AFTER=15:30     收盘整理时刻（默认 15:30）
    - KRONOS_PATTERN_REFRESH_INTERVAL=1800   轮询间隔秒（默认 1800，最低 60）
    """
    global pattern_autorefresh_thread
    flag = os.environ.get("KRONOS_DISABLE_PATTERN_AUTOREFRESH", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        print("[pattern-autorefresh] 已被 KRONOS_DISABLE_PATTERN_AUTOREFRESH 关闭")
        return None
    with pattern_autorefresh_lock:
        if pattern_autorefresh_thread and pattern_autorefresh_thread.is_alive():
            return pattern_autorefresh_thread
        after_close = _parse_after_close(os.environ.get("KRONOS_PATTERN_REFRESH_AFTER", "15:30"))
        try:
            interval = float(os.environ.get("KRONOS_PATTERN_REFRESH_INTERVAL", "1800"))
        except (TypeError, ValueError):
            interval = 1800.0
        interval = max(60.0, interval)
        pattern_autorefresh_thread = threading.Thread(
            target=_pattern_autorefresh_loop,
            args=(after_close, interval),
            daemon=True,
        )
        pattern_autorefresh_thread.start()
        print(f"[pattern-autorefresh] 已启动：收盘 {after_close.strftime('%H:%M')} 后自动重建，轮询 {int(interval)}s")
        return pattern_autorefresh_thread


def _run_pattern_backtest_job(job_id, params):
    _update_job(job_id, status='running', started_at=datetime.datetime.now().isoformat())
    _append_job_log(job_id, '开始同类图形回测')
    try:
        def log_cb(message):
            _append_job_log(job_id, message)

        result = PATTERN_SEARCH_SERVICE.backtest(params, progress_callback=log_cb)
        if not result.get('ok'):
            raise RuntimeError(result.get('error') or '回测失败')
        _append_job_log(
            job_id,
            f"回测完成: 命中 {result.get('sample_count', 0)} 个相似样本，"
            f"成功扫描 {result.get('candidates_scanned', 0)}/{result.get('candidates_total', 0)} 只股票"
        )
        _update_job(
            job_id,
            status='finished',
            finished_at=datetime.datetime.now().isoformat(),
            result=result,
        )
    except Exception as exc:
        _append_job_log(job_id, f'形态回测失败: {exc}')
        _update_job(
            job_id,
            status='failed',
            finished_at=datetime.datetime.now().isoformat(),
            error=str(exc),
        )


DESKTOP_PAGES = {
    'features': {
        'title': '总览',
        'subtitle': '市场状态、核心指标、热榜与个股快搜',
    },
    'watchlist': {
        'title': '自选',
        'subtitle': '自选股实时行情、快捷分析与一键管理',
    },
    'workbench': {
        'title': '分析工作台',
        'subtitle': '机会挖掘、批量分析、任务日志与结果复盘',
    },
    'patterns': {
        'title': '形态搜股',
        'subtitle': '手绘曲线或载入个股形态检索相似股票',
    },
    'reports': {
        'title': '报告与健康',
        'subtitle': '本地报告与模块运行状态',
    },
    'settings': {
        'title': '后台配置',
        'subtitle': '配置 AI 分析模型、TuShare 数据源和模型运行状态',
    },
    'about': {
        'title': '关于',
        'subtitle': '免责声明 · 使用条款 · 数据来源',
    },
}

DESKTOP_PAGE_ALIASES = {
    'opportunities': 'workbench',
    'overview': 'features',  # 「总览」「功能总览」已合并为 features 单页
}


def resolve_desktop_page(page):
    """Resolve legacy desktop URLs to the visible desktop information architecture."""
    return DESKTOP_PAGE_ALIASES.get(page, page)


def get_server_config():
    """Return WebUI host, port, and debug mode from environment."""
    host = os.environ.get('KRONOS_HOST', '0.0.0.0')
    port = int(os.environ.get('KRONOS_PORT', '7070'))
    desktop_mode = os.environ.get('KRONOS_DESKTOP') == 'tauri'
    debug_env = os.environ.get('FLASK_DEBUG')
    debug = (debug_env not in ('0', 'false', 'False')) if debug_env is not None else not desktop_mode
    return host, port, debug


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
        user_root=USER_ROOT,
        kronos_cls=Kronos if MODEL_AVAILABLE else None,
        tokenizer_cls=KronosTokenizer if MODEL_AVAILABLE else None,
        predictor_cls=KronosPredictor if MODEL_AVAILABLE else None,
        pandas=pd,
        load_data_file=load_data_file,
        create_prediction_chart=create_prediction_chart,
        save_prediction_results=save_prediction_results,
    )
