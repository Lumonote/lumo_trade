#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos 预测运行脚本
简化的预测接口，支持单次和批量预测
"""

import sys
import os
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple
import matplotlib.pyplot as plt
import warnings

warnings.filterwarnings('ignore')


# === A股交易日与交易时间工具 ===
def _is_trading_day(dt: datetime) -> bool:
    """判断是否为交易日（周一到周五）"""
    return dt.weekday() < 5


def _is_trading_time(dt: datetime) -> bool:
    """严格判断是否为A股交易时间：9:30-11:30, 13:00-15:00"""
    if not _is_trading_day(dt):
        return False
    time_minutes = dt.hour * 60 + dt.minute
    morning_start = 9 * 60 + 30  # 9:30
    morning_end = 11 * 60 + 30  # 11:30
    afternoon_start = 13 * 60  # 13:00
    afternoon_end = 15 * 60  # 15:00
    return (morning_start <= time_minutes <= morning_end) or (afternoon_start <= time_minutes <= afternoon_end)


def _normalize_to_next_trading_time(dt: datetime) -> datetime:
    """将任意时间归一化到下一个有效的A股交易时间点(5分钟粒度)。"""
    # 跳过周末到下一个交易日
    while dt.weekday() >= 5:
        dt = dt + pd.Timedelta(days=1)

    # 当前日期的关键时间点
    morning_start = dt.replace(hour=9, minute=30, second=0, microsecond=0)
    morning_end = dt.replace(hour=11, minute=30, second=0, microsecond=0)
    afternoon_start = dt.replace(hour=13, minute=0, second=0, microsecond=0)
    afternoon_end = dt.replace(hour=15, minute=0, second=0, microsecond=0)

    # 早于开盘 -> 归一到9:30
    if dt < morning_start:
        return morning_start
    # 上午交易时段内 -> 向上取到最近的5分钟刻度
    if morning_start <= dt <= morning_end:
        # 计算当前时间到9:30的分钟数
        minutes_from_start = (dt - morning_start).total_seconds() / 60
        # 向上取整到下一个5分钟刻度
        next_interval = int((minutes_from_start // 5) + 1) * 5
        normalized = morning_start + pd.Timedelta(minutes=next_interval)
        # 不得超过上午结束，如果超过则跳到下午开始
        if normalized > morning_end:
            return afternoon_start
        return normalized
    # 午休区间 -> 归一到13:00
    if morning_end < dt < afternoon_start:
        return afternoon_start
    # 下午交易时段内 -> 向上取到最近的5分钟刻度
    if afternoon_start <= dt <= afternoon_end:
        # 计算当前时间到13:00的分钟数
        minutes_from_start = (dt - afternoon_start).total_seconds() / 60
        # 向上取整到下一个5分钟刻度
        next_interval = int((minutes_from_start // 5) + 1) * 5
        normalized = afternoon_start + pd.Timedelta(minutes=next_interval)
        # 不得超过下午结束，如果超过则跳到下一个交易日
        if normalized > afternoon_end:
            next_day = dt + pd.Timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day = next_day + pd.Timedelta(days=1)
            return next_day.replace(hour=9, minute=30, second=0, microsecond=0)
        return normalized
    # 已过收盘 -> 下一个交易日9:30
    next_day = dt + pd.Timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day = next_day + pd.Timedelta(days=1)
    return next_day.replace(hour=9, minute=30, second=0, microsecond=0)


def _generate_a_share_pred_timestamps(start_time: pd.Timestamp, total_points: int) -> pd.Series:
    """根据A股交易时间生成指定数量的5分钟预测时间戳，严格排除非交易时段与周末。"""
    timestamps = []
    current = pd.Timestamp(start_time)
    # 从下一个有效交易时间开始
    current = _normalize_to_next_trading_time(current)

    while len(timestamps) < total_points:
        # 如果当前不是交易时间（如11:35、午休、收盘后），归一化到下一个交易时间
        if not _is_trading_time(current):
            current = _normalize_to_next_trading_time(current)
        # 追加当前时间点
        timestamps.append(current)
        # 前进5分钟
        current = current + pd.Timedelta(minutes=5)

    return pd.Series(timestamps, name='timestamps')


# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from model import Kronos, KronosTokenizer, KronosPredictor
    from modelscope import snapshot_download
    from analysis.news_sentiment_collector import NewsSentimentCollector
    from analysis.investor_sentiment import InvestorSentimentAnalyzer
    from analysis.event_analyzer import EventAnalyzer
    from analysis.sampling_tuner import tune_sampling_params

    KRONOS_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  未找到 Kronos 模型库: {e}")
    KRONOS_AVAILABLE = False


class KronosStockPredictor:
    """Kronos股票预测器封装"""

    def __init__(self, model_name: str = "kronos-small", device: str = "cpu"):
        """初始化预测器"""
        self.model_name = model_name
        self.device = device
        self.model = None
        self.tokenizer = None
        self.predictor = None

    def load_model(self):
        """加载Kronos模型和分词器"""
        try:
            if not KRONOS_AVAILABLE:
                print("❌ Kronos模型库不可用")
                print("💡 提示: 请确保已正确安装项目依赖")
                return False

            print(f"🔄 加载Kronos模型: {self.model_name}")

            # 设置模型目录
            model_dir = os.path.join(os.path.dirname(__file__), '..', 'models')

            # 检查本地模型是否存在 - 使用统一的一级目录结构
            from pathlib import Path
            import shutil

            model_dir = Path(model_dir)
            model_dir.mkdir(exist_ok=True)

            # 一级目录结构，直接在models下
            tokenizer_dir = model_dir / "Kronos-Tokenizer-base"
            if self.model_name == "kronos-small":
                model_dir_path = model_dir / "Kronos-small"
                model_model = 'northwind9898/Kronos-small'
            elif self.model_name == "kronos-base":
                model_dir_path = model_dir / "Kronos-base"
                model_model = 'northwind9898/Kronos-base'
            else:
                print(f"❌ 不支持的模型: {self.model_name}")
                return False

            # 优先使用本地模型（一级目录结构），外层已有异常捕获，这里不再嵌套 try
            # 加载分词器
            if tokenizer_dir.exists() and (tokenizer_dir / "config.json").exists():
                print("Found local tokenizer, loading...")
                tokenizer_path = str(tokenizer_dir)
            else:
                # 下载并保存到一级目录
                print("Downloading tokenizer...")
                downloaded_path = snapshot_download('northwind9898/Kronos-Tokenizer-base', cache_dir=str(model_dir))
                # 如果下载路径有嵌套结构，将其移动到一级目录
                if "northwind9898" in downloaded_path:
                    if not tokenizer_dir.exists():
                        shutil.move(downloaded_path, str(tokenizer_dir))
                    tokenizer_path = str(tokenizer_dir)
                else:
                    tokenizer_path = downloaded_path

            # 加载模型
            if model_dir_path.exists() and (model_dir_path / "config.json").exists():
                print("Found local model, loading...")
                model_path = str(model_dir_path)
            else:
                # 下载并保存到一级目录
                print("Downloading model...")
                downloaded_path = snapshot_download(model_model, cache_dir=str(model_dir))
                # 如果下载路径有嵌套结构，将其移动到一级目录
                if "northwind9898" in downloaded_path:
                    if not model_dir_path.exists():
                        shutil.move(downloaded_path, str(model_dir_path))
                    model_path = str(model_dir_path)
                else:
                    model_path = downloaded_path

            # 加载模型
            self.tokenizer = KronosTokenizer.from_pretrained(tokenizer_path)
            self.model = Kronos.from_pretrained(model_path)
            self.predictor = KronosPredictor(self.model, self.tokenizer, device=self.device, max_context=512)

            print("✅ Kronos模型加载成功")
            return True

        except Exception as e:
            print(f"❌ 模型加载失败: {e}")
            return False

    def load_data(self, data_path: str, lookback: int = 400) -> Optional[Tuple[pd.DataFrame, pd.Series, int]]:
        """加载和预处理数据，优先使用最近一年的数据进行预测"""
        try:
            print(f"📊 加载数据: {data_path}")

            # 读取CSV文件
            df = pd.read_csv(data_path)

            # 检查必要列
            required_cols = ['timestamps', 'open', 'high', 'low', 'close', 'volume', 'amount']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                # 尝试使用timestamp列
                if 'timestamp' in df.columns:
                    df = df.rename(columns={'timestamp': 'timestamps'})
                    missing_cols = [col for col in required_cols if col not in df.columns]

                if missing_cols:
                    print(f"❌ 缺少必要列: {missing_cols}")
                    print(f"可用列: {list(df.columns)}")
                    return None

            # 转换时间戳
            df['timestamps'] = pd.to_datetime(df['timestamps'])
            df = df.sort_values('timestamps').reset_index(drop=True)

            # 过滤非交易时段，仅保留A股有效交易时间点（9:30-11:30, 13:00-15:00）
            try:
                mask_trading = df['timestamps'].apply(lambda ts: _is_trading_time(ts.to_pydatetime()))
                before_len = len(df)
                df = df[mask_trading].reset_index(drop=True)
                after_len = len(df)
                removed = before_len - after_len
                if removed > 0:
                    print(f"🧹 已过滤非交易时段数据: 移除 {removed} 行，保留 {after_len} 行")
                else:
                    print("🧹 数据已在交易时段内，无需过滤")
            except Exception as e:
                print(f"⚠️  交易时段过滤失败: {e}")

            # 智能选择数据范围：优先使用最近一年的数据
            # 计算一年的数据点数（已过滤非交易时间）
            # 一年约250个交易日 × 50个数据点/交易日 = 12,500个数据点
            one_year_points = 12500

            # 如果数据足够，优先使用最近一年的数据
            if len(df) >= one_year_points:
                optimal_lookback = one_year_points
                print(f"📈 数据充足，使用最近一年数据进行预测 ({optimal_lookback} 个数据点)")
            elif len(df) >= lookback:
                # 如果数据不足一年但超过默认lookback，使用所有可用数据
                optimal_lookback = len(df)
                print(f"📊 使用所有可用数据进行预测 ({optimal_lookback} 个数据点)")
            else:
                print(f"❌ 数据长度不足: {len(df)} < {lookback}")
                return None

            # 使用最近的数据点
            start_idx = len(df) - optimal_lookback
            end_idx = len(df)

            # 准备输入数据
            x_df = df.loc[start_idx:end_idx - 1, ['open', 'high', 'low', 'close', 'volume', 'amount']].reset_index(
                drop=True)
            x_timestamp = df.loc[start_idx:end_idx - 1, 'timestamps'].reset_index(drop=True)

            # 计算时间范围
            time_range = f"{x_timestamp.iloc[0].strftime('%Y-%m-%d')} 至 {x_timestamp.iloc[-1].strftime('%Y-%m-%d')}"

            print(f"✅ 数据加载成功: 总数据 {len(df)} 行, 使用最近 {optimal_lookback} 个数据点")
            print(f"📅 数据时间范围: {time_range}")
            print(f"💰 价格范围: {x_df['close'].min():.2f} - {x_df['close'].max():.2f}")

            # 验证时间间隔是否为5分钟
            try:
                diffs = x_timestamp.diff().dropna().dt.total_seconds() / 60.0
                five_min_ratio = (diffs == 5).mean() if len(diffs) else 1.0
                print(f"⏱️ 时间间隔校验: 5分钟比例 {five_min_ratio:.2%}，样本 {len(diffs)}")
            except Exception as e:
                print(f"⚠️  时间间隔校验失败: {e}")

            return x_df, x_timestamp, len(df)

        except Exception as e:
            print(f"❌ 数据加载失败: {e}")
            return None

    def predict(self, x_df: pd.DataFrame, x_timestamp: pd.Series, pred_len: int = 5, sample_count: int = 1) -> Optional[
        pd.DataFrame]:
        """执行预测"""
        try:
            print(f"🔮 开始预测: 预测长度={pred_len}, 样本数={sample_count}")

            if self.predictor is None:
                print("❌ 模型未加载")
                return None

            # 确保时间戳是Series格式，避免DatetimeIndex的.dt属性错误
            if isinstance(x_timestamp, pd.DatetimeIndex):
                x_timestamp = pd.Series(x_timestamp, name='timestamps')

            # 生成预测时间戳 - 从历史数据的下一个时间点开始
            from datetime import timedelta
            last_timestamp = x_timestamp.iloc[-1]

            print(f"📅 预测数据准备: ")
            print(f"   - 历史输入: {len(x_df)} 点 (从 {x_timestamp.iloc[0]} 到 {last_timestamp}) ")

            # 计算下一个5分钟时间点（将归一化到有效交易时段）
            start_time = last_timestamp + pd.Timedelta(minutes=5)

            # 生成预测时间戳：严格遵守A股交易时间
            # A股交易时间: 9:30-11:30(25个点) + 13:00-15:00(25个点) = 50个点/天
            points_per_day = 50  # 上午25个点 + 下午25个点
            total_pred_points = pred_len * points_per_day
            print(f"   - 预测目标: {pred_len} 天 × {points_per_day} 点/天 = {total_pred_points} 点")

            # 前置：采集与量化分析（用于调参）
            try:
                print("\n🔎 前置采集与量化分析（用于调参）...")
                # 注意：此脚本没有股票代码上下文，尽量从数据文件名推断或用户传入；此处使用环境变量或默认代码
                stock_code = os.environ.get('KRONOS_STOCK_CODE', '未知代码')
                news_collector = NewsSentimentCollector(stock_code)
                news_data = news_collector.get_comprehensive_news(verbose=False)
                sentiment_analyzer = InvestorSentimentAnalyzer(stock_code)
                sentiment_data = sentiment_analyzer.get_comprehensive_sentiment(verbose=False)
                event_analyzer = EventAnalyzer(stock_code, news_data=news_data)
                event_data = event_analyzer.get_comprehensive_analysis(verbose=False)

                # 打印摘要
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
                print(f"    - 板块情绪: {s.get('overall','未知')} ({s.get('sector_name','板块')}) 涨跌: {s.get('change_pct','N/A')}%")
                summary = event_data.get("summary", {})
                print("✅ 事件分析完成")
                print(f"    - 综合评级: {summary.get('rating','未知')} (得分: {summary.get('comprehensive_score',0)})")
                print(f"    - 利好事件: {summary.get('total_positive_events',0)} 个")
                print(f"    - 利空事件: {summary.get('total_negative_events',0)} 个")
                print(f"    - 风险等级: {summary.get('risk_level','未知')}")
                print(f"    - 机会等级: {summary.get('opportunity_level','未知')}")
                print("✅ 综合面数据采集完成")

                tuned = tune_sampling_params(sentiment_data, events_summary=event_data.get("summary"))
                T_val = tuned.get('T', 0.7)
                top_p_val = tuned.get('top_p', 0.90)
                sample_count_val = tuned.get('sample_count', sample_count)
                print("\n🧠 动态采样参数调整:")
                print(f"   - Temperature: {T_val}")
                print(f"   - Top-p: {top_p_val}")
                print(f"   - Sample Count: {sample_count_val}")
                print(f"   - 依据: {tuned.get('reason','未提供')}")
            except Exception as e:
                print(f"⚠️ 前置分析或动态调参失败，使用默认参数: {e}")
                T_val = 1.0
                top_p_val = 0.9
                sample_count_val = sample_count

            pred_timestamps = _generate_a_share_pred_timestamps(start_time, total_pred_points)

            print(
                f"   - 预测输出: {len(pred_timestamps)} 点 (从 {pred_timestamps.iloc[0]} 到 {pred_timestamps.iloc[-1]}) ")

            # 验证预测时间戳的正确性
            if len(pred_timestamps) != total_pred_points:
                print(f"⚠️ 预测时间戳数量不匹配: 期望 {total_pred_points}, 实际 {len(pred_timestamps)}")

            # 确保预测时间戳也是Series格式
            # pred_timestamps 已为Series
            y_timestamp = pred_timestamps

            # 执行分批预测以处理模型限制
            print(f"🔮 开始执行预测，预测长度: {total_pred_points}")

            # 模型的最大上下文长度
            max_context = 512
            batch_size = min(max_context, total_pred_points)

            all_predictions = []
            current_data = x_df.copy()
            current_timestamp = x_timestamp.copy()
            remaining_points = total_pred_points
            current_y_start = 0

            batch_count = 0
            while remaining_points > 0:
                batch_count += 1
                current_batch_size = min(batch_size, remaining_points)
                print(f"📦 预测批次 {batch_count}: {current_batch_size} 个点，剩余: {remaining_points}")

                # 获取当前批次的预测时间戳
                batch_y_timestamp = pred_timestamps[current_y_start:current_y_start + current_batch_size]
                if isinstance(batch_y_timestamp, pd.DatetimeIndex):
                    batch_y_timestamp = pd.Series(batch_y_timestamp, name='timestamps')

                # 预测当前批次
                batch_pred = self.predictor.predict(
                    df=current_data,
                    x_timestamp=current_timestamp,
                    y_timestamp=batch_y_timestamp,
                    pred_len=current_batch_size,
                    T=T_val,
                    top_p=top_p_val,
                    sample_count=sample_count_val,
                    verbose=True
                )

                all_predictions.append(batch_pred)

                # 更新计数器
                remaining_points -= current_batch_size
                current_y_start += current_batch_size

                print(f"批次 {batch_count} 完成，预测了 {len(batch_pred)} 个点")

                # 更新输入数据：保留最后max_context个点，加上新预测的点
                if remaining_points > 0:
                    # 合并历史数据和预测数据
                    combined_data = pd.concat(
                        [current_data, batch_pred[['open', 'high', 'low', 'close', 'volume', 'amount']]])
                    combined_timestamp = pd.concat([current_timestamp, batch_y_timestamp])

                    # 保留最后max_context个点作为下一批次的输入
                    current_data = combined_data.tail(max_context).reset_index(drop=True)
                    current_timestamp = combined_timestamp.tail(max_context).reset_index(drop=True)

                # 防止无限循环
                if batch_count > 10:
                    print("警告：批次数量过多，停止预测")
                    break

            # 合并所有预测结果
            pred_df = pd.concat(all_predictions, ignore_index=True)

            # 将时间戳添加到预测结果中
            if pred_df is not None and len(pred_df) == len(pred_timestamps):
                pred_df['timestamps'] = pred_timestamps.values if hasattr(pred_timestamps,
                                                                          'values') else pred_timestamps
                # 重新排列列顺序，将timestamps放在第一列
                cols = ['timestamps'] + [col for col in pred_df.columns if col != 'timestamps']
                pred_df = pred_df[cols]

            print(f"✅ 预测完成: 生成 {len(pred_df)} 个预测点")

            # 计算并输出量化指标
            self.calculate_and_display_metrics(x_df, pred_df, pred_len)

            return pred_df

        except Exception as e:
            print(f"❌ 预测失败: {e}")
            return None

    def calculate_and_display_metrics(self, x_df: pd.DataFrame, pred_df: pd.DataFrame, pred_len: int):
        """计算并显示量化指标"""
        try:
            print("\n" + "=" * 60)
            print("📊 量化指标分析")
            print("=" * 60)

            # 基础价格信息
            current_price = x_df['close'].iloc[-1]
            current_volume = x_df['volume'].iloc[-1]

            # 预测价格信息（按天分组）
            points_per_day = 50  # A股每天50个5分钟点（上午25个+下午25个）

            for day in range(pred_len):
                start_idx = day * points_per_day
                end_idx = (day + 1) * points_per_day
                day_data = pred_df.iloc[start_idx:end_idx]

                day_label = f"第{day + 1}天"

                # 当日预测统计
                day_open = day_data['close'].iloc[0]
                day_close = day_data['close'].iloc[-1]
                day_high = day_data['high'].max()
                day_low = day_data['low'].min()
                day_volume = day_data['volume'].sum()

                # 价格变化
                price_change = day_close - current_price
                price_change_pct = (price_change / current_price) * 100

                # 日内波动
                intraday_range = day_high - day_low
                intraday_range_pct = (intraday_range / day_open) * 100

                print(f"\n📈 {day_label}预测:")
                print(f"  开盘价: {day_open:.2f}")
                print(f"  收盘价: {day_close:.2f}")
                print(f"  最高价: {day_high:.2f}")
                print(f"  最低价: {day_low:.2f}")
                print(f"  成交量: {day_volume:,.0f}")
                print(f"  价格变化: {price_change:+.2f} ({price_change_pct:+.2f}%)")
                print(f"  日内波动: {intraday_range:.2f} ({intraday_range_pct:.2f}%)")

                # 技术指标
                self.calculate_technical_indicators(day_data, day_label)

            # 历史数据技术指标
            print(f"\n📊 历史数据技术指标:")
            self.calculate_historical_indicators(x_df)

            # 风险评估
            self.calculate_risk_metrics(x_df, pred_df)

        except Exception as e:
            print(f"❌ 量化指标计算失败: {e}")

    def calculate_technical_indicators(self, day_data: pd.DataFrame, day_label: str):
        """计算技术指标"""
        try:
            closes = day_data['close']
            highs = day_data['high']
            lows = day_data['low']
            volumes = day_data['volume']

            # 移动平均线
            if len(closes) >= 20:
                ma5 = closes.rolling(5).mean().iloc[-1]
                ma10 = closes.rolling(10).mean().iloc[-1]
                ma20 = closes.rolling(20).mean().iloc[-1]
                print(f"  MA5: {ma5:.2f}, MA10: {ma10:.2f}, MA20: {ma20:.2f}")

            # RSI
            if len(closes) >= 14:
                delta = closes.diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                print(f"  RSI: {rsi.iloc[-1]:.2f}")

            # 布林带
            if len(closes) >= 20:
                ma20 = closes.rolling(20).mean()
                std20 = closes.rolling(20).std()
                upper_band = ma20 + (std20 * 2)
                lower_band = ma20 - (std20 * 2)
                print(f"  布林带: 上轨{upper_band.iloc[-1]:.2f}, 下轨{lower_band.iloc[-1]:.2f}")

            # 成交量指标
            avg_volume = volumes.mean()
            volume_ratio = volumes.iloc[-1] / avg_volume
            print(f"  成交量比率: {volume_ratio:.2f}")

        except Exception as e:
            print(f"  ⚠️ {day_label}技术指标计算失败: {e}")

    def calculate_historical_indicators(self, x_df: pd.DataFrame):
        """计算历史数据技术指标"""
        try:
            closes = x_df['close']
            highs = x_df['high']
            lows = x_df['low']
            volumes = x_df['volume']

            # 当前价格
            current_price = closes.iloc[-1]

            # 移动平均线
            ma5 = closes.rolling(5).mean().iloc[-1]
            ma10 = closes.rolling(10).mean().iloc[-1]
            ma20 = closes.rolling(20).mean().iloc[-1]
            ma60 = closes.rolling(60).mean().iloc[-1] if len(closes) >= 60 else None

            print(f"  当前价格: {current_price:.2f}")
            print(f"  MA5: {ma5:.2f}, MA10: {ma10:.2f}, MA20: {ma20:.2f}")
            if ma60:
                print(f"  MA60: {ma60:.2f}")

            # 价格相对位置
            price_vs_ma5 = ((current_price - ma5) / ma5) * 100
            price_vs_ma20 = ((current_price - ma20) / ma20) * 100
            print(f"  相对MA5: {price_vs_ma5:+.2f}%, 相对MA20: {price_vs_ma20:+.2f}%")

            # 波动率
            returns = closes.pct_change().dropna()
            volatility = returns.std() * 100
            print(f"  历史波动率: {volatility:.2f}%")

            # 最近涨跌幅
            price_1d = closes.iloc[-2] if len(closes) >= 2 else current_price
            price_5d = closes.iloc[-6] if len(closes) >= 6 else current_price
            price_20d = closes.iloc[-21] if len(closes) >= 21 else current_price

            change_1d = ((current_price - price_1d) / price_1d) * 100
            change_5d = ((current_price - price_5d) / price_5d) * 100
            change_20d = ((current_price - price_20d) / price_20d) * 100

            print(f"  近期涨跌: 1日{change_1d:+.2f}%, 5日{change_5d:+.2f}%, 20日{change_20d:+.2f}%")

        except Exception as e:
            print(f"  ⚠️ 历史指标计算失败: {e}")

    def calculate_risk_metrics(self, x_df: pd.DataFrame, pred_df: pd.DataFrame):
        """计算风险指标"""
        try:
            print(f"\n⚠️ 风险评估:")

            # 历史波动率
            hist_returns = x_df['close'].pct_change().dropna()
            hist_volatility = hist_returns.std() * 100

            # 预测波动率
            pred_returns = pred_df['close'].pct_change().dropna()
            pred_volatility = pred_returns.std() * 100

            print(f"  历史波动率: {hist_volatility:.2f}%")
            print(f"  预测波动率: {pred_volatility:.2f}%")

            # 最大回撤
            hist_cummax = x_df['close'].cummax()
            hist_drawdown = ((x_df['close'] - hist_cummax) / hist_cummax * 100).min()

            pred_cummax = pred_df['close'].cummax()
            pred_drawdown = ((pred_df['close'] - pred_cummax) / pred_cummax * 100).min()

            print(f"  历史最大回撤: {hist_drawdown:.2f}%")
            print(f"  预测最大回撤: {pred_drawdown:.2f}%")

            # 风险等级评估
            if pred_volatility < 2:
                risk_level = "低风险"
            elif pred_volatility < 5:
                risk_level = "中等风险"
            else:
                risk_level = "高风险"

            print(f"  风险等级: {risk_level}")

        except Exception as e:
            print(f"  ⚠️ 风险指标计算失败: {e}")

    def visualize_prediction(self, x_df: pd.DataFrame, x_timestamp: pd.Series, pred_df: pd.DataFrame, pred_len: int,
                             output_dir: Path) -> Path:
        """可视化预测结果 - 展示前15天历史数据+后5天预测数据，确保时间连续性"""
        try:
            print("📊 生成预测图表...")

            # 设置中文字体
            plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False

            # 创建图表
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10))

            # 获取历史数据的最后15天用于显示（而不是5天）
            hist_days = 15
            points_per_day = 50  # A股每天50个5分钟点（上午25个+下午25个）
            hist_points = min(len(x_df), hist_days * points_per_day)

            hist_data = x_df.iloc[-hist_points:]
            hist_timestamp = x_timestamp.iloc[-hist_points:]
            hist_close = hist_data['close']
            hist_volume = hist_data['volume']

            # 从预测结果中获取时间戳
            if 'timestamps' in pred_df.columns:
                pred_timestamp = pd.to_datetime(pred_df['timestamps'])
                print(f"📅 使用预测结果中的时间戳: {len(pred_timestamp)} 个点")
                print(f"   时间范围: {pred_timestamp.iloc[0]} 到 {pred_timestamp.iloc[-1]}")
            else:
                # 如果预测结果中没有时间戳，则生成（这种情况不应该发生）
                print("⚠️ 预测结果中缺少时间戳，重新生成")
                last_timestamp = x_timestamp.iloc[-1]
                # 使用严格的A股交易时间生成预测时间戳
                pred_timestamp = _generate_a_share_pred_timestamps(last_timestamp, len(pred_df))

            # 获取最后一个历史时间戳用于连接点
            last_hist_timestamp = x_timestamp.iloc[-1]
            last_hist_price = x_df['close'].iloc[-1]

            # 检查预测数据与历史数据的时间连续性
            first_pred_timestamp = pred_timestamp.iloc[0]
            time_gap = (first_pred_timestamp - last_hist_timestamp).total_seconds() / 60  # 分钟

            print(f"🔗 时间连续性检查:")
            print(f"   历史数据结束: {last_hist_timestamp}")
            print(f"   预测数据开始: {first_pred_timestamp}")
            print(f"   时间间隔: {time_gap} 分钟")

            # 绘制历史价格数据
            ax1.plot(hist_timestamp, hist_close, label='历史价格', color='#2E86AB', linewidth=2, alpha=0.9)

            # 如果预测数据与历史数据有重叠的交易日，需要特殊处理
            last_hist_date = last_hist_timestamp.date()
            pred_dates = pred_timestamp.dt.date.unique()

            # 检查是否有重叠日期
            overlap_exists = last_hist_date in pred_dates

            if overlap_exists:
                print(f"🔄 检测到重叠交易日: {last_hist_date}")

                # 分离重叠日和未来日的预测数据
                overlap_mask = pred_timestamp.dt.date == last_hist_date
                future_mask = pred_timestamp.dt.date > last_hist_date

                overlap_pred = pred_df[overlap_mask].copy()
                future_pred = pred_df[future_mask].copy()
                overlap_timestamps = pred_timestamp[overlap_mask]
                future_timestamps = pred_timestamp[future_mask]

                # 🔧 关键修正：检查并修复重叠日→未来日的价格断层
                if not overlap_pred.empty and not future_pred.empty:
                    overlap_last_close = overlap_pred['close'].iloc[-1]
                    future_first_close = future_pred['close'].iloc[0]
                    price_gap = future_first_close - overlap_last_close
                    gap_pct = abs(price_gap / overlap_last_close) * 100

                    if gap_pct > 0.5:  # 如果gap超过0.5%，应用修正
                        print(f"  🔧 检测到重叠日→未来日价格断层: {gap_pct:.2f}%，应用修正")
                        print(f"     重叠日终点: ¥{overlap_last_close:.2f} -> 未来日起点: ¥{future_first_close:.2f}")

                        # 修正未来预测数据，确保价格连续性
                        for col in ['open', 'high', 'low', 'close']:
                            pred_df.loc[future_mask, col] = pred_df.loc[future_mask, col] - price_gap

                        # 重新创建修正后的数据
                        future_pred = pred_df[future_mask].copy()

                        # 验证修正效果
                        new_future_first = future_pred['close'].iloc[0]
                        new_gap = abs(new_future_first - overlap_last_close)
                        print(f"  ✅ 修正后:")
                        print(f"     重叠日终点: ¥{overlap_last_close:.2f}")
                        print(f"     未来日起点: ¥{new_future_first:.2f}")
                        print(f"     价格差异: ¥{new_gap:.3f} ({abs(new_gap / overlap_last_close) * 100:.2f}%)")

                # 绘制重叠日的预测数据（用虚线表示对比）
                if not overlap_pred.empty:
                    ax1.plot(overlap_timestamps, overlap_pred['close'],
                             label='重叠日预测对比', color='#F18F01',
                             linewidth=2, linestyle=':', alpha=0.8)

                # 绘制未来预测数据，确保与历史数据平滑连接
                if not future_pred.empty:
                    # 连接线：从历史数据最后一点到未来预测第一点
                    if len(overlap_pred) > 0:
                        # 如果有重叠数据，从重叠数据的最后一点连接
                        connect_price = overlap_pred['close'].iloc[-1]
                        connect_time = overlap_timestamps.iloc[-1]
                    else:
                        # 如果没有重叠数据，从历史数据最后一点连接
                        connect_price = last_hist_price
                        connect_time = last_hist_timestamp

                    # 绘制连接线
                    ax1.plot([connect_time, future_timestamps.iloc[0]],
                             [connect_price, future_pred['close'].iloc[0]],
                             color='#E71D36', linewidth=2, alpha=0.7, linestyle='--')

                    # 绘制未来预测数据
                    ax1.plot(future_timestamps, future_pred['close'],
                             label='未来5天预测', color='#E71D36', linewidth=2, alpha=0.9)
            else:
                # 没有重叠，直接连接历史数据和预测数据
                print("📈 直接连接历史数据和预测数据")

                # 绘制连接线
                ax1.plot([last_hist_timestamp, pred_timestamp.iloc[0]],
                         [last_hist_price, pred_df['close'].iloc[0]],
                         color='#E71D36', linewidth=2, alpha=0.7, linestyle='--')

                # 绘制预测数据
                ax1.plot(pred_timestamp, pred_df['close'],
                         label='未来5天预测', color='#E71D36', linewidth=2, alpha=0.9)

            # 添加预测区域背景
            if len(pred_timestamp) > 0:
                ax1.axvspan(pred_timestamp.iloc[0], pred_timestamp.iloc[-1],
                            alpha=0.1, color='orange', label='预测区域')

            # 添加分界线标记
            ax1.axvline(x=last_hist_timestamp, color='gray', linestyle=':', alpha=0.7, linewidth=1)
            ax1.text(last_hist_timestamp, ax1.get_ylim()[1] * 0.95, '预测开始',
                     rotation=90, verticalalignment='top', alpha=0.7, fontsize=10)

            # 添加每日预测统计标注
            pred_days = min(pred_len, 5)  # 最多显示5天
            colors = ['#E71D36', '#F18F01', '#2E86AB', '#A23B72', '#F18701']

            for day in range(pred_days):
                start_idx = day * points_per_day
                end_idx = min((day + 1) * points_per_day, len(pred_df))

                if start_idx < len(pred_df):
                    day_data = pred_df.iloc[start_idx:end_idx]
                    if not day_data.empty:
                        day_high = day_data['high'].max()
                        day_low = day_data['low'].min()
                        day_close = day_data['close'].iloc[-1]

                        # 在图表上标注每日预测摘要
                        day_timestamps = pred_timestamp[start_idx:end_idx]
                        if len(day_timestamps) > 0:
                            mid_idx = len(day_timestamps) // 2
                            mid_time = day_timestamps.iloc[mid_idx]  # 使用.iloc访问
                            ax1.annotate(f'D{day + 1}: ¥{day_close:.2f}\n↑{day_high:.2f} ↓{day_low:.2f}',
                                         xy=(mid_time, day_high),
                                         xytext=(10, 20), textcoords='offset points',
                                         fontsize=8, color=colors[day % len(colors)],
                                         bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8),
                                         alpha=0.9)

            ax1.set_title(f'Kronos股价预测 - 前15天历史 + 后5天预测 (交叉1天)', fontsize=14, fontweight='bold')
            ax1.set_ylabel('价格 (¥)', fontsize=12)
            ax1.legend(loc='upper left')
            ax1.grid(True, alpha=0.3)

            # 绘制成交量图表
            bar_width = pd.Timedelta(minutes=4)  # 柱状图宽度

            # 历史成交量
            ax2.bar(hist_timestamp, hist_volume, label='历史成交量',
                    color='#2E86AB', alpha=0.6, width=bar_width)

            # 预测成交量
            if overlap_exists and not overlap_pred.empty:
                # 重叠日预测成交量
                ax2.bar(overlap_timestamps, overlap_pred['volume'],
                        label='重叠日预测成交量', color='#F18F01', alpha=0.7, width=bar_width)

                # 未来预测成交量
                if not future_pred.empty:
                    ax2.bar(future_timestamps, future_pred['volume'],
                            label='未来预测成交量', color='#E71D36', alpha=0.7, width=bar_width)
            else:
                # 直接绘制预测成交量
                ax2.bar(pred_timestamp, pred_df['volume'],
                        label='预测成交量', color='#E71D36', alpha=0.7, width=bar_width)

            ax2.axvline(x=last_hist_timestamp, color='gray', linestyle=':', alpha=0.7, linewidth=1)
            ax2.set_title('成交量预测', fontsize=12)
            ax2.set_ylabel('成交量', fontsize=12)
            ax2.set_xlabel('时间', fontsize=12)
            ax2.legend()
            ax2.grid(True, alpha=0.3)

            # 调整布局
            plt.tight_layout()

            # 保存图表
            plot_path = output_dir / "prediction_chart.png"
            plt.savefig(plot_path, dpi=300, bbox_inches='tight', facecolor='white')
            plt.close()

            print(f"✅ 图表已保存: {plot_path}")
            print(f"📊 图表包含: {len(hist_data)}个历史点 + {len(pred_df)}个预测点")
            return plot_path

        except Exception as e:
            print(f"❌ 图表生成失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def save_prediction_results(self, pred_df: pd.DataFrame, output_path: str) -> bool:
        """保存预测结果到CSV"""
        try:
            print(f"💾 保存预测结果: {output_path}")

            # 保存到CSV
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            pred_df.to_csv(output_path, index=False)

            print(f"✅ 预测结果已保存: {len(pred_df)} 行")
            return True

        except Exception as e:
            print(f"❌ 保存结果失败: {e}")
            return False


def find_data_files(data_dir: str = "./data/") -> List[str]:
    """查找可用的数据文件"""
    data_path = Path(data_dir)
    if not data_path.exists():
        return []

    # 查找CSV文件
    csv_files = list(data_path.glob("*.csv"))
    return [str(f) for f in csv_files]


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Kronos预测工具')
    parser.add_argument('--data', '-d', help='数据文件路径')
    parser.add_argument('--model', '-m', default='kronos-small',
                        help='模型名称 (默认: kronos-small, 可选: kronos-base)')
    parser.add_argument('--lookback', '-l', type=int, default=400,
                        help='历史数据长度 (默认: 400)')
    parser.add_argument('--pred-len', '-p', type=int, default=5,
                        help='预测长度 (默认: 5天)')
    parser.add_argument('--samples', '-s', type=int, default=1,
                        help='预测样本数 (默认: 1)')
    parser.add_argument('--output', '-o', help='输出目录 (默认: results/)')
    parser.add_argument('--no-plot', action='store_true', help='不显示图表')
    parser.add_argument('--list-data', action='store_true', help='列出可用数据文件')

    args = parser.parse_args()

    print("🚀 Kronos预测工具启动")
    print("=" * 50)

    # 列出数据文件
    if args.list_data:
        print("📁 可用数据文件:")
        data_files = find_data_files()
        if data_files:
            for i, file in enumerate(data_files, 1):
                print(f"  {i:2d}. {file}")
        else:
            print("  未找到数据文件")
        return 0

    # 检查数据文件
    if not args.data:
        # 自动查找数据文件
        data_files = find_data_files()
        if not data_files:
            print("❌ 未找到数据文件，请使用 --data 指定或运行 --list-data 查看可用文件")
            return 1

        if len(data_files) == 1:
            args.data = data_files[0]
            print(f"📊 自动选择数据文件: {args.data}")
        else:
            print("📁 发现多个数据文件:")
            for i, file in enumerate(data_files, 1):
                print(f"  {i:2d}. {file}")

            while True:
                try:
                    choice = int(input("\n请选择文件序号: ")) - 1
                    if 0 <= choice < len(data_files):
                        args.data = data_files[choice]
                        break
                    else:
                        print("❌ 无效选择")
                except (ValueError, KeyboardInterrupt):
                    print("\n❌ 操作取消")
                    return 1

    if not Path(args.data).exists():
        print(f"❌ 数据文件不存在: {args.data}")
        return 1

    # 设置输出目录
    if not args.output:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.output = f"results/prediction_{timestamp}"

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"📊 数据文件: {args.data}")
    print(f"🤖 模型: {args.model}")
    print(f"📈 预测参数: lookback={args.lookback}, pred_len={args.pred_len}, samples={args.samples}")
    print(f"📁 输出目录: {output_dir}")
    print("=" * 50)

    # 初始化预测器
    predictor = KronosStockPredictor(args.model)

    # 加载模型
    if not predictor.load_model():
        return 1

    # 加载数据
    data_result = predictor.load_data(args.data, args.lookback)
    if data_result is None:
        return 1

    x_df, x_timestamp, data_len = data_result

    # 执行预测
    pred_df = predictor.predict(x_df, x_timestamp, args.pred_len, args.samples)
    if pred_df is None:
        return 1

    # 保存预测结果
    csv_path = output_dir / "prediction_results.csv"
    predictor.save_prediction_results(pred_df, str(csv_path))

    # 生成可视化
    plot_path = predictor.visualize_prediction(x_df, x_timestamp, pred_df, args.pred_len, output_dir)

    # 生成摘要报告
    summary_path = output_dir / "prediction_summary.txt"
    try:
        current_price = x_df['close'].iloc[-1]

        # 按天分组计算预测结果
        points_per_day = 50  # A股每天50个5分钟点（上午25个+下午25个）

        summary = []
        summary.append("Kronos 预测摘要报告")
        summary.append("=" * 50)
        summary.append(f"预测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        summary.append(f"数据文件: {args.data}")
        summary.append(f"模型: {args.model}")
        summary.append(f"历史数据长度: {len(x_df)}")
        summary.append(f"预测天数: {args.pred_len}天")
        summary.append(f"当前价格: {current_price:.2f}")
        summary.append("")

        # 分天显示预测结果
        for day in range(args.pred_len):
            start_idx = day * points_per_day
            end_idx = (day + 1) * points_per_day
            day_data = pred_df.iloc[start_idx:end_idx]

            day_label = f"第{day + 1}天"

            day_open = day_data['close'].iloc[0]
            day_close = day_data['close'].iloc[-1]
            day_high = day_data['high'].max()
            day_low = day_data['low'].min()
            day_volume = day_data['volume'].sum()

            price_change = day_close - current_price
            price_change_pct = (price_change / current_price) * 100
            intraday_range = day_high - day_low
            intraday_range_pct = (intraday_range / day_open) * 100

            summary.append(f"📈 {day_label}预测结果:")
            summary.append(f"  开盘价: {day_open:.2f}")
            summary.append(f"  收盘价: {day_close:.2f}")
            summary.append(f"  最高价: {day_high:.2f}")
            summary.append(f"  最低价: {day_low:.2f}")
            summary.append(f"  成交量: {day_volume:,.0f}")
            summary.append(f"  价格变化: {price_change:+.2f} ({price_change_pct:+.2f}%)")
            summary.append(f"  日内波动: {intraday_range:.2f} ({intraday_range_pct:.2f}%)")
            summary.append("")

        # 整体预测统计
        total_change = pred_df['close'].iloc[-1] - current_price
        total_change_pct = (total_change / current_price) * 100
        max_price = pred_df['high'].max()
        min_price = pred_df['low'].min()

        summary.append("📊 整体预测统计:")
        summary.append(f"  预测期间最高价: {max_price:.2f}")
        summary.append(f"  预测期间最低价: {min_price:.2f}")
        summary.append(f"  总体价格变化: {total_change:+.2f} ({total_change_pct:+.2f}%)")
        summary.append("")
        summary.append("📁 输出文件:")
        summary.append(f"  预测数据: {csv_path}")
        summary.append(f"  预测图表: {plot_path}")

        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(summary))

        print("\n" + "\n".join(summary))

    except Exception as e:
        print(f"⚠️  生成摘要失败: {e}")

    print(f"\n✅ 预测完成! 结果保存在: {output_dir}")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⚠️  操作被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        sys.exit(1)
