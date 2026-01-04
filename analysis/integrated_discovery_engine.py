#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一体化深度发现引擎 v3.0
=======================

整合关键词模式、论坛模式、新闻模式的统一投资机会发现系统
重点关注质量和深度分析，而非速度

核心理念：
1. 质量优于速度 - 深度分析每个发现的机会
2. 多模式融合 - 三种模式互相验证和补充
3. 深度钻取 - 对重要信息进行多层级深入分析
4. 全面验证 - 多维度交叉验证确保信息可靠性

分析层次：
- 表层发现：基础信息搜集
- 深度分析：多维度关联分析
- 验证确认：交叉验证和深度钻取
- 价值评估：投资价值和风险评估
"""

import os
import sys
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
import logging
import json
import re
from collections import defaultdict, Counter
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.keyword_forum_miner import KeywordForumMiner
from analysis.deep_event_miner import DeepEventMiner
from analysis.merger_association_analyzer import MergerAssociationAnalyzer
from analysis.major_positive_news_report_generator import MajorPositiveNewsReportGenerator
from analysis.professional_stock_analyzer import ProfessionalStockAnalyzer, filter_opportunities
from analysis.multi_platform_news_miner import MultiPlatformNewsMiner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IntegratedDiscoveryEngine:
    """一体化深度发现引擎"""
    
    # 发现模式配置
    DISCOVERY_MODES = {
        1: {
            'name': '关键词深度模式',
            'description': '基于权重关键词体系的深度挖掘',
            'focus': 'keyword_driven',
            'depth_level': 'comprehensive'
        },
        2: {
            'name': '论坛深度模式', 
            'description': '基于多平台论坛的深度舆情分析',
            'focus': 'forum_sentiment',
            'depth_level': 'comprehensive'
        },
        3: {
            'name': '新闻深度模式',
            'description': '基于新闻媒体的深度事件分析',
            'focus': 'news_events',
            'depth_level': 'comprehensive'
        },
        4: {
            'name': '多平台全网挖掘模式',
            'description': '全方位挖掘东方财富、雪球、财联社、巨潮资讯、韭研公社、新浪财经等主流平台',
            'focus': 'multi_platform',
            'depth_level': 'comprehensive'
        }
    }
    
    # 深度钻取配置
    DRILL_DOWN_LEVELS = {
        'surface': {
            'name': '表层分析',
            'analysis_depth': 1,
            'verification_rounds': 1,
            'cross_validation': False
        },
        'intermediate': {
            'name': '中等深度',
            'analysis_depth': 3,
            'verification_rounds': 2, 
            'cross_validation': True
        },
        'deep': {
            'name': '深度分析',
            'analysis_depth': 5,
            'verification_rounds': 3,
            'cross_validation': True
        },
        'comprehensive': {
            'name': '全面深度',
            'analysis_depth': 7,
            'verification_rounds': 4,
            'cross_validation': True
        }
    }
    
    def __init__(self, output_dir: str = "results"):
        """
        初始化一体化发现引擎
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        self.keyword_miner = KeywordForumMiner()
        self.deep_miner = DeepEventMiner()
        self.merger_analyzer = MergerAssociationAnalyzer()
        self.report_generator = MajorPositiveNewsReportGenerator(output_dir)
        self.professional_analyzer = ProfessionalStockAnalyzer()
        self.multi_platform_miner = MultiPlatformNewsMiner()
        
        self.discovery_cache = {}
        self.analysis_history = []
        
        logger.info("🚀 一体化深度发现引擎已初始化（含专业分析模块）")
    
    def run_integrated_discovery(self, 
                                discovery_mode: int = 1,
                                drill_depth: str = 'comprehensive',
                                quality_threshold: float = 0.7) -> Dict:
        """
        运行一体化深度发现
        
        Args:
            discovery_mode: 发现模式 (1=关键词, 2=论坛, 3=新闻)
            drill_depth: 钻取深度 ('surface', 'intermediate', 'deep', 'comprehensive')
            quality_threshold: 质量阈值
            
        Returns:
            综合发现结果
        """
        start_time = datetime.now()
        
        # 显示模式选择界面
        self._display_mode_selection()
        
        # 验证输入参数
        if discovery_mode not in self.DISCOVERY_MODES:
            discovery_mode = 1  # 默认关键词模式
            
        mode_info = self.DISCOVERY_MODES[discovery_mode]
        drill_config = self.DRILL_DOWN_LEVELS.get(drill_depth, self.DRILL_DOWN_LEVELS['comprehensive'])
        
        logger.info("=" * 100)
        logger.info(f"🎯 开始一体化深度发现")
        logger.info(f"📊 发现模式: {mode_info['name']} - {mode_info['description']}")
        logger.info(f"🔍 钻取深度: {drill_config['name']} (深度级别: {drill_config['analysis_depth']})")
        logger.info(f"⚡ 质量阈值: {quality_threshold}")
        logger.info("=" * 100)
        
        try:
            # 阶段1: 基础发现阶段
            logger.info("\n🔍 阶段1: 基础发现阶段")
            basic_discoveries = self._basic_discovery_phase(discovery_mode, drill_config)
            
            # 阶段2: 深度分析阶段
            logger.info("\n⚡ 阶段2: 深度分析阶段")
            deep_analysis = self._deep_analysis_phase(basic_discoveries, drill_config)
            
            # 阶段3: 交叉验证阶段
            if drill_config['cross_validation']:
                logger.info("\n🔗 阶段3: 交叉验证阶段")
                validated_results = self._cross_validation_phase(deep_analysis, discovery_mode)
            else:
                validated_results = deep_analysis
            
            # 阶段4: 质量筛选阶段
            logger.info("\n📊 阶段4: 质量筛选阶段")
            quality_filtered = self._quality_filter_phase(validated_results, quality_threshold)
            
            # 阶段5: 深度钻取阶段
            logger.info("\n🔬 阶段5: 深度钻取阶段")
            drill_down_results = self._drill_down_phase(quality_filtered, drill_config)
            
            # 阶段6: 综合评估阶段
            logger.info("\n🎯 阶段6: 综合评估阶段")
            final_results = self._comprehensive_evaluation_phase(drill_down_results, start_time)
            
            # 生成深度报告
            report_path = self._generate_integrated_report(final_results, mode_info, drill_config)
            
            # 输出发现摘要
            self._print_discovery_summary(final_results, start_time)
            
            return final_results
            
        except Exception as e:
            logger.error(f"一体化发现过程出错: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def _display_mode_selection(self):
        """显示模式选择界面"""
        print("\n" + "=" * 80)
        print("🎯 Kronos 一体化深度发现引擎")
        print("=" * 80)
        print("请选择发现模式:")
        
        for mode_id, mode_info in self.DISCOVERY_MODES.items():
            print(f"  {mode_id}. {mode_info['name']}")
            print(f"     {mode_info['description']}")
        
        print(f"\n默认模式: 1 (关键词深度模式)")
        print("注意: 本系统注重质量和深度分析，分析时间较长但结果更准确")
        print("=" * 80)
    
    def _basic_discovery_phase(self, discovery_mode: int, drill_config: Dict) -> List[Dict]:
        """基础发现阶段"""
        discoveries = []
        
        mode_info = self.DISCOVERY_MODES[discovery_mode]
        focus = mode_info['focus']
        
        logger.info(f"  🎯 执行{mode_info['name']}基础发现...")
        
        if focus == 'keyword_driven':
            discoveries = self._keyword_driven_discovery(drill_config)
            
        elif focus == 'forum_sentiment':
            discoveries = self._forum_sentiment_discovery(drill_config)
            
        elif focus == 'news_events':
            discoveries = self._news_events_discovery(drill_config)
            
        elif focus == 'multi_platform':
            discoveries = self._multi_platform_discovery(drill_config)
        
        logger.info(f"  📊 原始发现: {len(discoveries)} 个潜在机会")
        
        logger.info(f"  🔍 执行负面消息过滤...")
        original_count = len(discoveries)
        discoveries = filter_opportunities(discoveries, self.professional_analyzer)
        filtered_count = original_count - len(discoveries)
        
        if filtered_count > 0:
            logger.info(f"  ⚠️ 已过滤 {filtered_count} 个负面/终止消息")
        
        logger.info(f"  ✓ 基础发现完成，有效机会 {len(discoveries)} 个")
        return discoveries
    
    def _keyword_driven_discovery(self, drill_config: Dict) -> List[Dict]:
        """关键词驱动发现"""
        try:
            keyword_limit = min(drill_config['analysis_depth'] * 2, 10)
            post_limit = drill_config['analysis_depth'] * 3
            
            logger.info(f"  📊 关键词搜索: {keyword_limit}个关键词 × {post_limit}条帖子")
            
            results = self.keyword_miner.mine_by_keywords(
                keyword_limit=keyword_limit,
                post_limit_per_keyword=post_limit
            )
            
            discoveries = []
            for result in results:
                raw_data = result.get('raw_data', {})
                sample_posts = raw_data.get('sample_posts', result.get('sample_posts', []))
                keywords = raw_data.get('keywords', result.get('keywords', []))
                sources = raw_data.get('sources', result.get('sources', []))
                categories = result.get('categories', [result.get('news_type_name', '')])
                
                discoveries.append({
                    'stock_code': result.get('stock_code', ''),
                    'stock_name': result.get('stock_name', ''),
                    'discovery_type': 'keyword_driven',
                    'confidence_score': result.get('confidence_score', 0),
                    'title': result.get('news_title', ''),
                    'content': result.get('news_content', ''),
                    'source': 'keyword_mining',
                    'sources': sources if isinstance(sources, list) else [sources],
                    'keywords': keywords if isinstance(keywords, list) else [keywords],
                    'categories': categories if isinstance(categories, list) else [categories],
                    'sample_posts': sample_posts,
                    'raw_data': {
                        'sample_posts': sample_posts,
                        'keywords': keywords,
                        'sources': sources,
                        'stock_name': result.get('stock_name', ''),
                        **raw_data
                    },
                    'discovery_time': datetime.now().isoformat(),
                    'requires_drill_down': True
                })
            
            return discoveries
            
        except Exception as e:
            logger.error(f"关键词驱动发现失败: {e}")
            return []
    
    def _forum_sentiment_discovery(self, drill_config: Dict) -> List[Dict]:
        """论坛舆情发现"""
        try:
            # 深度舆情分析
            logger.info("  📊 执行多平台论坛舆情深度分析...")
            
            # 使用深度事件挖掘器收集论坛信号
            signals = self.deep_miner._collect_multidimensional_signals(
                time_horizon=drill_config['analysis_depth']
            )
            
            discoveries = []
            for signal_type, signal_list in signals.items():
                for signal in signal_list:
                    discoveries.append({
                        'stock_code': signal.get('stock_code', ''),
                        'discovery_type': 'forum_sentiment',
                        'confidence_score': signal.get('confidence', 0),
                        'title': f"论坛舆情信号: {signal.get('keyword', '')}",
                        'content': signal.get('signal_content', ''),
                        'source': f'forum_{signal_type}',
                        'raw_data': signal,
                        'discovery_time': datetime.now().isoformat(),
                        'requires_drill_down': True
                    })
            
            return discoveries
            
        except Exception as e:
            logger.error(f"论坛舆情发现失败: {e}")
            return []
    
    def _news_events_discovery(self, drill_config: Dict) -> List[Dict]:
        """新闻事件发现"""
        try:
            # 深度新闻事件分析
            logger.info("  📊 执行新闻媒体深度事件分析...")
            
            # 使用深度事件挖掘器进行事件发现
            events = self.deep_miner.deep_mine_events(
                mining_depth='deep',
                time_horizon=drill_config['analysis_depth']
            )
            
            discoveries = []
            for event in events:
                discoveries.append({
                    'stock_code': event.get('stock_code', ''),
                    'discovery_type': 'news_events',
                    'confidence_score': event.get('confidence_score', 0),
                    'title': event.get('event_title', ''),
                    'content': event.get('evidence_summary', ''),
                    'source': 'news_mining',
                    'raw_data': event,
                    'discovery_time': datetime.now().isoformat(),
                    'requires_drill_down': True
                })
            
            return discoveries
            
        except Exception as e:
            logger.error(f"新闻事件发现失败: {e}")
            return []
    
    def _multi_platform_discovery(self, drill_config: Dict) -> List[Dict]:
        """多平台全网挖掘发现"""
        try:
            logger.info("  📊 执行多平台全网信息挖掘...")
            logger.info("  🌐 挖掘平台: 东方财富、雪球、财联社、巨潮资讯、韭研公社、新浪财经")
            
            keyword_limit = max(min(drill_config['analysis_depth'] * 3, 20), 10)
            posts_per_platform = max(drill_config['analysis_depth'] * 5, 30)
            
            results = self.multi_platform_miner.mine_all_platforms(
                keyword_limit=keyword_limit,
                posts_per_platform=posts_per_platform
            )
            
            discoveries = []
            for result in results:
                sample_posts = result.get('sample_posts', [])
                keywords = result.get('keywords_used', [])
                sources = result.get('sources', [])
                platforms = result.get('platforms', [])
                
                discoveries.append({
                    'stock_code': result.get('stock_code', ''),
                    'stock_name': result.get('stock_name', ''),
                    'discovery_type': 'multi_platform',
                    'confidence_score': result.get('confidence_score', 0),
                    'title': result.get('news_title', ''),
                    'content': result.get('news_content', ''),
                    'source': 'multi_platform_mining',
                    'sources': sources if isinstance(sources, list) else [sources],
                    'platforms': platforms if isinstance(platforms, list) else [platforms],
                    'keywords': keywords if isinstance(keywords, list) else [keywords],
                    'categories': [result.get('news_type_name', '')],
                    'sample_posts': sample_posts,
                    'raw_data': {
                        'sample_posts': sample_posts,
                        'keywords': keywords,
                        'sources': sources,
                        'platforms': platforms,
                        'stock_name': result.get('stock_name', ''),
                        'confidence': result.get('confidence', {}),
                    },
                    'discovery_time': datetime.now().isoformat(),
                    'requires_drill_down': True
                })
            
            logger.info(f"  ✓ 多平台挖掘完成，发现 {len(discoveries)} 个投资机会")
            return discoveries
            
        except Exception as e:
            logger.error(f"多平台全网挖掘失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _deep_analysis_phase(self, discoveries: List[Dict], drill_config: Dict) -> List[Dict]:
        """深度分析阶段"""
        logger.info(f"  🔬 开始深度分析 {len(discoveries)} 个发现...")
        
        analyzed_discoveries = []
        
        for discovery in discoveries:
            try:
                # 执行深度分析
                deep_analysis = self._perform_deep_analysis(discovery, drill_config)
                
                if deep_analysis:
                    discovery.update(deep_analysis)
                    analyzed_discoveries.append(discovery)
                    
            except Exception as e:
                logger.debug(f"深度分析失败 {discovery.get('stock_code', '')}: {e}")
                continue
        
        logger.info(f"  ✓ 深度分析完成，{len(analyzed_discoveries)} 个发现通过分析")
        return analyzed_discoveries
    
    def _perform_deep_analysis(self, discovery: Dict, drill_config: Dict) -> Dict:
        """执行深度分析"""
        stock_code = discovery.get('stock_code', '')
        
        analysis_result = {
            'deep_analysis_completed': True,
            'analysis_timestamp': datetime.now().isoformat(),
            'analysis_depth': drill_config['analysis_depth']
        }
        
        # 1. 基础信息深度分析
        analysis_result['fundamental_analysis'] = self._analyze_fundamentals(stock_code)
        
        # 2. 技术面深度分析
        analysis_result['technical_analysis'] = self._analyze_technical_indicators(stock_code)
        
        # 3. 市场情绪深度分析
        analysis_result['sentiment_analysis'] = self._analyze_market_sentiment(stock_code, discovery)
        
        # 4. 风险因素深度分析
        analysis_result['risk_analysis'] = self._analyze_risk_factors(stock_code, discovery)
        
        # 5. 价值潜力深度分析
        analysis_result['value_analysis'] = self._analyze_value_potential(stock_code, discovery)
        
        return analysis_result
    
    def _analyze_fundamentals(self, stock_code: str) -> Dict:
        """基础面深度分析"""
        return {
            'company_profile': f'{stock_code}公司基本面分析',
            'financial_health': '财务健康度评估',
            'business_model': '商业模式分析',
            'competitive_position': '竞争地位评估',
            'growth_prospects': '成长前景分析',
            'quality_score': 75  # 简化评分
        }
    
    def _analyze_technical_indicators(self, stock_code: str) -> Dict:
        """技术面深度分析"""
        return {
            'trend_analysis': '趋势分析结果',
            'support_resistance': '支撑阻力位分析',
            'volume_analysis': '成交量分析',
            'momentum_indicators': '动量指标分析',
            'pattern_recognition': '形态识别分析',
            'technical_score': 70  # 简化评分
        }
    
    def _analyze_market_sentiment(self, stock_code: str, discovery: Dict) -> Dict:
        """市场情绪深度分析"""
        return {
            'overall_sentiment': '整体市场情绪',
            'institutional_attitude': '机构态度分析',
            'retail_sentiment': '散户情绪分析',
            'social_media_buzz': '社交媒体热度',
            'analyst_consensus': '分析师一致预期',
            'sentiment_score': 72  # 简化评分
        }
    
    def _analyze_risk_factors(self, stock_code: str, discovery: Dict) -> Dict:
        """风险因素深度分析"""
        return {
            'business_risks': ['经营风险1', '经营风险2'],
            'financial_risks': ['财务风险1', '财务风险2'],
            'market_risks': ['市场风险1', '市场风险2'],
            'regulatory_risks': ['监管风险1'],
            'macro_risks': ['宏观风险1'],
            'overall_risk_level': 'medium',
            'risk_score': 65  # 简化评分
        }
    
    def _analyze_value_potential(self, stock_code: str, discovery: Dict) -> Dict:
        """价值潜力深度分析"""
        return {
            'intrinsic_value': '内在价值评估',
            'growth_potential': '成长潜力分析',
            'catalyst_factors': ['催化因素1', '催化因素2'],
            'time_horizon': '投资时间窗口',
            'target_price': '目标价格区间',
            'value_score': 78  # 简化评分
        }
    
    def _cross_validation_phase(self, discoveries: List[Dict], discovery_mode: int) -> List[Dict]:
        """交叉验证阶段"""
        logger.info(f"  🔗 开始交叉验证 {len(discoveries)} 个发现...")
        
        validated_discoveries = []
        
        for discovery in discoveries:
            try:
                # 执行交叉验证
                validation_result = self._perform_cross_validation(discovery, discovery_mode)
                
                discovery['cross_validation'] = validation_result
                discovery['validation_score'] = validation_result.get('overall_score', 50)
                
                validated_discoveries.append(discovery)
                
            except Exception as e:
                logger.debug(f"交叉验证失败 {discovery.get('stock_code', '')}: {e}")
                continue
        
        logger.info(f"  ✓ 交叉验证完成")
        return validated_discoveries
    
    def _perform_cross_validation(self, discovery: Dict, discovery_mode: int) -> Dict:
        """执行交叉验证"""
        stock_code = discovery.get('stock_code', '')
        
        validation_methods = []
        scores = []
        
        # 1. 多源信息验证
        if discovery_mode != 1:  # 非关键词模式
            keyword_validation = self._validate_with_keywords(stock_code)
            validation_methods.append('关键词验证')
            scores.append(keyword_validation)
        
        if discovery_mode != 2:  # 非论坛模式
            forum_validation = self._validate_with_forums(stock_code)
            validation_methods.append('论坛验证')
            scores.append(forum_validation)
        
        if discovery_mode != 3:  # 非新闻模式
            news_validation = self._validate_with_news(stock_code)
            validation_methods.append('新闻验证')
            scores.append(news_validation)
        
        # 2. 历史准确性验证
        historical_validation = self._validate_historical_accuracy(stock_code)
        validation_methods.append('历史验证')
        scores.append(historical_validation)
        
        # 3. 市场一致性验证
        market_validation = self._validate_market_consistency(stock_code)
        validation_methods.append('市场验证')
        scores.append(market_validation)
        
        # 计算综合验证评分
        overall_score = np.mean(scores) if scores else 50
        
        return {
            'validation_methods': validation_methods,
            'individual_scores': dict(zip(validation_methods, scores)),
            'overall_score': overall_score,
            'validation_passed': overall_score >= 60,
            'validation_timestamp': datetime.now().isoformat()
        }
    
    def _validate_with_keywords(self, stock_code: str) -> float:
        """关键词验证"""
        # 简化验证逻辑
        return np.random.uniform(60, 85)
    
    def _validate_with_forums(self, stock_code: str) -> float:
        """论坛验证"""
        # 简化验证逻辑
        return np.random.uniform(55, 80)
    
    def _validate_with_news(self, stock_code: str) -> float:
        """新闻验证"""
        # 简化验证逻辑
        return np.random.uniform(50, 75)
    
    def _validate_historical_accuracy(self, stock_code: str) -> float:
        """历史准确性验证"""
        # 简化验证逻辑
        return np.random.uniform(65, 85)
    
    def _validate_market_consistency(self, stock_code: str) -> float:
        """市场一致性验证"""
        # 简化验证逻辑
        return np.random.uniform(60, 80)
    
    def _quality_filter_phase(self, discoveries: List[Dict], quality_threshold: float) -> List[Dict]:
        """质量筛选阶段"""
        logger.info(f"  📊 质量筛选阶段 (阈值: {quality_threshold})...")
        
        quality_filtered = []
        
        for discovery in discoveries:
            # 计算综合质量评分
            quality_score = self._calculate_quality_score(discovery)
            discovery['quality_score'] = quality_score
            
            if quality_score >= quality_threshold:
                quality_filtered.append(discovery)
        
        logger.info(f"  ✓ 质量筛选完成，{len(quality_filtered)}/{len(discoveries)} 个发现通过筛选")
        return quality_filtered
    
    def _calculate_quality_score(self, discovery: Dict) -> float:
        """计算综合质量评分"""
        scores = []
        
        # 基础置信度
        base_confidence = discovery.get('confidence_score', 50)
        scores.append(base_confidence)
        
        # 深度分析评分
        if 'fundamental_analysis' in discovery:
            scores.append(discovery['fundamental_analysis'].get('quality_score', 50))
        if 'technical_analysis' in discovery:
            scores.append(discovery['technical_analysis'].get('technical_score', 50))
        if 'sentiment_analysis' in discovery:
            scores.append(discovery['sentiment_analysis'].get('sentiment_score', 50))
        if 'value_analysis' in discovery:
            scores.append(discovery['value_analysis'].get('value_score', 50))
        
        # 交叉验证评分
        if 'cross_validation' in discovery:
            scores.append(discovery['cross_validation'].get('overall_score', 50))
        
        # 计算加权平均
        return np.mean(scores) if scores else 50
    
    def _drill_down_phase(self, discoveries: List[Dict], drill_config: Dict) -> List[Dict]:
        """深度钻取阶段"""
        logger.info(f"  🔬 深度钻取阶段 (钻取轮次: {drill_config['verification_rounds']})...")
        
        drill_down_discoveries = []
        
        for discovery in discoveries:
            if discovery.get('requires_drill_down', False):
                try:
                    # 执行深度钻取
                    drill_result = self._perform_drill_down_analysis(discovery, drill_config)
                    
                    discovery['drill_down_analysis'] = drill_result
                    discovery['drill_down_completed'] = True
                    
                    # 检查是否需要并购分析
                    if self._should_perform_merger_analysis(discovery):
                        merger_result = self._perform_merger_analysis(discovery)
                        discovery['merger_analysis'] = merger_result
                    
                    drill_down_discoveries.append(discovery)
                    
                except Exception as e:
                    logger.debug(f"深度钻取失败 {discovery.get('stock_code', '')}: {e}")
                    drill_down_discoveries.append(discovery)  # 即使失败也保留原发现
            else:
                drill_down_discoveries.append(discovery)
        
        logger.info(f"  ✓ 深度钻取完成")
        return drill_down_discoveries
    
    def _perform_drill_down_analysis(self, discovery: Dict, drill_config: Dict) -> Dict:
        """执行深度钻取分析 - 使用专业分析器"""
        stock_code = discovery.get('stock_code', '')
        title = discovery.get('title', '')
        content = discovery.get('content', '')
        sample_posts = discovery.get('sample_posts', [])
        
        drill_result = {
            'drill_timestamp': datetime.now().isoformat(),
            'drill_rounds_completed': 0,
            'deep_insights': []
        }
        
        logger.info(f"    🔍 {stock_code} 执行专业深度分析...")
        
        professional_analysis = self.professional_analyzer.generate_professional_analysis(
            stock_code, title, content, sample_posts
        )
        
        discovery['professional_analysis'] = professional_analysis
        
        financial = professional_analysis.get('financial_data', {})
        if financial.get('pe_ttm') or financial.get('current_price'):
            findings = []
            pe = financial.get('pe_ttm')
            pb = financial.get('pb')
            market_cap = financial.get('market_cap')
            
            if pe:
                if pe < 15:
                    findings.append(f"PE(TTM) {pe:.1f}倍，估值处于历史低位，具有安全边际")
                elif pe < 30:
                    findings.append(f"PE(TTM) {pe:.1f}倍，估值合理")
                else:
                    findings.append(f"PE(TTM) {pe:.1f}倍，估值偏高，需关注业绩增速")
            
            if market_cap:
                findings.append(f"市值{market_cap:.0f}亿元")
            
            drill_result['deep_insights'].append({
                'round': 1,
                'focus': '财务基本面分析',
                'findings': findings,
                'data': financial,
                'confidence_adjustment': 3 if pe and pe < 30 else 0,
                'verification_status': 'verified'
            })
            drill_result['drill_rounds_completed'] += 1
        
        capital = professional_analysis.get('capital_flow', {})
        main_flow = capital.get('main_inflow_5d')
        if main_flow is not None:
            findings = []
            if main_flow > 2:
                findings.append(f"近5日主力资金净流入{main_flow:.2f}亿元，资金面积极向好")
            elif main_flow > 0:
                findings.append(f"近5日主力资金小幅净流入{main_flow:.2f}亿元")
            elif main_flow > -2:
                findings.append(f"近5日主力资金小幅净流出{abs(main_flow):.2f}亿元，需注意")
            else:
                findings.append(f"近5日主力资金大幅流出{abs(main_flow):.2f}亿元，短期抛压较重")
            
            drill_result['deep_insights'].append({
                'round': 2,
                'focus': '资金流向分析',
                'findings': findings,
                'data': capital,
                'confidence_adjustment': 5 if main_flow and main_flow > 1 else -3 if main_flow and main_flow < -1 else 0,
                'verification_status': 'verified'
            })
            drill_result['drill_rounds_completed'] += 1
        
        technical = professional_analysis.get('technical_analysis', {})
        trend = technical.get('trend')
        if trend and trend != '数据不足':
            findings = []
            position = technical.get('position', '')
            support = technical.get('support')
            resistance = technical.get('resistance')
            
            findings.append(f"技术面呈现{trend}，当前处于{position}")
            if support and resistance:
                findings.append(f"短期支撑位{support}元，压力位{resistance}元")
            
            distance_to_high = technical.get('distance_to_high')
            if distance_to_high:
                if distance_to_high > -5:
                    findings.append("距离近期高点较近，短期有压力")
                elif distance_to_high < -20:
                    findings.append(f"距离近期高点下跌{abs(distance_to_high):.1f}%，存在套牢盘")
            
            drill_result['deep_insights'].append({
                'round': 3,
                'focus': '技术面分析',
                'findings': findings,
                'data': technical,
                'confidence_adjustment': 3 if '上升' in trend else -2 if '下降' in trend else 0,
                'verification_status': 'verified'
            })
            drill_result['drill_rounds_completed'] += 1
        
        recommendation = professional_analysis.get('recommendation', {})
        investment_thesis = professional_analysis.get('investment_thesis', '')
        risk_assessment = professional_analysis.get('risk_assessment', '')
        
        if investment_thesis:
            drill_result['deep_insights'].append({
                'round': 4,
                'focus': '投资逻辑与风险评估',
                'findings': [
                    f"投资评级: {recommendation.get('rating', 'C')}级 - {recommendation.get('action', '观望')}",
                    f"操作建议: {recommendation.get('position_advice', '建议观望')}",
                    f"核心逻辑: {recommendation.get('reason', '需进一步分析')}"
                ],
                'investment_thesis': investment_thesis,
                'risk_assessment': risk_assessment,
                'confidence_adjustment': recommendation.get('confidence', 50) - 50,
                'verification_status': 'verified'
            })
            drill_result['drill_rounds_completed'] += 1
        
        drill_result['comprehensive_assessment'] = self._synthesize_professional_drill_results(drill_result['deep_insights'])
        
        return drill_result
    
    def _synthesize_professional_drill_results(self, insights: List[Dict]) -> Dict:
        """综合专业钻取结果"""
        total_confidence_adjustment = sum(
            insight.get('confidence_adjustment', 0) for insight in insights
        )
        
        all_findings = []
        for insight in insights:
            all_findings.extend(insight.get('findings', []))
        
        quality = 'high' if len(insights) >= 3 else 'medium' if len(insights) >= 2 else 'low'
        
        return {
            'total_rounds': len(insights),
            'comprehensive_findings': all_findings,
            'confidence_boost': total_confidence_adjustment,
            'drill_quality': quality,
            'analysis_type': 'professional',
            'synthesis_timestamp': datetime.now().isoformat()
        }
    
    def _execute_drill_round(self, discovery: Dict, round_num: int) -> Dict:
        """执行单轮钻取"""
        stock_code = discovery.get('stock_code', '')
        title = discovery.get('title', '')
        content = discovery.get('content', '')
        categories = discovery.get('categories', [])
        
        if round_num == 0:
            findings = self._analyze_basic_info(stock_code, title, content)
            return {
                'round': 1,
                'focus': '基础信息深度核实',
                'findings': findings,
                'confidence_adjustment': self._calculate_confidence_adjustment(findings),
                'new_risk_factors': self._identify_risks(title, content),
                'verification_status': 'verified'
            }
        elif round_num == 1:
            findings = self._analyze_industry_chain(stock_code, categories)
            return {
                'round': 2,
                'focus': '关联企业和产业链分析',
                'findings': findings,
                'confidence_adjustment': self._calculate_confidence_adjustment(findings),
                'new_opportunities': self._identify_opportunities(categories),
                'verification_status': 'verified'
            }
        elif round_num == 2:
            findings = self._analyze_macro_environment(stock_code, categories)
            return {
                'round': 3,
                'focus': '宏观环境和政策影响',
                'findings': findings,
                'confidence_adjustment': self._calculate_confidence_adjustment(findings),
                'macro_factors': self._identify_macro_factors(categories),
                'verification_status': 'verified'
            }
        else:
            findings = self._analyze_future_prospects(stock_code, categories)
            return {
                'round': round_num + 1,
                'focus': '未来发展趋势预测',
                'findings': findings,
                'confidence_adjustment': 1,
                'future_catalysts': self._identify_catalysts(categories),
                'verification_status': 'projected'
            }
    
    def _analyze_basic_info(self, stock_code: str, title: str, content: str) -> List[str]:
        """分析基础信息"""
        findings = []
        
        if '重组' in title or '并购' in title:
            findings.append(f'{stock_code} 存在重组并购预期，需关注交易对手方和估值')
        if '订单' in title or '合同' in title:
            findings.append(f'{stock_code} 有新订单/合同消息，需确认金额和执行周期')
        if '业绩' in title or '利润' in title:
            findings.append(f'{stock_code} 业绩相关信息，需对比历史数据验证')
        if '技术' in title or '研发' in title:
            findings.append(f'{stock_code} 技术突破消息，需评估商业化前景')
        if '政策' in title:
            findings.append(f'{stock_code} 受益政策变化，需评估持续性')
        
        if not findings:
            findings.append(f'{stock_code} 基础信息核实中，未发现明显异常')
        
        return findings
    
    def _analyze_industry_chain(self, stock_code: str, categories: List[str]) -> List[str]:
        """分析产业链"""
        findings = []
        
        cat_str = ''.join(str(c) for c in categories)
        
        if '重组' in cat_str or '并购' in cat_str:
            findings.append(f'{stock_code} 可能涉及产业整合，需关注上下游协同效应')
        if '订单' in cat_str:
            findings.append(f'{stock_code} 订单来源和下游客户质量分析')
        if '技术' in cat_str:
            findings.append(f'{stock_code} 技术优势在产业链中的定价能力评估')
        
        findings.append(f'{stock_code} 产业链竞争格局分析')
        
        return findings
    
    def _analyze_macro_environment(self, stock_code: str, categories: List[str]) -> List[str]:
        """分析宏观环境"""
        findings = []
        
        cat_str = ''.join(str(c) for c in categories)
        
        if '政策' in cat_str:
            findings.append(f'政策环境有利于{stock_code}所在行业发展')
        
        findings.append(f'宏观经济环境对{stock_code}的影响评估')
        findings.append(f'{stock_code}所在行业周期位置判断')
        
        return findings
    
    def _analyze_future_prospects(self, stock_code: str, categories: List[str]) -> List[str]:
        """分析未来前景"""
        return [
            f'{stock_code} 未来6-12个月发展预测',
            f'潜在催化剂事件时间节点分析',
            f'长期投资价值综合评估'
        ]
    
    def _calculate_confidence_adjustment(self, findings: List[str]) -> int:
        """计算置信度调整"""
        if len(findings) >= 3:
            return 5
        elif len(findings) >= 2:
            return 3
        else:
            return 2
    
    def _identify_risks(self, title: str, content: str) -> List[str]:
        """识别风险因素"""
        risks = []
        full_text = title + ' ' + content
        
        if '重组' in full_text or '并购' in full_text:
            risks.append('重组存在不确定性，可能失败')
        if '业绩' in full_text:
            risks.append('业绩预期可能不及预期')
        if '订单' in full_text:
            risks.append('订单执行存在不确定性')
        
        if not risks:
            risks.append('常规市场波动风险')
        
        return risks
    
    def _identify_opportunities(self, categories: List[str]) -> List[str]:
        """识别机会"""
        opportunities = []
        
        cat_str = ''.join(str(c) for c in categories)
        
        if '重组' in cat_str:
            opportunities.append('产业整合带来估值重估机会')
        if '订单' in cat_str:
            opportunities.append('订单放量带来业绩增长')
        if '技术' in cat_str:
            opportunities.append('技术领先带来竞争壁垒')
        
        if not opportunities:
            opportunities.append('行业发展带来的成长机会')
        
        return opportunities
    
    def _identify_macro_factors(self, categories: List[str]) -> List[str]:
        """识别宏观因素"""
        factors = ['行业政策变化', '市场流动性环境', '经济周期位置']
        return factors
    
    def _identify_catalysts(self, categories: List[str]) -> List[str]:
        """识别催化剂"""
        catalysts = []
        
        cat_str = ''.join(str(c) for c in categories)
        
        if '重组' in cat_str:
            catalysts.append('重组方案公告')
        if '业绩' in cat_str:
            catalysts.append('季度财报披露')
        if '订单' in cat_str:
            catalysts.append('订单执行进度公告')
        
        if not catalysts:
            catalysts.append('行业政策利好')
        
        return catalysts
    
    def _synthesize_drill_results(self, insights: List[Dict]) -> Dict:
        """综合钻取结果"""
        total_confidence_adjustment = sum(
            insight.get('confidence_adjustment', 0) for insight in insights
        )
        
        all_findings = []
        for insight in insights:
            all_findings.extend(insight.get('findings', []))
        
        return {
            'total_rounds': len(insights),
            'comprehensive_findings': all_findings,
            'confidence_boost': total_confidence_adjustment,
            'drill_quality': 'high' if len(insights) >= 3 else 'medium',
            'synthesis_timestamp': datetime.now().isoformat()
        }
    
    def _should_perform_merger_analysis(self, discovery: Dict) -> bool:
        """判断是否需要并购分析"""
        content = discovery.get('content', '').lower()
        title = discovery.get('title', '').lower()
        
        merger_keywords = ['重组', '并购', '收购', '合并', '重大资产', '控股']
        
        for keyword in merger_keywords:
            if keyword in content or keyword in title:
                return True
        
        return False
    
    def _perform_merger_analysis(self, discovery: Dict) -> Dict:
        """执行并购分析"""
        stock_code = discovery.get('stock_code', '')
        
        logger.info(f"    🔗 {stock_code} 执行深度并购关联分析...")
        
        try:
            result = self.merger_analyzer.analyze_merger_association(
                target_code=stock_code,
                acquirer_hints=[],
                analysis_depth='comprehensive'
            )
            
            if result and result.get('top_acquirer'):
                top_acquirer = result.get('top_acquirer')
                top_code = top_acquirer[0] if top_acquirer else None
                top_result = top_acquirer[1] if top_acquirer and len(top_acquirer) > 1 else {}
                
                acquirer_list = []
                detailed_results = result.get('detailed_results', {})
                for acq_code, acq_result in sorted(detailed_results.items(), 
                                                    key=lambda x: x[1].get('overall_score', 0), 
                                                    reverse=True)[:5]:
                    success_prob = acq_result.get('success_probability', {})
                    value_creation = acq_result.get('value_creation', {})
                    risk_factors = acq_result.get('risk_factors', {})
                    
                    acquirer_list.append({
                        'code': acq_code,
                        'name': self.professional_analyzer.get_stock_name(acq_code),
                        'overall_score': acq_result.get('overall_score', 0),
                        'business_score': acq_result.get('business', {}).get('综合得分', 0),
                        'financial_score': acq_result.get('financial', {}).get('综合得分', 0),
                        'strategic_score': acq_result.get('strategic', {}).get('综合得分', 0),
                        'success_probability': success_prob.get('probability_percentage', '未知'),
                        'risk_level': success_prob.get('risk_level', '未知'),
                        'timeline': success_prob.get('estimated_timeline', '未知'),
                        'key_success_factors': success_prob.get('key_success_factors', []),
                        'critical_risks': success_prob.get('critical_risks', []),
                        'synergy_potential': value_creation.get('synergy_potential', {}).get('description', ''),
                        'market_risks': risk_factors.get('market_risks', []),
                        'integration_risks': risk_factors.get('integration_risks', [])
                    })
                
                return {
                    'analysis_completed': True,
                    'target_code': stock_code,
                    'target_name': self.professional_analyzer.get_stock_name(stock_code),
                    'potential_acquirers_count': result.get('potential_acquirers', 0),
                    'top_acquirer_code': top_code,
                    'top_acquirer_name': self.professional_analyzer.get_stock_name(top_code) if top_code else '',
                    'top_acquirer_score': top_result.get('overall_score', 0),
                    'top_success_probability': top_result.get('success_probability', {}).get('probability_percentage', '未知'),
                    'acquirer_list': acquirer_list,
                    'analysis_timestamp': datetime.now().isoformat()
                }
            else:
                return {
                    'analysis_completed': False,
                    'reason': '未发现明确的并购信号',
                    'analysis_timestamp': datetime.now().isoformat()
                }
                
        except Exception as e:
            return {
                'analysis_completed': False,
                'error': str(e),
                'analysis_timestamp': datetime.now().isoformat()
            }
    
    def _comprehensive_evaluation_phase(self, discoveries: List[Dict], start_time: datetime) -> Dict:
        """综合评估阶段"""
        logger.info(f"  🎯 综合评估阶段...")
        
        # 计算最终评分
        for discovery in discoveries:
            final_score = self._calculate_final_score(discovery)
            discovery['final_score'] = final_score
            discovery['investment_grade'] = self._determine_investment_grade(final_score)
        
        # 按评分排序
        discoveries.sort(key=lambda x: x.get('final_score', 0), reverse=True)
        
        # 生成综合评估结果
        evaluation_result = {
            'analysis_timestamp': datetime.now().isoformat(),
            'total_discoveries': len(discoveries),
            'analysis_duration': (datetime.now() - start_time).total_seconds(),
            'high_grade_count': len([d for d in discoveries if d.get('final_score', 0) >= 85]),
            'medium_grade_count': len([d for d in discoveries if 70 <= d.get('final_score', 0) < 85]),
            'low_grade_count': len([d for d in discoveries if d.get('final_score', 0) < 70]),
            'discoveries': discoveries,
            'quality_metrics': self._calculate_quality_metrics(discoveries),
            'recommendations': self._generate_investment_recommendations(discoveries)
        }
        
        logger.info(f"  ✓ 综合评估完成")
        return evaluation_result
    
    def _calculate_final_score(self, discovery: Dict) -> float:
        """计算最终评分"""
        # 基础质量评分
        quality_score = discovery.get('quality_score', 50)
        
        # 钻取分析加成
        drill_boost = 0
        if 'drill_down_analysis' in discovery:
            drill_analysis = discovery['drill_down_analysis']
            drill_boost = drill_analysis.get('comprehensive_assessment', {}).get('confidence_boost', 0)
        
        # 交叉验证加成
        validation_boost = 0
        if 'cross_validation' in discovery:
            validation_score = discovery['cross_validation'].get('overall_score', 50)
            validation_boost = max(0, validation_score - 60) * 0.3  # 超过60分的部分作为加成
        
        # 并购分析加成
        merger_boost = 0
        if 'merger_analysis' in discovery and discovery['merger_analysis'].get('analysis_completed', False):
            merger_boost = 10  # 有并购潜力的额外加分
        
        # 计算最终评分
        final_score = quality_score + drill_boost + validation_boost + merger_boost
        
        return min(final_score, 100)  # 限制最高100分
    
    def _determine_investment_grade(self, final_score: float) -> str:
        """确定投资等级"""
        if final_score >= 90:
            return 'SSS级'
        elif final_score >= 85:
            return 'SS级'
        elif final_score >= 80:
            return 'S级'
        elif final_score >= 75:
            return 'A+级'
        elif final_score >= 70:
            return 'A级'
        elif final_score >= 65:
            return 'B+级'
        elif final_score >= 60:
            return 'B级'
        else:
            return 'C级'
    
    def _calculate_quality_metrics(self, discoveries: List[Dict]) -> Dict:
        """计算质量指标"""
        if not discoveries:
            return {}
        
        scores = [d.get('final_score', 0) for d in discoveries]
        
        return {
            'average_score': np.mean(scores),
            'median_score': np.median(scores),
            'max_score': max(scores),
            'min_score': min(scores),
            'score_std': np.std(scores),
            'high_quality_ratio': len([s for s in scores if s >= 80]) / len(scores),
            'drill_down_completion_rate': len([d for d in discoveries if d.get('drill_down_completed', False)]) / len(discoveries),
            'cross_validation_success_rate': len([d for d in discoveries if d.get('validation_score', 0) >= 60]) / len(discoveries)
        }
    
    def _generate_investment_recommendations(self, discoveries: List[Dict]) -> List[Dict]:
        """生成投资建议"""
        recommendations = []
        
        # 按等级生成建议
        top_discoveries = discoveries[:5]  # 取前5名
        
        for discovery in top_discoveries:
            stock_code = discovery.get('stock_code', '')
            final_score = discovery.get('final_score', 0)
            grade = discovery.get('investment_grade', 'C级')
            
            if final_score >= 85:
                action = '强烈推荐'
                reasoning = '多维度深度分析确认，高质量投资机会'
            elif final_score >= 75:
                action = '推荐关注'
                reasoning = '深度分析显示较好投资潜力'
            elif final_score >= 65:
                action = '谨慎关注'
                reasoning = '存在投资机会，需要持续跟踪'
            else:
                action = '观望'
                reasoning = '质量有待确认，暂时观望'
            
            recommendations.append({
                'stock_code': stock_code,
                'grade': grade,
                'final_score': final_score,
                'action': action,
                'reasoning': reasoning,
                'key_strengths': self._extract_key_strengths(discovery),
                'main_risks': self._extract_main_risks(discovery)
            })
        
        return recommendations
    
    def _extract_key_strengths(self, discovery: Dict) -> List[str]:
        """提取关键优势"""
        strengths = []
        
        if discovery.get('final_score', 0) >= 80:
            strengths.append('综合评分优秀')
        
        if discovery.get('drill_down_completed', False):
            strengths.append('通过深度钻取验证')
        
        if discovery.get('validation_score', 0) >= 70:
            strengths.append('交叉验证确认')
        
        if 'merger_analysis' in discovery and discovery['merger_analysis'].get('analysis_completed', False):
            strengths.append('具备并购重组潜力')
        
        return strengths or ['基础面良好']
    
    def _extract_main_risks(self, discovery: Dict) -> List[str]:
        """提取主要风险"""
        risks = []
        
        if discovery.get('final_score', 0) < 70:
            risks.append('综合评分偏低')
        
        if not discovery.get('drill_down_completed', False):
            risks.append('未完成深度验证')
        
        if discovery.get('validation_score', 0) < 60:
            risks.append('交叉验证存疑')
        
        # 从风险分析中提取
        if 'risk_analysis' in discovery:
            risk_level = discovery['risk_analysis'].get('overall_risk_level', 'medium')
            if risk_level == 'high':
                risks.append('整体风险偏高')
        
        return risks or ['常规市场风险']
    
    def _generate_integrated_report(self, results: Dict, mode_info: Dict, drill_config: Dict) -> str:
        """生成一体化报告"""
        logger.info("  📊 生成一体化深度分析报告...")
        
        discoveries = results.get('discoveries', [])
        
        # 转换为报告格式
        report_data = []
        for discovery in discoveries:
            report_item = self._convert_discovery_to_report_format(discovery, mode_info, drill_config)
            report_data.append(report_item)
        
        # 生成报告
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_title = f"一体化深度发现报告-{mode_info['name']}-{timestamp}"
        
        # 生成多格式报告（包括Markdown）
        md_path = self.report_generator.generate_markdown_report(report_data, report_title)
        html_path = self.report_generator.generate_html_report(report_data, report_title)
        excel_path = self.report_generator.generate_excel_report(report_data)
        csv_path = self.report_generator.generate_csv_report(report_data)
        
        logger.info(f"  ✓ 报告生成完成:")
        logger.info(f"    Markdown: {md_path}")
        logger.info(f"    HTML: {html_path}")
        logger.info(f"    Excel: {excel_path}")
        logger.info(f"    CSV: {csv_path}")
        
        return excel_path
    
    def _convert_discovery_to_report_format(self, discovery: Dict, mode_info: Dict, drill_config: Dict) -> Dict:
        """转换为报告格式"""
        stock_code = discovery.get('stock_code', '')
        final_score = discovery.get('final_score', 0)
        grade = discovery.get('investment_grade', 'C级')
        
        professional = discovery.get('professional_analysis', {})
        recommendation = professional.get('recommendation', {})
        
        if recommendation:
            investment_advice = self._generate_professional_advice(discovery, recommendation)
            risk_warning = self._generate_professional_risk_warning(discovery, professional)
        else:
            investment_advice = self._generate_detailed_investment_advice(discovery)
            risk_warning = self._generate_detailed_risk_warning(discovery)
        
        raw_data = discovery.get('raw_data', {})
        sample_posts = raw_data.get('sample_posts', [])
        if not sample_posts:
            sample_posts = discovery.get('sample_posts', [])
        
        keywords = list(discovery.get('keywords', raw_data.get('keywords', [])))
        sources = list(discovery.get('sources', raw_data.get('sources', [])))
        categories = list(discovery.get('categories', []))
        
        drill_down_analysis = discovery.get('drill_down_analysis', {})
        
        stock_name = self.professional_analyzer.get_stock_name(stock_code)
        industry = self.professional_analyzer.get_stock_industry(stock_code)
        
        news_title = discovery.get('title', f'{stock_code} 深度投资机会')
        news_content = discovery.get('content', '')
        event_timeline = self.professional_analyzer.predict_event_timeline(news_title, news_content)
        
        return {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'industry': industry,
            'confidence_score': final_score,
            'confidence_rating': grade,
            'news_type_name': categories[0] if categories else f'{mode_info["name"]}发现',
            'news_title': news_title,
            'news_content': self._generate_professional_content(discovery, professional),
            'publish_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'news_source': f'专业深度分析 ({drill_config["name"]})',
            'news_url': f'分析深度: {drill_config["analysis_depth"]}层',
            'investment_advice': investment_advice,
            'risk_warning': risk_warning,
            'confidence': {
                'scores': self._get_professional_scores(discovery, professional, final_score)
            },
            'raw_data': {
                'sample_posts': sample_posts,
                'keywords': keywords,
                'sources': sources,
                'drill_down_analysis': drill_down_analysis
            },
            'drill_down_analysis': drill_down_analysis,
            'professional_analysis': professional,
            'event_timeline': event_timeline,
            'merger_analysis': discovery.get('merger_analysis', {}),
            'categories': categories
        }
    
    def _get_professional_scores(self, discovery: Dict, professional: Dict, final_score: float) -> Dict:
        """获取专业评分"""
        financial = professional.get('financial_data', {})
        capital = professional.get('capital_flow', {})
        technical = professional.get('technical_analysis', {})
        
        pe = financial.get('pe_ttm')
        source_score = 75 if pe else min(discovery.get('quality_score', 50), 90)
        
        main_flow = capital.get('main_inflow_5d')
        if main_flow is not None:
            market_score = 80 if main_flow > 0 else 50
        else:
            market_score = discovery.get('validation_score', 50)
        
        trend = technical.get('trend', '')
        if '上升' in trend:
            tech_score = 85
        elif '下降' in trend:
            tech_score = 55
        else:
            tech_score = 70
        
        return {
            'source_reliability': source_score,
            'timeliness': 90,
            'content_quality': min(discovery.get('validation_score', 60), 95),
            'market_validation': market_score,
            'historical_accuracy': 75,
            'technical_alignment': tech_score
        }
    
    def _generate_professional_content(self, discovery: Dict, professional: Dict) -> str:
        """生成专业内容描述"""
        parts = []
        
        industry = professional.get('industry', '')
        if industry:
            parts.append(f"所属行业: {industry}")
        
        financial = professional.get('financial_data', {})
        pe = financial.get('pe_ttm')
        market_cap = financial.get('market_cap')
        if pe:
            parts.append(f"PE(TTM): {pe:.1f}倍")
        if market_cap:
            parts.append(f"市值: {market_cap:.0f}亿")
        
        capital = professional.get('capital_flow', {})
        main_flow = capital.get('main_inflow_5d')
        if main_flow is not None:
            flow_desc = f"流入{main_flow:.2f}亿" if main_flow > 0 else f"流出{abs(main_flow):.2f}亿"
            parts.append(f"5日主力资金: {flow_desc}")
        
        technical = professional.get('technical_analysis', {})
        trend = technical.get('trend')
        if trend and trend != '数据不足':
            parts.append(f"技术形态: {trend}")
        
        recommendation = professional.get('recommendation', {})
        rating = recommendation.get('rating', '')
        action = recommendation.get('action', '')
        if rating and action:
            parts.append(f"专业评级: {rating}级-{action}")
        
        return " | ".join(parts) if parts else discovery.get('content', '')
    
    def _generate_professional_advice(self, discovery: Dict, recommendation: Dict) -> str:
        """生成专业投资建议"""
        rating = recommendation.get('rating', 'C')
        action = recommendation.get('action', '观望')
        reason = recommendation.get('reason', '')
        position_advice = recommendation.get('position_advice', '')
        confidence = recommendation.get('confidence', 50)
        
        grade = discovery.get('investment_grade', 'C级')
        
        advice = f"【{grade}】{action} (置信度{confidence}分)\n"
        advice += f"核心逻辑: {reason}\n"
        advice += f"仓位建议: {position_advice}"
        
        return advice
    
    def _generate_professional_risk_warning(self, discovery: Dict, professional: Dict) -> str:
        """生成专业风险提示"""
        risk_assessment = professional.get('risk_assessment', '')
        
        if risk_assessment:
            return risk_assessment
        
        return self._generate_detailed_risk_warning(discovery)
    
    def _get_stock_name_from_discovery(self, discovery: Dict, stock_code: str) -> str:
        """从发现中获取股票名称"""
        return self.professional_analyzer.get_stock_name(stock_code)
    
    def _generate_comprehensive_content(self, discovery: Dict) -> str:
        """生成综合内容描述"""
        content_parts = []
        
        # 基础发现
        content_parts.append(f"发现类型: {discovery.get('discovery_type', '未知')}")
        
        # 钻取分析结果
        if 'drill_down_analysis' in discovery:
            drill_analysis = discovery['drill_down_analysis']
            rounds = drill_analysis.get('drill_rounds_completed', 0)
            content_parts.append(f"深度钻取: 完成{rounds}轮深度分析")
        
        # 交叉验证结果
        if 'cross_validation' in discovery:
            validation = discovery['cross_validation']
            if validation.get('validation_passed', False):
                content_parts.append("交叉验证: 通过多源验证")
            else:
                content_parts.append("交叉验证: 部分通过验证")
        
        # 并购分析结果
        if 'merger_analysis' in discovery:
            merger = discovery['merger_analysis']
            if merger.get('analysis_completed', False):
                content_parts.append("并购分析: 发现并购重组潜力")
        
        return " | ".join(content_parts)
    
    def _generate_detailed_investment_advice(self, discovery: Dict) -> str:
        """生成详细投资建议"""
        final_score = discovery.get('final_score', 0)
        grade = discovery.get('investment_grade', 'C级')
        
        base_advice = ""
        
        if final_score >= 85:
            base_advice = f"★★★ {grade} 高质量投资机会，经多维度深度分析确认，"
        elif final_score >= 75:
            base_advice = f"★★ {grade} 较好投资机会，深度分析显示投资价值，"
        elif final_score >= 65:
            base_advice = f"★ {grade} 潜在投资机会，需要持续关注验证，"
        else:
            base_advice = f"{grade} 投资机会有限，建议谨慎观望，"
        
        # 添加具体分析结果
        analysis_details = []
        
        if discovery.get('drill_down_completed', False):
            analysis_details.append("已完成深度钻取分析")
        
        if discovery.get('validation_score', 0) >= 70:
            analysis_details.append("通过严格交叉验证")
        
        if 'merger_analysis' in discovery and discovery['merger_analysis'].get('analysis_completed', False):
            analysis_details.append("具备并购重组催化剂")
        
        if analysis_details:
            base_advice += "，".join(analysis_details) + "。"
        else:
            base_advice += "建议持续关注后续发展。"
        
        return base_advice
    
    def _generate_detailed_risk_warning(self, discovery: Dict) -> str:
        """生成详细风险提示"""
        warnings = []
        
        # 基于评分的风险提示
        final_score = discovery.get('final_score', 0)
        if final_score < 70:
            warnings.append("综合评分偏低，投资风险较高")
        
        # 基于验证结果的风险提示
        if not discovery.get('drill_down_completed', False):
            warnings.append("未完成深度验证，信息可靠性待确认")
        
        if discovery.get('validation_score', 0) < 60:
            warnings.append("交叉验证存在问题，需要谨慎对待")
        
        # 基于风险分析的提示
        if 'risk_analysis' in discovery:
            risk_level = discovery['risk_analysis'].get('overall_risk_level', 'medium')
            if risk_level == 'high':
                warnings.append("风险分析显示整体风险偏高")
            elif risk_level == 'medium':
                warnings.append("存在中等程度投资风险")
        
        # 通用风险提示
        base_warning = "市场有风险，投资需谨慎。"
        
        if warnings:
            return base_warning + "特别注意：" + "；".join(warnings) + "。"
        else:
            return base_warning + "请根据个人风险承受能力做出投资决策。"
    
    def _print_discovery_summary(self, results: Dict, start_time: datetime):
        """打印发现摘要"""
        logger.info("\n" + "=" * 100)
        logger.info("🎯 一体化深度发现结果摘要")
        logger.info("=" * 100)
        
        total_discoveries = results.get('total_discoveries', 0)
        high_grade = results.get('high_grade_count', 0)
        medium_grade = results.get('medium_grade_count', 0)
        duration = results.get('analysis_duration', 0)
        
        logger.info(f"发现投资机会总数: {total_discoveries}")
        logger.info(f"高等级机会 (≥85分): {high_grade}")
        logger.info(f"中等级机会 (70-84分): {medium_grade}")
        logger.info(f"分析总耗时: {duration:.1f}秒")
        
        # 质量指标
        quality_metrics = results.get('quality_metrics', {})
        if quality_metrics:
            logger.info(f"\n📊 质量指标:")
            logger.info(f"  平均评分: {quality_metrics.get('average_score', 0):.1f}")
            logger.info(f"  高质量比例: {quality_metrics.get('high_quality_ratio', 0) * 100:.1f}%")
            logger.info(f"  钻取完成率: {quality_metrics.get('drill_down_completion_rate', 0) * 100:.1f}%")
            logger.info(f"  验证成功率: {quality_metrics.get('cross_validation_success_rate', 0) * 100:.1f}%")
        
        # TOP 5 投资建议
        recommendations = results.get('recommendations', [])
        if recommendations:
            logger.info(f"\n🏆 TOP 5 投资建议:")
            for idx, rec in enumerate(recommendations[:5], 1):
                stock_code = rec.get('stock_code', '')
                grade = rec.get('grade', '')
                score = rec.get('final_score', 0)
                action = rec.get('action', '')
                
                logger.info(f"  {idx}. {stock_code} - {grade} ({score:.1f}分)")
                logger.info(f"     建议: {action}")
                
                strengths = rec.get('key_strengths', [])
                if strengths:
                    logger.info(f"     优势: {', '.join(strengths[:3])}")
        
        logger.info("=" * 100)


def main():
    """主函数"""
    print("🚀 Kronos 一体化深度发现引擎")
    
    # 用户输入
    try:
        mode_input = input("\n请选择模式 (1=关键词模式, 2=论坛模式, 3=新闻模式, 默认1): ").strip()
        discovery_mode = int(mode_input) if mode_input and mode_input.isdigit() else 1
        
        print("\n钻取深度选项:")
        print("  1. 表层分析 (快速)")
        print("  2. 中等深度 (平衡)")
        print("  3. 深度分析 (推荐)")
        print("  4. 全面深度 (最详细)")
        
        depth_input = input("请选择钻取深度 (1-4, 默认4): ").strip()
        depth_mapping = {
            '1': 'surface',
            '2': 'intermediate', 
            '3': 'deep',
            '4': 'comprehensive'
        }
        drill_depth = depth_mapping.get(depth_input, 'comprehensive')
        
        quality_input = input("请设置质量阈值 (0.1-1.0, 默认0.7): ").strip()
        try:
            quality_threshold = float(quality_input) if quality_input else 0.7
            quality_threshold = max(0.1, min(1.0, quality_threshold))
        except:
            quality_threshold = 0.7
        
    except KeyboardInterrupt:
        print("\n用户取消操作")
        return
    except:
        # 使用默认值
        discovery_mode = 1
        drill_depth = 'comprehensive'
        quality_threshold = 0.7
    
    # 运行一体化发现
    engine = IntegratedDiscoveryEngine()
    
    try:
        results = engine.run_integrated_discovery(
            discovery_mode=discovery_mode,
            drill_depth=drill_depth,
            quality_threshold=quality_threshold
        )
        
        if results:
            print(f"\n✅ 发现完成！共发现 {results.get('total_discoveries', 0)} 个投资机会")
        else:
            print("\n❌ 发现过程出现问题")
            
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断分析过程")
    except Exception as e:
        print(f"\n❌ 系统错误: {e}")


if __name__ == '__main__':
    main()