#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
利好利空事件分析模块
分析潜在的利好和利空因素
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

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class EventAnalyzer:
    """利好利空事件分析器 - 基于真实公告提取"""

    def __init__(self, stock_code, news_data=None):
        """
        初始化事件分析器

        Args:
            stock_code: 股票代码 (例如: '688343', '000001')
            news_data: 消息面数据(由NewsSentimentCollector提供),如果为None则内部获取
        """
        self.stock_code = stock_code
        self.news_data = news_data
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/'
        }

        # 利好关键词
        self.positive_keywords = {
            'policy': ['政策支持', '补贴', '税收优惠', '产业扶持', '国家战略', '政府采购', '政策利好'],
            'performance': ['业绩预增', '营收增长', '利润增长', '超预期', '盈利能力提升', '订单增加', '业绩大幅'],
            'corporate': ['重大合同', '战略合作', '并购重组', '股权激励', '分红', '回购', '增持'],
            'technology': ['技术突破', '研发成功', '专利', '创新', '产品升级', '核心技术', '研发'],
            'market': ['市场份额提升', '新市场开拓', '出口增长', '行业龙头', '竞争优势', '中标'],
            'capital': ['机构增持', '战略投资', '融资成功', '信用评级上调', '入选指数', '外资'],
        }

        # 利空关键词
        self.negative_keywords = {
            'policy': ['政策限制', '监管加强', '处罚', '调查', '违规', '整改', '行政处罚'],
            'performance': ['业绩下滑', '亏损', '营收下降', '利润下降', '低于预期', '订单减少', '业绩下降'],
            'corporate': ['高管离职', '股东减持', '诉讼', '担保风险', '债务违约', '资金链', '减持'],
            'market': ['市场份额下降', '竞争加剧', '价格战', '客户流失', '行业下行', '市场竞争'],
            'risk': ['商誉减值', '坏账', '存货积压', '安全事故', '环保问题', '质量问题', '风险'],
            'capital': ['融资失败', '信用评级下调', '质押风险', '资金紧张', '资金压力'],
        }

    def analyze_policy_events(self):
        """
        分析政策面事件

        Returns:
            dict: 政策事件分析
        """
        events = {
            'positive': [],
            'negative': [],
            'score': 0  # 政策得分(-100到100)
        }

        try:
            # 实际应用中应该从新闻API获取政策相关新闻
            # 这里使用示例数据
            policy_news = [
                {'title': '国家支持新能源产业发展', 'date': '2025-09-28', 'impact': 8},
                {'title': '行业监管政策加强', 'date': '2025-09-25', 'impact': -5},
            ]

            for news in policy_news:
                if news['impact'] > 0:
                    events['positive'].append({
                        'event': news['title'],
                        'date': news['date'],
                        'impact_score': news['impact'],
                        'description': '政策利好'
                    })
                    events['score'] += news['impact']
                else:
                    events['negative'].append({
                        'event': news['title'],
                        'date': news['date'],
                        'impact_score': abs(news['impact']),
                        'description': '政策利空'
                    })
                    events['score'] += news['impact']

        except Exception as e:
            print(f"⚠️ 分析政策事件失败: {str(e)}")

        return events

    def analyze_corporate_events(self):
        """
        分析公司事件

        Returns:
            dict: 公司事件分析
        """
        events = {
            'positive': [],
            'negative': [],
            'score': 0
        }

        try:
            # 实际应用中应该从公告API获取
            # 这里使用示例数据
            corporate_events = [
                {'event': '签署重大合同', 'date': '2025-09-30', 'type': 'positive', 'impact': 10},
                {'event': '完成战略融资', 'date': '2025-09-28', 'type': 'positive', 'impact': 8},
                {'event': '高管减持', 'date': '2025-09-26', 'type': 'negative', 'impact': -6},
            ]

            for event in corporate_events:
                event_data = {
                    'event': event['event'],
                    'date': event['date'],
                    'impact_score': abs(event['impact']),
                    'description': self._get_event_description(event['event'])
                }

                if event['type'] == 'positive':
                    events['positive'].append(event_data)
                    events['score'] += event['impact']
                else:
                    events['negative'].append(event_data)
                    events['score'] += event['impact']

        except Exception as e:
            print(f"⚠️ 分析公司事件失败: {str(e)}")

        return events

    def analyze_industry_events(self):
        """
        分析行业事件

        Returns:
            dict: 行业事件分析
        """
        events = {
            'positive': [],
            'negative': [],
            'score': 0
        }

        try:
            # 行业事件示例
            industry_events = [
                {'event': '行业景气度上升', 'date': '2025-09-29', 'type': 'positive', 'impact': 7},
                {'event': '上游原材料价格上涨', 'date': '2025-09-27', 'type': 'negative', 'impact': -5},
            ]

            for event in industry_events:
                event_data = {
                    'event': event['event'],
                    'date': event['date'],
                    'impact_score': abs(event['impact']),
                    'description': '行业层面影响'
                }

                if event['type'] == 'positive':
                    events['positive'].append(event_data)
                    events['score'] += event['impact']
                else:
                    events['negative'].append(event_data)
                    events['score'] += event['impact']

        except Exception as e:
            print(f"⚠️ 分析行业事件失败: {str(e)}")

        return events

    def analyze_market_events(self):
        """
        分析市场事件

        Returns:
            dict: 市场事件分析
        """
        events = {
            'positive': [],
            'negative': [],
            'score': 0
        }

        try:
            # 市场事件示例
            market_events = [
                {'event': '北向资金大幅流入', 'date': '2025-09-30', 'type': 'positive', 'impact': 6},
                {'event': '市场整体下跌', 'date': '2025-09-29', 'type': 'negative', 'impact': -4},
            ]

            for event in market_events:
                event_data = {
                    'event': event['event'],
                    'date': event['date'],
                    'impact_score': abs(event['impact']),
                    'description': '市场环境影响'
                }

                if event['type'] == 'positive':
                    events['positive'].append(event_data)
                    events['score'] += event['impact']
                else:
                    events['negative'].append(event_data)
                    events['score'] += event['impact']

        except Exception as e:
            print(f"⚠️ 分析市场事件失败: {str(e)}")

        return events

    def _get_event_description(self, event_text):
        """获取事件描述"""
        # 匹配利好关键词
        for category, keywords in self.positive_keywords.items():
            for keyword in keywords:
                if keyword in event_text:
                    return f'{category}层面利好'

        # 匹配利空关键词
        for category, keywords in self.negative_keywords.items():
            for keyword in keywords:
                if keyword in event_text:
                    return f'{category}层面利空'

        return '其他事件'

    def _extract_events_from_announcements(self, announcements: list) -> tuple:
        """从公告中提取利好利空事件"""
        positive_events = []
        negative_events = []

        for announcement in announcements:
            title = announcement.get('title', '')
            date = announcement.get('date', '')
            importance = announcement.get('importance', '中')

            # 计算影响分数(重要性越高,分数越高)
            base_score = {'高': 10, '中': 6, '低': 3}.get(importance, 5)

            # 检查利好关键词
            positive_match = False
            positive_category = None
            for category, keywords in self.positive_keywords.items():
                if any(keyword in title for keyword in keywords):
                    positive_match = True
                    positive_category = category
                    break

            # 检查利空关键词
            negative_match = False
            negative_category = None
            for category, keywords in self.negative_keywords.items():
                if any(keyword in title for keyword in keywords):
                    negative_match = True
                    negative_category = category
                    break

            # 优先利空,然后利好,最后忽略中性
            if negative_match:
                negative_events.append({
                    'event': title,
                    'date': date,
                    'impact_score': base_score,
                    'category': negative_category,
                    'description': f'{negative_category}层面利空'
                })
            elif positive_match:
                positive_events.append({
                    'event': title,
                    'date': date,
                    'impact_score': base_score,
                    'category': positive_category,
                    'description': f'{positive_category}层面利好'
                })

        return positive_events, negative_events

    def _extract_events_from_news(self, news_list: list) -> tuple:
        """从新闻中提取利好利空事件"""
        positive_events = []
        negative_events = []

        for news in news_list[:10]:  # 只取前10条新闻
            title = news.get('title', '')
            date = news.get('date', '')
            sentiment = news.get('sentiment', '中性')

            # 基于情感的基础分数
            base_score = {'正面': 7, '负面': 7, '中性': 3}.get(sentiment, 3)

            # 检查利好关键词
            positive_match = False
            positive_category = None
            for category, keywords in self.positive_keywords.items():
                if any(keyword in title for keyword in keywords):
                    positive_match = True
                    positive_category = category
                    break

            # 检查利空关键词
            negative_match = False
            negative_category = None
            for category, keywords in self.negative_keywords.items():
                if any(keyword in title for keyword in keywords):
                    negative_match = True
                    negative_category = category
                    break

            # 根据情感和关键词匹配分类
            if sentiment == '正面' and positive_match:
                positive_events.append({
                    'event': title,
                    'date': date,
                    'impact_score': base_score,
                    'category': positive_category,
                    'description': f'{positive_category}层面利好'
                })
            elif sentiment == '负面' and negative_match:
                negative_events.append({
                    'event': title,
                    'date': date,
                    'impact_score': base_score,
                    'category': negative_category,
                    'description': f'{negative_category}层面利空'
                })

        return positive_events, negative_events

    def get_comprehensive_analysis(self):
        """
        获取综合事件分析 - 基于真实公告和新闻

        Returns:
            dict: 综合事件分析
        """
        print(f"🔍 正在分析 {self.stock_code} 的利好利空事件...")

        # 如果没有提供news_data,则内部获取
        if not self.news_data:
            from analysis.news_sentiment_collector import NewsSentimentCollector
            collector = NewsSentimentCollector(self.stock_code)
            self.news_data = collector.get_comprehensive_news()

        # 从公告中提取事件
        announcements = self.news_data.get('announcements', [])
        ann_positive, ann_negative = self._extract_events_from_announcements(announcements)

        # 从新闻中提取事件
        news_list = self.news_data.get('news', [])
        news_positive, news_negative = self._extract_events_from_news(news_list)

        # 合并事件
        all_positive_events = ann_positive + news_positive
        all_negative_events = ann_negative + news_negative

        # 按影响分数排序
        all_positive_events.sort(key=lambda x: x['impact_score'], reverse=True)
        all_negative_events.sort(key=lambda x: x['impact_score'], reverse=True)

        # 计算综合得分
        total_positive_score = sum(e['impact_score'] for e in all_positive_events)
        total_negative_score = sum(e['impact_score'] for e in all_negative_events)
        total_score = total_positive_score - total_negative_score

        data = {
            'stock_code': self.stock_code,
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'policy_events': {'positive': [], 'negative': [], 'score': 0},
            'corporate_events': {'positive': [], 'negative': [], 'score': 0},
            'industry_events': {'positive': [], 'negative': [], 'score': 0},
            'market_events': {'positive': [], 'negative': [], 'score': 0},
        }

        # 按类别分组事件
        for event in all_positive_events:
            category = event.get('category', 'corporate')
            if category == 'policy':
                data['policy_events']['positive'].append(event)
                data['policy_events']['score'] += event['impact_score']
            elif category in ['performance', 'corporate', 'technology']:
                data['corporate_events']['positive'].append(event)
                data['corporate_events']['score'] += event['impact_score']
            elif category == 'market':
                data['market_events']['positive'].append(event)
                data['market_events']['score'] += event['impact_score']
            elif category == 'capital':
                data['industry_events']['positive'].append(event)
                data['industry_events']['score'] += event['impact_score']

        for event in all_negative_events:
            category = event.get('category', 'corporate')
            if category == 'policy':
                data['policy_events']['negative'].append(event)
                data['policy_events']['score'] -= event['impact_score']
            elif category in ['performance', 'corporate', 'risk']:
                data['corporate_events']['negative'].append(event)
                data['corporate_events']['score'] -= event['impact_score']
            elif category == 'market':
                data['market_events']['negative'].append(event)
                data['market_events']['score'] -= event['impact_score']
            elif category == 'capital':
                data['industry_events']['negative'].append(event)
                data['industry_events']['score'] -= event['impact_score']

        data['summary'] = {
            'total_positive_events': len(all_positive_events),
            'total_negative_events': len(all_negative_events),
            'comprehensive_score': total_score,
            'risk_level': self._get_risk_level(total_score, len(all_negative_events)),
            'opportunity_level': self._get_opportunity_level(total_score, len(all_positive_events)),
        }

        # 综合评级
        if total_score >= 15:
            data['summary']['rating'] = '强烈利好'
        elif total_score >= 5:
            data['summary']['rating'] = '偏利好'
        elif total_score >= -5:
            data['summary']['rating'] = '中性'
        elif total_score >= -15:
            data['summary']['rating'] = '偏利空'
        else:
            data['summary']['rating'] = '强烈利空'

        print(f"✅ 事件分析完成")
        print(f"   - 综合评级: {data['summary']['rating']} (得分: {total_score})")
        print(f"   - 利好事件: {len(all_positive_events)} 个")
        print(f"   - 利空事件: {len(all_negative_events)} 个")
        print(f"   - 风险等级: {data['summary']['risk_level']}")
        print(f"   - 机会等级: {data['summary']['opportunity_level']}")

        return data

    def _get_risk_level(self, score, negative_count):
        """获取风险等级"""
        if score < -10 or negative_count >= 5:
            return '高风险'
        elif score < 0 or negative_count >= 3:
            return '中等风险'
        else:
            return '低风险'

    def _get_opportunity_level(self, score, positive_count):
        """获取机会等级"""
        if score > 15 and positive_count >= 5:
            return '高机会'
        elif score > 5 and positive_count >= 3:
            return '中等机会'
        else:
            return '低机会'


if __name__ == "__main__":
    # 测试代码
    analyzer = EventAnalyzer("688343")
    data = analyzer.get_comprehensive_analysis()

    print("\n" + "=" * 60)
    print("利好利空事件分析结果:")
    print("=" * 60)

    import json

    print(json.dumps(data, indent=2, ensure_ascii=False))
