#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版数据获取脚本 - 支持分批采集长时间范围数据
集成智能数据补全、完整性检查和处理功能
"""

import os
import sys
import json
import argparse
import pandas as pd
import tushare as ts
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
import asyncio
import time
import warnings

warnings.filterwarnings('ignore')

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

# 导入需要的模块
try:
    from scripts.crawler import CrawlerManager

    CRAWLER_AVAILABLE = True
    print("✅ 爬虫模块已加载")
except ImportError as e:
    CRAWLER_AVAILABLE = False
    print(f"⚠️ 爬虫模块不可用: {e}")

try:
    from analysis.data_processor import DataProcessor

    DATA_PROCESSOR_AVAILABLE = True
    print("✅ 数据处理模块已加载")
except ImportError as e:
    DATA_PROCESSOR_AVAILABLE = False
    print(f"⚠️ 数据处理模块不可用: {e}")

try:
    from scripts.data_completeness_checker import DataCompletenessChecker

    CHECKER_AVAILABLE = True
    print("✅ 数据完整性检查模块已加载")
except ImportError as e:
    CHECKER_AVAILABLE = False
    print(f"⚠️ 数据完整性检查模块不可用: {e}")


class EnhancedDataFetcher:
    """增强版数据获取器 - 支持长时间范围分批采集"""

    def __init__(self, config_path: str = "config/tushare_config.json",
                 crawler_config_path: str = "config/crawler_config.json",
                 data_dir: str = "data"):
        """初始化增强版数据获取器"""
        self.config_path = config_path
        self.crawler_config_path = crawler_config_path
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        self.tushare_config = {}
        self.crawler_manager = None
        self.data_processor = DataProcessor() if DATA_PROCESSOR_AVAILABLE else None

        # 初始化数据完整性检查器
        self.data_checker = DataCompletenessChecker(str(self.data_dir)) if CHECKER_AVAILABLE else None

        # 加载Tushare配置
        self._load_tushare_config()

        # 初始化爬虫管理器
        if CRAWLER_AVAILABLE:
            self.crawler_manager = CrawlerManager(crawler_config_path)

    def check_existing_data(self, symbol: str, period: str = '5m') -> Dict[str, Any]:
        """检查指定股票的现有数据状态"""
        if not self.data_checker:
            return {'exists': False, 'need_action': True, 'reason': '数据检查器不可用'}

        # 生成标准文件名
        filename = self.get_standard_filename(symbol, period)
        filepath = self.data_dir / filename

        if not filepath.exists():
            return {
                'exists': False,
                'need_action': True,
                'action': 'create',
                'reason': '数据文件不存在',
                'filepath': str(filepath)
            }

        # 分析现有文件
        file_info = {
            'file_path': str(filepath),
            'file_name': filename,
            'exchange': self._get_exchange_code(symbol),
            'period': period,
            'stock_code': self._extract_stock_code(symbol),
            'file_size': filepath.stat().st_size,
            'last_modified': datetime.fromtimestamp(filepath.stat().st_mtime)
        }

        analysis = self.data_checker.analyze_data_file(file_info)

        # 判断是否需要采取行动
        need_action = False
        action = None

        if analysis['status'] in ['empty', 'invalid', 'error']:
            need_action = True
            action = 'reacquire'
        elif analysis.get('freshness') == 'outdated':
            need_action = True
            action = 'update'
        elif analysis.get('completeness') in ['poor', 'fair']:
            need_action = True
            action = 'complete'
        elif analysis.get('freshness') == 'stale':
            need_action = True
            action = 'update'

        return {
            'exists': True,
            'need_action': need_action,
            'action': action,
            'analysis': analysis,
            'file_info': file_info,
            'reason': analysis.get('issue') or analysis.get('freshness_issue') or analysis.get('completeness_issue')
        }

    async def smart_fetch_with_check(self, symbol: str, source: str = 'auto', period: str = '5m',
                                     start_date: str = None, end_date: str = None,
                                     target_days: int = None, force: bool = False) -> Optional[pd.DataFrame]:
        """
        智能数据获取：先检查现有数据，再决定是否需要采集
        
        Args:
            symbol: 股票代码
            source: 数据源
            period: 数据周期
            start_date: 开始日期
            end_date: 结束日期
            target_days: 目标天数
            force: 强制重新采集，忽略现有数据
        
        Returns:
            处理后的数据DataFrame
        """
        print(f"🔍 智能数据获取: {symbol}")

        if not force:
            # 检查现有数据状态
            data_status = self.check_existing_data(symbol, period)

            print(f"📊 数据状态检查:")
            print(f"  - 文件存在: {'是' if data_status['exists'] else '否'}")
            print(f"  - 需要处理: {'是' if data_status['need_action'] else '否'}")

            if data_status['exists'] and data_status.get('reason'):
                print(f"  - 状态说明: {data_status['reason']}")

            if not data_status['need_action']:
                print(f"✅ 现有数据状态良好，无需重新采集")
                # 返回现有数据
                try:
                    filepath = data_status['file_info']['file_path']
                    df = pd.read_csv(filepath)
                    df['timestamps'] = pd.to_datetime(df['timestamps'])
                    print(f"📂 使用现有数据: {len(df)} 条记录")
                    return df
                except Exception as e:
                    print(f"⚠️ 读取现有数据失败: {e}，将重新采集")
            else:
                action = data_status.get('action', 'update')
                print(f"🔄 需要执行操作: {action}")
        else:
            print(f"🔄 强制模式：忽略现有数据，重新采集")

        # 执行数据采集
        return await self.fetch_data(symbol, source, period, start_date, end_date, target_days)

    def get_standard_filename(self, symbol: str, period: str) -> str:
        """生成标准的文件名格式，与data目录现有格式一致"""
        # 转换股票代码格式
        if '.' in symbol:
            code, exchange = symbol.split('.')
            if exchange == 'SZ':
                exchange_code = 'XSHE'
            elif exchange == 'SH':
                exchange_code = 'XSHG'
            else:
                exchange_code = exchange
        else:
            # 根据股票代码推断交易所
            code = symbol.zfill(6)
            if code.startswith(('000', '001', '002', '003', '300')):
                exchange_code = 'XSHE'  # 深交所
            elif code.startswith(('600', '601', '603', '605', '688')):
                exchange_code = 'XSHG'  # 上交所
            else:
                exchange_code = 'XSHG'  # 默认上交所

        # 转换周期格式
        if period == '5m':
            period_str = '5min'
        elif period == '1m':
            period_str = '1min'
        elif period == '15m':
            period_str = '15min'
        elif period == '30m':
            period_str = '30min'
        elif period == '1h':
            period_str = '1h'
        elif period == '1d':
            period_str = 'D'
        else:
            period_str = period

        # 生成标准格式文件名: XSHG_5min_300555.csv
        return f"{exchange_code}_{period_str}_{code}.csv"

    def _get_exchange_code(self, symbol: str) -> str:
        """获取交易所代码"""
        if '.' in symbol:
            _, exchange = symbol.split('.')
            return 'XSHE' if exchange == 'SZ' else 'XSHG'
        else:
            code = symbol.zfill(6)
            return 'XSHE' if code.startswith(('000', '001', '002', '003', '300')) else 'XSHG'

    def _extract_stock_code(self, symbol: str) -> str:
        """提取股票代码"""
        if '.' in symbol:
            code, _ = symbol.split('.')
            return code
        else:
            return symbol.zfill(6)

    def _load_tushare_config(self):
        """加载Tushare配置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.tushare_config = json.load(f)
                print(f"✅ Tushare配置已加载: {self.config_path}")
            else:
                print(f"⚠️ Tushare配置文件不存在: {self.config_path}")
        except Exception as e:
            print(f"❌ 加载Tushare配置失败: {e}")

    def _calculate_time_chunks(self, start_date: str, end_date: str, period: str) -> List[Dict[str, str]]:
        """
        根据数据量计算时间分块
        
        Args:
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 数据周期 (5m, 1h, 1d等)
            
        Returns:
            时间分块列表
        """
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            total_days = (end_dt - start_dt).days

            # 根据周期确定分块策略
            if period in ['1m', '5m']:
                # 分钟级数据：每月分批
                chunk_days = 30
                max_chunks = min(20, (total_days // chunk_days) + 1)
            elif period in ['15m', '30m', '1h']:
                # 小时级数据：每季度分批
                chunk_days = 90
                max_chunks = min(15, (total_days // chunk_days) + 1)
            elif period == '1d':
                # 日线数据：每年分批
                chunk_days = 365
                max_chunks = min(10, (total_days // chunk_days) + 1)
            else:
                # 其他周期：不分批
                return [{'start': start_date, 'end': end_date}]

            print(f"📊 数据分块策略: {period} 周期, 每块 {chunk_days} 天, 最多 {max_chunks} 块")

            # 生成时间分块
            chunks = []
            current_start = start_dt

            while current_start < end_dt and len(chunks) < max_chunks:
                current_end = min(current_start + timedelta(days=chunk_days), end_dt)

                chunks.append({
                    'start': current_start.strftime('%Y-%m-%d'),
                    'end': current_end.strftime('%Y-%m-%d')
                })

                # 下一块的开始时间
                current_start = current_end + timedelta(days=1)

            print(f"🔄 生成 {len(chunks)} 个时间分块")
            return chunks

        except Exception as e:
            print(f"❌ 时间分块计算失败: {e}")
            return [{'start': start_date, 'end': end_date}]

    async def fetch_data_with_crawler(self, symbol: str, period: str = '5m',
                                      start_date: str = None, end_date: str = None,
                                      source: str = 'auto') -> Optional[pd.DataFrame]:
        """
        使用爬虫获取数据（支持分批采集）
        
        Args:
            symbol: 股票代码
            period: 数据周期
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            source: 数据源 (auto, eastmoney, tonghuashun, xueqiu)
            
        Returns:
            数据DataFrame
        """
        if not self.crawler_manager:
            print("❌ 爬虫管理器不可用")
            return None

        # 设置默认时间范围
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

        print(f"📈 开始爬虫数据采集: {symbol}")
        print(f"📅 时间范围: {start_date} 到 {end_date}")
        print(f"⏰ 数据周期: {period}")
        print(f"🌐 数据源: {source}")

        # 计算时间分块
        time_chunks = self._calculate_time_chunks(start_date, end_date, period)

        if len(time_chunks) == 1:
            # 单次获取
            print(f"📦 单次采集数据...")
            return await self.crawler_manager.get_stock_data(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                source=source
            )
        else:
            # 分批获取
            print(f"🔄 分批采集数据（{len(time_chunks)}个批次）...")
            all_dataframes = []

            for i, chunk in enumerate(time_chunks, 1):
                print(f"\\n📦 批次 {i}/{len(time_chunks)}: {chunk['start']} 到 {chunk['end']}")

                try:
                    chunk_df = await self.crawler_manager.get_stock_data(
                        symbol=symbol,
                        period=period,
                        start_date=chunk['start'],
                        end_date=chunk['end'],
                        source=source
                    )

                    if chunk_df is not None and not chunk_df.empty:
                        all_dataframes.append(chunk_df)
                        print(f"✅ 批次 {i} 获取到 {len(chunk_df)} 条数据")
                    else:
                        print(f"⚠️ 批次 {i} 无数据")

                    # 添加延时避免过于频繁的请求
                    if i < len(time_chunks):
                        delay = 1.0 + (i * 0.2)  # 递增延时
                        print(f"⏱️ 等待 {delay:.1f} 秒...")
                        await asyncio.sleep(delay)

                except Exception as e:
                    print(f"❌ 批次 {i} 获取失败: {e}")
                    continue

            if all_dataframes:
                # 合并所有数据
                print(f"\\n🔗 合并 {len(all_dataframes)} 个批次的数据...")
                combined_df = pd.concat(all_dataframes, ignore_index=True)

                # 去重并排序
                if 'timestamps' in combined_df.columns:
                    combined_df['timestamps'] = pd.to_datetime(combined_df['timestamps'])
                    combined_df = combined_df.drop_duplicates(subset=['timestamps']).reset_index(drop=True)
                    combined_df = combined_df.sort_values('timestamps').reset_index(drop=True)

                print(f"🎉 分批采集完成! 总共 {len(combined_df)} 条唯一数据")
                return combined_df
            else:
                print(f"❌ 所有批次都失败，未获取到任何数据")
                return None

    def fetch_data_with_tushare(self, symbol: str, period: str = '1d',
                                start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """
        使用Tushare获取数据（支持分批采集）
        
        Args:
            symbol: 股票代码 (带交易所后缀，如000001.SZ)
            period: 数据周期 (1d, 1w, 1M)
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            
        Returns:
            数据DataFrame
        """
        if not self.tushare_config or 'token' not in self.tushare_config:
            print("❌ Tushare配置不完整，请先配置token")
            return None

        try:
            # 初始化Tushare
            ts.set_token(self.tushare_config['token'])
            pro = ts.pro_api()

            # 设置默认时间范围
            if not end_date:
                end_date = datetime.now().strftime('%Y%m%d')
            else:
                end_date = end_date.replace('-', '')

            if not start_date:
                start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
            else:
                start_date = start_date.replace('-', '')

            print(f"📈 Tushare数据采集: {symbol}")
            print(f"📅 时间范围: {start_date} 到 {end_date}")

            # 计算时间跨度，判断是否需要分批
            start_dt = datetime.strptime(start_date, '%Y%m%d')
            end_dt = datetime.strptime(end_date, '%Y%m%d')
            days_diff = (end_dt - start_dt).days

            # Tushare普通用户限制：每次最多获取约3000条数据
            max_days_per_request = 3000 if period == '1d' else 1000

            if days_diff > max_days_per_request:
                print(f"🔄 数据量过大({days_diff}天)，启用分批采集...")
                return self._fetch_tushare_in_batches(pro, symbol, period, start_date, end_date)
            else:
                # 单次获取
                print(f"📦 单次采集数据...")

                # 根据周期选择API
                if period == '1d':
                    df = pro.daily(ts_code=symbol, start_date=start_date, end_date=end_date)
                elif period == '1w':
                    df = pro.weekly(ts_code=symbol, start_date=start_date, end_date=end_date)
                elif period == '1M':
                    df = pro.monthly(ts_code=symbol, start_date=start_date, end_date=end_date)
                else:
                    # 分钟级数据需要特殊处理
                    print(f"⚠️ Tushare不支持 {period} 周期，建议使用爬虫获取")
                    return None

                if df is not None and not df.empty:
                    # 转换为Kronos格式
                    kronos_df = self._convert_tushare_to_kronos_format(df)
                    print(f"✅ 成功获取 {len(kronos_df)} 条数据")
                    return kronos_df
                else:
                    print(f"❌ 未获取到数据")
                    return None

        except Exception as e:
            print(f"❌ Tushare数据获取失败: {e}")
            return None

    def _fetch_tushare_in_batches(self, pro, symbol: str, period: str, start_date: str, end_date: str) -> Optional[
        pd.DataFrame]:
        """Tushare分批获取数据"""
        start_dt = datetime.strptime(start_date, '%Y%m%d')
        end_dt = datetime.strptime(end_date, '%Y%m%d')

        # 分批策略
        batch_days = 1000 if period == '1d' else 365
        all_dataframes = []
        current_end = end_dt
        batch_count = 0
        max_batches = 10  # 限制最大批次数

        while current_end > start_dt and batch_count < max_batches:
            batch_count += 1
            current_start = max(start_dt, current_end - timedelta(days=batch_days))

            batch_start_str = current_start.strftime('%Y%m%d')
            batch_end_str = current_end.strftime('%Y%m%d')

            print(f"📦 批次 {batch_count}: {batch_start_str} 到 {batch_end_str}")

            try:
                # 根据周期选择API
                if period == '1d':
                    batch_df = pro.daily(ts_code=symbol, start_date=batch_start_str, end_date=batch_end_str)
                elif period == '1w':
                    batch_df = pro.weekly(ts_code=symbol, start_date=batch_start_str, end_date=batch_end_str)
                elif period == '1M':
                    batch_df = pro.monthly(ts_code=symbol, start_date=batch_start_str, end_date=batch_end_str)
                else:
                    print(f"❌ 不支持的周期: {period}")
                    break

                if batch_df is not None and not batch_df.empty:
                    all_dataframes.append(batch_df)
                    print(f"✅ 批次 {batch_count} 获取到 {len(batch_df)} 条数据")
                else:
                    print(f"⚠️ 批次 {batch_count} 无数据")

                current_end = current_start - timedelta(days=1)

                # 添加延时避免API限制
                time.sleep(0.5)

            except Exception as e:
                print(f"❌ 批次 {batch_count} 获取失败: {e}")
                current_end = current_start - timedelta(days=1)
                time.sleep(2)  # 错误时延时更长
                continue

        if all_dataframes:
            # 合并数据
            combined_df = pd.concat(all_dataframes, ignore_index=True)
            combined_df = combined_df.drop_duplicates().sort_values('trade_date').reset_index(drop=True)

            # 转换格式
            kronos_df = self._convert_tushare_to_kronos_format(combined_df)
            print(f"🎉 Tushare分批采集完成! 总共 {len(kronos_df)} 条数据")
            return kronos_df
        else:
            print(f"❌ Tushare分批采集失败")
            return None

    def _convert_tushare_to_kronos_format(self, df: pd.DataFrame) -> pd.DataFrame:
        """将Tushare格式转换为Kronos格式"""
        if df is None or df.empty:
            return pd.DataFrame()

        # Tushare列名映射
        column_mapping = {
            'trade_date': 'timestamps',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'vol': 'volume',
            'amount': 'amount'
        }

        kronos_df = df.copy()

        # 重命名列
        for old_name, new_name in column_mapping.items():
            if old_name in kronos_df.columns:
                kronos_df = kronos_df.rename(columns={old_name: new_name})

        # 处理时间戳
        if 'timestamps' in kronos_df.columns:
            kronos_df['timestamps'] = pd.to_datetime(kronos_df['timestamps'], format='%Y%m%d')

        # 确保数值类型
        numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'amount']
        for col in numeric_columns:
            if col in kronos_df.columns:
                kronos_df[col] = pd.to_numeric(kronos_df[col], errors='coerce')

        # 选择需要的列
        required_columns = ['timestamps', 'open', 'high', 'low', 'close', 'volume', 'amount']
        available_columns = [col for col in required_columns if col in kronos_df.columns]

        return kronos_df[available_columns].copy()

    async def fetch_data(self, symbol: str, source: str = 'auto', period: str = '5m',
                         start_date: str = None, end_date: str = None,
                         target_days: int = None) -> Optional[pd.DataFrame]:
        """
        智能获取股票数据（支持分批采集和自动补全）
        
        Args:
            symbol: 股票代码
            source: 数据源 (auto, tushare, crawler, eastmoney, tonghuashun, xueqiu)
            period: 数据周期
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            target_days: 目标天数（用于数据补全）
            
        Returns:
            处理后的数据DataFrame
        """
        df = None

        # 根据数据源获取数据
        if source == 'tushare':
            print(f"🔄 使用Tushare获取数据...")
            df = self.fetch_data_with_tushare(symbol, period, start_date, end_date)

        elif source in ['crawler', 'auto', 'eastmoney', 'tonghuashun', 'xueqiu']:
            print(f"🔄 使用爬虫获取数据...")
            crawler_source = source if source != 'auto' and source != 'crawler' else 'auto'
            df = await self.fetch_data_with_crawler(symbol, period, start_date, end_date, crawler_source)

        else:
            print(f"❌ 不支持的数据源: {source}")
            return None

        # 数据后处理
        if df is not None and not df.empty:
            print(f"📊 原始数据: {len(df)} 条记录")

            # 如果有数据处理器，进行智能处理
            if self.data_processor and target_days:
                print(f"🔧 启用智能数据处理...")
                df = self.data_processor.smart_data_completion(df, target_days, symbol)
                df = self.data_processor.format_for_analysis(df)
                print(f"📈 处理后数据: {len(df)} 条记录")

            return df
        else:
            print(f"❌ 未获取到任何数据")
            return None


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='增强版股票数据获取工具')
    parser.add_argument('--symbol', '-s', required=True, help='股票代码')
    parser.add_argument('--source', choices=['auto', 'tushare', 'crawler', 'eastmoney', 'tonghuashun', 'xueqiu'],
                        default='auto', help='数据源')
    parser.add_argument('--period', '-p', default='5m', help='数据周期')
    parser.add_argument('--start-date', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=365, help='获取天数（从今天往前）')
    parser.add_argument('--target-days', type=int, help='目标天数（用于数据补全）')
    parser.add_argument('--output-dir', default='data', help='输出目录')
    parser.add_argument('--force', action='store_true', help='强制重新采集，忽略现有数据')
    parser.add_argument('--check-only', action='store_true', help='仅检查数据状态，不进行采集')

    args = parser.parse_args()

    # 创建输出目录
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)

    print(f"🚀 增强版数据获取器启动")
    print(f"📊 股票代码: {args.symbol}")
    print(f"🌐 数据源: {args.source}")
    print(f"⏰ 数据周期: {args.period}")
    print(f"📁 输出目录: {output_dir}")

    # 如果只是检查数据状态
    if args.check_only:
        fetcher = EnhancedDataFetcher(data_dir=str(output_dir))
        data_status = fetcher.check_existing_data(args.symbol, args.period)

        print(f"\n📊 数据状态检查结果:")
        print(f"  - 文件存在: {'是' if data_status['exists'] else '否'}")
        print(f"  - 需要处理: {'是' if data_status['need_action'] else '否'}")
        if data_status.get('reason'):
            print(f"  - 状态说明: {data_status['reason']}")
        if data_status.get('action'):
            print(f"  - 建议操作: {data_status['action']}")

        return 0 if not data_status['need_action'] else 1

    # 设置时间范围
    if not args.end_date:
        args.end_date = datetime.now().strftime('%Y-%m-%d')

    if not args.start_date:
        end_dt = datetime.strptime(args.end_date, '%Y-%m-%d')
        start_dt = end_dt - timedelta(days=args.days)
        args.start_date = start_dt.strftime('%Y-%m-%d')

    print(f"📅 时间范围: {args.start_date} 到 {args.end_date}")

    async def run_fetch():
        fetcher = EnhancedDataFetcher(data_dir=str(output_dir))

        # 使用智能数据获取
        df = await fetcher.smart_fetch_with_check(
            symbol=args.symbol,
            source=args.source,
            period=args.period,
            start_date=args.start_date,
            end_date=args.end_date,
            target_days=args.target_days,
            force=args.force
        )

        if df is not None and not df.empty:
            # 使用fetcher的标准文件名生成方法
            filename = fetcher.get_standard_filename(args.symbol, args.period)
            filepath = output_dir / filename

            try:
                # 保存数据到data目录
                df.to_csv(filepath, index=False)
                print(f"\n✅ 数据已保存到data目录: {filepath}")
                print(f"📊 数据概览:")
                print(f"  - 记录数: {len(df)}")

                if 'timestamps' in df.columns and len(df) > 0:
                    print(f"  - 时间范围: {df['timestamps'].min()} 到 {df['timestamps'].max()}")

                if 'close' in df.columns and len(df) > 0:
                    close_min = df['close'].min()
                    close_max = df['close'].max()
                    if pd.notna(close_min) and pd.notna(close_max):
                        print(f"  - 价格范围: {close_min:.2f} - {close_max:.2f}")

                if 'volume' in df.columns and len(df) > 0:
                    vol_min = df['volume'].min()
                    vol_max = df['volume'].max()
                    if pd.notna(vol_min) and pd.notna(vol_max):
                        print(f"  - 成交量范围: {vol_min:.0f} - {vol_max:.0f}")

                # 验证文件是否真的保存成功
                if filepath.exists():
                    file_size = filepath.stat().st_size
                    print(f"  - 文件大小: {file_size:,} 字节")
                    print(f"💾 确认：数据已成功保存到 {filepath}")
                else:
                    print(f"⚠️ 警告：文件保存可能失败，请检查目录权限")

            except Exception as e:
                print(f"❌ 保存数据到data目录失败: {e}")
                return 1
        else:
            print(f"\n❌ 未获取到数据，无法保存")
            return 1

        return 0

    # 运行异步函数
    exit_code = asyncio.run(run_fetch())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
