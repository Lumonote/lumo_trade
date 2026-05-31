"""龙虎榜机构席位 provider。"""
from __future__ import annotations

import datetime as _dt
import logging

import pandas as pd

from analysis.institutional.base import BaseProvider, ProviderResult, humanize_unavailable
from analysis.institutional.quant_seat_registry import QuantSeatRegistry
from data_store import dragon_tiger_repo
from data_store.akshare_adapter import AkshareUnavailable

logger = logging.getLogger(__name__)

_QUANT_KEYWORDS = ("量化", "DMA", "程序化", "算法")


def _classify_quant(name: str) -> tuple[int, float]:
    is_q = int(any(k in (name or "") for k in _QUANT_KEYWORDS))
    return is_q, 0.6 if is_q else 0.0


class LhbProvider(BaseProvider):
    def __init__(self, seat_registry: QuantSeatRegistry, akshare_adapter):
        self._registry = seat_registry
        self._adapter = akshare_adapter
        self._last_error: str | None = None

    def _fetch_and_save(self, ts_code: str) -> None:
        self._last_error = None
        symbol = ts_code.split(".")[0]
        end = _dt.date.today().strftime("%Y%m%d")
        start = (_dt.date.today() - _dt.timedelta(days=365)).strftime("%Y%m%d")
        try:
            df = self._adapter.fetch("lhb_jgmm", start_date=start, end_date=end)
        except AkshareUnavailable as exc:
            self._last_error = str(exc)
            logger.warning("lhb fetch failed for %s: %s", ts_code, exc)
            return
        if df is None or df.empty:
            return
        # 机构买卖统计返回全市场，按代码过滤
        if "代码" in df.columns:
            df = df[df["代码"].astype(str).str.zfill(6) == symbol]
        if df.empty:
            return
        rows = []
        for _, r in df.iterrows():
            raw_date = r.get("上榜日期")
            trade_date = pd.to_datetime(raw_date).strftime("%Y-%m-%d") if raw_date is not None else ""
            buy_total = float(r.get("机构买入总额") or 0.0)
            sell_total = float(r.get("机构卖出总额") or 0.0)
            net = float(r.get("机构买入净额") or (buy_total - sell_total))
            buyers = int(r.get("买方机构数") or 0)
            sellers = int(r.get("卖方机构数") or 0)
            # 机构买入席位聚合行
            rows.append({
                "ts_code": ts_code, "trade_date": trade_date,
                "inst_name": f"机构买入({buyers}家)", "side": "buy",
                "net_amount": net, "buy_amount": buy_total, "sell_amount": 0.0,
                "is_quant": 0, "quant_confidence": 0.0,
                "reason": str(r.get("上榜原因") or ""),
            })
            # 机构卖出席位聚合行
            rows.append({
                "ts_code": ts_code, "trade_date": trade_date,
                "inst_name": f"机构卖出({sellers}家)", "side": "sell",
                "net_amount": -sell_total, "buy_amount": 0.0, "sell_amount": sell_total,
                "is_quant": 0, "quant_confidence": 0.0,
                "reason": str(r.get("上榜原因") or ""),
            })
        if rows:
            dragon_tiger_repo.upsert_rows(rows)
            logger.info("lhb: saved %d rows for %s", len(rows), ts_code)

    def get(self, ts_code: str, days: int = 90, **kwargs) -> ProviderResult:
        since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
        df = dragon_tiger_repo.get_by_code(ts_code)
        if df.empty:
            self._fetch_and_save(ts_code)
            df = dragon_tiger_repo.get_by_code(ts_code)
        if df.empty:
            return ProviderResult.unavailable(
                reason=humanize_unavailable("龙虎榜机构席位", self._last_error)
            )
        # Filter to recent N days
        df = df[df["trade_date"] >= since]
        if df.empty:
            return ProviderResult.unavailable(
                reason=f"龙虎榜机构席位：近 {days} 日无机构上榜记录"
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
