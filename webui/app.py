import os
import pandas as pd
import numpy as np
import json
import plotly.graph_objects as go
import plotly.utils
import re
import uuid
from html import unescape
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, abort
from flask_cors import CORS
import sys
import warnings
import datetime
import threading
import time
import random
import math
import plistlib
import platform
import shutil
import subprocess
import urllib.request
import urllib.parse

warnings.filterwarnings('ignore')

# Add project root directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from model import Kronos, KronosTokenizer, KronosPredictor

    MODEL_AVAILABLE = True
except ImportError:
    MODEL_AVAILABLE = False
    print("Warning: Kronos model cannot be imported, will use simulated data for demonstration")

app = Flask(__name__)
CORS(app)

# === Pattern Search ===
from analysis.pattern_matcher import (
    TARGET_LENGTH as PATTERN_TARGET_LENGTH,
    comparison_window as pattern_comparison_window,
    search_similar as pattern_search_similar,
)
from analysis.pattern_store import PatternStore

PATTERN_DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'pattern_fingerprints.db'
_pattern_store_instance = None


def _get_pattern_store():
    global _pattern_store_instance
    if _pattern_store_instance is None:
        _pattern_store_instance = PatternStore(PATTERN_DB_PATH)
        _pattern_store_instance.init_schema()
    return _pattern_store_instance


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / 'results'
REPORT_DIRS = {
    'results': RESULTS_DIR,
    'reports': PROJECT_ROOT / 'reports',
    'integrated_results': PROJECT_ROOT / 'integrated_results',
}
PRIMARY_OPPORTUNITY_REPORT_RE = re.compile(r'^opportunity_top10_\d{8}_\d{6}\.md$')

analysis_jobs = {}
analysis_jobs_lock = threading.Lock()
market_intelligence_cache = {
    'ts': 0,
    'payload': None,
}
MARKET_INTELLIGENCE_TTL = 180
TRADING_CLIENT_CONFIG_PATH = PROJECT_ROOT / 'config' / 'trading_client_adapters.json'
TRADING_CLIENT_DISCOVERY_TTL = 30
trading_client_cache = {
    'ts': 0,
    'payload': None,
}

# Global variables to store models
tokenizer = None
model = None
predictor = None

