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
warnings.filterwarnings('ignore')

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from model import Kronos, KronosTokenizer, KronosPredictor
    MODEL_AVAILABLE = True
except ImportError:
    MODEL_AVAILABLE = False
    print("警告: Kronos模型无法导入，将使用模拟数据进行演示")

app = Flask(__name__)
CORS(app)

# 全局变量存储模型
tokenizer = None
model = None
predictor = None

# 可用的模型配置
AVAILABLE_MODELS = {
    'kronos-mini': {
        'name': 'Kronos-mini',
        'model_id': 'NeoQuasar/Kronos-mini',
        'tokenizer_id': 'NeoQuasar/Kronos-Tokenizer-2k',
        'context_length': 2048,
        'params': '4.1M',
        'description': '轻量级模型，适合快速预测'
    },
    'kronos-small': {
        'name': 'Kronos-small',
        'model_id': 'NeoQuasar/Kronos-small',
        'tokenizer_id': 'NeoQuasar/Kronos-Tokenizer-base',
        'context_length': 512,
        'params': '24.7M',
        'description': '小型模型，平衡性能和速度'
    },
    'kronos-base': {
        'name': 'Kronos-base',
        'model_id': 'NeoQuasar/Kronos-base',
        'tokenizer_id': 'NeoQuasar/Kronos-Tokenizer-base',
        'context_length': 512,
        'params': '102.3M',
        'description': '基础模型，提供更好的预测质量'
    }
}

def load_data_files():
    """扫描data目录并返回可用的数据文件"""
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
                    'size': f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.1f} MB"
                })
    
    return data_files

def load_data_file(file_path):
    """加载数据文件"""
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.endswith('.feather'):
            df = pd.read_feather(file_path)
        else:
            return None, "不支持的文件格式"
        
        # 检查必要的列
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            return None, f"缺少必要的列: {required_cols}"
        
        # 处理时间戳列
        if 'timestamps' in df.columns:
            df['timestamps'] = pd.to_datetime(df['timestamps'])
        elif 'timestamp' in df.columns:
            df['timestamps'] = pd.to_datetime(df['timestamp'])
        elif 'date' in df.columns:
            # 如果列名是'date'，将其重命名为'timestamps'
            df['timestamps'] = pd.to_datetime(df['date'])
        else:
            # 如果没有时间戳列，创建一个
            df['timestamps'] = pd.date_range(start='2024-01-01', periods=len(df), freq='1H')
        
        # 确保数值列是数值类型
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 处理volume列（可选）
        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        
        # 处理amount列（可选，但不用于预测）
        if 'amount' in df.columns:
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        
        # 删除包含NaN的行
        df = df.dropna()
        
        return df, None
        
    except Exception as e:
        return None, f"加载文件失败: {str(e)}"

def convert_price_to_returns(df, price_cols=['open', 'high', 'low', 'close']):
    """将绝对价格转换为相对变化率，解决Kronos模型的连续性问题"""
    print(f"[DEBUG] convert_price_to_returns: 开始转换，输入数据形状: {df.shape}")
    print(f"[DEBUG] convert_price_to_returns: 输入数据前3行:")
    print(df[price_cols].head(3))
    
    returns_df = df.copy()
    
    # 计算相对变化率 (pct_change)
    for col in price_cols:
        if col in returns_df.columns:
            print(f"[DEBUG] convert_price_to_returns: 转换列 {col}")
            returns_df[col] = returns_df[col].pct_change()
    
    # 第一行会是NaN，用0填充
    returns_df = returns_df.fillna(0)
    
    print(f"[DEBUG] convert_price_to_returns: 转换完成，输出数据前3行:")
    print(returns_df[price_cols].head(3))
    
    return returns_df

def convert_returns_to_price(returns_df, initial_prices, price_cols=['open', 'high', 'low', 'close']):
    """将相对变化率转换回绝对价格"""
    print(f"[DEBUG] convert_returns_to_price: 开始转换，输入数据形状: {returns_df.shape}")
    print(f"[DEBUG] convert_returns_to_price: 初始价格: {initial_prices}")
    print(f"[DEBUG] convert_returns_to_price: 输入相对变化率前3行:")
    print(returns_df[price_cols].head(3))
    
    price_df = returns_df.copy()
    
    for col in price_cols:
        if col in price_df.columns:
            print(f"[DEBUG] convert_returns_to_price: 转换列 {col}")
            # 正确的转换逻辑：从初始价格开始，逐步累积计算绝对价格
            # 第一个点：price = initial_price * (1 + return_1)
            # 第二个点：price = price_1 * (1 + return_2)
            # 第三个点：price = price_2 * (1 + return_3)
            # 以此类推...
            
            # 使用cumprod来累积计算
            price_df[col] = initial_prices[col] * (1 + returns_df[col]).cumprod()
            
            print(f"[DEBUG] convert_returns_to_price: 列 {col} 转换完成，前3个值:")
            print(f"  初始价格: {initial_prices[col]}")
            print(f"  相对变化率: {returns_df[col].head(3).tolist()}")
            print(f"  累积因子: {(1 + returns_df[col]).cumprod().head(3).tolist()}")
            print(f"  最终价格: {price_df[col].head(3).tolist()}")
    
    print(f"[DEBUG] convert_returns_to_price: 转换完成，输出绝对价格前3行:")
    print(price_df[price_cols].head(3))
    
    return price_df

