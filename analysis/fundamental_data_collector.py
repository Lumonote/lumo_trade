#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本面财务数据采集模块
采集股票的关键财务指标和基本面数据
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import json
import time
import random
from pathlib import Path
import sys

# 添加项目根目录到路径 - 优先使用环境变量
# 尝试多个可能的路径位置
possible_roots = []
if 'KRONOS_PROJECT_ROOT' in os.environ:
    possible_roots.append(os.environ['KRONOS_PROJECT_ROOT'])
possible_roots.append(str(Path(__file__).parent.parent))  # analysis 的父目录
possible_roots.append(str(Path(__file__).parent.parent.parent))  # Frameworks 的父目录
possible_roots.append(str(Path(__file__).parent))  # 当前目录

# 查找有效的根目录
project_root = None
for root in possible_roots:
    root_path = Path(root)
    utils_path = root_path / 'utils'
    if root_path.exists() and utils_path.exists():
        project_root = str(root_path)
        break

if project_root is None:
    # 最后尝试从当前工作目录查找
    project_root = os.getcwd()

sys.path.insert(0, project_root)
# 也添加 utils 目录
utils_path = Path(project_root) / 'utils'
if utils_path.exists():
    sys.path.insert(0, str(utils_path))

from utils.retry_utils import (
    exponential_backoff_with_jitter,
    retry_with_fallback,
    validate_data_quality,
    handle_missing_fields
)

import logging
logger = logging.getLogger(__name__)

_INDUSTRY_COMPARISON_CACHE = {}
_INDUSTRY_COMPARISON_CACHE_TTL = 3600


