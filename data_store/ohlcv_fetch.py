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
    """Fetch qfq daily bars via Eastmoney (free), then Tushare (supplement).

    ``start``/``end`` are 'YYYYMMDD'. Returns a canonical OHLCV DataFrame
    (possibly empty), ascending by timestamp.
    """
    df = fetch_daily_eastmoney(code, start, end)
    if df.empty:
        df = fetch_daily_tushare(code, start, end)
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