def save_prediction_results(file_path, prediction_type, prediction_results, actual_data, input_data, prediction_params):
    """保存预测结果到文件"""
    try:
        # 创建预测结果目录
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prediction_results')
        os.makedirs(results_dir, exist_ok=True)
        
        # 生成文件名
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'prediction_{timestamp}.json'
        filepath = os.path.join(results_dir, filename)
        
        # 准备保存的数据
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
        
        # 如果有实际数据，进行对比分析
        if actual_data and len(actual_data) > 0:
            # 计算连续性分析
            if len(prediction_results) > 0 and len(actual_data) > 0:
                last_pred = prediction_results[0]  # 第一个预测点
                first_actual = actual_data[0]      # 第一个实际点
                
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
        
        # 保存到文件
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        
        print(f"预测结果已保存到: {filepath}")
        return filepath
        
    except Exception as e:
        print(f"保存预测结果失败: {e}")
        return None

def create_prediction_chart(df, pred_df, lookback, pred_len, actual_df=None, historical_start_idx=0):
    """创建预测图表"""
    # 使用指定的历史数据起始位置，而不是总是从df的开头开始
    if historical_start_idx + lookback + pred_len <= len(df):
        # 显示指定位置开始的lookback个历史点 + pred_len个预测点
        historical_df = df.iloc[historical_start_idx:historical_start_idx+lookback]
        prediction_range = range(historical_start_idx+lookback, historical_start_idx+lookback+pred_len)
    else:
        # 如果数据不够，调整到可用的最大范围
        available_lookback = min(lookback, len(df) - historical_start_idx)
        available_pred_len = min(pred_len, max(0, len(df) - historical_start_idx - available_lookback))
        historical_df = df.iloc[historical_start_idx:historical_start_idx+available_lookback]
        prediction_range = range(historical_start_idx+available_lookback, historical_start_idx+available_lookback+available_pred_len)
    
    # 创建图表
    fig = go.Figure()
    
    # 添加历史数据（K线图）
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
    
    # 添加预测数据（K线图）
    if pred_df is not None and len(pred_df) > 0:
        # 计算预测数据的时间戳 - 确保与历史数据连续
        if 'timestamps' in df.columns and len(historical_df) > 0:
            # 从历史数据的最后一个时间点开始，按相同的时间间隔创建预测时间戳
            last_timestamp = historical_df['timestamps'].iloc[-1]
            time_diff = df['timestamps'].iloc[1] - df['timestamps'].iloc[0] if len(df) > 1 else pd.Timedelta(hours=1)
            
            pred_timestamps = pd.date_range(
                start=last_timestamp + time_diff,
                periods=len(pred_df),
                freq=time_diff
            )
        else:
            # 如果没有时间戳，使用索引
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
    
    # 添加实际数据用于对比（如果存在）
    if actual_df is not None and len(actual_df) > 0:
        # 实际数据应该与预测数据在同一个时间段
        if 'timestamps' in df.columns:
            # 实际数据应该使用与预测数据相同的时间戳，确保时间对齐
            if 'pred_timestamps' in locals():
                actual_timestamps = pred_timestamps
            else:
                # 如果没有预测时间戳，从历史数据最后一个时间点开始计算
                if len(historical_df) > 0:
                    last_timestamp = historical_df['timestamps'].iloc[-1]
                    time_diff = df['timestamps'].iloc[1] - df['timestamps'].iloc[0] if len(df) > 1 else pd.Timedelta(hours=1)
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
    
    # 更新布局
    fig.update_layout(
        title='Kronos 金融预测结果 - 400个历史点 + 120个预测点 vs 120个实际点',
        xaxis_title='时间',
        yaxis_title='价格',
        template='plotly_white',
        height=600,
        showlegend=True
    )
    
    # 确保x轴时间连续
    if 'timestamps' in historical_df.columns:
        # 获取所有时间戳并排序
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
    """主页"""
    return render_template('index.html')

