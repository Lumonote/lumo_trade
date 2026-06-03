#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块信息和情绪API模块
提供股票板块信息查询和板块情绪分析功能
支持多数据源自动切换: 东方财富 -> 新浪财经 -> 腾讯财经
"""

import requests
import time
import re
import os
import json
import difflib
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from bs4 import BeautifulSoup
from analysis.sentiment_cache_manager import SentimentCacheManager
from scripts.stock_filter_utils import load_tushare_token

# 初始化缓存管理器
cache_manager = SentimentCacheManager()


def _load_tushare_token() -> str:
    return load_tushare_token()


def _get_tushare_pro():
    try:
        import tushare as ts
    except Exception:
        return None

    token = _load_tushare_token()
    if not token:
        return None

    try:
        return ts.pro_api(token)
    except Exception:
        return None


def _resolve_latest_trade_date(pro, base_dt: datetime, max_back_days: int = 14) -> str:
    base_str = base_dt.strftime('%Y%m%d')
    try:
        start_str = (base_dt - timedelta(days=30)).strftime('%Y%m%d')
        cal_df = pro.trade_cal(exchange='SSE', start_date=start_str, end_date=base_str, fields='cal_date,is_open')
        if cal_df is not None and not cal_df.empty and 'is_open' in cal_df.columns and 'cal_date' in cal_df.columns:
            cal_df = cal_df.sort_values('cal_date')
            open_dates = cal_df.loc[cal_df['is_open'] == 1, 'cal_date'].tolist()
            if open_dates:
                return open_dates[-1]
    except Exception:
        pass

    candidate = base_dt
    for _ in range(max_back_days):
        if candidate.weekday() < 5:
            return candidate.strftime('%Y%m%d')
        candidate -= timedelta(days=1)
    return base_str


def _normalize_sector_name(name: str) -> str:
    return re.sub(r'(行业|板块|指数|概念|产业|Ⅱ|Ⅰ)', '', str(name or '').strip())


def _fetch_moneyflow_ind_dc_all(trade_date: str):
    cached = cache_manager.get('moneyflow_ind_dc', trade_date)
    if isinstance(cached, list) and cached:
        return cached

    pro = _get_tushare_pro()
    if not pro or not hasattr(pro, 'moneyflow_ind_dc'):
        return None

    try:
        df = pro.moneyflow_ind_dc(trade_date=trade_date)
        if df is None or df.empty:
            return None
        rows = df.to_dict('records')
        cache_manager.set('moneyflow_ind_dc', rows, trade_date)
        return rows
    except Exception:
        return None


def _fetch_moneyflow_mkt_dc_all(trade_date: str):
    cached = cache_manager.get('moneyflow_mkt_dc', trade_date)
    if isinstance(cached, list) and cached:
        return cached

    pro = _get_tushare_pro()
    if not pro or not hasattr(pro, 'moneyflow_mkt_dc'):
        return None

    try:
        df = pro.moneyflow_mkt_dc(trade_date=trade_date)
        if df is None or df.empty:
            return None
        rows = df.to_dict('records')
        cache_manager.set('moneyflow_mkt_dc', rows, trade_date)
        return rows
    except Exception:
        return None


def _expand_sector_name_candidates(sector_name: str) -> List[str]:
    if not sector_name:
        return []
    sector_name = str(sector_name).strip()
    if not sector_name:
        return []
    candidates = [sector_name]
    if sector_name == 'IT服务':
        candidates.append('互联网服务')
    if 'IT' in sector_name:
        candidates.append(sector_name.replace('IT', '互联网'))
        candidates.append(sector_name.replace('IT', '信息技术'))
    return list(dict.fromkeys([c for c in candidates if c]))


def _pick_industry_row_and_name(rows, sector_names: List[str]) -> Optional[Tuple[str, Dict]]:
    if not rows or not sector_names:
        return None

    normalized_targets = []
    for n in sector_names:
        for cand in _expand_sector_name_candidates(n):
            normalized_targets.append(cand)

    normalized_targets = [t for t in normalized_targets if t]
    if not normalized_targets:
        return None

    candidates: List[Tuple[str, Dict]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get('name', '') or r.get('ind_name', '') or '')
        if not name:
            continue
        candidates.append((name, r))

    if not candidates:
        return None

    for target_name in normalized_targets:
        for name, r in candidates:
            if name == target_name:
                return name, r

    for target_name in normalized_targets:
        target = _normalize_sector_name(target_name)
        for name, r in candidates:
            norm = _normalize_sector_name(name)
            if target and norm and (norm == target or norm in target or target in norm):
                return name, r

    best: Optional[Tuple[float, str, Dict]] = None
    for target_name in normalized_targets:
        t = _normalize_sector_name(target_name)
        if not t:
            continue
        for name, r in candidates:
            n = _normalize_sector_name(name)
            if not n:
                continue
            score = difflib.SequenceMatcher(a=t, b=n).ratio()
            if best is None or score > best[0]:
                best = (score, name, r)

    if best and best[0] >= 0.6:
        return best[1], best[2]

    return None


def _build_sector_sentiment_from_ind_row(sector_name: str, row: Dict, trade_date: str) -> Dict:
    change_pct = row.get('pct_change', row.get('change_pct', 0))
    try:
        change_pct = float(change_pct)
    except Exception:
        change_pct = 0.0
    change_pct = round(change_pct, 2)

    turnover_rate = 0

    sentiment_score = round(50 + (change_pct / 5.0) * 50, 1)
    sentiment_score = max(0, min(100, sentiment_score))

    if sentiment_score >= 65:
        overall = '强势领涨'
        emotion = 'bullish'
    elif sentiment_score >= 52:
        overall = '偏强'
        emotion = 'slightly_bullish'
    elif sentiment_score >= 48:
        overall = '震荡'
        emotion = 'neutral'
    elif sentiment_score >= 35:
        overall = '偏弱'
        emotion = 'slightly_bearish'
    else:
        overall = '弱势下跌'
        emotion = 'bearish'

    net_amount_yuan = row.get('net_amount')
    try:
        net_amount_yuan = float(net_amount_yuan)
    except Exception:
        net_amount_yuan = None

    net_amount_wan = (net_amount_yuan / 10000.0) if isinstance(net_amount_yuan, (int, float)) else None
    if isinstance(net_amount_wan, (int, float)):
        net_amount_wan = round(net_amount_wan, 2)

    return {
        'sector_name': sector_name,
        'sentiment_score': sentiment_score,
        'overall': overall,
        'change_pct': change_pct,
        'turnover_rate': turnover_rate,
        'emotion': emotion,
        'data_source': 'tushare_moneyflow_ind_dc',
        'trade_date': trade_date,
        'net_amount': net_amount_wan,
        '_amount_unit': '万元',
        'net_amount_rate': row.get('net_amount_rate'),
    }


def _get_sector_sentiment_from_moneyflow_ind_dc(stock_code: str) -> Optional[Dict]:
    sector_info = get_stock_sector_info_multi_source(stock_code)
    if not isinstance(sector_info, dict):
        sector_info = {}

    sector_name = sector_info.get('industry') or sector_info.get('sector_name')
    concept_sectors = sector_info.get('concept_sectors')
    if not isinstance(concept_sectors, list):
        concept_sectors = []
    sector_candidates = [sector_name] + concept_sectors
    sector_candidates = [str(s).strip() for s in sector_candidates if s and str(s).strip() and str(s).strip() != '未知']

    if not sector_candidates:
        return None

    pro = _get_tushare_pro()
    if not pro:
        return None

    trade_date = _resolve_latest_trade_date(pro, datetime.now())
    rows = _fetch_moneyflow_ind_dc_all(trade_date)
    if not rows:
        trade_date = _resolve_latest_trade_date(pro, datetime.now() - timedelta(days=1))
        rows = _fetch_moneyflow_ind_dc_all(trade_date)

    picked = _pick_industry_row_and_name(rows, sector_candidates)
    if not picked:
        return None

    matched_name, row = picked
    return _build_sector_sentiment_from_ind_row(matched_name, row, trade_date)


def _get_sector_by_reverse_lookup(stock_code: str, headers: Dict) -> Optional[Dict]:
    """
    通过反向查询获取股票所属行业
    思路: 遍历行业板块列表,获取成分股,查找当前股票
    优化: 使用缓存管理器存储板块列表和成分股数据，避免重复请求

    Args:
        stock_code: 股票代码
        headers: 请求头

    Returns:
        dict: 板块信息,包含sector_name和sector_code
    """
    try:
        print(f"   🔍 开始反向查询板块信息...")

        # 1. 获取所有行业板块列表 (优先从缓存获取)
        sectors = cache_manager.get('sector_list', 'all')
        
        if not sectors:
            sector_list_url = "http://push2.eastmoney.com/api/qt/clist/get"
            sector_params = {
                'pn': '1',
                'pz': '300',  # 获取300个行业(足够覆盖所有)
                'po': '1',
                'np': '1',
                'fltt': '2',
                'invt': '2',
                'fid': 'f3',
                'fs': 'm:90 t:2',  # 行业板块
                'fields': 'f12,f14'  # 只要代码和名称
            }

            # 增加重试机制
            max_retries = 3
            
            for attempt in range(max_retries):
                try:
                    resp = requests.get(sector_list_url, params=sector_params, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('data') and data['data'].get('diff'):
                            sectors = data['data']['diff']
                            # 存入缓存，有效期1小时
                            cache_manager.set('sector_list', sectors, 'all')
                            break
                    
                    # 如果失败，打印日志并等待
                    if attempt < max_retries - 1:
                        print(f"   ⚠️  获取板块列表失败: HTTP {resp.status_code}, 重试中 ({attempt+1}/{max_retries})...")
                        time.sleep(2)
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"   ⚠️  获取板块列表异常: {str(e)}, 重试中 ({attempt+1}/{max_retries})...")
                        time.sleep(2)

        if not sectors:
            print(f"   ❌ 获取板块列表失败")
            return None

        print(f"   📋 获取到 {len(sectors)} 个行业板块")

        # 2. 遍历每个行业,查询成分股
        checked_count = 0
        for i, sector in enumerate(sectors):
            sector_code_val = sector.get('f12')
            sector_name = sector.get('f14')

            if not sector_code_val:
                continue

            try:
                checked_count += 1
                
                # 尝试从缓存获取成分股
                stocks = cache_manager.get('sector_constituents', sector_code_val)
                
                if not stocks:
                    # 查询该行业的成分股
                    constituents_url = "http://push2.eastmoney.com/api/qt/clist/get"
                    constituents_params = {
                        'pn': '1',
                        'pz': '1000',  # 每个行业最多1000只股票
                        'po': '1',
                        'np': '1',
                        'fltt': '2',
                        'invt': '2',
                        'fid': 'f3',
                        'fs': f"b:{sector_code_val}",
                        'fields': 'f12'  # 只要股票代码
                    }

                    # 添加少量延时避免触发频率限制 (仅在未命中缓存时)
                    if i % 10 == 0:
                        time.sleep(0.2)

                    try:
                        const_resp = requests.get(constituents_url, params=constituents_params, headers=headers, timeout=5)
                        if const_resp.status_code != 200:
                            continue

                        const_data = const_resp.json()
                        if const_data.get('data') and const_data['data'].get('diff'):
                            stocks = const_data['data']['diff']
                            # 存入缓存，有效期1小时
                            cache_manager.set('sector_constituents', stocks, sector_code_val)
                        else:
                            stocks = []
                    except:
                        continue
                
                if not stocks:
                    continue

                # 检查当前股票是否在成分股列表中
                for stock in stocks:
                    stock_id = stock.get('f12', '')
                    # 匹配逻辑: 完全匹配或以目标代码结尾
                    if stock_id == stock_code or stock_id.endswith(stock_code):
                        print(f"   ✅ 通过反向查询找到所属行业: {sector_name} ({sector_code_val})")
                        print(f"      匹配的股票ID: {stock_id}")
                        print(f"      查询了 {checked_count} 个行业后找到")
                        return {
                            'sector_name': sector_name,
                            'sector_code': sector_code_val
                        }

            except Exception:
                continue

        print(f"   ❌ 查询完 {checked_count} 个行业未找到匹配")
        return None

    except Exception as e:
        print(f"   ⚠️  反向查询失败: {str(e)}")
        return None


def _is_placeholder_text(text: str) -> bool:
    if text is None:
        return True
    stripped = str(text).strip()
    return stripped in {'', '-', '--', 'N/A', 'nan', 'NaN', 'None', 'null'}


def _is_numeric_text(text: str) -> bool:
    try:
        stripped = str(text).strip()
    except Exception:
        return False
    if not stripped:
        return False
    if stripped.startswith(('+', '-')):
        stripped = stripped[1:]
    if stripped.count('.') > 1:
        return False
    parts = stripped.split('.')
    if not all(p.isdigit() for p in parts if p != ''):
        return False
    return any(p != '' for p in parts)


def _pick_sector_name_from_stock_data(stock_data: Dict, fields_to_try: list[str]) -> str:
    for field in fields_to_try:
        raw_value = stock_data.get(field)
        if not isinstance(raw_value, str):
            continue
        candidate = raw_value.strip()
        if _is_placeholder_text(candidate):
            continue
        if _is_numeric_text(candidate):
            continue
        if len(candidate) > 30:
            continue
        return candidate
    return '未知'


def get_stock_sector_info(stock_code: str) -> Dict:
    """
    获取股票所属板块信息
    优化策略: 优先从tushare缓存获取(稳定且只需一次API调用),
    失败时才回退到东方财富/新浪/腾讯等网页API

    Args:
        stock_code: 股票代码 (例如: '688343', '000001')

    Returns:
        dict: 板块信息数据
    """
    # 优先从tushare缓存获取 (稳定,无需额外网络请求)
    tushare_result = _get_industry_from_tushare(stock_code)
    if tushare_result:
        return tushare_result

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://quote.eastmoney.com/'
    }

    try:
        # 方法1: 使用 stock/get 接口 (更稳定，支持 f127 行业字段)
        # 优先尝试 HTTPS (避免被拦截)
        # 沪市: 6开头(主板/科创板), 900开头(B股) -> 1
        # 深市: 0/3开头, 200开头(B股) -> 0
        # 北交所: 8/4/92开头 -> 0
        market = '1' if stock_code.startswith('6') or stock_code.startswith('900') else '0'
        urls_to_try = [
            "https://push2.eastmoney.com/api/qt/stock/get",
            "http://push2.eastmoney.com/api/qt/stock/get"
        ]
        params = {
            'secid': f"{market}.{stock_code}",
            'fltt': '2',
            'fields': 'f57,f58,f43,f100,f127'  # f57=code, f58=name, f43=price, f100=行业(可能为空), f127=行业(更可靠)
        }

        # 重试机制: 每个URL最多2次
        max_retries = 2
        data = None
        last_error = None

        for url in urls_to_try:
            for attempt in range(max_retries):
                try:
                    response = requests.get(url, params=params, headers=headers, timeout=10)

                    if response.status_code == 200 and response.text and response.text.strip() != '':
                        try:
                            data = response.json()
                            if data and data.get('data'):
                                break
                        except Exception:
                            last_error = "JSON解析失败"
                            continue
                    else:
                        last_error = f"HTTP {response.status_code}"
                        if attempt < max_retries - 1:
                            time.sleep(0.5)

                except requests.exceptions.Timeout:
                    last_error = "请求超时"
                    if attempt < max_retries - 1:
                        time.sleep(1)
                except requests.exceptions.RequestException as e:
                    last_error = f"请求异常: {str(e)}"
                    if attempt < max_retries - 1:
                        time.sleep(0.5)

            if data and data.get('data'):
                break
        
        # 尝试方法1.5: 如果 stock/get 失败，尝试 ulist.np
        if not (data and data.get('data')):
            try:
                ulist_url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
                ulist_params = {
                    'secids': f"{market}.{stock_code}",
                    'fltt': '2',
                    'fields': 'f12,f14,f100,f127'
                }
                ulist_resp = requests.get(ulist_url, params=ulist_params, headers=headers, timeout=10)
                if ulist_resp.status_code == 200:
                    ulist_data = ulist_resp.json()
                    if ulist_data.get('data') and ulist_data['data'].get('diff'):
                        # 构造类似 stock/get 的数据结构以便复用后续逻辑
                        item = ulist_data['data']['diff'][0]
                        data = {'data': {'f58': item.get('f14'), 'f43': 0, 'f100': item.get('f100'), 'f127': item.get('f127')}}
            except Exception:
                pass

        if not (data and data.get('data')):
            raise Exception(f"东方财富API无有效数据: {last_error or '无返回'}")

        if data and data.get('data'):
            stock_data = data['data']
            stock_name = stock_data.get('f58', '')  # 股票名称
            current_price = stock_data.get('f43', 0)  # 最新价

            sector_name = _pick_sector_name_from_stock_data(stock_data, ['f127', 'f100', 'f128', 'f129', 'f136'])

            if sector_name in ['', '-', '--', 'N/A', 'nan', 'NaN', None]:
                sector_name = '未知'

            # 调试：打印实际返回的字段
            if not sector_name or sector_name == '未知':
                # 打印所有以'f'开头的字段，帮助诊断
                f_fields = {k: v for k, v in stock_data.items() if k.startswith('f') and v}
                print(f"   🔍 东方财富API返回的f字段: {f_fields}")

            # 获取概念板块（简化版，只返回主要板块）
            concept_sectors = []
            if sector_name and sector_name != '未知':
                concept_sectors.append(sector_name)
                return {
                    'success': True,
                    'data_source': 'eastmoney_stock_get',
                    'sector_name': sector_name,
                    'stock_name': stock_name,
                    'current_price': float(current_price) if current_price else 0,
                    'industry': sector_name,
                    'concept_sectors': concept_sectors
                }

            # 行业字段为空，返回失败以触发fallback
            raise Exception("东方财富API返回数据但行业字段为空")

    except Exception as e:
        print(f"   ⚠️  获取板块信息失败: {str(e)}")

        # 方法2: 优先尝试新浪财经 (更稳定)
        print(f"   🔄 切换至新浪财经接口获取...")
        sina_info = _get_sector_info_from_sina(stock_code)
        if sina_info.get('success') and sina_info.get('sector_name') != '未知':
            print(f"   ✅ 通过sina获取板块信息成功")
            return sina_info
        elif sina_info.get('success'):
             print(f"   ⚠️ 通过sina获取了基础行情，但未获取到板块信息")

        # 方法3: 尝试腾讯财经
        print(f"   🔄 切换至腾讯财经接口获取...")
        tencent_info = _get_sector_info_from_tencent(stock_code)
        if tencent_info.get('success') and tencent_info.get('sector_name') != '未知':
            print(f"   ✅ 通过tencent获取板块信息成功")
            return tencent_info
        elif tencent_info.get('success'):
             print(f"   ⚠️ 通过tencent获取了基础行情，但未获取到板块信息")

        # 方法4: 最后尝试反向查询 (最慢)
        print(f"   🔄 尝试通过反向查询获取行业信息...")
        sector_info = _get_sector_by_reverse_lookup(stock_code, headers)

        if sector_info:
            # 整合信息：如果之前从Sina/Tencent获取到了价格/名称，就使用它们
            base_info = sina_info if sina_info.get('success') else (tencent_info if tencent_info.get('success') else {})
            
            stock_name = base_info.get('stock_name', '')
            current_price = base_info.get('current_price', 0)
            
            return {
                'success': True,
                'data_source': 'reverse_lookup',
                'sector_name': sector_info['sector_name'],
                'sector_code': sector_info['sector_code'],
                'stock_name': stock_name,
                'current_price': current_price,
                'industry': sector_info['sector_name'],
                'concept_sectors': [sector_info['sector_name']]
            }

        # 最终兜底: 返回未知但标记为成功，避免中断流程
        # 如果有基础行情数据（Sina/Tencent），至少返回那个
        fallback_data = sina_info if sina_info.get('success') else (tencent_info if tencent_info.get('success') else None)
        
        if fallback_data:
            print(f"   ⚠️  无法获取板块信息，仅返回基础行情")
            fallback_data['data_source'] = 'fallback_basic_only'
            return fallback_data

        print(f"   ⚠️  所有渠道获取板块信息失败，使用默认值")
        return {
            'success': True, # 标记为True以免上层报错
            'data_source': 'default',
            'sector_name': '未知',
            'stock_name': '',
            'current_price': 0,
            'industry': '未知',
            'concept_sectors': []
        }


# ===== Tushare行业缓存 (一次加载,全局复用) =====
_TUSHARE_INDUSTRY_CACHE = {}  # {stock_code: {'industry': '...', 'name': '...'}}
_TUSHARE_INDUSTRY_LOADED = False


def _load_tushare_industry_cache() -> bool:
    """
    从tushare stock_basic一次性加载所有股票的行业信息到全局缓存
    只调用一次,后续直接从缓存读取,避免重复API请求
    """
    global _TUSHARE_INDUSTRY_CACHE, _TUSHARE_INDUSTRY_LOADED

    if _TUSHARE_INDUSTRY_LOADED:
        return bool(_TUSHARE_INDUSTRY_CACHE)

    pro = _get_tushare_pro()
    if not pro:
        _TUSHARE_INDUSTRY_LOADED = True
        return False

    try:
        # 一次性获取所有上市股票的行业信息
        df = pro.stock_basic(
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,industry'
        )
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(row.get('symbol', ''))
                industry = str(row.get('industry', '') or '')
                name = str(row.get('name', '') or '')
                if code and industry and industry not in ('', 'nan', 'None', 'N/A'):
                    _TUSHARE_INDUSTRY_CACHE[code] = {
                        'industry': industry,
                        'name': name
                    }
            print(f"   ✅ Tushare行业缓存加载完成: {len(_TUSHARE_INDUSTRY_CACHE)}只股票")
    except Exception as e:
        print(f"   ⚠️ Tushare行业缓存加载失败: {e}")

    _TUSHARE_INDUSTRY_LOADED = True
    return bool(_TUSHARE_INDUSTRY_CACHE)


def _get_industry_from_tushare(stock_code: str) -> Optional[Dict]:
    """
    从tushare缓存中查询股票行业信息
    首次调用时自动加载缓存

    Returns:
        dict with sector_name, stock_name, industry or None
    """
    if not _TUSHARE_INDUSTRY_LOADED:
        _load_tushare_industry_cache()

    info = _TUSHARE_INDUSTRY_CACHE.get(stock_code)
    if info and info['industry']:
        return {
            'success': True,
            'data_source': 'tushare_stock_basic',
            'sector_name': info['industry'],
            'stock_name': info['name'],
            'current_price': 0,
            'industry': info['industry'],
            'concept_sectors': [info['industry']]
        }
    return None


# ============ 个股关联的多个板块（东方财富 F10 核心题材） ============
# 噪音标签：指数成分 / 市值风格 / 交易状态 / 地域，这些不是「行业/题材」板块，
# 个股副标题只展示有意义的行业+概念板块，故过滤掉。
_BOARD_DENY_SUBSTR = (
    '融资融券', '证金', '重仓', '富时', 'MSCI', '标普', '标准普尔', '茅指数', '宁组合',
    '漂亮', '股通', '大盘', '中盘', '小盘', '微盘', '权重', '百元股', '低价股',
    '送转', '预增', '预减', '预盈', '预亏', '中证', '成份', '板综', 'QFII', '社保',
)
_BOARD_DENY_SUFFIX = ('板块', '特区', '_', '指数')
_BOARD_DENY_EXACT = {'深成500', '上证50', '上证180', '沪深300', '行业龙头', '机构重仓'}


def _board_is_noise(name: str) -> bool:
    n = str(name or '').strip()
    if not n or n in _BOARD_DENY_EXACT:
        return True
    if n.endswith(_BOARD_DENY_SUFFIX):
        return True
    return any(k in n for k in _BOARD_DENY_SUBSTR)


def get_stock_boards(stock_code: str, limit: int = 8) -> list:
    """获取个股关联的多个板块名称（行业 + 概念题材，已过滤指数/市值/交易类噪音）。

    数据源：东方财富 F10「核心题材」PageAjax 的 ssbk(所属板块)，按 BOARD_RANK 顺序返回。
    该接口走 emweb.securities.eastmoney.com（非 push2，本机系统代理可达）。结果用情绪
    缓存持久化（namespace=stock_boards），失败返回 []，调用方据此降级到单一行业/占位符。
    """
    code = str(stock_code or '').strip()
    if not code:
        return []

    cached = cache_manager.get('stock_boards', code)
    if isinstance(cached, list) and cached:
        return cached[:limit]

    if code.startswith(('6', '9')):
        prefix = 'SH'
    elif code.startswith(('8', '4')):
        prefix = 'BJ'
    else:
        prefix = 'SZ'

    try:
        resp = requests.get(
            "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax",
            params={'code': f"{prefix}{code}"},
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://emweb.securities.eastmoney.com/',
            },
            timeout=8,
        )
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        print(f"   ⚠️ 获取个股板块失败: {str(e)[:80]}")
        return []

    boards: list = []
    seen = set()
    for item in (data.get('ssbk') or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get('BOARD_NAME') or '').strip()
        if not name or name in seen or _board_is_noise(name):
            continue
        seen.add(name)
        boards.append(name)

    if boards:
        try:
            cache_manager.set('stock_boards', boards, code)
        except Exception:  # noqa: BLE001
            pass
    return boards[:limit]


# 全局缓存板块列表，避免重复请求
_SECTOR_LIST_CACHE = None
_SECTOR_LIST_CACHE_TIME = 0
_SECTOR_LIST_CACHE_TTL = 3600  # 1小时缓存

def _get_all_sectors() -> list:
    """
    获取所有行业板块列表（带缓存和重试）
    """
    global _SECTOR_LIST_CACHE, _SECTOR_LIST_CACHE_TIME
    
    current_time = time.time()
    if _SECTOR_LIST_CACHE and (current_time - _SECTOR_LIST_CACHE_TIME < _SECTOR_LIST_CACHE_TTL):
        return _SECTOR_LIST_CACHE

    url = "http://push2.eastmoney.com/api/qt/clist/get"
    params = {
        'pn': '1',
        'pz': '500',  # 扩大获取数量，确保包含所有行业
        'po': '1',
        'np': '1',
        'fltt': '2',
        'invt': '2',
        'fid': 'f3',
        'fs': 'm:90 t:2',
        'fields': 'f12,f14,f2,f3,f8'
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # 重试3次
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response.json()
            
            if data and data.get('data') and data['data'].get('diff'):
                sectors = data['data']['diff']
                _SECTOR_LIST_CACHE = sectors
                _SECTOR_LIST_CACHE_TIME = current_time
                # print(f"   ✅ 成功获取全市场板块列表: {len(sectors)}个") # Reduce log noise
                return sectors
        except Exception as e:
            print(f"   ⚠️ 获取板块列表失败 (尝试 {attempt+1}/3): {e}")
            time.sleep(1)
    
    return []


def get_sector_sentiment(stock_code: str) -> Dict:
    """
    获取板块情绪数据

    Args:
        stock_code: 股票代码 (例如: '688343', '000001')

    Returns:
        dict: 板块情绪数据
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://quote.eastmoney.com/'
    }

    try:
        sector_info = get_stock_sector_info(stock_code)
        if not isinstance(sector_info, dict):
            sector_info = {}
        sector_name = sector_info.get('sector_name', '未知')
        sector_code = sector_info.get('sector_code', '')

        if sector_name == '未知':
            return _get_default_sector_sentiment(sector_name)

        # 方法1: 优先尝试从东方财富网站抓取板块指数实时涨幅
        index_change = _get_sector_index_change(sector_name)

        if index_change is not None:
            change_pct = round(index_change, 2)
            turnover_rate = 0

            sentiment_score = round(50 + (change_pct / 5.0) * 50, 1)
            sentiment_score = max(0, min(100, sentiment_score))

            if sentiment_score >= 65:
                overall = '强势领涨'
                emotion = 'bullish'
            elif sentiment_score >= 52:
                overall = '偏强'
                emotion = 'slightly_bullish'
            elif sentiment_score >= 48:
                overall = '震荡'
                emotion = 'neutral'
            elif sentiment_score >= 35:
                overall = '偏弱'
                emotion = 'slightly_bearish'
            else:
                overall = '弱势下跌'
                emotion = 'bearish'

            return {
                'sector_name': sector_name,
                'sentiment_score': sentiment_score,
                'overall': overall,
                'change_pct': change_pct,
                'turnover_rate': turnover_rate,
                'emotion': emotion,
                'data_source': 'eastmoney_index'
            }

        # 方法2: 如果抓取失败，使用成分股平均涨幅
        if sector_code:
            try:
                constituents_url = "http://push2.eastmoney.com/api/qt/clist/get"
                constituents_params = {
                    'pn': '1',
                    'pz': '200',
                    'po': '1',
                    'np': '1',
                    'fltt': '2',
                    'invt': '2',
                    'fid': 'f3',
                    'fs': f"b:{sector_code}",  # 使用板块代码
                    'fields': 'f12,f14,f3,f8'  # 代码、名称、涨跌幅、换手率
                }

                resp = requests.get(constituents_url, params=constituents_params, headers=headers, timeout=10)
                resp_data = resp.json()

                if resp_data.get('data') and resp_data['data'].get('diff'):
                    stocks = resp_data['data']['diff']
                    if stocks:
                        # 计算板块平均涨跌幅和换手率
                        changes = [s.get('f3') for s in stocks if isinstance(s.get('f3'), (int, float))]
                        turns = [s.get('f8') for s in stocks if isinstance(s.get('f8'), (int, float))]

                        if changes:
                            change_pct = round(sum(changes) / len(changes), 2)
                            turnover_rate = round(sum(turns) / len(turns), 2) if turns else 0

                            # 计算板块情绪分数 (0-100)
                            sentiment_score = round(50 + (change_pct / 5.0) * 50, 1)
                            sentiment_score = max(0, min(100, sentiment_score))

                            # 情绪判断
                            if sentiment_score >= 65:
                                overall = '强势领涨'
                                emotion = 'bullish'
                            elif sentiment_score >= 52:
                                overall = '偏强'
                                emotion = 'slightly_bullish'
                            elif sentiment_score >= 48:
                                overall = '震荡'
                                emotion = 'neutral'
                            elif sentiment_score >= 35:
                                overall = '偏弱'
                                emotion = 'slightly_bearish'
                            else:
                                overall = '弱势下跌'
                                emotion = 'bearish'

                            return {
                                'sector_name': sector_name if sector_name != '未知' else '行业板块',
                                'sentiment_score': sentiment_score,
                                'overall': overall,
                                'change_pct': change_pct,
                                'turnover_rate': turnover_rate,
                                'emotion': emotion,
                                'data_source': 'eastmoney_constituents'
                            }
            except Exception as e:
                print(f"   ⚠️  通过板块代码获取数据失败: {str(e)}")

        # 方法2: 通过行业板块列表匹配（作为备选）
        # 优化: 使用全局缓存的板块列表，避免重复请求
        sectors = _get_all_sectors()

        if sectors:
            # 先尝试精确匹配
            for sector in sectors:
                if not isinstance(sector, dict):
                    continue
                if sector.get('f14', '') == sector_name or sector.get('f12', '') == sector_code:
                    return _extract_sector_sentiment(sector, sector_name)

            # 如果精确匹配失败，尝试模糊匹配（去除"行业"、"板块"等后缀）
            import re
            normalized_name = re.sub(r'(行业|板块|指数|概念|产业|Ⅱ|Ⅰ)', '', str(sector_name or ''))
            for sector in sectors:
                if not isinstance(sector, dict):
                    continue
                sector_title = sector.get('f14', '')
                normalized_title = re.sub(r'(行业|板块|指数|概念|产业|Ⅱ|Ⅰ)', '', str(sector_title or ''))
                if normalized_name and normalized_title and (
                    normalized_name in normalized_title or normalized_title in normalized_name
                ):
                    return _extract_sector_sentiment(sector, sector_name)

        # 如果都失败，返回默认值
        return _get_default_sector_sentiment(sector_name)

    except Exception as e:
        print(f"   ⚠️  获取板块情绪失败: {str(e)}")
        return _get_default_sector_sentiment('未知')


