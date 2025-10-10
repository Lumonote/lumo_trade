#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos 快速使用示例
展示如何获取股票数据和运行预测
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def print_header(title):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f"🚀 {title}")
    print("=" * 60)


def print_step(step, description):
    """打印步骤"""
    print(f"\n📋 步骤 {step}: {description}")
    print("-" * 40)


def example_tushare_data():
    """Tushare 数据获取示例"""
    print_header("Tushare 数据获取示例")

    try:
        # 这里应该导入实际的数据获取模块
        # from scripts.fetch_data import MultiSourceDataFetcher

        print_step(1, "初始化 Tushare 数据获取器")
        print("正在初始化数据获取器...")

        # 模拟数据获取过程
        import time
        time.sleep(1)

        print("✅ 数据获取器初始化成功")

        print_step(2, "获取平安银行(000001.SZ)历史数据")
        print("正在获取数据...")

        # 模拟数据
        sample_data = {
            'date': ['2024-01-15', '2024-01-16', '2024-01-17'],
            'open': [10.50, 10.60, 10.55],
            'high': [10.80, 10.75, 10.70],
            'low': [10.40, 10.50, 10.45],
            'close': [10.65, 10.55, 10.60],
            'volume': [1000000, 1200000, 950000]
        }

        time.sleep(2)

        print("✅ 数据获取成功！")
        print("\n📊 数据预览:")
        print(f"日期范围: {sample_data['date'][0]} 到 {sample_data['date'][-1]}")
        print(f"数据条数: {len(sample_data['date'])} 条")
        print(f"最新收盘价: {sample_data['close'][-1]} 元")

        return sample_data

    except Exception as e:
        print(f"❌ Tushare 数据获取失败: {e}")
        print("💡 请检查:")
        print("   1. Tushare Token 是否正确配置")
        print("   2. 网络连接是否正常")
        print("   3. 运行 python scripts/config_wizard.py 重新配置")
        return None


def example_crawler_data():
    """爬虫数据获取示例"""
    print_header("爬虫数据获取示例")

    try:
        print_step(1, "初始化爬虫数据获取器")
        print("正在启动浏览器...")

        import time
        time.sleep(2)

        print("✅ 浏览器启动成功")

        print_step(2, "从多个数据源获取实时数据")

        sources = ['新浪财经', '东方财富', '网易财经']
        for i, source in enumerate(sources, 1):
            print(f"正在从 {source} 获取数据... ({i}/{len(sources)})")
            time.sleep(1)
            print(f"✅ {source} 数据获取成功")

        # 模拟实时数据
        realtime_data = {
            'symbol': '000001',
            'name': '平安银行',
            'current_price': 10.68,
            'change': 0.08,
            'change_percent': 0.75,
            'volume': 15000000,
            'turnover': 160200000,
            'timestamp': '2024-01-17 15:00:00'
        }

        print("\n📊 实时数据:")
        print(f"股票代码: {realtime_data['symbol']}")
        print(f"股票名称: {realtime_data['name']}")
        print(f"当前价格: {realtime_data['current_price']} 元")
        print(f"涨跌幅: {realtime_data['change_percent']:+.2f}%")
        print(f"成交量: {realtime_data['volume']:,} 股")

        return realtime_data

    except Exception as e:
        print(f"❌ 爬虫数据获取失败: {e}")
        print("💡 请检查:")
        print("   1. Playwright 浏览器是否已安装")
        print("   2. 爬虫配置是否正确")
        print("   3. 网络连接是否正常")
        print("   4. 运行 ./quick_start.sh 选择 '8. 安装 Playwright 浏览器'")
        return None


def example_prediction():
    """股票预测示例"""
    print_header("股票预测示例")

    try:
        print_step(1, "加载历史数据")
        print("正在加载平安银行历史数据...")

        import time
        time.sleep(1)

        print("✅ 历史数据加载完成 (30天数据)")

        print_step(2, "训练预测模型")
        print("正在训练机器学习模型...")

        # 模拟训练过程
        for i in range(1, 6):
            print(f"训练进度: {i * 20}%")
            time.sleep(0.5)

        print("✅ 模型训练完成")

        print_step(3, "生成预测结果")
        print("正在生成未来5天预测...")

        # 模拟预测结果
        predictions = {
            '2024-01-18': {'price': 10.72, 'confidence': 0.85},
            '2024-01-19': {'price': 10.68, 'confidence': 0.82},
            '2024-01-22': {'price': 10.75, 'confidence': 0.78},
            '2024-01-23': {'price': 10.80, 'confidence': 0.75},
            '2024-01-24': {'price': 10.77, 'confidence': 0.72}
        }

        time.sleep(1)

        print("✅ 预测完成！")
        print("\n🔮 预测结果:")
        for date, pred in predictions.items():
            confidence_str = f"{pred['confidence'] * 100:.0f}%"
            print(f"{date}: {pred['price']:.2f} 元 (置信度: {confidence_str})")

        print("\n⚠️ 风险提示:")
        print("   股票预测仅供参考，投资有风险，决策需谨慎！")

        return predictions

    except Exception as e:
        print(f"❌ 预测失败: {e}")
        print("💡 请检查:")
        print("   1. 是否有足够的历史数据")
        print("   2. 模型文件是否完整")
        print("   3. 系统依赖是否正确安装")
        return None


