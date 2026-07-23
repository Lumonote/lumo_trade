#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市场热门新闻采集器
从东方财富、同花顺、雪球等来源抓取首页/热点新闻，生成统一TOP列表。

设计目标：
- 尝试多个候选入口，尽量稳健获取首页热点或今日要闻；
- 统一结构：title, url, source, publish_time, heat(0-100), rank；
- 允许部分来源失败，最终合并去重并按热度排序返回TopN。
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict
import time


class GlobalHotNewsCollector:
    """热门新闻采集器"""

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.eastmoney.com/'
        }

    def get_top_news(self, limit: int = 10) -> List[Dict]:
        """获取全市场热门新闻TopN（合并多源并排序）"""
        items: List[Dict] = []
        items += self._fetch_eastmoney_hot_news(limit * 2)
        items += self._fetch_tonghuashun_hot_news(limit * 2)
        items += self._fetch_xueqiu_hot_news(limit * 2)

        # 去重：按title+url，保留热度高的
        uniq = {}
        for it in items:
            key = (it.get('title', '').strip(), it.get('url', '').strip())
            if not key[0]:
                continue
            old = uniq.get(key)
            if (old is None) or (it.get('heat', 0) > old.get('heat', 0)):
                uniq[key] = it

        merged = list(uniq.values())
        merged.sort(key=lambda x: (x.get('heat', 0), 100 - x.get('rank', 100)), reverse=True)

        # 重新赋rank
        for i, it in enumerate(merged[:limit], start=1):
            it['rank'] = i

        return merged[:limit]

    # ----------------- 各来源实现 -----------------
    def _fetch_eastmoney_hot_news(self, limit: int = 20) -> List[Dict]:
        """东方财富热点/要闻页解析"""
        results: List[Dict] = []
        candidates = [
            'https://stock.eastmoney.com/news.html',
            'https://finance.eastmoney.com/',
            'https://finance.eastmoney.com/a/cgsj.html',
            'https://finance.eastmoney.com/yaowen.html'
        ]
        base_weight = 1.0
        for url in candidates:
            try:
                r = requests.get(url, headers=self.headers, timeout=10)
                r.encoding = 'utf-8'
                soup = BeautifulSoup(r.text, 'html.parser')

                # 选择器尝试：常见的列表结构
                blocks = []
                blocks += soup.find_all('div', class_='news-item')
                blocks += soup.find_all('div', class_='item')
                blocks += soup.find_all('li')

                seen_titles = set()
                rank = 0
                for b in blocks:
                    a = b.find('a', href=True) if hasattr(b, 'find') else None
                    if not a:
                        continue
                    title = a.get_text(strip=True)
                    href = a.get('href', '')
                    if not title or len(title) < 8:
                        continue
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)

                    # 时间兜底
                    dt = ''
                    dt_elem = b.find('span', class_='time') if hasattr(b, 'find') else None
                    if dt_elem:
                        dt = dt_elem.get_text(strip=True)
                    if not dt:
                        dt = datetime.now().strftime('%Y-%m-%d %H:%M')

                    rank += 1
                    heat = max(20, int((limit + 5 - rank) / (limit + 5) * 100 * base_weight))
                    results.append({
                        'title': title,
                        'url': href if href.startswith('http') else f"https://stock.eastmoney.com{href}",
                        'source': '东方财富',
                        'publish_time': dt,
                        'heat': heat,
                        'rank': rank,
                    })
                    if len(results) >= limit:
                        break
                if results:
                    break  # 一个入口抓到即可
            except Exception:
                continue
        return results[:limit]

    def _fetch_tonghuashun_hot_news(self, limit: int = 20) -> List[Dict]:
        """同花顺今日要闻/新闻首页解析"""
        results: List[Dict] = []
        candidates = [
            'https://news.10jqka.com.cn/today_list/',
            'https://news.10jqka.com.cn/'
        ]
        base_weight = 0.9
        for url in candidates:
            try:
                r = requests.get(url, headers=self.headers, timeout=10)
                # 同花顺页面服务器声明 charset=gbk，强制 utf-8 会整页解成 � 乱码；
                # 仅当 header 未声明(requests 默认 ISO-8859-1)时才用探测编码兜底
                if not r.encoding or r.encoding.lower() == 'iso-8859-1':
                    r.encoding = r.apparent_encoding or 'utf-8'
                soup = BeautifulSoup(r.text, 'html.parser')

                items = []
                items += soup.find_all('li')
                items += soup.find_all('div', class_='list')
                seen_titles = set()
                rank = 0
                for it in items:
                    a = it.find('a', href=True)
                    if not a:
                        continue
                    title = a.get_text(strip=True)
                    href = a.get('href', '')
                    if not title or len(title) < 8:
                        continue
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)

                    t_elem = it.find('span', class_='date') or it.find('span', class_='time')
                    dt = t_elem.get_text(strip=True) if t_elem else datetime.now().strftime('%Y-%m-%d %H:%M')

                    rank += 1
                    heat = max(18, int((limit + 5 - rank) / (limit + 5) * 100 * base_weight))
                    results.append({
                        'title': title,
                        'url': href,
                        'source': '同花顺',
                        'publish_time': dt,
                        'heat': heat,
                        'rank': rank,
                    })
                    if len(results) >= limit:
                        break
                if results:
                    break
            except Exception:
                continue
        return results[:limit]

    def _fetch_xueqiu_hot_news(self, limit: int = 20) -> List[Dict]:
        """雪球热帖/热文尝试获取（若被反爬则返回空列表）"""
        results: List[Dict] = []
        base_weight = 0.85
        try:
            sess = requests.Session()
            sess.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://xueqiu.com/'
            })
            # 先获取主页以拿到cookie
            sess.get('https://xueqiu.com/', timeout=8)
            # 热帖列表API（可能需要登录cookie，失败则异常）
            resp = sess.get('https://xueqiu.com/statuses/hot/list.json?since_id=-1&max_id=-1&count=20', timeout=8)
            data = resp.json() if resp.status_code == 200 else {}
            list_data = data.get('items', []) or data.get('list', [])
            rank = 0
            for it in list_data:
                title = (it.get('title') or it.get('text') or '').strip()
                if not title or len(title) < 8:
                    continue
                url = it.get('target') or it.get('url') or 'https://xueqiu.com/'
                dt = datetime.fromtimestamp(int(it.get('created_at', time.time()))/1000.0).strftime('%Y-%m-%d %H:%M') if it.get('created_at') else datetime.now().strftime('%Y-%m-%d %H:%M')
                rank += 1
                heat = max(16, int((limit + 5 - rank) / (limit + 5) * 100 * base_weight))
                results.append({
                    'title': title,
                    'url': url,
                    'source': '雪球',
                    'publish_time': dt,
                    'heat': heat,
                    'rank': rank,
                })
                if len(results) >= limit:
                    break
        except Exception:
            # 雪球来源失败时，返回空列表，不影响整体结果
            return []
        return results[:limit]


if __name__ == '__main__':
    c = GlobalHotNewsCollector()
    top = c.get_top_news(limit=10)
    import json
    print(json.dumps(top, ensure_ascii=False, indent=2))