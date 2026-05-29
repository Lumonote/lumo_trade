"""陆股通个股持股 provider（骨架）。"""
from __future__ import annotations

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import hsgt_repo


class HsgtProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        df = hsgt_repo.get_by_code(ts_code)
        if df.empty:
            return ProviderResult.unavailable(
                reason="M1: hsgt_individual empty for this code"
            )
        df = df.sort_values("trade_date")
        latest = df.iloc[-1]
        trend = df.tail(30)[["trade_date", "hold_ratio"]].to_dict("records")
        baseline_idx = max(0, len(df) - 30)
        delta = float(latest["hold_ratio"] - df.iloc[baseline_idx]["hold_ratio"])
        return ProviderResult(
            data={
                "latest": {
                    "hold_vol": float(latest["hold_vol"]),
                    "hold_ratio": float(latest["hold_ratio"]),
                    "trade_date": str(latest["trade_date"]),
                },
                "trend_30d": trend,
                "delta_30d_pct": delta,
            },
            data_status="stale",
            last_updated=str(latest["trade_date"]),
        )
