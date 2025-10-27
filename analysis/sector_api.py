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


def _get_sector_by_reverse_lookup(stock_code: str, headers: Dict) -> Optional[Dict]:
    """
    通过反向查询获取股票所属行业
    思路: 遍历行业板块列表,获取成分股,查找当前股票
    优化: 并行查询多个板块,减少总耗时

    Args:
        stock_code: 股票代码
        headers: 请求头

    Returns:
        dict: 板块信息,包含sector_name和sector_code
    """
    try:
        print(f"   🔍 开始反向查询板块信息...")

        # 1. 获取所有行业板块列表
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

        resp = requests.get(sector_list_url, params=sector_params, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"   ❌ 获取板块列表失败: HTTP {resp.status_code}")
            return None

        data = resp.json()
        if not (data.get('data') and data['data'].get('diff')):
            print(f"   ❌ 板块列表数据格式异常")
            return None

        sectors = data['data']['diff']
        print(f"   📋 获取到 {len(sectors)} 个行业板块")

        # 2. 遍历每个行业,查询成分股
        checked_count = 0
        for sector in sectors:
            sector_code_val = sector.get('f12')
            sector_name = sector.get('f14')

            if not sector_code_val:
                continue

            try:
                checked_count += 1
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

                const_resp = requests.get(constituents_url, params=constituents_params, headers=headers, timeout=5)
                if const_resp.status_code != 200:
                    continue

                const_data = const_resp.json()
                if not (const_data.get('data') and const_data['data'].get('diff')):
                    continue

                stocks = const_data['data']['diff']

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

                # 优化: 减少延迟,每5个行业才延迟一次
                if checked_count % 5 == 0:
                    time.sleep(0.05)

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
        'Referer': 'http://quote.eastmoney.com/'
    }

    try:
        # 方法1: 尝试直接查询个股API
        url = "http://push2.eastmoney.com/api/qt/stock/get"
        params = {
            'secid': f"{'1' if stock_code.startswith('6') else '0'}.{stock_code}",
            'fields': 'f57,f58,f127,f128,f43,f44'  # 板块、行业、价格等字段
        }

        # 重试机制: 最多3次
        max_retries = 3
        data = None
        last_error = None

        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=10)

                # 检查HTTP状态码
                if response.status_code == 502:
                    last_error = f"HTTP 502 (尝试 {attempt+1}/{max_retries})"
                    if attempt < max_retries - 1:
                        time.sleep(1)  # 等待1秒后重试
                        continue
                    else:
                        raise Exception(last_error)

                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code} (尝试 {attempt+1}/{max_retries})"
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise Exception(last_error)

                # 检查响应内容
                if not response.text or response.text.strip() == '':
                    last_error = f"空响应 (尝试 {attempt+1}/{max_retries})"
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise Exception(last_error)

                # 解析JSON
                data = response.json()
                break  # 成功,跳出重试循环

            except requests.exceptions.Timeout:
                last_error = f"请求超时 (尝试 {attempt+1}/{max_retries})"
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
            except requests.exceptions.RequestException as e:
                last_error = f"请求异常: {str(e)} (尝试 {attempt+1}/{max_retries})"
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue

        if data is None:
            raise Exception(f"API请求失败(已重试{max_retries}次): {last_error}")

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

        # 方法2: 尝试反向查询
        print(f"   🔄 尝试通过反向查询获取行业信息...")
        sector_info = _get_sector_by_reverse_lookup(stock_code, headers)

        if sector_info:
            # 从新浪或腾讯获取股票基本信息
            stock_name = ''
            current_price = 0

            # 尝试新浪
            sina_info = _get_sector_info_from_sina(stock_code)
            if sina_info.get('success'):
                stock_name = sina_info.get('stock_name', '')
                current_price = sina_info.get('current_price', 0)

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

        # 重试机制
        max_retries = 3
        data = None
        last_error = None

        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=10)

                # 检查HTTP状态码
                if response.status_code == 502:
                    last_error = f"HTTP 502 (尝试 {attempt+1}/{max_retries})"
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise Exception(last_error)

                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code} (尝试 {attempt+1}/{max_retries})"
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise Exception(last_error)

                # 检查响应内容
                if not response.text or response.text.strip() == '':
                    last_error = f"空响应 (尝试 {attempt+1}/{max_retries})"
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise Exception(last_error)

                # 解析JSON
                data = response.json()
                break  # 成功

            except requests.exceptions.Timeout:
                last_error = f"请求超时 (尝试 {attempt+1}/{max_retries})"
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
            except requests.exceptions.RequestException as e:
                last_error = f"请求异常: {str(e)} (尝试 {attempt+1}/{max_retries})"
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue

        if data is None:
            print(f"   ⚠️  获取板块情绪失败(已重试{max_retries}次): {last_error}")
            return _get_default_sector_sentiment('未知')

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
        'sector_name': sector_name,
        'sentiment_score': 50,
        'overall': '数据不足',
        'change_pct': 0,
        'turnover_rate': 0,
        'emotion': 'neutral',
        'data_source': 'default'
    }


# ============ 备用数据源: 新浪财经 ============

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
        # 需要添加市场前缀: sh/sz
        market_code = f"{'sh' if stock_code.startswith('6') else 'sz'}{stock_code}"

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

        # 新浪不直接提供板块信息,需要从其他API获取
        # 使用新浪行业分类API
        sector_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=1&sort=symbol&asc=0&node=hs_a&symbol={market_code}"

        try:
            sector_response = requests.get(sector_url, headers=headers, timeout=5)
            if sector_response.status_code == 200:
                sector_data = sector_response.json()
                if sector_data and len(sector_data) > 0:
                    industry = sector_data[0].get('industry', '未知')
                else:
                    industry = '未知'
            else:
                industry = '未知'
        except:
            industry = '未知'

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
        market_code = f"{'sh' if stock_code.startswith('6') else 'sz'}{stock_code}"

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
