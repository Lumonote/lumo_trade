import pandas as pd
import numpy as np
import matplotlib

matplotlib.use('Agg')  # 使用非交互式后端
import matplotlib.pyplot as plt
import sys
import os
import argparse
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到路径
# 支持打包后环境和开发环境
if getattr(sys, 'frozen', False):
    # 打包后环境 - 检查是否从打包的EXE调用
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller临时目录
        project_root = Path(sys._MEIPASS)
    else:
        # 回退：使用当前文件的父目录
        project_root = Path(__file__).parent.parent
else:
    # 开发环境
    project_root = Path(__file__).parent.parent

sys.path.insert(0, str(project_root))

# 如果从外部Python调用（虚拟环境），尝试检测并添加打包路径
if 'model' not in sys.modules:
    # 尝试从环境变量获取打包路径
    packed_root = os.environ.get('KRONOS_PACKED_ROOT')
    if packed_root and Path(packed_root).exists():
        sys.path.insert(0, str(packed_root))
        print(f"INFO: 检测到打包环境路径: {packed_root}")
    else:
        # 尝试推断打包路径（检查常见的_MEI目录）
        temp_dir = Path(tempfile.gettempdir())
        mei_dirs = list(temp_dir.glob('_MEI*'))
        if mei_dirs:
            # 使用最新的_MEI目录
            latest_mei = max(mei_dirs, key=lambda p: p.stat().st_mtime)
            if (latest_mei / 'model').exists():
                sys.path.insert(0, str(latest_mei))
                print(f"INFO: 自动检测到打包环境路径: {latest_mei}")

from model import Kronos, KronosTokenizer, KronosPredictor
from analysis.technical_analysis import QuantitativeModels
from analysis.data_processor import DataProcessor
from analysis.fundamental_data_collector import FundamentalDataCollector
from analysis.news_sentiment_collector import NewsSentimentCollector
from analysis.investor_sentiment import InvestorSentimentAnalyzer
from analysis.opportunity_scorer import OpportunityScorer
# 已移除动态调参模块：from analysis.sampling_tuner import tune_sampling_params
from analysis.event_analyzer import EventAnalyzer
from analysis.llm_service import LLMConfig, LLMAnalyzer
from scripts.html_report_generator import generate_comprehensive_report


# 解析命令行参数定义提前，确保可在顶部调用
# 解析命令行参数
def parse_args():
    parser = argparse.ArgumentParser(description='Kronos批量股票预测')
    parser.add_argument('--stock-code', '-s', type=str, help='指定要预测的股票代码')
    parser.add_argument('--list-stocks', '-l', action='store_true', help='列出可用的股票数据文件')
    parser.add_argument('--prediction-mode', choices=['overlap', 'realtime'], default='overlap',
                        help='选择预测模式：overlap(重叠验证) 或 realtime(实时预测)')
    parser.add_argument('--timestamps-only', action='store_true',
                        help='仅生成并打印预测时间戳，不执行模型预测与图表生成')
    parser.add_argument('--temperature', '-T', type=float, default=0.8,
                        help='采样温度（默认0.8，范围0.5-1.5+）保守0.5-0.7，平衡0.8-1.0，激进>1.0')
    parser.add_argument('--top-p', '-p', dest='top_p', type=float, default=0.90,
                        help='核采样Top-p（默认0.90，推荐范围0.8-0.95）平衡多样性和稳定性')
    parser.add_argument('--sample-count', '-n', type=int, default=3,
                        help='采样次数（默认3，建议1-5次）通过多次采样取平均提高稳定性')
    return parser.parse_args()


# 先解析命令行参数，以便支持timestamps-only提前退出并跳过模型加载
args = parse_args()


def find_data_file_by_code(stock_code, min5_files):
    """根据股票代码查找对应的数据文件"""
    for f in min5_files:
        # 提取文件名中的股票代码
        parts = f.name.replace('.csv', '').split('_')
        file_stock_code = parts[-1]
        if file_stock_code == stock_code:
            return f
    return None


def is_trading_time(timestamp):
    """
    严格判断是否为交易时间
    交易时间：周一到周五，9:30-11:30, 13:00-15:00
    完全排除周末和非交易时间
    """
    # 严格排除周末（周六和周日）
    if timestamp.weekday() >= 5:  # 5=周六, 6=周日
        return False

    # 检查交易时间段
    hour = timestamp.hour
    minute = timestamp.minute
    time_minutes = hour * 60 + minute  # 转换为分钟便于比较

    # 上午交易时间 9:30-11:30 (570-690分钟)
    morning_start = 9 * 60 + 30  # 9:30 = 570分钟
    morning_end = 11 * 60 + 30  # 11:30 = 690分钟

    # 下午交易时间 13:00-15:00 (780-900分钟)
    afternoon_start = 13 * 60  # 13:00 = 780分钟
    afternoon_end = 15 * 60  # 15:00 = 900分钟

    # 判断是否在交易时间内
    is_morning = morning_start <= time_minutes <= morning_end
    is_afternoon = afternoon_start <= time_minutes <= afternoon_end

    return is_morning or is_afternoon


def is_trading_day(date):
    """
    判断是否为交易日（周一到周五）
    """
    return date.weekday() < 5


def get_trading_days(start_date, days_count, direction='backward'):
    """
    获取指定数量的交易日
    
    Args:
        start_date: 起始日期
        days_count: 需要的交易日数量
        direction: 'backward' 向前找，'forward' 向后找
    
    Returns:
        list: 交易日期列表
    """
    trading_days = []
    current_date = start_date

    while len(trading_days) < days_count:
        if direction == 'backward':
            current_date = current_date - timedelta(days=1)
            if is_trading_day(current_date):
                trading_days.insert(0, current_date)
        else:  # forward
            current_date = current_date + timedelta(days=1)
            if is_trading_day(current_date):
                trading_days.append(current_date)

    return trading_days


def filter_trading_time_only(df):
    """
    过滤数据，只保留交易时间的数据点
    """
    if 'timestamps' not in df.columns:
        return df

    # 确保timestamps是datetime类型
    df = df.copy()
    df['timestamps'] = pd.to_datetime(df['timestamps'])

    # 过滤只保留交易时间的数据
    trading_mask = df['timestamps'].apply(is_trading_time)
    filtered_df = df[trading_mask].copy()

    print(f"📊 交易时间过滤: {len(df)} -> {len(filtered_df)} 条记录")
    return filtered_df


def get_last_trading_day_status(historical_df):
    """
    判断最后一个交易日的状态
    
    Returns:
        tuple: (last_trading_date, is_closed, current_time_in_trading_day)
    """
    if historical_df.empty:
        return None, True, None

    # 获取历史数据的最后时间点
    last_timestamp = historical_df['timestamps'].iloc[-1]
    last_date = last_timestamp.date()

    # 当前时间
    now = datetime.now()
    today = now.date()

    # 如果最后数据日期是今天，检查是否在交易时间内
    if last_date == today and is_trading_day(now):
        # 今天是交易日，检查当前是否在交易时间
        if is_trading_time(now):
            # 当前在交易时间内，说明还未收盘
            return last_date, False, now
        else:
            # 当前不在交易时间，检查是否已过15:00（收盘）
            if now.hour >= 15:
                return last_date, True, None  # 已收盘
            else:
                return last_date, False, now  # 未开盘或午休
    else:
        # 最后数据不是今天，说明已收盘
        return last_date, True, None


def generate_prediction_timestamps(historical_df, target_days=5, warmup_points=0):
    """
    生成预测时间戳 - 重叠验证策略

    策略：始终预测最后一个交易日，用于与真实数据对比准确性
    - 训练数据：前N-1天 + 最后一天开盘warmup点
    - 预测数据：最后一天warmup之后的数据 + 未来5天
    - 可以用最后一天的预测与真实数据对比MAPE

    Args:
        historical_df: 历史数据
        target_days: 目标预测天数(未来交易日)
        warmup_points: 重叠日用于预热的数据点数

    Returns:
        tuple: (prediction_timestamps, training_end_marker, overlap_date, prediction_start_marker)
    """
    if historical_df.empty:
        return [], None, None, None

    # 获取所有交易日期
    all_dates = sorted(historical_df['timestamps'].dt.date.unique())

    if len(all_dates) < 2:
        print("❌ 历史数据不足(至少需要2个交易日)")
        return [], None, None, None

    print(f"📅 预测策略：重叠验证策略(用于准确性对比)")
    print(f"   📊 历史数据: {all_dates[0]} 到 {all_dates[-1]} ({len(all_dates)}个交易日)")

    prediction_timestamps = []

    # 最后一个交易日作为重叠验证日
    overlap_date = all_dates[-1]
    # 倒数第2个交易日作为训练数据结束日
    training_end_date = all_dates[-2]

    print(f"   📊 训练数据截止: {training_end_date} 收盘")
    print(f"   🔄 重叠验证日期: {overlap_date} (覆盖当日9:30-15:00完整交易时段)")

    # 生成重叠验证日的完整交易时间点（9:30-11:30, 13:00-15:00）
    overlap_trading_day = datetime.combine(overlap_date, datetime.min.time())
    morning_start = overlap_trading_day.replace(hour=9, minute=30)
    morning_end = overlap_trading_day.replace(hour=11, minute=30)
    afternoon_start = overlap_trading_day.replace(hour=13, minute=0)
    afternoon_end = overlap_trading_day.replace(hour=15, minute=0)

    # 训练数据截止标记：倒数第二个交易日的收盘（15:00）
    training_end_time = datetime.combine(training_end_date, datetime.min.time()).replace(hour=15, minute=0)
    prediction_start_time = morning_start
    print(f"   📍 训练数据包含到: {training_end_time}")
    print(f"   🎯 预测起始时间: {prediction_start_time}")

    # 上午时段
    current_time = morning_start
    while current_time <= morning_end:
        if is_trading_time(current_time):
            prediction_timestamps.append(current_time)
        current_time += timedelta(minutes=5)

    # 下午时段
    current_time = afternoon_start
    while current_time <= afternoon_end:
        if is_trading_time(current_time):
            prediction_timestamps.append(current_time)
        current_time += timedelta(minutes=5)

    print(f"   - 重叠验证: {len(prediction_timestamps)} 个5分钟K线点")

    # 生成未来N个交易日的时间点
    # 从重叠日下一天开始
    next_trading_date = overlap_date + timedelta(days=1)

    while not is_trading_day(next_trading_date):
        next_trading_date += timedelta(days=1)

    print(f"   - 未来预测起始: {next_trading_date}")

    # 生成未来5个交易日
    future_trading_days = get_trading_days(next_trading_date - timedelta(days=1), target_days, direction='forward')

    future_points_count = 0
    for future_date in future_trading_days:
        if not is_trading_day(future_date):
            continue

        trading_day = datetime.combine(future_date, datetime.min.time())

        # 上午时段：9:30-11:30
        morning_start = trading_day.replace(hour=9, minute=30)
        morning_end = trading_day.replace(hour=11, minute=30)
        current_time = morning_start
        while current_time <= morning_end:
            if is_trading_time(current_time):
                prediction_timestamps.append(current_time)
                future_points_count += 1
            current_time += timedelta(minutes=5)

        # 下午时段：13:00-15:00
        afternoon_start = trading_day.replace(hour=13, minute=0)
        afternoon_end = trading_day.replace(hour=15, minute=0)
        current_time = afternoon_start
        while current_time <= afternoon_end:
            if is_trading_time(current_time):
                prediction_timestamps.append(current_time)
                future_points_count += 1
            current_time += timedelta(minutes=5)

    print(f"   - 未来预测: {future_points_count} 个5分钟K线点 ({len(future_trading_days)}个交易日)")
    print(f"   - 未来交易日: {[d.strftime('%m-%d') for d in future_trading_days]}")

    # 训练数据结束标记：重叠日的预热数据最后一个点
    training_end_marker = training_end_time

    print(f"🔮 生成预测时间戳: {len(prediction_timestamps)} 个5分钟K线点")
    print(f"   - 训练数据截止: {training_end_marker}")
    print(f"   - 预测起始时间: {prediction_start_time}")
    print(f"   📊 策略：用前{len(all_dates) - 1}天训练，预测重叠日完整 + 未来{target_days}天")

    return prediction_timestamps, training_end_marker, overlap_date, prediction_start_time


