#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
0数据问题处理工具 - 专门解决"有些日期下数据为0"的问题
"""

import os
import sys
import asyncio
import argparse
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

try:
    from scripts.eastmoney_crawler import EastMoneyCrawler
    from scripts.data_processor import DataProcessor  # 使用scripts下的DataProcessor

    MODULES_AVAILABLE = True
except ImportError as e:
    MODULES_AVAILABLE = False
    print(f"❌ 模块导入失败: {e}")


class ZeroDataHandler:
    """0数据问题处理器"""

    def __init__(self, data_dir: str = 'data'):
        """初始化处理器"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        if MODULES_AVAILABLE:
            self.crawler = EastMoneyCrawler()
            self.data_processor = DataProcessor()

        print(f"📁 数据保存目录: {self.data_dir.absolute()}")

    async def handle_zero_data_collection(self, symbol: str, period: str = '5m',
                                          days: int = 365, mode: str = 'smart') -> Dict[str, Any]:
        """处理0数据采集问题"""
        if not MODULES_AVAILABLE:
            return {'success': False, 'error': '必需模块不可用'}

        print(f"🎯 处理股票 {symbol} 的0数据问题")
        print(f"📊 目标: {days}天的{period}数据")
        print(f"🧠 模式: {mode}")

        if mode == 'smart':
            return await self._smart_collection_mode(symbol, period, days)
        elif mode == 'recent':
            return await self._recent_data_mode(symbol, period, days)
        elif mode == 'segment':
            return await self._segment_collection_mode(symbol, period, days)
        else:
            return {'success': False, 'error': f'未知模式: {mode}'}

    async def _smart_collection_mode(self, symbol: str, period: str, days: int) -> Dict[str, Any]:
        """智能采集模式 - 自动选择最佳时间段"""
        print(f"🧠 智能采集模式启动...")

        # 定义多个候选时间段
        now = datetime.now()
        time_segments = [
            {
                'name': '最近3个月',
                'start': (now - timedelta(days=90)).strftime('%Y-%m-%d'),
                'end': (now - timedelta(days=1)).strftime('%Y-%m-%d'),
                'priority': 1
            },
            {
                'name': '最近6个月',
                'start': (now - timedelta(days=180)).strftime('%Y-%m-%d'),
                'end': (now - timedelta(days=1)).strftime('%Y-%m-%d'),
                'priority': 2
            },
            {
                'name': '去年同期',
                'start': (now - timedelta(days=365)).strftime('%Y-%m-%d'),
                'end': (now - timedelta(days=275)).strftime('%Y-%m-%d'),
                'priority': 3
            }
        ]

        results = []
        total_collected = 0

        for segment in time_segments:
            if total_collected >= days * 0.8:  # 达到80%目标即可
                break

            print(f"\\n📦 尝试时段: {segment['name']}")
            print(f"📅 时间: {segment['start']} 到 {segment['end']}")

            try:
                data = await self.crawler.get_kline_data(
                    symbol=symbol,
                    period=period,
                    start_date=segment['start'].replace('-', ''),
                    end_date=segment['end'].replace('-', '')
                )

                if data and data.get('rc') == 0:
                    klines = data.get('data', {}).get('klines', [])
                    if klines:
                        # 直接使用现有的处理方法
                        df_data = []
                        for kline in klines:
                            # 东方财富K线数据格式: "时间,开盘,收盘,最高,最低,成交量,成交额,..."
                            parts = kline.split(',')
                            if len(parts) >= 7:
                                df_data.append({
                                    'timestamps': parts[0],
                                    'open': float(parts[1]) if parts[1] else 0,
                                    'close': float(parts[2]) if parts[2] else 0,
                                    'high': float(parts[3]) if parts[3] else 0,
                                    'low': float(parts[4]) if parts[4] else 0,
                                    'volume': float(parts[5]) if parts[5] else 0,
                                    'amount': float(parts[6]) if parts[6] else 0
                                })

                        if df_data:
                            df = pd.DataFrame(df_data)
                            # 标准化数据格式
                            df = self.data_processor._standardize_csv_format(df)
                        if df is not None and not df.empty:
                            collected_count = len(df)
                            total_collected += collected_count

                            # 保存数据
                            filepath = await self._save_data(df, symbol, period, segment['name'])

                            results.append({
                                'segment': segment['name'],
                                'records': collected_count,
                                'file_path': filepath,
                                'success': True
                            })

                            print(f"✅ 成功采集 {collected_count} 条数据")
                        else:
                            print(f"❌ 数据处理失败")
                    else:
                        print(f"⚠️ 该时段无数据")
                        results.append({
                            'segment': segment['name'],
                            'success': False,
                            'reason': '该时段无交易数据'
                        })
                else:
                    print(f"❌ API调用失败")

            except Exception as e:
                print(f"❌ 采集异常: {e}")
                results.append({
                    'segment': segment['name'],
                    'success': False,
                    'error': str(e)
                })

            await asyncio.sleep(1)  # 延时避免过快请求

        success_count = len([r for r in results if r.get('success', False)])
        return {
            'success': success_count > 0,
            'mode': 'smart',
            'total_records': total_collected,
            'successful_segments': success_count,
            'results': results
        }

    async def _recent_data_mode(self, symbol: str, period: str, days: int) -> Dict[str, Any]:
        """最近数据模式 - 只采集最近的有效交易日"""
        print(f"📅 最近数据模式启动...")

        now = datetime.now()
        # 确保不采集未来和当天的数据
        end_date = now - timedelta(days=1)
        start_date = end_date - timedelta(days=min(days, 180))  # 限制在6个月内

        print(f"📊 时间范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")

        try:
            data = await self.crawler.get_kline_data(
                symbol=symbol,
                period=period,
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )

            if data and data.get('rc') == 0:
                klines = data.get('data', {}).get('klines', [])
                if klines:
                    # 直接处理K线数据
                    df_data = []
                    for kline in klines:
                        # 东方财富K线数据格式: "时间,开盘,收盘,最高,最低,成交量,成交额,..."
                        parts = kline.split(',')
                        if len(parts) >= 7:
                            df_data.append({
                                'timestamps': parts[0],
                                'open': float(parts[1]) if parts[1] else 0,
                                'close': float(parts[2]) if parts[2] else 0,
                                'high': float(parts[3]) if parts[3] else 0,
                                'low': float(parts[4]) if parts[4] else 0,
                                'volume': float(parts[5]) if parts[5] else 0,
                                'amount': float(parts[6]) if parts[6] else 0
                            })

                    if df_data:
                        df = pd.DataFrame(df_data)
                        # 标准化数据格式
                        df = self.data_processor._standardize_csv_format(df)
                        if df is not None and not df.empty:
                            filepath = await self._save_data(df, symbol, period, '最近数据')

                            return {
                                'success': True,
                                'mode': 'recent',
                                'records': len(df),
                                'file_path': filepath,
                                'time_range': f"{df['timestamps'].min()} 到 {df['timestamps'].max()}"
                            }

            return {
                'success': False,
                'mode': 'recent',
                'error': '未获取到有效数据'
            }

        except Exception as e:
            return {
                'success': False,
                'mode': 'recent',
                'error': str(e)
            }

    async def _segment_collection_mode(self, symbol: str, period: str, days: int) -> Dict[str, Any]:
        """分段采集模式 - 将长时间范围分成多个短段"""
        print(f"🔄 分段采集模式启动...")

        now = datetime.now()
        end_date = now - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        # 计算分段策略
        if days <= 90:
            segment_days = 30  # 每段30天
        elif days <= 180:
            segment_days = 45  # 每段45天
        else:
            segment_days = 60  # 每段60天

        print(f"📊 总时间范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")
        print(f"🔄 分段策略: 每段{segment_days}天")

        segments = []
        current_end = end_date

        while current_end > start_date:
            current_start = max(start_date, current_end - timedelta(days=segment_days))
            segments.append({
                'start': current_start,
                'end': current_end,
                'name': f"{current_start.strftime('%m%d')}_{current_end.strftime('%m%d')}"
            })
            current_end = current_start - timedelta(days=1)

        print(f"📦 总共{len(segments)}个分段")

        results = []
        total_collected = 0
        all_dataframes = []

        for i, segment in enumerate(segments, 1):
            print(
                f"\\n📦 分段 {i}/{len(segments)}: {segment['start'].strftime('%Y-%m-%d')} 到 {segment['end'].strftime('%Y-%m-%d')}")

            try:
                data = await self.crawler.get_kline_data(
                    symbol=symbol,
                    period=period,
                    start_date=segment['start'].strftime('%Y%m%d'),
                    end_date=segment['end'].strftime('%Y%m%d')
                )

                if data and data.get('rc') == 0:
                    klines = data.get('data', {}).get('klines', [])
                    if klines:
                        # 直接处理K线数据
                        df_data = []
                        for kline in klines:
                            # 东方财富K线数据格式: "时间,开盘,收盘,最高,最低,成交量,成交额,..."
                            parts = kline.split(',')
                            if len(parts) >= 7:
                                df_data.append({
                                    'timestamps': parts[0],
                                    'open': float(parts[1]) if parts[1] else 0,
                                    'close': float(parts[2]) if parts[2] else 0,
                                    'high': float(parts[3]) if parts[3] else 0,
                                    'low': float(parts[4]) if parts[4] else 0,
                                    'volume': float(parts[5]) if parts[5] else 0,
                                    'amount': float(parts[6]) if parts[6] else 0
                                })

                        if df_data:
                            df = pd.DataFrame(df_data)
                            # 标准化数据格式
                            df = self.data_processor._standardize_csv_format(df)
                            if df is not None and not df.empty:
                                collected = len(df)
                                total_collected += collected
                                all_dataframes.append(df)

                                results.append({
                                    'segment': segment['name'],
                                    'records': collected,
                                    'success': True
                                })

                                print(f"✅ 采集到 {collected} 条数据")
                            else:
                                print(f"❌ 数据处理失败")
                        else:
                            print(f"⚠️ 该分段无数据")
                            results.append({
                                'segment': segment['name'],
                                'success': False,
                                'reason': '无数据'
                            })

            except Exception as e:
                print(f"❌ 分段 {i} 异常: {e}")
                results.append({
                    'segment': segment['name'],
                    'success': False,
                    'error': str(e)
                })

            await asyncio.sleep(1)

        # 合并所有成功的数据
        if all_dataframes:
            combined_df = pd.concat(all_dataframes, ignore_index=True)
            combined_df['timestamps'] = pd.to_datetime(combined_df['timestamps'])
            combined_df = combined_df.drop_duplicates(subset=['timestamps']).reset_index(drop=True)
            combined_df = combined_df.sort_values('timestamps').reset_index(drop=True)

            filepath = await self._save_data(combined_df, symbol, period, '分段采集')

            return {
                'success': True,
                'mode': 'segment',
                'total_records': len(combined_df),
                'successful_segments': len([r for r in results if r.get('success', False)]),
                'file_path': filepath,
                'time_range': f"{combined_df['timestamps'].min()} 到 {combined_df['timestamps'].max()}",
                'results': results
            }
        else:
            return {
                'success': False,
                'mode': 'segment',
                'error': '所有分段都失败',
                'results': results
            }

    def _get_standard_filename(self, symbol: str, period: str) -> str:
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

    async def _save_data(self, df: pd.DataFrame, symbol: str, period: str, mode_name: str) -> str:
        """保存数据到data目录，使用标准文件名格式"""
        # 使用标准文件名格式
        filename = self._get_standard_filename(symbol, period)
        filepath = self.data_dir / filename

        try:
            df.to_csv(filepath, index=False)
            print(f"💾 数据已保存到标准格式文件: {filepath}")

            # 显示保存的数据信息
            print(f"📊 文件信息:")
            print(f"   - 文件名: {filename}")
            print(f"   - 记录数: {len(df)}")
            if not df.empty and 'timestamps' in df.columns:
                print(f"   - 时间范围: {df['timestamps'].min()} 到 {df['timestamps'].max()}")

            return str(filepath)
        except Exception as e:
            print(f"❌ 保存失败: {e}")
            return ""

    def print_summary(self, result: Dict[str, Any]):
        """打印处理结果摘要"""
        print(f"\\n{'=' * 60}")
        print(f"📊 0数据问题处理结果")
        print(f"{'=' * 60}")

        if result['success']:
            print(f"✅ 处理成功")
            print(f"🧠 使用模式: {result['mode']}")
            print(f"📈 总记录数: {result.get('total_records', 0):,}")

            if 'file_path' in result:
                print(f"💾 数据文件: {result['file_path']}")

            if 'time_range' in result:
                print(f"📅 时间范围: {result['time_range']}")

            if 'successful_segments' in result:
                print(f"📦 成功分段: {result['successful_segments']}")

        else:
            print(f"❌ 处理失败: {result.get('error', 'Unknown')}")

        print(f"\\n💡 建议:")
        if result['success']:
            print(f"  🎉 数据已成功保存到data目录")
            print(f"  📊 现在可以用这些数据进行预测分析")
        else:
            print(f"  🔄 尝试其他采集模式:")
            print(f"    - --mode recent : 仅采集最近有效数据")
            print(f"    - --mode segment: 分段采集长时间范围")
            print(f"  📅 或者调整时间范围参数")

        print(f"{'=' * 60}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='0数据问题处理工具')
    parser.add_argument('--symbol', '-s', required=True, help='股票代码')
    parser.add_argument('--period', '-p', default='5m',
                        help='数据周期 (1m, 5m, 15m, 30m, 1h, 1d)')
    parser.add_argument('--days', '-d', type=int, default=180,
                        help='目标天数 (默认: 180)')
    parser.add_argument('--mode', '-m', choices=['smart', 'recent', 'segment'],
                        default='smart', help='处理模式')
    parser.add_argument('--data-dir', default='data', help='数据保存目录')

    args = parser.parse_args()

    print(f"🛠️  0数据问题处理工具")
    print(f"📊 股票: {args.symbol}")
    print(f"⏰ 周期: {args.period}")
    print(f"📅 天数: {args.days}")
    print(f"🧠 模式: {args.mode}")
    print(f"📁 数据目录: {args.data_dir}")

    handler = ZeroDataHandler(args.data_dir)

    result = await handler.handle_zero_data_collection(
        symbol=args.symbol,
        period=args.period,
        days=args.days,
        mode=args.mode
    )

    handler.print_summary(result)

    return 0 if result['success'] else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
