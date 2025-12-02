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
        self.company_name = None  # 用于提升新闻关联性判断
        self.related_keywords = []  # 关联实体关键词，如合作方/子公司/品牌等
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
            'market': ['市场份额提升', '新市场开拓', '出口增长', '行业龙头', '竞争优势', '中标', '涨停', '创历史新高', '净流入', '主力资金净流入', '集体净买入'],
            'capital': ['机构增持', '战略投资', '融资成功', '信用评级上调', '入选指数', '外资'],
        }

        # 利空关键词
        self.negative_keywords = {
            'policy': ['政策限制', '监管加强', '处罚', '调查', '违规', '整改', '行政处罚'],
            'performance': ['业绩下滑', '亏损', '营收下降', '利润下降', '低于预期', '订单减少', '业绩下降'],
            'corporate': ['高管离职', '股东减持', '诉讼', '担保风险', '债务违约', '资金链', '减持'],
            'market': ['市场份额下降', '竞争加剧', '价格战', '客户流失', '行业下行', '市场竞争', '跌停', '创历史新低', '净流出', '主力资金净流出', '集体净卖出'],
            'risk': ['商誉减值', '坏账', '存货积压', '安全事故', '环保问题', '质量问题', '风险'],
            'capital': ['融资失败', '信用评级下调', '质押风险', '资金紧张', '资金压力'],
        }

    def analyze_policy_events(self, verbose: bool = True):
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
            if verbose:
                print(f"⚠️ 分析政策事件失败: {str(e)}")

        return events

    def analyze_corporate_events(self, verbose: bool = True):
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
            if verbose:
                print(f"⚠️ 分析公司事件失败: {str(e)}")

        return events

    def analyze_industry_events(self, verbose: bool = True):
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
            if verbose:
                print(f"⚠️ 分析行业事件失败: {str(e)}")

        return events

    def analyze_market_events(self, verbose: bool = True):
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
            if verbose:
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

    def _market_prefix(self) -> str:
        """根据股票代码推断市场前缀(sh/sz)"""
        code = str(self.stock_code)
        if code.startswith(('600', '601', '603', '605', '688')):
            return 'sh'
        return 'sz'

    def _load_company_name(self):
        """加载公司名称用于新闻强关联判断(东财push2接口)"""
        if self.company_name:
            return
        try:
            exchange_flag = '1' if self._market_prefix() == 'sh' else '0'
            # 使用 ulist.np 替代 stock/get
            url = "http://push2.eastmoney.com/api/qt/ulist.np/get"
            params = {
                'secids': f"{exchange_flag}.{self.stock_code}",
                'fltt': '2',
                'fields': 'f14'
            }
            resp = requests.get(url, params=params, headers=self.headers, timeout=8)
            data = resp.json() if resp.content else {}
            
            name = None
            if data.get('data') and data['data'].get('diff'):
                name = data['data']['diff'][0].get('f14')
                
            if isinstance(name, str) and name.strip():
                self.company_name = name.strip()
        except Exception:
            # 保持company_name为None, 仅使用代码匹配
            pass

    def _load_related_keywords(self):
        """从配置文件加载关联实体关键词，用于扩展强关联判断"""
        if self.related_keywords:
            return
        try:
            cfg_path = Path(__file__).parent.parent / 'config' / 'related_entities.json'
            if cfg_path.exists():
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                code = str(self.stock_code)
                # 支持直接代码、带交易所前缀的键名
                keys = [code, f"SZ{code}", f"SH{code}", f"{code}.SZ", f"{code}.SH"]
                for k in keys:
                    kws = data.get(k)
                    if isinstance(kws, list):
                        self.related_keywords.extend([s for s in kws if isinstance(s, str)])
                # 去重
                self.related_keywords = list(dict.fromkeys(self.related_keywords))
        except Exception:
            # 保持为空，不影响主流程
            pass

    def _is_strongly_related_news(self, title: str, url: str, source: str, summary: str = '') -> bool:
        """判断新闻与当前股票的强关联性

        规则:
        - 标题或URL包含股票代码(300290、SZ300290、300290.SZ等)
        - 若已获取公司名称, 标题包含公司中文名
        - 允许通过配置的关联实体关键词命中(如合作方“新凯来”等)
        - 对可信来源(证券时报、上证报、财联社、新华社、同花顺、东方财富)更宽松,但仍需代码或公司名命中
        """
        # 确保加载公司名与关联关键词
        self._load_company_name()
        self._load_related_keywords()

        t = (title or '').strip()
        u = (url or '').strip()
        s = (source or '').strip()
        sm = (summary or '').strip()
        code = str(self.stock_code)

        # 代码匹配模式
        patterns = [
            rf"\b{re.escape(code)}\b",
            rf"\b{re.escape(code)}\.SZ\b",
            rf"\b{re.escape(code)}\.SH\b",
            rf"\bSZ{re.escape(code)}\b",
            rf"\bsz{re.escape(code)}\b",
            rf"\bSH{re.escape(code)}\b",
            rf"\bsh{re.escape(code)}\b",
            re.escape(code)  # 宽松匹配,防止中文环境下边界识别失败
        ]

        def match_any(text: str) -> bool:
            for p in patterns:
                try:
                    if re.search(p, text):
                        return True
                except Exception:
                    if p in text:
                        return True
            return False

        code_hit = match_any(t) or match_any(u)
        name_hit = False
        if self.company_name:
            name_hit = self.company_name in t

        credible_sources = ['证券时报', '上证报', '财联社', '新华社', '央广网', '同花顺', '东方财富']
        credible = any(cs in s for cs in credible_sources) or any(cs in u for cs in ['10jqka', 'eastmoney'])

        # 必须至少命中代码或公司名
        if code_hit or name_hit:
            return True

        # 关联关键词命中(标题/摘要/URL任一命中则视为强关联)
        if self.related_keywords:
            for kw in self.related_keywords:
                if not kw:
                    continue
                if kw in t or kw in sm or kw in u:
                    return True

        # 对可信来源，不放行无命中内容
        return False

    def _is_major_event(self, title: str) -> bool:
        """判断是否为“大事件提醒”级别的内容"""
        if not title:
            return False
        t = str(title)
        major_keywords = [
            '重大', '停牌', '复牌', '并购', '重组', '增持', '减持', '回购', '终止', '签署', '中标', '中签',
            '诉讼', '立案', '处罚', '质押', '解除质押', '业绩预告', '业绩快报', '分红', '配股', '定增',
            '限售股解禁', '股东大会', '问询函', '关注函', '被调查', '破产', '退市风险', 'ST', '摘帽',
            '战略合作', '重大合同', '重大项目', '停产', '复产', '设备事故', '控股股东变更', '高管变动',
            '评级上调', '评级下调', '目标价', '上调', '下调', '涨停', '跌停', '创历史新高', '创历史新低'
        ]
        return any(k in t for k in major_keywords)

    def _extract_events_from_announcements(self, announcements: list) -> tuple:
        """从公告中提取利好利空事件"""
        positive_events = []
        negative_events = []

        for announcement in announcements:
            title = announcement.get('title', '')
            date = announcement.get('date', '') or announcement.get('publish_time', '')
            url = announcement.get('url', '')
            summary = announcement.get('summary', '')
            importance = announcement.get('importance', '中')

            # 只保留“大事件提醒”级别
            if not self._is_major_event(title):
                continue

            # 计算影响分数(重要性越高,分数越高)
            base_score = {'高': 12, '中': 7, '低': 4}.get(importance, 6)

            # 时效加权：近3日 +2，近7日 +1
            recency_bonus = 0
            try:
                from datetime import datetime
                d = datetime.strptime(date[:10], '%Y-%m-%d')
                days = (datetime.now() - d).days
                if days <= 3:
                    recency_bonus = 2
                elif days <= 7:
                    recency_bonus = 1
            except Exception:
                pass
            base_score += recency_bonus

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
                    'category': negative_category or 'corporate',
                    'description': f'{negative_category}层面利空'
                    if negative_category else '公司层面利空',
                    'source': '公司公告',
                    'url': url,
                    'summary': summary
                })
            elif positive_match:
                positive_events.append({
                    'event': title,
                    'date': date,
                    'impact_score': base_score,
                    'category': positive_category or 'corporate',
                    'description': f'{positive_category}层面利好'
                    if positive_category else '公司层面利好',
                    'source': '公司公告',
                    'url': url,
                    'summary': summary
                })

        return positive_events, negative_events

    def _extract_events_from_news(self, news_list: list) -> tuple:
        """从新闻中提取利好利空事件"""
        positive_events = []
        negative_events = []

        for news in news_list[:15]:  # 适度增加覆盖
            title = news.get('title', '')
            date = news.get('date', '') or news.get('publish_time', '')
            sentiment = news.get('sentiment', '中性')
            source = news.get('source', '')
            url = news.get('url', '')
            summary = news.get('summary', '')

            # 只保留“大事件提醒”或命中显式利好/利空关键词；若命中关联关键词也放宽
            allow_major = self._is_major_event(title)
            # 先预判关键词匹配，用于放宽门槛
            prelim_positive = any(keyword in title for keywords in self.positive_keywords.values() for keyword in keywords)
            prelim_negative = any(keyword in title for keywords in self.negative_keywords.values() for keyword in keywords)

            if not allow_major and not (prelim_positive or prelim_negative):
                self._load_related_keywords()
                if any((kw and (kw in title or kw in summary)) for kw in self.related_keywords):
                    allow_major = True
            # 若仍不满足重大或关键词命中则跳过
            if not allow_major and not (prelim_positive or prelim_negative):
                continue

            # 增加强关联性过滤(包含摘要用于关联关键词匹配)
            related_ok = self._is_strongly_related_news(title, url, source, summary)
            # 若未强关联，但为可信来源且含显式利好/利空关键词，则放宽（避免错过行业/公司重要新闻）
            if not related_ok and (prelim_positive or prelim_negative):
                credible_sources = ['证券时报', '上证报', '财联社', '新华社', '央广网', '同花顺', '东方财富']
                if any(cs in source for cs in credible_sources) or any(h in url for h in ['10jqka', 'eastmoney']):
                    related_ok = True
            if not related_ok:
                continue

            # 基于情感的基础分数
            base_score = {'正面': 6, '负面': 6, '中性': 2}.get(sentiment, 3)

            # 来源可信度加权
            credibility_bonus = 0
            credible_sources = ['证券时报', '上证报', '财联社', '新华社', '央广网']
            if any(cs in source for cs in credible_sources):
                credibility_bonus = 1

            # 时效加权
            recency_bonus = 0
            try:
                from datetime import datetime
                d = datetime.strptime(date[:10], '%Y-%m-%d')
                days = (datetime.now() - d).days
                if days <= 3:
                    recency_bonus = 2
                elif days <= 7:
                    recency_bonus = 1
            except Exception:
                pass
            base_score += recency_bonus + credibility_bonus

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

            # 若无显式利好/利空关键词，但命中关联关键词或重大事件，则视为关联利好
            if not positive_match and not negative_match and related_ok:
                positive_match = True
                if not positive_category:
                    positive_category = 'corporate'

            # 根据关键词匹配分类（不再强制依赖情感标签，以免漏报）
            if positive_match:
                positive_events.append({
                    'event': title,
                    'date': date,
                    'impact_score': base_score,
                    'category': positive_category or 'industry',
                    'description': f'{positive_category}层面利好' if positive_category else '行业层面利好',
                    'source': source,
                    'url': url,
                    'summary': summary
                })
            elif negative_match:
                negative_events.append({
                    'event': title,
                    'date': date,
                    'impact_score': base_score,
                    'category': negative_category or 'industry',
                    'description': f'{negative_category}层面利空' if negative_category else '行业层面利空',
                    'source': source,
                    'url': url,
                    'summary': summary
                })

        return positive_events, negative_events

    def get_comprehensive_analysis(self, verbose: bool = True):
        """
        获取综合事件分析 - 基于真实公告和新闻

        Returns:
            dict: 综合事件分析
        """
        if verbose:
            print(f"🔍 正在分析 {self.stock_code} 的利好利空事件...")

        # 如果没有提供news_data,则内部获取
        if not self.news_data:
            from analysis.news_sentiment_collector import NewsSentimentCollector
            collector = NewsSentimentCollector(self.stock_code)
            self.news_data = collector.get_comprehensive_news(verbose=verbose)

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

        # 按类别分组事件（优先公司类信息）
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
            elif category in ['industry', 'capital']:
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
            elif category in ['industry', 'capital']:
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

        if verbose:
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
