"""官方筹码分布 provider（骨架：M1 不调 akshare）。"""
from __future__ import annotations

from analysis.institutional.base import BaseProvider, ProviderResult


class CyqProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        return ProviderResult.unavailable(reason="M1: cyq_em not yet integrated")
