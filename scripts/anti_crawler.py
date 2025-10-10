#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反爬虫处理模块
提供随机延时、用户代理轮换、IP代理支持等功能
"""

import random
import time
import asyncio
from typing import List, Dict, Optional, Any
import logging
from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)


class AntiCrawlerHandler:
    """反爬虫处理器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.user_agents = self._load_user_agents()
        self.proxies = self._load_proxies()
        self.current_proxy_index = 0

    def _load_user_agents(self) -> List[str]:
        """加载用户代理列表"""
        default_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0'
        ]

        # 从配置中获取自定义用户代理
        custom_agents = self.config.get('user_agents', [])
        return custom_agents + default_agents

    def _load_proxies(self) -> List[Dict[str, str]]:
        """加载代理列表"""
        return self.config.get('proxies', [])

    def get_random_user_agent(self) -> str:
        """获取随机用户代理"""
        return random.choice(self.user_agents)

    def get_next_proxy(self) -> Optional[Dict[str, str]]:
        """获取下一个代理"""
        if not self.proxies:
            return None

        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy

    async def random_delay(self, min_delay: float = None, max_delay: float = None):
        """随机延时"""
        if min_delay is None:
            min_delay = self.config.get('min_delay', 1.0)
        if max_delay is None:
            max_delay = self.config.get('max_delay', 3.0)

        delay = random.uniform(min_delay, max_delay)
        logger.debug(f"随机延时 {delay:.2f} 秒")
        await asyncio.sleep(delay)

    async def setup_page_stealth(self, page: Page):
        """设置页面隐身模式"""
        # 设置随机用户代理
        user_agent = self.get_random_user_agent()
        await page.set_user_agent(user_agent)
        logger.debug(f"设置用户代理: {user_agent[:50]}...")

        # 设置视口大小
        viewport_sizes = [
            {'width': 1920, 'height': 1080},
            {'width': 1366, 'height': 768},
            {'width': 1440, 'height': 900},
            {'width': 1536, 'height': 864},
            {'width': 1280, 'height': 720}
        ]
        viewport = random.choice(viewport_sizes)
        await page.set_viewport_size(**viewport)

        # 添加JavaScript来隐藏自动化特征
        await page.add_init_script("""
            // 删除webdriver属性
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            // 修改plugins长度
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            // 修改languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en'],
            });
            
            // 修改chrome对象
            window.chrome = {
                runtime: {},
            };
            
            // 修改permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)

        # 设置额外的请求头
        await page.set_extra_http_headers({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })

    async def setup_context_stealth(self, context: BrowserContext):
        """设置浏览器上下文隐身模式"""
        # 获取代理配置
        proxy = self.get_next_proxy()
        if proxy:
            logger.info(f"使用代理: {proxy.get('server', 'unknown')}")

    def should_retry(self, error: Exception, attempt: int) -> bool:
        """判断是否应该重试"""
        max_retries = self.config.get('max_retries', 3)
        if attempt >= max_retries:
            return False

        # 检查错误类型
        error_str = str(error).lower()
        retry_errors = [
            'timeout',
            'connection',
            'network',
            'blocked',
            'rate limit',
            '429',
            '503',
            '502',
            '504'
        ]

        return any(retry_error in error_str for retry_error in retry_errors)

    async def handle_rate_limit(self, response_status: int = None):
        """处理速率限制"""
        if response_status in [429, 503]:
            # 被限制时增加延时
            delay = random.uniform(5.0, 15.0)
            logger.warning(f"检测到速率限制，延时 {delay:.2f} 秒")
            await asyncio.sleep(delay)

    async def simulate_human_behavior(self, page: Page):
        """模拟人类行为"""
        # 随机滚动
        if random.random() < 0.3:  # 30%概率滚动
            scroll_distance = random.randint(100, 500)
            await page.evaluate(f"window.scrollBy(0, {scroll_distance})")
            await asyncio.sleep(random.uniform(0.5, 1.5))

        # 随机鼠标移动
        if random.random() < 0.2:  # 20%概率移动鼠标
            x = random.randint(100, 800)
            y = random.randint(100, 600)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.1, 0.5))

    def get_retry_delay(self, attempt: int) -> float:
        """获取重试延时（指数退避）"""
        base_delay = self.config.get('base_retry_delay', 2.0)
        max_delay = self.config.get('max_retry_delay', 30.0)

        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
        return min(delay, max_delay)

    async def check_if_blocked(self, page: Page) -> bool:
        """检查是否被阻止访问"""
        try:
            # 检查常见的阻止页面特征
            title = await page.title()
            content = await page.content()

            blocked_indicators = [
                '403 forbidden',
                '访问被拒绝',
                'access denied',
                '验证码',
                'captcha',
                '人机验证',
                'cloudflare',
                '请稍后再试',
                'rate limit',
                '频率限制'
            ]

            title_lower = title.lower()
            content_lower = content.lower()

            for indicator in blocked_indicators:
                if indicator in title_lower or indicator in content_lower:
                    logger.warning(f"检测到阻止访问指示器: {indicator}")
                    return True

            return False

        except Exception as e:
            logger.error(f"检查阻止状态时出错: {e}")
            return False

    def get_session_config(self) -> Dict[str, Any]:
        """获取会话配置"""
        config = {
            'user_agent': self.get_random_user_agent(),
            'proxy': self.get_next_proxy(),
            'delay_range': (self.config.get('min_delay', 1.0), self.config.get('max_delay', 3.0))
        }
        return config


class RateLimiter:
    """速率限制器"""

    def __init__(self, max_requests: int = 10, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []

    async def acquire(self):
        """获取请求许可"""
        now = time.time()

        # 清理过期的请求记录
        self.requests = [req_time for req_time in self.requests if now - req_time < self.time_window]

        # 检查是否超过限制
        if len(self.requests) >= self.max_requests:
            sleep_time = self.time_window - (now - self.requests[0]) + random.uniform(1, 3)
            logger.info(f"速率限制，等待 {sleep_time:.2f} 秒")
            await asyncio.sleep(sleep_time)
            return await self.acquire()

        # 记录请求时间
        self.requests.append(now)

        # 添加随机延时
        await asyncio.sleep(random.uniform(0.5, 2.0))


def create_anti_crawler_handler(config: Dict[str, Any]) -> AntiCrawlerHandler:
    """创建反爬虫处理器"""
    return AntiCrawlerHandler(config)


def create_rate_limiter(max_requests: int = 10, time_window: int = 60) -> RateLimiter:
    """创建速率限制器"""
    return RateLimiter(max_requests, time_window)
