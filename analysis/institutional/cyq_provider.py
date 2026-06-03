"""官方筹码分布 provider（akshare stock_cyq_em）。

读/写 sentiment_cache（cache_type=cyq_em, identifier=ts_code, TTL 30min）。
产出 90/70 成本集中度与成本区间、获利比例，喂 chip_control。
"""
from __future__ import annotations

import logging
import time

from analysis.institutional.base import BaseProvider, ProviderResult, humanize_unavailable
from data_store import sentiment_repo, tushare_client
from data_store.akshare_adapter import AkshareUnavailable

logger = logging.getLogger(__name__)

_CACHE_TYPE = "cyq_em"
_TTL_SECONDS = 30 * 60


def _f(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None  # NaN -> None
    except (TypeError, ValueError):
        return None


def _pct(v) -> float | None:
    """获利比例/集中度在 akshare cyq_em 中为 0–1 小数；统一转成百分数。"""
    f = _f(v)
    if f is None:
        return None
    return round(f * 100, 2) if abs(f) <= 1.5 else round(f, 2)


class CyqProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter
        self._last_error: str | None = None

    def _cache_get(self, ts_code: str):
        # sentiment_cache 仅作加速，读失败不应拖垮在线取数。
        try:
            return sentiment_repo.get(_CACHE_TYPE, ts_code)
        except Exception:  # noqa: BLE001
            return None

    def _cache_set(self, ts_code: str, data: dict) -> None:
        try:
            sentiment_repo.set_(_CACHE_TYPE, data, ts_code)
        except Exception:  # noqa: BLE001
            pass

    def _summarize(self, df) -> dict | None:
        """把 stock_cyq_em 表归一化成精简快照 + 近 30 日趋势。"""
        if df is None or getattr(df, "empty", True):
            return None
        date_col = "日期" if "日期" in df.columns else df.columns[0]
        latest = df.iloc[-1]
        data = {
            "as_of": str(latest.get(date_col)),
            "profit_ratio_pct": _pct(latest.get("获利比例")),
            "avg_cost": _f(latest.get("平均成本")),
            "concentration_90_pct": _pct(latest.get("90集中度")),
            "concentration_70_pct": _pct(latest.get("70集中度")),
            "cost_90_low": _f(latest.get("90成本-低")),
            "cost_90_high": _f(latest.get("90成本-高")),
            "cost_70_low": _f(latest.get("70成本-低")),
            "cost_70_high": _f(latest.get("70成本-高")),
        }
        trend = []
        for _, r in df.tail(30).iterrows():
            trend.append({
                "date": str(r.get(date_col)),
                "profit_ratio_pct": _pct(r.get("获利比例")),
                "concentration_90_pct": _pct(r.get("90集中度")),
            })
        data["trend_30d"] = trend
        return data

    def _summarize_tushare(self, df) -> dict | None:
        """把 Tushare cyq_perf 归一化成与 akshare 一致的快照 + 近 30 日趋势。

        cyq_perf 给的是成本分位（cost_5/15/50/85/95pct，单位元）与 winner_rate(0–100)，
        没有现成「集中度」字段——按通用筹码集中度公式 (高位-低位)/(高位+低位) 估算
        （值越小越集中）。winner_rate 即获利比例。
        """
        if df is None or getattr(df, "empty", True):
            return None
        df = df.sort_values("trade_date").reset_index(drop=True)

        def _conc(low, high):
            lo, hi = _f(low), _f(high)
            if lo is None or hi is None or (lo + hi) == 0:
                return None
            return round(abs(hi - lo) / (hi + lo) * 100, 2)

        latest = df.iloc[-1]
        data = {
            "as_of": tushare_client.yyyymmdd_to_iso(latest.get("trade_date")),
            "profit_ratio_pct": _f(latest.get("winner_rate")),
            "avg_cost": _f(latest.get("weight_avg")),
            "concentration_90_pct": _conc(latest.get("cost_5pct"), latest.get("cost_95pct")),
            "concentration_70_pct": _conc(latest.get("cost_15pct"), latest.get("cost_85pct")),
            "cost_90_low": _f(latest.get("cost_5pct")),
            "cost_90_high": _f(latest.get("cost_95pct")),
            "cost_70_low": _f(latest.get("cost_15pct")),
            "cost_70_high": _f(latest.get("cost_85pct")),
        }
        trend = []
        for r in df.tail(30).itertuples(index=False):
            trend.append({
                "date": tushare_client.yyyymmdd_to_iso(getattr(r, "trade_date", "")),
                "profit_ratio_pct": _f(getattr(r, "winner_rate", None)),
                "concentration_90_pct": _conc(getattr(r, "cost_5pct", None), getattr(r, "cost_95pct", None)),
            })
        data["trend_30d"] = trend
        return data

    def _fetch_tushare(self, ts_code: str) -> dict | None:
        pro = tushare_client.get_pro()
        if pro is None:
            return None
        try:
            df = pro.cyq_perf(ts_code=tushare_client.to_ts_code(ts_code), limit=60)
        except Exception as exc:  # noqa: BLE001
            if self._last_error is None:
                self._last_error = f"tushare cyq_perf: {exc}"
            logger.warning("tushare cyq fetch failed for %s: %s", ts_code, exc)
            return None
        return self._summarize_tushare(df)

    def get(self, ts_code: str, **kwargs) -> ProviderResult:
        self._last_error = None
        symbol = ts_code.split(".")[0]

        cached = self._cache_get(ts_code)
        if cached and (time.time() - cached[1]) < _TTL_SECONDS:
            return ProviderResult(
                data=cached[0], data_status="fresh",
                last_updated=cached[0].get("as_of"),
            )

        try:
            df = self._adapter.fetch("cyq", symbol=symbol)
            data = self._summarize(df)
        except AkshareUnavailable as exc:
            self._last_error = str(exc)
            data = None

        if data is None:
            # akshare 不可达（本机 push2his 常断）→ Tushare cyq_perf 回退
            data = self._fetch_tushare(ts_code)

        if data is None:
            # 取数失败：有旧缓存就降级返回 stale，比整体 unavailable 更有用。
            if cached:
                return ProviderResult(
                    data=cached[0], data_status="stale",
                    last_updated=cached[0].get("as_of"),
                    reason=humanize_unavailable("筹码分布", self._last_error),
                )
            return ProviderResult.unavailable(
                reason=humanize_unavailable("筹码分布", self._last_error)
            )

        self._cache_set(ts_code, data)
        return ProviderResult(
            data=data, data_status="fresh", last_updated=data.get("as_of"),
        )
