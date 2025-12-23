#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步数据采集模块
支持并发采集多支股票的基础数据和新闻情感数据
"""

import asyncio
import aiohttp
import pandas as pd
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from pathlib import Path
import sys
import logging

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from analysis.fundamental_data_collector import FundamentalDataCollector
from analysis.news_sentiment_collector import NewsSentimentCollector
from utils.retry_utils import validate_data_quality

logger = logging.getLogger(__name__)


class AsyncDataCollector:
    """异步数据采集器 - 支持并发采集多支股票的基础数据和新闻情感数据"""

    def __init__(self, max_concurrent: int = 5, timeout_per_stock: int = 30):
        """
        初始化异步数据采集器

        Args:
            max_concurrent: 最大并发任务数
            timeout_per_stock: 每支股票的超时时间（秒）
        """
        self.max_concurrent = max_concurrent
        self.timeout_per_stock = timeout_per_stock
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """上下文管理器 - 进入"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器 - 退出"""
        if self.session:
            await self.session.close()

    async def collect_batch_fundamental_data(
        self, stock_codes: List[str], show_progress: bool = True
    ) -> Tuple[Dict[str, Dict], List[str]]:
        """
        并发采集多支股票的基础数据

        Args:
            stock_codes: 股票代码列表
            show_progress: 是否显示进度

        Returns:
            (成功数据字典, 失败的股票代码列表)
        """
        tasks = []
        for stock_code in stock_codes:
            task = self._collect_fundamental_data_with_timeout(stock_code)
            tasks.append(task)

        if show_progress:
            print(f"🔄 开始并发采集 {len(stock_codes)} 支股票的基础数据...")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_data = {}
        failed_stocks = []

        for stock_code, result in zip(stock_codes, results):
            if isinstance(result, Exception):
                logger.error(f"采集 {stock_code} 基础数据失败: {str(result)}")
                failed_stocks.append(stock_code)
                if show_progress:
                    print(f"   ❌ {stock_code}: 采集失败")
            elif result is None:
                failed_stocks.append(stock_code)
                if show_progress:
                    print(f"   ⚠️  {stock_code}: 采集为空")
            else:
                success_data[stock_code] = result
                if show_progress:
                    print(f"   ✅ {stock_code}: 采集成功")

        if show_progress:
            print(
                f"✅ 基础数据采集完成: {len(success_data)}/{len(stock_codes)} 成功"
            )

        return success_data, failed_stocks

    async def collect_batch_news_sentiment(
        self, stock_codes: List[str], show_progress: bool = True
    ) -> Tuple[Dict[str, Dict], List[str]]:
        """
        并发采集多支股票的新闻情感数据

        Args:
            stock_codes: 股票代码列表
            show_progress: 是否显示进度

        Returns:
            (成功数据字典, 失败的股票代码列表)
        """
        tasks = []
        for stock_code in stock_codes:
            task = self._collect_news_sentiment_with_timeout(stock_code)
            tasks.append(task)

        if show_progress:
            print(f"🔄 开始并发采集 {len(stock_codes)} 支股票的新闻情感数据...")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_data = {}
        failed_stocks = []

        for stock_code, result in zip(stock_codes, results):
            if isinstance(result, Exception):
                logger.error(f"采集 {stock_code} 新闻情感数据失败: {str(result)}")
                failed_stocks.append(stock_code)
                if show_progress:
                    print(f"   ❌ {stock_code}: 采集失败")
            elif result is None:
                failed_stocks.append(stock_code)
                if show_progress:
                    print(f"   ⚠️  {stock_code}: 采集为空")
            else:
                success_data[stock_code] = result
                if show_progress:
                    print(f"   ✅ {stock_code}: 采集成功")

        if show_progress:
            print(
                f"✅ 新闻情感数据采集完成: {len(success_data)}/{len(stock_codes)} 成功"
            )

        return success_data, failed_stocks

    async def collect_batch_comprehensive(
        self, stock_codes: List[str], show_progress: bool = True
    ) -> Tuple[Dict[str, Dict], List[str]]:
        """
        并发采集多支股票的综合数据（基础 + 新闻情感）

        Args:
            stock_codes: 股票代码列表
            show_progress: 是否显示进度

        Returns:
            (成功数据字典，失败的股票代码列表)
        """
        tasks = []
        for stock_code in stock_codes:
            task = self._collect_comprehensive_with_timeout(stock_code)
            tasks.append(task)

        if show_progress:
            print(f"🔄 开始并发采集 {len(stock_codes)} 支股票的综合数据...")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_data = {}
        failed_stocks = []

        for stock_code, result in zip(stock_codes, results):
            if isinstance(result, Exception):
                logger.error(f"采集 {stock_code} 综合数据失败: {str(result)}")
                failed_stocks.append(stock_code)
                if show_progress:
                    print(f"   ❌ {stock_code}: 采集失败")
            elif result is None:
                failed_stocks.append(stock_code)
                if show_progress:
                    print(f"   ⚠️  {stock_code}: 采集为空")
            else:
                success_data[stock_code] = result
                if show_progress:
                    print(f"   ✅ {stock_code}: 采集成功")

        if show_progress:
            print(
                f"✅ 综合数据采集完成: {len(success_data)}/{len(stock_codes)} 成功"
            )

        return success_data, failed_stocks

    async def _collect_fundamental_data_with_timeout(
        self, stock_code: str
    ) -> Optional[Dict]:
        """采集单支股票基础数据（带超时控制和信号量限制）"""
        async with self.semaphore:
            try:
                # 在同步函数外使用同步采集器
                loop = asyncio.get_event_loop()
                collector = FundamentalDataCollector(stock_code)

                # 在线程池中运行同步操作
                data = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, self._get_fundamental_data_sync, collector
                    ),
                    timeout=self.timeout_per_stock,
                )

                return data
            except asyncio.TimeoutError:
                logger.warning(f"{stock_code} 基础数据采集超时")
                return None
            except Exception as e:
                logger.error(f"{stock_code} 基础数据采集异常: {str(e)}")
                return None

    async def _collect_news_sentiment_with_timeout(
        self, stock_code: str
    ) -> Optional[Dict]:
        """采集单支股票新闻情感数据（带超时控制和信号量限制）"""
        async with self.semaphore:
            try:
                loop = asyncio.get_event_loop()
                collector = NewsSentimentCollector(stock_code)

                data = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, self._get_news_sentiment_sync, collector
                    ),
                    timeout=self.timeout_per_stock,
                )

                return data
            except asyncio.TimeoutError:
                logger.warning(f"{stock_code} 新闻情感数据采集超时")
                return None
            except Exception as e:
                logger.error(f"{stock_code} 新闻情感数据采集异常: {str(e)}")
                return None

    async def _collect_comprehensive_with_timeout(
        self, stock_code: str
    ) -> Optional[Dict]:
        """采集单支股票综合数据（基础 + 新闻情感）"""
        async with self.semaphore:
            try:
                loop = asyncio.get_event_loop()

                # 并行采集基础数据和新闻情感数据
                fundamental_task = asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._get_fundamental_data_sync,
                        FundamentalDataCollector(stock_code),
                    ),
                    timeout=self.timeout_per_stock,
                )

                sentiment_task = asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._get_news_sentiment_sync,
                        NewsSentimentCollector(stock_code),
                    ),
                    timeout=self.timeout_per_stock,
                )

                # 等待两个并行任务完成
                fundamental_data, sentiment_data = await asyncio.gather(
                    fundamental_task, sentiment_task, return_exceptions=True
                )

                # 检查异常
                if isinstance(fundamental_data, Exception):
                    fundamental_data = None
                if isinstance(sentiment_data, Exception):
                    sentiment_data = None

                # 合并数据
                if fundamental_data is None and sentiment_data is None:
                    return None

                return {
                    "stock_code": stock_code,
                    "fundamental_data": fundamental_data or {},
                    "sentiment_data": sentiment_data or {},
                    "collected_time": datetime.now().isoformat(),
                }

            except asyncio.TimeoutError:
                logger.warning(f"{stock_code} 综合数据采集超时")
                return None
            except Exception as e:
                logger.error(f"{stock_code} 综合数据采集异常: {str(e)}")
                return None

    @staticmethod
    def _get_fundamental_data_sync(collector: FundamentalDataCollector) -> Dict:
        """同步获取基础数据"""
        try:
            data = {
                "financial_indicators": collector.get_financial_indicators() or {},
                "profit_data": collector.get_profit_data() or {},
                "debt_data": collector.get_debt_data() or {},
                "cashflow_data": collector.get_cashflow_data() or {},
                "growth_data": collector.get_growth_data() or {},
                "valuation_data": collector.get_valuation_data() or {},
            }

            # 验证数据质量
            required_fields = list(data.keys())
            if validate_data_quality(
                data, required_fields=required_fields, min_rows=0, data_type="基础数据"
            ):
                return data
            return None
        except Exception as e:
            logger.error(f"获取基础数据失败: {str(e)}")
            return None

    @staticmethod
    def _get_news_sentiment_sync(collector: NewsSentimentCollector) -> Dict:
        """同步获取新闻情感数据"""
        try:
            data = {
                "announcements": collector.get_latest_announcements(limit=5) or [],
                "news": collector.get_latest_news(limit=5) or [],
                "research_reports": collector.get_research_reports(limit=3) or [],
                "comprehensive_news": collector.get_comprehensive_news(limit=20)
                or {},
            }

            # 验证数据质量
            if validate_data_quality(
                data, required_fields=["comprehensive_news"], min_rows=0, data_type="新闻情感数据"
            ):
                return data
            return None
        except Exception as e:
            logger.error(f"获取新闻情感数据失败: {str(e)}")
            return None


