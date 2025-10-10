#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器管理模块
用于统一管理Playwright浏览器实例，提供浏览器池和资源清理功能
"""

import asyncio
import json
import logging
import random
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional, Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# 尝试导入fake_useragent，如果失败则使用内置User-Agent列表
try:
    from fake_useragent import UserAgent

    FAKE_USERAGENT_AVAILABLE = True
except (ImportError, TypeError) as e:
    FAKE_USERAGENT_AVAILABLE = False
    print(f"⚠️ fake_useragent 不可用: {e}，将使用内置 User-Agent 列表")


class BrowserManager:
    """浏览器管理器"""

    def __init__(self, config_path: str = None):
        self.config_path = config_path or "config/crawler_config.json"
        self.config = self._load_config()
        self.playwright = None
        self.browser = None
        self.contexts: List[BrowserContext] = []
        self.pages: List[Page] = []

        # 初始化UserAgent，如果fake_useragent不可用则使用备用方案
        if FAKE_USERAGENT_AVAILABLE:
            try:
                self.ua = UserAgent()
            except Exception as e:
                print(f"⚠️ UserAgent初始化失败: {e}，使用备用方案")
                self.ua = None
        else:
            self.ua = None

        self.logger = self._setup_logger()

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "playwright_settings": {
                "browser_type": "chromium",
                "headless": True,
                "viewport": {"width": 1920, "height": 1080},
                "args": ["--no-sandbox", "--disable-setuid-sandbox"]
            },
            "anti_crawler_settings": {
                "random_delay": {"enabled": True, "min_delay": 1, "max_delay": 3},
                "user_agent_rotation": {"enabled": True}
            }
        }

    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger("BrowserManager")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    async def start(self) -> None:
        """启动浏览器管理器"""
        try:
            self.playwright = await async_playwright().start()

            # 获取浏览器类型
            browser_type = self.config.get("playwright_settings", {}).get("browser_type", "chromium")
            browser_launcher = getattr(self.playwright, browser_type)

            # 启动浏览器
            launch_options = self._get_launch_options()
            self.browser = await browser_launcher.launch(**launch_options)

            self.logger.info(f"浏览器管理器启动成功，使用 {browser_type} 浏览器")

        except Exception as e:
            self.logger.error(f"启动浏览器管理器失败: {e}")
            raise

    def _get_launch_options(self) -> Dict[str, Any]:
        """获取浏览器启动选项"""
        playwright_settings = self.config.get("playwright_settings", {})

        options = {
            "headless": playwright_settings.get("headless", True),
            "args": playwright_settings.get("args", []),
        }

        # 添加用户数据目录（如果指定）
        user_data_dir = playwright_settings.get("user_data_dir")
        if user_data_dir:
            options["user_data_dir"] = user_data_dir

        return options

    async def create_context(self, **kwargs) -> BrowserContext:
        """创建浏览器上下文"""
        if not self.browser:
            await self.start()

        # 获取上下文选项
        context_options = self._get_context_options(**kwargs)

        # 创建上下文
        context = await self.browser.new_context(**context_options)
        self.contexts.append(context)

        # 应用反爬虫设置
        await self._apply_stealth_settings(context)

        self.logger.info(f"创建新的浏览器上下文，当前上下文数量: {len(self.contexts)}")
        return context

    def _get_context_options(self, **kwargs) -> Dict[str, Any]:
        """获取上下文选项"""
        playwright_settings = self.config.get("playwright_settings", {})
        anti_crawler_settings = self.config.get("anti_crawler_settings", {})

        options = {
            "viewport": playwright_settings.get("viewport", {"width": 1920, "height": 1080}),
            "ignore_https_errors": playwright_settings.get("ignore_https_errors", True),
            "java_script_enabled": playwright_settings.get("java_script_enabled", True),
            "accept_downloads": playwright_settings.get("accept_downloads", False),
            "bypass_csp": playwright_settings.get("bypass_csp", True),
        }

        # 设置用户代理
        if anti_crawler_settings.get("user_agent_rotation", {}).get("enabled", False):
            user_agents = anti_crawler_settings["user_agent_rotation"].get("pool", [])
            if user_agents:
                options["user_agent"] = random.choice(user_agents)
            else:
                # 使用UserAgent或备用方案
                options["user_agent"] = self._get_random_user_agent()

        # 设置额外的HTTP头
        extra_headers = playwright_settings.get("extra_http_headers", {})
        if extra_headers:
            options["extra_http_headers"] = extra_headers

        # 合并用户提供的选项
        options.update(kwargs)

        return options

    def _get_random_user_agent(self):
        """获取随机User-Agent，支持备用方案"""
        if self.ua:
            try:
                return self.ua.random
            except Exception as e:
                print(f"⚠️ UserAgent获取失败: {e}，使用备用方案")

        # 备用User-Agent列表
        fallback_user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
        ]
        return random.choice(fallback_user_agents)

    async def _apply_stealth_settings(self, context: BrowserContext) -> None:
        """应用隐身设置"""
        anti_crawler_settings = self.config.get("anti_crawler_settings", {})

        # 注入隐身脚本
        if anti_crawler_settings.get("stealth_mode", {}).get("enabled", False):
            stealth_script = """
            // 隐藏webdriver属性
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            // 修改plugins
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
            """

            await context.add_init_script(stealth_script)

    async def create_page(self, context: BrowserContext = None) -> Page:
        """创建页面"""
        if not context:
            context = await self.create_context()

        page = await context.new_page()
        self.pages.append(page)

        # 设置页面事件监听
        await self._setup_page_events(page)

        self.logger.info(f"创建新页面，当前页面数量: {len(self.pages)}")
        return page

    async def _setup_page_events(self, page: Page) -> None:
        """设置页面事件监听"""
        # 监听请求
        page.on("request", lambda request: self.logger.debug(f"请求: {request.url}"))

        # 监听响应
        page.on("response", lambda response: self.logger.debug(f"响应: {response.url} - {response.status}"))

        # 监听控制台消息
        page.on("console", lambda msg: self.logger.debug(f"控制台: {msg.text}"))

    async def random_delay(self) -> None:
        """随机延时"""
        anti_crawler_settings = self.config.get("anti_crawler_settings", {})
        random_delay_config = anti_crawler_settings.get("random_delay", {})

        if random_delay_config.get("enabled", False):
            min_delay = random_delay_config.get("min_delay", 1)
            max_delay = random_delay_config.get("max_delay", 3)
            delay = random.uniform(min_delay, max_delay)

            self.logger.debug(f"随机延时: {delay:.2f}秒")
            await asyncio.sleep(delay)

    async def simulate_human_behavior(self, page: Page) -> None:
        """模拟人类行为"""
        anti_crawler_settings = self.config.get("anti_crawler_settings", {})

        # 模拟鼠标移动
        if anti_crawler_settings.get("mouse_simulation", {}).get("enabled", False):
            await self._simulate_mouse_movement(page)

        # 模拟滚动
        if anti_crawler_settings.get("scroll_simulation", {}).get("enabled", False):
            await self._simulate_scroll(page)

    async def _simulate_mouse_movement(self, page: Page) -> None:
        """模拟鼠标移动"""
        try:
            # 随机移动鼠标
            x = random.randint(100, 800)
            y = random.randint(100, 600)
            await page.mouse.move(x, y)

            # 随机点击延时
            click_delay = self.config.get("anti_crawler_settings", {}).get(
                "mouse_simulation", {}
            ).get("click_delay", [100, 300])

            delay = random.randint(click_delay[0], click_delay[1]) / 1000
            await asyncio.sleep(delay)

        except Exception as e:
            self.logger.debug(f"模拟鼠标移动失败: {e}")

    async def _simulate_scroll(self, page: Page) -> None:
        """模拟滚动"""
        try:
            # 随机滚动
            scroll_distance = random.randint(100, 500)
            await page.evaluate(f"window.scrollBy(0, {scroll_distance})")

            # 滚动延时
            scroll_delay = self.config.get("anti_crawler_settings", {}).get(
                "scroll_simulation", {}
            ).get("scroll_delay", [500, 1500])

            delay = random.randint(scroll_delay[0], scroll_delay[1]) / 1000
            await asyncio.sleep(delay)

        except Exception as e:
            self.logger.debug(f"模拟滚动失败: {e}")

    async def close_page(self, page: Page) -> None:
        """关闭页面"""
        try:
            if page in self.pages:
                self.pages.remove(page)
            await page.close()
            self.logger.info(f"页面已关闭，剩余页面数量: {len(self.pages)}")
        except Exception as e:
            self.logger.error(f"关闭页面失败: {e}")

    async def close_context(self, context: BrowserContext) -> None:
        """关闭上下文"""
        try:
            if context in self.contexts:
                self.contexts.remove(context)
            await context.close()
            self.logger.info(f"上下文已关闭，剩余上下文数量: {len(self.contexts)}")
        except Exception as e:
            self.logger.error(f"关闭上下文失败: {e}")

    async def cleanup(self) -> None:
        """清理资源"""
        try:
            # 关闭所有页面
            for page in self.pages.copy():
                await self.close_page(page)

            # 关闭所有上下文
            for context in self.contexts.copy():
                await self.close_context(context)

            # 关闭浏览器
            if self.browser:
                await self.browser.close()
                self.browser = None

            # 停止playwright
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None

            self.logger.info("浏览器管理器资源清理完成")

        except Exception as e:
            self.logger.error(f"清理资源失败: {e}")

    async def close(self) -> None:
        """关闭浏览器管理器（cleanup的别名）"""
        await self.cleanup()

    @asynccontextmanager
    async def get_page(self, **context_kwargs):
        """获取页面的上下文管理器"""
        context = None
        page = None

        try:
            context = await self.create_context(**context_kwargs)
            page = await self.create_page(context)
            yield page
        finally:
            if page:
                await self.close_page(page)
            if context:
                await self.close_context(context)

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.cleanup()


# 全局浏览器管理器实例
_browser_manager = None


async def get_browser_manager(config_path: str = None) -> BrowserManager:
    """获取全局浏览器管理器实例"""
    global _browser_manager

    if _browser_manager is None:
        _browser_manager = BrowserManager(config_path)
        await _browser_manager.start()

    return _browser_manager


async def cleanup_browser_manager() -> None:
    """清理全局浏览器管理器"""
    global _browser_manager

    if _browser_manager:
        await _browser_manager.cleanup()
        _browser_manager = None


if __name__ == "__main__":
    async def test_browser_manager():
        """测试浏览器管理器"""
        async with BrowserManager() as manager:
            async with manager.get_page() as page:
                await page.goto("https://www.baidu.com")
                title = await page.title()
                print(f"页面标题: {title}")

                # 模拟人类行为
                await manager.simulate_human_behavior(page)
                await manager.random_delay()


    asyncio.run(test_browser_manager())
