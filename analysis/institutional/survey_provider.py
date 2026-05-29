"""机构调研 provider（骨架）。"""
from __future__ import annotations

import datetime as _dt

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import survey_repo


class SurveyProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, days: int = 90, **kwargs) -> ProviderResult:
        since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
        df = survey_repo.get_by_code(ts_code, since=since)
        if df.empty:
            return ProviderResult.unavailable(reason="M1: jgdy_detail empty")
        return ProviderResult(
            data={"recent_90d": df.to_dict("records")},
            data_status="stale",
            last_updated=str(df["survey_date"].max()),
        )
