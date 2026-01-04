#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关键词驱动的论坛利好挖掘系统 v1.0
===============================

核心理念：关键词优先，反向挖掘
1. 先在论坛中搜索重大利好关键词
2. 从包含关键词的帖子中提取股票代码
3. 分析讨论热度和情绪倾向
4. 生成投资机会列表

优势：
- 更精准：直接定位包含利好信息的讨论
- 更全面：不受热门股票列表限制
- 更及时：第一时间发现小众股票的重大利好
- 更深度：基于实际讨论内容而非表面指标

搜索策略：
1. 高权重关键词优先搜索
2. 多平台并行搜索
3. 智能去重和聚合
4. 上下文语义分析
"""

import os
import sys
import re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
import logging
from collections import Counter, defaultdict
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import json

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.dynamic_crawler import DynamicCrawler
from analysis.investor_sentiment import InvestorSentimentAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KeywordForumMiner:
    """关键词驱动的论坛挖掘器"""

    # 重大利好关键词分类（按搜索优先级排序）
    # 重点关注：未公告的传言、小道消息、内幕信息
    PRIORITY_KEYWORDS = {
        'tier_0': {  # 最高优先级：传言/小道消息类（未公告）
            'keywords': [
                '传闻', '据说', '听说', '小道消息', '内部消息',
                '传言', '风声', '爆料', '透露', '知情人士',
                '可能被收购', '或将重组', '有望并购', '疑似重组',
                '正在洽谈', '秘密接触', '私下协商', '暗中筹划',
                '即将公告', '近期公告', '消息称', '市场传闻',
                '坊间传闻', '有消息称', '据悉', '据透露'
            ],
            'weight': 12,
            'search_priority': 0
        },
        'tier_1': {  # 高优先级：重组并购传言类
            'keywords': [
                '重组传闻', '并购传言', '收购传闻', '借壳传闻',
                '要被收购', '将被收购', '拟被收购', '被看中',
                '接盘', '入主', '举牌', '增持', '要约收购',
                '战略入股', '引入战投', '混改', '国资入场',
                '央企整合', '地方国资', '产业资本'
            ],
            'weight': 11,
            'search_priority': 1
        },
        'tier_2': {  # 高优先级：股吧讨论热点类
            'keywords': [
                '大利好', '重磅利好', '特大利好', '隐藏利好',
                '低估', '严重低估', '价值洼地', '错杀',
                '主力吸筹', '机构建仓', '游资介入', '庄家进场',
                '底部放量', '异动', '蹊跷', '有猫腻'
            ],
            'weight': 10,
            'search_priority': 2
        },
        'tier_3': {  # 中高优先级：未公开订单/合作
            'keywords': [
                '签大单', '拿下订单', '接到订单', '订单传闻',
                '战略合作', '深度合作', '牵手', '联姻',
                '进入供应链', '打入', '获得认证', '通过验证'
            ],
            'weight': 9,
            'search_priority': 3
        },
        'tier_4': {  # 中优先级：政策预期类
            'keywords': [
                '政策预期', '有望受益', '或将纳入', '可能入选',
                '政策风口', '风口', '赛道', '概念龙头'
            ],
            'weight': 8,
            'search_priority': 4
        },
        'tier_5': {  # 中优先级：业绩预期类
            'keywords': [
                '业绩有望', '盈利预期', '拐点', '反转在即',
                '触底反弹', '困境反转', '扭亏', '业绩拐点'
            ],
            'weight': 7,
            'search_priority': 5
        }
    }
    
    # 排除已公告的关键词（过滤官方新闻）
    EXCLUDE_KEYWORDS = [
        '公告', '披露', '发布公告', '根据公告', '公告显示',
        '证监会', '交易所', '上市公司公告', '官宣', '正式宣布',
        '已经', '已完成', '已获批', '已通过'
    ]

    # 股票代码正则表达式
    STOCK_CODE_PATTERNS = [
        r'[0-9]{6}',              # 6位数字代码
        r'[0-9]{6}\.SZ',          # 深交所格式
        r'[0-9]{6}\.SH',          # 上交所格式
        r'SZ[0-9]{6}',            # SZ前缀
        r'SH[0-9]{6}',            # SH前缀
    ]

    # 论坛搜索URL模板
    FORUM_SEARCH_URLS = {
        'eastmoney_guba': {
            'base_url': 'https://so.eastmoney.com/web/s',
            'params_template': {
                'keyword': '{keyword}',
                'type': 'guba',
                'pageindex': '{page}',
                'pagesize': 20
            }
        },
        'tonghuashun': {
            'base_url': 'https://search.10jqka.com.cn/unifiedwap/unified/result/',
            'params_template': {
                'keyword': '{keyword}',
                'type': 'guba',
                'page': '{page}'
            }
        }
    }

    def __init__(self):
        """初始化关键词论坛挖掘器"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

    def mine_by_keywords(self, keyword_limit: int = 10, post_limit_per_keyword: int = 20) -> List[Dict]:
        """
        基于关键词挖掘论坛利好信息

        Args:
            keyword_limit: 搜索的关键词数量上限
            post_limit_per_keyword: 每个关键词搜索的帖子数量

        Returns:
            挖掘结果列表
        """
        logger.info("=" * 70)
        logger.info("🎯 开始基于关键词的论坛利好挖掘")
        logger.info(f"📊 搜索策略: {keyword_limit} 个关键词 × {post_limit_per_keyword} 条帖子")
        logger.info("=" * 70)

        results = []
        keyword_stats = {}
        processed_keywords = 0

        try:
            # 1. 按优先级获取关键词
            priority_keywords = self._get_priority_keywords(keyword_limit)
            
            logger.info(f"选择 {len(priority_keywords)} 个高优先级关键词进行搜索...")

            # 2. 多线程并行搜索关键词
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_keyword = {
                    executor.submit(
                        self._search_keyword_in_forums, 
                        keyword_info, 
                        post_limit_per_keyword
                    ): keyword_info 
                    for keyword_info in priority_keywords[:keyword_limit]
                }

                # 收集搜索结果
                all_posts = []
                for future in as_completed(future_to_keyword):
                    keyword_info = future_to_keyword[future]
                    processed_keywords += 1
                    
                    try:
                        keyword_posts = future.result(timeout=120)  # 2分钟超时
                        if keyword_posts:
                            all_posts.extend(keyword_posts)
                            keyword_stats[keyword_info['keyword']] = {
                                'posts_found': len(keyword_posts),
                                'weight': keyword_info['weight']
                            }
                            logger.info(f"✓ 关键词 '{keyword_info['keyword']}' 找到 {len(keyword_posts)} 条相关讨论")
                        else:
                            keyword_stats[keyword_info['keyword']] = {
                                'posts_found': 0,
                                'weight': keyword_info['weight']
                            }
                            logger.debug(f"- 关键词 '{keyword_info['keyword']}' 未找到相关讨论")
                            
                    except Exception as e:
                        logger.warning(f"✗ 搜索关键词 '{keyword_info['keyword']}' 失败: {e}")
                        keyword_stats[keyword_info['keyword']] = {
                            'posts_found': 0,
                            'weight': keyword_info['weight'],
                            'error': str(e)
                        }
                    
                    # 显示进度
                    if processed_keywords % 5 == 0:
                        logger.info(f"已处理 {processed_keywords}/{min(len(priority_keywords), keyword_limit)} 个关键词")

            # 3. 从帖子中提取股票代码并分析
            logger.info(f"\n步骤2: 从 {len(all_posts)} 条帖子中提取股票代码...")
            stock_opportunities = self._extract_stocks_from_posts(all_posts)

            # 4. 计算置信度和排序
            logger.info(f"步骤3: 分析 {len(stock_opportunities)} 个股票机会...")
            for opportunity in stock_opportunities:
                opportunity['confidence_score'] = self._calculate_confidence_score(opportunity)
                opportunity['confidence_rating'] = self._get_confidence_rating(opportunity['confidence_score'])

            # 5. 按置信度排序
            stock_opportunities.sort(key=lambda x: x['confidence_score'], reverse=True)

            # 6. 过滤低质量机会
            results = [op for op in stock_opportunities if op['confidence_score'] >= 30]

            # 7. 输出统计信息
            self._print_mining_summary(results, keyword_stats)

            return results

        except Exception as e:
            logger.error(f"关键词挖掘过程出错: {e}")
            import traceback
            traceback.print_exc()
            return results

    def _get_priority_keywords(self, limit: int) -> List[Dict]:
        """
        按优先级获取关键词列表

        Args:
            limit: 关键词数量限制

        Returns:
            关键词信息列表
        """
        keywords_list = []
        
        # 按tier优先级顺序处理
        for tier_name, tier_config in self.PRIORITY_KEYWORDS.items():
            tier_keywords = [
                {
                    'keyword': kw,
                    'weight': tier_config['weight'],
                    'tier': tier_name,
                    'priority': tier_config['search_priority']
                }
                for kw in tier_config['keywords']
            ]
            keywords_list.extend(tier_keywords)
        
        # 按优先级和权重排序
        keywords_list.sort(key=lambda x: (x['priority'], -x['weight']))
        
        return keywords_list[:limit]

    def _search_keyword_in_forums(self, keyword_info: Dict, post_limit: int) -> List[Dict]:
        """
        在论坛中搜索特定关键词

        Args:
            keyword_info: 关键词信息
            post_limit: 帖子数量限制

        Returns:
            搜索到的帖子列表
        """
        keyword = keyword_info['keyword']
        posts = []
        
        try:
            # 方法1: 使用动态爬虫搜索
            dynamic_posts = self._search_with_dynamic_crawler(keyword, post_limit // 2)
            if dynamic_posts:
                posts.extend(dynamic_posts)
            
            # 方法2: 使用API搜索
            api_posts = self._search_with_api(keyword, post_limit // 2)
            if api_posts:
                posts.extend(api_posts)
            
            # 去重
            seen_titles = set()
            unique_posts = []
            for post in posts:
                title = post.get('title', '')
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    post['search_keyword'] = keyword
                    post['keyword_weight'] = keyword_info['weight']
                    unique_posts.append(post)
            
            return unique_posts[:post_limit]
            
        except Exception as e:
            logger.debug(f"搜索关键词 '{keyword}' 时出错: {e}")
            return []

    def _search_with_dynamic_crawler(self, keyword: str, limit: int) -> List[Dict]:
        """使用动态爬虫搜索关键词"""
        try:
            # 使用DynamicCrawler搜索东方财富股吧
            posts = []
            
            # 构建搜索URL
            search_url = f"https://so.eastmoney.com/web/s?keyword={keyword}&type=guba&pageindex=1"
            
            try:
                from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
                
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True,
                        args=['--disable-blink-features=AutomationControlled']
                    )
                    
                    page = browser.new_page()
                    page.goto(search_url, timeout=30000)
                    
                    # 等待搜索结果加载
                    time.sleep(2)
                    
                    # 获取页面HTML
                    html_content = page.content()
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # 解析搜索结果
                    result_items = soup.find_all(['div', 'li'], class_=re.compile(r'result|item|post|list'))
                    
                    for item in result_items[:limit]:
                        try:
                            # 查找标题链接
                            title_elem = item.find('a', href=True)
                            if not title_elem:
                                continue
                                
                            title = title_elem.get_text(strip=True)
                            if not title or len(title) < 5:
                                continue
                                
                            # 提取内容摘要
                            content_elem = item.find(['div', 'p'], class_=re.compile(r'content|summary|desc'))
                            content = content_elem.get_text(strip=True)[:200] if content_elem else ''
                            
                            # 提取时间
                            time_elem = item.find(['span', 'time'], class_=re.compile(r'time|date'))
                            post_time = time_elem.get_text(strip=True) if time_elem else ''
                            
                            # 只保留包含股票代码的帖子
                            full_text = f"{title} {content}"
                            if self._contains_stock_code(full_text):
                                posts.append({
                                    'title': title,
                                    'content': content,
                                    'time': post_time or '最近',
                                    'author': '股吧用户',
                                    'source': 'eastmoney_search',
                                    'platform': '东方财富股吧',
                                    'url': title_elem.get('href', '')
                                })
                                
                        except Exception as e:
                            continue
                    
                    browser.close()
                    
            except Exception as e:
                logger.debug(f"Playwright搜索失败: {e}")
            
            return posts
            
        except Exception as e:
            logger.debug(f"动态爬虫搜索 '{keyword}' 失败: {e}")
            return []

    def _search_with_api(self, keyword: str, limit: int) -> List[Dict]:
        """使用API搜索关键词"""
        posts = []
        
        try:
            # 东方财富股吧搜索
            em_posts = self._search_eastmoney_guba(keyword, limit)
            if em_posts:
                posts.extend(em_posts)
            
            # 尝试其他平台搜索
            # 同花顺搜索
            ths_posts = self._search_tonghuashun(keyword, limit // 2)
            if ths_posts:
                posts.extend(ths_posts)
                
        except Exception as e:
            logger.debug(f"API搜索 '{keyword}' 失败: {e}")
        
        return posts[:limit]
    
    def _contains_stock_code(self, text: str) -> bool:
        """检查文本是否包含股票代码"""
        for pattern in self.STOCK_CODE_PATTERNS:
            if re.search(pattern, text):
                return True
        return False
    
    def _search_tonghuashun(self, keyword: str, limit: int) -> List[Dict]:
        """搜索同花顺论坛"""
        posts = []
        try:
            # 构建同花顺搜索URL
            search_url = f"https://search.10jqka.com.cn/unifiedwap/unified/result/?keyword={keyword}&type=guba"
            
            response = self.session.get(search_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找搜索结果
            result_items = soup.find_all(['div', 'li'], class_=re.compile(r'result|item|post'))
            
            for item in result_items[:limit]:
                try:
                    title_elem = item.find(['a', 'h3'], href=True)
                    if not title_elem:
                        continue
                        
                    title = title_elem.get_text(strip=True)
                    if not title or len(title) < 5:
                        continue
                    
                    # 检查是否包含股票代码
                    if self._contains_stock_code(title):
                        posts.append({
                            'title': title,
                            'content': '',
                            'time': '最近',
                            'author': '投资者',
                            'source': 'tonghuashun_search',
                            'platform': '同花顺',
                            'url': title_elem.get('href', '')
                        })
                        
                except Exception as e:
                    continue
            
        except Exception as e:
            logger.debug(f"同花顺搜索失败: {e}")
        
        return posts

    def _is_official_announcement(self, title: str, content: str) -> bool:
        """判断是否为官方公告/已公开新闻（需要过滤）"""
        full_text = (title + ' ' + content).lower()
        
        for exclude_kw in self.EXCLUDE_KEYWORDS:
            if exclude_kw in full_text:
                return True
        
        official_patterns = [
            r'公司公告', r'交易所.*公告', r'证监会.*批准',
            r'已.*完成', r'已.*获批', r'正式.*宣布',
            r'官方.*发布', r'官宣'
        ]
        for pattern in official_patterns:
            if re.search(pattern, full_text):
                return True
        
        return False
    
    def _is_rumor_post(self, title: str, content: str) -> Tuple[bool, str]:
        """判断是否为传言/小道消息类帖子，返回(是否传言, 匹配的关键词)"""
        full_text = title + ' ' + content
        
        rumor_keywords = [
            '传闻', '据说', '听说', '小道消息', '内部消息',
            '传言', '风声', '爆料', '透露', '知情人士',
            '可能被收购', '或将重组', '有望并购', '疑似重组',
            '正在洽谈', '秘密接触', '私下协商', '暗中筹划',
            '即将公告', '近期公告', '消息称', '市场传闻',
            '坊间传闻', '有消息称', '据悉', '据透露',
            '要被收购', '将被收购', '拟被收购', '被看中',
            '接盘', '入主', '举牌', '增持', '要约收购'
        ]
        
        for kw in rumor_keywords:
            if kw in full_text:
                return True, kw
        
        return False, ''
    
    def _fetch_active_stocks(self) -> List[str]:
        """动态获取活跃股票列表（涨幅榜、跌幅榜、换手率榜等）"""
        active_stocks = set()
        
        try:
            url = "https://push2.eastmoney.com/api/qt/clist/get"
            params = {
                'cb': 'callback',
                'pn': 1,
                'pz': 50,
                'po': 1,
                'np': 1,
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                'fltt': 2,
                'invt': 2,
                'fid': 'f3',
                'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
                'fields': 'f12,f14,f2,f3,f4,f5'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 200:
                text = response.text
                match = re.search(r'callback\((.*)\)', text)
                if match:
                    data = json.loads(match.group(1))
                    diff_list = data.get('data', {}).get('diff', [])
                    for item in diff_list:
                        code = item.get('f12', '')
                        if code and len(code) == 6:
                            active_stocks.add(code)
            
            params['fid'] = 'f8'
            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 200:
                text = response.text
                match = re.search(r'callback\((.*)\)', text)
                if match:
                    data = json.loads(match.group(1))
                    diff_list = data.get('data', {}).get('diff', [])
                    for item in diff_list:
                        code = item.get('f12', '')
                        if code and len(code) == 6:
                            active_stocks.add(code)
                            
        except Exception as e:
            logger.debug(f"获取活跃股票列表失败: {e}")
        
        try:
            url = "https://guba.eastmoney.com/remenba.aspx"
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                response.encoding = 'utf-8'
                codes = re.findall(r'/list,(\d{6})\.html', response.text)
                for code in codes[:30]:
                    active_stocks.add(code)
        except Exception as e:
            logger.debug(f"获取热门股吧失败: {e}")
        
        logger.info(f"动态获取到 {len(active_stocks)} 个活跃股票")
        return list(active_stocks)
    
    def _search_eastmoney_guba(self, keyword: str, limit: int) -> List[Dict]:
        """搜索东方财富股吧 - 重点挖掘未公告的传言/小道消息"""
        posts = []
        
        active_stocks = self._fetch_active_stocks()
        
        if not active_stocks:
            logger.warning("未获取到活跃股票，使用全局股吧搜索")
            self._search_eastmoney_global_guba(keyword, limit, posts)
            return posts[:limit]
        
        rumor_signals = [
            '传闻', '据说', '听说', '小道', '内部消息', '爆料', '透露',
            '可能', '或将', '有望', '疑似', '正在洽谈', '秘密',
            '即将', '消息称', '坊间', '据悉', '据透露',
            '要被', '将被', '拟被', '被看中', '接盘', '入主',
            '大利好', '隐藏', '低估', '错杀', '价值洼地',
            '主力吸筹', '机构建仓', '游资介入', '庄家',
            '异动', '蹊跷', '有猫腻', '底部放量'
        ]
        
        try:
            for stock_code in active_stocks:
                try:
                    url = f'https://guba.eastmoney.com/list,{stock_code}.html'
                    response = self.session.get(url, timeout=10)
                    
                    if response.status_code != 200:
                        continue
                    
                    response.encoding = 'utf-8'
                    
                    match = re.search(r'var article_list=(\{.*?\});', response.text, re.DOTALL)
                    if not match:
                        continue
                    
                    data = json.loads(match.group(1))
                    article_list = data.get('re', [])
                    
                    for article in article_list:
                        title = article.get('post_title', '')
                        content = article.get('post_content', '')
                        full_text = (title + ' ' + content).lower()
                        
                        if self._is_official_announcement(title, content):
                            continue
                        
                        matched_keyword = None
                        is_rumor, rumor_kw = self._is_rumor_post(title, content)
                        
                        if keyword.lower() in full_text:
                            matched_keyword = keyword
                        elif is_rumor:
                            matched_keyword = rumor_kw
                        else:
                            for signal in rumor_signals:
                                if signal in full_text:
                                    matched_keyword = signal
                                    break
                        
                        if matched_keyword:
                            post_id = article.get('post_id', '')
                            guba_code = article.get('post_guba', {}).get('stockbar_code', stock_code)
                            post_url = f'https://guba.eastmoney.com/news,{guba_code},{post_id}.html'
                            
                            author = article.get('post_user', {}).get('user_nickname', '')
                            post_time = article.get('post_publish_time', '')
                            
                            posts.append({
                                'title': title,
                                'content': content[:500] if content else '',
                                'url': post_url,
                                'post_time': post_time,
                                'author': author if author else '股吧用户',
                                'source': 'eastmoney_guba',
                                'source_name': '东方财富股吧',
                                'platform': '东方财富股吧',
                                'matched_keyword': matched_keyword,
                                'stock_code': stock_code,
                                'is_rumor': is_rumor
                            })
                            
                            if len(posts) >= limit * 2:
                                break
                                
                except Exception as e:
                    logger.debug(f"获取{stock_code}股吧失败: {e}")
                    continue
                    
            self._search_eastmoney_global_guba(keyword, limit - len(posts), posts)
                    
        except Exception as e:
            logger.debug(f"搜索东方财富股吧失败: {e}")
        
        return posts[:limit]
    
    def _search_eastmoney_global_guba(self, keyword: str, limit: int, posts: List[Dict]) -> None:
        """搜索东方财富全局股吧（上证、深证、创业板）- 重点挖掘传言"""
        global_gubas = ['zssh000001', 'zssz399001', 'zssz399006']  # 上证、深证、创业板
        
        rumor_signals = [
            '传闻', '据说', '听说', '小道', '内部消息', '爆料', '透露',
            '可能', '或将', '有望', '疑似', '正在洽谈', '秘密',
            '即将', '消息称', '坊间', '据悉', '据透露',
            '要被', '将被', '拟被', '被看中', '接盘', '入主',
            '大利好', '隐藏', '低估', '错杀', '价值洼地',
            '主力吸筹', '机构建仓', '游资介入', '庄家',
            '异动', '蹊跷', '有猫腻', '底部放量'
        ]
        
        try:
            for guba_code in global_gubas:
                url = f'https://guba.eastmoney.com/list,{guba_code}.html'
                response = self.session.get(url, timeout=10)
                
                if response.status_code != 200:
                    continue
                
                response.encoding = 'utf-8'
                
                match = re.search(r'var article_list=(\{.*?\});', response.text, re.DOTALL)
                if not match:
                    continue
                
                data = json.loads(match.group(1))
                article_list = data.get('re', [])
                
                for article in article_list:
                    title = article.get('post_title', '')
                    content = article.get('post_content', '')
                    full_text = (title + ' ' + content).lower()
                    
                    if self._is_official_announcement(title, content):
                        continue
                    
                    matched_keyword = None
                    is_rumor, rumor_kw = self._is_rumor_post(title, content)
                    
                    if keyword.lower() in full_text:
                        matched_keyword = keyword
                    elif is_rumor:
                        matched_keyword = rumor_kw
                    else:
                        for signal in rumor_signals:
                            if signal in full_text:
                                matched_keyword = signal
                                break
                    
                    if matched_keyword:
                        post_id = article.get('post_id', '')
                        post_guba = article.get('post_guba', {}).get('stockbar_code', guba_code)
                        post_url = f'https://guba.eastmoney.com/news,{post_guba},{post_id}.html'
                        
                        author = article.get('post_user', {}).get('user_nickname', '')
                        post_time = article.get('post_publish_time', '')
                        
                        posts.append({
                            'title': title,
                            'content': content[:500] if content else '',
                            'url': post_url,
                            'post_time': post_time,
                            'author': author if author else '股吧用户',
                            'source': 'eastmoney_guba',
                            'source_name': '东方财富股吧',
                            'platform': '东方财富股吧',
                            'matched_keyword': matched_keyword,
                            'guba_type': 'global',
                            'is_rumor': is_rumor
                        })
                        
                        if len(posts) >= limit:
                            return
                        
        except Exception as e:
            logger.debug(f"搜索全局股吧失败: {e}")

    def _extract_stocks_from_posts(self, posts: List[Dict]) -> List[Dict]:
        """
        从帖子中提取股票代码并聚合分析

        Args:
            posts: 帖子列表

        Returns:
            股票机会列表
        """
        stock_data = defaultdict(lambda: {
            'mentions': [],
            'keywords_used': set(),
            'keyword_weights': [],
            'posts_count': 0,
            'total_weight': 0,
            'first_mention_time': None,
            'latest_mention_time': None,
            'sources': set(),
            'sample_posts': []
        })
        
        for post in posts:
            extracted_codes = set()
            if post.get('stock_code'):
                extracted_codes.add(post.get('stock_code'))
            
            text_codes = self._extract_stock_codes_from_text(
                post.get('title', '') + ' ' + post.get('content', '')
            )
            extracted_codes.update(text_codes)
            
            if not extracted_codes:
                continue
            
            post_time = self._parse_time(post.get('time', '') or post.get('post_time', ''))
            search_keyword = post.get('search_keyword', '') or post.get('matched_keyword', '')
            keyword_weight = post.get('keyword_weight', 1)
            
            for code in extracted_codes:
                stock_data[code]['mentions'].append(post)
                stock_data[code]['keywords_used'].add(search_keyword)
                stock_data[code]['keyword_weights'].append(keyword_weight)
                stock_data[code]['posts_count'] += 1
                stock_data[code]['total_weight'] += keyword_weight
                stock_data[code]['sources'].add(post.get('source', 'unknown'))
                
                # 更新时间范围
                if post_time:
                    if not stock_data[code]['first_mention_time'] or post_time < stock_data[code]['first_mention_time']:
                        stock_data[code]['first_mention_time'] = post_time
                    if not stock_data[code]['latest_mention_time'] or post_time > stock_data[code]['latest_mention_time']:
                        stock_data[code]['latest_mention_time'] = post_time
                
                # 保存样本帖子
                if len(stock_data[code]['sample_posts']) < 5:
                    stock_data[code]['sample_posts'].append({
                        'title': post.get('title', ''),
                        'content': post.get('content', '')[:300],
                        'url': post.get('url', post.get('link', '')),
                        'keyword': search_keyword,
                        'author': post.get('author', ''),
                        'source': post.get('source', 'eastmoney_search'),
                        'source_name': post.get('source_name', post.get('platform', '东方财富')),
                        'post_time': post_time.strftime('%Y-%m-%d %H:%M') if post_time else post.get('post_time', '')
                    })

        # 转换为结果列表
        opportunities = []
        for stock_code, data in stock_data.items():
            if data['posts_count'] >= 1:  # 至少被提及1次
                # 尝试获取股票名称
                stock_name = self._get_stock_name(stock_code)
                
                # 构建利好消息内容
                best_post = data['sample_posts'][0] if data['sample_posts'] else {}
                top_keyword = max(data['keywords_used'], key=lambda k: self._get_keyword_weight(k)) if data['keywords_used'] else ''
                
                # 生成利好标题和内容
                news_title = self._generate_news_title(stock_code, top_keyword, best_post)
                news_type = self._classify_news_type(top_keyword, best_post.get('title', ''), best_post.get('content', ''))
                news_content = self._generate_news_content(data['sample_posts'], list(data['keywords_used']))
                
                # 生成投资建议和风险提示
                investment_advice = self._generate_investment_advice(data['total_weight'], data['posts_count'])
                risk_warning = self._generate_risk_warning(top_keyword, data['posts_count'])
                
                opportunities.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'confidence_score': 0,  # 将在后面计算
                    'confidence_rating': 'C',  # 将在后面计算
                    'news_type_name': news_type,
                    'news_title': news_title,
                    'news_content': news_content,
                    'publish_time': data['latest_mention_time'].strftime('%Y-%m-%d %H:%M:%S') if data['latest_mention_time'] else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'news_source': f"论坛挖掘 ({', '.join(list(data['sources'])[:2])})",
                    'news_url': f"关键词搜索: {', '.join(list(data['keywords_used'])[:2])}",
                    'investment_advice': investment_advice,
                    'risk_warning': risk_warning,
                    # 置信度详细评分
                    'confidence': {
                        'scores': {
                            'source_reliability': min(data['posts_count'] * 20, 80),  # 基于帖子数量
                            'timeliness': self._calculate_timeliness_score(data['latest_mention_time']),
                            'content_quality': min(len(data['keywords_used']) * 25, 75),  # 基于关键词多样性
                            'market_validation': min(data['total_weight'] * 8, 70),  # 基于关键词权重
                            'historical_accuracy': 60,  # 固定值
                            'technical_alignment': min(data['posts_count'] * 15, 60)  # 基于讨论热度
                        }
                    },
                    # 原始数据保留用于调试
                    'posts_count': data['posts_count'],
                    'total_keyword_weight': data['total_weight'],
                    'avg_keyword_weight': data['total_weight'] / data['posts_count'],
                    'keywords_used': list(data['keywords_used']),
                    'sources': list(data['sources']),
                    'first_mention_time': data['first_mention_time'].isoformat() if data['first_mention_time'] else None,
                    'latest_mention_time': data['latest_mention_time'].isoformat() if data['latest_mention_time'] else None,
                    'sample_posts': data['sample_posts'],
                    'timestamp': datetime.now().isoformat(),
                    'data_source': 'keyword_forum_mining'
                })

        return opportunities

    def _get_keyword_weight(self, keyword: str) -> int:
        """获取关键词权重"""
        for tier_config in self.PRIORITY_KEYWORDS.values():
            if keyword in tier_config['keywords']:
                return tier_config['weight']
        return 1
    
    def _generate_news_title(self, stock_code: str, keyword: str, best_post: Dict) -> str:
        """生成利好标题 - 优先使用原始帖子标题"""
        post_title = best_post.get('title', '') if best_post else ''
        
        if post_title and len(post_title) > 5:
            return post_title
        
        if not keyword:
            return f"{stock_code} 论坛热议 - 投资机会关注"
        
        if '重组' in keyword or '并购' in keyword or '收购' in keyword:
            return f"{stock_code} {keyword}传言持续发酵，市场关注度提升"
        elif '订单' in keyword or '合同' in keyword:
            return f"{stock_code} 传获{keyword}消息，业绩增长可期"
        elif '政策' in keyword or '支持' in keyword:
            return f"{stock_code} 受益{keyword}东风，前景看好"
        elif '技术' in keyword or '突破' in keyword:
            return f"{stock_code} {keyword}消息引关注，创新实力凸显"
        elif '业绩' in keyword:
            return f"{stock_code} {keyword}相关消息热议，投资价值受关注"
        else:
            return f"{stock_code} 论坛热议消息，投资机会值得关注"
    
    def _classify_news_type(self, keyword: str, post_title: str = '', post_content: str = '') -> str:
        """分类利好类型 - 基于帖子内容分析"""
        full_text = (post_title + ' ' + post_content + ' ' + keyword).lower()
        
        if any(w in full_text for w in ['重组', '并购', '收购', '借壳', '注入']):
            return "重组并购"
        elif any(w in full_text for w in ['订单', '合同', '中标', '签约']):
            return "重大合同"
        elif any(w in full_text for w in ['政策', '补贴', '扶持', '支持']):
            return "政策利好"
        elif any(w in full_text for w in ['技术', '突破', '专利', '研发', '创新']):
            return "技术突破"
        elif any(w in full_text for w in ['业绩', '利润', '营收', '增长', '翻倍']):
            return "业绩利好"
        elif any(w in full_text for w in ['增持', '回购', '举牌', '大股东']):
            return "股东增持"
        elif any(w in full_text for w in ['涨停', '异动', '放量', '突破']):
            return "异动关注"
        elif any(w in full_text for w in ['送转', '分红', '派息']):
            return "分红送转"
        else:
            return "市场热议"
    
    def _generate_news_content(self, sample_posts: List[Dict], keywords: List[str]) -> str:
        """生成利好内容摘要"""
        if not sample_posts:
            return f"市场传言相关{', '.join(keywords[:2])}消息，具体内容需进一步关注官方公告。"
        
        # 提取关键信息
        key_contents = []
        for post in sample_posts[:2]:
            content = post.get('content', '').strip()
            if content and len(content) > 10:
                key_contents.append(content[:50] + "...")
        
        if key_contents:
            return "论坛消息显示：" + " | ".join(key_contents) + " 投资者对此表示关注。"
        else:
            return f"论坛出现多条关于{', '.join(keywords[:2])}的讨论，市场关注度明显提升。"
    
    def _generate_investment_advice(self, total_weight: int, posts_count: int) -> str:
        """生成投资建议"""
        if total_weight >= 30 and posts_count >= 3:
            return "关注度较高，建议密切关注官方公告，适当配置，注意仓位控制。"
        elif total_weight >= 20:
            return "论坛热议度适中，建议关注后续进展，谨慎参与。"
        elif total_weight >= 10:
            return "初步关注阶段，建议观望为主，等待更多确认信息。"
        else:
            return "关注度较低，建议持续跟踪，不建议盲目参与。"
    
    def _generate_risk_warning(self, keyword: str, posts_count: int) -> str:
        """生成风险提示"""
        base_warning = "论坛消息真实性待确认，投资需谨慎。"
        
        if '重组' in keyword or '并购' in keyword:
            return f"{base_warning}重组类消息风险较高，需等待正式公告。"
        elif posts_count <= 2:
            return f"{base_warning}讨论热度较低，消息可能不实。"
        elif '业绩' in keyword:
            return f"{base_warning}业绩消息需以正式财报为准。"
        else:
            return f"{base_warning}市场波动较大，注意控制风险。"
    
    def _calculate_timeliness_score(self, latest_time: Optional[datetime]) -> int:
        """计算时效性得分"""
        if not latest_time:
            return 30
        
        hours_ago = (datetime.now() - latest_time).total_seconds() / 3600
        
        if hours_ago <= 2:
            return 90
        elif hours_ago <= 6:
            return 80
        elif hours_ago <= 24:
            return 70
        elif hours_ago <= 48:
            return 60
        else:
            return 40

    def _extract_stock_codes_from_text(self, text: str) -> Set[str]:
        """从文本中提取股票代码"""
        codes = set()
        
        for pattern in self.STOCK_CODE_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                # 清理和标准化代码
                code = re.sub(r'[^0-9]', '', match)
                if len(code) == 6:
                    # 验证股票代码格式
                    if code.startswith(('000', '001', '002', '003')):  # 深市主板/中小板/创业板
                        codes.add(code)
                    elif code.startswith(('300', '301')):  # 创业板
                        codes.add(code)
                    elif code.startswith('600'):  # 沪市主板
                        codes.add(code)
                    elif code.startswith('601'):  # 沪市主板
                        codes.add(code)
                    elif code.startswith('603'):  # 沪市主板
                        codes.add(code)
                    elif code.startswith('688'):  # 科创板
                        codes.add(code)
                    elif code.startswith('689'):  # 科创板
                        codes.add(code)
        
        return codes

    def _get_stock_name(self, stock_code: str) -> str:
        """获取股票名称 - 从东方财富API动态获取"""
        try:
            if hasattr(self, '_stock_name_cache'):
                cache = self._stock_name_cache
            else:
                cache = self._stock_name_cache = {}
            
            if stock_code in cache:
                return cache[stock_code]
            
            market = '1' if stock_code.startswith(('6', '9')) else '0'
            url = f"https://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': f"{market}.{stock_code}",
                'fields': 'f57,f58'
            }
            
            response = self.session.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json().get('data', {})
                if data and data.get('f58'):
                    name = data.get('f58', '')
                    cache[stock_code] = name
                    return name
            
            cache[stock_code] = f'股票{stock_code}'
            return f'股票{stock_code}'
            
        except Exception as e:
            logger.debug(f"获取{stock_code}名称失败: {e}")
            return f"股票{stock_code}"

    def _parse_time(self, time_str: str) -> Optional[datetime]:
        """解析时间字符串"""
        if not time_str:
            return None
            
        try:
            # 处理相对时间
            if '分钟前' in time_str:
                minutes = int(re.search(r'(\d+)', time_str).group(1))
                return datetime.now() - timedelta(minutes=minutes)
            elif '小时前' in time_str:
                hours = int(re.search(r'(\d+)', time_str).group(1))
                return datetime.now() - timedelta(hours=hours)
            elif '天前' in time_str:
                days = int(re.search(r'(\d+)', time_str).group(1))
                return datetime.now() - timedelta(days=days)
            elif '昨天' in time_str:
                return datetime.now() - timedelta(days=1)
            elif '前天' in time_str:
                return datetime.now() - timedelta(days=2)
            else:
                # 尝试解析绝对时间
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%m-%d %H:%M']:
                    try:
                        return datetime.strptime(time_str, fmt)
                    except ValueError:
                        continue
        except Exception:
            pass
        
        return datetime.now()

    def _calculate_confidence_score(self, opportunity: Dict) -> float:
        """计算置信度评分 (0-100)"""
        score = 0
        
        # 基础分：提及次数 (最高30分)
        posts_count = opportunity.get('posts_count', 0)
        score += min(posts_count * 10, 30)
        
        # 关键词权重分 (最高40分)
        avg_weight = opportunity.get('avg_keyword_weight', 0)
        score += min(avg_weight * 4, 40)
        
        # 关键词多样性分 (最高15分)
        keywords_count = len(opportunity.get('keywords_used', []))
        score += min(keywords_count * 5, 15)
        
        # 数据源多样性分 (最高10分)
        sources_count = len(opportunity.get('sources', []))
        score += min(sources_count * 5, 10)
        
        # 时效性加分 (最高5分)
        latest_time_str = opportunity.get('latest_mention_time')
        if latest_time_str:
            try:
                latest_time = datetime.fromisoformat(latest_time_str.replace('Z', '+00:00'))
                hours_ago = (datetime.now() - latest_time.replace(tzinfo=None)).total_seconds() / 3600
                if hours_ago <= 24:
                    score += 5
                elif hours_ago <= 48:
                    score += 3
            except Exception:
                pass
        
        return min(score, 100)

    def _get_confidence_rating(self, score: float) -> str:
        """根据分数获取置信度等级"""
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

    def _print_mining_summary(self, results: List[Dict], keyword_stats: Dict):
        """打印挖掘结果摘要"""
        logger.info("\n" + "=" * 70)
        logger.info("📊 关键词论坛挖掘结果摘要")
        logger.info("=" * 70)
        
        total_opportunities = len(results)
        s_level = [r for r in results if r.get('confidence_rating') == 'S']
        a_plus_level = [r for r in results if r.get('confidence_rating') == 'A+']
        a_level = [r for r in results if r.get('confidence_rating') == 'A']
        b_level = [r for r in results if r.get('confidence_rating') == 'B']

        logger.info(f"发现投资机会总数: {total_opportunities}")
        logger.info(f"S级 (极高置信度): {len(s_level)}")
        logger.info(f"A+级 (高置信度): {len(a_plus_level)}")
        logger.info(f"A级 (较高置信度): {len(a_level)}")
        logger.info(f"B级 (中等置信度): {len(b_level)}")

        # 关键词效果统计
        logger.info(f"\n🔍 关键词搜索效果:")
        effective_keywords = {k: v for k, v in keyword_stats.items() if v.get('posts_found', 0) > 0}
        for keyword, stats in sorted(effective_keywords.items(), key=lambda x: x[1]['posts_found'], reverse=True)[:5]:
            logger.info(f"  '{keyword}': {stats['posts_found']} 条帖子")

        if s_level or a_plus_level:
            logger.info("\n🏆 TOP 5 推荐:")
            top_stocks = results[:5]
            for idx, result in enumerate(top_stocks, 1):
                stock_code = result.get('stock_code', '')
                stock_name = result.get('stock_name', '')
                score = result.get('confidence_score', 0)
                rating = result.get('confidence_rating', 'C')
                keywords = ', '.join(result.get('keywords_used', [])[:2])
                logger.info(f"  {idx}. {stock_code} {stock_name} - {rating}级 ({score:.1f}分)")
                logger.info(f"     关键词: {keywords}")

        logger.info("=" * 70)