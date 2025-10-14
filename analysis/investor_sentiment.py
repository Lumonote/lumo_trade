#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股民情绪分析模块
分析股吧评论、社交媒体讨论等股民情绪指标
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
import re
import unicodedata

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from analysis.dynamic_crawler import DynamicCrawler


class InvestorSentimentAnalyzer:
    """股民情绪分析器"""

    def __init__(self, stock_code):
        """
        初始化股民情绪分析器

        Args:
            stock_code: 股票代码 (例如: '688343', '000001')
        """
        self.stock_code = stock_code
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://guba.eastmoney.com/'
        }

    def get_capital_flow(self):
        """
        获取资金流向数据

        Returns:
            dict: 资金流向数据
        """
        try:
            # 东方财富资金流向API
            url = "http://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"
            params = {
                'lmt': '0',
                'klt': '101',
                'secid': f"{'1' if self.stock_code.startswith('6') else '0'}.{self.stock_code}",
                'fields1': 'f1,f2,f3,f7',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63'
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            if data.get('data') and data['data'].get('klines'):
                latest_data = data['data']['klines'][-1].split(',')

                capital_flow = {
                    'date': latest_data[0] if len(latest_data) > 0 else 'N/A',
                    'main_inflow': float(latest_data[1]) if len(latest_data) > 1 else 0,  # 主力净流入
                    'retail_inflow': float(latest_data[2]) if len(latest_data) > 2 else 0,  # 散户净流入
                    'main_inflow_rate': float(latest_data[3]) if len(latest_data) > 3 else 0,  # 主力净流入率
                    'super_large_inflow': float(latest_data[4]) if len(latest_data) > 4 else 0,  # 超大单净流入
                    'large_inflow': float(latest_data[5]) if len(latest_data) > 5 else 0,  # 大单净流入
                    'medium_inflow': float(latest_data[6]) if len(latest_data) > 6 else 0,  # 中单净流入
                    'small_inflow': float(latest_data[7]) if len(latest_data) > 7 else 0,  # 小单净流入
                }

                # 判断资金流向趋势
                capital_flow['trend'] = '流入' if capital_flow['main_inflow'] > 0 else '流出'
                capital_flow['strength'] = self._classify_capital_strength(capital_flow['main_inflow_rate'])

                return capital_flow

        except Exception as e:
            print(f"⚠️ 获取资金流向失败: {str(e)}")

        return self._get_default_capital_flow()

    def get_market_sentiment(self):
        """
        获取市场情绪指标 (个股)

        Returns:
            dict: 市场情绪数据
        """
        try:
            # 东方财富市场情绪数据
            url = "http://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': f"{'1' if self.stock_code.startswith('6') else '0'}.{self.stock_code}",
                'fields': 'f57,f58,f168,f169,f170,f46,f44,f45,f47,f260,f261,f262'
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            if data.get('data'):
                stock_data = data['data']

                sentiment = {
                    'turnover_rate': stock_data.get('f168', 'N/A'),  # 换手率
                    'volume_ratio': stock_data.get('f169', 'N/A'),  # 量比
                    'amplitude': stock_data.get('f170', 'N/A'),  # 振幅
                    'up_down_ratio': 'N/A',  # 涨跌家数比(需要板块数据)
                    'market_cap_rank': 'N/A',  # 市值排名
                }

                # 换手率情绪判断
                if isinstance(sentiment['turnover_rate'], (int, float)):
                    if sentiment['turnover_rate'] > 10:
                        sentiment['turnover_emotion'] = '活跃'
                    elif sentiment['turnover_rate'] > 5:
                        sentiment['turnover_emotion'] = '正常'
                    else:
                        sentiment['turnover_emotion'] = '低迷'
                else:
                    sentiment['turnover_emotion'] = '未知'

                return sentiment

        except Exception as e:
            print(f"⚠️ 获取市场情绪失败: {str(e)}")

        return self._get_default_market_sentiment()

    def get_overall_market_sentiment(self):
        """
        获取大盘整体情绪 (上证、深证、创业板)

        Returns:
            dict: 大盘情绪数据
        """
        try:
            # 主要指数代码
            indices = {
                'sh000001': {'name': '上证指数', 'secid': '1.000001'},
                'sh000688': {'name': '科创板', 'secid': '1.000688'},  # 科创板主指数（科创50）
                'sz399001': {'name': '深证成指', 'secid': '0.399001'},
                'sz399006': {'name': '创业板指', 'secid': '0.399006'},
            }

            # 根据股票代码推断所属大盘
            def _infer_primary_index(code: str) -> str:
                try:
                    c = code or ''
                    # 先识别科创板（688开头）
                    if c.startswith('688'):
                        return 'sh000688'  # 科创板
                    # 6开头视为上证主板
                    if c.startswith('6'):
                        return 'sh000001'  # 上证指数
                    # 创业板
                    if c.startswith('300'):
                        return 'sz399006'  # 创业板指
                    # 其他默认深证主板/中小板
                    return 'sz399001'
                except Exception:
                    return 'sz399001'

            primary_key = _infer_primary_index(self.stock_code)

            market_data = {}

            for code, info in indices.items():
                try:
                    url = "http://push2.eastmoney.com/api/qt/stock/get"
                    params = {
                        'secid': info['secid'],
                        'fields': 'f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f169,f170'  # 价格、涨跌幅、量比等
                    }

                    response = requests.get(url, params=params, headers=self.headers, timeout=10)
                    data = response.json()

                    if data.get('data'):
                        stock_data = data['data']

                        # 当前价
                        current = stock_data.get('f43', 0)
                        if current:
                            current = current / 1000  # 除以1000转换为正常值

                        # 涨跌幅
                        change_pct = stock_data.get('f170', 0)
                        if isinstance(change_pct, (int, float)):
                            change_pct = round(change_pct / 100, 2)

                        # 量比
                        volume_ratio = stock_data.get('f169', 0)
                        if isinstance(volume_ratio, (int, float)):
                            volume_ratio = round(volume_ratio / 100, 2)

                        market_data[code] = {
                            'name': info['name'],
                            'current': round(current, 2) if current else 'N/A',
                            'change_pct': change_pct if change_pct else 'N/A',
                            'volume_ratio': volume_ratio if volume_ratio else 'N/A',
                        }

                except Exception as e:
                    market_data[code] = {
                        'name': info['name'],
                        'current': 'N/A',
                        'change_pct': 'N/A',
                        'volume_ratio': 'N/A',
                    }

            # 计算整体市场情绪
            valid_changes = [v['change_pct'] for v in market_data.values()
                           if isinstance(v['change_pct'], (int, float))]

            avg_change = None
            primary_change = None
            if valid_changes:
                try:
                    avg_change = sum(valid_changes) / len(valid_changes)
                except Exception:
                    avg_change = None

                # 主指数涨跌（所属大盘）
                pk_data = market_data.get(primary_key, {})
                pc = pk_data.get('change_pct')
                if isinstance(pc, (int, float)):
                    primary_change = pc

                # 情绪评分 (0-100) 基于主指数
                # 涨幅 +3% 对应 100分, -3% 对应 0分
                base_change = primary_change if isinstance(primary_change, (int, float)) else 0
                sentiment_score = round(50 + (base_change / 3.0) * 50, 1)
                sentiment_score = max(0, min(100, sentiment_score))

                # 情绪判断
                if sentiment_score >= 65:
                    overall = '强势上涨'
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
            else:
                sentiment_score = 50
                overall = '数据不足'
                emotion = 'neutral'

            return {
                'indices': market_data,
                'sentiment_score': sentiment_score,
                'overall': overall,
                'emotion': emotion,
                'primary_index': {
                    'key': primary_key,
                    'name': market_data.get(primary_key, {}).get('name', '所属大盘'),
                    'change_pct': primary_change if isinstance(primary_change, (int, float)) else 'N/A',
                },
                'primary_change_pct': round(primary_change, 2) if isinstance(primary_change, (int, float)) else 'N/A',
                'avg_change_pct': round(avg_change, 2) if isinstance(avg_change, (int, float)) else 'N/A',
            }

        except Exception as e:
            print(f"⚠️ 获取大盘情绪失败: {str(e)}")
            return self._get_default_overall_market_sentiment()

    def get_sector_info_and_sentiment(self):
        """
        获取股票所属板块及板块情绪

        Returns:
            dict: 板块信息和情绪数据
        """
        try:
            # 获取股票所属行业/板块
            url = "http://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': f"{'1' if self.stock_code.startswith('6') else '0'}.{self.stock_code}",
                'fields': 'f127,f128'  # 行业相关字段
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            sector_name = 'N/A'
            sector_code = None

            if data.get('data'):
                # f127: 所属行业名称
                sector_name = data['data'].get('f127', 'N/A')

            # 如果无法获取行业名称，返回默认值
            if sector_name == 'N/A' or not sector_name:
                return self._get_default_sector_sentiment()

            # 获取同行业板块行情数据
            try:
                # 东方财富行业板块接口
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

                response = requests.get(sector_url, params=sector_params, headers=self.headers, timeout=10)
                sector_data = response.json()

                sector_sentiment = None

                if sector_data.get('data') and sector_data['data'].get('diff'):
                    sectors = sector_data['data']['diff']

                    # 查找匹配的行业板块
                    for sector in sectors:
                        if sector.get('f14', '') == sector_name:
                            change_pct = sector.get('f3', 0)
                            turnover_rate = sector.get('f8', 0)

                            # 东财行业板块接口 f3/f8 已为百分比数值（如 2.34 表示 2.34%），无需再次 /100
                            if isinstance(change_pct, (int, float)):
                                change_pct = round(change_pct, 2)
                            if isinstance(turnover_rate, (int, float)):
                                turnover_rate = round(turnover_rate, 2)

                            # 计算板块情绪分数
                            # 涨幅 +5% 对应 100分, -5% 对应 0分
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

                            sector_sentiment = {
                                'sector_name': sector_name,
                                'sector_code': sector.get('f12', 'N/A'),
                                'change_pct': change_pct,
                                'turnover_rate': turnover_rate,
                                'sentiment_score': sentiment_score,
                                'overall': overall,
                                'emotion': emotion,
                            }

                            # === 获取板块成分股并识别龙头 ===
                            try:
                                sec_code = sector.get('f12')
                                if sec_code:
                                    constituents_url = "http://push2.eastmoney.com/api/qt/clist/get"
                                    constituents_params = {
                                        'pn': '1',
                                        'pz': '200',
                                        'po': '1',
                                        'np': '1',
                                        'fltt': '2',
                                        'invt': '2',
                                        'fid': 'f3',  # 按涨跌幅排序
                                        'fs': f"b:{sec_code}",  # 板块成分股
                                        'fields': 'f12,f14,f3,f8'  # 代码、名称、涨跌幅、换手率
                                    }

                                    resp2 = requests.get(constituents_url, params=constituents_params, headers=self.headers, timeout=10)
                                    data2 = resp2.json()
                                    if data2.get('data') and data2['data'].get('diff'):
                                        stocks = data2['data']['diff']

                                        # 识别龙头：以当日涨跌幅最高者为龙头候选
                                        leader = None
                                        try:
                                            leader_item = max(stocks, key=lambda x: x.get('f3', -999999))
                                            leader = {
                                                'code': leader_item.get('f12', ''),
                                                'name': leader_item.get('f14', ''),
                                                'change_pct': round(leader_item.get('f3', 0), 2) if isinstance(leader_item.get('f3', 0), (int, float)) else leader_item.get('f3', 'N/A'),
                                                'turnover_rate': round(leader_item.get('f8', 0), 2) if isinstance(leader_item.get('f8', 0), (int, float)) else leader_item.get('f8', 'N/A'),
                                                'is_current_stock': True if leader_item.get('f12', '').endswith(self.stock_code) else False
                                            }
                                        except Exception:
                                            leader = None

                                        if leader:
                                            sector_sentiment['leader_stock'] = leader
                                    # 若无成分股数据，跳过龙头识别
                            except Exception:
                                pass
                            break

                if sector_sentiment:
                    return sector_sentiment

            except Exception as e:
                print(f"   ⚠️  获取板块行情失败: {str(e)}")

            # 如果无法获取板块行情，返回基本信息
            return {
                'sector_name': sector_name,
                'sector_code': 'N/A',
                'change_pct': 'N/A',
                'turnover_rate': 'N/A',
                'sentiment_score': 50,
                'overall': '数据不足',
                'emotion': 'neutral',
            }

        except Exception as e:
            print(f"⚠️ 获取板块情绪失败: {str(e)}")
            return self._get_default_sector_sentiment()

    def get_guba_sentiment(self, limit=50):
        """
        获取股吧情绪 - 使用Playwright爬取动态页面

        Args:
            limit: 采样评论数

        Returns:
            dict: 股吧情绪数据
        """
        # 首先尝试使用Playwright爬取动态网页
        posts = DynamicCrawler.crawl_guba_posts(self.stock_code, limit)

        if not posts:
            print(f"   ⚠️  Playwright爬取失败,尝试API接口")
            return self._get_guba_from_api(limit)

        # 标题规范化工具（全角转半角，去除多余空白）
        def _normalize_text(s: str) -> str:
            if not s:
                return ''
            s = unicodedata.normalize('NFKC', s)
            s = s.strip()
            return s

        # 过滤广告/垃圾帖关键词（不区分大小写）
        spam_keywords = [
            '荐股', '老师', '课程', '培训', '私募', '开户', '佣金', '带盘', '风控',
            '福利', '抽奖', '活动', '推广', '点击', '链接', '加我', '关注', '实盘',
            '交流群', '加群', '群号', 'vx', 'v信', '微信', 'qq', 'qq群', 'q群',
            '收徒', '收学员', '指导', '内参', '牛股', '打赏', '转发', '置顶'
        ]

        def _is_spam(title: str) -> bool:
            t = title.lower()
            if any(k in t for k in spam_keywords):
                return True
            # 联系方式模式（手机号/微信号/QQ群号）
            if re.search(r'(vx|v信|微信|qq|群)[^\w]*[\d]{5,}', t):
                return True
            if re.search(r'(\d{3}[- ]?\d{4}[- ]?\d{4})', t):  # 电话
                return True
            return False

        # 去重并过滤垃圾帖
        seen_titles = set()
        filtered_posts = []
        spam_removed = 0
        for p in posts:
            title = _normalize_text(p.get('title', ''))
            if not title:
                continue
            if _is_spam(title):
                spam_removed += 1
                continue
            if title in seen_titles:
                continue
            seen_titles.add(title)
            p['title'] = title
            filtered_posts.append(p)

        # 如果过滤过后为空，降级到API
        if not filtered_posts:
            return self._get_guba_from_api(limit)
        posts = filtered_posts

        # 增强的情绪关键词库
        bullish_keywords = {
            # 直接看多词汇
            '看多': 3, '买入': 3, '加仓': 3, '抄底': 3, '建仓': 2,
            # 涨势词汇
            '涨': 2, '上涨': 2, '暴涨': 4, '大涨': 3, '飙涨': 4, '拉升': 2, '冲高': 2,
            # 利好词汇
            '利好': 3, '好消息': 2, '利多': 3, '重大利好': 4,
            # 技术词汇
            '突破': 2, '新高': 3, '强势': 2, '反弹': 2, '回升': 1,
            # 市场情绪
            '牛': 2, '牛市': 3, '看好': 2, '乐观': 2, '推荐': 2,
            # 分红相关
            '分红': 1, '派息': 1, '高股息': 2,
            # 板块与交易术语
            '涨停': 4, '封板': 3, '连板': 3, '反包': 3, '一字板': 3, '妖股': 3
        }

        bearish_keywords = {
            # 直接看空词汇
            '看空': 3, '卖出': 3, '减仓': 3, '清仓': 4, '止损': 3,
            # 跌势词汇
            '跌': 2, '下跌': 2, '暴跌': 4, '大跌': 3, '跳水': 4, '闪崩': 4, '破位': 3,
            # 利空词汇
            '利空': 3, '坏消息': 2, '利淡': 3, '重大利空': 4,
            # 风险词汇
            '风险': 2, '危险': 3, '警惕': 2, '小心': 2, '谨慎': 1,
            # 市场情绪
            '熊': 2, '熊市': 3, '悲观': 2, '恐慌': 3,
            # 退市相关
            '退市': 3, '摘牌': 3, '割肉': 4, '腰斩': 4,
            # 跌停与极端负面
            '跌停': 4, '天地板': 4, '开盘跌停': 4, '大阴': 3, '黑天鹅': 4
        }

        neutral_keywords = {
            '观望': 2, '持有': 1, '等待': 1, '震荡': 2, '横盘': 2,
            '整理': 1, '调整': 1, '盘整': 2, '分化': 1, '轮动': 1
        }

        # 扩展否定词和疑问词
        negations = ['不', '不是', '无', '未', '没', '没有', '别', '莫', '勿', '非']
        questions = ['吗', '呢', '？', '?', '什么时候', '如何', '怎么', '为什么']

        # 强化词汇（增强情绪强度）
        intensifiers = ['非常', '特别', '极其', '超级', '巨', '狂', '疯狂', '史上', '创纪录', '重磅', '实锤', '官方']

        # 削弱词汇（降低确定性）
        downtoners = ['可能', '或许', '也许', '大概', '估计', '疑似']

        def _negation_scope_score(text: str, keywords: dict) -> float:
            """计算带否定词近邻作用的关键词得分（返回累加得分）"""
            score = 0.0
            for kw, w in keywords.items():
                start = 0
                while True:
                    idx = text.find(kw, start)
                    if idx == -1:
                        break
                    # 在关键词前3个字符内出现否定词则反向计分（降低权重）
                    window = text[max(0, idx - 3):idx]
                    if any(n in window for n in negations):
                        score -= w * 0.8
                    else:
                        score += w
                    start = idx + len(kw)
            return score

        def _classify_title_sentiment(title: str) -> str:
            """增强版标题情绪分类，考虑权重、上下文和语义"""
            if not title:
                return 'neutral'

            t = title.strip().lower()
            # 保留标点符号用于上下文分析

            # 检查是否为疑问句（疑问句通常为中性）
            has_question = any(q in t for q in questions)
            if has_question and not any(
                    kw in t for kw in list(bullish_keywords.keys()) + list(bearish_keywords.keys())):
                return 'neutral'

            # 计算情绪得分
            bull_score = 0.0
            bear_score = 0.0
            neu_score = 0.0

            # 检查强化词
            intensity_multiplier = 1.0
            for intensifier in intensifiers:
                if intensifier in t:
                    intensity_multiplier = 1.35
                    break
            # 削弱词处理
            if any(d in t for d in downtoners):
                intensity_multiplier *= 0.85

            # 计算看多得分
            bull_score += _negation_scope_score(t, bullish_keywords) * intensity_multiplier

            # 计算看空得分
            bear_score += _negation_scope_score(t, bearish_keywords) * intensity_multiplier

            # 计算中性得分
            for keyword, weight in neutral_keywords.items():
                if keyword in t:
                    neu_score += weight

            # 标点作用：感叹号增强，问号弱化
            exclamations = t.count('!') + t.count('！')
            questions_cnt = t.count('?') + t.count('？')
            if exclamations:
                bull_score *= (1 + 0.1 * min(exclamations, 2))
                bear_score *= (1 + 0.1 * min(exclamations, 2))
            if questions_cnt:
                bull_score *= (1 - 0.1 * min(questions_cnt, 2))
                bear_score *= (1 - 0.1 * min(questions_cnt, 2))

            # 上下文分析：检查数字和百分比
            import re
            numbers = re.findall(r'\d+(?:\.\d+)?%?', t)
            if numbers:
                # 如果有大数字（>20%），增强情绪
                for num_str in numbers:
                    try:
                        num = float(num_str.replace('%', ''))
                        if num > 20:
                            if bull_score > bear_score:
                                bull_score *= 1.3
                            elif bear_score > bull_score:
                                bear_score *= 1.3
                    except:
                        pass

            # 决策逻辑
            total_score = bull_score + bear_score + neu_score

            # 如果总得分太低，判为中性
            if total_score < 1:
                return 'neutral'

            # 如果看多看空得分接近，判为中性
            if abs(bull_score - bear_score) < 1 and max(bull_score, bear_score) > 0:
                return 'neutral'

            # 中性得分占主导
            if neu_score > max(bull_score, bear_score) * 1.5:
                return 'neutral'

            # 最终判断
            if bull_score > bear_score:
                return 'bullish'
            elif bear_score > bull_score:
                return 'bearish'
            else:
                return 'neutral'

        # 统计热词时也使用新的关键词库
        all_keywords = {**bullish_keywords, **bearish_keywords, **neutral_keywords}

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        total_posts = len(posts)
        hot_keywords = {}

        # 分析帖子标题情绪
        decisive_count = 0
        for post in posts:
            title = post.get('title', '')
            sentiment_cls = _classify_title_sentiment(title)
            if sentiment_cls == 'bullish':
                bullish_count += 1
                decisive_count += 1
            elif sentiment_cls == 'bearish':
                bearish_count += 1
                decisive_count += 1
            else:
                neutral_count += 1

            # 统计热词
            for keyword in all_keywords:
                if keyword in title:
                    hot_keywords[keyword] = hot_keywords.get(keyword, 0) + 1

        # 计算比例
        bullish_ratio = round(bullish_count / total_posts * 100, 1) if total_posts > 0 else 0
        bearish_ratio = round(bearish_count / total_posts * 100, 1) if total_posts > 0 else 0
        neutral_ratio = round(neutral_count / total_posts * 100, 1) if total_posts > 0 else 0

        # 归一化
        total_ratio = bullish_ratio + bearish_ratio + neutral_ratio
        if total_ratio > 0:
            bullish_ratio = round(bullish_ratio / total_ratio * 100, 1)
            bearish_ratio = round(bearish_ratio / total_ratio * 100, 1)
            neutral_ratio = round(neutral_ratio / total_ratio * 100, 1)

        # 情绪得分 (0-100, 基于看涨比例)
        sentiment_score = round(50 + (bullish_ratio - bearish_ratio) / 2, 1)

        # 提取top5热词
        top_keywords = sorted(hot_keywords.items(), key=lambda x: x[1], reverse=True)[:5]
        hot_keywords_list = [kw for kw, count in top_keywords]

        guba_sentiment = {
            'total_posts': total_posts,
            'active_users': max(int(total_posts * 0.3), 1),  # 估算活跃用户
            'bullish_ratio': bullish_ratio,
            'bearish_ratio': bearish_ratio,
            'neutral_ratio': neutral_ratio,
            'hot_keywords': hot_keywords_list,
            'sentiment_score': sentiment_score,
            'effective_posts': total_posts,
            'spam_removed': spam_removed,
            'confidence': round(decisive_count / total_posts * 100, 1) if total_posts else 0.0,
        }

        # 综合判断
        if bullish_ratio > 60:
            guba_sentiment['overall'] = '强烈看多'
        elif bullish_ratio > 50:
            guba_sentiment['overall'] = '看多'
        elif bearish_ratio > 60:
            guba_sentiment['overall'] = '强烈看空'
        elif bearish_ratio > 50:
            guba_sentiment['overall'] = '看空'
        else:
            guba_sentiment['overall'] = '中性'

        return guba_sentiment

    def _get_guba_from_api(self, limit=50):
        """使用API获取股吧情绪作为备用方案"""
        try:
            # 东方财富股吧API
            url = f"http://gbapi.eastmoney.com/post/api/v1/posts"
            params = {
                'code': self.stock_code,
                'ps': limit,
                'pn': 1
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            if data and data.get('data') and data['data'].get('list'):
                posts = data['data']['list']

                bullish_keywords = ['看多', '买入', '加仓', '涨', '利好', '牛', '突破', '上涨', '暴涨']
                bearish_keywords = ['看空', '卖出', '减仓', '跌', '利空', '熊', '破位', '下跌', '暴跌']

                bullish_count = 0
                bearish_count = 0

                for post in posts:
                    title = post.get('title', '')
                    is_bullish = any(kw in title for kw in bullish_keywords)
                    is_bearish = any(kw in title for kw in bearish_keywords)

                    if is_bullish and not is_bearish:
                        bullish_count += 1
                    elif is_bearish and not is_bullish:
                        bearish_count += 1

                total_posts = len(posts)
                bullish_ratio = round(bullish_count / total_posts * 100, 1) if total_posts > 0 else 0
                bearish_ratio = round(bearish_count / total_posts * 100, 1) if total_posts > 0 else 0
                neutral_ratio = round((total_posts - bullish_count - bearish_count) / total_posts * 100,
                                      1) if total_posts > 0 else 0

                sentiment_score = round(50 + (bullish_ratio - bearish_ratio) / 2, 1)

                guba_sentiment = {
                    'total_posts': total_posts,
                    'active_users': max(int(total_posts * 0.3), 50),
                    'bullish_ratio': bullish_ratio,
                    'bearish_ratio': bearish_ratio,
                    'neutral_ratio': neutral_ratio,
                    'hot_keywords': [],
                    'sentiment_score': sentiment_score,
                    'overall': '强烈看多' if bullish_ratio > 60 else (
                        '偏多' if bullish_ratio > 50 else ('偏空' if bearish_ratio > 50 else '中性'))
                }

                return guba_sentiment

        except Exception as e:
            print(f"⚠️ API获取股吧情绪失败: {str(e)}")

        return self._get_default_guba_sentiment()

    def get_institutional_activity(self):
        """
        获取机构活动数据 - 已移除(股民情绪只关注评论)

        Returns:
            dict: 机构活动数据
        """
        # 根据用户要求,股民情绪分析只需要展示评论情绪
        # 机构活动数据已移除
        return self._get_default_institutional_activity()

    def _classify_capital_strength(self, inflow_rate):
        """分类资金流向强度"""
        if abs(inflow_rate) > 10:
            return '强'
        elif abs(inflow_rate) > 5:
            return '中'
        else:
            return '弱'

    def get_comprehensive_sentiment(self, verbose: bool = True):
        """
        获取综合情绪分析 - 专注于评论情绪分析

        Returns:
            dict: 综合情绪数据
        """
        if verbose:
            print(f"😊 正在分析 {self.stock_code} 的股民评论情绪...")

        # 获取股吧评论情绪数据
        guba_sentiment = self.get_guba_sentiment()

        # 获取大盘整体情绪与所属板块情绪
        try:
            overall_market_sentiment = self.get_overall_market_sentiment()
        except Exception as e:
            if verbose:
                print(f"   ⚠️  获取大盘情绪失败，使用默认值: {str(e)}")
            overall_market_sentiment = self._get_default_overall_market_sentiment()

        try:
            sector_sentiment = self.get_sector_info_and_sentiment()
        except Exception as e:
            if verbose:
                print(f"   ⚠️  获取板块情绪失败，使用默认值: {str(e)}")
            sector_sentiment = self._get_default_sector_sentiment()

        data = {
            'stock_code': self.stock_code,
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'guba_sentiment': guba_sentiment,
            'overall_market_sentiment': overall_market_sentiment,
            'sector_sentiment': sector_sentiment,
        }

        # 综合情绪评分基于股吧评论情绪
        sentiment_score = guba_sentiment['sentiment_score']
        data['comprehensive_score'] = max(0, min(100, round(sentiment_score, 1)))

        # 综合情绪判断
        if data['comprehensive_score'] >= 70:
            data['comprehensive_sentiment'] = '强烈看多'
        elif data['comprehensive_score'] >= 55:
            data['comprehensive_sentiment'] = '偏多'
        elif data['comprehensive_score'] >= 45:
            data['comprehensive_sentiment'] = '中性'
        elif data['comprehensive_score'] >= 30:
            data['comprehensive_sentiment'] = '偏空'
        else:
            data['comprehensive_sentiment'] = '强烈看空'

        if verbose:
            print(f"✅ 情绪分析完成")
            print(f"   - 综合情绪: {data['comprehensive_sentiment']} ({data['comprehensive_score']}分)")
            print(f"   - 股吧评论: {data['guba_sentiment']['overall']}")
            print(f"   - 看多比例: {data['guba_sentiment']['bullish_ratio']}%")
            print(f"   - 看空比例: {data['guba_sentiment']['bearish_ratio']}%")
            # 额外输出市场与板块情绪摘要
            try:
                om = data['overall_market_sentiment']
                primary_name = om.get('primary_index', {}).get('name', '所属大盘')
                primary_chg = om.get('primary_change_pct', 'N/A')
                print(f"   - 大盘情绪: {om.get('overall', 'N/A')} 所属大盘: {primary_name} 涨跌: {primary_chg}%")
            except Exception:
                pass
            try:
                print(f"   - 板块情绪: {data['sector_sentiment'].get('overall', 'N/A')} ({data['sector_sentiment'].get('sector_name', 'N/A')}) 涨跌: {data['sector_sentiment'].get('change_pct', 'N/A')}%")
            except Exception:
                pass

        return data

    def _get_default_capital_flow(self):
        """返回默认资金流向数据"""
        return {
            'date': 'N/A',
            'main_inflow': 0,
            'retail_inflow': 0,
            'main_inflow_rate': 0,
            'super_large_inflow': 0,
            'large_inflow': 0,
            'medium_inflow': 0,
            'small_inflow': 0,
            'trend': '未知',
            'strength': '未知',
        }

    def _get_default_market_sentiment(self):
        """返回默认市场情绪数据"""
        return {
            'turnover_rate': 'N/A',
            'volume_ratio': 'N/A',
            'amplitude': 'N/A',
            'up_down_ratio': 'N/A',
            'market_cap_rank': 'N/A',
            'turnover_emotion': '未知',
        }

    def _get_default_overall_market_sentiment(self):
        """返回默认大盘整体情绪数据"""
        return {
            'indices': {},
            'sentiment_score': 50,
            'overall': '数据不足',
            'emotion': 'neutral',
            'primary_index': {
                'key': 'sz399001',
                'name': '所属大盘',
                'change_pct': 'N/A',
            },
            'primary_change_pct': 'N/A',
            'avg_change_pct': 'N/A',
        }

    def _get_default_sector_sentiment(self):
        """返回默认板块情绪数据"""
        return {
            'sector_name': 'N/A',
            'sector_code': 'N/A',
            'change_pct': 'N/A',
            'turnover_rate': 'N/A',
            'sentiment_score': 50,
            'overall': '数据不足',
            'emotion': 'neutral',
        }

    def _get_default_guba_sentiment(self):
        """返回默认股吧情绪数据"""
        return {
            'total_posts': 0,
            'active_users': 0,
            'bullish_ratio': 50,
            'bearish_ratio': 30,
            'neutral_ratio': 20,
            'hot_keywords': [],
            'sentiment_score': 50,
            'overall': '中性',
        }

    def _get_default_institutional_activity(self):
        """返回默认机构活动数据"""
        return {
            'recent_research': 0,
            'institutional_buyers': 0,
            'institutional_sellers': 0,
            'net_institutional_buy': 0,
            'activity_level': '未知',
            'last_research_date': 'N/A',
        }


if __name__ == "__main__":
    # 测试代码
    analyzer = InvestorSentimentAnalyzer("688343")
    data = analyzer.get_comprehensive_sentiment()

    print("\n" + "=" * 60)
    print("股民情绪分析结果:")
    print("=" * 60)

    import json

    print(json.dumps(data, indent=2, ensure_ascii=False))
