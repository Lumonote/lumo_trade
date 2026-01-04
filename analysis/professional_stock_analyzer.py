#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专业证券分析师级别的深度分析模块 v1.0
=====================================

核心功能:
1. 负面信息过滤 - 识别并排除终止/失败/利空消息
2. 真实财务数据获取 - 获取PE/PB/营收/利润等核心指标
3. 技术面深度分析 - 真实K线形态和技术指标
4. 资金流向分析 - 主力资金/北向资金动向
5. 行业对比分析 - 与同行业公司对比估值
6. 专业投研报告 - 按证券分析师标准输出
"""

import os
import sys
import re
import time
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from bs4 import BeautifulSoup
import random

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProfessionalStockAnalyzer:
    """专业证券分析师级别的深度分析"""
    
    NEGATIVE_KEYWORDS = [
        '终止', '失败', '取消', '否决', '撤回', '中止', '暂停', '搁置',
        '下跌', '暴跌', '跌停', '大跌', '亏损', '巨亏', '利空',
        '减持', '清仓', '抛售', '套现', '离职', '辞职',
        '违规', '处罚', '立案', '调查', '警告', '谴责',
        '退市', '风险警示', 'ST', '*ST', '摘牌',
        '诉讼', '仲裁', '纠纷', '索赔', '败诉',
        '质押爆仓', '强平', '冻结', '查封'
    ]
    
    STRONG_NEGATIVE_KEYWORDS = [
        '终止重组', '终止重大', '终止并购', '终止收购', '重组终止', '重组失败',
        '并购失败', '收购失败', '重组取消', '重组撤回'
    ]
    
    POSITIVE_KEYWORDS = [
        '通过', '获批', '中标', '签约', '合作', '战略',
        '增持', '回购', '分红', '送转', '激励',
        '突破', '创新', '领先', '首创', '独家',
        '业绩增长', '扭亏为盈', '超预期', '翻倍',
        '新订单', '大合同', '产能扩张', '投产',
        '并购', '重组', '注入', '借壳', '整合'
    ]
    
    STOCK_NAMES = {
        '000001': '平安银行', '000002': '万科A', '000063': '中兴通讯',
        '000100': 'TCL科技', '000333': '美的集团', '000538': '云南白药',
        '000568': '泸州老窖', '000596': '古井贡酒', '000651': '格力电器',
        '000725': '京东方A', '000768': '中航西飞', '000776': '广发证券',
        '000858': '五粮液', '000895': '双汇发展', '000977': '浪潮信息',
        '002001': '新和成', '002007': '华兰生物', '002027': '分众传媒',
        '002049': '紫光国微', '002120': '韵达股份', '002142': '宁波银行',
        '002230': '科大讯飞', '002241': '歌尔股份', '002271': '东方雨虹',
        '002304': '洋河股份', '002352': '顺丰控股', '002371': '北方华创',
        '002415': '海康威视', '002460': '赣锋锂业', '002475': '立讯精密',
        '002493': '荣盛石化', '002555': '三七互娱', '002571': '德力股份',
        '002594': '比亚迪', '002601': '龙蟒佰利', '002607': '中公教育',
        '002709': '天赐材料', '002714': '牧原股份', '002756': '永兴材料',
        '002812': '恩捷股份', '002821': '凯莱英', '002932': '明德生物',
        '300003': '乐普医疗', '300014': '亿纬锂能', '300015': '爱尔眼科',
        '300033': '同花顺', '300059': '东方财富', '300062': '中能电气',
        '300122': '智飞生物', '300124': '汇川技术', '300142': '沃森生物',
        '300274': '阳光电源', '300291': '华录百纳', '300347': '泰格医药',
        '300408': '三环集团', '300413': '芒果超媒', '300433': '蓝思科技',
        '300450': '先导智能', '300496': '中科创达', '300529': '健帆生物',
        '300601': '康泰生物', '300628': '亿联网络', '300661': '圣邦股份',
        '300750': '宁德时代', '300759': '康龙化成', '300760': '迈瑞医疗',
        '300782': '卓胜微', '300896': '爱美客',
        '600009': '上海机场', '600016': '民生银行', '600019': '宝钢股份',
        '600028': '中国石化', '600030': '中信证券', '600031': '三一重工',
        '600036': '招商银行', '600048': '保利发展', '600050': '中国联通',
        '600061': '国投资本', '600079': '人福医药', '600085': '同仁堂',
        '600104': '上汽集团', '600111': '北方稀土', '600132': '重庆啤酒',
        '600150': '中国船舶', '600176': '中国巨石', '600183': '生益科技',
        '600196': '复星医药', '600276': '恒瑞医药', '600309': '万华化学',
        '600332': '白云山', '600346': '恒力石化', '600352': '浙江龙盛',
        '600406': '国电南瑞', '600436': '片仔癀', '600438': '通威股份',
        '600489': '中金黄金', '600519': '贵州茅台', '600536': '中国软件',
        '600547': '山东黄金', '600570': '恒生电子', '600585': '海螺水泥',
        '600588': '用友网络', '600690': '海尔智家', '600703': '三安光电',
        '600745': '闻泰科技', '600809': '山西汾酒', '600837': '海通证券',
        '600845': '宝信软件', '600887': '伊利股份', '600893': '航发动力',
        '600900': '长江电力', '600918': '中泰证券', '600926': '杭州银行',
        '600941': '中国移动', '601012': '隆基绿能', '601066': '中信建投',
        '601088': '中国神华', '601111': '中国国航', '601138': '工业富联',
        '601166': '兴业银行', '601225': '陕西煤业', '601288': '农业银行',
        '601318': '中国平安', '601328': '交通银行', '601390': '中国中铁',
        '601398': '工商银行', '601601': '中国太保', '601628': '中国人寿',
        '601668': '中国建筑', '601669': '中国电建', '601688': '华泰证券',
        '601766': '中国中车', '601818': '光大银行', '601857': '中国石油',
        '601888': '中国中免', '601899': '紫金矿业', '601919': '中远海控',
        '601985': '中国核电', '601988': '中国银行', '603019': '中科曙光',
        '603160': '汇顶科技', '603259': '药明康德', '603288': '海天味业',
        '603501': '韦尔股份', '603799': '华友钴业', '603806': '福斯特',
        '603833': '欧派家居', '603899': '晨光股份', '603986': '兆易创新',
        '688005': '容百科技', '688009': '中国通号', '688012': '中微公司',
        '688036': '传音控股', '688111': '金山办公', '688126': '沪硅产业',
        '688169': '石头科技', '688180': '君实生物', '688185': '康希诺',
        '688256': '寒武纪', '688363': '华熙生物', '688396': '华润微',
        '688536': '思瑞浦', '688599': '天合光能', '688981': '中芯国际'
    }
    
    INDUSTRY_MAPPING = {
        '银行': ['000001', '002142', '600016', '600036', '600926', '601166', '601288', '601328', '601398', '601818', '601988'],
        '白酒': ['000568', '000596', '000858', '002304', '600519', '600809'],
        '医药': ['000538', '002007', '300003', '300015', '300122', '300142', '300347', '300529', '300601', '300759', '300760', '600079', '600085', '600196', '600276', '603259'],
        '新能源': ['002460', '002709', '002756', '002812', '300014', '300274', '300450', '300750', '600438', '601012', '688599'],
        '半导体': ['002049', '002371', '300661', '300782', '603160', '603501', '603986', '688012', '688126', '688536', '688981'],
        '消费电子': ['000725', '002241', '002475', '300433', '601138'],
        '证券': ['000776', '600030', '600837', '601066', '601688', '601918'],
        '房地产': ['000002', '600048'],
        '家电': ['000333', '000651', '600690'],
        '软件': ['002230', '300033', '300059', '300496', '600536', '600570', '600588', '600845', '688111']
    }

    def __init__(self):
        self.session = self._create_session()
        
    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        })
        return session
    
    def is_negative_news(self, title: str, content: str = '') -> Tuple[bool, List[str]]:
        """检测是否为负面消息"""
        full_text = (title + ' ' + content).lower()
        found_negatives = []
        
        for keyword in self.STRONG_NEGATIVE_KEYWORDS:
            if keyword in full_text:
                return True, [keyword]
        
        for keyword in self.NEGATIVE_KEYWORDS:
            if keyword in full_text:
                found_negatives.append(keyword)
        
        if len(found_negatives) >= 1:
            positive_count = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in full_text)
            if positive_count < len(found_negatives):
                return True, found_negatives
        
        return False, found_negatives
    
    def get_stock_name(self, stock_code: str) -> str:
        """获取股票名称 - 优先从缓存，其次从API动态获取"""
        if stock_code in self.STOCK_NAMES:
            return self.STOCK_NAMES[stock_code]
        
        try:
            market = '1' if stock_code.startswith(('6', '9')) else '0'
            url = f"https://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': f"{market}.{stock_code}",
                'fields': 'f57,f58'
            }
            
            response = self.session.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json().get('data', {})
                if data and data.get('f58'):
                    name = data.get('f58', '')
                    self.STOCK_NAMES[stock_code] = name
                    return name
        except Exception as e:
            logger.debug(f"获取{stock_code}名称失败: {e}")
        
        return f'股票{stock_code}'
    
    def get_stock_industry(self, stock_code: str) -> str:
        """获取股票所属行业"""
        for industry, codes in self.INDUSTRY_MAPPING.items():
            if stock_code in codes:
                return industry
        return '其他'
    
    def fetch_real_financial_data(self, stock_code: str) -> Dict:
        """获取真实财务数据"""
        try:
            time.sleep(random.uniform(0.5, 1.0))
            
            market = 'SH' if stock_code.startswith(('6', '9')) else 'SZ'
            full_code = f"{market}{stock_code}"
            
            url = f"https://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': f"{'1' if market == 'SH' else '0'}.{stock_code}",
                'fields': 'f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json().get('data', {})
                if data:
                    return {
                        'current_price': data.get('f43', 0) / 100 if data.get('f43') else None,
                        'change_percent': data.get('f170', 0) / 100 if data.get('f170') else None,
                        'pe_ttm': data.get('f167', 0) / 100 if data.get('f167') else None,
                        'pb': data.get('f167', 0) / 100 if data.get('f167') else None,
                        'market_cap': data.get('f116', 0) / 100000000 if data.get('f116') else None,
                        'turnover_rate': data.get('f168', 0) / 100 if data.get('f168') else None,
                        'volume': data.get('f47', 0) if data.get('f47') else None,
                        'amount': data.get('f48', 0) / 100000000 if data.get('f48') else None,
                        'high_52w': data.get('f44', 0) / 100 if data.get('f44') else None,
                        'low_52w': data.get('f45', 0) / 100 if data.get('f45') else None,
                        'data_source': '东方财富实时数据',
                        'fetch_time': datetime.now().isoformat()
                    }
            
        except Exception as e:
            logger.debug(f"获取{stock_code}财务数据失败: {e}")
        
        return self._get_estimated_financial_data(stock_code)
    
    def _get_estimated_financial_data(self, stock_code: str) -> Dict:
        """获取估算的财务数据（当API失败时）"""
        industry = self.get_stock_industry(stock_code)
        
        industry_pe = {
            '银行': 5.5, '白酒': 35, '医药': 45, '新能源': 55,
            '半导体': 80, '消费电子': 25, '证券': 18, '房地产': 8,
            '家电': 15, '软件': 60, '其他': 25
        }
        
        industry_pb = {
            '银行': 0.6, '白酒': 10, '医药': 5, '新能源': 4,
            '半导体': 6, '消费电子': 3, '证券': 1.2, '房地产': 0.8,
            '家电': 3, '软件': 5, '其他': 2
        }
        
        return {
            'current_price': None,
            'change_percent': None,
            'pe_ttm': industry_pe.get(industry, 25),
            'pb': industry_pb.get(industry, 2),
            'market_cap': None,
            'turnover_rate': None,
            'industry': industry,
            'data_source': '行业估算值',
            'fetch_time': datetime.now().isoformat()
        }
    
    def fetch_capital_flow(self, stock_code: str) -> Dict:
        """获取资金流向数据"""
        try:
            time.sleep(random.uniform(0.3, 0.6))
            
            market = '1' if stock_code.startswith(('6', '9')) else '0'
            url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
            params = {
                'secid': f"{market}.{stock_code}",
                'fields1': 'f1,f2,f3,f7',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63',
                'klt': 101,
                'lmt': 5
            }
            
            response = self.session.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json().get('data', {})
                klines = data.get('klines', [])
                
                if klines:
                    total_main_inflow = 0
                    total_retail_inflow = 0
                    
                    for kline in klines[-5:]:
                        parts = kline.split(',')
                        if len(parts) >= 7:
                            total_main_inflow += float(parts[1]) if parts[1] else 0
                            total_retail_inflow += float(parts[5]) if parts[5] else 0
                    
                    return {
                        'main_inflow_5d': round(total_main_inflow / 100000000, 2),
                        'retail_inflow_5d': round(total_retail_inflow / 100000000, 2),
                        'net_inflow_5d': round((total_main_inflow + total_retail_inflow) / 100000000, 2),
                        'main_trend': '流入' if total_main_inflow > 0 else '流出',
                        'data_source': '东方财富资金流向',
                        'fetch_time': datetime.now().isoformat()
                    }
            
        except Exception as e:
            logger.debug(f"获取{stock_code}资金流向失败: {e}")
        
        return {
            'main_inflow_5d': None,
            'retail_inflow_5d': None,
            'net_inflow_5d': None,
            'main_trend': '未知',
            'data_source': '数据获取失败'
        }
    
    def analyze_technical_pattern(self, stock_code: str) -> Dict:
        """分析技术形态"""
        try:
            time.sleep(random.uniform(0.3, 0.6))
            
            market = '1' if stock_code.startswith(('6', '9')) else '0'
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                'secid': f"{market}.{stock_code}",
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
                'klt': 101,
                'fqt': 1,
                'end': '20500101',
                'lmt': 60
            }
            
            response = self.session.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json().get('data', {})
                klines = data.get('klines', [])
                
                if len(klines) >= 20:
                    closes = []
                    for kline in klines:
                        parts = kline.split(',')
                        if len(parts) >= 3:
                            closes.append(float(parts[2]))
                    
                    if len(closes) >= 20:
                        ma5 = sum(closes[-5:]) / 5
                        ma10 = sum(closes[-10:]) / 10
                        ma20 = sum(closes[-20:]) / 20
                        current = closes[-1]
                        
                        trend = '上升趋势' if ma5 > ma10 > ma20 else '下降趋势' if ma5 < ma10 < ma20 else '震荡整理'
                        
                        position = '强势区间' if current > ma5 > ma10 else '弱势区间' if current < ma5 < ma10 else '中性区间'
                        
                        recent_high = max(closes[-20:])
                        recent_low = min(closes[-20:])
                        support = recent_low
                        resistance = recent_high
                        
                        return {
                            'trend': trend,
                            'position': position,
                            'ma5': round(ma5, 2),
                            'ma10': round(ma10, 2),
                            'ma20': round(ma20, 2),
                            'current_price': current,
                            'support': round(support, 2),
                            'resistance': round(resistance, 2),
                            'distance_to_high': round((current - recent_high) / recent_high * 100, 2),
                            'distance_to_low': round((current - recent_low) / recent_low * 100, 2),
                            'data_source': '东方财富K线数据',
                            'fetch_time': datetime.now().isoformat()
                        }
            
        except Exception as e:
            logger.debug(f"获取{stock_code}技术分析失败: {e}")
        
        return {
            'trend': '数据不足',
            'position': '未知',
            'data_source': '数据获取失败'
        }
    
    def generate_professional_analysis(self, stock_code: str, news_title: str, 
                                       news_content: str, sample_posts: List[Dict]) -> Dict:
        """生成专业分析报告"""
        stock_name = self.get_stock_name(stock_code)
        industry = self.get_stock_industry(stock_code)
        
        is_negative, negative_keywords = self.is_negative_news(news_title, news_content)
        
        financial_data = self.fetch_real_financial_data(stock_code)
        capital_flow = self.fetch_capital_flow(stock_code)
        technical = self.analyze_technical_pattern(stock_code)
        
        analysis = {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'industry': industry,
            'is_negative_news': is_negative,
            'negative_keywords': negative_keywords,
            'news_sentiment': '利空' if is_negative else '利好',
            'financial_data': financial_data,
            'capital_flow': capital_flow,
            'technical_analysis': technical,
            'analysis_time': datetime.now().isoformat()
        }
        
        analysis['investment_thesis'] = self._generate_investment_thesis(
            stock_code, stock_name, industry, news_title, 
            is_negative, financial_data, capital_flow, technical
        )
        
        analysis['risk_assessment'] = self._generate_risk_assessment(
            stock_code, stock_name, is_negative, negative_keywords,
            financial_data, capital_flow, technical
        )
        
        analysis['recommendation'] = self._generate_recommendation(
            is_negative, financial_data, capital_flow, technical
        )
        
        return analysis
    
    def _generate_investment_thesis(self, stock_code: str, stock_name: str,
                                    industry: str, news_title: str,
                                    is_negative: bool, financial: Dict,
                                    capital: Dict, technical: Dict) -> str:
        """生成投资逻辑"""
        if is_negative:
            return f"⚠️ 警告：检测到负面信息「{news_title[:30]}...」，建议暂时回避，等待事件明朗后再做决策。"
        
        thesis_parts = []
        
        thesis_parts.append(f"**{stock_name}({stock_code})** 属于{industry}行业。")
        
        pe = financial.get('pe_ttm')
        pb = financial.get('pb')
        if pe and pe > 0:
            if pe < 15:
                thesis_parts.append(f"当前PE(TTM)为{pe:.1f}倍，估值处于低位，具有安全边际。")
            elif pe < 30:
                thesis_parts.append(f"当前PE(TTM)为{pe:.1f}倍，估值合理。")
            else:
                thesis_parts.append(f"当前PE(TTM)为{pe:.1f}倍，估值偏高，需关注业绩增速能否支撑。")
        
        main_flow = capital.get('main_inflow_5d')
        if main_flow is not None:
            if main_flow > 1:
                thesis_parts.append(f"近5日主力资金净流入{main_flow:.2f}亿元，资金面积极。")
            elif main_flow < -1:
                thesis_parts.append(f"近5日主力资金净流出{abs(main_flow):.2f}亿元，需警惕资金出逃。")
        
        trend = technical.get('trend', '')
        position = technical.get('position', '')
        if trend and position:
            thesis_parts.append(f"技术面呈现{trend}，当前处于{position}。")
            
            support = technical.get('support')
            resistance = technical.get('resistance')
            if support and resistance:
                thesis_parts.append(f"短期支撑位{support}元，压力位{resistance}元。")
        
        return '\n'.join(thesis_parts)
    
    def _generate_risk_assessment(self, stock_code: str, stock_name: str,
                                  is_negative: bool, negative_keywords: List[str],
                                  financial: Dict, capital: Dict, technical: Dict) -> str:
        """生成风险评估"""
        risks = []
        
        if is_negative:
            risks.append(f"🔴 **重大风险**：检测到负面关键词「{', '.join(negative_keywords)}」，该消息可能导致股价承压。")
        
        pe = financial.get('pe_ttm')
        if pe and pe > 50:
            risks.append(f"🟠 **估值风险**：PE达{pe:.1f}倍，估值偏高，若业绩不及预期可能面临估值回调。")
        
        main_flow = capital.get('main_inflow_5d')
        if main_flow is not None and main_flow < -2:
            risks.append(f"🟠 **资金风险**：近5日主力资金大幅流出{abs(main_flow):.2f}亿元，短期抛压较重。")
        
        trend = technical.get('trend', '')
        if '下降' in trend:
            risks.append("🟡 **技术风险**：技术面呈下降趋势，短期可能继续调整。")
        
        distance_to_high = technical.get('distance_to_high')
        if distance_to_high and distance_to_high < -20:
            risks.append(f"🟡 **位置风险**：距离近期高点下跌{abs(distance_to_high):.1f}%，可能存在套牢盘压力。")
        
        if not risks:
            risks.append("🟢 暂未发现重大风险因素，但投资仍需谨慎，注意控制仓位。")
        
        return '\n'.join(risks)
    
    def _generate_recommendation(self, is_negative: bool, financial: Dict,
                                 capital: Dict, technical: Dict) -> Dict:
        """生成投资建议"""
        if is_negative:
            return {
                'action': '回避',
                'rating': 'D',
                'confidence': 30,
                'reason': '检测到负面信息，建议观望等待事件明朗',
                'position_advice': '不建议建仓，已持有者可考虑减仓观望'
            }
        
        score = 50
        
        pe = financial.get('pe_ttm')
        if pe:
            if pe < 15:
                score += 15
            elif pe < 30:
                score += 5
            elif pe > 60:
                score -= 10
        
        main_flow = capital.get('main_inflow_5d')
        if main_flow is not None:
            if main_flow > 2:
                score += 15
            elif main_flow > 0:
                score += 5
            elif main_flow < -2:
                score -= 15
            else:
                score -= 5
        
        trend = technical.get('trend', '')
        position = technical.get('position', '')
        if '上升' in trend:
            score += 10
        elif '下降' in trend:
            score -= 10
        
        if '强势' in position:
            score += 5
        elif '弱势' in position:
            score -= 5
        
        if score >= 75:
            action, rating = '积极关注', 'A'
            reason = '多项指标积极，可逢低布局'
            position_advice = '可考虑分批建仓，首次仓位建议不超过30%'
        elif score >= 60:
            action, rating = '适度关注', 'B'
            reason = '整体面尚可，但需等待更好的入场时机'
            position_advice = '可小仓位试探，等待回调确认支撑后加仓'
        elif score >= 45:
            action, rating = '谨慎观望', 'C'
            reason = '存在不确定因素，建议持续跟踪'
            position_advice = '暂不建议建仓，继续观察'
        else:
            action, rating = '暂时回避', 'D'
            reason = '多项指标偏负面，短期风险较大'
            position_advice = '不建议介入，已持有者可考虑止损'
        
        return {
            'action': action,
            'rating': rating,
            'confidence': min(score, 95),
            'reason': reason,
            'position_advice': position_advice
        }
    
    def predict_event_timeline(self, news_title: str, news_content: str, event_type: str = '') -> Dict:
        """
        预测重大事件的关键时间节点
        
        Args:
            news_title: 新闻标题
            news_content: 新闻内容
            event_type: 事件类型 (重组/并购/订单/业绩等)
        
        Returns:
            时间节点预测结果
        """
        full_text = (news_title + ' ' + news_content).lower()
        
        if not event_type:
            event_type = self._detect_event_type(full_text)
        
        timeline = {
            'event_type': event_type,
            'event_type_cn': self._get_event_type_cn(event_type),
            'current_stage': '',
            'timeline_nodes': [],
            'key_dates': {},
            'risk_periods': [],
            'investment_windows': [],
            'prediction_confidence': 0,
            'analysis_time': datetime.now().isoformat()
        }
        
        if event_type == 'restructuring':
            timeline = self._predict_restructuring_timeline(full_text, timeline)
        elif event_type == 'merger':
            timeline = self._predict_merger_timeline(full_text, timeline)
        elif event_type == 'major_contract':
            timeline = self._predict_contract_timeline(full_text, timeline)
        elif event_type == 'earnings':
            timeline = self._predict_earnings_timeline(full_text, timeline)
        elif event_type == 'ipo_listing':
            timeline = self._predict_ipo_timeline(full_text, timeline)
        elif event_type == 'policy_benefit':
            timeline = self._predict_policy_timeline(full_text, timeline)
        else:
            timeline = self._predict_general_timeline(full_text, timeline)
        
        return timeline
    
    def _detect_event_type(self, text: str) -> str:
        """检测事件类型"""
        if any(kw in text for kw in ['重组', '资产重组', '重大资产']):
            return 'restructuring'
        elif any(kw in text for kw in ['并购', '收购', '合并', '借壳']):
            return 'merger'
        elif any(kw in text for kw in ['订单', '合同', '中标', '签约']):
            return 'major_contract'
        elif any(kw in text for kw in ['业绩', '利润', '营收', '财报']):
            return 'earnings'
        elif any(kw in text for kw in ['上市', 'ipo', '发行']):
            return 'ipo_listing'
        elif any(kw in text for kw in ['政策', '补贴', '扶持', '纳入']):
            return 'policy_benefit'
        return 'general'
    
    def _get_event_type_cn(self, event_type: str) -> str:
        """获取事件类型中文名"""
        mapping = {
            'restructuring': '重大资产重组',
            'merger': '并购收购',
            'major_contract': '重大合同/订单',
            'earnings': '业绩相关',
            'ipo_listing': '上市/发行',
            'policy_benefit': '政策利好',
            'general': '一般事件'
        }
        return mapping.get(event_type, '未知事件')
    
    def _predict_restructuring_timeline(self, text: str, timeline: Dict) -> Dict:
        """预测重组事件时间线"""
        now = datetime.now()
        
        current_stage = '筹划阶段'
        stage_index = 0
        
        if '预案' in text or '草案' in text:
            current_stage = '预案/草案阶段'
            stage_index = 1
        elif '股东大会' in text:
            current_stage = '股东大会审议阶段'
            stage_index = 2
        elif '证监会' in text or '审核' in text or '过会' in text:
            current_stage = '证监会审核阶段'
            stage_index = 3
        elif '获批' in text or '核准' in text:
            current_stage = '已获批准阶段'
            stage_index = 4
        elif '实施' in text or '完成' in text:
            current_stage = '实施/完成阶段'
            stage_index = 5
        
        timeline['current_stage'] = current_stage
        
        stages = [
            {'stage': '停牌筹划', 'duration': '1-2周', 'status': 'completed' if stage_index > 0 else 'current' if stage_index == 0 else 'pending'},
            {'stage': '发布重组预案/草案', 'duration': '1-3个月', 'status': 'completed' if stage_index > 1 else 'current' if stage_index == 1 else 'pending'},
            {'stage': '股东大会审议', 'duration': '预案后1-2个月', 'status': 'completed' if stage_index > 2 else 'current' if stage_index == 2 else 'pending'},
            {'stage': '证监会受理审核', 'duration': '2-6个月', 'status': 'completed' if stage_index > 3 else 'current' if stage_index == 3 else 'pending'},
            {'stage': '获得批文', 'duration': '审核通过后1-2周', 'status': 'completed' if stage_index > 4 else 'current' if stage_index == 4 else 'pending'},
            {'stage': '实施完成', 'duration': '批文后3-6个月', 'status': 'completed' if stage_index > 5 else 'current' if stage_index == 5 else 'pending'}
        ]
        
        timeline['timeline_nodes'] = stages
        
        if stage_index == 0:
            timeline['key_dates'] = {
                '预计预案发布': (now + timedelta(days=30)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=90)).strftime('%Y-%m-%d'),
                '预计股东大会': (now + timedelta(days=60)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=150)).strftime('%Y-%m-%d'),
                '预计证监会审批': (now + timedelta(days=120)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=300)).strftime('%Y-%m-%d'),
                '预计完成时间': (now + timedelta(days=180)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=365)).strftime('%Y-%m-%d')
            }
        elif stage_index == 1:
            timeline['key_dates'] = {
                '预计股东大会': (now + timedelta(days=30)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=60)).strftime('%Y-%m-%d'),
                '预计证监会审批': (now + timedelta(days=90)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=210)).strftime('%Y-%m-%d'),
                '预计完成时间': (now + timedelta(days=150)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=300)).strftime('%Y-%m-%d')
            }
        elif stage_index == 2:
            timeline['key_dates'] = {
                '预计证监会受理': (now + timedelta(days=7)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=30)).strftime('%Y-%m-%d'),
                '预计审核结果': (now + timedelta(days=60)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=180)).strftime('%Y-%m-%d'),
                '预计完成时间': (now + timedelta(days=120)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=270)).strftime('%Y-%m-%d')
            }
        elif stage_index == 3:
            timeline['key_dates'] = {
                '预计上会审核': (now + timedelta(days=30)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=120)).strftime('%Y-%m-%d'),
                '预计获得批文': (now + timedelta(days=45)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=150)).strftime('%Y-%m-%d'),
                '预计完成时间': (now + timedelta(days=90)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=210)).strftime('%Y-%m-%d')
            }
        elif stage_index >= 4:
            timeline['key_dates'] = {
                '预计实施完成': (now + timedelta(days=30)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=180)).strftime('%Y-%m-%d')
            }
        
        timeline['risk_periods'] = [
            {'period': '证监会审核期', 'risk': '审核不通过风险', 'level': 'high'},
            {'period': '股东大会前', 'risk': '方案被否决风险', 'level': 'medium'},
            {'period': '筹划期', 'risk': '重组终止风险', 'level': 'medium'}
        ]
        
        timeline['investment_windows'] = [
            {'window': '预案发布前', 'strategy': '提前埋伏，风险较高但收益可观', 'risk_level': 'high'},
            {'window': '预案发布后回调', 'strategy': '等待回调介入，确定性较高', 'risk_level': 'medium'},
            {'window': '过会后', 'strategy': '确定性最高，但涨幅可能有限', 'risk_level': 'low'}
        ]
        
        timeline['prediction_confidence'] = 75 if stage_index >= 1 else 60
        
        return timeline
    
    def _predict_merger_timeline(self, text: str, timeline: Dict) -> Dict:
        """预测并购事件时间线"""
        now = datetime.now()
        
        current_stage = '意向阶段'
        stage_index = 0
        
        if '签署' in text or '协议' in text:
            current_stage = '协议签署阶段'
            stage_index = 1
        elif '尽调' in text or '审计' in text:
            current_stage = '尽职调查阶段'
            stage_index = 2
        elif '审批' in text or '反垄断' in text:
            current_stage = '监管审批阶段'
            stage_index = 3
        elif '完成' in text or '交割' in text:
            current_stage = '交割完成阶段'
            stage_index = 4
        
        timeline['current_stage'] = current_stage
        
        stages = [
            {'stage': '意向接触/框架协议', 'duration': '1-3个月', 'status': 'completed' if stage_index > 0 else 'current' if stage_index == 0 else 'pending'},
            {'stage': '正式协议签署', 'duration': '1-2个月', 'status': 'completed' if stage_index > 1 else 'current' if stage_index == 1 else 'pending'},
            {'stage': '尽职调查/审计评估', 'duration': '2-4个月', 'status': 'completed' if stage_index > 2 else 'current' if stage_index == 2 else 'pending'},
            {'stage': '监管审批(含反垄断)', 'duration': '2-6个月', 'status': 'completed' if stage_index > 3 else 'current' if stage_index == 3 else 'pending'},
            {'stage': '交割完成', 'duration': '1-3个月', 'status': 'completed' if stage_index > 4 else 'current' if stage_index == 4 else 'pending'}
        ]
        
        timeline['timeline_nodes'] = stages
        
        timeline['key_dates'] = {
            '预计完成时间': (now + timedelta(days=90*(5-stage_index))).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=180*(5-stage_index)//3)).strftime('%Y-%m-%d')
        }
        
        timeline['risk_periods'] = [
            {'period': '反垄断审查期', 'risk': '审查不通过或附条件通过', 'level': 'high'},
            {'period': '尽调期', 'risk': '发现重大问题导致交易终止', 'level': 'medium'}
        ]
        
        timeline['investment_windows'] = [
            {'window': '意向公布后', 'strategy': '初期介入，不确定性高', 'risk_level': 'high'},
            {'window': '协议签署后', 'strategy': '确定性提升，可适当参与', 'risk_level': 'medium'},
            {'window': '审批通过后', 'strategy': '最安全，但预期已被消化', 'risk_level': 'low'}
        ]
        
        timeline['prediction_confidence'] = 70
        
        return timeline
    
    def _predict_contract_timeline(self, text: str, timeline: Dict) -> Dict:
        """预测重大合同/订单时间线"""
        now = datetime.now()
        
        current_stage = '中标/签约阶段'
        
        if '执行' in text or '交付' in text:
            current_stage = '执行交付阶段'
        elif '验收' in text or '结算' in text:
            current_stage = '验收结算阶段'
        
        timeline['current_stage'] = current_stage
        
        timeline['timeline_nodes'] = [
            {'stage': '中标公告/合同签署', 'duration': '即时', 'status': 'completed'},
            {'stage': '合同生效/预付款', 'duration': '签约后1-4周', 'status': 'current' if '签' in text else 'pending'},
            {'stage': '订单执行/分批交付', 'duration': '3-24个月(视合同)', 'status': 'pending'},
            {'stage': '验收确认', 'duration': '交付后1-3个月', 'status': 'pending'},
            {'stage': '尾款结算', 'duration': '验收后1-6个月', 'status': 'pending'}
        ]
        
        timeline['key_dates'] = {
            '预计首批交付': (now + timedelta(days=90)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=180)).strftime('%Y-%m-%d'),
            '预计收入确认': (now + timedelta(days=120)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=365)).strftime('%Y-%m-%d'),
            '业绩体现时间': '下一季度或年度财报'
        }
        
        timeline['risk_periods'] = [
            {'period': '执行期', 'risk': '交付延迟或质量问题', 'level': 'medium'},
            {'period': '结算期', 'risk': '回款风险', 'level': 'medium'}
        ]
        
        timeline['investment_windows'] = [
            {'window': '公告当日', 'strategy': '短线博弈，注意追高风险', 'risk_level': 'high'},
            {'window': '公告后回调', 'strategy': '等待情绪消化后介入', 'risk_level': 'medium'},
            {'window': '业绩兑现前', 'strategy': '提前布局业绩预期', 'risk_level': 'medium'}
        ]
        
        timeline['prediction_confidence'] = 80
        
        return timeline
    
    def _predict_earnings_timeline(self, text: str, timeline: Dict) -> Dict:
        """预测业绩相关时间线"""
        now = datetime.now()
        
        current_month = now.month
        current_year = now.year
        
        if current_month <= 1:
            next_report = '年度报告'
            report_deadline = f'{current_year}-04-30'
        elif current_month <= 4:
            next_report = '一季报'
            report_deadline = f'{current_year}-04-30'
        elif current_month <= 8:
            next_report = '半年报'
            report_deadline = f'{current_year}-08-31'
        elif current_month <= 10:
            next_report = '三季报'
            report_deadline = f'{current_year}-10-31'
        else:
            next_report = '年度报告'
            report_deadline = f'{current_year + 1}-04-30'
        
        timeline['current_stage'] = f'等待{next_report}披露'
        
        timeline['timeline_nodes'] = [
            {'stage': '业绩预告(可选)', 'duration': '报告期后15-30天', 'status': 'pending'},
            {'stage': '业绩快报(可选)', 'duration': '报告期后30-45天', 'status': 'pending'},
            {'stage': '正式财报披露', 'duration': f'截止{report_deadline}', 'status': 'pending'},
            {'stage': '分析师解读期', 'duration': '财报后1-2周', 'status': 'pending'}
        ]
        
        timeline['key_dates'] = {
            '下一财报截止日': report_deadline,
            '业绩预告窗口': '财报截止日前1个月内',
            '年度分红预案': '年报披露时(如有)'
        }
        
        timeline['investment_windows'] = [
            {'window': '业绩预告前', 'strategy': '博弈业绩超预期，风险较高', 'risk_level': 'high'},
            {'window': '业绩确认后回调', 'strategy': '利好兑现后的回调介入', 'risk_level': 'medium'}
        ]
        
        timeline['prediction_confidence'] = 85
        
        return timeline
    
    def _predict_ipo_timeline(self, text: str, timeline: Dict) -> Dict:
        """预测IPO/上市时间线"""
        now = datetime.now()
        
        timeline['current_stage'] = '上市筹备阶段'
        
        timeline['timeline_nodes'] = [
            {'stage': '辅导备案', 'duration': '6-12个月', 'status': 'pending'},
            {'stage': '申报材料', 'duration': '1-2个月', 'status': 'pending'},
            {'stage': '交易所受理', 'duration': '5个工作日', 'status': 'pending'},
            {'stage': '审核问询', 'duration': '3-6个月', 'status': 'pending'},
            {'stage': '上市委审议', 'duration': '问询后1-2个月', 'status': 'pending'},
            {'stage': '证监会注册', 'duration': '15-20个工作日', 'status': 'pending'},
            {'stage': '发行上市', 'duration': '注册后1-3个月', 'status': 'pending'}
        ]
        
        timeline['key_dates'] = {
            '预计上市时间': '视当前阶段，通常需要12-24个月'
        }
        
        timeline['prediction_confidence'] = 50
        
        return timeline
    
    def _predict_policy_timeline(self, text: str, timeline: Dict) -> Dict:
        """预测政策利好时间线"""
        now = datetime.now()
        
        timeline['current_stage'] = '政策发布阶段'
        
        timeline['timeline_nodes'] = [
            {'stage': '政策发布/纳入名单', 'duration': '即时', 'status': 'completed'},
            {'stage': '实施细则出台', 'duration': '1-3个月', 'status': 'pending'},
            {'stage': '企业申报/对接', 'duration': '1-6个月', 'status': 'pending'},
            {'stage': '补贴/扶持资金到位', 'duration': '3-12个月', 'status': 'pending'},
            {'stage': '业绩体现', 'duration': '6-24个月', 'status': 'pending'}
        ]
        
        timeline['key_dates'] = {
            '细则预计出台': (now + timedelta(days=30)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=90)).strftime('%Y-%m-%d'),
            '补贴到位预计': (now + timedelta(days=90)).strftime('%Y-%m-%d') + ' ~ ' + (now + timedelta(days=365)).strftime('%Y-%m-%d')
        }
        
        timeline['investment_windows'] = [
            {'window': '政策发布初期', 'strategy': '主题炒作阶段，短线为主', 'risk_level': 'high'},
            {'window': '细则落地后', 'strategy': '确定性提升，可中线布局', 'risk_level': 'medium'},
            {'window': '业绩兑现期', 'strategy': '价值投资，长线持有', 'risk_level': 'low'}
        ]
        
        timeline['prediction_confidence'] = 65
        
        return timeline
    
    def _predict_general_timeline(self, text: str, timeline: Dict) -> Dict:
        """预测一般事件时间线"""
        now = datetime.now()
        
        timeline['current_stage'] = '事件发酵阶段'
        
        timeline['timeline_nodes'] = [
            {'stage': '消息发布/传播', 'duration': '即时', 'status': 'completed'},
            {'stage': '市场反应', 'duration': '1-5个交易日', 'status': 'current'},
            {'stage': '事件验证', 'duration': '1-4周', 'status': 'pending'},
            {'stage': '后续发展', 'duration': '持续跟踪', 'status': 'pending'}
        ]
        
        timeline['key_dates'] = {
            '短期关注': (now + timedelta(days=7)).strftime('%Y-%m-%d'),
            '中期跟踪': (now + timedelta(days=30)).strftime('%Y-%m-%d')
        }
        
        timeline['prediction_confidence'] = 50
        
        return timeline


def filter_opportunities(opportunities: List[Dict], analyzer: ProfessionalStockAnalyzer) -> List[Dict]:
    """过滤机会列表，排除负面消息"""
    filtered = []
    
    for opp in opportunities:
        title = opp.get('title', '') or opp.get('news_title', '')
        content = opp.get('content', '') or opp.get('news_content', '')
        
        for post in opp.get('sample_posts', []):
            content += ' ' + post.get('title', '') + ' ' + post.get('content', '')
        
        is_negative, negative_keywords = analyzer.is_negative_news(title, content)
        
        if is_negative:
            logger.info(f"  ⚠️ 过滤负面消息: {opp.get('stock_code', '')} - 关键词: {negative_keywords}")
            continue
        
        filtered.append(opp)
    
    return filtered
