---
name: Investment Opportunity Discovery
description: Multi-dimensional stock analysis and opportunity discovery system for financial markets. Integrates hot stocks fetching, technical analysis, quantitative models, fundamental data, sentiment analysis, sector performance, news events, and LLM-powered intelligent recommendations to identify high-potential investment opportunities.
---

# Investment Opportunity Discovery Skill

## Overview

This skill provides a comprehensive investment opportunity discovery system that analyzes stocks across multiple dimensions to identify high-potential investment opportunities. It combines real-time data collection, quantitative analysis, sentiment analysis, and AI-powered recommendations.

## Core Capabilities

### 1. Multi-Source Data Collection
- **Hot Stocks Fetcher**: Real-time popular stock data from multiple sources
- **Global Market News**: Top 10 trending financial news
- **Sector-Specific News**: Industry-relevant news based on filtered stocks
- **Investor Sentiment**: Market sentiment analysis from forums and discussions

### 2. Comprehensive Scoring System (7 Dimensions)
- **Technical Analysis**: 20+ indicators (RSI, MACD, Bollinger Bands, MA5/10/20, KDJ)
- **Quantitative Models**: 30 professional trading strategies with buy/sell signals
- **Fundamental Data**: PE/PB ratios, revenue/profit growth, market cap
- **Market Sentiment**: Overall market sentiment across major indices
- **Sector Analysis**: Sector performance and leader identification
- **News & Events**: Company announcements and news sentiment
- **Dragon Tiger List**: Institutional trading data (buy/sell orders)

### 3. Smart Filtering Pipeline
- Multi-stage filtering to identify high-quality opportunities
- Configurable thresholds for different investment strategies
- Automatic exclusion of low-quality or high-risk stocks

### 4. LLM-Powered Analysis (Optional)
- **Deep AI Analysis**: For stocks scoring ≥60 points
- **K-Line Predictions**: AI-generated price forecasts
- **Risk Assessment**: Multi-dimensional risk evaluation
- **Investment Recommendations**: Actionable trading advice
- **Target Prices & Stop-Loss**: Specific entry/exit points

### 5. Report Generation
- **HTML Reports**: Interactive, visual reports with charts
- **Markdown Reports**: Text-based summaries for documentation
- **Top 10 Highlights**: Best opportunities with detailed analysis
- **Export Options**: Save results for further analysis

## When to Use This Skill

Use this skill when you need to:

1. **Screen Investment Opportunities**: Find promising stocks from a large universe
2. **Multi-Dimensional Analysis**: Evaluate stocks using technical, fundamental, and sentiment factors
3. **Identify Market Trends**: Discover trending sectors and hot stocks
4. **Get AI Recommendations**: Leverage LLM for deep analysis and predictions
5. **Generate Investment Reports**: Create professional reports for stakeholders
6. **Monitor Market Sentiment**: Track overall and sector-specific sentiment
7. **Batch Analysis**: Analyze multiple stocks simultaneously

## Usage Patterns

### Pattern 1: Complete Discovery Run
```
I want to discover top investment opportunities from today's hot stocks.
```
This triggers the full pipeline: data collection → scoring → filtering → LLM analysis → report generation.

### Pattern 2: Specific Stock Analysis
```
Analyze stock 600977 for investment potential.
```
This performs deep analysis on a single stock with all dimensions.

### Pattern 3: Sector-Focused Discovery
```
Find opportunities in the semiconductor sector.
```
This filters by sector and finds the best opportunities within that sector.

### Pattern 4: Custom Filtering
```
Show me stocks with low PE ratios and high growth potential.
```
This applies custom filtering criteria to find specific types of opportunities.

## Key Components

### Scripts (`scripts/`)

#### `discover_opportunities.py`
Main discovery script that orchestrates the entire pipeline.
- Fetches hot stocks
- Runs multi-dimensional scoring
- Applies filtering
- Generates reports

**Usage**:
```bash
python scripts/discover_opportunities.py --limit 100 --workers 10
```

**Parameters**:
- `--limit`: Number of hot stocks to analyze (default: 100)
- `--workers`: Concurrent processing threads (default: 10)
- `--test-codes`: Comma-separated list of stock codes for testing
- `--output-dir`: Directory for generated reports

#### `analyze_single_stock.py`
Single stock analysis script.
- Comprehensive multi-dimensional analysis
- LLM-powered insights (if configured)
- Detailed scoring breakdown

**Usage**:
```bash
python scripts/analyze_single_stock.py --code 600977
```

#### `fetch_hot_stocks.py`
Hot stocks data fetcher.
- Supports multiple data sources (Eastmoney, Tonghuashun, Xueqiu)
- Automatic fallback between sources
- Configurable cache settings

**Usage**:
```bash
python scripts/fetch_hot_stocks.py --limit 100 --force-refresh
```

#### `generate_report.py`
Report generation script.
- Creates HTML and Markdown reports
- Customizable templates
- Top 10 stock highlights

**Usage**:
```bash
python scripts/generate_report.py --input results.json --output-dir reports/
```

### References (`references/`)

#### `scoring_methodology.md`
Detailed explanation of the 7-dimensional scoring system:
- Technical analysis indicators and weights
- Quantitative model strategies
- Fundamental analysis metrics
- Sentiment analysis methodology
- Scoring thresholds and ratings

#### `filtering_criteria.md`
Complete filtering pipeline documentation:
- Stage 1: Basic quality filters
- Stage 2: Technical filters
- Stage 3: Risk filters
- Stage 4: Custom criteria
- Pass/fail conditions

