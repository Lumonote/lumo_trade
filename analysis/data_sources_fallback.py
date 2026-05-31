"""直连 HTTP 兜底（行情 / 快讯）。spec §6.8 / E7。

`DirectHTTPFallback`：0-key、独立 try/except、TTL 缓存、多源按可用性顺序回退。
仅作为 `investor_sentiment` / `news_sentiment_collector` 主路径（akshare /
爬虫）失败时的兜底，降低「数据不足」。

数据源：
- 行情：Tencent `qt.gtimg.cn/q=` → Sina `hq.sinajs.cn/list=`（均 GBK）。
- 快讯：金十 `flash-api.jin10.com/get_flash_list` → 东财快讯
  `newsapi.eastmoney.com/kuaixun/v1/...`（JSONP）。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Optional

import requests

DEFAULT_TTL = 300  # 5min（spec：5–10min）
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _default_fetch(url, *, headers=None, timeout=6, encoding=None) -> Optional[str]:
    """真实 HTTP 取数：返回解码后文本；非 200 或任何异常 → None。"""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if encoding:
            resp.encoding = encoding
        if resp.status_code != 200:
            return None
        return resp.text or None
    except Exception:
        return None


def _to_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        s = str(v).strip()
        if s in ("", "N/A", "None", "-"):
            return None
        return float(s)
    except Exception:
        return None


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


class DirectHTTPFallback:
    """直连 HTTP 兜底。`fetch` 可注入（测试用），默认走 requests。"""

    def __init__(self, *, fetch: Optional[Callable] = None, ttl_seconds: int = DEFAULT_TTL):
        self._fetch = fetch or _default_fetch
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Any]] = {}

    def _cached(self, key: str, producer: Callable):
        now = time.time()
        hit = self._cache.get(key)
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        val = producer()
        self._cache[key] = (now, val)
        return val

    # ---- 行情：Tencent gtimg → Sina sinajs --------------------------------
    def fetch_index_quote(self, code: str) -> Optional[dict]:
        """指数行情兜底，code 形如 'sh000001' / 'sz399006'。"""
        return self._cached(f"idx:{code}", lambda: self._quote(str(code).strip().lower()))

    def fetch_stock_quote(self, code: str) -> Optional[dict]:
        """个股行情兜底，code 接受 '000001' / '600519' / 'sz000001'。"""
        norm = self._normalize_stock_code(code)
        return self._cached(f"stk:{norm}", lambda: self._quote(norm))

    def _quote(self, code: str) -> Optional[dict]:
        return self._quote_tencent(code) or self._quote_sina(code)

    def _quote_tencent(self, code: str) -> Optional[dict]:
        text = self._fetch(f"http://qt.gtimg.cn/q={code}", encoding="gbk", timeout=6)
        if not text:
            return None
        m = re.search(r'="([^"]*)"', text)
        if not m:
            return None
        parts = m.group(1).split("~")
        if len(parts) < 33:
            return None
        current, prev_close = _to_float(parts[3]), _to_float(parts[4])
        if current is None or prev_close is None:
            return None
        change_pct = _to_float(parts[32])
        if change_pct is None and prev_close:
            change_pct = round((current - prev_close) / prev_close * 100, 2)
        return {
            "current": round(current, 4),
            "prev_close": round(prev_close, 4),
            "change_pct": change_pct,
            "name": parts[1] or "",
            "source": "tencent",
        }

    def _quote_sina(self, code: str) -> Optional[dict]:
        text = self._fetch(
            f"http://hq.sinajs.cn/list={code}",
            headers={"User-Agent": _UA, "Referer": "http://finance.sina.com.cn/"},
            encoding="gbk", timeout=6,
        )
        if not text:
            return None
        m = re.search(r'="([^"]*)"', text)
        if not m:
            return None
        parts = m.group(1).split(",")
        if len(parts) < 4:
            return None
        prev_close, current = _to_float(parts[2]), _to_float(parts[3])
        if current is None or not prev_close:
            return None
        return {
            "current": round(current, 4),
            "prev_close": round(prev_close, 4),
            "change_pct": round((current - prev_close) / prev_close * 100, 2),
            "name": parts[0],
            "source": "sina",
        }

    @staticmethod
    def _normalize_stock_code(code: str) -> str:
        c = str(code).strip().lower()
        if c.startswith(("sh", "sz", "bj")):
            return c
        digits = re.sub(r"\D", "", c)
        return f"sh{digits}" if digits.startswith(("5", "6", "9")) else f"sz{digits}"

    # ---- 快讯：金十 → 东财快讯 --------------------------------------------
    def fetch_flash_news(self, limit: int = 20) -> list[dict]:
        return self._cached(f"flash:{limit}", lambda: self._flash_news(limit))

    def _flash_news(self, limit: int) -> list[dict]:
        return self._flash_jin10(limit) or self._flash_eastmoney(limit) or []

    def _flash_jin10(self, limit: int) -> list[dict]:
        text = self._fetch(
            "https://flash-api.jin10.com/get_flash_list?channel=-8200&vip=1",
            headers={
                "User-Agent": _UA,
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.jin10.com/",
                "x-app-id": "SO1EJGmNgCtmpcPF",
                "x-version": "1.0.0",
            },
            timeout=5,
        )
        if not text:
            return []
        try:
            payload = json.loads(text)
        except Exception:
            return []
        rows = payload.get("data") if isinstance(payload, dict) else None
        out: list[dict] = []
        for row in rows or []:
            data = row.get("data") or {}
            title = _strip_tags(data.get("title") or data.get("vip_title") or data.get("content") or "")
            if not title:
                continue
            out.append({
                "title": title[:150],
                "time": row.get("time"),
                "source": (data.get("source") or "金十数据").strip() or "金十数据",
                "url": data.get("source_link") or data.get("link") or "",
                "origin": "jin10",
            })
            if len(out) >= limit:
                break
        return out

    def _flash_eastmoney(self, limit: int) -> list[dict]:
        text = self._fetch(
            "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html",
            headers={"User-Agent": _UA, "Referer": "https://kuaixun.eastmoney.com/"},
            timeout=5,
        )
        if not text:
            return []
        m = re.search(r"\{.*\}", text, re.S)  # 去 JSONP 包裹：var ajaxResult={...};
        if not m:
            return []
        try:
            payload = json.loads(m.group(0))
        except Exception:
            return []
        rows = payload.get("LivesList") if isinstance(payload, dict) else None
        out: list[dict] = []
        for row in rows or []:
            title = _strip_tags(row.get("title") or "")
            if not title:
                continue
            out.append({
                "title": title[:150],
                "time": row.get("showtime") or row.get("time"),
                "source": "东方财富",
                "url": row.get("url_w") or row.get("url_unique") or row.get("url_m") or "",
                "origin": "eastmoney",
            })
            if len(out) >= limit:
                break
        return out
