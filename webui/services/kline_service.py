"""Stock K-line data loading for WebUI routes."""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from webui.services.analysis_jobs import normalize_stock_codes, safe_int
from webui.services.http_client import request_json


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, '', '—', 'N/A'):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class StockKlineService:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    @staticmethod
    def sina_symbol_for_code(stock_code: str) -> str:
        code = str(stock_code or '').strip().zfill(6)
        if code.startswith(('43', '83', '87', '92')):
            return f'bj{code}'
        if code.startswith(('6', '9')):
            return f'sh{code}'
        return f'sz{code}'

    @staticmethod
    def period_to_sina_scale(period: str) -> str:
        period_map = {
            '5m': '5',
            '5': '5',
            '15m': '15',
            '15': '15',
            '30m': '30',
            '30': '30',
            '60m': '60',
            '1h': '60',
            'daily': '240',
            '1d': '240',
            'day': '240',
        }
        return period_map.get(str(period or 'daily'), '240')

    def local_kline_candidates(self, stock_code: str, period: str) -> list[Path]:
        if not self.data_dir.exists():
            return []
        prefixes = []
        if str(period) in ('5m', '5'):
            prefixes.extend(['5m', '5min'])
        prefixes.extend(['1d', 'daily', 'day'])
        patterns = [f'{prefix}_{stock_code}.*' for prefix in prefixes]
        candidates = []
        for pattern in patterns:
            candidates.extend(self.data_dir.glob(pattern))
        return [path for path in candidates if path.suffix.lower() in ('.csv', '.feather')]

    @staticmethod
    def frame_to_kline_records(df: Any, limit: int) -> list[dict[str, Any]]:
        import pandas as pd

        if df is None or df.empty:
            return []

        work = df.copy()
        timestamp_col = next(
            (col for col in ['timestamps', 'timestamp', 'date', 'datetime', 'time'] if col in work.columns),
            None,
        )
        if timestamp_col:
            work[timestamp_col] = pd.to_datetime(work[timestamp_col], errors='coerce')
            work = work.dropna(subset=[timestamp_col])
            work = work.sort_values(timestamp_col)
        else:
            work['_timestamp'] = pd.RangeIndex(start=1, stop=len(work) + 1)
            timestamp_col = '_timestamp'

        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            if col in work.columns:
                work[col] = pd.to_numeric(work[col], errors='coerce')
        work = work.dropna(subset=[col for col in ['open', 'high', 'low', 'close'] if col in work.columns])

        records = []
        for _, row in work.tail(limit).iterrows():
            timestamp = row[timestamp_col]
            if isinstance(timestamp, pd.Timestamp):
                date_text = timestamp.strftime('%Y-%m-%d')
            else:
                date_text = str(timestamp)
            open_price = float(row['open'])
            close_price = float(row['close'])
            pct_chg = ((close_price - open_price) / open_price * 100) if open_price else 0.0
            records.append({
                'date': date_text,
                'open': open_price,
                'close': close_price,
                'high': float(row['high']),
                'low': float(row['low']),
                'volume': float(row['volume']) if 'volume' in row and pd.notna(row.get('volume')) else 0.0,
                'amount': float(row['amount']) if 'amount' in row and pd.notna(row.get('amount')) else 0.0,
                'pct_chg': round(pct_chg, 2),
            })
        return records

    def load_local_kline(self, stock_code: str, period: str, limit: int) -> tuple[list[dict[str, Any]], str | None]:
        import pandas as pd

        for path in self.local_kline_candidates(stock_code, period):
            try:
                if path.suffix.lower() == '.csv':
                    df = pd.read_csv(path)
                else:
                    df = pd.read_feather(path)
                records = self.frame_to_kline_records(df, limit)
                if records:
                    return records, path.name
            except Exception as exc:
                print(f"Failed to load local kline {path}: {exc}")
        return [], None

    @staticmethod
    def parse_sina_klines(klines: list[Any]) -> list[dict[str, Any]]:
        records = []
        prev_close = None
        for item in klines or []:
            if not isinstance(item, dict):
                continue
            open_price = _safe_float(item.get('open'))
            close_price = _safe_float(item.get('close'))
            if open_price <= 0 or close_price <= 0:
                continue
            high_price = _safe_float(item.get('high'), max(open_price, close_price))
            low_price = _safe_float(item.get('low'), min(open_price, close_price))
            pct_chg = 0.0
            if prev_close and prev_close > 0:
                pct_chg = (close_price / prev_close - 1) * 100
            records.append({
                'date': str(item.get('day') or item.get('date') or ''),
                'open': open_price,
                'close': close_price,
                'high': high_price,
                'low': low_price,
                'volume': _safe_float(item.get('volume')),
                'amount': _safe_float(item.get('amount')),
                'pct_chg': round(pct_chg, 2),
            })
            prev_close = close_price
        return records

    def fetch_sina_kline(self, stock_code: str, period: str, limit: int) -> tuple[list[dict[str, Any]], str]:
        params = {
            'symbol': self.sina_symbol_for_code(stock_code),
            'scale': self.period_to_sina_scale(period),
            'ma': 'no',
            'datalen': str(limit),
        }
        url = (
            'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
            'CN_MarketData.getKLineData?' + urllib.parse.urlencode(params)
        )
        payload = request_json(
            url,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
                ),
                'Accept': 'application/json,text/plain,*/*',
                'Referer': 'https://finance.sina.com.cn/',
            },
            timeout=8,
        )
        records = self.parse_sina_klines(payload if isinstance(payload, list) else [])
        return records, ''

    def get_payload(
        self,
        stock_code: str,
        period: str = 'daily',
        limit: int | str = 120,
    ) -> tuple[dict[str, Any] | None, str | None]:
        codes = normalize_stock_codes([stock_code])
        if not codes:
            return None, 'Invalid stock code'
        code = codes[0]
        normalized_limit = safe_int(limit, 120, minimum=30, maximum=500) or 120
        normalized_period = str(period or 'daily')

        sina_records: list[dict[str, Any]] = []
        sina_error: str | None = None
        try:
            sina_records, _sina_name = self.fetch_sina_kline(code, normalized_period, normalized_limit)
        except Exception as exc:
            sina_error = str(exc)

        if sina_records:
            return {
                'code': code,
                'name': '',
                'period': normalized_period,
                'source': 'sina',
                'available': True,
                'records': sina_records,
            }, None

        local_records, local_source = self.load_local_kline(code, normalized_period, normalized_limit)
        if local_records:
            return {
                'code': code,
                'name': '',
                'period': normalized_period,
                'source': f'local:{local_source}',
                'available': True,
                'records': local_records,
                'message': 'Sina 行情接口暂不可用，已使用本地缓存数据（可能不是最新）。' if sina_error else None,
            }, None

        if sina_error:
            return {
                'code': code,
                'name': '',
                'period': normalized_period,
                'source': 'sina',
                'available': False,
                'records': [],
                'message': '暂无K线数据：本地没有该股票数据，Sina 行情接口暂不可用。',
                'detail': sina_error,
            }, None

        return {
            'code': code,
            'name': '',
            'period': normalized_period,
            'source': 'sina',
            'available': False,
            'records': [],
            'message': '暂无K线数据：本地没有该股票数据，Sina 行情接口未返回记录。',
        }, None
