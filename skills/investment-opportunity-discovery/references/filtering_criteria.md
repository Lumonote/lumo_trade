# Filtering Criteria

## Overview

The filtering pipeline applies multi-stage filters to eliminate low-quality stocks and identify high-potential opportunities. Filters are applied sequentially, with each stage narrowing down the candidate pool.

## Filter Stages

### Stage 1: Data Quality Filters

**Purpose**: Ensure data completeness and reliability.

#### 1.1 Price Data Availability
- **Criteria**: Current price > 0
- **Reasoning**: Invalid or missing price data
- **Action**: Exclude stocks with zero or negative prices

#### 1.2 Trading Volume Filter
- **Criteria**: Average daily volume > 1,000,000 shares
- **Reasoning**: Low volume stocks may have liquidity issues
- **Action**: Exclude illiquid stocks

#### 1.3 Exchange Listing
- **Criteria**: Must be listed on SSE or SZSE
- **Reasoning**: Ensure standard trading mechanisms
- **Action**: Exclude delisted, suspended, or invalid exchanges

#### 1.4 Market Cap Filter
- **Criteria**: Market cap > 1 billion CNY (optional)
- **Reasoning**: Avoid micro-cap stocks with high volatility
- **Action**: Exclude stocks below threshold (configurable)

### Stage 2: Technical Filters

**Purpose**: Eliminate stocks with poor technical setups.

#### 2.1 Price Trend Filter
- **Criteria**: Price > MA20 (20-day moving average)
- **Reasoning**: Stocks below long-term trend are in downtrend
- **Action**: Exclude stocks in sustained downtrend

#### 2.2 Volume Confirmation
- **Criteria**: Current volume > 20-day average volume
- **Reasoning**: Breakouts require volume confirmation
- **Action**: Exclude stocks without volume support

#### 2.3 RSI Range Filter
- **Criteria**: RSI(14) between 20 and 80
- **Reasoning**: Extreme RSI indicates overbought/oversold
- **Action**: Exclude stocks with RSI < 20 (oversold) or > 80 (overbought)

#### 2.4 Price Stability
- **Criteria**: Daily volatility < 15%
- **Reasoning**: Excessive volatility indicates high risk
- **Action**: Exclude extremely volatile stocks

### Stage 3: Fundamental Filters

**Purpose**: Ensure basic financial health.

#### 3.1 PE Ratio Filter
- **Criteria**: PE ratio < 100 (sector-adjusted)
- **Reasoning**: Extreme valuations are risky
- **Action**: Exclude stocks with unreasonable PE ratios

#### 3.2 Profitability Filter
- **Criteria**: Net profit > 0 (TTM)
- **Reasoning**: Avoid losing companies
- **Action**: Exclude unprofitable stocks

#### 3.3 Debt Level Filter
- **Criteria**: Debt-to-Equity < 2.0
- **Reasoning**: Excessive debt increases risk
- **Action**: Exclude highly leveraged stocks

### Stage 4: Quantitative Model Filters

**Purpose**: Require minimum quantitative signals.

#### 4.1 Buy Signal Ratio
- **Criteria**: Buy signals / Total signals > 0.4
- **Reasoning**: Majority of models should be bullish
- **Action**: Exclude stocks with weak quantitative support

#### 4.2 Model Consensus
- **Criteria**: At least 5 buy signals from 30 models
- **Reasoning**: Diversified model consensus required
- **Action**: Exclude stocks with insufficient buy signals

#### 4.3 Signal Quality
- **Criteria**: Top models must include at least 1 high-win-rate model
- **Reasoning**: Prefer proven strategies
- **Action**: Exclude stocks only supported by weak models

### Stage 5: Risk Filters

**Purpose**: Eliminate high-risk situations.

#### 5.1 Maximum Drawdown Filter
- **Criteria**: Recent max drawdown < 30%
- **Reasoning**: Limit downside risk
- **Action**: Exclude stocks with large recent declines

#### 5.2 Volatility Filter
- **Criteria**: 30-day volatility < 50%
- **Reasoning**: Control portfolio volatility
- **Action**: Exclude extremely volatile stocks

#### 5.3 News Risk Filter
- **Criteria**: No major negative events in past 7 days
- **Reasoning**: Avoid stocks with recent bad news
- **Action**: Exclude stocks with significant negative events

### Stage 6: Custom Criteria (Optional)

**Purpose**: Apply user-defined filters.

#### 6.1 Sector Filter
- **Criteria**: Must belong to specified sector(s)
- **Reasoning**: Sector-focused investing
- **Action**: Include only specified sectors

#### 6.2 Market Cap Range
- **Criteria**: Market cap between X and Y billion
- **Reasoning**: Size-based strategy
- **Action**: Include only stocks in range

#### 6.3 Price Range
- **Criteria**: Stock price between X and Y CNY
- **Reasoning**: Price point preferences
- **Action**: Include only stocks in range

## Filter Implementation

### Filter Logic Flow

```
Input: Scored Stocks (N)

Stage 1: Data Quality
  ↓ (Filter out: Data Issues)
Remaining: N1

Stage 2: Technical
  ↓ (Filter out: Poor Technicals)
Remaining: N2

Stage 3: Fundamental
  ↓ (Filter out: Weak Fundamentals)
Remaining: N3

Stage 4: Quantitative
  ↓ (Filter out: Weak Signals)
Remaining: N4

Stage 5: Risk
  ↓ (Filter out: High Risk)
Remaining: N5

Stage 6: Custom
  ↓ (Filter out: Doesn't Match Criteria)
Output: Passed Stocks (N_final)
```

### Pass/Fail Criteria

**Pass Condition**: Stock must pass ALL filters in all stages

**Fail Condition**: Stock fails if ANY filter condition is not met