#### `llm_analysis_guide.md`
LLM integration and analysis guide:
- Supported LLM models (Qwen, DeepSeek)
- Analysis output format
- Prediction data structure
- Risk assessment methodology
- Confidence scoring

#### `data_sources.md`
Data source documentation:
- Hot stocks sources and APIs
- News aggregation methods
- Market sentiment data
- Sector classification
- Rate limiting and fallbacks

### Assets (`assets/`)

#### `report_templates/`
HTML and Markdown report templates with:
- Professional styling
- Interactive charts
- Top 10 highlights section
- Detailed scoring tables
- LLM analysis integration

#### `config/`
Configuration files:
- Default scoring weights
- Filtering thresholds
- LLM model settings
- Data source configurations

## Workflow

### Standard Discovery Flow

1. **Data Collection Phase**
   - Fetch hot stocks from multiple sources
   - Collect global market news
   - Gather sector-specific news
   - Preload market sentiment data

2. **Analysis Phase**
   - Run 7-dimensional scoring for each stock
   - Apply technical indicators (20+ metrics)
   - Evaluate 30 quantitative models
   - Assess fundamental metrics
   - Analyze sentiment data
   - Check news/events impact

3. **Filtering Phase**
   - Apply multi-stage filters
   - Eliminate low-quality stocks
   - Identify passing candidates

4. **LLM Analysis Phase** (Optional)
   - Select stocks with score ≥60
   - Top 10 by score
   - Run LLM deep analysis
   - Generate predictions and recommendations

5. **Report Generation Phase**
   - Compile results
   - Generate HTML/Markdown reports
   - Highlight top opportunities
   - Export findings

### Scoring Dimensions

| Dimension | Weight | Key Metrics |
|-----------|--------|-------------|
| Technical | 20% | RSI, MACD, Bollinger, MA, KDJ |
| Quantitative | 25% | 30 trading models, buy/sell ratio |
| Fundamental | 15% | PE, PB, revenue/profit growth |
| Sentiment | 15% | Forum sentiment, market mood |
| Sector | 10% | Sector performance, leaders |
| Events | 10% | News sentiment, announcements |
| Dragon Tiger | 5% | Institutional trading data |

### Rating System

- **A Grade**: Score ≥80 (Excellent opportunity)
- **B Grade**: Score 60-79 (Good opportunity)
- **C Grade**: Score 40-59 (Average opportunity)
- **D Grade**: Score <40 (Poor opportunity)

## Configuration

### Environment Variables

- `KRONOS_RESULTS_DIR`: Custom output directory for reports
- `LLM_MODEL`: Preferred LLM model (qwen, deepseek)
- `MAX_WORKERS`: Default concurrent workers
- `CACHE_DIR`: Data cache directory

### Config File

Edit `assets/config/default_config.json`:

```json
{
  "scoring": {
    "technical_weight": 0.20,
    "quantitative_weight": 0.25,
    "fundamental_weight": 0.15,
    "sentiment_weight": 0.15,
    "sector_weight": 0.10,
    "events_weight": 0.10,
    "dragon_tiger_weight": 0.05
  },
  "filtering": {
    "min_score": 40,
    "max_market_cap": null,
    "min_volume": 1000000
  },
  "llm": {
    "enabled": true,
    "model": "qwen",
    "max_stocks": 10,
    "min_score_for_llm": 60
  }
}
```

## Best Practices

1. **Use Test Mode for Development**: Use `--test-codes` to test with specific stocks
2. **Adjust Workers Based on Resources**: More workers = faster analysis but higher resource usage
3. **Configure LLM for Best Results**: Enable LLM analysis for top-tier insights
4. **Review Filtering Criteria**: Adjust thresholds based on investment strategy
5. **Monitor Data Sources**: Ensure data source connectivity for real-time analysis
6. **Interpret Reports Contextually**: Use reports as guidance, not definitive investment advice

## Example Workflows

### Example 1: Daily Opportunity Discovery
```bash
# Run complete discovery with default settings
python scripts/discover_opportunities.py --limit 100 --workers 10

# Output: HTML report in results/ directory
```

### Example 2: Focused Sector Analysis
```python
from scripts.discover_opportunities import OpportunityDiscovery

discovery = OpportunityDiscovery()
# Configure for tech sector
results = discovery.run(limit=100, sector_filter='technology')
```

### Example 3: Single Stock Deep Dive
```bash
python scripts/analyze_single_stock.py --code 600977 --enable-llm

# Output: Detailed analysis report
```

## Integration Notes

This skill integrates with:
- **Kronos Model**: For K-line predictions
- **Market Data APIs**: Tushare, Eastmoney, Tonghuashun, Xueqiu
- **News Sources**: Financial news aggregation
- **LLM Services**: Qwen, DeepSeek for AI analysis
- **Technical Analysis**: 20+ indicators and 30 quantitative models

## Troubleshooting

### Common Issues

1. **Low Data Quality**
   - Check internet connectivity
   - Verify API credentials
   - Use fallback data sources

2. **Slow Performance**
   - Reduce `--limit` parameter
   - Decrease `--workers` count
   - Enable caching

3. **LLM Analysis Fails**
   - Verify LLM API configuration
   - Check API quotas
   - Review error logs

4. **Missing Reports**
   - Check output directory permissions
   - Verify `KRONOS_RESULTS_DIR` setting
   - Review error messages

For detailed troubleshooting, see `references/troubleshooting.md`.
