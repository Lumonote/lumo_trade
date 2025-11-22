#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热门股票获取器
从多个数据源获取市场热度TOP100的股票
"""

import requests
import pandas as pd
from typing import List, Dict, Optional
import time
import json
import os
import asyncio
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HotStocksFetcher:
    """热门股票获取器 - 从多个数据源获取市场热度TOP股票"""

    def __init__(self, cache_dir: str = None):
        """
        初始化热门股票获取器

        Args:
            cache_dir: 缓存目录路径（可选）。
                      若未提供，将优先使用环境变量 KRONOS_DATA_DIR 下的 cache 目录，
                      否则回退到项目相对路径 data/cache。
        """
        # 优先使用用户数据目录，适配打包环境的写权限
        if cache_dir is None:
            base_data_dir = os.environ.get("KRONOS_DATA_DIR") or os.path.join(os.getcwd(), "data")
            cache_dir = os.path.join(base_data_dir, "cache")

        self.cache_dir = cache_dir
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception as e:
            # 在极端情况下（目录不可写）回退到用户家目录临时缓存
            fallback_dir = os.path.join(os.path.expanduser("~"), "Kronos", "cache")
            try:
                os.makedirs(fallback_dir, exist_ok=True)
                self.cache_dir = fallback_dir
                logger.warning(f"缓存目录不可写，回退到: {fallback_dir} (原因: {e})")
            except Exception:
                # 最后回退到系统临时目录
                import tempfile
                self.cache_dir = tempfile.mkdtemp(prefix="kronos_cache_")
                logger.warning(f"缓存目录不可写，回退到临时目录: {self.cache_dir}")

        # 使用最终确定的缓存目录，避免在回退后仍指向不可写目录
        self.cache_file = os.path.join(self.cache_dir, "hot_stocks_cache.json")
        self.cache_ttl = 3600  # 缓存1小时

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'http://quote.eastmoney.com/',
        }

        # 浏览器采集支持（用于同花顺反爬场景）
        try:
            from scripts.browser_manager import BrowserManager  # 延迟导入以避免未安装Playwright时失败
            self._BrowserManager = BrowserManager
        except Exception:
            self._BrowserManager = None

    def get_hot_stocks(self, limit: int = 100, force_refresh: bool = False) -> List[Dict]:
        """
        获取热门股票TOP100

        Args:
            limit: 返回股票数量，默认100
            force_refresh: 是否忽略缓存，强制直接采集（默认否）

        Returns:
            list: [{
                'code': '688401',
                'name': '金山云',
                'exchange': 'SH',  # SH或SZ
                'popularity_score': 95.5,  # 综合热度评分
                'change_pct': 3.2,  # 涨跌幅%
                'turnover_rate': 8.5,  # 换手率%
                'volume': 1234567,  # 成交量
                'amount': 1234567890.0,  # 成交额
                'latest_price': 123.45,  # 最新价
                'source': 'eastmoney'  # 数据来源
            }, ...]
        """
        logger.info(f"开始获取热门股票 TOP{limit}")

        # 环境变量可强制刷新
        env_force = os.environ.get('KRONOS_FORCE_REFRESH') == '1'

        # 检查缓存（可被强制刷新禁用）
        cached_data = None if (force_refresh or env_force) else self._load_cache()
        if cached_data:
            stocks_from_cache = cached_data.get('stocks') or []
            # 若缓存来源为本地回退或未知来源，则忽略缓存
            valid_sources = {'eastmoney', 'tonghuashun', 'xueqiu', 'tushare'}
            all_sources = {str(s.get('source') or '').lower() for s in stocks_from_cache}
            if all_sources and all_sources.issubset(valid_sources):
                logger.info(f"使用缓存数据（缓存时间: {cached_data['timestamp']}）")
                return stocks_from_cache[:limit]
            else:
                logger.info("检测到缓存来源非直接采集（可能为fallback/未知），忽略缓存，改为直接采集")

        stocks = []

        try:
            logger.info("正在从东方财富VIP接口获取热度榜...")
            vip_stocks = self._fetch_from_eastmoney_vip(limit=limit)
            if vip_stocks:
                stocks = vip_stocks
                logger.info(f"✓ 东方财富VIP获取成功: {len(vip_stocks)} 只股票")
            else:
                logger.info("VIP接口为空，尝试东方财富API...")
                eastmoney_stocks = self._fetch_from_eastmoney()
                if eastmoney_stocks:
                    stocks = eastmoney_stocks
                    logger.info(f"✓ 东方财富API获取成功: {len(eastmoney_stocks)} 只股票")
        except Exception as e:
            logger.warning(f"东方财富获取失败: {e}")
            try:
                logger.info("尝试东方财富备用入口...")
                alt_stocks = self._fetch_from_eastmoney_alt(limit=limit)
                if alt_stocks:
                    stocks = alt_stocks
                    logger.info(f"✓ 东方财富备用入口获取成功: {len(alt_stocks)} 只股票")
            except Exception as e2:
                logger.warning(f"东方财富备用入口获取失败: {e2}")

        if not stocks:
            try:
                logger.info("正在从同花顺获取热度榜...")
                tonghuashun_stocks = self._fetch_from_tonghuashun()
                if tonghuashun_stocks:
                    stocks = tonghuashun_stocks[:limit]
                    logger.info(f"✓ 同花顺获取成功: {len(tonghuashun_stocks)} 只股票")
            except Exception as e:
                logger.warning(f"同花顺获取失败: {e}")

        if not stocks:
            logger.error("所有数据源均获取失败，尝试使用备用数据源")
            # 尝试使用备用数据源或生成示例数据
            fallback_stocks = self._get_fallback_stocks(limit)
            if fallback_stocks:
                logger.warning(f"使用备用数据源，获取 {len(fallback_stocks)} 只股票")
                stocks = fallback_stocks
            else:
                logger.error("所有数据源均获取失败，返回空列表")
                return []

        # 缓存数据
        self._save_cache(stocks)

        logger.info(f"✓ 热门股票获取完成: {len(stocks)} 只股票")
        return stocks[:limit]

    

    def _fetch_from_eastmoney(self) -> List[Dict]:
        """
        从东方财富获取热榜-热股100

        API说明:
        - 使用东方财富热榜（基于用户关注度、搜索量、讨论热度等综合人气）
        - f164: 热度指数/人气值
        """
        stocks = []

        # 方案1: 东方财富热榜-热股100（按热度指数排序）
        popularity_url = "https://push2.eastmoney.com/api/qt/clist/get"

        # 尝试多个可能的热度排序字段
        heat_fields = [
            ('f164', '热度指数')
        ]

        for field_id, field_name in heat_fields:
            try:
                popularity_params = {
                    'pn': '1',
                    'pz': '100',
                    'po': '1',
                    'np': '1',
                    'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                    'fltt': '2',
                    'invt': '2',
                    'fid': field_id,  # 热度排序字段
                    'fs': 'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23',  # A股市场（主板+创业板+科创板）
                    'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f11,f62,f128,f136,f115,f152,f164',
                    '_': str(int(time.time() * 1000))
                }

                logger.info(f"尝试获取热榜（按{field_name}排序）...")
                response = requests.get(popularity_url, params=popularity_params, headers=self.headers, timeout=10)
                response.raise_for_status()
                data = response.json()

                if data.get('data') and data['data'].get('diff') and len(data['data']['diff']) > 0:
                    logger.info(f"✓ 热榜API返回 {len(data['data']['diff'])} 只股票（使用{field_name}）")

                    for idx, item in enumerate(data['data']['diff'], start=1):
                        try:
                            # 解析股票信息
                            code = item.get('f12', '')  # 股票代码
                            name = item.get('f14', '')  # 股票名称
                            market = item.get('f13', '')  # 市场代码 (0=深市, 1=沪市)

                            # 过滤无效数据
                            if not code or not name:
                                continue

                            # 确定交易所（使用股票代码判断，更可靠）
                            if market == '0':
                                exchange = 'SZ'
                            elif market == '1':
                                exchange = 'SH'
                            else:
                                # 根据股票代码判断交易所
                                if code.startswith(('000', '001', '002', '003', '300')):
                                    exchange = 'SZ'
                                elif code.startswith(('600', '601', '603', '605', '688', '689')):
                                    exchange = 'SH'
                                else:
                                    exchange = 'SZ'  # 默认深交所

                            # 获取各项指标
                            change_pct = float(item.get('f3', 0)) if item.get('f3') else 0  # 涨跌幅
                            turnover_rate = float(item.get('f8', 0)) if item.get('f8') else 0  # 换手率
                            volume = float(item.get('f5', 0)) if item.get('f5') else 0  # 成交量（手）
                            amount = float(item.get('f6', 0)) if item.get('f6') else 0  # 成交额（元）
                            main_fund_flow = float(item.get('f62', 0)) if item.get('f62') else 0  # 主力资金净流入
                            heat_index = float(item.get('f164', 0)) if item.get('f164') else 0  # 热度指数

                            # 计算综合人气评分
                            if heat_index > 0:
                                # 如果有热度指数，直接使用并归一化到0-100
                                popularity_score = min(100, heat_index)
                            else:
                                # 否则使用其他指标计算
                                popularity_score = self._calculate_popularity_score_v2(
                                    main_fund_flow=main_fund_flow,
                                    amount=amount,
                                    turnover_rate=turnover_rate,
                                    change_pct=change_pct,
                                    volume=volume
                                )

                            stock_info = {
                                'code': code,
                                'name': name,
                                'exchange': exchange,
                                'popularity_score': round(popularity_score, 2),
                                'change_pct': round(change_pct, 2),
                                'turnover_rate': round(turnover_rate, 2),
                                'volume': int(volume * 100),  # 手转换为股
                                'amount': round(amount, 2),
                                'latest_price': float(item.get('f2', 0)) if item.get('f2') else 0,  # 最新价
                                'source': 'eastmoney',
                                'rank': idx
                            }

                            stocks.append(stock_info)
                        except Exception as e:
                            logger.debug(f"解析股票信息失败: {e}")
                            continue

                    if len(stocks) >= 50:
                        return stocks[:100]

            except Exception as e:
                logger.warning(f"使用{field_name}获取失败: {e}，尝试下一个字段...")
                continue

        # 如果所有方案都失败
        if not stocks:
            logger.error("所有热榜API方案均失败")
            raise Exception("无法获取东方财富热榜数据")

        return stocks

    def _fetch_from_eastmoney_alt(self, limit: int = 100) -> List[Dict]:
        if self._BrowserManager is None:
            return []
        try:
            return asyncio.run(self._fetch_from_eastmoney_alt_async(limit))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(self._fetch_from_eastmoney_alt_async(limit))
            finally:
                loop.close()

    async def _fetch_from_eastmoney_alt_async(self, limit: int = 100) -> List[Dict]:
        url = "https://vipmoney.eastmoney.com/collect/app_ranking/ranking/app.html?hashcode=_1763026482032&market=&appfenxiang=1#/stock"
        extra_headers = {
            **self.headers,
            'Referer': 'https://vipmoney.eastmoney.com/',
            'Cache-Control': 'no-cache'
        }
        stocks: List[Dict] = []
        async with self._BrowserManager() as manager:
            async with manager.get_page() as page:
                await page.set_extra_http_headers(extra_headers)
                resp = await page.goto(url, wait_until='networkidle', timeout=20000)
                if not resp or resp.status != 200:
                    return []
                try:
                    await page.wait_for_selector('table', timeout=10000)
                except Exception:
                    pass
                rows = await page.locator('tr').all()
                rank_idx = 0
                for row in rows:
                    try:
                        cells = await row.locator('td').all()
                        if len(cells) < 3:
                            continue
                        texts = []
                        for c in cells[:8]:
                            try:
                                texts.append((await c.inner_text()).strip())
                            except Exception:
                                texts.append('')
                        joined = ' '.join(texts)
                        import re
                        m_code = re.search(r'(\d{6})', joined)
                        if not m_code:
                            continue
                        code = m_code.group(1)
                        name = texts[1] if len(texts) > 1 and texts[1] and not texts[1].isdigit() else ''
                        if not name:
                            m_name = re.search(r'(\D+)', joined)
                            name = m_name.group(1).strip() if m_name else ''
                        if code.startswith(('000','001','002','003','300')):
                            exchange = 'SZ'
                        elif code.startswith(('600','601','603','605','688','689')):
                            exchange = 'SH'
                        else:
                            exchange = 'SZ'
                        latest_price = 0.0
                        change_pct = 0.0
                        turnover_rate = 0.0
                        for t in texts:
                            try:
                                if t.endswith('%'):
                                    change_pct = float(t.replace('%','').replace(',',''))
                                elif t.replace('.','',1).replace(',','').isdigit():
                                    latest_price = float(t.replace(',',''))
                            except Exception:
                                pass
                        rank_idx += 1
                        popularity_score = max(0, 100 - (rank_idx - 1))
                        stocks.append({
                            'code': code,
                            'name': name,
                            'exchange': exchange,
                            'popularity_score': round(popularity_score, 2),
                            'change_pct': round(change_pct, 2),
                            'turnover_rate': round(turnover_rate, 2),
                            'volume': 0,
                            'amount': 0.0,
                            'latest_price': latest_price,
                            'source': 'eastmoney_alt',
                            'rank': rank_idx
                        })
                        if len(stocks) >= limit:
                            break
                    except Exception:
                        continue
        return stocks

    def _fetch_from_eastmoney_vip(self, limit: int = 100) -> List[Dict]:
        stocks: List[Dict] = []
        headers = {
            **self.headers,
            'Referer': 'https://vipmoney.eastmoney.com/collect/stockranking/pages/ranking/list.html'
        }
        try:
            js_url = 'https://vipmoney.eastmoney.com/collect/stockranking/static/script/ranking_list.js'
            r1 = requests.get(js_url, headers=headers, timeout=10)
            r1.raise_for_status()
            txt = r1.text
            import re
            m_ut = re.search(r'ut:"(.*?)"', txt)
            m_fields = re.search(r'fields:"(.*?)"', txt)
            m_gid = re.search(r'globalId:"(.*?)"', txt)
            ut_val = m_ut.group(1) if m_ut else ''
            fields_val = m_fields.group(1) if m_fields else ''
            gid_val = m_gid.group(1) if m_gid else ''
            if not ut_val or not fields_val:
                return []
            h2 = {
                **headers,
                'Host': 'emappdata.eastmoney.com',
                'Origin': 'https://vipmoney.eastmoney.com'
            }
            payload = {
                'appId': 'appId01',
                'globalId': gid_val,
                'pageNo': '1',
                'pageSize': str(limit)
            }
            r2 = requests.post('https://emappdata.eastmoney.com/stockrank/getAllCurrentList', json=payload, headers=h2, timeout=10)
            r2.raise_for_status()
            j2 = r2.json()
            items = j2.get('data') or []
            if not items:
                return []
            secids: List[str] = []
            for it in items[:limit]:
                sc = str(it.get('sc') or '')
                if not sc:
                    continue
                if 'SH' in sc:
                    secids.append('1.' + sc.replace('SH', ''))
                elif 'SZ' in sc:
                    secids.append('0.' + sc.replace('SZ', ''))
            if not secids:
                return []
            secids_str = ','.join(secids)
            h3 = {
                **headers,
                'Host': 'push2.eastmoney.com'
            }
            params = {
                'ut': ut_val,
                'fltt': '2',
                'invt': '2',
                'fields': fields_val,
                'secids': secids_str
            }
            r3 = requests.post('https://push2.eastmoney.com/api/qt/ulist.np/get?', data=params, headers=h3, timeout=10)
            r3.raise_for_status()
            j3 = r3.json()
            diff = ((j3.get('data') or {}).get('diff')) or []
            rank_idx = 0
            for item in diff:
                try:
                    code = str(item.get('f12') or '')
                    name = str(item.get('f14') or '')
                    if not code or not name:
                        continue
                    if code.startswith(('000', '001', '002', '003', '300')):
                        exchange = 'SZ'
                    elif code.startswith(('600', '601', '603', '605', '688', '689')):
                        exchange = 'SH'
                    else:
                        exchange = 'SZ'
                    change_pct = float(item.get('f3', 0) or 0)
                    turnover_rate = float(item.get('f8', 0) or 0)
                    volume = float(item.get('f5', 0) or 0)
                    amount = float(item.get('f6', 0) or 0)
                    heat_index = float(item.get('f164', 0) or 0)
                    latest_price = float(item.get('f2', 0) or 0)
                    rank_idx += 1
                    popularity_score = heat_index if heat_index > 0 else max(0, 100 - (rank_idx - 1))
                    stocks.append({
                        'code': code,
                        'name': name,
                        'exchange': exchange,
                        'popularity_score': round(popularity_score, 2),
                        'change_pct': round(change_pct, 2),
                        'turnover_rate': round(turnover_rate, 2),
                        'volume': int(volume * 100),
                        'amount': round(amount, 2),
                        'latest_price': latest_price,
                        'source': 'eastmoney_vip',
                        'rank': rank_idx
                    })
                    if len(stocks) >= limit:
                        break
                except Exception:
                    continue
            return stocks
        except Exception as e:
            logger.warning(f"东方财富VIP接口失败: {e}")
            return []

    def _calculate_popularity_score_v2(self, main_fund_flow: float, amount: float,
                                       turnover_rate: float, change_pct: float, volume: float) -> float:
        """
        计算人气评分V2（基于主力资金流向）

        评分维度:
        1. 主力资金净流入 (50%) - 核心人气指标
        2. 成交额 (25%) - 市场关注度
        3. 换手率 (15%) - 交易活跃度
        4. 涨跌幅 (10%) - 市场情绪
        """
        import math

        # 主力资金评分（亿为单位，正流入加分，负流入减分）
        fund_score = 0
        if main_fund_flow != 0:
            fund_yi = main_fund_flow / 1e8
            # 使用sigmoid函数将资金流入映射到0-100
            # 正值越大分数越高，负值越小分数越低
            fund_score = 50 + 50 * (2 / (1 + math.exp(-fund_yi / 5)) - 1)
        else:
            fund_score = 50  # 无数据时给中性分

        # 成交额评分
        amount_score = min(100, (math.log10(amount / 1e8 + 1) / math.log10(1000)) * 100) if amount > 0 else 0

        # 换手率评分
        turnover_score = min(100, (turnover_rate / 20) * 100)

        # 涨跌幅评分
        change_score = min(100, (abs(change_pct) / 10) * 100)

        # 加权计算
        total_score = (
            fund_score * 0.5 +
            amount_score * 0.25 +
            turnover_score * 0.15 +
            change_score * 0.1
        )

        return total_score

    def _fetch_from_tonghuashun(self) -> List[Dict]:
        """
        从同花顺获取热度榜/人气榜

        优化说明:
        - 使用同花顺人气榜专用URL
        - 多URL备选，提高成功率
        - 改进HTML解析逻辑
        """
        stocks = []

        # 同花顺人气榜URL（多个备选）
        urls_to_try = [
            # 人气榜（按关注度排序）
            "https://data.10jqka.com.cn/rank/lhb/board/all/field/lbhy/order/desc/page/1/ajax/1/",
            "https://data.10jqka.com.cn/rank/cjl/board/all/field/hs/order/desc/page/1/ajax/1/",  # 换手率榜
            "https://data.10jqka.com.cn/rank/cjl/board/all/field/amount/order/desc/page/1/ajax/1/",  # 成交额榜
            # 不带ajax参数的备用URL
            "https://data.10jqka.com.cn/rank/lhb/board/all/field/lbhy/order/desc/page/1/",
            "https://data.10jqka.com.cn/rank/cjl/board/all/field/hs/order/desc/page/1/",
        ]

        headers = {
            **self.headers,
            'Referer': 'https://data.10jqka.com.cn/',
            'Host': 'data.10jqka.com.cn',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'text/html, */*; q=0.01'
        }

        for url in urls_to_try:
            try:
                logger.info(f"尝试同花顺URL: {url}")
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()

                html = response.text
                logger.debug(f"同花顺响应长度: {len(html)}")

                # 检查是否返回了有效内容
                if len(html) < 100 or '<html><head></head><body></body></html>' in html:
                    logger.warning(f"同花顺URL返回空内容: {url}")
                    continue

                # 尝试多种解析方法
                parsed = self._parse_tonghuashun_table_v2(html)
                if not parsed:
                    parsed = self._parse_tonghuashun_table(html)

                if parsed and len(parsed) >= 20:  # 至少要有20只股票才认为成功
                    stocks.extend(parsed[:100])
                    logger.info(f"✓ 同花顺获取成功: {len(parsed)} 只股票")
                    return stocks
                else:
                    logger.warning(f"同花顺HTML解析结果不足: 仅{len(parsed) if parsed else 0}只股票")

            except Exception as e:
                logger.warning(f"同花顺URL失败: {url} - {e}")
                continue

        # 如果所有URL都失败，尝试浏览器采集
        logger.warning("所有同花顺URL均失败，尝试浏览器采集")
        try:
            browser_result = self._fetch_tonghuashun_via_browser(limit=100)
            stocks.extend(browser_result)
            return stocks
        except Exception as e:
            logger.error(f"同花顺浏览器采集也失败: {e}")
            return []

    def _parse_tonghuashun_table_v2(self, html: str) -> List[Dict]:
        """解析同花顺排行榜HTML片段为股票列表（改进版）"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            result: List[Dict] = []
            rows = soup.find_all('tr')

            for row in rows:
                try:
                    cells = row.find_all('td')
                    if len(cells) < 3:
                        continue

                    # 尝试提取股票代码和名称
                    code_cell = cells[1] if len(cells) > 1 else None
                    name_cell = cells[2] if len(cells) > 2 else None

                    if not code_cell or not name_cell:
                        continue

                    code = code_cell.get_text(strip=True)
                    name = name_cell.get_text(strip=True)

                    # 验证股票代码格式
                    if not code or not code.isdigit() or len(code) != 6:
                        continue

                    # 确定交易所
                    if code.startswith(('000', '001', '002', '003', '300')):
                        exchange = 'SZ'
                    elif code.startswith(('600', '601', '603', '605', '688', '689')):
                        exchange = 'SH'
                    else:
                        exchange = 'SZ'

                    # 尝试提取更多数据
                    price = 0.0
                    change_pct = 0.0
                    turnover_rate = 0.0

                    if len(cells) > 3:
                        try:
                            price = float(cells[3].get_text(strip=True).replace(',', ''))
                        except:
                            pass

                    if len(cells) > 4:
                        try:
                            change_text = cells[4].get_text(strip=True).replace('%', '')
                            change_pct = float(change_text)
                        except:
                            pass

                    if len(cells) > 7:
                        try:
                            turnover_text = cells[7].get_text(strip=True).replace('%', '')
                            turnover_rate = float(turnover_text)
                        except:
                            pass

                    # 计算人气评分
                    popularity_score = 50.0 + abs(change_pct) * 2 + turnover_rate * 1.5
                    popularity_score = min(100, popularity_score)

                    result.append({
                        'code': code,
                        'name': name,
                        'exchange': exchange,
                        'popularity_score': round(popularity_score, 2),
                        'change_pct': round(change_pct, 2),
                        'turnover_rate': round(turnover_rate, 2),
                        'volume': 0,
                        'amount': 0.0,
                        'latest_price': price,
                        'source': 'tonghuashun'
                    })
                except Exception as e:
                    logger.debug(f"解析行失败: {e}")
                    continue

            return result
        except ImportError:
            logger.warning("BeautifulSoup未安装，回退到正则表达式解析")
            return []
        except Exception as parse_err:
            logger.debug(f"同花顺HTML解析异常(V2): {parse_err}")
            return []

    def _parse_tonghuashun_table(self, html: str) -> List[Dict]:
        """解析同花顺排行榜HTML片段为股票列表"""
        try:
            import re
            pattern = r'<td>(\d{6})</td><td[^>]*>([^<]+)</td><td[^>]*>([^<]+)</td>'
            matches = re.findall(pattern, html)
            result: List[Dict] = []
            for code, name, price in matches:
                exchange = 'SH' if code.startswith('6') else 'SZ'
                result.append({
                    'code': code,
                    'name': name,
                    'exchange': exchange,
                    'popularity_score': 50.0,
                    'change_pct': 0.0,
                    'turnover_rate': 0.0,
                    'volume': 0,
                    'amount': 0.0,
                    'latest_price': float(price) if price else 0.0,
                    'source': 'tonghuashun'
                })
            return result
        except Exception as parse_err:
            logger.debug(f"同花顺HTML解析异常: {parse_err}")
            return []

    def _fetch_tonghuashun_via_browser(self, limit: int = 100) -> List[Dict]:
        """使用浏览器采集同花顺排行榜，绕过反爬与鉴权"""
        if self._BrowserManager is None:
            logger.error("浏览器管理器不可用，无法进行浏览器采集")
            return []

        try:
            return asyncio.run(self._fetch_tonghuashun_via_browser_async(limit))
        except RuntimeError:
            # 如果已有事件循环在运行，使用新循环
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(self._fetch_tonghuashun_via_browser_async(limit))
            finally:
                loop.close()

    async def _fetch_tonghuashun_via_browser_async(self, limit: int = 100) -> List[Dict]:
        # 尝试多个同花顺URL
        urls_to_try = [
            "https://data.10jqka.com.cn/rank/cjl/board/all/field/amount/order/desc/page/1/ajax/1/",
            "https://data.10jqka.com.cn/rank/cjl/board/all/field/amount/order/desc/page/1/",
            "https://data.10jqka.com.cn/rank/cjl/board/all/field/amount/order/desc/",
            "https://data.10jqka.com.cn/rank/cjl/board/all/field/amount/order/desc/page/1/ajax/1"
        ]
        
        extra_headers = {
            **self.headers,
            'Referer': 'https://data.10jqka.com.cn/',
            'Host': 'data.10jqka.com.cn',
            'X-Requested-With': 'XMLHttpRequest',
            'Cache-Control': 'no-cache'
        }
        stocks: List[Dict] = []

        try:
            async with self._BrowserManager() as manager:
                async with manager.get_page() as page:
                    await page.set_extra_http_headers(extra_headers)
                    
                    for url in urls_to_try:
                        try:
                            logger.info(f"浏览器尝试同花顺URL: {url}")
                            resp = await page.goto(url, wait_until='networkidle', timeout=15000)
                            if not resp or resp.status != 200:
                                logger.warning(f"同花顺浏览器请求失败，状态码: {resp.status if resp else 'None'}")
                                continue
                                
                            html = await page.content()
                            logger.debug(f"浏览器响应长度: {len(html)}")
                            
                            # 检查是否返回了有效内容
                            if len(html) < 100 or '<html><head></head><body></body></html>' in html:
                                logger.warning(f"同花顺浏览器返回空内容: {url}")
                                continue
                                
                            parsed = self._parse_tonghuashun_table(html)
                            if parsed:
                                stocks.extend(parsed[:limit])
                                logger.info(f"✓ 同花顺浏览器采集成功: {len(parsed)} 只股票")
                                return stocks
                            else:
                                logger.warning(f"同花顺浏览器HTML解析失败: {url}")
                                
                        except Exception as e:
                            logger.warning(f"同花顺浏览器URL失败: {url} - {e}")
                            continue
                            
        except Exception as e:
            logger.error(f"同花顺浏览器采集异常: {e}")
            return []

        return stocks

    def _calculate_popularity_score(self, amount: float, turnover_rate: float,
                                   change_pct: float, volume: float) -> float:
        """
        计算综合热度评分（0-100分）

        评分维度:
        1. 成交额 (40%) - 反映市场关注度
        2. 换手率 (30%) - 反映交易活跃度
        3. 涨跌幅 (20%) - 反映市场情绪
        4. 成交量 (10%) - 反映参与度

        Args:
            amount: 成交额（元）
            turnover_rate: 换手率(%)
            change_pct: 涨跌幅(%)
            volume: 成交量（股）
        """
        # 归一化处理（使用对数缩放）
        import math

        # 成交额评分（亿为单位，对数缩放到0-100）
        amount_score = min(100, (math.log10(amount / 1e8 + 1) / math.log10(1000)) * 100) if amount > 0 else 0

        # 换手率评分（超过20%为满分）
        turnover_score = min(100, (turnover_rate / 20) * 100)

        # 涨跌幅评分（绝对值，-10%到+10%映射到0-100）
        change_score = min(100, (abs(change_pct) / 10) * 100)

        # 成交量评分（百万股为单位，对数缩放）
        volume_score = min(100, (math.log10(volume / 1e6 + 1) / math.log10(1000)) * 100) if volume > 0 else 0

        # 加权计算综合得分
        total_score = (
            amount_score * 0.4 +
            turnover_score * 0.3 +
            change_score * 0.2 +
            volume_score * 0.1
        )

        return total_score

    def _deduplicate_and_sort(self, stocks: List[Dict]) -> List[Dict]:
        """
        去重并按热度评分排序

        Args:
            stocks: 股票列表

        Returns:
            去重排序后的股票列表
        """
        # 使用字典去重（以股票代码为key）
        unique_stocks = {}
        for stock in stocks:
            code = stock['code']
            if code not in unique_stocks:
                unique_stocks[code] = stock
            else:
                # 如果已存在，保留热度更高的
                if stock['popularity_score'] > unique_stocks[code]['popularity_score']:
                    unique_stocks[code] = stock

        # 转换为列表并按热度评分降序排序
        sorted_stocks = sorted(
            unique_stocks.values(),
            key=lambda x: x['popularity_score'],
            reverse=True
        )

        return sorted_stocks

    def _get_fallback_stocks(self, limit: int) -> List[Dict]:
        """
        获取备用股票数据（当所有数据源都失败时使用）
        
        Args:
            limit: 返回股票数量
            
        Returns:
            备用股票列表
        """
        # 扩展的知名热门股票作为备用数据（包含更多板块）
        fallback_stocks = [
            # 银行板块
            {'code': '000001', 'name': '平安银行', 'exchange': 'SZ', 'popularity_score': 85.5, 'change_pct': 2.3, 'turnover_rate': 3.2, 'volume': 50000000, 'amount': 5000000000, 'latest_price': 12.45, 'source': 'fallback'},
            {'code': '600036', 'name': '招商银行', 'exchange': 'SH', 'popularity_score': 84.6, 'change_pct': 1.9, 'turnover_rate': 3.1, 'volume': 40000000, 'amount': 4000000000, 'latest_price': 35.78, 'source': 'fallback'},
            {'code': '601398', 'name': '工商银行', 'exchange': 'SH', 'popularity_score': 78.2, 'change_pct': 0.8, 'turnover_rate': 1.9, 'volume': 30000000, 'amount': 3000000000, 'latest_price': 5.23, 'source': 'fallback'},
            {'code': '601939', 'name': '建设银行', 'exchange': 'SH', 'popularity_score': 76.8, 'change_pct': 0.5, 'turnover_rate': 1.5, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 6.45, 'source': 'fallback'},
            {'code': '600000', 'name': '浦发银行', 'exchange': 'SH', 'popularity_score': 74.3, 'change_pct': 0.3, 'turnover_rate': 1.8, 'volume': 32000000, 'amount': 3200000000, 'latest_price': 8.12, 'source': 'fallback'},
            
            # 白酒板块
            {'code': '600519', 'name': '贵州茅台', 'exchange': 'SH', 'popularity_score': 96.3, 'change_pct': 3.8, 'turnover_rate': 2.9, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 1688.88, 'source': 'fallback'},
            {'code': '000858', 'name': '五粮液', 'exchange': 'SZ', 'popularity_score': 88.9, 'change_pct': 3.2, 'turnover_rate': 4.1, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 156.78, 'source': 'fallback'},
            {'code': '000596', 'name': '古井贡酒', 'exchange': 'SZ', 'popularity_score': 82.4, 'change_pct': 2.8, 'turnover_rate': 3.5, 'volume': 18000000, 'amount': 1800000000, 'latest_price': 98.45, 'source': 'fallback'},
            {'code': '600809', 'name': '山西汾酒', 'exchange': 'SH', 'popularity_score': 86.7, 'change_pct': 4.1, 'turnover_rate': 4.8, 'volume': 22000000, 'amount': 2200000000, 'latest_price': 245.67, 'source': 'fallback'},
            {'code': '000799', 'name': '酒鬼酒', 'exchange': 'SZ', 'popularity_score': 79.6, 'change_pct': 1.9, 'turnover_rate': 2.7, 'volume': 15000000, 'amount': 1500000000, 'latest_price': 45.23, 'source': 'fallback'},
            
            # 新能源板块
            {'code': '300750', 'name': '宁德时代', 'exchange': 'SZ', 'popularity_score': 95.8, 'change_pct': 6.1, 'turnover_rate': 7.2, 'volume': 90000000, 'amount': 9000000000, 'latest_price': 234.56, 'source': 'fallback'},
            {'code': '002594', 'name': '比亚迪', 'exchange': 'SZ', 'popularity_score': 93.7, 'change_pct': 5.2, 'turnover_rate': 6.3, 'volume': 80000000, 'amount': 8000000000, 'latest_price': 198.45, 'source': 'fallback'},
            {'code': '300274', 'name': '阳光电源', 'exchange': 'SZ', 'popularity_score': 89.2, 'change_pct': 4.8, 'turnover_rate': 5.9, 'volume': 45000000, 'amount': 4500000000, 'latest_price': 78.34, 'source': 'fallback'},
            {'code': '688599', 'name': '天合光能', 'exchange': 'SH', 'popularity_score': 87.5, 'change_pct': 4.2, 'turnover_rate': 5.1, 'volume': 38000000, 'amount': 3800000000, 'latest_price': 45.67, 'source': 'fallback'},
            {'code': '002460', 'name': '赣锋锂业', 'exchange': 'SZ', 'popularity_score': 85.3, 'change_pct': 3.7, 'turnover_rate': 4.8, 'volume': 42000000, 'amount': 4200000000, 'latest_price': 67.89, 'source': 'fallback'},
            
            # 科技板块
            {'code': '002415', 'name': '海康威视', 'exchange': 'SZ', 'popularity_score': 91.2, 'change_pct': 4.5, 'turnover_rate': 5.8, 'volume': 60000000, 'amount': 6000000000, 'latest_price': 28.67, 'source': 'fallback'},
            {'code': '300059', 'name': '东方财富', 'exchange': 'SZ', 'popularity_score': 87.4, 'change_pct': 2.8, 'turnover_rate': 4.2, 'volume': 55000000, 'amount': 5500000000, 'latest_price': 15.67, 'source': 'fallback'},
            {'code': '000725', 'name': '京东方A', 'exchange': 'SZ', 'popularity_score': 83.6, 'change_pct': 2.1, 'turnover_rate': 3.8, 'volume': 48000000, 'amount': 4800000000, 'latest_price': 4.23, 'source': 'fallback'},
            {'code': '002230', 'name': '科大讯飞', 'exchange': 'SZ', 'popularity_score': 88.9, 'change_pct': 3.9, 'turnover_rate': 4.7, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 56.78, 'source': 'fallback'},
            {'code': '688981', 'name': '中芯国际', 'exchange': 'SH', 'popularity_score': 86.1, 'change_pct': 3.2, 'turnover_rate': 4.5, 'volume': 40000000, 'amount': 4000000000, 'latest_price': 45.67, 'source': 'fallback'},
            
            # 医药板块
            {'code': '603259', 'name': '药明康德', 'exchange': 'SH', 'popularity_score': 92.1, 'change_pct': 5.6, 'turnover_rate': 6.1, 'volume': 38000000, 'amount': 3800000000, 'latest_price': 67.89, 'source': 'fallback'},
            {'code': '000661', 'name': '长春高新', 'exchange': 'SZ', 'popularity_score': 84.7, 'change_pct': 2.9, 'turnover_rate': 3.6, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 89.12, 'source': 'fallback'},
            {'code': '300015', 'name': '爱尔眼科', 'exchange': 'SZ', 'popularity_score': 81.3, 'change_pct': 1.8, 'turnover_rate': 2.9, 'volume': 22000000, 'amount': 2200000000, 'latest_price': 34.56, 'source': 'fallback'},
            {'code': '600276', 'name': '恒瑞医药', 'exchange': 'SH', 'popularity_score': 79.8, 'change_pct': 1.5, 'turnover_rate': 2.7, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 45.23, 'source': 'fallback'},
            {'code': '300760', 'name': '迈瑞医疗', 'exchange': 'SZ', 'popularity_score': 87.2, 'change_pct': 3.4, 'turnover_rate': 4.2, 'volume': 32000000, 'amount': 3200000000, 'latest_price': 234.56, 'source': 'fallback'},
            
            # 消费板块
            {'code': '600887', 'name': '伊利股份', 'exchange': 'SH', 'popularity_score': 81.7, 'change_pct': 1.5, 'turnover_rate': 2.3, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 28.45, 'source': 'fallback'},
            {'code': '000876', 'name': '新希望', 'exchange': 'SZ', 'popularity_score': 79.3, 'change_pct': -1.2, 'turnover_rate': 2.5, 'volume': 30000000, 'amount': 3000000000, 'latest_price': 12.34, 'source': 'fallback'},
            {'code': '000858', 'name': '五粮液', 'exchange': 'SZ', 'popularity_score': 88.9, 'change_pct': 3.2, 'turnover_rate': 4.1, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 156.78, 'source': 'fallback'},
            {'code': '600519', 'name': '贵州茅台', 'exchange': 'SH', 'popularity_score': 96.3, 'change_pct': 3.8, 'turnover_rate': 2.9, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 1688.88, 'source': 'fallback'},
            {'code': '000002', 'name': '万科A', 'exchange': 'SZ', 'popularity_score': 82.1, 'change_pct': 1.8, 'turnover_rate': 2.8, 'volume': 45000000, 'amount': 4500000000, 'latest_price': 8.95, 'source': 'fallback'},
            
            # 保险板块
            {'code': '601318', 'name': '中国平安', 'exchange': 'SH', 'popularity_score': 83.9, 'change_pct': 2.1, 'turnover_rate': 3.4, 'volume': 48000000, 'amount': 4800000000, 'latest_price': 45.67, 'source': 'fallback'},
            {'code': '601601', 'name': '中国太保', 'exchange': 'SH', 'popularity_score': 78.6, 'change_pct': 1.2, 'turnover_rate': 2.1, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 23.45, 'source': 'fallback'},
            {'code': '601628', 'name': '中国人寿', 'exchange': 'SH', 'popularity_score': 76.4, 'change_pct': 0.9, 'turnover_rate': 1.8, 'volume': 22000000, 'amount': 2200000000, 'latest_price': 18.67, 'source': 'fallback'},
            {'code': '601336', 'name': '新华保险', 'exchange': 'SH', 'popularity_score': 74.8, 'change_pct': 0.7, 'turnover_rate': 1.6, 'volume': 18000000, 'amount': 1800000000, 'latest_price': 15.23, 'source': 'fallback'},
            {'code': '601319', 'name': '中国人保', 'exchange': 'SH', 'popularity_score': 73.2, 'change_pct': 0.5, 'turnover_rate': 1.4, 'volume': 15000000, 'amount': 1500000000, 'latest_price': 12.89, 'source': 'fallback'},
            
            # 房地产板块
            {'code': '000002', 'name': '万科A', 'exchange': 'SZ', 'popularity_score': 82.1, 'change_pct': 1.8, 'turnover_rate': 2.8, 'volume': 45000000, 'amount': 4500000000, 'latest_price': 8.95, 'source': 'fallback'},
            {'code': '600048', 'name': '保利发展', 'exchange': 'SH', 'popularity_score': 79.5, 'change_pct': 1.5, 'turnover_rate': 2.3, 'volume': 38000000, 'amount': 3800000000, 'latest_price': 12.34, 'source': 'fallback'},
            {'code': '001979', 'name': '招商蛇口', 'exchange': 'SZ', 'popularity_score': 77.8, 'change_pct': 1.2, 'turnover_rate': 2.1, 'volume': 32000000, 'amount': 3200000000, 'latest_price': 9.67, 'source': 'fallback'},
            {'code': '600606', 'name': '绿地控股', 'exchange': 'SH', 'popularity_score': 75.6, 'change_pct': 0.8, 'turnover_rate': 1.9, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 3.45, 'source': 'fallback'},
            {'code': '000069', 'name': '华侨城A', 'exchange': 'SZ', 'popularity_score': 73.4, 'change_pct': 0.6, 'turnover_rate': 1.7, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 6.78, 'source': 'fallback'},
            
            # 钢铁板块
            {'code': '000717', 'name': '韶钢松山', 'exchange': 'SZ', 'popularity_score': 76.8, 'change_pct': 1.4, 'turnover_rate': 2.2, 'volume': 30000000, 'amount': 3000000000, 'latest_price': 4.56, 'source': 'fallback'},
            {'code': '600019', 'name': '宝钢股份', 'exchange': 'SH', 'popularity_score': 74.2, 'change_pct': 1.1, 'turnover_rate': 1.9, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 5.67, 'source': 'fallback'},
            {'code': '000825', 'name': '太钢不锈', 'exchange': 'SZ', 'popularity_score': 72.6, 'change_pct': 0.9, 'turnover_rate': 1.7, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 3.89, 'source': 'fallback'},
            {'code': '600010', 'name': '包钢股份', 'exchange': 'SH', 'popularity_score': 70.8, 'change_pct': 0.7, 'turnover_rate': 1.5, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 2.34, 'source': 'fallback'},
            {'code': '000708', 'name': '中信特钢', 'exchange': 'SZ', 'popularity_score': 69.4, 'change_pct': 0.5, 'turnover_rate': 1.3, 'volume': 22000000, 'amount': 2200000000, 'latest_price': 18.45, 'source': 'fallback'},
            
            # 有色金属板块
            {'code': '600362', 'name': '江西铜业', 'exchange': 'SH', 'popularity_score': 78.9, 'change_pct': 2.3, 'turnover_rate': 3.1, 'volume': 40000000, 'amount': 4000000000, 'latest_price': 23.45, 'source': 'fallback'},
            {'code': '000630', 'name': '铜陵有色', 'exchange': 'SZ', 'popularity_score': 76.5, 'change_pct': 2.1, 'turnover_rate': 2.8, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 4.67, 'source': 'fallback'},
            {'code': '600219', 'name': '南山铝业', 'exchange': 'SH', 'popularity_score': 74.8, 'change_pct': 1.8, 'turnover_rate': 2.5, 'volume': 32000000, 'amount': 3200000000, 'latest_price': 3.89, 'source': 'fallback'},
            {'code': '000831', 'name': '五矿稀土', 'exchange': 'SZ', 'popularity_score': 72.6, 'change_pct': 1.5, 'turnover_rate': 2.2, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 15.67, 'source': 'fallback'},
            {'code': '600111', 'name': '北方稀土', 'exchange': 'SH', 'popularity_score': 70.4, 'change_pct': 1.2, 'turnover_rate': 1.9, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 12.34, 'source': 'fallback'},
            
            # 化工板块
            {'code': '600309', 'name': '万华化学', 'exchange': 'SH', 'popularity_score': 85.6, 'change_pct': 3.2, 'turnover_rate': 4.1, 'volume': 45000000, 'amount': 4500000000, 'latest_price': 78.45, 'source': 'fallback'},
            {'code': '000792', 'name': '盐湖股份', 'exchange': 'SZ', 'popularity_score': 82.3, 'change_pct': 2.8, 'turnover_rate': 3.6, 'volume': 38000000, 'amount': 3800000000, 'latest_price': 23.67, 'source': 'fallback'},
            {'code': '600346', 'name': '恒力石化', 'exchange': 'SH', 'popularity_score': 79.8, 'change_pct': 2.4, 'turnover_rate': 3.2, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 15.89, 'source': 'fallback'},
            {'code': '002493', 'name': '荣盛石化', 'exchange': 'SZ', 'popularity_score': 77.4, 'change_pct': 2.1, 'turnover_rate': 2.9, 'volume': 32000000, 'amount': 3200000000, 'latest_price': 12.45, 'source': 'fallback'},
            {'code': '600426', 'name': '华鲁恒升', 'exchange': 'SH', 'popularity_score': 75.6, 'change_pct': 1.8, 'turnover_rate': 2.6, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 28.67, 'source': 'fallback'},
            
            # 电力板块
            {'code': '600900', 'name': '长江电力', 'exchange': 'SH', 'popularity_score': 81.2, 'change_pct': 1.9, 'turnover_rate': 2.8, 'volume': 40000000, 'amount': 4000000000, 'latest_price': 23.45, 'source': 'fallback'},
            {'code': '000027', 'name': '深圳能源', 'exchange': 'SZ', 'popularity_score': 78.6, 'change_pct': 1.6, 'turnover_rate': 2.4, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 6.78, 'source': 'fallback'},
            {'code': '600886', 'name': '国投电力', 'exchange': 'SH', 'popularity_score': 76.3, 'change_pct': 1.3, 'turnover_rate': 2.1, 'volume': 32000000, 'amount': 3200000000, 'latest_price': 12.34, 'source': 'fallback'},
            {'code': '000690', 'name': '宝新能源', 'exchange': 'SZ', 'popularity_score': 74.8, 'change_pct': 1.1, 'turnover_rate': 1.9, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 5.67, 'source': 'fallback'},
            {'code': '600027', 'name': '华电国际', 'exchange': 'SH', 'popularity_score': 73.2, 'change_pct': 0.9, 'turnover_rate': 1.7, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 4.56, 'source': 'fallback'},
            
            # 交通运输板块
            {'code': '601111', 'name': '中国国航', 'exchange': 'SH', 'popularity_score': 79.4, 'change_pct': 2.1, 'turnover_rate': 3.2, 'volume': 38000000, 'amount': 3800000000, 'latest_price': 8.45, 'source': 'fallback'},
            {'code': '600115', 'name': '东方航空', 'exchange': 'SH', 'popularity_score': 77.8, 'change_pct': 1.8, 'turnover_rate': 2.9, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 5.67, 'source': 'fallback'},
            {'code': '000089', 'name': '深圳机场', 'exchange': 'SZ', 'popularity_score': 75.6, 'change_pct': 1.5, 'turnover_rate': 2.6, 'volume': 32000000, 'amount': 3200000000, 'latest_price': 7.89, 'source': 'fallback'},
            {'code': '600029', 'name': '南方航空', 'exchange': 'SH', 'popularity_score': 73.4, 'change_pct': 1.2, 'turnover_rate': 2.3, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 6.23, 'source': 'fallback'},
            {'code': '601006', 'name': '大秦铁路', 'exchange': 'SH', 'popularity_score': 71.8, 'change_pct': 1.0, 'turnover_rate': 2.1, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 7.45, 'source': 'fallback'},
            
            # 军工板块
            {'code': '000768', 'name': '中航飞机', 'exchange': 'SZ', 'popularity_score': 83.7, 'change_pct': 2.8, 'turnover_rate': 3.9, 'volume': 42000000, 'amount': 4200000000, 'latest_price': 18.67, 'source': 'fallback'},
            {'code': '600893', 'name': '航发动力', 'exchange': 'SH', 'popularity_score': 81.4, 'change_pct': 2.5, 'turnover_rate': 3.6, 'volume': 38000000, 'amount': 3800000000, 'latest_price': 23.45, 'source': 'fallback'},
            {'code': '002179', 'name': '中航光电', 'exchange': 'SZ', 'popularity_score': 79.2, 'change_pct': 2.2, 'turnover_rate': 3.3, 'volume': 35000000, 'amount': 3500000000, 'latest_price': 45.67, 'source': 'fallback'},
            {'code': '600372', 'name': '中航电子', 'exchange': 'SH', 'popularity_score': 77.6, 'change_pct': 1.9, 'turnover_rate': 3.0, 'volume': 32000000, 'amount': 3200000000, 'latest_price': 12.34, 'source': 'fallback'},
            {'code': '000547', 'name': '航天发展', 'exchange': 'SZ', 'popularity_score': 75.8, 'change_pct': 1.6, 'turnover_rate': 2.7, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 8.45, 'source': 'fallback'},
            
            # 农业板块
            {'code': '000876', 'name': '新希望', 'exchange': 'SZ', 'popularity_score': 79.3, 'change_pct': -1.2, 'turnover_rate': 2.5, 'volume': 30000000, 'amount': 3000000000, 'latest_price': 12.34, 'source': 'fallback'},
            {'code': '002714', 'name': '牧原股份', 'exchange': 'SZ', 'popularity_score': 76.8, 'change_pct': -0.8, 'turnover_rate': 2.2, 'volume': 28000000, 'amount': 2800000000, 'latest_price': 45.67, 'source': 'fallback'},
            {'code': '300498', 'name': '温氏股份', 'exchange': 'SZ', 'popularity_score': 74.5, 'change_pct': -0.5, 'turnover_rate': 1.9, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 18.23, 'source': 'fallback'},
            {'code': '600598', 'name': '北大荒', 'exchange': 'SH', 'popularity_score': 72.3, 'change_pct': -0.3, 'turnover_rate': 1.7, 'volume': 22000000, 'amount': 2200000000, 'latest_price': 12.45, 'source': 'fallback'},
            {'code': '000998', 'name': '隆平高科', 'exchange': 'SZ', 'popularity_score': 70.6, 'change_pct': -0.1, 'turnover_rate': 1.5, 'volume': 20000000, 'amount': 2000000000, 'latest_price': 15.67, 'source': 'fallback'},
            
            # 旅游板块
            {'code': '601888', 'name': '中国中免', 'exchange': 'SH', 'popularity_score': 89.4, 'change_pct': 4.2, 'turnover_rate': 4.8, 'volume': 42000000, 'amount': 4200000000, 'latest_price': 89.12, 'source': 'fallback'},
            {'code': '000069', 'name': '华侨城A', 'exchange': 'SZ', 'popularity_score': 73.4, 'change_pct': 0.6, 'turnover_rate': 1.7, 'volume': 25000000, 'amount': 2500000000, 'latest_price': 6.78, 'source': 'fallback'},
            {'code': '600138', 'name': '中青旅', 'exchange': 'SH', 'popularity_score': 71.8, 'change_pct': 0.4, 'turnover_rate': 1.5, 'volume': 22000000, 'amount': 2200000000, 'latest_price': 12.34, 'source': 'fallback'},
            {'code': '000428', 'name': '华天酒店', 'exchange': 'SZ', 'popularity_score': 69.6, 'change_pct': 0.2, 'turnover_rate': 1.3, 'volume': 18000000, 'amount': 1800000000, 'latest_price': 3.45, 'source': 'fallback'},
            {'code': '600258', 'name': '首旅酒店', 'exchange': 'SH', 'popularity_score': 67.8, 'change_pct': 0.1, 'turnover_rate': 1.1, 'volume': 15000000, 'amount': 1500000000, 'latest_price': 18.67, 'source': 'fallback'},
        ]
        
        # 返回指定数量的股票
        return fallback_stocks[:limit]

    def _load_cache(self) -> Optional[Dict]:
        """
        加载缓存数据

        Returns:
            缓存数据或None（如果缓存无效）
        """
        if not os.path.exists(self.cache_file):
            return None

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # 检查缓存是否过期
            cache_time = datetime.fromisoformat(cache_data['timestamp'])
            if datetime.now() - cache_time > timedelta(seconds=self.cache_ttl):
                logger.info("缓存已过期")
                return None

            return cache_data

        except Exception as e:
            logger.warning(f"加载缓存失败: {e}")
            return None

    def _save_cache(self, stocks: List[Dict]):
        """
        保存缓存数据（原子写入，避免文件损坏）

        Args:
            stocks: 股票列表
        """
        tmp_file = self.cache_file + ".tmp"
        try:
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'stocks': stocks
            }

            # 先写入临时文件并确保刷盘，再原子替换
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_file, self.cache_file)
            logger.info(f"缓存已保存: {self.cache_file}")

        except Exception as e:
            logger.warning(f"保存缓存失败: {e}")
            # 清理可能残留的临时文件
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except Exception:
                pass


