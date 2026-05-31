"""机构调研 provider。

stock_jgdy_detail_em 按交易日返回全市场，无单股直拉路径 —— 本 provider 只读库，
数据由 E2 市场级回填脚本（scripts/sync_institutional_data.py --tables jgdy）填充。
"""
from __future__ import annotations

import datetime as _dt
import logging

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import survey_repo

logger = logging.getLogger(__name__)

_NO_DATA_REASON = (
    "机构调研：暂无数据（按交易日全市场返回，无单股直拉；"
    "请运行 scripts/sync_institutional_data.py --tables jgdy 回填）"
)


class SurveyProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def get(self, ts_code: str, days: int = 90, **kwargs) -> ProviderResult:
        since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
        df = survey_repo.get_by_code(ts_code, since=since)
        if df.empty:
            return ProviderResult.unavailable(reason=_NO_DATA_REASON)
        return ProviderResult(
            data={"recent_90d": df.to_dict("records")},
            data_status="stale",
            last_updated=str(df["survey_date"].max()),
        )
