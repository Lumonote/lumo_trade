#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情绪数据全局缓存管理器（SQLite 后端 + 进程内 L1）.

L1：进程内 dict（_memory_cache），降低 SQLite round-trip。
L2：data_store.sentiment_repo 持久化到 data/kronos_data.sqlite。

公开 API 与旧版兼容：get/set/各类型快捷方法 / clear_all / clear_expired / get_cache_stats。
"""

import json
import time
from typing import Any, Dict, Optional
from threading import Lock
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SentimentCacheManager:
    """情绪数据全局缓存管理器 - 单例模式"""

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = {
            'overall_market': 600,
            'sector': 600,
            'capital_flow': 600,
            'dragon_tiger': 1800,
            'sector_list': 3600,
            'sector_constituents': 3600,
            'moneyflow_ind_dc': 3600,
            'moneyflow_mkt_dc': 3600,
            'sector_name': 3600,
        }
        from data_store.connection import db_path
        logger.info(f"✓ 情绪缓存管理器已初始化 (SQLite: {db_path()})")

    def _key(self, cache_type: str, identifier: str = '') -> str:
        return f"{cache_type}_{identifier}" if identifier else cache_type

    def get(self, cache_type: str, identifier: str = '') -> Optional[Dict]:
        from data_store import sentiment_repo

        key = self._key(cache_type, identifier)
        ttl = self.cache_ttl.get(cache_type, 600)
        now = time.time()

        cached = self._memory_cache.get(key)
        if cached and now - cached['timestamp'] < ttl:
            return cached['data']
        if cached:
            del self._memory_cache[key]

        row = sentiment_repo.get(cache_type, identifier)
        if row is None:
            return None
        data, epoch = row
        if now - epoch >= ttl:
            sentiment_repo.delete(cache_type, identifier)
            return None
        self._memory_cache[key] = {'timestamp': epoch, 'data': data}
        return data

    def set(self, cache_type: str, data: Dict, identifier: str = ''):
        from data_store import sentiment_repo

        key = self._key(cache_type, identifier)
        self._memory_cache[key] = {'timestamp': time.time(), 'data': data}
        try:
            sentiment_repo.set_(cache_type, data, identifier)
        except Exception as e:
            logger.warning(f"写入 SQLite 失败 {key}: {e}")

    def get_overall_market(self) -> Optional[Dict]:
        return self.get('overall_market')

    def set_overall_market(self, data: Dict):
        self.set('overall_market', data)

    def get_market_sentiment(self) -> Optional[Dict]:
        return self.get_overall_market()

    def set_market_sentiment(self, data: Dict):
        self.set_overall_market(data)

    def get_sector(self, sector_identifier: str) -> Optional[Dict]:
        return self.get('sector', sector_identifier)

    def set_sector(self, sector_identifier: str, data: Dict):
        self.set('sector', data, sector_identifier)

    def get_capital_flow(self, stock_code: str) -> Optional[Dict]:
        return self.get('capital_flow', stock_code)

    def set_capital_flow(self, stock_code: str, data: Dict):
        self.set('capital_flow', data, stock_code)

    def get_dragon_tiger(self, stock_code: str) -> Optional[Dict]:
        return self.get('dragon_tiger', stock_code)

    def set_dragon_tiger(self, stock_code: str, data: Dict):
        self.set('dragon_tiger', data, stock_code)

    def clear_all(self):
        from data_store import sentiment_repo

        self._memory_cache.clear()
        removed = sentiment_repo.clear_all()
        logger.info(f"✓ 已清空所有缓存 (SQLite removed={removed})")

    def clear_expired(self):
        from data_store import sentiment_repo

        current = time.time()
        expired_keys = [
            k for k, v in self._memory_cache.items()
            if current - v['timestamp'] >= self.cache_ttl.get(k.split('_')[0], 600)
        ]
        for k in expired_keys:
            del self._memory_cache[k]
        removed = sentiment_repo.clear_expired(self.cache_ttl)
        logger.info(f"✓ 已清理过期缓存 (memory={len(expired_keys)}, sqlite={removed})")

    def get_cache_stats(self) -> Dict:
        from data_store import sentiment_repo

        by_type = sentiment_repo.count_by_type()
        memory_types: Dict[str, int] = {}
        for key in self._memory_cache.keys():
            ctype = key.split('_')[0]
            memory_types[ctype] = memory_types.get(ctype, 0) + 1
        return {
            'memory_cache_count': len(self._memory_cache),
            'sqlite_cache_count': sentiment_repo.count(),
            'cache_types': memory_types,
            'sqlite_by_type': by_type,
        }


_global_cache = None


def get_sentiment_cache() -> SentimentCacheManager:
    global _global_cache
    if _global_cache is None:
        _global_cache = SentimentCacheManager()
    return _global_cache


if __name__ == "__main__":
    print("=" * 60)
    print("情绪缓存管理器 - 测试")
    print("=" * 60)
    cache = get_sentiment_cache()
    cache.set_overall_market({'sentiment_score': 65, 'overall': '偏强'})
    print("get_overall_market ->", cache.get_overall_market())
    cache.set_sector('BK0447', {'sector_name': '半导体', 'sentiment_score': 75})
    print("get_sector('BK0447') ->", cache.get_sector('BK0447'))
    print("stats ->", json.dumps(cache.get_cache_stats(), indent=2, ensure_ascii=False))

