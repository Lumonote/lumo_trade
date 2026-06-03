"""Homepage market-intelligence aggregation."""

from __future__ import annotations

import datetime
import re
import time
import urllib.parse
from html import unescape
from typing import Any

from webui.services.http_client import request_json, request_json_post, request_text


DEFAULT_TTL_SECONDS = 180

_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
)


def _tencent_symbol_from_secid(secid: str) -> str:
    """东财 secid（'SH601991' / 'SZ300502' / 'BJ8xxxxx'）→ 腾讯行情 symbol（小写）。"""
    market = secid[:2].lower()
    code = secid[2:].strip()
    return f"{market}{code}"


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


# 东方财富盘口异动（getAllStockChanges）的看涨类型：t 码 → 中文标签。
# i 字段为逗号分隔串，格式随类型而异（封板类 / 买卖盘类 / 速度类三种），
# 统一用 _parse_change_info 启发式提取价格与涨跌幅，避免逐类型硬解析出错。
_BULLISH_CHANGE_TYPES: dict[str, str] = {
    '8201': '火箭发射',
    '8202': '快速反弹',
    '8193': '大笔买入',
    '8207': '有大买盘',
    '4': '封涨停板',
}


def _parse_change_info(raw: Any) -> tuple[float | None, float | None]:
    """从异动 i 字段（逗号分隔）启发式解析 (价格, 涨跌幅%)。

    三种已知格式：封板类 [价,封单量,价,幅]、买卖盘类 [量,价,幅,额]、速度类 [幅,价,幅]。
    规律：涨跌幅是绝对值 < 0.5 的比例值，价格是首个落在 [0.5, 10000) 的数。
    """
    parts: list[float] = []
    for token in str(raw or '').split(','):
        value = _safe_float(token, None)
        if value is not None:
            parts.append(value)
    pct = next((round(v * 100, 2) for v in parts if abs(v) < 0.5), None)
    price = next((round(v, 2) for v in parts if 0.5 <= v < 10000), None)
    return price, pct


def _format_change_time(tm: Any) -> str:
    """异动时间 145619（HHMMSS int）→ '14:56'。"""
    try:
        n = int(tm)
    except (TypeError, ValueError):
        return ''
    return f"{n // 10000:02d}:{(n // 100) % 100:02d}"


