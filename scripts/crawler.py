#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主爬虫脚本
整合多个数据源的Playwright爬虫，支持智能切换和反爬虫处理
"""

import asyncio
import json
import logging
import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.eastmoney_crawler import EastMoneyCrawler
from scripts.tonghuashun_crawler import TongHuaShunCrawler
from scripts.xueqiu_crawler import XueQiuCrawler
from scripts.data_processor import DataProcessor
from scripts.anti_crawler import AntiCrawlerHandler, RateLimiter
from scripts.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


class CrawlerManager:
    """爬虫管理器"""

    def __init__(self, config_path: str = None):
        self.config_path = config_path or os.path.join(project_root, 'config', 'crawler_config.json')
        self.config = self._load_config()

        # 初始化组件
        self.browser_manager = BrowserManager(self.config_path)
        self.anti_crawler = AntiCrawlerHandler(self.config.get('anti_crawler_settings', {}))
        self.data_processor = DataProcessor(self.config_path)

        # 数据源状态跟踪
        self.source_status = {}
        self.failure_counts = {}

        # 初始化爬虫实例
        self.crawlers = {}
        self._init_crawlers()

        # 速率限制器
        rate_config = self.config.get('anti_crawler_settings', {}).get('rate_limiting', {})
        self.rate_limiter = RateLimiter(
            max_requests=rate_config.get('max_requests_per_minute', 10),
            time_window=rate_config.get('time_window', 60)
        )

        logger.info("爬虫管理器初始化完成")

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info(f"配置文件加载成功: {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"配置文件加载失败: {e}")
            return {}

    def _init_crawlers(self):
        """初始化爬虫实例"""
        data_sources = self.config.get('data_sources', {})

        for source_name, source_config in data_sources.items():
            if not source_config.get('enabled', False):
                continue

            try:
                if source_name == 'eastmoney':
                    crawler = EastMoneyCrawler(self.config_path)
                elif source_name == 'tonghuashun':
                    crawler = TongHuaShunCrawler(self.config_path)
                elif source_name == 'xueqiu':
                    crawler = XueQiuCrawler(self.config_path)
                else:
                    logger.warning(f"未知的数据源: {source_name}")
                    continue

                self.crawlers[source_name] = crawler
                self.source_status[source_name] = 'active'
                self.failure_counts[source_name] = 0

                logger.info(f"爬虫初始化成功: {source_name}")

            except Exception as e:
                logger.error(f"爬虫初始化失败 {source_name}: {e}")
                self.source_status[source_name] = 'failed'

    def get_available_sources(self) -> List[str]:
        """获取可用的数据源列表"""
        available = []
        for source_name, status in self.source_status.items():
            if status == 'active' and source_name in self.crawlers:
                available.append(source_name)
        return available

    def get_priority_source(self) -> Optional[str]:
        """获取优先级最高的可用数据源"""
        available_sources = self.get_available_sources()
        if not available_sources:
            return None

        # 按优先级排序
        data_sources = self.config.get('data_sources', {})
        sorted_sources = sorted(
            available_sources,
            key=lambda x: data_sources.get(x, {}).get('priority', 999)
        )

        return sorted_sources[0] if sorted_sources else None

    async def get_realtime_data(self, symbol: str, source: str = None) -> Optional[Dict[str, Any]]:
        """获取实时数据"""
        await self.rate_limiter.acquire()

        if source:
            sources_to_try = [source] if source in self.crawlers else []
        else:
            sources_to_try = self.get_available_sources()
            # 按优先级排序
            data_sources = self.config.get('data_sources', {})
            sources_to_try.sort(key=lambda x: data_sources.get(x, {}).get('priority', 999))

        for source_name in sources_to_try:
            try:
                crawler = self.crawlers[source_name]

                # 可用性检查已禁用 - 直接尝试获取数据
                # print(f"🔍 检查数据源 {source_name} 可用性...")
                # is_available = await self._check_source_availability(source_name)
                # print(f"📊 数据源 {source_name} 可用性检查结果: {is_available}")
                # if not is_available:
                #     print(f"❌ 数据源 {source_name} 不可用，跳过")
                #     continue

                logger.info(f"使用数据源 {source_name} 获取 {symbol} 的数据")

                # 获取数据 - 雪球爬虫需要传递列表参数
                if source_name == 'xueqiu':
                    data = await crawler.get_realtime_data([symbol])
                    # 雪球返回列表，取第一个元素
                    if data and isinstance(data, list) and len(data) > 0:
                        data = data[0]
                else:
                    data = await crawler.get_realtime_data(symbol)

                if data:
                    # 重置失败计数
                    self.failure_counts[source_name] = 0
                    self.source_status[source_name] = 'active'

                    # 数据处理和验证
                    processed_data = self.data_processor.process_realtime_data(data, source_name)
                    return processed_data

            except Exception as e:
                logger.error(f"数据源 {source_name} 获取数据失败: {e}")
                await self._handle_source_failure(source_name, e)
                continue

        logger.warning(f"所有数据源都无法获取 {symbol} 的实时数据")
        return None

    async def get_kline_data(self, symbol: str, period: str = '1d',
                             start_date: str = None, end_date: str = None,
                             source: str = None) -> Optional[List[Dict[str, Any]]]:
        """获取K线数据"""
        await self.rate_limiter.acquire()

        if source:
            sources_to_try = [source] if source in self.crawlers else []
        else:
            sources_to_try = self.get_available_sources()
            # 按优先级排序
            data_sources = self.config.get('data_sources', {})
            sources_to_try.sort(key=lambda x: data_sources.get(x, {}).get('priority', 999))

        for source_name in sources_to_try:
            try:
                crawler = self.crawlers[source_name]

                # 检查数据源是否可用
                if not await self._check_source_availability(source_name):
                    continue

                logger.info(f"使用数据源 {source_name} 获取 {symbol} 的K线数据")

                # 获取数据
                data = await crawler.get_kline_data(symbol, period, start_date, end_date)

                if data:
                    # 重置失败计数
                    self.failure_counts[source_name] = 0
                    self.source_status[source_name] = 'active'

                    # 数据处理和验证
                    processed_data = self.data_processor.process_kline_data(data, source_name)
                    return processed_data

            except Exception as e:
                logger.error(f"数据源 {source_name} 获取K线数据失败: {e}")
                await self._handle_source_failure(source_name, e)
                continue

        logger.warning(f"所有数据源都无法获取 {symbol} 的K线数据")
        return None

    async def get_minute_data(self, symbol: str, source: str = None) -> Optional[List[Dict[str, Any]]]:
        """获取分时数据"""
        await self.rate_limiter.acquire()

        if source:
            sources_to_try = [source] if source in self.crawlers else []
        else:
            sources_to_try = self.get_available_sources()
            # 按优先级排序
            data_sources = self.config.get('data_sources', {})
            sources_to_try.sort(key=lambda x: data_sources.get(x, {}).get('priority', 999))

        for source_name in sources_to_try:
            try:
                crawler = self.crawlers[source_name]

                # 检查数据源是否可用
                if not await self._check_source_availability(source_name):
                    continue

                logger.info(f"使用数据源 {source_name} 获取 {symbol} 的分时数据")

                # 获取数据
                data = await crawler.get_minute_data(symbol)

                if data:
                    # 重置失败计数
                    self.failure_counts[source_name] = 0
                    self.source_status[source_name] = 'active'

                    # 数据处理和验证
                    processed_data = self.data_processor.process_minute_data(data, source_name)
                    return processed_data

            except Exception as e:
                logger.error(f"数据源 {source_name} 获取分时数据失败: {e}")
                await self._handle_source_failure(source_name, e)
                continue

        logger.warning(f"所有数据源都无法获取 {symbol} 的分时数据")
        return None

    async def _check_source_availability(self, source_name: str) -> bool:
        """检查数据源可用性"""
        if source_name not in self.crawlers:
            return False

        # 检查失败次数
        max_failures = self.config.get('fallback_strategy', {}).get('max_source_failures', 3)
        if self.failure_counts.get(source_name, 0) >= max_failures:
            # 检查冷却期
            cooldown = self.config.get('fallback_strategy', {}).get('cooldown_period', 300)
            if hasattr(self, f'_{source_name}_last_failure'):
                last_failure = getattr(self, f'_{source_name}_last_failure')
                if time.time() - last_failure < cooldown:
                    return False
                else:
                    # 冷却期结束，重置失败计数
                    self.failure_counts[source_name] = 0
                    self.source_status[source_name] = 'active'

        try:
            crawler = self.crawlers[source_name]
            is_available = await crawler.check_availability()

            if not is_available:
                self.source_status[source_name] = 'unavailable'
                return False

            self.source_status[source_name] = 'active'
            return True

        except Exception as e:
            logger.error(f"检查数据源 {source_name} 可用性失败: {e}")
            self.source_status[source_name] = 'error'
            return False

    async def _handle_source_failure(self, source_name: str, error: Exception):
        """处理数据源失败"""
        self.failure_counts[source_name] = self.failure_counts.get(source_name, 0) + 1
        setattr(self, f'_{source_name}_last_failure', time.time())

        max_failures = self.config.get('fallback_strategy', {}).get('max_source_failures', 3)

        if self.failure_counts[source_name] >= max_failures:
            self.source_status[source_name] = 'disabled'
            logger.warning(f"数据源 {source_name} 失败次数过多，暂时禁用")
        else:
            self.source_status[source_name] = 'error'

        # 如果支持重试，添加延时
        if self.anti_crawler.should_retry(error, self.failure_counts[source_name]):
            delay = self.anti_crawler.get_retry_delay(self.failure_counts[source_name])
            logger.info(f"数据源 {source_name} 将在 {delay:.2f} 秒后重试")
            await asyncio.sleep(delay)

    async def get_stock_info(self, symbol: str, source: str = None) -> Optional[Dict[str, Any]]:
        """获取股票基本信息"""
        await self.rate_limiter.acquire()

        if source:
            sources_to_try = [source] if source in self.crawlers else []
        else:
            sources_to_try = self.get_available_sources()

        for source_name in sources_to_try:
            try:
                crawler = self.crawlers[source_name]

                if not await self._check_source_availability(source_name):
                    continue

                logger.info(f"使用数据源 {source_name} 获取 {symbol} 的基本信息")

                data = await crawler.get_stock_info(symbol)

                if data:
                    self.failure_counts[source_name] = 0
                    self.source_status[source_name] = 'active'
                    return data

            except Exception as e:
                logger.error(f"数据源 {source_name} 获取股票信息失败: {e}")
                await self._handle_source_failure(source_name, e)
                continue

        logger.warning(f"所有数据源都无法获取 {symbol} 的基本信息")
        return None

    async def get_stock_data(self, symbol: str, period: str = '5m',
                             start_date: str = None, end_date: str = None,
                             source: str = None) -> Optional[pd.DataFrame]:
        """
        获取股票数据并返回DataFrame格式（统一接口）
        
        Args:
            symbol: 股票代码
            period: 数据周期
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD) 
            source: 指定数据源
            
        Returns:
            DataFrame格式的股票数据
        """
        # 获取K线数据
        kline_data = await self.get_kline_data(symbol, period, start_date, end_date, source)

        if not kline_data:
            logger.warning(f"未获取到 {symbol} 的K线数据")
            return None

        try:
            # 转换为DataFrame格式
            df = self.data_processor.convert_to_dataframe(kline_data, period)

            if df is not None and not df.empty:
                logger.info(f"成功获取并转换 {symbol} 的数据: {len(df)} 条记录")
                return df
            else:
                logger.warning(f"数据转换失败: {symbol}")
                return None

        except Exception as e:
            logger.error(f"数据转换出错: {e}")
            return None

    def get_source_status(self) -> Dict[str, Any]:
        """获取数据源状态"""
        status_info = {}
        for source_name in self.crawlers.keys():
            status_info[source_name] = {
                'status': self.source_status.get(source_name, 'unknown'),
                'failure_count': self.failure_counts.get(source_name, 0),
                'available': self.source_status.get(source_name) == 'active'
            }
        return status_info

    async def close(self):
        """关闭爬虫管理器"""
        logger.info("正在关闭爬虫管理器...")

        # 关闭所有爬虫
        for crawler in self.crawlers.values():
            try:
                await crawler.close()
            except Exception as e:
                logger.error(f"关闭爬虫时出错: {e}")

        # 关闭浏览器管理器
        try:
            await self.browser_manager.close()
        except Exception as e:
            logger.error(f"关闭浏览器管理器时出错: {e}")

        logger.info("爬虫管理器已关闭")


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Kronos 爬虫系统')
    parser.add_argument('--symbol', '-s', required=True, help='股票代码')
    parser.add_argument('--action', '-a', choices=['realtime', 'kline', 'minute', 'info'],
                        default='realtime', help='操作类型')
    parser.add_argument('--source', choices=['eastmoney', 'tonghuashun', 'xueqiu'],
                        help='指定数据源')
    parser.add_argument('--period', '-p', default='1d', help='K线周期')
    parser.add_argument('--start-date', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--config', '-c', help='配置文件路径')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')

    args = parser.parse_args()

    # 设置日志级别
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 创建爬虫管理器
    crawler_manager = CrawlerManager(args.config)

    try:
        # 执行操作
        if args.action == 'realtime':
            data = await crawler_manager.get_realtime_data(args.symbol, args.source)
        elif args.action == 'kline':
            data = await crawler_manager.get_kline_data(
                args.symbol, args.period, args.start_date, args.end_date, args.source
            )
        elif args.action == 'minute':
            data = await crawler_manager.get_minute_data(args.symbol, args.source)
        elif args.action == 'info':
            data = await crawler_manager.get_stock_info(args.symbol, args.source)

        # 输出结果
        if data:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print("未获取到数据")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("用户中断操作")
    except Exception as e:
        logger.error(f"执行失败: {e}")
        sys.exit(1)
    finally:
        await crawler_manager.close()


if __name__ == '__main__':
    asyncio.run(main())
