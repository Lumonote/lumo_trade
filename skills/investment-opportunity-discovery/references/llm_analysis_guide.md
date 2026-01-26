# LLM Analysis Guide

## Overview

The LLM (Large Language Model) analysis module provides AI-powered deep analysis for high-scoring stocks. It integrates quantitative analysis with natural language understanding to generate actionable investment recommendations.

## Supported LLM Models

### 1. Qwen (Tongyi Qianwen)
- **Provider**: Alibaba Cloud
- **Model**: qwen-plus, qwen-max
- **Strengths**: Chinese language, financial analysis
- **API**: DashScope
- **Cost**: Moderate

### 2. DeepSeek
- **Provider**: DeepSeek AI
- **Model**: deepseek-chat, deepseek-coder
- **Strengths**: Logical reasoning, numerical analysis
- **API**: Direct API
- **Cost**: Low

## LLM Analysis Triggers

### Automatic Selection Criteria
- **Minimum Score**: 60+ points (B grade or higher)
- **Top Selection**: Top 10 by score
- **Enable Flag**: `--enable-llm` (default: true)

### Manual Override
```bash
# Force LLM analysis for all stocks
python scripts/discover_opportunities.py --force-llm

# Analyze specific stock with LLM
python scripts/analyze_single_stock.py --code 600977
```

## LLM Analysis Process

### Step 1: Data Preparation

The system prepares comprehensive data for LLM analysis:

```python
{
    "code": "600977",
    "name": "Example Stock",
    "current_price": 45.67,
    "technical_analysis": {
        "RSI": 65.4,
        "MACD": "Golden Cross",
        "MA5": 44.2,
        "MA20": 43.8,
        "bollinger_position": "Upper Band"
    },
    "quantitative_models": {
        "buy_signals": 18,
        "sell_signals": 4,
        "buy_ratio": 0.75,
        "top_models": ["MACD Golden Cross", "Volume Breakout"]
    },
    "fundamental_data": {
        "pe_ratio": 22.5,
        "pb_ratio": 2.1,
        "revenue_growth": 0.15,
        "profit_growth": 0.18
    },
    "sentiment_data": {
        "market_sentiment": "Bullish",
        "forum_sentiment": "Positive",
        "confidence": 0.72
    },
    "sector_data": {
        "sector_name": "Technology",
        "sector_performance": "Outperforming",
        "relative_strength": 0.85
    },
    "overall_rating": "Score: 78.5, Rating: B+"
}
```

### Step 2: Prompt Engineering

The system constructs a detailed prompt:

```
You are an expert financial analyst. Analyze the following stock data:

Stock: {name} ({code})
Current Price: {current_price}

Technical Analysis:
{technical_analysis}

Quantitative Models:
{quantitative_models}

Fundamental Data:
{fundamental_data}

Sentiment Analysis:
{sentiment_data}

Sector Analysis:
{sector_data}

Overall Rating: {overall_rating}

Provide comprehensive analysis including:
1. Investment recommendation (Buy/Hold/Sell)
2. Risk assessment (High/Medium/Low)
3. Price prediction (target price, timeframe)
4. Key catalysts and risks
5. Position sizing recommendation
6. Confidence level (0-100%)
```

### Step 3: LLM Processing

- **Timeout**: 30 seconds per stock
- **Retry Logic**: Up to 2 retries on failure
- **Concurrency**: 2-5 parallel requests (configurable)
- **Rate Limiting**: Respect API limits

### Step 4: Result Parsing

The system parses LLM responses into structured data:

```python
{
    "operation_advice": {
        "action": "Buy",
        "position_control": "Medium (30%)",
        "target_price": 52.00,
        "stop_loss": 42.00,
        "timeframe": "3-6 months",
        "confidence": 0.78
    },
    "risk_assessment": {
        "risk_level": "Medium",
        "overall_score": 65,
        "risk_points": [
            "Sector volatility",
            "Valuation stretch",
            "Market sentiment dependency"
        ],
        "mitigation": [
            "Use stop-loss",
            "Diversify holdings",
            "Monitor earnings"
        ]
    },
    "kline_prediction": {
        "trend": "Upward",
        "confidence": 0.75,
        "support_levels": [43.50, 41.00],
        "resistance_levels": [48.00, 52.00],
        "prediction_days": 30
    },
    "catalysts": {
        "positive": [
            "Strong quarterly earnings",
            "New product launch",
            "Analyst upgrade"
        ],
        "negative": [
            "Market uncertainty",
            "Regulatory changes"
        ]
    },
    "strategy": {
        "short_term": "Buy on pullbacks to MA20",
        "medium_term": "Hold for earnings growth",
        "long_term": "Monitor sector rotation"
    },
    "summary": "Stock shows strong technical and fundamental signals..."
}
```

