"""Homepage market-intelligence aggregation."""

from __future__ import annotations

import datetime
import re
import time
import urllib.parse
from html import unescape
from typing import Any

from webui.services.http_client import request_json


DEFAULT_TTL_SECONDS = 180


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value in (None, '', '—', 'N/A'):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_datetime(ts: datetime.datetime | float | int | None = None) -> str:
    if ts is None:
        dt = datetime.datetime.now()
    elif isinstance(ts, (int, float)):
        dt = datetime.datetime.fromtimestamp(ts)
    elif isinstance(ts, datetime.datetime):
        dt = ts
    else:
        return str(ts)
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def _strip_markup(value: Any) -> str:
    text = unescape(str(value or ''))
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('**', '').replace('&nbsp;', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _truncate_text(value: Any, limit: int = 180) -> str:
    text = _strip_markup(value)
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + '…'


def _money_text(value: Any) -> str:
    number = _safe_float(value, 0.0) or 0.0
    if abs(number) >= 100000000:
        return f"{number / 100000000:.2f}亿"
    if abs(number) >= 10000:
        return f"{number / 10000:.1f}万"
    return f"{number:.0f}"


class MarketIntelligenceService:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, Any] = {'ts': 0, 'payload': None}

    def _request_json(self, url: str, headers: dict[str, str] | None = None, timeout: int = 5) -> Any:
        return request_json(url, headers=headers, timeout=timeout, retries=3)

    def fetch_jinshi_flash(self, limit: int = 12) -> list[dict[str, Any]]:
        """Fetch Jinshi flash headlines for homepage macro tape."""
        url = 'https://flash-api.jin10.com/get_flash_list?channel=-8200&vip=1'
        payload = self._request_json(
            url,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
                ),
                'Accept': 'application/json,text/plain,*/*',
                'Referer': 'https://www.jin10.com/',
                'x-app-id': 'SO1EJGmNgCtmpcPF',
                'x-version': '1.0.0',
            },
            timeout=4,
        )
        rows = payload.get('data') if isinstance(payload, dict) else []
        items = []
        for row in rows or []:
            data = row.get('data') or {}
            title = data.get('title') or data.get('vip_title') or ''
            content = data.get('content') or ''
            text = _strip_markup(title or content)
            if not text:
                continue
            source = _strip_markup(data.get('source') or '')
            link = data.get('source_link') or data.get('link') or ''
            items.append({
                'id': row.get('id'),
                'time': row.get('time'),
                'title': _truncate_text(text, 150),
                'source': source or '金十数据',
                'important': bool(row.get('important')),
                'url': link,
            })
            if len(items) >= limit:
                break
        return items

    def fetch_xueqiu_hot(self, limit: int = 12) -> list[dict[str, Any]]:
        """雪球关注热度榜（akshare stock_hot_follow_xq，仅展示用）。

        akshare 内部已处理雪球 cookie/反爬；失败/被限时由 load() 捕获并降级为空面板。
        """
        import akshare as ak  # 延迟导入，避免拖慢模块加载
        df = ak.stock_hot_follow_xq(symbol="最热门")
        if df is None or getattr(df, 'empty', True):
            return []
        items: list[dict[str, Any]] = []
        for _, row in df.head(limit).iterrows():
            raw_code = str(row.get('股票代码') or '').strip()
            code = re.sub(r'\D', '', raw_code)  # 去掉 SH/SZ 前缀，留 6 位数字
            name = str(row.get('股票简称') or '').strip()
            if not code or not name:
                continue
            follow = _safe_float(row.get('关注'), 0.0) or 0.0
            items.append({
                'code': code,
                'name': name,
                'follow': int(follow),
                'follow_text': _money_text(follow),
                'price': _safe_float(row.get('最新价'), None),
                'source': 'xueqiu',
            })
        return items

    def fetch_eastmoney_clist(self, fs: str, fid: str = 'f3', limit: int = 10) -> list[dict[str, Any]]:
        """Fetch Eastmoney board/stock ranking rows for display only."""
        params = {
            'pn': '1',
            'pz': str(limit),
            'po': '1',
            'np': '1',
            'fltt': '2',
            'invt': '2',
            'fid': fid,
            'fs': fs,
            'fields': 'f12,f14,f2,f3,f62',
        }
        url = 'https://push2.eastmoney.com/api/qt/clist/get?' + urllib.parse.urlencode(params)
        payload = self._request_json(
            url,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
                ),
                'Accept': 'application/json,text/plain,*/*',
                'Referer': 'https://quote.eastmoney.com/',
            },
            timeout=4,
        )
        rows = ((payload or {}).get('data') or {}).get('diff') or []
        items = []
        for row in rows:
            code = str(row.get('f12') or '').strip()
            name = str(row.get('f14') or '').strip()
            if not code or not name:
                continue
            money_flow = _safe_float(row.get('f62'), 0.0) or 0.0
            items.append({
                'code': code,
                'name': name,
                'price': _safe_float(row.get('f2'), None),
                'change_pct': round(_safe_float(row.get('f3'), 0.0) or 0.0, 2),
                'main_net_inflow': money_flow,
                'main_net_inflow_text': _money_text(money_flow),
                'source': 'eastmoney',
            })
        return items

    def load(self) -> dict[str, Any]:
        now = time.time()
        cached = self._cache.get('payload')
        if cached and now - self._cache.get('ts', 0) < self.ttl_seconds:
            return cached

        payload = {
            'updated_at': _format_datetime(now),
            'jinshi': [],
            'xueqiu_hot': [],
            'eastmoney': {
                'industry_boards': [],
                'concept_boards': [],
                'money_boards': [],
                'hot_stocks': [],
                'top_gainers': [],
                'updated_at': _format_datetime(now),
            },
            'errors': {},
        }

        try:
            payload['jinshi'] = self.fetch_jinshi_flash(limit=12)
        except Exception as exc:
            payload['errors']['jinshi'] = str(exc)

        try:
            payload['xueqiu_hot'] = self.fetch_xueqiu_hot(limit=12)
        except Exception as exc:
            payload['errors']['xueqiu_hot'] = str(exc)

        try:
            payload['eastmoney']['industry_boards'] = self.fetch_eastmoney_clist(
                'm:90+t:2', fid='f3', limit=8
            )
        except Exception as exc:
            payload['errors']['eastmoney_industry'] = str(exc)

        try:
            payload['eastmoney']['concept_boards'] = self.fetch_eastmoney_clist(
                'm:90+t:3', fid='f3', limit=8
            )
        except Exception as exc:
            payload['errors']['eastmoney_concept'] = str(exc)

        try:
            payload['eastmoney']['money_boards'] = self.fetch_eastmoney_clist(
                'm:90+t:2', fid='f62', limit=8
            )
        except Exception as exc:
            payload['errors']['eastmoney_money_boards'] = str(exc)

        try:
            payload['eastmoney']['hot_stocks'] = self.fetch_eastmoney_clist(
                'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', fid='f62', limit=12
            )
        except Exception as exc:
            payload['errors']['eastmoney_hot_stocks'] = str(exc)

        try:
            # 涨幅榜（含涨停股），按当日涨跌幅 f3 降序 — 用于"涨停/领涨热点"面板
            payload['eastmoney']['top_gainers'] = self.fetch_eastmoney_clist(
                'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', fid='f3', limit=12
            )
        except Exception as exc:
            payload['errors']['eastmoney_top_gainers'] = str(exc)

        self._cache['payload'] = payload
        self._cache['ts'] = now
        return payload
