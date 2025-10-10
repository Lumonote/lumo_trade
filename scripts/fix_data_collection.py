#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据采集修复脚本
专门解决"有些获取的数据为0"的问题，并确保数据正确保存到data目录
"""

import os
import sys
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging
from typing import List, Dict, Any, Optional

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from scripts.eastmoney_crawler import EastMoneyCrawler
    from scripts.crawler import CrawlerManager
    from analysis.data_processor import DataProcessor

    MODULES_AVAILABLE = True
except ImportError as e:
    MODULES_AVAILABLE = False
    logger.error(f"模块导入失败: {e}")


class DataCollectionFixer:
    """数据采集修复器 - 专门解决0数据问题"""

    def __init__(self, data_dir: str = 'data'):
        """初始化修复器"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        if MODULES_AVAILABLE:
            self.crawler = EastMoneyCrawler()
            self.crawler_manager = CrawlerManager()
            self.data_processor = DataProcessor()

        logger.info(f"数据目录: {self.data_dir.absolute()}")

    def detect_stock_listing_date(self, symbol: str) -> datetime:
        """检测股票上市时间（简化版）"""
        # 根据股票代码前缀估算上市时间
        code = symbol.split('.')[0] if '.' in symbol else symbol

        # 常见股票上市时间规律
        if code.startswith('688'):  # 科创板
            return datetime(2019, 7, 1)
        elif code.startswith('300'):  # 创业板
            if int(code) <= 300100:
                return datetime(2009, 10, 1)
            elif int(code) <= 300500:
                return datetime(2012, 1, 1)
            else:
                return datetime(2015, 1, 1)
        elif code.startswith('000') or code.startswith('002'):  # 深市主板/中小板
            if int(code) <= 2000:
                return datetime(1990, 12, 1)
            else:
                return datetime(2004, 5, 1)
        elif code.startswith('600') or code.startswith('601') or code.startswith('603'):  # 沪市主板
            return datetime(1990, 12, 1)
        else:
            # 默认上市时间
            return datetime(2000, 1, 1)

    def calculate_optimal_time_range(self, symbol: str, requested_start: str,
                                     requested_end: str) -> Dict[str, str]:
        """计算最优时间范围，避免请求过早的历史数据"""
        listing_date = self.detect_stock_listing_date(symbol)

        start_dt = datetime.strptime(requested_start, '%Y-%m-%d')
        end_dt = datetime.strptime(requested_end, '%Y-%m-%d')

        # 确保开始时间不早于上市时间
        if start_dt < listing_date:
            optimal_start = listing_date
            logger.warning(f"股票 {symbol} 上市时间约为 {listing_date.strftime('%Y-%m-%d')}")
            logger.warning(f"调整开始时间: {requested_start} -> {optimal_start.strftime('%Y-%m-%d')}")
        else:
            optimal_start = start_dt

        return {
            'start': optimal_start.strftime('%Y-%m-%d'),
            'end': end_dt.strftime('%Y-%m-%d'),
            'adjusted': optimal_start != start_dt,
            'listing_date': listing_date.strftime('%Y-%m-%d')
        }

    async def smart_batch_collection(self, symbol: str, period: str = '5m',
                                     start_date: str = None, end_date: str = None,
                                     max_retries: int = 3) -> Optional[pd.DataFrame]:
        """智能分批采集，解决0数据问题"""
        if not MODULES_AVAILABLE:
            logger.error("必需模块不可用")
            return None

        # 设置默认时间范围
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

        # 计算最优时间范围
        time_range = self.calculate_optimal_time_range(symbol, start_date, end_date)
        logger.info(f"时间范围优化: {time_range}")

        # 如果时间范围被调整，使用新的时间范围
        if time_range['adjusted']:
            start_date = time_range['start']
            logger.info(f"使用调整后的时间范围: {start_date} 到 {end_date}")

        logger.info(f"开始智能分批采集: {symbol}")
        logger.info(f"时间范围: {start_date} 到 {end_date}")
        logger.info(f"数据周期: {period}")

        success_data = []
        total_attempts = 0
        successful_batches = 0

        try:
            # 使用东方财富爬虫进行分批采集
            data = await self.crawler.get_kline_data(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date
            )

            total_attempts += 1

            if data and data.get('rc') == 0:
                klines = data.get('data', {}).get('klines', [])
                if klines:
                    logger.info(f"✅ 成功获取 {len(klines)} 条原始数据")

                    # 处理数据格式
                    processed_df = self.data_processor.process_eastmoney_data(data, symbol)

                    if processed_df is not None and not processed_df.empty:
                        success_data.append(processed_df)
                        successful_batches += 1
                        logger.info(f"✅ 数据处理成功: {len(processed_df)} 条记录")
                    else:
                        logger.warning("数据处理后为空")
                else:
                    logger.warning("API响应成功但无klines数据")

                    # 如果是因为时间过早，尝试更近期的数据
                    recent_start = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
                    if start_date < recent_start:
                        logger.info(f"尝试获取更近期的数据: {recent_start} 到 {end_date}")

                        retry_data = await self.crawler.get_kline_data(
                            symbol=symbol,
                            period=period,
                            start_date=recent_start,
                            end_date=end_date
                        )

                        total_attempts += 1

                        if retry_data and retry_data.get('rc') == 0:
                            retry_klines = retry_data.get('data', {}).get('klines', [])
                            if retry_klines:
                                processed_df = self.data_processor.process_eastmoney_data(retry_data, symbol)
                                if processed_df is not None and not processed_df.empty:
                                    success_data.append(processed_df)
                                    successful_batches += 1
                                    logger.info(f"✅ 近期数据获取成功: {len(processed_df)} 条记录")
            else:
                error_code = data.get('rc', 'Unknown') if data else 'No Response'
                logger.error(f"数据获取失败，错误码: {error_code}")

            # 合并成功的数据
            if success_data:
                combined_df = pd.concat(success_data, ignore_index=True)

                # 去重和排序
                if 'timestamps' in combined_df.columns:
                    combined_df['timestamps'] = pd.to_datetime(combined_df['timestamps'])
                    combined_df = combined_df.drop_duplicates(subset=['timestamps']).reset_index(drop=True)
                    combined_df = combined_df.sort_values('timestamps').reset_index(drop=True)

                logger.info(f"🎉 智能采集完成!")
                logger.info(f"📊 总尝试次数: {total_attempts}")
                logger.info(f"✅ 成功批次: {successful_batches}")
                logger.info(f"📈 最终记录数: {len(combined_df)}")

                return combined_df
            else:
                logger.error("所有批次都失败，未获取到任何数据")
                return None

        except Exception as e:
            logger.error(f"智能分批采集异常: {e}")
            return None

    async def collect_and_save_data(self, symbol: str, period: str = '5m',
                                    days: int = 365) -> Dict[str, Any]:
        """采集数据并确保保存到data目录"""
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        logger.info(f"📊 开始数据采集和保存: {symbol}")
        logger.info(f"📅 时间范围: {start_date} 到 {end_date} ({days}天)")
        logger.info(f"⏰ 数据周期: {period}")
        logger.info(f"📁 保存目录: {self.data_dir}")

        result = {
            'symbol': symbol,
            'success': False,
            'records': 0,
            'file_path': '',
            'file_size': 0,
            'error': ''
        }

        try:
            # 使用智能分批采集
            df = await self.smart_batch_collection(symbol, period, start_date, end_date)

            if df is not None and not df.empty:
                result['records'] = len(df)

                # 生成文件名
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{symbol}_{period}_fixed_{timestamp}.csv"
                filepath = self.data_dir / filename

                try:
                    # 确保data目录存在
                    self.data_dir.mkdir(exist_ok=True)

                    # 保存数据
                    df.to_csv(filepath, index=False)

                    # 验证保存结果
                    if filepath.exists():
                        file_size = filepath.stat().st_size
                        result['success'] = True
                        result['file_path'] = str(filepath)
                        result['file_size'] = file_size

                        # 验证数据完整性
                        verification_df = pd.read_csv(filepath)
                        if len(verification_df) == len(df):
                            logger.info(f"✅ 数据已成功保存并验证: {filepath}")
                            logger.info(f"📊 记录数: {len(df)}")
                            logger.info(f"💾 文件大小: {file_size:,} 字节")
                            logger.info(f"📅 数据时间范围: {df['timestamps'].min()} 到 {df['timestamps'].max()}")
                        else:
                            logger.warning(f"数据完整性验证失败: 保存{len(verification_df)}条，原始{len(df)}条")
                    else:
                        result['error'] = '文件保存后不存在，可能权限问题'
                        logger.error(result['error'])

                except Exception as save_error:
                    result['error'] = f'保存数据失败: {save_error}'
                    logger.error(result['error'])
            else:
                result['error'] = '数据采集失败或为空'
                logger.error(result['error'])

        except Exception as e:
            result['error'] = f'采集过程异常: {e}'
            logger.error(result['error'])

        return result

    def print_summary(self, results: List[Dict[str, Any]]):
        """打印汇总报告"""
        total = len(results)
        successful = len([r for r in results if r['success']])
        failed = total - successful
        total_records = sum(r['records'] for r in results if r['success'])
        total_size = sum(r['file_size'] for r in results if r['success'])

        print(f"\n{'=' * 70}")
        print(f"📊 数据采集修复汇总报告")
        print(f"{'=' * 70}")
        print(f"📈 处理股票数: {total}")
        print(f"✅ 成功采集: {successful} ({successful / total * 100:.1f}%)")
        print(f"❌ 失败采集: {failed} ({failed / total * 100:.1f}%)")
        print(f"📊 总记录数: {total_records:,}")
        print(f"💾 总文件大小: {total_size:,} 字节")
        print(f"📁 数据保存目录: {self.data_dir.absolute()}")

        if successful > 0:
            print(f"\n✅ 成功采集的股票:")
            for r in results:
                if r['success']:
                    print(f"  📈 {r['symbol']}: {r['records']:,} 条记录")
                    print(f"      💾 文件: {Path(r['file_path']).name}")
                    print(f"      📊 大小: {r['file_size']:,} 字节")

        if failed > 0:
            print(f"\n❌ 采集失败的股票:")
            for r in results:
                if not r['success']:
                    print(f"  ❌ {r['symbol']}: {r['error']}")

        print(f"\n💡 修复建议:")
        if failed == 0:
            print(f"  🎉 所有股票数据采集成功！")
        else:
            print(f"  🔄 对于失败的股票，可尝试:")
            print(f"    - 调整时间范围（缩短到最近6个月）")
            print(f"    - 检查股票代码是否正确")
            print(f"    - 确认股票是否已上市")
        print(f"{'=' * 70}")


async def main():
    """主函数"""
    # 测试股票列表（包含一些可能有问题的股票）
    test_symbols = [
        '300622',  # 盈趣科技
        '000001',  # 平安银行
        '600977',  # 朗新科技
        '688343'  # 科创板股票
    ]

    print(f"🚀 数据采集修复器启动")
    print(f"🎯 目标：解决'有些获取的数据为0'问题")
    print(f"📊 测试股票: {', '.join(test_symbols)}")

    fixer = DataCollectionFixer()
    results = []

    for i, symbol in enumerate(test_symbols, 1):
        print(f"\n🔄 [{i}/{len(test_symbols)}] 处理股票: {symbol}")
        result = await fixer.collect_and_save_data(symbol, period='5m', days=180)
        results.append(result)

        # 添加延时避免请求过快
        if i < len(test_symbols):
            await asyncio.sleep(2)

    # 打印汇总报告
    fixer.print_summary(results)

    # 返回状态码
    successful_count = len([r for r in results if r['success']])
    if successful_count == len(test_symbols):
        return 0  # 全部成功
    elif successful_count > 0:
        return 2  # 部分成功  
    else:
        return 1  # 全部失败


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