## LLM Output Structure

### 1. Operation Advice

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| action | string | Buy/Hold/Sell recommendation | "Buy" |
| position_control | string | Position size recommendation | "Medium (30%)" |
| target_price | float | Price target | 52.00 |
| stop_loss | float | Stop-loss price | 42.00 |
| timeframe | string | Investment horizon | "3-6 months" |
| confidence | float | Confidence level (0-1) | 0.78 |

### 2. Risk Assessment

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| risk_level | string | High/Medium/Low | "Medium" |
| overall_score | int | Risk score (0-100) | 65 |
| risk_points | list | Key risk factors | ["Volatility", "Valuation"] |
| mitigation | list | Risk mitigation strategies | ["Stop-loss", "Diversify"] |

### 3. K-Line Prediction

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| trend | string | Upward/Downward/Sideways | "Upward" |
| confidence | float | Prediction confidence (0-1) | 0.75 |
| support_levels | list | Support price levels | [43.50, 41.00] |
| resistance_levels | list | Resistance price levels | [48.00, 52.00] |
| prediction_days | int | Forecast period | 30 |

### 4. Catalysts

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| positive | list | Positive catalysts | ["Earnings beat", "Product launch"] |
| negative | list | Negative catalysts | ["Regulatory risk", "Competition"] |

### 5. Strategy

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| short_term | string | 1-3 month strategy | "Buy on pullbacks" |
| medium_term | string | 3-12 month strategy | "Hold for growth" |
| long_term | string | 1+ year strategy | "Monitor rotation" |

### 6. Summary

- **Type**: string
- **Description**: Comprehensive analysis summary
- **Length**: 200-500 words

## LLM Configuration

### Environment Variables

```bash
# Qwen Configuration
export QWEN_API_KEY="your-api-key"
export QWEN_MODEL="qwen-plus"
export QWEN_GROUP_ID="your-group-id"

# DeepSeek Configuration
export DEEPSEEK_API_KEY="your-api-key"
export DEEPSEEK_MODEL="deepseek-chat"

# General Settings
export LLM_TIMEOUT=30
export LLM_MAX_RETRIES=2
export LLM_MAX_CONCURRENT=5
```

### Config File (`assets/config/default_config.json`)

```json
{
  "llm": {
    "enabled": true,
    "preferred_models": ["qwen", "deepseek"],
    "timeout": 30,
    "max_retries": 2,
    "max_concurrent": 5,
    "min_score_for_llm": 60,
    "max_stocks_for_llm": 10,
    "output_format": "structured",
    "include_predictions": true,
    "include_risk_analysis": true
  }
}
```

### GUI Configuration

Access LLM settings via web GUI:
```
Settings → LLM Analysis → Configure
```

## LLM Model Comparison

| Feature | Qwen | DeepSeek |
|---------|------|----------|
| Chinese Language | Excellent | Good |
| Financial Analysis | Excellent | Very Good |
| Numerical Reasoning | Good | Excellent |
| API Reliability | High | High |
| Cost | Moderate | Low |
| Speed | Medium | Fast |
| Concurrency | Good | Excellent |

## LLM Analysis Quality

### Quality Metrics

1. **Accuracy**: Alignment with actual performance
2. **Precision**: Specificity of recommendations
3. **Recall**: Coverage of important factors
4. **Coherence**: Logical consistency
5. **Actionability**: Practical usability

### Quality Assurance

- **Input Validation**: Check data completeness
- **Output Validation**: Verify response format
- **Sanity Checks**: Ensure reasonable ranges
- **Consistency Checks**: Cross-validate predictions

### Example Validation Rules

```python
# Price target should be within ±50% of current price
assert abs(target_price - current_price) / current_price <= 0.5

# Confidence should be between 0 and 1
assert 0 <= confidence <= 1

# Stop-loss should be below current price for long positions
if action == "Buy":
    assert stop_loss < current_price
```

