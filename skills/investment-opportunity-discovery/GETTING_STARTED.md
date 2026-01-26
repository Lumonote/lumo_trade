# Getting Started

## Overview

The Investment Opportunity Discovery skill provides a comprehensive system for analyzing stocks across 7 dimensions to identify high-potential investment opportunities.

## Quick Start (5 minutes)

### 1. Check Your Environment

```bash
# Verify you're in the Kronos directory
cd /path/to/Kronos

# Check Python path
python -c "import sys; print(sys.path[0])"
# Should show: /path/to/Kronos
```

### 2. Run a Simple Test

```bash
# Test with test stocks (no real data fetching)
cd skills/investment-opportunity-discovery
python scripts/discover_opportunities.py --limit 50 --test-codes 600977,000001,000002 --no-llm
```

This will:
- Analyze 3 test stock codes
- Skip LLM analysis for speed
- Generate a basic report

Expected output:
```
🎯 Investment Opportunity Discovery Started
Step 1: Using test stock codes: ['600977', '000001', '000002']
✓ Successfully fetched 3 hot stocks
Step 2: Running multi-dimensional scoring...
✓ Completed 3/3 stock analyses
Step 3: Applying filter pipeline...
✓ Filtering complete: 1/3 stocks passed
Report path: results/investment_report_20240115.html
```

### 3. View Your Results

```bash
# Open the generated report
open results/investment_report_20240115.html  # macOS
# or
xdg-open results/investment_report_20240115.html  # Linux
```

## Usage Examples

### Example 1: Daily Stock Screening

```bash
# Morning routine: Find top 100 opportunities
python scripts/discover_opportunities.py --limit 100 --workers 10 --output-dir daily_reports/
```

This analyzes 100 hot stocks and generates a comprehensive report.

### Example 2: Analyze Specific Stocks

```bash
# Analyze a watchlist
python scripts/discover_opportunities.py --test-codes 600519,000858,000001 --output-dir watchlist/
```

### Example 3: Single Stock Deep Dive

```bash
# Deep analysis of one stock
python scripts/analyze_single_stock.py --code 600977

# With LLM analysis
python scripts/analyze_single_stock.py --code 600977 --enable-llm
```

### Example 4: Quick Stock List

```bash
# Just get hot stocks without analysis
python scripts/fetch_hot_stocks.py --limit 50 --output hot_stocks.json

# View the data
cat hot_stocks.json | python -m json.tool | head -30
```

## Understanding the Output

### Console Output

The system provides detailed progress updates:

```
Step 1: Fetching hot stocks TOP 100...
✓ Successfully fetched 100 hot stocks

Step 2: Running multi-dimensional scoring...
Concurrent threads: 10
✓ Completed 100/100 stock analyses

Step 3: Applying filter pipeline...
✓ Filtering complete: 23/100 stocks passed

Step 3.5: Running LLM deep analysis...
Found 10 high-grade stocks (≥60 pts)
✓ LLM analysis complete: 10 stocks

Step 4: Generating investment report...
✓ Report generated: results/investment_report_20240115.html
```

### Report Structure

The HTML report includes:

1. **Summary Section**
   - Total stocks analyzed
   - Pass rate
   - Top scores

2. **Top 10 Highlights**
   - Best opportunities with detailed scores
   - LLM AI analysis (if enabled)
   - Key metrics

3. **Detailed Tables**
   - All passed stocks
   - Scoring breakdown by dimension
   - Filter results

4. **Market Sentiment**
   - Overall market status
   - Hot news
   - Sector performance

## Configuration

### Basic Settings

Edit `assets/config/default_config.json`:

```json
{
  "performance": {
    "max_workers": 10,        // Concurrent threads
    "enable_rich_progress": true
  },
  "filtering": {
    "stage4_quantitative": {
      "min_buy_ratio": 0.4,   // Minimum buy signal ratio
      "min_buy_signals": 5     // Minimum buy signals
    }
  },
  "llm": {
    "enabled": true,          // Enable LLM analysis
    "min_score_for_llm": 60   // Min score for LLM analysis
  }
}
```

### Common Customizations

#### Conservative Filtering
```json
{
  "filtering": {
    "stage4_quantitative": {
      "min_buy_ratio": 0.6,    // Higher threshold
      "min_buy_signals": 10
    },
    "stage5_risk": {
      "max_drawdown_30d": 0.20  // Lower risk tolerance
    }
  }
}
```

#### Aggressive Filtering
```json
{
  "filtering": {
    "stage4_quantitative": {
      "min_buy_ratio": 0.3,    // Lower threshold
      "min_buy_signals": 3
    }
  }
}
```

