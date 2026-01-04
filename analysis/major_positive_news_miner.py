#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重大利好消息挖掘系统 v2.0
==========================

核心功能：
1. 从全市场资讯流中挖掘潜在重大利好
2. 识别相关股票代码
3. 全方位置信度分析
4. 用于股票提前埋伏

利好类型：
- 重大资产重组
- 并购重组
- 大额订单/合同
- 政策利好
- 业绩预增
- 技术突破
- 战略合作
- 股权激励
- 分红回购
- 其他重大利好

置信度分析维度：
1. 消息来源可信度
2. 消息时效性
3. 消息内容质量
4. 市场验证度
5. 历史准确度
6. 技术面配合度
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re
import logging

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.global_hot_news_collector import GlobalHotNewsCollector
from analysis.news_sentiment_collector import NewsSentimentCollector
from analysis.fundamental_data_collector import FundamentalDataCollector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MajorPositiveNewsMiner:
    """重大利好消息挖掘器 - 从资讯流中挖掘股票"""

    # 利好消息类型定义
    NEWS_TYPES = {
        'restructuring': '重大资产重组',
        'merger_acquisition': '并购重组',
        'large_order': '大额订单/合同',
        'policy_support': '政策利好',
        'performance_forecast': '业绩预增',
        'tech_breakthrough': '技术突破',
        'strategic_cooperation': '战略合作',
        'equity_incentive': '股权激励',
        'dividend_buyback': '分红回购',
        'other_major': '其他重大利好'
    }

    # 股票代码正则表达式（匹配A股代码）
    STOCK_CODE_PATTERN = re.compile(r'(?:^|[^0-9a-zA-Z])([0-6]\d{5}|300\d{3}|301\d{3}|688\d{3})(?:[^0-9a-zA-Z]|$)')

    # 常见公司名称模式（用于从新闻中提取公司名称）
    COMPANY_NAME_PATTERN = re.compile(r'([\u4e00-\u9fa5]{2,4})(?:股份|集团|公司|科技|实业|控股|有限|发展|投资|能源|医药|生物|电子|通信|汽车|制造|材料|化工|机械|设备|系统|软件|网络|信息|数据|智能|创新|技术|工程|建设|贸易|商业|服务|文化|传媒|教育|金融|银行|保险|证券|基金|信托|租赁|物流|运输|仓储|餐饮|酒店|旅游|房地产|建筑|建材|装饰|环保|新能源|电力|水务|燃气|供热|矿业|冶金|钢铁|有色金属|黄金|白银|石油|天然气|煤炭|化工|化肥|农药|塑料|橡胶|玻璃|陶瓷|造纸|印刷|包装|纺织|服装|鞋帽|皮革|家具|家电|电子|通信|计算机|软件|互联网|电子商务|游戏|影视|出版|广告|公关|咨询|法律|会计|审计|税务|咨询|培训|教育|科研|设计|建筑|工程|监理|检测|认证|评估|拍卖|典当|担保|租赁|信托|基金|证券|银行|保险|期货|期权|外汇|黄金|白银|石油|天然气|煤炭|电力|新能源|环保|水务|燃气|供热|矿业|冶金|钢铁|有色金属|黄金|白银|石油|天然气|煤炭|化工|化肥|农药|塑料|橡胶|玻璃|陶瓷|造纸|印刷|包装|纺织|服装|鞋帽|皮革|家具|家电|电子|通信|计算机|软件|互联网|电子商务|游戏|影视|出版|广告|公关|咨询|法律|会计|审计|税务|咨询|培训|教育|科研|设计|建筑|工程|监理|检测|认证|评估|拍卖|典当|担保|租赁|信托|基金|证券|银行|保险|期货|期权|外汇)')

    # 利好关键词库（按类型分类）
    POSITIVE_KEYWORDS = {
        'restructuring': [
            '重大资产重组', '资产重组', '重组方案', '重组预案',
            '重大资产置换', '重大资产出售', '重大资产购买',
            '借壳上市', '壳资源', '重组获得通过', '重组获批',
            '重组完成', '重组公告', '重大重组', '资产注入',
            '整体上市', '分拆上市', '资产注入', '资产置换'
        ],
        'merger_acquisition': [
            '并购', '收购', '兼并', '重组', '合并', '控股',
            '收购股权', '收购资产', '并购重组', '战略并购',
            '全资收购', '控股收购', '收购完成', '并购完成',
            '收购案', '并购案', '重大收购', '重大并购',
            '控股权', '股权收购', '资产收购', '并购交易'
        ],
        'large_order': [
            '重大合同', '中标', '签订合同', '签署协议', '订单',
            '大额合同', '亿元合同', '亿元订单', '重大订单',
            '签署重大合同', '中标金额', '合同金额', '订单金额',
            '中标项目', '签订协议', '签署合作', '获得订单',
            '拿下订单', '合同签署', '协议签署', '订单签署'
        ],
        'policy_support': [
            '政策支持', '产业扶持', '国家战略', '纳入规划',
            '政策利好', '税收优惠', '财政补贴', '政府补助',
            '列入名单', '获得支持', '政策倾斜', '产业政策',
            '补贴', '扶持', '支持', '利好', '政策', '规划',
            '实施方案', '实施细则', '印发', '发布', '出台',
            '国家', '部委', '部门', '政府', '财政', '税收',
            '纳入', '列入', '重点', '示范', '试点', '推广'
        ],
        'performance_forecast': [
            '业绩预增', '业绩大幅增长', '净利润增长', '营收增长',
            '超预期', '业绩预告', '业绩修正', '业绩向上修正',
            '利润增长', '盈利能力提升', '业绩大幅提升',
            '业绩大增', '利润大增', '营收大增', '业绩向好',
            '盈利增长', '利润预增', '营收预增', '业绩增长'
        ],
        'tech_breakthrough': [
            '技术突破', '研发成功', '专利', '核心技术',
            '技术领先', '技术优势', '研发突破', '技术创新',
            '获得专利', '技术成果', '技术升级', '技术革新',
            '突破', '领先', '创新', '研发', '专利', '技术',
            '标准', '门槛', '第一股', '首发', '首发上市',
            '募资', '上市', 'IPO', '首发申请', '上市申请'
        ],
        'strategic_cooperation': [
            '战略合作', '战略合作协议', '签署协议', '合作',
            '战略合作框架', '深度合作', '全面合作', '战略伙伴',
            '建立合作', '达成合作', '合作项目', '合作开发',
            '合作签约', '合作达成', '合作启动', '合作开展',
            '战略合作', '业务合作', '产业合作', '技术合作'
        ],
        'equity_incentive': [
            '股权激励', '限制性股票', '股票期权', '激励计划',
            '员工持股', '股权激励方案', '激励草案', '激励公告',
            '激励', '持股', '期权', '限制性', '员工',
            '股权', '激励计划', '激励方案', '激励草案'
        ],
        'dividend_buyback': [
            '分红', '派现', '现金分红', '分红方案',
            '回购', '股份回购', '回购股份', '回购计划',
            '回购公告', '增持', '控股股东增持', '高管增持',
            '增持', '回购', '分红', '派现', '现金分红',
            '股份回购', '增持计划', '增持公告', '回购方案'
        ],
        'other_major': [
            '重大事项', '重要事项', '重大利好', '重大消息',
            '重大进展', '重大突破', '重大成果', '重大公告',
            '重磅', '重大', '重要', '利好', '突破', '进展',
            '成果', '公告', '事项', '消息', '新闻', '头条',
            '涨停', '涨停板', '大涨', '暴涨', '拉升', '上涨',
            '龙头', '领涨', '热门', '热点', '概念', '题材'
        ]
    }

    # 置信度权重配置
    CONFIDENCE_WEIGHTS = {
        'source_reliability': 0.25,  # 消息来源可信度
        'timeliness': 0.20,          # 消息时效性
        'content_quality': 0.20,     # 消息内容质量
        'market_validation': 0.15,   # 市场验证度
        'historical_accuracy': 0.10, # 历史准确度
        'technical_alignment': 0.10  # 技术面配合度
    }

    # 评级阈值
    RATING_THRESHOLDS = {
        'S': 85,   # S级：85分以上，极高置信度
        'A+': 75,  # A+级：75-85分，高置信度
        'A': 65,   # A级：65-75分，较高置信度
        'B': 50,   # B级：50-65分，中等置信度
        'C': 0     # C级：50分以下，低置信度
    }

    def __init__(self):
        """
        初始化重大利好消息挖掘器
        """
        self.news_collector = GlobalHotNewsCollector()
        self.stock_collectors = {}  # 缓存股票采集器

    def mine_from_news_stream(self, news_limit: int = 50, min_confidence: int = 30) -> List[Dict]:
        """
        从资讯流中挖掘重大利好消息

        Args:
            news_limit: 获取新闻的数量
            min_confidence: 最低置信度阈值（默认30分，降低阈值以发现更多机会）

        Returns:
            list: 挖掘结果列表，每个结果包含股票代码、利好消息、置信度等信息
        """
        logger.info("=" * 60)
        logger.info("🎯 开始从资讯流中挖掘重大利好消息")
        logger.info("=" * 60)

        results = []

        try:
            # 1. 获取全市场热门新闻
            logger.info(f"\n步骤1: 获取全市场热门新闻 TOP {news_limit}...")
            news_list = self.news_collector.get_top_news(limit=news_limit)
            logger.info(f"  ✓ 获取到 {len(news_list)} 条新闻")

            # 2. 分析每条新闻
            logger.info(f"\n步骤2: 分析新闻内容，识别利好消息和股票代码...")
            for idx, news in enumerate(news_list, 1):
                title = news.get('title', '')
                logger.info(f"\n  [{idx}/{len(news_list)}] 分析: {title[:60]}...")

                # 2.1 识别利好类型
                news_type, keywords = self._classify_positive_news(title)
                
                if not news_type:
                    logger.info(f"    - 非利好消息（未匹配到关键词）")
                    continue

                logger.info(f"    ✓ 识别为利好类型: {self.NEWS_TYPES[news_type]}")
                logger.info(f"    ✓ 匹配关键词: {', '.join(keywords)}")

                # 2.2 提取股票代码
                full_text = title + ' ' + news.get('url', '')
                stock_codes = self._extract_stock_codes(full_text)
                
                # 2.3 提取公司名称
                company_names = self._extract_company_names(title)
                
                if not stock_codes and not company_names:
                    logger.info(f"    - 未找到股票代码或公司名称")
                    continue

                if stock_codes:
                    logger.info(f"    ✓ 找到股票代码: {', '.join(stock_codes)}")
                if company_names:
                    logger.info(f"    ✓ 找到公司名称: {', '.join(company_names)}")

                # 2.4 对每个股票进行分析
                analyzed_stocks = set()
                has_stock_code = False
                
                if stock_codes:
                    for stock_code in stock_codes:
                        if stock_code in analyzed_stocks:
                            continue
                        analyzed_stocks.add(stock_code)
                        has_stock_code = True
                        
                        logger.info(f"    → 分析股票 {stock_code}...")

                        try:
                            # 获取股票基本信息
                            stock_info = self._get_stock_info(stock_code)
                            
                            # 进行置信度分析
                            confidence = self._analyze_confidence(news, stock_code, news_type, keywords)
                            
                            # 如果置信度达到阈值，加入结果
                            if confidence['overall_score'] >= min_confidence:
                                result = {
                                    'stock_code': stock_code,
                                    'stock_name': stock_info.get('name', ''),
                                    'company_names': company_names,
                                    'news_title': title,
                                    'news_url': news.get('url', ''),
                                    'news_source': news.get('source', ''),
                                    'news_type': news_type,
                                    'news_type_name': self.NEWS_TYPES[news_type],
                                    'keywords': keywords,
                                    'publish_time': news.get('publish_time', ''),
                                    'heat': news.get('heat', 0),
                                    'rank': news.get('rank', 0),
                                    'confidence': confidence,
                                    'confidence_score': confidence['overall_score'],
                                    'confidence_rating': confidence['rating'],
                                    'investment_advice': self._generate_investment_advice(confidence),
                                    'risk_warning': self._generate_risk_warning(confidence),
                                    'stock_info': stock_info
                                }
                                results.append(result)
                                logger.info(f"      ✓ 置信度: {confidence['overall_score']:.1f} ({confidence['rating']})")
                            else:
                                logger.info(f"      - 置信度不足: {confidence['overall_score']:.1f}")

                        except Exception as e:
                            logger.error(f"      ✗ 分析失败: {e}")
                            continue
                
                # 如果没有股票代码，但识别为利好消息，仍然记录
                if not has_stock_code:
                    logger.info(f"    → 无股票代码，基于新闻内容分析...")
                    
                    # 基于新闻内容进行置信度分析
                    confidence = self._analyze_confidence_for_news_only(news, news_type, keywords)
                    
                    # 如果置信度达到阈值，加入结果
                    if confidence['overall_score'] >= min_confidence:
                        result = {
                            'stock_code': '',
                            'stock_name': '',
                            'company_names': company_names,
                            'news_title': title,
                            'news_url': news.get('url', ''),
                            'news_source': news.get('source', ''),
                            'news_type': news_type,
                            'news_type_name': self.NEWS_TYPES[news_type],
                            'keywords': keywords,
                            'publish_time': news.get('publish_time', ''),
                            'heat': news.get('heat', 0),
                            'rank': news.get('rank', 0),
                            'confidence': confidence,
                            'confidence_score': confidence['overall_score'],
                            'confidence_rating': confidence['rating'],
                            'investment_advice': self._generate_investment_advice(confidence),
                            'risk_warning': self._generate_risk_warning(confidence),
                            'stock_info': {}
                        }
                        results.append(result)
                        logger.info(f"      ✓ 置信度: {confidence['overall_score']:.1f} ({confidence['rating']})")
                    else:
                        logger.info(f"      - 置信度不足: {confidence['overall_score']:.1f}")
                
                # 如果只有公司名称没有股票代码，记录到日志
                if company_names and not stock_codes:
                    logger.info(f"    ℹ 公司名称: {', '.join(company_names)}（可作为后续人工筛选参考）")

            # 3. 按置信度排序
            results.sort(key=lambda x: x['confidence_score'], reverse=True)

            logger.info(f"\n✓ 完成，共发现 {len(results)} 个重大利好机会")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"挖掘重大利好消息失败: {e}")

        return results

    def _extract_stock_codes(self, text: str) -> List[str]:
        """
        从文本中提取股票代码

        Args:
            text: 文本内容

        Returns:
            list: 股票代码列表
        """
        matches = self.STOCK_CODE_PATTERN.findall(text)
        return list(set(matches))  # 去重

    def _extract_company_names(self, text: str) -> List[str]:
        """
        从文本中提取公司名称

        Args:
            text: 文本内容

        Returns:
            list: 公司名称列表
        """
        matches = self.COMPANY_NAME_PATTERN.findall(text)
        # 过滤掉一些常见的非公司名称词汇
        exclude_words = {'中国', '美国', '全球', '全国', '市场', '行业', '产业', '政策', '政府', '部门', '国家', '地方', '城市', '区域', '地区', '国际', '国内', '海外', '外资', '民营', '国有', '股份', '集团', '公司', '科技', '实业', '控股', '有限', '发展', '投资', '能源', '医药', '生物', '电子', '通信', '汽车', '制造', '材料', '化工', '机械', '设备', '系统', '软件', '网络', '信息', '数据', '智能', '创新', '技术', '工程', '建设', '贸易', '商业', '服务', '文化', '传媒', '教育', '金融', '银行', '保险', '证券', '基金', '信托', '租赁', '物流', '运输', '仓储', '餐饮', '酒店', '旅游', '房地产', '建筑', '建材', '装饰', '环保', '新能源', '电力', '水务', '燃气', '供热', '矿业', '冶金', '钢铁', '有色金属', '黄金', '白银', '石油', '天然气', '煤炭', '化工', '化肥', '农药', '塑料', '橡胶', '玻璃', '陶瓷', '造纸', '印刷', '包装', '纺织', '服装', '鞋帽', '皮革', '家具', '家电', '电子', '通信', '计算机', '软件', '互联网', '电子商务', '游戏', '影视', '出版', '广告', '公关', '咨询', '法律', '会计', '审计', '税务', '咨询', '培训', '教育', '科研', '设计', '建筑', '工程', '监理', '检测', '认证', '评估', '拍卖', '典当', '担保', '租赁', '信托', '基金', '证券', '银行', '保险', '期货', '期权', '外汇'}
        
        filtered = [m for m in matches if m not in exclude_words and len(m) >= 2]
        return list(set(filtered))  # 去重

    def _classify_positive_news(self, title: str) -> Tuple[Optional[str], List[str]]:
        """
        识别利好消息类型

        Args:
            title: 新闻标题

        Returns:
            tuple: (利好类型, 匹配的关键词列表)
        """
        if not title:
            return None, []
        
        title = title.lower()
        
        # 记录所有匹配的关键词和类型
        all_matches = []
        
        for news_type, keywords in self.POSITIVE_KEYWORDS.items():
            matched_keywords = []
            for keyword in keywords:
                if keyword.lower() in title:
                    matched_keywords.append(keyword)
            
            if matched_keywords:
                all_matches.append({
                    'type': news_type,
                    'keywords': matched_keywords,
                    'count': len(matched_keywords)
                })
        
        # 如果没有匹配到任何关键词
        if not all_matches:
            return None, []
        
        # 按匹配关键词数量排序，选择匹配最多的类型
        all_matches.sort(key=lambda x: x['count'], reverse=True)
        best_match = all_matches[0]
        
        return best_match['type'], best_match['keywords']

    def _get_stock_info(self, stock_code: str) -> Dict:
        """
        获取股票基本信息

        Args:
            stock_code: 股票代码

        Returns:
            dict: 股票基本信息
        """
        try:
            if stock_code not in self.stock_collectors:
                self.stock_collectors[stock_code] = FundamentalDataCollector(stock_code)
            
            collector = self.stock_collectors[stock_code]
            financial_data = collector.get_financial_indicators()
            
            return {
                'name': financial_data.get('name', ''),
                'price': financial_data.get('price', 0),
                'pe': financial_data.get('pe', 0),
                'pb': financial_data.get('pb', 0),
                'market_cap': financial_data.get('market_cap', 0),
                'change_percent': financial_data.get('change_percent', 0)
            }
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 信息失败: {e}")
            return {}

    def _analyze_confidence(self, news: Dict, stock_code: str, news_type: str, keywords: List[str]) -> Dict:
        """
        分析置信度

        Args:
            news: 新闻信息
            stock_code: 股票代码
            news_type: 利好消息类型
            keywords: 匹配的关键词

        Returns:
            dict: 置信度分析结果
        """
        scores = {}

        # 1. 消息来源可信度
        scores['source_reliability'] = self._analyze_source_reliability(news)

        # 2. 消息时效性
        scores['timeliness'] = self._analyze_timeliness(news)

        # 3. 消息内容质量
        scores['content_quality'] = self._analyze_content_quality(news, news_type, keywords)

        # 4. 市场验证度
        scores['market_validation'] = self._analyze_market_validation(news)

        # 5. 历史准确度
        scores['historical_accuracy'] = self._analyze_historical_accuracy(news_type)

        # 6. 技术面配合度
        scores['technical_alignment'] = self._analyze_technical_alignment(stock_code)

        # 计算加权总分
        overall_score = sum(scores[key] * self.CONFIDENCE_WEIGHTS[key] for key in scores)

        # 确定评级
        rating = self._get_rating(overall_score)

        return {
            'scores': scores,
            'overall_score': overall_score,
            'rating': rating
        }

    def _analyze_source_reliability(self, news: Dict) -> float:
        """分析消息来源可信度"""
        source = news.get('source', '')
        
        # 官方来源得分高
        if '公告' in source or '公司' in source:
            return 100
        elif '东方财富' in source or '同花顺' in source:
            return 90
        elif '雪球' in source:
            return 75
        else:
            return 60

    def _analyze_timeliness(self, news: Dict) -> float:
        """分析消息时效性"""
        try:
            publish_time = news.get('publish_time', '')
            if not publish_time:
                return 50

            now = datetime.now()
            news_time = datetime.strptime(publish_time, '%Y-%m-%d %H:%M')
            
            hours_diff = (now - news_time).total_seconds() / 3600
            
            if hours_diff < 1:
                return 100
            elif hours_diff < 6:
                return 90
            elif hours_diff < 24:
                return 80
            elif hours_diff < 48:
                return 60
            else:
                return 40
        except Exception:
            return 50

    def _analyze_content_quality(self, news: Dict, news_type: str, keywords: List[str]) -> float:
        """分析消息内容质量"""
        score = 0
        
        # 关键词数量
        score += min(len(keywords) * 10, 30)
        
        # 标题长度
        title = news.get('title', '')
        if len(title) > 20:
            score += 20
        elif len(title) > 10:
            score += 10
        
        # 是否包含具体数字
        if re.search(r'\d+', title):
            score += 20
        
        # 热度
        heat = news.get('heat', 0)
        score += min(heat * 0.3, 30)
        
        return min(score, 100)

    def _analyze_market_validation(self, news: Dict) -> float:
        """分析市场验证度"""
        heat = news.get('heat', 0)
        rank = news.get('rank', 100)
        
        # 热度越高，排名越靠前，市场验证度越高
        score = heat * 0.5 + (100 - rank) * 0.5
        return min(score, 100)

    def _analyze_historical_accuracy(self, news_type: str) -> float:
        """分析历史准确度"""
        # 不同类型的利好消息历史准确度不同
        accuracy_map = {
            'restructuring': 85,
            'merger_acquisition': 80,
            'large_order': 90,
            'policy_support': 70,
            'performance_forecast': 75,
            'tech_breakthrough': 65,
            'strategic_cooperation': 60,
            'equity_incentive': 70,
            'dividend_buyback': 95,
            'other_major': 50
        }
        
        return accuracy_map.get(news_type, 50)

    def _analyze_technical_alignment(self, stock_code: str) -> float:
        """分析技术面配合度"""
        try:
            if stock_code not in self.stock_collectors:
                self.stock_collectors[stock_code] = FundamentalDataCollector(stock_code)
            
            collector = self.stock_collectors[stock_code]
            financial_data = collector.get_financial_indicators()
            
            score = 0
            
            # 涨幅
            change_percent = financial_data.get('change_percent', 0)
            if change_percent > 5:
                score += 30
            elif change_percent > 0:
                score += 20
            elif change_percent > -3:
                score += 10
            
            # PE估值
            pe = financial_data.get('pe', 0)
            if 0 < pe < 30:
                score += 30
            elif 30 <= pe < 60:
                score += 20
            elif pe >= 60:
                score += 10
            
            # 市值
            market_cap = financial_data.get('market_cap', 0)
            if market_cap < 100:  # 小市值
                score += 40
            elif market_cap < 500:  # 中市值
                score += 30
            else:  # 大市值
                score += 20
            
            return min(score, 100)
        except Exception as e:
            logger.warning(f"分析技术面配合度失败: {e}")
            return 50

    def _get_rating(self, score: float) -> str:
        """根据得分获取评级"""
        for rating, threshold in sorted(self.RATING_THRESHOLDS.items(), key=lambda x: x[1], reverse=True):
            if score >= threshold:
                return rating
        return 'C'

    def _generate_investment_advice(self, confidence: Dict) -> str:
        """生成投资建议"""
        score = confidence['overall_score']
        rating = confidence['rating']
        
        if rating == 'S':
            return "强烈建议关注，可考虑建仓"
        elif rating == 'A+':
            return "建议关注，可考虑小仓位试水"
        elif rating == 'A':
            return "值得跟踪，等待更好的入场时机"
        elif rating == 'B':
            return "谨慎观察，等待更多确认信号"
        else:
            return "不建议介入，风险较高"

    def _generate_risk_warning(self, confidence: Dict) -> str:
        """生成风险提示"""
        score = confidence['overall_score']
        
        warnings = []
        
        if score < 60:
            warnings.append("置信度较低，消息可能不准确")
        
        if confidence['scores'].get('technical_alignment', 0) < 50:
            warnings.append("技术面配合度不足")
        
        if confidence['scores'].get('market_validation', 0) < 50:
            warnings.append("市场关注度不高")
        
        if warnings:
            return "；".join(warnings)
        else:
            return "无明显风险"
