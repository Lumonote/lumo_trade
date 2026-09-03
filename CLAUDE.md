# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kronos is a foundation model for financial market forecasting, specifically designed for K-line (candlestick) data,
plus a complete A-share **investment opportunity mining system** built on top of it. The repository is a three-layer
system:

1. **Data & Model Foundation**: A PyTorch-based Kronos model (tokenizer + Transformer predictor) and a multi-source
   data pipeline (Tushare / Eastmoney / Tonghuashun / Xueqiu) with SQLite data warehouse (`kronos_data.sqlite`,
   30+ topic tables).
2. **Analysis Engine**: The investment opportunity mining pipeline — candidate pool construction → market regime
   recognition → 9-dimension multi-factor scoring → v25 data-driven scoring rules → one-vote veto → soft filter funnel
   → LLM deep analysis → report generation → auto-backtest. Includes 30 quantitative trading models, 20+ technical
   indicators, and 3-dimensional sentiment analysis.
3. **Applications**: Tauri 2 desktop client **Lumo Trade** (15 pages / 21 stock-analysis tabs), Flask/Robyn Web UI,
   and CLI tools.

**Core design philosophy**: AI (LLM) is only used to *explain factors in plain language*; all real decision logic lives
in **backtestable, traceable, auditable rules and factor systems**. Never let the LLM directly recommend stocks.

## Development Commands

### Installation and Setup

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Playwright for web scraping
pip install playwright
playwright install chromium

# Run quick setup (interactive)
./quick_start.sh              # Linux/macOS
quick_start.bat               # Windows
.\quick_start.ps1             # Windows PowerShell

# Check environment status
python scripts/check_environment.py

# Configure data sources
python scripts/config_wizard.py

# Validate data collection and saving
python scripts/validate_data_collection.py

# Fix data collection issues (resolves "0 data" problems)
python scripts/fix_data_collection.py

# Analyze zero data batches and get suggestions
python scripts/zero_data_analyzer.py

# Handle zero data with smart collection strategies
python scripts/handle_zero_data.py --symbol 300555 --mode smart

# Intelligent data collection with fallback strategies
python scripts/smart_data_strategy.py
```

### Data Management

```bash
# Fetch stock data using Tushare
python scripts/fetch_data.py --symbol 000001.SZ --source tushare

# Fetch data using web crawler (with multi-crawler automatic switching)
python scripts/fetch_data.py --symbol 000001 --source eastmoney

# Automatic multi-source data fetching (recommended)
python scripts/fetch_data.py --symbol 000001 --source auto

# Batch fetch multiple stocks with automatic fallback
python scripts/batch_fetch_enhanced.py --symbols 600977,000001,000002 --source auto --period 5m --min-days 365

# Setup Tushare API token
python scripts/setup_tushare.py
```

### Opportunity Mining (Investment Opportunity Discovery)

```bash
# Run the full 6-stage opportunity mining pipeline (recommended, multi-source candidate pool)
python scripts/run_opportunity_discovery.py --source multi --limit 100

# Candidate source: heat ranking / money-flow ranking / hot sector members
python scripts/run_opportunity_discovery.py --source heat
python scripts/run_opportunity_discovery.py --source moneyflow_dc
python scripts/run_opportunity_discovery.py --source sector_hot

# Concurrency (default 10 workers, per-stock timeout 60s)
python scripts/run_opportunity_discovery.py --workers 10

# Rewrite scoring config from backtest results after run (off by default)
python scripts/run_opportunity_discovery.py --enable-auto-optimize

# Disable hot-stock cache globally (data is always fetched live)
export KRONOS_DISABLE_HOT_CACHE=1
```

### Model Training and Inference

```bash
# Run prediction example with technical analysis
python examples/prediction_example.py

# Run prediction without volume data
python examples/prediction_wo_vol_example.py

# Run batch prediction with integrated technical analysis (使用默认参数)
python examples/prediction_batch_example.py --stock-code 688343

# 自定义采样参数进行批量预测
python examples/prediction_batch_example.py \
  --stock-code 000001 \
  --temperature 1.0 \
  --top-p 0.95 \
  --sample-count 5

