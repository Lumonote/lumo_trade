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
from collections import deque
import random

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

    # 循环数据源��序：东方财富→同花顺→雪球→新浪财经→Tushare→东方财富
    # Tushare 放最后，因为有API调用限制
    CIRCULAR_SOURCE_ORDER = ['eastmoney', 'tonghuashun', 'xueqiu', 'sina', 'tushare']

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

        # 循环切换源状态：记录当前起始索引位置
        self._circular_source_index = 0

        # 初始化爬虫实例
        self.crawlers = {}
        self._init_crawlers()

        # 速率限制器
        rate_config = self.config.get('anti_crawler_settings', {}).get('rate_limiting', {})
        self.rate_limiter = RateLimiter(
            max_requests=rate_config.get('max_requests_per_minute', 10),
            time_window=rate_config.get('time_window', 60)
        )

        # 域名级并发与滑动窗口节流（管理器级，支持配置化）
        self.domain_semaphores: Dict[str, asyncio.Semaphore] = {}
        self.domain_windows: Dict[str, Dict[str, Any]] = {}
        domain_limits_cfg = self.config.get('domain_limits', {})
        if domain_limits_cfg:
            for domain, lim in domain_limits_cfg.items():
                try:
                    concurrency = max(1, int(lim.get('concurrency', 1)))
                except Exception:
                    concurrency = 1
                self.domain_semaphores[domain] = asyncio.Semaphore(concurrency)

                try:
                    max_per_minute = int(lim.get('max_per_minute', 6))
                    window_seconds = float(lim.get('window_seconds', 60.0))
                except Exception:
                    max_per_minute = 6
                    window_seconds = 60.0
                self.domain_windows[domain] = {
                    'max': max_per_minute,
                    'window': window_seconds,
                    'times': deque()
                }
        else:
            # 默认域控（当配置缺失时使用）
            defaults = {
                'push2his.eastmoney.com': {'concurrency': 1, 'max_per_minute': 6, 'window_seconds': 60},
                'push2.eastmoney.com': {'concurrency': 1, 'max_per_minute': 6, 'window_seconds': 60},
                'd.10jqka.com.cn': {'concurrency': 1, 'max_per_minute': 6, 'window_seconds': 60},
                'stockpage.10jqka.com.cn': {'concurrency': 1, 'max_per_minute': 6, 'window_seconds': 60},
                'basic.10jqka.com.cn': {'concurrency': 1, 'max_per_minute': 4, 'window_seconds': 60},
                'searchapi.10jqka.com.cn': {'concurrency': 1, 'max_per_minute': 4, 'window_seconds': 60},
                'stock.xueqiu.com': {'concurrency': 1, 'max_per_minute': 4, 'window_seconds': 60},
                'web.ifzq.gtimg.cn': {'concurrency': 1, 'max_per_minute': 10, 'window_seconds': 60},
                'qt.gtimg.cn': {'concurrency': 2, 'max_per_minute': 20, 'window_seconds': 60},
            }
            for domain, lim in defaults.items():
                self.domain_semaphores[domain] = asyncio.Semaphore(lim['concurrency'])
                self.domain_windows[domain] = {
                    'max': lim['max_per_minute'],
                    'window': float(lim['window_seconds']),
                    'times': deque()
                }

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

    def get_circular_sources(self) -> List[str]:
        """
        获取循环排序的数据源列表
        按照 东方财富→同花顺→Tushare→新浪财经→雪球 的循环顺序返回可用数据源
        从当前 _circular_source_index 位置开始循环
        """
        # 构建完整循环列表（包含所有可能的源，不仅仅是已初始化的爬虫）
        all_sources = list(self.CIRCULAR_SOURCE_ORDER)

        # 从当前索引开始构建循环列表
        n = len(all_sources)
        ordered = []
        for i in range(n):
            idx = (self._circular_source_index + i) % n
            ordered.append(all_sources[idx])

        return ordered

    def advance_circular_index(self, failed_source: str = None):
        """
        推进循环索引到下一个数据源
        当某个数据源失败时调用，使下次调用从下一个源开始
        """
        if failed_source and failed_source in self.CIRCULAR_SOURCE_ORDER:
            # 找到失败源的位置，���索引设为下一个
            try:
                idx = self.CIRCULAR_SOURCE_ORDER.index(failed_source)
                self._circular_source_index = (idx + 1) % len(self.CIRCULAR_SOURCE_ORDER)
                next_source = self.CIRCULAR_SOURCE_ORDER[self._circular_source_index]
                logger.info(f"🔄 数据源 {failed_source} 失败，循环切换到下一个: {next_source}")
            except ValueError:
                self._circular_source_index = (self._circular_source_index + 1) % len(self.CIRCULAR_SOURCE_ORDER)
        else:
            self._circular_source_index = (self._circular_source_index + 1) % len(self.CIRCULAR_SOURCE_ORDER)

    async def get_realtime_data(self, symbol: str, source: str = None) -> Optional[Dict[str, Any]]:
        """
        获取实时数据
        使用循环切换策略：失败一次立即切换到下一个数据源
        循环顺序：东方财富→同花顺→Tushare→新浪财经→雪球
        """
        await self.rate_limiter.acquire()

        if source:
            sources_to_try = [source] if source in self.crawlers or source in ['tushare', 'sina'] else []
        else:
            # 使用循环排序的数据源列表
            sources_to_try = self.get_circular_sources()

        tried_sources = []
        for source_name in sources_to_try:
            # 防止重复尝试
            if source_name in tried_sources:
                continue
            tried_sources.append(source_name)

            try:
                # 处理特殊数据源（Tushare、Sina）- 它们没有专用爬虫类
                if source_name == 'tushare':
                    logger.info(f"使用数据源 Tushare 获取 {symbol} 的数据")
                    data = await self._fetch_tushare_realtime(symbol)
                    if data:
                        logger.info(f"✓ Tushare 成功获取 {symbol} 实时数据")
                        return self.data_processor.process_realtime_data(data, 'tushare')
                    else:
                        logger.warning(f"Tushare 获取 {symbol} 数据返回空，循环切换")
                        self.advance_circular_index(source_name)
                        continue

                elif source_name == 'sina':
                    logger.info(f"使用数据源 新浪财经 获取 {symbol} 的数据")
                    data = await self._fetch_sina_realtime(symbol)
                    if data:
                        logger.info(f"✓ 新浪财经 成功获取 {symbol} 实时数据")
                        return self.data_processor.process_realtime_data(data, 'sina')
                    else:
                        logger.warning(f"新浪财经 获取 {symbol} 数据返回空，循环切换")
                        self.advance_circular_index(source_name)
                        continue

                # 标准爬虫数据源
                if source_name not in self.crawlers:
                    continue

                crawler = self.crawlers[source_name]
                logger.info(f"使用数据源 {source_name} 获取 {symbol} 的数据")

                # 获取数据 - 雪球爬虫需要传递列表参数
                domain = self._get_domain_for_source(source_name, 'realtime')
                if domain:
                    await self._acquire_domain_slot(domain)
                try:
                    if source_name == 'xueqiu':
                        data = await crawler.get_realtime_data([symbol])
                        if data and isinstance(data, list) and len(data) > 0:
                            data = data[0]
                    else:
                        data = await crawler.get_realtime_data(symbol)
                finally:
                    if domain:
                        self._release_domain_slot(domain)

                if data:
                    # 重置失败计数
                    self.failure_counts[source_name] = 0
                    self.source_status[source_name] = 'active'

                    # 数据处理和验证
                    processed_data = self.data_processor.process_realtime_data(data, source_name)
                    return processed_data
                else:
                    # 数据为空，立即循环切换
                    logger.warning(f"数据源 {source_name} 返回空数据，循环切换")
                    self.advance_circular_index(source_name)

            except Exception as e:
                logger.error(f"数据源 {source_name} 获取数据失败: {e}")
                # 失败一次立即切换，不再重试同一个源
                self.advance_circular_index(source_name)
                await self._handle_source_failure_circular(source_name, e)
                continue

        logger.warning(f"所有数据源都无法获取 {symbol} 的实时数据")
        # 备选：尝试免费实时源（Tencent）
        try:
            fallback = await self._fallback_realtime_free(symbol)
            if fallback:
                return self.data_processor.process_realtime_data(fallback, 'free')
        except Exception as fe:
            logger.warning(f"免费源实时数据备选失败: {fe}")
        return None

    async def _fetch_tushare_realtime(self, symbol: str) -> Optional[Dict[str, Any]]:
        """通过 Tushare 获取实时数据"""
        try:
            import tushare as ts

            # 读取 Tushare 配置
            tushare_config_path = os.path.join(project_root, 'config', 'tushare_config.json')
            if os.path.exists(tushare_config_path):
                with open(tushare_config_path, 'r', encoding='utf-8') as f:
                    tushare_cfg = json.load(f)
                    token = tushare_cfg.get('token', '')
                    if token:
                        ts.set_token(token)

            # 标准化股票代码
            code = symbol.upper().strip()
            if '.' in code:
                raw, _ = code.split('.')
                code = raw
            code = code.zfill(6)

            # 使用 Tushare 实时行情接口
            df = ts.get_realtime_quotes(code)
            if df is None or df.empty:
                return None

            row = df.iloc[0]
            return {
                'code': symbol,
                'name': row.get('name', ''),
                'price': float(row.get('price', 0)) if row.get('price') else None,
                'open': float(row.get('open', 0)) if row.get('open') else None,
                'high': float(row.get('high', 0)) if row.get('high') else None,
                'low': float(row.get('low', 0)) if row.get('low') else None,
                'volume': float(row.get('volume', 0)) if row.get('volume') else None,
                'time': row.get('time', '')
            }
        except ImportError:
            logger.warning("Tushare 未安装，跳过该数据源")
            return None
        except Exception as e:
            logger.error(f"Tushare 获取实时数据失败: {e}")
            return None

    async def _fetch_sina_realtime(self, symbol: str) -> Optional[Dict[str, Any]]:
        """通过新浪财经获取实时数据"""
        import urllib.request
        import urllib.parse

        try:
            code = symbol.upper().strip()
            if '.' in code:
                raw, exch = code.split('.')
                prefix = 'sh' if exch == 'SH' else 'sz'
                tgt = f"{prefix}{raw}"
            else:
                code = code.zfill(6)
                prefix = 'sh' if code.startswith(('600', '601', '603', '605', '688')) else 'sz'
                tgt = f"{prefix}{code}"

            url = f"http://hq.sinajs.cn/list={urllib.parse.quote(tgt)}"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://finance.sina.com.cn/'
            })

            with urllib.request.urlopen(req, timeout=10) as resp:
                txt = resp.read().decode('gbk', errors='ignore')

            # 解析格式: var hq_str_sz000001="平安银行,11.12,11.06,..."
            start = txt.find('="')
            end = txt.rfind('"')
            if start == -1 or end == -1:
                return None

            payload = txt[start+2:end]
            parts = payload.split(',')
            if len(parts) < 10:
                return None

            return {
                'code': symbol,
                'name': parts[0] if parts[0] else '',
                'open': float(parts[1]) if parts[1] else None,
                'pre_close': float(parts[2]) if parts[2] else None,
                'price': float(parts[3]) if parts[3] else None,
                'high': float(parts[4]) if parts[4] else None,
                'low': float(parts[5]) if parts[5] else None,
                'volume': float(parts[8]) if len(parts) > 8 and parts[8] else None,
                'amount': float(parts[9]) if len(parts) > 9 and parts[9] else None,
                'time': f"{parts[30]} {parts[31]}" if len(parts) > 31 else ''
            }
        except Exception as e:
            logger.error(f"新浪财经获取���时数据失败: {e}")
            return None

    async def _handle_source_failure_circular(self, source_name: str, error: Exception):
        """处理数据源失败（循环切换模式，不等待重试延迟）"""
        self.failure_counts[source_name] = self.failure_counts.get(source_name, 0) + 1
        setattr(self, f'_{source_name}_last_failure', time.time())

        # 针对反爬检测快速标记
        if 'ERR_EMPTY_RESPONSE' in str(error) or 'ProxyError' in str(error) or '502' in str(error):
            self.source_status[source_name] = 'blocked'
            logger.warning(f"数据源 {source_name} 疑似被反爬，临时禁用")
        else:
            self.source_status[source_name] = 'error'

        # 循环切换模式下不等待，直接切换下一个源

    async def _fallback_realtime_free(self, symbol: str) -> Optional[Dict[str, Any]]:
        """免费实时源备选（Tencent优先）"""
        import urllib.request
        import urllib.parse

        code = symbol.upper().strip()
        if '.' in code:
            raw, exch = code.split('.')
            prefix = 'sh' if exch == 'SH' else 'sz'
            tgt = f"{prefix}{raw}"
        else:
            code = code.zfill(6)
            prefix = 'sh' if code.startswith(('600', '601', '603', '605', '688')) else 'sz'
            tgt = f"{prefix}{code}"

        url = f"http://qt.gtimg.cn/q={urllib.parse.quote(tgt)}"
        await self._acquire_domain_slot('qt.gtimg.cn')
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://qt.gtimg.cn/'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            txt = resp.read().decode('gbk', errors='ignore')
        self._release_domain_slot('qt.gtimg.cn')
        # 格式: v_sz000001="name~price~..."
        start = txt.find('="')
        end = txt.rfind('"')
        if start == -1 or end == -1:
            return None
        payload = txt[start+2:end]
        parts = payload.split('~')
        if len(parts) < 5:
            return None
        # 组装最小字段集，交由处理器规范化
        return {
            'code': symbol,
            'name': parts[1] if len(parts) > 1 else '',
            'price': float(parts[3]) if parts[3] else None,
            'open': float(parts[5]) if len(parts) > 5 and parts[5] else None,
            'high': float(parts[33]) if len(parts) > 33 and parts[33] else None,
            'low': float(parts[34]) if len(parts) > 34 and parts[34] else None,
            'volume': float(parts[36]) if len(parts) > 36 and parts[36] else None,
            'time': parts[30] if len(parts) > 30 else ''
        }

    async def _fallback_kline_free(self, symbol: str, period: str, start_date: Optional[str], end_date: Optional[str]) -> Optional[List[Dict[str, Any]]]:
        """免费K线源备选（Tencent day K线）"""
        import urllib.request
        import urllib.parse
        import json as _json

        code = symbol.upper().strip()
        if '.' in code:
            raw, exch = code.split('.')
            prefix = 'sh' if exch == 'SH' else 'sz'
            tgt = f"{prefix}{raw}"
        else:
            code = code.zfill(6)
            prefix = 'sh' if code.startswith(('600', '601', '603', '605', '688')) else 'sz'
            tgt = f"{prefix}{code}"

        # 仅支持日K作为兜底
        ktype = 'day'
        url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={urllib.parse.quote(tgt)},{ktype},,,320"
        await self._acquire_domain_slot('web.ifzq.gtimg.cn')
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://web.ifzq.gtimg.cn/'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            txt = resp.read().decode('utf-8', errors='ignore')
        self._release_domain_slot('web.ifzq.gtimg.cn')
        data = _json.loads(txt)
        try:
            series = data['data'][tgt].get('day') or []
        except Exception:
            series = []
        if not series:
            return None

        records: List[Dict[str, Any]] = []
        for item in series:
            # [YYYY-MM-DD, open, close, high, low, volume]
            if isinstance(item, list) and len(item) >= 6:
                ts = f"{item[0]} 15:00:00"
                try:
                    rec = {
                        'timestamps': ts,
                        'open': float(item[1]) if item[1] else 0,
                        'close': float(item[2]) if item[2] else 0,
                        'high': float(item[3]) if item[3] else 0,
                        'low': float(item[4]) if item[4] else 0,
                        'volume': float(item[5]) if item[5] else 0,
                        'amount': 0,
                    }
                except Exception:
                    continue
                # 时间范围过滤（若提供）
                if start_date:
                    s = start_date.replace('-', '')
                    if item[0].replace('-', '') < s:
                        continue
                if end_date:
                    e = end_date.replace('-', '')
                    if item[0].replace('-', '') > e:
                        continue
                records.append(rec)

        return records if records else None

    async def get_kline_data(self, symbol: str, period: str = '1d',
                             start_date: str = None, end_date: str = None,
                             source: str = None) -> Optional[List[Dict[str, Any]]]:
        """
        获取K线数据
        使用循环切换策略：失败一次立即切换到下一个数据源
        循环顺序：东方财富→同花顺→Tushare→新浪财经→雪球
        """
        await self.rate_limiter.acquire()

        if source:
            sources_to_try = [source] if source in self.crawlers or source in ['tushare', 'sina'] else []
        else:
            # 使用循环排序的数据源列表
            sources_to_try = self.get_circular_sources()

        tried_sources = []
        for source_name in sources_to_try:
            # 防止重复尝试
            if source_name in tried_sources:
                continue
            tried_sources.append(source_name)

            try:
                # 处理特殊数据源（Tushare、Sina）
                if source_name == 'tushare':
                    logger.info(f"使用数据源 Tushare 获取 {symbol} 的K线数据")
                    data = await self._fetch_tushare_kline(symbol, period, start_date, end_date)
                    if data:
                        logger.info(f"✓ Tushare 成功获取 {symbol} K线数据")
                        return self.data_processor.process_kline_data(data, 'tushare')
                    else:
                        logger.warning(f"Tushare 获取 {symbol} K线数据返回空，循环切换")
                        self.advance_circular_index(source_name)
                        continue

                elif source_name == 'sina':
                    logger.info(f"使用数据源 新浪财经 获取 {symbol} 的K线数据")
                    data = await self._fetch_sina_kline(symbol, period, start_date, end_date)
                    if data:
                        logger.info(f"✓ 新浪财经 成功获取 {symbol} K线数据")
                        return self.data_processor.process_kline_data(data, 'sina')
                    else:
                        logger.warning(f"新浪财经 获取 {symbol} K线数据返回空，循环切换")
                        self.advance_circular_index(source_name)
                        continue

                # 标准爬虫数据源
                if source_name not in self.crawlers:
                    continue

                crawler = self.crawlers[source_name]
                logger.info(f"使用数据源 {source_name} 获取 {symbol} 的K线数据")

                domain = self._get_domain_for_source(source_name, 'kline')
                if domain:
                    await self._acquire_domain_slot(domain)
                try:
                    data = await crawler.get_kline_data(symbol, period, start_date, end_date)
                finally:
                    if domain:
                        self._release_domain_slot(domain)

                if data:
                    # 重置失败计数
                    self.failure_counts[source_name] = 0
                    self.source_status[source_name] = 'active'

                    # 数据处理和验证
                    processed_data = self.data_processor.process_kline_data(data, source_name)
                    return processed_data
                else:
                    # 数据为空，立即循环切换
                    logger.warning(f"数据源 {source_name} 返回空数据，循环切换")
                    self.advance_circular_index(source_name)

            except Exception as e:
                logger.error(f"数据源 {source_name} 获取K线数据失败: {e}")
                # 失败一次立即切换，不再重试同一个源
                self.advance_circular_index(source_name)
                await self._handle_source_failure_circular(source_name, e)
                continue

        logger.warning(f"所有数据源都无法获取 {symbol} 的K线数据")
        # 备选：免费日K线（Tencent）
        try:
            fallback = await self._fallback_kline_free(symbol, period, start_date, end_date)
            if fallback:
                return fallback
        except Exception as fe:
            logger.warning(f"免费源K线数据备选失败: {fe}")
        return None

    async def _fetch_tushare_kline(self, symbol: str, period: str, start_date: str = None, end_date: str = None) -> Optional[List[Dict[str, Any]]]:
        """通过 Tushare 获取K线数据"""
        try:
            import tushare as ts

            # 读取 Tushare 配置
            tushare_config_path = os.path.join(project_root, 'config', 'tushare_config.json')
            if os.path.exists(tushare_config_path):
                with open(tushare_config_path, 'r', encoding='utf-8') as f:
                    tushare_cfg = json.load(f)
                    token = tushare_cfg.get('token', '')
                    if token:
                        ts.set_token(token)

            # 标准化股票代码
            code = symbol.upper().strip()
            if '.' in code:
                raw, exch = code.split('.')
                ts_code = f"{raw}.{exch}"
            else:
                code = code.zfill(6)
                exch = 'SH' if code.startswith(('600', '601', '603', '605', '688')) else 'SZ'
                ts_code = f"{code}.{exch}"

            # 获取K线数据
            pro = ts.pro_api()
            df = pro.daily(ts_code=ts_code, start_date=start_date.replace('-', '') if start_date else None,
                          end_date=end_date.replace('-', '') if end_date else None)

            if df is None or df.empty:
                return None

            records = []
            for _, row in df.iterrows():
                records.append({
                    'timestamps': f"{row['trade_date'][:4]}-{row['trade_date'][4:6]}-{row['trade_date'][6:]} 15:00:00",
                    'open': float(row['open']) if pd.notna(row['open']) else 0,
                    'high': float(row['high']) if pd.notna(row['high']) else 0,
                    'low': float(row['low']) if pd.notna(row['low']) else 0,
                    'close': float(row['close']) if pd.notna(row['close']) else 0,
                    'volume': float(row['vol']) if pd.notna(row['vol']) else 0,
                    'amount': float(row['amount']) * 1000 if pd.notna(row['amount']) else 0,
                })
            return records if records else None

        except ImportError:
            logger.warning("Tushare 未安装，跳过该数据源")
            return None
        except Exception as e:
            logger.error(f"Tushare 获取K线数据失败: {e}")
            return None

    async def _fetch_sina_kline(self, symbol: str, period: str, start_date: str = None, end_date: str = None) -> Optional[List[Dict[str, Any]]]:
        """通过新浪财经获取K线数据"""
        import urllib.request
        import urllib.parse

        try:
            code = symbol.upper().strip()
            if '.' in code:
                raw, exch = code.split('.')
                prefix = 'sh' if exch == 'SH' else 'sz'
                tgt = f"{prefix}{raw}"
            else:
                code = code.zfill(6)
                prefix = 'sh' if code.startswith(('600', '601', '603', '605', '688')) else 'sz'
                tgt = f"{prefix}{code}"

            # 新浪财经K线接口
            url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={urllib.parse.quote(tgt)}&scale=240&ma=no&datalen=500"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://finance.sina.com.cn/'
            })

            with urllib.request.urlopen(req, timeout=15) as resp:
                txt = resp.read().decode('utf-8', errors='ignore')

            import json as _json
            data = _json.loads(txt)
            if not data:
                return None

            records = []
            for item in data:
                # 过滤日期范围
                day = item.get('day', '')
                if start_date and day < start_date:
                    continue
                if end_date and day > end_date:
                    continue

                records.append({
                    'timestamps': f"{day} 15:00:00",
                    'open': float(item.get('open', 0)) if item.get('open') else 0,
                    'high': float(item.get('high', 0)) if item.get('high') else 0,
                    'low': float(item.get('low', 0)) if item.get('low') else 0,
                    'close': float(item.get('close', 0)) if item.get('close') else 0,
                    'volume': float(item.get('volume', 0)) if item.get('volume') else 0,
                    'amount': 0,
                })
            return records if records else None

        except Exception as e:
            logger.error(f"新浪财经获取K线数据失败: {e}")
            return None

    async def get_minute_data(self, symbol: str, source: str = None) -> Optional[List[Dict[str, Any]]]:
        """
        获取分时数据
        使用循环切换策略：失败一次立即切换到下一个数据源
        """
        await self.rate_limiter.acquire()

        if source:
            sources_to_try = [source] if source in self.crawlers or source in ['tushare', 'sina'] else []
        else:
            # 使用循环排序的数据源列表
            sources_to_try = self.get_circular_sources()

        tried_sources = []
        for source_name in sources_to_try:
            # 防止重复尝试
            if source_name in tried_sources:
                continue
            tried_sources.append(source_name)

            # Tushare/Sina 分时数据暂不支持，跳过
            if source_name in ['tushare', 'sina']:
                continue

            try:
                # 标准爬虫数据源
                if source_name not in self.crawlers:
                    continue

                crawler = self.crawlers[source_name]
                logger.info(f"使用数据源 {source_name} 获取 {symbol} 的分时数据")

                domain = self._get_domain_for_source(source_name, 'minute')
                if domain:
                    await self._acquire_domain_slot(domain)
                try:
                    data = await crawler.get_minute_data(symbol)
                finally:
                    if domain:
                        self._release_domain_slot(domain)

                if data:
                    # 重置失败计数
                    self.failure_counts[source_name] = 0
                    self.source_status[source_name] = 'active'

                    # 数据处理和验证
                    processed_data = self.data_processor.process_minute_data(data, source_name)
                    return processed_data
                else:
                    # 数据为空，立即循环切换
                    logger.warning(f"数据源 {source_name} 返回空数据，循环切换")
                    self.advance_circular_index(source_name)

            except Exception as e:
                logger.error(f"数据源 {source_name} 获取分时数据失败: {e}")
                # 失败一次立即切换，不再重试同一个源
                self.advance_circular_index(source_name)
                await self._handle_source_failure_circular(source_name, e)
                continue

        logger.warning(f"所有数据源都无法获取 {symbol} 的分时数据")
        return None

    def _get_domain_for_source(self, source_name: str, action: str) -> Optional[str]:
        """根据配置映射数据源动作到域名，缺失时使用默认映射"""
        try:
            ds = self.config.get('data_sources', {}).get(source_name, {})
            domains = ds.get('domains', {})
            mapped = domains.get(action)
            if mapped:
                return mapped
        except Exception:
            pass

        if source_name == 'eastmoney':
            if action == 'kline':
                return 'push2his.eastmoney.com'
            elif action in ('realtime', 'minute'):
                return 'push2.eastmoney.com'
        if source_name == 'tonghuashun':
            if action == 'kline':
                return 'stockpage.10jqka.com.cn'
            elif action in ('realtime', 'minute'):
                return 'd.10jqka.com.cn'
        if source_name == 'xueqiu':
            return 'stock.xueqiu.com'
        return None

    async def _acquire_domain_slot(self, domain: str) -> None:
        """获取域名级并发与滑动窗口许可"""
        # 并发控制
        sem = self.domain_semaphores.get(domain)
        if sem:
            await sem.acquire()

        # 滑动窗口节流
        win = self.domain_windows.get(domain)
        if win:
            now = time.time()
            window = win['window']
            times: deque = win['times']
            # 清理过期
            cutoff = now - window
            while times and times[0] < cutoff:
                times.popleft()
            # 若达到上限，等待到最早记录过窗
            if len(times) >= win['max']:
                wait_time = window - (now - times[0]) + random.uniform(0.2, 0.7)
                await asyncio.sleep(max(0.0, wait_time))

    def _release_domain_slot(self, domain: str) -> None:
        """释放并记录域名级并发与滑动窗口"""
        # 记录请求时间到滑动窗口
        win = self.domain_windows.get(domain)
        if win:
            now = time.time()
            times: deque = win['times']
            times.append(now)
        # 释放并发信号量
        sem = self.domain_semaphores.get(domain)
        if sem:
            try:
                sem.release()
            except ValueError:
                pass

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

        # 针对反爬重置（ERR_EMPTY_RESPONSE）快速降级
        if 'ERR_EMPTY_RESPONSE' in str(error):
            self.failure_counts[source_name] = max_failures

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
