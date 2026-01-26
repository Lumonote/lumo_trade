# Data Sources

## Overview

The Investment Opportunity Discovery system integrates multiple data sources to ensure comprehensive, real-time market data. This document describes available data sources, their capabilities, and fallback mechanisms.

## Hot Stocks Data Sources

### 1. Eastmoney (东方财富)
- **URL**: http://www.eastmoney.com
- **Data Type**: Real-time hot stocks, rankings
- **Update Frequency**: 1 minute
- **Reliability**: High
- **API Method**: Web scraping with Playwright

**Features**:
- Hot stocks ranking by volume, turnover,涨幅
- Real-time price updates
- Market sector classification
- Stock metadata (name, code, exchange)

**Rate Limiting**:
- Requests: 1 per 2 seconds
- Daily limit: 10,000 requests
- Anti-crawler: User-agent rotation, proxy support

**Example Output**:
```json
{
    "code": "600977",
    "name": "Example Stock",
    "price": 45.67,
    "change_pct": 3.45,
    "volume": 12500000,
    "turnover": 567890000,
    "source": "eastmoney"
}
```

### 2. Tonghuashun (同花顺)
- **URL**: http://www.10jqka.com.cn
- **Data Type**: Hot stocks, technical indicators
- **Update Frequency**: 1 minute
- **Reliability**: High
- **API Method**: Web scraping with Playwright

**Features**:
- Hot stocks by industry
- Technical analysis data
- Financial indicators
- Market sentiment data

**Rate Limiting**:
- Requests: 1 per 3 seconds
- Daily limit: 8,000 requests
- Anti-crawler: Captcha handling, delay randomization

### 3. Xueqiu (雪球)
- **URL**: https://xueqiu.com
- **Data Type**: User-driven hot stocks, discussions
- **Update Frequency**: 5 minutes
- **Reliability**: Medium-High
- **API Method**: Web scraping with Playwright

**Features**:
- Community-driven rankings
- User sentiment indicators
- Discussion volume
- Investment themes

**Rate Limiting**:
- Requests: 1 per 5 seconds
- Daily limit: 5,000 requests
- Anti-crawler: Session management, cookie handling

### 4. Auto Mode (Recommended)
- **Description**: Automatically tries sources in order
- **Fallback Order**: Eastmoney → Tonghuashun → Xueqiu
- **Benefits**: Highest success rate
- **Use Case**: Default for production systems

**Logic Flow**:
```
1. Try Eastmoney
   If success: Return data
   If fail: Log error, try next source

2. Try Tonghuashun
   If success: Return data
   If fail: Log error, try next source

3. Try Xueqiu
   If success: Return data
   If fail: Log error, use fallback data
```

## News Data Sources

### 1. Global Hot News
- **Sources**: Eastmoney, Tonghuashun, Xueqiu
- **Categories**: Market-wide news, economic updates
- **Update Frequency**: Every 15 minutes
- **Limit**: Top 10 news items

**Data Structure**:
```json
{
    "title": "China announces new economic policy",
    "url": "https://example.com/news/123",
    "source": "Eastmoney",
    "publish_time": "2024-01-15 10:30:00",
    "heat": 95,
    "rank": 1
}
```

### 2. Sector-Specific News
- **Sources**: Industry publications, sector trackers
- **Categories**: Sector trends, industry news
- **Update Frequency**: Every 30 minutes
- **Limit**: 4 news per sector, 10 total

### 3. Company News
- **Sources**: Stock forums, announcement systems
- **Categories**: Earnings, announcements, events
- **Update Frequency**: Real-time
- **Limit**: 3 news per stock

## Market Data Sources

### 1. Price Data
- **Sources**: Tushare API, Exchange APIs
- **Frequency**: Real-time during trading hours
- **Data**: OHLCV (Open, High, Low, Close, Volume)

