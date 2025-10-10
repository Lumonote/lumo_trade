#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息面采集模块
采集股票相关的新闻、公告、研报等消息面数据
"""

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

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from analysis.dynamic_crawler import DynamicCrawler


class NewsSentimentCollector:
    """消息面采集器"""

    def __init__(self, stock_code):
        """
        初始化消息面采集器

        Args:
            stock_code: 股票代码 (例如: '688343', '000001')
        """
        self.stock_code = stock_code
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/'
        }

    def get_latest_announcements(self, limit=10):
        """
        获取最新公告 - 使用Playwright爬取

        Args:
            limit: 获取公告数量

        Returns:
            list: 公告列表
        """
        # 首先尝试使用Playwright爬取
        announcements = DynamicCrawler.crawl_announcements(self.stock_code, limit)

        if announcements:
            # 为Playwright爬取的公告重新分类重要性(覆盖默认的'medium')
            for ann in announcements:
                ann['importance'] = self._classify_importance(ann.get('title', ''))
                # 确保有摘要字段
                if 'summary' not in ann:
                    ann['summary'] = self._extract_summary(ann.get('title', ''))

            print(f"   ✅ Playwright成功获取{len(announcements)}条公告")
            return announcements

        # Playwright失败，尝试API
        print(f"   ⚠️  Playwright爬取失败,尝试API接口")
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
                print(f"   🔁 尝试公告API代码格式({idx}/{len(variants)}): stock_list={code_variant}")
                response = requests.get(url, params=params, headers=self.headers, timeout=10)
                data = response.json()

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
                    break  # 成功则不再尝试更多格式

            # 如果API返回空数据,尝试网页爬取
            if not announcements:
                print(f"   ⚠️  API未返回公告数据,尝试网页爬取")
                announcements = self._scrape_announcements(limit)

            return announcements[:limit]

        except Exception as e:
            print(f"⚠️ 获取公告失败: {str(e)},尝试网页爬取")
            return self._scrape_announcements(limit)

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
                if not date_text:
                    date_text = datetime.now().strftime('%Y-%m-%d')

                announcements.append({
                    'title': title,
                    'date': date_text,
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
        # 首先尝试使用Playwright爬取
        news_list = DynamicCrawler.crawl_news_list(self.stock_code, limit)

        if news_list:
            # 为Playwright爬取的新闻添加情感分析
            for news in news_list:
                if 'sentiment' not in news:
                    # 使用标题和摘要进行情感分析
                    text = news.get('title', '') + ' ' + news.get('summary', '')
                    news['sentiment'] = self._analyze_sentiment(text)

            print(f"   ✅ Playwright成功获取{len(news_list)}条新闻")
            return news_list

        # Playwright失败，尝试API
        print(f"   ⚠️  Playwright爬取失败,尝试API接口")
        try:
            # 现阶段新闻API不稳定，直接快速回退至网页爬取
            print(f"   ⚠️  API未返回新闻数据或不稳定,直接网页爬取")
            news_list = self._scrape_news(limit)
            return news_list[:limit]

        except Exception as e:
            print(f"⚠️ 获取新闻失败: {str(e)},尝试网页爬取")
            return self._scrape_news(limit)

    def _scrape_news(self, limit=20):
        """网页爬取新闻数据"""
        try:
            # 东方财富搜索新闻页（按关键词=股票代码）
            url = f"https://so.eastmoney.com/news/s?keyword={self.stock_code}"

            response = requests.get(url, headers=self.headers, timeout=10)
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            news_list = []
            # 选择器较为通用：查找包含标题链接的li/div项
            candidates = []
            for class_name in ['news-item', 'result-item', 'search-item', 'list-item', 'item', 'article']:
                candidates += soup.find_all('div', class_=class_name)
                candidates += soup.find_all('li', class_=class_name)

            if not candidates:
                # 退回通用li策略
                candidates = [li for li in soup.find_all('li') if li.find('a') and len(li.get_text(strip=True)) > 10]

            for item in candidates[:limit * 2]:
                a = item.find('a', href=True)
                if not a:
                    continue
                title = a.get_text(strip=True)
                if not title or len(title) < 8:
                    continue
                href = a.get('href', '')
                if not href:
                    continue

                # 过滤广告或活动页
                bad_hosts = ['acttg.eastmoney.com', 'tg.eastmoney.com', 'emapp', 'dfcfwl2']
                if any(b in href for b in bad_hosts) or 'Level-2' in title or '开户' in title or '理财' in title:
                    continue

                # 日期提取
                date_text = ''
                date_elem = item.find('span', class_='date') or item.find('span', class_='time') or item.find('time')
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                else:
                    m = re.search(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})', item.get_text(" ", strip=True))
                    if m:
                        date_text = m.group(1)

                # 来源提取
                source = '东方财富网'
                source_elem = item.find('span', class_='source')
                if source_elem:
                    st = source_elem.get_text(strip=True)
                    if st and len(st) < 30:
                        source = st

                news_list.append({
                    'title': title,
                    'date': date_text,
                    'source': source,
                    'url': href if href.startswith('http') else f"https://so.eastmoney.com{href}",
                    'summary': self._extract_summary(title),
                    'sentiment': self._analyze_sentiment(title)
                })

            if not news_list:
                print(f"   ⚠️  网页爬取也未获取到新闻")

            return news_list

        except Exception as e:
            print(f"⚠️ 网页爬取新闻失败: {str(e)}")
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
            # 东方财富研报API
            url = "http://reportapi.eastmoney.com/report/list"
            params = {
                'qType': '0',
                'pageSize': str(limit),
                'code': self.stock_code
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            reports = []
            if data.get('data'):
                for item in data['data']:
                    report = {
                        'title': item.get('title', ''),
                        'date': item.get('publishDate', ''),
                        'institution': item.get('orgSName', ''),
                        'researcher': item.get('researcher', ''),
                        'rating': item.get('investRating', ''),
                        'target_price': item.get('predictNextTwoYearEps', ''),
                        'summary': item.get('title', '')[:100],
                    }
                    reports.append(report)

            return reports[:limit]

        except Exception as e:
            print(f"⚠️ 获取研报失败: {str(e)}")
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

    def _get_mock_announcements(self, limit=10):
        """生成示例公告数据"""
        from datetime import datetime, timedelta

        mock_announcements = [
            {'title': '2024年第三季度业绩预告', 'importance': '高', 'days_ago': 2},
            {'title': '关于股东增持股份计划的公告', 'importance': '高', 'days_ago': 5},
            {'title': '董事会决议公告', 'importance': '中', 'days_ago': 7},
            {'title': '关于获得政府补助的公告', 'importance': '中', 'days_ago': 10},
            {'title': '关于签订重大合同的公告', 'importance': '高', 'days_ago': 12},
            {'title': '投资者关系活动记录表', 'importance': '低', 'days_ago': 15},
            {'title': '监事会决议公告', 'importance': '低', 'days_ago': 18},
            {'title': '关于回购股份的进展公告', 'importance': '中', 'days_ago': 20},
            {'title': '独立董事关于相关事项的独立意见', 'importance': '低', 'days_ago': 22},
            {'title': '关于使用闲置募集资金进行现金管理的公告', 'importance': '中', 'days_ago': 25},
        ]

        announcements = []
        for i, item in enumerate(mock_announcements[:limit]):
            date = (datetime.now() - timedelta(days=item['days_ago'])).strftime('%Y-%m-%d')
            announcements.append({
                'title': item['title'],
                'date': date,
                'type': '公告',
                'url': f"http://data.eastmoney.com/notices/detail/{self.stock_code}/AN{date.replace('-', '')}{i:03d}.html",
                'summary': item['title'][:50],
                'importance': item['importance']
            })

        return announcements

    def _get_mock_news(self, limit=20):
        """生成示例新闻数据"""
        from datetime import datetime, timedelta

        mock_news = [
            {'title': '公司三季度业绩超预期,净利润同比增长35%', 'sentiment': '正面', 'days_ago': 1},
            {'title': '机构调研频繁,多家券商上调目标价', 'sentiment': '正面', 'days_ago': 2},
            {'title': '行业景气度持续提升,公司订单饱满', 'sentiment': '正面', 'days_ago': 3},
            {'title': '技术突破获得重大进展,核心竞争力增强', 'sentiment': '正面', 'days_ago': 4},
            {'title': '市场份额稳步提升,龙头地位巩固', 'sentiment': '正面', 'days_ago': 5},
            {'title': '北向资金连续5日净流入,外资看好公司前景', 'sentiment': '正面', 'days_ago': 6},
            {'title': '公司发布股权激励计划,彰显发展信心', 'sentiment': '正面', 'days_ago': 7},
            {'title': '原材料价格波动,短期成本压力加大', 'sentiment': '负面', 'days_ago': 8},
            {'title': '行业竞争加剧,市场格局面临调整', 'sentiment': '中性', 'days_ago': 9},
            {'title': '公司积极拓展海外市场,国际化战略稳步推进', 'sentiment': '正面', 'days_ago': 10},
            {'title': '研发投入持续加大,创新能力显著提升', 'sentiment': '正面', 'days_ago': 11},
            {'title': '分析师预测全年业绩将保持高增长', 'sentiment': '正面', 'days_ago': 12},
            {'title': '监管政策调整,行业发展迎来新机遇', 'sentiment': '正面', 'days_ago': 13},
            {'title': '供应链管理优化,成本控制能力增强', 'sentiment': '正面', 'days_ago': 14},
            {'title': '市场整体调整,公司股价出现回调', 'sentiment': '负面', 'days_ago': 15},
            {'title': '产能扩张项目顺利推进,未来增长可期', 'sentiment': '正面', 'days_ago': 16},
            {'title': '高管增持彰显信心,长期价值获认可', 'sentiment': '正面', 'days_ago': 17},
            {'title': '行业政策利好频出,发展环境持续改善', 'sentiment': '正面', 'days_ago': 18},
            {'title': '公司治理水平提升,获评最佳上市公司', 'sentiment': '正面', 'days_ago': 19},
            {'title': 'ESG评级上调,可持续发展能力受认可', 'sentiment': '正面', 'days_ago': 20},
        ]

        news_list = []
        for item in mock_news[:limit]:
            date = (datetime.now() - timedelta(days=item['days_ago'])).strftime('%Y-%m-%d')
            news_list.append({
                'title': item['title'],
                'date': date,
                'source': '财经资讯' if item['days_ago'] % 3 == 0 else '证券时报' if item[
                                                                                         'days_ago'] % 2 == 0 else '东方财富网',
                'url': f"http://finance.eastmoney.com/news/{date.replace('-', '')}/AN{item['days_ago']:03d}.html",
                'summary': item['title'][:50],
                'sentiment': item['sentiment']
            })

        return news_list

    def _format_stock_code_variants(self, code: str):
        """生成适配东财公告API的股票代码多种格式"""
        code = str(code).strip()
        variants = [code]
        # 根据常见规则推断交易所前缀
        try:
            if code.startswith(('600', '601', '603', '605', '688')):
                prefix = 'SH'
            else:
                prefix = 'SZ'
            variants.extend([f"{prefix}{code}", f"{prefix.lower()}{code}"])
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

    def get_comprehensive_news(self):
        """
        获取综合消息面数据

        Returns:
            dict: 综合消息面数据
        """
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

        print(f"✅ 消息面数据采集完成")
        print(f"   - 公告: {len(data['announcements'])} 条")
        print(f"   - 新闻: {len(data['news'])} 条")
        print(f"   - 研报: {len(data['research_reports'])} 条")
        print(
            f"   - 情感统计: 正面{data['sentiment_summary']['positive']} 负面{data['sentiment_summary']['negative']} 中性{data['sentiment_summary']['neutral']}")

        return data


if __name__ == "__main__":
    # 测试代码
    collector = NewsSentimentCollector("688343")
    data = collector.get_comprehensive_news()

    print("\n" + "=" * 60)
    print("消息面数据采集结果:")
    print("=" * 60)

    import json

    print(json.dumps(data, indent=2, ensure_ascii=False))
