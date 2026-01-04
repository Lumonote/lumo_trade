#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多平台财经新闻挖掘系统 v1.0
=========================

整合多个主流财经网站进行全方位信息挖掘:
- 东方财富 (Eastmoney) - 股吧、快讯、研报
- 雪球 (Xueqiu) - 社区讨论、热帖
- 财联社 (cls.cn) - 电报快讯、独家新闻
- 巨潮资讯 (cninfo.com.cn) - 官方公告、信息披露
- 韭研公社 (jiuyangongshe) - 投研社区
- 新浪财经 (Sina Finance) - 财经新闻、市场动态

核心理念: 多源交叉验证，提高信息可靠性
"""

import os
import sys
import re
import json
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MultiPlatformNewsMiner:
    """多平台财经新闻挖掘器"""
    
    PRIORITY_KEYWORDS = {
        'tier_0': {
            'keywords': [
                '传闻', '据说', '听说', '小道消息', '内部消息',
                '传言', '风声', '爆料', '透露', '知情人士',
                '可能被收购', '或将重组', '有望并购', '疑似重组',
                '正在洽谈', '秘密接触', '私下协商', '暗中筹划',
                '即将公告', '近期公告', '消息称', '市场传闻',
                '未经证实', '待确认', '尚未披露'
            ],
            'weight': 12,
            'search_priority': 0
        },
        'tier_1': {
            'keywords': [
                '拟重组', '拟并购', '拟收购', '筹划重组',
                '计划收购', '酝酿并购', '洽谈合作',
                '或将入股', '有望合作', '可能入主'
            ],
            'weight': 11,
            'search_priority': 1
        },
        'tier_2': {
            'keywords': [
                '隐藏利好', '潜在利好', '未挖掘',
                '严重低估', '价值洼地', '错杀', '超跌',
                '机构悄悄建仓', '主力暗中吸筹'
            ],
            'weight': 10,
            'search_priority': 2
        },
        'tier_3': {
            'keywords': [
                '即将中标', '有望签约', '洽谈订单',
                '接近达成', '谈判中', '协商中'
            ],
            'weight': 9,
            'search_priority': 3
        }
    }
    
    EXCLUDE_KEYWORDS = [
        '广告', '推广', '开户', '荐股', '老师带',
        '保证盈利', '稳赚', '内幕股', '黑马'
    ]
    
    STOCK_CODE_PATTERNS = [
        r'\b([0-9]{6})\b',
        r'([0-9]{6})\.SZ',
        r'([0-9]{6})\.SH',
        r'SZ([0-9]{6})',
        r'SH([0-9]{6})',
    ]

    def __init__(self):
        """初始化多平台挖掘器"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        })
        self._stock_name_cache = {}
        
    def mine_all_platforms(self, keyword_limit: int = 15, posts_per_platform: int = 30) -> List[Dict]:
        """
        全平台挖掘财经信息
        
        Args:
            keyword_limit: 每个平台搜索的关键词数量
            posts_per_platform: 每个平台获取的帖子数量
            
        Returns:
            挖掘到的投资机会列表
        """
        logger.info("=" * 70)
        logger.info("🌐 启动多平台财经信息挖掘系统")
        logger.info("=" * 70)
        
        all_posts = []
        platform_stats = {}
        
        platforms = [
            ('eastmoney', '东方财富', self._mine_eastmoney),
            ('xueqiu', '雪球', self._mine_xueqiu),
            ('cls', '财联社', self._mine_cls),
            ('cninfo', '巨潮资讯', self._mine_cninfo),
            ('sina', '新浪财经', self._mine_sina),
            ('jiuyan', '韭研公社', self._mine_jiuyan),
        ]
        
        for platform_id, platform_name, mine_func in platforms:
            logger.info(f"\n📱 正在挖掘 {platform_name}...")
            try:
                posts = mine_func(keyword_limit, posts_per_platform)
                if posts:
                    all_posts.extend(posts)
                    platform_stats[platform_name] = len(posts)
                    logger.info(f"  ✓ {platform_name}: 获取 {len(posts)} 条信息")
                else:
                    platform_stats[platform_name] = 0
                    logger.info(f"  - {platform_name}: 未获取到信息")
            except Exception as e:
                platform_stats[platform_name] = 0
                logger.warning(f"  ✗ {platform_name} 挖掘失败: {e}")
            
            time.sleep(1)
        
        logger.info(f"\n📊 各平台挖掘统计:")
        for platform, count in platform_stats.items():
            logger.info(f"  {platform}: {count} 条")
        logger.info(f"  总计: {len(all_posts)} 条")
        
        opportunities = self._aggregate_and_analyze(all_posts)
        
        return opportunities
    
    def _mine_eastmoney(self, keyword_limit: int, posts_limit: int) -> List[Dict]:
        """挖掘东方财富 - 新闻搜索、快讯、股吧"""
        posts = []
        
        posts.extend(self._mine_eastmoney_news_search(keyword_limit, posts_limit // 2))
        
        posts.extend(self._mine_eastmoney_kuaixun_filtered(posts_limit // 4))
        
        posts.extend(self._mine_eastmoney_guba(keyword_limit, posts_limit // 4))
        
        return posts
    
    def _mine_eastmoney_news_search(self, keyword_limit: int, limit: int) -> List[Dict]:
        """东方财富新闻搜索 - 专注传闻/未公告信息"""
        posts = []
        
        search_keywords = [
            '传闻 重组', '传闻 收购', '传闻 并购', '消息称 重组',
            '知情人士 收购', '或将 重组', '有望 并购', '拟 收购',
            '洽谈 合作', '筹划 重组', '秘密 收购', '私下 并购',
            '小道消息', '内部消息 利好', '未经证实 重组',
            '疑似 重组', '可能 收购', '计划 并购',
            '即将 公告', '近期 重组', '酝酿 收购'
        ]
        
        for keyword in search_keywords[:keyword_limit]:
            for page in range(1, 4):
                try:
                    url = "https://search-api-web.eastmoney.com/search/jsonp"
                    params = {
                        'cb': 'jQuery_callback',
                        'param': json.dumps({
                            'uid': '',
                            'keyword': keyword,
                            'type': ['cmsArticleWebOld'],
                            'client': 'web',
                            'clientType': 'web',
                            'clientVersion': 'curr',
                            'param': {
                                'cmsArticleWebOld': {
                                    'searchScope': 'default',
                                    'sort': 'default',
                                    'pageIndex': page,
                                    'pageSize': 30,
                                    'preTag': '',
                                    'postTag': ''
                                }
                            }
                        })
                    }
                    
                    response = self.session.get(url, params=params, timeout=10)
                    if response.status_code == 200:
                        text = response.text
                        json_match = re.search(r'jQuery_callback\((.*)\)', text)
                        if json_match:
                            data = json.loads(json_match.group(1))
                            results = data.get('result', {}).get('cmsArticleWebOld', [])
                            
                            if not results:
                                break
                            
                            for item in results:
                                title = item.get('title', '')
                                title = re.sub(r'<[^>]+>', '', title)
                                content = item.get('content', '') or ''
                                content = re.sub(r'<[^>]+>', '', content)
                                
                                if not title or len(title) < 5:
                                    continue
                                
                                news_type, score = self._classify_news_type_strict([], title, content)
                                if score < 65:
                                    continue
                                
                                posts.append({
                                    'title': title,
                                    'content': content[:500],
                                    'url': item.get('url', ''),
                                    'post_time': item.get('date', ''),
                                    'author': item.get('mediaName', '东方财富'),
                                    'source': 'eastmoney_news_search',
                                    'source_name': '东方财富新闻',
                                    'platform': '东方财富',
                                    'search_keyword': keyword
                                })
                                
                    time.sleep(0.15)
                except Exception as e:
                    logger.debug(f"搜索新闻关键词 '{keyword}' 页{page}失败: {e}")
                    break
        
        seen_titles = set()
        unique_posts = []
        for p in posts:
            title_key = p['title'][:30]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_posts.append(p)
        
        return unique_posts[:limit]
    
    def _mine_eastmoney_kuaixun_filtered(self, limit: int) -> List[Dict]:
        """东方财富快讯 - 筛选重大事件"""
        posts = []
        try:
            url = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"
            params = {
                'client': 'web',
                'biz': 'web_724',
                'fastColumn': 'news',
                'sortEnd': '',
                'pageSize': limit * 5,
                'type': 1
            }
            
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                news_list = data.get('data', {}).get('fastNewsList', [])
                
                for news in news_list:
                    title = news.get('title', '')
                    content = news.get('digest', '') or news.get('summary', '') or title
                    
                    if title:
                        if self._is_major_event_news(title, content):
                            posts.append({
                                'title': title,
                                'content': content[:500],
                                'url': news.get('url', ''),
                                'post_time': news.get('showTime', ''),
                                'author': '东方财富快讯',
                                'source': 'eastmoney_kuaixun',
                                'source_name': '东方财富快讯',
                                'platform': '东方财富'
                            })
                        
                        if len(posts) >= limit:
                            break
        except Exception as e:
            logger.debug(f"东方财富快讯挖掘失败: {e}")
        
        return posts
    
    def _mine_eastmoney_guba_keywords(self, keyword_limit: int, limit: int) -> List[Dict]:
        """东方财富股吧 - 基于关键词搜索传闻/重大事件"""
        posts = []
        
        search_keywords = self._get_search_keywords(keyword_limit)
        
        for keyword in search_keywords:
            try:
                keyword_posts = self._search_eastmoney_guba_keyword(keyword, limit // len(search_keywords) + 1)
                posts.extend(keyword_posts)
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"搜索关键词 '{keyword}' 失败: {e}")
                continue
        
        return posts[:limit]
    
    def _get_search_keywords(self, limit: int) -> List[str]:
        """获取搜索关键词列表 - 按优先级排序"""
        all_keywords = []
        
        for tier_config in sorted(self.PRIORITY_KEYWORDS.values(), key=lambda x: x['search_priority']):
            all_keywords.extend(tier_config['keywords'])
        
        return all_keywords[:limit]
    
    def _search_eastmoney_guba_keyword(self, keyword: str, limit: int) -> List[Dict]:
        """搜索东方财富股吧特定关键词 - 使用JSON API"""
        posts = []
        try:
            search_url = "https://search-api-web.eastmoney.com/search/jsonp"
            params = {
                'cb': 'jQuery_callback',
                'param': json.dumps({
                    'uid': '',
                    'keyword': keyword,
                    'type': ['cmsArticleWebOld'],
                    'client': 'web',
                    'clientType': 'web',
                    'clientVersion': 'curr',
                    'param': {
                        'cmsArticleWebOld': {
                            'searchScope': 'default',
                            'sort': 'default',
                            'pageIndex': 1,
                            'pageSize': 30,
                            'preTag': '',
                            'postTag': ''
                        }
                    }
                })
            }
            
            response = self.session.get(search_url, params=params, timeout=10)
            if response.status_code == 200:
                text = response.text
                json_match = re.search(r'jQuery_callback\((.*)\)', text)
                if json_match:
                    data = json.loads(json_match.group(1))
                    results = data.get('result', {}).get('cmsArticleWebOld', [])
                    
                    for item in results[:limit]:
                        title = item.get('title', '')
                        title = re.sub(r'<[^>]+>', '', title)
                        content = item.get('content', '') or item.get('summary', '')
                        content = re.sub(r'<[^>]+>', '', content)
                        
                        if not title or len(title) < 5:
                            continue
                        
                        if self._is_official_announcement(title, content):
                            continue
                        
                        posts.append({
                            'title': title,
                            'content': content[:500],
                            'url': item.get('url', ''),
                            'post_time': item.get('date', ''),
                            'author': item.get('mediaName', '股吧用户'),
                            'source': 'eastmoney_guba_search',
                            'source_name': '东方财富股吧搜索',
                            'platform': '东方财富',
                            'search_keyword': keyword
                        })
        except Exception as e:
            logger.debug(f"搜索东方财富关键词 '{keyword}' 失败: {e}")
        
        if not posts:
            try:
                alt_url = "https://guba.eastmoney.com/interface/GetData.aspx"
                params = {
                    'path': 'search/api/Info/Search',
                    'searchtext': keyword,
                    'type': 1,
                    'pageindex': 1,
                    'pagesize': 30,
                    'sort': 1
                }
                
                response = self.session.get(alt_url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('Data', {}).get('Result', [])
                    
                    for item in results[:limit]:
                        title = item.get('Title', '')
                        content = item.get('Content', '') or item.get('Summary', '')
                        
                        if not title or len(title) < 5:
                            continue
                            
                        if self._is_official_announcement(title, content):
                            continue
                        
                        posts.append({
                            'title': title,
                            'content': content[:500],
                            'url': f"https://guba.eastmoney.com/news,{item.get('guba', '')},{item.get('PostId', '')}.html",
                            'post_time': item.get('PostDate', ''),
                            'author': item.get('UserName', '股吧用户'),
                            'source': 'eastmoney_guba_search',
                            'source_name': '东方财富股吧搜索',
                            'platform': '东方财富',
                            'search_keyword': keyword
                        })
            except Exception as e:
                logger.debug(f"备用搜索关键词 '{keyword}' 失败: {e}")
        
        return posts
    
    def _is_major_event_news(self, title: str, content: str, strict: bool = True) -> bool:
        """判断是否为重大事件新闻
        
        Args:
            title: 标题
            content: 内容
            strict: 严格模式，只保留真正的重大事件传闻
        """
        if not title and not content:
            return False
            
        full_text = (title + ' ' + content).lower()
        
        exclude_patterns = [
            r'^涨幅榜', r'^跌幅榜', r'^换手率榜', r'^龙虎榜',
            r'今日涨幅', r'今日跌幅', r'今日涨停', r'今日跌停',
            r'大盘收报', r'上证指数.*点', r'收盘.*点',
            r'盘中.*涨', r'盘中.*跌', r'午盘.*点',
            r'热门股', r'人气股', r'资金流入', r'资金流出',
            r'成交额', r'成交量', r'换手率',
            r'技术分析', r'K线', r'均线', r'MACD',
            r'开户', r'荐股', r'老师', r'带你',
            r'涨停板', r'连板', r'封板'
        ]
        
        for pattern in exclude_patterns:
            if re.search(pattern, full_text):
                return False
        
        major_event_keywords = [
            '传闻', '据说', '听说', '小道消息', '内部消息',
            '传言', '风声', '爆料', '透露', '知情人士',
            '可能被收购', '或将重组', '有望并购', '疑似重组',
            '正在洽谈', '秘密接触', '私下协商', '暗中筹划',
            '即将公告', '近期公告', '消息称', '市场传闻',
            '重组', '并购', '收购', '借壳', '注入资产',
            '战略入股', '引入战投', '混改', '国资入场',
            '举牌', '要约收购', '入主',
            '重大合同', '大订单', '重大订单', '巨额订单',
            '中标', '签约', '独家供应', '进入供应链',
            '战略合作', '深度合作', '独家合作',
            '资产注入', '股权转让', '控股权',
            '停牌', '重大事项', '筹划重大',
            '特大利好', '重磅利好', '隐藏利好'
        ]
        
        for keyword in major_event_keywords:
            if keyword in full_text:
                return True
        
        if not strict:
            secondary_keywords = [
                '增持', '回购', '大股东', '实控人',
                '获得认证', '通过验证', '纳入',
                '政策利好', '补贴', '扶持',
                '扩产', '投产', '达产'
            ]
            for keyword in secondary_keywords:
                if keyword in full_text:
                    return True
        
        return False
    
    def _is_official_announcement(self, title: str, content: str) -> bool:
        """判断是否为官方已公告信息（只过滤明确的已完成事项）"""
        full_text = (title + ' ' + content).lower()
        
        completed_keywords = [
            '已完成', '已获批', '已通过', '已实施',
            '完成交割', '正式生效'
        ]
        
        for kw in completed_keywords:
            if kw in full_text:
                return True
        
        return False
    
    def _mine_eastmoney_guba(self, keyword_limit: int, limit: int) -> List[Dict]:
        """东方财富股吧热帖 - 筛选包含重大事件关键词的帖子"""
        posts = []
        try:
            hot_gubas = ['zssh000001', 'zssz399001', 'zssz399006']
            
            for guba_code in hot_gubas:
                try:
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
                        content = article.get('post_content', '') or title
                        
                        if not title:
                            continue
                        
                        if not self._is_major_event_news(title, content):
                            continue
                        
                        post_id = article.get('post_id', '')
                        post_guba = article.get('post_guba', {}).get('stockbar_code', guba_code)
                        post_url = f'https://guba.eastmoney.com/news,{post_guba},{post_id}.html'
                        
                        posts.append({
                            'title': title,
                            'content': content[:500],
                            'url': post_url,
                            'post_time': article.get('post_publish_time', ''),
                            'author': article.get('post_user', {}).get('user_nickname', '股吧用户'),
                            'source': 'eastmoney_guba',
                            'source_name': '东方财富股吧',
                            'platform': '东方财富'
                        })
                        
                        if len(posts) >= limit:
                            break
                            
                except Exception as e:
                    logger.debug(f"获取{guba_code}股吧失败: {e}")
                    continue
                    
        except Exception as e:
            logger.debug(f"东方财富股吧挖掘失败: {e}")
        
        return posts
    
    
    def _mine_xueqiu(self, keyword_limit: int, posts_limit: int) -> List[Dict]:
        """挖掘雪球 - 专注传闻/重大事件讨论"""
        posts = []
        
        try:
            self.session.get('https://xueqiu.com/', timeout=10)
            time.sleep(0.5)
        except:
            pass
        
        major_keywords = [
            '传闻', '重组', '并购', '收购', '中标', '大订单',
            '战略合作', '资产注入', '借壳', '举牌'
        ]
        
        for keyword in major_keywords[:keyword_limit]:
            try:
                url = "https://xueqiu.com/query/v1/search/status.json"
                params = {
                    'q': keyword,
                    'count': 10,
                    'comment': 0,
                    'symbol': '',
                    'hl': 'true',
                    'source': 'all',
                    'sort': 'time',
                    'page': 1
                }
                
                headers = {
                    'Referer': 'https://xueqiu.com/',
                    'X-Requested-With': 'XMLHttpRequest'
                }
                
                response = self.session.get(url, params=params, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get('list', [])
                    
                    for item in items:
                        title = item.get('title', '') or item.get('description', '')[:100]
                        content = item.get('text', '') or item.get('description', '')
                        content = re.sub(r'<[^>]+>', '', content)
                        title = re.sub(r'<[^>]+>', '', title)
                        
                        if not self._is_major_event_news(title, content):
                            continue
                        
                        if self._is_official_announcement(title, content):
                            continue
                        
                        status_id = item.get('id', '')
                        user_id = item.get('user', {}).get('id', '') if item.get('user') else ''
                        
                        posts.append({
                            'title': title[:200],
                            'content': content[:500],
                            'url': f'https://xueqiu.com/{user_id}/{status_id}' if status_id and user_id else '',
                            'post_time': self._format_timestamp(item.get('created_at', 0)),
                            'author': item.get('user', {}).get('screen_name', '雪球用户') if item.get('user') else '雪球用户',
                            'source': 'xueqiu_search',
                            'source_name': '雪球搜索',
                            'platform': '雪球',
                            'search_keyword': keyword
                        })
                        
                time.sleep(0.3)
            except Exception as e:
                logger.debug(f"雪球搜索关键词 '{keyword}' 失败: {e}")
                continue
        
        try:
            url = "https://xueqiu.com/statuses/hot/listV2.json"
            params = {
                'since_id': -1,
                'max_id': -1,
                'size': posts_limit * 2
            }
            
            headers = {
                'Referer': 'https://xueqiu.com/',
                'X-Requested-With': 'XMLHttpRequest'
            }
            
            response = self.session.get(url, params=params, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                
                for item in items:
                    original = item.get('original_status', {}) or item
                    title = original.get('title', '') or original.get('description', '')[:100]
                    content = original.get('text', '') or original.get('description', '')
                    
                    content = re.sub(r'<[^>]+>', '', content)
                    
                    if not self._is_major_event_news(title, content):
                        continue
                    
                    if self._is_official_announcement(title, content):
                        continue
                    
                    status_id = original.get('id', '')
                    user_id = original.get('user', {}).get('id', '')
                    
                    posts.append({
                        'title': title[:200],
                        'content': content[:500],
                        'url': f'https://xueqiu.com/{user_id}/{status_id}' if status_id else '',
                        'post_time': self._format_timestamp(original.get('created_at', 0)),
                        'author': original.get('user', {}).get('screen_name', '雪球用户'),
                        'source': 'xueqiu_hot',
                        'source_name': '雪球热帖',
                        'platform': '雪球',
                        'likes': original.get('like_count', 0),
                        'comments': original.get('reply_count', 0)
                    })
                    
                    if len(posts) >= posts_limit:
                        break
                        
        except Exception as e:
            logger.debug(f"雪球热帖挖掘失败: {e}")
        
        try:
            url = "https://xueqiu.com/statuses/livenews/list.json"
            params = {
                'since_id': -1,
                'max_id': -1,
                'count': posts_limit
            }
            
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', {}).get('items', []) or data.get('items', [])
                
                for item in items:
                    title = item.get('title', '') or item.get('text', '')[:100]
                    content = item.get('text', '') or item.get('description', '')
                    content = re.sub(r'<[^>]+>', '', content)
                    
                    if not self._is_major_event_news(title, content):
                        continue
                    
                    if self._is_official_announcement(title, content):
                        continue
                    
                    posts.append({
                        'title': title[:200],
                        'content': content[:500],
                        'url': item.get('target', ''),
                        'post_time': self._format_timestamp(item.get('created_at', 0)),
                        'author': '雪球7x24',
                        'source': 'xueqiu_live',
                        'source_name': '雪球7x24快讯',
                        'platform': '雪球'
                    })
                        
        except Exception as e:
            logger.debug(f"雪球快讯挖掘失败: {e}")
        
        return posts
    
    def _mine_cls(self, keyword_limit: int, posts_limit: int) -> List[Dict]:
        """挖掘财联社 - 专注传闻/重大事件电报"""
        posts = []
        
        try:
            url = "https://www.cls.cn/telegraph"
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                response.encoding = 'utf-8'
                
                pattern = r'"content":"(.*?)","in_roll"'
                matches = re.findall(pattern, response.text)
                
                for content in matches[:posts_limit * 3]:
                    content = content.replace('\\n', ' ').replace('\\r', '')
                    content = re.sub(r'<[^>]+>', '', content)
                    
                    title_match = re.search(r'【(.*?)】', content)
                    title = title_match.group(1) if title_match else content[:50]
                    
                    if not self._is_major_event_news(title, content):
                        continue
                    
                    if self._is_official_announcement(title, content):
                        continue
                    
                    posts.append({
                        'title': title[:200],
                        'content': content[:500],
                        'url': 'https://www.cls.cn/telegraph',
                        'post_time': '',
                        'author': '财联社',
                        'source': 'cls_telegraph',
                        'source_name': '财联社电报',
                        'platform': '财联社'
                    })
                    
                    if len(posts) >= posts_limit:
                        break
                        
        except Exception as e:
            logger.debug(f"财联社电报挖掘失败: {e}")
        
        try:
            url = "https://www.cls.cn/api/depth"
            params = {
                'app': 'CailianpressWeb',
                'os': 'web'
            }
            
            data = {
                'depth_type': 1,
                'rn': posts_limit
            }
            
            response = self.session.post(url, params=params, json=data, timeout=15)
            if response.status_code == 200:
                result = response.json()
                items = result.get('data', {}).get('depth_list', [])
                
                for item in items:
                    title = item.get('title', '')
                    content = item.get('brief', '') or item.get('content', '')
                    content = re.sub(r'<[^>]+>', '', content)
                    
                    if not self._is_major_event_news(title, content):
                        continue
                    
                    if self._is_official_announcement(title, content):
                        continue
                    
                    posts.append({
                        'title': title[:200],
                        'content': content[:500],
                        'url': f"https://www.cls.cn/depth/{item.get('id', '')}",
                        'post_time': self._format_timestamp(item.get('ctime', 0)),
                        'author': item.get('author', {}).get('name', '财联社'),
                        'source': 'cls_depth',
                        'source_name': '财联社深度',
                        'platform': '财联社'
                    })
                        
        except Exception as e:
            logger.debug(f"财联社深度挖掘失败: {e}")
        
        return posts
    
    def _mine_cninfo(self, keyword_limit: int, posts_limit: int) -> List[Dict]:
        """巨潮资讯 - 跳过，因为是已公告信息，不符合挖掘未公告传闻的目标"""
        return []
    
    def _mine_sina(self, keyword_limit: int, posts_limit: int) -> List[Dict]:
        """挖掘新浪财经 - 专注传闻/重大事件新闻"""
        posts = []
        
        try:
            url = "https://feed.mix.sina.com.cn/api/roll/get"
            params = {
                'pageid': '153',
                'lid': '2516',
                'k': '',
                'num': posts_limit * 2,
                'page': 1,
                'r': str(time.time())
            }
            
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                items = data.get('result', {}).get('data', [])
                
                for item in items:
                    title = item.get('title', '')
                    content = item.get('intro', '') or item.get('summary', '')
                    
                    if not self._is_major_event_news(title, content):
                        continue
                    
                    if self._is_official_announcement(title, content):
                        continue
                    
                    posts.append({
                        'title': title[:200],
                        'content': content[:500],
                        'url': item.get('url', ''),
                        'post_time': self._format_timestamp(item.get('ctime', 0)),
                        'author': item.get('media_name', '新浪财经'),
                        'source': 'sina_finance',
                        'source_name': '新浪财经',
                        'platform': '新浪财经'
                    })
                    
                    if len(posts) >= posts_limit:
                        break
                        
        except Exception as e:
            logger.debug(f"新浪财经新闻挖掘失败: {e}")
        
        try:
            url = "https://finance.sina.com.cn/7x24/"
            response = self.session.get(url, timeout=15)
            
            if response.status_code == 200:
                response.encoding = 'utf-8'
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('div', class_=re.compile(r'bd_i|item'))
                
                for item in items[:posts_limit]:
                    try:
                        content_elem = item.find(['p', 'div'], class_=re.compile(r'bd_i_txt|content'))
                        if content_elem:
                            content = content_elem.get_text(strip=True)
                            
                            if not self._is_major_event_news('', content):
                                continue
                            
                            if self._is_official_announcement('', content):
                                continue
                            
                            time_elem = item.find(['span', 'div'], class_=re.compile(r'time|date'))
                            post_time = time_elem.get_text(strip=True) if time_elem else ''
                            
                            posts.append({
                                'title': content[:100],
                                'content': content[:500],
                                'url': 'https://finance.sina.com.cn/7x24/',
                                'post_time': post_time,
                                'author': '新浪7x24',
                                'source': 'sina_7x24',
                                'source_name': '新浪财经7x24',
                                'platform': '新浪财经'
                            })
                    except Exception:
                        continue
                        
        except Exception as e:
            logger.debug(f"新浪财经7x24挖掘失败: {e}")
        
        return posts
    
    def _mine_jiuyan(self, keyword_limit: int, posts_limit: int) -> List[Dict]:
        """挖掘韭研公社 - 专注传闻/重大事件投研内容"""
        posts = []
        
        try:
            url = "https://www.jiuyangongshe.com/api/posts"
            params = {
                'page': 1,
                'limit': posts_limit * 2,
                'sort': 'hot'
            }
            
            headers = {
                'Referer': 'https://www.jiuyangongshe.com/',
                'Origin': 'https://www.jiuyangongshe.com'
            }
            
            response = self.session.get(url, params=params, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', {}).get('list', []) or data.get('list', [])
                
                for item in items:
                    title = item.get('title', '')
                    content = item.get('content', '') or item.get('summary', '')
                    content = re.sub(r'<[^>]+>', '', content)
                    
                    if not self._is_major_event_news(title, content):
                        continue
                    
                    if self._is_official_announcement(title, content):
                        continue
                    
                    posts.append({
                        'title': title[:200],
                        'content': content[:500],
                        'url': f"https://www.jiuyangongshe.com/post/{item.get('id', '')}",
                        'post_time': item.get('created_at', '') or item.get('publish_time', ''),
                        'author': item.get('author', {}).get('nickname', '韭研用户'),
                        'source': 'jiuyan_post',
                        'source_name': '韭研公社',
                        'platform': '韭研公社',
                        'likes': item.get('like_count', 0),
                        'views': item.get('view_count', 0)
                    })
                    
                    if len(posts) >= posts_limit:
                        break
                        
        except Exception as e:
            logger.debug(f"韭研公社API挖掘失败: {e}")
        
        try:
            url = "https://www.jiuyangongshe.com/"
            response = self.session.get(url, timeout=15)
            
            if response.status_code == 200:
                response.encoding = 'utf-8'
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all(['div', 'article'], class_=re.compile(r'post|article|item'))
                
                for item in items[:posts_limit]:
                    try:
                        title_elem = item.find(['h2', 'h3', 'a'], class_=re.compile(r'title'))
                        if title_elem:
                            title = title_elem.get_text(strip=True)
                            
                            content_elem = item.find(['p', 'div'], class_=re.compile(r'content|summary|desc'))
                            content = content_elem.get_text(strip=True) if content_elem else ''
                            
                            if not self._is_major_event_news(title, content):
                                continue
                            
                            if self._is_official_announcement(title, content):
                                continue
                            
                            link = title_elem.get('href', '') if title_elem.name == 'a' else ''
                            if link and not link.startswith('http'):
                                link = f"https://www.jiuyangongshe.com{link}"
                            
                            posts.append({
                                'title': title[:200],
                                'content': content[:500],
                                'url': link,
                                'post_time': '',
                                'author': '韭研公社',
                                'source': 'jiuyan_web',
                                'source_name': '韭研公社',
                                'platform': '韭研公社'
                            })
                    except Exception:
                        continue
                        
        except Exception as e:
            logger.debug(f"韭研公社网页挖掘失败: {e}")
        
        return posts
    
    def _is_relevant_news(self, title: str, content: str) -> bool:
        """判断是否为相关的投资信息（已废弃，使用 _is_major_event_news 替代）"""
        return self._is_major_event_news(title, content)
    
    def _is_important_announcement(self, title: str) -> bool:
        """判断公告是否重要"""
        important_keywords = [
            '重大', '重组', '并购', '收购', '注入', '借壳',
            '合同', '订单', '中标', '签约', '战略合作',
            '增持', '减持', '回购', '举牌',
            '业绩预告', '业绩快报', '业绩修正',
            '停牌', '复牌', '退市',
            '股权激励', '员工持股',
            '分红', '送转', '配股', '增发'
        ]
        
        title_lower = title.lower()
        for keyword in important_keywords:
            if keyword in title_lower:
                return True
        
        return False
    
    def _format_timestamp(self, timestamp) -> str:
        """格式化时间戳"""
        if not timestamp:
            return ''
        
        try:
            if isinstance(timestamp, str):
                return timestamp
            
            if timestamp > 1e12:
                timestamp = timestamp / 1000
            
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return ''
    
    def _aggregate_and_analyze(self, posts: List[Dict]) -> List[Dict]:
        """聚合分析所有平台的数据 - 每条新闻只关联一个最相关的股票"""
        stock_data = defaultdict(lambda: {
            'mentions': [],
            'keywords_used': set(),
            'sources': set(),
            'platforms': set(),
            'posts_count': 0,
            'total_weight': 0,
            'sample_posts': []
        })
        
        for post in posts:
            title = post.get('title', '')
            content = post.get('content', '')
            full_text = title + ' ' + content
            
            primary_code = None
            if post.get('stock_code'):
                primary_code = post.get('stock_code')
            else:
                extracted_codes = self._extract_primary_stock_code(title, content)
                if extracted_codes:
                    primary_code = extracted_codes
            
            if not primary_code:
                continue
            
            if not self._is_rumor_or_undisclosed(title, content):
                continue
            
            matched_keywords = self._find_matched_keywords(full_text)
            keyword_weight = max([self._get_keyword_weight(kw) for kw in matched_keywords]) if matched_keywords else 1
            
            stock_data[primary_code]['mentions'].append(post)
            stock_data[primary_code]['keywords_used'].update(matched_keywords)
            stock_data[primary_code]['sources'].add(post.get('source', 'unknown'))
            stock_data[primary_code]['platforms'].add(post.get('platform', 'unknown'))
            stock_data[primary_code]['posts_count'] += 1
            stock_data[primary_code]['total_weight'] += keyword_weight
            
            if len(stock_data[primary_code]['sample_posts']) < 5:
                stock_data[primary_code]['sample_posts'].append({
                    'title': title,
                    'content': content[:300],
                    'url': post.get('url', ''),
                    'source_name': post.get('source_name', post.get('platform', '')),
                    'platform': post.get('platform', ''),
                    'post_time': post.get('post_time', ''),
                    'author': post.get('author', '')
                })
        
        opportunities = []
        for stock_code, data in stock_data.items():
            if data['posts_count'] >= 1:
                best_post = data['sample_posts'][0] if data['sample_posts'] else {}
                top_keywords = list(data['keywords_used'])[:3]
                
                news_type, event_score = self._classify_news_type_strict(
                    top_keywords, 
                    best_post.get('title', ''), 
                    best_post.get('content', '')
                )
                
                if news_type == '无实质事件':
                    continue
                
                stock_name = self._get_stock_name(stock_code)
                confidence_score = self._calculate_confidence_strict(data, event_score)
                
                if confidence_score < 50:
                    continue
                
                confidence_rating = self._get_confidence_rating(confidence_score)
                news_title = best_post.get('title', '') or f"{stock_code} {news_type}"
                
                opportunities.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'confidence_score': confidence_score,
                    'confidence_rating': confidence_rating,
                    'news_type_name': news_type,
                    'news_title': news_title,
                    'news_content': self._generate_news_summary(data),
                    'publish_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'news_source': f"多平台挖掘 ({', '.join(list(data['platforms'])[:3])})",
                    'news_url': best_post.get('url', ''),
                    'investment_advice': self._generate_investment_advice(data),
                    'risk_warning': self._generate_risk_warning(data),
                    'confidence': {
                        'scores': {
                            'source_reliability': min(len(data['platforms']) * 25, 85),
                            'timeliness': 70,
                            'content_quality': min(len(data['keywords_used']) * 20, 75),
                            'market_validation': min(data['total_weight'] * 6, 70),
                            'cross_platform_confirmation': min(len(data['platforms']) * 20, 80)
                        }
                    },
                    'posts_count': data['posts_count'],
                    'total_keyword_weight': data['total_weight'],
                    'keywords_used': list(data['keywords_used']),
                    'sources': list(data['sources']),
                    'platforms': list(data['platforms']),
                    'sample_posts': data['sample_posts'],
                    'timestamp': datetime.now().isoformat(),
                    'data_source': 'multi_platform_mining'
                })
        
        opportunities.sort(key=lambda x: x['confidence_score'], reverse=True)
        
        return opportunities
    
    def _extract_primary_stock_code(self, title: str, content: str) -> Optional[str]:
        """从文本中提取最主要的一个股票代码 - 避免串股"""
        title_codes = set()
        for pattern in self.STOCK_CODE_PATTERNS:
            matches = re.findall(pattern, title)
            for match in matches:
                code = re.sub(r'[^0-9]', '', match)
                if len(code) == 6 and self._is_valid_stock_code(code):
                    title_codes.add(code)
        
        if len(title_codes) == 1:
            return list(title_codes)[0]
        
        full_text = title + ' ' + content[:300]
        
        company_patterns = [
            r'([\u4e00-\u9fa5]{2,6})(?:股份|集团|科技|智能|电子|汽车|家居|医药|银行|证券)',
            r'【([\u4e00-\u9fa5]{2,6})】',
            r'「([\u4e00-\u9fa5]{2,6})」',
        ]
        
        for pattern in company_patterns:
            matches = re.findall(pattern, full_text)
            for company_name in matches:
                if len(company_name) >= 2 and len(company_name) <= 6:
                    code = self._search_stock_code_by_name(company_name)
                    if code:
                        return code
        
        subject_patterns = [
            r'^[【\[]?(.{2,6}?)[】\]]?(?:拟|将|或|传闻|计划|筹划|：|:|涨停)',
            r'(.{2,6}?)(?:拟|或将|有望|计划)(?:收购|重组|并购)',
            r'(?:收购|重组|并购|入主)(.{2,6}?)(?:传闻|消息|$)',
        ]
        
        for pattern in subject_patterns:
            match = re.search(pattern, title)
            if match:
                company_name = match.group(1).strip()
                if 2 <= len(company_name) <= 6:
                    code = self._search_stock_code_by_name(company_name)
                    if code:
                        return code
        
        if title_codes:
            return list(title_codes)[0]
        
        return None
    
    def _is_rumor_or_undisclosed(self, title: str, content: str) -> bool:
        """判断是否为传闻/未公告/潜在利好信息（非已公告官方信息，排除纯利空）"""
        full_text = (title + ' ' + content).lower()
        
        pure_negative_keywords = [
            '终止重组', '重组失败', '重组取消', '并购失败', '终止重大资产重组',
            '利空', '暴跌', '跌停', '退市警告', '巨额亏损',
            '处罚', '违规', '立案调查', '警示函', '终止'
        ]
        
        for neg in pure_negative_keywords:
            if neg in full_text:
                return False
        
        official_patterns = [
            r'公司发布公告', r'正式公告', r'公开披露',
            r'已.*完成', r'已.*通过', r'已.*获批', r'已.*生效',
            r'董事会决议通过', r'股东大会审议', r'证监会.*批准'
        ]
        
        for pattern in official_patterns:
            if re.search(pattern, full_text):
                rumor_words = ['传闻', '据说', '消息称', '知情人士', '或将', '有望', '拟', '计划', '筹划', '洽谈']
                if not any(w in full_text for w in rumor_words):
                    return False
        
        rumor_indicators = [
            '传闻', '据说', '听说', '小道消息', '内部消息', '传言', 
            '风声', '爆料', '透露', '知情人士', '消息称', '市场传闻',
            '据传', '有传', '或将', '有望', '疑似', '可能',
            '正在洽谈', '秘密接触', '私下协商', '暗中筹划',
            '即将', '近期将', '拟', '计划', '筹划',
            '未经证实', '待确认', '尚未公告',
            '否认', '澄清', '辟谣'
        ]
        
        rumor_count = sum(1 for w in rumor_indicators if w in full_text)
        
        if rumor_count >= 1:
            return True
        
        potential_patterns = [
            r'(?:可能|或将|有望).*(?:收购|重组|并购|合作)',
            r'(?:洽谈|接触|协商).*(?:收购|重组|并购|合作)',
            r'(?:传|据).{0,5}(?:收购|重组|并购)',
        ]
        
        for pattern in potential_patterns:
            if re.search(pattern, full_text):
                return True
        
        return False
    
    def _extract_stock_codes(self, text: str) -> Set[str]:
        """从文本中提取股票代码"""
        codes = set()
        
        for pattern in self.STOCK_CODE_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                code = re.sub(r'[^0-9]', '', match)
                if len(code) == 6 and self._is_valid_stock_code(code):
                    codes.add(code)
        
        company_codes = self._extract_codes_from_company_names(text)
        codes.update(company_codes)
        
        return codes
    
    def _extract_codes_from_company_names(self, text: str) -> Set[str]:
        """从公司名称中动态提取股票代码 - 基于API搜索而非写死映射"""
        codes = set()
        
        company_patterns = [
            r'([\u4e00-\u9fa5]{2,8})(股份有限公司|有限公司)',
            r'([\u4e00-\u9fa5]{2,6})(股份|集团|科技|智能|电子|医药|银行|证券|汽车|家居|影业|传媒|能源|电力|通信|软件|网络|生物|新材料|半导体|芯片)',
            r'【([\u4e00-\u9fa5]{2,6})】',
            r'「([\u4e00-\u9fa5]{2,6})」',
            r'([\u4e00-\u9fa5]{2,4})(公司|企业)'
        ]
        
        candidate_names = set()
        
        for pattern in company_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    company_name = ''.join(match)
                else:
                    company_name = match
                
                if len(company_name) >= 2:
                    candidate_names.add(company_name)
                    if len(match) > 0 and isinstance(match, tuple):
                        candidate_names.add(match[0])
        
        special_pattern = r'([\u4e00-\u9fa5]{2,4})(?:拟|将|或|传闻|计划|筹划)(?:收购|并购|重组|入股|合作)'
        special_matches = re.findall(special_pattern, text)
        for name in special_matches:
            if len(name) >= 2:
                candidate_names.add(name)
        
        target_pattern = r'(?:收购|并购|重组|入股)([\u4e00-\u9fa5]{2,6})(?:股权|资产|业务|公司)?'
        target_matches = re.findall(target_pattern, text)
        for name in target_matches:
            if len(name) >= 2:
                candidate_names.add(name)
        
        for company_name in list(candidate_names)[:10]:
            code = self._search_stock_code_by_name(company_name)
            if code:
                codes.add(code)
                if len(codes) >= 5:
                    break
        
        return codes
    
    def _search_stock_code_by_name(self, company_name: str) -> Optional[str]:
        """通过公司名称搜索股票代码"""
        if not company_name or len(company_name) < 2:
            return None
        
        cache_key = f"name_{company_name}"
        if cache_key in self._stock_name_cache:
            return self._stock_name_cache[cache_key]
        
        try:
            url = "https://searchapi.eastmoney.com/api/suggest/get"
            params = {
                'input': company_name,
                'type': 14,
                'token': 'D43BF722C8E33BDC906FB84D85E326E8',
                'count': 3
            }
            
            response = self.session.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get('QuotationCodeTable', {}).get('Data', [])
                
                for item in results:
                    code = item.get('Code', '')
                    if code and self._is_valid_stock_code(code):
                        self._stock_name_cache[cache_key] = code
                        return code
        except Exception:
            pass
        
        self._stock_name_cache[cache_key] = None
        return None
    
    def _is_valid_stock_code(self, code: str) -> bool:
        """验证股票代码格式"""
        valid_prefixes = ['000', '001', '002', '003', '300', '301', '600', '601', '603', '605', '688', '689']
        return any(code.startswith(prefix) for prefix in valid_prefixes)
    
    def _find_matched_keywords(self, text: str) -> List[str]:
        """查找匹配的关键词"""
        matched = []
        text_lower = text.lower()
        
        for tier_config in self.PRIORITY_KEYWORDS.values():
            for keyword in tier_config['keywords']:
                if keyword in text_lower:
                    matched.append(keyword)
        
        return matched
    
    def _get_keyword_weight(self, keyword: str) -> int:
        """获取关键词权重"""
        for tier_config in self.PRIORITY_KEYWORDS.values():
            if keyword in tier_config['keywords']:
                return tier_config['weight']
        return 1
    
    def _get_stock_name(self, stock_code: str) -> str:
        """获取股票名称"""
        if stock_code in self._stock_name_cache:
            return self._stock_name_cache[stock_code]
        
        try:
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
                    self._stock_name_cache[stock_code] = name
                    return name
        except Exception:
            pass
        
        self._stock_name_cache[stock_code] = f'股票{stock_code}'
        return f'股票{stock_code}'
    
    def _calculate_confidence_strict(self, data: Dict, event_score: int) -> float:
        """严格计算置信度评分 - 事件质量为核心"""
        base_score = event_score * 0.6
        
        platform_score = min(len(data['platforms']) * 10, 20)
        
        keyword_score = 0
        for kw in data['keywords_used']:
            weight = self._get_keyword_weight(kw)
            if weight >= 11:
                keyword_score += 8
            elif weight >= 9:
                keyword_score += 5
        keyword_score = min(keyword_score, 15)
        
        confirmation_score = 0
        if len(data['platforms']) >= 2:
            confirmation_score = 5
        
        total = base_score + platform_score + keyword_score + confirmation_score
        return min(total, 100)
    
    def _calculate_confidence(self, data: Dict) -> float:
        """计算置信度评分（兼容旧接口）"""
        return self._calculate_confidence_strict(data, 70)
    
    def _get_confidence_rating(self, score: float) -> str:
        """获取置信度等级"""
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
    
    def _classify_news_type_strict(self, keywords: List[str], title: str, content: str) -> Tuple[str, int]:
        """严格分类新闻类型，返回(类型, 事件分数)"""
        full_text = ' '.join(keywords) + ' ' + title + ' ' + content
        full_text = full_text.lower()
        
        rumor_words = ['传闻', '小道消息', '内部消息', '知情人士', '消息称', '市场传闻', '据传', '有传', '传言']
        ma_words = ['重组', '并购', '收购', '借壳', '注入资产', '战略入股', '混改', '国资入场', '举牌', '要约收购', '入主']
        contract_words = ['重大合同', '大订单', '巨额订单', '中标', '独家供应', '进入供应链']
        coop_words = ['战略合作', '深度合作', '合作', '联合', '携手', '牵手']
        fund_words = ['国家大基金', '大基金', '社保基金', '险资']
        shareholder_words = ['增持', '回购', '股权激励', '员工持股', '大股东']
        
        has_rumor = any(w in full_text for w in rumor_words)
        
        if any(w in full_text for w in ma_words):
            event_type = '重组并购传闻' if has_rumor else '重组并购'
            return (event_type, 100 if has_rumor else 85)
        
        if any(w in full_text for w in ['订单', '合同', '中标', '签约']):
            has_major = any(w in full_text for w in ['亿', '千万', '重大', '大额', '巨额', '大订单'])
            if has_major:
                return ('重大合同', 90)
        
        if any(w in full_text for w in contract_words):
            return ('战略合作', 80)
        
        if any(w in full_text for w in coop_words) and has_rumor:
            return ('合作传闻', 75)
        
        if any(w in full_text for w in fund_words):
            return ('国家战略投资', 95)
        
        if any(w in full_text for w in shareholder_words):
            has_major = any(w in full_text for w in ['大幅', '巨额', '亿', '大规模', '大手笔'])
            if has_major or has_rumor:
                return ('股东增持', 70)
        
        if has_rumor:
            if any(w in full_text for w in ['利好', '重大', '突破', '爆发']):
                return ('重大传闻', 65)
        
        return ('无实质事件', 0)
    
    def _classify_news_type(self, keywords: List[str], title: str, content: str) -> str:
        """分类新闻类型（兼容旧接口）"""
        news_type, _ = self._classify_news_type_strict(keywords, title, content)
        return news_type
    
    def _generate_news_summary(self, data: Dict) -> str:
        """生成新闻摘要"""
        platforms = list(data['platforms'])
        keywords = list(data['keywords_used'])[:3]
        
        summary = f"该股票在{', '.join(platforms[:3])}等{len(platforms)}个平台被讨论"
        if keywords:
            summary += f"，涉及关键词: {', '.join(keywords)}"
        summary += f"。共发现{data['posts_count']}条相关信息。"
        
        return summary
    
    def _generate_investment_advice(self, data: Dict) -> str:
        """生成投资建议"""
        platforms_count = len(data['platforms'])
        posts_count = data['posts_count']
        
        if platforms_count >= 3 and posts_count >= 5:
            return "多平台交叉验证，关注度较高，建议密切跟踪后续公告，适当关注。"
        elif platforms_count >= 2:
            return "多个平台有讨论，建议关注后续进展，谨慎参与。"
        else:
            return "单平台信息，建议观望为主，等待更多确认。"
    
    def _generate_risk_warning(self, data: Dict) -> str:
        """生成风险提示"""
        keywords = list(data['keywords_used'])
        
        base_warning = "网络信息真实性待确认，投资需谨慎。"
        
        if any('传闻' in kw or '据说' in kw for kw in keywords):
            return f"{base_warning}传言类消息风险较高，需等待正式公告确认。"
        elif any('重组' in kw or '并购' in kw for kw in keywords):
            return f"{base_warning}重组并购类消息不确定性较大，注意控制仓位。"
        else:
            return f"{base_warning}市场波动较大，注意风险控制。"


if __name__ == '__main__':
    miner = MultiPlatformNewsMiner()
    results = miner.mine_all_platforms(keyword_limit=15, posts_per_platform=30)
    
    print(f"\n发现 {len(results)} 个投资机会:")
    for i, opp in enumerate(results[:10], 1):
        print(f"\n{i}. {opp['stock_code']} {opp['stock_name']}")
        print(f"   置信度: {opp['confidence_rating']} ({opp['confidence_score']:.1f}分)")
        print(f"   类型: {opp['news_type_name']}")
        print(f"   平台: {', '.join(opp['platforms'])}")
        print(f"   标题: {opp['news_title'][:50]}...")
