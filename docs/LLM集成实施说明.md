# Kronos LLM 智能分析集成说明

## 已完成的功能

### 1. LLM 配置管理
- ✅ 创建 `config/llm_config.json` 配置文件
- ✅ 创建 `analysis/llm_service.py` 服务模块
- ✅ 支持通义千问和 DeepSeek 两个大模型
- ✅ 提供统一的 API 调用接口

### 2. GUI 配置界面
- ✅ 在主界面添加"AI模型配置"功能卡片
- ✅ 创建 `LLMConfigDialog` 配置对话框类
- ✅ 支持启用/禁用开关
- ✅ API Key 配置和测试连接功能
- ✅ 注册说明和文档链接

## 待实现功能

### 3. 集成到批量分析流程

需要修改 `examples/prediction_batch_example.py`：

1. **导入 LLM 服务**
```python
from analysis.llm_service import LLMConfig, LLMAnalyzer
```

2. **在主函数中添加 LLM 分析**
```python
def run_analysis_with_llm(stock_code, kline_data, technical_results, ...):
    """集成 LLM 分析的主函数"""

    # 检查 LLM 是否配置
    llm_config = LLMConfig()
    if llm_config.is_configured():
        llm_analyzer = LLMAnalyzer(llm_config)

        # 构建分析数据
        stock_data = {
            'code': stock_code,
            'name': stock_name,
            'kline_data': format_kline_for_llm(kline_data),
            'technical_analysis': format_technical_for_llm(technical_results),
            'fundamental_data': format_fundamental_for_llm(fundamental_data),
            'news_sentiment': format_news_for_llm(news_data),
            'market_env': format_market_for_llm(market_data)
        }

        # 调用 LLM 分析
        success, llm_result = llm_analyzer.analyze_stock(stock_data)

        if success:
            # 解析 LLM 返回的结果
            llm_analysis = parse_llm_result(llm_result)

            # 提取 K 线预测数据
            predicted_kline = extract_predicted_kline(llm_analysis)

            return llm_analysis, predicted_kline

    return None, None
```

3. **解析 LLM 预测的 K 线数据**

LLM 返回的文本需要解析成结构化数据：
```python
def parse_llm_result(llm_text):
    """解析 LLM 返回的分析文本"""
    result = {
        'prediction': {},      # K线走势预测
        'operation': {},       # 操作建议
        'risk': {},           # 风险提示
        'strategy': {}        # 操作策略
    }

    # 使用正则表达式或 NLP 方法解析文本
    # 提取价格区间、涨跌幅、支撑位、压力位等

    return result

def extract_predicted_kline(llm_analysis):
    """从 LLM 分析中提取 K 线预测数据"""
    prediction = llm_analysis.get('prediction', {})

    # 构建未来 5-10 天的 K 线数据
    predicted_data = []
    for day in range(1, 11):
        predicted_data.append({
            'date': (datetime.now() + timedelta(days=day)).strftime('%Y-%m-%d'),
            'open': prediction.get(f'day{day}_open'),
            'high': prediction.get(f'day{day}_high'),
            'low': prediction.get(f'day{day}_low'),
            'close': prediction.get(f'day{day}_close'),
            'volume': None  # LLM 可能不预测成交量
        })

    return pd.DataFrame(predicted_data)
```

### 4. 集成到投资机会挖掘

修改投资机会挖掘脚本（需要找到对应的文件）：

1. **对 B 级及以上股票进行 LLM 深度分析**
```python
def analyze_passed_stocks(passed_stocks):
    """对通过筛选的股票进行 LLM 深度分析"""
    llm_config = LLMConfig()
    if not llm_config.is_configured():
        print("LLM 未配置，跳过 AI 分析")
        return passed_stocks

    llm_analyzer = LLMAnalyzer(llm_config)

    for stock in passed_stocks:
        if stock['grade'] >= 'B':  # B 级及以上
            # 收集股票数据
            stock_data = collect_stock_data(stock['code'])

            # LLM 分析
            success, llm_result = llm_analyzer.analyze_stock(stock_data)

            if success:
                stock['llm_analysis'] = parse_llm_result(llm_result)
                stock['llm_predicted_kline'] = extract_predicted_kline(stock['llm_analysis'])

    return passed_stocks
```

### 5. 增强 HTML 报表

修改 `scripts/html_report_generator.py` 添加 AI 分析板块：