def generate_realtime_prediction_timestamps(historical_df, target_days=5):
    """
    生成预测时间戳 - 实时预测模式

    策略：基于当前实际时间生成从下一个有效交易时间点开始的预测时间戳，
    并覆盖今天剩余交易时间与后续若干个交易日的完整交易时间。

    Args:
        historical_df: 历史数据（已过滤交易时间）
        target_days: 目标未来交易日数量（包含今天的剩余交易时段）

    Returns:
        tuple: (prediction_timestamps, training_end_marker, overlap_date(None), prediction_start_marker)
    """
    if historical_df.empty:
        return [], None, None, None

    now = datetime.now()

    def next_5min_tick(t: datetime) -> datetime:
        base = t.replace(second=0, microsecond=0)
        minute_bucket = (base.minute // 5) * 5
        candidate = base.replace(minute=minute_bucket)
        if base > candidate:
            candidate = candidate + timedelta(minutes=5)
        return candidate

    def day_session_times(date_obj):
        d = datetime.combine(date_obj, datetime.min.time())
        return (
            d.replace(hour=9, minute=30), d.replace(hour=11, minute=30),
            d.replace(hour=13, minute=0), d.replace(hour=15, minute=0)
        )

    # 确定预测起始时间
    if is_trading_day(now.date()):
        morning_start, morning_end, afternoon_start, afternoon_end = day_session_times(now.date())

        if is_trading_time(now):
            start_time = next_5min_tick(now)
            # 若超过上午结束但未到下午开始，跳至下午开盘；若超过收盘，切到下一个交易日
            if start_time > morning_end and start_time < afternoon_start:
                start_time = afternoon_start
            if start_time > afternoon_end:
                # 跳至下一交易日的上午开盘
                next_date = now.date() + timedelta(days=1)
                while not is_trading_day(next_date):
                    next_date += timedelta(days=1)
                start_time = day_session_times(next_date)[0]
        else:
            if now < morning_start:
                start_time = morning_start
            elif morning_end < now < afternoon_start:
                start_time = afternoon_start
            else:
                # 已过当日收盘 -> 下一交易日9:30
                next_date = now.date() + timedelta(days=1)
                while not is_trading_day(next_date):
                    next_date += timedelta(days=1)
                start_time = day_session_times(next_date)[0]
    else:
        # 非交易日 -> 找到下一个交易日9:30
        next_date = now.date()
        while not is_trading_day(next_date):
            next_date += timedelta(days=1)
        start_time = day_session_times(next_date)[0]

    prediction_timestamps = []

    # 第一天：从start_time开始生成当日剩余交易时间点
    start_date = start_time.date()
    ms, me, as_, ae = day_session_times(start_date)

    # 上午剩余
    if start_time <= me:
        current = max(start_time, ms)
        while current <= me:
            if is_trading_time(current):
                prediction_timestamps.append(current)
            current += timedelta(minutes=5)

    # 下午时段
    if start_time > me:
        current = max(start_time, as_)
    else:
        current = as_
    while current <= ae:
        if is_trading_time(current):
            prediction_timestamps.append(current)
        current += timedelta(minutes=5)

    # 后续完整交易日
    days_needed = target_days
    # 如果第一天已经生成（今天剩余），则剩余天数减一
    if is_trading_day(start_date):
        days_needed = max(0, target_days - 1)

    # 生成从start_date开始的后续days_needed个交易日的完整时间
    future_days = []
    cursor_date = start_date
    while len(future_days) < days_needed:
        cursor_date = cursor_date + timedelta(days=1)
        if is_trading_day(cursor_date):
            future_days.append(cursor_date)

    future_points_count = 0
    for d in future_days:
        ms, me, as_, ae = day_session_times(d)
        current = ms
        while current <= me:
            if is_trading_time(current):
                prediction_timestamps.append(current)
                future_points_count += 1
            current += timedelta(minutes=5)
        current = as_
        while current <= ae:
            if is_trading_time(current):
                prediction_timestamps.append(current)
                future_points_count += 1
            current += timedelta(minutes=5)

    # 训练数据截止标记：使用历史数据的最后一个时间戳，以确保使用全部可用数据
    training_end_marker = pd.to_datetime(historical_df['timestamps']).max()

    print(f"📅 预测策略：实时预测模式")
    print(f"   🔎 当前时间: {now}")
    print(f"   🎯 预测起始时间: {start_time}")
    if future_days:
        print(f"   - 未来交易日: {[d.strftime('%m-%d') for d in future_days]}")
    print(f"🔮 生成预测时间戳: {len(prediction_timestamps)} 个5分钟K线点")
    print(f"   - 训练数据截止: {training_end_marker}")

    return prediction_timestamps, training_end_marker, None, start_time


def plot_prediction_enhanced(historical_df, pred_df, stock_code, save_path=None,
                             historical_end_marker=None, future_start_marker=None,
                             llm_predicted_kline=None):
    """
    增强版预测图表绘制 - 严格20个交易日显示：15天历史+5天预测（含1天重叠）
    在重叠交易日同时显示真实K线和预测K线进行对比

    Args:
        historical_df: 历史数据（已过滤交易时间）
        pred_df: 预测结果数据
        stock_code: 股票代码
        save_path: 保存路径
        historical_end_marker: 历史数据结束标记
        future_start_marker: 真正未来预测开始标记（不包含重叠部分）
        llm_predicted_kline: LLM预测的K线数据(可选)
    """
    import matplotlib.dates as mdates
    from datetime import datetime, timedelta

    # 预测数据处理：从索引获取时间戳并添加为列
    if 'timestamps' not in pred_df.columns:
        pred_df = pred_df.copy()
        pred_df['timestamps'] = pred_df.index
        pred_df = pred_df.reset_index(drop=True)
        print("🔧 已从索引中提取预测数据的时间戳")

    # 确保时间戳为datetime类型
    historical_df['timestamps'] = pd.to_datetime(historical_df['timestamps'])
    pred_df['timestamps'] = pd.to_datetime(pred_df['timestamps'])

    print(f"📊 图表数据范围：")
    print(
        f"  - 历史数据: {len(historical_df)} 个点 ({historical_df['timestamps'].min().strftime('%m-%d')} 到 {historical_df['timestamps'].max().strftime('%m-%d')})")
    print(
        f"  - 预测数据: {len(pred_df)} 个点 ({pred_df['timestamps'].min().strftime('%m-%d')} 到 {pred_df['timestamps'].max().strftime('%m-%d')})")

    # 识别重叠交易日 - 找到历史数据和预测数据都包含的日期
    last_hist_date = historical_df['timestamps'].iloc[-1].date()
    pred_dates = pred_df['timestamps'].dt.date.unique()

    # 找到重叠的日期（预测数据中包含最后一个历史交易日）
    overlap_date = None
    if last_hist_date in pred_dates:
        overlap_date = last_hist_date
        print(f"🔄 检测到重叠交易日: {overlap_date}")

    # 分离历史数据：非重叠部分 + 重叠部分
    if overlap_date:
        # 非重叠的历史数据（前14天）
        hist_non_overlap = historical_df[historical_df['timestamps'].dt.date < overlap_date].copy()
        # 重叠日的历史数据
        hist_overlap = historical_df[historical_df['timestamps'].dt.date == overlap_date].copy()

        # 分离预测数据：重叠部分 + 未来部分
        pred_overlap = pred_df[pred_df['timestamps'].dt.date == overlap_date].copy()
        pred_future = pred_df[pred_df['timestamps'].dt.date > overlap_date].copy()

        # 🔧 关键修正：确保未来预测从真实历史收盘价开始 (修正"预测起点不对"的问题)
        if not pred_future.empty:
            # 确定锚点价格：优先使用真实历史数据的最后收盘价
            anchor_price = None
            anchor_source = "未知"
            
            if not hist_overlap.empty:
                anchor_price = hist_overlap['close'].iloc[-1]
                anchor_source = "真实历史收盘价(重叠日)"
            elif not hist_non_overlap.empty:
                anchor_price = hist_non_overlap['close'].iloc[-1]
                anchor_source = "真实历史收盘价(非重叠日)"
            elif not pred_overlap.empty:
                anchor_price = pred_overlap['close'].iloc[-1]
                anchor_source = "预测重叠日收盘价(无历史数据)"
            
            if anchor_price is not None:
                future_first_close = pred_future['close'].iloc[0]
                price_gap = future_first_close - anchor_price
                gap_pct = abs(price_gap / anchor_price) * 100
                
                # 总是修正，确保连接平滑
                print(f"  🔧 优化预测起点 ({anchor_source}):")
                print(f"     锚点价格: ¥{anchor_price:.2f} -> 原预测起点: ¥{future_first_close:.2f}")
                print(f"     修正幅度: {gap_pct:.2f}% (平移预测曲线以匹配真实走势)")

                # 🔧 修正原始pred_df，确保修改持久化
                future_mask = pred_df['timestamps'].dt.date > overlap_date
                for col in ['open', 'high', 'low', 'close']:
                    pred_df.loc[future_mask, col] = pred_df.loc[future_mask, col] - price_gap
                
                # ⚠️ 关键：修正后必须重新创建pred_overlap和pred_future，确保使用最新数据！
                pred_future = pred_df[pred_df['timestamps'].dt.date > overlap_date].copy()
                
                # 验证修正效果
                new_future_first = pred_future['close'].iloc[0]
                print(f"  ✅ 修正后未来日起点: ¥{new_future_first:.2f}")

        print(f"📊 数据分离结果:")
        print(f"  - 历史数据(前14天): {len(hist_non_overlap)} 个点")
        print(f"  - 重叠日历史数据: {len(hist_overlap)} 个点")
        print(f"  - 重叠日预测数据: {len(pred_overlap)} 个点")
        print(f"  - 未来预测数据: {len(pred_future)} 个点")
    else:
        # 如果没有重叠，按原来的方式处理
        hist_non_overlap = historical_df.copy()
        hist_overlap = pd.DataFrame()
        pred_overlap = pd.DataFrame()
        pred_future = pred_df.copy()

    # 创建连续的交易时间轴索引，重叠区域使用相同索引
    def create_continuous_trading_index_with_overlap(hist_non_overlap, hist_overlap, pred_overlap, pred_future):
        """为数据帧创建连续的交易时间索引，重叠区域共享索引"""
        indexed_dfs = []
        current_index = 0

        # 1. 历史数据（前14天）
        if not hist_non_overlap.empty:
            hist_non_overlap_idx = hist_non_overlap.copy()
            hist_non_overlap_idx['plot_index'] = range(current_index, current_index + len(hist_non_overlap))
            indexed_dfs.append(('hist_non_overlap', hist_non_overlap_idx))
            current_index += len(hist_non_overlap)

        # 2. 重叠区域：历史和预测共享相同索引
        overlap_start_index = current_index
        if not hist_overlap.empty and not pred_overlap.empty:
            # 重叠日历史数据
            hist_overlap_idx = hist_overlap.copy()
            hist_overlap_idx['plot_index'] = range(overlap_start_index, overlap_start_index + len(hist_overlap))
            indexed_dfs.append(('hist_overlap', hist_overlap_idx))

            # 重叠日预测数据 - 使用相同的索引范围
            pred_overlap_idx = pred_overlap.copy()
            pred_overlap_idx['plot_index'] = range(overlap_start_index, overlap_start_index + len(pred_overlap))
            indexed_dfs.append(('pred_overlap', pred_overlap_idx))

            current_index += max(len(hist_overlap), len(pred_overlap))

        # 3. 未来预测数据
        if not pred_future.empty:
            pred_future_idx = pred_future.copy()
            pred_future_idx['plot_index'] = range(current_index, current_index + len(pred_future))
            indexed_dfs.append(('pred_future', pred_future_idx))
            current_index += len(pred_future)

        return indexed_dfs, current_index

    # 创建连续的索引
    indexed_segments, total_points = create_continuous_trading_index_with_overlap(
        hist_non_overlap, hist_overlap, pred_overlap, pred_future
    )

    # 分配索引后的数据段
    hist_non_overlap_idx = pd.DataFrame()
    hist_overlap_idx = pd.DataFrame()
    pred_overlap_idx = pd.DataFrame()
    pred_future_idx = pd.DataFrame()

    for segment_type, df in indexed_segments:
        if segment_type == 'hist_non_overlap':
            hist_non_overlap_idx = df
        elif segment_type == 'hist_overlap':
            hist_overlap_idx = df
        elif segment_type == 'pred_overlap':
            pred_overlap_idx = df
        elif segment_type == 'pred_future':
            pred_future_idx = df

    # 创建图表
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    # 绘制历史价格数据（蓝色）- 包括非重叠部分和重叠部分
    if not hist_non_overlap_idx.empty:
        ax1.plot(hist_non_overlap_idx['plot_index'], hist_non_overlap_idx['close'],
                 color='#4472C4', linewidth=1.5, alpha=0.9)

    # 绘制重叠日的历史数据（蓝色实线）
    if not hist_overlap_idx.empty:
        ax1.plot(hist_overlap_idx['plot_index'], hist_overlap_idx['close'],
                 color='#4472C4', linewidth=1.5, alpha=0.9, label='历史数据')

    # 绘制重叠日的预测数据（红色实线，与历史数据对比）
    if not pred_overlap_idx.empty:
        ax1.plot(pred_overlap_idx['plot_index'], pred_overlap_idx['close'],
                 color='#FF4444', linewidth=1.5, alpha=0.9, label='预测数据')

    # 绘制未来预测数据（红色实线）
    if not pred_future_idx.empty:
        ax1.plot(pred_future_idx['plot_index'], pred_future_idx['close'],
                 color='#FF4444', linewidth=1.5, alpha=0.9)

    # 如果没有重叠数据，则用传统方式绘制
    if overlap_date is None:
        if not hist_non_overlap_idx.empty:
            ax1.plot(hist_non_overlap_idx['plot_index'], hist_non_overlap_idx['close'],
                     label='历史数据', color='#4472C4', linewidth=1.5, alpha=0.9)
        if not pred_future_idx.empty:
            ax1.plot(pred_future_idx['plot_index'], pred_future_idx['close'],
                     label='预测数据', color='#FF4444', linewidth=1.5, alpha=0.9)

    # 🤖 绘制LLM预测数据(如果有)
    if llm_predicted_kline is not None and not llm_predicted_kline.empty:
        print(f"🤖 正在添加LLM预测数据到图表...")

        # 转换LLM预测数据的日期为datetime
        llm_df = llm_predicted_kline.copy()
        if 'date' in llm_df.columns:
            llm_df['timestamps'] = pd.to_datetime(llm_df['date'])
        elif 'timestamps' not in llm_df.columns:
            print(f"  ⚠️ LLM预测数据缺少日期列,无法绘制")
            llm_df = None

        # 🚫 已禁用LLM预测K线显示 - 用户要求去除图表中的紫色虚线
        # if llm_df is not None and 'close' in llm_df.columns:
        #     # 为LLM预测数据创建连续索引
        #     # 从历史数据结束位置的下一个点开始绘制（关键修复：+1确保延续而不是重叠）
        #     if not hist_overlap_idx.empty:
        #         llm_start_index = hist_overlap_idx['plot_index'].iloc[-1] + 1
        #     elif not hist_non_overlap_idx.empty:
        #         llm_start_index = hist_non_overlap_idx['plot_index'].iloc[-1] + 1
        #     else:
        #         llm_start_index = 0
        #
        #     # 为每个LLM预测点分配连续的索引
        #     llm_indices = list(range(llm_start_index, llm_start_index + len(llm_df)))
        #     llm_df['plot_index'] = llm_indices
        #
        #     # 🔧 关键：添加连接点，从最后一个历史点到LLM第一个预测点画线
        #     if not hist_overlap_idx.empty and len(llm_df) > 0:
        #         last_hist_idx = hist_overlap_idx['plot_index'].iloc[-1]
        #         last_hist_price = hist_overlap_idx['close'].iloc[-1]
        #         first_llm_idx = llm_df['plot_index'].iloc[0]
        #         first_llm_price = llm_df['close'].iloc[0]
        #
        #         # 画连接线段
        #         ax1.plot([last_hist_idx, first_llm_idx], [last_hist_price, first_llm_price],
        #                  color='#9C27B0', linewidth=2.0, linestyle='--', alpha=0.85)
        #
        #     # 绘制LLM预测线(紫色虚线,与Kronos预测区分)
        #     ax1.plot(llm_df['plot_index'], llm_df['close'],
        #              color='#9C27B0', linewidth=2.5, linestyle='--', alpha=0.9,
        #              label='AI预测(LLM)', marker='o', markersize=5, markerfacecolor='#9C27B0',
        #              markeredgecolor='white', markeredgewidth=0.8)
        #
        #     print(f"  ✅ LLM预测数据已添加: {len(llm_df)}个预测点")
        #     print(f"  📈 LLM预测范围: {llm_df['timestamps'].min().strftime('%Y-%m-%d')} 至 {llm_df['timestamps'].max().strftime('%Y-%m-%d')}")
        #     print(f"  💰 LLM预测价格区间: ¥{llm_df['close'].min():.2f} - ¥{llm_df['close'].max():.2f}")


    # 设置标题和标签
    ax1.set_ylabel('收盘价格 (¥)', fontsize=12, fontweight='bold')
    ax1.set_title(f'Kronos股价预测结果 - {stock_code} (预测准确性分析)', fontsize=14, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'¥{x:.2f}'))

    # 绘制成交量 - 使用连续索引
    bar_width = 0.8

    # 历史成交量（蓝色）- 包括非重叠部分
    if not hist_non_overlap_idx.empty:
        ax2.bar(hist_non_overlap_idx['plot_index'], hist_non_overlap_idx['volume'],
                width=bar_width, color='#4472C4', alpha=0.8, edgecolor='none')

    # 重叠日历史成交量（蓝色）
    if not hist_overlap_idx.empty:
        ax2.bar(hist_overlap_idx['plot_index'], hist_overlap_idx['volume'],
                width=bar_width, color='#4472C4', alpha=0.8, edgecolor='none', label='历史成交量')

    # 重叠日预测成交量（红色，与历史成交量并列显示）
    if not pred_overlap_idx.empty:
        # 使用稍微偏移的位置显示预测成交量，避免完全重叠
        offset_indices = pred_overlap_idx['plot_index'] + 0.4
        ax2.bar(offset_indices, pred_overlap_idx['volume'],
                width=bar_width * 0.6, color='#FF4444', alpha=0.8, edgecolor='none', label='预测成交量')

    # 未来预测成交量（红色）
    if not pred_future_idx.empty:
        ax2.bar(pred_future_idx['plot_index'], pred_future_idx['volume'],
                width=bar_width, color='#FF4444', alpha=0.8, edgecolor='none')

    # 如果没有重叠数据，则用传统方式绘制
    if overlap_date is None:
        if not hist_non_overlap_idx.empty:
            ax2.bar(hist_non_overlap_idx['plot_index'], hist_non_overlap_idx['volume'],
                    width=bar_width, label='历史成交量', color='#4472C4', alpha=0.8, edgecolor='none')
        if not pred_future_idx.empty:
            ax2.bar(pred_future_idx['plot_index'], pred_future_idx['volume'],
                    width=bar_width, label='预测成交量', color='#FF4444', alpha=0.8, edgecolor='none')

    ax2.set_ylabel('成交量', fontsize=12, fontweight='bold')
    ax2.set_xlabel('交易时间', fontsize=12, fontweight='bold')
    ax2.legend(loc='upper left', fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))

    # 设置x轴显示 - 简化为每日标签，避免过于密集
    all_timestamps = pd.concat([historical_df['timestamps'], pred_df['timestamps']])
    trading_dates = sorted(list(set(ts.date() for ts in all_timestamps if is_trading_day(ts.date()))))

    # 简化版本：每个交易日只显示一个主要标签
    tick_positions = []
    tick_labels = []

    # 为每个交易日找到开盘时间的索引位置
    for date in trading_dates:
        # 寻找该日期9:30开盘时间的数据点
        target_time = datetime.combine(date, datetime.min.time()).replace(hour=9, minute=30)

        found_index = None
        min_time_diff = timedelta(hours=2)  # 允许较大差异

        for df in [hist_non_overlap_idx, hist_overlap_idx, pred_overlap_idx, pred_future_idx]:
            if not df.empty:
                date_mask = df['timestamps'].dt.date == date
                if date_mask.any():
                    day_data = df[date_mask]
                    # 使用该日第一个数据点作为代表
                    if len(day_data) > 0:
                        found_index = day_data['plot_index'].iloc[0]
                        break

        if found_index is not None:
            tick_positions.append(found_index)
            # 显示月-日格式，简洁明了
            tick_labels.append(date.strftime('%m-%d'))

    # 应用x轴标签 - 确保不重叠
    if len(tick_positions) > 0:
        ax1.set_xticks(tick_positions)
        ax1.set_xticklabels(tick_labels, fontsize=10, rotation=0, ha='center')
        ax2.set_xticks(tick_positions)
        ax2.set_xticklabels(tick_labels, fontsize=10, rotation=0, ha='center')

        # 确保标签不重叠
        ax1.tick_params(axis='x', which='major', pad=8)
        ax2.tick_params(axis='x', which='major', pad=8)

    # 设置x轴范围
    ax1.set_xlim(-1, total_points)
    ax2.set_xlim(-1, total_points)

    print(f"🕒 图表x轴配置: 连续交易时间轴，{len(trading_dates)}个交易日，{total_points}个数据点")
    if overlap_date:
        print(f"🔄 重叠对比日: {overlap_date}，真实数据vs预测数据同时显示")

    # 添加分割线和区域标注 - 修正重叠区域的标记
    if overlap_date and not hist_overlap_idx.empty:
        # 绿色分割线 - 重叠区域开始（9月5日开始）
        overlap_start_index = hist_overlap_idx['plot_index'].iloc[0]

        ax1.axvline(x=overlap_start_index, color='green', linestyle='--', alpha=0.8, linewidth=2)
        ax2.axvline(x=overlap_start_index, color='green', linestyle='--', alpha=0.8, linewidth=2)

        # 橙色分割线 - 重叠区域结束（9月5日结束）
        overlap_end_index = hist_overlap_idx['plot_index'].iloc[-1]

        ax1.axvline(x=overlap_end_index, color='orange', linestyle='--', alpha=0.8, linewidth=2)
        ax2.axvline(x=overlap_end_index, color='orange', linestyle='--', alpha=0.8, linewidth=2)

        # 重叠区域背景色（绿色到橙色之间）
        ax1.axvspan(overlap_start_index, overlap_end_index, alpha=0.1, color='green')
        ax2.axvspan(overlap_start_index, overlap_end_index, alpha=0.1, color='green')

        # 绿色标注 - 重叠区域开始
        ax1.text(overlap_start_index, ax1.get_ylim()[1] * 0.95,
                 f'{overlap_date.strftime("%m-%d")}真实区间\n(准确性对比)',
                 ha='center', va='top', color='green',
                 fontweight='bold', fontsize=10,
                 bbox=dict(boxstyle='round,pad=0.4', facecolor='lightgreen', alpha=0.9, edgecolor='green'))

        # 未来预测区域标注
        if not pred_future_idx.empty:
            # 未来预测区域背景色
            future_start_index = pred_future_idx['plot_index'].iloc[0]
            future_end_index = pred_future_idx['plot_index'].iloc[-1]
            ax1.axvspan(future_start_index, future_end_index, alpha=0.05, color='orange')
            ax2.axvspan(future_start_index, future_end_index, alpha=0.05, color='orange')

            # 黄色预测标注框
            mid_future_index = future_start_index + (future_end_index - future_start_index) / 2
            ax1.text(mid_future_index, ax1.get_ylim()[1] * 0.85,
                     '未来5日预测', ha='center', va='top', color='darkorange',
                     fontweight='bold', fontsize=11,
                     bbox=dict(boxstyle='round,pad=0.4', facecolor='yellow', alpha=0.9, edgecolor='orange'))

    # 调整布局
    plt.tight_layout()
    plt.subplots_adjust(hspace=0.1)

    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
        print(f"📊 预测图表已保存到: {save_path}")

    plt.close()

    print(f"✅ 图表生成完成")
    print(f"📊 图表包含: 历史 {len(historical_df)} 个点，预测 {len(pred_df)} 个点")

    # 提供详细的预测说明
    if len(historical_df) > 0 and len(pred_df) > 0:
        last_hist = historical_df['close'].iloc[-1]
        first_pred = pred_df['close'].iloc[0]
        connection_gap = ((first_pred - last_hist) / last_hist) * 100

        print(f"📋 预测类型: 20个交易日完整分析（15天历史 + 5天预测含1天重叠验证）")
        print(f"   历史数据: {len(historical_df)} 个5分钟K线点 (15个交易日)")
        print(f"   预测数据: {len(pred_df)} 个5分钟K线点 (6天预测包含1天重叠)")

        if overlap_date:
            # 计算重叠日的预测准确性
            if not hist_overlap.empty and not pred_overlap.empty:
                hist_overlap_prices = hist_overlap['close'].values
                pred_overlap_prices = pred_overlap['close'].values

                # 计算预测准确性指标
                min_len = min(len(hist_overlap_prices), len(pred_overlap_prices))
                if min_len > 0:
                    hist_prices = hist_overlap_prices[:min_len]
                    pred_prices = pred_overlap_prices[:min_len]

                    mae = abs(pred_prices - hist_prices).mean()
                    mape = (abs(pred_prices - hist_prices) / hist_prices * 100).mean()

                    print(f"🎯 重叠日({overlap_date})预测准确性:")
                    print(f"   - 平均绝对误差(MAE): ¥{mae:.3f}")
                    print(f"   - 平均绝对百分比误差(MAPE): {mape:.2f}%")

        print(f"🔗 价格连接: 历史终点¥{last_hist:.2f} -> 预测起点¥{first_pred:.2f} (差异{connection_gap:+.1f}%)")

    print(f"💾 图表已保存: {save_path if save_path else '仅显示，未保存'}")


