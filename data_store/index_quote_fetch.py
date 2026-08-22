# -*- coding: utf-8 -*-
"""指数实时报价(新浪 hq.sinajs.cn)。

``WatchlistService.quotes`` 只吃个股代码,指数取不到,故单开此模块。
返回字段:名称 / 当前点位 / 涨跌额 / 涨跌幅(%) / 成交量(手) / 成交额(万元)。

网络策略与 ``market_regime.fetch_index_daily`` 一致:先绕系统代理直连
(``trust_env=False``,本机 Clash 会吃掉部分请求),失败再走默认路由。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_URL = "https://hq.sinajs.cn/list={codes}"
_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
}
_LINE = re.compile(r'hq_str_s_([a-z]{2}\d{6})="([^"]*)"')


def _num(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result


def parse_sina_payload(text: str) -> Dict[str, Dict[str, Any]]:
    """新浪响应文本 → {sina_symbol: quote}。字段缺失或非数值的行整条丢弃。"""
    out: Dict[str, Dict[str, Any]] = {}
    for symbol, body in _LINE.findall(text or ""):
        parts = [p.strip() for p in body.split(",")]
        if len(parts) < 6:
            continue
        close, change, pct = _num(parts[1]), _num(parts[2]), _num(parts[3])
        if close is None or pct is None:
            continue
        out[symbol] = {
            "name": parts[0],
            "close": close,
            "change": change,
            "pct_chg": pct,
            "volume": _num(parts[4]),
            "amount": _num(parts[5]),
        }
    return out


def fetch_index_quotes(symbols: Iterable[str], timeout: float = 6.0) -> Dict[str, Dict[str, Any]]:
    """批量取指数实时报价。全部路由失败 → {}(调用方回退纯历史 bar)。"""
    codes: List[str] = [f"s_{s}" for s in symbols or [] if s]
    if not codes:
        return {}
    import requests

    url = _URL.format(codes=",".join(codes))
    for trust_env in (False, True):
        try:
            with requests.Session() as session:
                session.trust_env = trust_env
                resp = session.get(url, headers=_HEADERS, timeout=timeout)
                resp.encoding = "gbk"
                resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — 双路由逐个尝试
            logger.debug("fetch_index_quotes(trust_env=%s) 失败: %s", trust_env, exc)
            continue
        parsed = parse_sina_payload(resp.text)
        if parsed:
            return parsed
    return {}
