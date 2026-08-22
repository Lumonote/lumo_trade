"""股票池「入选后涨幅」的价格取数。

口径:``(最新收盘 - 首次入选次日开盘) / 次日开盘 * 100``,与报告的「次日开盘买入」
一致。价格面按**每只股票同源**的原则选取,避免把不复权价(market_daily)和前复权价
(ohlcv)混在一次涨幅计算里:

1. ``market_daily`` —— Tushare 全市场日线,覆盖 5500+ 只、按交易日整批补齐
   (见 :mod:`data_store.market_daily_fetch`);
2. ``ohlcv`` —— 本地逐只抓的前复权日线,只覆盖被单独分析过的少数股票,做兜底。

同一只股票的买入价与现价必须来自同一张表;两张表都凑不齐则返回 ``None``
(前端显示 ``--``),不做跨表拼接。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from data_store import connection

# 个股行过滤:market_daily 同时存着 analysis/market_regime 写入的指数日 K
# (000001.SH 上证指数 / 399303.SZ 国证2000 等),其 6 位前缀会和真实个股代码
# 撞车(000001.SZ 是平安银行),取价时必须只认个股 ts_code。
STOCK_TS_CODE_FILTER = (
    "(ts_code LIKE '6%.SH' OR ts_code LIKE '0%.SZ' OR ts_code LIKE '3%.SZ' "
    " OR ts_code LIKE '%.BJ') AND ts_code NOT LIKE '39%.SZ'"
)

# 单日全市场行数下限:低于该值说明这天只有零星指数行/抓取被截断,不能当价格面用。
_MIN_ROWS_PER_DAY = 1000


def _iso(compact: str) -> str:
    s = str(compact or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 and s.isdigit() else s


def _compact(iso: str) -> str:
    return str(iso or "").replace("-", "")


def _market_stock_dates(conn) -> List[str]:
    """market_daily 中「有全市场个股行」的交易日(YYYYMMDD 升序)。"""
    rows = conn.execute(
        f"""
        SELECT trade_date FROM market_daily
        WHERE {STOCK_TS_CODE_FILTER}
        GROUP BY trade_date HAVING COUNT(*) >= ?
        ORDER BY trade_date ASC
        """,
        (_MIN_ROWS_PER_DAY,),
    ).fetchall()
    return [str(r[0]) for r in rows]


def _market_prices_on(conn, trade_date: str, codes: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """某交易日全市场日线 → ``{code: {open, close}}``(只保留 ``codes`` 里的股票)。"""
    wanted = set(codes)
    if not wanted:
        return {}
    rows = conn.execute(
        f"""
        SELECT SUBSTR(ts_code, 1, 6) AS code, open, close FROM market_daily
        WHERE trade_date = ? AND {STOCK_TS_CODE_FILTER}
        """,
        (str(trade_date),),
    ).fetchall()
    return {
        str(r[0]): {"open": r[1], "close": r[2]}
        for r in rows
        if str(r[0]) in wanted
    }


def _ohlcv_entry_and_latest(conn, first_dates: Mapping[str, str]) -> Dict[str, Dict[str, Any]]:
    """本地 ohlcv 兜底:每只股票的「首次入选之后第一根日线」与「最新日线」。"""
    out: Dict[str, Dict[str, Any]] = {}
    for code, first_date in first_dates.items():
        entry = conn.execute(
            """
            SELECT SUBSTR(ts, 1, 10) AS d, open FROM ohlcv
            WHERE code = ? AND frequency = '1d' AND SUBSTR(ts, 1, 10) > ?
            ORDER BY ts ASC LIMIT 1
            """,
            (code, str(first_date)),
        ).fetchone()
        if not entry:
            continue
        latest = conn.execute(
            """
            SELECT SUBSTR(ts, 1, 10) AS d, close FROM ohlcv
            WHERE code = ? AND frequency = '1d'
            ORDER BY ts DESC LIMIT 1
            """,
            (code,),
        ).fetchone()
        if not latest:
            continue
        out[code] = {
            "entry_date": entry[0], "entry_open": entry[1],
            "price_date": latest[0], "latest_close": latest[1],
            "price_source": "ohlcv",
        }
    return out


def _pct(entry_open, latest_close) -> Optional[float]:
    try:
        entry = float(entry_open)
        close = float(latest_close)
    except (TypeError, ValueError):
        return None
    if entry <= 0:
        return None
    return round((close - entry) / entry * 100, 2)


def post_selection_returns(first_dates: Mapping[str, str]) -> Dict[str, Dict[str, Any]]:
    """``{code: 首次入选日}`` → ``{code: {entry_date, entry_open, price_date,
    latest_close, post_select_return_pct, price_source}}``。

    没有可用价格的股票不出现在返回值里(调用方按 ``None`` 处理)。
    """
    clean = {
        str(code): str(day)
        for code, day in (first_dates or {}).items()
        if code and day
    }
    if not clean:
        return {}

    conn = connection.get_conn()
    out: Dict[str, Dict[str, Any]] = {}
    market_dates = _market_stock_dates(conn)
    if market_dates:
        latest_date = market_dates[-1]
        latest = _market_prices_on(conn, latest_date, list(clean))
        # 买入基准日 = 首次入选之后第一个有全市场行情的交易日;同一基准日的
        # 股票合并成一次查询(全市场日线按 trade_date 建索引,逐日取最省)。
        by_entry_date: Dict[str, List[str]] = {}
        for code, first_date in clean.items():
            if code not in latest:
                continue  # 现价缺失(退市/停牌/北交所未覆盖)→ 交给 ohlcv 兜底
            compact_first = _compact(first_date)
            entry_date = next((d for d in market_dates if d > compact_first), None)
            if entry_date:
                by_entry_date.setdefault(entry_date, []).append(code)
        for entry_date, codes in by_entry_date.items():
            opens = _market_prices_on(conn, entry_date, codes)
            for code, px in opens.items():
                pct = _pct(px.get("open"), latest[code].get("close"))
                if pct is None:
                    continue
                out[code] = {
                    "entry_date": _iso(entry_date),
                    "entry_open": px.get("open"),
                    "price_date": _iso(latest_date),
                    "latest_close": latest[code].get("close"),
                    "post_select_return_pct": pct,
                    "price_source": "market_daily",
                }

    missing = {code: day for code, day in clean.items() if code not in out}
    for code, px in _ohlcv_entry_and_latest(conn, missing).items():
        pct = _pct(px.get("entry_open"), px.get("latest_close"))
        if pct is None:
            continue
        out[code] = {**px, "post_select_return_pct": pct}
    return out
