#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本面财务数据采集模块
采集股票的关键财务指标和基本面数据
"""

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

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/'
        }

    def _get_market_code(self):
        """获取市场代码"""
        if self.stock_code.startswith('6'):
            return 'sh' + self.stock_code  # 沪市
        elif self.stock_code.startswith(('0', '3')):
            return 'sz' + self.stock_code  # 深市
        elif self.stock_code.startswith('688'):
            return 'sh' + self.stock_code  # 科创板
        else:
            return 'sz' + self.stock_code

    def get_financial_indicators(self):
        """
        获取关键财务指标

        Returns:
            dict: 财务指标数据
        """
        try:
            market_code = self._get_market_code()

            # 东方财富财务指标API
            url = f"http://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': f"{'1' if market_code.startswith('sh') else '0'}.{self.stock_code}",
                'fields': 'f57,f58,f162,f167,f173,f116,f117,f189,f135,f136'
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            if data.get('data'):
                stock_data = data['data']

                # 调试：打印原始数据
                # print(f"   调试: f162={stock_data.get('f162')}, f167={stock_data.get('f167')}, f173={stock_data.get('f173')}")

                # PE值需要除以100，负值表示亏损
                pe_raw = stock_data.get('f162')
                if isinstance(pe_raw, (int, float)) and pe_raw > 0:
                    pe_ratio = round(pe_raw / 100, 2)
                elif isinstance(pe_raw, (int, float)) and pe_raw < 0:
                    pe_ratio = '亏损'
                else:
                    pe_ratio = 'N/A'

                # PB值需要除以100
                pb_raw = stock_data.get('f167')
                if isinstance(pb_raw, (int, float)) and pb_raw > 0:
                    pb_ratio = round(pb_raw / 100, 2)
                else:
                    pb_ratio = 'N/A'

                # PS值需要除以100
                ps_raw = stock_data.get('f173')
                if isinstance(ps_raw, (int, float)) and ps_raw > 0:
                    ps_ratio = round(ps_raw / 100, 2)
                else:
                    ps_ratio = 'N/A'

                indicators = {
                    'pe_ratio': pe_ratio,  # 市盈率(动态)
                    'pb_ratio': pb_ratio,  # 市净率
                    'ps_ratio': ps_ratio,  # 市销率
                    'total_market_cap': stock_data.get('f116', 'N/A'),  # 总市值(亿)
                    'circulation_market_cap': stock_data.get('f117', 'N/A'),  # 流通市值(亿)
                    'roe': 'N/A',  # ROE需要从财报获取
                    'gross_margin': 'N/A',  # 毛利率
                    'net_margin': 'N/A',  # 净利率
                    'debt_ratio': 'N/A',  # 资产负债率
                    'current_ratio': 'N/A',  # 流动比率
                }

                # 转换市值单位(亿元)
                if isinstance(indicators['total_market_cap'], (int, float)):
                    indicators['total_market_cap'] = round(indicators['total_market_cap'] / 100000000, 2)
                if isinstance(indicators['circulation_market_cap'], (int, float)):
                    indicators['circulation_market_cap'] = round(indicators['circulation_market_cap'] / 100000000, 2)

                return indicators
            else:
                print(f"   ⚠️  API未返回数据: {data}")
                return self._get_default_indicators()

        except Exception as e:
            print(f"⚠️ 获取财务指标失败: {str(e)}")

        return self._get_default_indicators()

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
            # 东方财富行业数据API
            url = "http://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': f"{'1' if self.stock_code.startswith('6') else '0'}.{self.stock_code}",
                'fields': 'f127,f128'  # 行业相关字段
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            if data.get('data'):
                stock_data = data['data']

                comparison = {
                    'industry': stock_data.get('f127', 'N/A'),  # 所属行业
                    'industry_rank': 'N/A',  # 行业排名
                    'industry_pe': 'N/A',  # 行业平均PE
                    'industry_pb': 'N/A',  # 行业平均PB
                    'vs_industry_pe': 'N/A',  # vs行业PE
                }

                return comparison

        except Exception as e:
            print(f"⚠️ 获取行业对比数据失败: {str(e)}")

        return self._get_default_industry_comparison()

    def get_comprehensive_data(self):
        """
        获取综合基本面数据

        Returns:
            dict: 综合基本面数据
        """
        print(f"📊 正在采集 {self.stock_code} 的基本面数据...")

        data = {
            'stock_code': self.stock_code,
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'financial_indicators': self.get_financial_indicators(),
            'financial_reports': self.get_financial_reports(),
            'shareholder_info': self.get_shareholder_info(),
            'industry_comparison': self.get_industry_comparison(),
        }

        print(f"✅ 基本面数据采集完成")
        return data

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
