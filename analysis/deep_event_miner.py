#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度事件挖掘系统 v2.0
====================

突破表面信息，深度挖掘隐含的重大投资事件

核心策略：
1. 多维度信号交叉验证 - 不依赖单一消息源
2. 隐含信号提取 - 从异常数据模式中发现事件
3. 事件链路追踪 - 构建事件发展时间线
4. 预测性分析 - 基于历史模式预测事件发展

挖掘层次：
Level 1: 显性信息 - 直接的公告和新闻
Level 2: 半隐含信息 - 论坛讨论、资金流向异常
Level 3: 深层隐含信息 - 关联企业动态、产业链信号
Level 4: 预测性信息 - 基于模式识别的事件预测

应用场景：
- 重大重组前的蛛丝马迹
- 大订单签署的早期信号
- 技术突破的前期布局
- 政策利好的提前感知
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
import logging
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict, Counter
import requests
from bs4 import BeautifulSoup
import time

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.keyword_forum_miner import KeywordForumMiner
from analysis.dynamic_crawler import DynamicCrawler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DeepEventMiner:
    """深度事件挖掘器"""
    
    # 深度挖掘信号模式
    DEEP_SIGNAL_PATTERNS = {
        'financial_anomaly': {  # 财务异常信号
            'patterns': [
                '资金异动', '大宗交易', '机构调研', '高管增减持',
                '股权质押', '解除质押', '股份回购', '分红派息',
                '业绩预告', '业绩修正', '业绩快报', '年报预披露'
            ],
            'weight': 9,
            'category': '财务信号'
        },
        'industry_chain': {  # 产业链信号
            'patterns': [
                '上游涨价', '原材料涨价', '供应链', '产业链重构',
                '行业景气', '需求旺盛', '产能扩张', '新产能投产',
                '技术升级', '产业升级', '智能化改造', '数字化转型'
            ],
            'weight': 8,
            'category': '产业信号'
        },
        'regulatory_signals': {  # 监管信号
            'patterns': [
                '监管问询', '交易所问询', '证监会关注', '现场检查',
                '信披违规', '内幕交易', '市场操纵', '异常交易',
                '风险提示', '交易提示', '澄清公告', '风险警示'
            ],
            'weight': 7,
            'category': '监管信号'
        },
        'market_microstructure': {  # 市场微观结构信号
            'patterns': [
                '放量异动', '缩量下跌', '巨量封板', '尾盘拉升',
                '开盘跳空', '分时异常', '成交异常', '换手异常',
                '北上资金', '南下资金', '融资融券', '期权异动'
            ],
            'weight': 6,
            'category': '交易信号'
        },
        'ecosystem_signals': {  # 生态系统信号
            'patterns': [
                '生态圈', '产业联盟', '战略联盟', '合作伙伴',
                '客户集中度', '供应商集中度', '关联交易', '同业竞争',
                '市场份额', '竞争格局', '护城河', '商业模式'
            ],
            'weight': 5,
            'category': '生态信号'
        }
    }
    
    # 隐含事件触发器
    IMPLICIT_EVENT_TRIGGERS = {
        'merger_acquisition': {  # 并购重组隐含信号
            'early_signals': [
                '停牌筹划', '重大事项', '控制权变更', '股东会', '董事会',
                '审计评估', '中介机构', '财务顾问', '律师事务所',
                '股价异常', '成交放量', '机构调研增加'
            ],
            'confirmation_signals': [
                '重组预案', '重组草案', '重组报告书', '股东大会',
                '证监会核准', '交易完成', '资产交割'
            ],
            'weight': 10
        },
        'major_contract': {  # 重大合同隐含信号
            'early_signals': [
                '招标公告', '中标候选', '商务谈判', '框架协议',
                '产能准备', '人员扩充', '设备采购', '原材料备货',
                '上下游动态', '行业需求增长'
            ],
            'confirmation_signals': [
                '中标公告', '合同签署', '首笔回款', '产能投产',
                '业绩兑现', '收入确认'
            ],
            'weight': 9
        },
        'technology_breakthrough': {  # 技术突破隐含信号
            'early_signals': [
                '研发投入增加', '技术人员招聘', '专利申请',
                '产学研合作', '技术引进', '设备更新',
                '试验验证', '小批量试产', '客户测试'
            ],
            'confirmation_signals': [
                '技术认证', '产品发布', '量产准备',
                '客户订单', '市场推广'
            ],
            'weight': 8
        }
    }
    
    def __init__(self):
        """初始化深度事件挖掘器"""
        self.keyword_miner = KeywordForumMiner()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        # 事件缓存
        self.event_cache = {}
        self.signal_history = defaultdict(list)
        
    def deep_mine_events(self, mining_depth: str = 'deep', time_horizon: int = 30) -> List[Dict]:
        """
        深度挖掘投资事件
        
        Args:
            mining_depth: 挖掘深度 ('surface', 'medium', 'deep', 'predictive')
            time_horizon: 时间跨度（天）
            
        Returns:
            深度事件列表
        """
        logger.info("=" * 80)
        logger.info(f"🔍 深度事件挖掘系统启动 - 挖掘深度: {mining_depth}")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        all_events = []
        
        try:
            # 第一层：多维度信号收集
            logger.info("第一层: 多维度信号收集...")
            signals = self._collect_multidimensional_signals(time_horizon)
            
            # 第二层：隐含事件识别
            logger.info("第二层: 隐含事件识别...")
            implicit_events = self._identify_implicit_events(signals)
            
            # 第三层：事件链路构建
            logger.info("第三层: 事件链路构建...")
            event_chains = self._build_event_chains(implicit_events)
            
            # 第四层：深度关联分析
            logger.info("第四层: 深度关联分析...")
            deep_correlations = self._analyze_deep_correlations(event_chains)
            
            # 第五层：预测性分析（仅在深度和预测模式下）
            if mining_depth in ['deep', 'predictive']:
                logger.info("第五层: 预测性分析...")
                predictive_events = self._predictive_analysis(deep_correlations)
                all_events.extend(predictive_events)
            
            # 整合所有事件
            all_events.extend(deep_correlations)
            
            # 第六层：事件评分和排序
            logger.info("第六层: 事件评分和排序...")
            scored_events = self._score_and_rank_events(all_events)
            
            # 生成深度挖掘报告
            self._generate_deep_mining_summary(scored_events, start_time)
            
            return scored_events
            
        except Exception as e:
            logger.error(f"深度挖掘过程出错: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _collect_multidimensional_signals(self, time_horizon: int) -> Dict[str, List[Dict]]:
        """收集多维度信号"""
        signals = {}
        
        # 并行收集各维度信号
        with ThreadPoolExecutor(max_workers=5) as executor:
            tasks = {
                executor.submit(self._collect_financial_signals, time_horizon): 'financial',
                executor.submit(self._collect_industry_signals, time_horizon): 'industry', 
                executor.submit(self._collect_regulatory_signals, time_horizon): 'regulatory',
                executor.submit(self._collect_market_signals, time_horizon): 'market',
                executor.submit(self._collect_ecosystem_signals, time_horizon): 'ecosystem'
            }
            
            for future in as_completed(tasks):
                signal_type = tasks[future]
                try:
                    signal_data = future.result(timeout=300)  # 5分钟超时
                    signals[signal_type] = signal_data
                    logger.info(f"✓ {signal_type}信号收集完成: {len(signal_data)} 条")
                except Exception as e:
                    logger.warning(f"✗ {signal_type}信号收集失败: {e}")
                    signals[signal_type] = []
        
        return signals
    
    def _collect_financial_signals(self, time_horizon: int) -> List[Dict]:
        """收集财务异常信号"""
        signals = []
        
        try:
            # 搜索财务相关关键词
            financial_keywords = self.DEEP_SIGNAL_PATTERNS['financial_anomaly']['patterns']
            
            for keyword in financial_keywords[:5]:  # 限制搜索数量
                try:
                    posts = self.keyword_miner._search_keyword_in_forums(
                        {'keyword': keyword, 'weight': 9}, 
                        10
                    )
                    
                    for post in posts:
                        # 提取股票代码
                        stock_codes = self.keyword_miner._extract_stock_codes_from_text(
                            post.get('title', '') + ' ' + post.get('content', '')
                        )
                        
                        for code in stock_codes:
                            signals.append({
                                'stock_code': code,
                                'signal_type': 'financial_anomaly',
                                'signal_content': post.get('title', ''),
                                'signal_source': post.get('platform', ''),
                                'signal_time': post.get('time', ''),
                                'keyword': keyword,
                                'confidence': self._calculate_signal_confidence(post, keyword),
                                'raw_data': post
                            })
                            
                except Exception as e:
                    logger.debug(f"搜索财务关键词 '{keyword}' 失败: {e}")
                    continue
        
        except Exception as e:
            logger.debug(f"财务信号收集失败: {e}")
        
        return signals
    
    def _collect_industry_signals(self, time_horizon: int) -> List[Dict]:
        """收集产业链信号"""
        signals = []
        
        try:
            industry_keywords = self.DEEP_SIGNAL_PATTERNS['industry_chain']['patterns']
            
            for keyword in industry_keywords[:5]:
                try:
                    posts = self.keyword_miner._search_keyword_in_forums(
                        {'keyword': keyword, 'weight': 8},
                        10
                    )
                    
                    for post in posts:
                        stock_codes = self.keyword_miner._extract_stock_codes_from_text(
                            post.get('title', '') + ' ' + post.get('content', '')
                        )
                        
                        for code in stock_codes:
                            signals.append({
                                'stock_code': code,
                                'signal_type': 'industry_chain',
                                'signal_content': post.get('title', ''),
                                'signal_source': post.get('platform', ''),
                                'signal_time': post.get('time', ''),
                                'keyword': keyword,
                                'confidence': self._calculate_signal_confidence(post, keyword),
                                'raw_data': post
                            })
                            
                except Exception as e:
                    logger.debug(f"搜索产业关键词 '{keyword}' 失败: {e}")
                    continue
                    
        except Exception as e:
            logger.debug(f"产业信号收集失败: {e}")
        
        return signals
    
    def _collect_regulatory_signals(self, time_horizon: int) -> List[Dict]:
        """收集监管信号"""
        signals = []
        
        try:
            regulatory_keywords = self.DEEP_SIGNAL_PATTERNS['regulatory_signals']['patterns']
            
            # 监管信号通常更正式，可能出现在公告中
            for keyword in regulatory_keywords[:3]:  # 监管信号相对少见
                try:
                    posts = self.keyword_miner._search_keyword_in_forums(
                        {'keyword': keyword, 'weight': 7},
                        5
                    )
                    
                    for post in posts:
                        stock_codes = self.keyword_miner._extract_stock_codes_from_text(
                            post.get('title', '') + ' ' + post.get('content', '')
                        )
                        
                        for code in stock_codes:
                            signals.append({
                                'stock_code': code,
                                'signal_type': 'regulatory_signals', 
                                'signal_content': post.get('title', ''),
                                'signal_source': post.get('platform', ''),
                                'signal_time': post.get('time', ''),
                                'keyword': keyword,
                                'confidence': self._calculate_signal_confidence(post, keyword),
                                'raw_data': post
                            })
                            
                except Exception as e:
                    logger.debug(f"搜索监管关键词 '{keyword}' 失败: {e}")
                    continue
                    
        except Exception as e:
            logger.debug(f"监管信号收集失败: {e}")
        
        return signals
    
    def _collect_market_signals(self, time_horizon: int) -> List[Dict]:
        """收集市场微观结构信号"""
        signals = []
        
        try:
            market_keywords = self.DEEP_SIGNAL_PATTERNS['market_microstructure']['patterns']
            
            for keyword in market_keywords[:5]:
                try:
                    posts = self.keyword_miner._search_keyword_in_forums(
                        {'keyword': keyword, 'weight': 6},
                        8
                    )
                    
                    for post in posts:
                        stock_codes = self.keyword_miner._extract_stock_codes_from_text(
                            post.get('title', '') + ' ' + post.get('content', '')
                        )
                        
                        for code in stock_codes:
                            signals.append({
                                'stock_code': code,
                                'signal_type': 'market_microstructure',
                                'signal_content': post.get('title', ''),
                                'signal_source': post.get('platform', ''),
                                'signal_time': post.get('time', ''),
                                'keyword': keyword,
                                'confidence': self._calculate_signal_confidence(post, keyword),
                                'raw_data': post
                            })
                            
                except Exception as e:
                    logger.debug(f"搜索市场关键词 '{keyword}' 失败: {e}")
                    continue
                    
        except Exception as e:
            logger.debug(f"市场信号收集失败: {e}")
        
        return signals
    
    def _collect_ecosystem_signals(self, time_horizon: int) -> List[Dict]:
        """收集生态系统信号"""
        signals = []
        
        try:
            ecosystem_keywords = self.DEEP_SIGNAL_PATTERNS['ecosystem_signals']['patterns']
            
            for keyword in ecosystem_keywords[:4]:
                try:
                    posts = self.keyword_miner._search_keyword_in_forums(
                        {'keyword': keyword, 'weight': 5},
                        6
                    )
                    
                    for post in posts:
                        stock_codes = self.keyword_miner._extract_stock_codes_from_text(
                            post.get('title', '') + ' ' + post.get('content', '')
                        )
                        
                        for code in stock_codes:
                            signals.append({
                                'stock_code': code,
                                'signal_type': 'ecosystem_signals',
                                'signal_content': post.get('title', ''),
                                'signal_source': post.get('platform', ''),
                                'signal_time': post.get('time', ''),
                                'keyword': keyword,
                                'confidence': self._calculate_signal_confidence(post, keyword),
                                'raw_data': post
                            })
                            
                except Exception as e:
                    logger.debug(f"搜索生态关键词 '{keyword}' 失败: {e}")
                    continue
                    
        except Exception as e:
            logger.debug(f"生态信号收集失败: {e}")
        
        return signals
    
    def _calculate_signal_confidence(self, post: Dict, keyword: str) -> float:
        """计算信号置信度"""
        confidence = 50.0  # 基础分
        
        # 标题包含关键词加分
        title = post.get('title', '').lower()
        if keyword.lower() in title:
            confidence += 20
        
        # 内容长度影响可信度
        content = post.get('content', '')
        if len(content) > 50:
            confidence += 10
        elif len(content) > 100:
            confidence += 15
        
        # 来源可信度
        platform = post.get('platform', '')
        if '东方财富' in platform:
            confidence += 10
        elif '同花顺' in platform:
            confidence += 8
        
        # 时间新鲜度
        post_time = post.get('time', '')
        if '小时前' in post_time or '分钟前' in post_time:
            confidence += 15
        elif '天前' in post_time:
            confidence += 5
        
        return min(confidence, 100.0)
    
    def _identify_implicit_events(self, signals: Dict[str, List[Dict]]) -> List[Dict]:
        """识别隐含事件"""
        implicit_events = []
        
        # 按股票代码聚合信号
        stock_signals = defaultdict(lambda: defaultdict(list))
        for signal_type, signal_list in signals.items():
            for signal in signal_list:
                stock_code = signal['stock_code']
                stock_signals[stock_code][signal_type].append(signal)
        
        # 为每个股票分析隐含事件
        for stock_code, signal_dict in stock_signals.items():
            # 分析并购重组信号
            merger_event = self._analyze_merger_signals(stock_code, signal_dict)
            if merger_event:
                implicit_events.append(merger_event)
            
            # 分析重大合同信号
            contract_event = self._analyze_contract_signals(stock_code, signal_dict)
            if contract_event:
                implicit_events.append(contract_event)
            
            # 分析技术突破信号
            tech_event = self._analyze_technology_signals(stock_code, signal_dict)
            if tech_event:
                implicit_events.append(tech_event)
        
        return implicit_events
    
    def _analyze_merger_signals(self, stock_code: str, signal_dict: Dict) -> Optional[Dict]:
        """分析并购重组信号"""
        merger_signals = []
        trigger_patterns = self.IMPLICIT_EVENT_TRIGGERS['merger_acquisition']
        
        # 收集相关信号
        for signal_type, signals in signal_dict.items():
            for signal in signals:
                keyword = signal.get('keyword', '')
                content = signal.get('signal_content', '')
                
                # 检查早期信号
                for early_signal in trigger_patterns['early_signals']:
                    if early_signal in keyword or early_signal in content:
                        merger_signals.append({
                            'signal': early_signal,
                            'type': 'early',
                            'confidence': signal.get('confidence', 0),
                            'time': signal.get('signal_time', ''),
                            'source': signal
                        })
                
                # 检查确认信号
                for confirm_signal in trigger_patterns['confirmation_signals']:
                    if confirm_signal in keyword or confirm_signal in content:
                        merger_signals.append({
                            'signal': confirm_signal,
                            'type': 'confirmation',
                            'confidence': signal.get('confidence', 0) + 20,  # 确认信号加权
                            'time': signal.get('signal_time', ''),
                            'source': signal
                        })
        
        # 如果有足够的信号，构建事件
        if len(merger_signals) >= 2:  # 至少2个相关信号
            avg_confidence = np.mean([s['confidence'] for s in merger_signals])
            
            return {
                'stock_code': stock_code,
                'event_type': 'merger_acquisition',
                'event_title': f'{stock_code} 重大重组事件挖掘',
                'event_stage': self._determine_event_stage(merger_signals),
                'confidence_score': min(avg_confidence + 10, 100),  # 多信号交叉验证加分
                'signal_count': len(merger_signals),
                'early_signals': [s for s in merger_signals if s['type'] == 'early'],
                'confirmation_signals': [s for s in merger_signals if s['type'] == 'confirmation'],
                'evidence_summary': self._generate_evidence_summary(merger_signals),
                'prediction': self._predict_event_development('merger_acquisition', merger_signals),
                'timestamp': datetime.now().isoformat()
            }
        
        return None
    
    def _analyze_contract_signals(self, stock_code: str, signal_dict: Dict) -> Optional[Dict]:
        """分析重大合同信号"""
        contract_signals = []
        trigger_patterns = self.IMPLICIT_EVENT_TRIGGERS['major_contract']
        
        # 收集相关信号
        for signal_type, signals in signal_dict.items():
            for signal in signals:
                keyword = signal.get('keyword', '')
                content = signal.get('signal_content', '')
                
                # 检查早期信号
                for early_signal in trigger_patterns['early_signals']:
                    if early_signal in keyword or early_signal in content:
                        contract_signals.append({
                            'signal': early_signal,
                            'type': 'early',
                            'confidence': signal.get('confidence', 0),
                            'time': signal.get('signal_time', ''),
                            'source': signal
                        })
                
                # 检查确认信号
                for confirm_signal in trigger_patterns['confirmation_signals']:
                    if confirm_signal in keyword or confirm_signal in content:
                        contract_signals.append({
                            'signal': confirm_signal,
                            'type': 'confirmation',
                            'confidence': signal.get('confidence', 0) + 15,
                            'time': signal.get('signal_time', ''),
                            'source': signal
                        })
        
        if len(contract_signals) >= 1:  # 合同信号相对容易确认
            avg_confidence = np.mean([s['confidence'] for s in contract_signals])
            
            return {
                'stock_code': stock_code,
                'event_type': 'major_contract',
                'event_title': f'{stock_code} 重大合同事件挖掘',
                'event_stage': self._determine_event_stage(contract_signals),
                'confidence_score': min(avg_confidence + 5, 100),
                'signal_count': len(contract_signals),
                'early_signals': [s for s in contract_signals if s['type'] == 'early'],
                'confirmation_signals': [s for s in contract_signals if s['type'] == 'confirmation'],
                'evidence_summary': self._generate_evidence_summary(contract_signals),
                'prediction': self._predict_event_development('major_contract', contract_signals),
                'timestamp': datetime.now().isoformat()
            }
        
        return None
    
    def _analyze_technology_signals(self, stock_code: str, signal_dict: Dict) -> Optional[Dict]:
        """分析技术突破信号"""
        tech_signals = []
        trigger_patterns = self.IMPLICIT_EVENT_TRIGGERS['technology_breakthrough']
        
        # 收集相关信号
        for signal_type, signals in signal_dict.items():
            for signal in signals:
                keyword = signal.get('keyword', '')
                content = signal.get('signal_content', '')
                
                # 检查早期信号
                for early_signal in trigger_patterns['early_signals']:
                    if early_signal in keyword or early_signal in content:
                        tech_signals.append({
                            'signal': early_signal,
                            'type': 'early',
                            'confidence': signal.get('confidence', 0),
                            'time': signal.get('signal_time', ''),
                            'source': signal
                        })
                
                # 检查确认信号
                for confirm_signal in trigger_patterns['confirmation_signals']:
                    if confirm_signal in keyword or confirm_signal in content:
                        tech_signals.append({
                            'signal': confirm_signal,
                            'type': 'confirmation',
                            'confidence': signal.get('confidence', 0) + 12,
                            'time': signal.get('signal_time', ''),
                            'source': signal
                        })
        
        if len(tech_signals) >= 1:
            avg_confidence = np.mean([s['confidence'] for s in tech_signals])
            
            return {
                'stock_code': stock_code,
                'event_type': 'technology_breakthrough',
                'event_title': f'{stock_code} 技术突破事件挖掘',
                'event_stage': self._determine_event_stage(tech_signals),
                'confidence_score': min(avg_confidence + 8, 100),
                'signal_count': len(tech_signals),
                'early_signals': [s for s in tech_signals if s['type'] == 'early'],
                'confirmation_signals': [s for s in tech_signals if s['type'] == 'confirmation'],
                'evidence_summary': self._generate_evidence_summary(tech_signals),
                'prediction': self._predict_event_development('technology_breakthrough', tech_signals),
                'timestamp': datetime.now().isoformat()
            }
        
        return None
    
    def _determine_event_stage(self, signals: List[Dict]) -> str:
        """确定事件发展阶段"""
        early_count = len([s for s in signals if s['type'] == 'early'])
        confirm_count = len([s for s in signals if s['type'] == 'confirmation'])
        
        if confirm_count > 0:
            return '确认阶段'
        elif early_count >= 2:
            return '发展阶段'
        elif early_count >= 1:
            return '萌芽阶段'
        else:
            return '探索阶段'
    
    def _generate_evidence_summary(self, signals: List[Dict]) -> str:
        """生成证据摘要"""
        if not signals:
            return "暂无明确证据"
        
        early_signals = [s['signal'] for s in signals if s['type'] == 'early']
        confirm_signals = [s['signal'] for s in signals if s['type'] == 'confirmation']
        
        summary = []
        if early_signals:
            summary.append(f"早期信号: {', '.join(early_signals[:3])}")
        if confirm_signals:
            summary.append(f"确认信号: {', '.join(confirm_signals[:3])}")
        
        return " | ".join(summary)
    
    def _predict_event_development(self, event_type: str, signals: List[Dict]) -> str:
        """预测事件发展"""
        if not signals:
            return "发展趋势不明"
        
        confirm_count = len([s for s in signals if s['type'] == 'confirmation'])
        avg_confidence = np.mean([s['confidence'] for s in signals])
        
        if event_type == 'merger_acquisition':
            if confirm_count > 0:
                return "重组进入实质性阶段，建议密切关注后续公告"
            elif avg_confidence > 70:
                return "重组信号较强，可能在1-3个月内有实质进展"
            else:
                return "重组仍在酝酿阶段，需要更多信号确认"
        
        elif event_type == 'major_contract':
            if confirm_count > 0:
                return "合同签署可能性高，关注业绩影响时间"
            elif avg_confidence > 60:
                return "合同谈判进展顺利，可能近期有突破"
            else:
                return "合同仍在洽谈阶段，存在不确定性"
        
        elif event_type == 'technology_breakthrough':
            if confirm_count > 0:
                return "技术突破基本确认，关注商业化进程"
            elif avg_confidence > 65:
                return "技术研发取得重要进展，关注后续验证"
            else:
                return "技术开发处于早期阶段，需要持续关注"
        
        return "发展趋势需要进一步观察"
    
    def _build_event_chains(self, implicit_events: List[Dict]) -> List[Dict]:
        """构建事件链路"""
        # 简化版本：为每个事件添加链路信息
        for event in implicit_events:
            event['event_chain'] = self._construct_event_chain(event)
        
        return implicit_events
    
    def _construct_event_chain(self, event: Dict) -> Dict:
        """构造单个事件的链路"""
        event_type = event.get('event_type', '')
        stage = event.get('event_stage', '')
        
        # 根据事件类型和阶段构建链路
        if event_type == 'merger_acquisition':
            chain = {
                'current_stage': stage,
                'next_possible_stages': self._get_next_merger_stages(stage),
                'key_milestones': ['停牌筹划', '重组预案', '股东大会', '监管核准', '资产交割'],
                'estimated_timeline': '3-12个月'
            }
        elif event_type == 'major_contract':
            chain = {
                'current_stage': stage,
                'next_possible_stages': self._get_next_contract_stages(stage),
                'key_milestones': ['招标公告', '中标公示', '合同签署', '首笔回款', '业绩兑现'],
                'estimated_timeline': '1-6个月'
            }
        elif event_type == 'technology_breakthrough':
            chain = {
                'current_stage': stage,
                'next_possible_stages': self._get_next_tech_stages(stage),
                'key_milestones': ['技术验证', '产品发布', '市场测试', '量产准备', '商业化'],
                'estimated_timeline': '6-24个月'
            }
        else:
            chain = {
                'current_stage': stage,
                'next_possible_stages': ['持续关注'],
                'key_milestones': ['后续跟踪'],
                'estimated_timeline': '不确定'
            }
        
        return chain
    
    def _get_next_merger_stages(self, current_stage: str) -> List[str]:
        """获取重组下一阶段"""
        if current_stage == '萌芽阶段':
            return ['发展阶段', '停牌筹划']
        elif current_stage == '发展阶段':
            return ['确认阶段', '重组预案发布']
        elif current_stage == '确认阶段':
            return ['股东大会审议', '监管核准']
        else:
            return ['持续跟踪']
    
    def _get_next_contract_stages(self, current_stage: str) -> List[str]:
        """获取合同下一阶段"""
        if current_stage == '萌芽阶段':
            return ['发展阶段', '中标公示']
        elif current_stage == '发展阶段':
            return ['确认阶段', '合同签署']
        elif current_stage == '确认阶段':
            return ['执行阶段', '业绩兑现']
        else:
            return ['持续跟踪']
    
    def _get_next_tech_stages(self, current_stage: str) -> List[str]:
        """获取技术突破下一阶段"""
        if current_stage == '萌芽阶段':
            return ['发展阶段', '技术验证']
        elif current_stage == '发展阶段':
            return ['确认阶段', '产品发布']
        elif current_stage == '确认阶段':
            return ['商业化阶段', '市场推广']
        else:
            return ['持续跟踪']
    
    def _analyze_deep_correlations(self, event_chains: List[Dict]) -> List[Dict]:
        """分析深度关联"""
        # 为每个事件添加深度关联分析
        for event in event_chains:
            event['deep_correlations'] = self._find_correlations(event)
        
        return event_chains
    
    def _find_correlations(self, event: Dict) -> Dict:
        """查找事件关联性"""
        stock_code = event.get('stock_code', '')
        event_type = event.get('event_type', '')
        
        correlations = {
            'industry_correlation': f'{stock_code}所在行业相关事件关联度中等',
            'market_correlation': '当前市场环境对该事件类型较为有利',
            'policy_correlation': '相关政策环境支持度较好',
            'risk_correlation': '事件实现存在一定不确定性，需要关注进展'
        }
        
        return correlations
    
    def _predictive_analysis(self, events: List[Dict]) -> List[Dict]:
        """预测性分析"""
        predictive_events = []
        
        # 基于现有事件模式预测可能的新事件
        for event in events:
            if event.get('confidence_score', 0) > 75:  # 高置信度事件
                predicted_event = self._generate_predicted_event(event)
                if predicted_event:
                    predictive_events.append(predicted_event)
        
        return predictive_events
    
    def _generate_predicted_event(self, base_event: Dict) -> Optional[Dict]:
        """基于基础事件生成预测事件"""
        stock_code = base_event.get('stock_code', '')
        base_type = base_event.get('event_type', '')
        
        # 简化的预测逻辑
        if base_type == 'merger_acquisition' and base_event.get('confidence_score', 0) > 80:
            return {
                'stock_code': stock_code,
                'event_type': 'predicted_merger_success',
                'event_title': f'{stock_code} 重组成功概率预测',
                'confidence_score': base_event.get('confidence_score', 0) - 15,
                'prediction_basis': '基于多维度信号分析',
                'predicted_timeline': '未来2-6个月',
                'predicted_impact': '股价可能在重组成功后获得20-50%涨幅',
                'risk_factors': ['监管审核风险', '市场环境变化', '重组方案调整'],
                'timestamp': datetime.now().isoformat(),
                'is_prediction': True
            }
        
        return None
    
    def _score_and_rank_events(self, events: List[Dict]) -> List[Dict]:
        """事件评分和排序"""
        for event in events:
            # 计算综合评分
            base_score = event.get('confidence_score', 50)
            signal_count = event.get('signal_count', 1)
            
            # 信号数量加成
            signal_bonus = min(signal_count * 5, 25)
            
            # 事件类型权重
            event_type = event.get('event_type', '')
            if 'merger' in event_type:
                type_bonus = 20
            elif 'contract' in event_type:
                type_bonus = 15
            elif 'technology' in event_type:
                type_bonus = 10
            else:
                type_bonus = 5
            
            # 预测事件降权
            prediction_penalty = -10 if event.get('is_prediction', False) else 0
            
            final_score = min(base_score + signal_bonus + type_bonus + prediction_penalty, 100)
            event['final_score'] = final_score
        
        # 按最终得分排序
        return sorted(events, key=lambda x: x.get('final_score', 0), reverse=True)
    
    def _generate_deep_mining_summary(self, events: List[Dict], start_time: datetime):
        """生成深度挖掘摘要"""
        logger.info("\n" + "=" * 80)
        logger.info("🔍 深度事件挖掘结果摘要")
        logger.info("=" * 80)
        
        total_events = len(events)
        high_confidence = len([e for e in events if e.get('final_score', 0) >= 80])
        medium_confidence = len([e for e in events if 60 <= e.get('final_score', 0) < 80])
        predictions = len([e for e in events if e.get('is_prediction', False)])
        
        logger.info(f"发现深度事件总数: {total_events}")
        logger.info(f"高置信度事件 (≥80分): {high_confidence}")
        logger.info(f"中等置信度事件 (60-79分): {medium_confidence}")
        logger.info(f"预测性事件: {predictions}")
        
        # 事件类型分布
        event_types = Counter([e.get('event_type', '') for e in events])
        logger.info(f"\n事件类型分布:")
        for event_type, count in event_types.most_common():
            type_name = self._get_event_type_name(event_type)
            logger.info(f"  {type_name}: {count}")
        
        # TOP 5 深度事件
        if events:
            logger.info(f"\n🏆 TOP 5 深度挖掘事件:")
            for idx, event in enumerate(events[:5], 1):
                stock_code = event.get('stock_code', '')
                title = event.get('event_title', '')
                score = event.get('final_score', 0)
                stage = event.get('event_stage', '')
                logger.info(f"  {idx}. {stock_code} - {title}")
                logger.info(f"     评分: {score:.1f} | 阶段: {stage}")
                logger.info(f"     预测: {event.get('prediction', '无')}")
        
        elapsed_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"\n深度挖掘总耗时: {elapsed_time:.2f}秒")
        logger.info("=" * 80)
    
    def _get_event_type_name(self, event_type: str) -> str:
        """获取事件类型中文名称"""
        type_mapping = {
            'merger_acquisition': '重大重组',
            'major_contract': '重大合同',
            'technology_breakthrough': '技术突破',
            'predicted_merger_success': '重组成功预测',
            'predicted_contract_win': '合同获取预测',
            'predicted_tech_commercialization': '技术商业化预测'
        }
        return type_mapping.get(event_type, event_type)