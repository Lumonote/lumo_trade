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
from scripts.anti_crawler_helper import RequestOptimizer, classify_playwright_error
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
        self.timeout = self.crawler_settings.get('timeout', 45) * 1000  # 增加到45秒
        self.max_retries = self.crawler_settings.get('max_retries', 3)
        self.retry_delay = self.crawler_settings.get('retry_delay', 3)  # 增加到3秒

        # 初始化请求优化器
        self.request_optimizer = RequestOptimizer(
            requests_per_minute=6,
            max_retries=self.max_retries,
            base_delay=self.retry_delay,
            enable_adaptive=True
        )

        # 速率限制（保留用于兼容性）
        self.rate_limit = self.config.get('rate_limit', 1.5)  # 增加到1.5秒
        self.min_interval = self.rate_limit
        self.last_request_time = 0

        # 浏览器管理
        self.browser_manager = None
        self.context = None
        self.page = None

        # 日志配置
        self.logger = logging.getLogger(__name__)

        print(f"✅ 同花顺爬虫已加载")

    async def check_availability(self) -> bool:
        """检查数据源可用性"""
        try:
            if not self.browser_manager:
                await self._init_browser()
            
            # 使用页面监听模式检查可用性
            test_url = 'https://stockpage.10jqka.com.cn/000001/'
            print(f"🔍 同花顺可用性检查开始...")
            print(f"🌐 测试URL: {test_url}")
            
            # 设置网络监听
            api_responses = []
            
            async def handle_response(response):
                if '10jqka.com.cn' in response.url and response.status == 200:
                    try:
                        content_type = response.headers.get('content-type', '')
                        if 'json' in content_type or 'javascript' in content_type:
                            api_responses.append(response)
                    except:
                        pass
            
            self.page.on('response', handle_response)
            
            # 访问测试页面
            response = await self.page.goto(
                test_url,
                wait_until='domcontentloaded',
                timeout=15000
            )
            
            if response and response.status == 200:
                # 等待数据加载
                await asyncio.sleep(3)
                
                # 检查是否有API响应或页面数据
                if api_responses:
                    print(f"✅ 同花顺数据源可用 - 捕获到 {len(api_responses)} 个API响应")
                    self.page.remove_listener('response', handle_response)
                    return True
                
                # 检查页面是否正常加载
                try:
                    page_title = await self.page.title()
                    if page_title and '000001' in page_title:
                        print(f"✅ 同花顺数据源可用 - 页面正常加载")
                        self.page.remove_listener('response', handle_response)
                        return True
                except:
                    pass
            
            self.page.remove_listener('response', handle_response)
            print(f"❌ 同花顺数据源不可用")
            return False
            
        except Exception as e:
            print(f"❌ 同花顺可用性检查异常: {e}")
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
        """发送HTTP请求，使用智能重试和频率控制"""
        await self._init_browser()

        # 使用请求优化器执行请求
        async def _do_request():
            # 构建完整URL
            if params:
                query_string = urlencode(params)
                full_url = f"{url}?{query_string}"
            else:
                full_url = url

            print(f"🌐 请求URL: {full_url[:100]}...")

            # 添加随机延迟，模拟人类行为
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # 发送请求
            response = await self.page.goto(full_url, timeout=self.timeout, wait_until='networkidle')

            if not response:
                raise Exception("No response received")

            if response.status != 200:
                raise Exception(f"HTTP {response.status}")

            # 获取页面文本内容
            text_content = await self.page.evaluate('() => document.body.innerText')

            if not text_content:
                raise Exception("页面内容为空")

            # 处理JSONP响应
            if 'callback(' in text_content or '(' in text_content:
                # 匹配JSONP格式: function_name({...})
                jsonp_pattern = r'\w+\((.+)\)$'
                match = re.search(jsonp_pattern, text_content.strip())

                if match:
                    json_str = match.group(1)
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError as e:
                        raise Exception(f"JSONP解析失败: {e}")
                else:
                    # 尝试简单的括号匹配
                    start_idx = text_content.find('(')
                    end_idx = text_content.rfind(')')

                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        json_str = text_content[start_idx + 1:end_idx]
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError as e:
                            raise Exception(f"JSONP解析失败: {e}")

            # 尝试直接解析JSON
            try:
                return json.loads(text_content)
            except json.JSONDecodeError:
                raise Exception(f"JSON解析失败，内容: {text_content[:200]}")

        try:
            # 使用RequestOptimizer执行请求（带智能重试和频率控制）
            result = await self.request_optimizer.execute_request(
                _do_request,
                error_classifier=classify_playwright_error
            )
            print(f"✅ 请求成功")
            return result

        except Exception as e:
            print(f"❌ 请求最终失败: {e}")
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

        # 尝试通过股票页面获取数据 - 使用页面监听模式
        print(f"📈 获取K线数据: {symbol} -> {exchange}_{ths_symbol}, 周期: {period}")
        
        # 构造股票详情页URL
        stock_page_url = f'https://stockpage.10jqka.com.cn/{ths_symbol}/'
        print(f"🔄 尝试股票页面: {stock_page_url}")
        
        try:
            if not self.browser_manager:
                await self._init_browser()
            
            # 设置网络监听
            api_responses = []
            
            async def handle_response(response):
                # 监听可能的数据接口
                if any(domain in response.url for domain in ['10jqka.com.cn', 'hexun.com', 'ifeng.com']) and response.status == 200:
                    try:
                        content_type = response.headers.get('content-type', '')
                        if 'json' in content_type or 'javascript' in content_type:
                            api_responses.append(response)
                            print(f"✅ 捕获到数据响应: {response.url[:80]}...")
                    except:
                        pass
            
            self.page.on('response', handle_response)
            
            # 访问股票页面
            response = await self.page.goto(
                stock_page_url,
                wait_until='domcontentloaded',
                timeout=15000
            )
            
            if response and response.status == 200:
                print(f"📄 股票页面加载成功，等待数据加载...")
                # 等待页面数据加载
                await asyncio.sleep(5)
                
                # 尝试从页面中提取数据
                try:
                    # 执行JavaScript获取页面数据
                    page_data = await self.page.evaluate("""
                        () => {
                            // 尝试获取页面中的股票数据
                            const data = {};
                            
                            // 查找可能的数据变量
                            if (typeof window.stockData !== 'undefined') {
                                data.stockData = window.stockData;
                            }
                            if (typeof window.klineData !== 'undefined') {
                                data.klineData = window.klineData;
                            }
                            if (typeof window.priceData !== 'undefined') {
                                data.priceData = window.priceData;
                            }
                            
                            return data;
                        }
                    """)
                    
                    if page_data and any(page_data.values()):
                        print(f"✅ 从页面获取到数据")
                        return page_data
                        
                except Exception as js_error:
                    print(f"⚠️ JavaScript执行失败: {js_error}")
                
                # 检查API响应
                if api_responses:
                    print(f"✅ 捕获到 {len(api_responses)} 个API响应，尝试解析...")
                    for api_response in api_responses:
                        try:
                            text = await api_response.text()
                            if text and len(text) > 100:  # 有实际内容
                                return {'raw_data': text, 'url': api_response.url}
                        except:
                            continue
                            
            # 移除监听器
            self.page.remove_listener('response', handle_response)
            
        except Exception as e:
            print(f"❌ 页面访问异常: {e}")
        
        # 如果页面方式失败，尝试备用方案
        print(f"⚠️ 页面方式获取失败，尝试备用数据源...")
        
        # 尝试一些可能仍然可用的端点
        backup_urls = [
            f'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={exchange}.{ths_symbol}&klt={ths_period}&fqt=1&lmt=100',
            f'https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param={exchange}{ths_symbol},day,,,100,qfq',
            f'https://stock.xueqiu.com/v5/stock/chart/kline.json?symbol={exchange.upper()}{ths_symbol}&begin={int(time.time()*1000)}&period=day&type=before&count=-100'
        ]
        
        for backup_url in backup_urls:
            print(f"🔄 尝试备用URL: {backup_url[:60]}...")
            try:
                response = await self.page.goto(backup_url, timeout=10000)
                if response and response.status == 200:
                    content = await response.text()
                    if content and len(content) > 50:
                        print(f"✅ 备用数据源成功")
                        return {'raw_data': content, 'url': backup_url}
            except:
                continue

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