# 参数配置说明:
# - Temperature (温度): 0.8(默认) - 控制预测随机性
#   · 保守预测: 0.5-0.7 (趋势明确市场)
#   · 平衡预测: 0.8-1.0 (一般市场环境)
#   · 激进预测: >1.0 (高波动市场)
# - Top-p (核采样): 0.90(默认) - 平衡多样性和稳定性，推荐0.8-0.95
# - Sample Count (采样次数): 3(默认) - 建议1-5次，通过多次采样取平均提高稳定性
# 详细参数配置指南请参考: docs/批量分析参数配置说明.md

# Finetuning (requires multi-GPU setup)
torchrun --standalone --nproc_per_node=2 finetune/train_tokenizer.py
torchrun --standalone --nproc_per_node=2 finetune/train_predictor.py

# Backtesting evaluation
python finetune/qlib_test.py --device cuda:0
```

### Web Interface

```bash
# Start Flask/Robyn web UI
cd webui
python run.py
# OR ./start.sh
```

### Desktop (Lumo Trade)

Desktop frontend lives in `desktop/` (Tauri 2 shell pages) and `src-tauri/` (Tauri app). The backend is the same
`webui/` Flask/Robyn API plus SQLite data stores.

## Architecture Overview

### Core Components

**Model Architecture (`model/`)**

- `kronos.py`: Contains three main classes:
    - `KronosTokenizer`: Quantizes OHLCV data using Binary Spherical Quantization (BSQuantizer)
    - `Kronos`: Main Transformer-based predictor model
    - `KronosPredictor`: High-level interface for making predictions with built-in preprocessing

**Opportunity Mining Core (`analysis/`)**

- `opportunity_scorer.py`: 9-dimension multi-factor scoring engine ("游资思维重构版 v4.0"):
    - Momentum (反追涨), quant signal scarcity (信号稀缺性, not count), technical resonance,
      sentiment as **contrarian indicator**, liquidity gates, one-vote veto
    - 4 dynamic weight templates: `base` / `bottom_start` / `trend_continuation` / `news_driven`
    - v22 weights: 量化 0.30 / 量价 0.24 / 技术 0.12 / 位置 0.12 / 板块 0.08 / 龙虎榜 0.06 / 流动性 0.05 / 基本面 0.03
    - Rating: S ≥85, A+ 82-85, A 78-82, B 70-78, C <70
- `scoring_rules.py`: **v25 shared scoring rules** — single source of truth (`RULESET`) for both sim and live scoring.
    Data-driven rewards/penalties (e.g., RSI≥85 → -25, sell=0 → +4, quant≥95 → -18). Never add a rule without
    backtest evidence; be willing to disable rules that lose discrimination.
- `outcome_markers.py`: **m1 marker system** — post-selection performance review. 7 split-half-validated markers
  (🚀爆发基因 / ✅零卖压 positive; 🔥板块过热 / ⚠️追高透支 / 📈超买风险 / 🔻卖压聚集 / 📉技术乏力 negative) +
  constitution stratification (net markers: ≥+2 爆发体质, ≤-3 高危体质 27.5% crash rate).
- `market_env_analyzer.py`: market regime recognition → 6 weight schemes (过热谨慎 / 低迷机会 / 均衡稳健 /
  高波猎手 / 低波蓄势 / 资金入场激进).
- `opportunity_filter.py` / `comprehensive_score_filter.py`: 4-layer soft filter funnel
  (等级 → 综合评分 → 维度要求 → 风险软化). Since v8.0: **只打分不淘汰** (score everything, mark risks, never hard-drop).
- `technical_analysis.py`: 20+ technical indicators + 30 quantitative trading models
- `retry_utils.py`: exponential backoff with jitter + multi-source fallback + data quality validation
- `async_data_collector.py` / `async_opportunity_scorer.py` / `batch_processor.py`: asyncio + semaphore + timeout
  three-stage pipeline (采集→评分→排序)

**Sentiment & Fundamentals**

- `investor_sentiment.py`: `InvestorSentimentAnalyzer` — stock forum NLP sentiment, 4 major index market sentiment,
  sector sentiment, capital flow, 0-100 scoring
- `fundamental_data_collector.py`: PE/PB/PS, revenue/profit/cash flow with YoY growth, TTM
- `news_sentiment_collector.py`: announcements with importance classification, news sentiment, research reports

**Data Pipeline**

- Raw financial data (CSV with timestamps, OHLC, volume, amount columns)
- Tokenizer converts continuous values to discrete tokens
- Predictor generates forecasts in token space
- Results are decoded back to OHLCV predictions
- Opportunity mining adds: scoring → rules → markers → report → SQLite → auto-backtest

**Web Scraping System (`scripts/`)**

- Multi-source crawler supporting:
    - Eastmoney (`eastmoney_crawler.py`)
    - Tonghuashun (`tonghuashun_crawler.py`)
    - Xueqiu (`xueqiu_crawler.py`)
- **Multi-crawler automatic switching**: when one source returns 0 data, automatically try the next
  (Tushare → Eastmoney → Tonghuashun → Xueqiu)
- Anti-crawler mechanisms: rate limiting, user agent rotation, proxy alternation, Playwright browser management

### Configuration

**Model Configurations (`config/`)**

- `crawler_config.json`: Web scraper settings, anti-crawler parameters
- `tushare_config.json`: Tushare API configuration

**Available Models**

- Kronos-mini: 4.1M params, 2048 context length
- Kronos-small: 24.7M params, 512 context length
- Kronos-base: 102.3M params, 512 context length

### Data Format Requirements

Input data must be CSV with columns:

- `timestamps`: Pandas datetime format
- `open`, `high`, `low`, `close`: Price data (required)
- `volume`, `amount`: Optional, will be zero-filled if missing

Data files use standard naming `{EXCHANGE}_{PERIOD}_{CODE}.csv` (e.g., `XSHG_5min_600977.csv`).

### Opportunity Mining Pipeline (6 Stages)

```
Stage 0   Market regime assessment (沪深300 5/20日涨跌 → 强势/震荡/弱势) → "当前是否值得入场"
Stage 1   Candidate pool construction (5 orthogonal sources, multi-source fusion)
          · Hot TOP100 (Eastmoney popularity ranking)
          · Hot sector members (70% concept quota via KRONOS_HOT_SECTOR_CONCEPT_RATIO)
          · Oversold rebound (10-day drop ≥8% + reversal signal)
          · Money flow (top 20 net inflow / outflow)
          · Low-position volume breakout scan
          · Dedup + ST/delisting filter + deep-rank trimming (rank > max(300, limit*2))