@app.route('/api/data-files')
def get_data_files():
    """获取可用的数据文件列表"""
    data_files = load_data_files()
    return jsonify(data_files)

@app.route('/api/load-data', methods=['POST'])
def load_data():
    """加载数据文件"""
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        
        if not file_path:
            return jsonify({'error': '文件路径不能为空'}), 400
        
        df, error = load_data_file(file_path)
        if error:
            return jsonify({'error': error}), 400
        
        # 检测数据的时间频率
        def detect_timeframe(df):
            if len(df) < 2:
                return "未知"
            
            time_diffs = []
            for i in range(1, min(10, len(df))):  # 检查前10个时间差
                diff = df['timestamps'].iloc[i] - df['timestamps'].iloc[i-1]
                time_diffs.append(diff)
            
            if not time_diffs:
                return "未知"
            
            # 计算平均时间差
            avg_diff = sum(time_diffs, pd.Timedelta(0)) / len(time_diffs)
            
            # 转换为可读格式
            if avg_diff < pd.Timedelta(minutes=1):
                return f"{avg_diff.total_seconds():.0f}秒"
            elif avg_diff < pd.Timedelta(hours=1):
                return f"{avg_diff.total_seconds() / 60:.0f}分钟"
            elif avg_diff < pd.Timedelta(days=1):
                return f"{avg_diff.total_seconds() / 3600:.0f}小时"
            else:
                return f"{avg_diff.days}天"
        
        # 返回数据信息
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
            'message': f'成功加载数据，共 {len(df)} 行'
        })
        
    except Exception as e:
        return jsonify({'error': f'加载数据失败: {str(e)}'}), 500

