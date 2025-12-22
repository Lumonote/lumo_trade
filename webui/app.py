import os
import pandas as pd
import numpy as np
import json
import plotly.graph_objects as go
import plotly.utils
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sys
import warnings
import datetime
import threading
import time
import random
import math
import urllib.request

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

# Market Global State
market_state = {
    "stocks": [],
    "index": 3824.56,
    "index_change": 2.15,
    "trades": [],
    "news": [],
    "sectors": SECTORS,
    "last_update": time.time(),
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

def fetch_real_market_data():
    try:
        url = f"http://qt.gtimg.cn/q={','.join(ALL_REAL_CODES)}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as f:
            content = f.read().decode('gbk')
        
        lines = content.strip().split(';')
        total_change = 0
        count = 0
        
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
                    
                    total_change += change_pct
                    count += 1
        
        if count > 0:
            avg_change = total_change / count
            market_state["index_change"] = avg_change
            market_state["index"] = 3800 * (1 + avg_change / 100)
            
    except Exception as e:
        print(f"Error fetching real data: {e}")

def monitor_loop():
    print("Market data monitor started...")
    while True:
        try:
            # 1. Fetch Real Data
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


@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')


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


@app.route('/particles')
def particles():
    """Render market particles visualization"""
    return render_template('market_particles.html')


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

    app.run(debug=True, host='0.0.0.0', port=7070)
