"""龙虎榜单(含游资净额)回填 provider —— Tushare `top_list` 口径。

backfill_recent 循环最近 N 个交易日,逐日取全市场龙虎榜单,归一化日期后落
dragon_tiger_list 表并写 sync_log。dates / fetcher 可注入(便于测试与切换数据源);
默认走 tushare_client.recent_trade_dates + pro.top_list。

tushare_client 仅在默认路径内惰性导入,故注入式调用零网络依赖。
"""
from __future__ import annotations

import logging
import re

import pandas as pd

from data_store import dragon_tiger_list_repo, sync_log_repo

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW = 30


def _to_iso(d) -> str:
    """'YYYYMMDD' / Timestamp / 'YYYY-MM-DD' → 'YYYY-MM-DD'。"""
    if d is None:
        return ""
    s = str(d).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return pd.to_datetime(s).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return s


def _default_fetcher(pro):
    def fetch(d):
        return pro.top_list(trade_date=d)
    return fetch


def backfill_recent(days=_DEFAULT_WINDOW, *, dates=None, fetcher=None, pro=None, skip_existing: bool = False) -> dict:
    """回填最近 days 个交易日的龙虎榜单。

    dates:  显式 YYYYMMDD 列表(测试/定制);None → tushare_client.recent_trade_dates(days)。
    fetcher: callable(date_yyyymmdd) -> DataFrame;None → pro.top_list(默认 get_pro())。
    返回 {"dates", "ok_dates", "rows", "errors": [(date, msg)], "newest"}。
    """
    if dates is None:
        from data_store import tushare_client
        dates = tushare_client.recent_trade_dates(days) or []
    requested_dates = list(dates)
    skipped_dates = 0
    if skip_existing:
        existing = dragon_tiger_list_repo.existing_dates(dates)
        dates = [d for d in dates if _to_iso(d) not in existing]
        skipped_dates = len(requested_dates) - len(dates)

    if fetcher is None:
        if pro is None:
            from data_store import tushare_client
            pro = tushare_client.get_pro()
        if pro is None:
            sync_log_repo.append("dragon_tiger_list", "", status="failed",
                                 error="tushare pro unavailable")
            return {"dates": 0, "requested_dates": len(requested_dates), "skipped_dates": skipped_dates,
                    "ok_dates": 0, "rows": 0,
                    "errors": [("", "tushare pro unavailable")], "newest": None}
        fetcher = _default_fetcher(pro)

    total_rows = 0
    ok_dates = 0
    errors: list[tuple[str, str]] = []
    for d in dates:
        try:
            df = fetcher(d)
        except Exception as exc:  # noqa: BLE001
            errors.append((str(d), str(exc)))
            logger.warning("top_list fetch failed %s: %s", d, exc)
            continue
        ok_dates += 1
        if df is None or len(df) == 0:
            continue
        work = df.copy()
        if "trade_date" in work.columns:
            work["trade_date"] = work["trade_date"].map(_to_iso)
        else:
            work["trade_date"] = _to_iso(d)
        total_rows += dragon_tiger_list_repo.upsert_df(work)

    status = "ok" if not errors else ("partial" if ok_dates else "failed")
    sync_log_repo.append(
        "dragon_tiger_list", "", status=status, rows=total_rows,
        error=("; ".join(f"{dt}:{m}" for dt, m in errors) or None),
    )
    logger.info("dragon_tiger_list backfill: %d/%d days ok, %d rows",
                ok_dates, len(dates), total_rows)
    return {
        "dates": len(dates), "requested_dates": len(requested_dates),
        "skipped_dates": skipped_dates, "ok_dates": ok_dates, "rows": total_rows,
        "errors": errors, "newest": (dates[0] if dates else None),
    }
