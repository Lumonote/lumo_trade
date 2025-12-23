# 并发优化功能集成指南

本文档说明如何在现有项目中集成并发优化功能。

---

## 📋 目录

1. [快速集成](#快速集成)
2. [模块说明](#模块说明)
3. [实战示例](#实战示例)
4. [常见问题](#常见问题)

---

## 🚀 快速集成

### 方案1：一行代码启用并发处理

最简单的集成方式 - 替换现有的处理流程：

```python
from analysis.batch_processor import process_stocks_batch_sync

# 原代码:
# for stock in stock_codes:
#     result = analyze_stock(stock)

# 新代码:
stock_codes = ['688343', '000001', '600519']  # 你的股票列表

result_df, details, stats = process_stocks_batch_sync(
    stock_codes,
    data_types=['comprehensive'],
    filter_strategy='balanced',
    max_concurrent=5
)

print(result_df)  # DataFrame格式，包含所有通过过滤的股票
print(stats.to_summary_text())  # 显示处理统计
```

**优势**:
- ✅ 一行代码替换旧流程
- ✅ 性能提升 3-5 倍
- ✅ 自动进度显示
- ✅ 无需修改其他代码

---

### 方案2：生成报告

在并发处理的基础上，生成 HTML 和 Markdown 报告：

```python
from analysis.batch_processor import process_stocks_batch_sync
from analysis.report_generator_v5 import ReportGeneratorV5

# 1. 并发处理
stock_codes = ['688343', '000001', '600519']
result_df, details, stats = process_stocks_batch_sync(stock_codes)

# 2. 生成报告
generator = ReportGeneratorV5(output_dir='results')
html_file = generator.generate_concurrent_report(
    result_df,
    details,
    stats,
    market_environment='沪深300强势，创业板调整'
)

print(f"✅ 报告已生成: {html_file}")
```

---

### 方案3：自定义市场环境权重

配合市场环境分析，自动选择最优权重：

```python
from analysis.batch_processor import process_stocks_batch_sync

# 市场环境数据
market_data = {
    'sentiment': 65,  # 0-100，越高越乐观
    'volatility': 45,  # 0-100，越高波动越大
    'capital_flow': 55  # 0-100，越高表示资金入场
}

# 系统会自动分析市场环境，选择合适的权重方案
result_df, details, stats = process_stocks_batch_sync(
    stock_codes,
    market_data=market_data,  # 传入市场环境数据
    filter_strategy='balanced'
)
```

---

## 🔧 模块说明

### 1. AsyncDataCollector - 异步数据采集

**目的**: 并发采集多支股票的基础数据和新闻情感数据

**基本用法**:
```python
import asyncio
from analysis.async_data_collector import batch_collect_data

async def main():
    # 采集综合数据
    success, failed = await batch_collect_data(
        stock_codes=['688343', '000001'],
        data_type='comprehensive',  # 或 'fundamental'/'sentiment'
        max_concurrent=5,
        timeout_per_stock=30
    )
    
    print(f"✅ 采集成功: {len(success)}")
    print(f"❌ 采集失败: {failed}")

asyncio.run(main())
```

**数据结构**:
```python
{
    'stock_code': '688343',
    'fundamental_data': {...},  # 基础数据
    'sentiment_data': {...},    # 情感数据
    'collected_time': '2025-12-23T10:30:00'
}
```

### 2. AsyncOpportunityScorer - 异步打分系统

**目的**: 并发对多支股票进行评分和过滤

**基本用法**:
```python
import asyncio
from analysis.async_opportunity_scorer import batch_score_stocks

async def main():
    passed, failed, errors = await batch_score_stocks(
        stock_codes=['688343', '000001'],
        filter_strategy='balanced',  # 可选: conservative/aggressive/bottom_hunting
        max_concurrent=5,
        timeout_per_stock=15,
        use_v4_1=True  # 使用市场环境分析版本
    )
    
    print(f"✅ 通过: {len(passed)}")
    print(f"⏭️  未通过: {len(failed)}")
    print(f"❌ 异常: {len(errors)}")

asyncio.run(main())
```

**返回格式**:
```python
# passed: 通过过滤的股票评分结果
{
    '688343': {
        'total_score': 85.5,
        'rating': 'S',
        'recommendation': '强烈推荐',
        'scores': {
            'quantitative': 88.0,
            'technical': 82.0,
            ...
        }
    }
}

# failed: 未通过过滤的股票
{
    '000001': {
        'score': 65.2,
        'rating': 'B',
        'reason': '综合评分不足',
        'full_result': {...}
    }
}
```

### 3. BatchProcessor - 批处理管理器

**目的**: 协调完整的采集-评分-过滤-排序流程

**基本用法**:
```python
from analysis.batch_processor import process_stocks_batch_sync

# 一行代码完成完整流程
result_df, details, stats = process_stocks_batch_sync(
    stock_codes=['688343', '000001', '600519'],
    data_types=['comprehensive'],
    filter_strategy='balanced',
    max_concurrent=5,
    collection_timeout=30,
    scoring_timeout=15
)
```

**统计信息** (`stats`):
```python
stats.to_summary_text()
# 输出:
# ╔════════════════════════════════════════════╗
# ║         批处理执行统计                      ║
# ╚════════════════════════════════════════════╝
#   总处理股票数:     100
#   已完成:          95
#   处理失败:        5
#   
#   数据采集:
#     ✅ 成功:       95
#     ❌ 失败:       5
#     成功率:       95.0%
#     
#   评分过滤:
#     ✅ 通过:       15
#     ❌ 未通过:     80
#     通过率:       15.8%
```

### 4. ReportGeneratorV5 - 报告生成器

**目的**: 生成美观的 HTML 和 Markdown 报告

**基本用法**:
```python
from analysis.report_generator_v5 import ReportGeneratorV5

generator = ReportGeneratorV5(output_dir='results')

html_file = generator.generate_concurrent_report(
    result_df,
    detailed_results,
    stats,
    report_title='投资机会挖掘 - 2025年12月',
    market_environment='沪深300强势运行'
)
```

**生成文件**:
- `opportunity_report_v5_YYYYMMDD_HHMMSS.html` - 可视化报告
- `opportunity_summary_v5_YYYYMMDD_HHMMSS.md` - Markdown摘要

### 5. QuickConfigTuner - 快速配置调整

**目的**: 快速调整打分参数而无需修改代码

**基本用法**:
```python
from analysis.quick_config_tuner import QuickConfigTuner

tuner = QuickConfigTuner()

# 调整单个参数
tuner.adjust_rating_threshold('S', 85)  # S级提高到85分
tuner.adjust_dimension_weight('quantitative', 0.40)  # 量化权重提高到40%

# 应用预设方案
tuner.apply_preset('aggressive')  # 激进模式
# 可选: conservative/balanced/high_volatility/low_volatility

# 保存配置
tuner.save_config('config/my_scoring_config.json')

# 显示当前配置
tuner.print_config()
```

**预设方案**:
- `aggressive` - 降低门槛，强调量化信号
- `conservative` - 提高门槛，强调基本面
- `balanced` - 标准配置
- `high_volatility` - 高波动环境
- `low_volatility` - 低波动环境

---

## 💡 实战示例

### 示例1：每日自动挖掘投资机会

```python
import asyncio
from datetime import datetime
from analysis.batch_processor import process_stocks_batch_sync
from analysis.report_generator_v5 import ReportGeneratorV5

def daily_opportunity_discovery():
    """每日自动挖掘投资机会"""
    
    print(f"🚀 开始每日投资机会挖掘: {datetime.now()}")
    
    # 获取今日热门股票
    hot_stocks = get_hot_stocks_from_api()  # 你的API
    
    # 并发处理
    result_df, details, stats = process_stocks_batch_sync(
        hot_stocks,
        data_types=['comprehensive'],
        filter_strategy='balanced',
        max_concurrent=5
    )
    
    # 生成报告
    if not result_df.empty:
        generator = ReportGeneratorV5()
        generator.generate_concurrent_report(
            result_df,
            details,
            stats,
            market_environment='今日市场环境描述'
        )
        
        # 发送通知
        send_email_notification(result_df)
        print(f"✅ 完成！发现 {len(result_df)} 个机会")
    else:
        print("⚠️  今日未发现合适的机会")

# 定时任务
import schedule
schedule.every().day.at("09:30").do(daily_opportunity_discovery)

while True:
    schedule.run_pending()
```

### 示例2：根据市场环境动态调整策略

```python
from analysis.quick_config_tuner import QuickConfigTuner
from analysis.market_env_analyzer import MarketEnvAnalyzer
from analysis.batch_processor import process_stocks_batch_sync

def adaptive_strategy_discovery():
    """根据市场环境自适应调整策略"""
    
    # 1. 分析当前市场环境
    analyzer = MarketEnvAnalyzer()
    market_data = {
        'sentiment': get_market_sentiment(),
        'volatility': get_market_volatility(),
        'capital_flow': get_capital_flow()
    }
    
    env_name, weights = analyzer.analyze_market_environment(market_data)
    print(f"📊 当前市场环境: {env_name}")
    print(f"📈 推荐权重方案: {weights}")
    
    # 2. 根据环境选择过滤策略
    tuner = QuickConfigTuner()
    if env_name == 'overheated_caution':
        filter_strategy = 'conservative'  # 过热时保守
    elif env_name == 'depressed_opportunity':
        filter_strategy = 'aggressive'  # 低迷时激进
    else:
        filter_strategy = 'balanced'  # 其他情况均衡
    
    # 3. 执行发现流程
    stock_codes = get_stock_candidates()
    
    result_df, details, stats = process_stocks_batch_sync(
        stock_codes,
        market_data=market_data,
        filter_strategy=filter_strategy,
        max_concurrent=5
    )
    
    return result_df, env_name

# 使用
discoveries, market_env = adaptive_strategy_discovery()
print(discoveries)
```

### 示例3：与现有系统集成

```python
# 现有的处理流程
from analysis.opportunity_filter import OpportunityFilter

class InvestmentDiscoverySystem:
    def __init__(self):
        self.old_filter = OpportunityFilter()  # 旧的处理器
    
    def discover_with_concurrency(self, stock_codes):
        """使用并发优化的新流程"""
        
        # 替换旧的逐个处理
        # for stock_code in stock_codes:
        #     result = self.old_filter.analyze(stock_code)
        
        # 使用新的并发处理
        from analysis.batch_processor import process_stocks_batch_sync
        
        result_df, details, stats = process_stocks_batch_sync(
            stock_codes,
            filter_strategy='balanced'
        )
        
        # 转换为旧格式（如需要）
        results = []
        for _, row in result_df.iterrows():
            results.append({
                'stock_code': row['股票代码'],
                'score': row['综合评分'],
                'rating': row['评级'],
                'recommendation': row['建议']
            })
        
        return results
```

---

## ❓ 常见问题

### Q1: 如何处理 API 超时?

**A**: 调整超时参数：

```python
result_df, _, stats = process_stocks_batch_sync(
    stock_codes,
    collection_timeout=40,  # 采集超时增加到40秒
    scoring_timeout=20,     # 评分超时增加到20秒
    max_concurrent=3        # 降低并发数以减少负载
)
```

### Q2: 如何查看详细的处理过程?

**A**: 启用日志：

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

result_df, _, _ = process_stocks_batch_sync(stock_codes)
```

### Q3: 如何只进行数据采集，不进行评分?

**A**: 使用异步采集器直接采集：

```python
from analysis.async_data_collector import collect_batch_data_sync

success_data, failed = collect_batch_data_sync(
    stock_codes=['688343', '000001'],
    data_type='comprehensive',
    max_concurrent=5
)
```

### Q4: 如何修改过滤阈值?

**A**: 使用快速调整工具：

```python
from analysis.quick_config_tuner import QuickConfigTuner

tuner = QuickConfigTuner()

# 方案A：直接调整
tuner.adjust_rating_threshold('A', 60)  # A级阈值改为60

# 方案B：应用预设
tuner.apply_preset('aggressive')

# 方案C：保存为配置文件供持续使用
tuner.save_config('config/my_strategy.json')

# 后续加载
tuner2 = QuickConfigTuner('config/my_strategy.json')
```

### Q5: 如何在现有的网络应用中使用?

**A**: 在后台任务或异步处理中调用：

```python
# Flask 应用
from flask import Flask, jsonify
from analysis.batch_processor import process_stocks_batch_sync

app = Flask(__name__)

@app.route('/discovery', methods=['POST'])
def discovery():
    stock_codes = request.json.get('stocks', [])
    
    result_df, details, stats = process_stocks_batch_sync(
        stock_codes,
        filter_strategy='balanced'
    )
    
    return jsonify({
        'discoveries': result_df.to_dict(orient='records'),
        'statistics': stats.to_dict()
    })
```

### Q6: 可以同时处理多个不同的股票组吗?

**A**: 可以，每个批次处理是独立的：

```python
from analysis.batch_processor import BatchProcessor

processor = BatchProcessor(max_concurrent=5)

# 第一批
result1, _, _ = asyncio.run(processor.process_batch(stocks_group1))

# 第二批
result2, _, _ = asyncio.run(processor.process_batch(stocks_group2))
```

---

## 📞 获取帮助

- 查看测试脚本: `examples/test_concurrent_optimization.py`
- 查看完整文档: `OPTIMIZATION_COMPLETE.md`
- 查看源代码: `analysis/` 目录下各模块

---

**祝集成顺利！🚀**