class FundamentalDataCollector:
    """基本面财务数据采集器"""

    def __init__(self, stock_code):
        """
        初始化基本面数据采集器

        Args:
            stock_code: 股票代码 (例如: '688343', '000001')
        """
        self.stock_code = stock_code
        self.headers = {
            'User-Agent': 'curl/8.6.0',
            'Connection': 'close'
        }

    def _get_data_via_curl(self, url, params):
        """使用curl命令行工具获取数据（作为requests的fallback）"""
        import subprocess
        import time
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 构建完整的URL参数
                query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                full_url = f"{url}?{query_string}"
                
                cmd = ['curl', '-s', full_url, '-H', 'User-Agent: curl/8.6.0']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    try:
                        return json.loads(result.stdout)
                    except json.JSONDecodeError:
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                        return None
                else:
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    print(f"   ⚠️  Curl请求失败: {result.stderr}")
                    return None
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                print(f"   ⚠️  Curl执行出错: {e}")
                return None
        return None

    def _get_market_code(self):
        """获取市场代码"""
        if self.stock_code.startswith('6') or self.stock_code.startswith('900'):
            return 'sh' + self.stock_code  # 沪市
        elif self.stock_code.startswith(('8', '4', '92')):
            return 'bj' + self.stock_code  # 北交所
        else:
            return 'sz' + self.stock_code  # 深市 (0, 3, 200等)

    def _get_market_id(self):
        """获取市场标识 (沪市1, 深市/北交所0)"""
        # 沪市: 6开头(主板/科创板), 900开头(B股)
        # 注意: 92开头是北交所, 应归为0
        if self.stock_code.startswith('6') or self.stock_code.startswith('900'):
            return '1'
        # 深市: 0开头(主板), 3开头(创业板), 2开头(B股)
        # 北交所: 8开头, 4开头, 92开头 -> 也在东方财富接口中通常归为0
        else:
            return '0'

    @exponential_backoff_with_jitter(max_retries=3, base_delay=1.0)
    def get_financial_indicators(self):
        """
        获取主要财务指标 (PE, PB, 市值等) - 带重试机制
        
        Returns:
            dict: 财务指标数据
        """
        try:
            # 1. 尝试使用 stock/get 接口 (最准确)
            url = "https://push2.eastmoney.com/api/qt/stock/get"
            secid = f"{self._get_market_id()}.{self.stock_code}"
            
            params = {
                'secid': secid,
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281', # 使用通用token
                'fields': 'f9,f23,f20,f21,f162,f167,f116,f117', # f9/f23(clist用), f162/f167(stock用)
                'invt': '2',
                'fltt': '2'
            }
            
            headers = self.headers.copy()
            headers['Referer'] = 'https://quote.eastmoney.com/'
            
            try:
                response = requests.get(url, params=params, headers=headers, timeout=5)
                data = response.json()
                
                if data and data.get('data'):
                    stock_data = data['data']
                    # 优先使用 stock/get 的字段 (f162=PE-TTM, f167=PB, f116=总市值, f117=流通市值)
                    pe = stock_data.get('f162') or stock_data.get('f9')
                    pb = stock_data.get('f167') or stock_data.get('f23')
                    total_mv = stock_data.get('f116') or stock_data.get('f20')
                    circ_mv = stock_data.get('f117') or stock_data.get('f21')
                    
                    return self._format_indicators(pe, pb, total_mv, circ_mv)
            except Exception as e:
                print(f"⚠️ stock/get接口请求失败: {e}")

            # 2. 尝试备用方案: ulist.np (统一列表)
            return self._get_financial_indicators_fallback()

        except Exception as e:
            print(f"⚠️ 获取财务指标失败: {str(e)}")
            return self._get_default_indicators()

    def _get_financial_indicators_fallback(self):
        """备用方案：使用腾讯接口、ulist或clist获取"""
        try:
            # 尝试方案A: 腾讯财经接口 (最优先备用，稳定且包含PE/PB/市值)
            tencent_data = self._get_financial_indicators_tencent()
            if tencent_data:
                print(f"✅ 通过腾讯财经接口获取指标成功")
                return tencent_data

            # 尝试方案B: ulist.np (指定股票代码)
            url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
            params = {
                'fltt': '2',
                'secids': f"{self._get_market_id()}.{self.stock_code}",
                'fields': 'f12,f14,f9,f23,f20,f21', # f9=PE, f23=PB
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281'
            }
            
            try:
                response = requests.get(url, params=params, headers=self.headers, timeout=5)
                data = response.json()
                if data and data.get('data') and data['data'].get('diff'):
                    stock_data = data['data']['diff'][0]
                    return self._format_indicators(
                        stock_data.get('f9'), 
                        stock_data.get('f23'), 
                        stock_data.get('f20'), 
                        stock_data.get('f21')
                    )
            except:
                pass

            # 尝试方案B: clist (全市场热门/活跃股查找 - 最后的兜底)
            # 获取成交额前200的股票（覆盖大部分热门股）
            return self._get_from_top_active_stocks()

        except Exception as e:
            print(f"⚠️ 备用方案失败: {str(e)}")
        
        return self._get_default_indicators()

    def _get_financial_indicators_tencent(self):
        """从腾讯财经获取实时指标"""
        try:
            # 确定前缀
            if self.stock_code.startswith('6') or self.stock_code.startswith('900'):
                prefix = 'sh'
            elif self.stock_code.startswith(('0', '3', '2')):
                prefix = 'sz'
            elif self.stock_code.startswith(('4', '8', '92')):
                prefix = 'bj'
            else:
                return None
            
            url = f"http://qt.gtimg.cn/q={prefix}{self.stock_code}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                content = resp.text
                if f"v_{prefix}{self.stock_code}=" in content:
                    data_str = content.split('="')[1].strip('";')
                    data = data_str.split('~')
                    if len(data) > 53:
                        # Index 52: PE (TTM)
                        # Index 46: PB
                        # Index 44: Total Market Cap (100M)
                        # Index 45: Circulating Market Cap (100M)
                        
                        pe = data[52]
                        pb = data[46]
                        total_mv = float(data[44]) * 100000000 if data[44] else None
                        circ_mv = float(data[45]) * 100000000 if data[45] else None
                        
                        return {
                            'pe_ratio': float(pe) if pe else 'N/A',
                            'pb_ratio': float(pb) if pb else 'N/A',
                            'total_market_cap': total_mv,
                            'circulation_market_cap': circ_mv,
                            # Others default to N/A
                            'ps_ratio': 'N/A',
                            'roe': 'N/A',
                            'gross_margin': 'N/A',
                            'net_margin': 'N/A',
                            'debt_ratio': 'N/A',
                            'current_ratio': 'N/A'
                        }
        except Exception as e:
            print(f"   ⚠️ 腾讯接口获取失败: {str(e)}")
        return None

    def _get_from_top_active_stocks(self):
        """从全市场成交额前200名中查找 (兜底方案)"""
        try:
            url = "https://push2.eastmoney.com/api/qt/clist/get"
            params = {
                'pn': '1',
                'pz': '200', # 前200名
                'po': '1',   # 降序
                'np': '1',
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                'fltt': '2',
                'invt': '2',
                'fid': 'f6', # 按成交额排序 (f6)
                'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
                'fields': 'f12,f9,f23,f20,f21'
            }
            
            response = requests.get(url, params=params, headers=self.headers, timeout=8)
            data = response.json()
            
            if data and data.get('data') and data['data'].get('diff'):
                for stock in data['data']['diff']:
                    if str(stock.get('f12')) == self.stock_code:
                        print(f"✅ 在活跃股列表中找到 {self.stock_code}")
                        return self._format_indicators(
                            stock.get('f9'), 
                            stock.get('f23'), 
                            stock.get('f20'), 
                            stock.get('f21')
                        )
        except Exception as e:
            print(f"⚠️ 活跃股列表查找失败: {e}")
            
        return self._get_default_indicators()

    def _format_indicators(self, pe, pb, total_mv, circ_mv):
        """格式化指标数据"""
        # 处理PE
        pe_ratio = 'N/A'
        if pe != '-':
            try:
                pe_val = float(pe)
                if pe_val < 0:
                    pe_ratio = f"亏损({pe_val})"
                else:
                    pe_ratio = round(pe_val, 2)
            except:
                pass

        # 处理PB
        pb_ratio = 'N/A'
        if pb != '-':
            try:
                pb_ratio = round(float(pb), 2)
            except:
                pass

        # 处理市值 (API通常返回的是元，需要确认)
        # clist返回的通常是元
        total_market_cap = 'N/A'
        if total_mv != '-':
            try:
                total_market_cap = float(total_mv)
            except:
                pass
                
        circulation_market_cap = 'N/A'
        if circ_mv != '-':
            try:
                circulation_market_cap = float(circ_mv)
            except:
                pass

        return {
            'pe_ratio': pe_ratio,
            'pb_ratio': pb_ratio,
            'ps_ratio': 'N/A',
            'total_market_cap': total_market_cap,
            'circulation_market_cap': circulation_market_cap,
            'roe': 'N/A',
            'gross_margin': 'N/A',
            'net_margin': 'N/A',
            'debt_ratio': 'N/A',
            'current_ratio': 'N/A',
        }

    def get_financial_reports(self):
        """
        获取最新财报数据 - 使用可靠的东方财富API

        Returns:
            dict: 财报数据
        """
        try:
            # 使用东方财富业绩报表API - 最可靠的数据源
            url = "http://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                'reportName': 'RPT_LICO_FN_CPD',
                'columns': 'ALL',
                'filter': f'(SECURITY_CODE="{self.stock_code}")',
                'pageNumber': '1',
                'pageSize': '12',  # 获取最近12期用于TTM计算
                'sortColumns': 'UPDATE_DATE',
                'sortTypes': '-1'
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            # 初始化默认值
            reports = {
                'report_date': 'N/A',
                'revenue': 'N/A',
                'net_profit': 'N/A',
                'revenue_yoy': 'N/A',
                'net_profit_yoy': 'N/A',
                'roe': 'N/A',
                'gross_margin': 'N/A',
                'net_margin': 'N/A',
                'debt_ratio': 'N/A',
                'accounts_receivable': 'N/A',  # 应收账款
                'cash_flow': 'N/A',  # 现金流
            }

            if data.get('success') and data.get('result'):
                records = data['result'].get('data', [])
                if records:
                    # 按报告期排序（降序）
                    try:
                        records_sorted = sorted(records, key=lambda r: str(r.get('REPORTDATE', '')), reverse=True)
                    except Exception:
                        records_sorted = records
                    latest = records_sorted[0]

                    # 提取报告期
                    report_date = latest.get('REPORTDATE', 'N/A')
                    if report_date != 'N/A':
                        reports['report_date'] = report_date[:10]  # 格式化日期

                    # 营业总收入 (元 -> 亿元)
                    revenue = latest.get('TOTAL_OPERATE_INCOME')
                    if revenue is not None:
                        reports['revenue'] = round(float(revenue) / 100000000, 2)

                    # 净利润 (元 -> 亿元)
                    net_profit = latest.get('PARENT_NETPROFIT')
                    if net_profit is not None:
                        reports['net_profit'] = round(float(net_profit) / 100000000, 2)

                    # 经营现金流 - 从现金流量表API获取
                    cash_flow = self._get_cash_flow_data()
                    if cash_flow != 'N/A':
                        reports['cash_flow'] = cash_flow

                    # 同比增长率（接口提供）
                    revenue_yoy = latest.get('YSTZ')  # 营收同比增长
                    if revenue_yoy is not None:
                        reports['revenue_yoy'] = round(float(revenue_yoy), 2)

                    net_profit_yoy = latest.get('SJLTZ')  # 净利润同比增长
                    if net_profit_yoy is not None:
                        reports['net_profit_yoy'] = round(float(net_profit_yoy), 2)

                    # 备选视角：基于TTM（近4季）计算同比
                    try:
                        # 提取最近8期的单季营收与净利润（单位：元）
                        quarterly_rev = []
                        quarterly_np = []
                        for rec in records_sorted:
                            rev = rec.get('TOTAL_OPERATE_INCOME')
                            np = rec.get('PARENT_NETPROFIT')
                            if rev is not None and np is not None:
                                quarterly_rev.append(float(rev))
                                quarterly_np.append(float(np))
                            # 足够数据即可
                            if len(quarterly_rev) >= 8 and len(quarterly_np) >= 8:
                                break

                        if len(quarterly_rev) >= 8 and len(quarterly_np) >= 8:
                            # 近4季TTM与上一年4季TTM
                            current_rev_ttm = sum(quarterly_rev[:4])
                            prev_rev_ttm = sum(quarterly_rev[4:8])
                            current_np_ttm = sum(quarterly_np[:4])
                            prev_np_ttm = sum(quarterly_np[4:8])

                            # 转换为亿元
                            reports['revenue_ttm'] = round(current_rev_ttm / 100000000, 2)
                            reports['net_profit_ttm'] = round(current_np_ttm / 100000000, 2)

                            # 计算TTM同比（百分比）
                            if prev_rev_ttm != 0:
                                reports['revenue_yoy_calc'] = round((current_rev_ttm - prev_rev_ttm) / abs(prev_rev_ttm) * 100, 2)
                            else:
                                reports['revenue_yoy_calc'] = 'N/A'

                            if prev_np_ttm != 0:
                                reports['net_profit_yoy_calc'] = round((current_np_ttm - prev_np_ttm) / abs(prev_np_ttm) * 100, 2)
                            else:
                                reports['net_profit_yoy_calc'] = 'N/A'

                            reports['yoy_calc_note'] = 'TTM计算(近4季对比上年4季)'
                        else:
                            reports['revenue_ttm'] = 'N/A'
                            reports['net_profit_ttm'] = 'N/A'
                            reports['revenue_yoy_calc'] = 'N/A'
                            reports['net_profit_yoy_calc'] = 'N/A'
                            reports['yoy_calc_note'] = '数据不足，TTM同比不可用'
                    except Exception:
                        reports['revenue_ttm'] = 'N/A'
                        reports['net_profit_ttm'] = 'N/A'
                        reports['revenue_yoy_calc'] = 'N/A'
                        reports['net_profit_yoy_calc'] = 'N/A'
                        reports['yoy_calc_note'] = '计算异常'

                    # ROE (加权平均)
                    roe = latest.get('WEIGHTAVG_ROE')
                    if roe is not None:
                        reports['roe'] = round(float(roe), 2)

                    # 毛利率
                    gross_margin = latest.get('XSMLL')  # 销售毛利率
                    if gross_margin is not None:
                        reports['gross_margin'] = round(float(gross_margin), 2)

                    print(f"   ✅ API成功获取财报数据 (报告期: {reports['report_date']})")
                    return reports

            print(f"   ⚠️  API未返回财报数据")
            return reports

        except Exception as e:
            print(f"⚠️ 获取财报数据失败: {str(e)}")
            return self._get_default_reports()

    def _get_reports_from_api(self):
        """使用API获取财报数据作为备用方案"""
        try:
            # 东方财富业绩快报API
            url = "http://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax"
            params = {
                'code': self._get_market_code()
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            if data and isinstance(data, dict):
                # 提取最新一期数据
                reports = {
                    'report_date': data.get('date', 'N/A'),
                    'revenue': self._parse_financial_value(str(data.get('yysr', 'N/A'))),
                    'net_profit': self._parse_financial_value(str(data.get('jlr', 'N/A'))),
                    'revenue_yoy': self._parse_percentage(str(data.get('yysrtbzz', 'N/A'))),
                    'net_profit_yoy': self._parse_percentage(str(data.get('jlrtbzz', 'N/A'))),
                    'roe': self._parse_percentage(str(data.get('roe', 'N/A'))),
                    'gross_margin': self._parse_percentage(str(data.get('xsmll', 'N/A'))),
                    'net_margin': self._parse_percentage(str(data.get('xsjll', 'N/A'))),
                    'debt_ratio': self._parse_percentage(str(data.get('zcfzl', 'N/A'))),
                }
                return reports

        except Exception as e:
            print(f"⚠️ API获取财报数据失败: {str(e)}")

        return self._get_default_reports()

    def _get_cash_flow_data(self):
        """获取现金流数据"""
        try:
            url = "http://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                'reportName': 'RPT_DMSK_FN_CASHFLOW',  # 现金流量表
                'columns': 'NETCASH_OPERATE',
                'filter': f'(SECURITY_CODE="{self.stock_code}")',
                'pageNumber': '1',
                'pageSize': '1',
                'sortColumns': 'REPORT_DATE',
                'sortTypes': '-1'
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            if data.get('success') and data.get('result'):
                records = data['result'].get('data', [])
                if records:
                    cash_flow = records[0].get('NETCASH_OPERATE')
                    if cash_flow is not None:
                        return round(float(cash_flow) / 100000000, 2)

        except Exception as e:
            pass

        return 'N/A'

    def _parse_financial_value(self, value_str):
        """解析财务数值(转换为亿元)"""
        try:
            # 移除逗号和空格
            value_str = value_str.replace(',', '').replace(' ', '').strip()

            # 处理单位
            if '亿' in value_str:
                return round(float(re.sub(r'[^0-9.-]', '', value_str)), 2)
            elif '万' in value_str:
                return round(float(re.sub(r'[^0-9.-]', '', value_str)) / 10000, 2)
            elif value_str and value_str != 'N/A':
                # 假设原始单位是元,转换为亿元
                return round(float(value_str) / 100000000, 2)
            else:
                return 'N/A'
        except:
            return 'N/A'

    def _parse_percentage(self, value_str):
        """解析百分比值"""
        try:
            value_str = value_str.replace('%', '').replace(' ', '').strip()
            if value_str and value_str != 'N/A':
                return round(float(value_str), 2)
            else:
                return 'N/A'
        except:
            return 'N/A'

    def get_shareholder_info(self):
        """
        获取股东信息

        Returns:
            dict: 股东信息
        """
        try:
            # 东方财富股东数据API
            url = "http://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageSDGD"
            params = {
                'code': self.stock_code
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            if data.get('gdrs') and len(data['gdrs']) > 0:
                latest_shareholder = data['gdrs'][0]

                info = {
                    'end_date': latest_shareholder.get('END_DATE', 'N/A'),
                    'shareholder_count': latest_shareholder.get('HOLDER_NUM', 'N/A'),  # 股东数
                    'shareholder_change': latest_shareholder.get('HOLDER_NUM_CHANGE', 'N/A'),  # 股东数变化
                    'avg_shares_per_holder': latest_shareholder.get('AVG_HOLD_NUM', 'N/A'),  # 户均持股
                    'institutional_ratio': 'N/A',  # 机构持股比例(需从其他接口获取)
                }

                # 转换股东数单位
                if isinstance(info['shareholder_count'], (int, float)):
                    info['shareholder_count'] = int(info['shareholder_count'])

                return info

        except Exception as e:
            print(f"⚠️ 获取股东信息失败: {str(e)}")

        return self._get_default_shareholder_info()

    def get_industry_comparison(self):
        """
        获取行业对比数据

        Returns:
            dict: 行业对比数据
        """
        try:
            cached = _INDUSTRY_COMPARISON_CACHE.get(self.stock_code)
            if cached and time.time() - cached['timestamp'] < _INDUSTRY_COMPARISON_CACHE_TTL:
                return cached['data']

            # 东方财富行业数据API - 使用ulist.np替代stock/get
            url = "http://push2.eastmoney.com/api/qt/ulist.np/get"
            market_id = '1' if self.stock_code.startswith('6') or self.stock_code.startswith('900') else '0'
            params = {
                'secids': f"{market_id}.{self.stock_code}",
                'fltt': '2',
                'fields': 'f100'  # f100: 所属行业
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = None
            if response.status_code == 200 and response.text and response.text.strip():
                try:
                    data = response.json()
                except Exception:
                    data = None
            if data is None:
                data = self._get_data_via_curl(url, params)

            if data and data.get('data') and data['data'].get('diff'):
                stock_data = data['data']['diff'][0]

                comparison = {
                    'industry': stock_data.get('f100', 'N/A'),  # 所属行业
                    'industry_rank': 'N/A',  # 行业排名
                    'industry_pe': 'N/A',  # 行业平均PE
                    'industry_pb': 'N/A',  # 行业平均PB
                    'vs_industry_pe': 'N/A',  # vs行业PE
                }
                
                # 兼容逻辑
                if comparison['industry'] == 'N/A':
                     comparison['industry'] = stock_data.get('f102', 'N/A')

                _INDUSTRY_COMPARISON_CACHE[self.stock_code] = {
                    'timestamp': time.time(),
                    'data': comparison
                }
                return comparison

        except Exception as e:
            print(f"⚠️ 获取行业对比数据失败: {str(e)}")

        return self._get_default_industry_comparison()

    def get_comprehensive_data(self):
        """
        获取综合基本面数据 - 新增重试机制和数据验证

        Returns:
            dict: 综合基本面数据
        """
        logger.info(f"📊 正在采集 {self.stock_code} 的基本面数据...")

        try:
            # 采集各维度数据（带重试机制）
            data = {
                'stock_code': self.stock_code,
                'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }

            # 财务指标（已添加@exponential_backoff_with_jitter装饰器）
            try:
                indicators = self.get_financial_indicators()
                # 验证数据质量
                is_valid, error_msg = validate_data_quality(
                    indicators,
                    required_fields=['pe_ratio', 'pb_ratio'],
                    min_rows=0,  # 字典类型检查
                    data_type="财务指标"
                )
                if not is_valid:
                    logger.warning(f"财务指标验证失败: {error_msg}，使用默认值")
                    indicators = self._get_default_indicators()
                data['financial_indicators'] = indicators
            except Exception as e:
                logger.warning(f"财务指标采集失败: {e}，使用默认值")
                data['financial_indicators'] = self._get_default_indicators()

            # 财务报告
            try:
                reports = self.get_financial_reports()
                data['financial_reports'] = reports
            except Exception as e:
                logger.warning(f"财务报告采集失败: {e}")
                data['financial_reports'] = {}

            # 股东信息
            try:
                shareholder = self.get_shareholder_info()
                data['shareholder_info'] = shareholder
            except Exception as e:
                logger.warning(f"股东信息采集失败: {e}")
                data['shareholder_info'] = {}

            # 行业对比
            try:
                industry = self.get_industry_comparison()
                data['industry_comparison'] = industry
            except Exception as e:
                logger.warning(f"行业对比采集失败: {e}")
                data['industry_comparison'] = {}

            logger.info(f"✅ 基本面数据采集完成")
            return data

        except Exception as e:
            logger.error(f"基本面数据采集异常: {e}")
            raise

    def _get_default_indicators(self):
        """返回默认财务指标"""
        return {
            'pe_ratio': 'N/A',
            'pb_ratio': 'N/A',
            'ps_ratio': 'N/A',
            'total_market_cap': 'N/A',
            'circulation_market_cap': 'N/A',
            'roe': 'N/A',
            'gross_margin': 'N/A',
            'net_margin': 'N/A',
            'debt_ratio': 'N/A',
            'current_ratio': 'N/A',
        }

    def _get_default_reports(self):
        """返回默认财报数据"""
        return {
            'report_date': 'N/A',
            'revenue': 'N/A',
            'net_profit': 'N/A',
            'revenue_yoy': 'N/A',
            'net_profit_yoy': 'N/A',
            'roe': 'N/A',
            'gross_margin': 'N/A',
            'net_margin': 'N/A',
            'debt_ratio': 'N/A',
        }

    def _get_default_shareholder_info(self):
        """返回默认股东信息"""
        return {
            'end_date': 'N/A',
            'shareholder_count': 'N/A',
            'shareholder_change': 'N/A',
            'avg_shares_per_holder': 'N/A',
            'institutional_ratio': 'N/A',
        }

    def _get_default_industry_comparison(self):
        """返回默认行业对比数据"""
        return {
            'industry': 'N/A',
            'industry_rank': 'N/A',
            'industry_pe': 'N/A',
            'industry_pb': 'N/A',
            'vs_industry_pe': 'N/A',
        }


if __name__ == "__main__":
    # 测试代码
    collector = FundamentalDataCollector("688343")
    data = collector.get_comprehensive_data()

    print("\n" + "=" * 60)
    print("基本面数据采集结果:")
    print("=" * 60)

    import json

    print(json.dumps(data, indent=2, ensure_ascii=False))
