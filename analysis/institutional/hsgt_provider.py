"""陆股通个股持股 provider。"""
from __future__ import annotations

import logging

import pandas as pd

from analysis.institutional.base import BaseProvider, ProviderResult, humanize_unavailable
from data_store import hsgt_repo
from data_store.akshare_adapter import AkshareUnavailable

logger = logging.getLogger(__name__)


class HsgtProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter
        self._last_error: str | None = None

    def _fetch_and_save(self, ts_code: str) -> None:
        self._last_error = None
        symbol = ts_code.split(".")[0]
        try:
            df = self._adapter.fetch("hsgt_hold", symbol=symbol)
        except AkshareUnavailable as exc:
            self._last_error = str(exc)
            logger.warning("hsgt fetch failed for %s: %s", ts_code, exc)
            return
        if df is None or df.empty:
            return
        col_map = {
            "持股日期": "trade_date",
            "持股数量": "hold_vol",
            "持股数量占A股百分比": "hold_ratio",
            "持股市值": "market_cap",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["ts_code"] = ts_code
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        for col in ("hold_vol", "hold_ratio", "market_cap"):
            if col not in df.columns:
                df[col] = 0.0
        rows = df[list(hsgt_repo._FIELDS)].to_dict("records")
        hsgt_repo.upsert_rows(rows)
        logger.info("hsgt: saved %d rows for %s", len(rows), ts_code)

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        df = hsgt_repo.get_by_code(ts_code)
        if df.empty:
            self._fetch_and_save(ts_code)
            df = hsgt_repo.get_by_code(ts_code)
        if df.empty:
            return ProviderResult.unavailable(
                reason=humanize_unavailable("北向持股", self._last_error)
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