def _extract_sector_sentiment(sector: Dict, sector_name: str) -> Dict:
    """
    从板块数据中提取情绪信息

    Args:
        sector: 板块数据字典
        sector_name: 板块名称

    Returns:
        dict: 板块情绪数据
    """
    change_pct = sector.get('f3', 0)
    turnover_rate = sector.get('f8', 0)

    # 东财行业板块接口 f3/f8 已为百分比数值（如 2.34 表示 2.34%）
    if isinstance(change_pct, (int, float)):
        change_pct = round(change_pct, 2)
    if isinstance(turnover_rate, (int, float)):
        turnover_rate = round(turnover_rate, 2)

    # 计算板块情绪分数 (0-100)
    sentiment_score = round(50 + (change_pct / 5.0) * 50, 1)
    sentiment_score = max(0, min(100, sentiment_score))

    # 情绪判断
    if sentiment_score >= 65:
        overall = '强势领涨'
        emotion = 'bullish'
    elif sentiment_score >= 52:
        overall = '偏强'
        emotion = 'slightly_bullish'
    elif sentiment_score >= 48:
        overall = '震荡'
        emotion = 'neutral'
    elif sentiment_score >= 35:
        overall = '偏弱'
        emotion = 'slightly_bearish'
    else:
        overall = '弱势下跌'
        emotion = 'bearish'

    return {
        'sector_name': sector_name if sector_name != '未知' else sector.get('f14', '未知'),
        'sentiment_score': sentiment_score,
        'overall': overall,
        'change_pct': change_pct,
        'turnover_rate': turnover_rate,
        'emotion': emotion,
        'data_source': 'eastmoney'
    }


