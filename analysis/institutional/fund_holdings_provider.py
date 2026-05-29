"""重仓基金 provider（骨架）。"""
from __future__ import annotations

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import fund_hold_repo


class FundHoldingsProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        period = fund_hold_repo.latest_period(ts_code)
        if period is None:
            return ProviderResult.unavailable(reason="M1: fund_hold_detail empty")
        df = fund_hold_repo.get_by_code(ts_code, period)
        total_nv = float(df["nv_ratio"].sum()) if not df.empty else 0.0
        return ProviderResult(
            data={
                "period": period,
                "rows": df.to_dict("records"),
                "total_nv_pct": total_nv,
            },
            data_status="stale",
            last_updated=period,
        )
