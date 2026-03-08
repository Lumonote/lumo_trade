#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情绪数据全局缓存管理器
用于批量分析时避免重复获取大盘/板块情绪数据
"""

import os
import json
import time
import re
from pathlib import Path
from typing import Dict, Optional, Any
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
        """初始化缓存管理器"""
        if hasattr(self, '_initialized'):
            return

        self._initialized = True

        # 缓存目录
        project_root = Path(__file__).parent.parent
        self.cache_dir = project_root / 'cache' / 'sentiment'
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # 回退到临时目录
            import tempfile
            self.cache_dir = Path(tempfile.mkdtemp(prefix="sentiment_cache_"))
            logger.warning(f"缓存目录创建失败,使用临时目录: {self.cache_dir}")

        # 内存缓存
        self._memory_cache: Dict[str, Dict[str, Any]] = {}

        # 缓存配置【优化】扩展sector TTL从120s到600s，减少重复API调用
        self.cache_ttl = {
            'overall_market': 600,      # 大盘情绪:10分钟
            'sector': 600,              # 板块情绪:10分钟(从2分钟优化到10分钟，单次运行复用)
            'capital_flow': 600,        # 资金流向:10分钟(从5分钟优化到10分钟)
            'dragon_tiger': 1800,       # 龙虎榜:30分钟
            'sector_list': 3600,        # 板块列表:1小时
            'sector_constituents': 3600,# 板块成分股:1小时
            'moneyflow_ind_dc': 3600,    # 板块资金流向(单日):1小时
            'moneyflow_mkt_dc': 3600,    # 大盘资金流向(单日):1小时
            'sector_name': 3600,         # 个股板块名称缓存:1小时
        }

        logger.info(f"✓ 情绪缓存管理器已初始化: {self.cache_dir}")

    def _get_cache_key(self, cache_type: str, identifier: str = '') -> str:
        """
        生成缓存键

        Args:
            cache_type: 缓存类型 (overall_market, sector, capital_flow, dragon_tiger)
            identifier: 标识符 (板块代码、股票代码等,可选)

        Returns:
            缓存键字符串
        """
        if identifier:
            return f"{cache_type}_{identifier}"
        return cache_type

    def _get_cache_file(self, cache_key: str) -> Path:
        safe_key = cache_key.replace('/', '_').replace('\\', '_')
        safe_key = re.sub(r'[^\w\-.]', '_', safe_key)
        return self.cache_dir / f"{safe_key}.json"

    def get(self, cache_type: str, identifier: str = '') -> Optional[Dict]:
        """
        获取缓存数据

        Args:
            cache_type: 缓存类型
            identifier: 标识符

        Returns:
            缓存的数据字典,如果不存在或过期则返回None
        """
        cache_key = self._get_cache_key(cache_type, identifier)

        # 1. 尝试内存缓存
        if cache_key in self._memory_cache:
            cached = self._memory_cache[cache_key]
            if time.time() - cached['timestamp'] < self.cache_ttl.get(cache_type, 600):
                logger.debug(f"✓ 内存缓存命中: {cache_key}")
                return cached['data']
            else:
                # 过期,删除内存缓存
                del self._memory_cache[cache_key]

        # 2. 尝试文件缓存
        cache_file = self._get_cache_file(cache_key)
        if cache_file.exists():
            try:
                with cache_file.open('r', encoding='utf-8') as f:
                    cached = json.load(f)

                if time.time() - cached['timestamp'] < self.cache_ttl.get(cache_type, 600):
                    # 回写到内存缓存
                    self._memory_cache[cache_key] = cached
                    logger.debug(f"✓ 文件缓存命中: {cache_key}")
                    return cached['data']
                else:
                    # 过期,删除文件缓存
                    cache_file.unlink()
            except Exception as e:
                logger.warning(f"读取文件缓存失败 {cache_key}: {e}")

        return None

    def set(self, cache_type: str, data: Dict, identifier: str = ''):
        """
        设置缓存数据

        Args:
            cache_type: 缓存类型
            data: 要缓存的数据
            identifier: 标识符
        """
        cache_key = self._get_cache_key(cache_type, identifier)

        cached = {
            'timestamp': time.time(),
            'data': data
        }

        # 1. 写入内存缓存
        self._memory_cache[cache_key] = cached

        # 2. 写入文件缓存
        try:
            cache_file = self._get_cache_file(cache_key)
            with cache_file.open('w', encoding='utf-8') as f:
                json.dump(cached, f, ensure_ascii=False, indent=2)
            logger.debug(f"✓ 缓存已保存: {cache_key}")
        except Exception as e:
            logger.warning(f"写入文件缓存失败 {cache_key}: {e}")

    def get_overall_market(self) -> Optional[Dict]:
        """获取大盘整体情绪缓存"""
        return self.get('overall_market')

    def set_overall_market(self, data: Dict):
        """设置大盘整体情绪缓存"""
        self.set('overall_market', data)

    def get_market_sentiment(self) -> Optional[Dict]:
        """获取市场情绪缓存(兼容旧接口, 等价于大盘整体情绪)"""
        return self.get_overall_market()

    def set_market_sentiment(self, data: Dict):
        """设置市场情绪缓存(兼容旧接口, 等价于大盘整体情绪)"""
        self.set_overall_market(data)

    def get_sector(self, sector_identifier: str) -> Optional[Dict]:
        """
        获取板块情绪缓存

        Args:
            sector_identifier: 板块标识符(板块代码或板块名称)
        """
        return self.get('sector', sector_identifier)

    def set_sector(self, sector_identifier: str, data: Dict):
        """
        设置板块情绪缓存

        Args:
            sector_identifier: 板块标识符(板块代码或板块名称)
            data: 板块情绪数据
        """
        self.set('sector', data, sector_identifier)

    def get_capital_flow(self, stock_code: str) -> Optional[Dict]:
        """获取资金流向缓存"""
        return self.get('capital_flow', stock_code)

    def set_capital_flow(self, stock_code: str, data: Dict):
        """设置资金流向缓存"""
        self.set('capital_flow', data, stock_code)

    def get_dragon_tiger(self, stock_code: str) -> Optional[Dict]:
        """获取龙虎榜缓存"""
        return self.get('dragon_tiger', stock_code)

    def set_dragon_tiger(self, stock_code: str, data: Dict):
        """设置龙虎榜缓存"""
        self.set('dragon_tiger', data, stock_code)

    def clear_all(self):
        """清空所有缓存"""
        # 清空内存缓存
        self._memory_cache.clear()

        # 清空文件缓存
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
            logger.info("✓ 已清空所有缓存")
        except Exception as e:
            logger.warning(f"清空文件缓存失败: {e}")

    def clear_expired(self):
        """清理过期缓存"""
        # 清理内存缓存
        current_time = time.time()
        expired_keys = []
        for key, cached in self._memory_cache.items():
            cache_type = key.split('_')[0]
            if current_time - cached['timestamp'] >= self.cache_ttl.get(cache_type, 600):
                expired_keys.append(key)

        for key in expired_keys:
            del self._memory_cache[key]

        # 清理文件缓存
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    with cache_file.open('r', encoding='utf-8') as f:
                        cached = json.load(f)

                    cache_type = cache_file.stem.split('_')[0]
                    if current_time - cached['timestamp'] >= self.cache_ttl.get(cache_type, 600):
                        cache_file.unlink()
                except Exception:
                    pass

            logger.info(f"✓ 已清理过期缓存 ({len(expired_keys)} 个内存缓存)")
        except Exception as e:
            logger.warning(f"清理文件缓存失败: {e}")

    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        stats = {
            'memory_cache_count': len(self._memory_cache),
            'file_cache_count': len(list(self.cache_dir.glob("*.json"))),
            'cache_types': {}
        }

        # 统计各类型缓存数量
        for key in self._memory_cache.keys():
            cache_type = key.split('_')[0]
            stats['cache_types'][cache_type] = stats['cache_types'].get(cache_type, 0) + 1

        return stats


# 全局单例实例
_global_cache = None

def get_sentiment_cache() -> SentimentCacheManager:
    """获取全局缓存管理器实例"""
    global _global_cache
    if _global_cache is None:
        _global_cache = SentimentCacheManager()
    return _global_cache


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("情绪缓存管理器 - 测试")
    print("=" * 60)

    cache = get_sentiment_cache()

    # 测试大盘情绪缓存
    print("\n1. 测试大盘情绪缓存")
    test_market_data = {
        'sentiment_score': 65,
        'overall': '偏强',
        'avg_change_pct': 1.5
    }
    cache.set_overall_market(test_market_data)
    retrieved = cache.get_overall_market()
    print(f"   设置: {test_market_data}")
    print(f"   获取: {retrieved}")
    print(f"   结果: {'✓ 通过' if retrieved == test_market_data else '✗ 失败'}")

    # 测试板块情绪缓存
    print("\n2. 测试板块情绪缓存")
    test_sector_data = {
        'sector_name': '半导体',
        'sentiment_score': 75,
        'change_pct': 2.3
    }
    cache.set_sector('BK0447', test_sector_data)
    retrieved = cache.get_sector('BK0447')
    print(f"   设置: {test_sector_data}")
    print(f"   获取: {retrieved}")
    print(f"   结果: {'✓ 通过' if retrieved == test_sector_data else '✗ 失败'}")

    # 测试缓存统计
    print("\n3. 缓存统计")
    stats = cache.get_cache_stats()
    print(f"   {json.dumps(stats, indent=2, ensure_ascii=False)}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
