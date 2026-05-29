"""Top10 流通股东 + 股东户数 provider（骨架）。"""
from __future__ import annotations

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import holders_repo


class HoldersProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        top10 = holders_repo.latest_top10(ts_code)
        history = holders_repo.get_holdernumber_history(ts_code)
        if top10.empty and history.empty:
            return ProviderResult.unavailable(
                reason="M1: top10_floatholders / stk_holdernumber empty"
            )
        latest_period = str(top10.iloc[0]["end_date"]) if not top10.empty else None
        data = {
            "top10_floatholders": {
                "period": latest_period,
                "rows": top10.to_dict("records") if not top10.empty else [],
                "concentration": float(top10["hold_ratio"].sum()) if not top10.empty else 0.0,
            },
            "holder_number": {
                "latest_num": int(history.iloc[0]["holder_num"]) if not history.empty else None,
                "pct_change_qoq": float(history.iloc[0]["pct_change"]) if (not history.empty and history.iloc[0]["pct_change"] is not None) else None,
                "history": history.to_dict("records") if not history.empty else [],
            },
        }
        last_updated = latest_period or (
            str(history.iloc[0]["end_date"]) if not history.empty else None
        )
        return ProviderResult(data=data, data_status="stale", last_updated=last_updated)
