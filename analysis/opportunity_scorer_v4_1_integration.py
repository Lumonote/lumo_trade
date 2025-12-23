#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会打分系统 v4.1 - 市场环境分析器集成模块

集成市场环境分析器到打分系统中，实现动态权重调整。
这是一个包装器模块，在调用原有OpportunityScorer前进行市场环境分析。
"""

import os
import sys
from typing import Dict, Optional
import logging

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.opportunity_scorer import OpportunityScorer
from analysis.market_env_analyzer import MarketEnvAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OpportunityScorerV41:
    """
    投资机会打分系统 v4.1 - 动态权重版
    
    核心改进：
    1. 集成市场环境分析器
    2. 根据市场环境动态调整权重
    3. 支持快速权重方案切换
    4. 增强对不同市场环境的适应性
    """
    
    def __init__(self, analyze_market_env: bool = True):
        """
        初始化v4.1版打分系统
        
        Args:
            analyze_market_env: 是否启用市场环境分析和权重动态调整（默认True）
        """
        self.scorer = OpportunityScorer()
        self.market_analyzer = MarketEnvAnalyzer() if analyze_market_env else None
        self.market_env = None
        self.dynamic_weights = None
        self.analyze_enabled = analyze_market_env
        
    def analyze_and_score(self, stock_code: str, market_data: Optional[Dict] = None, **kwargs) -> Dict:
        """
        分析市场环境并计算打分
        
        Args:
            stock_code: 股票代码
            market_data: 市场环境数据 (可选)，包含：
                - sentiment_score: 市场情绪分数 (0-100)
                - volatility: 年化波动率
                - capital_flow_ratio: 资金流入比例 (0-1)
            **kwargs: 传递给OpportunityScorer.calculate_comprehensive_score的参数
        
        Returns:
            包含打分和市场环境信息的字典
        """
        result = {}
        
        # Step 1: 分析市场环境并获取动态权重
        if self.analyze_enabled and market_data:
            try:
                logger.info(f"🔍 正在分析市场环境...")
                env_name, weights = self.market_analyzer.analyze_market_environment(market_data)
                
                self.market_env = env_name
                self.dynamic_weights = weights
                
                result['market_environment'] = {
                    'environment': env_name,
                    'environment_name': self.market_analyzer.WEIGHT_SCHEMES[env_name]['name'],
                    'description': self.market_analyzer.WEIGHT_SCHEMES[env_name]['desc'],
                    'weights': weights,
                    'sentiment_score': market_data.get('sentiment_score', 50),
                    'volatility': market_data.get('volatility', 0.20),
                    'capital_flow_ratio': market_data.get('capital_flow_ratio', 0.5),
                }
                
                # 获取评级阈值调整
                rating_adjustment = self.market_analyzer.get_rating_adjustment(env_name)
                result['rating_adjustments'] = rating_adjustment
                
                # 获取其他参数
                result['exclusion_multiplier'] = self.market_analyzer.get_exclusion_multiplier(env_name)
                result['score_boost'] = self.market_analyzer.get_score_boost(env_name)
                
            except Exception as e:
                logger.warning(f"市场环境分析失败，使用标准权重: {e}")
                result['market_environment_error'] = str(e)
        elif not self.analyze_enabled:
            logger.info("市场环境分析已禁用，使用标准权重")
        else:
            logger.info("未提供市场数据，使用标准权重")
        
        # Step 2: 计算股票打分
        try:
            logger.info(f"📊 正在计算 {stock_code} 的综合评分...")
            stock_score = self.scorer.calculate_comprehensive_score(stock_code, **kwargs)
            
            # 合并结果
            result.update(stock_score)
            
            # 应用市场环境调整
            if self.market_env and result.get('total_score'):
                original_score = result['total_score']
                
                # 应用总分加值
                if 'score_boost' in result:
                    result['total_score'] += result['score_boost']
                    result['total_score'] = max(0, min(100, result['total_score']))
                    logger.info(f"应用市场环境总分调整: {original_score:.2f} -> {result['total_score']:.2f} " +
                              f"(+{result['score_boost']}分)")
                
                # 更新评级（如果有调整）
                if 'rating_adjustments' in result:
                    old_rating = result.get('rating', 'C')
                    result = self._apply_rating_adjustments(result)
                    new_rating = result.get('rating', 'C')
                    if old_rating != new_rating:
                        logger.info(f"评级调整: {old_rating} -> {new_rating}")
            
            return result
            
        except Exception as e:
            logger.error(f"计算打分失败: {e}")
            result['error'] = str(e)
            return result
    
    def _apply_rating_adjustments(self, result: Dict) -> Dict:
        """
        应用评级阈值调整
        
        根据市场环境调整评级阈值，然后重新计算评级
        """
        if 'rating_adjustments' not in result:
            return result
        
        try:
            total_score = result.get('total_score', 0)
            adjustments = result['rating_adjustments']
            
            # 创建调整后的阈值
            adjusted_thresholds = self.scorer.RATING_THRESHOLDS.copy()
            for rating, adjustment in adjustments.items():
                if rating in adjusted_thresholds:
                    adjusted_thresholds[rating] += adjustment
            
            # 重新计算评级
            if total_score >= adjusted_thresholds['S']:
                new_rating = 'S'
            elif total_score >= adjusted_thresholds['A+']:
                new_rating = 'A+'
            elif total_score >= adjusted_thresholds['A']:
                new_rating = 'A'
            elif total_score >= adjusted_thresholds['B']:
                new_rating = 'B'
            else:
                new_rating = 'C'
            
            result['rating'] = new_rating
            result['recommendation'] = self.scorer._get_recommendation(new_rating)
            result['adjusted_thresholds'] = adjusted_thresholds
            
            return result
        except Exception as e:
            logger.warning(f"应用评级调整失败: {e}")
            return result
    
    def get_all_schemes(self) -> Dict:
        """获取所有可用的权重方案"""
        if self.market_analyzer:
            return self.market_analyzer.list_all_schemes()
        return {}
    
    def quick_analyze_by_condition(self, stock_code: str, **market_conditions) -> Dict:
        """
        快速分析：根据市场条件直接返回推荐权重
        
        支持的参数：
        - sentiment_hot: bool, 市场过热
        - volatility_high: bool, 高波动率
        - capital_inflow: bool, 资金入场
        
        Returns:
            打分结果字典
        """
        if not self.market_analyzer:
            return {}
        
        # 快速获取推荐权重
        suggested_weights = self.market_analyzer.suggest_weight_by_market_condition(**market_conditions)
        
        # 创建虚拟市场环境数据用于完整分析
        market_data = {
            'sentiment_score': 75 if market_conditions.get('sentiment_hot') else 50,
            'volatility': 0.40 if market_conditions.get('volatility_high') else 0.20,
            'capital_flow_ratio': 0.75 if market_conditions.get('capital_inflow') else 0.5,
        }
        
        return self.analyze_and_score(stock_code, market_data=market_data)


# 便捷函数：创建推荐用的分析器
def create_scorer(use_dynamic_weights: bool = True) -> OpportunityScorerV41:
    """创建打分系统实例"""
    return OpportunityScorerV41(analyze_market_env=use_dynamic_weights)


if __name__ == '__main__':
    # 测试代码
    print("\n" + "="*60)
    print("🚀 投资机会打分系统 v4.1 集成测试")
    print("="*60)
    
    # 创建打分系统
    scorer = create_scorer(use_dynamic_weights=True)
    
    # 测试场景1：市场过热
    print("\n【测试场景1】市场过热环境")
    market_data = {
        'sentiment_score': 85,
        'volatility': 0.25,
        'capital_flow_ratio': 0.7,
    }
    result = scorer.analyze_and_score('000001', market_data=market_data)
    if 'error' not in result:
        print(f"✓ 推荐方案: {result.get('market_environment', {}).get('environment_name', 'N/A')}")
        print(f"✓ 打分: {result.get('total_score', 0):.2f} 分")
        print(f"✓ 评级: {result.get('rating', 'C')}")
    else:
        print(f"✗ 错误: {result.get('error')}")
    
    # 测试场景2：市场低迷+资金入场
    print("\n【测试场景2】市场低迷+资金入场")
    market_data = {
        'sentiment_score': 25,
        'volatility': 0.18,
        'capital_flow_ratio': 0.75,
    }
    result = scorer.analyze_and_score('000001', market_data=market_data)
    if 'error' not in result:
        print(f"✓ 推荐方案: {result.get('market_environment', {}).get('environment_name', 'N/A')}")
        print(f"✓ 打分: {result.get('total_score', 0):.2f} 分")
        print(f"✓ 评级: {result.get('rating', 'C')}")
    else:
        print(f"✗ 错误: {result.get('error')}")
    
    # 列出所有可用方案
    print("\n【可用权重方案】")
    schemes = scorer.get_all_schemes()
    for scheme_name, info in list(schemes.items())[:3]:
        print(f"  - {info['name']}: {info['desc']}")