@app.route('/api/predict', methods=['POST'])
def predict():
    """进行预测"""
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        lookback = int(data.get('lookback', 400))
        pred_len = int(data.get('pred_len', 120))
        
        # 获取预测质量参数
        temperature = float(data.get('temperature', 1.0))
        top_p = float(data.get('top_p', 0.9))
        sample_count = int(data.get('sample_count', 1))
        
        if not file_path:
            return jsonify({'error': '文件路径不能为空'}), 400
        
        # 加载数据
        df, error = load_data_file(file_path)
        if error:
            return jsonify({'error': error}), 400
        
        if len(df) < lookback:
            return jsonify({'error': f'数据长度不足，需要至少 {lookback} 行数据'}), 400
        
        # 进行预测
        if MODEL_AVAILABLE and predictor is not None:
            try:
                # 使用真实的Kronos模型
                # 只使用必要的列：OHLCV，不包含amount
                required_cols = ['open', 'high', 'low', 'close']
                if 'volume' in df.columns:
                    required_cols.append('volume')
                
                # 处理时间段选择
                start_date = data.get('start_date')
                
                if start_date:
                    # 自定义时间段 - 修复逻辑：使用选择的窗口内的数据
                    start_dt = pd.to_datetime(start_date)
                    
                    # 找到开始时间之后的数据
                    mask = df['timestamps'] >= start_dt
                    time_range_df = df[mask]
                    
                    # 确保有足够的数据：lookback + pred_len
                    if len(time_range_df) < lookback + pred_len:
                        return jsonify({'error': f'从开始时间 {start_dt.strftime("%Y-%m-%d %H:%M")} 开始的数据不足，需要至少 {lookback + pred_len} 个数据点，当前只有 {len(time_range_df)} 个'}), 400
                    
                    # 使用选择的窗口内的前lookback个数据点进行预测
                    x_df = time_range_df.iloc[:lookback][required_cols]
                    x_timestamp = time_range_df.iloc[:lookback]['timestamps']
                    
                    # 使用选择的窗口内的后pred_len个数据点作为实际值
                    y_timestamp = time_range_df.iloc[lookback:lookback+pred_len]['timestamps']
                    
                    # 计算实际的时间段长度
                    start_timestamp = time_range_df['timestamps'].iloc[0]
                    end_timestamp = time_range_df['timestamps'].iloc[lookback+pred_len-1]
                    time_span = end_timestamp - start_timestamp
                    
                    prediction_type = f"Kronos模型预测 (选择的窗口内：前{lookback}个数据点预测，后{pred_len}个数据点对比，时间跨度: {time_span})"
                else:
                    # 使用最新数据
                    x_df = df.iloc[:lookback][required_cols]
                    x_timestamp = df.iloc[:lookback]['timestamps']
                    y_timestamp = df.iloc[lookback:lookback+pred_len]['timestamps']
                    prediction_type = "Kronos模型预测 (最新数据)"
                
                print(f"[DEBUG] 步骤1: 检查并转换时间戳格式...")
                # 确保时间戳是Series格式，不是DatetimeIndex，避免Kronos模型的.dt属性错误
                if isinstance(x_timestamp, pd.DatetimeIndex):
                    print(f"[DEBUG] 将x_timestamp从DatetimeIndex转换为Series")
                    x_timestamp = pd.Series(x_timestamp, name='timestamps')
                if isinstance(y_timestamp, pd.DatetimeIndex):
                    print(f"[DEBUG] 将y_timestamp从DatetimeIndex转换为Series")
                    y_timestamp = pd.Series(y_timestamp, name='timestamps')
                
                print(f"[DEBUG] 步骤2: 准备价格转换，保存初始价格...")
                # 解决Kronos模型连续性问题：将绝对价格转换为相对变化率
                original_x_df = x_df.copy()
                initial_prices = {
                    'open': x_df['open'].iloc[0],
                    'high': x_df['high'].iloc[0],
                    'low': x_df['low'].iloc[0],
                    'close': x_df['close'].iloc[0]
                }
                print(f"[DEBUG] 初始价格: {initial_prices}")
                
                print(f"[DEBUG] 步骤3: 将绝对价格转换为相对变化率...")
                # 转换为相对变化率
                x_df_returns = convert_price_to_returns(x_df, ['open', 'high', 'low', 'close'])
                print(f"[DEBUG] 转换完成，输入数据前5行相对变化率:")
                print(x_df_returns[['open', 'high', 'low', 'close']].head())
                
                print(f"[DEBUG] 步骤4: 使用转换后的数据进行Kronos模型预测...")
                # 使用转换后的数据进行预测
                pred_df_returns = predictor.predict(
                    df=x_df_returns,
                    x_timestamp=x_timestamp,
                    y_timestamp=y_timestamp,
                    pred_len=pred_len,
                    T=temperature,
                    top_p=top_p,
                    sample_count=sample_count
                )
                print(f"[DEBUG] 预测完成，预测结果前5行相对变化率:")
                print(pred_df_returns[['open', 'high', 'low', 'close']].head())
                
                print(f"[DEBUG] 步骤5: 将预测结果转换回绝对价格...")
                # 将预测结果转换回绝对价格
                pred_df = convert_returns_to_price(pred_df_returns, initial_prices, ['open', 'high', 'low', 'close'])
                print(f"[DEBUG] 转换完成，预测结果前5行绝对价格:")
                print(pred_df[['open', 'high', 'low', 'close']].head())
                
                print(f"[DEBUG] 步骤6: 处理volume和amount列...")
                # 保持volume列不变（如果存在）
                if 'volume' in pred_df.columns:
                    pred_df['volume'] = pred_df_returns['volume']
                    print(f"[DEBUG] 已复制volume列")
                if 'amount' in pred_df.columns:
                    pred_df['amount'] = pred_df_returns['amount']
                    print(f"[DEBUG] 已复制amount列")
                
                print(f"[DEBUG] 步骤7: 检查最终预测结果...")
                print(f"[DEBUG] 最终预测结果形状: {pred_df.shape}")
                print(f"[DEBUG] 最终预测结果列: {list(pred_df.columns)}")
                
            except Exception as e:
                return jsonify({'error': f'Kronos模型预测失败: {str(e)}'}), 500
        else:
            return jsonify({'error': 'Kronos模型未加载，请先加载模型'}), 400
        
        # 准备实际数据用于对比（如果存在）
        actual_data = []
        actual_df = None
        
        if start_date:  # 自定义时间段
            # 修复逻辑：使用选择的窗口内的数据
            # 预测使用的是选择的窗口内的前400个数据点
            # 实际数据应该是选择的窗口内的后120个数据点
            start_dt = pd.to_datetime(start_date)
            
            # 找到从start_date开始的数据
            mask = df['timestamps'] >= start_dt
            time_range_df = df[mask]
            
            if len(time_range_df) >= lookback + pred_len:
                # 获取选择的窗口内的后120个数据点作为实际值
                actual_df = time_range_df.iloc[lookback:lookback+pred_len]
                
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
        else:  # 最新数据
            # 预测使用的是前400个数据点
            # 实际数据应该是400个数据点之后的120个数据点
            if len(df) >= lookback + pred_len:
                actual_df = df.iloc[lookback:lookback+pred_len]
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
        
        # 创建图表 - 传递历史数据的起始位置
        if start_date:
            # 自定义时间段：找到历史数据在原始df中的起始位置
            start_dt = pd.to_datetime(start_date)
            mask = df['timestamps'] >= start_dt
            historical_start_idx = df[mask].index[0] if len(df[mask]) > 0 else 0
        else:
            # 最新数据：从开头开始
            historical_start_idx = 0
        
        chart_json = create_prediction_chart(df, pred_df, lookback, pred_len, actual_df, historical_start_idx)
        
        # 准备预测结果数据 - 修复时间戳计算逻辑
        if 'timestamps' in df.columns:
            if start_date:
                # 自定义时间段：使用选择的窗口数据计算时间戳
                start_dt = pd.to_datetime(start_date)
                mask = df['timestamps'] >= start_dt
                time_range_df = df[mask]
                
                if len(time_range_df) >= lookback:
                    # 从选择的窗口的最后一个时间点开始计算预测时间戳
                    last_timestamp = time_range_df['timestamps'].iloc[lookback-1]
                    time_diff = df['timestamps'].iloc[1] - df['timestamps'].iloc[0]
                    future_timestamps = pd.date_range(
                        start=last_timestamp + time_diff,
                        periods=pred_len,
                        freq=time_diff
                    )
                else:
                    future_timestamps = []
            else:
                # 最新数据：从整个数据文件的最后时间点开始计算
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
        
        # 保存预测结果到文件
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
            print(f"保存预测结果失败: {e}")
        
        return jsonify({
            'success': True,
            'prediction_type': prediction_type,
            'chart': chart_json,
            'prediction_results': prediction_results,
            'actual_data': actual_data,
            'has_comparison': len(actual_data) > 0,
            'message': f'预测完成，生成了 {pred_len} 个预测点' + (f'，包含 {len(actual_data)} 个实际数据点用于对比' if len(actual_data) > 0 else '')
        })
        
    except Exception as e:
        return jsonify({'error': f'预测失败: {str(e)}'}), 500