async def batch_collect_data(
    stock_codes: List[str],
    data_type: str = "comprehensive",
    max_concurrent: int = 5,
    timeout_per_stock: int = 30,
) -> Tuple[Dict[str, Dict], List[str]]:
    """
    便利函数：并发采集多支股票的数据

    Args:
        stock_codes: 股票代码列表
        data_type: 数据类型 ('fundamental', 'sentiment', 'comprehensive')
        max_concurrent: 最大并发数
        timeout_per_stock: 单支股票超时时间

    Returns:
        (成功数据字典, 失败的股票代码列表)
    """
    async with AsyncDataCollector(
        max_concurrent=max_concurrent, timeout_per_stock=timeout_per_stock
    ) as collector:
        if data_type == "fundamental":
            return await collector.collect_batch_fundamental_data(stock_codes)
        elif data_type == "sentiment":
            return await collector.collect_batch_news_sentiment(stock_codes)
        else:  # comprehensive
            return await collector.collect_batch_comprehensive(stock_codes)


# 兼容同步接口的包装函数
def collect_batch_data_sync(
    stock_codes: List[str],
    data_type: str = "comprehensive",
    max_concurrent: int = 5,
    timeout_per_stock: int = 30,
) -> Tuple[Dict[str, Dict], List[str]]:
    """
    同步包装函数：并发采集多支股票的数据

    Args:
        stock_codes: 股票代码列表
        data_type: 数据类型 ('fundamental', 'sentiment', 'comprehensive')
        max_concurrent: 最大并发数
        timeout_per_stock: 单支股票超时时间

    Returns:
        (成功数据字典, 失败的股票代码列表)
    """
    # 创建事件循环
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(
            batch_collect_data(
                stock_codes, data_type, max_concurrent, timeout_per_stock
            )
        )
    finally:
        # 不关闭loop，让其保持供后续使用
        pass


if __name__ == "__main__":
    # 测试异步采集
    import time

    test_stocks = ["688343", "000001", "600519"]

    print("\n" + "=" * 60)
    print("异步数据采集器 - 测试")
    print("=" * 60)

    # 异步采集
    start = time.time()

    async def main():
        success_data, failed = await batch_collect_data(test_stocks, data_type="comprehensive")
        print(f"\n✅ 采集成功: {len(success_data)}/{len(test_stocks)}")
        print(f"⏱️  耗时: {time.time() - start:.2f}s")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  采集被中断")