## Troubleshooting

### Issue: "No hot stocks fetched"

**Solution**: Check internet connection and data sources
```bash
# Test data sources
python scripts/fetch_hot_stocks.py --limit 5 --source eastmoney

# Check cache
ls -la cache/hot_stocks_*.json
```

### Issue: "LLM analysis failed"

**Solution**: Configure LLM API or disable LLM
```bash
# Disable LLM for now
python scripts/discover_opportunities.py --no-llm

# Check LLM config
python -c "from analysis.llm_service import LLMConfig; print(LLMConfig().is_configured())"
```

### Issue: "Too many stocks pass/fail"

**Solution**: Adjust filter thresholds
```bash
# If pass rate < 10%, loosen filters
# Edit assets/config/default_config.json
# Lower min_buy_ratio, min_buy_signals

# If pass rate > 40%, tighten filters
# Edit assets/config/default_config.json
# Raise min_buy_ratio, min_buy_signals
```

### Issue: "Slow performance"

**Solution**: Optimize settings
```bash
# Reduce workers if CPU-bound
python scripts/discover_opportunities.py --workers 5

# Use fewer stocks
python scripts/discover_opportunities.py --limit 50

# Disable LLM
python scripts/discover_opportunities.py --no-llm
```

## Best Practices

### 1. Start Simple
```bash
# First run: Use test mode
python scripts/discover_opportunities.py --test-codes 600977,000001 --no-llm
```

### 2. Understand Filters
```bash
# Enable verbose logging
python scripts/discover_opportunities.py --limit 50 --verbose
```

### 3. Monitor Pass Rates
- Ideal pass rate: 20-25%
- < 10%: Filters too strict
- > 40%: Filters too loose

### 4. Regular Updates
```bash
# Set up daily run
# Add to cron (macOS/Linux)
0 9 * * 1-5 cd /path/to/Kronos/skills/investment-opportunity-discovery && python scripts/discover_opportunities.py --limit 100 --output-dir reports/$(date +\%Y-\%m-\%d)/
```

### 5. Validate Results
- Cross-check top picks
- Review LLM analysis
- Consider market context

## Advanced Usage

### Custom Filtering

```python
from scripts.discover_opportunities import OpportunityDiscovery

# Create custom instance
discovery = OpportunityDiscovery(max_workers=5)

# Modify filter criteria
discovery.filter.min_buy_ratio = 0.6
discovery.filter.min_buy_signals = 10

# Run discovery
report_path = discovery.run(
    limit=100,
    output_dir='custom_reports/'
)
```

### Batch Processing

```bash
# Process multiple batches
for day in 2024-01-01 2024-01-02 2024-01-03; do
    python scripts/discover_opportunities.py --limit 100 --output-dir reports/$day/
done
```

### Generate Multiple Reports

```bash
# HTML report
python scripts/generate_report.py --input results.json --format html

# Markdown report
python scripts/generate_report.py --input results.json --format markdown

# Both formats
python scripts/generate_report.py --input results.json --format both
```

## Next Steps

1. **Read the Documentation**
   - `references/scoring_methodology.md` - Understand scoring
   - `references/filtering_criteria.md` - Learn filtering
   - `references/llm_analysis_guide.md` - Configure LLM

2. **Explore Examples**
   - `examples/quick_start.py` - Run example code
   - `examples/custom_analysis.py` - Custom analysis

3. **Customize for Your Needs**
   - Adjust weights in config
   - Modify filter criteria
   - Set up automated runs

4. **Integrate with Other Tools**
   - Combine with Kronos predictions
   - Export to portfolio managers
   - Set up alerts

## Getting Help

### Documentation
- Full docs: `references/` directory
- README: `README.md`
- Skill guide: `SKILL.md`

### Logs
```bash
# View logs
tail -f logs/investment_discovery.log

# Debug mode
python scripts/discover_opportunities.py --debug
```

### Common Commands
```bash
# Check environment
python -c "from analysis.opportunity_scorer import OpportunityScorer; print('OK')"

# Test individual components
python scripts/fetch_hot_stocks.py --limit 5
python scripts/analyze_single_stock.py --code 600977 --no-llm

# Generate report
python scripts/generate_report.py --input results.json --summary
```

## Summary

You now know how to:
- ✓ Run basic discovery
- ✓ Analyze single stocks
- ✓ Customize filters
- ✓ Configure LLM
- ✓ Troubleshoot issues

For more advanced usage, explore the documentation and examples!
