#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块信息和情绪API模块
提供股票板块信息查询和板块情绪分析功能
"""

import requests
import time
from typing import Dict, Optional


def get_stock_sector_info(stock_code: str) -> Dict:
    """
    获取股票所属板块信息

    Args:
        stock_code: 股票代码 (例如: '688343', '000001')

    Returns:
        dict: 板块信息数据
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'http://quote.eastmoney.com/'
    }

    try:
        # 东方财富股票详情API
        url = "http://push2.eastmoney.com/api/qt/stock/get"
        params = {
            'secid': f"{'1' if stock_code.startswith('6') else '0'}.{stock_code}",
            'fields': 'f57,f58,f127,f128,f43,f44'  # 板块、行业、价格等字段
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()

        if data.get('data'):
            stock_data = data['data']
            sector_name = stock_data.get('f127', '未知')  # 所属行业名称
            sector_code = stock_data.get('f128', '')  # 行业板块代码
            current_price = stock_data.get('f43', 0)
            if current_price:
                current_price = current_price / 1000  # 除以1000转换为正常值

            # 获取股票名称（需要额外请求）
            stock_name = _get_stock_name(stock_code, headers)

            # 获取概念板块（简化版，只返回主要板块）
            concept_sectors = []
            if sector_name and sector_name != '未知':
                concept_sectors.append(sector_name)

            return {
                'success': True,
                'data_source': 'eastmoney',
                'sector_name': sector_name if sector_name else '未知',
                'stock_name': stock_name,
                'current_price': round(current_price, 2) if current_price else 0,
                'industry': sector_name if sector_name else '未知',
                'concept_sectors': concept_sectors
            }
        else:
            return {
                'success': False,
                'data_source': 'eastmoney',
                'sector_name': '未知',
                'stock_name': '',
                'current_price': 0,
                'industry': '未知',
                'concept_sectors': []
            }

    except Exception as e:
        print(f"   ⚠️  获取板块信息失败: {str(e)}")
        return {
            'success': False,
            'data_source': 'error',
            'sector_name': '未知',
            'stock_name': '',
            'current_price': 0,
            'industry': '未知',
            'concept_sectors': []
        }


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
        'Referer': 'http://quote.eastmoney.com/'
    }

    try:
        # 先获取股票所属板块和板块代码
        url = "http://push2.eastmoney.com/api/qt/stock/get"
        params = {
            'secid': f"{'1' if stock_code.startswith('6') else '0'}.{stock_code}",
            'fields': 'f127,f128'  # 板块、行业
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()

        if not data.get('data'):
            return _get_default_sector_sentiment('未知')

        stock_data = data['data']
        sector_name = stock_data.get('f127', '未知')  # 所属行业名称
        sector_code = stock_data.get('f128', '')  # 行业板块代码

        if sector_name == '未知' and not sector_code:
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
        sector_url = "http://push2.eastmoney.com/api/qt/clist/get"
        sector_params = {
            'pn': '1',
            'pz': '200',
            'po': '1',
            'np': '1',
            'fltt': '2',
            'invt': '2',
            'fid': 'f3',  # 按涨跌幅排序
            'fs': 'm:90 t:2',  # 行业板块
            'fields': 'f12,f14,f2,f3,f8'  # 代码、名称、价格、涨跌幅、换手率
        }

        response = requests.get(sector_url, params=sector_params, headers=headers, timeout=10)
        sector_data = response.json()

        if sector_data.get('data') and sector_data['data'].get('diff'):
            sectors = sector_data['data']['diff']

            # 先尝试精确匹配
            for sector in sectors:
                if sector.get('f14', '') == sector_name or sector.get('f12', '') == sector_code:
                    return _extract_sector_sentiment(sector, sector_name)

            # 如果精确匹配失败，尝试模糊匹配（去除"行业"、"板块"等后缀）
            import re
            normalized_name = re.sub(r'(行业|板块|指数|概念|产业|Ⅱ|Ⅰ)', '', sector_name or '')
            for sector in sectors:
                sector_title = sector.get('f14', '')
                normalized_title = re.sub(r'(行业|板块|指数|概念|产业|Ⅱ|Ⅰ)', '', sector_title)
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
        url = "http://push2.eastmoney.com/api/qt/stock/get"
        params = {
            'secid': f"{'1' if stock_code.startswith('6') else '0'}.{stock_code}",
            'fields': 'f58'  # 股票名称
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()

        if data.get('data'):
            return data['data'].get('f58', '')
        return ''
    except:
        return ''


def _get_default_sector_sentiment(sector_name: str = '未知') -> Dict:
    """
    返回默认板块情绪数据

    Args:
        sector_name: 板块名称

    Returns:
        dict: 默认板块情绪数据
    """
    return {
        'sector_name': sector_name,
        'sentiment_score': 50,
        'overall': '数据不足',
        'change_pct': 0,
        'turnover_rate': 0,
        'emotion': 'neutral',
        'data_source': 'default'
    }


if __name__ == "__main__":
    # 测试代码
    test_code = "688343"

    print(f"测试获取股票 {test_code} 的板块信息...")
    sector_info = get_stock_sector_info(test_code)
    print(f"板块信息: {sector_info}")

    print(f"\n测试获取股票 {test_code} 的板块情绪...")
    sector_sentiment = get_sector_sentiment(test_code)
    print(f"板块情绪: {sector_sentiment}")
