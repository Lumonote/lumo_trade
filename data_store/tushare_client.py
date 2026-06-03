"""Shared Tushare ``pro_api`` client + small helpers.

Token-gated. Every accessor returns ``None`` / empty when no token is
configured (or tushare isn't installed) so callers degrade gracefully and
never raise just because Tushare is unavailable.

Why this exists: on some networks/hosts (notably this Intel Mac) the
akshare/eastmoney endpoints — ``push2his`` (cyq), ``ulist.np`` (quotes),
``datacenter`` (lhb/holders) — are blocked or disconnected, leaving the
institutional repos empty and the stock-analysis suite panels showing
「数据不足」. Tushare reaches the same data over a different host that *is*
reachable here, so providers use it as a fallback source.

Token is read from ``TUSHARE_TOKEN`` env first, then
``config/tushare_config.json`` (``tushare.token``) — same precedence as
``data_store.ohlcv_fetch``.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_PLACEHOLDER = "your_tushare_token_here"

_lock = threading.Lock()
_pro = None  # cached tushare pro_api handle
_init_failed = False  # latch: once init fails (no token / not installed) stop retrying


def _load_token() -> str:
    tok = os.environ.get("TUSHARE_TOKEN", "").strip()
    if tok:
        return tok
    try:
        cfg_path = Path(__file__).resolve().parents[1] / "config" / "tushare_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return str((cfg.get("tushare") or {}).get("token") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def get_pro():
    """Return a cached tushare ``pro_api`` client, or ``None`` if unavailable."""
    global _pro, _init_failed
    if _pro is not None:
        return _pro
    if _init_failed:
        return None
    with _lock:
        if _pro is not None:
            return _pro
        if _init_failed:
            return None
        token = _load_token()
        if not token or token == _PLACEHOLDER:
            _init_failed = True
            return None
        try:
            import tushare as ts  # type: ignore

            ts.set_token(token)
            _pro = ts.pro_api()
            return _pro
        except Exception as exc:  # noqa: BLE001
            logger.warning("tushare init failed: %s", exc)
            _init_failed = True
            return None


def available() -> bool:
    """True when a Tushare client could be built (token present + lib installed)."""
    return get_pro() is not None


def to_ts_code(code: str) -> str:
    """6-digit code → tushare ``ts_code`` (``XXXXXX.SH`` / ``.SZ`` / ``.BJ``).

    Accepts an already-suffixed code and re-derives the suffix from the digits,
    so ``600519`` / ``600519.SH`` / ``sh600519`` all normalise correctly.
    """
    digits = "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]
    if digits.startswith("92"):  # 北交所 920xxx 新代码段，须先于 9→SH 判断
        return f"{digits}.BJ"
    head = digits[:1]
    if head in ("5", "6", "9"):  # 9 此处仅余沪市 B 股（900xxx）
        return f"{digits}.SH"
    if head in ("4", "8"):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def recent_trade_dates(n: int = 20, exchange: str = "SSE") -> List[str]:
    """Up to ``n`` most-recent open trading days as ``YYYYMMDD`` (newest first).

    Returns ``[]`` when Tushare is unavailable. Used by the date-keyed
    龙虎榜 (top_inst) backfill, which has no per-stock query.
    """
    pro = get_pro()
    if pro is None:
        return []
    today = _dt.date.today()
    start = today - _dt.timedelta(days=max(n * 2, 40))
    try:
        cal = pro.trade_cal(
            exchange=exchange,
            start_date=start.strftime("%Y%m%d"),
            end_date=today.strftime("%Y%m%d"),
            is_open="1",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("tushare trade_cal failed: %s", exc)
        return []
    if cal is None or cal.empty:
        return []
    days = sorted(str(d) for d in cal["cal_date"].tolist())
    return days[-n:][::-1]


def yyyymmdd_to_iso(value: Optional[str]) -> str:
    """``20260601`` → ``2026-06-01``; passes through other shapes defensively."""
    s = str(value or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s
