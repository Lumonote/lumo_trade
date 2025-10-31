"""
LLM 智能分析集成示例
演示如何在批量分析中集成 LLM 智能预测
"""

import pandas as pd
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from analysis.llm_service import LLMConfig, LLMAnalyzer
from analysis.technical_analysis import TechnicalAnalysis


def format_kline_for_llm(df: pd.DataFrame, last_n=30) -> str:
    """格式化 K 线数据供 LLM 分析"""
    if df.empty:
        return "无K线数据"

    # 取最近N天
    recent_df = df.tail(last_n).copy()

    # 格式化输出
    output = "日期       | 开盘价 | 最高价 | 最低价 | 收盘价 | 涨跌幅\n"
    output += "-" * 60 + "\n"

    for idx, row in recent_df.iterrows():
        date_str = row['timestamps'].strftime('%Y-%m-%d') if 'timestamps' in row else str(idx)
        output += f"{date_str} | {row['open']:.2f} | {row['high']:.2f} | {row['low']:.2f} | {row['close']:.2f}"

        # 计算涨跌幅
        if idx > 0:
            prev_close = recent_df.iloc[idx - 1]['close']
            change_pct = (row['close'] - prev_close) / prev_close * 100
            output += f" | {change_pct:+.2f}%"
        else:
            output += " | --"

        output += "\n"

    return output


def format_technical_for_llm(tech_results: dict) -> str:
    """格式化技术分析结果供 LLM 分析"""
    if not tech_results:
        return "无技术分析数据"

    output = []

    # 均线系统
    if 'ma' in tech_results:
        ma = tech_results['ma']
        output.append(f"均线系统：MA5={ma.get('ma5', 0):.2f}, MA10={ma.get('ma10', 0):.2f}, MA20={ma.get('ma20', 0):.2f}, MA60={ma.get('ma60', 0):.2f}")

    # MACD
    if 'macd' in tech_results:
        macd = tech_results['macd']
        output.append(f"MACD：DIF={macd.get('dif', 0):.4f}, DEA={macd.get('dea', 0):.4f}, 柱={macd.get('histogram', 0):.4f}")

    # RSI
    if 'rsi' in tech_results:
        rsi = tech_results['rsi']
        output.append(f"RSI：RSI6={rsi.get('rsi6', 0):.2f}, RSI12={rsi.get('rsi12', 0):.2f}, RSI24={rsi.get('rsi24', 0):.2f}")

    # KDJ
    if 'kdj' in tech_results:
        kdj = tech_results['kdj']
        output.append(f"KDJ：K={kdj.get('k', 0):.2f}, D={kdj.get('d', 0):.2f}, J={kdj.get('j', 0):.2f}")

    # 布林带
    if 'bollinger' in tech_results:
        boll = tech_results['bollinger']
        output.append(f"布林带：上轨={boll.get('upper', 0):.2f}, 中轨={boll.get('middle', 0):.2f}, 下轨={boll.get('lower', 0):.2f}")

    return "\n".join(output)