@app.route('/api/load-model', methods=['POST'])
def load_model():
    """加载Kronos模型"""
    global tokenizer, model, predictor
    
    try:
        if not MODEL_AVAILABLE:
            return jsonify({'error': 'Kronos模型库不可用'}), 400
        
        data = request.get_json()
        model_key = data.get('model_key', 'kronos-small')
        device = data.get('device', 'cpu')
        
        if model_key not in AVAILABLE_MODELS:
            return jsonify({'error': f'不支持的模型: {model_key}'}), 400
        
        model_config = AVAILABLE_MODELS[model_key]
        
        # 加载tokenizer和模型
        tokenizer = KronosTokenizer.from_pretrained(model_config['tokenizer_id'])
        model = Kronos.from_pretrained(model_config['model_id'])
        
        # 创建predictor
        predictor = KronosPredictor(model, tokenizer, device=device, max_context=model_config['context_length'])
        
        return jsonify({
            'success': True,
            'message': f'模型加载成功: {model_config["name"]} ({model_config["params"]}) on {device}',
            'model_info': {
                'name': model_config['name'],
                'params': model_config['params'],
                'context_length': model_config['context_length'],
                'description': model_config['description']
            }
        })
        
    except Exception as e:
        return jsonify({'error': f'模型加载失败: {str(e)}'}), 500

@app.route('/api/available-models')
def get_available_models():
    """获取可用的模型列表"""
    return jsonify({
        'models': AVAILABLE_MODELS,
        'model_available': MODEL_AVAILABLE
    })

@app.route('/api/model-status')
def get_model_status():
    """获取模型状态"""
    if MODEL_AVAILABLE:
        if predictor is not None:
            return jsonify({
                'available': True,
                'loaded': True,
                'message': 'Kronos模型已加载并可用',
                'current_model': {
                    'name': predictor.model.__class__.__name__,
                    'device': str(next(predictor.model.parameters()).device)
                }
            })
        else:
            return jsonify({
                'available': True,
                'loaded': False,
                'message': 'Kronos模型可用但未加载'
            })
    else:
        return jsonify({
            'available': False,
            'loaded': False,
            'message': 'Kronos模型库不可用，请安装相关依赖'
        })

if __name__ == '__main__':
    print("启动Kronos Web UI...")
    print(f"模型可用性: {MODEL_AVAILABLE}")
    if MODEL_AVAILABLE:
        print("提示: 可以通过 /api/load-model 接口加载Kronos模型")
    else:
        print("提示: 将使用模拟数据进行演示")
    
    app.run(debug=True, host='0.0.0.0', port=7070)
