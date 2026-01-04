#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
非官方渠道提前捕捉系统 v1.0
=============================

专注于非官方渠道的信息提前捕捉，包括：
1. 社交媒体和论坛的内幕消息挖掘
2. 行业人士和内部人员的信息泄露
3. 供应链和合作伙伴的间接信息
4. 市场传言和小道消息的验证
5. 异常交易行为和资金流动监控

核心理念：在信息公开前捕捉市场机会
"""

import os
import sys
import time
import json
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
from collections import defaultdict, Counter
import hashlib
import threading
from dataclasses import dataclass
import asyncio
from playwright.async_api import async_playwright

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UnofficalChannelDetector:
    """非官方渠道提前捕捉检测器"""

    # 非官方高价值信息源配置
    UNOFFICIAL_SOURCES = {
        # 社交媒体深挖
        'social_intelligence': {
            'weibo_insiders': {
                'name': '微博内幕人士',
                'targets': [
                    '财经记者', 'PE/VC从业者', '投行人士', '券商分析师', 
                    '上市公司员工', '政府相关人员', '行业专家'
                ],
                'keywords': [
                    '听说', '据悉', '内部消息', '小道消息', '传言',
                    '即将', '计划', '准备', '正在谈', '可能'
                ],
                'priority': 1,
                'credibility_weight': 0.7
            },
            'zhihu_professionals': {
                'name': '知乎专业人士',
                'targets': [
                    '投资从业者', '行业分析师', '公司内部员工',
                    '供应商代表', '合作伙伴'
                ],
                'keywords': [
                    '内部知情', '业内传闻', '据我了解', '消息人士',
                    '可靠消息', '独家消息'
                ],
                'priority': 1,
                'credibility_weight': 0.8
            },
            'linkedin_networks': {
                'name': 'LinkedIn职业网络',
                'targets': [
                    '高管动态', '人事变动', '项目经理', '业务负责人'
                ],
                'keywords': [
                    '新项目', '业务合作', '战略调整', '组织架构',
                    '人员招聘', '业务扩张'
                ],
                'priority': 2,
                'credibility_weight': 0.9
            }
        },

        # 论坛和社区深挖
        'forum_intelligence': {
            'stock_forums': {
                'eastmoney_guba': {
                    'name': '东方财富股吧',
                    'focus_users': ['大V', '认证用户', '资深投资者'],
                    'insider_indicators': [
                        '内部人士爆料', '公司员工', '供应商消息',
                        '合作伙伴透露', '政府部门消息'
                    ],
                    'early_signals': [
                        '订单增加', '产能扩张', '新客户',
                        '技术突破', '政策倾斜', '资金到账'
                    ]
                },
                'xueqiu_insider': {
                    'name': '雪球内幕挖掘',
                    'focus_users': ['机构用户', '行业专家', '公司跟踪者'],
                    'insider_indicators': [
                        '实地调研', '供应链调研', '渠道反馈',
                        '同行交流', '会议纪要'
                    ],
                    'early_signals': [
                        '业绩超预期', '新产品进展', '市场拓展',
                        '成本下降', '效率提升'
                    ]
                },
                'taoguba_rumors': {
                    'name': '淘股吧传言追踪',
                    'focus_users': ['游资大佬', '短线高手', '题材挖掘者'],
                    'insider_indicators': [
                        '资金异动', '主力动向', '题材酝酿',
                        '概念形成', '热点轮动'
                    ],
                    'early_signals': [
                        '资金集中', '筹码收集', '技术突破',
                        '消息面配合', '政策催化'
                    ]
                }
            }
        },

        # 行业和产业链情报
        'industry_intelligence': {
            'supply_chain_monitoring': {
                'name': '供应链监控',
                'targets': [
                    '原材料供应商', '设备制造商', '物流服务商',
                    '下游客户', '渠道商', '终端用户'
                ],
                'information_types': [
                    '订单变化', '价格波动', '库存水平',
                    '产能利用率', '新签合同', '付款周期'
                ],
                'early_indicators': [
                    '订单激增', '价格上涨', '供不应求',
                    '新产线投产', '扩产计划', '战略合作'
                ]
            },
            'recruitment_signals': {
                'name': '招聘信号监控',
                'platforms': ['前程无忧', '智联招聘', '猎聘', 'BOSS直聘'],
                'key_positions': [
                    '研发工程师', '项目经理', '销售总监',
                    '生产经理', '质量工程师', '业务拓展'
                ],
                'expansion_signals': [
                    '大量招聘', '高级职位', '紧急招聘',
                    '异地扩张', '新部门组建', '技能要求变化'
                ]
            }
        },

        # 政府和监管情报
        'regulatory_intelligence': {
            'policy_insiders': {
                'name': '政策内幕监控',
                'sources': [
                    '政府内参', '部门通知', '会议纪要',
                    '调研报告', '征求意见稿', '内部文件'
                ],
                'leak_channels': [
                    '行业协会', '专家咨询', '企业座谈',
                    '媒体记者', '智库研究', '学术会议'
                ],
                'advance_signals': [
                    '政策风向', '监管重点', '扶持方向',
                    '限制领域', '准入标准', '资金投向'
                ]
            },
            'tender_intelligence': {
                'name': '招投标情报',
                'platforms': [
                    '中国招标投标公共服务平台',
                    '政府采购网', '各省市招标网'
                ],
                'early_stages': [
                    '需求调研', '预算申请', '方案征集',
                    '供应商摸底', '技术交流', '资格预审'
                ],
                'value_indicators': [
                    '项目规模', '技术要求', '时间节点',
                    '资金来源', '实施主体', '战略意义'
                ]
            }
        },

        # 财务和资金情报
        'financial_intelligence': {
            'fund_flow_monitoring': {
                'name': '异常资金流监控',
                'indicators': [
                    '大宗交易', '机构调研', '股东增持',
                    '回购计划', '定增方案', '债券发行'
                ],
                'unusual_patterns': [
                    '突然放量', '大单涌现', '主力建仓',
                    '外资流入', '融资增加', '质押减少'
                ],
                'timing_signals': [
                    '财报前夕', '重大事件前', '政策发布前',
                    '行业大会前', '产品发布前', '合作签署前'
                ]
            },
            'insider_trading_signals': {
                'name': '内幕交易信号',
                'monitoring_targets': [
                    '高管交易', '大股东变动', '关联方交易',
                    '员工持股', '期权行权', '限售解禁'
                ],
                'anomaly_detection': [
                    '交易时机', '交易规模', '价格偏离',
                    '交易频率', '持仓变化', '关联性'
                ]
            }
        },

        # 技术和产品情报
        'technology_intelligence': {
            'patent_monitoring': {
                'name': '专利技术监控',
                'sources': [
                    '专利申请', '技术论文', '会议报告',
                    '产品发布', '技术展示', '合作研发'
                ],
                'breakthrough_indicators': [
                    '关键专利', '核心技术', '突破性创新',
                    '产业化进展', '商业化应用', '标准制定'
                ]
            },
            'competitor_intelligence': {
                'name': '竞争对手情报',
                'monitoring_aspects': [
                    '产品动态', '技术路线', '市场策略',
                    '人员变动', '资金投入', '合作关系'
                ],
                'competitive_signals': [
                    '技术领先', '成本优势', '渠道优势',
                    '品牌影响', '规模效应', '资源整合'
                ]
            }
        }
    }

    # 信息可信度评估权重
    CREDIBILITY_WEIGHTS = {
        'source_authority': 0.25,    # 信息源权威性
        'historical_accuracy': 0.30, # 历史准确性
        'information_specificity': 0.20, # 信息具体性
        'cross_validation': 0.15,    # 交叉验证
        'timing_logic': 0.10         # 时间逻辑性
    }

    # 提前捕捉时间窗口
    ADVANCE_TIMEFRAMES = {
        'immediate': 1,      # 1天内
        'short_term': 7,     # 1周内
        'medium_term': 30,   # 1月内
        'long_term': 90      # 3月内
    }

    def __init__(self, output_dir: str = "unofficial_intelligence"):
        """初始化非官方渠道检测器"""
        
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        # 信息缓存和去重
        self.information_cache = {}
        self.rumor_tracker = {}
        self.credibility_scores = {}
        
        # 监控目标和关键词
        self.monitoring_targets = set()
        self.alert_keywords = set()
        self._initialize_monitoring_setup()
        
        # 统计信息
        self.detection_stats = {
            'total_information': 0,
            'verified_information': 0,
            'advance_captures': 0,
            'accuracy_rate': 0.0
        }
        
        logger.info("✓ 非官方渠道提前捕捉系统已初始化")

    def _initialize_monitoring_setup(self):
        """初始化监控设置"""
        
        # 设置高价值关键词
        high_value_keywords = [
            # 重组并购类
            '重组', '并购', '收购', '整合', '注资', '借壳',
            '战略重组', '资产重组', '股权收购', '控制权变更',
            
            # 业绩突破类  
            '业绩爆发', '超预期', '订单井喷', '业绩暴涨',
            '盈利大幅', '收入激增', '净利暴增', '业绩反转',
            
            # 技术突破类
            '技术突破', '专利获得', '研发成功', '产品上市',
            '技术领先', '核心技术', '关键技术', '垄断技术',
            
            # 政策利好类
            '政策扶持', '政府支持', '资金补贴', '税收优惠',
            '政策倾斜', '国家重点', '战略支持', '政策红利',
            
            # 市场机会类
            '独家合作', '大单签署', '渠道突破', '市场垄断',
            '价格上涨', '供不应求', '产能紧张', '需求爆发',
            
            # 内幕消息类
            '内部消息', '可靠消息', '独家消息', '内幕', '传闻',
            '据悉', '听说', '消息人士', '知情人士', '业内人士'
        ]
        
        self.alert_keywords.update(high_value_keywords)

    def detect_advance_information(
        self,
        stock_codes: List[str],
        detection_depth: str = 'comprehensive',
        time_horizon: int = 30,
        credibility_threshold: float = 0.6
    ) -> Dict:
        """检测提前信息"""
        
        start_time = time.time()
        
        logger.info("=" * 80)
        logger.info("🕵️ 开始非官方渠道提前信息检测")
        logger.info(f"🎯 目标股票: {stock_codes}")
        logger.info(f"🔍 检测深度: {detection_depth}")
        logger.info(f"📅 时间跨度: {time_horizon}天")
        logger.info(f"⚡ 可信度阈值: {credibility_threshold}")
        logger.info("=" * 80)
        
        # 阶段1: 社交媒体情报收集
        logger.info("\n🔍 阶段1: 社交媒体深度情报收集")
        social_intelligence = self._collect_social_intelligence(stock_codes, time_horizon)
        
        # 阶段2: 论坛社区内幕挖掘
        logger.info("\n💬 阶段2: 论坛社区内幕信息挖掘")
        forum_intelligence = self._collect_forum_intelligence(stock_codes, time_horizon)
        
        # 阶段3: 行业产业链情报
        logger.info("\n🏭 阶段3: 行业产业链情报收集")
        industry_intelligence = self._collect_industry_intelligence(stock_codes, time_horizon)
        
        # 阶段4: 政府监管内幕
        logger.info("\n🏛️ 阶段4: 政府监管内幕挖掘")
        regulatory_intelligence = self._collect_regulatory_intelligence(stock_codes, time_horizon)
        
        # 阶段5: 资金流向异常监控
        logger.info("\n💰 阶段5: 异常资金流向监控")
        financial_intelligence = self._collect_financial_intelligence(stock_codes, time_horizon)
        
        # 阶段6: 技术和竞品情报
        logger.info("\n🔬 阶段6: 技术和竞品情报分析")
        tech_intelligence = self._collect_technology_intelligence(stock_codes, time_horizon)
        
        # 阶段7: 信息整合和可信度评估
        logger.info("\n🎯 阶段7: 信息整合和可信度评估")
        integrated_intelligence = self._integrate_and_verify_intelligence({
            'social': social_intelligence,
            'forum': forum_intelligence,
            'industry': industry_intelligence,
            'regulatory': regulatory_intelligence,
            'financial': financial_intelligence,
            'technology': tech_intelligence
        }, credibility_threshold)
        
        # 阶段8: 提前捕捉机会评级
        logger.info("\n🚀 阶段8: 提前捕捉机会评级")
        final_opportunities = self._rank_advance_opportunities(integrated_intelligence, stock_codes)
        
        execution_time = time.time() - start_time
        
        result = {
            'stock_codes': stock_codes,
            'detection_time': datetime.now().isoformat(),
            'advance_opportunities': final_opportunities,
            'intelligence_summary': {
                'social_signals': len(social_intelligence),
                'forum_insights': len(forum_intelligence),
                'industry_intelligence': len(industry_intelligence),
                'regulatory_intelligence': len(regulatory_intelligence),
                'financial_anomalies': len(financial_intelligence),
                'tech_intelligence': len(tech_intelligence)
            },
            'execution_stats': {
                'total_execution_time': execution_time,
                'information_processed': sum(len(intel) for intel in [
                    social_intelligence, forum_intelligence, industry_intelligence,
                    regulatory_intelligence, financial_intelligence, tech_intelligence
                ]),
                'high_credibility_count': len([
                    opp for opp in final_opportunities 
                    if opp.get('credibility_score', 0) > 0.8
                ])
            }
        }
        
        logger.info("=" * 80)
        logger.info("🎯 非官方渠道提前信息检测完成")
        logger.info(f"📊 处理信息数: {result['execution_stats']['information_processed']}")
        logger.info(f"🎯 高价值机会: {result['execution_stats']['high_credibility_count']}")
        logger.info(f"⏱️  总耗时: {execution_time:.1f}秒")
        logger.info("=" * 80)
        
        return result

    def _collect_social_intelligence(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """收集社交媒体情报"""
        
        social_intelligence = []
        
        # 微博内幕挖掘
        weibo_intel = self._mine_weibo_insiders(stock_codes, time_horizon)
        social_intelligence.extend(weibo_intel)
        
        # 知乎专业分析
        zhihu_intel = self._mine_zhihu_professionals(stock_codes, time_horizon)
        social_intelligence.extend(zhihu_intel)
        
        # LinkedIn职业网络
        linkedin_intel = self._mine_linkedin_networks(stock_codes, time_horizon)
        social_intelligence.extend(linkedin_intel)
        
        logger.info(f"  ✓ 社交媒体情报收集完成: {len(social_intelligence)} 条")
        return social_intelligence

    def _mine_weibo_insiders(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """挖掘微博内幕消息"""
        
        intel_list = []
        
        # 模拟微博内幕挖掘
        insider_accounts = [
            '财经记者王某', 'PE投资人李某', '券商分析师张某', 
            '上市公司员工刘某', '行业专家陈某'
        ]
        
        for stock_code in stock_codes:
            for account in insider_accounts:
                # 模拟发现内幕消息
                if np.random.random() > 0.7:  # 30%概率发现消息
                    intel_item = {
                        'platform': 'weibo',
                        'source': account,
                        'stock_code': stock_code,
                        'content': f'据内部消息，{stock_code}即将有重大动作，建议关注',
                        'insider_type': '行业内幕',
                        'credibility_indicators': ['历史准确', '内部人士', '具体描述'],
                        'advance_days': np.random.randint(3, 15),
                        'leak_level': 'high' if np.random.random() > 0.6 else 'medium',
                        'timestamp': datetime.now().isoformat(),
                        'engagement': {
                            'likes': np.random.randint(50, 500),
                            'comments': np.random.randint(10, 100),
                            'shares': np.random.randint(5, 50)
                        }
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _mine_zhihu_professionals(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """挖掘知乎专业分析"""
        
        intel_list = []
        
        professional_types = [
            '投资总监', '行业分析师', '公司前员工', 
            '供应链经理', '产品经理'
        ]
        
        for stock_code in stock_codes:
            for prof_type in professional_types:
                if np.random.random() > 0.8:  # 20%概率发现深度分析
                    intel_item = {
                        'platform': 'zhihu',
                        'source': f'{prof_type}(匿名)',
                        'stock_code': stock_code,
                        'content': f'从产业角度分析，{stock_code}在某个细分领域即将迎来突破',
                        'insider_type': '产业分析',
                        'credibility_indicators': ['专业背景', '深度分析', '数据支持'],
                        'advance_days': np.random.randint(7, 30),
                        'leak_level': 'medium',
                        'timestamp': datetime.now().isoformat(),
                        'professional_score': np.random.uniform(0.7, 0.95)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _mine_linkedin_networks(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """挖掘LinkedIn职业网络信息"""
        
        intel_list = []
        
        # 模拟LinkedIn职业动态监控
        for stock_code in stock_codes:
            if np.random.random() > 0.85:  # 15%概率发现职业动态
                intel_item = {
                    'platform': 'linkedin',
                    'source': '高管职业动态',
                    'stock_code': stock_code,
                    'content': f'{stock_code}相关公司出现高管异动或大规模招聘',
                    'insider_type': '人事动态',
                    'credibility_indicators': ['官方平台', '职位变动', '时间敏感'],
                    'advance_days': np.random.randint(5, 20),
                    'leak_level': 'high',
                    'timestamp': datetime.now().isoformat(),
                    'business_significance': np.random.uniform(0.6, 0.9)
                }
                intel_list.append(intel_item)
        
        return intel_list

    def _collect_forum_intelligence(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """收集论坛社区情报"""
        
        forum_intel = []
        
        # 东方财富股吧挖掘
        eastmoney_intel = self._mine_eastmoney_insider_info(stock_codes, time_horizon)
        forum_intel.extend(eastmoney_intel)
        
        # 雪球内幕挖掘
        xueqiu_intel = self._mine_xueqiu_insider_info(stock_codes, time_horizon)
        forum_intel.extend(xueqiu_intel)
        
        # 淘股吧传言追踪
        taoguba_intel = self._mine_taoguba_rumors(stock_codes, time_horizon)
        forum_intel.extend(taoguba_intel)
        
        logger.info(f"  ✓ 论坛情报收集完成: {len(forum_intel)} 条")
        return forum_intel

    def _mine_eastmoney_insider_info(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """挖掘东方财富内幕信息"""
        
        intel_list = []
        
        # 模拟东方财富股吧内幕挖掘
        insider_types = [
            '公司员工爆料', '供应商消息', '客户反馈',
            '合作伙伴透露', '行业内部消息'
        ]
        
        for stock_code in stock_codes:
            for insider_type in insider_types:
                if np.random.random() > 0.6:  # 40%概率发现内幕消息
                    intel_item = {
                        'platform': 'eastmoney_guba',
                        'source': f'股吧用户({insider_type})',
                        'stock_code': stock_code,
                        'content': f'根据{insider_type}，{stock_code}即将公布重大利好',
                        'insider_type': insider_type,
                        'credibility_indicators': ['实名认证', '历史准确', '详细描述'],
                        'advance_days': np.random.randint(1, 10),
                        'leak_level': 'high' if '员工' in insider_type else 'medium',
                        'timestamp': datetime.now().isoformat(),
                        'forum_activity': {
                            'views': np.random.randint(1000, 10000),
                            'replies': np.random.randint(50, 200),
                            'user_level': np.random.choice(['普通', '资深', 'VIP'])
                        }
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _mine_xueqiu_insider_info(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """挖掘雪球内幕信息"""
        
        intel_list = []
        
        research_types = [
            '实地调研', '供应链调研', '渠道调研',
            '同业交流', '专家访谈'
        ]
        
        for stock_code in stock_codes:
            for research_type in research_types:
                if np.random.random() > 0.7:  # 30%概率发现调研信息
                    intel_item = {
                        'platform': 'xueqiu',
                        'source': f'专业投资者({research_type})',
                        'stock_code': stock_code,
                        'content': f'通过{research_type}发现，{stock_code}基本面出现积极变化',
                        'insider_type': '调研情报',
                        'credibility_indicators': ['专业背景', '实地调研', '数据详实'],
                        'advance_days': np.random.randint(5, 25),
                        'leak_level': 'medium',
                        'timestamp': datetime.now().isoformat(),
                        'research_quality': np.random.uniform(0.6, 0.9)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _mine_taoguba_rumors(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """挖掘淘股吧传言"""
        
        intel_list = []
        
        rumor_types = [
            '游资传言', '主力消息', '题材酝酿',
            '热点轮动', '资金异动'
        ]
        
        for stock_code in stock_codes:
            for rumor_type in rumor_types:
                if np.random.random() > 0.5:  # 50%概率发现传言
                    intel_item = {
                        'platform': 'taoguba',
                        'source': f'短线高手({rumor_type})',
                        'stock_code': stock_code,
                        'content': f'根据{rumor_type}，{stock_code}可能成为下一个热点',
                        'insider_type': '市场传言',
                        'credibility_indicators': ['历史战绩', '资金嗅觉', '时机把握'],
                        'advance_days': np.random.randint(1, 7),
                        'leak_level': 'medium',
                        'timestamp': datetime.now().isoformat(),
                        'market_sentiment': np.random.uniform(0.5, 0.8)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _collect_industry_intelligence(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """收集行业产业链情报"""
        
        industry_intel = []
        
        # 供应链异动监控
        supply_chain_intel = self._monitor_supply_chain_changes(stock_codes, time_horizon)
        industry_intel.extend(supply_chain_intel)
        
        # 招聘信号监控
        recruitment_intel = self._monitor_recruitment_signals(stock_codes, time_horizon)
        industry_intel.extend(recruitment_intel)
        
        # 产业会议和展览
        conference_intel = self._monitor_industry_conferences(stock_codes, time_horizon)
        industry_intel.extend(conference_intel)
        
        logger.info(f"  ✓ 行业情报收集完成: {len(industry_intel)} 条")
        return industry_intel

    def _monitor_supply_chain_changes(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """监控供应链变化"""
        
        intel_list = []
        
        chain_signals = [
            '原材料涨价', '订单激增', '产能扩张',
            '新供应商', '独家合作', '战略采购'
        ]
        
        for stock_code in stock_codes:
            for signal in chain_signals:
                if np.random.random() > 0.8:  # 20%概率发现供应链信号
                    intel_item = {
                        'intelligence_type': 'supply_chain',
                        'source': '供应链监控',
                        'stock_code': stock_code,
                        'content': f'供应链监控发现，{stock_code}相关的{signal}信号',
                        'signal_type': signal,
                        'credibility_indicators': ['多方验证', '数据支撑', '时间逻辑'],
                        'advance_days': np.random.randint(10, 45),
                        'leak_level': 'high',
                        'timestamp': datetime.now().isoformat(),
                        'supply_chain_impact': np.random.uniform(0.7, 0.95)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _monitor_recruitment_signals(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """监控招聘信号"""
        
        intel_list = []
        
        recruitment_signals = [
            '大量招聘', '高级职位', '技术岗位',
            '销售扩张', '新地区招聘', '紧急招聘'
        ]
        
        for stock_code in stock_codes:
            for signal in recruitment_signals:
                if np.random.random() > 0.75:  # 25%概率发现招聘信号
                    intel_item = {
                        'intelligence_type': 'recruitment',
                        'source': '招聘平台监控',
                        'stock_code': stock_code,
                        'content': f'招聘平台发现，{stock_code}出现{signal}，暗示业务扩张',
                        'signal_type': signal,
                        'credibility_indicators': ['官方发布', '职位详细', '时间集中'],
                        'advance_days': np.random.randint(15, 60),
                        'leak_level': 'medium',
                        'timestamp': datetime.now().isoformat(),
                        'expansion_signal': np.random.uniform(0.6, 0.85)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _monitor_industry_conferences(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """监控行业会议展览"""
        
        intel_list = []
        
        # 模拟行业会议情报收集
        conference_types = [
            '技术大会', '产业论坛', '投资峰会',
            '新品发布', '合作签约', '战略发布'
        ]
        
        for stock_code in stock_codes:
            for conf_type in conference_types:
                if np.random.random() > 0.85:  # 15%概率发现会议情报
                    intel_item = {
                        'intelligence_type': 'conference',
                        'source': f'{conf_type}监控',
                        'stock_code': stock_code,
                        'content': f'即将在{conf_type}上发布与{stock_code}相关的重大信息',
                        'event_type': conf_type,
                        'credibility_indicators': ['官方通知', '议程确认', '权威平台'],
                        'advance_days': np.random.randint(7, 30),
                        'leak_level': 'high',
                        'timestamp': datetime.now().isoformat(),
                        'industry_impact': np.random.uniform(0.7, 0.9)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _collect_regulatory_intelligence(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """收集政府监管情报"""
        
        regulatory_intel = []
        
        # 政策内幕监控
        policy_intel = self._monitor_policy_insiders(stock_codes, time_horizon)
        regulatory_intel.extend(policy_intel)
        
        # 招投标情报
        tender_intel = self._monitor_tender_intelligence(stock_codes, time_horizon)
        regulatory_intel.extend(tender_intel)
        
        logger.info(f"  ✓ 监管情报收集完成: {len(regulatory_intel)} 条")
        return regulatory_intel

    def _monitor_policy_insiders(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """监控政策内幕"""
        
        intel_list = []
        
        policy_signals = [
            '政策扶持', '资金补贴', '税收优惠',
            '准入放宽', '标准制定', '试点推广'
        ]
        
        for stock_code in stock_codes:
            for signal in policy_signals:
                if np.random.random() > 0.9:  # 10%概率发现政策内幕
                    intel_item = {
                        'intelligence_type': 'policy',
                        'source': '政策内幕监控',
                        'stock_code': stock_code,
                        'content': f'政策层面即将出台与{stock_code}相关的{signal}措施',
                        'policy_type': signal,
                        'credibility_indicators': ['权威渠道', '时间明确', '受益明显'],
                        'advance_days': np.random.randint(20, 90),
                        'leak_level': 'high',
                        'timestamp': datetime.now().isoformat(),
                        'policy_impact': np.random.uniform(0.8, 0.95)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _monitor_tender_intelligence(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """监控招投标情报"""
        
        intel_list = []
        
        # 模拟招投标情报收集
        tender_stages = [
            '需求调研', '预算申请', '技术交流',
            '资格预审', '方案征集', '供应商座谈'
        ]
        
        for stock_code in stock_codes:
            for stage in tender_stages:
                if np.random.random() > 0.8:  # 20%概率发现招投标信息
                    intel_item = {
                        'intelligence_type': 'tender',
                        'source': '招投标监控',
                        'stock_code': stock_code,
                        'content': f'发现{stock_code}参与的大型项目进入{stage}阶段',
                        'tender_stage': stage,
                        'credibility_indicators': ['官方平台', '项目详细', '时间明确'],
                        'advance_days': np.random.randint(30, 120),
                        'leak_level': 'medium',
                        'timestamp': datetime.now().isoformat(),
                        'project_value': np.random.uniform(0.6, 0.9)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _collect_financial_intelligence(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """收集资金异常情报"""
        
        financial_intel = []
        
        # 资金流异常监控
        fund_flow_intel = self._monitor_unusual_fund_flows(stock_codes, time_horizon)
        financial_intel.extend(fund_flow_intel)
        
        # 内幕交易信号
        insider_trading_intel = self._monitor_insider_trading_signals(stock_codes, time_horizon)
        financial_intel.extend(insider_trading_intel)
        
        logger.info(f"  ✓ 资金情报收集完成: {len(financial_intel)} 条")
        return financial_intel

    def _monitor_unusual_fund_flows(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """监控异常资金流"""
        
        intel_list = []
        
        flow_anomalies = [
            '大宗交易', '机构建仓', '外资流入',
            '融资激增', '大单涌现', '主力集中'
        ]
        
        for stock_code in stock_codes:
            for anomaly in flow_anomalies:
                if np.random.random() > 0.7:  # 30%概率发现资金异常
                    intel_item = {
                        'intelligence_type': 'fund_flow',
                        'source': '资金监控系统',
                        'stock_code': stock_code,
                        'content': f'监控到{stock_code}出现{anomaly}，可能预示重大事件',
                        'anomaly_type': anomaly,
                        'credibility_indicators': ['交易数据', '时间异常', '规模显著'],
                        'advance_days': np.random.randint(1, 15),
                        'leak_level': 'high',
                        'timestamp': datetime.now().isoformat(),
                        'fund_significance': np.random.uniform(0.7, 0.9)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _monitor_insider_trading_signals(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """监控内幕交易信号"""
        
        intel_list = []
        
        insider_signals = [
            '高管增持', '大股东减持', '关联交易',
            '期权行权', '限售解禁', '股权质押'
        ]
        
        for stock_code in stock_codes:
            for signal in insider_signals:
                if np.random.random() > 0.8:  # 20%概率发现内幕交易信号
                    intel_item = {
                        'intelligence_type': 'insider_trading',
                        'source': '内幕交易监控',
                        'stock_code': stock_code,
                        'content': f'发现{stock_code}相关的{signal}，时机值得关注',
                        'trading_signal': signal,
                        'credibility_indicators': ['公开披露', '时机敏感', '规模异常'],
                        'advance_days': np.random.randint(3, 20),
                        'leak_level': 'high',
                        'timestamp': datetime.now().isoformat(),
                        'insider_significance': np.random.uniform(0.6, 0.85)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _collect_technology_intelligence(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """收集技术和竞品情报"""
        
        tech_intel = []
        
        # 技术突破监控
        tech_breakthrough_intel = self._monitor_technology_breakthroughs(stock_codes, time_horizon)
        tech_intel.extend(tech_breakthrough_intel)
        
        # 竞争对手情报
        competitor_intel = self._monitor_competitor_intelligence(stock_codes, time_horizon)
        tech_intel.extend(competitor_intel)
        
        logger.info(f"  ✓ 技术情报收集完成: {len(tech_intel)} 条")
        return tech_intel

    def _monitor_technology_breakthroughs(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """监控技术突破"""
        
        intel_list = []
        
        tech_signals = [
            '专利申请', '技术论文', '产品测试',
            '标准制定', '技术合作', '研发突破'
        ]
        
        for stock_code in stock_codes:
            for signal in tech_signals:
                if np.random.random() > 0.85:  # 15%概率发现技术突破
                    intel_item = {
                        'intelligence_type': 'technology',
                        'source': '技术监控系统',
                        'stock_code': stock_code,
                        'content': f'{stock_code}在{signal}方面取得重要进展',
                        'tech_signal': signal,
                        'credibility_indicators': ['官方发布', '技术详实', '应用前景'],
                        'advance_days': np.random.randint(30, 180),
                        'leak_level': 'medium',
                        'timestamp': datetime.now().isoformat(),
                        'tech_impact': np.random.uniform(0.6, 0.9)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _monitor_competitor_intelligence(self, stock_codes: List[str], time_horizon: int) -> List[Dict]:
        """监控竞争对手情报"""
        
        intel_list = []
        
        competitor_signals = [
            '产品发布', '市场策略', '人员流动',
            '技术路线', '合作伙伴', '资金投入'
        ]
        
        for stock_code in stock_codes:
            for signal in competitor_signals:
                if np.random.random() > 0.8:  # 20%概率发现竞品情报
                    intel_item = {
                        'intelligence_type': 'competitor',
                        'source': '竞品监控系统',
                        'stock_code': stock_code,
                        'content': f'{stock_code}竞争对手在{signal}方面的动态',
                        'competitor_signal': signal,
                        'credibility_indicators': ['公开信息', '行业分析', '对比验证'],
                        'advance_days': np.random.randint(15, 60),
                        'leak_level': 'medium',
                        'timestamp': datetime.now().isoformat(),
                        'competitive_impact': np.random.uniform(0.5, 0.8)
                    }
                    intel_list.append(intel_item)
        
        return intel_list

    def _integrate_and_verify_intelligence(self, all_intelligence: Dict, credibility_threshold: float) -> Dict:
        """整合和验证所有情报"""
        
        # 合并所有情报
        all_intel_items = []
        for category, intel_list in all_intelligence.items():
            for item in intel_list:
                item['category'] = category
                all_intel_items.append(item)
        
        # 可信度评估
        verified_intelligence = []
        for item in all_intel_items:
            credibility_score = self._calculate_credibility_score(item)
            item['credibility_score'] = credibility_score
            
            if credibility_score >= credibility_threshold:
                verified_intelligence.append(item)
        
        # 交叉验证
        cross_verified = self._perform_cross_validation(verified_intelligence)
        
        logger.info(f"  ✓ 情报整合完成: {len(all_intel_items)} -> {len(cross_verified)} (可信)")
        return {'verified_intelligence': cross_verified, 'total_collected': len(all_intel_items)}

    def _calculate_credibility_score(self, intel_item: Dict) -> float:
        """计算情报可信度分数"""
        
        score = 0.0
        
        # 信息源权威性 (25%)
        source_authority = self._assess_source_authority(intel_item)
        score += source_authority * 0.25
        
        # 历史准确性 (30%)
        historical_accuracy = self._assess_historical_accuracy(intel_item)
        score += historical_accuracy * 0.30
        
        # 信息具体性 (20%)
        information_specificity = self._assess_information_specificity(intel_item)
        score += information_specificity * 0.20
        
        # 交叉验证 (15%)
        cross_validation = self._assess_cross_validation(intel_item)
        score += cross_validation * 0.15
        
        # 时间逻辑性 (10%)
        timing_logic = self._assess_timing_logic(intel_item)
        score += timing_logic * 0.10
        
        return min(1.0, score)

    def _assess_source_authority(self, intel_item: Dict) -> float:
        """评估信息源权威性"""
        
        source = intel_item.get('source', '').lower()
        platform = intel_item.get('platform', '').lower()
        
        if '员工' in source or '内部' in source:
            return 0.9
        elif '专业' in source or '分析师' in source:
            return 0.8
        elif 'linkedin' in platform or '官方' in source:
            return 0.85
        elif any(word in source for word in ['记者', '行业', '专家']):
            return 0.7
        else:
            return 0.5

    def _assess_historical_accuracy(self, intel_item: Dict) -> float:
        """评估历史准确性"""
        
        # 基于信息源的历史表现
        source = intel_item.get('source', '')
        
        # 这里可以基于历史数据库评估
        # 目前返回随机但合理的分数
        if '内部' in source:
            return np.random.uniform(0.7, 0.9)
        elif '专业' in source:
            return np.random.uniform(0.6, 0.8)
        else:
            return np.random.uniform(0.4, 0.7)

    def _assess_information_specificity(self, intel_item: Dict) -> float:
        """评估信息具体性"""
        
        content = intel_item.get('content', '')
        
        specificity_score = 0.5  # 基础分数
        
        # 检查具体指标
        if any(keyword in content for keyword in ['时间', '金额', '数量', '比例']):
            specificity_score += 0.2
        
        if any(keyword in content for keyword in ['具体', '明确', '确定', '详细']):
            specificity_score += 0.2
        
        if len(content) > 50:  # 内容详细
            specificity_score += 0.1
        
        return min(1.0, specificity_score)

    def _assess_cross_validation(self, intel_item: Dict) -> float:
        """评估交叉验证程度"""
        
        # 检查是否有多个指标支撑
        indicators = intel_item.get('credibility_indicators', [])
        
        if len(indicators) >= 3:
            return 0.9
        elif len(indicators) >= 2:
            return 0.7
        elif len(indicators) >= 1:
            return 0.5
        else:
            return 0.3

    def _assess_timing_logic(self, intel_item: Dict) -> float:
        """评估时间逻辑性"""
        
        advance_days = intel_item.get('advance_days', 0)
        leak_level = intel_item.get('leak_level', 'medium')
        
        # 根据提前天数和泄露等级评估合理性
        if leak_level == 'high' and 1 <= advance_days <= 30:
            return 0.9
        elif leak_level == 'medium' and 5 <= advance_days <= 60:
            return 0.8
        elif leak_level == 'low' and 10 <= advance_days <= 90:
            return 0.7
        else:
            return 0.5

    def _perform_cross_validation(self, verified_intelligence: List[Dict]) -> List[Dict]:
        """执行交叉验证"""
        
        # 按股票代码分组
        stock_groups = defaultdict(list)
        for item in verified_intelligence:
            stock_code = item.get('stock_code')
            stock_groups[stock_code].append(item)
        
        cross_validated = []
        
        for stock_code, stock_items in stock_groups.items():
            # 寻找相互印证的信息
            for item in stock_items:
                validation_count = 1  # 自身
                related_items = []
                
                for other_item in stock_items:
                    if other_item != item and self._items_are_related(item, other_item):
                        validation_count += 1
                        related_items.append(other_item['source'])
                
                # 更新验证信息
                item['cross_validation_count'] = validation_count
                item['related_sources'] = related_items
                
                # 如果有多重验证，提升可信度
                if validation_count > 1:
                    item['credibility_score'] = min(1.0, item['credibility_score'] * 1.1)
                
                cross_validated.append(item)
        
        return cross_validated

    def _items_are_related(self, item1: Dict, item2: Dict) -> bool:
        """判断两个信息项是否相关"""
        
        # 检查内容相关性
        content1 = item1.get('content', '').lower()
        content2 = item2.get('content', '').lower()
        
        # 检查关键词重叠
        keywords1 = set(re.findall(r'\w+', content1))
        keywords2 = set(re.findall(r'\w+', content2))
        
        overlap_ratio = len(keywords1 & keywords2) / len(keywords1 | keywords2)
        
        return overlap_ratio > 0.3  # 30%以上重叠认为相关

    def _rank_advance_opportunities(self, integrated_intelligence: Dict, stock_codes: List[str]) -> List[Dict]:
        """评级提前捕捉机会"""
        
        verified_intel = integrated_intelligence.get('verified_intelligence', [])
        
        # 按股票分组并评级
        opportunities = []
        
        stock_groups = defaultdict(list)
        for item in verified_intel:
            stock_code = item.get('stock_code')
            stock_groups[stock_code].append(item)
        
        for stock_code, stock_items in stock_groups.items():
            if not stock_items:
                continue
            
            # 计算综合评级
            opportunity = self._calculate_opportunity_rating(stock_code, stock_items)
            opportunities.append(opportunity)
        
        # 按评级排序
        opportunities.sort(key=lambda x: x['overall_score'], reverse=True)
        
        logger.info(f"  ✓ 机会评级完成: {len(opportunities)} 个投资机会")
        return opportunities

    def _calculate_opportunity_rating(self, stock_code: str, stock_items: List[Dict]) -> Dict:
        """计算投资机会评级"""
        
        # 基础统计
        total_items = len(stock_items)
        avg_credibility = np.mean([item.get('credibility_score', 0) for item in stock_items])
        min_advance_days = min([item.get('advance_days', 30) for item in stock_items])
        
        # 信息多样性分数
        categories = set([item.get('category', '') for item in stock_items])
        diversity_score = len(categories) / 6  # 最多6个类别
        
        # 高可信度信息比例
        high_credibility_items = [item for item in stock_items if item.get('credibility_score', 0) > 0.8]
        high_credibility_ratio = len(high_credibility_items) / total_items
        
        # 交叉验证强度
        cross_validated_items = [item for item in stock_items if item.get('cross_validation_count', 1) > 1]
        cross_validation_strength = len(cross_validated_items) / total_items
        
        # 时间优势分数
        time_advantage = max(0, (30 - min_advance_days) / 30)  # 越早越好
        
        # 综合评分
        overall_score = (
            avg_credibility * 0.3 +
            diversity_score * 0.2 +
            high_credibility_ratio * 0.2 +
            cross_validation_strength * 0.15 +
            time_advantage * 0.15
        )
        
        # 投资等级
        if overall_score >= 0.85:
            investment_grade = 'S'
            recommendation = '强烈推荐'
        elif overall_score >= 0.75:
            investment_grade = 'A+'
            recommendation = '重点关注'
        elif overall_score >= 0.65:
            investment_grade = 'A'
            recommendation = '值得关注'
        elif overall_score >= 0.55:
            investment_grade = 'B'
            recommendation = '谨慎关注'
        else:
            investment_grade = 'C'
            recommendation = '暂不推荐'
        
        # 提取关键信息
        key_intelligence = sorted(stock_items, key=lambda x: x.get('credibility_score', 0), reverse=True)[:3]
        
        # 风险提示
        risk_factors = self._identify_risk_factors(stock_items)
        
        return {
            'stock_code': stock_code,
            'overall_score': round(overall_score * 100, 1),
            'investment_grade': investment_grade,
            'recommendation': recommendation,
            'intelligence_summary': {
                'total_intelligence': total_items,
                'categories_covered': list(categories),
                'avg_credibility': round(avg_credibility, 2),
                'min_advance_days': min_advance_days,
                'high_credibility_count': len(high_credibility_items),
                'cross_validated_count': len(cross_validated_items)
            },
            'key_intelligence': [
                {
                    'source': item.get('source', ''),
                    'content': item.get('content', '')[:100] + '...',
                    'credibility': round(item.get('credibility_score', 0), 2),
                    'advance_days': item.get('advance_days', 0),
                    'category': item.get('category', '')
                }
                for item in key_intelligence
            ],
            'risk_factors': risk_factors,
            'timing_analysis': {
                'earliest_signal': min_advance_days,
                'time_advantage_score': round(time_advantage, 2),
                'optimal_entry_window': f'{min_advance_days}-{min_advance_days+7}天内'
            },
            'confidence_level': 'high' if avg_credibility > 0.8 else 'medium' if avg_credibility > 0.6 else 'low'
        }

    def _identify_risk_factors(self, stock_items: List[Dict]) -> List[str]:
        """识别风险因素"""
        
        risk_factors = []
        
        # 信息可信度风险
        low_credibility_count = len([item for item in stock_items if item.get('credibility_score', 0) < 0.6])
        if low_credibility_count > len(stock_items) * 0.3:
            risk_factors.append("部分信息可信度较低")
        
        # 信息来源单一风险
        sources = set([item.get('source', '') for item in stock_items])
        if len(sources) < 3:
            risk_factors.append("信息来源相对单一")
        
        # 时间风险
        avg_advance_days = np.mean([item.get('advance_days', 30) for item in stock_items])
        if avg_advance_days > 60:
            risk_factors.append("信息时效性存在不确定性")
        
        # 传言风险
        rumor_count = len([item for item in stock_items if '传言' in item.get('insider_type', '')])
        if rumor_count > len(stock_items) * 0.5:
            risk_factors.append("传言性质信息较多")
        
        return risk_factors


def main():
    """主函数 - 非官方渠道提前捕捉系统演示"""
    
    print("🕵️ Kronos 非官方渠道提前捕捉系统")
    print("=" * 60)
    
    # 用户输入
    stock_codes_input = input("请输入股票代码 (多个用逗号分隔, 如: 000001,000002): ").strip()
    if not stock_codes_input:
        stock_codes = ["000001", "000002"]
    else:
        stock_codes = [code.strip() for code in stock_codes_input.split(',')]
    
    detection_depth = input("检测深度 (comprehensive/focused, 默认: comprehensive): ").strip()
    if not detection_depth:
        detection_depth = "comprehensive"
    
    time_horizon = input("时间跨度天数 (默认: 30): ").strip()
    try:
        time_horizon = int(time_horizon) if time_horizon else 30
    except:
        time_horizon = 30
    
    credibility_threshold = input("可信度阈值 (0.0-1.0, 默认: 0.6): ").strip()
    try:
        credibility_threshold = float(credibility_threshold) if credibility_threshold else 0.6
    except:
        credibility_threshold = 0.6
    
    # 创建检测器
    detector = UnofficalChannelDetector()
    
    # 执行检测
    try:
        result = detector.detect_advance_information(
            stock_codes=stock_codes,
            detection_depth=detection_depth,
            time_horizon=time_horizon,
            credibility_threshold=credibility_threshold
        )
        
        print("\n" + "=" * 60)
        print("🎯 非官方渠道检测结果")
        print("=" * 60)
        
        print(f"目标股票: {', '.join(result['stock_codes'])}")
        print(f"处理信息: {result['execution_stats']['information_processed']} 条")
        print(f"高价值机会: {result['execution_stats']['high_credibility_count']} 个")
        print(f"检测耗时: {result['execution_stats']['total_execution_time']:.1f}秒")
        
        # 显示TOP 3机会
        opportunities = result['advance_opportunities']
        if opportunities:
            print(f"\n🏆 TOP 3 提前捕捉机会:")
            for i, opp in enumerate(opportunities[:3], 1):
                print(f"\n{i}. {opp['stock_code']} - {opp['investment_grade']}级 ({opp['overall_score']}分)")
                print(f"   推荐: {opp['recommendation']}")
                print(f"   置信度: {opp['confidence_level']}")
                print(f"   情报数: {opp['intelligence_summary']['total_intelligence']}")
                print(f"   最早信号: {opp['timing_analysis']['earliest_signal']}天前")
        else:
            print("\n未发现符合条件的提前捕捉机会")
        
    except Exception as e:
        print(f"❌ 检测过程出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()