def _format_news_time(value: Any) -> str:
    """东财发布时间 '2026-06-02 22:58:02' → 'MM-DD HH:MM'；非常规格式按原串截断。"""
    text = str(value or '').strip()
    match = re.match(r'\d{4}-(\d{2}-\d{2})[ T](\d{2}:\d{2})', text)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return text[:16]


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

    def fetch_eastmoney_news(self, limit: int = 15) -> list[dict[str, Any]]:
        """东方财富 7×24 全球财经快讯（akshare stock_info_global_em），首页「东财资讯」面板。

        与金十快讯并列的宏观资讯流。akshare 内部处理东财接口/系统代理，本机
        push2 clist 被掐时该接口仍可达；失败/被限时由 load() 捕获并降级为空面板。
        """
        import akshare as ak  # 延迟导入，避免拖慢模块加载
        df = ak.stock_info_global_em()
        if df is None or getattr(df, 'empty', True):
            return []
        items: list[dict[str, Any]] = []
        for _, row in df.head(limit).iterrows():
            title = _strip_markup(row.get('标题'))
            if not title:
                continue
            items.append({
                'title': _truncate_text(title, 80),
                'summary': _truncate_text(row.get('摘要'), 160),
                'time': _format_news_time(row.get('发布时间')),
                'url': str(row.get('链接') or '').strip(),
                'source': '东方财富',
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

    def fetch_eastmoney_changes(self, limit: int = 15) -> list[dict[str, Any]]:
        """东方财富盘口异动（push2ex getAllStockChanges），仅取看涨异动用于「实时异动」面板。

        返回按时间倒序的最新异动：name｜code｜异动类型｜时间｜价格｜涨跌幅。
        盘口异动仅交易时段有数据，盘后/休市 allstock 可能为空（由 load() 视为空面板）。
        """
        params = {
            'type': ','.join(_BULLISH_CHANGE_TYPES),
            'ut': '7eea3edcaed734bea9cbfc24409ed989',
            'pageindex': '0',
            'pagesize': str(max(limit * 3, 30)),
            'dpt': 'wzchanges',
        }
        url = 'https://push2ex.eastmoney.com/getAllStockChanges?' + urllib.parse.urlencode(params)
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
        rows = ((payload or {}).get('data') or {}).get('allstock') or []
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get('c') or '').strip()
            name = str(row.get('n') or '').strip()
            label = _BULLISH_CHANGE_TYPES.get(str(row.get('t')))
            if not code or not name or not label or code in seen:
                continue  # 同股多次异动只保留最近一次（rows 已按时间倒序）
            seen.add(code)
            price, change_pct = _parse_change_info(row.get('i'))
            items.append({
                'code': code,
                'name': name,
                'type': label,
                'time': _format_change_time(row.get('tm')),
                'price': price,
                'change_pct': change_pct,
                'source': 'eastmoney',
            })
            if len(items) >= limit:
                break
        return items

    def _tencent_quotes(self, secids: list[str]) -> dict[str, dict[str, Any]]:
        """腾讯行情批量报价（qt.gtimg.cn，本机可达，作为东财 push2 被掐时的回退源）。

        返回 {6位代码: {name, price, change_pct}}。腾讯返回 GBK 文本，'~' 分隔。
        """
        if not secids:
            return {}
        symbols = ','.join(_tencent_symbol_from_secid(s) for s in secids)
        text = request_text(
            'https://qt.gtimg.cn/q=' + symbols,
            headers={'User-Agent': _UA, 'Referer': 'https://gu.qq.com/'},
            timeout=4,
            encoding='gbk',
            errors='ignore',
            retries=2,
        )
        out: dict[str, dict[str, Any]] = {}
        for line in text.splitlines():
            if '~' not in line or '=' not in line:
                continue
            body = line.split('=', 1)[1].strip().rstrip(';').strip('"')
            fields = body.split('~')
            if len(fields) < 33:  # 停牌/无效代码时字段被截断
                continue
            code = (fields[2] or '').strip()
            if not code:
                continue
            out[code] = {
                'name': (fields[1] or '').strip(),
                'price': _safe_float(fields[3], None),
                'change_pct': round(_safe_float(fields[32], 0.0) or 0.0, 2),
            }
        return out

    def fetch_hot_rank(self, limit: int = 12) -> list[dict[str, Any]]:
        """东方财富实时人气榜（emappdata host，本机可达）+ 腾讯行情补涨跌幅。

        热点面板的回退源：当 push2.eastmoney 的 clist 在本机被掐时，改走
        emappdata 取人气排名（仅返回 secid），再用腾讯行情补 name/price/涨跌幅。
        两个 host 均独立于被掐的 push2.eastmoney，保证热点面板始终有数据。
        """
        payload = request_json_post(
            'https://emappdata.eastmoney.com/stockrank/getAllCurrentList',
            json_body={
                'appId': 'appId01',
                'globalId': '786e4c21-70dc-435a-93bb-38',
                'marketType': '',
                'pageNo': 1,
                'pageSize': max(limit, 12),
            },
            headers={
                'User-Agent': _UA,
                'Content-Type': 'application/json',
                'Origin': 'https://emrnweb.eastmoney.com',
            },
            timeout=5,
            retries=2,
        )
        rows = (payload or {}).get('data') or []
        secids = [str(r.get('sc') or '').strip() for r in rows if isinstance(r, dict) and r.get('sc')]
        secids = secids[:limit]
        if not secids:
            return []
        quotes = self._tencent_quotes(secids)
        items: list[dict[str, Any]] = []
        for secid in secids:
            code = secid[2:].strip()
            quote = quotes.get(code)
            if not quote:
                continue
            items.append({
                'code': code,
                'name': quote['name'] or code,
                'price': quote['price'],
                'change_pct': quote['change_pct'],
                'main_net_inflow': None,  # 腾讯基础行情不含主力净流入
                'main_net_inflow_text': '—',
                'source': 'eastmoney_rank',
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
            'eastmoney_news': [],
            'eastmoney': {
                'industry_boards': [],
                'concept_boards': [],
                'money_boards': [],
                'hot_stocks': [],
                'top_gainers': [],
                'changes': [],
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
            payload['eastmoney_news'] = self.fetch_eastmoney_news(limit=15)
        except Exception as exc:
            payload['errors']['eastmoney_news'] = str(exc)

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
            # 优先 clist（含主力净流入排序）。
            hot = self.fetch_eastmoney_clist(
                'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', fid='f62', limit=12
            )
        except Exception:
            hot = []
        if not hot:
            # clist 在本机/网络被掐时回退人气榜+腾讯行情，保证热点面板不空。
            try:
                hot = self.fetch_hot_rank(limit=12)
            except Exception as exc:
                payload['errors']['eastmoney_hot_stocks'] = str(exc)
        payload['eastmoney']['hot_stocks'] = hot

        try:
            # 涨幅榜（含涨停股），按当日涨跌幅 f3 降序 — 用于"涨停/领涨热点"面板
            payload['eastmoney']['top_gainers'] = self.fetch_eastmoney_clist(
                'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', fid='f3', limit=12
            )
        except Exception as exc:
            payload['errors']['eastmoney_top_gainers'] = str(exc)

        try:
            # 实时异动（盘口异动，仅看涨）— 「实时异动」面板专用，区别于涨幅榜
            payload['eastmoney']['changes'] = self.fetch_eastmoney_changes(limit=15)
        except Exception as exc:
            payload['errors']['eastmoney_changes'] = str(exc)

        self._cache['payload'] = payload
        self._cache['ts'] = now
        return payload
