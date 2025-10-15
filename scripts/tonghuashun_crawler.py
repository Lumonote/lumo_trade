#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同花顺数据爬虫模块
从同花顺网站爬取实时股票数据
"""

import asyncio
import time
import json
import random
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode, urljoin
from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
from scripts.browser_manager import BrowserManager
import pandas as pd
import re


class TongHuaShunCrawler:
    """同花顺数据爬虫"""

    def __init__(self, config_path: str = None):
        """初始化同花顺爬虫"""
        # 加载配置
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.config = config.get('data_sources', {}).get('tonghuashun', {})
                self.crawler_settings = config.get('crawler_settings', {})
        else:
            self.config = {}
            self.crawler_settings = {}

        # 基础配置
        self.base_url = self.config.get('base_url', 'https://d.10jqka.com.cn')
        self.endpoints = self.config.get('endpoints', {
            'realtime': '/v6/line/hs_{symbol}/01/last.js',
            'kline': '/v6/line/hs_{symbol}/01/today.js',
            'minute': '/v6/line/hs_{symbol}/01/today.js'
        })
        self.headers = self.config.get('headers', {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://stockpage.10jqka.com.cn/',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9'
        })

        # 网络配置
        self.timeout = self.crawler_settings.get('timeout', 30) * 1000  # 转换为毫秒
        self.max_retries = self.crawler_settings.get('max_retries', 3)
        self.retry_delay = self.crawler_settings.get('retry_delay', 2)

        # 速率限制
        self.rate_limit = self.config.get('rate_limit', 1.0)
        self.min_interval = self.rate_limit
        self.last_request_time = 0

        # 浏览器管理
        self.browser_manager = None
        self.context = None
        self.page = None

        # 日志配置
        self.logger = logging.getLogger(__name__)

        print(f"🚀 同花顺爬虫初始化完成")
        print(f"📡 基础URL: {self.base_url}")
        print(f"⏱️ 速率限制: {self.rate_limit}秒")
        print(f"⏰ 超时设置: {self.timeout / 1000}秒")
        print(f"🔄 重试次数: {self.max_retries}")
        print(f"🔧 端点配置: {self.endpoints}")

    async def check_availability(self) -> bool:
        """检查数据源可用性"""
        try:
            # 简单的连通性测试
            test_url = "https://d.10jqka.com.cn/v6/line/hs_000001/01/last.js"

            if not self.browser_manager:
                await self._init_browser()

            response = await self.page.goto(
                test_url,
                wait_until='networkidle',
                timeout=10000
            )

            return response.status == 200
        except Exception as e:
            self.logger.error(f"同花顺数据源可用性检查失败: {e}")
            return False

    async def _init_browser(self):
        """初始化浏览器"""
        try:
            self.browser_manager = BrowserManager()
            self.context = await self.browser_manager.create_context()
            self.page = await self.context.new_page()

            # 设置额外的请求头
            await self.page.set_extra_http_headers(self.headers)

            print("✅ 同花顺爬虫浏览器初始化成功")
        except Exception as e:
            print(f"❌ 同花顺爬虫浏览器初始化失败: {e}")

    async def _rate_limit_wait(self):
        """速率限制等待"""
        current_time = time.time()
        time_diff = current_time - self.last_request_time

        if time_diff < self.min_interval:
            wait_time = self.min_interval - time_diff
            await asyncio.sleep(wait_time)

        self.last_request_time = time.time()

    def _convert_symbol(self, symbol: str) -> str:
        """转换股票代码为同花顺格式"""
        symbol = symbol.upper().strip()

        # 如果已经是标准格式 (000001.SZ)
        if '.' in symbol:
            code, exchange = symbol.split('.')
            return code

        # 如果只有数字代码
        if symbol.isdigit():
            return symbol.zfill(6)

        return symbol

    def _get_exchange_code(self, symbol: str) -> str:
        """获取交易所代码"""
        symbol = symbol.upper().strip()

        if '.' in symbol:
            code, exchange = symbol.split('.')
            if exchange == 'SZ':
                return 'sz'
            elif exchange == 'SH':
                return 'sh'

        # 根据代码判断交易所
        if symbol.isdigit():
            code = symbol.zfill(6)
            if code.startswith(('000', '001', '002', '003', '300')):
                return 'sz'  # 深交所
            elif code.startswith(('600', '601', '603', '605', '688')):
                return 'sh'  # 上交所
            else:
                return 'sz'  # 默认深交所

        return 'sh'

    async def _make_request(self, url: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """发送HTTP请求，带重试机制"""
        await self._init_browser()
        await self._rate_limit_wait()

        for attempt in range(self.max_retries + 1):
            try:
                # 构建完整URL
                if params:
                    query_string = urlencode(params)
                    full_url = f"{url}?{query_string}"
                else:
                    full_url = url

                if attempt > 0:
                    print(f"🔄 重试请求 ({attempt}/{self.max_retries}): {full_url[:100]}...")
                else:
                    print(f"🌐 请求URL: {full_url[:100]}...")

                # 发送请求，使用配置的超时时间
                response = await self.page.goto(full_url, timeout=self.timeout, wait_until='networkidle')

                if response and response.status == 200:
                    # 获取页面文本内容
                    text_content = await self.page.evaluate('() => document.body.innerText')

                    if not text_content:
                        print("❌ 页面内容为空")
                        if attempt < self.max_retries:
                            await asyncio.sleep(self.retry_delay)
                            continue
                        return None

                    # 处理JSONP响应
                    if 'callback(' in text_content or '(' in text_content:
                        # 查找JSONP函数名和JSON部分
                        import re
                        # 匹配JSONP格式: function_name({...})
                        jsonp_pattern = r'\w+\((.+)\)$'
                        match = re.search(jsonp_pattern, text_content.strip())

                        if match:
                            json_str = match.group(1)
                            try:
                                return json.loads(json_str)
                            except json.JSONDecodeError as e:
                                print(f"❌ JSONP解析失败: {e}")
                                print(f"原始内容: {text_content[:200]}...")
                                if attempt == self.max_retries:
                                    return None
                                continue
                        else:
                            # 尝试简单的括号匹配
                            start_idx = text_content.find('(')
                            end_idx = text_content.rfind(')')

                            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                                json_str = text_content[start_idx + 1:end_idx]
                                try:
                                    return json.loads(json_str)
                                except json.JSONDecodeError as e:
                                    print(f"❌ JSONP解析失败: {e}")
                                    print(f"原始内容: {text_content[:200]}...")
                                    if attempt == self.max_retries:
                                        return None
                                    continue

                    # 尝试直接解析JSON
                    try:
                        return json.loads(text_content)
                    except json.JSONDecodeError:
                        print(f"❌ JSON解析失败")
                        print(f"响应内容: {text_content[:200]}...")
                        if attempt == self.max_retries:
                            return None
                        continue

                elif response and response.status in [429, 503]:  # 速率限制或服务不可用
                    print(f"⚠️ 遇到速率限制或服务不可用 (状态码: {response.status})，等待后重试")
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_delay * (2 ** attempt))  # 指数退避
                        continue
                    else:
                        print(f"❌ 请求失败，状态码: {response.status}")
                        return None
                else:
                    print(f"❌ 请求失败，状态码: {response.status if response else 'None'}")
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    return None

            except Exception as e:
                print(f"❌ 请求异常 (尝试 {attempt + 1}/{self.max_retries + 1}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                return None

        # 模拟人类行为
        await asyncio.sleep(random.uniform(0.1, 0.3))
        return None

    async def get_realtime_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取实时数据"""
        ths_symbol = self._convert_symbol(symbol)
        exchange = self._get_exchange_code(symbol)

        # 尝试多个可能的同花顺API端点
        urls_to_try = [
            f'{self.base_url}/v6/line/{exchange}_{ths_symbol}/01/last.js',
            f'{self.base_url}/v2/line/{exchange}_{ths_symbol}/last.js',
            f'http://d.10jqka.com.cn/v6/line/hs_{ths_symbol}/01/last.js'
        ]

        params = {
            '_': int(time.time() * 1000)
        }

        print(f"📊 获取实时数据: {symbol} -> {exchange}_{ths_symbol}")

        for url in urls_to_try:
            print(f"🔄 尝试URL: {url}")
            data = await self._make_request(url, params)
            if data:
                return data

        print(f"❌ 获取实时数据失败: {symbol}")
        return None

    async def get_kline_data(self, symbol: str, period: str = '1d',
                             start_date: str = None, end_date: str = None) -> Optional[Dict[str, Any]]:
        """获取K线数据"""
        ths_symbol = self._convert_symbol(symbol)
        exchange = self._get_exchange_code(symbol)

        # 周期映射 - 使用同花顺的周期代码
        period_map = {
            '1m': '01',  # 1分钟
            '5m': '05',  # 5分钟
            '15m': '15',  # 15分钟
            '30m': '30',  # 30分钟
            '1h': '60',  # 60分钟
            '1d': 'D',  # 日线
            '1w': 'W',  # 周线
            '1M': 'M'  # 月线
        }

        ths_period = period_map.get(period, 'D')

        # 尝试多个可能的API端点 - 更新为可能的新格式
        urls_to_try = [
            f'http://d.10jqka.com.cn/v6/line/{exchange}_{ths_symbol}/{ths_period}/last.js',
            f'http://d.10jqka.com.cn/v2/line/{exchange}_{ths_symbol}/{ths_period}.js',
            f'https://d.10jqka.com.cn/v6/line/{exchange}_{ths_symbol}/{ths_period}/last.js',
            f'https://d.10jqka.com.cn/v2/line/{exchange}_{ths_symbol}/{ths_period}.js',
            f'http://d.10jqka.com.cn/v6/line/hs_{ths_symbol}/{ths_period}/last.js',
            f'https://stockpage.10jqka.com.cn/realHead_v2.html#{exchange}{ths_symbol}'
        ]

        params = {
            '_': int(time.time() * 1000)
        }

        print(f"📈 获取K线数据: {symbol} -> {exchange}_{ths_symbol}, 周期: {period}")

        for url in urls_to_try:
            print(f"🔄 尝试K线URL: {url}")
            data = await self._make_request(url, params)
            if data:
                return data

        print(f"❌ 获取K线数据失败: {symbol}")
        return None

    async def get_minute_data(self, symbol: str, date: str = None) -> Optional[Dict[str, Any]]:
        """获取分时数据"""
        ths_symbol = self._convert_symbol(symbol)
        exchange = self._get_exchange_code(symbol)

        if not date:
            date = datetime.now().strftime('%Y%m%d')

        # 同花顺分时数据API
        url = f'{self.base_url}/v2/line/{exchange}_{ths_symbol}/time/{date}.js'

        params = {
            '_': int(time.time() * 1000)
        }

        print(f"📊 获取分时数据: {symbol} -> {exchange}_{ths_symbol}, 日期: {date}")

        data = await self._make_request(url, params)
        if data:
            return data
        else:
            print(f"❌ 获取分时数据失败: {symbol}")
            return None

    async def get_stock_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取股票基本信息"""
        ths_symbol = self._convert_symbol(symbol)
        exchange = self._get_exchange_code(symbol)

        # 同花顺股票信息API
        url = 'https://basic.10jqka.com.cn/basicapi/stock/info'

        params = {
            'code': f'{exchange}{ths_symbol}',
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data and data.get('status_code') == 0:
            return data.get('data', {})
        else:
            return None

    async def search_stock(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索股票"""
        url = 'https://searchapi.10jqka.com.cn/stocksearch/search'

        params = {
            'tid': 'stockpick',
            'qs': 'ta',
            'ts': '1',
            'w': keyword,
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data and data.get('status_code') == 0:
            return data.get('data', {}).get('stock', [])
        else:
            return []

    async def get_market_overview(self) -> Optional[Dict[str, Any]]:
        """获取市场概览"""
        url = 'https://d.10jqka.com.cn/v6/line/hs_a_board/01/last.js'

        params = {
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data:
            return data
        else:
            return None

    async def get_hot_stocks(self, count: int = 50) -> List[Dict[str, Any]]:
        """获取热门股票"""
        url = 'https://d.10jqka.com.cn/v6/line/hs_a_board/01/last.js'

        params = {
            'limit': count,
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data and 'data' in data:
            return data['data'][:count]
        else:
            return []

    async def get_sector_data(self, sector_code: str) -> Optional[Dict[str, Any]]:
        """获取板块数据"""
        url = f'https://d.10jqka.com.cn/v6/line/hs_{sector_code}/01/last.js'

        params = {
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data:
            return data
        else:
            return None

    async def get_financial_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取财务数据"""
        ths_symbol = self._convert_symbol(symbol)
        exchange = self._get_exchange_code(symbol)

        url = 'https://basic.10jqka.com.cn/basicapi/finance/stock/summary'

        params = {
            'code': f'{exchange}{ths_symbol}',
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data and data.get('status_code') == 0:
            return data.get('data', {})
        else:
            return None

    async def get_news(self, symbol: str = None, count: int = 20) -> List[Dict[str, Any]]:
        """获取新闻资讯"""
        if symbol:
            ths_symbol = self._convert_symbol(symbol)
            exchange = self._get_exchange_code(symbol)
            url = 'https://news.10jqka.com.cn/tapp/news/push/stock'
            params = {
                'stock_code': f'{exchange}{ths_symbol}',
                'page': '1',
                'page_size': str(count),
                '_': int(time.time() * 1000)
            }
        else:
            url = 'https://news.10jqka.com.cn/tapp/news/push/stock'
            params = {
                'page': '1',
                'page_size': str(count),
                '_': int(time.time() * 1000)
            }

        data = await self._make_request(url, params)
        if data and data.get('status_code') == 0:
            return data.get('data', {}).get('list', [])
        else:
            return []

    async def is_available(self) -> bool:
        """检查数据源是否可用"""
        try:
            # 尝试获取上证指数数据来测试连接
            data = await self.get_realtime_data('000001.SH')
            return data is not None
        except Exception as e:
            print(f"❌ 同花顺数据源不可用: {e}")
            return False

    async def get_trading_status(self) -> str:
        """获取交易状态"""
        now = datetime.now()
        current_time = now.time()

        # 交易时间判断
        morning_start = datetime.strptime('09:30', '%H:%M').time()
        morning_end = datetime.strptime('11:30', '%H:%M').time()
        afternoon_start = datetime.strptime('13:00', '%H:%M').time()
        afternoon_end = datetime.strptime('15:00', '%H:%M').time()

        # 周末不交易
        if now.weekday() >= 5:
            return 'closed'

        # 判断是否在交易时间内
        if (morning_start <= current_time <= morning_end or
                afternoon_start <= current_time <= afternoon_end):
            return 'trading'
        elif current_time < morning_start:
            return 'pre_market'
        elif morning_end < current_time < afternoon_start:
            return 'lunch_break'
        else:
            return 'after_market'

    async def batch_get_realtime_data(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取实时数据"""
        results = {}

        for symbol in symbols:
            try:
                data = await self.get_realtime_data(symbol)
                if data:
                    results[symbol] = data
                else:
                    results[symbol] = None

                # 避免请求过于频繁
                await asyncio.sleep(0.1)

            except Exception as e:
                print(f"❌ 获取 {symbol} 数据失败: {e}")
                results[symbol] = None

        return results

    async def get_index_data(self, index_code: str) -> Optional[Dict[str, Any]]:
        """获取指数数据"""
        # 指数代码映射
        index_map = {
            '000001.SH': 'sh_000001',  # 上证指数
            '399001.SZ': 'sz_399001',  # 深证成指
            '399006.SZ': 'sz_399006',  # 创业板指
            '000300.SH': 'sh_000300',  # 沪深300
            '000905.SH': 'sh_000905',  # 中证500
        }

        ths_code = index_map.get(index_code, index_code)

        url = f'https://d.10jqka.com.cn/v2/line/{ths_code}/last.js'

        params = {
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data:
            return data
        else:
            return None

    async def close(self):
        """清理资源"""
        try:
            if self.page:
                await self.page.close()
                print("✅ 同花顺爬虫页面已关闭")

            if self.context:
                await self.context.close()
                print("✅ 同花顺爬虫上下文已关闭")

            if self.browser_manager:
                await self.browser_manager.close()
                print("✅ 同花顺爬虫浏览器管理器已关闭")

        except Exception as e:
            print(f"❌ 同花顺爬虫资源清理失败: {e}")