**Tushare Configuration**:
```python
# Set token in environment
export TUSHARE_TOKEN="your-token"

# Or in config file
{
    "tushare": {
        "token": "your-token",
        "fields": ["ts_code", "trade_date", "open", "high", "low", "close", "volume"]
    }
}
```

### 2. Fundamental Data
- **Sources**: Company filings, financial statements
- **Frequency**: Daily (after market close)
- **Data**: PE, PB, revenue, profit, ratios

### 3. Dragon Tiger List
- **Sources**: Exchange data, institutional trading
- **Frequency**: Daily (post-market)
- **Data**: Net buy/sell volumes, institutional activity

## Sentiment Data Sources

### 1. Market Sentiment
- **Sources**: Major indices (SSE, SZSE, ChiNext, STAR)
- **Components**:
  - Index performance
  - Volume trends
  - Volatility indicators

**Calculation**:
```
Market Sentiment Score = (Index Returns * 0.4) +
                        (Volume Change * 0.3) +
                        (Volatility Inverse * 0.3)
```

### 2. Sector Sentiment
- **Sources**: Sector indices, industry trackers
- **Components**:
  - Sector performance
  - Relative strength
  - Money flow

### 3. Forum Sentiment
- **Sources**: Stock forums, discussion boards
- **Components**:
  - Bullish/Bearish ratios
  - Discussion volume
  - Keyword analysis

**Processing Pipeline**:
```
1. Fetch discussions
2. Remove spam/ads
3. NLP sentiment analysis
4. Calculate ratios
5. Apply confidence weighting
```

## Technical Indicator Data

### 1. Price-Based Indicators
- **Sources**: Calculated from OHLCV data
- **Indicators**: MA, EMA, MACD, RSI, Bollinger Bands

### 2. Volume-Based Indicators
- **Sources**: Volume data
- **Indicators**: Volume MA, Volume Ratio, OBV

### 3. Composite Indicators
- **Sources**: Combined price/volume
- **Indicators**: KDJ, Williams %R, CCI

## Data Quality Assurance

### 1. Validation Rules
- **Price**: Must be > 0
- **Volume**: Must be ≥ 0
- **Change**: Must be within ±20% daily
- **Timestamp**: Must be recent (< 1 hour for real-time)

### 2. Outlier Detection
- **Method**: Statistical (3-sigma rule)
- **Action**: Flag and exclude from calculations
- **Logging**: Record all outliers

### 3. Data Completeness
- **Required Fields**: Price, Volume, Timestamp
- **Optional Fields**: Turnover, Change %
- **Missing Data**: Fill with last known value or null

## Fallback Mechanisms

### 1. Data Source Fallback
```
Primary Source Failed
    ↓
Secondary Source
    ↓
Tertiary Source
    ↓
Fallback Cache
    ↓
Static Backup Data
```

### 2. Cache Strategy
- **Hot Stocks**: Cache for 5 minutes
- **News**: Cache for 30 minutes
- **Prices**: Cache for 1 minute
- **Indicators**: Cache for 15 minutes

### 3. Stale Data Handling
```
Data Age < Threshold
    ↓ (Use fresh data)
Data Age > Threshold
    ↓ (Warn and use stale data)
Data Age > Max Age
    ↓ (Reject and refetch)
```

## Rate Limiting

### Global Limits
- **Total Requests**: 100 per minute
- **Per Source**: 30 per minute
- **Burst Limit**: 10 requests per second

### Exponential Backoff
```python
def backoff_delay(attempt):
    return min(60, 2 ** attempt)  # 1, 2, 4, 8, 16... seconds

for attempt in range(max_retries):
    try:
        fetch_data()
        break
    except RateLimitError:
        sleep(backoff_delay(attempt))
```

## Configuration

