#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雪球数据爬虫模块
用于从雪球网站获取实时股票数据
"""

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from scripts.browser_manager import BrowserManager
from scripts.anti_crawler_helper import RequestOptimizer, classify_playwright_error


class XueQiuCrawler:
    """雪球数据爬虫（使用Playwright）"""

    def __init__(self, config_path: str = None):
        """初始化雪球爬虫"""
        # 加载配置
        if config_path is None:
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'crawler_config.json')

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 加载爬虫通用设置
        crawler_settings = config.get('crawler_settings', {})
        self.timeout = crawler_settings.get('timeout', 45) * 1000  # 增加到45秒
        self.max_retries = crawler_settings.get('max_retries', 3)
        self.retry_delay = crawler_settings.get('retry_delay', 3)  # 增加到3秒

        # 初始化请求优化器
        self.request_optimizer = RequestOptimizer(
            requests_per_minute=5,  # 雪球最严格，降低到5次/分钟
            max_retries=self.max_retries,
            base_delay=self.retry_delay,
            enable_adaptive=True
        )

        # 加载雪球特定配置
        self.config = config.get('data_sources', {}).get('xueqiu', {})
        self.endpoints = self.config.get('endpoints', {})
        self.headers = self.config.get('headers', {})

        # 浏览器相关
        self.browser = None
        self.page = None
        self.last_request_time = 0
        self.rate_limit_delay = 2.0  # 增加到2秒

        # 会话管理
        self.session = None
        self.cookies = {}
        self.token = None

        print(f"✅ 雪球爬虫初始化完成")
        print(f"📊 配置的端点数量: {len(self.endpoints)}")
        print(f"🔧 请求头配置: {len(self.headers)} 个")
        print(f"⏱️ 速率限制: {self.rate_limit_delay}秒")
        print(f"🕐 超时设置: {self.timeout // 1000}秒")
        print(f"🔄 最大重试次数: {self.max_retries}")
        print(f"⏳ 重试延迟: {self.retry_delay}秒")

        # 设置日志
        self.logger = logging.getLogger(__name__)

        self.base_url = self.config.get('base_url', 'https://stock.xueqiu.com')
        self.browser_manager = None

        # 速率限制
        rate_limit = self.config.get('rate_limit', 1.5)
        if isinstance(rate_limit, dict):
            self.rate_limit = rate_limit.get('min_interval', 1.5)
        else:
            self.rate_limit = rate_limit

    async def check_availability(self) -> bool:
        """检查数据源可用性"""
        try:
            # 简单的连通性测试
            test_url = "https://stock.xueqiu.com/v5/stock/chart/kline.json"
            params = {
                'symbol': 'SZ000001',
                'begin': int(time.time() * 1000) - 86400000,  # 1天前
                'period': 'day',
                'type': 'before',
                'count': '1',
                'indicator': 'kline'
            }

            if not self.page:
                await self._init_token()

            # 构建完整URL
            query_string = urlencode(params)
            full_url = f"{test_url}?{query_string}"

            response = await self.page.goto(
                full_url,
                wait_until='networkidle',
                timeout=10000
            )

            return response.status == 200
        except Exception as e:
            self.logger.error(f"雪球数据源可用性检查失败: {e}")
            return False

    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger('XueQiuCrawler')
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    async def _init_browser(self) -> None:
        """初始化浏览器"""
        if not self.browser_manager:
            self.browser_manager = BrowserManager()
            await self.browser_manager.start()

        if not self.page:
            self.context = await self.browser_manager.create_context()
            self.page = await self.context.new_page()

            # 设置额外的请求头
            headers = self.config.get('headers', {})
            default_headers = {
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': 'https://xueqiu.com/',
            }
            default_headers.update(headers)
            await self.page.set_extra_http_headers(default_headers)

    async def _init_token(self) -> None:
        """初始化token和cookies"""
        try:
            await self._init_browser()

            # 访问雪球首页获取token和cookies
            await self.page.goto('https://xueqiu.com/', wait_until='networkidle')

            # 等待页面加载完成
            await asyncio.sleep(2)

            # 获取cookies
            self.cookies = await self.page.context.cookies()

            # 从cookies中提取token
            for cookie in self.cookies:
                if cookie['name'] == 'xq_a_token':
                    self.token = cookie['value']
                    break

            if self.token:
                # 设置token到请求头
                await self.page.set_extra_http_headers({
                    'X-Xq-A-Token': self.token
                })
                self.logger.info(f"获取雪球token成功: {self.token[:20]}...")
            else:
                self.logger.warning("未能获取雪球token")

        except Exception as e:
            self.logger.error(f"初始化雪球token失败: {e}")

    async def _rate_limit(self) -> None:
        """速率限制"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.rate_limit:
            sleep_time = self.rate_limit - time_since_last_request
            await asyncio.sleep(sleep_time)
        self.last_request_time = time.time()

    def _convert_symbol(self, symbol: str) -> str:
        """转换股票代码为雪球格式"""
        if not symbol or not isinstance(symbol, str):
            self.logger.error(f"无效的股票代码: {symbol}")
            return "SZ000001"  # 返回默认代码

        symbol = str(symbol).upper().strip()

        # 如果为空或无效，返回默认代码
        if not symbol or symbol in ['0', '.', 'NONE', 'NULL']:
            self.logger.warning(f"股票代码为空或无效: {symbol}，使用默认代码")
            return "SZ000001"

        # 如果已经是标准格式 (000001.SZ)
        if '.' in symbol:
            parts = symbol.split('.')
            if len(parts) == 2:
                code, exchange = parts
                if exchange == 'SZ':
                    return f"SZ{code}"
                elif exchange == 'SH':
                    return f"SH{code}"

        # 如果只有数字代码
        if symbol.isdigit():
            code = symbol.zfill(6)
            if code.startswith(('000', '001', '002', '003', '300')):
                return f"SZ{code}"  # 深交所
            elif code.startswith(('600', '601', '603', '605', '688')):
                return f"SH{code}"  # 上交所
            else:
                return f"SZ{code}"  # 默认深交所

        # 如果已经是雪球格式，直接返回
        if symbol.startswith(('SZ', 'SH')):
            return symbol

        self.logger.warning(f"无法识别的股票代码格式: {symbol}，使用默认代码")
        return "SZ000001"

    async def _make_request(self, url: str, params: Dict[str, Any] = None,
                            retries: int = None) -> Optional[Dict[str, Any]]:
        """发送HTTP请求，使用智能重试和频率控制"""
        if not self.page:
            await self._init_token()

        # 使用请求优化器执行请求
        async def _do_request():
            # 构建完整URL
            if params:
                query_string = urlencode(params)
                full_url = f"{url}?{query_string}"
            else:
                full_url = url

            self.logger.info(f"🌐 请求URL: {full_url}")

            # 添加随机延迟，模拟人类行为
            await asyncio.sleep(random.uniform(1.0, 2.0))  # 雪球需要更长延迟

            # 使用Playwright发送请求
            response = await self.page.goto(full_url, wait_until='networkidle', timeout=self.timeout)

            if response.status != 200:
                raise Exception(f"HTTP {response.status}")

            # 尝试解析JSON
            try:
                # 如果页面包含JSON数据，提取它
                json_data = await self.page.evaluate('''() => {
                    try {
                        const pre = document.querySelector("pre");
                        if (pre) {
                            return JSON.parse(pre.textContent);
                        }
                        return window.jsonData || null;
                    } catch (e) {
                        return null;
                    }
                }''')

                if json_data:
                    return json_data

                # 如果没有找到JSON，尝试从响应中解析
                text_content = await response.text()
                if text_content.strip().startswith('{') or text_content.strip().startswith('['):
                    return json.loads(text_content)

                # 返回原始内容
                content = await self.page.content()
                return {'content': content}

            except json.JSONDecodeError as e:
                raise Exception(f"无法解析JSON响应: {e}")

        try:
            # 使用RequestOptimizer执行请求（带智能重试和频率控制）
            result = await self.request_optimizer.execute_request(
                _do_request,
                error_classifier=classify_playwright_error
            )
            self.logger.info(f"✅ 请求成功")
            return result

        except Exception as e:
            # 如果是401错误，尝试重新获取token
            if '401' in str(e):
                self.logger.warning(f"🔑 检测到401错误，尝试重新获取token")
                await self._init_token()

            self.logger.error(f"❌ 请求最终失败: {e}")
            return None

    async def get_realtime_data(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """获取实时股票数据"""
        if not symbols:
            return []

        results = []

        for symbol in symbols:
            try:
                # 转换股票代码
                xq_symbol = self._convert_symbol(symbol)

                # 构建请求URL
                url = f"{self.base_url}/v5/stock/quote.json"
                params = {
                    'symbol': xq_symbol,
                    'extend': 'detail'
                }

                # 发送请求
                self.logger.info(f"发送请求到: {url}, 参数: {params}")
                response_data = await self._make_request(url, params)
                self.logger.info(f"收到响应数据: {response_data}")

                if response_data and isinstance(response_data, dict) and 'data' in response_data:
                    data = response_data.get('data')
                    if data and isinstance(data, dict) and 'quote' in data:
                        quote_data = data['quote']

                        # 转换为标准格式
                        result = {
                            'symbol': symbol,
                            'name': quote_data.get('name', ''),
                            'current_price': quote_data.get('current', 0),
                            'change': quote_data.get('chg', 0),
                            'change_percent': quote_data.get('percent', 0),
                            'volume': quote_data.get('volume', 0),
                            'turnover': quote_data.get('amount', 0),
                            'high': quote_data.get('high', 0),
                            'low': quote_data.get('low', 0),
                            'open': quote_data.get('open', 0),
                            'prev_close': quote_data.get('last_close', 0),
                            'timestamp': int(time.time()),
                            'source': 'xueqiu'
                        }

                        results.append(result)
                    else:
                        self.logger.warning(f"获取 {symbol} 实时数据失败: 数据格式错误")
                else:
                    self.logger.warning(f"获取 {symbol} 实时数据失败: 响应为空或格式错误")

            except Exception as e:
                self.logger.error(f"处理 {symbol} 时出错: {e}")
                continue

        return results

    async def get_kline_data(self, symbol: str, period: str = '1d',
                             start_date: str = None, end_date: str = None) -> Optional[List[Dict[str, Any]]]:
        """获取K线数据"""
        xq_symbol = self._convert_symbol(symbol)

        # 雪球的时间周期映射
        period_map = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '30m': '30m',
            '1h': '60m',
            '1d': 'day',
            '1w': 'week',
            '1M': 'month'
        }

        xq_period = period_map.get(period, 'day')

        # 默认获取100条数据
        count = 100

        url = f'{self.base_url}/stock/history/kline.json'

        params = {
            'symbol': xq_symbol,
            'begin': int(time.time() * 1000) - count * 300000,  # 5分钟 * count
            'period': xq_period,
            'type': 'before',
            'count': count,
            'indicator': 'kline,pe,pb,ps,pcf,market_capital,agt,ggt,balance'
        }

        self.logger.info(f"获取K线数据: {symbol} -> {xq_symbol}, 周期: {period}")

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            klines = data.get('data', {}).get('item', [])

            result = []
            for kline in klines:
                if len(kline) >= 6:
                    result.append({
                        'timestamp': kline[0],
                        'open': kline[2],
                        'high': kline[3],
                        'low': kline[4],
                        'close': kline[5],
                        'volume': kline[1],
                        'symbol': symbol,
                        'period': period
                    })

            return result
        else:
            self.logger.error(f"获取K线数据失败: {symbol}")
            return None

    async def get_minute_data(self, symbol: str, date: str = None) -> Optional[Dict[str, Any]]:
        """获取分时数据"""
        xq_symbol = self._convert_symbol(symbol)

        url = f'{self.base_url}/stock/chart/minute.json'

        params = {
            'symbol': xq_symbol,
            'period': '1d'
        }

        self.logger.info(f"获取分时数据: {symbol} -> {xq_symbol}")

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {})
        else:
            self.logger.error(f"获取分时数据失败: {symbol}")
            return None

    async def get_stock_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取股票基本信息"""
        xq_symbol = self._convert_symbol(symbol)

        url = f'{self.base_url}/stock/quote.json'

        params = {
            'symbol': xq_symbol,
            'extend': 'detail'
        }

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {})
        else:
            return None

    async def search_stock(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索股票"""
        url = f'{self.base_url}/search/query.json'

        params = {
            'query': keyword,
            'count': 10,
            'type': 11  # 股票类型
        }

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {}).get('stocks', [])
        else:
            return []

    async def get_market_overview(self) -> Optional[Dict[str, Any]]:
        """获取市场概览"""
        url = f'{self.base_url}/stock/screener/quote/list.json'

        params = {
            'page': 1,
            'size': 50,
            'order': 'desc',
            'orderby': 'percent',
            'order_by': 'percent',
            'market': 'CN',
            'type': 'sh_sz'
        }

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {})
        else:
            return None

    async def get_hot_stocks(self, count: int = 50) -> List[Dict[str, Any]]:
        """获取热门股票"""
        url = f'{self.base_url}/stock/hot_stock/list.json'

        params = {
            'size': count,
            'type': 12
        }

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {}).get('items', [])
        else:
            return []

    async def get_sector_data(self, sector_code: str) -> Optional[Dict[str, Any]]:
        """获取板块数据"""
        url = f'{self.base_url}/stock/screener/quote/list.json'

        params = {
            'page': 1,
            'size': 100,
            'order': 'desc',
            'orderby': 'percent',
            'order_by': 'percent',
            'market': 'CN',
            'type': 'sh_sz',
            'ind_code': sector_code
        }

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {})
        else:
            return None

    async def get_financial_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取财务数据"""
        xq_symbol = self._convert_symbol(symbol)

        url = f'{self.base_url}/stock/finance/indicator.json'

        params = {
            'symbol': xq_symbol,
            'type': 'all',
            'is_detail': 'true',
            'count': 5
        }

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {})
        else:
            return None

    async def get_news(self, symbol: str = None, count: int = 20) -> List[Dict[str, Any]]:
        """获取新闻资讯"""
        if symbol:
            xq_symbol = self._convert_symbol(symbol)
            url = f'{self.base_url}/stock/timeline/list.json'
            params = {
                'symbol': xq_symbol,
                'count': count
            }
        else:
            url = 'https://xueqiu.com/statuses/hot/listV2.json'
            params = {
                'since_id': -1,
                'max_id': -1,
                'size': count
            }

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {}).get('items', [])
        else:
            return []

    async def get_dividend_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取分红数据"""
        xq_symbol = self._convert_symbol(symbol)

        url = f'{self.base_url}/stock/f10/bonus.json'

        params = {
            'symbol': xq_symbol,
            'size': 20
        }

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {})
        else:
            return None

    async def get_holder_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取股东数据"""
        xq_symbol = self._convert_symbol(symbol)

        url = f'{self.base_url}/stock/f10/skholders.json'

        params = {
            'symbol': xq_symbol,
            'count': 10
        }

        data = await self._make_request(url, params)
        if data and data.get('error_code') == 0:
            return data.get('data', {})
        else:
            return None

    async def is_available(self) -> bool:
        """检查数据源是否可用"""
        try:
            # 尝试获取上证指数数据来测试连接
            data = await self.get_realtime_data(['000001.SH'])
            return data is not None and len(data) > 0
        except Exception as e:
            self.logger.error(f"雪球数据源不可用: {e}")
            return False

    async def check_data_source_availability(self) -> bool:
        """检查数据源可用性"""
        try:
            url = f'{self.base_url}/stock/screener/screen.json'
            params = {
                'category': 'CN',
                'size': 1
            }

            data = await self._make_request(url, params)
            return data is not None and data.get('error_code') == 0

        except Exception as e:
            self.logger.error(f"数据源检查失败: {e}")
            return False

    async def get_trading_status(self) -> Dict[str, Any]:
        """获取交易状态"""
        try:
            # 获取市场状态
            url = f'{self.base_url}/stock/screener/screen.json'
            params = {
                'category': 'CN',
                'size': 1
            }

            data = await self._make_request(url, params)

            if data and data.get('error_code') == 0:
                from datetime import datetime
                current_time = datetime.now()

                # 简单的交易时间判断
                if current_time.weekday() >= 5:  # 周末
                    status = 'closed'
                elif current_time.hour < 9 or current_time.hour >= 15:
                    status = 'closed'
                elif current_time.hour == 11 and current_time.minute >= 30:
                    status = 'break'
                elif current_time.hour == 12:
                    status = 'break'
                elif current_time.hour == 13 and current_time.minute < 0:
                    status = 'break'
                else:
                    status = 'trading'

                return {
                    'status': status,
                    'timestamp': int(time.time()),
                    'source': 'xueqiu'
                }
            else:
                return {
                    'status': 'unknown',
                    'timestamp': int(time.time()),
                    'source': 'xueqiu'
                }

        except Exception as e:
            self.logger.error(f"获取交易状态失败: {e}")
            return {
                'status': 'error',
                'timestamp': int(time.time()),
                'source': 'xueqiu'
            }

    async def batch_get_realtime_data(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取实时数据"""
        results = {}

        # 雪球支持批量查询，但这里使用逐个查询以确保稳定性
        data_list = await self.get_realtime_data(symbols)

        for data in data_list:
            if data and 'symbol' in data:
                results[data['symbol']] = data

        return results

    async def close(self):
        """关闭连接和清理资源"""
        try:
            if self.page:
                await self.page.close()
                self.page = None

            if hasattr(self, 'context') and self.context:
                await self.context.close()
                self.context = None

            if self.browser_manager:
                await self.browser_manager.cleanup()
                self.browser_manager = None

            self.logger.info("雪球爬虫连接已关闭")

        except Exception as e:
            self.logger.error(f"关闭连接时出错: {e}")
