"""
数据处理和自动补全模块
为Kronos系统提供数据清理、验证和补全功能
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings('ignore')


class DataProcessor:
    """数据处理器 - 负责数据清理、验证和自动补全"""

    def __init__(self):
        self.trading_calendar = None

    def generate_trading_calendar(self, start_date, end_date):
        """生成A股交易日历（排除周末和节假日）"""
        trading_days = []
        current_date = start_date

        while current_date <= end_date:
            # 排除周末
            if current_date.weekday() < 5:  # 0-4 为周一到周五
                trading_days.append(current_date)
            current_date += timedelta(days=1)

        return trading_days

    def validate_stock_data(self, df, required_days=None, stock_code=None):
        """
        验证股票数据完整性和合理性
        
        Args:
            df: 股票数据DataFrame
            required_days: 需要的天数
            stock_code: 股票代码
            
        Returns:
            dict: 验证结果
        """
        validation_result = {
            'is_valid': True,
            'issues': [],
            'data_range': None,
            'missing_days': 0,
            'suggestions': []
        }

        if df.empty:
            validation_result['is_valid'] = False
            validation_result['issues'].append('数据为空')
            return validation_result

        # 检查必要列
        required_columns = ['timestamps', 'open', 'high', 'low', 'close', 'volume']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            validation_result['is_valid'] = False
            validation_result['issues'].append(f'缺少必要列: {missing_columns}')

        # 检查数据范围
        if 'timestamps' in df.columns:
            df['timestamps'] = pd.to_datetime(df['timestamps'])
            start_date = df['timestamps'].min()
            end_date = df['timestamps'].max()
            validation_result['data_range'] = {
                'start': start_date,
                'end': end_date,
                'actual_days': len(df)
            }

            # 计算期望的交易日数量
            if required_days:
                expected_end = datetime.now().date()
                expected_start = expected_end - timedelta(days=int(required_days * 1.4))  # 考虑周末
                trading_days = self.generate_trading_calendar(expected_start, expected_end)
                expected_trading_days = len(trading_days)

                validation_result['missing_days'] = max(0, expected_trading_days - len(df))

                if validation_result['missing_days'] > 0:
                    validation_result['suggestions'].append(
                        f'数据不足：当前{len(df)}天，建议{expected_trading_days}天'
                    )

        # 检查数据合理性
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_columns:
            if col in df.columns:
                # 检查负值
                if (df[col] < 0).any():
                    validation_result['issues'].append(f'{col}列存在负值')

                # 检查异常值（价格列）
                if col in ['open', 'high', 'low', 'close']:
                    # OHLC逻辑检查
                    invalid_ohlc = (df['high'] < df[['open', 'close']].max(axis=1)) | \
                                   (df['low'] > df[['open', 'close']].min(axis=1))
                    if invalid_ohlc.any():
                        validation_result['issues'].append('OHLC数据逻辑错误')

        # 检查数据连续性
        if len(df) > 1 and 'timestamps' in df.columns:
            time_gaps = df['timestamps'].diff().dt.days
            large_gaps = time_gaps[time_gaps > 7]  # 超过7天的间隔
            if not large_gaps.empty:
                validation_result['suggestions'].append(
                    f'发现{len(large_gaps)}个较大时间间隔，可能需要补全数据'
                )

        return validation_result

    def auto_complete_data(self, df, target_days=365, stock_code=None):
        """
        自动补全股票数据
        
        Args:
            df: 原始股票数据
            target_days: 目标天数
            stock_code: 股票代码
            
        Returns:
            pd.DataFrame: 补全后的数据
        """
        if df.empty:
            print("⚠️ 数据为空，无法补全")
            return df

        df = df.copy()
        df['timestamps'] = pd.to_datetime(df['timestamps'])
        df = df.sort_values('timestamps').reset_index(drop=True)

        print(f"📊 原始数据: {len(df)} 条记录")
        print(f"🎯 目标天数: {target_days} 天")

        # 如果数据已经足够，直接返回最近的数据
        if len(df) >= target_days:
            result_df = df.tail(target_days).reset_index(drop=True)
            print(f"✅ 数据充足，返回最近 {target_days} 天数据")
            return result_df

        # 数据不足，需要补全
        shortage = target_days - len(df)
        print(f"📈 数据不足 {shortage} 天，开始自动补全...")

        # 获取最早的数据点
        earliest_date = df['timestamps'].min()
        print(f"📅 最早数据日期: {earliest_date.date()}")

        # 计算需要补全的起始日期
        extend_start_date = earliest_date - timedelta(days=int(shortage * 1.5))  # 多生成一些以防周末

        # 生成补全的交易日期
        extend_dates = []
        current_date = extend_start_date
        generated_count = 0

        while generated_count < shortage and current_date < earliest_date:
            # 只在工作日添加数据
            if current_date.weekday() < 5:  # 0-4 为周一到周五
                extend_dates.append(current_date)
                generated_count += 1
            current_date += timedelta(days=1)

        if not extend_dates:
            print("⚠️ 无法生成补全数据")
            return df

        print(f"🔧 生成 {len(extend_dates)} 天补全数据")

        # 使用现有数据的统计特征来生成合理的历史数据
        base_stats = self._calculate_base_stats(df)

        # 生成补全数据
        extended_data = []
        base_price = df['close'].iloc[0]  # 使用最早的收盘价作为基准

        for i, date in enumerate(reversed(extend_dates)):  # 从远到近生成
            # 计算价格趋势（简单随机游走）
            price_change = np.random.normal(
                base_stats['daily_return_mean'],
                base_stats['daily_return_std']
            )

            # 避免价格过度偏离
            price_change = np.clip(price_change, -0.1, 0.1)

            if i == 0:
                close_price = base_price * (1 + price_change)
            else:
                close_price = extended_data[-1]['close'] * (1 + price_change)

            # 确保价格为正
            close_price = max(close_price, 0.01)

            # 生成OHLC数据
            volatility = np.random.uniform(
                base_stats['volatility_min'],
                base_stats['volatility_max']
            )

            high = close_price * (1 + volatility * np.random.uniform(0.3, 1.0))
            low = close_price * (1 - volatility * np.random.uniform(0.3, 1.0))
            open_price = low + (high - low) * np.random.uniform(0.2, 0.8)

            # 生成成交量
            volume = np.random.lognormal(
                base_stats['volume_log_mean'],
                base_stats['volume_log_std']
            )
            volume = max(int(volume), 100)  # 最小100股

            # 计算成交额
            amount = volume * close_price

            extended_data.append({
                'timestamps': date,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close_price,
                'volume': volume,
                'amount': amount
            })

        # 创建补全数据的DataFrame
        extended_df = pd.DataFrame(extended_data)

        # 合并原始数据和补全数据
        combined_df = pd.concat([extended_df, df], ignore_index=True)
        combined_df = combined_df.sort_values('timestamps').reset_index(drop=True)

        # 返回目标天数的数据
        result_df = combined_df.tail(target_days).reset_index(drop=True)

        print(f"✅ 数据补全完成: {len(result_df)} 条记录")
        print(f"📊 数据时间范围: {result_df['timestamps'].min().date()} 到 {result_df['timestamps'].max().date()}")

        return result_df

    def _calculate_base_stats(self, df):
        """计算基础统计特征用于数据补全"""
        stats = {}

        # 价格相关统计
        if len(df) > 1:
            daily_returns = df['close'].pct_change().dropna()
            stats['daily_return_mean'] = daily_returns.mean()
            stats['daily_return_std'] = daily_returns.std()
        else:
            stats['daily_return_mean'] = 0.0
            stats['daily_return_std'] = 0.02

        # 波动率统计
        if len(df) > 0:
            daily_volatility = (df['high'] - df['low']) / df['close']
            stats['volatility_min'] = daily_volatility.quantile(0.1)
            stats['volatility_max'] = daily_volatility.quantile(0.9)
        else:
            stats['volatility_min'] = 0.01
            stats['volatility_max'] = 0.05

        # 成交量统计（对数正态分布）
        if len(df) > 0 and df['volume'].min() > 0:
            log_volumes = np.log(df['volume'])
            stats['volume_log_mean'] = log_volumes.mean()
            stats['volume_log_std'] = log_volumes.std()
        else:
            stats['volume_log_mean'] = 13.0  # 约45万股
            stats['volume_log_std'] = 1.0

        return stats

    def detect_listing_date(self, stock_code):
        """
        检测股票上市日期（简化版本）
        在实际应用中，这里应该查询股票数据库或API
        """
        # 这是一个简化的实现，实际应用中需要查询真实的股票上市数据
        known_listing_dates = {
            '000001': datetime(1991, 7, 3),  # 平安银行
            '000002': datetime(1991, 1, 29),  # 万科A
            '600000': datetime(1999, 11, 10),  # 浦发银行
            '600036': datetime(2007, 1, 9),  # 招商银行
            '600519': datetime(2001, 8, 27),  # 贵州茅台
        }

        # 移除可能的交易所后缀
        clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code

        if clean_code in known_listing_dates:
            return known_listing_dates[clean_code]

        # 默认假设是较新的股票（最近10年上市）
        return datetime.now() - timedelta(days=3650)  # 10年前

    def smart_data_completion(self, df, required_days, stock_code=None):
        """
        智能数据补全 - 优先使用最近一年数据进行预测
        
        Args:
            df: 原始数据
            required_days: 需要的天数
            stock_code: 股票代码
            
        Returns:
            pd.DataFrame: 处理后的数据
        """
        # 检测股票上市日期
        if stock_code:
            listing_date = self.detect_listing_date(stock_code)
            days_since_listing = (datetime.now() - listing_date).days

            print(f"📅 股票 {stock_code} 上市日期: {listing_date.date()}")
            print(f"📊 上市天数: {days_since_listing} 天")

            # 如果要求的天数超过上市天数，调整为上市天数
            if required_days > days_since_listing:
                print(f"⚠️ 要求天数({required_days})超过上市天数({days_since_listing})，调整为上市天数")
                required_days = min(days_since_listing, required_days)

        # 验证数据
        validation = self.validate_stock_data(df, required_days, stock_code)

        print("📋 数据验证结果:")
        print(f"   有效性: {'✅' if validation['is_valid'] else '❌'}")
        if validation['issues']:
            print(f"   问题: {'; '.join(validation['issues'])}")
        if validation['suggestions']:
            print(f"   建议: {'; '.join(validation['suggestions'])}")

        # 智能选择数据范围：优先使用最近一年的数据
        one_year_days = 365

        # 如果数据足够，优先使用最近一年的数据
        if len(df) >= one_year_days:
            print(f"📈 数据充足，优先使用最近一年数据进行预测 ({one_year_days} 天)")
            return df.tail(one_year_days).reset_index(drop=True)
        elif len(df) >= required_days:
            # 如果数据不足一年但超过要求天数，使用所有可用数据
            print(f"📊 使用所有可用数据进行预测 ({len(df)} 天)")
            return df.tail(len(df)).reset_index(drop=True)
        else:
            # 数据不足，进行补全
            print(f"⚠️ 数据不足，进行数据补全")
            return self.auto_complete_data(df, required_days, stock_code)

    def format_for_analysis(self, df):
        """
        格式化数据用于技术分析
        确保数据格式符合技术分析模块的要求
        """
        df = df.copy()

        # 确保时间列为datetime类型
        if 'timestamps' in df.columns:
            df['timestamps'] = pd.to_datetime(df['timestamps'])

        # 确保数值列为float类型
        numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'amount']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 删除包含NaN的行
        df = df.dropna()

        # 确保按时间排序
        df = df.sort_values('timestamps').reset_index(drop=True)

        return df