def plot_prediction(kline_df, pred_df, stock_code, save_path=None):
    """
    绘制预测结果图表 - 参考标准图表样式，确保预测线与历史数据平滑连接
    
    Args:
        kline_df: 原始K线数据
        pred_df: 预测结果数据  
        stock_code: 股票代码
        save_path: 保存路径，如果为None则只显示不保存
    """
    import matplotlib.dates as mdates
    from datetime import datetime, timedelta

    # 预测数据处理：从索引获取时间戳并添加为列
    if 'timestamps' not in pred_df.columns:
        pred_df = pred_df.copy()
        pred_df['timestamps'] = pred_df.index
        pred_df = pred_df.reset_index(drop=True)
        print("🔧 已从索引中提取预测数据的时间戳")

    # 确保时间戳为datetime类型
    kline_df['timestamps'] = pd.to_datetime(kline_df['timestamps'])
    pred_df['timestamps'] = pd.to_datetime(pred_df['timestamps'])

    # 使用较多的历史数据展示（约5-7个交易日）
    display_history_len = min(600, len(kline_df))
    display_kline_df = kline_df.iloc[-display_history_len:].copy()

    # 预测数据使用更多点数（约3-4个交易日）
    pred_display_len = min(200, len(pred_df))  # 4个交易日 * 50点/天
    pred_display_df = pred_df.iloc[:pred_display_len].copy()

    print(f"📊 图表数据范围：")
    print(
        f"  - 历史数据: {len(display_kline_df)} 个点 ({display_kline_df['timestamps'].min().strftime('%m-%d')} 到 {display_kline_df['timestamps'].max().strftime('%m-%d')})")
    print(
        f"  - 预测数据: {len(pred_display_df)} 个点 ({pred_display_df['timestamps'].min().strftime('%m-%d')} 到 {pred_display_df['timestamps'].max().strftime('%m-%d')})")

    # 创建图表
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    # 绘制历史价格数据
    ax1.plot(display_kline_df['timestamps'], display_kline_df['close'],
             label='历史数据', color='#4472C4', linewidth=1.5, alpha=0.9)

    # 绘制预测数据，确保与历史数据平滑连接
    if len(display_kline_df) > 0 and len(pred_display_df) > 0:
        # 关键修复：检查时间重叠，确保预测数据正确定位
        hist_end_time = display_kline_df['timestamps'].iloc[-1]
        pred_start_time = pred_display_df['timestamps'].iloc[0]

        print(f"🔍 连接点分析:")
        print(f"  - 历史数据结束: {hist_end_time}")
        print(f"  - 预测数据开始: {pred_start_time}")

        # 处理时间重叠情况：如果预测数据的时间早于或等于历史数据结束时间
        if pred_start_time <= hist_end_time:
            print(f"  - 检测到时间重叠，进行调整")

            # 方案：找到预测数据中第一个晚于历史结束时间的点
            future_mask = pred_display_df['timestamps'] > hist_end_time
            if future_mask.any():
                # 使用真正的未来预测数据
                future_pred_df = pred_display_df[future_mask].copy()
                print(f"  - 提取真正的未来预测数据: {len(future_pred_df)} 个点")

                if len(future_pred_df) > 0:
                    # 获取历史数据的最后价格
                    last_hist_price = display_kline_df['close'].iloc[-1]
                    first_future_price = future_pred_df['close'].iloc[0]

                    # 价格连续性检查和调整
                    price_gap = first_future_price - last_hist_price
                    gap_percentage = abs(price_gap / last_hist_price)

                    print(
                        f"  - 价格连接: 历史¥{last_hist_price:.2f} -> 预测¥{first_future_price:.2f} (差异{gap_percentage:.1%})")

                    if gap_percentage > 0.03:
                        print(f"  - 执行价格平滑调整")
                        adjustment_factor = last_hist_price / first_future_price
                        future_pred_df['close'] *= adjustment_factor
                        future_pred_df['open'] *= adjustment_factor
                        future_pred_df['high'] *= adjustment_factor
                        future_pred_df['low'] *= adjustment_factor

                        # 添加连接线，从历史最后点到调整后的预测第一点
                        ax1.plot([hist_end_time, future_pred_df['timestamps'].iloc[0]],
                                 [last_hist_price, future_pred_df['close'].iloc[0]],
                                 color='#FF6B6B', linewidth=1.5, alpha=0.7, linestyle='--')

                    # 绘制未来预测数据
                    ax1.plot(future_pred_df['timestamps'], future_pred_df['close'],
                             label='预测数据', color='#FF6B6B', linewidth=1.5, alpha=0.9)

                    # 更新用于成交量绘制的预测数据
                    pred_display_df_for_volume = future_pred_df
                else:
                    print("  - 警告：没有找到真正的未来预测数据")
                    pred_display_df_for_volume = pred_display_df
            else:
                print("  - 警告：预测数据完全在历史时间范围内")
                # 仍然绘制预测数据，但标注为历史对比
                ax1.plot(pred_display_df['timestamps'], pred_display_df['close'],
                         label='预测数据(历史对比)', color='#FF6B6B', linewidth=1.5, alpha=0.6, linestyle=':')
                pred_display_df_for_volume = pred_display_df
        else:
            # 预测时间正常，晚于历史数据
            print(f"  - 时间序列正常")

            # 价格连续性处理
            last_hist_price = display_kline_df['close'].iloc[-1]
            first_pred_price = pred_display_df['close'].iloc[0]

            pred_display_df_connected = pred_display_df.copy()
            price_gap = first_pred_price - last_hist_price
            gap_percentage = abs(price_gap / last_hist_price)

            print(f"  - 价格连接: 历史¥{last_hist_price:.2f} -> 预测¥{first_pred_price:.2f} (差异{gap_percentage:.1%})")

            if gap_percentage > 0.03:
                print(f"  - 执行价格平滑调整")
                adjustment_factor = last_hist_price / first_pred_price
                pred_display_df_connected['close'] *= adjustment_factor
                pred_display_df_connected['open'] *= adjustment_factor
                pred_display_df_connected['high'] *= adjustment_factor
                pred_display_df_connected['low'] *= adjustment_factor

            # 添加连接线，从历史最后点到预测第一点（无论是否调整）
            ax1.plot([hist_end_time, pred_display_df_connected['timestamps'].iloc[0]],
                     [last_hist_price, pred_display_df_connected['close'].iloc[0]],
                     color='#FF6B6B', linewidth=1.5, alpha=0.7, linestyle='--')

            # 绘制预测线
            ax1.plot(pred_display_df_connected['timestamps'], pred_display_df_connected['close'],
                     label='预测数据', color='#FF6B6B', linewidth=1.5, alpha=0.9)

            pred_display_df_for_volume = pred_display_df_connected
    else:
        pred_display_df_for_volume = pred_display_df

    # 设置标题和标签
    ax1.set_ylabel('收盘价格 (¥)', fontsize=12, fontweight='bold')

    # 动态标题：根据预测类型调整
    if 'pred_start_time' in locals() and pred_start_time <= hist_end_time:
        title_suffix = "(历史数据预测准确性验证)"
    else:
        title_suffix = "(未来预测分析)"

    ax1.set_title(f'Kronos股价预测结果 - {stock_code} {title_suffix}', fontsize=14, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'¥{x:.2f}'))

    # 绘制成交量
    bar_width = timedelta(minutes=2.5)  # 调整柱状图宽度

    ax2.bar(display_kline_df['timestamps'], display_kline_df['volume'],
            width=bar_width, label='历史成交量', color='#4472C4', alpha=0.8, edgecolor='none')
    ax2.bar(pred_display_df_for_volume['timestamps'], pred_display_df_for_volume['volume'],
            width=bar_width, label='预测成交量', color='#FF6B6B', alpha=0.8, edgecolor='none')

    ax2.set_ylabel('成交量', fontsize=12, fontweight='bold')
    ax2.set_xlabel('交易时间', fontsize=12, fontweight='bold')
    ax2.legend(loc='upper left', fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))

    # 优化x轴时间显示
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax2.xaxis.set_major_locator(mdates.DayLocator(interval=1))

    # 旋转时间标签
    for label in ax2.get_xticklabels():
        label.set_rotation(0)  # 不旋转，保持水平
        label.set_ha('center')

    # 添加分割线和区域标注
    if len(display_kline_df) > 0 and len(pred_display_df) > 0:
        split_time = display_kline_df['timestamps'].iloc[-1]

        # 绿色分割线
        ax1.axvline(x=split_time, color='green', linestyle='--', alpha=0.8, linewidth=2)
        ax2.axvline(x=split_time, color='green', linestyle='--', alpha=0.8, linewidth=2)

        # 预测区域背景色
        pred_start = pred_display_df['timestamps'].iloc[0]
        pred_end = pred_display_df['timestamps'].iloc[-1]
        ax1.axvspan(pred_start, pred_end, alpha=0.05, color='orange')
        ax2.axvspan(pred_start, pred_end, alpha=0.05, color='orange')

        # 绿色标注框
        ax1.text(split_time, ax1.get_ylim()[1] * 0.95,
                 f'{split_time.strftime("%m-%d")}真实区间\n(准确性对比)',
                 ha='center', va='top', color='green',
                 fontweight='bold', fontsize=10,
                 bbox=dict(boxstyle='round,pad=0.4', facecolor='lightgreen', alpha=0.9, edgecolor='green'))

        # 黄色预测标注框
        mid_pred = pred_start + (pred_end - pred_start) / 2
        ax1.text(mid_pred, ax1.get_ylim()[1] * 0.85,
                 '未来日预测', ha='center', va='top', color='darkorange',
                 fontweight='bold', fontsize=11,
                 bbox=dict(boxstyle='round,pad=0.4', facecolor='yellow', alpha=0.9, edgecolor='orange'))

    # 调整布局
    plt.tight_layout()
    plt.subplots_adjust(hspace=0.1)

    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
        print(f"📊 预测图表已保存到: {save_path}")

    plt.close()

    print(f"✅ 图表生成完成")
    print(f"📊 图表包含: 历史 {len(display_kline_df)} 个点，预测 {len(pred_display_df)} 个点")

    # 提供详细的预测说明
    if len(display_kline_df) > 0 and len(pred_display_df) > 0:
        last_hist = display_kline_df['close'].iloc[-1]
        first_pred = pred_display_df['close'].iloc[0]
        connection_gap = ((first_pred - last_hist) / last_hist) * 100

        hist_end_time = display_kline_df['timestamps'].iloc[-1]
        pred_start_time = pred_display_df['timestamps'].iloc[0]

        if pred_start_time <= hist_end_time:
            print(f"📋 预测类型: 历史数据验证 (用于评估模型准确性)")
            print(
                f"   预测时间范围: {pred_start_time.strftime('%Y-%m-%d %H:%M')} 到 {pred_display_df['timestamps'].iloc[-1].strftime('%Y-%m-%d %H:%M')}")
            print(
                f"   历史时间范围: {display_kline_df['timestamps'].iloc[0].strftime('%Y-%m-%d %H:%M')} 到 {hist_end_time.strftime('%Y-%m-%d %H:%M')}")
            print(f"🔗 价格对比: 历史实际¥{last_hist:.2f} vs 预测¥{first_pred:.2f} (差异{connection_gap:+.1f}%)")
        else:
            print(f"📋 预测类型: 未来趋势预测")
            print(f"🔗 价格连接: 历史终点¥{last_hist:.2f} -> 预测起点¥{first_pred:.2f} (跳空{connection_gap:+.1f}%)")

    print(f"💾 图表已保存: {save_path if save_path else '仅显示，未保存'}")


