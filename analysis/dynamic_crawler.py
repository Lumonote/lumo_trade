#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态网页爬虫模块 - 使用Playwright处理JavaScript渲染的页面
"""

from bs4 import BeautifulSoup
from typing import List, Dict
import time
import re
import threading
from datetime import datetime


class DynamicCrawler:
    """动态网页爬虫 - 支持JavaScript渲染"""
    
    # 限制并发浏览器实例数，防止EPIPE错误和资源耗尽
    # 即使在多线程环境下，也最多只允许2个浏览器同时运行
    _browser_semaphore = threading.Semaphore(6)

    @staticmethod
    def crawl_guba_posts(stock_code: str, limit: int = 50) -> List[Dict]:
        """
        爬取股吧帖子列表 - 改进版，支持重试和多种等待策略

        Args:
            stock_code: 股票代码
            limit: 采样评论数

        Returns:
            list: 帖子列表
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

            max_retries = 3
            retry_delay = 2

            for attempt in range(max_retries):
                try:
                    # 使用信号量控制并发
                    with DynamicCrawler._browser_semaphore:
                        with sync_playwright() as p:
                            # 使用自定义浏览器参数
                            browser = p.chromium.launch(
                                headless=True,
                                args=['--disable-blink-features=AutomationControlled']
                            )

                            context = browser.new_context(
                                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                                viewport={'width': 1920, 'height': 1080}
                            )
                            page = context.new_page()

                            url = f"http://guba.eastmoney.com/list,{stock_code}.html"
                            print(f"   🌐 访问股吧 (尝试 {attempt + 1}/{max_retries}): {url}")

                            # 改用load等待策略，更快
                            # 尝试多种排序/参数的搜索结果，提高解析成功率
                            candidate_urls = [
                                f"https://so.eastmoney.com/news/s?keyword={stock_code}",
                                f"https://so.eastmoney.com/news/s?keyword={stock_code}&sort=time",
                                f"https://so.eastmoney.com/news/s?keyword={stock_code}&sort=score",
                            ]

                            content = ''
                            for idx, u in enumerate(candidate_urls, start=1):
                                print(f"   🌐 访问新闻候选URL {idx}/{len(candidate_urls)}: {u}")
                                page.goto(u, wait_until='load', timeout=30000)
                                page.wait_for_timeout(4000)

                                # 逐步滚动触发懒加载
                                try:
                                    for _ in range(2):
                                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                        page.wait_for_timeout(800)
                                except:
                                    pass

                                # 获取HTML
                                content = page.content()
                                # 简单判断是否包含新闻结构标记，否则继续尝试下一个URL
                                if any(k in content for k in ['news', 'result', 'search']):
                                    break

                            # 等待页面渲染
                            page.wait_for_timeout(5000)

                            # 尝试滚动页面触发懒加载
                            try:
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                page.wait_for_timeout(2000)
                            except:
                                pass

                            # 获取渲染后的HTML
                            content = page.content()
                            browser.close()

                        # 解析HTML
                        soup = BeautifulSoup(content, 'html.parser')

                        posts = []

                        # 尝试多种选择器查找帖子
                        selectors = [
                            ('div', 'articleh'),
                            ('div', 'normal_post'),
                            ('div', 'list-item'),
                            ('div', 'post-item'),
                            ('tr', None),  # 尝试表格行
                            ('li', 'item'),
                        ]

                        elements = []
                        for tag, class_name in selectors:
                            if class_name:
                                elements = soup.find_all(tag, class_=class_name)
                            else:
                                # 对于tr，查找包含文章标题的行
                                all_elements = soup.find_all(tag)
                                elements = [e for e in all_elements if e.find('a')]

                            if elements and len(elements) > 3:  # 至少找到3个才算有效
                                print(
                                    f"   ✅ 找到{len(elements)}个元素 (选择器: {tag}.{class_name if class_name else 'any'})")
                                break

                        if not elements:
                            print(f"   ⚠️  未找到帖子元素 (尝试 {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                            return []

                        for elem in elements[:limit]:
                            # 尝试提取标题
                            title_elem = None
                            title_selectors = [
                                ('a', 'title'),
                                ('span', 'l3'),
                                ('a', 'article-title'),
                                ('a', None),
                                ('span', 'title-text'),
                            ]

                            for tag, class_name in title_selectors:
                                if class_name:
                                    title_elem = elem.find(tag, class_=class_name)
                                else:
                                    title_elem = elem.find(tag)
                                if title_elem:
                                    break

                            if not title_elem:
                                continue

                            title = title_elem.get_text(strip=True)
                            if not title or len(title) < 2:
                                continue

                            # 提取其他信息
                            author_elem = elem.find('span', class_='l4') or elem.find('a', class_='author')
                            author = author_elem.get_text(strip=True) if author_elem else '匿名'

                            read_elem = elem.find('span', class_='l1') or elem.find('span', class_='read-count')
                            read_count = read_elem.get_text(strip=True) if read_elem else '0'

                            comment_elem = elem.find('span', class_='l2') or elem.find('span', class_='comment-count')
                            comment_count = comment_elem.get_text(strip=True) if comment_elem else '0'

                            posts.append({
                                'title': title,
                                'author': author,
                                'read_count': read_count,
                                'comment_count': comment_count
                            })

                        if posts:
                            print(f"   ✅ 成功解析{len(posts)}条有效帖子")
                            return posts

                        print(f"   ⚠️  未解析到有效帖子 (尝试 {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue

                except PlaywrightTimeout:
                    print(f"   ⚠️  页面加载超时 (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                except Exception as e:
                    print(f"   ⚠️  爬取出错: {e} (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue

            return []

        except ImportError:
            print(f"   ⚠️  Playwright未安装")
            print(f"   💡 请运行: pip install playwright && playwright install chromium")
            return []
        except Exception as e:
            print(f"   ⚠️  Playwright爬取失败: {e}")
            return []

    @staticmethod
    def crawl_news_list(stock_code: str, limit: int = 10) -> List[Dict]:
        """
        爬取股票新闻列表 - 改进版v2，使用更通用的选择器

        Args:
            stock_code: 股票代码
            limit: 新闻数量限制

        Returns:
            list: 新闻列表
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

            max_retries = 2
            retry_delay = 2

            for attempt in range(max_retries):
                try:
                    # 使用信号量控制并发
                    with DynamicCrawler._browser_semaphore:
                        with sync_playwright() as p:
                            browser = p.chromium.launch(
                                headless=True,
                                args=['--disable-blink-features=AutomationControlled']
                            )
                            context = browser.new_context(
                                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                            )
                            page = context.new_page()

                            # --- 策略升级：优先尝试股吧资讯 (Guba News) ---
                            guba_success = False
                            guba_news = []
                            try:
                                guba_url = f"http://guba.eastmoney.com/list,{stock_code},1,f.html"
                                print(f"   🌐 尝试股吧资讯: {guba_url}")
                                page.goto(guba_url, wait_until='domcontentloaded', timeout=15000)
                                page.wait_for_timeout(2000)
                                g_content = page.content()
                                g_soup = BeautifulSoup(g_content, 'html.parser')
                                
                                # 解析股吧
                                g_items = g_soup.find_all('div', class_='articleh') or g_soup.find_all('div', class_='list-item')
                                for item in g_items[:limit]:
                                    title_elem = item.find('span', class_='l3') 
                                    a = title_elem.find('a') if title_elem else (item.find('a', class_='title') or item.find('a'))
                                    if a:
                                        t = a.get_text(strip=True)
                                        if t and len(t) > 6 and not re.search(r'\[(of|so)\d+\]', t, re.IGNORECASE):
                                            u = a.get('href', '')
                                            if not u.startswith('http'): u = f"http://guba.eastmoney.com{u}"
                                            dt = item.find('span', class_='l5')
                                            d = dt.get_text(strip=True) if dt else ''
                                            guba_news.append({'title': t, 'url': u, 'publish_time': d, 'source': '东财股吧', 'summary': t})
                                
                                if guba_news:
                                    guba_success = True
                            except Exception as e:
                                print(f"   ⚠️ 股吧尝试失败: {e}")

                            if guba_success:
                                print(f"   ✅ 股吧获取成功: {len(guba_news)}条")
                                browser.close()
                                return guba_news

                            # --- 回退：原有搜索逻辑 ---
                            # 使用东方财富搜索新闻页(按关键词=股票代码)
                            url = f"https://so.eastmoney.com/news/s?keyword={stock_code}"
                            print(f"   🌐 访问新闻搜索 (尝试 {attempt + 1}/{max_retries}): {url}")

                            page.goto(url, wait_until='load', timeout=30000)

                            # 等待页面初始渲染
                            page.wait_for_timeout(3000)

                            # 轻度滚动以触发懒加载
                            try:
                                for _ in range(2):
                                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                    page.wait_for_timeout(800)
                            except:
                                pass

                            # 获取HTML内容（确保定义content，避免NameError）
                            content = page.content()

                            # 调试：保存HTML到临时文件
                            # import tempfile
                            # with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                            #     f.write(content)
                            #     print(f"   🔍 调试: HTML已保存到 {f.name}")

                            browser.close()

                        soup = BeautifulSoup(content, 'html.parser')

                        news_list = []

                        # 更针对东方财富搜索页的选择器
                        news_items = []

                        # 优先：ul新闻列表结构
                        ul_candidates = []
                        for ul in soup.find_all('ul'):
                            cls = (ul.get('class') or [])
                            idv = ul.get('id') or ''
                            text_len = len(ul.get_text(strip=True))
                            if (
                                ('news' in ' '.join(cls).lower() or 'list' in ' '.join(cls).lower() or 'news' in idv.lower())
                                and text_len > 50
                            ):
                                ul_candidates.append(ul)
                        for ul in ul_candidates:
                            lis = ul.find_all('li')
                            if len(lis) >= 3:
                                news_items = lis
                                print(f"   ✅ 找到{len(lis)}个新闻候选 (ul列表)")
                                break

                        # 次选：常见新闻容器class
                        if not news_items:
                            for class_name in ['news-item', 'result-item', 'search-item', 'list-item', 'item', 'article']:
                                items = soup.find_all('div', class_=class_name) + soup.find_all('li', class_=class_name)
                                if len(items) > 2:
                                    news_items = items
                                    print(f"   ✅ 找到{len(items)}个新闻候选 (class={class_name})")
                                    break

                        # 兜底：包含<a>标签的li元素
                        if not news_items:
                            all_li = soup.find_all('li')
                            news_items = [li for li in all_li if li.find('a') and len(li.get_text(strip=True)) > 10]
                            if len(news_items) > 2:
                                print(f"   ✅ 找到{len(news_items)}个新闻候选 (通用li)")

                        # 最后：包含标题的div
                        if not news_items:
                            all_divs = soup.find_all('div')
                            news_items = [div for div in all_divs if div.find('a') and 20 < len(div.get_text(strip=True)) < 500]
                            if len(news_items) > 2:
                                news_items = news_items[:50]  # 限制数量避免误匹配
                                print(f"   ✅ 找到{len(news_items)}个新闻候选 (通用div)")

                        if not news_items or len(news_items) < 2:
                            print(f"   ⚠️  未找到新闻元素 (尝试 {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                            return []

                        for item in news_items[:limit * 2]:  # 多获取一些以防部分解析失败
                            # 在容器内选择文本最长的链接，避免选到“查看详情”一类
                            a_tags = [a for a in item.find_all('a', href=True) if a.get_text(strip=True)]
                            if not a_tags:
                                continue
                            title_elem = max(a_tags, key=lambda x: len(x.get_text(strip=True)))
                            title = title_elem.get_text(strip=True)

                            # 过滤无效标题（更宽松）
                            if not title or len(title) < 6:
                                continue

                            # 过滤导航栏、用户链接等非新闻内容(不区分大小写)
                            title_lower = title.lower()
                            skip_keywords = [
                                '首页', '登录', '注册', '关于', '联系', '帮助',
                                '股友', 'level', 'choice', 'api', 'app',
                                '限售股解禁',
                                '数据中心', '行情中心', '资讯中心'
                            ]
                            if any(skip.lower() in title_lower for skip in skip_keywords):
                                continue

                            # 过滤非股票类代码（如基金of、期权so）
                            # 用户反馈: 长盛同裕...[of002285]; 50ETF购3...[so10002285]
                            import re
                            if re.search(r'\[(of|so)\d+\]', title_lower):
                                continue

                            link = title_elem.get('href', '')
                            if not link:
                                continue

                            # 过滤非新闻URL（用户主页、工具页面等）
                            skip_urls = ['i.eastmoney.com', 'acttg.eastmoney.com', 'quantapi', 'choiceapp', '/dxf/']
                            if any(skip_url in link for skip_url in skip_urls):
                                continue

                            # 优先选择疑似新闻详情页链接
                            if not (link.endswith('.html') or '/a/' in link or '/news/' in link or 'finance' in link):
                                # 尝试容器内其他a标签
                                fallback_a = next((a for a in item.find_all('a', href=True)
                                                   if a.get('href', '').endswith('.html')), None)
                                if fallback_a:
                                    link = fallback_a.get('href')

                            # 规范相对链接
                            if not link.startswith('http'):
                                link = f'https://so.eastmoney.com{link}'

                            # 提取日期 - 多种模式（未命中则置空，避免误填今天）
                            date_text = ''
                            date_patterns = [
                                ('span', 'date'),
                                ('span', 'time'),
                                ('span', 'publish-time'),
                                ('time', None),
                                ('span', 'pub-time'),
                            ]

                            for tag, class_name in date_patterns:
                                if class_name:
                                    date_elem = item.find(tag, class_=class_name)
                                else:
                                    date_elem = item.find(tag)
                                if date_elem:
                                    date_text = date_elem.get_text(strip=True)
                                    break

                            # 如果没找到日期标签，尝试正则匹配
                            if not date_text:
                                # 支持YYYY-MM-DD或MM-DD HH:MM等常见格式
                                date_match = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2})', item.get_text())
                                if date_match:
                                    date_text = date_match.group(0)

                            # 提取来源
                            source = '东方财富网'
                            source_patterns = [
                                ('span', 'source'),
                                ('span', 'media'),
                                ('span', 'from'),
                                ('span', 'author'),
                                ('p', 'source'),
                                ('em', 'source'),
                            ]

                            for tag, class_name in source_patterns:
                                source_elem = item.find(tag, class_=class_name)
                                if source_elem:
                                    source_text = source_elem.get_text(strip=True)
                                    if source_text and len(source_text) < 30:
                                        source = source_text
                                        break

                            news_list.append({
                                'title': title,
                                'url': link,
                                'publish_time': date_text,
                                'source': source,
                                'summary': title[:100]
                            })

                            if len(news_list) >= limit:
                                break

                        if news_list:
                            print(f"   ✅ 成功解析{len(news_list)}条新闻")
                            return news_list

                        # 兜底：全局扫描<a>，选取疑似新闻详情页链接
                        if not news_list:
                            fallback_news = []
                            for a in soup.find_all('a', href=True):
                                text = a.get_text(strip=True)
                                href = a.get('href', '')
                                if not text or not href:
                                    continue
                                if len(text) < 6 or len(text) > 120:
                                    continue
                                # 过滤文本为URL的情况
                                if text.startswith('http'):
                                    continue
                                # 要求包含中文或字母，避免纯符号
                                if not re.search(r'[\u4e00-\u9fffA-Za-z]', text):
                                    continue

                                # 过滤非股票类代码（如基金of、期权so）
                                if re.search(r'\[(of|so)\d+\]', text, re.IGNORECASE):
                                    continue

                                # 仅保留东方财富及常见新闻详情结构
                                if (
                                    'eastmoney.com' in href and (
                                        href.endswith('.html') or '/a/' in href or '/news/' in href or 'finance' in href
                                    )
                                ):
                                    if not href.startswith('http'):
                                        href = f'https://so.eastmoney.com{href}'
                                    fallback_news.append({
                                        'title': text,
                                        'url': href,
                                        'publish_time': '',
                                        'source': '东方财富网',
                                        'summary': text[:100]
                                    })
                                    if len(fallback_news) >= limit:
                                        break

                            if fallback_news:
                                print(f"   ✅ 兜底解析{len(fallback_news)}条新闻")
                                return fallback_news

                        print(f"   ⚠️  未解析到有效新闻 (尝试 {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue

                except PlaywrightTimeout:
                    print(f"   ⚠️  页面加载超时 (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                except Exception as e:
                    print(f"   ⚠️  爬取出错: {e} (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue

            return []

        except ImportError:
            print(f"   ⚠️  Playwright未安装")
            return []
        except Exception as e:
            print(f"   ⚠️  Playwright爬取新闻失败: {e}")
            return []

    @staticmethod
    def crawl_announcements(stock_code: str, limit: int = 10) -> List[Dict]:
        """
        爬取公司公告列表 - 改进版

        Args:
            stock_code: 股票代码
            limit: 公告数量限制

        Returns:
            list: 公告列表
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

            max_retries = 2
            retry_delay = 2

            for attempt in range(max_retries):
                try:
                    # 使用信号量控制并发
                    with DynamicCrawler._browser_semaphore:
                        with sync_playwright() as p:
                            browser = p.chromium.launch(
                                headless=True,
                                args=['--disable-blink-features=AutomationControlled']
                            )
                            context = browser.new_context(
                                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                            )
                            page = context.new_page()

                            # 东方财富公告页
                            url = f"http://data.eastmoney.com/notices/stock/{stock_code}.html"
                            print(f"   🌐 访问公告 (尝试 {attempt + 1}/{max_retries}): {url}")

                            page.goto(url, wait_until='load', timeout=30000)
                            page.wait_for_timeout(4000)

                            # 滚动页面
                            try:
                                page.evaluate("window.scrollTo(0, 500)")
                                page.wait_for_timeout(1000)
                            except:
                                pass

                            content = page.content()
                            browser.close()

                        soup = BeautifulSoup(content, 'html.parser')

                        announcements = []

                        # 多种选择器查找公告表格或列表容器
                        table = soup.find('table', class_='default_web_table') or \
                                soup.find('table') or \
                                soup.find('div', class_='notice-list') or \
                                soup.find('ul', class_='announcement-list')

                        if not table:
                            print(f"   ⚠️  未找到公告表格 (尝试 {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                            return []

                        # 提取表格行
                        if table.name == 'table':
                            rows = table.find_all('tr')[1:]  # 跳过表头
                        elif table.name == 'ul':
                            rows = table.find_all('li')
                        else:
                            rows = table.find_all('div', class_='item')

                        if not rows or len(rows) < 2:
                            # 直接查找包含公告详情链接的a标签
                            direct_items = []
                            for a in soup.find_all('a', href=True):
                                href = a.get('href', '')
                                text = a.get_text(strip=True)
                                if '/notices/detail/' in href and text and len(text) >= 6:
                                    direct_items.append(a)

                            if not direct_items:
                                print(f"   ⚠️  未找到公告行 (尝试 {attempt + 1}/{max_retries})")
                                if attempt < max_retries - 1:
                                    time.sleep(retry_delay)
                                    continue
                                return []
                            rows = direct_items

                        print(f"   ✅ 找到{len(rows)}条公告候选")

                        for row in rows[:limit]:
                            # 提取公告标题和链接
                            title_elem = row.find('a') if hasattr(row, 'find') else row
                            if not title_elem:
                                continue

                            title = title_elem.get_text(strip=True)
                            if not title or len(title) < 5:
                                continue

                            link = title_elem.get('href', '')

                            # 提取日期
                            cells = row.find_all('td') if hasattr(row, 'find_all') and row.name == 'tr' else (
                                [row] if hasattr(row, 'get_text') else [])

                            date_text = ''
                            if len(cells) > 0:
                                # 尝试在第一列找日期
                                date_elem = cells[0].find('span', class_='date') or cells[0]
                                date_text = date_elem.get_text(strip=True)

                                # 如果第一列不是日期，试试其他列
                                if not re.search(r'\d{4}', date_text):
                                    for cell in cells:
                                        text = cell.get_text(strip=True)
                                        if re.search(r'\d{4}', text):
                                            date_text = text
                                            break

                            if not date_text:
                                # 再尝试在title元素的父级文本中用正则匹配日期
                                try:
                                    text_ctx = title_elem.parent.get_text(" ",
                                                                          strip=True) if title_elem and title_elem.parent else ''
                                    m = re.search(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})', text_ctx)
                                    if m:
                                        date_text = m.group(1)
                                except Exception:
                                    pass
                            if not date_text:
                                # 保持为空，后续由上层统一归一化/兜底
                                date_text = ''

                            # 提取类型
                            ann_type = '其他'
                            if len(cells) > 2:
                                type_elem = cells[2]
                                ann_type = type_elem.get_text(strip=True) if type_elem else '其他'

                            announcements.append({
                                'title': title,
                                'url': link if link.startswith('http') else f'http://data.eastmoney.com{link}',
                                'publish_time': date_text,
                                'type': ann_type,
                                'importance': 'medium'
                            })

                        if announcements:
                            print(f"   ✅ 成功解析{len(announcements)}条公告")
                            return announcements

                        print(f"   ⚠️  未解析到有效公告 (尝试 {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            continue

                except PlaywrightTimeout:
                    print(f"   ⚠️  页面加载超时 (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                except Exception as e:
                    print(f"   ⚠️  爬取出错: {e} (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue

            return []

        except ImportError:
            print(f"   ⚠️  Playwright未安装")
            return []
        except Exception as e:
            print(f"   ⚠️  Playwright爬取公告失败: {e}")
            return []
