"""Forward daily-OHLCV fetcher (sqlite-native).

Fetches daily candlesticks for A-share codes and upserts them into the
``ohlcv`` table (frequency ``'1d'``), so downstream code (e.g. the backtest
return-calculator) can read post-recommendation prices that the prediction
pipeline never stored.

Sources, in priority order (free first, per project policy):

1. **Eastmoney** public kline API — free, no token, the *same* data source
   akshare uses under the hood. We bypass the ``akshare`` library because, in
   some environments, Eastmoney drops Python ``requests``/``urllib3`` TLS
   handshakes (anti-bot fingerprinting) and the system HTTP(S) proxy may be a
   dead local Clash port. We therefore talk to the endpoint directly with a
   transport that survives both:
     - ``curl_cffi`` with browser TLS impersonation (preferred), then
     - stdlib ``urllib`` with an explicit no-proxy opener + browser UA.
2. **Tushare** ``pro_bar`` — token-gated supplement; only used when a token is
   configured (``TUSHARE_TOKEN`` env or ``config/tushare_config.json``).

All bars are 前复权 (qfq) so a buy/sell pair computed from one series is
internally consistent.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional
from urllib.parse import urlencode

import pandas as pd

from data_store import ohlcv_repo

logger = logging.getLogger(__name__)

_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_SINA_KLINE_URL = (
    "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# Canonical ohlcv columns expected by ohlcv_repo.upsert_df / load_dataframe.
_CANON = ["timestamps", "open", "high", "low", "close", "volume", "amount"]


def _em_secid(code: str) -> str:
    """Map a 6-digit A-share code to an Eastmoney secid (``market.code``)."""
    c = str(code).strip().zfill(6)
    market = "1" if c[0] in "56789" else "0"  # 1=SH, 0=SZ/BJ
    return f"{market}.{c}"


def _sina_symbol(code: str) -> str:
    """6 位代码 → 新浪行情 symbol（沪 sh / 深 sz / 北 bj，含北交所 92 新段）。"""
    c = str(code).strip().zfill(6)
    if c.startswith(("43", "83", "87", "92")):
        return f"bj{c}"
    if c.startswith(("5", "6", "9")):
        return f"sh{c}"
    return f"sz{c}"


def _to_iso_date(value) -> str:
    """'20260812' / '2026-08-12' / None → '2026-08-12'（空 → ''）。"""
    s = str(value or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _http_get_sina_json(params: dict) -> Optional[list]:
    """GET 新浪 K 线接口。返回 JSON 列表（可能为空）；失败 → None。

    新浪 `CN_MarketData.getKLineData` 返回的是**非标准 JSON**（裸数组/键名裸奔），
    直接用 requests/urllib 拉回文本后按 JSON 解析；也兼容返回 dict 包裹的形态。
    """
    full = f"{_SINA_KLINE_URL}?{urlencode(params)}"
    try:
        import urllib.request as urlreq

        req = urlreq.Request(
            full,
            headers={"User-Agent": _BROWSER_UA, "Referer": "https://finance.sina.com.cn/"},
        )
        opener = urlreq.build_opener(urlreq.ProxyHandler({}))
        raw = opener.open(req, timeout=12).read().decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        logger.debug("sina kline fetch failed: %s", exc)
        return None
    if not raw:
        return None
    # 新浪接口偶发在数组前后带 JS 赋值壳（var xxx=...;），剥离后解析
    text = raw.strip()
    if "=" in text:
        text = text.split("=", 1)[1]
    text = text.rstrip(";").strip()
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        # 裸键名（无引号）容错：转成合法 JSON 再试
        try:
            import re

            fixed = re.sub(r"([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)
            payload = json.loads(fixed)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if isinstance(payload, dict):
        payload = payload.get("data") or payload.get("result") or []
    return payload if isinstance(payload, list) else None


def fetch_daily_sina(code: str, start: str, end: str) -> pd.DataFrame:
    """Fetch qfq-ish daily bars via Sina (free, no token; 无需 TLS 指纹即可达).

    Sina 返回的是不复权日K（最新在前）；`start`/`end` 用于截取窗口。
    失败 / 无数据 → 空 DataFrame（不抛异常，供 fetch_daily 链兜底）。
    """
    params = {
        "symbol": _sina_symbol(code),
        "scale": "240",  # 日K
        "ma": "no",
        "datalen": "620",  # 新股/次新股也能覆盖全量历史
    }
    rows_raw = _http_get_sina_json(params)
    if not rows_raw:
        return pd.DataFrame(columns=_CANON)
    # start/end 可能是 YYYYMMDD 或 YYYY-MM-DD；统一转 ISO 再与新浪的 day 比较
    start_iso = _to_iso_date(start)
    end_iso = _to_iso_date(end)
    rows = []
    for item in rows_raw:
        if not isinstance(item, dict):
            continue
        day = str(item.get("day") or item.get("date") or "").strip()
        if not day:
            continue
        iso_day = day.replace("/", "-")
        if start_iso and iso_day < start_iso:
            continue
        if end_iso and iso_day > end_iso:
            continue
        try:
            o, h, lo, c = (float(item.get("open")), float(item.get("high")),
                           float(item.get("low")), float(item.get("close")))
        except (TypeError, ValueError):
            continue
        if o <= 0 or c <= 0:
            continue
        rows.append({
            "timestamps": f"{iso_day} 00:00:00",
            "open": o,
            "high": h if h > 0 else max(o, c),
            "low": lo if lo > 0 else min(o, c),
            "close": c,
            "volume": float(item.get("volume") or 0),
            "amount": float(item.get("amount") or 0),
        })
    if not rows:
        return pd.DataFrame(columns=_CANON)
    df = pd.DataFrame(rows, columns=_CANON)
    df["timestamps"] = pd.to_datetime(df["timestamps"], errors="coerce")
    df = df.dropna(subset=["timestamps"]).sort_values("timestamps").reset_index(drop=True)
    df["timestamps"] = df["timestamps"].dt.strftime("%Y-%m-%d 00:00:00")
    return df


def _http_get_json(params: dict) -> Optional[dict]:
    """GET the Eastmoney kline endpoint, returning parsed JSON or None.

    Tries curl_cffi (browser-impersonated TLS) first, then stdlib urllib with
    a forced no-proxy opener. Both deliberately avoid the system proxy.
    """
    full = f"{_EM_KLINE_URL}?{urlencode(params)}"

    # 1) curl_cffi — browser TLS fingerprint; does not read the macOS sysconf proxy.
    try:
        from curl_cffi import requests as creq  # type: ignore

        resp = creq.get(full, impersonate="chrome", timeout=15, proxies={})
        if resp.status_code == 200:
            return resp.json()
        logger.debug("eastmoney curl_cffi status %s", resp.status_code)
    except Exception as exc:  # noqa: BLE001 — fall through to urllib
        logger.debug("eastmoney curl_cffi failed: %s", exc)

    # 2) stdlib urllib — explicit empty ProxyHandler so the dead system proxy
    #    is ignored; browser UA so Eastmoney does not drop the request.
    try:
        import urllib.request as urlreq

        req = urlreq.Request(
            full,
            headers={"User-Agent": _BROWSER_UA, "Referer": "https://quote.eastmoney.com/"},
        )
        opener = urlreq.build_opener(urlreq.ProxyHandler({}))
        raw = opener.open(req, timeout=15).read()
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.debug("eastmoney urllib failed: %s", exc)
        return None


def _parse_em_klines(payload: dict) -> pd.DataFrame:
    """Turn an Eastmoney kline payload into a canonical OHLCV DataFrame."""
    data = (payload or {}).get("data") or {}
    klines = data.get("klines") or []
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        # fields2 order: date, open, close, high, low, volume, amount, ...
        date, o, c, h, low, vol, amt = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
        rows.append(
            {
                "timestamps": f"{date} 00:00:00",
                "open": float(o),
                "high": float(h),
                "low": float(low),
                "close": float(c),
                "volume": float(vol),
                "amount": float(amt),
            }
        )
    return pd.DataFrame(rows, columns=_CANON)


def fetch_daily_eastmoney(code: str, start: str, end: str) -> pd.DataFrame:
    """Fetch qfq daily bars for ``code`` in [start, end] (YYYYMMDD). Empty df on failure."""
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",   # daily
        "fqt": "1",     # qfq (前复权)
        "secid": _em_secid(code),
        "beg": start,
        "end": end,
    }
    payload = _http_get_json(params)
    if not payload:
        return pd.DataFrame(columns=_CANON)
    return _parse_em_klines(payload)


def _tushare_token() -> str:
    try:
        from scripts.stock_filter_utils import load_tushare_token
        return load_tushare_token()
    except Exception:  # noqa: BLE001
        tok = os.environ.get("TUSHARE_TOKEN", "").strip()
        if tok:
            return tok
        try:
            cfg_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config", "tushare_config.json",
            )
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            return str((cfg.get("tushare") or {}).get("token") or "").strip()
        except Exception:  # noqa: BLE001
            return ""


def fetch_daily_tushare(code: str, start: str, end: str) -> pd.DataFrame:
    """Token-gated supplement. Returns empty df if no token / unavailable."""
    token = _tushare_token()
    if not token or token == "your_tushare_token_here":
        return pd.DataFrame(columns=_CANON)
    try:
        import tushare as ts  # type: ignore

        ts.set_token(token)
        pro = ts.pro_api()
        c = str(code).strip().zfill(6)
        ts_code = f"{c}.SH" if c[0] in "56789" else f"{c}.SZ"
        df = ts.pro_bar(ts_code=ts_code, api=pro, start_date=start, end_date=end,
                        freq="D", adj="qfq", asset="E")
        if df is None or df.empty:
            return pd.DataFrame(columns=_CANON)
        df = df.rename(columns={"trade_date": "timestamps", "vol": "volume"})
        df["timestamps"] = pd.to_datetime(df["timestamps"]).dt.strftime("%Y-%m-%d 00:00:00")
        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col not in df.columns:
                df[col] = None
        return df[_CANON].sort_values("timestamps").reset_index(drop=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("tushare fallback failed for %s: %s", code, exc)
        return pd.DataFrame(columns=_CANON)


def fetch_daily(code: str, start: str, end: str, throttle: float = 0.0) -> pd.DataFrame:
    """Fetch qfq daily bars via Eastmoney (free), then Tushare, then Sina.

    ``start``/``end`` are 'YYYYMMDD'. Returns a canonical OHLCV DataFrame
    (possibly empty), ascending by timestamp.

    Sina 兜底：Eastmoney push2his 在部分网络/本机被断开、Tushare 又未配 Token 时，
    新股/次新股也能通过新浪拉到全量日K（已验证 688825 等可达），避免「数据不足」。
    """
    df = fetch_daily_eastmoney(code, start, end)
    if df.empty:
        df = fetch_daily_tushare(code, start, end)
    if df.empty:
        df = fetch_daily_sina(code, start, end)
    if throttle:
        time.sleep(throttle)
    if not df.empty:
        df = df.sort_values("timestamps").reset_index(drop=True)
    return df


def ensure_daily(code: str, start: str, end: str, throttle: float = 0.0) -> pd.DataFrame:
    """Fetch daily bars for [start, end] and upsert into the ohlcv table.

    Returns the freshly fetched DataFrame (the source of truth for callers),
    so return calculations use one internally-consistent qfq series rather than
    the possibly-mixed contents of the table.
    """
    df = fetch_daily(code, start, end, throttle=throttle)
    if not df.empty:
        try:
            ohlcv_repo.upsert_df(str(code).zfill(6), "1d", df)
        except Exception as exc:  # noqa: BLE001 — caching is best-effort
            logger.warning("ohlcv upsert failed for %s: %s", code, exc)
    return df
