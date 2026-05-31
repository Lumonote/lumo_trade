"""Pattern-search API logic shared by web framework routes."""

from __future__ import annotations

import datetime
import threading
import time
from pathlib import Path
from typing import Any

from analysis.pattern_store import PatternStore


DEFAULT_TARGET_LENGTH = 30


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


class PatternSearchService:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._store: PatternStore | None = None
        self._lock = threading.RLock()

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
        return {
            'matches': results,
            'query_curve': query_curve,
            'window_days': len(query_curve),
            'requested_window_days': window_days,
            'query_offset_days': query_offset_days,
            'snapshot_date': status.get('last_snapshot_date'),
            'compute_ms': elapsed_ms,
            'count': len(results),
        }, 200

    def search_stocks(self, query: str, limit: Any = 10) -> dict[str, Any]:
        query = str(query or '').strip()
        normalized_limit = _safe_int(limit, default=10, minimum=1, maximum=30)
        if not query:
            return {'stocks': [], 'count': 0}

        stocks = self.get_store().search_stocks(query, limit=normalized_limit or 10)
        return {
            'stocks': stocks,
            'count': len(stocks),
            'query': query,
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
    # 已保存形态（历史图形）
    # ------------------------------------------------------------------

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

        try:
            saved = self.get_store().save_pattern(
                name=name,
                normalized_curve=curve,
                points=points,
                window_days=window_days,
                source=source,
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

