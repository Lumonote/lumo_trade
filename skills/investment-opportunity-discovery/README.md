# Investment Opportunity Discovery Skill

A comprehensive multi-dimensional stock analysis and investment opportunity discovery system for financial markets.

## Quick Start

### Run Full Discovery
```bash
# Analyze top 100 hot stocks
python scripts/discover_opportunities.py --limit 100

# With custom settings
python scripts/discover_opportunities.py --limit 50 --workers 5 --output-dir my_reports/
```

### Analyze Single Stock
```bash
# Deep analysis of a specific stock
python scripts/analyze_single_stock.py --code 600977

# Without LLM analysis
python scripts/analyze_single_stock.py --code 600977 --no-llm
```

### Fetch Hot Stocks
```bash
# Get hot stocks list
python scripts/fetch_hot_stocks.py --limit 50 --output hot_stocks.json

# Use specific data source
python scripts/fetch_hot_stocks.py --source eastmoney --limit 100
```

### Generate Report
```bash
# Generate HTML report
python scripts/generate_report.py --input results.json --format html

# Generate both HTML and Markdown
python scripts/generate_report.py --input results.json --format both
```

## Key Features

### 7-Dimensional Scoring
1. **Technical Analysis** (20%) - RSI, MACD, Bollinger Bands, Moving Averages
2. **Quantitative Models** (25%) - 30 professional trading strategies
3. **Fundamental Analysis** (15%) - PE/PB ratios, growth metrics
4. **Market Sentiment** (15%) - Forum sentiment, market mood
5. **Sector Analysis** (10%) - Sector performance and leadership
6. **News & Events** (10%) - News sentiment, announcements
7. **Dragon Tiger List** (5%) - Institutional trading data

### Smart Filtering Pipeline
- Multi-stage filtering (6 stages)
- Automatic quality checks
- Configurable thresholds
- Expected pass rate: 20-25%

### LLM-Powered Analysis (Optional)
- Deep AI analysis for top stocks (score ≥60)
- Investment recommendations
- Price predictions
- Risk assessment
- Support for Qwen and DeepSeek models

### Report Generation
- Professional HTML reports
- Interactive charts and tables
- Top 10 highlights
- Detailed scoring breakdown
- LLM analysis integration

## Configuration

### Environment Variables
```bash
# LLM Configuration
export QWEN_API_KEY="your-api-key"
export DEEPSEEK_API_KEY="your-api-key"

# Output Directory
export KRONOS_RESULTS_DIR="reports/"

# Performance
export MAX_WORKERS=10
```

### Config File
Edit `assets/config/default_config.json` to customize:
- Scoring weights
- Filter thresholds
- LLM settings
- Data source preferences

## Documentation

### References
- **Scoring Methodology**: `references/scoring_methodology.md`
- **Filtering Criteria**: `references/filtering_criteria.md`
- **LLM Analysis Guide**: `references/llm_analysis_guide.md`
- **Data Sources**: `references/data_sources.md`

### Scripts
- **discover_opportunities.py**: Main discovery pipeline
- **analyze_single_stock.py**: Single stock analysis
- **fetch_hot_stocks.py**: Hot stocks data fetching
- **generate_report.py**: Report generation

## Example Output

### Console Output
```
🎯 Investment Opportunity Discovery Started
============================================================

Step 1: Fetching hot stocks TOP 100...
✓ Successfully fetched 100 hot stocks

Step 2: Running multi-dimensional scoring...
✓ Completed 100/100 stock analyses

Step 3: Applying filter pipeline...
✓ Filtering complete: 23/100 stocks passed

Step 3.5: Running LLM deep analysis...
Found 10 high-grade stocks (≥60 pts)
✓ LLM analysis complete: 10 stocks

Step 4: Generating investment report...
✓ Report generated: reports/investment_report_20240115.html

============================================================
🎉 Investment Discovery Complete!
============================================================
Total time: 45.3 seconds
Analyzed stocks: 100
Passed filters: 23
Report path: reports/investment_report_20240115.html
============================================================
```

### Sample Report Structure
```
Investment Opportunity Discovery Report
├── Executive Summary
│   ├── Total Analyzed: 100 stocks
│   ├── Passed Filters: 23 stocks
│   ├── Top Score: 87.3 (Stock: 600977)
│   └── Average Score: 65.4
│
├── Top 10 Highlights
│   ├── Stock 600977: Score 87.3, Rating A
│   ├── Stock 000001: Score 84.1, Rating A
│   └── ... (Top 10 detailed)
│
├── Detailed Analysis
│   ├── Technical Analysis
│   ├── Quantitative Models
│   ├── Fundamental Data
│   ├── Sentiment Analysis
│   └── Sector Performance
│
├── LLM AI Analysis
│   ├── Investment Recommendations
│   ├── Price Predictions
│   ├── Risk Assessment
│   └── Strategy Advice
│
├── Market Sentiment
│   ├── Overall Market Status
│   ├── Sector Rankings
│   └── Hot News
│
└── Appendix
    ├── Scoring Methodology
    ├── Filter Results
    └── Data Sources
```

