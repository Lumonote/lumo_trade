"""全市场日线补齐(market_daily) —— Tushare ``daily`` 按交易日整批拉取。

为什么需要:股票池的「入选后涨幅」要用「首次入选次日开盘价」与「最新收盘价」,
而本地 ``ohlcv`` 表只覆盖被单独分析过的少数股票(673/3603),且很多停在几个月前,
于是绝大多数池内股票该列恒为空、少数还会拿几个月前的收盘当「现价」。
Tushare ``daily(trade_date=...)`` 一次调用返回**当日全市场约 5500 只**的 OHLC,
所以补价格按「需要的交易日」补(每天 1 次请求),而不是按股票逐只抓(3600 次请求)。

落库表沿用 ``market_daily``(字段与 Tushare ``daily`` 逐列同名),Token 缺失 /
Tushare 不可用时所有函数安全降级(返回 0 / 空),调用方不受影响。
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading
from typing import Dict, Iterable, List, Optional, Sequence

from data_store import calendar_repo, market_snapshot_repo, tushare_client
from data_store.connection import get_conn
from data_store.opportunity_prices import STOCK_TS_CODE_FILTER

logger = logging.getLogger(__name__)

# 后台补数线程的单例闸门(页面每次打开都会调用 ensure_pool_dates_background)。
_bg_lock = threading.Lock()
_bg_running = False

# 单个交易日「已补齐」的判定阈值:全市场约 5500 行,低于该值视为只有零星
# 指数行(market_regime 写的 4 只指数)或上次抓取被截断,需要重新抓。
_MIN_ROWS_PER_DAY = 1000


def _iso(value: Optional[str]) -> str:
    """'20260814' / '2026-08-14' → '2026-08-14'(空 → '')。"""
    s = str(value or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _compact(value: Optional[str]) -> str:
    """'2026-08-14' / '20260814' → '20260814'(空 → '')。"""
    s = str(value or "").strip()
    return s.replace("-", "")


def filled_dates(dates: Iterable[str]) -> set[str]:
    """返回 ``dates``(YYYYMMDD)中已经有全市场个股行的日期。"""
    wanted = [_compact(d) for d in dates if _compact(d)]
    if not wanted:
        return set()
    placeholders = ",".join("?" * len(wanted))
    rows = get_conn().execute(
        f"""
        SELECT trade_date, COUNT(*) AS n FROM market_daily
        WHERE trade_date IN ({placeholders}) AND {STOCK_TS_CODE_FILTER}
        GROUP BY trade_date
        """,
        wanted,
    ).fetchall()
    return {str(r[0]) for r in rows if int(r[1] or 0) >= _MIN_ROWS_PER_DAY}


def fetch_date(trade_date: str) -> int:
    """拉取并落库某交易日的全市场日线。返回写入行数(不可用时 0)。"""
    pro = tushare_client.get_pro()
    if pro is None:
        return 0
    day = _compact(trade_date)
    try:
        df = pro.daily(trade_date=day)
    except Exception as exc:  # noqa: BLE001 — 网络/额度问题一律降级
        logger.warning("tushare daily(%s) failed: %s", day, exc)
        return 0
    if df is None or df.empty:
        return 0
    return market_snapshot_repo.upsert_daily_df(df)


def ensure_dates(dates: Sequence[str], max_fetch: Optional[int] = None) -> Dict[str, int]:
    """补齐给定交易日的全市场日线(已补齐的跳过)。

    ``max_fetch`` 限制本次最多抓几天(页面请求路径上用它兜住耗时,剩余的留给
    下一次刷新或离线回填脚本)。返回 ``{requested, filled, fetched, remaining}``。
    """
    wanted = sorted({_compact(d) for d in dates if _compact(d)}, reverse=True)
    have = filled_dates(wanted)
    missing = [d for d in wanted if d not in have]
    budget = len(missing) if max_fetch is None else max(0, int(max_fetch))
    fetched = 0
    for day in missing[:budget]:
        if fetch_date(day) > 0:
            fetched += 1
        else:
            break  # Tushare 不可用/无权限:继续重试只是白等
    return {
        "requested": len(wanted),
        "filled": len(have),
        "fetched": fetched,
        "remaining": max(0, len(missing) - fetched),
    }


def open_days(start: str, end: str) -> List[str]:
    """[start, end] 内的交易日(YYYYMMDD 升序)。

    先读本地 ``trade_calendar``;本地没覆盖到 ``end`` 之后(说明日历还没拉过或
    已经过期)时向 Tushare 取一次 ``trade_cal``,并**多存到当年年底**,这样后续
    每天的调用都能直接命中本地、不会每次都发请求。Tushare 不可用时返回本地部分。
    """
    s, e = _compact(start), _compact(end)
    if not s or not e or s > e:
        return []
    cached = calendar_repo.open_days()
    local = [d for d in cached if s <= d <= e]
    if local and any(d > e for d in cached):
        return local
    pro = tushare_client.get_pro()
    if pro is None:
        return local
    year_end = f"{e[:4]}1231"
    try:
        df = pro.trade_cal(exchange="SSE", start_date=s, end_date=max(e, year_end), is_open="1")
    except Exception as exc:  # noqa: BLE001
        logger.warning("tushare trade_cal(%s~%s) failed: %s", s, e, exc)
        return local
    if df is None or df.empty:
        return local
    days = sorted(str(d) for d in df["cal_date"].tolist())
    try:
        calendar_repo.upsert(days, is_open=1)
    except Exception as exc:  # noqa: BLE001 — 缓存写失败不影响返回
        logger.warning("trade_calendar upsert failed: %s", exc)
    return [d for d in days if s <= d <= e]


def next_open_days(after_dates: Iterable[str], calendar: Sequence[str]) -> List[str]:
    """每个日期之后的第一个交易日(用作「次日开盘买入」的基准日)。"""
    cal = sorted({_compact(d) for d in calendar if _compact(d)})
    out: List[str] = []
    for raw in after_dates:
        day = _compact(raw)
        if not day:
            continue
        nxt = next((d for d in cal if d > day), None)
        if nxt:
            out.append(nxt)
    return sorted(set(out))


def latest_filled_date() -> str:
    """market_daily 里最近一个有全市场个股行的交易日(ISO;无数据 → '')。"""
    row = get_conn().execute(
        f"""
        SELECT trade_date FROM market_daily
        WHERE {STOCK_TS_CODE_FILTER}
        GROUP BY trade_date HAVING COUNT(*) >= ?
        ORDER BY trade_date DESC LIMIT 1
        """,
        (_MIN_ROWS_PER_DAY,),
    ).fetchone()
    return _iso(row[0]) if row else ""


def ensure_pool_dates_background(since_date: Optional[str] = None,
                                 max_fetch: int = 8) -> bool:
    """后台补齐股票池取价需要的交易日(不阻塞调用方)。

    页面每次打开都调一次:先补最近的交易日(现价),再往回补历史(买入基准日),
    每次最多 ``max_fetch`` 天,几次刷新之内补齐;历史区间也可以直接跑
    ``scripts/backfill_market_daily.py`` 一次补完。

    返回是否真的启动了后台线程(已有线程在跑 / 无 Tushare 时为 False)。
    网络请求全部发生在后台线程里,页面响应时间不受影响。
    """
    global _bg_running
    if not tushare_client.available():
        return False
    with _bg_lock:
        if _bg_running:
            return False
        _bg_running = True

    def _work() -> None:
        global _bg_running
        try:
            start = _compact(since_date) or _earliest_run_date()
            end = _dt.date.today().strftime("%Y%m%d")
            if not start or start > end:
                return
            days = open_days(start, end)
            if days:
                # 倒序:最近的交易日(现价)优先,历史买入日随后几次刷新补齐。
                ensure_dates(days, max_fetch=max_fetch)
        except Exception as exc:  # noqa: BLE001 — 后台补数失败只影响「暂无价格」
            logger.warning("market_daily background fill failed: %s", exc)
        finally:
            with _bg_lock:
                _bg_running = False

    threading.Thread(target=_work, name="market-daily-fill", daemon=True).start()
    return True


def _earliest_run_date() -> str:
    """最早一次机会挖掘 run 的日期(YYYYMMDD;没有 run → '')。"""
    row = get_conn().execute("SELECT MIN(run_date) FROM opportunity_run").fetchone()
    return _compact(row[0]) if row and row[0] else ""