def main():
    """测试热门股票获取器"""
    print("=" * 60)
    print("热门股票获取器 - 测试")
    print("=" * 60)

    fetcher = HotStocksFetcher()

    # 获取TOP 100热门股票
    hot_stocks = fetcher.get_hot_stocks(limit=100)

    if hot_stocks:
        print(f"\n✓ 成功获取 {len(hot_stocks)} 只热门股票\n")

        # 显示TOP 10
        print("TOP 10 热门股票:")
        print("-" * 100)
        print(f"{'排名':<6} {'代码':<10} {'名称':<15} {'交易所':<8} {'热度':<8} {'涨跌幅%':<10} {'换手率%':<10} {'成交额(亿)':<15}")
        print("-" * 100)

        for i, stock in enumerate(hot_stocks[:10], 1):
            amount_yi = stock['amount'] / 1e8  # 转换为亿
            print(f"{i:<6} {stock['code']:<10} {stock['name']:<15} {stock['exchange']:<8} "
                  f"{stock['popularity_score']:<8.2f} {stock['change_pct']:<10.2f} "
                  f"{stock['turnover_rate']:<10.2f} {amount_yi:<15.2f}")

        # 保存到CSV
        df = pd.DataFrame(hot_stocks)

        # 添加格式化的成交额（亿）字段，便于阅读
        df['amount_yi'] = df['amount'].apply(lambda x: round(x / 1e8, 2) if x > 0 else 0)

        # 调整列顺序，将amount_yi放在amount之后
        cols = list(df.columns)
        if 'amount_yi' in cols and 'amount' in cols:
            amount_idx = cols.index('amount')
            cols.remove('amount_yi')
            cols.insert(amount_idx + 1, 'amount_yi')
            df = df[cols]

        output_file = "data/hot_stocks_top100.csv"
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n✓ 数据已保存到: {output_file}")
    else:
        print("\n✗ 获取失败")


if __name__ == "__main__":
    main()
