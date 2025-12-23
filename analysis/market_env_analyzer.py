#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场环境分析器 - 根据市场环境动态调整权重

支持：
1. 市场情绪识别（过热/低迷/均衡）
2. 波动率环境检测（高波/低波）
3. 资金流向判断（入场/出场）
4. 动态权重选择（P0优化）
"""

import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from datetime import datetime, timedelta
import logging

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MarketEnvAnalyzer:
    """
    市场环境分析器 - 动态权重选择核心模块
    
    核心职责：
    1. 分析当前市场环境（情绪、波动率、资金流）
    2. 根据环境选择最优权重方案
    3. 支持快速环境切换和权重调整
    """
    
    # 市场情绪阈值配置
    SENTIMENT_THRESHOLDS = {
        'overheated': 75,      # 过热阈值
        'bullish': 60,         # 偏多
        'neutral': 40,         # 中性
        'bearish': 20,         # 偏空
    }
    
    # 波动率阈值配置（年化）
    VOLATILITY_THRESHOLDS = {
        'high': 0.35,          # 高波 >35%
        'medium': 0.20,        # 中波 20-35%
        'low': 0.00,           # 低波 <20%
    }
    
    # 资金流向判断标准
    CAPITAL_FLOW_THRESHOLDS = {
        'inflow': 0.65,        # 入场信号
        'outflow': 0.35,       # 出场信号
    }
    
    # 预定义权重方案库
    WEIGHT_SCHEMES = {
        # 【热点追涨模式】市场过热，需要强化风控和反追涨逻辑
        'overheated_caution': {
            'name': '过热谨慎模式',
            'weights': {
                'position_timing': 0.20,      # 提升位置权重，强化反追涨
                'volume_health': 0.12,
                'technical': 0.10,
                'quantitative': 0.30,         # 量化信号仍保持核心权重
                'liquidity': 0.10,             # 提升流动性权重过滤
                'sector': 0.05,
                'dragon_tiger': 0.05,         # 龙虎榜关注游资异动
                'fundamental': 0.05,
                'events': 0.03,
                'sentiment': 0.00,
            },
            'desc': '市场过热，强化风控和反追涨逻辑',
            'exclusion_multiplier': 1.2,      # 一票否决范围扩大20%
            'score_boost': -5,                 # 整体评分下调5分
        },
        
        # 【底部布局模式】市场低迷，寻找底部启动信号
        'depressed_opportunity': {
            'name': '低迷机会模式',
            'weights': {
                'position_timing': 0.18,      # 低吸逻辑加权
                'volume_health': 0.16,         # 量价结构是启动信号
                'technical': 0.14,             # 技术形态共振权重提升
                'quantitative': 0.28,
                'liquidity': 0.06,
                'sector': 0.06,
                'dragon_tiger': 0.06,         # 机构大宗交易机会
                'fundamental': 0.04,
                'events': 0.02,
                'sentiment': 0.00,
            },
            'desc': '市场低迷，寻找底部启动信号',
            'exclusion_multiplier': 0.8,      # 一票否决范围缩小20%
            'score_boost': 3,                  # 整体评分上调3分
        },
        
        # 【均衡稳健模式】市场均衡，标准权重
        'balanced_standard': {
            'name': '均衡稳健模式',
            'weights': {
                'position_timing': 0.16,
                'volume_health': 0.14,
                'technical': 0.12,
                'quantitative': 0.35,         # 量化仍是核心
                'liquidity': 0.08,
                'sector': 0.06,
                'dragon_tiger': 0.04,
                'fundamental': 0.03,
                'events': 0.02,
                'sentiment': 0.00,
            },
            'desc': '市场均衡，采用标准权重配置',
            'exclusion_multiplier': 1.0,
            'score_boost': 0,
        },
        
        # 【高波布局模式】高波动率环境，强化量价结构
        'high_volatility_hunting': {
            'name': '高波猎手模式',
            'weights': {
                'position_timing': 0.14,      # 高波是追高风险，降低权重
                'volume_health': 0.18,         # 量价结构是高波中的信号
                'technical': 0.15,             # 技术形态共振
                'quantitative': 0.30,
                'liquidity': 0.10,             # 提升流动性要求
                'sector': 0.07,
                'dragon_tiger': 0.03,
                'fundamental': 0.02,
                'events': 0.01,
                'sentiment': 0.00,
            },
            'desc': '高波环境，强化量价结构和流动性',
            'exclusion_multiplier': 1.5,      # 一票否决更严格
            'score_boost': -8,
        },
        
        # 【低波蓄势模式】低波动率，积蓄力量阶段
        'low_volatility_accumulate': {
            'name': '低波蓄势模式',
            'weights': {
                'position_timing': 0.16,
                'volume_health': 0.12,
                'technical': 0.14,             # 低波技术形态更重要
                'quantitative': 0.34,
                'liquidity': 0.06,
                'sector': 0.08,                # 板块轮动
                'dragon_tiger': 0.06,          # 龙虎榜异动
                'fundamental': 0.02,
                'events': 0.02,
                'sentiment': 0.00,
            },
            'desc': '低波蓄势，关注技术形态和板块轮动',
            'exclusion_multiplier': 0.9,
            'score_boost': 2,
        },
        
        # 【资金入场模式】主力资金活跃，机构配置
        'capital_inflow_aggressive': {
            'name': '资金入场激进模式',
            'weights': {
                'position_timing': 0.15,
                'volume_health': 0.15,
                'technical': 0.12,
                'quantitative': 0.33,
                'liquidity': 0.08,
                'sector': 0.05,
                'dragon_tiger': 0.08,         # 龙虎榜参考性提升
                'fundamental': 0.02,
                'events': 0.02,
                'sentiment': 0.00,
            },
            'desc': '资金活跃入场，龙虎榜参考权重提升',
            'exclusion_multiplier': 0.95,
            'score_boost': 2,
        },
    }
    
    # 评级阈值微调方案
    RATING_THRESHOLD_ADJUSTMENTS = {
        'overheated_caution': {'S': +5, 'A+': +3, 'A': +2, 'B': 0},
        'depressed_opportunity': {'S': -5, 'A+': -3, 'A': -2, 'B': 0},
        'balanced_standard': {'S': 0, 'A+': 0, 'A': 0, 'B': 0},
        'high_volatility_hunting': {'S': +8, 'A+': +5, 'A': +3, 'B': 0},
        'low_volatility_accumulate': {'S': -3, 'A+': -2, 'A': -1, 'B': 0},
        'capital_inflow_aggressive': {'S': -2, 'A+': -1, 'A': 0, 'B': 0},
    }
    
    def __init__(self):
        """初始化分析器"""
        self.current_env = 'balanced_standard'
        self.current_weights = self.WEIGHT_SCHEMES[self.current_env]['weights'].copy()
        self.analysis_cache = {}
        self.last_update_time = None
        
    def analyze_market_environment(self, market_data: Dict) -> Tuple[str, Dict]:
        """
        分析市场环境并返回推荐的权重方案
        
        Args:
            market_data: 市场数据字典，包含：
                - sentiment_score: 市场情绪分数 (0-100)
                - volatility: 年化波动率
                - capital_flow_ratio: 资金流入比例 (0-1)
                - 上升股数, 下跌股数等
        
        Returns:
            (environment_name, weight_scheme_dict)
        """
        logger.info("🔍 开始分析市场环境...")
        
        # 提取市场指标
        sentiment = market_data.get('sentiment_score', 50)
        volatility = market_data.get('volatility', 0.20)
        capital_flow = market_data.get('capital_flow_ratio', 0.5)
        
        # 1. 识别市场情绪
        sentiment_env = self._identify_sentiment(sentiment)
        
        # 2. 识别波动率环境
        volatility_env = self._identify_volatility(volatility)
        
        # 3. 识别资金流向
        capital_env = self._identify_capital_flow(capital_flow)
        
        # 4. 综合判断选择权重方案
        selected_scheme = self._select_weight_scheme(sentiment_env, volatility_env, capital_env)
        
        weights = self.WEIGHT_SCHEMES[selected_scheme]['weights'].copy()
        
        logger.info(f"✅ 环境分析完成: {self.WEIGHT_SCHEMES[selected_scheme]['name']}")
        logger.info(f"   - 市场情绪: {sentiment_env} ({sentiment:.1f})")
        logger.info(f"   - 波动率环境: {volatility_env} ({volatility:.2%})")
        logger.info(f"   - 资金流向: {capital_env} ({capital_flow:.1%})")
        
        self.current_env = selected_scheme
        self.current_weights = weights
        self.last_update_time = datetime.now()
        
        return selected_scheme, weights
    
    def _identify_sentiment(self, sentiment_score: float) -> str:
        """识别市场情绪"""
        if sentiment_score >= self.SENTIMENT_THRESHOLDS['overheated']:
            return 'overheated'
        elif sentiment_score >= self.SENTIMENT_THRESHOLDS['bullish']:
            return 'bullish'
        elif sentiment_score >= self.SENTIMENT_THRESHOLDS['neutral']:
            return 'neutral'
        elif sentiment_score >= self.SENTIMENT_THRESHOLDS['bearish']:
            return 'bearish'
        else:
            return 'depressed'
    
    def _identify_volatility(self, volatility: float) -> str:
        """识别波动率环境"""
        if volatility >= self.VOLATILITY_THRESHOLDS['high']:
            return 'high'
        elif volatility >= self.VOLATILITY_THRESHOLDS['medium']:
            return 'medium'
        else:
            return 'low'
    
    def _identify_capital_flow(self, capital_flow_ratio: float) -> str:
        """识别资金流向"""
        if capital_flow_ratio >= self.CAPITAL_FLOW_THRESHOLDS['inflow']:
            return 'inflow'
        elif capital_flow_ratio <= self.CAPITAL_FLOW_THRESHOLDS['outflow']:
            return 'outflow'
        else:
            return 'neutral'
    
    def _select_weight_scheme(self, sentiment: str, volatility: str, capital: str) -> str:
        """
        综合判断选择最优权重方案
        
        决策树：
        1. 如果过热 -> 过热谨慎模式（控风险）
        2. 如果低迷 + 资金入场 -> 低迷机会模式（抄底）
        3. 如果高波 -> 高波猎手模式
        4. 如果低波 -> 低波蓄势模式
        5. 如果资金入场 -> 资金入场激进模式
        6. 默认 -> 均衡稳健模式
        """
        
        # 判断逻辑优先级
        if sentiment == 'overheated':
            return 'overheated_caution'
        
        if sentiment == 'depressed' and capital == 'inflow':
            return 'depressed_opportunity'
        
        if volatility == 'high':
            return 'high_volatility_hunting'
        
        if volatility == 'low':
            return 'low_volatility_accumulate'
        
        if capital == 'inflow':
            return 'capital_inflow_aggressive'
        
        # 默认均衡模式
        return 'balanced_standard'
    
    def get_current_scheme(self) -> Tuple[str, Dict]:
        """获取当前权重方案"""
        return self.current_env, self.current_weights
    
    def get_scheme_by_name(self, scheme_name: str) -> Optional[Dict]:
        """根据方案名称获取权重"""
        if scheme_name in self.WEIGHT_SCHEMES:
            return self.WEIGHT_SCHEMES[scheme_name]['weights'].copy()
        return None
    
    def get_rating_adjustment(self, scheme_name: str) -> Dict[str, int]:
        """获取评级阈值调整"""
        if scheme_name in self.RATING_THRESHOLD_ADJUSTMENTS:
            return self.RATING_THRESHOLD_ADJUSTMENTS[scheme_name].copy()
        return {'S': 0, 'A+': 0, 'A': 0, 'B': 0}
    
    def get_exclusion_multiplier(self, scheme_name: str) -> float:
        """获取一票否决范围乘数"""
        if scheme_name in self.WEIGHT_SCHEMES:
            return self.WEIGHT_SCHEMES[scheme_name].get('exclusion_multiplier', 1.0)
        return 1.0
    
    def get_score_boost(self, scheme_name: str) -> int:
        """获取综合评分加值"""
        if scheme_name in self.WEIGHT_SCHEMES:
            return self.WEIGHT_SCHEMES[scheme_name].get('score_boost', 0)
        return 0
    
    def list_all_schemes(self) -> Dict:
        """列出所有可用的权重方案"""
        schemes_info = {}
        for name, scheme in self.WEIGHT_SCHEMES.items():
            schemes_info[name] = {
                'name': scheme['name'],
                'desc': scheme['desc'],
                'weights': scheme['weights'].copy(),
            }
        return schemes_info
    
    def validate_weights(self, weights: Dict[str, float]) -> Tuple[bool, str]:
        """
        验证权重配置是否有效
        
        Rules:
        1. 权重总和应为1.0
        2. 每个权重应在0-1之间
        3. 所有必需维度都应存在
        
        Returns:
            (is_valid, error_message)
        """
        required_dims = [
            'position_timing', 'volume_health', 'technical', 'quantitative',
            'liquidity', 'sector', 'dragon_tiger', 'fundamental', 'events', 'sentiment'
        ]
        
        # 检查必需维度
        missing = [d for d in required_dims if d not in weights]
        if missing:
            return False, f"缺失维度: {missing}"
        
        # 检查权重范围
        for dim, weight in weights.items():
            if not (0 <= weight <= 1):
                return False, f"权重 {dim}={weight} 超出范围 [0, 1]"
        
        # 检查权重总和
        total = sum(weights.values())
        if not (0.99 <= total <= 1.01):  # 允许浮点误差
            return False, f"权重总和 {total:.4f} 不等于 1.0"
        
        return True, "权重配置有效"
    
    def suggest_weight_by_market_condition(self, **condition_kwargs) -> Dict[str, float]:
        """
        根据市场条件快速提示最优权重
        
        支持的参数：
        - sentiment_hot: bool, 是否市场过热
        - volatility_high: bool, 是否高波动率
        - capital_inflow: bool, 是否资金入场
        - market_score: int, 市场评分
        
        Returns:
            Dict of weights
        """
        sentiment_hot = condition_kwargs.get('sentiment_hot', False)
        volatility_high = condition_kwargs.get('volatility_high', False)
        capital_inflow = condition_kwargs.get('capital_inflow', False)
        
        # 快速判断逻辑
        if sentiment_hot:
            return self.WEIGHT_SCHEMES['overheated_caution']['weights'].copy()
        
        if volatility_high and not capital_inflow:
            return self.WEIGHT_SCHEMES['high_volatility_hunting']['weights'].copy()
        
        if capital_inflow and not volatility_high:
            return self.WEIGHT_SCHEMES['capital_inflow_aggressive']['weights'].copy()
        
        # 默认均衡
        return self.WEIGHT_SCHEMES['balanced_standard']['weights'].copy()


if __name__ == '__main__':
    # 测试代码
    analyzer = MarketEnvAnalyzer()
    
    print("\n" + "="*60)
    print("📊 市场环境分析器测试")
    print("="*60)
    
    # 测试场景1：市场过热
    print("\n【场景1】市场过热")
    market_data = {
        'sentiment_score': 85,
        'volatility': 0.25,
        'capital_flow_ratio': 0.7,
    }
    env, weights = analyzer.analyze_market_environment(market_data)
    print(f"推荐方案: {analyzer.WEIGHT_SCHEMES[env]['name']}")
    print(f"权重配置: {weights}")
    
    # 测试场景2：市场低迷+资金入场
    print("\n【场景2】市场低迷+资金入场")
    market_data = {
        'sentiment_score': 25,
        'volatility': 0.18,
        'capital_flow_ratio': 0.75,
    }
    env, weights = analyzer.analyze_market_environment(market_data)
    print(f"推荐方案: {analyzer.WEIGHT_SCHEMES[env]['name']}")
    
    # 测试场景3：高波动率
    print("\n【场景3】高波动率")
    market_data = {
        'sentiment_score': 50,
        'volatility': 0.40,
        'capital_flow_ratio': 0.5,
    }
    env, weights = analyzer.analyze_market_environment(market_data)
    print(f"推荐方案: {analyzer.WEIGHT_SCHEMES[env]['name']}")
    
    # 列出所有可用方案
    print("\n【可用方案列表】")
    schemes = analyzer.list_all_schemes()
    for scheme_name, info in schemes.items():
        print(f"\n{info['name']}:")
        print(f"  {info['desc']}")