## Best Practices

### 1. Data Quality
- Ensure all input data is complete
- Validate numerical ranges
- Remove outliers before analysis
- Use recent data (< 1 day old)

### 2. Prompt Optimization
- Provide context clearly
- Include all relevant dimensions
- Use consistent formatting
- Specify output requirements

### 3. Result Interpretation
- Cross-check with quantitative scores
- Consider LLM confidence levels
- Validate predictions logically
- Monitor actual vs predicted outcomes

### 4. Error Handling
- Implement retry logic
- Handle timeouts gracefully
- Provide fallback options
- Log all errors for review

### 5. Performance Optimization
- Use appropriate concurrency levels
- Cache results when possible
- Batch requests efficiently
- Monitor API usage and costs

## Troubleshooting

### Issue: LLM Analysis Fails

**Symptoms**: No LLM results for stocks

**Possible Causes**:
1. LLM not configured
2. API key invalid
3. Network timeout
4. Rate limit exceeded
5. Insufficient credits

**Solutions**:
```bash
# Check LLM configuration
python -c "from analysis.llm_service import LLMConfig; c=LLMConfig(); print(c.is_configured())"

# Verify API keys
echo $QWEN_API_KEY
echo $DEEPSEEK_API_KEY

# Check logs
tail -f logs/opportunity_discovery.log
```

### Issue: Poor LLM Quality

**Symptoms**: Generic or irrelevant analysis

**Solutions**:
1. Improve input data quality
2. Optimize prompts
3. Switch LLM model
4. Adjust confidence thresholds
5. Add validation rules

### Issue: Slow Performance

**Symptoms**: Long analysis times

**Solutions**:
1. Reduce concurrent requests
2. Lower timeout values
3. Use faster models
4. Enable caching
5. Optimize network settings

### Issue: High Costs

**Symptoms**: Excessive API charges

**Solutions**:
1. Reduce LLM analysis frequency
2. Lower max stocks for LLM
3. Use cheaper models
4. Implement rate limiting
5. Monitor usage closely

## Cost Optimization

### Strategies

1. **Selective Analysis**: Only analyze top stocks (score ≥70)
2. **Batch Processing**: Process multiple stocks together
3. **Caching**: Cache LLM results for 24 hours
4. **Model Selection**: Use cost-effective models
5. **Request Optimization**: Minimize prompt length

### Cost Estimation

| Model | Cost per Request | 10 Stocks | 100 Stocks |
|-------|-----------------|-----------|------------|
| Qwen | $0.02 | $0.20 | $2.00 |
| DeepSeek | $0.01 | $0.10 | $1.00 |

### Budget Controls

```bash
# Set daily budget limit
export LLM_DAILY_BUDGET=10.00

# Monitor usage
python scripts/monitor_llm_usage.py
```

## Advanced Features

### 1. Multi-Model Aggregation

Combine results from multiple LLMs:

```python
{
    "qwen_analysis": {...},
    "deepseek_analysis": {...},
    "aggregated": {
        "action": "Buy",
        "confidence": 0.82,
        "vote_count": {"buy": 2, "hold": 0, "sell": 0}
    }
}
```

### 2. Historical Validation

Track LLM prediction accuracy:

```python
{
    "predictions": [
        {
            "stock_code": "600977",
            "predicted_price": 52.00,
            "actual_price": 51.50,
            "accuracy": 0.99
        }
    ],
    "overall_accuracy": 0.76
}
```

### 3. Custom Prompts

Create domain-specific prompts:

```python
custom_prompt = """
Analyze this growth stock for technology sector:
{fundamental_data}

Focus on:
1. Growth sustainability
2. Competitive position
3. Valuation metrics
4. Market opportunity
"""
```

## Future Enhancements

1. **Fine-tuned Models**: Custom models for financial analysis
2. **Real-time Updates**: Live LLM analysis during trading
3. **Portfolio Optimization**: LLM-based portfolio construction
4. **Risk Modeling**: Advanced risk assessment
5. **Sentiment Analysis**: News and social media integration

## Resources

- **Documentation**: `references/llm_api_docs.md`
- **Examples**: `examples/llm_analysis_examples.py`
- **Benchmarks**: `benchmarks/llm_performance.json`
- **FAQ**: `faq/llm_analysis_faq.md`
