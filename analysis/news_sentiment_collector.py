#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息面采集模块
采集股票相关的新闻、公告、研报等消息面数据
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import json
import time
import random
from pathlib import Path
import sys
import re

# 添加项目根目录到路径 - 优先使用环境变量
# 尝试多个可能的路径位置
possible_roots = []
if 'KRONOS_PROJECT_ROOT' in os.environ:
    possible_roots.append(os.environ['KRONOS_PROJECT_ROOT'])
possible_roots.append(str(Path(__file__).parent.parent))  # analysis 的父目录
possible_roots.append(str(Path(__file__).parent.parent.parent))  # Frameworks 的父目录
possible_roots.append(str(Path(__file__).parent))  # 当前目录

# 查找有效的根目录
project_root = None
for root in possible_roots:
    root_path = Path(root)
    utils_path = root_path / 'utils'
    if root_path.exists() and utils_path.exists():
        project_root = str(root_path)
        break

if project_root is None:
    # 最后尝试从当前工作目录查找
    project_root = os.getcwd()

sys.path.insert(0, project_root)
# 也添加 utils 目录
utils_path = Path(project_root) / 'utils'
if utils_path.exists():
    sys.path.insert(0, str(utils_path))

from analysis.dynamic_crawler import DynamicCrawler
from utils.retry_utils import (
    exponential_backoff_with_jitter,
    retry_with_fallback,
    validate_data_quality,
    handle_missing_fields
)

import logging
logger = logging.getLogger(__name__)


