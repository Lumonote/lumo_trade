#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos 数据获取脚本
支持多数据源：Tushare、Playwright爬虫（东方财富、同花顺、雪球）
从多个数据源获取股票数据并保存为Kronos兼容格式
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
import time
import asyncio

# 尝试导入可选依赖
try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("⚠️ pandas 不可用，某些功能将受限")

try:
    import tushare as ts

    TUSHARE_AVAILABLE = True
    print("✅ Tushare模块已加载")
except ImportError:
    TUSHARE_AVAILABLE = False
    print("⚠️ Tushare不可用，将仅使用爬虫数据源")

# 尝试导入Baostock
try:
    import baostock as bs
    BAOSTOCK_AVAILABLE = True
except ImportError:
    BAOSTOCK_AVAILABLE = False
    print("⚠️ Baostock不可用，请运行: pip install baostock")

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

# 导入Playwright爬虫
try:
    from scripts.crawler import CrawlerManager

    CRAWLER_AVAILABLE = True
    print("✅ 爬虫模块已加载 | Crawler module loaded")
except ImportError as e:
    CRAWLER_AVAILABLE = False
    print(f"⚠️ 爬虫模块不可用: {e} | Crawler module unavailable: {e}")

# 导入技术分析器 (已禁用，避免重复分析报告)
# try:
#     from scripts.technical_analyzer import TechnicalAnalyzer
#     TECHNICAL_ANALYZER_AVAILABLE = True
# except ImportError:
#     TECHNICAL_ANALYZER_AVAILABLE = False
#     print("⚠️  技术分析器模块不可用")
TECHNICAL_ANALYZER_AVAILABLE = False


