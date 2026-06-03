"""Request parsing for WebUI analysis background jobs."""

from __future__ import annotations

import re
from typing import Any


def safe_int(value: Any, default: int | None, minimum: int | None = None, maximum: int | None = None) -> int | None:
    try:
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


def normalize_stock_codes(raw_codes: Any) -> list[str]:
    if raw_codes is None:
        return []
    if isinstance(raw_codes, list):
        candidates = raw_codes
    else:
        candidates = re.split(r'[\s,，;；|/]+', str(raw_codes))

    normalized = []
    seen = set()
    for item in candidates:
        token = str(item or '').strip().upper()
        if not token:
            continue
        if token.startswith(('SH', 'SZ', 'BJ')) and len(token) >= 8:
            token = token[2:]
        if token.endswith(('.SH', '.SZ', '.BJ')):
            token = token.split('.')[0]
        match = re.search(r'\d{6}', token)
        if not match:
            continue
        code = match.group(0)
        if code not in seen:
            normalized.append(code)
            seen.add(code)
    return normalized


class AnalysisJobRequestParser:
    allowed_opportunity_sources = {'multi', 'heat', 'moneyflow_dc'}
    allowed_batch_types = {'comprehensive', 'fundamental', 'sentiment'}

    def opportunity_params(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        source = str(payload.get('source', 'multi')).strip()
        if source not in self.allowed_opportunity_sources:
            return None, 'Unsupported source, use multi / heat / moneyflow_dc'

        return {
            'limit': safe_int(payload.get('limit'), 100, minimum=5, maximum=500),
            'workers': safe_int(payload.get('workers'), 10, minimum=1, maximum=32),
            'source': source,
            'stock_codes': normalize_stock_codes(payload.get('stock_codes')),
        }, None

    def batch_params(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        stock_codes = normalize_stock_codes(payload.get('stock_codes'))
        if not stock_codes:
            return None, 'Please provide at least one 6-digit stock code'

        requested_types = payload.get('data_types') or ['comprehensive']
        if isinstance(requested_types, str):
            requested_types = re.split(r'[\s,，;；]+', requested_types)
        data_types = [item for item in requested_types if item in self.allowed_batch_types]
        if not data_types:
            data_types = ['comprehensive']

        filter_strategy = str(payload.get('filter_strategy', 'balanced')).strip() or 'balanced'
        return {
            'stock_codes': stock_codes[:100],
            'data_types': data_types,
            'filter_strategy': filter_strategy,
            'max_concurrent': safe_int(payload.get('max_concurrent'), 5, minimum=1, maximum=20),
            'collection_timeout': safe_int(payload.get('collection_timeout'), 30, minimum=5, maximum=180),
            'scoring_timeout': safe_int(payload.get('scoring_timeout'), 15, minimum=5, maximum=120),
            'skip_scoring': bool(payload.get('skip_scoring', False)),
        }, None