**Exceptions**: Some filters may be marked as "advisory" rather than mandatory

## Filter Configuration

### Default Settings (`assets/config/default_config.json`)

```json
{
  "filtering": {
    "stage1_data_quality": {
      "min_volume": 1000000,
      "require_price": true,
      "require_listing": true,
      "min_market_cap": null
    },
    "stage2_technical": {
      "price_above_ma20": true,
      "volume_confirmation": true,
      "rsi_range": [20, 80],
      "max_daily_volatility": 0.15
    },
    "stage3_fundamental": {
      "max_pe_ratio": 100,
      "require_profitability": true,
      "max_debt_to_equity": 2.0
    },
    "stage4_quantitative": {
      "min_buy_ratio": 0.4,
      "min_buy_signals": 5,
      "require_quality_models": true
    },
    "stage5_risk": {
      "max_drawdown_30d": 0.30,
      "max_volatility_30d": 0.50,
      "exclude_negative_news": true
    },
    "stage6_custom": {
      "sector_filter": null,
      "market_cap_range": null,
      "price_range": null
    }
  }
}
```

### Customization Examples

**Conservative Strategy**:
```json
{
  "filtering": {
    "stage1_data_quality": {
      "min_volume": 5000000,      // Higher liquidity
      "min_market_cap": 5000000000 // Larger companies only
    },
    "stage2_technical": {
      "price_above_ma20": true,
      "volume_confirmation": true
    },
    "stage3_fundamental": {
      "max_pe_ratio": 30,         // Stricter valuation
      "require_profitability": true
    },
    "stage4_quantitative": {
      "min_buy_ratio": 0.6,       // Higher signal threshold
      "min_buy_signals": 10
    },
    "stage5_risk": {
      "max_drawdown_30d": 0.20,  // Lower risk tolerance
      "max_volatility_30d": 0.30
    }
  }
}
```

**Aggressive Strategy**:
```json
{
  "filtering": {
    "stage1_data_quality": {
      "min_volume": 500000,       // Lower liquidity requirement
      "min_market_cap": null      // No market cap limit
    },
    "stage2_technical": {
      "price_above_ma20": false,  // Allow pullbacks
      "volume_confirmation": false
    },
    "stage3_fundamental": {
      "max_pe_ratio": 150,        // Higher valuation tolerance
      "require_profitability": false // Allow growth stocks
    },
    "stage4_quantitative": {
      "min_buy_ratio": 0.3,       // Lower signal threshold
      "min_buy_signals": 3
    },
    "stage5_risk": {
      "max_drawdown_30d": 0.50,  // Higher risk tolerance
      "max_volatility_30d": 0.70
    }
  }
}
```

## Filter Statistics

### Typical Pass Rates

| Stage | Filter Out | Pass Rate |
|-------|------------|-----------|
| Stage 1: Data Quality | 5-10% | 90-95% |
| Stage 2: Technical | 20-30% | 70-80% |
| Stage 3: Fundamental | 10-15% | 60-70% |
| Stage 4: Quantitative | 40-50% | 30-35% |
| Stage 5: Risk | 20-25% | 20-25% |
| **Overall** | **75-80%** | **20-25%** |

### Expected Results

- **Input**: 100 hot stocks
- **After Stage 1**: 90-95 stocks
- **After Stage 2**: 60-70 stocks
- **After Stage 3**: 50-60 stocks
- **After Stage 4**: 20-30 stocks
- **After Stage 5**: 15-25 stocks
- **Final Output**: 15-25 high-quality candidates

## Filter Monitoring

### Track Filter Performance

Monitor which filters eliminate the most stocks:

```bash
# Run with verbose logging
python scripts/discover_opportunities.py --limit 100 --verbose
```

Check log output for filter statistics:
```
✓ Filtering complete: 20/100 stocks passed
Filter Breakdown:
  ✓ Data Quality: 95 passed, 5 failed
  ✓ Technical: 70 passed, 30 failed
  ✓ Fundamental: 60 passed, 10 failed
  ✗ Quantitative: 25 passed, 35 failed
  ✓ Risk: 20 passed, 5 failed
```

### Adjusting Thresholds

If too many stocks pass:
- Tighten thresholds (lower limits, upper bounds)
- Add additional filter stages
- Increase minimum scores

If too few stocks pass:
- Loosen thresholds
- Remove some filter stages
- Reduce minimum scores
- Enable fallback mode

## Best Practices

1. **Start Conservative**: Use strict filters, then gradually relax
2. **Monitor Pass Rates**: Adjust to maintain 15-25% pass rate
3. **Backtest Filters**: Validate filters with historical data
4. **Sector Adjustments**: Tune filters per sector
5. **Market Conditions**: Adapt filters to market volatility
6. **Document Changes**: Track filter modifications and results
7. **Regular Review**: Monthly filter performance review

## Troubleshooting

### Issue: Too Many Stocks Pass
**Symptoms**: Pass rate > 40%
**Solutions**:
- Tighten thresholds
- Add new filter stages
- Increase minimum scores
- Enable stricter risk filters

### Issue: Too Few Stocks Pass
**Symptoms**: Pass rate < 10%
**Solutions**:
- Loosen thresholds
- Remove restrictive filters
- Enable fallback mode
- Lower minimum scores

### Issue: Inconsistent Results
**Symptoms**: Pass rate varies widely day-to-day
**Solutions**:
- Add data quality checks
- Implement smoothing
- Use percentile-based thresholds
- Add minimum data age requirements

### Issue: Filter Logic Errors
**Symptoms**: Unexpected pass/fail decisions
**Solutions**:
- Check filter logic implementation
- Verify data types and ranges
- Review threshold values
- Enable debug logging