1. **在报表中添加 "AI 智能分析" 章节**
```html
<section id="ai-analysis" class="section">
    <h2>🤖 AI 智能分析</h2>

    <div class="subsection">
        <h3>📊 K线走势预测</h3>
        <div class="chart-container">
            <!-- 使用 plotly/echarts 绘制包含 AI 预测的 K 线图 -->
            <div id="ai-kline-chart"></div>
        </div>
        <div class="prediction-details">
            <p>预测价格区间：{{ prediction_range }}</p>
            <p>预期涨跌幅：{{ expected_change }}</p>
            <p>关键支撑位：{{ support_levels }}</p>
            <p>关键压力位：{{ resistance_levels }}</p>
        </div>
    </div>

    <div class="subsection">
        <h3>💡 综合操作建议</h3>
        <div class="operation-advice">
            <div class="advice-badge {{ operation_type }}">
                {{ operation_type_text }}  <!-- 买入/持有/卖出 -->
            </div>
            <p>建议价位：{{ suggested_price }}</p>
            <p>仓位控制：{{ position_control }}</p>
        </div>
    </div>

    <div class="subsection">
        <h3>⚠️ 风险提示</h3>
        <div class="risk-warning">
            <p>主要风险点：{{ risk_points }}</p>
            <p>风险等级：{{ risk_level }}</p>
            <p>止损建议：{{ stop_loss }}</p>
        </div>
    </div>

    <div class="subsection">
        <h3>📋 操作策略</h3>
        <div class="strategy-details">
            <p>短线策略：{{ short_term_strategy }}</p>
            <p>中线策略：{{ mid_term_strategy }}</p>
            <p>分批建仓/减仓策略：{{ position_strategy }}</p>
        </div>
    </div>
</section>
```

2. **绘制包含 AI 预测的 K 线图**

使用 plotly 或 echarts 绘制：
```python
def plot_kline_with_ai_prediction(historical_data, ai_predicted_data):
    """绘制包含 AI 预测的 K 线图"""
    import plotly.graph_objects as go

    # 历史 K 线
    historical_trace = go.Candlestick(
        x=historical_data['date'],
        open=historical_data['open'],
        high=historical_data['high'],
        low=historical_data['low'],
        close=historical_data['close'],
        name='历史数据',
        increasing_line_color='red',
        decreasing_line_color='green'
    )

    # AI 预测 K 线（使用不同样式）
    ai_trace = go.Candlestick(
        x=ai_predicted_data['date'],
        open=ai_predicted_data['open'],
        high=ai_predicted_data['high'],
        low=ai_predicted_data['low'],
        close=ai_predicted_data['close'],
        name='AI预测',
        increasing_line_color='#FF6B6B',
        decreasing_line_color='#4ECDC4',
        opacity=0.6
    )

    fig = go.Figure(data=[historical_trace, ai_trace])

    fig.update_layout(
        title='K线走势 + AI预测',
        yaxis_title='价格',
        xaxis_rangeslider_visible=False
    )

    return fig.to_html(include_plotlyjs='cdn')
```

### 6. LLM 提示词优化

为了让 LLM 返回结构化的 K 线预测数据，需要优化提示词：

```python
def _build_analysis_prompt(self, stock_data: Dict) -> str:
    """构建分析提示词 - 要求返回结构化数据"""
    # ... 前面的提示词内容 ...

    prompt += """
## 分析要求
请基于以上信息，给出以下分析（必须按照指定格式输出）：

1. **K线走势预测**（未来5-10个交易日）
   请按以下 JSON 格式输出每日预测：
   ```json
   {
     "predictions": [
       {
         "day": 1,
         "date": "2025-11-01",
         "open": 12.50,
         "high": 13.20,
         "low": 12.30,
         "close": 13.00,
         "change_pct": 4.0
       },
       ...
     ],
     "support_levels": [12.00, 11.50],
     "resistance_levels": [13.50, 14.00]
   }
   ```

2. **综合操作建议**
   ```json
   {
     "operation": "买入",  // 买入/持有/卖出
     "suggested_price": "12.50-12.80",
     "position_control": "半仓",  // 轻仓/半仓/重仓
     "confidence": 0.75
   }
   ```

3. **风险提示**
   ```json
   {
     "risk_points": ["短期超买风险", "板块调整风险"],
     "risk_level": "中",  // 低/中/高
     "stop_loss": "11.50"
   }
   ```

4. **操作策略**
   ```json
   {
     "short_term": "回调至12.50-12.70区间分批买入",
     "mid_term": "目标价位13.50-14.00，分批止盈",
     "position_strategy": "首次3成，回调再加2成，突破再加2成"
   }
   ```

请严格按照以上 JSON 格式输出，方便程序解析和展示。
"""

    return prompt
```

## 实施步骤

1. ✅ 创建 LLM 配置文件和服务模块
2. ✅ 在 GUI 中添加模型配置界面
3. ⏳ 优化 LLM 服务，支持返回结构化数据
4. ⏳ 集成到批量分析流程
5. ⏳ 集成到投资机会挖掘
6. ⏳ 增强 HTML 报表显示 AI 分析结果
7. ⏳ 将 AI 预测的 K 线数据画到 K 线图上

## 技术要点

1. **结构化输出**：使用 JSON 格式要求 LLM 返回结构化数据
2. **数据解析**：使用正则表达式或 JSON 解析提取 LLM 返回的数据
3. **图表绘制**：使用 plotly 或 echarts 绘制包含历史和预测数据的 K 线图
4. **错误处理**：LLM 可能返回格式不规范的数据，需要容错处理
5. **性能优化**：LLM API 调用较慢，考虑异步处理和缓存机制

## 注意事项

1. LLM 的预测结果仅供参考，不构成投资建议
2. 需要在报表中明确标注"AI 预测结果仅供参考"
3. 建议设置 LLM API 调用超时和重试机制
4. 考虑 API 费用，可以设置开关控制是否启用 LLM 分析