## Use Cases

### 1. Daily Opportunity Screening
```bash
# Morning routine: Scan for opportunities
python scripts/discover_opportunities.py --limit 100 --output-dir daily/
```

### 2. Sector-Focused Analysis
```python
from scripts.discover_opportunities import OpportunityDiscovery

discovery = OpportunityDiscovery()
# Configure for specific sector
results = discovery.run(limit=50, sector_filter='technology')
```

### 3. High-Quality Opportunities
```bash
# Find only A-grade opportunities
python scripts/discover_opportunities.py --limit 100 | grep "Rating: A"
```

### 4. LLM-Powered Insights
```bash
# Enable LLM analysis for top 10
python scripts/discover_opportunities.py --limit 50 --enable-llm
```

## Integration

### With Kronos Model
```python
from analysis.kronos_predictor import KronosPredictor
from scripts.discover_opportunities import OpportunityDiscovery

# Combine both systems
discovery = OpportunityDiscovery()
predictor = KronosPredictor()

# Get opportunities
opportunities = discovery.run(limit=50)

# Generate predictions
for stock in opportunities:
    prediction = predictor.predict(stock['code'])
```

### With Portfolio Management
```python
from portfolio.manager import PortfolioManager

discovery = OpportunityDiscovery()
results = discovery.run(limit=100)

# Build portfolio from top 10
top_stocks = [s for s in results if s['filter_passed']][:10]
portfolio = PortfolioManager()
portfolio.add_stocks(top_stocks)
```

## Best Practices

### 1. Regular Updates
- Run discovery daily for fresh opportunities
- Update cache settings for balance of speed/freshness
- Monitor data source health

### 2. Filter Tuning
- Start with default settings
- Adjust based on pass rates
- Backtest filter changes

### 3. LLM Configuration
- Use for high-scoring stocks only (≥60)
- Monitor API costs
- Validate predictions

### 4. Report Customization
- Use templates in `assets/templates/`
- Adjust report sections
- Include relevant metrics

## Troubleshooting

### Issue: No Data Fetched
```bash
# Check data sources
python scripts/check_data_sources.py

# Test individual source
python scripts/fetch_hot_stocks.py --source eastmoney --limit 5
```

### Issue: Low Pass Rate (<10%)
- Loosen filter thresholds
- Check data quality
- Verify calculation logic

### Issue: High Pass Rate (>40%)
- Tighten filter thresholds
- Add more filter stages
- Increase minimum scores

### Issue: LLM Analysis Fails
```bash
# Check LLM configuration
python -c "from analysis.llm_service import LLMConfig; print(LLMConfig().is_configured())"

# Check API keys
echo $QWEN_API_KEY
echo $DEEPSEEK_API_KEY
```

## Performance

### Benchmarks
- **100 stocks**: 45-60 seconds
- **50 stocks**: 25-35 seconds
- **10 stocks**: 8-12 seconds
- **Single stock**: 2-5 seconds

### Optimization Tips
- Increase `--workers` for faster processing
- Enable caching for repeated runs
- Use SSD for data storage
- Monitor network latency

## Support

### Documentation
- Full documentation in `references/` directory
- API documentation in code comments
- Configuration examples in `examples/`

### Logging
- Logs: `logs/investment_discovery.log`
- Debug mode: Add `--debug` flag
- Verbose output: Add `--verbose` flag

### Common Questions

**Q: How often should I run the discovery?**
A: Daily for active trading, weekly for long-term investing.

**Q: What's a good pass rate?**
A: 20-25% is typical. <10% = too strict, >40% = too loose.

**Q: Do I need LLM analysis?**
A: Optional but recommended for top stocks. Provides deeper insights.

**Q: Can I customize the scoring?**
A: Yes, edit `assets/config/default_config.json` weights.

**Q: How reliable are the predictions?**
A: LLM predictions are for guidance only. Always do your own research.

## License

This skill is part of the Kronos financial forecasting system.

## Changelog

### Version 1.0.0
- Initial release
- 7-dimensional scoring system
- Multi-stage filtering
- LLM integration
- Report generation
