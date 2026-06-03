"""Pattern-search API logic shared by web framework routes."""

from __future__ import annotations

import datetime
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from analysis.pattern_store import PatternStore


DEFAULT_TARGET_LENGTH = 30

# 实时报价叠加到命中结果的最大只数（单次批量报价即可覆盖，避免对行情源过量请求）。
_REALTIME_OVERLAY_CAP = 50

# 合法 A 股 6 位代码：沪 6 / 深 0 / 创业 3 / 科创 688 / 北交所 8·4·92(920xxx 新代码段)。用于
# 「指纹库 + 全市场索引都未命中，但用户输入的就是合法代码」时直接放行——导航到分析页后 OHLCV 会按需补偿。
_VALID_CODE_RE = re.compile(r"^(?:6[0-9]{5}|[03][0-9]{5}|[84][0-9]{5}|92[0-9]{4})$")
_UNIVERSE_TTL_SECONDS = 86400  # 全 A 代码/名称索引按天刷新即可


def _market_label(code: str) -> str:
    """按代码段给出市场标签（与 list_all_stocks 的 market 文案口径一致的兜底）。"""
    if code.startswith("6"):
        return "沪市"
    if code.startswith(("0", "3")):
        return "深市"
    if code.startswith(("8", "4", "92")):
        return "北交所"
    return ""


def _safe_int(value: Any, default: int | None, minimum: int | None = None, maximum: int | None = None) -> int | None:
    try:
        if value in (None, ''):
            parsed = default
        else:
            parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed is None:
        return None
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _safe_float(value: Any, default: float | None, minimum: float | None = None, maximum: float | None = None) -> float | None:
    try:
        parsed = float(value) if value not in (None, '') else default
    except (TypeError, ValueError):
        parsed = default
    if parsed is None:
        return None
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


