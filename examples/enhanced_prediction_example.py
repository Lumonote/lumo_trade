"""
增强版预测示例 - 集成新的量化模型和数据自动补全功能
展示三个新增量化模型的完整信息和分析能力
"""
import pandas as pd
import matplotlib.pyplot as plt
import sys
import os
from modelscope import snapshot_download
import numpy as np
from datetime import datetime, timedelta

# 添加项目路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from model import Kronos, KronosTokenizer, KronosPredictor
from analysis.technical_analysis import TechnicalAnalysis, QuantitativeModels
from analysis.data_processor import DataProcessor


def enhanced_plot_prediction(kline_df, pred_df, technical_report=None):
    """增强版预测结果可视化，包含技术分析信息"""
    pred_df.index = kline_df.index[-pred_df.shape[0]:]

    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(3, 2, height_ratios=[2, 1, 1], width_ratios=[3, 1])

    # 主价格图
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(kline_df['close'], label='历史价格', color='blue', linewidth=1.5)
    ax1.plot(pred_df['close'], label='预测价格', color='red', linewidth=2, linestyle='--')
    ax1.set_ylabel('股价 (元)', fontsize=12)
    ax1.set_title('Kronos股票预测 + 高级量化分析', fontsize=16, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 成交量图
    ax2 = fig.add_subplot(gs[1, 0], sharex=ax1)
    ax2.plot(kline_df['volume'], label='历史成交量', color='green', alpha=0.7)
    ax2.plot(pred_df['volume'], label='预测成交量', color='orange', alpha=0.8, linestyle='--')
    ax2.set_ylabel('成交量', fontsize=12)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # RSI指标图
    if technical_report and 'technical_indicators' in technical_report:
        ax3 = fig.add_subplot(gs[2, 0], sharex=ax1)
        rsi_data = kline_df.get('rsi', pd.Series([50] * len(kline_df), index=kline_df.index))\n
        ax3.plot(rsi_data, label='RSI', color='purple', linewidth=1.5)
        ax3.axhline(y=70, color='r', linestyle='--', alpha=0.5, label='超买线')\n
        ax3.axhline(y=30, color='g', linestyle='--', alpha=0.5, label='超卖线')\n
        ax3.set_ylabel('RSI', fontsize=12)
        ax3.set_xlabel('时间', fontsize=12)
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        ax3.set_ylim(0, 100)

    # 技术分析摘要
    ax4 = fig.add_subplot(gs[:, 1])
    ax4.axis('off')

    if technical_report:
        summary_text = "📊 技术分析摘要\\n\\n"

        # 技术指标部分
        tech_indicators = technical_report.get('technical_indicators', {})
        summary_text += "🔢 关键指标\\n"
        for key, value in tech_indicators.items():
            summary_text += f"  {key}: {value}\\n"

        summary_text += "\\n🎯 新增高级模型\\n"

        # 显示新增的三个模型信息
        models_perf = technical_report.get('quantitative_models', {})
        current_signals = technical_report.get('current_signals', {})

        advanced_models = [
            'six_dimension_resonance',
            'statistical_quantitative',
            'super_profit_limit_up'
        ]

        for model_key in advanced_models:
            if model_key in models_perf:
                model_info = models_perf[model_key]
                signal = current_signals.get(model_key, '持有')

                # 获取信号emoji
                if signal == '买入':
                    signal_emoji = '🟢'
                elif signal == '卖出':
                    signal_emoji = '🔴'
                else:
                    signal_emoji = '🟡'

                summary_text += f"\\n{model_info.get('中文名称', model_key)}\\n"
                summary_text += f"  胜率: {model_info.get('胜率', 'N/A')}\\n"
                summary_text += f"  适用: {model_info.get('适用人群', 'N/A')}\\n"
                summary_text += f"  策略: {model_info.get('核心策略', 'N/A')}\\n"
                summary_text += f"  信号: {signal_emoji} {signal}\\n"

        # 风险评估
        risk_assessment = technical_report.get('risk_assessment', {})
        summary_text += "\\n⚠️ 风险评估\\n"
        for key, value in risk_assessment.items():
            summary_text += f"  {key}: {value}\\n"

        ax4.text(0.05, 0.95, summary_text, transform=ax4.transAxes,
                 fontsize=10, verticalalignment='top', fontfamily='monospace')

    plt.tight_layout()

    # 保存图表
    results_dir = os.path.join(os.path.dirname(__file__), '..', 'results')
    os.makedirs(results_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'enhanced_prediction_{timestamp}.png'
    filepath = os.path.join(results_dir, filename)

    try:
        plt.savefig(filepath, dpi=300, bbox_inches='tight', facecolor='white')
        print(f"📊 增强版预测图表已保存: {filepath}")
    except Exception as e:
        print(f"❌ 保存图表出错: {e}")

    plt.show()


def print_model_comparison_table(quantitative_models):
    """打印模型对比表格"""
    print("\\n" + "=" * 100)
    print("📈 KRONOS 量化模型全览表".center(100))
    print("=" * 100)

    # 获取所有模型信息
    models_data = []
    current_signals = quantitative_models._get_current_signals()

    for model_key, performance in quantitative_models.models_performance.items():
        model_name = performance.get('中文名称', model_key)
        win_rate = performance.get('胜率', 'N/A')
        target_user = performance.get('适用人群', 'N/A')
        strategy = performance.get('核心策略', 'N/A')
        signal = current_signals.get(model_key, '持有')

        # 信号emoji
        if signal == '买入':
            signal_display = '🟢 买入'
        elif signal == '卖出':
            signal_display = '🔴 卖出'
        else:
            signal_display = '🟡 持有'

        models_data.append({
            'name': model_name,
            'win_rate': win_rate,
            'users': target_user,
            'strategy': strategy,
            'signal': signal_display
        })

    # 按信号类型分组
    buy_models = [m for m in models_data if '买入' in m['signal']]
    sell_models = [m for m in models_data if '卖出' in m['signal']]
    hold_models = [m for m in models_data if '持有' in m['signal']]

    def print_model_group(models, title, emoji):
        if models:
            print(f"\\n{emoji} {title} ({len(models)}/{len(models_data)})")
            print("-" * 100)
            print(f"{'模型名称':<25} {'适用人群':<20} {'核心策略':<35} {'胜率':<10} {'信号':<10}")
            print("-" * 100)

            for model in models:
                # 截断过长的字符串
                name = model['name'][:24] if len(model['name']) > 24 else model['name']
                users = model['users'][:19] if len(model['users']) > 19 else model['users']
                strategy = model['strategy'][:34] if len(model['strategy']) > 34 else model['strategy']

                print(f"{name:<25} {users:<20} {strategy:<35} {model['win_rate']:<10} {model['signal']:<10}")

    # 打印各组模型
    print_model_group(buy_models, "买入信号模型", "🟢")
    print_model_group(sell_models, "卖出信号模型", "🔴")
    print_model_group(hold_models, "持有信号模型", "🟡")

    print("\\n" + "=" * 100)
    print("💡 说明: 以上为基于示例数据的模型测试结果，实际交易请结合市场情况谨慎决策")
    print("=" * 100)


def main():
    """主程序"""
    print("🚀 启动Kronos增强版预测系统...")

    # 1. 初始化数据处理器
    data_processor = DataProcessor()

    # 2. 加载模型 - 使用统一的模型加载方式
    print("📦 正在加载Kronos模型...")
    from pathlib import Path
    import shutil

    model_dir = Path(os.path.join(os.path.dirname(__file__), '..', 'models'))
    model_dir.mkdir(exist_ok=True)

    # 一级目录结构，直接在models下
    tokenizer_dir = model_dir / "Kronos-Tokenizer-base"
    model_dir_path = model_dir / "Kronos-base"

    try:
        # 优先使用本地模型（一级目录结构）
        if tokenizer_dir.exists() and (tokenizer_dir / "config.json").exists():
            print("Found local tokenizer, loading...")
            tokenizer = KronosTokenizer.from_pretrained(str(tokenizer_dir))
        else:
            # 下载并保存到一级目录
            print("Downloading tokenizer...")
            downloaded_path = snapshot_download('northwind9898/Kronos-Tokenizer-base', cache_dir=str(model_dir))
            # 如果下载路径有嵌套结构，将其移动到一级目录
            if "northwind9898" in downloaded_path:
                if not tokenizer_dir.exists():
                    shutil.move(downloaded_path, str(tokenizer_dir))
                downloaded_path = str(tokenizer_dir)
            tokenizer = KronosTokenizer.from_pretrained(downloaded_path)

        if model_dir_path.exists() and (model_dir_path / "config.json").exists():
            print("Found local model, loading...")
            model = Kronos.from_pretrained(str(model_dir_path))
        else:
            # 下载并保存到一级目录
            print("Downloading model...")
            downloaded_path = snapshot_download('northwind9898/Kronos-base', cache_dir=str(model_dir))
            # 如果下载路径有嵌套结构，将其移动到一级目录
            if "northwind9898" in downloaded_path:
                if not model_dir_path.exists():
                    shutil.move(downloaded_path, str(model_dir_path))
                downloaded_path = str(model_dir_path)
            model = Kronos.from_pretrained(downloaded_path)

        predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
        print("✅ 模型加载完成")
    except Exception as e:
        print(f"❌ 模型加载失败: {e}")
        print("This may be due to network issues or model availability.")
        print("Please check your internet connection and try again.")
        return

    # 3. 生成示例数据（模拟真实股票数据）
    print("📊 生成模拟股票数据...")
    np.random.seed(42)
    n_points = 800
    base_price = 28.50

    # 创建更真实的价格走势
    prices = [base_price]
    trend = 0.0001  # 轻微上升趋势

    for i in range(n_points - 1):
        # 加入趋势和随机波动
        random_change = np.random.normal(trend, 0.025)

        # 偶尔加入较大波动（模拟重要事件）
        if np.random.random() < 0.05:  # 5%概率大波动
            random_change += np.random.choice([-0.08, 0.08])  # ±8%的大波动

        new_price = max(prices[-1] * (1 + random_change), 0.1)
        prices.append(new_price)

    # 生成OHLC和成交量数据
    data = []
    base_date = datetime(2023, 1, 3)  # 从工作日开始

    for i, close in enumerate(prices):
        # 跳过周末
        date_offset = i
        while True:
            current_date = base_date + timedelta(days=date_offset)
            if current_date.weekday() < 5:  # 工作日
                break
            date_offset += 1

        # 生成OHLC
        volatility = np.random.uniform(0.01, 0.04)
        high = close * (1 + volatility * np.random.uniform(0.3, 1.0))
        low = close * (1 - volatility * np.random.uniform(0.3, 1.0))
        open_price = low + (high - low) * np.random.uniform(0.2, 0.8)

        # 生成成交量（对数正态分布）
        volume = int(np.random.lognormal(13, 0.8)) * 100  # 基础成交量
        amount = volume * close

        data.append({
            'timestamps': current_date,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
            'amount': amount
        })

    df = pd.DataFrame(data)
    print(f"📈 生成了 {len(df)} 条模拟股票数据")

    # 4. 使用数据处理器进行智能补全和验证
    print("\\n🔧 执行数据智能处理...")
    required_days = 600
    processed_df = data_processor.smart_data_completion(df, required_days, stock_code="000001")
    processed_df = data_processor.format_for_analysis(processed_df)

    # 5. 执行技术分析
    print("\\n📊 执行全套技术分析...")
    quantitative_models = QuantitativeModels(processed_df.copy())
    quantitative_models.run_all_models()

    # 生成分析报告
    technical_report = quantitative_models.generate_analysis_report()

    # 6. 打印模型对比表格
    print_model_comparison_table(quantitative_models)

    # 7. 执行预测
    print("\\n🔮 执行Kronos预测...")
    lookback = 400
    pred_len = 60

    x_df = processed_df.iloc[:lookback][['open', 'high', 'low', 'close', 'volume', 'amount']]
    x_timestamp = processed_df.iloc[:lookback]['timestamps']
    y_timestamp = processed_df.iloc[lookback:lookback + pred_len]['timestamps']

    try:
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=1.0,
            top_p=0.9,
            sample_count=1,
            verbose=True
        )

        print("✅ 预测完成")

        # 8. 生成增强版可视化
        print("\\n📈 生成增强版预测图表...")
        kline_df = processed_df.iloc[:lookback + pred_len].copy()

        # 为历史数据添加技术指标用于可视化
        if len(kline_df) > 20:
            ta = TechnicalAnalysis()
            kline_df['rsi'] = ta.calculate_rsi(kline_df['close'], 14)

        enhanced_plot_prediction(kline_df, pred_df, technical_report)

        print("\\n🎉 增强版预测分析完成!")
        print("\\n📋 报告摘要:")
        print(f"   📊 数据覆盖: {len(processed_df)} 天")
        print(f"   🔮 预测长度: {pred_len} 天")
        print(f"   🎯 量化模型: {len(quantitative_models.models_performance)} 个")
        print(f"   ⚠️  风险等级: {technical_report['risk_assessment']['风险等级']}")

    except Exception as e:
        print(f"❌ 预测过程出错: {e}")


if __name__ == "__main__":
    main()