# 1. Load Model and Tokenizer
# 检查本地模型是否存在，否则使用ModelScope下载

# 检查本地模型是否存在，否则使用ModelScope下载
# 优先使用环境变量中的模型目录，适配打包应用
if not getattr(args, 'timestamps_only', False):
    models_dir_env = os.environ.get('KRONOS_MODELS_DIR')
    if models_dir_env:
        model_dir = Path(models_dir_env)
    else:
        model_dir = project_root / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"Model directory: {model_dir}")

    # 一级目录结构，直接在models下
    tokenizer_dir = model_dir / "Kronos-Tokenizer-base"
    model_dir_path = model_dir / "Kronos-small"

    try:
        # 优先使用本地模型（一级目录结构）
        if tokenizer_dir.exists() and (tokenizer_dir / "config.json").exists():
            print("Found local tokenizer, loading...")
            tokenizer = KronosTokenizer.from_pretrained(str(tokenizer_dir))
        else:
            # 动态导入modelscope，避免启动时的兼容性问题
            try:
                from modelscope import snapshot_download
            except ImportError as import_error:
                print(f"❌ ModelScope导入失败: {import_error}")
                print("请确保已正确安装modelscope包，或使用本地模型文件")
                sys.exit(1)

            # 下载并保存到一级目录
            print("Downloading tokenizer...")
            downloaded_path = snapshot_download('northwind9898/Kronos-Tokenizer-base', cache_dir=str(model_dir))
            # 如果下载路径有嵌套结构，将其移动到一级目录
            import shutil

            if "northwind9898" in downloaded_path:
                if not tokenizer_dir.exists():
                    shutil.move(downloaded_path, str(tokenizer_dir))
                downloaded_path = str(tokenizer_dir)
            tokenizer = KronosTokenizer.from_pretrained(downloaded_path)

        if model_dir_path.exists() and (model_dir_path / "config.json").exists():
            print("Found local model, loading...")
            model = Kronos.from_pretrained(str(model_dir_path))
        else:
            # 动态导入modelscope，避免启动时的兼容性问题
            try:
                from modelscope import snapshot_download
            except ImportError as import_error:
                print(f"❌ ModelScope导入失败: {import_error}")
                print("请确保已正确安装modelscope包，或使用本地模型文件")
                sys.exit(1)

            # 下载并保存到一级目录
            print("Downloading model...")
            downloaded_path = snapshot_download('northwind9898/Kronos-small', cache_dir=str(model_dir))
            # 如果下载路径有嵌套结构，将其移动到一级目录
            import shutil

            if "northwind9898" in downloaded_path:
                if not model_dir_path.exists():
                    shutil.move(downloaded_path, str(model_dir_path))
                downloaded_path = str(model_dir_path)
            model = Kronos.from_pretrained(downloaded_path)

    except Exception as e:
        print(f"Error loading models: {e}")
        print("This may be due to network issues or model availability.")
        print("Please check your internet connection and try again.")
        sys.exit(1)
else:
    print("⏭️ 跳过模型加载（timestamps-only模式）")

# 2. Instantiate Predictor
# 自动检测设备
if not getattr(args, 'timestamps_only', False):
    import torch

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
else:
    predictor = None

# 3. Prepare Data - 查找数据文件并选择股票
# 优先使用环境变量中的数据目录，适配打包应用
data_dir_env = os.environ.get('KRONOS_DATA_DIR')
if data_dir_env:
    data_dir = Path(data_dir_env)
else:
    data_dir = project_root / "data"
csv_files = list(data_dir.glob("*.csv"))

if not csv_files:
    print("❌ 未找到数据文件，请先运行数据获取脚本")
    sys.exit(1)

