#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用反爬虫增强模块
提供智能请求策略、频率控制、错误恢复等功能
"""

import asyncio
import random
import time
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timedelta
from collections import deque
import logging


class RateLimiter:
    """智能频率限制器"""

    def __init__(self, requests_per_minute: int = 10, burst_size: int = 3):
        """
        初始化频率限制器

        Args:
            requests_per_minute: 每分钟最大请求数
            burst_size: 允许的突发请求数量
        """
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.request_times = deque(maxlen=100)
        self.last_request_time = 0
        self.cooldown_until = 0
        self.consecutive_errors = 0
        self.logger = logging.getLogger(__name__)

    async def acquire(self):
        """获取请求许可"""
        current_time = time.time()

        # 检查是否在冷却期
        if current_time < self.cooldown_until:
            wait_time = self.cooldown_until - current_time
            self.logger.info(f"⏸️  冷却中，等待 {wait_time:.1f} 秒")
            await asyncio.sleep(wait_time)
            current_time = time.time()

        # 清理1分钟前的请求记录
        cutoff_time = current_time - 60
        while self.request_times and self.request_times[0] < cutoff_time:
            self.request_times.popleft()

        # 检查是否超过每分钟限制
        if len(self.request_times) >= self.requests_per_minute:
            oldest_request = self.request_times[0]
            wait_time = 60 - (current_time - oldest_request) + random.uniform(1, 3)
            self.logger.info(f"⏳ 达到频率限制，等待 {wait_time:.1f} 秒")
            await asyncio.sleep(wait_time)
            current_time = time.time()

        # 基础延迟：避免请求过快
        min_interval = 60.0 / self.requests_per_minute
        time_since_last = current_time - self.last_request_time

        if time_since_last < min_interval:
            wait_time = min_interval - time_since_last + random.uniform(0.5, 2.0)
            await asyncio.sleep(wait_time)
            current_time = time.time()

        # 记录请求时间
        self.request_times.append(current_time)
        self.last_request_time = current_time

    def report_success(self):
        """报告请求成功"""
        self.consecutive_errors = 0

    def report_error(self, error_type: str = "generic"):
        """报告请求失败，触发自适应冷却"""
        self.consecutive_errors += 1

        # 根据连续错误次数增加冷却时间
        if self.consecutive_errors >= 3:
            cooldown_time = min(60 * (2 ** (self.consecutive_errors - 3)), 300)  # 最多5分钟
            self.cooldown_until = time.time() + cooldown_time
            self.logger.warning(f"🚨 连续 {self.consecutive_errors} 次错误，启动冷却 {cooldown_time:.0f} 秒")

        # ERR_EMPTY_RESPONSE 特殊处理 - 更长的冷却时间
        if error_type == "ERR_EMPTY_RESPONSE":
            cooldown_time = 30 + random.uniform(10, 30)  # 30-60秒
            self.cooldown_until = max(self.cooldown_until, time.time() + cooldown_time)
            self.logger.warning(f"🛑 检测到反爬虫拦截，强制冷却 {cooldown_time:.0f} 秒")


class SmartRetryStrategy:
    """智能重试策略"""

    def __init__(self, max_retries: int = 3, base_delay: float = 2.0, max_delay: float = 60.0):
        """
        初始化重试策略

        Args:
            max_retries: 最大重试次数
            base_delay: 基础延迟时间（秒）
            max_delay: 最大延迟时间（秒）
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.logger = logging.getLogger(__name__)

    def get_retry_delay(self, attempt: int, error_type: Optional[str] = None) -> float:
        """
        计算重试延迟时间（指数退避 + 随机抖动）

        Args:
            attempt: 当前重试次数（从0开始）
            error_type: 错误类型

        Returns:
            延迟时间（秒）
        """
        # 指数退避
        exponential_delay = self.base_delay * (2 ** attempt)

        # 添加随机抖动（±30%）
        jitter = exponential_delay * random.uniform(-0.3, 0.3)
        delay = exponential_delay + jitter

        # 特殊错误类型的额外延迟
        if error_type == "ERR_EMPTY_RESPONSE":
            delay *= 2  # 反爬虫拦截，延迟加倍
        elif error_type == "TIMEOUT":
            delay *= 1.5  # 超时错误，适当增加延迟

        # 限制最大延迟
        delay = min(delay, self.max_delay)

        self.logger.info(f"🔄 重试延迟: {delay:.1f} 秒 (尝试 {attempt + 1}/{self.max_retries + 1})")
        return delay

    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        error_handler: Optional[Callable] = None,
        **kwargs
    ) -> Any:
        """
        执行函数并自动重试

        Args:
            func: 要执行的异步函数
            error_handler: 错误处理函数，返回错误类型字符串
            *args, **kwargs: 传递给func的参数

        Returns:
            函数执行结果
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                return result

            except Exception as e:
                last_error = e

                # 获取错误类型
                error_type = "generic"
                if error_handler:
                    error_type = error_handler(e)

                # 最后一次尝试不再重试
                if attempt >= self.max_retries:
                    self.logger.error(f"❌ 重试次数已用尽: {e}")
                    raise

                # 计算延迟并等待
                delay = self.get_retry_delay(attempt, error_type)
                self.logger.warning(f"⚠️  请求失败 (尝试 {attempt + 1}/{self.max_retries + 1}): {e}")
                await asyncio.sleep(delay)

        # 理论上不会到达这里
        if last_error:
            raise last_error


class RequestOptimizer:
    """请求优化器 - 整合频率限制和智能重试"""

    def __init__(
        self,
        requests_per_minute: int = 8,  # 降低频率到8次/分钟
        max_retries: int = 3,
        base_delay: float = 3.0,  # 增加基础延迟到3秒
        enable_adaptive: bool = True
    ):
        """
        初始化请求优化器

        Args:
            requests_per_minute: 每分钟最大请求数
            max_retries: 最大重试次数
            base_delay: 基础延迟时间
            enable_adaptive: 是否启用自适应调整
        """
        self.rate_limiter = RateLimiter(requests_per_minute=requests_per_minute)
        self.retry_strategy = SmartRetryStrategy(max_retries=max_retries, base_delay=base_delay)
        self.enable_adaptive = enable_adaptive
        self.logger = logging.getLogger(__name__)

        # 统计信息
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_retry_count = 0

    async def execute_request(
        self,
        request_func: Callable,
        *args,
        error_classifier: Optional[Callable] = None,
        **kwargs
    ) -> Any:
        """
        执行请求（带频率限制和智能重试）

        Args:
            request_func: 请求函数
            error_classifier: 错误分类器，用于识别错误类型
            *args, **kwargs: 传递给request_func的参数

        Returns:
            请求结果
        """
        self.total_requests += 1

        # 等待频率限制
        await self.rate_limiter.acquire()

        # 执行请求（带重试）
        try:
            result = await self.retry_strategy.execute_with_retry(
                request_func,
                *args,
                error_handler=error_classifier,
                **kwargs
            )

            # 报告成功
            self.rate_limiter.report_success()
            self.successful_requests += 1

            return result

        except Exception as e:
            # 报告失败
            error_type = error_classifier(e) if error_classifier else "generic"
            self.rate_limiter.report_error(error_type)
            self.failed_requests += 1

            raise

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": (
                self.successful_requests / self.total_requests * 100
                if self.total_requests > 0 else 0
            ),
            "consecutive_errors": self.rate_limiter.consecutive_errors,
            "in_cooldown": time.time() < self.rate_limiter.cooldown_until
        }

    def print_stats(self):
        """打印统计信息"""
        stats = self.get_stats()
        self.logger.info("📊 请求统计:")
        self.logger.info(f"   总请求数: {stats['total_requests']}")
        self.logger.info(f"   成功: {stats['successful_requests']}")
        self.logger.info(f"   失败: {stats['failed_requests']}")
        self.logger.info(f"   成功率: {stats['success_rate']:.1f}%")


def classify_playwright_error(error: Exception) -> str:
    """
    分类Playwright错误类型

    Args:
        error: 异常对象

    Returns:
        错误类型字符串
    """
    error_str = str(error)

    if "ERR_EMPTY_RESPONSE" in error_str:
        return "ERR_EMPTY_RESPONSE"
    elif "TimeoutError" in error_str or "Timeout" in str(type(error)):
        return "TIMEOUT"
    elif "ERR_CONNECTION_REFUSED" in error_str:
        return "CONNECTION_REFUSED"
    elif "ERR_NAME_NOT_RESOLVED" in error_str:
        return "DNS_ERROR"
    elif "429" in error_str:
        return "RATE_LIMIT"
    elif "503" in error_str:
        return "SERVICE_UNAVAILABLE"
    else:
        return "generic"