Stage 1.5 Global data preload (market sentiment, sector data, dragon-tiger list) → cache reuse
Stage 2   Multi-dimension scoring (concurrent, per-stock 60s timeout)
Stage 3   Soft filter funnel (no elimination, only risk markers since v8.0)
Stage 3.5 LLM deep analysis (top-scored stocks ≥65; adaptive concurrency 2-5, adaptive count Top8-10)
Stage 3.8 Top10 selection-reason construction (signal-strength-priority string assembly)
Stage 4   Report generation (HTML + CSV + Excel; run_meta: run_at/source/ruleset_version/config_hash)
Stage 4.6 Results into SQLite opportunity_repo (per-run, per-day)
Stage 5   Auto-backtest (save_recommendations → update_returns(30d) → generate_backtest_report;
          optional KRONOS_ENABLE_AUTO_OPTIMIZE config rewriting)
Stage 6   Resource cleanup (scorer / HTTP Session with timeout protection)
```

### Version Evolution (design philosophy)

| Version | Codename | Core capability | Philosophy |
|---------|----------|-----------------|------------|
| v1 | Base | batch analysis + 30 quant models + 5-stage filter | multi-dimension parallelism |
| v2 | Ultra-Proactive | 6-dimension forward-looking signals, M&A association, keyword reverse mining | 超前性 (3-180 days ahead) |
| v3 | Quality-First | 3-mode integration (keyword/forum/news), 6-stage analysis, 5-dimension drill-down | "重要的不是快而是质量" |
| v4 | Real-Time Intelligence | unofficial-channel deep mining (social/supply-chain/recruiting/capital) | 信息公开前捕捉机会 |
| v5+ | Optimization | 5x concurrency, market-adaptive weights, soft filter, quick config tuner, report v5 | performance & flexibility |
| v24/v25 | Scoring rules | unified sim/live rules source, data-driven rewards, new factors (main capital/futures) | 数据驱动、宁缺毋滥 |
| m1 | Markers | post-selection review, boom/crash commonality, constitution stratification, batch crowding | 与总分正交的尾部风险 |

### Enhanced Prediction Pipeline

The prediction system now includes comprehensive multi-dimensional analysis:

1. **Historical Data Analysis**: Calculates 20+ technical indicators
2. **Quantitative Model Evaluation**: Runs 30 professional trading models
3. **Price Continuity Correction**: Automatically fixes prediction gaps >3%
4. **Risk Assessment**: Multi-dimensional risk evaluation
5. **Investment Recommendations**: Aggregated signals from all models
6. **Market Sentiment Analysis**: Overall market trends across major indices
7. **Sector Analysis**: Sector performance tracking and leader identification
8. **Investor Sentiment**: Stock forum discussion sentiment analysis

### Finetuning Pipeline

The finetuning system (`finetune/`) provides:

1. **Data Preparation**: `qlib_data_preprocess.py` processes Qlib market data
2. **Tokenizer Training**: `train_tokenizer.py` adapts tokenizer to specific domains
3. **Predictor Training**: `train_predictor.py` finetunes the main forecasting model
4. **Evaluation**: `qlib_test.py` runs backtesting with portfolio strategies

**Configuration**: Edit `finetune/config.py` to set:

- Data paths (Qlib data directory, output directories)
- Model paths (pretrained checkpoints)
- Training hyperparameters
- Backtesting parameters

### Web Interface Features

The Flask/Robyn web UI (`webui/`) provides:

- Model selection and loading
- Real-time stock data visualization
- Prediction generation and plotting
- Opportunity mining reports and history
- Results export functionality
- Supports multiple Kronos model variants

## Important Notes

- **Context Limits**: Kronos-small and Kronos-base have max_context=512. Input sequences longer than this will be
  automatically truncated.
- **GPU Usage**: Training requires CUDA-capable GPUs. Use `torchrun` for multi-GPU setups.
- **Data Sources**: Supports both Tushare API (Chinese markets) and web scraping from multiple financial websites.
- **Model Loading**: Models can be loaded from local paths or Hugging Face Hub identifiers.
- **Technical Analysis**: All prediction examples now include comprehensive technical analysis reports with quantitative
  model signals and risk assessment.
- **Market & Sector Sentiment**: Comprehensive analysis includes overall market trends (4 major indices), sector
  performance tracking, and investor sentiment from stock forums. The system automatically identifies the primary index
  and sector affiliation based on stock code.
- **Price Continuity**: Automatic correction of price gaps >3% between historical and predicted data for improved
  accuracy analysis.
- **Multi-Crawler Automatic Switching**: When one crawler returns 0 data, the system automatically tries other available
  crawlers (Tushare → Eastmoney → Tonghuashun → Xueqiu) to ensure robust data collection.
- **Data Collection Resilience**: The enhanced data fetching system provides automatic fallback between multiple data
  sources, significantly improving data collection success rates.
- **Data Saving**: All collected data is automatically saved to the `data/` directory in standard format:
  `{EXCHANGE}_{PERIOD}_{CODE}.csv` (e.g., `XSHG_5min_600977.csv`, `XSHE_5min_300622.csv`).
- **Batch Collection**: Large time ranges are automatically split into optimal batches to overcome API limitations (2000
  data point limit).
- **File Format Standardization**: All data files use consistent naming convention and CSV format with columns:
  `timestamps,open,high,low,close,volume,amount`.
- **Scoring Rules**: Never modify scoring weights/thresholds casually. `scoring_rules.py` is the single source of truth
  (`RULESET_VERSION`) shared by sim and live paths. Any change must be driven by backtest evidence and keep
  `config_hash` traceability.
- **Hot Stock Cache**: Opportunity mining always fetches hot-stock data live (cache disabled by default;
  `KRONOS_DISABLE_HOT_CACHE=1` forces it globally).
- **Compliance**: The unofficial-channel deep mining (v4) module operates at the edge of regulatory gray areas —
  it is a research-oriented signal-scanning experiment, not production trading capability. Keep this framing in docs.
- **Disclaimer**: All analysis/reports are for research only and are not investment advice.