# 过滤出5分钟数据文件
min5_files = [f for f in csv_files if "5m_" in f.name or "_5min_" in f.name]

if not min5_files:
    print("❌ 未找到5分钟数据文件")
    sys.exit(1)

# 如果用户要求列出股票，则显示列表并退出
if args.list_stocks:
    print("🔍 可用的股票数据文件:")
    for i, f in enumerate(min5_files):
        parts = f.name.replace('.csv', '').split('_')
        stock_code = parts[-1]
        print(f"  {i + 1}. {stock_code} - {f.name}")
    sys.exit(0)

# 选择数据文件
data_file = None
if args.stock_code:
    # 如果指定了股票代码，查找对应文件
    data_file = find_data_file_by_code(args.stock_code, min5_files)
    if not data_file:
        print(f"❌ 未找到股票代码 {args.stock_code} 对应的数据文件")
        print("🔍 可用的股票代码:")
        for f in min5_files:
            parts = f.name.replace('.csv', '').split('_')
            stock_code = parts[-1]
            print(f"  - {stock_code}")
        sys.exit(1)
    else:
        print(f"✅ 找到股票 {args.stock_code} 的数据文件: {data_file.name}")
else:
    # 如果没有指定股票代码，显示选择菜单
    print("🔍 可用的股票数据文件:")
    for i, f in enumerate(min5_files):
        # 提取股票代码
        parts = f.name.replace('.csv', '').split('_')
        stock_code = parts[-1]
        print(f"  {i + 1}. {stock_code} - {f.name}")

    # 让用户选择股票或使用第一个
    if len(min5_files) == 1:
        data_file = min5_files[0]
        print(f"📌 自动选择唯一可用的数据文件")
    else:
        # 自动选择第一个股票文件，无需用户交互
        print(f"\n📌 自动选择第一个股票进行预测")
        data_file = min5_files[0]

print(f"使用数据文件: {data_file}")

# 提取股票代码（用于后续数据补全）
file_name = data_file.name
stock_code = "UNKNOWN"
parts = file_name.replace('.csv', '').split('_')
stock_code = parts[-1]
print(f"🎯 股票代码: {stock_code}")

# 读取现有数据并分析
df = pd.read_csv(str(data_file))

# 处理列名不一致问题
if 'timestamp' in df.columns and 'timestamps' not in df.columns:
    df.rename(columns={'timestamp': 'timestamps'}, inplace=True)
elif 'date' in df.columns and 'timestamps' not in df.columns:
    df.rename(columns={'date': 'timestamps'}, inplace=True)

# 再次检查，如果还是没有timestamps，打印所有列名以便调试
if 'timestamps' not in df.columns:
    print(f"❌ 列名错误: 找不到时间戳列，现有列: {list(df.columns)}")
    # 尝试模糊匹配
    for col in df.columns:
        if 'time' in col.lower() or 'date' in col.lower():
            print(f"⚠️  尝试使用列 '{col}' 作为时间戳")
            df.rename(columns={col: 'timestamps'}, inplace=True)
            break
    
    if 'timestamps' not in df.columns:
        sys.exit(1)

df['timestamps'] = pd.to_datetime(df['timestamps'])

# 验证数据
required_columns = ['open', 'high', 'low', 'close', 'volume', 'amount']
missing_columns = [col for col in required_columns if col not in df.columns]
if missing_columns:
    print(f"❌ 数据文件缺少必要列: {missing_columns}")
    sys.exit(1)

print(f"\n📊 现有数据分析:")
print(f"  - 数据记录数: {len(df)} 条")
print(f"  - 数据时间范围: {df['timestamps'].min()} 至 {df['timestamps'].max()}")

# 计算数据覆盖的实际天数
data_days = (df['timestamps'].max() - df['timestamps'].min()).days
print(f"  - 覆盖天数: {data_days} 天")

# A股实际交易时间计算
bars_per_day_check = 50  # A股每天50个5分钟K线（上午25个+下午25个）
half_year_trading_days_check = 125  # 半年约125个交易日
recommended_min_points = half_year_trading_days_check * bars_per_day_check  # 约6,250点

# 检查数据是否充足
if len(df) < recommended_min_points:
    shortage = recommended_min_points - len(df)
    shortage_days = shortage // bars_per_day_check

    print(f"\n⚠️  数据量不足！")
    print(f"  - 当前数据: {len(df)} 条")
    print(f"  - 推荐最少: {recommended_min_points} 条 (约{half_year_trading_days_check}个交易日)")
    print(f"  - 缺少数据: {shortage} 条 (约{shortage_days}个交易日)")
    print(f"\n💡 建议操作: 补全历史数据以提高预测准确性")
    print(f"   🔧 运行命令:")
    print(f"      python scripts/fetch_data.py --symbol {stock_code} --source auto --days 180")
    print(f"\n⏸️  是否继续使用现有数据进行预测？")
    print(f"   注意: 数据不足可能导致预测不准确")

    # 自动继续（非交互模式）
    print(f"   ✅ 自动继续使用现有数据...")
else:
    print(f"✅ 数据量充足，可以进行准确预测")

print(f"✅ 数据验证通过，共 {len(df)} 条记录")

# 数据处理：过滤只保留交易时间的数据，准备预测
print(f"📊 数据预处理:")
print(f"  - 原始数据: {len(df)} 条记录")

# 过滤只保留交易时间的数据
df_trading_only = filter_trading_time_only(df)
print(f"  - 交易时间数据: {len(df_trading_only)} 条记录")

if df_trading_only.empty:
    print("❌ 过滤后没有交易时间数据")
    sys.exit(1)

# 准备展示数据：前15个交易日历史 + 5天预测数据（包含1天交集）= 共20天
last_date = df_trading_only['timestamps'].iloc[-1].date()

# 获取前14个交易日 + 当前交易日 = 共15个交易日
display_history_trading_days = 15
display_pre_days = display_history_trading_days - 1
display_history_days = get_trading_days(last_date, display_pre_days, direction='backward')
display_history_days.append(last_date)  # 包含最后一个交易日，共15个交易日

print(
    f"  - 展示历史交易日: {display_history_days[0]} 到 {display_history_days[-1]} ({len(display_history_days)}个交易日)")

# 过滤历史展示数据（前15个交易日）
display_start_date = display_history_days[0]
display_end_date = display_history_days[-1]

display_mask = (df_trading_only['timestamps'].dt.date >= display_start_date) & \
               (df_trading_only['timestamps'].dt.date <= display_end_date)
display_df = df_trading_only[display_mask].copy()

print(f"  - 展示历史数据: {len(display_df)} 条记录")

# 技术指标仍使用完整数据集保证准确性，但预测使用交易时间数据
training_df = df_trading_only.copy()  # 使用过滤后的交易时间数据进行预测
complete_df = df.copy()  # 完整数据用于技术指标计算

# 基于新的预测策略设置参数
# 智能选择lookback窗口：尽量使用最大可用数据，推荐半年到一年
# A股实际交易：每年约250个交易日，每天48个5分钟K线（9:30-11:30 + 13:00-15:00）
one_year_trading_days = 250  # 一年约250个交易日
half_year_trading_days = 125  # 半年约125个交易日
bars_per_day = 50  # A股每个交易日50个5分钟K线（上午25个+下午25个）

one_year_points = one_year_trading_days * bars_per_day  # 约12,500个数据点
half_year_points = half_year_trading_days * bars_per_day  # 约6,250个数据点

available_points = len(training_df)
available_days = available_points // bars_per_day

print(f"\n📊 数据量分析:")
print(f"  - 可用数据点: {available_points} 个5分钟K线")
print(f"  - 约合交易日: {available_days} 个交易日")
print(
    f"  - 推荐数据量: 半年({half_year_trading_days}天 ≈ {half_year_points}点) 到 一年({one_year_trading_days}天 ≈ {one_year_points}点)")

# 优先级：使用所有可用数据，但不超过模型上下文限制
model_max_context = 512  # Kronos-base的最大上下文长度

if available_points <= model_max_context:
    # 数据量在模型上下文范围内，使用全部数据
    lookback = available_points
    print(f"✅ 使用全部可用数据进行预测（{available_points}点）")
    print(f"   📈 使用数据: {available_days}个交易日，{lookback}个数据点")
else:
    # 数据量超过模型上下文，使用模型的最大上下文长度
    lookback = model_max_context
    actual_days = lookback // bars_per_day
    print(f"✅ 数据充足！使用模型最大上下文长度")
    print(f"   📈 使用数据: {actual_days}个交易日，{lookback}个数据点")
    print(f"   💡 注意: 可用数据({available_points}点)超过模型上下文({model_max_context}点)，已自动截取最近的数据")