def _get_stock_name(stock_code: str, headers: Dict) -> str:
    """
    获取股票名称

    Args:
        stock_code: 股票代码
        headers: 请求头

    Returns:
        str: 股票名称
    """
    try:
        # 使用 ulist.np 替代 stock/get
        url = "http://push2.eastmoney.com/api/qt/ulist.np/get"
        params = {
            'secids': f"{'1' if stock_code.startswith('6') else '0'}.{stock_code}",
            'fltt': '2',
            'fields': 'f14'  # 股票名称
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()

        if data and data.get('data') and data['data'].get('diff'):
            return data['data']['diff'][0].get('f14', '')
        return ''
    except:
        return ''


def _get_market_average_sector_sentiment() -> Dict:
    """
    获取市场整体行业平均情绪
    当无法获取个股所属行业时的备用方案

    Returns:
        dict: 市场整体行业情绪
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'http://quote.eastmoney.com/'
    }

    try:
        pro = _get_tushare_pro()
        if pro and hasattr(pro, 'moneyflow_mkt_dc'):
            trade_date = _resolve_latest_trade_date(pro, datetime.now())
            rows = _fetch_moneyflow_mkt_dc_all(trade_date)
            if not rows:
                trade_date = _resolve_latest_trade_date(pro, datetime.now() - timedelta(days=1))
                rows = _fetch_moneyflow_mkt_dc_all(trade_date)
            if rows:
                picked = None
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    name = str(r.get('name', '') or '')
                    if not picked:
                        picked = r
                    if name and ('沪' in name or '上证' in name):
                        picked = r
                        break

                if picked:
                    net_amount_wan = None
                    try:
                        if picked.get('net_amount') is not None:
                            net_amount_wan = round(float(picked.get('net_amount')) / 10000.0, 2)
                    except Exception:
                        net_amount_wan = None

                    change_pct = picked.get('pct_change', picked.get('change_pct', 0))
                    try:
                        change_pct = float(change_pct)
                    except Exception:
                        change_pct = 0.0
                    change_pct = round(change_pct, 2)

                    sentiment_score = round(50 + (change_pct / 5.0) * 50, 1)
                    sentiment_score = max(0, min(100, sentiment_score))

                    if sentiment_score >= 65:
                        overall = '市场强势'
                        emotion = 'bullish'
                    elif sentiment_score >= 52:
                        overall = '市场偏强'
                        emotion = 'slightly_bullish'
                    elif sentiment_score >= 48:
                        overall = '市场震荡'
                        emotion = 'neutral'
                    elif sentiment_score >= 35:
                        overall = '市场偏弱'
                        emotion = 'slightly_bearish'
                    else:
                        overall = '市场弱势'
                        emotion = 'bearish'

                    return {
                        'sector_name': str(picked.get('name', '') or '市场整体'),
                        'sentiment_score': sentiment_score,
                        'overall': overall,
                        'change_pct': change_pct,
                        'turnover_rate': 0,
                        'emotion': emotion,
                        'data_source': 'tushare_moneyflow_mkt_dc',
                        'trade_date': trade_date,
                        'net_amount': net_amount_wan,
                        '_amount_unit': '万元',
                        'net_amount_rate': picked.get('net_amount_rate'),
                    }

        # 获取所有行业板块涨跌数据
        sector_url = "http://push2.eastmoney.com/api/qt/clist/get"
        sector_params = {
            'pn': '1',
            'pz': '100',
            'po': '1',
            'np': '1',
            'fltt': '2',
            'invt': '2',
            'fid': 'f3',
            'fs': 'm:90 t:2',  # 行业板块
            'fields': 'f12,f14,f3,f8'  # 代码、名称、涨跌幅、换手率
        }

        response = requests.get(sector_url, params=sector_params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if data and data.get('data') and data['data'].get('diff'):
                sectors = data['data']['diff']

                # 计算所有行业平均涨跌和换手
                changes = [s.get('f3') for s in sectors if isinstance(s.get('f3'), (int, float))]
                turns = [s.get('f8') for s in sectors if isinstance(s.get('f8'), (int, float))]

                if changes:
                    avg_change = round(sum(changes) / len(changes), 2)
                    avg_turnover = round(sum(turns) / len(turns), 2) if turns else 0

                    # 计算情绪分数
                    sentiment_score = round(50 + (avg_change / 5.0) * 50, 1)
                    sentiment_score = max(0, min(100, sentiment_score))

                    # 情绪判断
                    if sentiment_score >= 65:
                        overall = '市场强势'
                        emotion = 'bullish'
                    elif sentiment_score >= 52:
                        overall = '市场偏强'
                        emotion = 'slightly_bullish'
                    elif sentiment_score >= 48:
                        overall = '市场震荡'
                        emotion = 'neutral'
                    elif sentiment_score >= 35:
                        overall = '市场偏弱'
                        emotion = 'slightly_bearish'
                    else:
                        overall = '市场弱势'
                        emotion = 'bearish'

                    return {
                        'sector_name': '市场整体',
                        'sentiment_score': sentiment_score,
                        'overall': overall,
                        'change_pct': avg_change,
                        'turnover_rate': avg_turnover,
                        'emotion': emotion,
                        'data_source': 'market_average'
                    }

    except Exception as e:
        print(f"   ⚠️  获取市场整体情绪失败: {str(e)}")

    return _get_default_sector_sentiment()


def _get_default_sector_sentiment(sector_name: str = '未知') -> Dict:
    """
    返回默认板块情绪数据

    Args:
        sector_name: 板块名称

    Returns:
        dict: 默认板块情绪数据
    """
    return {
        'sector_name': str(sector_name) if sector_name else '未知',
        'sentiment_score': 50,
        'overall': '数据不足',
        'change_pct': 0,
        'turnover_rate': 0,
        'emotion': 'neutral',
        'data_source': 'default'
    }


# ============ 备用数据源: 新浪财经 ============

def _scrape_sina_industry(stock_code: str) -> str:
    """
    从新浪财经网页抓取行业信息
    """
    try:
        url = f"http://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{stock_code}.phtml"
        resp = requests.get(url, timeout=5)
        resp.encoding = 'gbk'
        
        if resp.status_code != 200:
            return '未知'
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        target = soup.find(string=re.compile("所属行业"))
        
        if target:
            parent = target.parent
            if parent.name == 'a':
                href = parent.get('href')
                if href:
                    try:
                        resp2 = requests.get(href, timeout=5)
                        resp2.encoding = 'gbk'
                        if resp2.status_code == 200:
                            soup2 = BeautifulSoup(resp2.text, 'html.parser')
                            tables = soup2.find_all('table')
                            
                            for table in tables:
                                if "所属行业" in table.get_text():
                                    rows = table.find_all('tr')
                                    
                                    # Helper to get clean text
                                    def get_clean_text(r_idx, c_idx):
                                        if r_idx < len(rows):
                                            r = rows[r_idx]
                                            cs = r.find_all(['td', 'th'])
                                            if c_idx < len(cs):
                                                return cs[c_idx].get_text().strip()
                                        return None

                                    for k, row in enumerate(rows):
                                        cols = row.find_all(['td', 'th'])
                                        for j, col in enumerate(cols):
                                            if "所属行业" in col.get_text():
                                                # Strategy 1: Check next column in same row
                                                val = get_clean_text(k, j+1)
                                                if val and "同行业" not in val and "所属行业" not in val:
                                                    return val
                                                
                                                # Strategy 2: Check same column in next row
                                                val = get_clean_text(k+1, j)
                                                if val:
                                                    if "所属行业" in val or "同行业" in val:
                                                        # It's likely another header, try row k+2
                                                        val2 = get_clean_text(k+2, j)
                                                        if val2:
                                                            return val2
                                                    else:
                                                        return val
                                                    
                                                # Strategy 3: Check first column of next row (if j > 0)
                                                if j > 0:
                                                    val = get_clean_text(k+1, 0)
                                                    if val:
                                                        if "所属行业" in val or "同行业" in val:
                                                             val2 = get_clean_text(k+2, 0)
                                                             if val2:
                                                                 return val2
                                                        else:
                                                            return val
                    except Exception:
                        pass
            
            # Fallback: Check if it's in a table row on the main page
            table_row = target.find_parent('tr')
            if table_row:
                cells = table_row.find_all('td')
                for i, cell in enumerate(cells):
                    if "所属行业" in cell.get_text():
                        if i + 1 < len(cells):
                            return cells[i+1].get_text().strip()
                            
    except Exception as e:
        print(f"   ⚠️  新浪网页抓取失败: {str(e)}")
        
    return '未知'

def _get_sector_info_from_sina(stock_code: str) -> Dict:
    """
    从新浪财经获取板块信息(备用数据源)

    Args:
        stock_code: 股票代码

    Returns:
        dict: 板块信息
    """
    try:
        # 新浪财经股票详情API
        # 需要添加市场前缀: sh/sz/bj
        if stock_code.startswith('6') or stock_code.startswith('900'):
            prefix = 'sh'
        elif stock_code.startswith(('0', '3', '200')):
            prefix = 'sz'
        elif stock_code.startswith(('8', '4', '92')):
            prefix = 'bj'
        else:
            prefix = 'sh' if stock_code.startswith('6') else 'sz'

        market_code = f"{prefix}{stock_code}"

        url = f"http://hq.sinajs.cn/list={market_code}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://finance.sina.com.cn/'
        }

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return {'success': False}

        # 解析返回数据
        content = response.text
        if not content or 'var hq_str' not in content:
            return {'success': False}

        # 提取数据: var hq_str_sz301308="数据";
        match = re.search(r'var hq_str_.*?="(.*?)"', content)
        if not match:
            return {'success': False}

        data = match.group(1).split(',')
        if len(data) < 30:
            return {'success': False}

        # 新浪数据格式: 0=name, 1=开盘, 2=昨收, 3=当前, ...
        stock_name = data[0] if len(data) > 0 else ''
        current_price = float(data[3]) if len(data) > 3 and data[3] else 0

        # 使用网页抓取获取行业信息
        industry = _scrape_sina_industry(stock_code)

        # 如果行业为未知，返回失败以尝试其他数据源
        if industry == '未知':
            return {'success': False}

        return {
            'success': True,
            'data_source': 'sina',
            'sector_name': industry,
            'stock_name': stock_name,
            'current_price': round(current_price, 2),
            'industry': industry,
            'concept_sectors': [industry]
        }

    except Exception as e:
        print(f"   ⚠️  新浪财经获取失败: {str(e)}")
        return {'success': False}


def _get_sector_info_from_tencent(stock_code: str) -> Dict:
    """
    从腾讯财经获取板块信息(备用数据源)

    Args:
        stock_code: 股票代码

    Returns:
        dict: 板块信息
    """
    try:
        # 腾讯财经API
        if stock_code.startswith('6') or stock_code.startswith('900'):
            prefix = 'sh'
        elif stock_code.startswith(('0', '3', '200')):
            prefix = 'sz'
        elif stock_code.startswith(('8', '4', '92')):
            prefix = 'bj'
        else:
            prefix = 'sh' if stock_code.startswith('6') else 'sz'

        market_code = f"{prefix}{stock_code}"

        url = f"http://qt.gtimg.cn/q={market_code}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://gu.qq.com/'
        }

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return {'success': False}

        # 解析返回数据
        content = response.text
        if not content or 'v_' not in content:
            return {'success': False}

        # 提取数据: v_sz301308="xx~name~..."
        match = re.search(r'v_.*?="(.*?)"', content)
        if not match:
            return {'success': False}

        data = match.group(1).split('~')
        if len(data) < 45:
            return {'success': False}

        # 腾讯数据格式: 1=name, 3=当前价, ...
        stock_name = data[1] if len(data) > 1 else ''
        current_price = float(data[3]) if len(data) > 3 and data[3] else 0

        # 打印调试信息，查看行业字段位置
        if len(data) > 47:
            print(f"   🔍 腾讯API返回数据长度: {len(data)}, 部分字段: ")
            print(f"       字段1: {data[1] if len(data) > 1 else 'N/A'}")
            print(f"       字段45(行业代码): {data[45] if len(data) > 45 else 'N/A'}")
            print(f"       字段46(行业名称): {data[46] if len(data) > 46 else 'N/A'}")

        # 尝试多个位置的行业字段
        industry = '未知'
        candidate_fields = []
        if len(data) > 45:
            candidate_fields.append(data[45])
        if len(data) > 46:
            candidate_fields.append(data[46])
        if len(data) > 47:
            candidate_fields.append(data[47])

        for field in candidate_fields:
            if _is_placeholder_text(field) or _is_numeric_text(field):
                continue
            industry = str(field).strip()
            if industry:
                break

        if industry == '未知' or _is_numeric_text(industry):
            return {'success': False}

        return {
            'success': True,
            'data_source': 'tencent',
            'sector_name': industry,
            'stock_name': stock_name,
            'current_price': round(current_price, 2),
            'industry': industry,
            'concept_sectors': [industry]
        }

    except Exception as e:
        print(f"   ⚠️  腾讯财经获取失败: {str(e)}")
        return {'success': False}


def _get_industry_from_web(stock_code: str) -> Optional[str]:
    """
    从网页爬取行业信息(最后的兜底方案)

    Args:
        stock_code: 股票代码

    Returns:
        str: 行业名称或None
    """
    try:
        # 使用东方财富网页版
        market_code = f"{'1' if stock_code.startswith('6') else '0'}.{stock_code}"
        url = f"http://quote.eastmoney.com/{market_code}.html"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            content = response.text

            # 尝试从网页中提取行业信息
            # 方法1: 查找"所属行业"或"行业"标签
            patterns = [
                r'所属行业[：:]\s*<[^>]*>(.*?)</',
                r'行业[：:]\s*<[^>]*>(.*?)</',
                r'所属行业.*?title="(.*?)"',
            ]

            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    industry = match.group(1).strip()
                    if industry and industry != '' and len(industry) < 20:
                        return industry

        return None

    except:
        return None


# ============ 集成多数据源 ============

def get_stock_sector_info_multi_source(stock_code: str) -> Dict:
    """
    多数据源获取板块信息(自动切换)
    优先级: 缓存 -> Tushare -> 东方财富 -> 新浪财经 -> 腾讯财经

    Args:
        stock_code: 股票代码

    Returns:
        dict: 板块信息
    """
    cached_name = cache_manager.get('sector_name', stock_code)
    if isinstance(cached_name, str) and cached_name.strip() and cached_name.strip() != '未知':
        return {
            'success': True,
            'data_source': 'cache',
            'sector_name': cached_name,
            'stock_name': '',
            'current_price': 0,
            'industry': cached_name,
            'concept_sectors': [cached_name]
        }

    # 优先从tushare缓存获取 (稳定,一次加载全部)
    tushare_result = _get_industry_from_tushare(stock_code)
    if tushare_result:
        sector_name = tushare_result.get('sector_name', '')
        if sector_name and sector_name != '未知':
            cache_manager.set('sector_name', sector_name, stock_code)
            print(f"   ✅ Tushare行业缓存命中: {sector_name}")
        return tushare_result

    print(f"   🔄 尝试多数据源获取板块信息...")

    # 1. 尝试东方财富
    print(f"   📊 [1/3] 尝试东方财富API...")
    try:
        result = get_stock_sector_info(stock_code)
        if isinstance(result, dict) and result.get('sector_name', '未知') != '未知':
            sector_name = result.get('sector_name')
            if isinstance(sector_name, str) and sector_name.strip() and sector_name.strip() != '未知':
                cache_manager.set('sector_name', sector_name, stock_code)

            source = result.get('data_source') or 'eastmoney'
            if source == 'sina':
                print(f"   ✅ 新浪财经获取成功: {result.get('sector_name')}")
            elif source == 'tencent':
                print(f"   ✅ 腾讯财经获取成功: {result.get('sector_name')}")
            else:
                print(f"   ✅ 东方财富获取成功: {result.get('sector_name')}")
            return result
    except Exception as e:
        print(f"   ⚠️ 东方财富API失败: {str(e)}")

    # 2. 尝试新浪财经
    print(f"   📊 [2/3] 尝试新浪财经API...")
    result = _get_sector_info_from_sina(stock_code)
    if result.get('success') and result.get('sector_name', '未知') != '未知':
        sector_name = result.get('sector_name')
        if isinstance(sector_name, str) and sector_name.strip() and sector_name.strip() != '未知':
            cache_manager.set('sector_name', sector_name, stock_code)
        print(f"   ✅ 新浪财经获取成功: {result.get('sector_name')}")
        return result
    else:
        print(f"   ⚠️ 新浪财经未获取到板块信息")

    # 3. 尝试腾讯财经
    print(f"   📊 [3/3] 尝试腾讯财经API...")
    result = _get_sector_info_from_tencent(stock_code)
    if result.get('success') and result.get('sector_name', '未知') != '未知':
        sector_name = result.get('sector_name')
        if isinstance(sector_name, str) and sector_name.strip() and sector_name.strip() != '未知':
            cache_manager.set('sector_name', sector_name, stock_code)
        print(f"   ✅ 腾讯财经获取成功: {result.get('sector_name')}")
        return result
    else:
        print(f"   ⚠️ 腾讯财经未获取到板块信息")

    # 全部失败，返回默认值
    print(f"   ❌ 所有数据源均失败")
    return {
        'success': False,
        'data_source': 'none',
        'sector_name': '未知',
        'stock_name': '',
        'current_price': 0,
        'industry': '未知',
        'concept_sectors': []
    }


def get_sector_sentiment_multi_source(stock_code: str) -> Dict:
    """
    多数据源获取板块情绪(自动切换)
    策略: 如果无法获取个股所属行业，使用全市场行业平均情绪

    Args:
        stock_code: 股票代码

    Returns:
        dict: 板块情绪
    """
    try:
        cached = cache_manager.get('sector', stock_code)
        if isinstance(cached, dict) and cached.get('data_source') and cached.get('data_source') != 'default':
            return cached
    except Exception:
        pass

    result = _get_sector_sentiment_from_moneyflow_ind_dc(stock_code)
    if isinstance(result, dict) and result.get('data_source') == 'tushare_moneyflow_ind_dc':
        try:
            cache_manager.set('sector', result, stock_code)
        except Exception:
            pass
        return result

    result = get_sector_sentiment(stock_code)
    if result.get('data_source') != 'default':
        try:
            cache_manager.set('sector', result, stock_code)
        except Exception:
            pass
        return result

    print(f"   ⚠️  无法获取个股板块情绪，使用市场整体情绪")
    result = _get_market_average_sector_sentiment()
    try:
        cache_manager.set('sector', result, stock_code)
    except Exception:
        pass
    return result


def _get_sector_index_change(sector_name: str) -> Optional[float]:
    """
    使用Playwright从东方财富网站抓取板块指数实时涨幅

    Args:
        sector_name: 板块名称（如"光伏设备"）

    Returns:
        float: 板块指数涨跌幅，失败返回None
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

        sector_url_map = {
            '光伏设备': 'https://quote.eastmoney.com/bk/0907001.html',
        }

        target_url = sector_url_map.get(sector_name)
        if not target_url:
            return None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            page = context.new_page()

            try:
                page.goto(target_url, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(5000)

                content = page.content()

                patterns = [
                    r'当前涨跌幅["\']?\s*[:：]\s*["\']?([+-]?\d+\.?\d*)%?',
                    r'"f3"\s*:\s*([+-]?\d+\.?\d*)',
                    r'data-value\s*=\s*["\']?([+-]?\d+\.?\d*)',
                    r'change["\']?\s*[:＝=]\s*["\']?([+-]?\d+\.?\d*)',
                    r'涨幅["\']?\s*[:：]\s*([+-]?\d+\.?\d*)',
                ]

                for pattern in patterns:
                    match = re.search(pattern, content)
                    if match:
                        change_str = match.group(1)
                        try:
                            change = float(change_str)
                            if abs(change) <= 15:
                                return change
                        except:
                            continue

                return None

            except PlaywrightTimeout:
                return None
            finally:
                browser.close()

    except ImportError:
        print("   ⚠️  Playwright未安装，无法抓取板块指数数据")
        return None
    except Exception as e:
        print(f"   ⚠️  抓取板块指数数据失败: {str(e)}")
        return None


if __name__ == "__main__":
    # 测试代码
    test_code = "688343"

    print(f"测试获取股票 {test_code} 的板块信息...")
    sector_info = get_stock_sector_info(test_code)
    print(f"板块信息: {sector_info}")

    print(f"\n测试获取股票 {test_code} 的板块情绪...")
    sector_sentiment = get_sector_sentiment(test_code)
    print(f"板块情绪: {sector_sentiment}")
