import pandas as pd
import matplotlib.pyplot as plt
import sys
import os
from modelscope import snapshot_download

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from model import Kronos, KronosTokenizer, KronosPredictor


def plot_prediction(kline_df, pred_df):
    pred_df.index = kline_df.index[-pred_df.shape[0]:]
    sr_close = kline_df['close']
    sr_pred_close = pred_df['close']
    sr_close.name = '真实数据'
    sr_pred_close.name = "预测数据"

    sr_volume = kline_df['volume']
    sr_pred_volume = pred_df['volume']
    sr_volume.name = '真实数据'
    sr_pred_volume.name = "预测数据"

    close_df = pd.concat([sr_close, sr_pred_close], axis=1)
    volume_df = pd.concat([sr_volume, sr_pred_volume], axis=1)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    ax1.plot(close_df['真实数据'], label='真实数据', color='blue', linewidth=1.5)
    ax1.plot(close_df['预测数据'], label='预测数据', color='red', linewidth=1.5)
    ax1.set_ylabel('收盘价格', fontsize=14)
    ax1.set_title('Kronos股价预测结果', fontsize=16, fontweight='bold')
    ax1.legend(loc='lower left', fontsize=12)
    ax1.grid(True, alpha=0.3)

    ax2.plot(volume_df['真实数据'], label='真实数据', color='blue', linewidth=1.5)
    ax2.plot(volume_df['预测数据'], label='预测数据', color='red', linewidth=1.5)
    ax2.set_ylabel('成交量', fontsize=14)
    ax2.set_xlabel('时间', fontsize=14)
    ax2.legend(loc='upper left', fontsize=12)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    # 创建results目录（如果不存在）
    results_dir = os.path.join(os.path.dirname(__file__), '..', 'results')
    os.makedirs(results_dir, exist_ok=True)

    # 生成带时间戳的文件名
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'prediction_chart_{timestamp}.png'
    filepath = os.path.join(results_dir, filename)

    try:
        # 保存图片
        plt.savefig(filepath, dpi=300, bbox_inches='tight', facecolor='white')
        print(f"图表已保存到: {filepath}")
    except Exception as e:
        print(f"保存图片时出错: {e}")

    plt.show()


# 1. Load Model and Tokenizer using ModelScope
model_dir = os.path.join(os.path.dirname(__file__), '..', 'models')
from pathlib import Path

model_dir = Path(model_dir)
model_dir.mkdir(exist_ok=True)

# 一级目录结构，直接在models下
tokenizer_dir = model_dir / "Kronos-Tokenizer-base"
model_dir_path = model_dir / "Kronos-base"

try:
    # 优先使用本地模型（一级目录结构）
    if tokenizer_dir.exists() and (tokenizer_dir / "config.json").exists():
        print("Found local tokenizer, loading...")
        tokenizer = KronosTokenizer.from_pretrained(str(tokenizer_dir))
    else:
        # 下载并保存到一级目录
        print("Downloading tokenizer...")
        downloaded_path = snapshot_download('northwind9898/Kronos-Tokenizer-base', cache_dir=str(model_dir))
        # 如果下载路径有嵌套结构，将其移动到一级目录
        import shutil

        if "northwind9898" in downloaded_path:
            if not tokenizer_dir.exists():
                shutil.move(downloaded_path, str(tokenizer_dir))
            downloaded_path = str(tokenizer_dir)
        tokenizer = KronosTokenizer.from_pretrained(downloaded_path)

    if model_dir_path.exists() and (model_dir_path / "config.json").exists():
        print("Found local model, loading...")
        model = Kronos.from_pretrained(str(model_dir_path))
    else:
        # 下载并保存到一级目录
        print("Downloading model...")
        downloaded_path = snapshot_download('northwind9898/Kronos-base', cache_dir=str(model_dir))
        # 如果下载路径有嵌套结构，将其移动到一级目录
        import shutil

        if "northwind9898" in downloaded_path:
            if not model_dir_path.exists():
                shutil.move(downloaded_path, str(model_dir_path))
            downloaded_path = str(model_dir_path)
        model = Kronos.from_pretrained(downloaded_path)

except Exception as e:
    print(f"Error loading models: {e}")
    print("This may be due to network issues or model availability.")
    print("Please check your internet connection and try again.")
    sys.exit(1)

# 2. Instantiate Predictor
predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)

# 3. Prepare Data (Create sample data for testing)
import numpy as np
from datetime import datetime, timedelta

# Create sample financial data
np.random.seed(42)
n_points = 600
base_price = 100.0
prices = [base_price]

for i in range(n_points - 1):
    change = np.random.normal(0, 0.02) * prices[-1]
    new_price = max(prices[-1] + change, 1.0)  # Ensure price stays positive
    prices.append(new_price)


# Generate OHLC data with A-share trading hours
def generate_a_share_timestamps(start_date, num_points):
    """生成符合A股交易时间的时间戳"""
    timestamps = []
    current_date = start_date
    points_generated = 0

    while points_generated < num_points:
        # 跳过周末
        if current_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            current_date += timedelta(days=1)
            continue

        # 上午交易时间 9:30-11:30 (24个5分钟间隔)
        morning_start = current_date.replace(hour=9, minute=30, second=0, microsecond=0)
        for i in range(24):  # 9:30-11:30
            if points_generated >= num_points:
                break
            timestamps.append(morning_start + timedelta(minutes=5 * i))
            points_generated += 1

        # 下午交易时间 13:00-15:00 (24个5分钟间隔)
        afternoon_start = current_date.replace(hour=13, minute=0, second=0, microsecond=0)
        for i in range(24):  # 13:00-15:00
            if points_generated >= num_points:
                break
            timestamps.append(afternoon_start + timedelta(minutes=5 * i))
            points_generated += 1

        current_date += timedelta(days=1)

    return timestamps[:num_points]


data = []
start_date = datetime(2024, 1, 2)  # 从工作日开始
timestamps = generate_a_share_timestamps(start_date, n_points)

for i, close in enumerate(prices):
    timestamp = timestamps[i]

    # Generate realistic OHLC based on close price
    volatility = np.random.uniform(0.005, 0.02)
    high = close * (1 + volatility * np.random.uniform(0.5, 1.0))
    low = close * (1 - volatility * np.random.uniform(0.5, 1.0))
    open_price = low + (high - low) * np.random.uniform(0.2, 0.8)

    volume = np.random.randint(1000, 10000)
    amount = volume * close

    data.append({
        'timestamps': timestamp,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
        'amount': amount
    })

df = pd.DataFrame(data)
print(f"Created sample data with {len(df)} rows")
print("Sample data head:")
print(df.head())

lookback = 400
pred_len = 120

x_df = df.loc[:lookback - 1, ['open', 'high', 'low', 'close', 'volume', 'amount']]
x_timestamp = df.loc[:lookback - 1, 'timestamps']
y_timestamp = df.loc[lookback:lookback + pred_len - 1, 'timestamps']

# 4. Make Prediction
pred_df = predictor.predict(
    df=x_df,
    x_timestamp=x_timestamp,
    y_timestamp=y_timestamp,
    pred_len=pred_len,
    T=0.8,  # 平衡预测，适合一般市场环境
    top_p=0.9,
    sample_count=3,  # 建议1-5次，根据需求调整
    verbose=True
)

# 5. Visualize Results
print("Forecasted Data Head:")
print(pred_df.head())

# Combine historical and forecasted data for plotting
kline_df = df.loc[:lookback + pred_len - 1]

# visualize
plot_prediction(kline_df, pred_df)
