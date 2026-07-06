"""Homepage market-intelligence aggregation."""

from __future__ import annotations

import datetime
import json
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from typing import Any

from webui.services.http_client import request_json, request_json_post, request_text


DEFAULT_TTL_SECONDS = 180
# 主力净流入回退榜(Tushare moneyflow_dc)缓存时效：资金流向按日更新，半小时足够新鲜。
_MAIN_INFLOW_TTL = 1800

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
        # 主力净流入(元) by 6位代码：push2.eastmoney 的 f62 在本机被掐、热点榜回退人气榜时，
        # 用 Tushare moneyflow_dc(本机可达)补齐主力净流入，避免「主力 —」。整张当日榜一次取回、
        # 按 _MAIN_INFLOW_TTL 缓存（资金流向按日更新，无需频繁刷新）。
        self._inflow_cache: dict[str, Any] = {'ts': 0, 'map': None}
        # 行业映射（{6位代码: 行业名}）按天构建，供热点/异动行内「板块信息」。
        # 来源新浪行业分类（本机可达，独立于被掐的 push2.eastmoney）；后台线程构建不阻塞 load()。
        self._industry_map: dict[str, str] = {}
        self._industry_map_date: str = ''
        self._industry_building: bool = False
        self._industry_lock = threading.Lock()
        self._market_cloud_cache: dict[str, Any] = {'ts': 0, 'key': '', 'payload': None}
        self._maybe_refresh_industry_map()  # 进程启动即后台预热，首个 load 多半已就绪

    def _request_json(self, url: str, headers: dict[str, str] | None = None, timeout: int = 5,
                      trust_env: bool = True) -> Any:
        return request_json(url, headers=headers, timeout=timeout, retries=3, trust_env=trust_env)

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

    def fetch_futu_news(self, limit: int = 15) -> list[dict[str, Any]]:
        """富途 7×24 全球财经快讯（akshare stock_info_global_futu），首页「富途资讯」面板。

        与东财资讯并列的第二条宏观资讯流（雪球无资讯接口，akshare 的雪球接口全是
        股票榜，故改用富途）。返回字段与 fetch_eastmoney_news 一致（title/summary/
        time/url/source），前端复用同一资讯渲染。akshare 内部处理富途接口/系统代理；
        失败/被限时由 load() 捕获并降级为空面板。
        """
        import akshare as ak  # 延迟导入，避免拖慢模块加载
        df = ak.stock_info_global_futu()
        if df is None or getattr(df, 'empty', True):
            return []
        items: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            # 富途快讯常见「标题为空、正文承载标题」的情况，缺标题时用正文兜底，
            # 否则会把大量有效快讯（earlier 实测 50 行里多数无标题）整条丢掉。
            content = _strip_markup(row.get('内容'))
            title = _strip_markup(row.get('标题')) or content
            if not title:
                continue
            items.append({
                'title': _truncate_text(title, 80),
                'summary': _truncate_text(content, 160),
                'time': _format_news_time(row.get('发布时间')),
                'url': str(row.get('链接') or '').strip(),
                'source': '富途',
            })
            if len(items) >= limit:
                break
        return items

    def fetch_ths_flash(self, limit: int = 15) -> list[dict[str, Any]]:
        """同花顺 7×24 电报（akshare stock_info_global_ths），首页「同花顺电报」面板。

        替代原富途源：富途 akshare 接口(stock_info_global_futu)实为金十同一条电报，
        与「金十快讯」内容完全重复(实测 5/5 条标题、时间一致)；用户期望的财联社
        akshare 接口(stock_info_global_cls)本机实测 404 不可用，同花顺是最接近财联社
        电报的可用 A 股快讯源(带标题+链接)。字段与 fetch_eastmoney_news 一致
        (title/summary/time/url/source)。失败/被限时由 load() 捕获并降级为空面板。
        """
        import akshare as ak  # 延迟导入，避免拖慢模块加载
        df = ak.stock_info_global_ths()
        if df is None or getattr(df, 'empty', True):
            return []
        items: list[dict[str, Any]] = []
        for _, row in df.head(limit).iterrows():
            content = _strip_markup(row.get('内容'))
            title = _strip_markup(row.get('标题')) or content
            if not title:
                continue
            items.append({
                'title': _truncate_text(title, 80),
                'summary': _truncate_text(content, 160),
                'time': _format_news_time(row.get('发布时间')),
                'url': str(row.get('链接') or '').strip(),
                'source': '同花顺',
            })
        return items

    def fetch_sina_flash(self, limit: int = 12) -> list[dict[str, Any]]:
        """新浪 7×24 全球财经快讯（akshare stock_info_global_sina），首页「新浪快讯」面板。

        替代原「市场快讯」绑定的金十(与「金十快讯」重复)。新浪接口只含「时间/内容」，
        无独立标题与链接，故标题取正文。失败/被限时由 load() 捕获并降级为空面板。
        """
        import akshare as ak  # 延迟导入，避免拖慢模块加载
        df = ak.stock_info_global_sina()
        if df is None or getattr(df, 'empty', True):
            return []
        items: list[dict[str, Any]] = []
        for _, row in df.head(limit).iterrows():
            content = _strip_markup(row.get('内容'))
            if not content:
                continue
            items.append({
                'title': _truncate_text(content, 80),
                'summary': _truncate_text(content, 160),
                'time': _format_news_time(row.get('时间')),
                'url': '',
                'source': '新浪',
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
            'fields': 'f12,f14,f2,f3,f62,f100',
            '_': str(int(time.time() * 1000)),
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
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Referer': 'https://quote.eastmoney.com/',
            },
            timeout=4,
            trust_env=False,  # push2.eastmoney 是境内接口,系统代理(Clash)转发常被对端断连→直连
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
                'industry': str(row.get('f100') or '').strip(),  # 所属行业（push2 可达时直接带回）
                'source': 'eastmoney',
            })
        return items

    def _recent_tushare_trade_dates(self, pro: Any, max_back_days: int = 10) -> list[str]:
        """Resolve recent open trade dates for Tushare date-keyed snapshots."""
        today = datetime.datetime.now().date()
        start = today - datetime.timedelta(days=max(max_back_days * 2, 30))
        try:
            cal = pro.trade_cal(
                exchange='SSE',
                start_date=start.strftime('%Y%m%d'),
                end_date=today.strftime('%Y%m%d'),
                is_open='1',
                fields='cal_date,is_open',
            )
            if cal is not None and not getattr(cal, 'empty', True) and 'cal_date' in cal.columns:
                days = sorted(str(day) for day in cal['cal_date'].tolist() if str(day or '').strip())
                if days:
                    return days[-max_back_days:][::-1]
        except Exception:
            pass

        dates: list[str] = []
        candidate = today
        for _ in range(max_back_days * 2):
            if candidate.weekday() < 5:
                dates.append(candidate.strftime('%Y%m%d'))
                if len(dates) >= max_back_days:
                    break
            candidate -= datetime.timedelta(days=1)
        return dates

    @staticmethod
    def _stock_basic_by_ts_code(df: Any) -> dict[str, dict[str, Any]]:
        if df is None or getattr(df, 'empty', True) or 'ts_code' not in getattr(df, 'columns', []):
            return {}
        mapping: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            ts_code = str(row.get('ts_code') or '').strip()
            symbol = str(row.get('symbol') or ts_code.split('.')[0]).strip()
            # TuShare stock_basic is the A-share list, but defensive filters keep B-share
            # codes out of the cloud if a broader response ever slips through.
            if not ts_code or not symbol.isdigit() or len(symbol) != 6 or symbol.startswith(('200', '900')):
                continue
            mapping[ts_code] = {
                'code': symbol,
                'name': str(row.get('name') or '').strip(),
                'industry': str(row.get('industry') or '').strip(),
                'market': str(row.get('market') or '').strip(),
            }
        return mapping

    @staticmethod
    def _df_by_ts_code(df: Any) -> dict[str, Any]:
        if df is None or getattr(df, 'empty', True) or 'ts_code' not in getattr(df, 'columns', []):
            return {}
        return {
            str(row.get('ts_code') or '').strip(): row
            for _, row in df.iterrows()
            if str(row.get('ts_code') or '').strip()
        }

    def fetch_tushare_market_cloud_stocks(
        self,
        limit: int = 5000,
        trade_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Preferred full-market rows from Tushare Pro for the desktop market cloud.

        Unit contract for the frontend is yuan: daily.amount(千元) → 元,
        daily_basic.total_mv/circ_mv(万元) → 元, moneyflow_dc.net_amount(万元) → 元.
        Missing token/permission/network returns [] so callers can keep the older
        Eastmoney/Sina fallbacks visible.
        """
        limit = max(100, min(int(limit or 5000), 6000))
        try:
            import tushare as ts  # 延迟导入，避免拖慢模块加载
            from scripts.stock_filter_utils import load_tushare_token
        except Exception:
            return []

        try:
            token = load_tushare_token()
        except Exception:
            return []
        if not token or token == 'your_tushare_token_here':
            return []

        try:
            pro = ts.pro_api(token)
        except Exception:
            return []

        try:
            basic_df = pro.stock_basic(
                exchange='',
                list_status='L',
                fields='ts_code,symbol,name,industry,market,list_date',
            )
        except Exception:
            return []
        basics = self._stock_basic_by_ts_code(basic_df)
        if not basics:
            return []

        requested_trade_date = re.sub(r'\D', '', str(trade_date or '').strip())
        if requested_trade_date and len(requested_trade_date) != 8:
            return []
        quote_df = None
        resolved_trade_date = None
        for day in ([requested_trade_date] if requested_trade_date else self._recent_tushare_trade_dates(pro)):
            try:
                quote_df = pro.daily(
                    trade_date=day,
                    fields='ts_code,trade_date,close,pct_chg,amount',
                )
            except Exception:
                quote_df = None
            if quote_df is not None and not getattr(quote_df, 'empty', True):
                resolved_trade_date = day
                break
        if quote_df is None or getattr(quote_df, 'empty', True) or not resolved_trade_date:
            return []

        try:
            daily_basic_df = pro.daily_basic(
                trade_date=resolved_trade_date,
                fields='ts_code,trade_date,turnover_rate,total_mv,circ_mv',
            )
        except Exception:
            daily_basic_df = None

        flow_df = None
        fetch_flow = getattr(pro, 'moneyflow_dc', None) or getattr(pro, 'moneyflow_ths', None)
        if fetch_flow is not None:
            try:
                flow_df = fetch_flow(trade_date=resolved_trade_date)
            except Exception:
                flow_df = None

        quote_map = self._df_by_ts_code(quote_df)
        basic_map = self._df_by_ts_code(daily_basic_df)
        flow_map = self._df_by_ts_code(flow_df)
        flow_cols = ('net_amount', 'net_mf_amount', 'net_amount_main')

        items: list[dict[str, Any]] = []
        for ts_code, quote in quote_map.items():
            meta = basics.get(ts_code)
            if not meta:
                continue
            code = meta.get('code') or ts_code.split('.')[0]
            name = meta.get('name') or code
            amount = _safe_float(quote.get('amount'), None)
            amount_yuan = amount * 1000.0 if amount is not None else None
            metrics = basic_map.get(ts_code)
            total_mv = _safe_float(metrics.get('total_mv') if metrics is not None else None, None)
            circ_mv = _safe_float(metrics.get('circ_mv') if metrics is not None else None, None)
            market_cap = (total_mv if total_mv is not None else circ_mv)
            market_cap_yuan = market_cap * 10000.0 if market_cap is not None else None

            flow = None
            flow_row = flow_map.get(ts_code)
            if flow_row is not None:
                for col in flow_cols:
                    if col in getattr(flow_row, 'index', []):
                        value = _safe_float(flow_row.get(col), None)
                        if value is not None:
                            flow = value * 10000.0
                            break

            industry = meta.get('industry') or meta.get('market') or '其他'
            items.append({
                'code': code,
                'name': name,
                'price': _safe_float(quote.get('close'), None),
                'change_pct': round(_safe_float(quote.get('pct_chg'), 0.0) or 0.0, 2),
                'amount': amount_yuan,
                'turnover_rate': _safe_float(metrics.get('turnover_rate') if metrics is not None else None, None),
                'market_cap': market_cap_yuan,
                'main_net_inflow': flow,
                'main_net_inflow_text': _money_text(flow) if flow is not None else '—',
                'industry': industry,
                'trade_date': resolved_trade_date,
                'source': 'tushare_market_cloud',
            })

        items.sort(
            key=lambda row: (
                _safe_float(row.get('market_cap'), 0.0) or 0.0,
                _safe_float(row.get('amount'), 0.0) or 0.0,
            ),
            reverse=True,
        )
        return items[:limit]

    def fetch_eastmoney_market_cloud_stocks(
        self,
        limit: int = 5000,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Realtime full-market rows from Eastmoney for the desktop market cloud."""
        now = time.time() if now is None else now
        limit = max(100, min(int(limit or 5000), 6000))
        params = {
            'pn': '1',
            'pz': str(limit),
            'po': '1',
            'np': '1',
            'fltt': '2',
            'invt': '2',
            'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048',
            'fields': 'f12,f14,f2,f3,f6,f8,f20,f62,f100',
            '_': str(int(now * 1000)),
        }
        url = 'https://push2.eastmoney.com/api/qt/clist/get?' + urllib.parse.urlencode(params)
        try:
            payload = self._request_json(
                url,
                headers={
                    'User-Agent': _UA,
                    'Accept': 'application/json,text/plain,*/*',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache',
                    'Referer': 'https://quote.eastmoney.com/',
                },
                timeout=6,
                trust_env=False,
            )
            rows = ((payload or {}).get('data') or {}).get('diff') or []
        except Exception:
            rows = []

        items: list[dict[str, Any]] = []
        for row in rows:
            code = str(row.get('f12') or '').strip()
            name = str(row.get('f14') or '').strip()
            if not code or not name:
                continue
            flow = _safe_float(row.get('f62'), None)
            amount = _safe_float(row.get('f6'), None)
            market_cap = _safe_float(row.get('f20'), None)
            industry = str(row.get('f100') or '').strip() or self._industry_map.get(code, '')
            items.append({
                'code': code,
                'name': name,
                'price': _safe_float(row.get('f2'), None),
                'change_pct': round(_safe_float(row.get('f3'), 0.0) or 0.0, 2),
                'amount': amount,
                'turnover_rate': _safe_float(row.get('f8'), None),
                'market_cap': market_cap,
                'main_net_inflow': flow,
                'main_net_inflow_text': _money_text(flow) if flow is not None else '—',
                'industry': industry,
                'source': 'eastmoney_market_cloud',
            })
        return items

    def fetch_market_cloud_stocks(
        self,
        limit: int = 5000,
        force_refresh: bool = False,
        trade_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch a broad A-share list for the desktop market-cloud treemap."""
        now = time.time()
        requested_trade_date = re.sub(r'\D', '', str(trade_date or '').strip())
        if requested_trade_date and len(requested_trade_date) != 8:
            return []
        limit = max(100, min(int(limit or 5000), 6000))
        cache_key = f"{requested_trade_date or 'latest'}:{limit}"
        cached = self._market_cloud_cache.get('payload')
        if (
            not force_refresh
            and cached is not None
            and self._market_cloud_cache.get('key') == cache_key
            and now - self._market_cloud_cache.get('ts', 0) < self.ttl_seconds
        ):
            return cached

        if requested_trade_date:
            items = self.fetch_tushare_market_cloud_stocks(limit=limit, trade_date=requested_trade_date)
            self._market_cloud_cache = {'ts': now, 'key': cache_key, 'payload': items}
            return items

        if force_refresh:
            items = self.fetch_eastmoney_market_cloud_stocks(limit=limit, now=now)
            if not items:
                items = self.fetch_sina_market_cloud_stocks(limit=limit)
            if items:
                self._market_cloud_cache = {'ts': now, 'key': cache_key, 'payload': items}
                return items

        items = self.fetch_tushare_market_cloud_stocks(limit=limit)
        if items:
            self._market_cloud_cache = {'ts': now, 'key': cache_key, 'payload': items}
            return items

        items = self.fetch_eastmoney_market_cloud_stocks(limit=limit, now=now)
        if not items:
            items = self.fetch_sina_market_cloud_stocks(limit=limit)
        self._market_cloud_cache = {'ts': now, 'key': cache_key, 'payload': items}
        return items

    def fetch_sina_market_cloud_stocks(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Fallback full-market rows from Sina industry nodes."""
        limit = max(100, min(int(limit or 5000), 6000))
        headers = {'User-Agent': _UA, 'Referer': 'https://finance.sina.com.cn/'}
        index = request_text(
            'https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php',
            headers=headers, timeout=5, encoding='gbk', errors='ignore', retries=2,
        )
        nodes = [
            (node_id, name)
            for node_id, name in re.findall(r'"(new_\w+)"\s*:\s*"new_\w+,([^,]+),', index)
            if node_id != 'new_stock'
        ]
        if not nodes:
            return []

        def fetch_node(item: tuple[str, str]) -> list[dict[str, Any]]:
            node_id, industry = item
            url = (
                'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
                f'Market_Center.getHQNodeData?page=1&num=1000&sort=changepercent&asc=0'
                f'&node={node_id}&_s_r_a=page'
            )
            try:
                raw = request_text(url, headers=headers, timeout=5,
                                   encoding='gbk', errors='ignore', retries=1)
                rows = json.loads(raw) if raw.strip().startswith('[') else []
            except Exception:
                return []
            out: list[dict[str, Any]] = []
            for row in rows:
                code = str(row.get('code') or '').strip()
                name = str(row.get('name') or '').strip()
                if not code or not name:
                    continue
                amount = _safe_float(row.get('amount'), None)
                out.append({
                    'code': code,
                    'name': name,
                    'price': _safe_float(row.get('trade') or row.get('price'), None),
                    'change_pct': round(_safe_float(row.get('changepercent'), 0.0) or 0.0, 2),
                    'amount': amount,
                    'turnover_rate': _safe_float(row.get('turnoverratio'), None),
                    'market_cap': _safe_float(
                        row.get('mktcap') or row.get('totalmarketcap') or row.get('nmc'),
                        None,
                    ),
                    'main_net_inflow': None,
                    'main_net_inflow_text': '—',
                    'industry': industry,
                    'source': 'sina_market_cloud',
                })
            return out

        merged: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            for rows in executor.map(fetch_node, nodes):
                for row in rows:
                    merged.setdefault(row['code'], row)
                    if len(merged) >= limit:
                        break
                if len(merged) >= limit:
                    break
        return list(merged.values())[:limit]

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

    def _main_inflow_map(self) -> dict[str, float]:
        """主力净流入(元) by 6位代码，来自 Tushare moneyflow_dc(本机可达)。

        push2.eastmoney 的 f62 在本机被掐、热点/异动榜回退到人气榜(腾讯基础行情无主力净流入)时，
        用它补齐主力净流入。整张当日榜一次拉回(单次 API,约 5000 行)，按 _MAIN_INFLOW_TTL 缓存。
        失败(无 tushare / 无 token / 网络)时返回空 map，调用方据此显示「—」，best-effort 不抛错。
        """
        now = time.time()
        cache = self._inflow_cache
        if cache.get('map') is not None and now - cache.get('ts', 0) < _MAIN_INFLOW_TTL:
            return cache['map']

        mapping: dict[str, float] = {}
        try:
            import tushare as ts  # 延迟导入，避免拖慢模块加载
            from scripts.stock_filter_utils import load_tushare_token

            token = load_tushare_token()
            if token:
                pro = ts.pro_api(token)
                fetch = getattr(pro, 'moneyflow_dc', None) or getattr(pro, 'moneyflow_ths', None)
                df = None
                if fetch is not None:
                    base = datetime.datetime.now()
                    for i in range(7):  # 回溯最近交易日(跳过周末/节假日空表)
                        day = (base - datetime.timedelta(days=i)).strftime('%Y%m%d')
                        try:
                            df = fetch(trade_date=day)
                        except Exception:
                            df = None
                        if df is not None and not df.empty:
                            break
                if df is not None and not df.empty and 'ts_code' in df.columns:
                    # net_amount=主力净流入(万元)；不同接口字段名略有差异，按优先级取第一个可用列。
                    col = next((c for c in ('net_amount', 'net_mf_amount', 'net_amount_main')
                                if c in df.columns), None)
                    if col:
                        for _, row in df.iterrows():
                            ts_code = str(row.get('ts_code') or '')
                            code = ts_code.split('.')[0] if ts_code else ''
                            val = _safe_float(row.get(col), None)
                            if code and val is not None:
                                mapping[code] = val * 10000.0  # 万元 → 元，与 f62 口径一致
        except Exception:
            mapping = {}  # best-effort：补不到就维持「—」，热点面板照常显示价格

        self._inflow_cache = {'ts': now, 'map': mapping}
        return mapping

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
        inflow_map = self._main_inflow_map()  # 补主力净流入(本机 push2 被掐时的回退口径)
        items: list[dict[str, Any]] = []
        for secid in secids:
            code = secid[2:].strip()
            quote = quotes.get(code)
            if not quote:
                continue
            inflow = inflow_map.get(code)
            items.append({
                'code': code,
                'name': quote['name'] or code,
                'price': quote['price'],
                'change_pct': quote['change_pct'],
                'main_net_inflow': inflow,  # 来自 Tushare moneyflow_dc；补不到则 None
                'main_net_inflow_text': _money_text(inflow) if inflow is not None else '—',
                'source': 'eastmoney_rank',
            })
        return items

    def fetch_tencent_boards(self, board_type: str, limit: int = 8) -> list[dict[str, Any]]:
        """腾讯行业/概念板块排行（proxy.finance.qq.com，本机可达）。

        push2.eastmoney 的 clist 板块榜在本机/部分网络被掐时的回退源。
        board_type：'hy'=行业板块，'gn'=概念板块。返回 name｜涨跌幅｜主力净流入｜领涨股。

        注意：腾讯 getRank 仅 ``sort_type=price`` 返回数据（``zdf``/``zljlr`` 实测空），
        而 price 排序对板块是固定的申万行业序（食品饮料/电力设备/…），与「热点」无关，
        会让回退后的「热点板块」看起来永远是同一批旧数据。故这里多取一些再按当日涨跌幅
        客户端降序排序，取 Top ``limit``，使回退源也反映真实领涨板块。
        """
        fetch_count = max(limit, 50)  # 多取(行业约31/概念更多)以便客户端按涨幅重排
        url = (
            'https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank'
            f'?board_type={board_type}&sort_type=price&direct=down&offset=0&count={fetch_count}'
        )
        payload = self._request_json(
            url,
            headers={'User-Agent': _UA, 'Accept': 'application/json,text/plain,*/*',
                     'Referer': 'https://gu.qq.com/'},
            timeout=5,
            trust_env=False,  # 境内接口,直连绕过系统代理
        )
        rows = ((payload or {}).get('data') or {}).get('rank_list') or []
        items: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get('name') or '').strip()
            if not name:
                continue
            inflow_yuan = (_safe_float(row.get('zljlr'), 0.0) or 0.0) * 10000  # zljlr 单位为万元
            leader = row.get('lzg') if isinstance(row.get('lzg'), dict) else {}
            items.append({
                'code': str(row.get('code') or '').strip(),
                'name': name,
                'change_pct': round(_safe_float(row.get('zdf'), 0.0) or 0.0, 2),
                'main_net_inflow': inflow_yuan,
                'main_net_inflow_text': _money_text(inflow_yuan),
                'leader_name': str((leader or {}).get('name') or '').strip(),
                'leader_change_pct': round(_safe_float((leader or {}).get('zdf'), 0.0) or 0.0, 2),
                'source': 'tencent',
            })
        items.sort(key=lambda b: b['change_pct'], reverse=True)  # 真·领涨榜
        return items[:limit]

    @staticmethod
    def _today() -> str:
        return datetime.datetime.now().strftime('%Y-%m-%d')

    def _maybe_refresh_industry_map(self) -> None:
        """行业映射按天构建：首次/隔日在后台守护线程重建，绝不阻塞 load()。"""
        today = self._today()
        with self._industry_lock:
            if self._industry_map_date == today or self._industry_building:
                return
            self._industry_building = True
        threading.Thread(
            target=self._build_industry_map_worker, args=(today,), daemon=True
        ).start()

    def _build_industry_map_worker(self, today: str) -> None:
        try:
            new_map = self._build_industry_map()
            if new_map:
                with self._industry_lock:
                    self._industry_map = new_map
                    self._industry_map_date = today
        except Exception:
            pass  # 构建失败保留旧映射，下次 load 再触发重试
        finally:
            with self._industry_lock:
                self._industry_building = False

    def _build_industry_map(self) -> dict[str, str]:
        """从新浪行业分类构建 {6位代码: 行业名}，并行抓取约 49 个行业节点（~2s）。"""
        headers = {'User-Agent': _UA, 'Referer': 'https://finance.sina.com.cn/'}
        index = request_text(
            'https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php',
            headers=headers, timeout=5, encoding='gbk', errors='ignore', retries=2,
        )
        nodes = re.findall(r'"(new_\w+)"\s*:\s*"new_\w+,([^,]+),', index)
        if not nodes:
            return {}

        def fetch_node(item: tuple[str, str]) -> list[tuple[str, str]]:
            node_id, name = item
            url = (
                'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
                f'Market_Center.getHQNodeData?page=1&num=1000&sort=changepercent&asc=0'
                f'&node={node_id}&_s_r_a=page'
            )
            try:
                raw = request_text(url, headers=headers, timeout=5,
                                   encoding='gbk', errors='ignore', retries=1)
                arr = json.loads(raw) if raw.strip().startswith('[') else []
                return [(str(r.get('code') or '').strip(), name) for r in arr if r.get('code')]
            except Exception:
                return []

        industry_map: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            for pairs in executor.map(fetch_node, nodes):
                for code, name in pairs:
                    if code:
                        industry_map.setdefault(code, name)
        return industry_map

    def _attach_industry(self, rows: list[dict[str, Any]] | None) -> None:
        """就地给个股行补 industry：优先行业映射（标签统一），回退已带回的 f100。"""
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get('code') or '').strip()
            row['industry'] = self._industry_map.get(code) or str(row.get('industry') or '').strip()

    def load(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        cached = self._cache.get('payload')
        if not force_refresh and cached and now - self._cache.get('ts', 0) < self.ttl_seconds:
            return cached

        self._maybe_refresh_industry_map()  # 隔日则后台重建行业映射（非阻塞）

        payload = {
            'updated_at': _format_datetime(now),
            'jinshi': [],
            'ths_news': [],
            'sina_news': [],
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
            payload['ths_news'] = self.fetch_ths_flash(limit=15)
        except Exception as exc:
            payload['errors']['ths_news'] = str(exc)

        try:
            payload['sina_news'] = self.fetch_sina_flash(limit=12)
        except Exception as exc:
            payload['errors']['sina_news'] = str(exc)

        try:
            payload['eastmoney_news'] = self.fetch_eastmoney_news(limit=15)
        except Exception as exc:
            payload['errors']['eastmoney_news'] = str(exc)

        # 行业板块：clist 优先（含主力净流入），本机/被掐时回退腾讯板块榜，保证「热点板块」不空。
        try:
            industry_boards = self.fetch_eastmoney_clist('m:90+t:2', fid='f3', limit=8)
        except Exception:
            industry_boards = []
        if not industry_boards:
            try:
                industry_boards = self.fetch_tencent_boards('hy', limit=8)
            except Exception as exc:
                payload['errors']['eastmoney_industry'] = str(exc)
        payload['eastmoney']['industry_boards'] = industry_boards

        # 概念板块：同上，clist → 腾讯回退。
        try:
            concept_boards = self.fetch_eastmoney_clist('m:90+t:3', fid='f3', limit=10)
        except Exception:
            concept_boards = []
        if not concept_boards:
            try:
                concept_boards = self.fetch_tencent_boards('gn', limit=8)
            except Exception as exc:
                payload['errors']['eastmoney_concept'] = str(exc)
        payload['eastmoney']['concept_boards'] = concept_boards

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

        # 给热点/异动/涨幅个股就地补「板块信息」（行业映射就绪后生效，未就绪则留空）。
        self._attach_industry(payload['eastmoney']['hot_stocks'])
        self._attach_industry(payload['eastmoney']['changes'])
        self._attach_industry(payload['eastmoney']['top_gainers'])

        self._cache['payload'] = payload
        self._cache['ts'] = now
        return payload
