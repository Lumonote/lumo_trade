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
from typing import Dict, Optional
from bs4 import BeautifulSoup
from analysis.sentiment_cache_manager import SentimentCacheManager

# 初始化缓存管理器
cache_manager = SentimentCacheManager()


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


def get_stock_sector_info(stock_code: str) -> Dict:
    """
    获取股票所属板块信息
    优化策略: 个股API失败时,使用反向查询方法

    Args:
        stock_code: 股票代码 (例如: '688343', '000001')

    Returns:
        dict: 板块信息数据
    """
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

        if data and data.get('data'):
            stock_data = data['data']
            stock_name = stock_data.get('f58', '')  # 股票名称
            current_price = stock_data.get('f43', 0)  # 最新价

            # 优先使用 f127 (更可靠)，其次 f100
            raw_sector_name = stock_data.get('f127') or stock_data.get('f100')
            if isinstance(raw_sector_name, str):
                sector_name = raw_sector_name.strip()
            else:
                sector_name = '未知'

            if sector_name in ['', '-', '--', 'N/A', 'nan', 'NaN']:
                sector_name = '未知'

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

        # 如果方法1失败，引发异常进入fallback流程
        raise Exception(f"API请求失败: {last_error}")

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
        # 优化: 复用 get_stock_sector_info 获取行业名称 (它包含多源兜底逻辑)
        sector_info = get_stock_sector_info(stock_code)
        sector_name = sector_info.get('sector_name', '未知')
        sector_code = sector_info.get('sector_code', '')

        if sector_name == '未知':
            return _get_default_sector_sentiment(sector_name)

        # 方法1: 如果有板块代码，直接通过板块代码获取成分股数据，计算平均值
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
                if sector.get('f14', '') == sector_name or sector.get('f12', '') == sector_code:
                    return _extract_sector_sentiment(sector, sector_name)

            # 如果精确匹配失败，尝试模糊匹配（去除"行业"、"板块"等后缀）
            import re
            normalized_name = re.sub(r'(行业|板块|指数|概念|产业|Ⅱ|Ⅰ)', '', str(sector_name or ''))
            for sector in sectors:
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

        if data.get('data') and data['data'].get('diff'):
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
            if data.get('data') and data['data'].get('diff'):
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

        return {
            'success': True,
            'data_source': 'sina',
            'sector_name': industry,
            'stock_name': stock_name,
            'current_price': round(current_price, 2),
            'industry': industry,
            'concept_sectors': [industry] if industry != '未知' else []
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

        # 尝试从网页获取行业信息
        industry = _get_industry_from_web(stock_code) or '未知'

        return {
            'success': True,
            'data_source': 'tencent',
            'sector_name': industry,
            'stock_name': stock_name,
            'current_price': round(current_price, 2),
            'industry': industry,
            'concept_sectors': [industry] if industry != '未知' else []
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
    优先级: 东方财富 -> 新浪财经 -> 腾讯财经

    Args:
        stock_code: 股票代码

    Returns:
        dict: 板块信息
    """
    print(f"   🔄 尝试多数据源获取板块信息...")

    # 1. 尝试东方财富
    print(f"   📊 [1/3] 尝试东方财富API...")
    result = get_stock_sector_info(stock_code)
    if result.get('success'):
        print(f"   ✅ 东方财富获取成功: {result.get('sector_name')}")
        return result

    # 2. 尝试新浪财经
    print(f"   📊 [2/3] 尝试新浪财经API...")
    result = _get_sector_info_from_sina(stock_code)
    if result.get('success'):
        print(f"   ✅ 新浪财经获取成功: {result.get('sector_name')}")
        return result

    # 3. 尝试腾讯财经
    print(f"   📊 [3/3] 尝试腾讯财经API...")
    result = _get_sector_info_from_tencent(stock_code)
    if result.get('success'):
        print(f"   ✅ 腾讯财经获取成功: {result.get('sector_name')}")
        return result

    # 全部失败
    print(f"   ❌ 所有数据源均失败，返回默认值")
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
    # 尝试东方财富获取个股板块情绪
    result = get_sector_sentiment(stock_code)

    # 如果成功且不是默认值
    if result.get('data_source') != 'default':
        return result

    # 如果失败，返回市场整体行业情绪作为参考
    print(f"   ⚠️  无法获取个股板块情绪，使用市场整体情绪")
    return _get_market_average_sector_sentiment()


if __name__ == "__main__":
    # 测试代码
    test_code = "688343"

    print(f"测试获取股票 {test_code} 的板块信息...")
    sector_info = get_stock_sector_info(test_code)
    print(f"板块信息: {sector_info}")

    print(f"\n测试获取股票 {test_code} 的板块情绪...")
    sector_sentiment = get_sector_sentiment(test_code)
    print(f"板块情绪: {sector_sentiment}")
