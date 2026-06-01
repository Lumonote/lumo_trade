# data_store/akshare_adapter.py
"""统一 akshare 取数适配器（fallback / 限流 / 熔断）。

provider 层不直接 import akshare —— 通过 AkshareAdapter.fetch(key, *args, **kwargs)。
失败时按 FALLBACK_CHAINS[key] 依次试，全失败抛 AkshareUnavailable，并对该 key
开启 5 分钟熔断窗口。
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

logger = logging.getLogger(__name__)


class AkshareUnavailable(RuntimeError):
    """所有 fallback 源均失败 / 熔断窗口内。"""


@dataclass
class _BreakerState:
    opened_at: float = 0.0


# 瞬时网络/代理错误标记：这类失败下一秒可能就恢复（如系统代理 Clash 抖动），
# 不应像真正的接口/数据错误那样一次失败就黑掉数据源 5 分钟。
_TRANSIENT_MARKERS = (
    "proxy", "connection", "timeout", "timed out", "remotedisconnected",
    "max retries", "connection reset", "broken pipe", "temporarily",
    "ssl", "newconnectionerror", "connectionreset",
)


def _is_transient(exc: BaseException | None) -> bool:
    """是否为可立即重试的瞬时网络/代理错误（区别于真正的数据/接口错误）。"""
    if exc is None:
        return False
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def _now() -> float:
    return time.time()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _default_client_factory():
    import akshare as ak
    return ak


class AkshareAdapter:
    """单一 akshare 取数入口。"""

    FALLBACK_CHAINS: dict[str, list[str]] = {
        "lhb_detail":   ["stock_lhb_detail_em", "stock_lhb_detail_daily_sina"],
        "lhb_jgmm":    ["stock_lhb_jgmmtj_em"],
        "hsgt_hold":    ["stock_hsgt_individual_em", "stock_hsgt_hold_stock_em"],
        "top10_float":  ["stock_circulate_stock_holder", "stock_main_stock_holder"],
        "gdhs":         ["stock_zh_a_gdhs_detail_em", "stock_zh_a_gdhs"],
        "jgdy":         ["stock_jgdy_detail_em"],
        "fund_hold":    ["stock_report_fund_hold_detail"],
        "fund_stock_holder": ["stock_fund_stock_holder"],
        "cyq":          ["stock_cyq_em"],
        "minute":       ["stock_zh_a_minute", "stock_zh_a_hist_min_em"],
    }

    def __init__(
        self,
        client_factory: Callable[[], object] | None = None,
        rate_limit_per_min: int = 30,
        breaker_cooldown_sec: int = 300,
        retry_per_source: int = 2,
        transient_breaker_threshold: int = 3,
    ):
        self._client_factory = client_factory or _default_client_factory
        self._client = None
        self._rate_limit = rate_limit_per_min
        self._call_times: deque[float] = deque(maxlen=rate_limit_per_min)
        self._cooldown = breaker_cooldown_sec
        self._breakers: dict[str, _BreakerState] = {}
        self._retries = retry_per_source
        # 瞬时失败需连续累计到该阈值才熔断（单次代理抖动不黑数据源）
        self._transient_threshold = max(1, transient_breaker_threshold)
        self._transient_fails: dict[str, int] = {}

    def fetch(self, key: str, *args, **kwargs) -> pd.DataFrame:
        """按 key 查找 fallback chain 并依次尝试取数。"""
        if key not in self.FALLBACK_CHAINS:
            raise KeyError(f"AkshareAdapter: unknown key '{key}'")

        if self._is_breaker_open(key):
            raise AkshareUnavailable(f"circuit breaker open for {key}")

        self._throttle()

        if self._client is None:
            try:
                self._client = self._client_factory()
            except ImportError as exc:
                self._open_breaker(key)
                raise AkshareUnavailable(
                    f"akshare not installed: {exc}"
                ) from exc

        last_err: Exception | None = None
        for fn_name in self.FALLBACK_CHAINS[key]:
            for attempt in range(self._retries):
                try:
                    fn = getattr(self._client, fn_name)
                    df = fn(*args, **kwargs)
                    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                        last_err = RuntimeError(f"{fn_name} returned empty")
                        continue
                    self._transient_fails[key] = 0  # 成功 -> 清零瞬时失败计数
                    return df
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    logger.warning(
                        "akshare %s attempt %d failed: %s",
                        fn_name, attempt + 1, exc,
                    )
                    if attempt < self._retries - 1:
                        _sleep(2 ** attempt)

        # 瞬时网络/代理错误：连续累计到阈值才熔断；真正的接口/数据错误立即熔断。
        if _is_transient(last_err):
            self._transient_fails[key] = self._transient_fails.get(key, 0) + 1
            if self._transient_fails[key] >= self._transient_threshold:
                self._open_breaker(key)
        else:
            self._open_breaker(key)
        raise AkshareUnavailable(
            f"all sources failed for {key}: {last_err}"
        ) from last_err

    def _throttle(self) -> None:
        """滑动窗口限流：每分钟最多 rate_limit_per_min 次调用。"""
        now = _now()
        while self._call_times and now - self._call_times[0] > 60:
            self._call_times.popleft()
        if len(self._call_times) >= self._rate_limit:
            wait = 60 - (now - self._call_times[0]) + 0.01
            if wait > 0:
                logger.info("AkshareAdapter throttle sleep %.2fs", wait)
                _sleep(wait)
        self._call_times.append(_now())

    def _is_breaker_open(self, key: str) -> bool:
        """检查 key 的熔断器是否处于打开状态。"""
        state = self._breakers.get(key)
        if not state:
            return False
        if _now() - state.opened_at < self._cooldown:
            return True
        del self._breakers[key]
        return False

    def _open_breaker(self, key: str) -> None:
        """打开 key 的熔断器。"""
        self._breakers[key] = _BreakerState(opened_at=_now())
        self._transient_fails[key] = 0  # 熔断后清零，冷却结束重新计数
        logger.warning("AkshareAdapter breaker opened for %s", key)
