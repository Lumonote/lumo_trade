import pandas as pd
import matplotlib.pyplot as plt
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from model import Kronos, KronosTokenizer, KronosPredictor


def plot_prediction(kline_df, pred_df):
    pred_df.index = kline_df.index[-pred_df.shape[0]:]
    sr_close = kline_df['close']
    sr_pred_close = pred_df['close']
    sr_close.name = '真实数据'
    sr_pred_close.name = "预测数据"

    close_df = pd.concat([sr_close, sr_pred_close], axis=1)

    fig, ax = plt.subplots(1, 1, figsize=(12, 6))

    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    ax.plot(close_df['真实数据'], label='真实数据', color='blue', linewidth=1.5)
    ax.plot(close_df['预测数据'], label='预测数据', color='red', linewidth=1.5)
    ax.set_ylabel('收盘价格', fontsize=14)
    ax.set_xlabel('时间', fontsize=14)
    ax.set_title('Kronos股价预测结果（无成交量）', fontsize=16, fontweight='bold')
    ax.legend(loc='lower left', fontsize=12)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


# 1. Load Model and Tokenizer using ModelScope
from modelscope import snapshot_download
from pathlib import Path
import shutil

model_dir = Path(os.path.join(os.path.dirname(__file__), '..', 'models'))
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
        downloaded_path = snapshot_download('northwind9898/Kronos-small', cache_dir=str(model_dir))
        # 如果下载路径有嵌套结构，将其移动到一级目录
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

# 3. Prepare Data
df = pd.read_csv("./data/XSHG_5min_600977.csv")
df['timestamps'] = pd.to_datetime(df['timestamps'])

lookback = 400
pred_len = 120

x_df = df.loc[:lookback - 1, ['open', 'high', 'low', 'close']]
x_timestamp = df.loc[:lookback - 1, 'timestamps']
y_timestamp = df.loc[lookback:lookback + pred_len - 1, 'timestamps']

# 4. Make Prediction
pred_df = predictor.predict(
    df=x_df,
    x_timestamp=x_timestamp,
    y_timestamp=y_timestamp,
    pred_len=pred_len,
    T=0.6,
    top_p=0.9,
    sample_count=10,
    verbose=True
)

# 5. Visualize Results
print("Forecasted Data Head:")
print(pred_df.head())

# Combine historical and forecasted data for plotting
kline_df = df.loc[:lookback + pred_len - 1]

# visualize
plot_prediction(kline_df, pred_df)
