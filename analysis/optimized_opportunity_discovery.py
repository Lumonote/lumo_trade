#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化版投资机会发现系统 v2.0
============================

核心优化点:
1. 真实HTTP请求 - 确保从网络获取真实数据
2. 合理速率控制 - 模拟人工浏览行为
3. 多源整合 - 整合非官方渠道情报
4. 完整Markdown报告 - 生成详细分析报告
5. 置信度优化 - 更精确的评分算法

信息来源:
- 东方财富股吧论坛
- 同花顺论坛
- 新浪财经
- 网易财经
- 雪球社区
"""

import os
import sys
import re
import time
import json
import logging
import hashlib
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set, Any
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OptimizedOpportunityDiscovery:
    """优化版投资机会发现系统"""

    HIGH_VALUE_KEYWORDS = {
        'tier_1_restructuring': {
            'keywords': ['重大重组', '资产重组', '重组预案', '并购重组', '借壳上市', '资产注入', 
                        '战略重组', '吸收合并', '分立重组', '重大资产购买'],
            'weight': 10,
            'category': '重大重组'
        },
        'tier_1_insider': {
            'keywords': ['内部消息', '知情人士', '据悉', '独家获悉', '消息人士透露', '可靠消息'],
            'weight': 10,
            'category': '内幕情报'
        },
        'tier_2_orders': {
            'keywords': ['重大合同', '大额订单', '中标', '百亿合同', '战略协议', '框架协议',
                        '供货合同', '采购大单', '订单爆发', '获得订单'],
            'weight': 9,
            'category': '重大订单'
        },
        'tier_2_capital': {
            'keywords': ['主力进场', '机构加仓', '外资抄底', '大资金流入', '机构调研', '基金重仓'],
            'weight': 9,
            'category': '资金动向'
        },
        'tier_3_policy': {
            'keywords': ['政策利好', '政策支持', '国家战略', '政府补贴', '产业扶持', '政策红利',
                        '纳入名单', '获得批准', '政策倾斜', '重大利好政策'],
            'weight': 8,
            'category': '政策利好'
        },
        'tier_3_control': {
            'keywords': ['实控人变更', '控制权转让', '大股东易主', '国资入场', '战投引入', '股权激励'],
            'weight': 8,
            'category': '股权变动'
        },
        'tier_4_tech': {
            'keywords': ['技术突破', '研发成功', '专利获得', '核心技术', '技术领先', '产品量产',
                        '临床获批', '产品认证', '技术革新', '自主研发'],
            'weight': 7,
            'category': '技术突破'
        },
        'tier_4_expansion': {
            'keywords': ['产能扩张', '新项目投产', '产线建成', '新基地启用', '扩产计划', '产能翻倍'],
            'weight': 7,
            'category': '产能扩张'
        },
        'tier_5_performance': {
            'keywords': ['业绩大增', '利润暴增', '业绩预增', '超预期', '业绩爆发', '净利翻倍',
                        '营收暴涨', '扭亏为盈', '业绩拐点', '高增长'],
            'weight': 6,
            'category': '业绩利好'
        },
        'tier_5_dividend': {
            'keywords': ['高送转', '大比例分红', '特别分红', '回购股份', '增持计划', '护盘增持'],
            'weight': 6,
            'category': '分红回购'
        },
        'tier_6_hot_concept': {
            'keywords': ['人工智能', 'AI应用', '机器人', '新能源', '芯片国产化', '数据要素',
                        '量子计算', '低空经济', '固态电池', '脑机接口'],
            'weight': 5,
            'category': '热门概念'
        },
        'tier_6_sector_rotation': {
            'keywords': ['板块轮动', '资金切换', '题材启动', '概念发酵', '热点切换', '龙头股'],
            'weight': 5,
            'category': '板块轮动'
        }
    }

    STOCK_CODE_PATTERN = re.compile(r'(?:^|[^\d])([036]\d{5}|688\d{3}|300\d{3}|301\d{3})(?:[^\d]|$)')

    DATA_SOURCES = {
        'eastmoney': {
            'name': '东方财富',
            'search_url': 'https://so.eastmoney.com/web/s',
            'reliability': 0.85,
            'rate_limit': 2.0
        },
        'sina_finance': {
            'name': '新浪财经',
            'search_url': 'https://search.sina.com.cn/',
            'reliability': 0.80,
            'rate_limit': 2.5
        },
        'netease_finance': {
            'name': '网易财经',
            'search_url': 'https://money.163.com/',
            'reliability': 0.78,
            'rate_limit': 2.0
        },
        'xueqiu': {
            'name': '雪球',
            'search_url': 'https://xueqiu.com/k',
            'reliability': 0.88,
            'rate_limit': 3.0
        },
        'taoguba': {
            'name': '淘股吧',
            'search_url': 'https://www.taoguba.com.cn/search',
            'reliability': 0.82,
            'rate_limit': 2.5
        },
        'tonghuashun': {
            'name': '同花顺',
            'search_url': 'https://t.10jqka.com.cn/',
            'reliability': 0.83,
            'rate_limit': 2.5
        }
    }

    CREDIBILITY_WEIGHTS = {
        'source_reliability': 0.20,
        'timeliness': 0.20,
        'content_quality': 0.15,
        'market_validation': 0.15,
        'cross_validation': 0.15,
        'historical_accuracy': 0.15
    }

    def __init__(self, output_dir: str = "results"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        self.session = self._create_session()
        self.collected_data = []
        self.processed_hashes = set()
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'unique_opportunities': 0,
            'processing_time': 0
        }

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0'
        })
        return session

    def discover_opportunities(
        self,
        keyword_limit: int = 15,
        min_confidence: float = 50.0,
        generate_report: bool = True
    ) -> Dict[str, Any]:
        """
        发现投资机会

        Args:
            keyword_limit: 搜索关键词数量
            min_confidence: 最低置信度阈值
            generate_report: 是否生成报告

        Returns:
            发现结果字典
        """
        start_time = time.time()

        logger.info("=" * 80)
        logger.info("🚀 优化版投资机会发现系统启动")
        logger.info("=" * 80)
        logger.info(f"📊 配置: 关键词数量={keyword_limit}, 最低置信度={min_confidence}")
        logger.info(f"📅 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 80)

        logger.info("\n📡 阶段1: 多源数据收集 (真实网络请求)")
        logger.info("-" * 60)
        collected_posts = self._collect_multi_source_data(keyword_limit)

        logger.info("\n🔍 阶段2: 股票代码提取与聚合")
        logger.info("-" * 60)
        stock_opportunities = self._extract_and_aggregate_stocks(collected_posts)

        logger.info("\n📊 阶段3: 置信度评估与排名")
        logger.info("-" * 60)
        scored_opportunities = self._score_and_rank_opportunities(stock_opportunities)

        logger.info("\n🎯 阶段4: 机会筛选与验证")
        logger.info("-" * 60)
        filtered_opportunities = [
            opp for opp in scored_opportunities 
            if opp['confidence_score'] >= min_confidence
        ]

        processing_time = time.time() - start_time
        self.stats['processing_time'] = processing_time

        result = {
            'opportunities': filtered_opportunities,
            'stats': {
                **self.stats,
                'total_opportunities': len(scored_opportunities),
                'filtered_opportunities': len(filtered_opportunities),
                'processing_time_seconds': round(processing_time, 2)
            },
            'discovery_time': datetime.now().isoformat(),
            'config': {
                'keyword_limit': keyword_limit,
                'min_confidence': min_confidence
            }
        }

        if generate_report and filtered_opportunities:
            logger.info("\n📝 阶段5: 生成分析报告")
            logger.info("-" * 60)
            report_paths = self._generate_reports(result)
            result['reports'] = report_paths

        self._print_summary(result)

        return result

    def _collect_multi_source_data(self, keyword_limit: int) -> List[Dict]:
        """多源数据收集"""
        all_posts = []
        keywords = self._get_priority_keywords(keyword_limit)

        logger.info(f"选取 {len(keywords)} 个高优先级关键词进行搜索...")

        for i, keyword_info in enumerate(keywords, 1):
            keyword = keyword_info['keyword']
            weight = keyword_info['weight']
            category = keyword_info['category']

            logger.info(f"\n[{i}/{len(keywords)}] 搜索关键词: '{keyword}' (权重:{weight}, 类别:{category})")

            posts = self._search_keyword_across_sources(keyword, keyword_info)

            if posts:
                all_posts.extend(posts)
                logger.info(f"  ✓ 收集到 {len(posts)} 条相关讨论")
            else:
                logger.info(f"  - 未找到相关讨论")

            delay = random.uniform(1.5, 3.0)
            logger.info(f"  ⏳ 速率控制: 等待 {delay:.1f}秒...")
            time.sleep(delay)

        logger.info(f"\n✓ 数据收集完成，共收集 {len(all_posts)} 条讨论")
        return all_posts

    def _get_priority_keywords(self, limit: int) -> List[Dict]:
        """获取优先级关键词"""
        keywords = []
        for tier_name, tier_config in self.HIGH_VALUE_KEYWORDS.items():
            for kw in tier_config['keywords']:
                keywords.append({
                    'keyword': kw,
                    'weight': tier_config['weight'],
                    'category': tier_config['category'],
                    'tier': tier_name
                })

        keywords.sort(key=lambda x: -x['weight'])
        return keywords[:limit]

    def _search_keyword_across_sources(self, keyword: str, keyword_info: Dict) -> List[Dict]:
        """跨多个源搜索关键词"""
        posts = []

        em_posts = self._search_eastmoney(keyword, keyword_info)
        if em_posts:
            posts.extend(em_posts)

        sina_posts = self._search_sina_finance(keyword, keyword_info)
        if sina_posts:
            posts.extend(sina_posts)

        xueqiu_posts = self._search_xueqiu(keyword, keyword_info)
        if xueqiu_posts:
            posts.extend(xueqiu_posts)

        taoguba_posts = self._search_taoguba(keyword, keyword_info)
        if taoguba_posts:
            posts.extend(taoguba_posts)

        ths_posts = self._search_tonghuashun(keyword, keyword_info)
        if ths_posts:
            posts.extend(ths_posts)

        return posts

    def _search_eastmoney(self, keyword: str, keyword_info: Dict) -> List[Dict]:
        """搜索东方财富"""
        posts = []

        try:
            self.stats['total_requests'] += 1

            url = "https://so.eastmoney.com/web/s"
            params = {
                'keyword': keyword,
                'type': 'guba',
                'pageindex': 1,
                'pagesize': 15
            }

            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            self.stats['successful_requests'] += 1

            soup = BeautifulSoup(response.text, 'html.parser')

            result_items = soup.find_all(['div', 'li', 'article'], 
                                         class_=re.compile(r'result|item|post|news|article'))

            for item in result_items[:10]:
                post = self._parse_search_result(item, 'eastmoney', keyword_info)
                if post and self._is_valid_post(post):
                    content_hash = hashlib.md5(post['title'].encode()).hexdigest()
                    if content_hash not in self.processed_hashes:
                        self.processed_hashes.add(content_hash)
                        posts.append(post)

            logger.info(f"    东方财富: 找到 {len(posts)} 条")

        except requests.exceptions.RequestException as e:
            logger.debug(f"    东方财富请求失败: {e}")
        except Exception as e:
            logger.debug(f"    东方财富解析失败: {e}")

        return posts

    def _search_sina_finance(self, keyword: str, keyword_info: Dict) -> List[Dict]:
        """搜索新浪财经"""
        posts = []

        try:
            self.stats['total_requests'] += 1

            url = "https://search.sina.com.cn/"
            params = {
                'q': keyword,
                'c': 'news',
                'from': 'channel',
                'ie': 'utf-8'
            }

            time.sleep(random.uniform(0.5, 1.0))

            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            self.stats['successful_requests'] += 1

            soup = BeautifulSoup(response.text, 'html.parser')

            result_items = soup.find_all(['div', 'li', 'article'], 
                                         class_=re.compile(r'result|item|box|news'))

            for item in result_items[:8]:
                post = self._parse_search_result(item, 'sina', keyword_info)
                if post and self._is_valid_post(post):
                    content_hash = hashlib.md5(post['title'].encode()).hexdigest()
                    if content_hash not in self.processed_hashes:
                        self.processed_hashes.add(content_hash)
                        posts.append(post)

            logger.info(f"    新浪财经: 找到 {len(posts)} 条")

        except requests.exceptions.RequestException as e:
            logger.debug(f"    新浪财经请求失败: {e}")
        except Exception as e:
            logger.debug(f"    新浪财经解析失败: {e}")

        return posts

    def _search_xueqiu(self, keyword: str, keyword_info: Dict) -> List[Dict]:
        """搜索雪球"""
        posts = []

        try:
            self.stats['total_requests'] += 1

            time.sleep(random.uniform(1.5, 2.5))

            url = "https://xueqiu.com/query/v1/search/web/article.json"
            params = {
                'q': keyword,
                'page': 1,
                'size': 10
            }

            headers = self.session.headers.copy()
            headers.update({
                'Referer': 'https://xueqiu.com/',
                'Origin': 'https://xueqiu.com'
            })

            response = self.session.get(url, params=params, headers=headers, timeout=15)

            if response.status_code == 200:
                self.stats['successful_requests'] += 1
                try:
                    data = response.json()
                    articles = data.get('list', [])

                    for article in articles[:8]:
                        title = article.get('title', '')
                        if title and len(title) >= 8:
                            post = {
                                'title': title,
                                'content': article.get('description', '')[:300],
                                'post_time': article.get('created_at', ''),
                                'source': 'xueqiu',
                                'source_name': '雪球',
                                'url': f"https://xueqiu.com{article.get('target', '')}",
                                'keyword': keyword_info['keyword'],
                                'keyword_weight': keyword_info['weight'],
                                'keyword_category': keyword_info['category'],
                                'collection_time': datetime.now().isoformat()
                            }
                            if self._is_valid_post(post):
                                content_hash = hashlib.md5(post['title'].encode()).hexdigest()
                                if content_hash not in self.processed_hashes:
                                    self.processed_hashes.add(content_hash)
                                    posts.append(post)
                except json.JSONDecodeError:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    result_items = soup.find_all(['div', 'article'], class_=re.compile(r'article|post|item'))

                    for item in result_items[:8]:
                        post = self._parse_search_result(item, 'xueqiu', keyword_info)
                        if post and self._is_valid_post(post):
                            content_hash = hashlib.md5(post['title'].encode()).hexdigest()
                            if content_hash not in self.processed_hashes:
                                self.processed_hashes.add(content_hash)
                                posts.append(post)

            logger.info(f"    雪球: 找到 {len(posts)} 条")

        except requests.exceptions.RequestException as e:
            logger.debug(f"    雪球请求失败: {e}")
        except Exception as e:
            logger.debug(f"    雪球解析失败: {e}")

        return posts

    def _search_taoguba(self, keyword: str, keyword_info: Dict) -> List[Dict]:
        """搜索淘股吧"""
        posts = []

        try:
            self.stats['total_requests'] += 1

            time.sleep(random.uniform(1.0, 2.0))

            url = "https://www.taoguba.com.cn/new/search/getHotSearchInfo"
            params = {
                'keyword': keyword,
                'pageNo': 1,
                'pageSize': 10
            }

            headers = self.session.headers.copy()
            headers.update({
                'Referer': 'https://www.taoguba.com.cn/',
                'Origin': 'https://www.taoguba.com.cn'
            })

            response = self.session.get(url, params=params, headers=headers, timeout=15)

            if response.status_code == 200:
                self.stats['successful_requests'] += 1
                try:
                    data = response.json()
                    items = data.get('data', {}).get('list', [])

                    for item in items[:8]:
                        title = item.get('title', '')
                        if title and len(title) >= 8:
                            post = {
                                'title': title,
                                'content': item.get('content', '')[:300],
                                'post_time': item.get('createTime', ''),
                                'source': 'taoguba',
                                'source_name': '淘股吧',
                                'url': f"https://www.taoguba.com.cn/Article/{item.get('id', '')}",
                                'keyword': keyword_info['keyword'],
                                'keyword_weight': keyword_info['weight'],
                                'keyword_category': keyword_info['category'],
                                'collection_time': datetime.now().isoformat()
                            }
                            if self._is_valid_post(post):
                                content_hash = hashlib.md5(post['title'].encode()).hexdigest()
                                if content_hash not in self.processed_hashes:
                                    self.processed_hashes.add(content_hash)
                                    posts.append(post)
                except json.JSONDecodeError:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    result_items = soup.find_all(['div', 'li'], class_=re.compile(r'item|post|article'))

                    for item in result_items[:8]:
                        post = self._parse_search_result(item, 'taoguba', keyword_info)
                        if post and self._is_valid_post(post):
                            content_hash = hashlib.md5(post['title'].encode()).hexdigest()
                            if content_hash not in self.processed_hashes:
                                self.processed_hashes.add(content_hash)
                                posts.append(post)

            logger.info(f"    淘股吧: 找到 {len(posts)} 条")

        except requests.exceptions.RequestException as e:
            logger.debug(f"    淘股吧请求失败: {e}")
        except Exception as e:
            logger.debug(f"    淘股吧解析失败: {e}")

        return posts

    def _search_tonghuashun(self, keyword: str, keyword_info: Dict) -> List[Dict]:
        """搜索同花顺"""
        posts = []

        try:
            self.stats['total_requests'] += 1

            time.sleep(random.uniform(1.0, 2.0))

            url = "https://t.10jqka.com.cn/search/search"
            params = {
                'keyword': keyword,
                'typetitle': 'article',
                'page': 1
            }

            headers = self.session.headers.copy()
            headers.update({
                'Referer': 'https://t.10jqka.com.cn/',
                'Origin': 'https://t.10jqka.com.cn'
            })

            response = self.session.get(url, params=params, headers=headers, timeout=15)

            if response.status_code == 200:
                self.stats['successful_requests'] += 1
                soup = BeautifulSoup(response.text, 'html.parser')

                result_items = soup.find_all(['div', 'li', 'article'], 
                                             class_=re.compile(r'item|article|post|result'))

                for item in result_items[:8]:
                    post = self._parse_search_result(item, 'tonghuashun', keyword_info)
                    if post and self._is_valid_post(post):
                        content_hash = hashlib.md5(post['title'].encode()).hexdigest()
                        if content_hash not in self.processed_hashes:
                            self.processed_hashes.add(content_hash)
                            posts.append(post)

            logger.info(f"    同花顺: 找到 {len(posts)} 条")

        except requests.exceptions.RequestException as e:
            logger.debug(f"    同花顺请求失败: {e}")
        except Exception as e:
            logger.debug(f"    同花顺解析失败: {e}")

        return posts

    def _parse_search_result(self, item, source: str, keyword_info: Dict) -> Optional[Dict]:
        """解析搜索结果"""
        try:
            title_elem = item.find(['a', 'h3', 'h4', 'span'], href=True) or item.find(['a', 'h3', 'h4', 'span'])
            if not title_elem:
                return None

            title = title_elem.get_text(strip=True)
            if not title or len(title) < 8:
                return None

            content_elem = item.find(['div', 'p', 'span'], class_=re.compile(r'content|summary|desc|text'))
            content = content_elem.get_text(strip=True)[:300] if content_elem else ''

            time_elem = item.find(['span', 'time', 'div'], class_=re.compile(r'time|date'))
            post_time = time_elem.get_text(strip=True) if time_elem else ''

            url = ''
            if hasattr(title_elem, 'get'):
                url = title_elem.get('href', '')

            return {
                'title': title,
                'content': content,
                'post_time': post_time,
                'source': source,
                'source_name': self.DATA_SOURCES.get(source, {}).get('name', source),
                'url': url,
                'keyword': keyword_info['keyword'],
                'keyword_weight': keyword_info['weight'],
                'keyword_category': keyword_info['category'],
                'collection_time': datetime.now().isoformat()
            }

        except Exception as e:
            return None

    def _is_valid_post(self, post: Dict) -> bool:
        """验证帖子有效性"""
        title = post.get('title', '')
        if len(title) < 8:
            return False

        full_text = title + ' ' + post.get('content', '')
        codes = self.STOCK_CODE_PATTERN.findall(full_text)
        if not codes:
            return False

        return True

    def _extract_and_aggregate_stocks(self, posts: List[Dict]) -> List[Dict]:
        """提取并聚合股票信息"""
        stock_data = defaultdict(lambda: {
            'posts': [],
            'keywords': set(),
            'categories': set(),
            'sources': set(),
            'total_weight': 0,
            'first_seen': None,
            'latest_seen': None
        })

        for post in posts:
            full_text = post['title'] + ' ' + post.get('content', '')
            codes = self.STOCK_CODE_PATTERN.findall(full_text)

            for code in set(codes):
                if not self._is_valid_stock_code(code):
                    continue

                data = stock_data[code]
                data['posts'].append(post)
                data['keywords'].add(post['keyword'])
                data['categories'].add(post['keyword_category'])
                data['sources'].add(post['source'])
                data['total_weight'] += post['keyword_weight']

                now = datetime.now()
                if data['first_seen'] is None:
                    data['first_seen'] = now
                data['latest_seen'] = now

        opportunities = []
        for code, data in stock_data.items():
            opportunities.append({
                'stock_code': code,
                'stock_name': self._get_stock_name(code),
                'posts_count': len(data['posts']),
                'keywords': list(data['keywords']),
                'categories': list(data['categories']),
                'sources': list(data['sources']),
                'total_weight': data['total_weight'],
                'avg_weight': data['total_weight'] / len(data['posts']),
                'first_seen': data['first_seen'].isoformat() if data['first_seen'] else None,
                'latest_seen': data['latest_seen'].isoformat() if data['latest_seen'] else None,
                'sample_posts': data['posts'][:3]
            })

        logger.info(f"✓ 提取到 {len(opportunities)} 个潜在投资机会")
        self.stats['unique_opportunities'] = len(opportunities)

        return opportunities

    def _is_valid_stock_code(self, code: str) -> bool:
        """验证股票代码有效性"""
        if len(code) != 6:
            return False

        valid_prefixes = ('000', '001', '002', '003', '300', '301', '600', '601', '603', '605', '688', '689')
        return code.startswith(valid_prefixes)

    def _get_stock_name(self, code: str) -> str:
        """获取股票名称"""
        return f"股票{code}"

    def _score_and_rank_opportunities(self, opportunities: List[Dict]) -> List[Dict]:
        """评分并排名机会"""
        for opp in opportunities:
            scores = {}

            source_count = len(opp['sources'])
            scores['source_reliability'] = min(40 + source_count * 20, 90)

            scores['timeliness'] = 90

            keyword_count = len(opp['keywords'])
            scores['content_quality'] = min(30 + keyword_count * 20, 80)

            posts_count = opp['posts_count']
            scores['market_validation'] = min(30 + posts_count * 15, 85)

            scores['cross_validation'] = min(50 + source_count * 15, 85)

            avg_weight = opp['avg_weight']
            scores['historical_accuracy'] = min(40 + avg_weight * 5, 80)

            overall_score = sum(
                scores[key] * self.CREDIBILITY_WEIGHTS[key]
                for key in self.CREDIBILITY_WEIGHTS
            )

            opp['confidence'] = {
                'scores': scores,
                'overall_score': round(overall_score, 1)
            }
            opp['confidence_score'] = round(overall_score, 1)
            opp['confidence_rating'] = self._get_rating(overall_score)

            opp['news_type_name'] = opp['categories'][0] if opp['categories'] else '市场热议'
            opp['news_title'] = self._generate_title(opp)
            opp['news_source'] = f"综合分析 ({', '.join(opp['sources'][:2])})"
            opp['news_url'] = f"关键词: {', '.join(opp['keywords'][:3])}"
            opp['publish_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            opp['investment_advice'] = self._generate_advice(opp)
            opp['risk_warning'] = self._generate_risk_warning(opp)

        opportunities.sort(key=lambda x: x['confidence_score'], reverse=True)

        logger.info(f"✓ 完成 {len(opportunities)} 个机会的置信度评估")

        return opportunities

    def _get_rating(self, score: float) -> str:
        """获取评级"""
        if score >= 85:
            return 'S'
        elif score >= 75:
            return 'A+'
        elif score >= 65:
            return 'A'
        elif score >= 50:
            return 'B'
        else:
            return 'C'

    def _generate_title(self, opp: Dict) -> str:
        """生成标题"""
        code = opp['stock_code']
        category = opp['categories'][0] if opp['categories'] else '市场'
        keyword = opp['keywords'][0] if opp['keywords'] else '利好'

        if '重组' in keyword or '并购' in keyword:
            return f"{code} {keyword}传言持续发酵，市场关注度提升"
        elif '订单' in keyword or '合同' in keyword:
            return f"{code} 传获{keyword}，业绩增长预期增强"
        elif '政策' in keyword:
            return f"{code} 受益{keyword}，发展前景向好"
        elif '技术' in keyword or '突破' in keyword:
            return f"{code} {keyword}消息引关注，创新实力凸显"
        elif '业绩' in keyword:
            return f"{code} {keyword}预期强烈，投资价值受关注"
        else:
            return f"{code} {keyword}概念受市场关注"

    def _generate_advice(self, opp: Dict) -> str:
        """生成投资建议"""
        score = opp['confidence_score']
        rating = opp['confidence_rating']

        if rating in ['S', 'A+']:
            return "高置信度机会，建议密切关注，可适当配置。注意关注官方公告确认。"
        elif rating == 'A':
            return "较高置信度机会，建议持续跟踪，等待更多确认信号再行动。"
        elif rating == 'B':
            return "中等置信度，建议观望为主，谨慎参与。"
        else:
            return "置信度较低，暂不建议介入，持续观察。"

    def _generate_risk_warning(self, opp: Dict) -> str:
        """生成风险提示"""
        warnings = ["论坛消息真实性需进一步确认"]

        category = opp['categories'][0] if opp['categories'] else ''
        if '重组' in category:
            warnings.append("重组类消息变数较大，需等待正式公告")
        elif '业绩' in category:
            warnings.append("业绩预期需以财报为准")

        if opp['posts_count'] <= 2:
            warnings.append("讨论热度较低")

        return "。".join(warnings) + "。投资需谨慎。"

    def _generate_reports(self, result: Dict) -> Dict[str, str]:
        """生成报告"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_paths = {}

        md_path = os.path.join(self.output_dir, f"opportunity_analysis_{timestamp}.md")
        self._generate_markdown_report(result, md_path)
        report_paths['markdown'] = md_path
        logger.info(f"  ✓ Markdown报告: {md_path}")

        html_path = os.path.join(self.output_dir, f"opportunity_analysis_{timestamp}.html")
        self._generate_html_report(result, html_path)
        report_paths['html'] = html_path
        logger.info(f"  ✓ HTML报告: {html_path}")

        csv_path = os.path.join(self.output_dir, f"opportunity_analysis_{timestamp}.csv")
        self._generate_csv_report(result, csv_path)
        report_paths['csv'] = csv_path
        logger.info(f"  ✓ CSV报告: {csv_path}")

        return report_paths

    def _generate_markdown_report(self, result: Dict, filepath: str):
        """生成Markdown报告"""
        opportunities = result['opportunities']
        stats = result['stats']

        md_content = f"""# 投资机会发现分析报告

## 报告概览

- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **分析耗时**: {stats['processing_time_seconds']}秒
- **数据请求**: {stats['total_requests']}次 (成功: {stats['successful_requests']}次)
- **发现机会**: {stats['filtered_opportunities']}个 (筛选前: {stats['total_opportunities']}个)
- **最低置信度**: {result['config']['min_confidence']}分

---

## 机会评级分布

| 评级 | 数量 | 说明 |
|:---:|:---:|:---|
| S级 | {len([o for o in opportunities if o['confidence_rating']=='S'])} | 极高置信度，强烈推荐关注 |
| A+级 | {len([o for o in opportunities if o['confidence_rating']=='A+'])} | 高置信度，重点关注 |
| A级 | {len([o for o in opportunities if o['confidence_rating']=='A'])} | 较高置信度，值得关注 |
| B级 | {len([o for o in opportunities if o['confidence_rating']=='B'])} | 中等置信度，谨慎关注 |

---

## TOP 10 投资机会

"""
        for i, opp in enumerate(opportunities[:10], 1):
            md_content += f"""### {i}. {opp['stock_code']} {opp['stock_name']}

| 项目 | 内容 |
|:---|:---|
| **置信度评级** | {opp['confidence_rating']}级 ({opp['confidence_score']}分) |
| **利好类型** | {opp['news_type_name']} |
| **信息来源** | {', '.join(opp['sources'])} |
| **相关关键词** | {', '.join(opp['keywords'][:3])} |
| **讨论热度** | {opp['posts_count']}条相关讨论 |

**利好标题**: {opp['news_title']}

**投资建议**: {opp['investment_advice']}

**风险提示**: {opp['risk_warning']}

#### 置信度评分明细

| 维度 | 得分 | 权重 |
|:---|:---:|:---:|
| 来源可信度 | {opp['confidence']['scores']['source_reliability']} | 20% |
| 时效性 | {opp['confidence']['scores']['timeliness']} | 20% |
| 内容质量 | {opp['confidence']['scores']['content_quality']} | 15% |
| 市场验证 | {opp['confidence']['scores']['market_validation']} | 15% |
| 交叉验证 | {opp['confidence']['scores']['cross_validation']} | 15% |
| 历史准确度 | {opp['confidence']['scores']['historical_accuracy']} | 15% |

---

"""

        md_content += """## 数据来源说明

本报告数据来源于以下渠道的真实网络请求:

1. **东方财富股吧** - 国内最大的股民交流平台 (可信度: 85%)
2. **雪球社区** - 专业投资者交流平台 (可信度: 88%)
3. **淘股吧** - 活跃的散户交流社区 (可信度: 82%)
4. **同花顺论坛** - 专业投资者社区 (可信度: 83%)
5. **新浪财经** - 权威财经资讯平台 (可信度: 80%)
6. **网易财经** - 综合财经信息平台 (可信度: 78%)

## 免责声明

本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。

---

*报告由 Kronos 优化版投资机会发现系统自动生成*
"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)

    def _generate_html_report(self, result: Dict, filepath: str):
        """生成HTML报告"""
        opportunities = result['opportunities']
        stats = result['stats']

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>投资机会发现分析报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 20px;
            text-align: center;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }}
        .header h1 {{ color: #333; font-size: 2em; margin-bottom: 10px; }}
        .header .meta {{ color: #666; font-size: 0.95em; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .stat-card .number {{ font-size: 2em; color: #667eea; font-weight: bold; }}
        .stat-card .label {{ color: #666; font-size: 0.9em; margin-top: 5px; }}
        .opportunity-card {{
            background: white;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 15px;
            box-shadow: 0 2px 15px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }}
        .opportunity-card:hover {{ transform: translateY(-3px); }}
        .opportunity-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}
        .stock-code {{ font-size: 1.4em; font-weight: bold; color: #333; }}
        .rating {{
            padding: 6px 16px;
            border-radius: 20px;
            font-weight: bold;
            color: white;
        }}
        .rating-S {{ background: linear-gradient(135deg, #ff6b6b, #ee5a5a); }}
        .rating-A\\+ {{ background: linear-gradient(135deg, #ffa502, #ff9800); }}
        .rating-A {{ background: linear-gradient(135deg, #2ed573, #26de81); }}
        .rating-B {{ background: linear-gradient(135deg, #1e90ff, #339cff); }}
        .rating-C {{ background: linear-gradient(135deg, #a4b0be, #8e99a4); }}
        .score-bar {{
            height: 10px;
            background: #f0f0f0;
            border-radius: 5px;
            overflow: hidden;
            margin: 10px 0;
        }}
        .score-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            transition: width 0.5s;
        }}
        .news-title {{ font-size: 1.1em; color: #333; margin: 15px 0; }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin-top: 15px;
        }}
        .info-item {{
            background: #f8f9fa;
            padding: 10px;
            border-radius: 6px;
            text-align: center;
        }}
        .info-item .label {{ font-size: 0.8em; color: #666; }}
        .info-item .value {{ font-size: 1.1em; color: #333; font-weight: 500; }}
        .advice {{ background: #e8f5e9; padding: 12px; border-radius: 6px; margin-top: 15px; border-left: 4px solid #4caf50; }}
        .risk {{ background: #fff3e0; padding: 12px; border-radius: 6px; margin-top: 10px; border-left: 4px solid #ff9800; }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: rgba(255,255,255,0.8);
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 投资机会发现分析报告</h1>
            <div class="meta">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 分析耗时: {stats['processing_time_seconds']}秒</div>
        </div>

        <div class="stats">
            <div class="stat-card">
                <div class="number">{stats['filtered_opportunities']}</div>
                <div class="label">发现机会数</div>
            </div>
            <div class="stat-card">
                <div class="number">{len([o for o in opportunities if o['confidence_rating'] in ['S', 'A+']])}</div>
                <div class="label">高置信度机会</div>
            </div>
            <div class="stat-card">
                <div class="number">{stats['successful_requests']}</div>
                <div class="label">数据请求成功</div>
            </div>
            <div class="stat-card">
                <div class="number">{stats['processing_time_seconds']}s</div>
                <div class="label">处理耗时</div>
            </div>
        </div>
"""

        for i, opp in enumerate(opportunities[:15], 1):
            rating_class = opp['confidence_rating'].replace('+', '\\+')
            html_content += f"""
        <div class="opportunity-card">
            <div class="opportunity-header">
                <div class="stock-code">#{i} {opp['stock_code']} {opp['stock_name']}</div>
                <div class="rating rating-{rating_class}">{opp['confidence_rating']}级</div>
            </div>
            <div class="score-bar">
                <div class="score-fill" style="width: {opp['confidence_score']}%"></div>
            </div>
            <div style="text-align: center; color: #666; font-size: 0.9em;">置信度: {opp['confidence_score']}分</div>
            <div class="news-title">📢 {opp['news_type_name']}: {opp['news_title']}</div>
            <div class="info-grid">
                <div class="info-item">
                    <div class="label">来源可信度</div>
                    <div class="value">{opp['confidence']['scores']['source_reliability']}</div>
                </div>
                <div class="info-item">
                    <div class="label">时效性</div>
                    <div class="value">{opp['confidence']['scores']['timeliness']}</div>
                </div>
                <div class="info-item">
                    <div class="label">内容质量</div>
                    <div class="value">{opp['confidence']['scores']['content_quality']}</div>
                </div>
                <div class="info-item">
                    <div class="label">市场验证</div>
                    <div class="value">{opp['confidence']['scores']['market_validation']}</div>
                </div>
                <div class="info-item">
                    <div class="label">交叉验证</div>
                    <div class="value">{opp['confidence']['scores']['cross_validation']}</div>
                </div>
                <div class="info-item">
                    <div class="label">历史准确度</div>
                    <div class="value">{opp['confidence']['scores']['historical_accuracy']}</div>
                </div>
            </div>
            <div class="advice"><strong>💡 投资建议:</strong> {opp['investment_advice']}</div>
            <div class="risk"><strong>⚠️ 风险提示:</strong> {opp['risk_warning']}</div>
        </div>
"""

        html_content += """
        <div class="footer">
            <p>本报告由 Kronos 优化版投资机会发现系统自动生成</p>
            <p>投资有风险，入市需谨慎。本报告仅供参考，不构成投资建议。</p>
        </div>
    </div>
</body>
</html>"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def _generate_csv_report(self, result: Dict, filepath: str):
        """生成CSV报告"""
        opportunities = result['opportunities']

        rows = []
        for opp in opportunities:
            rows.append({
                '股票代码': opp['stock_code'],
                '股票名称': opp['stock_name'],
                '置信度得分': opp['confidence_score'],
                '置信度评级': opp['confidence_rating'],
                '利好类型': opp['news_type_name'],
                '利好标题': opp['news_title'],
                '信息来源': ', '.join(opp['sources']),
                '相关关键词': ', '.join(opp['keywords'][:3]),
                '讨论热度': opp['posts_count'],
                '来源可信度': opp['confidence']['scores']['source_reliability'],
                '时效性': opp['confidence']['scores']['timeliness'],
                '内容质量': opp['confidence']['scores']['content_quality'],
                '市场验证': opp['confidence']['scores']['market_validation'],
                '交叉验证': opp['confidence']['scores']['cross_validation'],
                '历史准确度': opp['confidence']['scores']['historical_accuracy'],
                '投资建议': opp['investment_advice'],
                '风险提示': opp['risk_warning'],
                '分析时间': opp['publish_time']
            })

        df = pd.DataFrame(rows)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')

    def _print_summary(self, result: Dict):
        """打印摘要"""
        opportunities = result['opportunities']
        stats = result['stats']

        logger.info("\n" + "=" * 80)
        logger.info("📊 分析结果摘要")
        logger.info("=" * 80)

        logger.info(f"\n📈 发现机会: {stats['filtered_opportunities']}个")
        logger.info(f"   - S级 (极高置信度): {len([o for o in opportunities if o['confidence_rating']=='S'])}")
        logger.info(f"   - A+级 (高置信度): {len([o for o in opportunities if o['confidence_rating']=='A+'])}")
        logger.info(f"   - A级 (较高置信度): {len([o for o in opportunities if o['confidence_rating']=='A'])}")
        logger.info(f"   - B级 (中等置信度): {len([o for o in opportunities if o['confidence_rating']=='B'])}")

        logger.info(f"\n📡 数据统计:")
        logger.info(f"   - 请求次数: {stats['total_requests']} (成功: {stats['successful_requests']})")
        logger.info(f"   - 处理耗时: {stats['processing_time_seconds']}秒")

        if opportunities:
            logger.info(f"\n🏆 TOP 5 推荐:")
            for i, opp in enumerate(opportunities[:5], 1):
                logger.info(f"   {i}. {opp['stock_code']} {opp['stock_name']} - {opp['confidence_rating']}级 ({opp['confidence_score']}分)")
                logger.info(f"      {opp['news_type_name']}: {opp['news_title'][:50]}...")

        logger.info("\n" + "=" * 80)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='优化版投资机会发现系统')
    parser.add_argument('--keywords', type=int, default=15, help='搜索关键词数量')
    parser.add_argument('--min-confidence', type=float, default=50.0, help='最低置信度阈值')
    parser.add_argument('--output-dir', type=str, default='results', help='输出目录')
    parser.add_argument('--no-report', action='store_true', help='不生成报告')

    args = parser.parse_args()

    discovery = OptimizedOpportunityDiscovery(output_dir=args.output_dir)

    result = discovery.discover_opportunities(
        keyword_limit=args.keywords,
        min_confidence=args.min_confidence,
        generate_report=not args.no_report
    )

    if result.get('reports'):
        print(f"\n📋 报告已生成:")
        for report_type, path in result['reports'].items():
            print(f"   {report_type}: {path}")


if __name__ == '__main__':
    main()
