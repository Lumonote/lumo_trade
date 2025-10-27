#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东方财富爬虫模块
用于从东方财富网站爬取股票数据
"""

import json
import time
import random
import asyncio
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin
import logging
from playwright.async_api import Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
from scripts.browser_manager import BrowserManager
import pandas as pd


class EastMoneyCrawler:
    """东方财富数据爬虫"""

    def __init__(self, config_path: str = None):
        """初始化东方财富爬虫"""
        # 加载配置
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.config = config.get('data_sources', {}).get('eastmoney', {})
                self.crawler_settings = config.get('crawler_settings', {})
        else:
            self.config = {}
            self.crawler_settings = {}

        # 基础配置
        self.base_url = self.config.get('base_url', 'https://push2.eastmoney.com')
        self.endpoints = self.config.get('endpoints', {
            'realtime': '/api/qt/stock/get',
            'kline': '/api/qt/stock/kline/get',
            'minute': '/api/qt/stock/trends2/get'
        })
        self.headers = self.config.get('headers', {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://quote.eastmoney.com/',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        })

        # 网络配置
        self.timeout = self.crawler_settings.get('timeout', 30) * 1000  # 转换为毫秒
        self.max_retries = self.crawler_settings.get('max_retries', 3)
        self.retry_delay = self.crawler_settings.get('retry_delay', 2)

        # 速率限制
        self.rate_limit = self.config.get('rate_limit', 0.5)
        self.min_interval = self.rate_limit
        self.last_request_time = 0

        # 浏览器管理
        self.browser_manager = None
        self.context = None
        self.page = None

        # 日志配置
        self.logger = logging.getLogger(__name__)

        print(f"🚀 东方财富爬虫初始化完成")
        print(f"📡 基础URL: {self.base_url}")
        print(f"⏱️ 速率限制: {self.rate_limit}秒")
        print(f"⏰ 超时设置: {self.timeout / 1000}秒")
        print(f"🔄 重试次数: {self.max_retries}")
        print(f"🔧 端点配置: {self.endpoints}")

    async def check_availability(self) -> bool:
        """检查数据源可用性 - 使用浏览器页面监听模式"""
        try:
            print(f"🔍 东方财富可用性检查开始...")
            
            if not self.browser_manager:
                print(f"🚀 初始化浏览器...")
                await self._init_browser()

            # 使用股票详情页测试，监听内部API调用
            test_stock_page = "https://quote.eastmoney.com/sz000001.html"
            print(f"🌐 测试股票页面: {test_stock_page}")
            
            # 设置网络监听
            api_responses = []
            
            async def handle_response(response):
                if 'push2.eastmoney.com' in response.url and response.status == 200:
                    api_responses.append(response)
                    print(f"✅ 捕获到API响应: {response.url[:100]}...")
            
            self.page.on('response', handle_response)
            
            # 访问股票页面
            try:
                response = await self.page.goto(
                    test_stock_page,
                    wait_until='domcontentloaded',
                    timeout=15000
                )
                
                if not response or response.status != 200:
                    print(f"❌ 股票页面访问失败，状态码: {response.status if response else 'None'}")
                    return False
                
                print(f"📄 股票页面加载成功，等待API调用...")
                
                # 等待API调用
                await asyncio.sleep(3)
                
                if api_responses:
                    print(f"✅ 东方财富可用性检查通过，捕获到 {len(api_responses)} 个API响应")
                    return True
                else:
                    print(f"⚠️ 未捕获到API响应，但页面可访问")
                    return True  # 页面可访问就认为可用
                    
            except Exception as page_error:
                print(f"❌ 页面访问异常: {page_error}")
                return False
            finally:
                # 移除监听器
                self.page.remove_listener('response', handle_response)

        except Exception as e:
            print(f"❌ 东方财富可用性检查异常: {e}")
            self.logger.error(f"东方财富数据源可用性检查失败: {e}")
            return False

    async def _init_browser(self):
        """初始化浏览器"""
        if not self.browser_manager:
            self.browser_manager = BrowserManager()
            await self.browser_manager.start()
            self.context = await self.browser_manager.create_context()
            self.page = await self.context.new_page()

            # 设置额外的请求头
            await self.page.set_extra_http_headers(self.headers)

            print("🌐 浏览器初始化完成")

    async def _rate_limit_wait(self):
        """速率限制等待"""
        current_time = time.time()
        time_diff = current_time - self.last_request_time
        if time_diff < self.min_interval:
            sleep_time = self.min_interval - time_diff
            await asyncio.sleep(sleep_time)
        self.last_request_time = time.time()

    def _convert_symbol(self, symbol: str) -> str:
        """转换股票代码为东方财富格式"""
        symbol = symbol.upper().strip()

        # 如果已经是标准格式 (000001.SZ)
        if '.' in symbol:
            code, exchange = symbol.split('.')
            if exchange == 'SZ':
                return f"0.{code}"
            elif exchange == 'SH':
                return f"1.{code}"

        # 如果只有数字代码
        if symbol.isdigit():
            code = symbol.zfill(6)
            if code.startswith(('000', '001', '002', '003', '300')):
                return f"0.{code}"  # 深交所
            elif code.startswith(('600', '601', '603', '605', '688')):
                return f"1.{code}"  # 上交所
            else:
                return f"0.{code}"  # 默认深交所

        return symbol

    async def _make_request(self, url: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """发送HTTP请求，带重试机制"""
        await self._init_browser()
        await self._rate_limit_wait()

        for attempt in range(self.max_retries + 1):
            try:
                # 构建完整URL
                if params:
                    param_str = '&'.join([f"{k}={v}" for k, v in params.items()])
                    full_url = f"{url}?{param_str}"
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

                    # 处理JSONP响应
                    if text_content and ('jQuery' in text_content or 'callback' in text_content):
                        # 查找JSON部分
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
        em_symbol = self._convert_symbol(symbol)

        url = urljoin(self.base_url, self.endpoints.get('realtime', '/api/qt/stock/get'))

        params = {
            'secid': em_symbol,
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
            'fields': 'f43,f57,f58,f107,f137,f46,f44,f45,f260,f47,f48,f19,f39,f161,f49,f530,f135,f136,f17,f531,f40,f45,f46,f47,f48',
            'cb': f'jQuery{random.randint(100000, 999999)}_{int(time.time() * 1000)}',
            '_': int(time.time() * 1000)
        }

        print(f"📊 获取实时数据: {symbol} -> {em_symbol}")
        print(f"🔄 请求URL: {url}")
        print(f"📋 请求参数: {params}")

        data = await self._make_request(url, params)
        print(f"📥 响应数据: {data}")

        if data and data.get('rc') == 0:
            result_data = data.get('data', {})
            print(f"✅ 成功获取数据: {result_data}")
            return result_data
        else:
            print(f"❌ 获取实时数据失败: {symbol}, 响应码: {data.get('rc') if data else 'None'}")
            return None

    async def get_kline_data(self, symbol: str, period: str = '1d',
                             start_date: str = None, end_date: str = None) -> Optional[Dict[str, Any]]:
        """获取K线数据"""
        em_symbol = self._convert_symbol(symbol)

        # 设置默认时间范围
        if not end_date:
            end_date = datetime.now().strftime('%Y%m%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')

        # 周期映射
        period_map = {
            '1m': '1',  # 1分钟
            '5m': '5',  # 5分钟
            '15m': '15',  # 15分钟
            '30m': '30',  # 30分钟
            '1h': '60',  # 60分钟
            '1d': '101',  # 日线
            '1w': '102',  # 周线
            '1M': '103'  # 月线
        }

        print(f"🔍 周期映射: {period} -> {period_map.get(period, '101')}")
        print(f"🔍 时间范围: {start_date} 到 {end_date}")
        print(f"🔍 股票代码转换: {symbol} -> {em_symbol}")

        klt = period_map.get(period, '101')

        # 计算需要的数据量并判断是否需要分批采集
        try:
            start_dt = datetime.strptime(start_date, '%Y%m%d') if '-' not in start_date else datetime.strptime(
                start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y%m%d') if '-' not in end_date else datetime.strptime(end_date,
                                                                                                         '%Y-%m-%d')
            days_diff = (end_dt - start_dt).days

            # 根据周期估算需要的数据量
            if period in ['1m', '5m', '15m', '30m', '1h']:
                # 分钟级数据：每天约240分钟交易时间
                minutes_per_day = 240
                if period == '1m':
                    estimated_points = days_diff * minutes_per_day
                elif period == '5m':
                    estimated_points = days_diff * (minutes_per_day // 5)
                elif period == '15m':
                    estimated_points = days_diff * (minutes_per_day // 15)
                elif period == '30m':
                    estimated_points = days_diff * (minutes_per_day // 30)
                else:  # 1h
                    estimated_points = days_diff * 4
            else:
                # 日级及以上数据
                estimated_points = days_diff

            print(f"📊 估算数据量: {estimated_points} 个点")

            # 如果数据量超过1500，使用分批采集
            if estimated_points > 1500:
                print(f"🔄 数据量过大({estimated_points}个点)，启用分批采集...")
                return await self._get_kline_data_in_batches(symbol, period, start_date, end_date)
            else:
                # 单次采集
                return await self._get_single_kline_data(symbol, period, start_date, end_date,
                                                         min(2000, estimated_points + 200))

        except Exception as e:
            print(f"⚠️ 数据量计算失败: {e}，使用默认单次采集")
            return await self._get_single_kline_data(symbol, period, start_date, end_date, 500)

    async def _get_single_kline_data(self, symbol: str, period: str, start_date: str, end_date: str, limit: int) -> \
    Optional[Dict[str, Any]]:
        """单次获取K线数据"""
        em_symbol = self._convert_symbol(symbol)
        url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'

        period_map = {
            '1m': '1', '5m': '5', '15m': '15', '30m': '30', '1h': '60',
            '1d': '101', '1w': '102', '1M': '103'
        }
        klt = period_map.get(period, '101')

        params = {
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
            'klt': klt,
            'secid': em_symbol,
            'fqt': '1',  # 前复权
            'lmt': str(limit),
            'end': end_date.replace('-', ''),
            'beg': start_date.replace('-', ''),
            '_': str(int(time.time() * 1000))
        }

        print(f"📈 单次获取K线数据: {symbol}, 数据量限制: {limit}")
        data = await self._make_request(url, params)

        if data and data.get('rc') == 0:
            print(f"✅ 成功获取 {len(data.get('data', {}).get('klines', []))} 条K线数据")
            return data
        else:
            print(f"❌ 获取K线数据失败: {symbol}")
            return None

    async def _get_kline_data_in_batches(self, symbol: str, period: str, start_date: str, end_date: str) -> Optional[
        Dict[str, Any]]:
        """分批获取K线数据 - 增强版，智能处理0数据"""
        print(f"🔄 开始分批获取K线数据...")

        # 解析时间
        start_dt = datetime.strptime(start_date, '%Y%m%d') if '-' not in start_date else datetime.strptime(start_date,
                                                                                                           '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y%m%d') if '-' not in end_date else datetime.strptime(end_date,
                                                                                                     '%Y-%m-%d')

        # 根据周期确定分批策略
        if period in ['1m', '5m']:
            # 分钟级数据：按月分批
            batch_days = 30
        elif period in ['15m', '30m', '1h']:
            # 小时级数据：按季度分批
            batch_days = 90
        else:
            # 日线及以上：按年分批
            batch_days = 365

        all_klines = []
        current_end = end_dt
        batch_count = 0
        max_batches = 20  # 限制最大批次数
        zero_data_batches = 0  # 统计0数据批次
        consecutive_zero = 0  # 连续0数据批次
        max_consecutive_zero = 5  # 最大连续0数据批次

        # 智能终止条件
        now = datetime.now()
        effective_batches = 0  # 有效批次计数

        while current_end > start_dt and batch_count < max_batches and consecutive_zero < max_consecutive_zero:
            batch_count += 1
            # 计算当前批次的开始时间
            current_start = max(start_dt, current_end - timedelta(days=batch_days))

            batch_start_str = current_start.strftime('%Y%m%d')
            batch_end_str = current_end.strftime('%Y%m%d')

            print(f"📦 批次 {batch_count}: {batch_start_str} 到 {batch_end_str}")

            # 智能跳过明显无效的时间段
            skip_reason = self._should_skip_batch(current_start, current_end, now)
            if skip_reason:
                print(f"⏭️  批次 {batch_count} 跳过: {skip_reason}")
                current_end = current_start - timedelta(days=1)
                continue

            # 获取当前批次数据
            batch_data = await self._get_single_kline_data(symbol, period, batch_start_str, batch_end_str, 1500)

            if batch_data and batch_data.get('rc') == 0:
                klines = batch_data.get('data', {}).get('klines', [])
                if klines:
                    all_klines.extend(klines)
                    # 显示数据时间范围
                    first_time = klines[0].split(',')[0]
                    last_time = klines[-1].split(',')[0]
                    print(f"✅ 批次 {batch_count} 获取到 {len(klines)} 条数据")
                    print(f"   📅 数据时间范围: {first_time} 到 {last_time}")

                    effective_batches += 1
                    consecutive_zero = 0  # 重置连续0数据计数
                else:
                    zero_data_batches += 1
                    consecutive_zero += 1

                    # 分析0数据原因并给出建议
                    reason = self._analyze_zero_data_reason(current_start, current_end, now, symbol)
                    print(f"⚠️ 批次 {batch_count} 响应成功但无数据: {reason}")

                    # 如果是未来日期，建议调整时间范围
                    if current_start > now:
                        print(f"   💡 建议: 调整开始日期到 {now.strftime('%Y-%m-%d')} 之前")

            else:
                error_code = batch_data.get('rc', 'Unknown') if batch_data else 'No Response'
                print(f"❌ 批次 {batch_count} 获取失败，错误码: {error_code}")

                consecutive_zero += 1
                zero_data_batches += 1

            # 更新下一批次的结束时间
            current_end = current_start - timedelta(days=1)

            # 智能终止判断
            if batch_count >= 3 and effective_batches == 0:
                print(f"🛑 前3个批次都无数据，可能时间范围有问题，提前终止")
                break

            # 添加延时避免请求过快
            await asyncio.sleep(random.uniform(0.5, 1.5))

        # 采集总结
        print(f"\\n📊 批次采集总结:")
        print(f"   📦 总批次数: {batch_count}")
        print(f"   ✅ 有效批次: {effective_batches}")
        print(f"   ⚠️  0数据批次: {zero_data_batches}")
        print(f"   🔄 连续0数据: {consecutive_zero}")

        if all_klines:
            # 按时间排序（从早到晚）
            all_klines.sort(key=lambda x: x.split(',')[0])
            # 去重（基于时间戳）
            seen_times = set()
            unique_klines = []
            for kline in all_klines:
                timestamp = kline.split(',')[0]
                if timestamp not in seen_times:
                    seen_times.add(timestamp)
                    unique_klines.append(kline)

            print(f"🎉 分批采集完成！总共获取 {len(unique_klines)} 条唯一数据（{effective_batches}个有效批次）")

            if unique_klines:
                print(f"📅 数据时间范围: {unique_klines[0].split(',')[0]} 到 {unique_klines[-1].split(',')[0]}")

            # 数据质量评估
            if zero_data_batches > effective_batches:
                print(f"⚠️  数据质量提醒: 0数据批次({zero_data_batches})多于有效批次({effective_batches})")
                print(f"   💡 建议缩短时间范围或选择其他时段")

            # 构造返回格式
            result = {
                'rc': 0,
                'data': {
                    'code': symbol,
                    'market': 0,
                    'name': f'股票{symbol}',
                    'klines': unique_klines,
                    'dktotal': len(unique_klines)
                },
                'batch_stats': {
                    'total_batches': batch_count,
                    'effective_batches': effective_batches,
                    'zero_data_batches': zero_data_batches,
                    'data_quality_ratio': effective_batches / batch_count if batch_count > 0 else 0
                }
            }
            return result
        else:
            print(f"❌ 分批采集失败，未获取到任何数据")
            print(f"💡 可能原因:")
            print(f"   - 时间范围包含过多未来日期或节假日")
            print(f"   - 股票在该时段停牌或未上市")
            print(f"   - 数据源临时不可用")
            return None

    def _should_skip_batch(self, start_dt: datetime, end_dt: datetime, now: datetime) -> Optional[str]:
        """判断是否应该跳过该批次"""
        # 完全是未来日期
        if start_dt > now:
            return "完全是未来日期"

        # 检查是否在明显的无交易期
        if self._is_obvious_no_trading_period(start_dt, end_dt):
            return "明显的无交易期（节假日密集）"

        # 检查是否过于久远（超过3年）
        if (now - end_dt).days > 1095:
            return "历史数据过于久远（超过3年）"

        return None

    def _is_obvious_no_trading_period(self, start_dt: datetime, end_dt: datetime) -> bool:
        """检查是否为明显的无交易期"""
        # 春节期间（简化判断）
        if start_dt.month == 2 and 10 <= start_dt.day <= 17:
            return True

        # 国庆期间
        if start_dt.month == 10 and 1 <= start_dt.day <= 7:
            return True

        return False

    def _analyze_zero_data_reason(self, start_dt: datetime, end_dt: datetime,
                                  now: datetime, symbol: str) -> str:
        """分析0数据的具体原因"""
        reasons = []

        # 检查未来日期
        if start_dt > now:
            days_future = (start_dt - now).days
            reasons.append(f"未来日期（还有{days_future}天）")
        elif end_dt > now:
            future_days = (end_dt - now).days
            past_days = (now - start_dt).days
            reasons.append(f"部分未来日期（{past_days}天已过，{future_days}天未来）")

        # 检查节假日
        total_days = (end_dt - start_dt).days + 1
        weekend_days = 0
        current = start_dt
        while current <= end_dt:
            if current.weekday() >= 5:  # 周末
                weekend_days += 1
            current += timedelta(days=1)

        if weekend_days / total_days > 0.5:
            reasons.append(f"周末较多（{weekend_days}/{total_days}天）")

        # 检查特殊时期
        if start_dt.month == 1 and start_dt.day <= 7:
            reasons.append("元旦假期")
        elif start_dt.month == 2:
            reasons.append("春节期间")
        elif start_dt.month == 10 and start_dt.day <= 7:
            reasons.append("国庆假期")

        # 检查股票特殊情况
        if symbol.startswith('300') and start_dt.year <= 2009:
            reasons.append("创业板2009年才开板")
        elif symbol.startswith('688') and start_dt.year <= 2019:
            reasons.append("科创板2019年才开板")

        if not reasons:
            reasons.append("数据源可能暂时不可用")

        return "、".join(reasons)

    async def get_minute_data(self, symbol: str, date: str = None) -> Optional[Dict[str, Any]]:
        """获取分时数据"""
        em_symbol = self._convert_symbol(symbol)

        url = urljoin(self.base_url, self.endpoints.get('minute', '/api/qt/stock/trends2/get'))

        if not date:
            date = datetime.now().strftime('%Y%m%d')

        params = {
            'secid': em_symbol,
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
            'fields1': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58',
            'iscr': '0',
            'ndays': '1',
            'cb': f'jQuery{random.randint(100000, 999999)}_{int(time.time() * 1000)}',
            '_': int(time.time() * 1000)
        }

        print(f"⏱️  获取分时数据: {symbol} -> {em_symbol}")

        data = await self._make_request(url, params)
        if data and data.get('rc') == 0:
            return data
        else:
            print(f"❌ 获取分时数据失败: {symbol}")
            return None

    async def get_stock_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取股票基本信息"""
        em_symbol = self._convert_symbol(symbol)

        url = urljoin(self.base_url, '/api/qt/stock/get')

        params = {
            'secid': em_symbol,
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
            'fields': 'f57,f58,f162,f109,f23,f8',
            'cb': f'jQuery{random.randint(100000, 999999)}_{int(time.time() * 1000)}',
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data and data.get('rc') == 0:
            return data.get('data', {})
        else:
            return None

    async def search_stock(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索股票"""
        url = 'https://searchapi.eastmoney.com/api/suggest/get'

        params = {
            'input': keyword,
            'type': '14',
            'token': 'D43BF722C8E33BDC906FB84D85E326E8',
            'count': '10',
            'cb': f'jQuery{random.randint(100000, 999999)}_{int(time.time() * 1000)}',
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data and data.get('QuotationCodeTable'):
            return data['QuotationCodeTable']['Data']
        else:
            return []

    async def get_market_overview(self) -> Optional[Dict[str, Any]]:
        """获取市场概览"""
        url = urljoin(self.base_url, '/api/qt/ulist.np/get')

        params = {
            'fltt': '2',
            'invt': '2',
            'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f33,f11,f62,f128,f136,f115,f152',
            'fid': 'f3',
            'po': '1',
            'pz': '50',
            'pn': '1',
            'np': '1',
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'cb': f'jQuery{random.randint(100000, 999999)}_{int(time.time() * 1000)}',
            '_': int(time.time() * 1000)
        }

        data = await self._make_request(url, params)
        if data and data.get('rc') == 0:
            return data
        else:
            return None

    async def is_available(self) -> bool:
        """检查数据源是否可用"""
        try:
            # 尝试获取上证指数数据来测试连接
            data = await self.get_realtime_data('000001.SH')
            return data is not None
        except Exception as e:
            print(f"❌ 东方财富数据源不可用: {e}")
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

    async def close(self):
        """清理资源"""
        try:
            if self.page:
                await self.page.close()
                print("📄 页面已关闭")

            if self.context:
                await self.context.close()
                print("🌐 浏览器上下文已关闭")

            if self.browser_manager:
                await self.browser_manager.cleanup()
                print("🧹 浏览器管理器已清理")

        except Exception as e:
            print(f"⚠️  清理资源时出错: {e}")

    def __del__(self):
        """析构函数"""
        # 注意：在析构函数中不能直接调用异步方法
        # 实际清理应该通过显式调用close()方法来完成
        pass