def example_batch_operation():
    """批量操作示例"""
    print_header("批量操作示例")

    try:
        print_step(1, "批量获取多只股票数据")

        # 热门股票列表
        popular_stocks = [
            {'code': '000001.SZ', 'name': '平安银行'},
            {'code': '000002.SZ', 'name': '万科A'},
            {'code': '600000.SH', 'name': '浦发银行'},
            {'code': '600036.SH', 'name': '招商银行'},
            {'code': '000858.SZ', 'name': '五粮液'}
        ]

        print(f"正在获取 {len(popular_stocks)} 只热门股票数据...")

        import time
        results = []

        for i, stock in enumerate(popular_stocks, 1):
            print(f"({i}/{len(popular_stocks)}) 获取 {stock['name']} ({stock['code']}) 数据...")
            time.sleep(0.8)

            # 模拟数据获取结果
            result = {
                'code': stock['code'],
                'name': stock['name'],
                'price': round(10 + i * 2.5, 2),
                'change_percent': round((i - 3) * 1.2, 2),
                'status': 'success'
            }
            results.append(result)
            print(f"   ✅ {stock['name']}: {result['price']} 元 ({result['change_percent']:+.2f}%)")

        print_step(2, "生成批量分析报告")

        # 统计分析
        total_stocks = len(results)
        rising_stocks = len([r for r in results if r['change_percent'] > 0])
        falling_stocks = len([r for r in results if r['change_percent'] < 0])

        print("\n📈 市场概况:")
        print(f"总股票数: {total_stocks}")
        print(f"上涨股票: {rising_stocks} 只 ({rising_stocks / total_stocks * 100:.1f}%)")
        print(f"下跌股票: {falling_stocks} 只 ({falling_stocks / total_stocks * 100:.1f}%)")

        # 推荐股票
        best_performer = max(results, key=lambda x: x['change_percent'])
        print(f"\n🏆 今日表现最佳: {best_performer['name']} ({best_performer['change_percent']:+.2f}%)")

        return results

    except Exception as e:
        print(f"❌ 批量操作失败: {e}")
        return None


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("🎉 欢迎使用 Kronos 股票预测系统快速示例！")
    print("=" * 80)
    print("\n本示例将展示 Kronos 的主要功能:")
    print("1. 📊 Tushare 数据获取")
    print("2. 🕷️ 爬虫实时数据")
    print("3. 🔮 股票价格预测")
    print("4. 📈 批量数据分析")

    input("\n按 Enter 键开始演示...")

    # 示例1: Tushare 数据获取
    tushare_data = example_tushare_data()
    input("\n按 Enter 键继续下一个示例...")

    # 示例2: 爬虫数据获取
    crawler_data = example_crawler_data()
    input("\n按 Enter 键继续下一个示例...")

    # 示例3: 股票预测
    predictions = example_prediction()
    input("\n按 Enter 键继续下一个示例...")

    # 示例4: 批量操作
    batch_results = example_batch_operation()

    # 总结
    print_header("演示完成")
    print("🎊 恭喜！您已经了解了 Kronos 的主要功能。")
    print("\n🚀 下一步建议:")
    print("1. 运行 ./quick_start.sh 进行实际配置")
    print("2. 使用配置向导设置您的数据源")
    print("3. 开始获取真实的股票数据")
    print("4. 尝试预测您感兴趣的股票")

    print("\n📚 更多信息:")
    print("- 查看 QUICK_START_GUIDE.md 获取详细使用说明")
    print("- 查看 README.md 了解完整功能")
    print("- 遇到问题请查看常见问题解答")

    print("\n💡 提示: 这只是演示数据，实际使用时会获取真实的股票数据！")
    print("\n👋 感谢使用 Kronos！")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 演示已取消")
    except Exception as e:
        print(f"\n❌ 演示过程中出现错误: {e}")