class TushareDataFetcher:
    """Tushare数据获取器"""

    def __init__(self, config: Dict[str, Any]):
        """初始化Tushare API"""
        self.config = config
        self.token = config.get('tushare', {}).get('token', '')

        # 尝试从环境变量获取
        if not self.token or self.token == "your_tushare_token_here":
            self.token = os.environ.get('TUSHARE_TOKEN', '')

        self.pro = None
        self.last_request_time = 0  # 上次请求时间，用于速率限制
        self.min_request_interval = 31  # Tushare限制每分钟最多2次，间隔至少31秒

        if self.token and TUSHARE_AVAILABLE:
            try:
                ts.set_token(self.token)
                self.pro = ts.pro_api()
                print("✅ Tushare API已连接")
            except Exception as e:
                print(f"⚠️  Tushare连接失败: {e}")
        else:
            if not TUSHARE_AVAILABLE:
                print("⚠️  Tushare模块未安装")
            else:
                print("⚠️  未找到Tushare Token，请配置config/tushare_config.json或设置TUSHARE_TOKEN环境变量")

    def _rate_limit_wait(self):
        """等待以满足Tushare速率限制（每分钟最多2次）"""
        import time
        current_time = time.time()
        elapsed = current_time - self.last_request_time

        if elapsed < self.min_request_interval:
            wait_time = self.min_request_interval - elapsed
            print(f"⏱️ Tushare速率限制，等待 {wait_time:.1f} 秒...")
            time.sleep(wait_time)

        self.last_request_time = time.time()

    def _convert_symbol_format(self, symbol: str) -> str:
        """转换股票代码为Tushare格式"""
        if not symbol:
            return ""
        if symbol.endswith(('.SZ', '.SH', '.BJ')):
            return symbol
            
        # 简单的交易所推断
        if symbol.startswith(('60', '68')):
            return f"{symbol}.SH"
        elif symbol.startswith(('00', '30')):
            return f"{symbol}.SZ"
        elif symbol.startswith(('4', '8')):
            return f"{symbol}.BJ"
        return symbol

    def fetch_stock_data(self, symbol: str, start_date: str = None, end_date: str = None,
                         freq: str = '5min', adj: str = 'qfq') -> Optional[pd.DataFrame]:
        """从Tushare获取股票数据"""
        if not self.pro:
            print("❌ Tushare未初始化，无法获取数据")
            return None

        ts_code = self._convert_symbol_format(symbol)
        if not ts_code:
            print(f"❌ 无效的股票代码: {symbol}")
            return None

        # 尝试获取数据
        df = self._fetch_tushare_data(ts_code, start_date, end_date, freq, adj)

        return df

    def _fetch_tushare_data(self, ts_code: str, start_date: str = None, end_date: str = None,
                            freq: str = '5min', adj: str = 'qfq'):
        """从Tushare获取股票数据（内部方法）"""
        try:
            # 不等待速率限制，直接尝试，失败后会自动切换到爬虫

            # 处理日期格式
            start_dt = start_date.replace('-', '') if start_date else ''
            end_dt = end_date.replace('-', '') if end_date else ''

            # Tushare freq映射
            ts_freq = freq
            if freq == '5min': ts_freq = '5min'
            elif freq == '1min': ts_freq = '1min'
            elif freq == 'daily': ts_freq = 'D'

            print(f"📡 Tushare正在获取 {ts_code} ({freq}) 数据...")

            # 使用pro_bar通用接口
            try:
                df = ts.pro_bar(
                    ts_code=ts_code,
                    api=self.pro,
                    start_date=start_dt,
                    end_date=end_dt,
                    freq=ts_freq,
                    adj=adj,
                    asset='E'
                )
            except UnboundLocalError:
                # 特别处理Tushare内部可能的UnboundLocalError
                print(f"⚠️  Tushare pro_bar 内部错误 (UnboundLocalError)，尝试不复权获取...")
                df = ts.pro_bar(
                    ts_code=ts_code,
                    api=self.pro,
                    start_date=start_dt,
                    end_date=end_dt,
                    freq=ts_freq,
                    adj=None,
                    asset='E'
                )

            if df is None or df.empty:
                print(f"⚠️  Tushare返回空数据: {ts_code}")
                return None
                
            # 转换列名以匹配系统标准
            # Tushare返回: trade_date, open, high, low, close, vol, amount, ...
            # 对于分钟数据: trade_time
            
            rename_map = {
                'trade_date': 'timestamp',
                'trade_time': 'timestamp',
                'vol': 'volume'
            }
            df = df.rename(columns=rename_map)
            
            # 确保timestamp格式
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                # 格式化为标准字符串
                df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # 按时间正序排列
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            return df
            
        except Exception as e:
            error_msg = str(e)
            # 检测频率限制/权限错误
            if '每分钟最多访问' in error_msg or 'rate limit' in error_msg.lower() or 'frequency' in error_msg.lower():
                print(f"⚠️  Tushare频率限制触发，自动切换到其他数据源...")
                return None
            # 检测权限不足错误
            if '权限' in error_msg or 'permission' in error_msg.lower() or 'no permission' in error_msg.lower():
                print(f"⚠️  Tushare权限不足，请检查账户积分和接口权限: {e}")
                print(f"💡 提示: 低频行情接口需要 5000+ 积分，实时行情需要更高权限")
                return None
            print(f"❌ Tushare获取失败: {e}")
            return None

    def get_stock_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取股票基本信息"""
        if not self.pro:
            return None

        ts_code = self._convert_symbol_format(symbol)
        try:
            # 速率限制等待
            self._rate_limit_wait()

            df = self.pro.stock_basic(
                ts_code=ts_code,
                fields='ts_code,symbol,name,area,industry,market,list_date'
            )
            if not df.empty:
                return df.iloc[0].to_dict()
            return None
        except Exception as e:
            error_msg = str(e)
            # 检测频率限制错误
            if '每分钟最多访问' in error_msg or 'rate limit' in error_msg.lower() or 'frequency' in error_msg.lower():
                print(f"⚠️  Tushare频率限制触发，跳过该接口...")
                return None
            print(f"⚠️  获取股票信息失败: {e}")
            return None


class BaostockFetcher:
    """Baostock数据获取器"""

    def __init__(self):
        """初始化Baostock"""
        self._bs = None
        self._init_baostock()

    def _init_baostock(self):
        """初始化Baostock连接"""
        if not BAOSTOCK_AVAILABLE:
            print("⚠️ Baostock模块未安装")
            return

        try:
            import baostock as bs

            # 登录Baostock
            lg = bs.login()
            if lg.error_code == '0':
                self._bs = bs
                print("✅ Baostock数据源已初始化")
            else:
                print(f"⚠️ Baostock登录失败: {lg.error_msg}")
                self._bs = None
        except Exception as e:
            print(f"⚠️ Baostock初始化失败: {e}")
            self._bs = None

    def _convert_symbol_format(self, symbol: str) -> str:
        """转换股票代码为Baostock格式"""
        if not symbol:
            return ""

        # 如果已经是baostock格式，直接返回
        if symbol.startswith(('sh.', 'sz.')):
            return symbol

        # 转换常见格式
        if symbol.endswith(('.SH', '.SZ')):
            return f"sh.{symbol.split('.')[0]}" if symbol.endswith('.SH') else f"sz.{symbol.split('.')[0]}"

        # 简单的交易所推断
        if symbol.startswith(('60', '68')):
            return f"sh.{symbol}"
        elif symbol.startswith(('00', '30')):
            return f"sz.{symbol}"

        return f"sz.{symbol}"

    def fetch_stock_data(self, symbol: str, start_date: str = None, end_date: str = None,
                         freq: str = '5min', adj: str = 'qfq') -> Optional[pd.DataFrame]:
        """从Baostock获取股票数据"""
        if not self._bs:
            return None

        bs_code = self._convert_symbol_format(symbol)
        if not bs_code:
            return None

        return self._fetch_baostock_data(bs_code, start_date, end_date, freq, adj)

    def _fetch_baostock_data(self, bs_code: str, start_date: str = None, end_date: str = None,
                             freq: str = '5min', adj: str = 'qfq') -> Optional[pd.DataFrame]:
        """从Baostock获取股票数据"""
        try:
            # 处理日期格式
            if not start_date:
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')

            # Baostock字段
            fields = "date,time,open,high,low,close,volume,amount"

            # 频率映射
            period_map = {'1min': '1', '5min': '5', '15min': '15', '30min': '30', '60min': '60'}
            period = period_map.get(freq, '5')

            # 复权映射
            adj_map = {'qfq': '1', 'hfq': '2', '': '3'}
            adj_flag = adj_map.get(adj, '3')

            print(f"📡 Baostock正在获取 {bs_code} ({freq})...")

            rs = self._bs.query_history_k_data_plus(
                bs_code, fields,
                start_date=start_date, end_date=end_date,
                frequency=period,
                adjustflag=adj_flag
            )

            if rs.error_code != '0':
                print(f"⚠️ Baostock查询失败: {rs.error_msg}")
                return None

            # 转换为DataFrame
            data_list = []
            while (rs.error_code == '0') and rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                print(f"⚠️ Baostock返回空数据")
                return None

            df = pd.DataFrame(data_list, columns=rs.fields)

            # 构建时间戳
            if 'time' in df.columns:
                timestamps = []
                for _, row in df.iterrows():
                    date_part = str(row.get('date', '')).strip()
                    time_part = str(row.get('time', '')).strip()
                    if time_part and time_part != '00:00:00':
                        # Baostock的time格式可能是 HHMMSSmmm 或 YYYYMMDDHHMMSSmmm
                        # 需要解析并转换为标准时间格式
                        try:
                            if len(time_part) == 17:  # YYYYMMDDHHMMSSmmm
                                # 格式: 20250205093500000 -> 2025-02-05 09:35:00
                                formatted_time = f"{time_part[8:10]}:{time_part[10:12]}:{time_part[12:14]}"
                            elif len(time_part) == 9:  # HHMMSSmmm
                                formatted_time = f"{time_part[0:2]}:{time_part[2:4]}:{time_part[4:6]}"
                            else:
                                formatted_time = time_part
                            timestamps.append(f"{date_part} {formatted_time}")
                        except Exception:
                            timestamps.append(date_part)
                    else:
                        timestamps.append(date_part)
                df['timestamp'] = timestamps
            else:
                df['timestamp'] = df['date']

            # 转换数值列
            numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # 排序
            df = df.sort_values('timestamp').reset_index(drop=True)

            print(f"✅ Baostock获取成功: {len(df)} 条")
            return df

        except Exception as e:
            print(f"❌ Baostock获取失败: {e}")
            return None

    def close(self):
        """关闭连接"""
        if self._bs:
            self._bs.logout()


class MultiSourceDataFetcher:
    """多数据源数据获取器"""

    def __init__(self, config_path: str = "config/tushare_config.json",
                 crawler_config_path: str = "config/crawler_config.json"):
        """初始化数据获取器"""
        self.config_path = config_path
        self.crawler_config_path = crawler_config_path
        self.config = {}
        self.tushare_fetcher = None
        self.baostock_fetcher = None
        self.crawler_manager = None
        self.technical_analyzer = None

        # 初始化可用的数据源
        self._init_data_sources()

        # 初始化技术分析器
        if TECHNICAL_ANALYZER_AVAILABLE:
            try:
                self.technical_analyzer = TechnicalAnalyzer()
                print("✅ 技术分析器已初始化")
            except Exception as e:
                print(f"⚠️  技术分析器初始化失败: {e}")

    def _init_data_sources(self):
        """初始化数据源"""
        # 初始化Tushare (仅在可用时)
        if TUSHARE_AVAILABLE:
            try:
                self.config = self._load_config(self.config_path)
                self.tushare_fetcher = TushareDataFetcher(self.config)
                print("✅ Tushare数据源已初始化")
            except Exception as e:
                print(f"⚠️  Tushare初始化失败: {e}")
                self.config = {'data_settings': {'output_dir': './data/'}}
        else:
            print("⚠️  Tushare不可用，跳过Tushare数据源初始化")
            self.config = {'data_settings': {'output_dir': './data/'}}

        # 初始化Baostock
        if BAOSTOCK_AVAILABLE:
            try:
                self.baostock_fetcher = BaostockFetcher()
            except Exception as e:
                print(f"⚠️  Baostock初始化失败: {e}")

        # 初始化Playwright爬虫
        if CRAWLER_AVAILABLE:
            try:
                if os.path.exists(self.crawler_config_path):
                    self.crawler_manager = CrawlerManager(self.crawler_config_path)
                    print("✅ Playwright爬虫数据源已初始化")
                else:
                    print(f"⚠️  爬虫配置文件不存在: {self.crawler_config_path}")
            except Exception as e:
                print(f"⚠️  Playwright爬虫初始化失败: {e}")

        # 检查是否有可用的数据源
        available_sources = self.get_available_sources()
        if not available_sources:
            print("❌ 没有可用的数据源，请检查配置")
            raise Exception("没有可用的数据源")

    def get_available_sources(self) -> List[str]:
        """获取可用的数据源列表"""
        sources = []
        if self.tushare_fetcher:
            sources.append('tushare')
        if self.baostock_fetcher:
            sources.append('baostock')
        if self.crawler_manager:
            sources.extend(['eastmoney', 'tonghuashun', 'xueqiu'])
        return sources

    async def close(self) -> None:
        """关闭并清理资源（特别是爬虫/浏览器管理器）"""
        try:
            if self.baostock_fetcher:
                self.baostock_fetcher.close()
                self.baostock_fetcher = None
        except Exception as e:
            print(f"⚠️  关闭Baostock失败: {e}")
        try:
            if self.crawler_manager:
                await self.crawler_manager.close()
                self.crawler_manager = None
        except Exception as e:
            print(f"⚠️  关闭爬虫管理器失败: {e}")

    async def fetch_stock_data(self,
                               symbol: str,
                               start_date: str = None,
                               end_date: str = None,
                               freq: str = '5min',
                               source: str = 'auto',
                               adj: str = 'qfq',
                               auto_extend: bool = True,
                               min_days: int = 365) -> Optional[Any]:
        """从指定数据源获取股票数据，支持多爬虫自动切换"""

        if not PANDAS_AVAILABLE:
            print("❌ pandas 不可用，无法处理数据")
            return None

        available_sources = self.get_available_sources()

        if not available_sources:
            print("❌ 没有可用的数据源")
            return None

        # 如果没有明确的时间范围且提供了min_days，则根据min_days计算时间范围
        if not start_date and not end_date and min_days:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=min_days)).strftime('%Y-%m-%d')
            print(f"📅 根据min_days({min_days}天)设置时间范围: {start_date} - {end_date}")
        elif not start_date and not end_date:
            # 只有在没有任何时间参数时才使用默认的365天
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            print(f"📅 使用默认一年时间范围: {start_date} - {end_date}")

        # 设置数据源尝试顺序
        sources_to_try = []

        if source == 'auto':
            # 自动模式：优先级 Tushare -> Baostock -> 爬虫
            if 'tushare' in available_sources:
                sources_to_try.append('tushare')
            if 'baostock' in available_sources:
                sources_to_try.append('baostock')
            # 添加所有可用的爬虫数据源
            crawler_sources = [s for s in available_sources if s in ['eastmoney', 'tonghuashun', 'xueqiu']]
            sources_to_try.extend(crawler_sources)
        else:
            # 指定数据源模式：先尝试指定的数据源，失败后尝试其他数据源
            if source in available_sources:
                sources_to_try.append(source)

            # 如果指定的数据源失败，添加其他可用数据源作为备选
            fallback_sources = [s for s in available_sources if s != source]
            sources_to_try.extend(fallback_sources)

        print(f"📊 数据源尝试顺序: {' -> '.join(sources_to_try)}")

        # 依次尝试每个数据源，直到成功获取数据
        data = None
        last_error = None

        for i, current_source in enumerate(sources_to_try):
            try:
                print(f"📡 尝试数据源 ({i + 1}/{len(sources_to_try)}): {current_source}")

                # 根据数据源获取数据
                if current_source == 'tushare' and self.tushare_fetcher:
                    data = self.tushare_fetcher.fetch_stock_data(symbol, start_date, end_date, freq, adj)

                elif current_source == 'baostock' and self.baostock_fetcher:
                    data = self.baostock_fetcher.fetch_stock_data(symbol, start_date, end_date, freq, adj)

                elif current_source in ['eastmoney', 'tonghuashun', 'xueqiu'] and self.crawler_manager:
                    data = await self._fetch_from_crawler(symbol, start_date, end_date, freq, current_source)

                else:
                    print(f"⚠️  数据源 {current_source} 不可用，跳过")
                    continue

                # 检查数据是否成功获取且不为空
                if data is not None and not data.empty:
                    print(f"✅ 数据源 {current_source} 成功获取 {len(data)} 条数据")
                    break
                else:
                    print(f"⚠️  数据源 {current_source} 返回空数据或获取失败")
                    data = None

            except Exception as e:
                print(f"❌ 数据源 {current_source} 获取失败: {e}")
                last_error = e
                data = None

        # 如果所有数据源都失败了
        if data is None or data.empty:
            print(f"❌ 所有数据源({len(sources_to_try)}个)均无法获取数据")
            if last_error:
                print(f"最后一次错误: {last_error}")
            return None

        # 如果数据获取成功，检查数据量并自动补全
        if auto_extend:
            data = await self._auto_extend_data(data, symbol, start_date, end_date, freq, current_source, adj, min_days)

        # 如果数据获取成功，进行技术分析
        if self.technical_analyzer:
            try:
                print(f"\n📈 开始对股票 {symbol} 进行技术分析...")
                self.technical_analyzer.analyze_and_print(data, symbol)
            except Exception as e:
                print(f"⚠️  技术分析失败: {e}")

        return data

    async def _auto_extend_data(self, data: pd.DataFrame, symbol: str, start_date: str,
                                end_date: str, freq: str, source: str, adj: str,
                                min_days: int = 365) -> pd.DataFrame:
        """自动扩展数据以达到最小天数要求"""
        if data is None or data.empty:
            return data

        # 检查数据量
        current_days = len(data)
        trading_days_per_year = 250  # 一年约250个交易日
        min_trading_days = int(min_days * trading_days_per_year / 365)

        print(f"📊 当前数据量: {current_days} 条，最少需要: {min_trading_days} 条")

        if current_days >= min_trading_days:
            print("✅ 数据量充足，无需扩展")
            return data

        # 计算需要扩展的天数
        needed_days = min_trading_days - current_days
        extend_days = int(needed_days * 365 / trading_days_per_year) + 30  # 加30天缓冲

        print(f"🔄 数据量不足，需要扩展约 {extend_days} 天")

        # 获取数据的时间范围
        if 'timestamp' not in data.columns:
            print("⚠️  无法确定时间范围，跳过自动扩展")
            return data

        try:
            # 转换时间戳
            data['timestamp'] = pd.to_datetime(data['timestamp'])
            data_start = data['timestamp'].min()
            data_end = data['timestamp'].max()

            # 确定扩展方向
            if start_date:
                start_dt = pd.to_datetime(start_date)
                # 向前扩展
                new_start = (start_dt - timedelta(days=extend_days)).strftime('%Y-%m-%d')
                print(f"📅 向前扩展到: {new_start}")

                # 获取扩展数据
                extended_data = await self._fetch_data_period(
                    symbol, new_start, start_date, freq, source, adj
                )

                if extended_data is not None and not extended_data.empty:
                    # 合并数据
                    extended_data['timestamp'] = pd.to_datetime(extended_data['timestamp'])
                    combined_data = pd.concat([extended_data, data], ignore_index=True)
                    combined_data = combined_data.sort_values('timestamp').reset_index(drop=True)
                    combined_data = combined_data.drop_duplicates(subset=['timestamp']).reset_index(drop=True)
                    print(f"✅ 成功扩展 {len(extended_data)} 条历史数据")
                    return combined_data
            else:
                # 向后扩展
                if end_date:
                    end_dt = pd.to_datetime(end_date)
                else:
                    end_dt = datetime.now()

                new_end = (end_dt + timedelta(days=extend_days)).strftime('%Y-%m-%d')
                print(f"📅 向后扩展到: {new_end}")

                # 获取扩展数据
                extended_data = await self._fetch_data_period(
                    symbol, end_date or data_end.strftime('%Y-%m-%d'), new_end, freq, source, adj
                )

                if extended_data is not None and not extended_data.empty:
                    # 合并数据
                    extended_data['timestamp'] = pd.to_datetime(extended_data['timestamp'])
                    combined_data = pd.concat([data, extended_data], ignore_index=True)
                    combined_data = combined_data.sort_values('timestamp').reset_index(drop=True)
                    combined_data = combined_data.drop_duplicates(subset=['timestamp']).reset_index(drop=True)
                    print(f"✅ 成功扩展 {len(extended_data)} 条后续数据")
                    return combined_data

        except Exception as e:
            print(f"⚠️  自动扩展失败: {e}")

        return data

    async def _fetch_data_period(self, symbol: str, start_date: str, end_date: str,
                                 freq: str, source: str, adj: str) -> Optional[pd.DataFrame]:
        """获取指定时间段的数据，支持多爬虫自动切换"""

        available_sources = self.get_available_sources()

        # 设置数据源尝试顺序（优先尝试原始数据源，失败后尝试其他数据源）
        sources_to_try = []

        if source in available_sources:
            sources_to_try.append(source)

        # 添加其他可用数据源作为备选
        fallback_sources = [s for s in available_sources if s != source]
        sources_to_try.extend(fallback_sources)

        print(f"🔄 扩展数据源尝试顺序: {' -> '.join(sources_to_try)}")

        # 依次尝试每个数据源
        for i, current_source in enumerate(sources_to_try):
            try:
                print(f"📡 尝试扩展数据源 ({i + 1}/{len(sources_to_try)}): {current_source}")

                if current_source == 'tushare' and self.tushare_fetcher:
                    data = self.tushare_fetcher.fetch_stock_data(symbol, start_date, end_date, freq, adj)
                elif current_source in ['eastmoney', 'tonghuashun', 'xueqiu'] and self.crawler_manager:
                    data = await self._fetch_from_crawler(symbol, start_date, end_date, freq, current_source)
                else:
                    print(f"⚠️  扩展数据源 {current_source} 不可用，跳过")
                    continue

                # 检查数据是否成功获取且不为空
                if data is not None and not data.empty:
                    print(f"✅ 扩展数据源 {current_source} 成功获取 {len(data)} 条数据")
                    return data
                else:
                    print(f"⚠️  扩展数据源 {current_source} 返回空数据")

            except Exception as e:
                print(f"❌ 扩展数据源 {current_source} 获取失败: {e}")

        print(f"❌ 所有扩展数据源均无法获取数据")
        return None

    async def _fetch_from_crawler(self, symbol: str, start_date: str, end_date: str,
                                  freq: str, source: str) -> Optional[pd.DataFrame]:
        """从爬虫获取数据"""
        try:
            # 转换股票代码格式
            crawler_symbol = self._convert_symbol_for_crawler(symbol)

            # 根据频率选择数据类型和周期
            period_map = {
                '1min': '1m',
                '5min': '5m',
                '15min': '15m',
                '30min': '30m',
                '60min': '1h',
                'daily': '1d',
                'weekly': '1w',
                'monthly': '1M'
            }

            # 获取K线数据，包括分钟级数据
            period = period_map.get(freq, '5m')  # 默认使用5分钟
            data = await self.crawler_manager.get_kline_data(
                crawler_symbol, period=period,
                start_date=start_date, end_date=end_date, source=source
            )

            if not data:
                return None

            # 转换为DataFrame
            if isinstance(data, dict) and 'data' in data:
                # 处理东方财富API返回的数据格式
                kline_data = data['data']['klines']
                if kline_data:
                    # 解析K线数据字符串
                    parsed_data = []
                    for kline in kline_data:
                        parts = kline.split(',')
                        if len(parts) >= 6:
                            parsed_data.append({
                                'timestamp': parts[0],
                                'open': float(parts[1]),
                                'close': float(parts[2]),
                                'high': float(parts[3]),
                                'low': float(parts[4]),
                                'volume': float(parts[5]),
                                'amount': float(parts[6]) if len(parts) > 6 else 0
                            })
                    df = pd.DataFrame(parsed_data)
                else:
                    df = pd.DataFrame()
            elif isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
            else:
                df = pd.DataFrame(data if data else [])

            # 数据格式转换
            df = self._convert_crawler_data_format(df, freq)

            return df

        except Exception as e:
            print(f"❌ 爬虫数据获取失败: {e}")
            return None

    def _convert_symbol_for_crawler(self, symbol: str) -> str:
        """转换股票代码格式用于爬虫"""
        if not symbol or not isinstance(symbol, str):
            raise ValueError(f"无效的股票代码: {symbol}")

        # 移除交易所后缀
        if '.' in symbol:
            symbol = symbol.split('.')[0]

        # 确保6位数字
        if symbol.isdigit():
            code = symbol.zfill(6)
            # 检查是否为有效的股票代码格式
            if code == '000000':
                raise ValueError(f"无效的股票代码: {symbol} (转换后为000000)")
            return code

        return symbol

    def _convert_crawler_data_format(self, df: pd.DataFrame, freq: str) -> pd.DataFrame:
        """转换爬虫数据格式为标准格式"""
        # 列名映射
        column_mapping = {
            'time': 'timestamp',
            'datetime': 'timestamp',
            'date': 'timestamp',
            'price': 'close',
            'current': 'close',
            'vol': 'volume',
            'amount': 'amount'
        }

        # 重命名列
        for old_col, new_col in column_mapping.items():
            if old_col in df.columns:
                df = df.rename(columns={old_col: new_col})

        # 确保必需的列存在
        required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']

        # 如果缺少OHLC数据，使用close价格填充
        if 'close' in df.columns:
            for col in ['open', 'high', 'low']:
                if col not in df.columns:
                    df[col] = df['close']

        # 如果缺少成交量，设为0
        if 'volume' not in df.columns:
            df['volume'] = 0

        # 处理时间戳
        if 'timestamp' in df.columns:
            # 尝试转换时间格式
            try:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass

        # 按时间排序
        if 'timestamp' in df.columns:
            df = df.sort_values('timestamp').reset_index(drop=True)

        return df

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config
        except FileNotFoundError:
            print(f"⚠️  配置文件不存在: {config_path}")
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        except json.JSONDecodeError as e:
            print(f"❌ 配置文件格式错误: {e}")
            raise json.JSONDecodeError(f"配置文件格式错误: {e}", "", 0)

    def save_data(self, df: Any, symbol: str, freq: str = '5min') -> str:
        """保存数据为Kronos兼容格式"""
        # 优先使用环境变量中的数据目录，适配打包应用
        data_dir_env = os.environ.get('KRONOS_DATA_DIR')
        if data_dir_env:
            output_dir = Path(data_dir_env)
        else:
            output_dir = Path(self.config.get('data_settings', {}).get('output_dir', './data/'))
        output_dir.mkdir(parents=True, exist_ok=True)

        # 提取股票代码
        if '.' in symbol:
            code = symbol.split('.')[0]
        else:
            code = symbol

        # 统一频率标识
        if freq in ['5min', '5m']:
            freq_str = '5m'
        else:
            freq_str = freq

        # 生成文件名 (格式: 5m_600977.csv)
        filename = f"{freq_str}_{code}.csv"
        filepath = output_dir / filename

        # 保存数据
        try:
            df.to_csv(filepath, index=False, encoding='utf-8')
            print(f"✅ 数据已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            print(f"❌ 保存数据失败: {e}")
            return ""

    def get_stock_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取股票基本信息"""
        if self.tushare_fetcher:
            return self.tushare_fetcher.get_stock_info(symbol)
        
        print("⚠️  Tushare不可用，无法获取详细股票信息")
        return None


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Kronos 多数据源数据获取工具')
    parser.add_argument('--symbol', '-s', help='股票代码 (如: 000001, 600519, 000001.SZ)')
    parser.add_argument('--start-date', help='开始日期 (YYYY-MM-DD 或 YYYYMMDD)')
    parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD 或 YYYYMMDD)')
    parser.add_argument('--days', type=int, help='获取最近N天的数据 (与--start-date互斥，优先级高于--start-date)')
    parser.add_argument('--freq', default='5min',
                        choices=['1min', '5min', '15min', '30min', '60min', 'D'],
                        help='数据频率 (默认: 5min)')
    parser.add_argument('--adj', default='qfq', choices=['qfq', 'hfq', None],
                        help='复权类型 (qfq=前复权, hfq=后复权, None=不复权)')
    parser.add_argument('--source', default='auto',
                        choices=['auto', 'tushare', 'baostock', 'eastmoney', 'tonghuashun', 'xueqiu'],
                        help='数据源选择 (默认: auto)')
    parser.add_argument('--config', default='config/tushare_config.json',
                        help='Tushare配置文件路径')
    parser.add_argument('--crawler-config', default='config/crawler_config.json',
                        help='爬虫配置文件路径')
    parser.add_argument('--info', action='store_true', help='显示股票基本信息')
    parser.add_argument('--list-sources', action='store_true', help='列出可用的数据源')
    parser.add_argument('--no-auto-extend', action='store_true', help='禁用数据自动扩展功能')
    parser.add_argument('--min-days', type=int, default=365, help='最少数据天数 (默认: 365天)')

    args = parser.parse_args()

    print("🚀 Kronos多数据源数据获取工具启动")
    print("=" * 50)

    # 列出可用数据源（不需要初始化数据获取器）
    if args.list_sources:
        print("\n📋 可用数据源:")
        print("  • tushare - Tushare金融数据接口")
        if BAOSTOCK_AVAILABLE:
            print("  • baostock - Baostock免费数据接口")
        else:
            print("  ⚠️  Baostock不可用，请安装: pip install baostock")
        if CRAWLER_AVAILABLE:
            print("  • eastmoney - 东方财富 (Playwright爬虫)")
            print("  • tonghuashun - 同花顺 (Playwright爬虫)")
            print("  • xueqiu - 雪球 (Playwright爬虫)")
        else:
            print("  ⚠️  Playwright爬虫不可用，请安装: pip install playwright")
        return 0

    # 检查必需参数
    if not args.symbol:
        print("❌ 错误: 必须指定股票代码 (--symbol)")
        return 1

    # 处理 --days 参数：将其转换为 start_date
    start_date = args.start_date
    end_date = args.end_date

    if args.days:
        # 如果指定了 --days，计算起始日期
        end_date = end_date or datetime.now().strftime("%Y%m%d")

        # 解析结束日期
        try:
            if '-' in end_date:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            else:
                end_dt = datetime.strptime(end_date, "%Y%m%d")
        except ValueError:
            end_dt = datetime.now()

        # 计算起始日期（往前推 N 天）
        start_dt = end_dt - timedelta(days=args.days)
        start_date = start_dt.strftime("%Y%m%d")
        end_date = end_dt.strftime("%Y%m%d")

        print(f"📅 使用 --days={args.days} 参数")
        print(f"   计算得到时间范围: {start_date} 到 {end_date}")

    # 初始化数据获取器
    try:
        fetcher = MultiSourceDataFetcher(args.config, args.crawler_config)
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return 1

    # 显示股票信息
    if args.info:
        info = fetcher.get_stock_info(args.symbol)
        if info:
            print(f"\n📋 股票信息:")
            print(f"  代码: {info.get('ts_code', 'N/A')}")
            print(f"  名称: {info.get('name', 'N/A')}")
            print(f"  行业: {info.get('industry', 'N/A')}")
            print(f"  地区: {info.get('area', 'N/A')}")
            print(f"  市场: {info.get('market', 'N/A')}")
            print(f"  上市日期: {info.get('list_date', 'N/A')}")
            print()

    # 获取数据
    df = await fetcher.fetch_stock_data(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        freq=args.freq,
        source=args.source,
        adj=args.adj,
        auto_extend=not args.no_auto_extend,
        min_days=args.min_days
    )

    try:
        if df is None:
            print("❌ 数据获取失败")
            return 1

        # 保存数据
        filepath = fetcher.save_data(df, args.symbol, args.freq)

        if filepath:
            print(f"\n🎉 任务完成！")
            print(f"📁 文件路径: {filepath}")
            print(f"📊 数据条数: {len(df)}")
            print(f"🔗 数据源: {args.source}")

            if len(df) > 0 and 'timestamp' in df.columns:
                print(f"📅 时间范围: {df['timestamp'].min()} - {df['timestamp'].max()}")

            print("\n💡 提示: 现在可以使用此数据文件进行Kronos预测")
            return 0
        else:
            return 1
    finally:
        # 确保清理异步资源，避免Windows上管道未关闭警告
        try:
            await fetcher.close()
        except Exception as e:
            print(f"⚠️  资源清理失败: {e}")


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⚠️  操作被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        sys.exit(1)
