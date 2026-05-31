"""Top10 流通股东 + 股东户数 provider。"""
from __future__ import annotations

import logging

import pandas as pd

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import holders_repo
from data_store.akshare_adapter import AkshareUnavailable

logger = logging.getLogger(__name__)


class HoldersProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def _fetch_and_save(self, ts_code: str) -> None:
        symbol = ts_code.split(".")[0]
        # top10 流通股东
        try:
            df = self._adapter.fetch("top10_float", symbol=symbol)
            if df is not None and not df.empty:
                col_map = {
                    "截止日期": "end_date", "编号": "holder_rank",
                    "股东名称": "holder_name", "持股数量": "hold_amount",
                    "占流通股比例": "hold_ratio", "股本性质": "change_type",
                }
                df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
                df["ts_code"] = ts_code
                if "end_date" in df.columns:
                    df["end_date"] = pd.to_datetime(df["end_date"]).dt.strftime("%Y-%m-%d")
                # 缺列、或上游 `编号` 列存在但部分行为空（NaN）时，按出现序补号。
                # holder_rank 是 NOT NULL 主键，NaN 直落 upsert 会崩综合分析。
                if "holder_rank" not in df.columns or df["holder_rank"].isna().any():
                    df["holder_rank"] = range(1, len(df) + 1)
                df["holder_rank"] = df["holder_rank"].astype(int)
                for col in ("hold_amount", "hold_ratio"):
                    if col not in df.columns:
                        df[col] = 0.0
                if "change_type" not in df.columns:
                    df["change_type"] = ""
                df["change_amount"] = 0.0
                rows = df[list(holders_repo._TOP10_FIELDS)].to_dict("records")
                holders_repo.upsert_top10(rows)
                logger.info("top10: saved %d rows for %s", len(rows), ts_code)
        except AkshareUnavailable as exc:
            logger.warning("top10 fetch failed for %s: %s", ts_code, exc)

        # 股东户数
        try:
            df = self._adapter.fetch("gdhs", symbol=symbol)
            if df is not None and not df.empty:
                col_map = {
                    "股东户数统计截止日": "end_date",
                    "股东户数-本次": "holder_num",
                    "户均持股数量": "avg_hold",
                    "股东户数-增减比例": "pct_change",
                }
                df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
                df["ts_code"] = ts_code
                if "end_date" in df.columns:
                    df["end_date"] = pd.to_datetime(df["end_date"]).dt.strftime("%Y-%m-%d")
                for col in ("holder_num", "avg_hold", "pct_change"):
                    if col not in df.columns:
                        df[col] = None
                rows = df[list(holders_repo._HN_FIELDS)].to_dict("records")
                holders_repo.upsert_holdernumber(rows)
                logger.info("gdhs: saved %d rows for %s", len(rows), ts_code)
        except AkshareUnavailable as exc:
            logger.warning("gdhs fetch failed for %s: %s", ts_code, exc)

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        top10 = holders_repo.latest_top10(ts_code)
        history = holders_repo.get_holdernumber_history(ts_code)
        if top10.empty and history.empty:
            self._fetch_and_save(ts_code)
            top10 = holders_repo.latest_top10(ts_code)
            history = holders_repo.get_holdernumber_history(ts_code)
        if top10.empty and history.empty:
            return ProviderResult.unavailable(reason="holders: no data for this code")
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
        last_updated = latest_period or (str(history.iloc[0]["end_date"]) if not history.empty else None)
        return ProviderResult(data=data, data_status="stale", last_updated=last_updated)
