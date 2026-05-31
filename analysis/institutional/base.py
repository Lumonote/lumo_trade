"""Provider 抽象 + 统一 DTO。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, Literal, Optional, TypeVar

T = TypeVar("T")

DataStatus = Literal["fresh", "stale", "unavailable"]


def humanize_unavailable(label: str, raw: Optional[str]) -> str:
    """把 adapter 的（多为英文）异常串翻成给用户看的中文「不可用原因」。

    E3：provider 不再把 AkshareUnavailable（熔断/限流/网络/空结果）统一压成
    「no data for this code」，而是带出具体条件，供前端 suiteUnavailableBanner 透出。
    raw 为空表示「取数成功但该股确实无此类记录」。
    """
    raw = (raw or "").strip()
    if not raw:
        return f"{label}：暂无数据（该股可能无此类记录，或尚未回填）"
    low = raw.lower()
    if "circuit breaker" in low or "熔断" in raw:
        return f"{label}：数据源熔断中（近期连续失败，约 5 分钟后自动恢复重试）"
    if "not installed" in low:
        return f"{label}：akshare 未安装，无法在线取数"
    if "returned empty" in low or "empty" in low:
        return f"{label}：数据源返回空（该股可能暂无此类数据）"
    if "timeout" in low or "timed out" in low:
        return f"{label}：数据源请求超时（网络或反爬限流）"
    if "proxy" in low:
        return f"{label}：网络代理异常，数据源暂不可达"
    return f"{label}：数据源暂不可用（{raw[:80]}）"


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    """所有 provider 的统一返回。

    data 为 None 时 data_status 必为 'unavailable'。
    """
    data: Optional[T]
    data_status: DataStatus
    last_updated: Optional[str] = None  # ISO8601
    reason: Optional[str] = None        # unavailable 时的失败原因

    @classmethod
    def unavailable(cls, reason: str = "not implemented") -> "ProviderResult[T]":
        return cls(data=None, data_status="unavailable", last_updated=None, reason=reason)


class BaseProvider(ABC):
    """所有 institutional provider 的抽象基类。"""

    @abstractmethod
    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        ...
