"""龙虎榜机构席位 provider（骨架：仅读 SQLite，未对接 akshare）。"""
from __future__ import annotations

import datetime as _dt

import pandas as pd

from analysis.institutional.base import BaseProvider, ProviderResult
from analysis.institutional.quant_seat_registry import QuantSeatRegistry
from data_store import dragon_tiger_repo


class LhbProvider(BaseProvider):
    def __init__(self, seat_registry: QuantSeatRegistry, akshare_adapter):
        self._registry = seat_registry
        self._adapter = akshare_adapter

    def get(self, ts_code: str, days: int = 90, **kwargs) -> ProviderResult:
        since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
        df = dragon_tiger_repo.get_by_code(ts_code)
        if df.empty:
            return ProviderResult.unavailable(
                reason="M1: dragon_tiger_inst empty for this code"
            )
        # Filter to recent N days
        df = df[df["trade_date"] >= since]
        if df.empty:
            return ProviderResult.unavailable(
                reason="M1: no dragon_tiger_inst records within date range"
            )
        records = df.to_dict("records")
        latest_date = df["trade_date"].max()
        quant_count = int((df["is_quant"] == 1).sum())
        net_inst_buy = float(df["net_amount"].sum())
        highlights = (
            df.sort_values("net_amount", ascending=False)
              .head(5)[["trade_date", "inst_name", "side", "net_amount",
                         "is_quant", "quant_confidence"]]
              .to_dict("records")
        )
        return ProviderResult(
            data={
                "history_90d": records,
                "quant_seat_appearances": quant_count,
                "net_inst_buy_30d": net_inst_buy,
                "highlight_seats": highlights,
            },
            data_status="stale",
            last_updated=latest_date,
        )