class PatternSearchService:
    def __init__(
        self,
        db_path: Path,
        universe_provider: Optional[Callable[[], list]] = None,
        quote_provider: Optional[Callable[[list], dict]] = None,
    ):
        self.db_path = Path(db_path)
        self._store: PatternStore | None = None
        self._lock = threading.RLock()
        # 全 A 股代码/名称索引（指纹库未覆盖时的兜底搜索源）。默认惰性调用
        # scripts.build_pattern_fingerprints.list_all_stocks；可注入以便测试离线。
        self._universe_provider = universe_provider
        self._universe_cache: list | None = None
        self._universe_fetched_at = 0.0
        self._universe_lock = threading.RLock()
        # 实时报价源（如 WatchlistService.quotes）。形态指纹是隔日快照，命中结果叠加当日
        # 实时价/涨跌幅，帮助判断该股今日是否已偏离形态。失败静默降级，绝不阻断检索。
        self._quote_provider = quote_provider

    def get_store(self) -> PatternStore:
        with self._lock:
            if self._store is None:
                self._store = PatternStore(self.db_path)
                self._store.init_schema()
            return self._store

    def status(self) -> dict[str, Any]:
        status = self.get_store().current_status()

        staleness_days = None
        warning = None
        if status.get('last_snapshot_date'):
            try:
                snapshot_date = datetime.date.fromisoformat(status['last_snapshot_date'])
                staleness_days = (datetime.date.today() - snapshot_date).days
                if staleness_days >= 3:
                    warning = f"指纹数据已陈旧 {staleness_days} 天，建议刷新"
            except ValueError:
                staleness_days = None
        if not status.get('available'):
            warning = warning or "指纹库尚未生成，请先点击刷新"

        return {
            'available': status.get('available', False),
            'snapshot_date': status.get('last_snapshot_date'),
            'total_stocks': status.get('total_stocks', 0),
            'updated_at': status.get('last_finished_at'),
            'last_status': status.get('last_status'),
            'staleness_days': staleness_days,
            'warning': warning,
        }

    def match(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        curve = payload.get('curve')
        if not isinstance(curve, list) or not (5 <= len(curve) <= DEFAULT_TARGET_LENGTH):
            return {'error': f'curve 必须为长度 5-{DEFAULT_TARGET_LENGTH} 的数组'}, 400
        try:
            curve = [float(x) for x in curve]
        except (TypeError, ValueError):
            return {'error': 'curve 元素必须为数字'}, 400

        top_n = _safe_int(payload.get('top_n'), default=30, minimum=1, maximum=200)
        window_days = _safe_int(
            payload.get('window_days'),
            default=DEFAULT_TARGET_LENGTH,
            minimum=5,
            maximum=DEFAULT_TARGET_LENGTH,
        )
        query_offset_days = _safe_int(
            payload.get('query_offset_days'),
            default=0,
            minimum=0,
            maximum=5,
        )

        from analysis.pattern_matcher import comparison_window, search_similar

        query_curve = comparison_window(
            curve,
            max_days=window_days or DEFAULT_TARGET_LENGTH,
            offset_days=query_offset_days or 0,
        )
        if not query_curve:
            return {'error': '当前相似天数/回推设置下曲线数据不足'}, 400

        filters = payload.get('filters') or {}
        markets = filters.get('market') or None
        if markets and not isinstance(markets, list):
            markets = [markets]
        industry = filters.get('industry') or None
        exclude_st = bool(filters.get('exclude_st', True))

        store = self.get_store()
        started = time.time()
        results = search_similar(
            store,
            curve,
            top_n=top_n or 30,
            markets=markets,
            industry=industry,
            exclude_st=exclude_st,
            window_days=window_days or DEFAULT_TARGET_LENGTH,
            query_offset_days=query_offset_days or 0,
        )
        elapsed_ms = int((time.time() - started) * 1000)

        status = store.current_status()
        quoted, quote_updated_at = self._overlay_realtime(results)
        return {
            'matches': results,
            'query_curve': query_curve,
            'window_days': len(query_curve),
            'requested_window_days': window_days,
            'query_offset_days': query_offset_days,
            'snapshot_date': status.get('last_snapshot_date'),
            'quoted': quoted,
            'quote_updated_at': quote_updated_at,
            'compute_ms': elapsed_ms,
            'count': len(results),
        }, 200

    def set_quote_provider(self, provider: Optional[Callable[[list], dict]]) -> None:
        """注入/更换实时报价源（如 WatchlistService.quotes）。与自选行情共用同一行情口径。"""
        self._quote_provider = provider

    def _overlay_realtime(self, results: list) -> tuple[bool, Optional[str]]:
        """给命中结果就地叠加当日实时价/涨跌幅（指纹是隔日快照，实时价帮助判断是否已变样）。

        返回 (quoted, quote_updated_at)。报价源缺失/异常/全部无效时静默降级（quoted=False），
        绝不影响形态结果本身；最多对前 ``_REALTIME_OVERLAY_CAP`` 只取价（单次批量请求即可覆盖）。
        """
        provider = self._quote_provider
        if not provider or not results:
            return False, None
        codes: list[str] = []
        seen: set[str] = set()
        for row in results[:_REALTIME_OVERLAY_CAP]:
            code = str(row.get('stock_code') or '').strip()
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
        if not codes:
            return False, None
        try:
            quote_map = provider(codes) or {}
        except Exception:  # noqa: BLE001 — 行情源不可用时降级，不应阻断形态检索
            return False, None
        if not quote_map:
            return False, None
        matched = 0
        for row in results:
            quote = quote_map.get(str(row.get('stock_code') or '').strip())
            if not quote:
                continue
            price = quote.get('price')
            if price in (None, 0, 0.0):  # 0 价 = 停牌/无效，按未取到处理
                continue
            row['realtime_price'] = price
            row['realtime_change_pct'] = quote.get('change_pct')
            row['realtime'] = True
            matched += 1
        if not matched:
            return False, None
        return True, datetime.datetime.now().isoformat(timespec='seconds')

    def search_stocks(self, query: str, limit: Any = 10) -> dict[str, Any]:
        query = str(query or '').strip()
        normalized_limit = _safe_int(limit, default=10, minimum=1, maximum=30)
        if not query:
            return {'stocks': [], 'count': 0}

        cap = normalized_limit or 10
        stocks = self.get_store().search_stocks(query, limit=cap)
        if not stocks:
            # 指纹库未覆盖（库未建 / 该股缺指纹）→ 兜底搜全 A 股索引，消除「没有匹配股票」假阴性。
            stocks = self._search_universe(query, cap)
        return {
            'stocks': stocks,
            'count': len(stocks),
            'query': query,
        }

    def _load_universe(self) -> list:
        """全 A 股代码/名称索引，进程内按天缓存；失败回退已有缓存或空（不钉死失败）。"""
        now = time.time()
        with self._universe_lock:
            if self._universe_cache is not None and (now - self._universe_fetched_at) < _UNIVERSE_TTL_SECONDS:
                return self._universe_cache
        try:
            provider = self._universe_provider
            if provider is None:
                from scripts.build_pattern_fingerprints import list_all_stocks
                provider = list_all_stocks
            universe = provider() or []
        except Exception:  # noqa: BLE001 — 兜底数据源尽力而为
            universe = []
        with self._universe_lock:
            if universe:  # 仅成功时更新时间戳，避免一次失败把空结果钉住一天
                self._universe_cache = universe
                self._universe_fetched_at = now
            elif self._universe_cache is None:
                self._universe_cache = []
            return self._universe_cache

    @staticmethod
    def _normalize_code_query(query: str) -> str:
        """剥离 SH/SZ/BJ 前缀与 .SH/.SZ/.BJ 后缀，取纯代码部分用于匹配。"""
        code_kw = str(query or '').strip().upper()
        if code_kw.startswith(("SH", "SZ", "BJ")) and len(code_kw) >= 8:
            code_kw = code_kw[2:]
        if "." in code_kw:
            code_kw = code_kw.split(".")[0]
        return code_kw

    def _search_universe(self, query: str, limit: int) -> list[dict[str, Any]]:
        """指纹库未命中后的兜底：在全 A 索引里按代码/名称匹配；都没有但输入是合法代码则直接放行。"""
        keyword = query.strip()
        code_kw = self._normalize_code_query(keyword)
        universe = self._load_universe()
        ranked: list[tuple[int, dict]] = []
        for s in universe:
            code = str(s.get("stock_code") or "")
            name = str(s.get("stock_name") or "")
            if code_kw and code_kw in code:
                ranked.append((0 if code.startswith(code_kw) else 1, s))
            elif keyword and keyword in name:
                ranked.append((2 if name.startswith(keyword) else 3, s))
        ranked.sort(key=lambda t: t[0])
        results = [self._universe_row(s) for _, s in ranked[:limit]]
        if results:
            return results
        # 全 A 索引也未命中（含离线取不到索引）：合法 6 位代码直接放行，避免对真实代码假阴性。
        if _VALID_CODE_RE.match(code_kw):
            return [self._universe_row({"stock_code": code_kw, "stock_name": "",
                                        "market": _market_label(code_kw), "industry": ""})]
        return []

    @staticmethod
    def _universe_row(s: dict[str, Any]) -> dict[str, Any]:
        """把全 A 索引条目归一成与指纹结果同形的字典（无指纹字段置默认值并标记）。"""
        return {
            "stock_code": str(s.get("stock_code") or ""),
            "stock_name": str(s.get("stock_name") or ""),
            "market": str(s.get("market") or ""),
            "industry": str(s.get("industry") or ""),
            "mean_slope": 0.0,
            "latest_close": 0.0,
            "latest_change_pct": 0.0,
            "snapshot_date": None,
            "in_fingerprint": False,
        }

    def stock_curve(self, stock_code: str) -> tuple[dict[str, Any], int]:
        code = str(stock_code or '').strip()
        if not code:
            return {'error': '股票代码不能为空'}, 400

        fp = self.get_store().load_fingerprint(code)
        if fp is None:
            return {
                'available': False,
                'message': '该股不在指纹库中（可能停牌、未上市或库尚未刷新）',
            }, 404

        return {
            'available': True,
            'stock_code': fp.stock_code,
            'stock_name': fp.stock_name,
            'market': fp.market,
            'industry': fp.industry,
            'normalized_curve': fp.normalized_curve,
            'mean_slope': fp.mean_slope,
            'latest_close': fp.latest_close,
            'latest_change_pct': fp.latest_change_pct,
            'snapshot_date': fp.snapshot_date.isoformat(),
        }, 200

    def refresh_params(self, payload: dict[str, Any]) -> dict[str, Any]:
        limit_raw = payload.get('limit')
        data_source = str(payload.get('data_source') or payload.get('source') or 'auto').strip().lower()
        if data_source not in {'auto', 'tushare', 'sina'}:
            data_source = 'auto'
        return {
            'limit': _safe_int(limit_raw, default=None, minimum=1, maximum=10000) if limit_raw else None,
            'workers': _safe_int(payload.get('workers'), default=16, minimum=1, maximum=64),
            'data_source': data_source,
        }

    def refresh_fingerprints(self, params: dict[str, Any], progress_callback=None) -> dict[str, Any]:
        from scripts.build_pattern_fingerprints import build_all

        return build_all(
            self.get_store(),
            limit=params.get('limit'),
            max_workers=params.get('workers', 16),
            data_source=params.get('data_source', 'auto'),
            progress_callback=progress_callback,
        )

    # ------------------------------------------------------------------
    # 同类图形回测（联网严谨回测）
    # ------------------------------------------------------------------

    def backtest_params(self, payload: dict[str, Any]) -> tuple[dict[str, Any], Optional[str]]:
        """同步校验回测请求并归一化参数；返回 (params, error)。error 非空即 400。"""
        curve = payload.get('curve')
        if not isinstance(curve, list) or not (5 <= len(curve) <= DEFAULT_TARGET_LENGTH):
            return {}, f'curve 必须为长度 5-{DEFAULT_TARGET_LENGTH} 的数组'
        try:
            curve = [float(x) for x in curve]
        except (TypeError, ValueError):
            return {}, 'curve 元素必须为数字'

        raw_codes = payload.get('stock_codes')
        codes: list[str] = []
        if isinstance(raw_codes, list):
            seen: set[str] = set()
            for c in raw_codes:
                code = self._normalize_code_query(str(c or ''))
                if code.isdigit():
                    code = code.zfill(6)
                if _VALID_CODE_RE.match(code) and code not in seen:
                    seen.add(code)
                    codes.append(code)

        filters = payload.get('filters') if isinstance(payload.get('filters'), dict) else {}
        params = {
            'curve': curve,
            'stock_codes': codes,
            'top_n': _safe_int(payload.get('top_n'), default=20, minimum=1, maximum=50),
            'window_days': _safe_int(
                payload.get('window_days'), default=DEFAULT_TARGET_LENGTH, minimum=5, maximum=DEFAULT_TARGET_LENGTH,
            ),
            'query_offset_days': _safe_int(payload.get('query_offset_days'), default=0, minimum=0, maximum=5),
            'history_days': _safe_int(payload.get('history_days'), default=250, minimum=60, maximum=500),
            'similarity_threshold': _safe_float(
                payload.get('similarity_threshold'), default=0.85, minimum=0.5, maximum=0.99,
            ),
            'filters': filters,
        }
        return params, None

    @staticmethod
    def _sina_symbol(code: str) -> str:
        """6 位代码 → Sina symbol（sh/sz/bj 前缀），优先复用构建脚本里的实现。"""
        try:
            from scripts.build_pattern_fingerprints import sina_symbol_from_code
            return sina_symbol_from_code(code)
        except Exception:  # noqa: BLE001 — 脚本不可用时按代码段兜底
            if code.startswith('6'):
                return f'sh{code}'
            if code.startswith(('0', '3')):
                return f'sz{code}'
            if code.startswith(('8', '4', '92')):
                return f'bj{code}'
            return f'sh{code}'

    def backtest(self, params: dict[str, Any], progress_callback=None, fetch_klines=None) -> dict[str, Any]:
        """对候选股票联网回测查询形态。``fetch_klines`` 可注入以便离线测试。"""
        from analysis.pattern_backtest import DEFAULT_HORIZONS, backtest_patterns
        from analysis.pattern_matcher import comparison_window, search_similar

        curve = params.get('curve')
        if not isinstance(curve, list) or len(curve) < 2:
            return {'ok': False, 'error': 'curve 数据不足'}

        window_days = params.get('window_days') or DEFAULT_TARGET_LENGTH
        query_offset_days = params.get('query_offset_days') or 0
        query_curve = comparison_window(curve, max_days=window_days, offset_days=query_offset_days)
        if not query_curve or len(query_curve) < 2:
            return {'ok': False, 'error': '当前相似天数/回推设置下曲线数据不足'}

        top_n = params.get('top_n') or 20
        store = self.get_store()
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        codes = params.get('stock_codes') or []
        if codes:
            # 形态/以股搜股：直接回测前端给出的 Top-N 命中代码。
            for code in codes[:top_n]:
                if code in seen:
                    continue
                seen.add(code)
                fp = store.load_fingerprint(code)
                candidates.append({
                    'stock_code': code,
                    'stock_name': fp.stock_name if fp else '',
                    'symbol': self._sina_symbol(code),
                })
        else:
            # 个股分析/未带代码：先用形态检索出同类 Top-N，再回测它们。
            filters = params.get('filters') or {}
            markets = filters.get('market') or None
            if markets and not isinstance(markets, list):
                markets = [markets]
            results = search_similar(
                store,
                curve,
                top_n=top_n,
                markets=markets,
                industry=filters.get('industry') or None,
                exclude_st=bool(filters.get('exclude_st', True)),
                window_days=window_days,
                query_offset_days=query_offset_days,
            )
            for row in results:
                code = str(row.get('stock_code') or '')
                if not code or code in seen:
                    continue
                seen.add(code)
                candidates.append({
                    'stock_code': code,
                    'stock_name': row.get('stock_name') or '',
                    'symbol': self._sina_symbol(code),
                })

        if not candidates:
            return {'ok': False, 'error': '没有可回测的候选股票（请先检索出相似股票）'}

        if fetch_klines is None:
            from scripts.build_pattern_fingerprints import fetch_recent_klines
            fetch_klines = fetch_recent_klines

        result = backtest_patterns(
            query_curve=query_curve,
            candidates=candidates,
            fetch_klines=fetch_klines,
            window_days=window_days,
            horizons=DEFAULT_HORIZONS,
            similarity_threshold=params.get('similarity_threshold') or 0.85,
            history_days=params.get('history_days') or 250,
            progress_callback=progress_callback,
        )
        result['query_curve'] = query_curve
        result['requested_window_days'] = window_days
        return result

    # ------------------------------------------------------------------
    # 已保存形态（历史图形）
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_tags(raw: Any) -> Optional[list]:
        if isinstance(raw, str):
            raw = re.split(r'[,，\s]+', raw)
        if not isinstance(raw, list):
            return None
        tags: list[str] = []
        for item in raw:
            text = str(item or '').strip()
            if text and text not in tags:
                tags.append(text[:20])
            if len(tags) >= 12:
                break
        return tags or None

    @staticmethod
    def _normalize_query_params(raw: Any) -> Optional[dict]:
        """白名单化检索条件，使「保存的查询」可被一键重跑。"""
        if not isinstance(raw, dict):
            return None
        out: dict[str, Any] = {}
        top_n = _safe_int(raw.get('top_n'), default=None, minimum=1, maximum=200)
        if top_n is not None:
            out['top_n'] = top_n
        window_days = _safe_int(raw.get('window_days'), default=None, minimum=5, maximum=DEFAULT_TARGET_LENGTH)
        if window_days is not None:
            out['window_days'] = window_days
        offset = _safe_int(raw.get('query_offset_days'), default=None, minimum=0, maximum=5)
        if offset is not None:
            out['query_offset_days'] = offset
        history_days = _safe_int(raw.get('history_days'), default=None, minimum=60, maximum=500)
        if history_days is not None:
            out['history_days'] = history_days
        threshold = _safe_float(raw.get('similarity_threshold'), default=None, minimum=0.5, maximum=0.99)
        if threshold is not None:
            out['similarity_threshold'] = threshold
        filters = raw.get('filters')
        if isinstance(filters, dict):
            clean: dict[str, Any] = {}
            market = filters.get('market')
            if isinstance(market, list):
                market = [str(m).strip() for m in market if str(m).strip()]
                if market:
                    clean['market'] = market
            elif isinstance(market, str) and market.strip():
                clean['market'] = market.strip()
            industry = filters.get('industry')
            if isinstance(industry, str) and industry.strip():
                clean['industry'] = industry.strip()
            if 'exclude_st' in filters:
                clean['exclude_st'] = bool(filters.get('exclude_st'))
            if clean:
                out['filters'] = clean
        return out or None

    @staticmethod
    def _normalize_snapshot(raw: Any, cap: int = 60) -> Optional[list]:
        """裁剪命中结果快照：限量 + 仅留标量字段，避免落库膨胀。"""
        if not isinstance(raw, list):
            return None
        out: list[dict] = []
        for item in raw[:cap]:
            if not isinstance(item, dict):
                continue
            slim = {
                key: value for key, value in item.items()
                if value is None or isinstance(value, (str, int, float, bool))
            }
            if slim:
                out.append(slim)
        return out or None

    def save_pattern(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        curve = payload.get('normalized_curve') or payload.get('curve')
        if not isinstance(curve, list) or len(curve) < 2:
            return {'error': 'normalized_curve 必须为长度 ≥2 的数组'}, 400
        try:
            curve = [float(x) for x in curve]
        except (TypeError, ValueError):
            return {'error': 'normalized_curve 元素必须为数字'}, 400

        points = payload.get('points')
        if points is not None and not isinstance(points, list):
            points = None

        name = str(payload.get('name') or '').strip()
        if not name:
            name = f"形态 {datetime.datetime.now().strftime('%m-%d %H:%M')}"
        window_days = _safe_int(payload.get('window_days'), default=None, minimum=2, maximum=DEFAULT_TARGET_LENGTH)
        source = str(payload.get('source') or 'draw').strip() or 'draw'
        tags = self._normalize_tags(payload.get('tags'))
        query_params = self._normalize_query_params(payload.get('query_params'))
        result_snapshot = self._normalize_snapshot(payload.get('result_snapshot'))

        try:
            saved = self.get_store().save_pattern(
                name=name,
                normalized_curve=curve,
                points=points,
                window_days=window_days,
                source=source,
                tags=tags,
                query_params=query_params,
                result_snapshot=result_snapshot,
            )
        except ValueError as exc:
            return {'error': str(exc)}, 400
        return {'pattern': saved}, 200

    def list_saved_patterns(self, limit: Any = 50) -> dict[str, Any]:
        normalized_limit = _safe_int(limit, default=50, minimum=1, maximum=200)
        patterns = self.get_store().list_saved_patterns(limit=normalized_limit or 50)
        return {'patterns': patterns, 'count': len(patterns)}

    def get_saved_pattern(self, pattern_id: Any) -> tuple[dict[str, Any], int]:
        pid = _safe_int(pattern_id, default=None, minimum=1)
        if pid is None:
            return {'error': '无效的形态 id'}, 400
        pattern = self.get_store().get_saved_pattern(pid)
        if pattern is None:
            return {'error': '形态不存在或已删除'}, 404
        return {'pattern': pattern}, 200

    def delete_saved_pattern(self, pattern_id: Any) -> tuple[dict[str, Any], int]:
        pid = _safe_int(pattern_id, default=None, minimum=1)
        if pid is None:
            return {'error': '无效的形态 id'}, 400
        deleted = self.get_store().delete_saved_pattern(pid)
        if not deleted:
            return {'error': '形态不存在或已删除'}, 404
        return {'deleted': True, 'id': pid}, 200

