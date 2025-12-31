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
    """热门股票获取器 - 从多个数据源获取市场热度TOP股票 (v4.0 游资思维优化版)"""

    def __init__(self, cache_dir: str = None, disable_cache: bool = None):
        """
        初始化热门股票获取器

        Args:
            cache_dir: 缓存目录路径（可选）。
                      若未提供，将优先使用环境变量 KRONOS_DATA_DIR 下的 cache 目录，
                      否则回退到项目相对路径 data/cache。
            disable_cache: 是否禁用缓存（可选）。
                      若未提供，将读取环境变量 KRONOS_DISABLE_HOT_CACHE 为 '1'/'true' 视为禁用。

        Note:
            v4.0版本移除了 allow_fallback 参数和静态备用数据源。
            游资思维：宁可不分析，也不能用过时数据误导决策。
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

        # 缓存禁用开关（环境变量优先）
        if disable_cache is None:
            env_disable = os.environ.get("KRONOS_DISABLE_HOT_CACHE", "0").strip().lower()
            disable_cache = env_disable in {"1", "true", "yes"}
        self.disable_cache = bool(disable_cache)

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
        
        # 【优化5】数据源健康状态缓存（避免重复检查）
        self._source_health_cache = {}
        self._health_check_timeout = 3  # 健康检查超时时间（秒）

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
        cached_data = None if (force_refresh or env_force or self.disable_cache) else self._load_cache()
        if cached_data:
            stocks_from_cache = cached_data.get('stocks') or []
            # 若缓存来源为本地回退或未知来源，则忽略缓存
            valid_sources = {'eastmoney', 'eastmoney_vip', 'eastmoney_alt', 'tonghuashun', 'xueqiu', 'tushare'}
            all_sources = {str(s.get('source') or '').lower() for s in stocks_from_cache}
            if all_sources and all_sources.issubset(valid_sources) and 'fallback' not in all_sources:
                logger.info(f"使用缓存数据（缓存时间: {cached_data['timestamp']}）")
                return stocks_from_cache[:limit]
            else:
                logger.info("检测到缓存来源非直接采集（可能为fallback/未知），忽略缓存，改为直接采集")

        stocks = []

        # 【优化5】数据源健康检查：优先使用健康的数据源
        logger.info("正在检查数据源健康状态...")
        source_health = self._check_data_source_health()
        healthy_sources = [name for name, status in source_health.items() if status.get('healthy', False)]
        if healthy_sources:
            logger.info(f"✓ 发现 {len(healthy_sources)} 个健康数据源: {', '.join(healthy_sources)}")
        else:
            logger.warning("⚠️ 所有数据源健康检查失败，将尝试所有数据源")

        try:
            logger.info("尝试东方财富股吧人气榜(优先)...")
            guba_stocks = self._fetch_from_guba_rank(limit=limit)
            if guba_stocks:
                stocks = guba_stocks
                logger.info(f"✓ 东方财富股吧人气榜获取成功: {len(guba_stocks)} 只股票")
        except Exception as e:
            logger.warning(f"东方财富股吧人气榜获取失败: {e}")

        if not stocks:
            try:
                logger.info("尝试东方财富VIP接口...")
                vip_stocks = self._fetch_from_eastmoney_vip(limit=limit)
                if vip_stocks:
                    stocks = vip_stocks
                    logger.info(f"✓ 东方财富VIP获取成功: {len(vip_stocks)} 只股票")
            except Exception as e:
                logger.warning(f"东方财富VIP获取失败: {e}")

        if not stocks:
            try:
                logger.info("正在从同花顺获取热度榜...")
                tonghuashun_stocks = self._fetch_from_tonghuashun(limit=limit)
                if tonghuashun_stocks:
                    stocks = tonghuashun_stocks[:limit]
                    logger.info(f"✓ 同花顺获取成功: {len(tonghuashun_stocks)} 只股票")
            except Exception as e:
                logger.warning(f"同花顺获取失败: {e}")

        if not stocks:
            try:
                logger.info("尝试东方财富增强热榜接口（支持>100只股票）...")
                enhanced_stocks = self._fetch_from_eastmoney_enhanced(limit=limit)
                if enhanced_stocks:
                    stocks = enhanced_stocks
                    logger.info(f"✓ 东方财富增强热榜获取成功: {len(enhanced_stocks)} 只股票")
            except Exception as e:
                logger.warning(f"东方财富增强热榜获取失败: {e}")

        if not stocks:
            try:
                logger.info("正在从东方财富API接口获取热度榜(备用)...")
                eastmoney_stocks = self._fetch_from_eastmoney(limit=limit)
                if eastmoney_stocks:
                    stocks = eastmoney_stocks
                    logger.info(f"✓ 东方财富API获取成功: {len(eastmoney_stocks)} 只股票")
            except Exception as e:
                logger.warning(f"东方财富API获取失败: {e}")

        if not stocks:
            try:
                logger.info("尝试东方财富备用入口...")
                alt_stocks = self._fetch_from_eastmoney_alt(limit=limit)
                if alt_stocks:
                    stocks = alt_stocks
                    logger.info(f"✓ 东方财富备用入口获取成功: {len(alt_stocks)} 只股票")
            except Exception as e:
                logger.warning(f"东方财富备用入口获取失败: {e}")

        if not stocks:
            # v4.0: 移除fallback备用数据源，确保只使用实时数据
            # 游资思维：宁可不分析，也不能用过时数据误导决策
            logger.error("所有实时数据源均获取失败，返回空列表（已禁用静态备用数据）")
            logger.error("请检查网络连接或稍后重试")
            return []

        # 批量补充基本面数据 (PE, PB, 市值等)
        if stocks:
            # 检查是否已包含基本面数据（新版API直接获取）
            has_fundamental = False
            if len(stocks) > 0:
                first_stock = stocks[0]
                if 'pe_ratio' in first_stock and 'pb_ratio' in first_stock and 'total_market_cap' in first_stock:
                    has_fundamental = True
            
            if not has_fundamental:
                try:
                    logger.info("正在批量补充基本面数据(PE/PB)...")
                    stocks_with_fund = self._batch_enrich_fundamental_data(stocks[:limit])
                    if stocks_with_fund:
                        stocks = stocks_with_fund
                        logger.info(f"✓ 基本面数据补充完成")
                except Exception as e:
                    logger.warning(f"批量补充基本面数据失败: {e}，后续将使用单独查询")
            else:
                logger.info("✓ 已在列表接口中直接获取基本面数据，跳过批量补充步骤")

        # 缓存数据（仅在未禁用且来源有效时写入，排除fallback来源）
        try:
            valid_sources = {'eastmoney', 'eastmoney_vip', 'eastmoney_alt', 'tonghuashun', 'xueqiu', 'tushare'}
            sources = {str(s.get('source') or '').lower() for s in stocks}
            # 明确排除fallback来源的数据写入缓存
            should_cache = (not self.disable_cache) and sources and sources.issubset(valid_sources) and 'fallback' not in sources
            if should_cache:
                self._save_cache(stocks)
            else:
                logger.info("跳过缓存写入（禁用缓存或来源为fallback/未知）")
        except Exception:
            # 严格避免因缓存失败影响主流程
            pass

        logger.info(f"✓ 热门股票获取完成: {len(stocks)} 只股票")
        return stocks[:limit]

    def _batch_enrich_fundamental_data(self, stocks: List[Dict]) -> List[Dict]:
        """
        批量补充基本面数据 (PE, PB, 市值)
        使用东方财富 ulist.np 接口批量获取
        """
        if not stocks:
            return stocks

        # 提取 secids
        # 东方财富 secid 格式: 1.600xxx (沪), 0.000xxx (深/创业), 0.300xxx (创业), 1.688xxx (科创)
        # 简单规则: 6开头是1., 其他是0.
        secids = []
        code_map = {} # code -> stock_dict
        
        for stock in stocks:
            code = stock.get('code')
            if not code:
                continue
            market_prefix = '1' if str(code).startswith('6') else '0'
            secid = f"{market_prefix}.{code}"
            secids.append(secid)
            code_map[code] = stock
            
        if not secids:
            return stocks

        # 东方财富接口一次最多支持约100个，安全起见分批处理
        # 降低 batch_size 以提高稳定性
        batch_size = 50
        
        for i in range(0, len(secids), batch_size):
            batch_secids = secids[i:i+batch_size]
            secids_str = ",".join(batch_secids)
            
            # 重试机制
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # 使用 https
                    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
                    # f12: code, f14: name, f9: PE(动态), f23: PB, f20: 总市值, f21: 流通市值, f183: 营收同比, f184: 净利同比
                    # f5: 成交量, f6: 成交额, f8: 换手率 (用于补全某些源缺失的行情数据)
                    params = {
                        'fltt': '2',
                        'secids': secids_str,
                        'fields': 'f12,f9,f23,f20,f21,f183,f184,f5,f6,f8' 
                    }
                    
                    response = requests.get(url, params=params, headers=self.headers, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if data and data.get('data') and data['data'].get('diff'):
                            for item in data['data']['diff']:
                                code = item.get('f12')
                                if code in code_map:
                                    stock = code_map[code]
                                    
                                    # 补全行情数据 (如果缺失或为0)
                                    if not stock.get('amount'):
                                        stock['amount'] = float(item.get('f6', 0) or 0)
                                    if not stock.get('volume'):
                                        stock['volume'] = int(float(item.get('f5', 0) or 0))
                                    if not stock.get('turnover_rate'):
                                        stock['turnover_rate'] = float(item.get('f8', 0) or 0)

                                    # PE (动态)
                                    pe = item.get('f9')
                                    if isinstance(pe, (int, float)):
                                        stock['pe_ratio'] = round(float(pe), 2) if pe > 0 else '亏损' if pe < 0 else 'N/A'
                                    else:
                                        stock['pe_ratio'] = 'N/A'
                                        
                                    # PB
                                    pb = item.get('f23')
                                    if isinstance(pb, (int, float)):
                                        stock['pb_ratio'] = round(float(pb), 2)
                                    else:
                                        stock['pb_ratio'] = 'N/A'
                                        
                                    # 总市值 (转为亿)
                                    tmc = item.get('f20')
                                    if isinstance(tmc, (int, float)):
                                        stock['total_market_cap'] = round(tmc / 100000000, 2)
                                    else:
                                        stock['total_market_cap'] = 'N/A'
                                        
                                    # 流通市值 (转为亿)
                                    cmc = item.get('f21')
                                    if isinstance(cmc, (int, float)):
                                        stock['circulation_market_cap'] = round(cmc / 100000000, 2)
                                    else:
                                        stock['circulation_market_cap'] = 'N/A'
                                        
                                    # 营收同比
                                    rev = item.get('f183')
                                    if isinstance(rev, (int, float)):
                                        stock['revenue_yoy'] = round(float(rev), 2)
                                    else:
                                        stock['revenue_yoy'] = 'N/A'
                                        
                                    # 净利同比
                                    profit = item.get('f184')
                                    if isinstance(profit, (int, float)):
                                        stock['net_profit_yoy'] = round(float(profit), 2)
                                    else:
                                        stock['net_profit_yoy'] = 'N/A'
                        # 成功后跳出重试循环
                        break
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.warning(f"批量获取基本面数据批次 {i} 失败(重试耗尽): {e}")
                    else:
                        time.sleep(1) # 稍作等待后重试
                
        return stocks
    

    def _fetch_from_eastmoney(self, limit: int = 100) -> List[Dict]:
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
            current_field_stocks = []
            page = 1
            page_size = 100 # 东方财富API通常每页最多100条
            
            try:
                while len(current_field_stocks) < limit:
                    popularity_params = {
                        'pn': str(page),
                        'pz': str(page_size),
                        'po': '1',
                        'np': '1',
                        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                        'fltt': '2',
                        'invt': '2',
                        'fid': field_id,  # 热度排序字段
                        'fs': 'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23',  # A股市场（主板+创业板+科创板）
                        'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f11,f62,f128,f136,f115,f152,f164,f183,f184',
                        '_': str(int(time.time() * 1000))
                    }

                    logger.info(f"尝试获取热榜（按{field_name}排序, 第{page}页）...")
                    response = requests.get(popularity_url, params=popularity_params, headers=self.headers, timeout=10)
                    response.raise_for_status()
                    data = response.json()

                    if not (data.get('data') and data['data'].get('diff') and len(data['data']['diff']) > 0):
                        if page == 1:
                            logger.warning(f"热榜API第{page}页无数据")
                        break

                    items = data['data']['diff']
                    logger.info(f"✓ 热榜API第{page}页返回 {len(items)} 只股票")

                    for idx, item in enumerate(items, start=1):
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
                            def safe_float(val, default=0.0):
                                try:
                                    if val == '-' or val is None:
                                        return default
                                    return float(val)
                                except (ValueError, TypeError):
                                    return default

                            change_pct = safe_float(item.get('f3'))  # 涨跌幅
                            turnover_rate = safe_float(item.get('f8'))  # 换手率
                            volume = safe_float(item.get('f5'))  # 成交量（手）
                            amount = safe_float(item.get('f6'))  # 成交额（元）
                            main_fund_flow = safe_float(item.get('f62'))  # 主力资金净流入
                            heat_index = safe_float(item.get('f164'))  # 热度指数

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
                                'latest_price': safe_float(item.get('f2')),  # 最新价
                                'source': 'eastmoney',
                                'rank': len(current_field_stocks) + 1
                            }

                            # 提取基本面数据
                            # PE (动态)
                            pe = item.get('f9')
                            if isinstance(pe, (int, float)):
                                stock_info['pe_ratio'] = round(float(pe), 2) if pe > 0 else '亏损' if pe < 0 else 'N/A'
                            else:
                                stock_info['pe_ratio'] = 'N/A'
                                
                            # PB
                            pb = item.get('f23')
                            if isinstance(pb, (int, float)):
                                stock_info['pb_ratio'] = round(float(pb), 2)
                            else:
                                stock_info['pb_ratio'] = 'N/A'
                                
                            # 总市值 (转为亿)
                            tmc = item.get('f20')
                            if isinstance(tmc, (int, float)):
                                stock_info['total_market_cap'] = round(tmc / 100000000, 2)
                            else:
                                stock_info['total_market_cap'] = 'N/A'
                                
                            # 流通市值 (转为亿)
                            cmc = item.get('f21')
                            if isinstance(cmc, (int, float)):
                                stock_info['circulation_market_cap'] = round(cmc / 100000000, 2)
                            else:
                                stock_info['circulation_market_cap'] = 'N/A'
                            
                            # 营收同比
                            rev = item.get('f183')
                            if isinstance(rev, (int, float)):
                                stock_info['revenue_yoy'] = round(float(rev), 2)
                            else:
                                stock_info['revenue_yoy'] = 'N/A'
                                
                            # 净利同比
                            profit = item.get('f184')
                            if isinstance(profit, (int, float)):
                                stock_info['net_profit_yoy'] = round(float(profit), 2)
                            else:
                                stock_info['net_profit_yoy'] = 'N/A'

                            current_field_stocks.append(stock_info)
                        except Exception as e:
                            logger.warning(f"解析股票信息失败: {e}, 数据: {item}")
                            continue

                    # Check if we have enough stocks or if the page returned less than page_size (meaning last page)
                    if len(current_field_stocks) >= limit:
                        break
                    
                    if len(items) < page_size:
                        break
                        
                    page += 1

                if current_field_stocks:
                    return current_field_stocks[:limit]

            except Exception as e:
                logger.warning(f"使用{field_name}获取失败: {e}，尝试下一个字段...")
                continue

        # 如果所有方案都失败
        if not stocks:
            logger.error("所有热榜API方案均失败")
            raise Exception("无法获取东方财富热榜数据")

        return stocks

    def _fetch_from_guba_rank(self, limit: int = 100) -> List[Dict]:
        """
        从东方财富股吧人气榜获取热门股票 (作为备用/第二通道)
        URL: https://guba.eastmoney.com/rank/
        API: https://emappdata.eastmoney.com/stockrank/getAllCurrentList
        """
        logger.info("尝试从股吧人气榜API获取...")
        stocks = []
        try:
            url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
            payload = {
                "appId": "appId01",
                "globalId": "786e4c21-70dc-435a-93bb-38",
                "marketType": "",
                "pageNo": 1,
                "pageSize": limit
            }
            headers = {
                "User-Agent": self.headers['User-Agent'],
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://guba.eastmoney.com",
                "Referer": "https://guba.eastmoney.com/rank/"
            }

            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.warning(f"股吧人气榜API请求失败: {response.status_code}")
                return []

            data = response.json()
            if not data.get('data'):
                logger.warning("股吧人气榜API返回数据为空")
                return []

            # 解析排名数据
            rank_items = data['data']
            secids = []
            rank_map = {}  # code -> rank_item

            for item in rank_items:
                sc = item.get('sc', '')  # e.g. SZ000063
                if not sc or len(sc) < 3:
                    continue
                
                # 解析市场和代码
                market_str = sc[:2].upper()
                code = sc[2:]
                
                market_id = '1' if market_str == 'SH' else '0'
                secid = f"{market_id}.{code}"
                
                secids.append(secid)
                rank_map[code] = {
                    'rank': item.get('rk'),
                    'code': code,
                    'exchange': market_str
                }

            if not secids:
                return []

            # 批量获取详细行情数据
            logger.info(f"从股吧人气榜获取到 {len(secids)} 个代码，正在批量查询详情...")
            
            # 分批查询，每批50个
            batch_size = 50
            for i in range(0, len(secids), batch_size):
                batch_secids = secids[i:i+batch_size]
                secids_str = ",".join(batch_secids)
                
                try:
                    details_url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
                    # f12: code, f14: name, f2: price, f3: change_pct, f5: volume, f6: amount, f8: turnover
                    # f9: PE, f23: PB, f20: total_cap, f21: circ_cap, f183: rev_yoy, f184: profit_yoy
                    params = {
                        'fltt': '2',
                        'secids': secids_str,
                        'fields': 'f12,f14,f2,f3,f5,f6,f8,f9,f23,f20,f21,f183,f184,f13'
                    }
                    
                    resp = requests.get(details_url, params=params, headers=self.headers, timeout=10)
                    if resp.status_code == 200:
                        det_data = resp.json()
                        if det_data and det_data.get('data') and det_data['data'].get('diff'):
                            for det in det_data['data']['diff']:
                                code = det.get('f12')
                                if code in rank_map:
                                    rk_info = rank_map[code]
                                    
                                    # 辅助函数
                                    def safe_float(val, default=0.0):
                                        try:
                                            if val == '-' or val is None:
                                                return default
                                            return float(val)
                                        except (ValueError, TypeError):
                                            return default

                                    stock_info = {
                                        'code': code,
                                        'name': det.get('f14', ''),
                                        'exchange': rk_info['exchange'],
                                        'rank': rk_info['rank'],
                                        'source': 'eastmoney_guba',
                                        'latest_price': safe_float(det.get('f2')),
                                        'change_pct': round(safe_float(det.get('f3')), 2),
                                        'turnover_rate': round(safe_float(det.get('f8')), 2),
                                        'volume': int(safe_float(det.get('f5'))),
                                        'amount': safe_float(det.get('f6')),
                                        # 简单的热度分转换：排名1->100分, 排名100->1分
                                        'popularity_score': max(0, 100 - rk_info['rank'] + 1)
                                    }
                                    
                                    # 基本面数据
                                    pe = det.get('f9')
                                    stock_info['pe_ratio'] = round(float(pe), 2) if isinstance(pe, (int, float)) and pe > 0 else 'N/A'
                                    
                                    pb = det.get('f23')
                                    stock_info['pb_ratio'] = round(float(pb), 2) if isinstance(pb, (int, float)) else 'N/A'
                                    
                                    tmc = det.get('f20')
                                    stock_info['total_market_cap'] = round(tmc / 100000000, 2) if isinstance(tmc, (int, float)) else 'N/A'
                                    
                                    cmc = det.get('f21')
                                    stock_info['circulation_market_cap'] = round(cmc / 100000000, 2) if isinstance(cmc, (int, float)) else 'N/A'
                                    
                                    rev = det.get('f183')
                                    stock_info['revenue_yoy'] = round(float(rev), 2) if isinstance(rev, (int, float)) else 'N/A'
                                    
                                    profit = det.get('f184')
                                    stock_info['net_profit_yoy'] = round(float(profit), 2) if isinstance(profit, (int, float)) else 'N/A'
                                    
                                    stocks.append(stock_info)
                                    
                except Exception as e:
                    logger.warning(f"获取详情批次失败: {e}")
            
            # 按排名排序
            stocks.sort(key=lambda x: x['rank'])
            return stocks[:limit]
            
        except Exception as e:
            logger.error(f"股吧人气榜获取异常: {e}")
            return []

    def _fetch_from_eastmoney_stockpicker(self, limit: int = 100) -> List[Dict]:
        """
        从东方财富选股器获取热门股票（基于股吧人气排名）
        URL: https://emrnweb.eastmoney.com/stockpicker/result
        可以获取前500名人气股票
        """
        logger.info(f"尝试从东方财富选股器获取前{limit}名人气股票...")
        stocks = []
        try:
            # 构造选股器接口URL
            # nF参数: [["005001",{"sdc":"005001004"}]] 表示股吧人气排名前500
            base_url = "https://emrnweb.eastmoney.com/stockpicker/result"
            params = {
                'nF': '[["005001",{"sdc":"005001004"}]]',  # 股吧人气排名前500
                'nN': '',
                'appfenxiang': '1'
            }
            
            headers = {
                **self.headers,
                'Referer': 'https://emrnweb.eastmoney.com/stockpicker/',
                'X-Requested-With': 'XMLHttpRequest'
            }
            
            response = requests.get(base_url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            
            # 解析返回的HTML内容
            html_content = response.text
            
            # 使用正则表达式提取股票数据
            import re
            
            # 匹配股票代码、名称和排名信息
            pattern = r'<tr[^>]*>.*?<td[^>]*>(\d+)</td>.*?<td[^>]*><a[^>]*>([\d\w]+)</a></td>.*?<td[^>]*><a[^>]*>([^<]+)</a></td>.*?<td[^>]*>([^<]*)</td>.*?</tr>'
            matches = re.findall(pattern, html_content, re.DOTALL)
            
            if not matches:
                # 尝试另一种匹配模式
                pattern2 = r'data-code="([\d\w]+)"[^>]*data-name="([^"]+)"[^>]*>.*?<td[^>]*>(\d+)</td>'
                matches2 = re.findall(pattern2, html_content, re.DOTALL)
                if matches2:
                    for code, name, rank in matches2[:limit]:
                        # 确定交易所
                        if code.startswith(('600', '601', '603', '605', '688')):
                            exchange = 'SH'
                        else:
                            exchange = 'SZ'
                            
                        stock_info = {
                            'code': code,
                            'name': name,
                            'exchange': exchange,
                            'rank': int(rank) if rank.isdigit() else 999,
                            'source': 'eastmoney_stockpicker',
                            'popularity_score': max(0, 100 - int(rank) + 1) if rank.isdigit() else 50
                        }
                        stocks.append(stock_info)
            else:
                # 使用第一种匹配结果
                for rank, code, name, _ in matches[:limit]:
                    # 确定交易所
                    if code.startswith(('600', '601', '603', '605', '688')):
                        exchange = 'SH'
                    else:
                        exchange = 'SZ'
                        
                    stock_info = {
                        'code': code,
                        'name': name,
                        'exchange': exchange,
                        'rank': int(rank) if rank.isdigit() else 999,
                        'source': 'eastmoney_stockpicker',
                        'popularity_score': max(0, 100 - int(rank) + 1) if rank.isdigit() else 50
                    }
                    stocks.append(stock_info)
            
            if stocks:
                logger.info(f"✓ 选股器接口获取成功: {len(stocks)} 只股票")
                
                # 补充基本面数据
                stock_codes = [s['code'] for s in stocks]
                self._supplement_fundamentals_batch(stock_codes, stocks)
                
                # 按排名排序
                stocks.sort(key=lambda x: x['rank'])
                return stocks[:limit]
                
        except Exception as e:
            logger.error(f"选股器接口获取失败: {e}")
            
        return []

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

    def _fetch_from_eastmoney_enhanced(self, limit: int = 100) -> List[Dict]:
        """
        增强版东方财富热榜获取（支持>100只股票）
        
        策略:
        1. 使用多个热度排序字段
        2. 支持分页获取
        3. 合并多个数据源
        """
        all_stocks = []
        
        # 多个热度排序字段，获取不同维度的热门股票
        heat_fields = [
            ('f164', '热度指数'),
            ('f62', '主力资金净流入'),
            ('f8', '换手率'),
            ('f6', '成交额'),
            ('f5', '成交量')
        ]
        
        logger.info(f"开始增强热榜获取，目标: {limit} 只股票")
        
        # 计算每个字段需要获取的数量（考虑去重，多获取一些）
        stocks_per_field = max(limit // len(heat_fields) + 50, 100)  # 每个字段至少获取100只，确保去重后有足够数量
        
        for field_id, field_name in heat_fields:
            # 如果已经获取足够的唯一股票，停止
            unique_stocks_so_far = len(set(s.get('code') for s in all_stocks))
            if unique_stocks_so_far >= limit:
                break
                
            field_stocks = []
            page = 1
            page_size = 100  # 每页最多100条
            
            try:
                # 为每个字段获取多页数据，直到达到目标数量
                while len(field_stocks) < stocks_per_field:
                    # 检查去重后的总数是否已足够
                    temp_all = all_stocks + field_stocks
                    unique_count = len(set(s.get('code') for s in temp_all))
                    if unique_count >= limit:
                        break
                        
                    popularity_params = {
                        'pn': str(page),
                        'pz': str(page_size),
                        'po': '1',
                        'np': '1',
                        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                        'fltt': '2',
                        'invt': '2',
                        'fid': field_id,
                        'fs': 'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23',
                        'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f11,f62,f128,f136,f115,f152,f164,f183,f184',
                        '_': str(int(time.time() * 1000))
                    }

                    logger.info(f"获取热榜（按{field_name}排序, 第{page}页）...")
                    response = requests.get(
                        "https://push2.eastmoney.com/api/qt/clist/get",
                        params=popularity_params,
                        headers=self.headers,
                        timeout=10
                    )
                    response.raise_for_status()
                    data = response.json()

                    if not (data.get('data') and data['data'].get('diff') and len(data['data']['diff']) > 0):
                        if page == 1:
                            logger.warning(f"热榜API（{field_name}）第{page}页无数据")
                        break

                    items = data['data']['diff']
                    logger.info(f"✓ 热榜API（{field_name}）第{page}页返回 {len(items)} 只股票")

                    # 解析股票数据
                    for item in items:
                        try:
                            code = item.get('f12', '')
                            name = item.get('f14', '')
                            market = item.get('f13', '')

                            if not code or not name:
                                continue

                            # 确定交易所
                            if market == '0':
                                exchange = 'SZ'
                            elif market == '1':
                                exchange = 'SH'
                            else:
                                if code.startswith(('000', '001', '002', '003', '300')):
                                    exchange = 'SZ'
                                elif code.startswith(('600', '601', '603', '605', '688', '689')):
                                    exchange = 'SH'
                                else:
                                    exchange = 'SZ'

                            # 获取各项指标
                            def safe_float(val, default=0.0):
                                try:
                                    if val == '-' or val is None:
                                        return default
                                    return float(val)
                                except (ValueError, TypeError):
                                    return default

                            change_pct = safe_float(item.get('f3'))
                            turnover_rate = safe_float(item.get('f8'))
                            volume = safe_float(item.get('f5'))
                            amount = safe_float(item.get('f6'))
                            main_fund_flow = safe_float(item.get('f62'))
                            heat_index = safe_float(item.get('f164'))

                            # 计算综合人气评分
                            if heat_index > 0:
                                popularity_score = min(100, heat_index)
                            else:
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
                                'volume': int(volume * 100),
                                'amount': round(amount, 2),
                                'latest_price': safe_float(item.get('f2')),
                                'source': 'eastmoney_enhanced',
                                'rank': len(field_stocks) + 1,
                                'sort_field': field_id,
                                'sort_field_name': field_name
                            }

                            # 提取基本面数据
                            self._extract_fundamental_data(item, stock_info)
                            
                            field_stocks.append(stock_info)
                            
                        except Exception as e:
                            logger.warning(f"解析股票信息失败: {e}, 数据: {item}")
                            continue

                    # 检查是否继续分页
                    if len(items) < page_size:
                        break
                    
                    page += 1
                    
                    # 动态限制页数：根据目标数量调整，确保能获取足够股票
                    max_pages = max(3, (limit // 100) + 1)  # 至少3页，根据目标数量动态调整
                    if page > max_pages:
                        break

                # 合并当前字段的股票到总列表
                all_stocks.extend(field_stocks)
                logger.info(f"✓ 字段 {field_name} 获取完成，共 {len(field_stocks)} 只股票")
                
            except Exception as e:
                logger.warning(f"字段 {field_name} 获取失败: {e}")
                continue

        # 去重并排序
        if all_stocks:
            unique_stocks = self._deduplicate_and_sort(all_stocks)
            logger.info(f"✓ 增强热榜获取完成，去重后共 {len(unique_stocks)} 只股票")
            
            # 如果去重后数量不足，尝试从其他字段获取更多数据
            if len(unique_stocks) < limit:
                logger.info(f"去重后仅 {len(unique_stocks)} 只股票，不足目标 {limit} 只，尝试获取更多...")
                existing_codes = set(s.get('code') for s in unique_stocks)
                
                # 继续从剩余字段获取，直到达到目标数量
                for field_id, field_name in heat_fields:
                    if len(unique_stocks) >= limit:
                        break
                    
                    field_stocks = []
                    page = 1
                    page_size = 100
                    
                    try:
                        while len(unique_stocks) < limit and page <= 5:  # 最多5页
                            popularity_params = {
                                'pn': str(page),
                                'pz': str(page_size),
                                'po': '1',
                                'np': '1',
                                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                                'fltt': '2',
                                'invt': '2',
                                'fid': field_id,
                                'fs': 'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23',
                                'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f11,f62,f128,f136,f115,f152,f164,f183,f184',
                                '_': str(int(time.time() * 1000))
                            }
                            
                            response = requests.get(
                                "https://push2.eastmoney.com/api/qt/clist/get",
                                params=popularity_params,
                                headers=self.headers,
                                timeout=10
                            )
                            response.raise_for_status()
                            data = response.json()
                            
                            if not (data.get('data') and data['data'].get('diff') and len(data['data']['diff']) > 0):
                                break
                            
                            items = data['data']['diff']
                            
                            # 解析并过滤已存在的股票
                            for item in items:
                                code = item.get('f12', '')
                                if code and code not in existing_codes:
                                    try:
                                        name = item.get('f14', '')
                                        market = item.get('f13', '')
                                        
                                        if not name:
                                            continue
                                        
                                        if market == '0':
                                            exchange = 'SZ'
                                        elif market == '1':
                                            exchange = 'SH'
                                        else:
                                            if code.startswith(('000', '001', '002', '003', '300')):
                                                exchange = 'SZ'
                                            elif code.startswith(('600', '601', '603', '605', '688', '689')):
                                                exchange = 'SH'
                                            else:
                                                exchange = 'SZ'
                                        
                                        def safe_float(val, default=0.0):
                                            try:
                                                if val == '-' or val is None:
                                                    return default
                                                return float(val)
                                            except (ValueError, TypeError):
                                                return default
                                        
                                        change_pct = safe_float(item.get('f3'))
                                        turnover_rate = safe_float(item.get('f8'))
                                        volume = safe_float(item.get('f5'))
                                        amount = safe_float(item.get('f6'))
                                        main_fund_flow = safe_float(item.get('f62'))
                                        heat_index = safe_float(item.get('f164'))
                                        
                                        if heat_index > 0:
                                            popularity_score = min(100, heat_index)
                                        else:
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
                                            'volume': int(volume * 100),
                                            'amount': round(amount, 2),
                                            'latest_price': safe_float(item.get('f2')),
                                            'source': 'eastmoney_enhanced',
                                            'rank': len(unique_stocks) + 1,
                                            'sort_field': field_id,
                                            'sort_field_name': field_name
                                        }
                                        
                                        self._extract_fundamental_data(item, stock_info)
                                        unique_stocks.append(stock_info)
                                        existing_codes.add(code)
                                        
                                        if len(unique_stocks) >= limit:
                                            break
                                    except Exception as e:
                                        logger.warning(f"补充获取股票信息失败: {e}")
                                        continue
                            
                            if len(items) < page_size or len(unique_stocks) >= limit:
                                break
                            
                            page += 1
                            time.sleep(0.2)  # 避免请求过快
                            
                    except Exception as e:
                        logger.warning(f"补充获取字段 {field_name} 失败: {e}")
                        continue
                
                # 重新排序
                unique_stocks = self._deduplicate_and_sort(unique_stocks)
                logger.info(f"✓ 补充获取完成，最终共 {len(unique_stocks)} 只股票")
            
            return unique_stocks[:limit]
        
        return []

    def _extract_fundamental_data(self, item: dict, stock_info: dict):
        """从API响应中提取基本面数据"""
        # PE (动态)
        pe = item.get('f9')
        if isinstance(pe, (int, float)):
            stock_info['pe_ratio'] = round(float(pe), 2) if pe > 0 else '亏损' if pe < 0 else 'N/A'
        else:
            stock_info['pe_ratio'] = 'N/A'
            
        # PB
        pb = item.get('f23')
        if isinstance(pb, (int, float)):
            stock_info['pb_ratio'] = round(float(pb), 2)
        else:
            stock_info['pb_ratio'] = 'N/A'
            
        # 总市值 (转为亿)
        tmc = item.get('f20')
        if isinstance(tmc, (int, float)):
            stock_info['total_market_cap'] = round(tmc / 100000000, 2)
        else:
            stock_info['total_market_cap'] = 'N/A'
            
        # 流通市值 (转为亿)
        cmc = item.get('f21')
        if isinstance(cmc, (int, float)):
            stock_info['circulation_market_cap'] = round(cmc / 100000000, 2)
        else:
            stock_info['circulation_market_cap'] = 'N/A'
            
        # 营收同比
        rev = item.get('f183')
        if isinstance(rev, (int, float)):
            stock_info['revenue_yoy'] = round(float(rev), 2)
        else:
            stock_info['revenue_yoy'] = 'N/A'
            
        # 净利同比
        profit = item.get('f184')
        if isinstance(profit, (int, float)):
            stock_info['net_profit_yoy'] = round(float(profit), 2)
        else:
            stock_info['net_profit_yoy'] = 'N/A'

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
                'pageSize': str(limit),
                '_': str(int(time.time() * 1000))
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

    def _fetch_from_tonghuashun(self, limit: int = 100) -> List[Dict]:
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
        if self.disable_cache:
            # 明确禁用缓存时直接返回
            return
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

    def _check_data_source_health(self) -> Dict[str, Dict]:
        """
        【优化5】检查各数据源的健康状态
        
        Returns:
            dict: {数据源名称: {'healthy': bool, 'latency': float, 'error': str}}
        """
        health_status = {}
        
        # 检查缓存（避免重复检查）
        cache_key = 'source_health'
        if cache_key in self._source_health_cache:
            cached_time = self._source_health_cache[cache_key].get('timestamp', 0)
            if time.time() - cached_time < 300:  # 5分钟内使用缓存
                return self._source_health_cache[cache_key]['data']
        
        # 定义数据源检查方法
        sources_to_check = {
            'eastmoney_guba': {
                'check': lambda: self._quick_check_eastmoney_guba(),
                'name': '东方财富股吧'
            },
            'eastmoney_vip': {
                'check': lambda: self._quick_check_eastmoney_vip(),
                'name': '东方财富VIP'
            },
            'tonghuashun': {
                'check': lambda: self._quick_check_tonghuashun(),
                'name': '同花顺'
            },
            'eastmoney_api': {
                'check': lambda: self._quick_check_eastmoney_api(),
                'name': '东方财富API'
            }
        }
        
        # 并发检查各数据源（快速检查）
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_source = {
                executor.submit(source_info['check']): source_name
                for source_name, source_info in sources_to_check.items()
            }
            
            for future in as_completed(future_to_source):
                source_name = future_to_source[future]
                try:
                    result = future.result(timeout=self._health_check_timeout)
                    health_status[source_name] = {
                        'healthy': result.get('healthy', False),
                        'latency': result.get('latency', 999),
                        'error': result.get('error', ''),
                        'name': sources_to_check[source_name]['name']
                    }
                except Exception as e:
                    health_status[source_name] = {
                        'healthy': False,
                        'latency': 999,
                        'error': str(e),
                        'name': sources_to_check[source_name]['name']
                    }
        
        # 缓存结果
        self._source_health_cache[cache_key] = {
            'data': health_status,
            'timestamp': time.time()
        }
        
        return health_status
    
    def _quick_check_eastmoney_guba(self) -> Dict:
        """快速检查东方财富股吧接口"""
        try:
            import time as time_module
            start = time_module.time()
            response = requests.get(
                "http://guba.eastmoney.com/rank",
                headers=self.headers,
                timeout=self._health_check_timeout
            )
            latency = time_module.time() - start
            return {
                'healthy': response.status_code == 200,
                'latency': latency,
                'error': '' if response.status_code == 200 else f'HTTP {response.status_code}'
            }
        except Exception as e:
            return {'healthy': False, 'latency': 999, 'error': str(e)}
    
    def _quick_check_eastmoney_vip(self) -> Dict:
        """快速检查东方财富VIP接口"""
        try:
            import time as time_module
            start = time_module.time()
            url = "http://push2.eastmoney.com/api/qt/clist/get"
            params = {'pn': '1', 'pz': '5', 'po': '1', 'np': '1'}
            response = requests.get(url, params=params, headers=self.headers, timeout=self._health_check_timeout)
            latency = time_module.time() - start
            return {
                'healthy': response.status_code == 200,
                'latency': latency,
                'error': '' if response.status_code == 200 else f'HTTP {response.status_code}'
            }
        except Exception as e:
            return {'healthy': False, 'latency': 999, 'error': str(e)}
    
    def _quick_check_tonghuashun(self) -> Dict:
        """快速检查同花顺接口"""
        try:
            import time as time_module
            start = time_module.time()
            # 简单的连接测试
            response = requests.get(
                "http://q.10jqka.com.cn",
                headers=self.headers,
                timeout=self._health_check_timeout
            )
            latency = time_module.time() - start
            return {
                'healthy': response.status_code in [200, 301, 302],
                'latency': latency,
                'error': '' if response.status_code in [200, 301, 302] else f'HTTP {response.status_code}'
            }
        except Exception as e:
            return {'healthy': False, 'latency': 999, 'error': str(e)}
    
    def _quick_check_eastmoney_api(self) -> Dict:
        """快速检查东方财富API接口"""
        try:
            import time as time_module
            start = time_module.time()
            url = "http://push2.eastmoney.com/api/qt/ulist.np/get"
            params = {'secids': '1.000001', 'fltt': '2', 'fields': 'f2'}
            response = requests.get(url, params=params, headers=self.headers, timeout=self._health_check_timeout)
            latency = time_module.time() - start
            return {
                'healthy': response.status_code == 200,
                'latency': latency,
                'error': '' if response.status_code == 200 else f'HTTP {response.status_code}'
            }
        except Exception as e:
            return {'healthy': False, 'latency': 999, 'error': str(e)}


def main():
    """测试热门股票获取器"""
    print("=" * 60)
    print("热门股票获取器 - 测试 (v4.0 游资思维优化版)")
    print("=" * 60)

    # v4.0: 默认禁用缓存，强制使用实时数据
    fetcher = HotStocksFetcher(disable_cache=True)

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
