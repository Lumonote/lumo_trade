"""龙虎榜机构席位 provider。"""
from __future__ import annotations

import datetime as _dt
import logging
import threading

import pandas as pd

from analysis.institutional.base import BaseProvider, ProviderResult, humanize_unavailable
from analysis.institutional.quant_seat_registry import QuantSeatRegistry
from data_store import dragon_tiger_repo, tushare_client
from data_store.akshare_adapter import AkshareUnavailable

logger = logging.getLogger(__name__)

_QUANT_KEYWORDS = ("量化", "DMA", "程序化", "算法")

# Tushare top_inst 按交易日返回全市场（无单股查询），故回填最近 N 个交易日的全市场席位
# 一次落库，整张自选都受益（与 akshare lhb_jgmm 全市场→filter 的思路一致）。
_LHB_WINDOW = 20
_TS_SIDE = {"0": "buy", "1": "sell"}
_CONF_SCORE = {"high": 0.9, "medium": 0.6}
# 本进程已回填的「最新交易日」集合：未上榜的票回填后查库仍空，靠该标记避免每次浏览重复打网络。
_backfill_lock = threading.Lock()
_backfilled_dates: set[str] = set()


def _classify_quant(name: str) -> tuple[int, float]:
    is_q = int(any(k in (name or "") for k in _QUANT_KEYWORDS))
    return is_q, 0.6 if is_q else 0.0


def _to_f(v) -> float:
    try:
        f = float(v)
        return f if f == f else 0.0  # NaN → 0
    except (TypeError, ValueError):
        return 0.0


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

    def _fetch_tushare(self, ts_code: str) -> None:
        """Tushare 回退源：top_inst 龙虎榜机构/营业部席位（akshare datacenter 不可达时）。

        top_inst 按 trade_date 返回全市场，无单股查询；故回填最近 _LHB_WINDOW 个交易日
        的全市场席位一次落库，整张自选都受益。本进程内同一最新交易日只回填一次
        （未上榜的票回填后查库仍空，靠 _backfilled_dates 避免重复打网络）。
        """
        pro = tushare_client.get_pro()
        if pro is None:
            return
        dates = tushare_client.recent_trade_dates(_LHB_WINDOW)
        if not dates:
            return
        newest = dates[0]
        with _backfill_lock:
            if newest in _backfilled_dates:
                return
            _backfilled_dates.add(newest)  # 先占位防并发重复回填；全失败时回滚
        ok = False
        ts_err = None
        try:
            for d in dates:
                try:
                    df = pro.top_inst(trade_date=d)
                except Exception as exc:  # noqa: BLE001
                    ts_err = str(exc)
                    self._last_error = f"tushare top_inst {d}: {exc}"
                    logger.warning("tushare top_inst failed %s: %s", d, exc)
                    continue
                ok = True
                if df is None or df.empty:
                    continue
                rows = []
                for r in df.itertuples(index=False):
                    exalter = tushare_client.text_field(getattr(r, "exalter", ""))
                    code = tushare_client.text_field(getattr(r, "ts_code", ""))
                    if not exalter or not code:
                        continue
                    is_q, conf = self._registry.classify(exalter)
                    if not is_q:  # 注册表未命中再退回关键词匹配
                        kw_q, _ = _classify_quant(exalter)
                        is_q = bool(kw_q)
                    rows.append({
                        "ts_code": code,
                        "trade_date": tushare_client.yyyymmdd_to_iso(getattr(r, "trade_date", "")),
                        "inst_name": exalter,
                        "side": _TS_SIDE.get(str(getattr(r, "side", "")), "buy"),
                        "net_amount": _to_f(getattr(r, "net_buy", None)),
                        "buy_amount": _to_f(getattr(r, "buy", None)),
                        "sell_amount": _to_f(getattr(r, "sell", None)),
                        "is_quant": 1 if is_q else 0,
                        "quant_confidence": _CONF_SCORE.get(conf, 0.6 if is_q else 0.0),
                        "reason": tushare_client.text_field(getattr(r, "reason", "")),
                    })
                if rows:
                    dragon_tiger_repo.upsert_rows(rows)
            logger.info("tushare lhb: backfilled %d open days (newest %s)", len(dates), newest)
            if ok and ts_err is None:
                # 全市场窗口回填成功：若该股仍查无，是「确实没上榜」而非取数失败，
                # 清掉 akshare 的报错，让降级文案回到「暂无记录」。
                self._last_error = None
        finally:
            if not ok:  # 一个交易日都没成功 → 回滚标记，允许下次重试
                with _backfill_lock:
                    _backfilled_dates.discard(newest)

    def get(self, ts_code: str, days: int = 90, **kwargs) -> ProviderResult:
        since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
        df = dragon_tiger_repo.get_by_code(ts_code)
        if df.empty:
            self._fetch_and_save(ts_code)
            df = dragon_tiger_repo.get_by_code(ts_code)
        if df.empty:
            # akshare 不可达 → Tushare 全市场窗口回填
            self._fetch_tushare(ts_code)
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
