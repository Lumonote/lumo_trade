#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票筛选通用工具。"""

import json
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple


_TUSHARE_NAME_CACHE: Optional[Dict[str, str]] = None


def normalize_stock_code(value) -> str:
    """规范化股票代码为6位数字；无法识别时返回原始文本。"""
    if value is None:
        return ''
    if isinstance(value, int):
        return str(value).zfill(6)
    if isinstance(value, float):
        try:
            if value.is_integer():
                return str(int(value)).zfill(6)
        except Exception:
            pass
    text = str(value).strip()
    if not text:
        return ''
    if text.endswith('.0') and text[:-2].isdigit():
        return text[:-2].zfill(6)
    if '.' in text:
        left, right = text.split('.', 1)
        if left.isdigit() and right.isalpha():
            return left.zfill(6)
    if text.isdigit():
        return text.zfill(6)
    return text


def _normalize_stock_name_for_flag(name) -> str:
    text = str(name or '').strip().upper()
    if not text:
        return ''
    # 兼容 "*ST"、"＊ST"、"S*ST"、名称中夹空格等写法。
    return re.sub(r'[\s*＊★]+', '', text)


def _is_placeholder_name(name, code: str = '') -> bool:
    text = str(name or '').strip()
    if not text:
        return True
    if text.lower() in {'nan', 'none', 'null', 'n/a', 'na', 'unknown'}:
        return True
    if text in {'未知', 'N/A', 'None', '测试股票'}:
        return True
    return bool(code and text == code)


def is_st_stock_name(name) -> bool:
    """判断名称是否为 ST / *ST / SST / 退市 类股票。"""
    compact = _normalize_stock_name_for_flag(name)
    if not compact:
        return False
    return compact.startswith(('ST', 'SST', '退市'))


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def candidate_tushare_config_paths(config_path: str = None) -> List[str]:
    paths: List[str] = []

    def add(path: str = None):
        if not path:
            return
        normalized = os.path.abspath(os.path.expanduser(str(path)))
        if normalized not in paths:
            paths.append(normalized)

    add(config_path)

    config_dir = os.environ.get('KRONOS_CONFIG_DIR')
    if config_dir:
        add(os.path.join(config_dir, 'tushare_config.json'))

    user_dir = os.environ.get('KRONOS_USER_DIR')
    if user_dir:
        add(os.path.join(user_dir, 'config', 'tushare_config.json'))

    source_config_dir = os.environ.get('KRONOS_SOURCE_CONFIG_DIR') or os.environ.get('KRONOS_LEGACY_CONFIG_DIR')
    if source_config_dir:
        if os.path.basename(os.path.normpath(source_config_dir)) == 'config':
            add(os.path.join(source_config_dir, 'tushare_config.json'))
        else:
            add(os.path.join(source_config_dir, 'config', 'tushare_config.json'))

    add(os.path.join(os.getcwd(), 'config', 'tushare_config.json'))
    add(os.path.join(_project_root(), 'config', 'tushare_config.json'))
    return paths


def load_tushare_config(config_path: str = None) -> Dict:
    for cfg_path in candidate_tushare_config_paths(config_path):
        if not os.path.exists(cfg_path):
            continue
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            continue
    return {}


def load_tushare_token(config_path: str = None) -> str:
    token = os.environ.get('TUSHARE_TOKEN', '').strip()
    if token:
        return token

    cfg = load_tushare_config(config_path)
    return str((cfg.get('tushare') or {}).get('token') or cfg.get('token') or '').strip()


def _load_tushare_token(config_path: str = None) -> str:
    return load_tushare_token(config_path)


def load_tushare_stock_name_map(config_path: str = None) -> Dict[str, str]:
    """加载全市场股票代码到名称映射，失败时返回空字典。"""
    global _TUSHARE_NAME_CACHE
    if _TUSHARE_NAME_CACHE is not None:
        return _TUSHARE_NAME_CACHE

    _TUSHARE_NAME_CACHE = {}
    token = _load_tushare_token(config_path)
    if not token:
        return _TUSHARE_NAME_CACHE

    try:
        import tushare as ts

        pro = ts.pro_api(token)
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
        if df is None or df.empty:
            return _TUSHARE_NAME_CACHE

        mapping: Dict[str, str] = {}
        for _, row in df.iterrows():
            code = normalize_stock_code(row.get('symbol') or row.get('ts_code'))
            name = str(row.get('name') or '').strip()
            if code and name:
                mapping[code] = name
        _TUSHARE_NAME_CACHE = mapping
    except Exception:
        pass

    return _TUSHARE_NAME_CACHE


def resolve_stock_name(stock: Dict, name_map: Dict[str, str] = None) -> str:
    """从记录自身或名称映射里解析股票名称。"""
    code = normalize_stock_code(stock.get('code') or stock.get('stock_code') or stock.get('ts_code'))
    name = str(stock.get('name') or stock.get('stock_name') or '').strip()
    if name and not _is_placeholder_name(name, code):
        return name

    if not code:
        return name
    lookup = name_map if name_map is not None else load_tushare_stock_name_map()
    mapped_name = str((lookup or {}).get(code) or '').strip()
    return mapped_name or name


def is_st_stock(stock: Dict, name_map: Dict[str, str] = None) -> bool:
    """判断股票记录是否为 ST 相关股票。"""
    if not stock:
        return False
    code = normalize_stock_code(stock.get('code') or stock.get('stock_code') or stock.get('ts_code'))
    raw_name = str(stock.get('name') or stock.get('stock_name') or '').strip()
    if is_st_stock_name(raw_name):
        return True

    if name_map is None and not _is_placeholder_name(raw_name, code):
        return False

    lookup = name_map if name_map is not None else load_tushare_stock_name_map()
    mapped_name = str((lookup or {}).get(code) or '').strip() if code else ''
    return is_st_stock_name(mapped_name)


def filter_st_stocks(
    stocks: Iterable[Dict],
    name_map: Dict[str, str] = None,
) -> Tuple[List[Dict], List[str]]:
    """过滤 ST 股票，返回 (保留列表, 被过滤的显示名称列表)。"""
    lookup = name_map
    kept: List[Dict] = []
    removed: List[str] = []

    for stock in stocks or []:
        if not isinstance(stock, dict):
            continue

        code = normalize_stock_code(stock.get('code') or stock.get('stock_code') or stock.get('ts_code'))
        if lookup is None and _is_placeholder_name(stock.get('name') or stock.get('stock_name'), code):
            lookup = load_tushare_stock_name_map()
        name = resolve_stock_name(stock, lookup)
        if name and _is_placeholder_name(stock.get('name') or stock.get('stock_name'), code):
            stock['name'] = name

        if is_st_stock(stock, lookup):
            removed.append(f"{name}({code})" if code else name)
            continue
        kept.append(stock)

    return kept, removed