# Available model configurations
AVAILABLE_MODELS = {
    'kronos-mini': {
        'name': 'Kronos-mini',
        'model_id': 'northwind9898/Kronos-mini',
        'tokenizer_id': 'northwind9898/Kronos-Tokenizer-2k',
        'context_length': 2048,
        'params': '4.1M',
        'description': 'Lightweight model, suitable for fast prediction'
    },
    'kronos-small': {
        'name': 'Kronos-small',
        'model_id': 'northwind9898/Kronos-small',
        'tokenizer_id': 'northwind9898/Kronos-Tokenizer-base',
        'context_length': 512,
        'params': '24.7M',
        'description': 'Small model, balanced performance and speed'
    },
    'kronos-base': {
        'name': 'Kronos-base',
        'model_id': 'northwind9898/Kronos-base',
        'tokenizer_id': 'northwind9898/Kronos-Tokenizer-base',
        'context_length': 512,
        'params': '102.3M',
        'description': 'Base model, provides better prediction quality'
    }
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
    { "id": 0, "key": 'ai', "name": 'AGI', "color": '#ff0055', "angle": 0, "count": 800, "hot": True },
    { "id": 1, "key": 'robot', "name": 'Humanoid Robots', "color": '#00ff88', "angle": 1.2, "count": 600, "hot": True },
    { "id": 2, "key": 'quantum', "name": 'Quantum Computing', "color": '#00ccff', "angle": 2.4, "count": 500, "hot": False },
    { "id": 3, "key": 'fusion', "name": 'Nuclear Fusion', "color": '#ffff00', "angle": 3.6, "count": 400, "hot": True },
    { "id": 4, "key": 'space', "name": 'Deep Space', "color": '#ff8800', "angle": 4.8, "count": 450, "hot": False },
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
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as f:
            content = f.read().decode('gbk', errors='ignore')

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
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as f:
            content = f.read().decode('gbk')
        
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


def load_data_files():
    """Scan data directory and return available data files"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    data_files = []

    if os.path.exists(data_dir):
        for file in os.listdir(data_dir):
            if file.endswith(('.csv', '.feather')):
                file_path = os.path.join(data_dir, file)
                file_size = os.path.getsize(file_path)
                data_files.append({
                    'name': file,
                    'path': file_path,
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
        # Create prediction results directory
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prediction_results')
        os.makedirs(results_dir, exist_ok=True)

        # Generate filename
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'prediction_{timestamp}.json'
        filepath = os.path.join(results_dir, filename)

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
        return filepath

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
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


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


def _request_json(url, headers=None, timeout=5):
    last_exc = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                headers=headers or {
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'application/json,text/plain,*/*',
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    raise last_exc


def _fetch_jinshi_flash(limit=12):
    """Fetch Jinshi flash headlines for homepage macro tape."""
    url = 'https://flash-api.jin10.com/get_flash_list?channel=-8200&vip=1'
    payload = _request_json(
        url,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
            ),
            'Accept': 'application/json,text/plain,*/*',
            'Referer': 'https://www.jin10.com/',
            'x-app-id': 'SO1EJGmNgCtmpcPF',
            'x-version': '1.0.0',
        },
        timeout=4,
    )
    rows = payload.get('data') if isinstance(payload, dict) else []
    items = []
    for row in rows or []:
        data = row.get('data') or {}
        title = data.get('title') or data.get('vip_title') or ''
        content = data.get('content') or ''
        text = _strip_markup(title or content)
        if not text:
            continue
        source = _strip_markup(data.get('source') or '')
        link = data.get('source_link') or data.get('link') or ''
        items.append({
            'id': row.get('id'),
            'time': row.get('time'),
            'title': _truncate_text(text, 150),
            'source': source or '金十数据',
            'important': bool(row.get('important')),
            'url': link,
        })
        if len(items) >= limit:
            break
    return items


def _eastmoney_money_text(value):
    number = _safe_float(value, 0.0)
    if abs(number) >= 100000000:
        return f"{number / 100000000:.2f}亿"
    if abs(number) >= 10000:
        return f"{number / 10000:.1f}万"
    return f"{number:.0f}"


def _fetch_eastmoney_clist(fs, fid='f3', limit=10):
    """Fetch Eastmoney board/stock ranking rows for display only, not K-line/OHLC sourcing."""
    params = {
        'pn': '1',
        'pz': str(limit),
        'po': '1',
        'np': '1',
        'fltt': '2',
        'invt': '2',
        'fid': fid,
        'fs': fs,
        'fields': 'f12,f14,f2,f3,f62',
    }
    url = 'https://push2.eastmoney.com/api/qt/clist/get?' + urllib.parse.urlencode(params)
    payload = _request_json(
        url,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
            ),
            'Accept': 'application/json,text/plain,*/*',
            'Referer': 'https://quote.eastmoney.com/',
        },
        timeout=4,
    )
    rows = ((payload or {}).get('data') or {}).get('diff') or []
    items = []
    for row in rows:
        code = str(row.get('f12') or '').strip()
        name = str(row.get('f14') or '').strip()
        if not code or not name:
            continue
        money_flow = _safe_float(row.get('f62'), 0.0)
        items.append({
            'code': code,
            'name': name,
            'price': _safe_float(row.get('f2'), None),
            'change_pct': round(_safe_float(row.get('f3'), 0.0), 2),
            'main_net_inflow': money_flow,
            'main_net_inflow_text': _eastmoney_money_text(money_flow),
            'source': 'eastmoney',
        })
    return items


def _load_market_intelligence():
    now = time.time()
    cached = market_intelligence_cache.get('payload')
    if cached and now - market_intelligence_cache.get('ts', 0) < MARKET_INTELLIGENCE_TTL:
        return cached

    payload = {
        'updated_at': _format_datetime(now),
        'jinshi': [],
        'eastmoney': {
            'industry_boards': [],
            'concept_boards': [],
            'money_boards': [],
            'hot_stocks': [],
            'updated_at': _format_datetime(now),
        },
        'errors': {},
    }

    try:
        payload['jinshi'] = _fetch_jinshi_flash(limit=12)
    except Exception as exc:
        payload['errors']['jinshi'] = str(exc)

    try:
        payload['eastmoney']['industry_boards'] = _fetch_eastmoney_clist(
            'm:90+t:2', fid='f3', limit=8
        )
    except Exception as exc:
        payload['errors']['eastmoney_industry'] = str(exc)

    try:
        payload['eastmoney']['concept_boards'] = _fetch_eastmoney_clist(
            'm:90+t:3', fid='f3', limit=8
        )
    except Exception as exc:
        payload['errors']['eastmoney_concept'] = str(exc)

    try:
        payload['eastmoney']['money_boards'] = _fetch_eastmoney_clist(
            'm:90+t:2', fid='f62', limit=8
        )
    except Exception as exc:
        payload['errors']['eastmoney_money_boards'] = str(exc)

    try:
        payload['eastmoney']['hot_stocks'] = _fetch_eastmoney_clist(
            'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', fid='f62', limit=12
        )
    except Exception as exc:
        payload['errors']['eastmoney_hot_stocks'] = str(exc)

    market_intelligence_cache['payload'] = payload
    market_intelligence_cache['ts'] = now
    return payload


def _normalize_stock_codes(raw_codes):
    if raw_codes is None:
        return []
    if isinstance(raw_codes, list):
        candidates = raw_codes
    else:
        candidates = re.split(r'[\s,，;；|/]+', str(raw_codes))

    normalized = []
    seen = set()
    for item in candidates:
        token = str(item or '').strip().upper()
        if not token:
            continue
        if token.startswith(('SH', 'SZ', 'BJ')) and len(token) >= 8:
            token = token[2:]
        if token.endswith(('.SH', '.SZ', '.BJ')):
            token = token.split('.')[0]
        match = re.search(r'\d{6}', token)
        if not match:
            continue
        code = match.group(0)
        if code not in seen:
            normalized.append(code)
            seen.add(code)
    return normalized


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


def _load_trading_client_config():
    default_config = {
        'discovery': {
            'macos_app_categories': ['public.app-category.finance'],
            'include_all_macos_finance_apps': False,
            'name_keywords': [
                '股票', '证券', '交易', '行情', '财富', '金融', '同花顺',
                '通达信', '大智慧', '指南针', '雪球', '富途', '老虎',
                'futu', 'niuniu', 'tiger', 'tradingview',
            ],
        },
        'jump': {
            'default_mode': 'keyboard',
            'keyboard_delay_ms': 700,
        },
        'adapters': [],
    }
    if not TRADING_CLIENT_CONFIG_PATH.exists():
        return default_config
    try:
        with TRADING_CLIENT_CONFIG_PATH.open('r', encoding='utf-8') as fh:
            loaded = json.load(fh)
    except Exception:
        return default_config

    config = default_config.copy()
    config['discovery'] = {**default_config['discovery'], **loaded.get('discovery', {})}
    config['jump'] = {**default_config['jump'], **loaded.get('jump', {})}
    config['adapters'] = loaded.get('adapters', [])
    return config


def _slugify_client_id(value):
    slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', str(value or '').strip()).strip('-').lower()
    return slug[:80] or 'client'


def _unique_client_id(base, used_ids):
    client_id = _slugify_client_id(base)
    original = client_id
    idx = 2
    while client_id in used_ids:
        client_id = f'{original}-{idx}'
        idx += 1
    used_ids.add(client_id)
    return client_id


def _client_match_score(client, adapter):
    match = adapter.get('match') or {}
    score = 0
    bundle_id = str(client.get('bundle_id') or '').lower()
    name = str(client.get('name') or '').lower()
    path = str(client.get('path') or '').lower()
    executable = str(client.get('executable') or '').lower()
    schemes = {str(item).lower() for item in client.get('url_schemes') or []}

    if bundle_id and bundle_id in {str(item).lower() for item in match.get('bundle_ids', [])}:
        score += 100
    if schemes.intersection({str(item).lower() for item in match.get('url_schemes', [])}):
        score += 80
    for keyword in match.get('name_keywords', []):
        kw = str(keyword).lower()
        if kw and (kw in name or kw in path or kw in executable):
            score += 25
    for executable_name in match.get('executable_names', []):
        if str(executable_name).lower() in executable:
            score += 35
    return score


def _match_trading_adapter(client, adapters):
    scored = [
        (_client_match_score(client, adapter), adapter)
        for adapter in adapters
    ]
    scored = [item for item in scored if item[0] > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _looks_like_trading_client(client, config):
    category = str(client.get('category') or '')
    discovery = config.get('discovery', {})
    category_match = category in set(discovery.get('macos_app_categories', []))
    haystack = ' '.join([
        str(client.get('name') or ''),
        str(client.get('path') or ''),
        str(client.get('executable') or ''),
    ]).lower()
    for keyword in discovery.get('name_keywords', []):
        if str(keyword).lower() in haystack:
            return True
    return bool(category_match and discovery.get('include_all_macos_finance_apps'))


def _macos_read_app_bundle(app_path):
    info_path = app_path / 'Contents' / 'Info.plist'
    if not info_path.exists():
        return None
    try:
        with info_path.open('rb') as fh:
            info = plistlib.load(fh)
    except Exception:
        return None

    schemes = []
    for item in info.get('CFBundleURLTypes') or []:
        schemes.extend(item.get('CFBundleURLSchemes') or [])
    executable = info.get('CFBundleExecutable') or app_path.stem
    return {
        'platform': 'macos',
        'name': (
            info.get('CFBundleDisplayName') or
            info.get('CFBundleName') or
            app_path.stem
        ),
        'path': str(app_path),
        'bundle_id': info.get('CFBundleIdentifier') or '',
        'executable': executable,
        'category': info.get('LSApplicationCategoryType') or '',
        'url_schemes': sorted(set(str(item) for item in schemes if item)),
    }


def _discover_macos_trading_clients(config):
    roots = [
        Path('/Applications'),
        Path.home() / 'Applications',
        Path('/System/Applications'),
    ]
    clients = []
    seen_paths = set()
    for root in roots:
        if not root.exists():
            continue
        for app_path in root.glob('*.app'):
            resolved = str(app_path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            client = _macos_read_app_bundle(app_path)
            if client and _looks_like_trading_client(client, config):
                clients.append(client)
    return clients


def _discover_windows_trading_clients(config):
    clients = []
    adapters = config.get('adapters', [])
    roots = [
        os.environ.get('ProgramFiles'),
        os.environ.get('ProgramFiles(x86)'),
        os.environ.get('LOCALAPPDATA'),
        os.environ.get('APPDATA'),
    ]
    executable_names = set()
    for adapter in adapters:
        executable_names.update(adapter.get('match', {}).get('executable_names', []))
        executable_names.update(adapter.get('windows', {}).get('executable_names', []))
    for name in executable_names:
        path = shutil.which(name)
        if path:
            clients.append({
                'platform': 'windows',
                'name': Path(path).stem,
                'path': path,
                'bundle_id': '',
                'executable': Path(path).name,
                'category': '',
                'url_schemes': [],
            })

    shortcut_roots = [
        Path(os.environ.get('PROGRAMDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs',
        Path(os.environ.get('APPDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs',
    ]
    for root in shortcut_roots:
        if not root.exists():
            continue
        for path in root.glob('**/*.lnk'):
            client = {
                'platform': 'windows',
                'name': path.stem,
                'path': str(path),
                'bundle_id': '',
                'executable': path.name,
                'category': '',
                'url_schemes': [],
            }
            if _looks_like_trading_client(client, config):
                clients.append(client)

    for root_raw in roots:
        if not root_raw:
            continue
        root = Path(root_raw)
        if not root.exists():
            continue
        for exe_name in executable_names:
            for path in root.glob(f'**/{exe_name}'):
                if path.is_file():
                    clients.append({
                        'platform': 'windows',
                        'name': path.stem,
                        'path': str(path),
                        'bundle_id': '',
                        'executable': path.name,
                        'category': '',
                        'url_schemes': [],
                    })
    return clients


def _parse_desktop_entry(path):
    data = {}
    try:
        for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                data[key.strip()] = value.strip()
    except Exception:
        return None
    exec_cmd = data.get('Exec', '').split()
    return {
        'platform': 'linux',
        'name': data.get('Name') or path.stem,
        'path': str(path),
        'bundle_id': '',
        'executable': exec_cmd[0] if exec_cmd else '',
        'category': data.get('Categories', ''),
        'url_schemes': [
            item.rsplit('/', 1)[-1]
            for item in data.get('MimeType', '').split(';')
            if item.startswith('x-scheme-handler/')
        ],
    }


def _discover_linux_trading_clients(config):
    roots = [
        Path('/usr/share/applications'),
        Path('/usr/local/share/applications'),
        Path.home() / '.local/share/applications',
    ]
    clients = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob('*.desktop'):
            client = _parse_desktop_entry(path)
            if client and _looks_like_trading_client(client, config):
                clients.append(client)
    return clients


def _platform_key():
    system = platform.system().lower()
    if system == 'darwin':
        return 'macos'
    if system == 'windows':
        return 'windows'
    if system == 'linux':
        return 'linux'
    return system


def _platform_trading_clients(config):
    system = _platform_key()
    if system == 'macos':
        return _discover_macos_trading_clients(config)
    if system == 'windows':
        return _discover_windows_trading_clients(config)
    if system == 'linux':
        return _discover_linux_trading_clients(config)
    return []


def _adapter_templates(adapter, platform_key):
    templates = []
    templates.extend(adapter.get('url_templates') or [])
    platform_config = adapter.get(platform_key) or {}
    templates.extend(platform_config.get('url_templates') or [])
    return templates


def _client_capabilities(client, adapter, config):
    platform_key = client.get('platform') or _platform_key()
    direct_targets = {
        item.get('target')
        for item in _adapter_templates(adapter or {}, platform_key)
        if item.get('target')
    }
    keyboard_targets = set((adapter or {}).get('keyboard_targets') or [])
    if not keyboard_targets and config.get('jump', {}).get('default_mode') == 'keyboard':
        keyboard_targets = {'stock', 'board', 'search'}
    return {
        'stock': 'stock' in direct_targets or 'stock' in keyboard_targets,
        'board': 'board' in direct_targets or 'board' in keyboard_targets or 'search' in keyboard_targets,
        'direct_targets': sorted(direct_targets),
        'keyboard_targets': sorted(keyboard_targets),
    }


def _discover_trading_clients(refresh=False):
    now = time.time()
    if (
        not refresh and
        trading_client_cache.get('payload') and
        now - trading_client_cache.get('ts', 0) < TRADING_CLIENT_DISCOVERY_TTL
    ):
        return trading_client_cache['payload']

    config = _load_trading_client_config()
    adapters = config.get('adapters', [])
    used_ids = set()
    clients = []
    seen = set()
    for client in _platform_trading_clients(config):
        key = (client.get('platform'), client.get('bundle_id'), client.get('path'))
        if key in seen:
            continue
        seen.add(key)
        adapter = _match_trading_adapter(client, adapters) or {}
        adapter_id = adapter.get('id') or client.get('bundle_id') or client.get('name')
        client_id = _unique_client_id(adapter_id, used_ids)
        capabilities = _client_capabilities(client, adapter, config)
        client.update({
            'id': client_id,
            'display_name': adapter.get('display_name') or client.get('name'),
            'adapter_id': adapter.get('id') or '',
            'capabilities': capabilities,
            'jump_mode': (adapter.get('jump') or {}).get('mode') or config.get('jump', {}).get('default_mode', 'keyboard'),
        })
        if capabilities.get('stock') or capabilities.get('board'):
            clients.append(client)

    payload = {
        'platform': _platform_key(),
        'clients': sorted(clients, key=lambda item: item.get('display_name') or item.get('name') or ''),
        'config_path': str(TRADING_CLIENT_CONFIG_PATH),
        'generated_at': _format_datetime(now),
    }
    trading_client_cache['payload'] = payload
    trading_client_cache['ts'] = now
    return payload


def _market_prefix_for_code(stock_code):
    code = str(stock_code or '').strip()
    if code.startswith(('43', '83', '87', '92')):
        return {'lower': 'bj', 'upper': 'BJ', 'ths_market': '48'}
    if code.startswith(('6', '9')):
        return {'lower': 'sh', 'upper': 'SH', 'ths_market': '17'}
    return {'lower': 'sz', 'upper': 'SZ', 'ths_market': '33'}


def _template_context(target):
    stock_code = _normalize_stock_codes(target.get('stock_code') or target.get('code'))
    code = stock_code[0] if stock_code else ''
    board_code = str(target.get('board_code') or '').strip().upper()
    board_name = str(target.get('board_name') or target.get('sector') or target.get('name') or '').strip()
    stock_name = str(target.get('stock_name') or target.get('name') or '').strip()
    query = code or board_code or board_name or stock_name
    market = _market_prefix_for_code(code)
    return {
        'code': code,
        'stock_code': code,
        'stock_name': stock_name,
        'board_code': board_code,
        'board_name': board_name,
        'query': query,
        'market': market['lower'],
        'market_upper': market['upper'],
        'ths_market': market['ths_market'],
    }


def _render_jump_template(template, context):
    try:
        return str(template).format(**{
            key: urllib.parse.quote(str(value), safe='')
            for key, value in context.items()
        })
    except KeyError:
        return ''


def _run_detached(args):
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _launch_client_app(client):
    system = client.get('platform') or _platform_key()
    path = client.get('path') or ''
    if system == 'macos':
        if path.endswith('.app'):
            return _run_detached(['open', path])
        return _run_detached(['open', '-a', client.get('display_name') or client.get('name') or path])
    if system == 'windows':
        if path and hasattr(os, 'startfile'):
            os.startfile(path)
            return True
        return _run_detached([path]) if path else False
    if system == 'linux':
        executable = client.get('executable') or path
        return _run_detached([executable]) if executable else False
    return False


def _applescript_string(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _send_keyboard_jump(client, query, delay_ms):
    if not query:
        return False, '缺少可跳转的代码或名称'
    system = client.get('platform') or _platform_key()
    _launch_client_app(client)
    delay_seconds = max(float(delay_ms or 700) / 1000, 0.1)

    if system == 'macos':
        app_name = client.get('name') or client.get('display_name')
        script = [
            f'tell application {_applescript_string(app_name)} to activate',
            f'delay {delay_seconds:.2f}',
            'tell application "System Events"',
            f'keystroke {_applescript_string(query)}',
            'key code 36',
            'end tell',
        ]
        args = ['osascript']
        for line in script:
            args.extend(['-e', line])
        completed = subprocess.run(args, capture_output=True, text=True, timeout=5)
        if completed.returncode == 0:
            return True, '已通过客户端快捷输入跳转'
        message = (completed.stderr or completed.stdout or '').strip()
        return False, message or '系统未允许键盘自动化'

    if system == 'windows':
        ps_query = str(query).replace("'", "''")
        command = (
            f"Start-Sleep -Milliseconds {int(delay_seconds * 1000)}; "
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait('{ps_query}{{ENTER}}')"
        )
        completed = subprocess.run(
            ['powershell', '-NoProfile', '-Command', command],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if completed.returncode == 0:
            return True, '已通过客户端快捷输入跳转'
        return False, (completed.stderr or completed.stdout or '').strip() or '键盘自动化失败'

    if system == 'linux':
        xdotool = shutil.which('xdotool')
        if not xdotool:
            return False, '未安装 xdotool，已尝试启动客户端'
        completed = subprocess.run(
            [xdotool, 'type', '--delay', '20', str(query)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if completed.returncode == 0:
            subprocess.run([xdotool, 'key', 'Return'], capture_output=True, timeout=2)
            return True, '已通过客户端快捷输入跳转'
        return False, (completed.stderr or completed.stdout or '').strip() or '键盘自动化失败'

    return False, '当前系统暂不支持键盘跳转'


def _open_trading_client_target(client_id, target):
    discovered = _discover_trading_clients(refresh=True)
    config = _load_trading_client_config()
    client = next((item for item in discovered['clients'] if item['id'] == client_id), None)
    if not client:
        return {'success': False, 'error': '未发现该交易客户端'}

    adapters = config.get('adapters', [])
    adapter = _match_trading_adapter(client, adapters) or {}
    target_type = str(target.get('type') or '').strip() or ('stock' if target.get('stock_code') else 'board')
    context = _template_context(target)

    for item in _adapter_templates(adapter, client.get('platform') or _platform_key()):
        if item.get('target') != target_type:
            continue
        url = _render_jump_template(item.get('url') or '', context)
        if not url:
            continue
        if client.get('platform') == 'macos' and client.get('bundle_id'):
            _run_detached(['open', '-b', client['bundle_id'], url])
        elif client.get('platform') == 'windows' and hasattr(os, 'startfile'):
            os.startfile(url)
        else:
            _run_detached(['open', url] if client.get('platform') == 'macos' else ['xdg-open', url])
        return {
            'success': True,
            'mode': 'scheme',
            'client': client.get('display_name'),
        }

    delay_ms = config.get('jump', {}).get('keyboard_delay_ms', 700)
    success, message = _send_keyboard_jump(client, context['query'], delay_ms)
    return {
        'success': success,
        'mode': 'keyboard',
        'client': client.get('display_name'),
        'message': message,
    }


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


def _extract_section(detail, label, limit=180):
    match = re.search(rf'【{re.escape(label)}】([^【]+)', detail)
    if not match:
        return ''
    return _truncate_text(match.group(1), limit)


QUANT_MODEL_LIBRARY = {
    '均衡双均线': {
        'category': '趋势',
        'focus': '中短均线共振',
        'description': '用快慢均线判断趋势方向，适合过滤刚形成多头排列的标的。',
    },
    '多重突破': {
        'category': '突破',
        'focus': '价格突破确认',
        'description': '同时观察关键高点、平台压力和短周期区间突破，强调确认度。',
    },
    '量能突破': {
        'category': '量价',
        'focus': '放量有效性',
        'description': '关注成交量相对近期均量的放大，判断突破是否有资金承接。',
    },
    '海龟交易': {
        'category': '趋势',
        'focus': '通道突破',
        'description': '以通道高低点识别趋势启动，偏向捕捉强势延续行情。',
    },
    '机器学习RF': {
        'category': '机器学习',
        'focus': '多因子非线性',
        'description': '随机森林模型融合技术、量价、位置等特征，输出概率型信号。',
    },
    '趋势回踩': {
        'category': '低吸',
        'focus': '强趋势回落',
        'description': '寻找上升趋势中的缩量回踩和重新转强位置。',
    },
    '资金趋势': {
        'category': '资金',
        'focus': '资金连续性',
        'description': '跟踪主力资金净流入和连续性，识别资金推动型机会。',
    },
    '均线共振': {
        'category': '趋势',
        'focus': '均线簇排列',
        'description': '多周期均线方向一致时提高趋势得分。',
    },
    '统计量化': {
        'category': '统计',
        'focus': '历史分布偏离',
        'description': '基于收益、波动和位置分布判断当前价格状态。',
    },
}


def _extract_quant_models(quant_text):
    models = []
    text = _strip_markup(quant_text)
    match = re.search(r'模型\[(.*?)\]', text)
    if match:
        models = [item.strip() for item in re.split(r'[,，、/]+', match.group(1)) if item.strip()]
    return models


def _build_quant_model_summary(items):
    model_counts = {}
    model_examples = {}
    for item in items:
        for model_name in item.get('quant_models', []):
            model_counts[model_name] = model_counts.get(model_name, 0) + 1
            model_examples.setdefault(model_name, []).append({
                'code': item.get('code'),
                'name': item.get('name'),
                'score': item.get('score'),
            })

    summary = []
    for model_name, count in sorted(model_counts.items(), key=lambda pair: pair[1], reverse=True):
        meta = QUANT_MODEL_LIBRARY.get(model_name, {})
        summary.append({
            'name': model_name,
            'count': count,
            'category': meta.get('category', '量化'),
            'focus': meta.get('focus', '信号确认'),
            'description': meta.get('description', '来自当前机会挖掘报告的触发模型。'),
            'examples': model_examples.get(model_name, [])[:4],
        })
    return summary


def _parse_opportunity_report(path):
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return {
            'file': path.name,
            'path': str(path),
            'url': _report_url(path),
            'updated_at': _format_datetime(path.stat().st_mtime),
            'market_env': '',
            'items': [],
        }

    market_env = ''
    env_match = re.search(r'>\s*\*\*市场环境\*\*:\s*(.+)', content)
    if env_match:
        market_env = _strip_markup(env_match.group(1))

    row_pattern = re.compile(
        r'<tr>\s*'
        r'<td[^>]*>\s*(\d+)\s*</td>\s*'
        r'<td[^>]*>\s*([0-9]{6})\s*</td>\s*'
        r'<td[^>]*>\s*(.*?)\s*</td>\s*'
        r'<td[^>]*>\s*([0-9.]+)\s*</td>\s*'
        r'<td[^>]*>\s*(.*?)\s*</td>\s*'
        r'</tr>',
        re.S,
    )

    items = []
    for row in row_pattern.finditer(content):
        detail = _strip_markup(row.group(5))
        overview = _extract_section(detail, '概览', 120)
        rating_match = re.search(r'评级\s*([A-Z+]+)', overview)
        recommendation_match = re.search(r'建议[:：]\s*([^；]+)', overview)
        risk_match = re.search(r'追高风险:\s*([^ ]+\s*[^ ]*\([^)]+\))', detail)
        score = _safe_float(row.group(4), 0.0)
        quant = _extract_section(detail, '量化', 160)
        quant_models = _extract_quant_models(quant)
        stock_code = row.group(2)
        item = {
            'rank': int(row.group(1)),
            'code': stock_code,
            'name': _strip_markup(row.group(3)),
            'score': round(score, 2),
            'rating': rating_match.group(1) if rating_match else '',
            'recommendation': _truncate_text(recommendation_match.group(1), 32) if recommendation_match else '',
            'change': _extract_section(detail, '涨幅', 110),
            'sector': _extract_section(detail, '板块', 100),
            'quant': quant,
            'quant_models': quant_models,
            'technical': _extract_section(detail, '技术', 100),
            'fundamental': _extract_section(detail, '基本面', 100),
            'sentiment': _extract_section(detail, '情绪资金', 120),
            'news': _extract_section(detail, '消息', 110),
            'reason': _extract_section(detail, '入选原因', 180),
            'latest_news': _extract_section(detail, '最新动态', 180),
            'risk': _truncate_text(risk_match.group(1), 60) if risk_match else _extract_section(detail, '高级', 100),
            'has_local_kline': bool(_local_kline_candidates(stock_code, 'daily')),
        }
        items.append(item)

    return {
        'file': path.name,
        'path': str(path),
        'url': _report_url(path),
        'updated_at': _format_datetime(path.stat().st_mtime),
        'market_env': market_env,
        'items': items,
    }


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

    parsed = _parse_opportunity_report(reports[0])
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


def _build_market_dashboard():
    stocks = market_state.get('stocks', [])
    real_stocks = [stock for stock in stocks if stock.get('real_api_code')]
    top_movers = sorted(
        real_stocks,
        key=lambda stock: _safe_float(stock.get('change'), 0.0),
        reverse=True,
    )[:8]

    sector_rows = []
    for sector in market_state.get('sectors', []):
        sector_stocks = [
            stock for stock in stocks
            if stock.get('sectorId') == sector.get('id') and stock.get('real_api_code')
        ]
        changes = [_safe_float(stock.get('change'), 0.0) for stock in sector_stocks]
        avg_change = round(sum(changes) / len(changes), 2) if changes else 0.0
        leader = max(sector_stocks, key=lambda stock: _safe_float(stock.get('change'), 0.0), default=None)
        sector_rows.append({
            'name': sector.get('name'),
            'key': sector.get('key'),
            'color': sector.get('color'),
            'avg_change': avg_change,
            'monitored_count': len(sector_stocks),
            'is_hot': bool(sector.get('hot')),
            'leader': {
                'code': leader.get('code'),
                'name': leader.get('name'),
                'change': round(_safe_float(leader.get('change'), 0.0), 2),
            } if leader else None,
        })

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
        'sectors': sorted(sector_rows, key=lambda row: row['avg_change'], reverse=True),
        'news': market_state.get('news', [])[:8],
        'intelligence': _load_market_intelligence(),
    }


def _sina_symbol_for_code(stock_code):
    code = str(stock_code or '').strip().zfill(6)
    if code.startswith(('43', '83', '87', '92')):
        return f'bj{code}'
    if code.startswith(('6', '9')):
        return f'sh{code}'
    return f'sz{code}'


def _period_to_sina_scale(period):
    period_map = {
        '1m': '1',
        '5m': '5',
        '5': '5',
        '15m': '15',
        '30m': '30',
        '60m': '60',
        '1h': '60',
        'daily': '240',
        '1d': '240',
        'day': '240',
    }
    return period_map.get(str(period or 'daily'), '240')


def _local_kline_candidates(stock_code, period):
    data_dir = PROJECT_ROOT / 'data'
    if not data_dir.exists():
        return []
    prefixes = []
    if str(period) in ('5m', '5'):
        prefixes.extend(['5m', '5min'])
    prefixes.extend(['1d', 'daily', 'day'])
    patterns = [f'{prefix}_{stock_code}.*' for prefix in prefixes]
    candidates = []
    for pattern in patterns:
        candidates.extend(data_dir.glob(pattern))
    return [path for path in candidates if path.suffix.lower() in ('.csv', '.feather')]


def _frame_to_kline_records(df, limit):
    if df is None or df.empty:
        return []

    work = df.copy()
    timestamp_col = next(
        (col for col in ['timestamps', 'timestamp', 'date', 'datetime', 'time'] if col in work.columns),
        None,
    )
    if timestamp_col:
        work[timestamp_col] = pd.to_datetime(work[timestamp_col], errors='coerce')
        work = work.dropna(subset=[timestamp_col])
        work = work.sort_values(timestamp_col)
    else:
        work['_timestamp'] = pd.RangeIndex(start=1, stop=len(work) + 1)
        timestamp_col = '_timestamp'

    for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors='coerce')
    work = work.dropna(subset=[col for col in ['open', 'high', 'low', 'close'] if col in work.columns])

    records = []
    for _, row in work.tail(limit).iterrows():
        timestamp = row[timestamp_col]
        if isinstance(timestamp, pd.Timestamp):
            date_text = timestamp.strftime('%Y-%m-%d')
        else:
            date_text = str(timestamp)
        open_price = float(row['open'])
        close_price = float(row['close'])
        pct_chg = ((close_price - open_price) / open_price * 100) if open_price else 0.0
        records.append({
            'date': date_text,
            'open': open_price,
            'close': close_price,
            'high': float(row['high']),
            'low': float(row['low']),
            'volume': float(row['volume']) if 'volume' in row and pd.notna(row.get('volume')) else 0.0,
            'amount': float(row['amount']) if 'amount' in row and pd.notna(row.get('amount')) else 0.0,
            'pct_chg': round(pct_chg, 2),
        })
    return records


def _load_local_kline(stock_code, period, limit):
    for path in _local_kline_candidates(stock_code, period):
        try:
            if path.suffix.lower() == '.csv':
                df = pd.read_csv(path)
            else:
                df = pd.read_feather(path)
            records = _frame_to_kline_records(df, limit)
            if records:
                return records, path.name
        except Exception as exc:
            print(f"Failed to load local kline {path}: {exc}")
    return [], None


def _parse_sina_klines(klines):
    records = []
    prev_close = None
    for item in klines or []:
        if not isinstance(item, dict):
            continue
        open_price = _safe_float(item.get('open'))
        close_price = _safe_float(item.get('close'))
        if open_price <= 0 or close_price <= 0:
            continue
        high_price = _safe_float(item.get('high'), max(open_price, close_price))
        low_price = _safe_float(item.get('low'), min(open_price, close_price))
        pct_chg = 0.0
        if prev_close and prev_close > 0:
            pct_chg = (close_price / prev_close - 1) * 100
        records.append({
            'date': str(item.get('day') or item.get('date') or ''),
            'open': open_price,
            'close': close_price,
            'high': high_price,
            'low': low_price,
            'volume': _safe_float(item.get('volume')),
            'amount': _safe_float(item.get('amount')),
            'pct_chg': round(pct_chg, 2),
        })
        prev_close = close_price
    return records


def _fetch_sina_kline(stock_code, period, limit):
    params = {
        'symbol': _sina_symbol_for_code(stock_code),
        'scale': _period_to_sina_scale(period),
        'ma': 'no',
        'datalen': str(limit),
    }
    url = (
        'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
        'CN_MarketData.getKLineData?' + urllib.parse.urlencode(params)
    )
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
            ),
            'Accept': 'application/json,text/plain,*/*',
            'Referer': 'https://finance.sina.com.cn/',
        },
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        payload = json.loads(response.read().decode('utf-8'))
    records = _parse_sina_klines(payload if isinstance(payload, list) else [])
    return records, ''


def _get_stock_kline_payload(stock_code, period='daily', limit=120):
    codes = _normalize_stock_codes([stock_code])
    if not codes:
        return None, 'Invalid stock code'
    code = codes[0]
    normalized_limit = _safe_int(limit, 120, minimum=30, maximum=500)
    normalized_period = str(period or 'daily')

    local_records, local_source = _load_local_kline(code, normalized_period, normalized_limit)
    if local_records:
        return {
            'code': code,
            'name': '',
            'period': normalized_period,
            'source': f'local:{local_source}',
            'available': True,
            'records': local_records,
        }, None

    try:
        records, stock_name = _fetch_sina_kline(code, normalized_period, normalized_limit)
        if records:
            return {
                'code': code,
                'name': stock_name,
                'period': normalized_period,
                'source': 'sina',
                'available': True,
                'records': records,
            }, None
        return {
            'code': code,
            'name': '',
            'period': normalized_period,
            'source': 'sina',
            'available': False,
            'records': [],
            'message': '暂无K线数据：本地没有该股票数据，Sina 行情接口未返回记录。',
        }, None
    except Exception as exc:
        return {
            'code': code,
            'name': '',
            'period': normalized_period,
            'source': 'sina',
            'available': False,
            'records': [],
            'message': '暂无K线数据：本地没有该股票数据，Sina 行情接口暂不可用。',
            'detail': str(exc),
        }, None


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


def _load_report_history(limit=12):
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
            })

    reports.sort(key=lambda item: item['updated_at'], reverse=True)
    return reports[:limit]


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


def _create_job(job_type, params):
    job_id = uuid.uuid4().hex[:12]
    job = {
        'id': job_id,
        'type': job_type,
        'status': 'queued',
        'created_at': datetime.datetime.now().isoformat(),
        'started_at': None,
        'finished_at': None,
        'params': params,
        'logs': ['任务已进入队列'],
        'result': None,
        'error': None,
    }
    with analysis_jobs_lock:
        analysis_jobs[job_id] = job
    return job


def _update_job(job_id, **updates):
    with analysis_jobs_lock:
        job = analysis_jobs.get(job_id)
        if not job:
            return
        job.update(_json_safe(updates))


def _append_job_log(job_id, message):
    with analysis_jobs_lock:
        job = analysis_jobs.get(job_id)
        if not job:
            return
        logs = job.setdefault('logs', [])
        logs.append(f"{_format_datetime()} {str(message).strip()}")
        if len(logs) > 120:
            del logs[:-120]


def _get_job_snapshot(job_id=None):
    with analysis_jobs_lock:
        if job_id:
            job = analysis_jobs.get(job_id)
            return _json_safe(job.copy()) if job else None
        jobs = sorted(
            [job.copy() for job in analysis_jobs.values()],
            key=lambda item: item.get('created_at', ''),
            reverse=True,
        )
        return _json_safe(jobs[:20])


def _run_opportunity_job(job_id, params):
    _update_job(job_id, status='running', started_at=datetime.datetime.now().isoformat())
    _append_job_log(job_id, '开始执行投资机会挖掘')
    try:
        from scripts.run_opportunity_discovery import OpportunityDiscovery

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

        result = {
            'rows': int(len(result_df)) if result_df is not None else 0,
            'statistics': stats.to_dict() if stats else {},
            'csv_path': str(csv_path) if csv_path else '',
            'json_path': str(json_path) if json_path else '',
            'csv_url': _report_url(csv_path) if csv_path else None,
            'json_url': _report_url(json_path) if json_path else None,
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
        from scripts.build_pattern_fingerprints import build_all

        store = _get_pattern_store()

        def log_cb(message):
            _append_job_log(job_id, message)

        result = build_all(
            store,
            limit=params.get('limit'),
            max_workers=params.get('workers', 16),
            progress_callback=log_cb,
        )
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


@app.route('/')
def index():
    """Stock analysis home page"""
    return render_template('stock_analysis_home.html')


@app.route('/prediction')
def prediction_console():
    """Kronos prediction console"""
    return render_template('index.html')


DESKTOP_PAGES = {
    'overview': {
        'title': '总览',
        'subtitle': '市场状态、核心指标与实时信息',
    },
    'opportunities': {
        'title': '投资机会',
        'subtitle': 'Top 机会、K线与单股量化视图',
    },
    'workbench': {
        'title': '分析工作台',
        'subtitle': '机会挖掘、批量分析与任务队列',
    },
    'patterns': {
        'title': '形态搜股',
        'subtitle': '手绘曲线或载入个股形态检索相似股票',
    },
    'reports': {
        'title': '报告与健康',
        'subtitle': '本地报告、批量结果与模块状态',
    },
}


@app.route('/desktop')
@app.route('/desktop/<page>')
def desktop_page(page='overview'):
    """Tauri desktop multi-page shell."""
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
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        lookback = int(data.get('lookback', 400))
        pred_len = int(data.get('pred_len', 120))

        # Get prediction quality parameters
        temperature = float(data.get('temperature', 0.6))
        top_p = float(data.get('top_p', 0.9))
        sample_count = int(data.get('sample_count', 10))

        if not file_path:
            return jsonify({'error': 'File path cannot be empty'}), 400

        # Load data
        df, error = load_data_file(file_path)
        if error:
            return jsonify({'error': error}), 400

        if len(df) < lookback:
            return jsonify({'error': f'Insufficient data length, need at least {lookback} rows'}), 400

        # Perform prediction
        if MODEL_AVAILABLE and predictor is not None:
            try:
                # Use real Kronos model
                # Only use necessary columns: OHLCV, excluding amount
                required_cols = ['open', 'high', 'low', 'close']
                if 'volume' in df.columns:
                    required_cols.append('volume')

                # Process time period selection
                start_date = data.get('start_date')

                if start_date:
                    # Custom time period - fix logic: use data within selected window
                    start_dt = pd.to_datetime(start_date)

                    # Find data after start time
                    mask = df['timestamps'] >= start_dt
                    time_range_df = df[mask]

                    # Ensure sufficient data: lookback + pred_len
                    if len(time_range_df) < lookback + pred_len:
                        return jsonify({
                                           'error': f'Insufficient data from start time {start_dt.strftime("%Y-%m-%d %H:%M")}, need at least {lookback + pred_len} data points, currently only {len(time_range_df)} available'}), 400

                    # Use first lookback data points within selected window for prediction
                    x_df = time_range_df.iloc[:lookback][required_cols]
                    x_timestamp = time_range_df.iloc[:lookback]['timestamps']

                    # Use last pred_len data points within selected window as actual values
                    y_timestamp = time_range_df.iloc[lookback:lookback + pred_len]['timestamps']

                    # Calculate actual time period length
                    start_timestamp = time_range_df['timestamps'].iloc[0]
                    end_timestamp = time_range_df['timestamps'].iloc[lookback + pred_len - 1]
                    time_span = end_timestamp - start_timestamp

                    prediction_type = f"Kronos model prediction (within selected window: first {lookback} data points for prediction, last {pred_len} data points for comparison, time span: {time_span})"
                else:
                    # Use latest data
                    x_df = df.iloc[:lookback][required_cols]
                    x_timestamp = df.iloc[:lookback]['timestamps']
                    y_timestamp = df.iloc[lookback:lookback + pred_len]['timestamps']
                    prediction_type = "Kronos model prediction (latest data)"

                # Ensure timestamps are Series format, not DatetimeIndex, to avoid .dt attribute error in Kronos model
                if isinstance(x_timestamp, pd.DatetimeIndex):
                    x_timestamp = pd.Series(x_timestamp, name='timestamps')
                if isinstance(y_timestamp, pd.DatetimeIndex):
                    y_timestamp = pd.Series(y_timestamp, name='timestamps')

                pred_df = predictor.predict(
                    df=x_df,
                    x_timestamp=x_timestamp,
                    y_timestamp=y_timestamp,
                    pred_len=pred_len,
                    T=temperature,
                    top_p=top_p,
                    sample_count=sample_count
                )

            except Exception as e:
                return jsonify({'error': f'Kronos model prediction failed: {str(e)}'}), 500
        else:
            return jsonify({'error': 'Kronos model not loaded, please load model first'}), 400

        # Prepare actual data for comparison (if exists)
        actual_data = []
        actual_df = None

        if start_date:  # Custom time period
            # Fix logic: use data within selected window
            # Prediction uses first 400 data points within selected window
            # Actual data should be last 120 data points within selected window
            start_dt = pd.to_datetime(start_date)

            # Find data starting from start_date
            mask = df['timestamps'] >= start_dt
            time_range_df = df[mask]

            if len(time_range_df) >= lookback + pred_len:
                # Get last 120 data points within selected window as actual values
                actual_df = time_range_df.iloc[lookback:lookback + pred_len]

                for i, (_, row) in enumerate(actual_df.iterrows()):
                    actual_data.append({
                        'timestamp': row['timestamps'].isoformat(),
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row['volume']) if 'volume' in row else 0,
                        'amount': float(row['amount']) if 'amount' in row else 0
                    })
        else:  # Latest data
            # Prediction uses first 400 data points
            # Actual data should be 120 data points after first 400 data points
            if len(df) >= lookback + pred_len:
                actual_df = df.iloc[lookback:lookback + pred_len]
                for i, (_, row) in enumerate(actual_df.iterrows()):
                    actual_data.append({
                        'timestamp': row['timestamps'].isoformat(),
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row['volume']) if 'volume' in row else 0,
                        'amount': float(row['amount']) if 'amount' in row else 0
                    })

        # Create chart - pass historical data start position
        if start_date:
            # Custom time period: find starting position of historical data in original df
            start_dt = pd.to_datetime(start_date)
            mask = df['timestamps'] >= start_dt
            historical_start_idx = df[mask].index[0] if len(df[mask]) > 0 else 0
        else:
            # Latest data: start from beginning
            historical_start_idx = 0

        chart_json = create_prediction_chart(df, pred_df, lookback, pred_len, actual_df, historical_start_idx)

        # Prepare prediction result data - fix timestamp calculation logic
        if 'timestamps' in df.columns:
            if start_date:
                # Custom time period: use selected window data to calculate timestamps
                start_dt = pd.to_datetime(start_date)
                mask = df['timestamps'] >= start_dt
                time_range_df = df[mask]

                if len(time_range_df) >= lookback:
                    # Calculate prediction timestamps starting from last time point of selected window
                    last_timestamp = time_range_df['timestamps'].iloc[lookback - 1]
                    time_diff = df['timestamps'].iloc[1] - df['timestamps'].iloc[0]
                    future_timestamps = pd.date_range(
                        start=last_timestamp + time_diff,
                        periods=pred_len,
                        freq=time_diff
                    )
                else:
                    future_timestamps = []
            else:
                # Latest data: calculate from last time point of entire data file
                last_timestamp = df['timestamps'].iloc[-1]
                time_diff = df['timestamps'].iloc[1] - df['timestamps'].iloc[0]
                future_timestamps = pd.date_range(
                    start=last_timestamp + time_diff,
                    periods=pred_len,
                    freq=time_diff
                )
        else:
            future_timestamps = range(len(df), len(df) + pred_len)

        prediction_results = []
        for i, (_, row) in enumerate(pred_df.iterrows()):
            prediction_results.append({
                'timestamp': future_timestamps[i].isoformat() if i < len(future_timestamps) else f"T{i}",
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']) if 'volume' in row else 0,
                'amount': float(row['amount']) if 'amount' in row else 0
            })

        # Save prediction results to file
        try:
            save_prediction_results(
                file_path=file_path,
                prediction_type=prediction_type,
                prediction_results=prediction_results,
                actual_data=actual_data,
                input_data=x_df,
                prediction_params={
                    'lookback': lookback,
                    'pred_len': pred_len,
                    'temperature': temperature,
                    'top_p': top_p,
                    'sample_count': sample_count,
                    'start_date': start_date if start_date else 'latest'
                }
            )
        except Exception as e:
            print(f"Failed to save prediction results: {e}")

        return jsonify({
            'success': True,
            'prediction_type': prediction_type,
            'chart': chart_json,
            'prediction_results': prediction_results,
            'actual_data': actual_data,
            'has_comparison': len(actual_data) > 0,
            'message': f'Prediction completed, generated {pred_len} prediction points' + (
                f', including {len(actual_data)} actual data points for comparison' if len(actual_data) > 0 else '')
        })

    except Exception as e:
        return jsonify({'error': f'Prediction failed: {str(e)}'}), 500


@app.route('/api/load-model', methods=['POST'])
def load_model():
    """Load Kronos model"""
    global tokenizer, model, predictor

    try:
        if not MODEL_AVAILABLE:
            return jsonify({'error': 'Kronos model library not available'}), 400

        data = request.get_json()
        model_key = data.get('model_key', 'kronos-small')
        device = data.get('device', 'cpu')

        if model_key not in AVAILABLE_MODELS:
            return jsonify({'error': f'Unsupported model: {model_key}'}), 400

        model_config = AVAILABLE_MODELS[model_key]

        # 使用统一的模型加载方式
        from modelscope import snapshot_download
        from pathlib import Path
        import shutil

        # 设置模型目录
        model_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / 'models'
        model_dir.mkdir(exist_ok=True)

        # 一级目录结构，直接在models下
        tokenizer_dir = model_dir / "Kronos-Tokenizer-base"  # 统一使用base tokenizer
        if model_key == 'kronos-mini':
            model_dir_path = model_dir / "Kronos-mini"
            model_model_id = 'northwind9898/Kronos-mini'
        elif model_key == 'kronos-small':
            model_dir_path = model_dir / "Kronos-small"
            model_model_id = 'northwind9898/Kronos-small'
        elif model_key == 'kronos-base':
            model_dir_path = model_dir / "Kronos-base"
            model_model_id = 'northwind9898/Kronos-base'
        else:
            return jsonify({'error': f'Unsupported model: {model_key}'}), 400

        # Load tokenizer
        if tokenizer_dir.exists() and (tokenizer_dir / "config.json").exists():
            print("Found local tokenizer, loading...")
            tokenizer = KronosTokenizer.from_pretrained(str(tokenizer_dir))
        else:
            # 下载并保存到一级目录
            print("Downloading tokenizer...")
            downloaded_path = snapshot_download('northwind9898/Kronos-Tokenizer-base', cache_dir=str(model_dir))
            if "northwind9898" in downloaded_path:
                if not tokenizer_dir.exists():
                    shutil.move(downloaded_path, str(tokenizer_dir))
                tokenizer = KronosTokenizer.from_pretrained(str(tokenizer_dir))
            else:
                tokenizer = KronosTokenizer.from_pretrained(downloaded_path)

        # Load model
        if model_dir_path.exists() and (model_dir_path / "config.json").exists():
            print("Found local model, loading...")
            model = Kronos.from_pretrained(str(model_dir_path))
        else:
            # 下载并保存到一级目录
            print("Downloading model...")
            downloaded_path = snapshot_download(model_model_id, cache_dir=str(model_dir))
            if "northwind9898" in downloaded_path:
                if not model_dir_path.exists():
                    shutil.move(downloaded_path, str(model_dir_path))
                model = Kronos.from_pretrained(str(model_dir_path))
            else:
                model = Kronos.from_pretrained(downloaded_path)

        # Create predictor
        predictor = KronosPredictor(model, tokenizer, device=device, max_context=model_config['context_length'])

        return jsonify({
            'success': True,
            'message': f'Model loaded successfully: {model_config["name"]} ({model_config["params"]}) on {device}',
            'model_info': {
                'name': model_config['name'],
                'params': model_config['params'],
                'context_length': model_config['context_length'],
                'description': model_config['description']
            }
        })

    except Exception as e:
        return jsonify({'error': f'Model loading failed: {str(e)}'}), 500


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
    if MODEL_AVAILABLE:
        if predictor is not None:
            return jsonify({
                'available': True,
                'loaded': True,
                'message': 'Kronos model loaded and available',
                'current_model': {
                    'name': predictor.model.__class__.__name__,
                    'device': str(next(predictor.model.parameters()).device)
                }
            })
        else:
            return jsonify({
                'available': True,
                'loaded': False,
                'message': 'Kronos model available but not loaded'
            })
    else:
        return jsonify({
            'available': False,
            'loaded': False,
            'message': 'Kronos model library not available, please install related dependencies'
        })


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


@app.route('/api/opportunity-discovery/start', methods=['POST'])
def start_opportunity_discovery():
    """Start the existing investment opportunity discovery flow in the background."""
    data = request.get_json(silent=True) or {}
    source = str(data.get('source', 'multi')).strip()
    if source not in ('multi', 'heat', 'moneyflow_dc'):
        return jsonify({'error': 'Unsupported source, use multi / heat / moneyflow_dc'}), 400

    stock_codes = _normalize_stock_codes(data.get('stock_codes'))
    params = {
        'limit': _safe_int(data.get('limit'), 80, minimum=5, maximum=500),
        'workers': _safe_int(data.get('workers'), 8, minimum=1, maximum=32),
        'source': source,
        'stock_codes': stock_codes,
    }
    job = _create_job('opportunity_discovery', params)
    thread = threading.Thread(
        target=_run_opportunity_job,
        args=(job['id'], params),
        daemon=True,
    )
    thread.start()
    return jsonify({'success': True, 'job': _get_job_snapshot(job['id'])})


@app.route('/api/batch-analysis/start', methods=['POST'])
def start_batch_analysis():
    """Start the existing batch analysis flow in the background."""
    data = request.get_json(silent=True) or {}
    stock_codes = _normalize_stock_codes(data.get('stock_codes'))
    if not stock_codes:
        return jsonify({'error': 'Please provide at least one 6-digit stock code'}), 400

    requested_types = data.get('data_types') or ['comprehensive']
    if isinstance(requested_types, str):
        requested_types = re.split(r'[\s,，;；]+', requested_types)
    allowed_types = {'comprehensive', 'fundamental', 'sentiment'}
    data_types = [item for item in requested_types if item in allowed_types]
    if not data_types:
        data_types = ['comprehensive']

    filter_strategy = str(data.get('filter_strategy', 'balanced')).strip() or 'balanced'
    params = {
        'stock_codes': stock_codes[:100],
        'data_types': data_types,
        'filter_strategy': filter_strategy,
        'max_concurrent': _safe_int(data.get('max_concurrent'), 5, minimum=1, maximum=20),
        'collection_timeout': _safe_int(data.get('collection_timeout'), 30, minimum=5, maximum=180),
        'scoring_timeout': _safe_int(data.get('scoring_timeout'), 15, minimum=5, maximum=120),
        'skip_scoring': bool(data.get('skip_scoring', False)),
    }
    job = _create_job('batch_analysis', params)
    thread = threading.Thread(
        target=_run_batch_analysis_job,
        args=(job['id'], params),
        daemon=True,
    )
    thread.start()
    return jsonify({'success': True, 'job': _get_job_snapshot(job['id'])})


@app.route('/api/jobs')
def list_jobs():
    """List recent analysis jobs."""
    return jsonify({'jobs': _get_job_snapshot()})


@app.route('/api/trading-clients')
def list_trading_clients():
    """Discover installed desktop trading clients for context-menu jumps."""
    refresh = str(request.args.get('refresh') or '').lower() in {'1', 'true', 'yes'}
    return jsonify(_json_safe(_discover_trading_clients(refresh=refresh)))


@app.route('/api/trading-clients/open', methods=['POST'])
def open_trading_client():
    """Jump to stock/board targets in an installed desktop trading client."""
    payload = request.get_json(silent=True) or {}
    client_id = str(payload.get('client_id') or '').strip()
    target = payload.get('target') or {}
    if not client_id or not isinstance(target, dict):
        return jsonify({'success': False, 'error': '参数不完整'}), 400
    result = _open_trading_client_target(client_id, target)
    status = 200 if result.get('success') else 400
    return jsonify(_json_safe(result)), status


@app.route('/api/pattern-search/status')
def pattern_search_status():
    store = _get_pattern_store()
    status = store.current_status()

    staleness_days = None
    warning = None
    if status.get('last_snapshot_date'):
        try:
            d = datetime.date.fromisoformat(status['last_snapshot_date'])
            staleness_days = (datetime.date.today() - d).days
            if staleness_days >= 3:
                warning = f"指纹数据已陈旧 {staleness_days} 天，建议刷新"
        except ValueError:
            staleness_days = None
    if not status.get('available'):
        warning = warning or "指纹库尚未生成，请先点击刷新"

    return jsonify({
        'available': status.get('available', False),
        'snapshot_date': status.get('last_snapshot_date'),
        'total_stocks': status.get('total_stocks', 0),
        'updated_at': status.get('last_finished_at'),
        'last_status': status.get('last_status'),
        'staleness_days': staleness_days,
        'warning': warning,
    })


@app.route('/api/pattern-search/match', methods=['POST'])
def pattern_search_match():
    payload = request.get_json(silent=True) or {}
    curve = payload.get('curve')
    if not isinstance(curve, list) or not (5 <= len(curve) <= PATTERN_TARGET_LENGTH):
        return jsonify({
            'error': f'curve 必须为长度 5-{PATTERN_TARGET_LENGTH} 的数组'
        }), 400
    try:
        curve = [float(x) for x in curve]
    except (TypeError, ValueError):
        return jsonify({'error': 'curve 元素必须为数字'}), 400

    top_n = _safe_int(payload.get('top_n'), default=30, minimum=1, maximum=200)
    window_days = _safe_int(
        payload.get('window_days'),
        default=PATTERN_TARGET_LENGTH,
        minimum=5,
        maximum=PATTERN_TARGET_LENGTH,
    )
    query_offset_days = _safe_int(
        payload.get('query_offset_days'),
        default=0,
        minimum=0,
        maximum=5,
    )
    query_curve = pattern_comparison_window(
        curve,
        max_days=window_days,
        offset_days=query_offset_days,
    )
    if not query_curve:
        return jsonify({'error': '当前相似天数/回推设置下曲线数据不足'}), 400

    filters = payload.get('filters') or {}
    markets = filters.get('market') or None
    if markets and not isinstance(markets, list):
        markets = [markets]
    industry = filters.get('industry') or None
    exclude_st = bool(filters.get('exclude_st', True))

    store = _get_pattern_store()
    started = time.time()
    results = pattern_search_similar(
        store, curve, top_n=top_n,
        markets=markets, industry=industry, exclude_st=exclude_st,
        window_days=window_days, query_offset_days=query_offset_days,
    )
    elapsed_ms = int((time.time() - started) * 1000)

    status = store.current_status()
    return jsonify({
        'matches': results,
        'query_curve': query_curve,
        'window_days': len(query_curve),
        'requested_window_days': window_days,
        'query_offset_days': query_offset_days,
        'snapshot_date': status.get('last_snapshot_date'),
        'compute_ms': elapsed_ms,
        'count': len(results),
    })


@app.route('/api/pattern-search/stocks')
def pattern_search_stocks():
    query = str(request.args.get('q') or '').strip()
    limit = _safe_int(request.args.get('limit'), default=10, minimum=1, maximum=30)
    if not query:
        return jsonify({'stocks': [], 'count': 0})

    store = _get_pattern_store()
    stocks = store.search_stocks(query, limit=limit)
    return jsonify({
        'stocks': stocks,
        'count': len(stocks),
        'query': query,
    })


@app.route('/api/pattern-search/stock-curve/<stock_code>')
def pattern_search_stock_curve(stock_code):
    code = (stock_code or '').strip()
    if not code:
        return jsonify({'error': '股票代码不能为空'}), 400
    store = _get_pattern_store()
    fp = store.load_fingerprint(code)
    if fp is None:
        return jsonify({
            'available': False,
            'message': '该股不在指纹库中（可能停牌、未上市或库尚未刷新）',
        }), 404
    return jsonify({
        'available': True,
        'stock_code': fp.stock_code,
        'stock_name': fp.stock_name,
        'market': fp.market,
        'industry': fp.industry,
        'normalized_curve': fp.normalized_curve,
        'mean_slope': fp.mean_slope,
        'latest_close': fp.latest_close,
        'latest_change_pct': fp.latest_change_pct,
        'snapshot_date': fp.snapshot_date.isoformat(),
    })


@app.route('/api/pattern-search/refresh', methods=['POST'])
def pattern_search_refresh():
    payload = request.get_json(silent=True) or {}
    limit_raw = payload.get('limit')
    params = {
        'limit': _safe_int(limit_raw, default=None, minimum=1, maximum=10000) if limit_raw else None,
        'workers': _safe_int(payload.get('workers'), default=16, minimum=1, maximum=64),
    }
    job = _create_job('pattern_refresh', params)
    thread = threading.Thread(
        target=_run_pattern_refresh_job, args=(job['id'], params), daemon=True
    )
    thread.start()
    return jsonify({'job_id': job['id'], 'status': 'queued'})


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
    return send_from_directory(str(Path(__file__).resolve().parent / 'templates'), 'market_particles.html')


@app.route('/api/snapshot')
def get_snapshot():
    """Get real-time market snapshot"""
    return jsonify(market_state)


# Initialize Market Data on startup
print("Initializing market data...")
init_market()

# Start Monitor Thread
monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()


if __name__ == '__main__':
    print("Starting Kronos Web UI...")

    print(f"Model availability: {MODEL_AVAILABLE}")
    if MODEL_AVAILABLE:
        print("Tip: You can load Kronos model through /api/load-model endpoint")
    else:
        print("Tip: Will use simulated data for demonstration")

    host = os.environ.get('KRONOS_HOST', '0.0.0.0')
    port = int(os.environ.get('KRONOS_PORT', '7070'))
    desktop_mode = os.environ.get('KRONOS_DESKTOP') == 'tauri'
    debug_env = os.environ.get('FLASK_DEBUG')
    debug = (debug_env not in ('0', 'false', 'False')) if debug_env is not None else not desktop_mode

    app.run(debug=debug, host=host, port=port, use_reloader=debug)
