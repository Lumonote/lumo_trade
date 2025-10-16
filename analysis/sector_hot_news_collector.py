#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块热门新闻采集器
按行业/板块关键词（如“半导体”“光伏”等）聚合相关新闻，
来源以东方财富搜索为主，兼容页面结构差异，输出统一结构。

输出字段：title, url, source, publish_time, heat(0-100), rank, sector_name
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from datetime import datetime
import urllib.parse
import re
import unicodedata


class SectorNewsCollector:
    """板块新闻采集器"""

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://so.eastmoney.com/'
        }
        # 宏观词黑名单：过滤与板块无关的宏观新闻
        self.macro_blacklist = {
            '美联储', '联邦', '就业', '通胀', 'CPI', 'GDP', 'PPI', '制造业指数', 'PMI', '纳斯达克', '标普', '道琼斯',
            '央行', '货币政策', '财政', '国际关系', '地缘', '宏观', '外贸', '进出口', '美元', '汇率'
        }
        # 板块相关词白名单：提升行业/概念相关性
        self.board_whitelist = {'板块', '行业', '概念', '个股', '公司', '龙头', '涨', '跌', '估值', '景气', '赛道'}
        # 可信来源域名
        self.allowed_domains = (
            'eastmoney.com', '10jqka.com.cn', 'xueqiu.com', 'stcn.com', 'finance.sina.com.cn', 'cj.sina.com.cn',
            'cnstock.com', 'stock.qq.com', 'jrj.com.cn', 'hexun.com', 'wallstreetcn.com'
        )

    def get_top_news_by_sectors(self, sector_names: List[str], per_sector_limit: int = 5, total_limit: int = 10) -> List[Dict]:
        """按板块关键词采集并合并Top新闻

        Args:
            sector_names: 板块/行业名称列表（将去重与清洗）
            per_sector_limit: 每个板块最多采集条数
            total_limit: 合并后返回的总条数上限
        """
        if not sector_names:
            return []

        # 去重与清洗
        uniq_names = []
        seen = set()
        for n in sector_names:
            n = (n or '').strip()
            if not n or n.lower() in ('n/a', '未知'):
                continue
            if n not in seen:
                seen.add(n)
                uniq_names.append(n)

        items: List[Dict] = []

        # 采集各板块新闻
        for idx, sector in enumerate(uniq_names):
            try:
                fetched = self._fetch_by_keyword(sector, max_items=per_sector_limit)
                # 赋热度基础权重：靠前板块略高
                base_weight = 1.0 - min(0.5, idx * 0.08)
                for rank, it in enumerate(fetched, start=1):
                    heat = max(20, int((per_sector_limit + 5 - rank) / (per_sector_limit + 5) * 100 * base_weight))
                    items.append({
                        'title': it.get('title', ''),
                        'url': it.get('url', ''),
                        'source': it.get('source', '东方财富网'),
                        'publish_time': it.get('date', it.get('publish_time', '')) or datetime.now().strftime('%Y-%m-%d %H:%M'),
                        'heat': heat,
                        'rank': rank,  # 临时rank，后续按合并排序重赋
                        'sector_name': sector
                    })
            except Exception:
                continue

        if not items:
            return []

        # 合并去重（按title+url保留热度高的）
        uniq = {}
        for it in items:
            key = ((it.get('title') or '').strip(), (it.get('url') or '').strip())
            if not key[0]:
                continue
            old = uniq.get(key)
            if (old is None) or (it.get('heat', 0) > old.get('heat', 0)):
                uniq[key] = it

        merged = list(uniq.values())
        merged.sort(key=lambda x: x.get('heat', 0), reverse=True)

        # 重新赋rank
        for i, it in enumerate(merged[:total_limit], start=1):
            it['rank'] = i

        return merged[:total_limit]

    def _fetch_by_keyword(self, keyword: str, max_items: int = 8) -> List[Dict]:
        """东方财富搜索按关键词抓取新闻列表（尽量稳健解析页面结构）"""
        url = f"https://so.eastmoney.com/news/s?keyword={urllib.parse.quote(keyword)}"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')

        items: List[Dict] = []
        candidates = []
        for class_name in ['news-item', 'result-item', 'search-item', 'list-item', 'item', 'article']:
            candidates += soup.find_all('div', class_=class_name)
            candidates += soup.find_all('li', class_=class_name)

        if not candidates:
            # 退回通用li策略
            candidates = [li for li in soup.find_all('li') if li.find('a') and len(li.get_text(strip=True)) > 10]

        for it in candidates[:max_items * 2]:
            a_tags = [a for a in it.find_all('a', href=True) if a.get_text(strip=True)]
            if not a_tags:
                continue
            a = max(a_tags, key=lambda x: len(x.get_text(strip=True)))
            title = self._clean_text(a.get_text(strip=True))
            href = a.get('href', '')
            if not title or len(title) < 6:
                continue
            if not href:
                continue

            # 过滤明显广告或推广链接
            bad_hosts = ['acttg.eastmoney.com', 'tg.eastmoney.com']
            if any(b in href for b in bad_hosts):
                continue

            # 日期提取
            date_text = ''
            date_elem = (
                it.find('span', class_='date') or it.find('span', class_='time') or it.find('time') or
                it.find('em', class_='time') or it.find('p', class_='time')
            )
            if date_elem:
                date_text = date_elem.get_text(strip=True)

            # 来源提取
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
                'url': href if href.startswith('http') else f"https://so.eastmoney.com{href}",
                'source': source,
                'date': date_text,
                'publish_time': date_text,
            })

        # 候选解析不足时，全局a标签兜底
        if len(items) < max_items // 2:
            for a in soup.find_all('a', href=True):
                text = self._clean_text(a.get_text(strip=True))
                href = a.get('href', '')
                if not text or not href:
                    continue
                if len(text) < 8:
                    continue
                if any(b in href for b in ['acttg.eastmoney.com', 'tg.eastmoney.com']):
                    continue
                if not (href.endswith('.html') or 'news' in href or 'finance' in href):
                    continue
                items.append({
                    'title': text,
                    'url': href if href.startswith('http') else f"https://so.eastmoney.com{href}",
                    'source': '东方财富网',
                    'date': '',
                    'publish_time': ''
                })

        # 相关性过滤：标题需包含板块词，且不含宏观黑名单；来源限制
        filtered: List[Dict] = []
        for it in items:
            title = it.get('title', '')
            url = it.get('url', '')
            if not self._is_relevant(title, keyword):
                continue
            if not self._is_allowed_domain(url):
                continue
            filtered.append(it)

        return filtered[:max_items]

    def _clean_text(self, text: str) -> str:
        if not text:
            return ''
        # 去除不可显示字符和常见乱码符号
        text = text.replace('\uFFFD', '').replace('�', '')
        text = re.sub(r"[\u0000-\u001F]", "", text)
        # 归一化全半角
        text = unicodedata.normalize('NFKC', text)
        return text.strip()

    def _is_allowed_domain(self, url: str) -> bool:
        try:
            host = urllib.parse.urlparse(url).netloc
            return any(d in host for d in self.allowed_domains)
        except Exception:
            return False

    def _is_relevant(self, title: str, sector: str) -> bool:
        t = (title or '').strip()
        s = (sector or '').strip()
        if not t or not s:
            return False
        # 宏观黑名单过滤
        if any(b in t for b in self.macro_blacklist):
            return False
        # 必须包含板块词或其同义词
        if not self._contains_sector(t, s):
            return False
        # 加分项：包含行业/板块等词，提高相关性
        if any(w in t for w in self.board_whitelist):
            return True
        # 否则要求有与股票相关的词
        stock_words = {'个股', '公司', '龙头', '涨停', '跌停', '估值', '盈利', '订单', '出货', '扩产', '降价', '提价'}
        return any(w in t for w in stock_words)

    def _contains_sector(self, text: str, sector: str) -> bool:
        # 简单同义词映射
        syn = {
            '半导体': ['芯片', '集成电路', 'IC', '晶圆'],
            '光伏': ['太阳能', '硅料', '硅片', '电池片', '组件'],
            '锂电': ['动力电池', '电池', '电池产业链', '正极', '负极', '隔膜', '电解液'],
            '新能源': ['风电', '光伏', '储能', '氢能'],
            '算力': ['数据中心', 'AI算力', 'GPU', '服务器'],
            '人工智能': ['AI', '大模型', 'AIGC'],
            '汽车': ['整车', '新能源车', '车企', '乘用车'],
            '券商': ['证券', '经纪业务', '投行'],
            '银行': ['商业银行', '存款', '贷款'],
            '保险': ['寿险', '财险'],
            '地产': ['房地产', '房企']
        }
        s = sector
        tokens = [s]
        for k, v in syn.items():
            if k in s:
                tokens += v
        return any(tok in text for tok in tokens)


if __name__ == '__main__':
    c = SectorNewsCollector()
    data = c.get_top_news_by_sectors(['半导体', '新能源', '算力', 'AI应用'], per_sector_limit=3, total_limit=10)
    import json
    print(json.dumps(data, ensure_ascii=False, indent=2))