### Config File Structure
```json
{
    "data_sources": {
        "hot_stocks": {
            "primary": "eastmoney",
            "fallback_order": ["tonghuashun", "xueqiu"],
            "rate_limits": {
                "eastmoney": {"requests_per_minute": 30},
                "tonghuashun": {"requests_per_minute": 20},
                "xueqiu": {"requests_per_minute": 12}
            }
        },
        "news": {
            "sources": ["eastmoney", "tonghuashun"],
            "update_interval_minutes": 15
        },
        "cache": {
            "hot_stocks_ttl": 300,
            "news_ttl": 1800,
            "prices_ttl": 60
        }
    }
}
```

## Monitoring

### 1. Data Source Health
```bash
# Check source status
python scripts/check_data_sources.py

# Output:
# Eastmoney: ✓ Healthy (99.5% success rate)
# Tonghuashun: ✓ Healthy (98.2% success rate)
# Xueqiu: ⚠️ Degraded (85.3% success rate)
```

### 2. Success Rates
Track daily success rates:
```
Date: 2024-01-15
Eastmoney: 98.5% (985/1000 requests)
Tonghuashun: 97.2% (972/1000 requests)
Xueqiu: 89.3% (893/1000 requests)
Overall: 95.0% success rate
```

### 3. Alerting
```python
ALERT_THRESHOLDS = {
    "success_rate_low": 0.90,      # Alert if < 90%
    "response_time_high": 5.0,     # Alert if > 5 seconds
    "error_rate_high": 0.10        # Alert if > 10% errors
}
```

## Best Practices

### 1. Data Collection
- Always use multiple sources
- Implement proper rate limiting
- Cache data appropriately
- Monitor source health

### 2. Error Handling
- Graceful degradation
- Informative error messages
- Automatic retries
- Fallback to cached data

### 3. Performance
- Concurrent requests where possible
- Connection pooling
- Compression for large responses
- Efficient parsing

### 4. Compliance
- Respect robots.txt
- Follow API terms of service
- Use data for authorized purposes only
- Implement data retention policies

## Troubleshooting

### Issue: All Sources Fail
**Symptoms**: No hot stocks data

**Solutions**:
1. Check internet connectivity
2. Verify DNS resolution
3. Test sources manually
4. Use fallback cache
5. Check API limits

**Diagnostic Commands**:
```bash
# Test network
ping eastmoney.com

# Test individual source
python -c "
from scripts.hot_stocks_fetcher import HotStocksFetcher
f = HotStocksFetcher()
print(f.fetch_from_eastmoney(limit=5))
"

# Check cache
ls -la cache/hot_stocks_*.json
```

### Issue: Slow Performance
**Symptoms**: Data fetching takes > 10 seconds

**Solutions**:
1. Check network latency
2. Reduce concurrency
3. Increase cache TTL
4. Use faster sources
5. Optimize parsing

**Performance Test**:
```bash
python scripts/benchmark_data_sources.py

# Output:
# Eastmoney: 1.2s average (100 requests)
# Tonghuashun: 1.8s average (100 requests)
# Xueqiu: 2.5s average (100 requests)
```

### Issue: Inconsistent Data
**Symptoms**: Different values from different sources

**Solutions**:
1. Check data timestamps
2. Verify calculation methods
3. Use most reliable source
4. Average multiple sources
5. Flag discrepancies

**Data Comparison**:
```bash
python scripts/compare_data_sources.py --code 600977

# Output:
# Eastmoney: Price=45.67, Volume=12500000
# Tonghuashun: Price=45.65, Volume=12480000
# Difference: 0.04%, 0.16% (acceptable)
```

## Future Enhancements

1. **More Sources**: Add Sina Finance, NetEase Finance
2. **Real-time Streams**: WebSocket connections
3. **Machine Learning**: Predict data availability
4. **API Integration**: Direct exchange APIs
5. **Global Expansion**: International markets

## Resources

- **Source Code**: `scripts/hot_stocks_fetcher.py`
- **Configuration**: `config/data_sources.json`
- **Logs**: `logs/data_sources.log`
- **Cache**: `cache/` directory
- **Tests**: `tests/test_data_sources.py`
