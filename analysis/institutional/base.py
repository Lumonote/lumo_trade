"""Provider 抽象 + 统一 DTO。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, Literal, Optional, TypeVar

T = TypeVar("T")

DataStatus = Literal["fresh", "stale", "unavailable"]


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