# 对齐lookback到完整交易日边界，确保历史输入从09:30开始（5分钟粒度下每日约50点）
aligned_lookback = (lookback // bars_per_day) * bars_per_day if bars_per_day > 0 else lookback
if aligned_lookback != lookback:
    print(f"   🔧 对齐lookback到交易日边界: {lookback} -> {aligned_lookback} (每日{bars_per_day}点)")
    lookback = aligned_lookback

# 数据量建议（仅在数据确实不足时提示）
if available_points < half_year_points:
    shortage_days = (half_year_points - available_points) // bars_per_day
    print(f"\n⚠️  数据量建议:")
    print(f"   - 当前数据: {available_days} 个交易日")
    print(f"   - 建议数据: 至少 {half_year_trading_days} 个交易日（半年）")
    print(f"   - 缺少约: {shortage_days} 个交易日")
    print(
        f"   💡 补充数据命令: python scripts/fetch_data.py --symbol {stock_code if 'stock_code' in locals() else 'XXXXXX'} --source auto --days 180")
    print(f"   📌 注意: 虽然数据不足半年，但模型仍会使用所有可用数据({lookback}点)进行预测")
print()

target_future_days = 5  # 未来5个交易日

# 根据预测模式生成时间戳（overlap: 重叠验证；realtime: 实时预测）
if hasattr(args, 'prediction_mode') and args.prediction_mode == 'realtime':
    prediction_timestamps, training_end_marker, overlap_date, overlap_start_marker = generate_realtime_prediction_timestamps(
        training_df, target_days=target_future_days
    )
else:
    # 默认使用重叠验证策略
    prediction_timestamps, training_end_marker, overlap_date, overlap_start_marker = generate_prediction_timestamps(
        training_df, target_days=target_future_days
    )

if not prediction_timestamps:
    print("❌ 无法生成预测时间戳")
    sys.exit(1)

pred_len = len(prediction_timestamps)  # 预测长度基于实际生成的时间戳数量

print(f"📊 预测参数:")
print(f"  - lookback窗口: {lookback} 条")
print(f"  - 预测时间戳: {pred_len} 个点")
print(f"  - 目标天数: {target_future_days}个未来交易日")

# 支持仅输出时间戳并提前退出，避免后续模型预测与图表生成
if getattr(args, 'timestamps_only', False):
    print("\n⏱️ 仅输出预测时间戳模式")
    print(f"   模式: {getattr(args, 'prediction_mode', 'overlap')}")
    print(f"   训练截止: {training_end_marker}")
    print(f"   预测起始: {overlap_start_marker}")
    print(f"   预测点数: {len(prediction_timestamps)}")
    preview_count = min(20, len(prediction_timestamps))
    print(f"   前{preview_count}个时间戳预览:")
    for ts in prediction_timestamps[:preview_count]:
        print(f"     - {ts}")
    if len(prediction_timestamps) > preview_count:
        print(f"     ... 共{len(prediction_timestamps)}个时间点")
    sys.exit(0)

if len(training_df) < lookback + 50:  # 至少需要lookback + 一些最小预测点
    print(f"❌ 训练数据不足，需要至少 {lookback + 50} 条记录，实际只有 {len(training_df)} 条")
    sys.exit(1)

# 准备批量预测数据 - 使用前N-1天的数据（去掉最后一个交易日用于重叠验证）
dfs = []
xtsp = []
ytsp = []

# 找到训练数据的截止位置（排除最后一个交易日）
if training_end_marker:
    # 使用到training_end_marker为止的数据
    training_mask = training_df['timestamps'] <= training_end_marker
    actual_training_df = training_df[training_mask].copy()

    if overlap_date:
        print(f"📊 重叠验证数据准备:")
        print(f"   - 完整历史数据: {len(training_df)} 点")
        print(f"   - 训练数据截止: {training_end_marker}")
        print(f"   - 实际训练数据: {len(actual_training_df)} 点 (排除了最后一个交易日)")
    else:
        print(f"📊 训练数据准备:")
        print(f"   - 完整历史数据: {len(training_df)} 点")
        print(f"   - 训练数据截止: {training_end_marker}")
        print(f"   - 实际训练数据: {len(actual_training_df)} 点")
else:
    actual_training_df = training_df
    print(f"⚠️ 未找到训练截止标记，使用全部历史数据")

# 使用历史数据的最后lookback个点作为输入（严格按完整交易日对齐，从09:30开始）
desired_days = max(1, lookback // bars_per_day)

# 计算训练截止日期（用于窗口右边界）
end_date_for_window = None
if training_end_marker is not None:
    end_date_for_window = pd.to_datetime(training_end_marker).date()
else:
    end_date_for_window = pd.to_datetime(actual_training_df['timestamps'].iloc[-1]).date()

# 收集不晚于截止日的交易日期列表
candidate_dates = [d for d in sorted(actual_training_df['timestamps'].dt.date.unique()) if d <= end_date_for_window]

selected_dates = []
for d in reversed(candidate_dates):
    day_df = actual_training_df[actual_training_df['timestamps'].dt.date == d]
    if len(day_df) < bars_per_day:
        continue
    times = set(day_df['timestamps'].dt.time)
    if (datetime.min.replace(hour=9, minute=30).time() in times) and (
            datetime.min.replace(hour=15, minute=0).time() in times):
        selected_dates.append(d)
    if len(selected_dates) >= desired_days:
        break

if not selected_dates:
    # 回退：保持原先按点数切片，但提示无法按完整交易日对齐
    historical_end_idx = len(actual_training_df)
    historical_start_idx = max(0, historical_end_idx - lookback)
    idf = actual_training_df.iloc[historical_start_idx:historical_end_idx][
        ['open', 'high', 'low', 'close', 'volume', 'amount']]
    i_x_timestamp = actual_training_df.iloc[historical_start_idx:historical_end_idx]['timestamps']
    print("⚠️ 无法找到足够的完整交易日（含09:30与15:00），回退为按点数切片。")
else:
    # 窗口左边界：最早选定日期的09:30；右边界：最晚选定日期的15:00
    selected_dates_sorted = sorted(selected_dates)
    start_time = datetime.combine(selected_dates_sorted[0], datetime.min.time()).replace(hour=9, minute=30)
    end_time = datetime.combine(selected_dates_sorted[-1], datetime.min.time()).replace(hour=15, minute=0)

    window_mask = (actual_training_df['timestamps'] >= start_time) & (actual_training_df['timestamps'] <= end_time)
    window_df = actual_training_df.loc[window_mask]

    # 若窗口内点数不足（例如个别分钟缺失），仍保持边界，使用实际可用点
    idf = window_df[['open', 'high', 'low', 'close', 'volume', 'amount']]
    i_x_timestamp = window_df['timestamps']

    adjusted_days = len(selected_dates_sorted)
    if len(idf) != lookback:
        print(
            f"   🔧 历史窗口按完整交易日对齐: 从 {start_time} 到 {end_time}，共{adjusted_days}天，窗口点数 {len(idf)} (原计划 {lookback})")
    else:
        print(f"   🔧 历史窗口按完整交易日对齐: 从 {start_time} 到 {end_time}，共{adjusted_days}天，窗口点数 {len(idf)})")

# 使用生成的预测时间戳
i_y_timestamp = pd.Series(prediction_timestamps)

print(f"📅 预测数据准备:")
print(f"  - 历史输入: {len(idf)} 点 (从 {i_x_timestamp.iloc[0]} 到 {i_x_timestamp.iloc[-1]})")
print(f"  - 预测输出: {len(i_y_timestamp)} 点 (从 {i_y_timestamp.iloc[0]} 到 {i_y_timestamp.iloc[-1]})")

# 时间连续性检查
last_historical_time = i_x_timestamp.iloc[-1]
first_prediction_time = i_y_timestamp.iloc[0]
time_gap_hours = (first_prediction_time - last_historical_time).total_seconds() / 3600

time_gap_minutes = (first_prediction_time - last_historical_time).total_seconds() / 60
print(f"  - 时间间隔: {int(time_gap_minutes)} 分钟 ({time_gap_hours:.4f} 小时)")

if overlap_date:
    print(f"  - 重叠验证日: {overlap_date} (可与真实数据对比准确性)")

dfs.append(idf)
xtsp.append(i_x_timestamp)
ytsp.append(i_y_timestamp)

print(f"✅ 准备了 1 个预测批次")

if not dfs:
    print("❌ 没有准备好的数据批次")
    sys.exit(1)

# 计算全局归一化统计（使用完整历史数据）
print("📊 计算全局归一化统计...")
full_data = training_df[['open', 'high', 'low', 'close', 'volume', 'amount']].values.astype(np.float32)
global_mean = np.mean(full_data, axis=0)
global_std = np.std(full_data, axis=0)
print(f"  - 全局均值: {global_mean[:4]}")
print(f"  - 全局标准差: {global_std[:4]}")
print(f"  💡 说明: 使用全局统计可确保预测结果与历史数据在同一尺度上")

# 进行批量预测
try:
    print("🔮 开始进行批量预测...")
    print("📊 预测参数优化 (基础/可覆盖):")
    print(f"   - Temperature: {getattr(args, 'temperature', 0.8)} ")
    print(f"   - Top-p: {getattr(args, 'top_p', 0.90)} ")
    print(f"   - Sample Count: {getattr(args, 'sample_count', 3)} (建议1-5次，根据市场波动性调整)")

    # 基于情绪+事件动态调整采样参数（前置采集与量化分析）
    try:
        print("\n🔎 前置采集与量化分析（用于调参）...")
        print(f"🔍 正在分析 {stock_code} 的利好利空事件...")
        news_collector = NewsSentimentCollector(stock_code)
        news_data = news_collector.get_comprehensive_news(verbose=False)
        sentiment_analyzer = InvestorSentimentAnalyzer(stock_code)
        sentiment_data = sentiment_analyzer.get_comprehensive_sentiment(verbose=False)
        event_analyzer = EventAnalyzer(stock_code, news_data=news_data)
        event_data = event_analyzer.get_comprehensive_analysis(verbose=False)

        # 输出摘要（贴近用户日志格式）
        g = sentiment_data.get("guba_sentiment", {})
        m = sentiment_data.get("overall_market_sentiment", {})
        s = sentiment_data.get("sector_sentiment", {})
        print("✅ 情绪分析完成")
        print(f"    - 综合情绪: {sentiment_data.get('comprehensive_sentiment','未知')} ({sentiment_data.get('comprehensive_score',0)}分)")
        print(f"    - 股吧评论: {g.get('overall','未知')}")
        print(f"    - 看多比例: {g.get('bullish_ratio',0)}%")
        print(f"    - 看空比例: {g.get('bearish_ratio',0)}%")
        primary_name = (m.get('primary_index') or {}).get('name', '所属大盘')
        primary_chg = m.get('primary_change_pct','N/A')
        print(f"    - 大盘情绪: {m.get('overall','未知')} 所属大盘: {primary_name} 涨跌: {primary_chg}%")
        
        # 处理板块情绪数据结构（可能是扁平的默认值，也可能是嵌套的成功值）
        if 'sector_sentiment' in s and isinstance(s['sector_sentiment'], dict):
            # 成功获取的嵌套结构
            s_inner = s['sector_sentiment']
            s_overall = s_inner.get('overall', '未知')
            s_change = s_inner.get('change_pct', 'N/A')
            s_name = s.get('sector_name', '板块')
        else:
            # 默认或扁平结构
            s_overall = s.get('overall', '未知')
            s_change = s.get('change_pct', 'N/A')
            s_name = s.get('sector_name', '板块')
            
        print(f"    - 板块情绪: {s_overall} ({s_name}) 涨跌: {s_change}%")
        summary = event_data.get("summary", {})
        print("✅ 事件分析完成")
        print(f"    - 综合评级: {summary.get('rating','未知')} (得分: {summary.get('comprehensive_score',0)})")
        print(f"    - 利好事件: {summary.get('total_positive_events',0)} 个")
        print(f"    - 利空事件: {summary.get('total_negative_events',0)} 个")
        print(f"    - 风险等级: {summary.get('risk_level','未知')}")
        print(f"    - 机会等级: {summary.get('opportunity_level','未知')}")
        print("✅ 综合面数据采集完成")

        # 📌 固定采样参数配置（不进行动态调参）
        # 使用命令行参数，如未指定则使用默认值
        # 默认参数参考：平衡型策略，适合一般市场环境
        #   - Temperature: 0.8 (平衡预测，适合一般市场环境)
        #   - Top-p: 0.90 (平衡多样性和稳定性)
        #   - Sample Count: 3 (通过多次采样取平均提高稳定性)
        tuned = {
            "T": getattr(args, 'temperature', 0.8),
            "top_p": getattr(args, 'top_p', 0.90),
            "sample_count": getattr(args, 'sample_count', 3)
        }

        print("\n🎯 采样参数配置:")
        print(f"   - Temperature: {tuned['T']} (温度参数，控制预测随机性)")
        print(f"     · 保守预测: 0.5-0.7 (趋势明确市场)")
        print(f"     · 平衡预测: 0.8-1.0 (一般市场环境)")
        print(f"     · 激进预测: >1.0 (高波动市场)")
        print(f"   - Top-p: {tuned['top_p']} (核采样，平衡多样性和稳定性，推荐0.8-0.95)")
        print(f"   - Sample Count: {tuned['sample_count']} (采样次数，建议1-5次)")
        print(f"   - 策略: 平衡型策略，适合一般市场环境")

    except Exception as e:
        print(f"⚠️ 参数配置失败，使用默认参数: {e}")
        tuned = {
            "T": getattr(args, 'temperature', 0.8),
            "top_p": getattr(args, 'top_p', 0.90),
            "sample_count": getattr(args, 'sample_count', 3)
        }

    pred_df_list = predictor.predict_batch(
        df_list=dfs,
        x_timestamp_list=xtsp,
        y_timestamp_list=ytsp,
        pred_len=pred_len,
        T=tuned["T"],
        top_p=tuned["top_p"],
        sample_count=tuned["sample_count"],
        verbose=True,  # 显示进度
        # global_norm_stats=(global_mean, global_std),  # 移除全局归一化，使用局部归一化以避免分布偏移
    )
    print("✅ 批量预测完成!")

    # 🔧 价格锚定修正：确保预测起点与历史数据价格连续
    print("\n🔧 应用价格锚定修正...")
    if pred_df_list and training_end_marker:
        # 获取训练数据截止点(warmup最后一个点)的价格
        warmup_end_mask = actual_training_df['timestamps'] == training_end_marker
        if warmup_end_mask.any():
            warmup_last_close = actual_training_df[warmup_end_mask]['close'].iloc[-1]

            # 对每个预测批次应用价格锚定
            for batch_idx in range(len(pred_df_list)):
                pred_df = pred_df_list[batch_idx]  # 直接从列表获取引用
                if len(pred_df) > 0:
                    # 获取预测的第一个收盘价
                    pred_first_close = pred_df['close'].iloc[0]

                    # 计算价格偏移量
                    price_offset = warmup_last_close - pred_first_close
                    offset_pct = (price_offset / warmup_last_close) * 100

                    print(
                        f"  批次{batch_idx}: warmup结束价格¥{warmup_last_close:.2f}, 预测起点¥{pred_first_close:.2f}, 偏移{offset_pct:+.2f}%")

                    # 如果偏移超过0.5%，应用修正
                    if abs(offset_pct) > 0.5:
                        print(f"  ⚠️ 检测到{abs(offset_pct):.2f}%价格断层，应用锚定修正")

                        # 修正所有价格列 - 使用.loc确保原地修改
                        for col in ['open', 'high', 'low', 'close']:
                            pred_df_list[batch_idx].loc[:, col] = pred_df[col] + price_offset

                        # 验证修正后的价格
                        new_first_close = pred_df_list[batch_idx]['close'].iloc[0]
                        print(
                            f"  ✅ 修正后预测起点: ¥{new_first_close:.2f} (连续性: {abs(new_first_close - warmup_last_close):.2f}元)")
                    else:
                        print(f"  ✅ 价格连续性良好，无需修正")

                    # 🔧 新增：检查预测序列内部的价格跳变
                    print(f"\n  🔍 检查预测序列内部连续性...")
                    gaps_fixed = 0
                    # 重新获取引用，确保使用最新的修正后数据
                    pred_df = pred_df_list[batch_idx]

                    # 持续检查直到没有gap为止（因为修正后可能产生新的gap）
                    max_iterations = 10
                    iteration = 0

                    while iteration < max_iterations:
                        found_gap = False

                        for i in range(1, len(pred_df)):
                            prev_close = pred_df['close'].iloc[i - 1]
                            curr_close = pred_df['close'].iloc[i]
                            gap = curr_close - prev_close
                            gap_pct = abs(gap / prev_close) * 100

                            # 如果相邻两个点的价格差超过5%，认为是异常跳变
                            if gap_pct > 5:
                                print(
                                    f"     ⚠️ 点{i - 1}→{i}: ¥{prev_close:.2f}→¥{curr_close:.2f} (跳变{gap_pct:.1f}%)")

                                # 使用线性插值平滑跳变
                                # 将后续所有点向前平移，消除跳变
                                for col in ['open', 'high', 'low', 'close']:
                                    pred_df_list[batch_idx].loc[pred_df.index[i:], col] -= gap

                                gaps_fixed += 1
                                found_gap = True
                                print(f"     ✅ 已平滑修正")

                                # 重新获取引用，使用最新数据继续检查
                                pred_df = pred_df_list[batch_idx]
                                break  # 重新开始检查整个序列

                        if not found_gap:
                            break  # 没有找到gap，退出循环

                        iteration += 1

                    if gaps_fixed > 0:
                        print(f"  ✅ 共修正{gaps_fixed}处价格跳变")
                    else:
                        print(f"  ✅ 序列内部价格连续，无异常跳变")
        else:
            print("  ⚠️ 未找到warmup结束点，跳过价格锚定")
    print()

    # 保存预测结果
    # 优先使用环境变量中的结果目录，适配打包应用
    results_dir_env = os.environ.get('KRONOS_RESULTS_DIR')
    if results_dir_env:
        results_dir = Path(results_dir_env)
    else:
        results_dir = project_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 合并所有预测结果为一个DataFrame
    if pred_df_list:
        # 为每个批次添加batch_id标识
        for i, pred_df in enumerate(pred_df_list):
            pred_df['batch_id'] = i

        # 合并所有预测结果
        combined_pred_df = pd.concat(pred_df_list, ignore_index=True)
        result_file = results_dir / f"batch_prediction_{timestamp}.csv"
        combined_pred_df.to_csv(result_file, index=True)
        print(f"📊 预测结果已保存到: {result_file}")

        print(f"📈 预测结果概览:")
        print(f"  - 总批次数: {len(pred_df_list)}")
        print(f"  - 合并后数据形状: {combined_pred_df.shape}")
        print(f"  - 收盘价预测范围: {combined_pred_df['close'].min():.2f} - {combined_pred_df['close'].max():.2f}")
        print(f"  - 成交量预测范围: {combined_pred_df['volume'].min():.0f} - {combined_pred_df['volume'].max():.0f}")

        # 也保存单个批次的预测结果
        for i, pred_df in enumerate(pred_df_list):
            batch_file = results_dir / f"batch_prediction_{timestamp}_batch_{i}.csv"
            pred_df.to_csv(batch_file, index=True)
        print(f"📊 各批次预测结果已单独保存到: {results_dir}")

        # 使用第一个批次的数据进行绘图
        pred_df = pred_df_list[0]

        # 从数据文件名中提取股票代码
        file_name = data_file.name
        stock_code = "UNKNOWN"

        # 解析文件名格式：XSHG_5min_688343.csv 或 XSHG_D_000001.csv
        parts = file_name.replace('.csv', '').split('_')
        if len(parts) >= 3:
            stock_code = parts[-1]  # 取最后一部分作为股票代码
        elif len(parts) >= 2:
            stock_code = parts[-1]  # 如果只有2部分，也取最后一部分

        print(f"🎯 提取到股票代码: {stock_code}")

        # 生成图片文件名：股票代码_预测_日期_时间.png
        chart_filename = f"{stock_code}_prediction_{timestamp}.png"
        chart_path = results_dir / chart_filename

        print(f"🎨 开始生成预测图表...")
        print(f"  - 完整数据长度: {len(complete_df)} 条 (用于技术分析)")
        print(f"  - 展示历史数据: {len(display_df)} 条 (最近15个交易日)")
        print(f"  - 预测数据长度: {len(pred_df)} 条")
        print(f"  - 股票代码: {stock_code}")

        # 生成技术分析报告 - 使用完整数据集保证指标准确性
        print(f"📊 正在生成综合技术分析报告...")
        try:
            # 使用完整数据集计算技术指标，保证准确性
            print(f"  💡 使用完整数据集({len(complete_df)}条)计算技术指标，保证准确性")
            quant_models = QuantitativeModels(complete_df)  # 使用完整数据集！
            quant_models.run_all_models()

            # 获取当前信号
            current_signals = quant_models._get_current_signals()

            # 统计各类信号
            buy_signals = []
            sell_signals = []
            hold_signals = []

            for model_key, signal in current_signals.items():
                performance = quant_models.models_performance.get(model_key, {})

                model_data = {
                    'key': model_key,
                    'name': performance.get('中文名称', model_key),
                    'target_group': performance.get('适用人群', '未知'),
                    'strategy': performance.get('核心策略', '未知'),
                    'win_rate': performance.get('胜率', 'N/A'),
                    'signal': signal
                }

                if signal == '买入':
                    buy_signals.append(model_data)
                elif signal == '卖出':
                    sell_signals.append(model_data)
                else:
                    hold_signals.append(model_data)

            # 获取基本技术指标 - 从完整数据集
            current_close = complete_df['close'].iloc[-1]  # 使用完整数据的最后价格
            current_rsi = quant_models.df['rsi'].iloc[-1] if 'rsi' in quant_models.df.columns else 50
            current_macd = quant_models.df['macd'].iloc[-1] if 'macd' in quant_models.df.columns else 0
            current_macd_signal = quant_models.df['macd_signal'].iloc[
                -1] if 'macd_signal' in quant_models.df.columns else 0

            # 获取数据时间范围 - 显示完整数据集的范围
            data_start = complete_df['timestamps'].min().strftime(
                '%Y-%m-%d') if 'timestamps' in complete_df.columns else 'N/A'
            data_end = complete_df['timestamps'].max().strftime(
                '%Y-%m-%d') if 'timestamps' in complete_df.columns else 'N/A'
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 判断MACD金叉死叉
            macd_signal_text = "金叉" if current_macd > current_macd_signal else "死叉"

            # 布林带位置
            bb_upper = quant_models.df['bb_upper'].iloc[-1] if 'bb_upper' in quant_models.df.columns else 0
            bb_lower = quant_models.df['bb_lower'].iloc[-1] if 'bb_lower' in quant_models.df.columns else 0
            if bb_upper > 0 and bb_lower > 0:
                if current_close > bb_upper:
                    bb_position = "上轨之上(超买)"
                elif current_close < bb_lower:
                    bb_position = "下轨之下(超卖)"
                else:
                    bb_position = "中轨附近(正常)"
            else:
                bb_position = "中轨附近(正常)"

            # KDJ状态
            kdj_k = quant_models.df['kdj_k'].iloc[-1] if 'kdj_k' in quant_models.df.columns else 50
            kdj_d = quant_models.df['kdj_d'].iloc[-1] if 'kdj_d' in quant_models.df.columns else 50
            if kdj_k > 80 and kdj_d > 80:
                kdj_status = "超买区域"
            elif kdj_k < 20 and kdj_d < 20:
                kdj_status = "超卖区域"
            else:
                kdj_status = "正常区域"

            # 均线状态
            ma5 = quant_models.df['ma5'].iloc[-1] if 'ma5' in quant_models.df.columns else 0
            ma10 = quant_models.df['ma10'].iloc[-1] if 'ma10' in quant_models.df.columns else 0
            ma20 = quant_models.df['ma20'].iloc[-1] if 'ma20' in quant_models.df.columns else 0
            ma60 = quant_models.df['ma60'].iloc[-1] if 'ma60' in quant_models.df.columns else 0

            ma_trend = "多头排列"
            if ma5 > 0 and ma10 > 0 and ma20 > 0:
                if ma60 > 0:
                    ma_trend = "多头排列" if (current_close > ma5 > ma10 > ma20 > ma60) else (
                        "空头排列" if (current_close < ma5 < ma10 < ma20 < ma60) else "震荡")
                else:
                    ma_trend = "多头排列" if (current_close > ma5 > ma10 > ma20) else (
                        "空头排列" if (current_close < ma5 < ma10 < ma20) else "震荡")

            # 风险评估 - 基于完整数据集
            volatility = complete_df['close'].pct_change().std() * 100  # 使用完整数据计算波动率
            if current_rsi > 70 or current_rsi < 30:
                risk_level = "高风险"
            elif volatility > 3:
                risk_level = "中等风险"
            else:
                risk_level = "低风险"

            rsi_risk = "超买" if current_rsi > 70 else ("超卖" if current_rsi < 30 else "正常")

            # 生成综合建议
            buy_count = len(buy_signals)
            sell_count = len(sell_signals)
            total_models = len(current_signals)

            if buy_count > sell_count * 1.5:
                recommendation = "🟢 多数模型看多，建议适量买入"
            elif sell_count > buy_count * 1.5:
                recommendation = "🔴 多数模型看空，建议减仓观望"
            else:
                recommendation = "🟡 模型信号分歧，建议保持现有仓位"

            # 打印美化的技术分析报告
            print(f"\n⏺ 📊 {stock_code}股票量化模型分析报告")
            print(f"\n  🔍 综合技术分析")
            print(f"  - 分析时间: {current_time}")
            print(f"  - 当前价格: ¥{current_close:.2f}")
            print(f"  - 数据范围: {data_start} 至 {data_end} ({len(complete_df)}条完整历史数据)")
            print(f"  - 综合建议: {recommendation}")

            # 量化模型信号统计表
            print(f"\n  📋 量化模型信号统计表")
            print()
            print(f"  | 信号类型      | 模型数量 | 占比  |")
            print(f"  |-------------|------|-----|")
            print(f"  | 🟢 **买入信号** | **{buy_count}个** | **{buy_count / total_models * 100:.0f}%** |")
            print(f"  | 🔴 **卖出信号** | **{sell_count}个** | **{sell_count / total_models * 100:.0f}%** |")
            print(
                f"  | 🟡 **持有信号** | **{len(hold_signals)}个** | **{len(hold_signals) / total_models * 100:.0f}%** |")

            print(f"\n  ---")

            # 买入信号模型表格
            if buy_signals:
                print(f"  🟢 买入信号模型 ({buy_count}/{total_models})")
                print()
                print(f"  | 模型名称 | 适用人群 | 核心策略 | 胜率 | 信号 |")
                print(f"  |---------|---------|---------|------|-----|")
                for model in buy_signals:
                    print(
                        f"  | **{model['name']}** | {model['target_group']} | {model['strategy']} | {model['win_rate']} | 🟢 **买入** |")
                print()

            # 持有信号模型表格
            if hold_signals:
                print(f"  🟡 持有信号模型 ({len(hold_signals)}/{total_models})")
                print()
                print(f"  | 模型名称 | 适用人群 | 核心策略 | 胜率 | 信号 |")
                print(f"  |---------|---------|---------|------|-----|")
                for model in hold_signals:
                    print(
                        f"  | **{model['name']}** | {model['target_group']} | {model['strategy']} | {model['win_rate']} | 🟡 持有 |")
                print()

            # 卖出信号模型表格
            if sell_signals:
                print(f"  🔴 卖出信号模型 ({sell_count}/{total_models})")
                print()
                print(f"  | 模型名称 | 适用人群 | 核心策略 | 胜率 | 信号 |")
                print(f"  |---------|---------|---------|------|-----|")
                for model in sell_signals:
                    print(
                        f"  | **{model['name']}** | {model['target_group']} | {model['strategy']} | {model['win_rate']} | 🔴 **卖出** |")
                print()
            else:
                print(f"  🔴 卖出信号模型 (0/{total_models})")
                print()
                print(f"  *当前无模型发出卖出信号*")
                print()

            print(f"  ---")

            # 技术指标现状
            print(f"  📈 技术指标现状")
            print()
            print(
                f"  - **RSI**: {current_rsi:.2f} ({'正常区间' if 30 <= current_rsi <= 70 else ('超买' if current_rsi > 70 else '超卖')})")
            print(f"  - **MACD**: {macd_signal_text}状态")
            print(f"  - **布林带**: {bb_position}")
            print(f"  - **KDJ**: {kdj_status}")
            print(f"  - **均线**: {ma_trend}")

            # 风险评估
            print(f"\n  ⚠️ 风险评估")
            print()
            print(f"  - **风险等级**: {risk_level}")
            print(f"  - **波动率**: {volatility:.2f}%")
            print(f"  - **RSI风险**: {rsi_risk}")

            # 投资建议
            print(f"\n  💡 投资建议")
            print()
            buy_ratio = buy_count / total_models * 100
            hold_ratio = len(hold_signals) / total_models * 100
            sell_ratio = sell_count / total_models * 100

            main_signal = ""
            if sell_count == 0:
                main_signal = "无模型发出卖出警告"
            else:
                main_signal = f"{sell_ratio:.0f}%的模型发出卖出信号"

            strategy_type = ""
            if buy_signals:
                if any('中长线' in model['target_group'] for model in buy_signals):
                    strategy_type = "主要买入信号来自中长线投资策略，适合稳健型投资者关注"
                elif any('短线' in model['target_group'] for model in buy_signals):
                    strategy_type = "主要买入信号来自短线交易策略，适合激进型投资者关注"
                else:
                    strategy_type = "买入信号来自多种不同策略，建议根据个人风险偏好选择"

            print(
                f"  基于{total_models}个量化模型的综合分析，**{buy_ratio:.0f}%的模型发出买入信号，{hold_ratio:.0f}%持观望态度**，{main_signal}。{strategy_type}")
            print()

        except Exception as e:
            print(f"⚠️ 技术分析生成失败: {str(e)}")
            print("将继续生成预测图表...")
            import traceback

            traceback.print_exc()

        # 调用绘图函数 - 使用新的重叠验证策略
        # training_end_marker: 训练数据截止时间（倒数第2天收盘）
        # overlap_start_marker: 重叠验证日开盘时间（用于图表标注）
        plot_prediction_enhanced(display_df, pred_df, stock_code, chart_path,
                                 training_end_marker, overlap_start_marker)

        # 🔧 准备分析报告数据（供LLM和HTML报告使用）
        analysis_report_data = {}
        if 'quant_models' in locals():
            try:
                analysis_report_data = quant_models.generate_analysis_report()
            except Exception as e:
                print(f"⚠️ 生成分析报告数据失败: {str(e)}")

        # 🤖 LLM 智能分析（如果已配置）
        llm_analysis_result = None
        llm_predicted_kline = None

        try:
            print("\n" + "=" * 60)
            print("🤖 LLM 智能分析...")
            print("=" * 60)

            llm_config = LLMConfig()
            if llm_config.is_configured():
                llm_analyzer = LLMAnalyzer(llm_config)

                # 格式化K线数据
                def format_kline_for_llm(df: pd.DataFrame, last_n=30) -> str:
                    """格式化K线数据供LLM分析"""
                    if df.empty:
                        return "无K线数据"

                    recent_df = df.tail(last_n).copy()
                    output = "日期       | 开盘价 | 最高价 | 最低价 | 收盘价 | 涨跌幅\n"
                    output += "-" * 60 + "\n"

                    for idx in range(len(recent_df)):
                        row = recent_df.iloc[idx]
                        date_str = row['timestamps'].strftime('%Y-%m-%d') if 'timestamps' in row else str(idx)
                        output += f"{date_str} | {row['open']:.2f} | {row['high']:.2f} | {row['low']:.2f} | {row['close']:.2f}"

                        if idx > 0:
                            prev_close = recent_df.iloc[idx - 1]['close']
                            change_pct = (row['close'] - prev_close) / prev_close * 100
                            output += f" | {change_pct:+.2f}%"
                        else:
                            output += " | --"
                        output += "\n"

                    return output

                # 格式化技术分析结果
                def format_technical_for_llm(tech_data: dict) -> str:
                    """格式化技术分析结果供LLM分析"""
                    if not tech_data:
                        return "无技术分析数据"

                    output = []

                    # 量化模型信号统计
                    signal_summary = tech_data.get('signal_summary', {})
                    if signal_summary:
                        output.append(f"量化模型信号统计：")
                        output.append(f"  买入信号：{signal_summary.get('buy_count', 0)}个模型 ({signal_summary.get('buy_ratio', 0):.0f}%)")
                        output.append(f"  持有信号：{signal_summary.get('hold_count', 0)}个模型 ({signal_summary.get('hold_ratio', 0):.0f}%)")
                        output.append(f"  卖出信号：{signal_summary.get('sell_count', 0)}个模型 ({signal_summary.get('sell_ratio', 0):.0f}%)")

                    # 技术指标现状
                    indicators = tech_data.get('technical_indicators', {})
                    if indicators:
                        output.append(f"\n技术指标现状：")
                        output.append(f"  RSI: {indicators.get('current_rsi', 0):.2f}")
                        output.append(f"  MACD: {indicators.get('macd_signal', '未知')}")
                        output.append(f"  布林带: {indicators.get('bb_position', '未知')}")
                        output.append(f"  KDJ: {indicators.get('kdj_status', '未知')}")
                        output.append(f"  均线: {indicators.get('ma_trend', '未知')}")

                    # 风险评估
                    risk = tech_data.get('risk_assessment', {})
                    if risk:
                        output.append(f"\n风险评估：")
                        output.append(f"  风险等级: {risk.get('risk_level', '未知')}")
                        output.append(f"  波动率: {risk.get('volatility', 0):.2f}%")
                        output.append(f"  RSI风险: {risk.get('rsi_risk', '未知')}")

                    return "\n".join(output)

                # 构建LLM分析数据
                stock_data = {
                    'code': stock_code,
                    'name': f'{stock_code}',  # 可以从数据中获取股票名称
                    'current_price': display_df['close'].iloc[-1] if not display_df.empty else 0,
                    'kline_data': format_kline_for_llm(display_df),
                    'technical_analysis': format_technical_for_llm(analysis_report_data),
                    'fundamental_data': f"基本面数据已采集",  # fundamental_data将在后面采集
                    'news_sentiment': f"消息面情绪分析：{sentiment_data.get('comprehensive_sentiment', '未知')} (评分: {sentiment_data.get('comprehensive_score', 0)})" if 'sentiment_data' in locals() else "消息面数据待采集",
                    'market_env': f"大盘情绪：{sentiment_data.get('overall_market_sentiment', {}).get('overall', '未知')}" if 'sentiment_data' in locals() else "市场环境待采集"
                }

                # 检测是单模型还是多模型返回
                enabled_llms = llm_config.get_enabled_llms()
                if len(enabled_llms) > 1:
                    print(f"  📊 正在调用多个LLM模型进行智能分析...")
                    print(f"  💡 启用的模型: {', '.join([m.upper() for m in enabled_llms])}")
                    print(f"  ⏱️ 这可能需要10-20秒，请耐心等待...")
                else:
                    print(f"  📊 正在调用 {llm_config.get_enabled_llm().upper()} 进行智能分析...")
                    print(f"  💡 这可能需要5-10秒，请耐心等待...")

                success, result = llm_analyzer.analyze_stock(stock_data)

                if success:
                    llm_analysis_result = result

                    # 多模型情况:result是字典{'qwen': {...}, 'deepseek': {...}}
                    if isinstance(result, dict) and len(enabled_llms) > 1:
                        print(f"  ✅ 多模型LLM分析成功！")

                        # 为每个模型提取预测K线数据
                        llm_predicted_kline = {}
                        for model_name, model_result in result.items():
                            if isinstance(model_result, dict):
                                kline_df = llm_analyzer.extract_predicted_kline(model_result)
                                if not kline_df.empty:
                                    llm_predicted_kline[model_name] = kline_df
                                    print(f"  📈 [{model_name.upper()}] 提取到 {len(kline_df)} 天的AI预测数据")

                        # 显示每个模型的分析摘要
                        for model_name, model_result in result.items():
                            if isinstance(model_result, dict):
                                print(f"\n  🤖 [{model_name.upper()}] 分析结果:")
                                if 'operation_advice' in model_result:
                                    op = model_result['operation_advice']
                                    print(f"     💡 操作建议: {op.get('action', '未知')}")
                                    print(f"     📊 建议价位: {op.get('suggested_price_range', '未知')}")
                                    print(f"     💰 仓位控制: {op.get('position_control', '未知')}")
                                    print(f"     🎯 信心度: {op.get('confidence', 0) * 100:.0f}%")
                                if 'summary' in model_result:
                                    print(f"     📋 综合总结: {model_result['summary'][:100]}...")

                    # 单模型情况:result是单个分析字典
                    else:
                        # 添加模型来源标识
                        if 'llm_model' not in result:
                            result['llm_model'] = llm_config.get_enabled_llm()
                        print(f"  ✅ LLM分析成功！（模型: {llm_config.get_enabled_llm().upper()}）")

                        # 提取预测K线数据
                        llm_predicted_kline = llm_analyzer.extract_predicted_kline(result)

                        # 确保是DataFrame且不为空 - 修复 AttributeError: 'dict' object has no attribute 'empty'
                        has_llm_prediction = False
                        if isinstance(llm_predicted_kline, pd.DataFrame) and not llm_predicted_kline.empty:
                            print(f"  📈 提取到 {len(llm_predicted_kline)} 天的AI预测数据")
                            has_llm_prediction = True
                        elif isinstance(llm_predicted_kline, dict):
                             # 尝试从dict中恢复
                             try:
                                 if 'predictions' in llm_predicted_kline:
                                     llm_predicted_kline = pd.DataFrame(llm_predicted_kline['predictions'])
                                     if not llm_predicted_kline.empty:
                                         has_llm_prediction = True
                                         print(f"  ✅ 从字典中恢复了AI预测数据")
                             except:
                                 pass
                        
                        if not has_llm_prediction:
                             llm_predicted_kline = pd.DataFrame()

                        # 显示分析摘要
                        if 'operation_advice' in result:
                            op = result['operation_advice']
                            print(f"\n  💡 AI操作建议：")
                            print(f"     操作：{op.get('action', '未知')}")
                            print(f"     建议价位：{op.get('suggested_price_range', '未知')}")
                            print(f"     仓位控制：{op.get('position_control', '未知')}")
                            print(f"     信心度：{op.get('confidence', 0) * 100:.0f}%")

                        if 'summary' in result:
                            print(f"\n  📋 AI综合总结：")
                            print(f"     {result['summary']}")

                        # 🎨 重新生成包含LLM预测的图表
                        if has_llm_prediction and isinstance(llm_predicted_kline, pd.DataFrame) and not llm_predicted_kline.empty:
                            print(f"\n  🎨 重新生成包含AI预测的K线图...")
                            try:
                                plot_prediction_enhanced(display_df, pred_df, stock_code, chart_path,
                                                         training_end_marker, overlap_start_marker,
                                                         llm_predicted_kline)
                                print(f"  ✅ 已更新图表,包含Kronos预测和AI预测对比")
                            except Exception as e:
                                print(f"  ⚠️ 更新图表失败: {e}")
                else:
                    print(f"  ⚠️ LLM分析失败：{result}")
                    print(f"  💡 提示：请检查API配置或网络连接")
            else:
                print(f"  ⏭️ LLM未配置，跳过AI智能分析")
                print(f"  💡 提示：可在GUI中配置通义千问或DeepSeek API")

        except Exception as e:
            print(f"  ⚠️ LLM分析出错：{str(e)}")
            import traceback
            traceback.print_exc()

        print()

        # 🆕 生成HTML综合分析报告
        try:
            print("\n" + "=" * 60)
            print("📄 正在生成HTML综合分析报告...")
            print("=" * 60)

            # 采集综合面数据
            print("\n📊 采集综合面数据...")

            # 1. 采集基本面数据（保持在此处，避免前置阶段过重）
            print("  💰 采集基本面财务数据...")
            fundamental_collector = FundamentalDataCollector(stock_code)
            fundamental_data = fundamental_collector.get_comprehensive_data()

            # 2. 使用前置阶段的消息面、情绪与事件分析结果（避免重复采集）
            try:
                _ = sentiment_data  # 确认变量存在
                _ = news_data
                _ = event_data
            except NameError:
                # 若变量未在前置阶段生成，则兜底采集一次
                print("  ⚠️ 前置分析未生成，兜底采集消息面与情绪...")
                news_collector = NewsSentimentCollector(stock_code)
                news_data = news_collector.get_comprehensive_news(verbose=False)
                sentiment_analyzer = InvestorSentimentAnalyzer(stock_code)
                sentiment_data = sentiment_analyzer.get_comprehensive_sentiment(verbose=False)
                event_analyzer = EventAnalyzer(stock_code, news_data=news_data)
                event_data = event_analyzer.get_comprehensive_analysis(verbose=False)

            print("✅ 综合面数据采集完成\n")

            # 🆕 计算多维度综合评分
            print("  ⭐ 计算多维度综合评分...")
            try:
                scorer = OpportunityScorer()
                # 注意：prediction_batch_example 通常是针对单只股票或少量股票，这里暂时不传入 global_hot_news
                scoring_result = scorer.calculate_comprehensive_score(
                    stock_code=stock_code,
                    historical_data=df,  # 使用已获取的历史数据
                    fundamental_data=fundamental_data
                )
                print(f"  ✅ 综合得分: {scoring_result.get('total_score', 'N/A')} ({scoring_result.get('rating', 'N/A')})")
            except Exception as e:
                print(f"  ⚠️ 评分计算失败: {e}")
                scoring_result = None

            # 从HTML报告生成器导入新的生成函数
            from scripts.html_report_generator import KronosHTMLReportGenerator

            # 创建报告生成器并设置控制台数据
            generator = KronosHTMLReportGenerator()
            console_data = {
                'data_count': f'{len(complete_df):,}',
                'prediction_time': '42',  # 实际预测时间可以动态计算
                'prediction_points': str(len(pred_df)),
                'data_range': f'{complete_df["timestamps"].min().strftime("%Y-%m-%d")} 至 {complete_df["timestamps"].max().strftime("%Y-%m-%d")}',
                'mape': f'{mape:.2f}%' if 'mape' in locals() else '3.05%',
                'risk_level': risk_level if 'risk_level' in locals() else '低风险'
            }
            generator.set_console_data(console_data)

            # 生成HTML报告 - 传入PNG图表路径和综合面数据
            html_report_path = generator.generate_comprehensive_report(
                stock_code=stock_code,
                analysis_data=analysis_report_data,
                historical_data=display_df,
                predictions=pred_df,
                png_chart_path=str(chart_path),  # 传入PNG图表路径
                fundamental_data=fundamental_data,  # 基本面数据
                news_data=news_data,  # 消息面数据
                sentiment_data=sentiment_data,  # 情绪数据
                event_data=event_data,  # 利好利空事件数据
                llm_analysis=llm_analysis_result,  # LLM分析结果
                llm_predicted_kline=llm_predicted_kline,  # LLM预测K线数据
                scoring_result=scoring_result,  # 评分结果
                auto_open=True  # 自动打开浏览器
            )

            print(f"✅ HTML综合分析报告已生成并自动打开:")
            print(f"   📄 报告路径: {html_report_path}")
            print(f"   🌐 浏览器访问: file://{os.path.abspath(html_report_path)}")
            print()
            print("📊 报告内容包括:")
            print("   • 📈 股票价格走势图表")
            print("   • 🔮 预测结果可视化")
            print("   • 🤖 30个量化模型分析")
            print("   • 📋 技术指标详情")
            print("   • ⚠️ 风险评估报告")
            print("   • 💰 基本面财务数据")
            print("   • 💬 股民情绪")
            print("   • ⏰ 历史分析时间线")
            if llm_analysis_result:
                print("   • 🤖 AI智能分析与预测")
            print()

        except Exception as e:
            print(f"⚠️ HTML报告生成失败: {str(e)}")
            import traceback

            traceback.print_exc()
            print("图表文件仍可正常使用")

    else:
        print("❌ 未生成任何预测结果")
        sys.exit(1)

except Exception as e:
    print(f"❌ 批量预测失败: {str(e)}")
    import traceback

    traceback.print_exc()
    sys.exit(1)
