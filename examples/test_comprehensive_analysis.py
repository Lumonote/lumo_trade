#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合分析测试脚本 - 测试新添加的基本面、消息面、情绪和事件分析功能
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from analysis.fundamental_data_collector import FundamentalDataCollector
from analysis.news_sentiment_collector import NewsSentimentCollector
from analysis.investor_sentiment import InvestorSentimentAnalyzer
from analysis.event_analyzer import EventAnalyzer
from scripts.html_report_generator import LumoHTMLReportGenerator


def test_comprehensive_analysis(stock_code):
    """
    测试综合分析功能

    Args:
        stock_code: 股票代码
    """
    print(f"\n{'=' * 80}")
    print(f"🚀 开始测试 {stock_code} 的综合分析功能")
    print(f"{'=' * 80}\n")

    # 1. 采集基本面数据
    print("📊 步骤 1/4: 采集基本面财务数据...")
    print("-" * 80)
    fundamental_collector = FundamentalDataCollector(stock_code)
    fundamental_data = fundamental_collector.get_comprehensive_data()
    print(f"✅ 基本面数据采集完成\n")

    # 2. 采集消息面数据
    print("📰 步骤 2/4: 采集消息面数据...")
    print("-" * 80)
    news_collector = NewsSentimentCollector(stock_code)
    news_data = news_collector.get_comprehensive_news()
    print(f"✅ 消息面数据采集完成\n")

    # 3. 分析股民情绪
    print("😊 步骤 3/4: 分析股民情绪...")
    print("-" * 80)
    sentiment_analyzer = InvestorSentimentAnalyzer(stock_code)
    sentiment_data = sentiment_analyzer.get_comprehensive_sentiment()
    print(f"✅ 股民情绪分析完成\n")

    # 4. 分析利好利空事件(传入news_data避免重复采集)
    print("🔍 步骤 4/4: 分析利好利空事件...")
    print("-" * 80)
    event_analyzer = EventAnalyzer(stock_code, news_data=news_data)
    event_data = event_analyzer.get_comprehensive_analysis()
    print(f"✅ 利好利空事件分析完成\n")

    # 5. 生成HTML综合报告
    print("📄 步骤 5/5: 生成HTML综合分析报告...")
    print("-" * 80)

    # 模拟技术分析数据（实际应该从QuantitativeModels获取）
    mock_analysis_data = {
        'technical_indicators': {
            'RSI': '65.23',
            'MACD': '金叉',
            '布林带': '中轨附近',
            'KDJ': 'K:75.3 D:68.2',
            'MA5': '27.85',
            'MA10': '27.52',
            'MA20': '27.15',
        },
        'quantitative_models': {
            'model_1': {'name': '均量双动模型', 'group': '短线交易者', 'strategy': '成交量+均线', 'win_rate': '65%'},
            'model_2': {'name': '多排突破模型', 'group': '趋势跟踪型', 'strategy': '均线多头排列', 'win_rate': '70%'},
        },
        'current_signals': {
            'model_1': '买入',
            'model_2': '持有',
        },
        'risk_assessment': {
            '风险等级': '中等风险',
            '波动率': '2.5%',
            'RSI风险': '正常',
        },
        'model_summary': {
            'buy_count': 1,
            'sell_count': 0,
            'hold_count': 1,
        }
    }

    # 创建报告生成器
    generator = LumoHTMLReportGenerator()

    # 设置控制台数据
    console_data = {
        'data_count': '1,500',
        'prediction_time': '45',
        'prediction_points': '240',
        'data_range': '2025-08-01 至 2025-09-30',
        'mape': '8.56%',
        'risk_level': '中等风险'
    }
    generator.set_console_data(console_data)

    # 生成综合报告
    report_path = generator.generate_comprehensive_report(
        stock_code=stock_code,
        analysis_data=mock_analysis_data,
        historical_data=None,
        predictions=None,
        png_chart_path=None,  # 如果有PNG图表路径可以传入
        fundamental_data=fundamental_data,
        news_data=news_data,
        sentiment_data=sentiment_data,
        event_data=event_data,
        auto_open=True
    )

    print(f"\n{'=' * 80}")
    print(f"✅ 综合分析测试完成!")
    print(f"{'=' * 80}\n")

    print(f"📄 HTML报告路径: {report_path}")
    print(f"\n📊 报告包含以下内容:")
    print(f"   • 💰 基本面财务数据 (PE、PB、财报、股东信息)")
    print(f"   • 📰 消息面分析 (公告、新闻、研报、情感统计)")
    print(f"   • 😊 股民情绪分析 (资金流向、股吧情绪、综合评分)")
    print(f"   • 🔍 利好利空事件 (政策、公司、行业、市场事件)")
    print(f"   • 🤖 量化模型分析")
    print(f"   • 📈 技术指标分析")
    print(f"\n🌐 浏览器已自动打开报告")


if __name__ == "__main__":
    # 测试股票代码
    test_stock_code = "300290"  # 可以修改为其他股票代码

    # 如果命令行提供了股票代码，使用命令行参数
    if len(sys.argv) > 1:
        test_stock_code = sys.argv[1]

    # 运行测试
    test_comprehensive_analysis(test_stock_code)
