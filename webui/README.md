# Kronos Web UI

Web user interface for Kronos financial prediction model, providing intuitive graphical operation interface.

## ✨ Features

- **Stock analysis home page**: Unified dashboard for opportunity discovery, batch analysis, module health and reports
- **Pattern search canvas (形态搜股)**: Top-bar button opens a full-screen modal — draw any close-price shape or pick a stock code to find the top-30 A-share stocks whose 30-day normalized close curves match best. Backed by a SQLite fingerprint cache (`data/pattern_fingerprints.db`).
- **Investment opportunity discovery**: Launches the existing multi-source opportunity mining flow from the browser
- **Batch stock analysis**: Runs the existing batch collector/scorer against a custom stock pool
- **Clickable stock K-line view**: Click any opportunity stock to load its K-line chart from local data or Eastmoney
- **Quant model panel**: Shows current opportunity-discovery model triggers and model heat distribution
- **Report center**: Opens generated opportunity, batch, single-stock and major-positive-news reports
- **Real market overview**: Displays provider-backed index quotes when available; unavailable quotes are shown explicitly
- **Multi-format data support**: Supports CSV, Feather and other financial data formats
- **Smart time window**: Fixed 400+120 data point time window slider selection
- **Real model prediction**: Integrated real Kronos model, supports multiple model sizes
- **Prediction quality control**: Adjustable temperature, nucleus sampling, sample count and other parameters
- **Multi-device support**: Supports CPU, CUDA, MPS and other computing devices
- **Comparison analysis**: Detailed comparison between prediction results and actual data
- **K-line chart display**: Professional financial K-line chart display

## 🚀 Quick Start

### Method 1: Start with Python script

```bash
cd webui
python run.py
```

### Method 2: Start with Shell script

```bash
cd webui
chmod +x start.sh
./start.sh
```

### Method 3: Start Flask application directly

```bash
cd webui
python app.py
```

After successful startup, visit http://localhost:7070

## 📍 Web Routes

- `http://localhost:7070/`: comprehensive stock analysis home page
- `http://localhost:7070/desktop/features`: Tauri desktop full feature overview
- `http://localhost:7070/prediction`: original Kronos K-line prediction console
- `http://localhost:7070/particles`: real-time market particle visualization

## 🖥️ Desktop Shell

The desktop package now uses Tauri as the native shell and reuses the Flask Web UI as a local backend.

```bash
npm install
npm run desktop:dev
npm run desktop:build
```

The Tauri entry opens `/desktop/features`, which keeps the stock-analysis workflow on one complete page.
The sidebar pages remain as focused shortcuts for overview, opportunities, workbench, pattern search, settings, and reports.

## 📋 Usage Steps

### Stock Analysis Home

1. Open `/` to review the latest opportunity report, market snapshot, module health and generated artifacts.
2. Click a stock in **投资机会** to switch the K-line chart and per-stock quant model panel.
3. Use **机会挖掘** to start the existing `scripts/run_opportunity_discovery.py` flow in a background job.
4. Use **批量分析** to start the existing `analysis.batch_processor` flow for a custom stock pool.
5. Track background progress in **任务队列** and open output files from **报告库** or **批量结果**.
6. 使用顶部 **形态搜股** 按钮打开 Modal，「手绘形态」画一条曲线或「选股票形态」输入代码 → 点击检索 → 右侧列出近 30 日形态最相似的 Top-30 股票；点击列表项可在下方查看曲线对比图。首次使用需点击 Modal 顶部「刷新指纹库」（约 10-15 分钟），之后每日 16:30 后台自动刷新。

### K-line Prediction Console

1. **Load data**: Select financial data file from data directory
2. **Load model**: Select Kronos model and computing device
3. **Set parameters**: Adjust prediction quality parameters
4. **Select time window**: Use slider to select 400+120 data point time range
5. **Start prediction**: Click prediction button to generate results
6. **View results**: View prediction results in charts and tables

## 🔧 Prediction Quality Parameters

### Temperature (T)

- **Range**: 0.1 - 2.0
- **Effect**: Controls prediction randomness
- **Recommendation**: 1.2-1.5 for better prediction quality

### Nucleus Sampling (top_p)

- **Range**: 0.1 - 1.0
- **Effect**: Controls prediction diversity
- **Recommendation**: 0.95-1.0 to consider more possibilities

### Sample Count

- **Range**: 1 - 10
- **Effect**: Generate multiple prediction samples
- **Recommendation**: 2-3 samples to improve quality

## 📊 Supported Data Formats

### Required Columns

- `open`: Opening price
- `high`: Highest price
- `low`: Lowest price
- `close`: Closing price

### Optional Columns

- `volume`: Trading volume
- `amount`: Trading amount (not used for prediction)
- `timestamps`/`timestamp`/`date`: Timestamp

## 🤖 Model Support

- **Kronos-mini**: 4.1M parameters, lightweight fast prediction
- **Kronos-small**: 24.7M parameters, balanced performance and speed
- **Kronos-base**: 102.3M parameters, high quality prediction

## 🖥️ GPU Acceleration Support

- **CPU**: General computing, best compatibility
- **CUDA**: NVIDIA GPU acceleration, best performance
- **MPS**: Apple Silicon GPU acceleration, recommended for Mac users

## ⚠️ Notes

- `amount` column is not used for prediction, only for display
- Time window is fixed at 400+120=520 data points
- Ensure data file contains sufficient historical data
- First model loading may require download, please be patient

## 🔍 Comparison Analysis

The system automatically provides comparison analysis between prediction results and actual data, including:

- Price difference statistics
- Error analysis
- Prediction quality assessment

## 🛠️ Technical Architecture

- **Backend**: Flask + Python
- **Frontend**: HTML + CSS + JavaScript
- **Charts**: Plotly.js
- **Data processing**: Pandas + NumPy
- **Model**: Hugging Face Transformers

## 📝 Troubleshooting

### Common Issues

1. **Port occupied**: Modify port number in app.py
2. **Missing dependencies**: Run `pip install -r requirements.txt`
3. **Model loading failed**: Check network connection and model ID
4. **Data format error**: Ensure data column names and format are correct

### Log Viewing

Detailed runtime information will be displayed in the console at startup, including model status and error messages.

## 📄 License

This project follows the license terms of the original Kronos project.

## 🤝 Contributing

Welcome to submit Issues and Pull Requests to improve this Web UI!

## 📞 Support

If you have questions, please check:

1. Project documentation
2. GitHub Issues
3. Console error messages
