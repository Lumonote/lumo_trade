"""重仓基金 provider。"""
from __future__ import annotations

import logging

from analysis.institutional.base import BaseProvider, ProviderResult, humanize_unavailable
from data_store import fund_hold_repo
from data_store.akshare_adapter import AkshareUnavailable

logger = logging.getLogger(__name__)

# 单股可能被上千只基金持有（茅台 ~997 只），仅留最新报告期、按持股市值取前 N，
# 避免灌爆 fund_hold_detail；前 N 已覆盖绝大部分集中持仓。
_MAX_FUNDS = 50


class FundHoldingsProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter
        self._last_error: str | None = None

    def _fetch_and_save(self, ts_code: str) -> None:
        """单股真实抓取：ak.stock_fund_stock_holder(symbol=code) 返回持有该股的基金列表。

        列：基金名称/基金代码/持仓数量/占流通股比例/持股市值/占净值比例/截止日期。
        """
        self._last_error = None
        symbol = ts_code.split(".")[0]
        try:
            df = self._adapter.fetch("fund_stock_holder", symbol=symbol)
        except AkshareUnavailable as exc:
            self._last_error = str(exc)
            logger.warning("fund_hold fetch failed for %s: %s", ts_code, exc)
            return
        if df is None or df.empty:
            return
        col_map = {
            "基金代码": "fund_code", "基金名称": "fund_name",
            "持仓数量": "hold_shares", "持股市值": "market_value",
            "占净值比例": "nv_ratio", "截止日期": "end_date",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        if "end_date" in df.columns:
            df["end_date"] = df["end_date"].astype(str)
            latest = df["end_date"].max()           # 只保留最新报告期
            df = df[df["end_date"] == latest]
        if "market_value" in df.columns:
            df = df.sort_values("market_value", ascending=False).head(_MAX_FUNDS)
        df = df.copy()
        df["ts_code"] = ts_code
        for col in ("end_date", "fund_code", "fund_name", "hold_shares", "market_value", "nv_ratio"):
            if col not in df.columns:
                df[col] = None
        rows = df[list(fund_hold_repo._FIELDS)].to_dict("records")
        if rows:
            fund_hold_repo.upsert_rows(rows)
            logger.info("fund_hold: saved %d rows for %s", len(rows), ts_code)

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        period = fund_hold_repo.latest_period(ts_code)
        if period is None:
            self._fetch_and_save(ts_code)
            period = fund_hold_repo.latest_period(ts_code)
        if period is None:
            return ProviderResult.unavailable(
                reason=humanize_unavailable("重仓基金", self._last_error)
            )
        df = fund_hold_repo.get_by_code(ts_code, period)
        total_nv = float(df["nv_ratio"].fillna(0).sum()) if not df.empty else 0.0
        return ProviderResult(
            data={
                "period": period,
                "rows": df.to_dict("records"),
                "total_nv_pct": total_nv,
            },
            data_status="stale",
            last_updated=period,
        )