def demo_llm_analysis():
    """演示 LLM 分析功能"""
    print("=" * 80)
    print("Kronos LLM 智能分析演示")
    print("=" * 80)

    # 1. 检查 LLM 配置
    llm_config = LLMConfig()
    if not llm_config.is_configured():
        print("\n❌ LLM 未配置")
        print("请先在 GUI 中配置通义千问或 DeepSeek API")
        print("运行：python tools/launchers/kronos_modern_gui.py")
        return

    print(f"\n✅ LLM 已配置：{llm_config.get_enabled_llm()}")

    # 2. 创建分析器
    llm_analyzer = LLMAnalyzer(llm_config)

    # 3. 准备测试数据（示例）
    print("\n准备测试数据...")

    # 模拟 K 线数据
    dates = pd.date_range(end=datetime.now(), periods=30, freq='D')
    kline_data = pd.DataFrame({
        'timestamps': dates,
        'open': [12.0 + i * 0.1 for i in range(30)],
        'high': [12.5 + i * 0.1 for i in range(30)],
        'low': [11.8 + i * 0.1 for i in range(30)],
        'close': [12.3 + i * 0.1 for i in range(30)],
        'volume': [1000000] * 30
    })

    # 计算技术指标
    tech_analyzer = TechnicalAnalysis()
    tech_results = tech_analyzer.calculate_all_indicators(kline_data)

    # 4. 构建分析数据
    stock_data = {
        'code': '600000',
        'name': '浦发银行',
        'current_price': kline_data.iloc[-1]['close'],
        'kline_data': format_kline_for_llm(kline_data),
        'technical_analysis': format_technical_for_llm(tech_results),
        'fundamental_data': "PE=5.2, PB=0.5, ROE=12.5%, 营收增长=8.5%",
        'news_sentiment': "最近无重大消息",
        'market_env': "大盘震荡，金融板块活跃"
    }

    print(f"\n股票：{stock_data['name']}({stock_data['code']})")
    print(f"当前价格：{stock_data['current_price']:.2f}")

    # 5. 调用 LLM 分析
    print("\n正在调用 LLM 进行智能分析...")
    print("（这可能需要几秒钟时间）")

    success, result = llm_analyzer.analyze_stock(stock_data)

    if not success:
        print(f"\n❌ LLM 分析失败：{result}")
        return

    print("\n✅ LLM 分析成功！")

    # 6. 显示分析结果
    print("\n" + "=" * 80)
    print("📊 AI 智能分析结果")
    print("=" * 80)

    # K线预测
    if 'kline_prediction' in result:
        pred = result['kline_prediction']
        print("\n【K线走势预测】")
        print(f"  趋势：{pred.get('trend', '未知')}")
        print(f"  信心度：{pred.get('confidence', 0) * 100:.1f}%")
        print(f"  支撑位：{', '.join(map(str, pred.get('support_levels', [])))}")
        print(f"  压力位：{', '.join(map(str, pred.get('resistance_levels', [])))}")

        predictions = pred.get('predictions', [])
        if predictions:
            print(f"\n  未来{len(predictions)}日预测：")
            for p in predictions[:5]:  # 只显示前5天
                print(f"    Day {p.get('day', 0)}: 开{p.get('open', 0):.2f} "
                      f"高{p.get('high', 0):.2f} 低{p.get('low', 0):.2f} "
                      f"收{p.get('close', 0):.2f} ({p.get('change_pct', 0):+.2f}%)")

    # 操作建议
    if 'operation_advice' in result:
        op = result['operation_advice']
        print("\n【综合操作建议】")
        print(f"  操作：{op.get('action', '未知')}")
        print(f"  建议价位：{op.get('suggested_price_range', '未知')}")
        print(f"  仓位控制：{op.get('position_control', '未知')}")
        print(f"  目标价位：{op.get('target_price', '未知')}")
        print(f"  止损价位：{op.get('stop_loss', '未知')}")
        print(f"  信心度：{op.get('confidence', 0) * 100:.1f}%")

    # 风险评估
    if 'risk_assessment' in result:
        risk = result['risk_assessment']
        print("\n【风险评估】")
        print(f"  风险等级：{risk.get('risk_level', '未知')}")
        print(f"  综合评分：{risk.get('overall_score', 0)}/100")
        risk_points = risk.get('risk_points', [])
        if risk_points:
            print(f"  主要风险：")
            for rp in risk_points:
                print(f"    - {rp}")

    # 操作策略
    if 'strategy' in result:
        strategy = result['strategy']
        print("\n【操作策略】")
        print(f"  短线策略：{strategy.get('short_term', '未知')}")
        print(f"  中线策略：{strategy.get('mid_term', '未知')}")
        print(f"  仓位策略：{strategy.get('position_strategy', '未知')}")

    # 总结
    if 'summary' in result:
        print("\n【综合总结】")
        print(f"  {result['summary']}")

    # 7. 提取预测K线数据
    print("\n" + "=" * 80)
    print("📈 提取预测K线数据")
    print("=" * 80)

    predicted_kline = llm_analyzer.extract_predicted_kline(result)

    if not predicted_kline.empty:
        print(f"\n成功提取 {len(predicted_kline)} 天的预测数据：")
        print(predicted_kline.to_string(index=False))

        print("\n这些数据可以用于：")
        print("  1. 在K线图上绘制AI预测走势")
        print("  2. 与实际走势对比分析准确性")
        print("  3. 生成HTML报告展示预测结果")
    else:
        print("\n⚠️  未能提取预测K线数据")

    print("\n" + "=" * 80)
    print("演示完成！")
    print("=" * 80)


if __name__ == "__main__":
    demo_llm_analysis()