class NewsSentimentCollector:
    """消息面采集器"""

    def __init__(self, stock_code):
        """
        初始化消息面采集器

        Args:
            stock_code: 股票代码 (例如: '688343', '000001')
        """
        self.stock_code = stock_code
        flag = os.environ.get('KRONOS_DISABLE_PLAYWRIGHT_NEWS', '1').strip().lower()
        self.disable_playwright_news = flag in {'1', 'true', 'yes', 'on'}
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/'
        }
    # 用于更强关联检索
        self.company_name = None
        self.related_keywords = []



    def get_latest_announcements(self, limit=10):
        """
        获取最新公告 - 使用Playwright爬取

        Args:
            limit: 获取公告数量

        Returns:
            list: 公告列表
        """
        announcements = []
        if not self.disable_playwright_news:
            announcements = DynamicCrawler.crawl_announcements(self.stock_code, limit)

        if announcements:
            # 统一字段命名与补充，避免后续分析出现空日期/链接
            normalized = []
            for ann in announcements:
                # 规范日期字段并归一化
                raw_date = ann.get('date') or ann.get('publish_time') or ann.get('notice_date') or ''
                ann['date'] = self._normalize_date_str(raw_date)
                # 规范链接字段，确保为绝对URL
                url = ann.get('url') or ''
                if url and not url.startswith('http'):
                    url = f"http://data.eastmoney.com{url}"
                ann['url'] = url
                # 重要性重新分类（覆盖来源默认值）
                ann['importance'] = self._classify_importance(ann.get('title', ''))
                # 摘要兜底
                if 'summary' not in ann or not ann.get('summary'):
                    ann['summary'] = self._extract_summary(ann.get('title', ''))
                normalized.append(ann)

            print(f"   ✅ Playwright成功获取{len(normalized)}条公告")
            return normalized

        try:
            # 东方财富公告API
            url = "http://np-anotice-stock.eastmoney.com/api/security/ann"

            announcements = []

            # 针对API的股票代码格式进行多种尝试（如SZ/SH前缀）
            variants = self._format_stock_code_variants(self.stock_code)
            for idx, code_variant in enumerate(variants, start=1):
                params = {
                    'sr': '-1',
                    'page_size': str(limit),
                    'page_index': '1',
                    'ann_type': 'SHA,SZA',
                    'client_source': 'web',
                    'stock_list': code_variant
                }
                # 【优化】减少日志输出，只在第一次尝试时输出
                if idx == 1:
                    pass  # 静默尝试，减少日志噪音
                response = requests.get(url, params=params, headers=self.headers, timeout=10)
                if response.status_code != 200 or not response.text or not response.text.strip():
                    continue
                try:
                    data = response.json()
                except Exception:
                    continue

                if data.get('data') and data['data'].get('list'):
                    for item in data['data']['list']:
                        announcement = {
                            'title': item.get('title', ''),
                            'date': item.get('notice_date', ''),
                            'type': item.get('columns', ''),
                            'url': f"http://data.eastmoney.com/notices/detail/{self.stock_code}/{item.get('art_code', '')}.html",
                            'summary': self._extract_summary(item.get('title', '')),
                            'importance': self._classify_importance(item.get('title', ''))
                        }
                        announcements.append(announcement)
                    # 成功获取到数据，静默返回
                    return announcements[:limit]

            # 如果API返回空数据,尝试网页爬取（静默尝试）
            if not announcements:
                announcements = self._scrape_announcements(limit)

            return announcements[:limit]

        except Exception as e:
            # 【优化】减少错误日志输出
            ann = self._scrape_announcements(limit)
            return ann

    def _scrape_announcements(self, limit=10):
        """网页爬取公告数据"""
        try:
            # 东方财富公告页面
            url = f"http://data.eastmoney.com/notices/stock/{self.stock_code}.html"

            response = requests.get(url, headers=self.headers, timeout=10)
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            announcements = []
            # 更稳健的选择器：查找所有公告详情链接（href包含/notices/detail/）
            candidate_links = []
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                text = a.get_text(strip=True)
                if '/notices/detail/' in href and text and len(text) >= 6:
                    candidate_links.append(a)

            if not candidate_links:
                # 退回到通用表格解析
                table = soup.find('table')
                if table:
                    rows = table.find_all('tr')
                    for row in rows:
                        a = row.find('a', href=True)
                        if not a:
                            continue
                        href = a.get('href', '')
                        text = a.get_text(strip=True)
                        if not text or len(text) < 6:
                            continue
                        candidate_links.append(a)

            # 解析候选公告
            for a in candidate_links[:limit]:
                title = a.get_text(strip=True)
                href = a.get('href', '')

                # 查找日期（在父级或同级的文本中用正则匹配）
                date_text = ''
                ctx = a.parent if a.parent else a
                contexts = [ctx, ctx.parent] if ctx and ctx.parent else [ctx]
                for c in contexts:
                    if not c:
                        continue
                    text_ctx = c.get_text(" ", strip=True)
                    m = re.search(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})', text_ctx)
                    if m:
                        date_text = m.group(1)
                        break
                # 若未解析到日期，不再填充今天，交由归一化逻辑处理
                if not date_text:
                    date_text = ''

                announcements.append({
                    'title': title,
                    'date': self._normalize_date_str(date_text),
                    'type': '公告',
                    'url': href if href.startswith('http') else f"http://data.eastmoney.com{href}",
                    'summary': self._extract_summary(title),
                    'importance': self._classify_importance(title)
                })

            if not announcements:
                print(f"   ⚠️  网页爬取也未获取到公告")

            return announcements

        except Exception as e:
            print(f"⚠️ 网页爬取公告失败: {str(e)}")
            return []

    def get_latest_news(self, limit=20):
        """
        获取最新新闻 - 使用Playwright爬取

        Args:
            limit: 获取新闻数量

        Returns:
            list: 新闻列表
        """
        news_list = []
        if not self.disable_playwright_news:
            news_list = DynamicCrawler.crawl_news_list(self.stock_code, limit)

        if news_list:
            # 归一化日期字段，并添加情感分析
            for news in news_list:
                raw_date = news.get('date') or news.get('publish_time') or ''
                normalized = self._normalize_date_str(raw_date)
                news['date'] = normalized
                news['publish_time'] = normalized
                if 'sentiment' not in news:
                    text = news.get('title', '') + ' ' + news.get('summary', '')
                    news['sentiment'] = self._analyze_sentiment(text)

            print(f"   ✅ Playwright成功获取{len(news_list)}条新闻")
            return news_list

        try:
            # 现阶段新闻API不稳定，先回退至网页爬取
            print(f"   ⚠️  API未返回新闻数据或不稳定,回退网页爬取")
            news_list = self._scrape_news(limit)

            # 如果网页爬取仍为空，尝试同花顺备用源
            if not news_list:
                print(f"   🔁 网页爬取为空,尝试同花顺新闻API备用源")
                news_list = self._fallback_news_tonghuashun(limit)

            return news_list[:limit]

        except Exception as e:
            print(f"⚠️ 获取新闻失败: {str(e)},尝试网页爬取与备用源")
            news_list = self._scrape_news(limit)
            if not news_list:
                news_list = self._fallback_news_tonghuashun(limit)
            return news_list[:limit]

    def _scrape_sina_news(self, limit=20):
        """爬取新浪财经个股资讯（高相关性）"""
        try:
            # 交易所前缀适配
            market_prefix = 'sh' if str(self.stock_code).startswith(('600', '601', '603', '605', '688')) else 'sz'
            symbol = f"{market_prefix}{self.stock_code}"
            url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/{symbol}.phtml"
            
            response = requests.get(url, headers=self.headers, timeout=10)
            response.encoding = 'gb2312' # 新浪财经通常使用GB2312
            soup = BeautifulSoup(response.text, 'html.parser')
            
            news_list = []
            # 新浪个股资讯列表通常在 .datelist ul a 中
            items = soup.select('.datelist ul a')
            
            for item in items[:limit]:
                title = item.get_text(strip=True)
                if not title or len(title) < 6:
                    continue
                    
                # 过滤非股票类代码（如基金of、期权so）
                if re.search(r'\[(of|so)\d+\]', title, re.IGNORECASE):
                    continue

                href = item.get('href', '')
                if not href:
                    continue
                    
                # 尝试提取日期 (新浪列表页通常没有直接日期，需从详情页或推断，这里暂空或从链接尝试提取)
                # 链接示例: .../2023-01-01/doc-xxxxx.shtml
                date_text = ''
                date_match = re.search(r'(\d{4}-\d{1,2}-\d{1,2})', href)
                if date_match:
                    date_text = date_match.group(1)
                else:
                    date_match = re.search(r'(\d{8})', href)
                    if date_match:
                        d = date_match.group(1)
                        date_text = f"{d[:4]}-{d[4:6]}-{d[6:]}"

                news_list.append({
                    'title': title,
                    'date': self._normalize_date_str(date_text),
                    'source': '新浪财经',
                    'url': href,
                    'summary': self._extract_summary(title),
                    'sentiment': self._analyze_sentiment(title)
                })
                
            return news_list
        except Exception as e:
            print(f"   ⚠️ 新浪财经爬取失败: {str(e)}")
            return []

    def _scrape_news(self, limit=20):
        """网页爬取新闻数据：优先使用新浪财经个股资讯，兜底使用东财搜索"""
        try:
            # 1. 优先尝试新浪财经个股资讯（相关性极高）
            sina_news = self._scrape_sina_news(limit)
            if sina_news:
                print(f"   ✅ 新浪财经获取到 {len(sina_news)} 条相关资讯")
                return sina_news

            # 2. 兜底：原有逻辑（东财搜索）
            # 预加载公司名与关联词
            if not self.company_name:
                self._load_company_name()
            if not self.related_keywords:
                self._load_related_keywords()

            def fetch_by_keyword(keyword: str, max_items: int = 10):
                url = f"https://so.eastmoney.com/news/s?keyword={keyword}"
                response = requests.get(url, headers=self.headers, timeout=10)
                response.encoding = 'utf-8'
                soup = BeautifulSoup(response.text, 'html.parser')

                items = []
                candidates = []
                for class_name in ['news-item', 'result-item', 'search-item', 'list-item', 'item', 'article']:
                    candidates += soup.find_all('div', class_=class_name)
                    candidates += soup.find_all('li', class_=class_name)

                if not candidates:
                    # 退回通用li策略
                    candidates = [li for li in soup.find_all('li') if li.find('a') and len(li.get_text(strip=True)) > 10]

                for it in candidates[:max_items * 2]:
                    # 优先选择内容最长的标题链接
                    a_tags = [a for a in it.find_all('a', href=True) if a.get_text(strip=True)]
                    if not a_tags:
                        continue
                    a = max(a_tags, key=lambda x: len(x.get_text(strip=True)))
                    title = a.get_text(strip=True)
                    if not title or len(title) < 6:
                        continue
                    href = a.get('href', '')
                    if not href:
                        continue

                    # 过滤明显广告或推广链接（尽量保守，避免过度过滤）
                    bad_hosts = ['acttg.eastmoney.com', 'tg.eastmoney.com']
                    if any(b in href for b in bad_hosts):
                        continue

                    # 过滤非股票类代码（如基金of、期权so）
                    if re.search(r'\[(of|so)\d+\]', title, re.IGNORECASE):
                        continue

                    # 日期提取，支持更多常见结构
                    date_text = ''
                    date_elem = (
                        it.find('span', class_='date') or it.find('span', class_='time') or it.find('time') or
                        it.find('em', class_='time') or it.find('p', class_='time')
                    )
                    if date_elem:
                        date_text = date_elem.get_text(strip=True)
                    else:
                        m = re.search(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})', it.get_text(" ", strip=True))
                        if m:
                            date_text = m.group(1)

                    # 来源提取，兼容更多标签
                    source = '东方财富网'
                    source_elem = (
                        it.find('span', class_='source') or it.find('p', class_='source') or
                        it.find('span', class_='media') or it.find('p', class_='from')
                    )
                    if source_elem:
                        st = source_elem.get_text(strip=True)
                        if st and 2 <= len(st) <= 40:
                            source = st

                    items.append({
                        'title': title,
                        'date': self._normalize_date_str(date_text),
                        'source': source,
                        'url': href if href.startswith('http') else f"https://so.eastmoney.com{href}",
                        'summary': self._extract_summary(title),
                        'sentiment': self._analyze_sentiment(title)
                    })

                # 候选解析后若仍过少，回退为全局a标签解析，尽量保证有数据
                if len(items) < max_items // 2:
                    for a in soup.find_all('a', href=True):
                        text = a.get_text(strip=True)
                        href = a.get('href', '')
                        if not text or not href:
                            continue
                        if len(text) < 8:
                            continue
                        if any(b in href for b in ['acttg.eastmoney.com', 'tg.eastmoney.com']):
                            continue
                        
                        # 过滤非股票类代码（如基金of、期权so）
                        if re.search(r'\[(of|so)\d+\]', text, re.IGNORECASE):
                            continue

                        # 仅采集疑似新闻详情页
                        if not (href.endswith('.html') or 'news' in href or 'finance' in href):
                            continue
                        items.append({
                            'title': text,
                            'date': '',
                            'source': '东方财富网',
                            'url': href if href.startswith('http') else f"https://so.eastmoney.com{href}",
                            'summary': self._extract_summary(text),
                            'sentiment': self._analyze_sentiment(text)
                        })

                # 截断到最大条数
                items = items[:max_items]
                return items

            # 构造检索队列：股票代码、公司名、关联关键词
            queries = [str(self.stock_code)]
            if self.company_name:
                queries.append(self.company_name)
            queries.extend(self.related_keywords)

            news_list = []
            seen_titles = set()
            for q in queries:
                if not q:
                    continue
                items = fetch_by_keyword(q, max_items=max(5, limit // 2))
                for it in items:
                    t = it.get('title', '')
                    if t and t not in seen_titles:
                        news_list.append(it)
                        seen_titles.add(t)
                    if len(news_list) >= limit:
                        break
                if len(news_list) >= limit:
                    break

            if not news_list:
                print(f"   ⚠️  网页爬取也未获取到新闻")

            return news_list

        except Exception as e:
            print(f"⚠️ 网页爬取新闻失败: {str(e)}")
            return []

    def _load_company_name(self):
        """通过东财push2接口加载公司名"""
        try:
            exchange_flag = '1' if str(self.stock_code).startswith(('600', '601', '603', '605', '688')) else '0'
            # 使用 ulist.np 替代 stock/get
            url = "http://push2.eastmoney.com/api/qt/ulist.np/get"
            params = {
                'secids': f"{exchange_flag}.{self.stock_code}",
                'fltt': '2',
                'fields': 'f14'  # f14: 股票名称
            }
            resp = requests.get(url, params=params, headers=self.headers, timeout=8)
            data = resp.json() if resp.content else {}
            # ulist返回结构: data -> diff -> [0]
            name = None
            if data.get('data') and data['data'].get('diff'):
                name = data['data']['diff'][0].get('f14')
                
            if isinstance(name, str) and name.strip():
                self.company_name = name.strip()
        except Exception:
            pass

    def _load_related_keywords(self):
        """加载配置中的关联实体关键词"""
        try:
            cfg_path = project_root / 'config' / 'related_entities.json'
            if cfg_path.exists():
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    rel = json.load(f)
                code = str(self.stock_code)
                keys = [code, f"SZ{code}", f"SH{code}", f"{code}.SZ", f"{code}.SH"]
                kws = []
                for k in keys:
                    v = rel.get(k)
                    if isinstance(v, list):
                        kws.extend([s for s in v if isinstance(s, str)])
                self.related_keywords = list(dict.fromkeys(kws))
        except Exception:
            pass

    def _fallback_news_tonghuashun(self, limit=20):
        """同花顺新闻API备用源"""
        try:
            url = 'https://news.10jqka.com.cn/tapp/news/push/stock'

            # 推断交易所编码
            exchange = 'sh' if str(self.stock_code).startswith(('600', '601', '603', '605', '688')) else 'sz'
            params = {
                'stock_code': f"{exchange}{self.stock_code}",
                'page': '1',
                'page_size': str(limit),
                '_': int(time.time() * 1000)
            }

            resp = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = resp.json() if resp.content else {}
            items = (data or {}).get('data', {}).get('list', []) if (data or {}).get('status_code') == 0 else []

            news_list = []
            for it in items[:limit]:
                title = it.get('title') or it.get('news_title') or ''
                date = it.get('ctime') or it.get('pub_time') or it.get('date') or ''
                url_item = it.get('url') or it.get('news_url') or ''
                source = it.get('source') or it.get('site_name') or '同花顺'
                if not title:
                    continue
                news_list.append({
                    'title': title,
                    'date': self._normalize_date_str(str(date)),
                    'source': source,
                    'url': url_item,
                    'summary': self._extract_summary(title),
                    'sentiment': self._analyze_sentiment(title)
                })

            if not news_list:
                print("   ⚠️ 同花顺新闻API未返回有效数据")

            return news_list
        except Exception as e:
            print(f"⚠️ 同花顺备用源获取失败: {str(e)}")
            return []

    def get_research_reports(self, limit=10):
        """
        获取研报信息

        Args:
            limit: 获取研报数量

        Returns:
            list: 研报列表
        """
        try:
            # 东方财富研报API (HTTPS)
            url = "https://reportapi.eastmoney.com/report/list"
            reports = []
            
            # 计算时间范围 (过去2年)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=365*2)
            
            begin_time = start_date.strftime('%Y-%m-%d')
            end_time = end_date.strftime('%Y-%m-%d')

            variants = self._format_stock_code_variants(self.stock_code)
            for idx, code_variant in enumerate(variants, start=1):
                params = {
                    'qType': '0',
                    'pageSize': str(limit),
                    'code': code_variant,
                    'beginTime': begin_time,
                    'endTime': end_time,
                    'pageNo': '1',
                    'type': '0'
                }
                print(f"   🔁 尝试研报API代码格式({idx}/{len(variants)}): code={code_variant}")
                try:
                    response = requests.get(url, params=params, headers=self.headers, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get('data'):
                            for item in data['data']:
                                report = {
                                    'title': item.get('title', ''),
                                    'date': item.get('publishDate', ''),
                                    'institution': item.get('orgSName', ''),
                                    'researcher': item.get('researcher', ''),
                                    'rating': item.get('emRatingName', '') or item.get('sRatingName', ''),
                                    'target_price': item.get('indvAimPriceT', '') or item.get('predictNextTwoYearEps', ''),
                                    'summary': item.get('title', '')[:100],
                                }
                                reports.append(report)
                            break
                except Exception:
                    pass

            # 如果API为空，尝试网页搜索研报作为兜底
            if not reports:
                print("   ⚠️  研报API未返回数据,尝试网页检索兜底")
                reports = self._scrape_research_reports(limit)

            return reports[:limit]

        except Exception as e:
            print(f"⚠️ 获取研报失败: {str(e)}")
            return self._scrape_research_reports(limit)

    def _scrape_research_reports(self, limit=10):
        """网页检索研报兜底"""
        try:
            url = f"https://so.eastmoney.com/news/s?keyword={self.stock_code}%20研报"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')

            candidates = []
            for class_name in ['news-item', 'result-item', 'search-item', 'list-item', 'item', 'article']:
                candidates += soup.find_all('div', class_=class_name)
                candidates += soup.find_all('li', class_=class_name)
            if not candidates:
                candidates = [li for li in soup.find_all('li') if li.find('a') and len(li.get_text(strip=True)) > 10]

            reports = []
            for item in candidates[:limit * 2]:
                a = item.find('a', href=True)
                if not a:
                    continue
                title = a.get_text(strip=True)
                if not title or len(title) < 8:
                    continue
                
                # 过滤非股票类代码（如基金of、期权so）
                if re.search(r'\[(of|so)\d+\]', title, re.IGNORECASE):
                    continue

                href = a.get('href', '')
                # 粗略筛选疑似研报内容
                if not any(k in title for k in ['研报', '评级', '上调', '下调', '目标价', '买入', '增持', '中性', '减持']):
                    continue

                date_text = ''
                date_elem = item.find('span', class_='date') or item.find('span', class_='time') or item.find('time')
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                else:
                    m = re.search(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})', item.get_text(" ", strip=True))
                    if m:
                        date_text = m.group(1)

                reports.append({
                    'title': title,
                    'date': date_text,
                    'institution': '研报来源',
                    'researcher': '',
                    'rating': '',
                    'target_price': '',
                    'summary': self._extract_summary(title),
                })

            if not reports:
                print("   ⚠️  网页检索也未获取到研报")

            return reports
        except Exception as e:
            print(f"⚠️ 网页检索研报失败: {str(e)}")
            return []

    def get_hot_topics(self):
        """
        获取热门话题

        Returns:
            list: 热门话题列表
        """
        try:
            # 雪球热门话题API (需要适配)
            topics = [
                {'topic': f'{self.stock_code}业绩预告', 'heat': 85, 'trend': 'up'},
                {'topic': f'{self.stock_code}技术分析', 'heat': 72, 'trend': 'stable'},
                {'topic': f'{self.stock_code}机构调研', 'heat': 68, 'trend': 'down'},
            ]

            return topics

        except Exception as e:
            print(f"⚠️ 获取热门话题失败: {str(e)}")
            return []

    def _extract_summary(self, title):
        """从标题提取摘要"""
        # 简化处理，实际可以进一步解析内容
        if len(title) > 50:
            return title[:50] + "..."
        return title

    def _classify_importance(self, title):
        """
        分类公告重要性

        Args:
            title: 公告标题

        Returns:
            str: 重要性等级
        """
        high_keywords = ['重大', '收购', '并购', '重组', '停牌', '复牌', '业绩预告', '分红', '增发', '定增']
        medium_keywords = ['公告', '通知', '提示', '变更', '补充']

        title_lower = title.lower()

        for keyword in high_keywords:
            if keyword in title_lower:
                return '高'

        for keyword in medium_keywords:
            if keyword in title_lower:
                return '中'

        return '低'

    def _analyze_sentiment(self, text):
        """
        简单情感分析

        Args:
            text: 文本内容

        Returns:
            str: 情感倾向
        """
        positive_keywords = ['利好', '上涨', '增长', '盈利', '突破', '创新高', '买入', '推荐', '优秀', '强势']
        negative_keywords = ['利空', '下跌', '亏损', '风险', '预警', '下调', '卖出', '减持', '暴跌', '弱势']

        text_lower = text.lower()

        positive_count = sum(1 for keyword in positive_keywords if keyword in text_lower)
        negative_count = sum(1 for keyword in negative_keywords if keyword in text_lower)

        if positive_count > negative_count:
            return '正面'
        elif negative_count > positive_count:
            return '负面'
        else:
            return '中性'


    def _format_stock_code_variants(self, code: str):
        """生成适配东财公告API的股票代码多种格式"""
        code = str(code).strip()
        variants = [code]
        # 根据常见规则推断交易所前缀
        try:
            if code.startswith('6') or code.startswith('900'):
                prefix = 'SH'
                variants.extend([f"{prefix}{code}", f"{prefix.lower()}{code}"])
            elif code.startswith(('0', '3', '2')):
                prefix = 'SZ'
                variants.extend([f"{prefix}{code}", f"{prefix.lower()}{code}"])
            elif code.startswith(('4', '8', '92')):
                prefix = 'BJ'
                variants.extend([f"{prefix}{code}", f"{prefix.lower()}{code}", f"SZ{code}", f"sz{code}"]) # 尝试BJ和SZ
            else:
                # 默认尝试SZ
                variants.extend([f"SZ{code}", f"sz{code}"])
        except Exception:
            pass
        # 去重保持顺序
        seen = set()
        uniq = []
        for v in variants:
            if v not in seen:
                uniq.append(v)
                seen.add(v)
        return uniq

    def get_comprehensive_news(self, verbose: bool = True):
        """
        获取综合消息面数据

        Returns:
            dict: 综合消息面数据
        """
        if verbose:
            print(f"📰 正在采集 {self.stock_code} 的消息面数据...")

        data = {
            'stock_code': self.stock_code,
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'announcements': self.get_latest_announcements(limit=10),
            'news': self.get_latest_news(limit=20),
            'research_reports': self.get_research_reports(limit=10),
            'hot_topics': self.get_hot_topics(),
        }

        # 统计情感倾向
        news_sentiments = [news['sentiment'] for news in data['news'] if 'sentiment' in news]
        data['sentiment_summary'] = {
            'positive': news_sentiments.count('正面'),
            'negative': news_sentiments.count('负面'),
            'neutral': news_sentiments.count('中性'),
            'total': len(news_sentiments)
        }

        # 公告重要性统计
        announcement_importance = [ann['importance'] for ann in data['announcements'] if 'importance' in ann]
        data['announcement_summary'] = {
            'high': announcement_importance.count('高'),
            'medium': announcement_importance.count('中'),
            'low': announcement_importance.count('低'),
            'total': len(announcement_importance)
        }

        if verbose:
            print(f"✅ 消息面数据采集完成")
            print(f"   - 公告: {len(data['announcements'])} 条")
            print(f"   - 新闻: {len(data['news'])} 条")
            print(f"   - 研报: {len(data['research_reports'])} 条")
            print(
                f"   - 情感统计: 正面{data['sentiment_summary']['positive']} 负面{data['sentiment_summary']['negative']} 中性{data['sentiment_summary']['neutral']}")

        return data

    def _normalize_date_str(self, s: str) -> str:
        """将各种日期文本归一化为YYYY-MM-DD，支持相对时间关键词与不同分隔符"""
        try:
            text = (s or '').strip()
            if text == '':
                return ''
            # 统一中文相对时间
            now = datetime.now()
            if any(k in text for k in ['刚刚', '秒前', '分钟前', '小时', '今天']):
                return now.strftime('%Y-%m-%d')
            if '昨天' in text:
                return (now - timedelta(days=1)).strftime('%Y-%m-%d')
            # 提取完整日期
            m = re.search(r'(\d{4})[\-/\.年](\d{1,2})[\-/\.月](\d{1,2})[日]?', text)
            if m:
                y, mo, d = m.groups()
                return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            # 提取 MM-DD 或 M/D
            m2 = re.search(r'(\d{1,2})[\-/\.](\d{1,2})', text)
            if m2:
                year = now.year
                mo, d = m2.groups()
                return f"{year:04d}-{int(mo):02d}-{int(d):02d}"
            # 时间戳（10位或13位）
            if text.isdigit() and len(text) in (10, 13):
                ts = int(text[:10])
                return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            # ISO日期或可解析格式
            for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M']:
                try:
                    dt = datetime.strptime(text, fmt)
                    return dt.strftime('%Y-%m-%d')
                except Exception:
                    pass
            # 不可识别则返回空
            return ''
        except Exception:
            return ''


if __name__ == "__main__":
    # 测试代码
    collector = NewsSentimentCollector("688343")
    data = collector.get_comprehensive_news()

    print("\n" + "=" * 60)
    print("消息面数据采集结果:")
    print("=" * 60)

    import json

    print(json.dumps(data, indent=2, ensure_ascii=False))
